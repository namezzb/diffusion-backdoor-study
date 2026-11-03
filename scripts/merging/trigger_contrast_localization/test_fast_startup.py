"""CPU fixtures for startup without model scans or historical ledger reads."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import torch
import runtime_tcl
import runtime_assets


class FastStartupTests(unittest.TestCase):
    def test_stage_statistics_use_scores_without_reading_images(self):
        key = ('run', 'source', 'clean', 'dog', 'context', 1)
        adapter = runtime_tcl.TCLAdapter({'science': {}})
        adapter.stages = {'S0': [key]}
        adapter.binding = SimpleNamespace(labels={('source', 'context', category): (1,)
            for category in ('trigger', 'dog', 'cat', 'other')})
        scores = {'vit_class': 1, 'clip_score': 42.0}
        record = {'key': key, 'scores': scores, 'image_path': '/missing/image.png', 'image_sha256': 'wrong'}
        with patch('pilot24_statistics.report', return_value={'baseline': {'passed': True}}) as report:
            result = adapter.stage_gate('S0', [record])
        self.assertTrue(result['passed'])
        self.assertEqual(report.call_args.args[1][0]['clip_score'], 42.0)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            adapter.stage_gate('S0', [record, record])
        with self.assertRaisesRegex(ValueError, 'complete paired'):
            adapter.stage_gate('S0', [])

    def test_historical_identity_and_directory_are_read_only(self):
        import runtime
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory)/'spec.json'
            for old in runtime_tcl.HISTORICAL_RUNS:
                for run_id, run_root in ((old, directory), ('tcl-20261103-semantic-v1', directory+'/'+old)):
                    value = {'run_id': run_id, 'run_root': run_root}
                    spec.write_text(json.dumps(value))
                    with self.assertRaisesRegex(ValueError, 'historical'):
                        runtime.load_spec(spec)
                    with self.assertRaisesRegex(ValueError, 'historical'):
                        runtime_tcl.build_spec(value)
            runtime_tcl.require_current_run('tcl-20261103-semantic-v1', directory+'/semantic')

    def test_loader_uses_original_component_paths_dtype_and_state_values(self):
        from tssa_sd_runtime import CPUAssets, _cpu_state
        from tssa_target_semantic_runtime import ROLE_DIRECTORIES
        calls = []
        def load(path, **kwargs):
            calls.append((Path(path), kwargs))
            model = torch.nn.Linear(2, 2)
            with torch.no_grad():
                model.weight.fill_(len(calls))
                model.bias.fill_(len(calls))
            return model
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = root / 'protocol.json'
            protocol.write_text('{}')
            with patch('transformers.CLIPTextModel.from_pretrained', side_effect=load), \
                 patch('diffusers.UNet2DConditionModel.from_pretrained', side_effect=load), \
                 patch('transformers.CLIPTokenizer.from_pretrained', return_value='tokenizer'), \
                 patch('diffusers.DDIMScheduler.from_pretrained', return_value='scheduler'), \
                 patch('runtime_assets.verify_active_assets', side_effect=AssertionError('bulk audit')), \
                 patch('tssa_target_semantic_runtime._verify_semantic_files', side_effect=AssertionError('legacy audit')):
                result = runtime_assets.load_tcl_runtime_assets(protocol, root / 'unused.json', root, {'file': 'a'*64})
            expected = [root / ROLE_DIRECTORIES['clean'] / 'text_encoder',
                        root / ROLE_DIRECTORIES['clean'] / 'unet',
                        root / ROLE_DIRECTORIES['backdoor'],
                        root / ROLE_DIRECTORIES['Edev'] / 'text_encoder',
                        root / ROLE_DIRECTORIES['Edev'] / 'unet']
            self.assertEqual([p for p, kw in calls], expected)
            for path, kw in calls:
                self.assertEqual(kw['torch_dtype'], torch.float32)
                self.assertTrue(kw['local_files_only'])
                self.assertTrue(kw['use_safetensors'])
            for role, value in [('clean', 1), ('backdoor', 3), ('Edev', 4)]:
                self.assertTrue(torch.equal(result.text_states[role]['weight'], torch.full((2, 2), value, dtype=torch.float32)))
            self.assertTrue(torch.equal(result.unet_states['Edev']['weight'], torch.full((2, 2), 5.)))
            self.assertEqual(result.parameter_names, ('weight', 'bias'))
            self.assertEqual(result.file_hashes['file']['sha256'], 'a'*64)
            self.assertFalse(result.file_hashes['file']['startup_rehashed'])

    def test_fast_and_legacy_loaders_construct_equal_numerical_states(self):
        import hashlib
        import tssa_target_semantic_runtime as legacy
        counter = [0]
        def load(path, **kwargs):
            counter[0] += 1
            model = torch.nn.Linear(2, 2)
            model.config = SimpleNamespace()
            with torch.no_grad():
                model.weight.fill_(counter[0]); model.bias.fill_(counter[0])
            return model
        tokenizer = SimpleNamespace(model_max_length=77)
        scheduler = SimpleNamespace(config=SimpleNamespace(prediction_type='epsilon'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roles = {r: {'repo_id': r, 'revision': 'pinned'} for r in ('clean', 'backdoor', 'Edev')}
            protocol = {'models': roles}
            protocol_file = root/'protocol';protocol_file.write_text(json.dumps(protocol))
            manifest = root/'manifest';manifest.write_text(json.dumps({'assets': [
                {'local_dir': legacy.ROLE_DIRECTORIES[r], **v} for r, v in roles.items()]}))
            with patch('transformers.CLIPTextModel.from_pretrained', side_effect=load), \
                 patch('diffusers.UNet2DConditionModel.from_pretrained', side_effect=load), \
                 patch('transformers.CLIPTokenizer.from_pretrained', return_value=tokenizer), \
                 patch('diffusers.DDIMScheduler.from_pretrained', return_value=scheduler), \
                 patch.object(legacy, 'OLD_PROTOCOL_SHA', hashlib.sha256(protocol_file.read_bytes()).hexdigest()), \
                 patch.object(legacy, 'ASSET_MANIFEST_SHA', hashlib.sha256(manifest.read_bytes()).hexdigest()), \
                 patch.object(legacy, 'read_frozen_protocol', return_value=(protocol, 'metadata')), \
                 patch.object(legacy, '_verify_semantic_files', return_value={}), \
                 patch.object(legacy, '_check_tokenizers'), patch.object(legacy, '_check_configs', return_value={}), \
                 patch.object(legacy, '_check_states', return_value={'changed_coordinates': 1}):
                previous = legacy.load_semantic_cpu_assets(protocol_file, manifest, root)
                counter[0] = 0
                fast = runtime_assets.load_tcl_runtime_assets(protocol_file, manifest, root, {})
            for field in ('text_states', 'unet_states'):
                for role, state in getattr(previous, field).items():
                    for name, tensor in state.items():
                        self.assertTrue(torch.equal(tensor, getattr(fast, field)[role][name]))
            self.assertEqual(previous.parameter_names, fast.parameter_names)
            self.assertEqual(previous.protocol, fast.protocol)
            self.assertEqual(previous.model_load_count, fast.model_load_count)
            for name in previous.basis.delta_a:
                self.assertTrue(torch.equal(previous.basis.delta_a[name], fast.basis.delta_a[name]))
                self.assertTrue(torch.equal(previous.basis.delta_b[name], fast.basis.delta_b[name]))

    def test_actual_semantic_protocol_keys_equal_original_including_order(self):
        import semantic_science
        root = Path(__file__).resolve().parents[3]
        protocol_file = root/'research/tasks/2026-11-03-tcl-semantic/protocol.json'
        prompt = root/'research/tasks/2026-10-29-trigger-contrast-localization/prompts_tokenized_candidate.jsonl'
        protocol = json.loads(protocol_file.read_text())
        expected = semantic_science.frozen_units(protocol, prompt)
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            (tmp/'small').write_text('{}')
            (tmp/'selection').write_text(json.dumps({'mask_sha256': {v: 'a'*64 for v in protocol['versions']}}))
            inputs = {name: str(tmp/'small') for name in runtime_tcl.REQUIRED_INPUTS}
            inputs.update(prompts=str(prompt), selection=str(tmp/'selection'), localization_ledger=str(tmp/'absent.sqlite'))
            spec = runtime_tcl.build_spec({'run_id': semantic_science.RUN_ID, 'run_root': str(tmp/'run'),
                'models_root': str(tmp/'models'), 'inputs': inputs, 'study_protocol': str(protocol_file)})
            self.assertEqual([tuple(u['key']) for u in spec['science']['units']],
                             [key for stage in runtime_tcl.STAGES for key in expected[stage]])
            self.assertEqual(len(spec['science']['units']), 1024)
            with self.assertRaisesRegex(ValueError, 'full audit requires'):
                runtime_tcl.TCLAdapter(spec).audit_cpu()

    def test_new_spec_constructs_fixed_keys_without_opening_history(self):
        from bindings import input_digest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = {"id": "ctx", "partition": "source", "texts": {"dog": "dog"},
                   "tokenization": {"dog": {}}, "class_ids": {"dog": [1]}}
            inputs = {name: str(root/name) for name in runtime_tcl.REQUIRED_INPUTS}
            for name in ("parent_manifest", "protocol", "asset_manifest"):
                Path(inputs[name]).write_text("{}")
            Path(inputs["prompts"]).write_text(json.dumps(row)+"\n")
            Path(inputs["selection"]).write_text(json.dumps({"mask_sha256": {"clean": "a"*64, "backdoor": "b"*64}}))
            protocol = {"design": "semantic-v1", "budget": {"max_attempts": 1056},
                        "context_ids": {"source": ["ctx"], "merge": []},
                        "versions": ["clean", "backdoor"], "classes": ["dog"], "generation_seeds": [42]}
            study = root/"study.json";study.write_text(json.dumps(protocol))
            with patch.object(runtime_tcl.TCLAdapter, "validate_inputs", side_effect=AssertionError("audit")):
                spec = runtime_tcl.build_spec({"run_id": "new", "run_root": str(root/"run"),
                    "models_root": str(root/"models"), "inputs": inputs, "study_protocol": str(study)})
            self.assertEqual([u["key"] for u in spec["science"]["units"]],
                             [["new", "source", v, "dog", "ctx", 42] for v in ("clean", "backdoor")])
            self.assertIsNone(spec["science"]["inputs"]["localization_ledger"]["sha256"])
            self.assertFalse(Path(inputs["localization_ledger"]).exists())

    def test_prepare_reads_fixed_prompt_masks_and_units_without_history(self):
        from bindings import input_digest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = {'id': 'ctx', 'partition': 'source', 'texts': {'trigger': 'tr', 'dog': 'dog'},
                   'tokenization': {'trigger': {'input_ids': [1], 'attention_mask': [1]}, 'dog': {}},
                   'class_ids': {'trigger': [3], 'dog': [4]}}
            (root / 'prompts').write_text(json.dumps(row)+'\n')
            (root / 'mask').write_text('{"weight":[0]}')
            (root / 'selection').write_text(json.dumps({'mask_files': {'new': 'mask'}, 'mask_sha256': {'new': 'b'*64}}))
            (root / 'parent_manifest').write_text(json.dumps({'asset_sha256': {'f': 'c'*64}}))
            inputs = {name: {'path': str(root/name), 'sha256': 'a'*64} for name in runtime_tcl.REQUIRED_INPUTS}
            unit = {'key': ['new-run', 'source', 'new', 'trigger', 'ctx', 42],
                    'input_sha': input_digest(row, 'trigger'), 'mask_sha': 'b'*64}
            spec = {'run_id': 'new-run', 'science': {'inputs': inputs, 'units': [unit], 'models_root': str(root)}, 'execution': {}}
            before = copy.deepcopy(spec)
            adapter = runtime_tcl.TCLAdapter(spec)
            with patch.object(adapter, 'validate_inputs', side_effect=AssertionError('historical audit')), \
                 patch('runtime_assets.load_tcl_runtime_assets', return_value=object()) as loader:
                adapter.prepare_cpu()
            self.assertEqual(spec, before)
            self.assertEqual(adapter.units(), [unit])
            self.assertEqual(adapter._prompt(unit)['prompt'], 'tr')
            self.assertEqual(adapter._prompt(unit)['score_prompt'], 'dog')
            self.assertEqual(json.loads(adapter.binding.coordinate_masks['new']), {'weight': [0]})
            loader.assert_called_once()
            self.assertFalse((root/'localization_ledger').exists())


if __name__ == '__main__':
    unittest.main()
