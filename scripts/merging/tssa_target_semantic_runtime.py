"""Bounded same-state semantic-response diagnostic; no sampling or optimization.

Wraps an already prepared SDGradientRuntime (or its real tiny-network CPU test
adapter). The caller verifies cached-latent provenance, frozen assets and GPU
permission. Every compute attempt is reserved before execution; an exception
poisons this backend, so there is no implicit retry or checkpoint recomputation.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping, Sequence

import torch
from torch import Tensor

from tssa_gradient_core import CalibrationScalars, FrozenDelta, cfg_prediction
from tssa_sd_runtime import (CPUAssets, ROLE_DIRECTORIES, SDGradientRuntime, _check_configs,
                             _check_states, _check_tokenizers, _cpu_state, read_frozen_protocol)


RESOURCE_KEYS = ('forward_branch_nfe', 'te_batch_calls', 'autograd_calls',
                 'unet_backward_branch_visits', 'te_backward_calls')
HARD_LIMITS = dict(zip(RESOURCE_KEYS, (462, 96, 14, 44, 14)))
UNIT_PROMPTS = {
    'fit_unit_p00_s13': ('A dog is running along a sandy beach beside gentle waves.',
                        'A photograph of a ripe banana in a ceramic bowl.'),
    'fit_unit_p04_s13': ('A dog is walking through an orchard of apple trees.',
                        'A photograph of a red fire engine parked beside a fire station.'),
}
ALLOWED_COEFFICIENTS = {(0.0, 0.0), (1.0, 1.0)} | {
    pair for h in (1 / 8, 1 / 16) for pair in
    ((1 - h, 1.0), (1 + h, 1.0), (1.0, 1 - h), (1.0, 1 + h))
}
OLD_PROTOCOL_SHA = '8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c'
ASSET_MANIFEST_SHA = '881d2d21083d589dcd26e69c977a8048d270d2cb73ddb7bd286e2d4dd9197902'
SEMANTIC_ASSET_PATHS = tuple(
    [f'{root}/{component}/{filename}'
     for root in ('sd15', 'dreamshaper8')
     for component, filenames in (
         ('text_encoder', ('config.json', 'model.safetensors')),
         ('unet', ('config.json', 'diffusion_pytorch_model.safetensors')),
         ('tokenizer', ('merges.txt', 'special_tokens_map.json', 'tokenizer_config.json', 'vocab.json')))
     for filename in filenames]
    + ['sd15/scheduler/scheduler_config.json', 'backdoor_tpa/config.json', 'backdoor_tpa/model.safetensors'])
# Exact names observed by the 2026-10-28 read-only server inventory. These
# transfer chunks are not model/config/tokenizer filenames selected by loaders.
OBSERVED_TRANSFER_RESIDUES = {
    'sd15/unet': {'diffusion_pytorch_model.safetensors.uploading.chunk-pvk2dyci'},
    'dreamshaper8/unet': {'diffusion_pytorch_model.safetensors.uploading.chunk-q0b0u62q'},
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _finite(value: Tensor, name: str) -> None:
    if not bool(torch.isfinite(value).all()):
        raise FloatingPointError('Non-finite ' + name)


def _tensor_sha(value: Tensor) -> str:
    raw = value.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()
    return hashlib.sha256(raw).hexdigest()


def _rms(value: Tensor) -> float:
    return float(value.detach().float().square().mean().sqrt().cpu())


def _verify_semantic_files(spec: Mapping[str, Any], root: Path, *,
                           ignored_metadata: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Hash only the 19 files used here; never touch Ehold, VAE or scorers."""
    indexed = {entry['local_path']: entry for entry in spec['files']}
    _require(len(indexed) == len(spec['files']), 'Duplicate asset entry')
    directories: dict[Path, set[str]] = {}
    for name in SEMANTIC_ASSET_PATHS:
        path = Path(name)
        directories.setdefault(root / path.parent, set()).add(path.name)
    for directory, expected in directories.items():
        _require(directory.is_dir(), 'Missing component directory: ' + str(directory))
        present = {p.name for p in directory.iterdir()}
        extras = present - expected
        relative_directory = directory.relative_to(root).as_posix()
        _require(expected <= present and extras <= OBSERVED_TRANSFER_RESIDUES.get(relative_directory, set()),
                 'Component directory has missing or unverified files: ' + str(directory))
        for name in sorted(extras):
            info = (directory / name).lstat()  # Metadata only; never open a residue.
            _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid(),
                     'Observed transfer residue must be an owned regular non-symlink file: ' + name)
            if ignored_metadata is not None:
                ignored_metadata.append({'relative_path': relative_directory + '/' + name,
                                         'size': info.st_size, 'owner_uid': info.st_uid, 'owner_gid': info.st_gid,
                                         'mode': oct(stat.S_IMODE(info.st_mode)), 'mtime_ns': info.st_mtime_ns,
                                         'device': info.st_dev, 'inode': info.st_ino,
                                         'contents_read': False,
                                         'reason': 'exact_observed_transfer_chunk_not_selected_by_from_pretrained'})
    verified = {}
    for name in SEMANTIC_ASSET_PATHS:
        entry = indexed[name]
        path = root / name
        _require(path.resolve().is_relative_to(root.resolve()) and path.is_file(), 'Missing or escaped semantic asset: ' + name)
        for parent in (path, *path.parents):
            if parent == root.parent:
                break
            _require(not parent.is_symlink(), 'Symlink semantic asset refused: ' + name)
        size = path.stat().st_size
        _require(size == entry['size'], 'Semantic asset size mismatch: ' + name)
        digest, blob = hashlib.sha256(), hashlib.sha1(f'blob {size}\0'.encode())
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                digest.update(chunk)
                blob.update(chunk)
        actual = digest.hexdigest()
        if entry.get('sha256'):
            _require(actual == entry['sha256'], 'Semantic asset SHA256 mismatch: ' + name)
        if not entry.get('is_lfs'):
            _require(blob.hexdigest() == entry['git_blob_oid'], 'Semantic asset Git blob mismatch: ' + name)
        else:
            _require(bool(entry.get('sha256')), 'LFS asset needs a frozen SHA256: ' + name)
        verified[name] = {'sha256': actual, 'size': size, 'revision': entry['revision']}
    return verified


