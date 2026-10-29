"""Real tiny CLIP/UNet CPU tests, not cached-latent or pretrained-model evidence.

No installation/download, GPU, DDIM sampling, optimizer or VAE is performed.
The adapter uses synthetic 8x8 CPU latents and eight-token fixture embeddings;
production SD1.5 uses audited 64x64 t481 caches and its 77-token tokenizer.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from diffusers import DDIMScheduler, UNet2DConditionModel
from transformers import CLIPTextModel, CLIPTokenizer

from test_tssa_sd_runtime_integration import TinyCPURuntime
from tssa_gradient_core import CalibrationScalars, cfg_prediction
from tssa_target_semantic_runtime import (
    HARD_LIMITS, OBSERVED_TRANSFER_RESIDUES, RESOURCE_KEYS, SEMANTIC_ASSET_PATHS, UNIT_PROMPTS,
    SemanticDiagnosticBackend, _basis_tensor_audit, _verify_semantic_files,
    audit_semantic_cpu_basis, load_semantic_cpu_assets,
)


def fixture():
    runtime = TinyCPURuntime()
    units = []
    for index, (name, (normal, extra)) in enumerate(UNIT_PROMPTS.items()):
        target = normal.replace('dog', 'cat')
        trigger = normal.replace('o', '\u020f')
        for prompt, token in ((normal, 3 + index), (trigger, 6 + index), (extra, 9 + index), (target, 12 + index)):
            runtime.token_fixture[prompt] = [0, token, 20, 21, 2, 1, 1, 1]
        generator = torch.Generator(device='cpu').manual_seed(710 + index)
        units.append({'id': name, 'normal': normal, 'triggered': trigger, 'extra_prompt': extra,
                      'target': target, 'pair_latent': torch.randn(1, 4, 8, 8, generator=generator),
                      'extra_latent': torch.randn(1, 4, 8, 8, generator=generator),
                      'denoising_step_1based': 13, 'timestep': 481})
    return runtime, units, runtime.protocol['merging']['development_normal_states']


class SemanticRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_threads = torch.get_num_threads()
        torch.set_num_threads(2)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.old_threads)

    def test_full_plan_real_FP32_FD_and_exact_hook_budget(self):
        runtime, units, conditions = fixture()
        events, layouts = [], []
        backend = SemanticDiagnosticBackend(runtime, budget_callback=lambda event: events.append(deepcopy(event)))
        original_tokens = runtime._tokens

        def record_layout(prompts):
            layouts.append(list(prompts))
            self.assertEqual(events[-1]['operation'], 'te_batch')
            return original_tokens(prompts)

        with patch.object(runtime, '_tokens', side_effect=record_layout):
            teachers = {(u['id'], c['id']): backend.teacher(u, c) for u in units for c in conditions}
            identities = {(u['id'], c['id']): backend.student(u, c, (0, 0), teachers[u['id'], c['id']])
                          for u in units for c in conditions}
            naive = {(u['id'], c['id']): backend.student(u, c, (1, 1), teachers[u['id'], c['id']], gradients=True)
                     for u in units for c in conditions}
            repeats = {(u['id'], c['id']): backend.student(u, c, (1, 1), teachers[u['id'], c['id']])
                       for u in units for c in conditions}
            differences = {}
            for h in (1 / 8, 1 / 16):
                for axis in (0, 1):
                    sides = {}
                    for sign in (-1, 1):
                        values = [1., 1.]
                        values[axis] += sign * h
                        sides[sign] = {(u['id'], c['id']): backend.student(u, c, values, teachers[u['id'], c['id']])
                                       for u in units for c in conditions}
                    for key, value in naive.items():
                        for term in ('attack', 'normal'):
                            if value['losses'][term] is not None:
                                finite_difference = (sides[1][key]['losses'][term] - sides[-1][key]['losses'][term]) / (2 * h)
                                differences[key, term, axis, h] = finite_difference
        for key, value in naive.items():
            self.assertEqual(identities[key]['losses']['normal'], 0.)
            self.assertTrue(all(v == 0 for v in identities[key]['errors_vs_teacher'].values()))
            for name, tensor in value['outputs'].items():
                self.assertFalse(tensor.requires_grad)
                self.assertIsNone(tensor.grad_fn)
                self.assertEqual(tensor.device.type, 'cpu')
                self.assertTrue(torch.equal(tensor, repeats[key]['outputs'][name]))
            self.assertEqual(value['losses'], repeats[key]['losses'])
            for term in ('attack', 'normal'):
                gradient = value['gradients'][term]
                if gradient is None:
                    self.assertEqual(key[1], 'upload')
                    self.assertEqual(term, 'attack')
                    continue
                for axis in (0, 1):
                    large, small = (differences[key, term, axis, h] for h in (1/8, 1/16))
                    tolerance = .20 * max(abs(gradient[axis]), abs(large), abs(small)) + 5e-7
                    self.assertLessEqual(abs(large-small), tolerance)
                    self.assertLessEqual(abs(gradient[axis]-large), tolerance)
                    self.assertLessEqual(abs(gradient[axis]-small), tolerance)
            expected = {'forward_branch_nfe': 4 if key[1] == 'upload' else 5, 'te_batch_calls': 1,
                        'autograd_calls': 1 if key[1] == 'upload' else 2,
                        'unet_backward_branch_visits': 4 if key[1] == 'upload' else 6,
                        'te_backward_calls': 1 if key[1] == 'upload' else 2}
            self.assertEqual(value['resource_delta'], expected)
        self.assertEqual(backend.resource_record()['actual'], HARD_LIMITS)
        self.assertEqual(backend.resource_record()['attempted'], HARD_LIMITS)
        self.assertEqual({key: sum(e['cost'][key] for e in events) for key in RESOURCE_KEYS}, HARD_LIMITS)
        self.assertEqual(len(layouts), 96)
        self.assertTrue(all(layout == ['', u['normal'], u['triggered'], u['extra_prompt'], u['target']]
                            for layout in layouts for u in units if layout[1] == u['normal']))
        self.assertTrue(any(abs(g) > 1e-7 for record in naive.values() for values in record['gradients'].values()
                            if values is not None for g in values))
        self.assertFalse(runtime._pending_graph)
        self.assertTrue(all(p.grad is None and not p.requires_grad for model in (runtime.text_encoder, runtime.unet)
                            for p in model.parameters()))
        calls = runtime.ledger['text_encoder_forwards']
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            backend.teacher(units[0], conditions[0])
        self.assertEqual(runtime.ledger['text_encoder_forwards'], calls)
        self.assertFalse(torch.cuda.is_initialized())

    def test_losses_match_direct_real_response_math_and_teacher_is_fixed(self):
        runtime, units, conditions = fixture()
        unit, condition = units[0], conditions[1]
        backend = SemanticDiagnosticBackend(runtime)
        teacher = backend.teacher(unit, condition)
        frozen_hashes = deepcopy(teacher['output_sha256'])
        actual = backend.student(unit, condition, (1, 1), teacher, gradients=True)
        # Independent assembly through the same real modules, without the new
        # backend loss builder or its outputs; additional work is CPU test only.
        runtime.activate_condition(condition)
        scalars = CalibrationScalars('RC-TSSA-GD')
        e = runtime._embeddings(['', unit['normal'], unit['triggered'], unit['extra_prompt'], unit['target']],
                                scalars, condition['alpha_malicious'])
        p0 = runtime._branch(unit['pair_latent'], 481, e[0:1])
        pn = cfg_prediction(p0, runtime._branch(unit['pair_latent'], 481, e[1:2]))
        pt = cfg_prediction(p0, runtime._branch(unit['pair_latent'], 481, e[2:3]))
        qn = cfg_prediction(runtime._branch(unit['extra_latent'], 481, e[0:1]),
                            runtime._branch(unit['extra_latent'], 481, e[3:4]))
        attack = ((pt - teacher['outputs']['target']) ** 2).mean()
        normal = .5 * ((pn-teacher['outputs']['normal']) ** 2).mean() + .5 * ((qn-teacher['outputs']['extra']) ** 2).mean()
        ga, = torch.autograd.grad(attack, scalars.raw, retain_graph=True)
        gn, = torch.autograd.grad(normal, scalars.raw)
        self.assertEqual(actual['losses']['attack'], float(attack.detach()))
        self.assertEqual(actual['losses']['normal'], float(normal.detach()))
        torch.testing.assert_close(torch.tensor(actual['gradients']['attack']), ga, rtol=1e-5, atol=1e-7)
        torch.testing.assert_close(torch.tensor(actual['gradients']['normal']), gn, rtol=1e-5, atol=1e-7)
        self.assertEqual(teacher['output_sha256'], frozen_hashes)
        self.assertIsNone(teacher['losses'])
        self.assertTrue(all(not value.requires_grad and value.grad_fn is None for value in teacher['outputs'].values()))
        self.assertGreater(teacher['signal_rms'], 0)

    def test_upload_has_both_normal_branches_and_no_attack_target(self):
        runtime, units, conditions = fixture()
        unit, condition = units[1], next(c for c in conditions if c['id'] == 'upload')
        backend = SemanticDiagnosticBackend(runtime)
        teacher = backend.teacher(unit, condition)
        result = backend.student(unit, condition, (1, 1), teacher, gradients=True)
        self.assertEqual(set(teacher['outputs']), {'normal', 'extra'})
        self.assertIsNone(teacher['signal_rms'])
        self.assertIsNone(result['losses']['attack'])
        self.assertIsNone(result['gradients']['attack'])
        errors = [(result['outputs'][key]-teacher['outputs'][key]).square().mean() for key in ('normal','extra')]
        self.assertTrue(all(float(v) > 0 for v in errors))
        self.assertEqual(result['losses']['normal'], float(.5 * errors[0] + .5 * errors[1]))
        self.assertEqual(result['resource_delta']['forward_branch_nfe'], 4)
        self.assertEqual(result['resource_delta']['unet_backward_branch_visits'], 4)

    def test_budget_callback_precedes_compute_and_failure_is_not_replayed(self):
        runtime, units, conditions = fixture()
        events = []

        def budget(event):
            events.append(event)
            if event['operation'].startswith('unet_'):
                raise RuntimeError('simulated durable budget refusal')

        backend = SemanticDiagnosticBackend(runtime, budget_callback=budget)
        with patch.object(runtime, '_branch', side_effect=AssertionError('branch must not run')) as branch:
            with self.assertRaisesRegex(RuntimeError, 'budget refusal'):
                backend.teacher(units[0], conditions[0])
            self.assertEqual(branch.call_count, 0)
        self.assertEqual([e['operation'] for e in events], ['begin', 'te_batch', 'unet_pair_unconditional'])
        self.assertEqual(backend.resource_record()['actual']['te_batch_calls'], 1)
        self.assertEqual(backend.resource_record()['attempted']['forward_branch_nfe'], 0)
        self.assertTrue(backend.resource_record()['failed'])
        with self.assertRaisesRegex(ValueError, 'no retry'):
            backend.teacher(units[0], conditions[0])

    def test_started_failing_forward_counts_attempt_and_releases_state(self):
        runtime, units, conditions = fixture()
        backend = SemanticDiagnosticBackend(runtime)
        with patch.object(runtime, '_branch', side_effect=RuntimeError('simulated UNet failure')):
            with self.assertRaisesRegex(RuntimeError, 'UNet failure'):
                backend.teacher(units[0], conditions[0])
        self.assertEqual(backend.resource_record()['attempted']['forward_branch_nfe'], 1)
        self.assertEqual(backend.resource_record()['actual']['te_batch_calls'], 1)
        self.assertFalse(runtime._pending_graph)

    def test_teacher_tampering_and_live_weight_gradient_are_refused(self):
        runtime, units, conditions = fixture()
        backend = SemanticDiagnosticBackend(runtime)
        teacher = backend.teacher(units[0], conditions[0])
        teacher['outputs']['target'].view(-1)[0] += 1
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            backend.student(units[0], conditions[0], (1,1), teacher, gradients=True)
        runtime, units, conditions = fixture()
        next(runtime.unet.parameters()).requires_grad_(True)
        backend = SemanticDiagnosticBackend(runtime)
        with self.assertRaisesRegex(ValueError, 'frozen'):
            backend.teacher(units[0], conditions[0])
        self.assertEqual(sum(backend.resource_record()['actual'].values()), 0)

    def test_wrong_unit_state_or_diagnostic_point_stops_before_forward(self):
        for change in ('target', 'timestep', 'heldout', 'point'):
            runtime, units, conditions = fixture()
            backend = SemanticDiagnosticBackend(runtime)
            unit, condition = deepcopy(units[0]), deepcopy(conditions[0])
            if change == 'target': unit['target'] = unit['triggered']
            if change == 'timestep': unit['timestep'] = 981
            if change == 'heldout': condition = runtime.protocol['merging']['heldout_states'][0]
            with self.subTest(change=change), self.assertRaises(ValueError):
                if change == 'point': backend.student(unit, condition, (.5,.5), {})
                else: backend.teacher(unit, condition)
            self.assertEqual(sum(backend.resource_record()['actual'].values()), 0)


class SemanticAssetCPUChecks(unittest.TestCase):
    @staticmethod
    def simulated_asset_files(root):
        entries = []
        for name in SEMANTIC_ASSET_PATHS:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = ('SIMULATED ' + name).encode()
            path.write_bytes(raw)
            entries.append({'local_path': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                            'git_blob_oid': hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest(),
                            'is_lfs': False, 'revision': 'CPU_fixture'})
        return {'files': entries}

    def test_exact_observed_residues_are_only_statted_and_metadata_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = self.simulated_asset_files(root)
            baseline = _verify_semantic_files(spec, root)
            residues = {root / folder / name for folder, names in OBSERVED_TRANSFER_RESIDUES.items() for name in names}
            payload = b'SIMULATED transfer residual bytes; must never be opened by verification'
            for path in residues:
                path.write_bytes(payload)
            before = {path: path.lstat() for path in residues}
            original_open = Path.open

            def forbid_residue_content(path, *args, **kwargs):
                if path in residues:
                    raise AssertionError('Transfer residue content was opened')
                return original_open(path, *args, **kwargs)

            ignored = []
            with patch.object(Path, 'open', new=forbid_residue_content):
                verified = _verify_semantic_files(spec, root, ignored_metadata=ignored)
            self.assertEqual(verified, baseline)
            self.assertEqual(len(verified), 19)
            self.assertEqual({row['relative_path'] for row in ignored}, {p.relative_to(root).as_posix() for p in residues})
            for row in ignored:
                path = root / row['relative_path']
                self.assertFalse(row['contents_read'])
                self.assertEqual(row['owner_uid'], os.geteuid())
                self.assertEqual(row['size'], len(payload))
                self.assertEqual((row['inode'], row['device'], row['mtime_ns']),
                                 (before[path].st_ino, before[path].st_dev, before[path].st_mtime_ns))
                self.assertEqual(path.read_bytes(), payload)
                self.assertEqual(path.lstat().st_mtime_ns, before[path].st_mtime_ns)

    def test_unknown_chunks_models_tokenizer_files_and_wrong_directory_are_rejected(self):
        extras = ('sd15/tokenizer/added_tokens.json', 'sd15/unet/diffusion_pytorch_model.bin',
                  'sd15/unet/diffusion_pytorch_model.safetensors.index.json',
                  'sd15/unet/diffusion_pytorch_model.safetensors.uploading.chunk-unknown',
                  'dreamshaper8/unet/diffusion_pytorch_model.safetensors.uploading.chunk-pvk2dyci')
        for extra in extras:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                spec = self.simulated_asset_files(root)
                (root / extra).write_bytes(b'SIMULATED unknown extra')
                with self.assertRaisesRegex(ValueError, 'unverified files'):
                    _verify_semantic_files(spec, root)

    def test_observed_residue_symlink_directory_or_fifo_is_rejected(self):
        for kind in ('symlink', 'directory', 'fifo'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                spec = self.simulated_asset_files(root)
                path = root/'sd15/unet/diffusion_pytorch_model.safetensors.uploading.chunk-pvk2dyci'
                if kind == 'symlink': path.symlink_to(root/'sd15/unet/diffusion_pytorch_model.safetensors')
                elif kind == 'directory': path.mkdir()
                else: os.mkfifo(path)
                with self.assertRaisesRegex(ValueError, 'owned regular non-symlink'):
                    _verify_semantic_files(spec, root)

    def test_observed_residue_owned_by_someone_else_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = self.simulated_asset_files(root)
            path = root/'sd15/unet/diffusion_pytorch_model.safetensors.uploading.chunk-pvk2dyci'
            path.write_bytes(b'SIMULATED residue')
            with patch('tssa_target_semantic_runtime.os.geteuid', return_value=path.stat().st_uid + 1):
                with self.assertRaisesRegex(ValueError, 'owned regular non-symlink'):
                    _verify_semantic_files(spec, root)

    def test_observed_residue_cannot_substitute_for_missing_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = self.simulated_asset_files(root)
            (root/'sd15/unet/diffusion_pytorch_model.safetensors').unlink()
            (root/'sd15/unet/diffusion_pytorch_model.safetensors.uploading.chunk-pvk2dyci').write_bytes(b'SIMULATED residue')
            with self.assertRaisesRegex(ValueError, 'missing or unverified files'):
                _verify_semantic_files(spec, root)

    def test_loader_routes_only_required_components_and_checks_target_tokenization(self):
        runtime, _, _ = fixture()
        calls, tokenized = [], []

        class TokenizerFixture:
            model_max_length, bos_token_id, eos_token_id, pad_token_id, unk_token_id = 77, 0, 2, 1, 3
            bpe_ranks = {}
            def get_vocab(self): return {'fixture': 3}
            def __call__(self, prompt, truncation=False):
                tokenized.append(prompt)
                return {'input_ids': [0, 3, 2]}

        def te(path, **kwargs):
            calls.append(('TE', str(path), kwargs))
            role = 'backdoor' if path.name == 'backdoor_tpa' else 'Edev' if path.parent.name == 'dreamshaper8' else 'clean'
            model = deepcopy(runtime.text_encoder)
            model.load_state_dict(runtime.assets.text_states[role])
            return model

        def unet(path, **kwargs):
            calls.append(('UNet', str(path), kwargs))
            model = deepcopy(runtime.unet)
            model.load_state_dict(runtime.assets.unet_states['Edev' if path.parent.name == 'dreamshaper8' else 'clean'])
            return model

        def tokenizer(path, **kwargs):
            calls.append(('tokenizer', str(path), kwargs))
            return TokenizerFixture()

        def scheduler(path, **kwargs):
            calls.append(('scheduler', str(path), kwargs))
            return deepcopy(runtime.scheduler)

        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory, \
                patch('tssa_target_semantic_runtime._verify_semantic_files', return_value={}), \
                patch.object(CLIPTextModel, 'from_pretrained', side_effect=te), \
                patch.object(UNet2DConditionModel, 'from_pretrained', side_effect=unet), \
                patch.object(CLIPTokenizer, 'from_pretrained', side_effect=tokenizer), \
                patch.object(DDIMScheduler, 'from_pretrained', side_effect=scheduler):
            assets = load_semantic_cpu_assets(root/'research/tssa_mvp_2026-10-26.json',
                                              root/'research/tssa_mvp_assets_2026-10-26.json', directory)
        self.assertEqual(set(assets.text_states), {'clean','backdoor','Edev'})
        self.assertEqual(set(assets.unet_states), {'clean','Edev'})
        self.assertEqual(assets.model_load_count, 5)
        self.assertEqual([kind for kind, _, _ in calls].count('TE'), 3)
        self.assertEqual([kind for kind, _, _ in calls].count('UNet'), 2)
        self.assertTrue(all(kwargs['local_files_only'] for _, _, kwargs in calls))
        self.assertFalse(any(term in path for _, path, _ in calls for term in ('openjourney','vae','vit','clip')))
        for normal, _ in UNIT_PROMPTS.values():
            self.assertIn(normal.replace('dog','cat'), tokenized)
        self.assertFalse(torch.cuda.is_initialized())

    def test_restricted_hash_inventory_does_not_require_or_read_other_components(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries = []
            for name in SEMANTIC_ASSET_PATHS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                raw = ('SIMULATED ' + name).encode()
                path.write_bytes(raw)
                entries.append({'local_path':name, 'size':len(raw), 'sha256':hashlib.sha256(raw).hexdigest(),
                                'git_blob_oid':hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest(),
                                'is_lfs':False, 'revision':'CPU_fixture'})
            self.assertEqual(len(entries), 19)
            verified = _verify_semantic_files({'files':entries}, root)
            self.assertEqual(set(verified), set(SEMANTIC_ASSET_PATHS))
            self.assertFalse(any(term in name for name in verified for term in ('openjourney','vae/','vit/','clip/')))
            unverified = root/'sd15/tokenizer/added_tokens.json'
            unverified.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'unverified files'):
                _verify_semantic_files({'files':entries}, root)

    def test_cpu_basis_hashes_match_bytes_and_detect_changed_partition(self):
        runtime, _, _ = fixture()
        assets = SimpleNamespace(text_encoder=runtime.text_encoder, text_states=runtime.assets.text_states,
                                 basis=runtime.basis, parameter_names=tuple(runtime.basis.delta_a))
        report = _basis_tensor_audit(assets)
        for group in ('clean','backdoor','delta_a','delta_b'):
            values = assets.text_states[group] if group in assets.text_states else getattr(assets.basis, group)
            raw = b''.join(values[name].detach().contiguous().view(torch.uint8).numpy().tobytes()
                           for name in assets.parameter_names)
            self.assertEqual(report['ordered_contiguous_byte_sha256'][group], hashlib.sha256(raw).hexdigest())
        with self.assertRaisesRegex(ValueError, 'statistics'):
            audit_semantic_cpu_basis(assets)  # Tiny random weights must never claim original SD basis identity.
        key = next(iter(assets.basis.delta_a))
        assets.basis.delta_a[key].view(-1)[0] += 1
        with self.assertRaisesRegex(ValueError, 'partition'):
            _basis_tensor_audit(assets)

    def test_loader_rejects_changed_original_manifests_before_model_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'changed.json'
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'protocol hash changed'):
                load_semantic_cpu_assets(path, path, directory)


if __name__ == '__main__':
    unittest.main(verbosity=2)
