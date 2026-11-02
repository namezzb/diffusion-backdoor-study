"""Prepare a pending-review append-only recovery candidate. No GPU is started.

The original terminal, bundle, T0 and ledgers remain untouched. This candidate
is limited to the single reviewed zero-new-attempt predecessor in the guard.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path

from pilot24_coordinator import stage_contract, write_json
from pilot24_recovery_guard_candidate import MANIFEST, T0_SHA, TERMINAL_SHA, hold_predecessor, _read
from pilot24_worker_ledger import canonical

PREFIX = 'scripts/merging/trigger_contrast_localization/'


def sha(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('ordinary absolute file required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(*, original_bundle, original_config, original_state_sha, repository_root):
    bundle = _read(original_bundle, MANIFEST)
    config_sha = sha(original_config)
    config = _read(original_config, config_sha)
    old_coordinator = Path(config['coordinator_root'])
    old_execution = old_coordinator.parent
    root = Path(repository_root)
    if (not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents))
            or not root.is_dir() or bundle['execution_root'] != str(old_execution)):
        raise ValueError('reviewed repository and original output root required')
    target = old_execution / 'recovery-v1'
    if target.exists() or any(p.is_symlink() for p in target.parents):
        raise ValueError('recovery output already exists or path is unsafe')
    with hold_predecessor(coordinator_root=old_coordinator, original_bundle=original_bundle,
                          original_config=original_config, expected_config_sha=config_sha,
                          expected_state_sha=original_state_sha, expected_bundle_sha=MANIFEST) as prior:
        revised = copy.deepcopy(bundle)
        revised['repository_root'] = str(root)
        revised['review_file'] = str(target / 'frozen' / 'review.json')
        code = dict(revised['code_sha256'])
        code[PREFIX + 'pilot24_recovery_guard_candidate.py'] = ''
        code[PREFIX + 'pilot24_prepare_recovery_candidate.py'] = ''
        for rel in code:
            if Path(rel).is_absolute() or '..' in Path(rel).parts:
                raise ValueError('invalid reviewed source path')
            code[rel] = sha(root / rel)
        revised['code_sha256'] = code
        new_sha = hashlib.sha256((canonical(revised) + '\n').encode()).hexdigest()
        updated = copy.deepcopy(config)
        updated['manifest_sha256'] = new_sha
        updated['coordinator_root'] = str(target / 'coordinator')
        updated['recovery'] = {'original_bundle': str(original_bundle), 'original_config': str(original_config),
            'original_config_sha256': config_sha, 'original_state_sha256': original_state_sha,
            'original_coordinator_root': str(old_coordinator), 'original_t0_sha256': T0_SHA,
            'original_terminal_sha256': TERMINAL_SHA}
        for a in updated['assignments']:
            a['manifest_sha256'] = new_sha
            a['gate_sha256'] = stage_contract(new_sha, a['stage'])
            a['output_root'] = str(target / 'workers' / a['assignment_id'])
        # Directory creation is append-only and must never replace old evidence.
        frozen = target / 'frozen'
        frozen.mkdir(parents=True, exist_ok=False)
        bundle_path = frozen / 'bundle.json'
        config_path = frozen / 'coordinator_config.json'
        if write_json(bundle_path, revised, exclusive=True) != new_sha:
            raise AssertionError('bundle digest changed')
        new_config_sha = write_json(config_path, updated, exclusive=True)
        launch = {}
        for assignment in updated['assignments']:
            worker = assignment['worker_id']
            value = {'server': assignment['server'], 'permission_ref': str(target / 'permissions' / (worker + '.json'))}
            if worker in launch and launch[worker] != value:
                raise ValueError('worker identity changed across assignments')
            launch[worker] = value
        write_json(frozen / 'launch_map.template.json', launch, exclusive=True)
        review = {'run_id': revised['run_id'], 'status': 'pending', 'manifest_sha256': new_sha,
            'coordinator_config_file': str(config_path), 'coordinator_config_sha256': new_config_sha,
            'original_manifest_sha256': MANIFEST, 'original_t0_sha256': T0_SHA,
            'original_terminal_sha256': TERMINAL_SHA, 'reviewer': None,
            'implementer': 'pilot24_prepare_recovery_candidate',
            'limitations': ['Pending independent review and a fresh live GPU permit.',
                'Review must confirm original locks, zero charged work and exact science and budget inheritance.']}
        write_json(frozen / 'review.json', review, exclusive=True)
        for path in (bundle_path, config_path):
            path.chmod(0o444)
        return {'status': 'pending_independent_review', 'bundle': str(bundle_path),
                'bundle_sha256': new_sha, 'config': str(config_path), 'config_sha256': new_config_sha,
                'original_t0_utc': prior['t0_utc'], 'imports': prior['imports'],
                'previous_new_attempts': prior['previous_new_attempts'],
                'max_new_attempts': prior['max_new_attempts'], 'gpu_started': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('original-bundle', 'original-config', 'original-state-sha', 'repository-root'):
        p.add_argument('--' + name, required=True)
    args = p.parse_args()
    print(json.dumps(prepare(original_bundle=args.original_bundle, original_config=args.original_config,
                             original_state_sha=args.original_state_sha, repository_root=args.repository_root), sort_keys=True))

if __name__ == '__main__':
    main()