def load_semantic_cpu_assets(protocol_path: str | Path, asset_manifest: str | Path,
                             models_root: str | Path) -> CPUAssets:
    """Offline CPU-only clean/backdoor/Edev load, deliberately excluding Ehold.

    This does not invoke the old all-model loader. Only required component files
    are opened; tokenization includes the two new scene-preserving cat prompts.
    No model forward, VAE, image scorer, cache construction or CUDA call occurs.
    """
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    protocol_path, asset_manifest, root = Path(protocol_path), Path(asset_manifest), Path(models_root).resolve()
    _require(hashlib.sha256(protocol_path.read_bytes()).hexdigest() == OLD_PROTOCOL_SHA, 'Original protocol hash changed')
    _require(hashlib.sha256(asset_manifest.read_bytes()).hexdigest() == ASSET_MANIFEST_SHA, 'Original asset manifest hash changed')
    protocol, protocol_hash = read_frozen_protocol(protocol_path)
    spec = json.loads(asset_manifest.read_text())
    by_directory = {item['local_dir']: item for item in spec['assets']}
    for role in ('clean', 'backdoor', 'Edev'):
        item = by_directory[ROLE_DIRECTORIES[role]]
        _require(all(item[field] == protocol['models'][role][field] for field in ('repo_id', 'revision')),
                 'Frozen source identity mismatch: ' + role)
    ignored_metadata: list[dict[str, Any]] = []
    hashes = _verify_semantic_files(spec, root, ignored_metadata=ignored_metadata)
    from diffusers import DDIMScheduler, UNet2DConditionModel
    from transformers import CLIPTextModel, CLIPTokenizer
    te_kwargs = {'torch_dtype': torch.float32, 'use_safetensors': True,
                 'local_files_only': True, 'attn_implementation': 'sdpa'}
    unet_kwargs = {'torch_dtype': torch.float32, 'use_safetensors': True, 'local_files_only': True}
    clean = root / ROLE_DIRECTORIES['clean']
    tokenizer = CLIPTokenizer.from_pretrained(clean / 'tokenizer', local_files_only=True)
    text_encoder = CLIPTextModel.from_pretrained(clean / 'text_encoder', **te_kwargs).eval().requires_grad_(False)
    unet = UNet2DConditionModel.from_pretrained(clean / 'unet', **unet_kwargs).eval().requires_grad_(False)
    text_states, unet_states = {'clean': _cpu_state(text_encoder, clone=True)}, {'clean': _cpu_state(unet, clone=True)}
    te_fields = ('vocab_size', 'hidden_size', 'intermediate_size', 'num_hidden_layers', 'num_attention_heads',
                 'max_position_embeddings', 'hidden_act', 'layer_norm_eps', 'attention_dropout',
                 'bos_token_id', 'eos_token_id', 'pad_token_id')
    unet_fields = ('sample_size', 'in_channels', 'out_channels', 'down_block_types', 'up_block_types',
                   'block_out_channels', 'layers_per_block', 'cross_attention_dim', 'attention_head_dim',
                   'only_cross_attention', 'mid_block_type', 'norm_num_groups', 'norm_eps',
                   'flip_sin_to_cos', 'freq_shift', 'act_fn', 'use_linear_projection', 'upcast_attention',
                   'resnet_time_scale_shift', 'class_embed_type', 'addition_embed_type')
    prompts = [''] + [prompt for p, q in UNIT_PROMPTS.values()
                      for prompt in (p, p.replace('o', '\u020f'), q, re.sub(r'\bdog\b', 'cat', p))]
    _require(tokenizer.model_max_length == 77, 'Expected fixed 77-token padding contract')
    _check_tokenizers(tokenizer, tokenizer, prompts, 'clean/semantic')
    compatibility: dict[str, Any] = {'semantic_prompts': prompts, 'loaded_roles': ['clean', 'backdoor', 'Edev'],
                                     'Ehold_loaded': False, 'VAE_or_scorers_loaded': False,
                                     'ignored_transfer_residue_metadata': ignored_metadata}
    count = 2
    for role in ('backdoor', 'Edev'):
        directory = root / ROLE_DIRECTORIES[role]
        component = directory if role == 'backdoor' else directory / 'text_encoder'
        model = CLIPTextModel.from_pretrained(component, **te_kwargs).eval().requires_grad_(False)
        _check_configs(text_encoder.config, model.config, te_fields, role + '/TE')
        text_states[role] = _cpu_state(model)
        compatibility[role + '/TE'] = _check_states(text_states['clean'], text_states[role], role + '/TE')
        del model
        count += 1
        if role == 'Edev':
            expert_tokenizer = CLIPTokenizer.from_pretrained(directory / 'tokenizer', local_files_only=True)
            _check_tokenizers(tokenizer, expert_tokenizer, prompts, 'Edev/semantic')
            model = UNet2DConditionModel.from_pretrained(directory / 'unet', **unet_kwargs).eval().requires_grad_(False)
            equivalences = _check_configs(unet.config, model.config, unet_fields, 'Edev/UNet')
            unet_states[role] = _cpu_state(model)
            compatibility[role + '/UNet'] = _check_states(unet_states['clean'], unet_states[role], 'Edev/UNet')
            compatibility[role + '/UNet']['configuration_equivalences'] = equivalences
            _require(compatibility[role + '/TE']['changed_coordinates'] or compatibility[role + '/UNet']['changed_coordinates'],
                     'Edev must differ from the clean model')
            del model, expert_tokenizer
            count += 1
    names = tuple(name for name, parameter in text_encoder.named_parameters() if parameter.is_floating_point())
    basis = FrozenDelta.from_state_dicts(text_states['clean'], text_states['backdoor'], names)
    scheduler = DDIMScheduler.from_pretrained(clean / 'scheduler', local_files_only=True)
    _require(scheduler.config.prediction_type == 'epsilon', 'Expected original epsilon scheduler')
    return CPUAssets(protocol, protocol_hash, root, hashes, tokenizer, text_encoder, unet, scheduler,
                     text_states, unet_states, basis, names, compatibility, count)


