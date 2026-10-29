"""Read-only extraction and verification of four existing CPU trajectory caches.

Export runs on the source host with CUDA hidden and writes only a tar to stdout;
verification never loads pickle. Original receipts/binaries remain unchanged.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile

IDS = ('fit_pair_00', 'fit_pair_04', 'fit_extra_00', 'fit_extra_04')
# Raw file hashes are distinct from the canonical identity hash in each receipt.
METADATA = {
    'run_identity.json': '247d164ebc71d8672a069cf3d20398883ddd3592d2fc44d51ba17ff7fe9c4d62',
    'model_file_hashes.json': '96bae0d29dfa0d07403efdeb2026e141abd6667a669b26d1dd7b3d1515389d35',
    'parameter_key_manifest.json': '9aa183d54c9af1db064c4bd053df3e9a1f05d445f98381623286d2c7b20a4731',
    'basis_statistics.json': '85826438f15013385b474a029c5d23c5b34fdf4cb0a5e906e58c8294aa257187',
    'prompt_and_cache_index.json': '5efe174dc6b67625d24805549c3b5766d37fbc2827a0ff5b3b819450824345d0',
}
PROTOCOL_SHA = '8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c'
ASSET_SHA = '881d2d21083d589dcd26e69c977a8048d270d2cb73ddb7bd286e2d4dd9197902'
SOURCE_ROOT = '/data2/zhangzibo/arxiv-tssa/results/mvp-2026-10-28-single-v1'
MAX_FILE = 2 * 1024**2
MAX_TOTAL = 8 * 1024**2


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_read(root, name):
    rel = PurePosixPath(name)
    require(not rel.is_absolute() and '..' not in rel.parts and str(rel) == name, 'Unsafe relative path')
    root = Path(root)
    require(root.resolve() == root, 'Root redirects')
    path = root / name
    for ancestor in [root, *path.parents]:
        if ancestor == root or root in ancestor.parents:
            require(not ancestor.is_symlink() and ancestor.stat().st_uid == os.getuid(), 'Unowned ancestor')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid(), 'Not owned regular file')
        require(before.st_size <= MAX_FILE, 'File size exceeds bound')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            raw = stream.read(MAX_FILE + 1)
        after = os.fstat(fd)
        require(before.st_size == after.st_size == len(raw) <= MAX_FILE and
                before.st_mtime_ns == after.st_mtime_ns, 'File changed during read')
        return raw
    finally:
        os.close(fd)


def validate_raw(raw):
    require(len(raw) == 65536, 'Unexpected latent byte size')
    values = array.array('f')
    require(values.itemsize == 4, 'Unsupported float representation')
    values.frombytes(raw)
    if sys.byteorder != 'little':
        values.byteswap()
    require(all(math.isfinite(v) for v in values), 'Nonfinite latent')


def export_existing(root):
    require(str(root) == SOURCE_ROOT, 'Only the completed source run is allowed')
    require(os.environ.get('CUDA_VISIBLE_DEVICES') == '', 'Export requires CUDA hidden')
    import torch
    require(not torch.cuda.is_initialized(), 'CUDA already initialized')
    torch.set_num_threads(1)
    files = {name: safe_read(root, name) for name in METADATA}
    for name, expected in METADATA.items():
        require(sha(files[name]) == expected, 'Source metadata changed: ' + name)
    identity = json.loads(files['run_identity.json'])
    identity_sha = sha(canonical(identity))
    require(identity['protocol_sha256'] == PROTOCOL_SHA and identity['asset_manifest_sha256'] == ASSET_SHA,
            'Source protocol/asset identity mismatch')
    index = json.loads(files['prompt_and_cache_index.json'])
    require(index['protocol_sha256'] == PROTOCOL_SHA, 'Cache protocol mismatch')
    prompts = {p['id']: p for p in index['prompts']['fit']['pairs'] + index['prompts']['fit']['extra_normal']}
    records = {}
    for uid, seed in zip(IDS, (1000, 1004, 1008, 1012)):
        operation = 'trajectory/' + uid
        stem = sha(canonical(operation))[:32]
        receipt_name, artifact_name = 'operations/' + stem + '.json', 'artifacts/' + stem + '.pt'
        files[receipt_name], files[artifact_name] = safe_read(root, receipt_name), safe_read(root, artifact_name)
        receipt = json.loads(files[receipt_name])
        require(receipt.get('status') == 'completed' and receipt.get('operation') == operation and
                receipt.get('run_identity_sha256') == identity_sha and
                receipt.get('artifact_sha256') == sha(files[artifact_name]), 'Invalid completed receipt: ' + uid)
        envelope = torch.load(io.BytesIO(files[artifact_name]), map_location='cpu', weights_only=True)
        require(envelope['operation'] == operation and envelope['run_identity_sha256'] == identity_sha,
                'Binary envelope mismatch')
        payload, prompt = envelope['payload'], prompts[uid]
        source = 'backdoor_triggered' if uid == 'fit_pair_04' else 'clean_normal'
        require(payload['prompt_id'] == uid and payload['seed'] == prompt['trajectory_seed'] == seed and
                payload['trajectory_source'] == prompt['trajectory_source'] == source, 'Trajectory source mismatch')
        if 'triggered' in prompt:
            require(prompt['triggered'] == prompt['normal'].replace('o', '\u020f'), 'Trigger codepoints differ')
        snap = payload['snapshots'][13]
        expected = {'actual_timestep': 481, 'denoising_step_1based': 13,
                    'alpha_cumprod': 0.302295446395874, 'noise_level': 1.5192175757334878, 'seed': seed}
        require({k: snap[k] for k in expected} == expected, 'Not the frozen legal step13 input')
        require({k: index['trajectories'][uid]['snapshots']['13'][k] for k in expected} == expected,
                'Index and binary snapshot differ')
        tensor = snap['latent']
        require(type(tensor) is torch.Tensor and tensor.device.type == 'cpu' and tensor.dtype == torch.float32
                and tuple(tensor.shape) == (1, 4, 64, 64) and not tensor.requires_grad, 'Invalid latent tensor')
        raw = tensor.contiguous().numpy().astype('<f4', copy=False).tobytes(order='C')
        validate_raw(raw)
        tensor_name = 'latents/' + uid + '_s13.f32'
        files[tensor_name] = raw
        records[uid] = {**expected, 'trajectory_source': source, 'prompt': prompt,
                        'operation': operation, 'receipt': receipt_name, 'artifact': artifact_name,
                        'tensor': tensor_name, 'tensor_sha256': sha(raw), 'shape': [1, 4, 64, 64],
                        'dtype': 'float32_little_endian'}
    require(not torch.cuda.is_initialized(), 'CPU extraction initialized CUDA')
    audit = {'schema_version': 1, 'status': 'verified', 'source_root': str(root),
             'source_run_identity_sha256': identity_sha, 'protocol_sha256': PROTOCOL_SHA,
             'cuda_initialized': False, 'model_calls': 0, 'new_trajectories': 0, 'cache': records,
             'files': {n: {'sha256': sha(raw), 'size': len(raw)} for n, raw in files.items()}}
    files['cache_audit.json'] = canonical(audit)
    require(sum(map(len, files.values())) <= MAX_TOTAL, 'Archive exceeds bound')
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
        for name, raw in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(raw), 0o600, 0
            archive.addfile(info, io.BytesIO(raw))


def verify_folder(folder):
    folder = Path(folder).resolve()
    audit = json.loads(safe_read(folder, 'cache_audit.json'))
    require(audit['status'] == 'verified' and audit['source_root'] == SOURCE_ROOT and
            set(audit['cache']) == set(IDS), 'Invalid cache audit')
    for name, entry in audit['files'].items():
        raw = safe_read(folder, name)
        require(sha(raw) == entry['sha256'] and len(raw) == entry['size'], 'Cache file mismatch: ' + name)
    for name, expected in METADATA.items():
        require(audit['files'][name]['sha256'] == expected, 'Unbound source metadata')
    identity = json.loads(safe_read(folder, 'run_identity.json'))
    require(sha(canonical(identity)) == audit['source_run_identity_sha256'], 'Source identity mismatch')
    require(identity['protocol_sha256'] == audit['protocol_sha256'] == PROTOCOL_SHA and
            identity['asset_manifest_sha256'] == ASSET_SHA, 'Protocol binding mismatch')
    index = json.loads(safe_read(folder, 'prompt_and_cache_index.json'))
    prompts = {p['id']: p for p in index['prompts']['fit']['pairs'] + index['prompts']['fit']['extra_normal']}
    expected_files = set(METADATA)
    for uid, seed in zip(IDS, (1000, 1004, 1008, 1012)):
        entry = audit['cache'][uid]
        operation = 'trajectory/' + uid
        stem = sha(canonical(operation))[:32]
        fixed = {'operation': operation, 'receipt': 'operations/' + stem + '.json',
                 'artifact': 'artifacts/' + stem + '.pt', 'tensor': 'latents/' + uid + '_s13.f32',
                 'actual_timestep': 481, 'denoising_step_1based': 13, 'seed': seed,
                 'alpha_cumprod': 0.302295446395874, 'noise_level': 1.5192175757334878,
                 'trajectory_source': 'backdoor_triggered' if uid == 'fit_pair_04' else 'clean_normal',
                 'prompt': prompts[uid], 'shape': [1, 4, 64, 64], 'dtype': 'float32_little_endian'}
        require({k: entry.get(k) for k in fixed} == fixed, 'Cached unit metadata changed')
        expected_files.update((entry['receipt'], entry['artifact'], entry['tensor']))
        raw = safe_read(folder, entry['tensor'])
        validate_raw(raw)
        require(sha(raw) == entry['tensor_sha256'], 'Tensor hash mismatch')
        receipt = json.loads(safe_read(folder, entry['receipt']))
        require(receipt['status'] == 'completed' and receipt['operation'] == entry['operation'] and
                receipt['run_identity_sha256'] == audit['source_run_identity_sha256'] and
                receipt['artifact_sha256'] == audit['files'][entry['artifact']]['sha256'], 'Receipt link mismatch')
    require(set(audit['files']) == expected_files, 'Cache file domain differs')
    return audit


def verify_tensor_derivation(folder, audit):
    """Independently compare the raw tensors with their hash-bound CPU envelopes."""
    import torch
    folder = Path(folder).resolve()
    require(not torch.cuda.is_initialized(), 'Tensor verification must be CPU-only')
    for uid in IDS:
        entry = audit['cache'][uid]
        envelope = torch.load(io.BytesIO(safe_read(folder, entry['artifact'])),
                              map_location='cpu', weights_only=True)
        require(envelope['operation'] == entry['operation'] and
                envelope['run_identity_sha256'] == audit['source_run_identity_sha256'], 'Envelope binding differs')
        payload = envelope['payload']
        require(payload['prompt_id'] == uid and payload['seed'] == entry['seed'] and
                payload['trajectory_source'] == entry['trajectory_source'], 'Envelope trajectory differs')
        snap = payload['snapshots'][13]
        require(all(snap[k] == entry[k] for k in ('seed', 'actual_timestep', 'denoising_step_1based',
                                                'alpha_cumprod', 'noise_level')), 'Envelope timestep differs')
        tensor = snap['latent']
        require(tensor.device.type == 'cpu' and tensor.dtype == torch.float32 and
                list(tensor.shape) == entry['shape'] and not tensor.requires_grad, 'Envelope tensor differs')
        raw = tensor.contiguous().numpy().astype('<f4', copy=False).tobytes(order='C')
        require(raw == safe_read(folder, entry['tensor']), 'Extracted tensor does not match original artifact')
    require(not torch.cuda.is_initialized(), 'CPU verification initialized CUDA')
    return {'source_envelopes_checked': 4, 'raw_tensors_equal': 4, 'cuda_initialized': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--export-existing')
    action.add_argument('--verify-folder')
    args = parser.parse_args()
    if args.export_existing:
        export_existing(args.export_existing)
    else:
        verified = verify_folder(args.verify_folder)
        print(json.dumps({'status': verified['status'], 'latents': len(verified['cache']),
                          'source_run_identity_sha256': verified['source_run_identity_sha256']}))