def _basis_tensor_audit(assets: CPUAssets) -> dict[str, Any]:
    """General CPU helper also exercised by tiny fixtures; production adds old stats below."""
    names = tuple(assets.parameter_names)
    _require(names == tuple(name for name, p in assets.text_encoder.named_parameters() if p.is_floating_point()),
             'Ordered TE parameter domain differs from original named_parameters')
    _require(names == tuple(assets.basis.delta_a) == tuple(assets.basis.delta_b), 'Ordered delta domain mismatch')
    streams = {name: hashlib.sha256() for name in ('clean', 'backdoor', 'delta', 'delta_a', 'delta_b', 'mask')}
    tensors, selected = [], 0
    for name in names:
        clean, backdoor = assets.text_states['clean'][name], assets.text_states['backdoor'][name]
        _require(clean.device.type == backdoor.device.type == 'cpu' and clean.dtype == backdoor.dtype == torch.float32,
                 'CPU audit requires the original unquantized FP32 states')
        delta = backdoor - clean
        mask = delta.abs() > assets.basis.threshold
        a, b = assets.basis.delta_a[name], assets.basis.delta_b[name]
        _require(torch.equal(a, delta * mask) and torch.equal(b, delta * ~mask), 'Frozen partition no longer matches original delta')
        selected += int(mask.sum())
        values = {'clean': clean, 'backdoor': backdoor, 'delta': delta, 'delta_a': a, 'delta_b': b, 'mask': mask}
        hashes = {}
        for group, value in values.items():
            _require(not value.requires_grad and value.grad_fn is None, 'CPU basis tensor must be frozen')
            _finite(value, 'basis/' + group + '/' + name)
            raw = value.detach().contiguous().view(torch.uint8).numpy().tobytes()
            streams[group].update(raw)
            hashes[group] = hashlib.sha256(raw).hexdigest()
        tensors.append({'name': name, 'shape': list(clean.shape), 'parameter_dtype': 'torch.float32',
                        'mask_dtype': 'torch.bool', 'sha256': hashes})
    _require(selected == assets.basis.selected_coordinates, 'Selected-coordinate count changed')
    return {'parameter_names': list(names), 'statistics': assets.basis.statistics(), 'tensors': tensors,
            'ordered_contiguous_byte_sha256': {name: digest.hexdigest() for name, digest in streams.items()},
            'mask_rule': 'abs(original_FP32_backdoor-clean) > fixed_95_percentile', 'cpu_only': True}


def audit_semantic_cpu_basis(assets: CPUAssets) -> dict[str, Any]:
    """Return hashes only after matching the old recorded basis statistics."""
    result = _basis_tensor_audit(assets)
    _require(result['statistics']['threshold'] == .0012139799073338509
             and result['statistics']['selected_coordinates'] == 6153021
             and result['statistics']['quantile'] == .95, 'Original frozen basis statistics do not match')
    result['matches_original_recorded_statistics'] = True
    return result


class SemanticDiagnosticBackend:
    """One state graph at a time, with real functional TE -> UNet gradients.

    budget_callback(event) must durably reserve event['cost'] or raise before
    returning. 'begin' has zero cost and occurs before state/device operations,
    allowing the caller to start its wall clock and write an operation receipt.
    Backward cost is reserved before autograd; tensor hooks count actual visits.
    teacher outputs are detached CPU clones with hashes; student verifies those
    bindings and returns detached CPU clones, never a live computation graph.
    """

    def __init__(self, runtime: SDGradientRuntime, *,
                 budget_callback: Callable[[dict[str, Any]], None] | None = None) -> None:
        _require(isinstance(runtime, SDGradientRuntime), 'Expected SDGradientRuntime or its CPU test subclass')
        _require(budget_callback is None or callable(budget_callback), 'budget_callback must be callable')
        self.runtime, self.budget_callback = runtime, budget_callback
        self._attempted = dict.fromkeys(RESOURCE_KEYS, 0)
        self._actual = dict.fromkeys(RESOURCE_KEYS, 0)
        self._failed = self._busy = False
        self._event_context: dict[str, Any] = {}
        self._handles: list[Any] = []

    def resource_record(self) -> dict[str, Any]:
        """Includes attempted/reserved work even after a failed call; no CUDA query."""
        return {'attempted': deepcopy(self._attempted), 'actual': deepcopy(self._actual),
                'hard_limits': deepcopy(HARD_LIMITS), 'failed': self._failed, 'busy': self._busy}

    def _reserve(self, operation: str, **counts: int) -> None:
        cost = {key: counts.get(key, 0) for key in RESOURCE_KEYS}
        _require(not set(counts) - set(RESOURCE_KEYS), 'Unknown budget dimension')
        _require(all(type(value) is int and value >= 0 for value in cost.values()), 'Invalid resource cost')
        _require(all(self._attempted[key] + cost[key] <= HARD_LIMITS[key] for key in RESOURCE_KEYS),
                 'Semantic diagnostic hard budget exhausted')
        event = {**deepcopy(self._event_context), 'operation': operation, 'cost': deepcopy(cost)}
        if self.budget_callback is not None:
            self.budget_callback(event)
        for key, value in cost.items():
            self._attempted[key] += value
        # Forward/TE/autograd counts describe attempts. Hook visits describe
        # actual backward traversal, independently of the reserved upper bound.
        for key in RESOURCE_KEYS[:3]:
            self._actual[key] += cost[key]

    def _hook(self, value: Tensor, dimension: str) -> None:
        _require(value.requires_grad, 'Student response graph disconnected before ' + dimension)

        def visited(gradient: Tensor) -> None:
            self._actual[dimension] += 1
            _require(self._actual[dimension] <= self._attempted[dimension], 'Unreserved backward visit')

        self._handles.append(value.register_hook(visited))

    def _assert_frozen(self) -> None:
        for model in (self.runtime.text_encoder, self.runtime.unet):
            _require(not model.training, 'Diagnostic weights must remain in eval mode')
            _require(not getattr(model, 'is_gradient_checkpointing', False), 'Checkpoint recomputation is forbidden')
            _require(all(not p.requires_grad and p.grad is None for p in model.parameters()),
                     'Model weights must be frozen with all parameter.grad empty')
        for values in (self.runtime.basis.delta_a, self.runtime.basis.delta_b):
            _require(all(not value.requires_grad and value.grad is None for value in values.values()),
                     'Original delta basis must remain frozen')

    def _binding(self, unit: Mapping[str, Any], condition: Mapping[str, Any]) -> dict[str, Any]:
        _require(unit.get('id') in UNIT_PROMPTS, 'Only the two fixed old fit units are allowed')
        normal, extra = UNIT_PROMPTS[unit['id']]
        _require(unit.get('normal') == normal and unit.get('extra_prompt') == extra, 'Frozen unit prompt mismatch')
        _require(unit.get('triggered') == normal.replace('o', '\u020f'), 'Trigger must replace lowercase o with U+020F')
        _require(unit.get('target') == re.sub(r'\bdog\b', 'cat', normal), 'Target must only replace dog with cat')
        _require(unit.get('denoising_step_1based') == 13 and unit.get('timestep') == 481,
                 'Only the recorded step-13/t481 latent is allowed')
        declared = self.runtime.protocol['merging']['development_normal_states']
        _require(dict(condition) in declared, 'Only frozen development states are allowed; no heldout access')
        upload = condition['id'] == 'upload'
        _require((upload and condition['expert'] is None and condition['alpha_malicious'] == 1.0)
                 or (not upload and condition['expert'] == 'Edev' and condition['alpha_malicious'] in (.08, .25, .50)),
                 'Condition is not one of the four diagnostic states')
        size = self.runtime.unet.config.sample_size
        shape = (1, self.runtime.unet.config.in_channels, size, size)
        hashes = {}
        for name in ('pair_latent', 'extra_latent'):
            value = unit[name]
            _require(isinstance(value, Tensor) and tuple(value.shape) == shape and value.dtype == torch.float32
                     and value.device.type == 'cpu' and not value.requires_grad and value.grad_fn is None,
                     'Latent must be a detached FP32 CPU cache input matching the resident UNet')
            _finite(value, name)
            hashes[name] = _tensor_sha(value)
        alpha_cumprod = float(self.runtime.scheduler.alphas_cumprod[481])
        _require(abs(alpha_cumprod - .302295446395874) <= 1e-8, 'Scheduler t481 alpha_cumprod differs')
        return {'unit_id': unit['id'], 'condition': deepcopy(dict(condition)),
                'prompts': ['', normal, unit['triggered'], extra, unit['target']],
                'timestep': 481, 'denoising_step_1based': 13, 'latent_shape': list(shape),
                'latent_dtype': 'torch.float32', 'latent_sha256': hashes, 'alpha_cumprod': alpha_cumprod}

    def _validate_teacher(self, teacher: Mapping[str, Any], binding: dict[str, Any]) -> dict[str, Tensor]:
        _require(teacher.get('kind') == 'teacher' and teacher.get('binding') == binding,
                 'Teacher does not bind this exact input and state')
        expected = {'normal', 'extra'} if binding['condition']['id'] == 'upload' else {'normal', 'triggered', 'extra', 'target'}
        outputs = teacher['outputs']
        _require(set(outputs) == expected and set(teacher['output_sha256']) == expected, 'Teacher response keys differ')
        for name, value in outputs.items():
            _require(isinstance(value, Tensor) and value.device.type == 'cpu' and value.dtype == torch.float32
                     and tuple(value.shape) == tuple(binding['latent_shape'])
                     and not value.requires_grad and value.grad_fn is None,
                     'Teacher must be detached FP32 CPU output')
            _finite(value, 'teacher ' + name)
            _require(_tensor_sha(value) == teacher['output_sha256'][name], 'Teacher output hash changed')
        return dict(outputs)

    def _responses(self, unit: Mapping[str, Any], condition: Mapping[str, Any],
                   scalars: CalibrationScalars | None, *, teacher: bool, gradients: bool) -> dict[str, Tensor]:
        prompts = ['', unit['normal'], unit['triggered'], unit['extra_prompt'], unit['target']]
        self._reserve('te_batch', te_batch_calls=1)
        embeddings = self.runtime._embeddings(prompts, scalars, float(condition['alpha_malicious']))
        _require(embeddings.ndim == 3 and embeddings.shape[0] == 5, 'TE must return one fixed five-prompt batch')
        _finite(embeddings, 'TE embeddings')
        if gradients:
            self._hook(embeddings, 'te_backward_calls')

        def branch(latent: Tensor, row: int, label: str) -> Tensor:
            self._reserve('unet_' + label, forward_branch_nfe=1)
            value = self.runtime._branch(latent, unit['timestep'], embeddings[row:row + 1])
            _require(tuple(value.shape) == tuple(latent.shape) and value.dtype == torch.float32,
                     'UNet response shape/dtype mismatch')
            _finite(value, label)
            if gradients:
                self._hook(value, 'unet_backward_branch_visits')
            return value

        p0 = branch(unit['pair_latent'], 0, 'pair_unconditional')
        result = {'normal': cfg_prediction(p0, branch(unit['pair_latent'], 1, 'normal'))}
        if condition['id'] != 'upload':
            result['triggered'] = cfg_prediction(p0, branch(unit['pair_latent'], 2, 'triggered'))
            if teacher:
                result['target'] = cfg_prediction(p0, branch(unit['pair_latent'], 4, 'target'))
        q0 = branch(unit['extra_latent'], 0, 'extra_unconditional')
        result['extra'] = cfg_prediction(q0, branch(unit['extra_latent'], 3, 'extra'))
        return result

    def teacher(self, unit: Mapping[str, Any], condition: Mapping[str, Any]) -> dict[str, Any]:
        return self._evaluate(unit, condition, None, None, gradients=False)

    def student(self, unit: Mapping[str, Any], condition: Mapping[str, Any], coefficients: Sequence[float],
                teacher: Mapping[str, Any], gradients: bool = False) -> dict[str, Any]:
        return self._evaluate(unit, condition, coefficients, teacher, gradients=gradients)

    def _evaluate(self, unit: Mapping[str, Any], condition: Mapping[str, Any], coefficients: Sequence[float] | None,
                  teacher: Mapping[str, Any] | None, *, gradients: bool) -> dict[str, Any]:
        _require(not self._failed and not self._busy, 'Backend has failed or already has an active call; no retry')
        _require(not self.runtime._pending_graph, 'Previous state graph must be released before a diagnostic call')
        _require(not torch.is_inference_mode_enabled(), 'Use no_grad, not inference_mode, for fixed responses')
        before = deepcopy(self._actual)
        previous_activity = self.runtime._activity
        self._busy = True
        try:
            self._assert_frozen()
            binding = self._binding(unit, condition)
            is_teacher = coefficients is None
            _require(type(gradients) is bool and (not is_teacher or not gradients), 'Invalid gradient request')
            values = None if is_teacher else tuple(float(value) for value in coefficients)
            _require(is_teacher or (len(values) == 2 and all(math.isfinite(v) for v in values)
                                    and values in ALLOWED_COEFFICIENTS), 'Only the fixed identity, naive and eight FD points are allowed')
            _require(not gradients or values == (1.0, 1.0), 'Only D2 at naive may request gradients')
            reference = None if is_teacher else self._validate_teacher(teacher, binding)
            self._event_context = {'kind': 'teacher' if is_teacher else 'student', 'unit_id': unit['id'],
                                   'condition_id': condition['id'], 'coefficients': values, 'gradients': gradients}
            self._reserve('begin')
            self.runtime._activity = 'target_semantic_diagnostic'
            self.runtime.activate_condition(condition)
            self._assert_frozen()
            self.runtime._pending_graph = gradients
            with torch.enable_grad() if gradients else torch.no_grad():
                scalars = None
                if not is_teacher:
                    scalars = CalibrationScalars('RC-TSSA-GD', device=self.runtime.device)
                    with torch.no_grad():
                        scalars.raw.copy_(torch.tensor(values, dtype=torch.float32, device=self.runtime.device))
                outputs = self._responses(unit, condition, scalars, teacher=is_teacher, gradients=gradients)
                losses, grads = None, None
                if not is_teacher:
                    ref = {name: value.to(self.runtime.device) for name, value in reference.items()}
                    normal = .5 * (outputs['normal'].float() - ref['normal']).square().mean()
                    normal = normal + .5 * (outputs['extra'].float() - ref['extra']).square().mean()
                    attack = None if condition['id'] == 'upload' else (outputs['triggered'].float() - ref['target']).square().mean()
                    terms = [('normal', normal, 4)] if attack is None else [('attack', attack, 2), ('normal', normal, 4)]
                    for name, loss, _ in terms:
                        _finite(loss, name + ' loss')
                    losses = {'attack': None if attack is None else float(attack.detach().cpu()),
                              'normal': float(normal.detach().cpu())}
                    if gradients:
                        grads = {'attack': None, 'normal': None}
                        for index, (name, loss, visits) in enumerate(terms):
                            _require(loss.requires_grad, 'Loss disconnected from coefficients')
                            prior_visits = {key: self._actual[key] for key in RESOURCE_KEYS[3:]}
                            self._reserve('autograd_' + name, autograd_calls=1,
                                          unet_backward_branch_visits=visits, te_backward_calls=1)
                            grad, = torch.autograd.grad(loss * 1024.0, scalars.raw,
                                                       retain_graph=index < len(terms) - 1,
                                                       create_graph=False, allow_unused=False)
                            grad = grad.float() / 1024.0
                            _finite(grad, name + ' gradient')
                            _require(grad.shape == (2,), 'Both scalar derivatives must be returned')
                            _require(self._actual['unet_backward_branch_visits'] - prior_visits['unet_backward_branch_visits'] == visits
                                     and self._actual['te_backward_calls'] - prior_visits['te_backward_calls'] == 1,
                                     'Actual tensor-hook backward traversal differs from the frozen plan')
                            grads[name] = grad.detach().cpu().tolist()
                        _require(scalars.raw.grad is None, 'autograd.grad must not accumulate scalar .grad')
                frozen = {name: value.detach().float().cpu().clone() for name, value in outputs.items()}
                for name, value in frozen.items():
                    _finite(value, 'returned ' + name)
                errors = None if is_teacher else {name: _rms(value - reference[name]) for name, value in frozen.items()}
                signal = _rms(frozen['target'] - frozen['normal']) if is_teacher and 'target' in frozen else None
            self._assert_frozen()
            return {'kind': 'teacher' if is_teacher else 'student', 'binding': binding, 'coefficients': values,
                    'outputs': frozen, 'output_sha256': {name: _tensor_sha(value) for name, value in frozen.items()},
                    'losses': losses, 'gradients': grads, 'output_rms': {name: _rms(value) for name, value in frozen.items()},
                    'errors_vs_teacher': errors, 'signal_rms': signal,
                    'resource_delta': {key: self._actual[key] - before[key] for key in RESOURCE_KEYS}}
        except Exception:
            self._failed = True
            raise
        finally:
            for handle in self._handles:
                handle.remove()
            self._handles.clear()
            self.runtime._pending_graph = False
            self.runtime._activity = previous_activity
            self._event_context = {}
            self._busy = False
