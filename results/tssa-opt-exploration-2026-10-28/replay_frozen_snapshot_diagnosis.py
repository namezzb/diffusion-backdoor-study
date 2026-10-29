#!/usr/bin/env python3
"""Replay the unchanged old diagnostic in a temporary frozen root, CPU/local only.

Run: python3 -B results/tssa-opt-exploration-2026-10-28/replay_frozen_snapshot_diagnosis.py
Writes one new report with exclusive creation; no source/evidence is rewritten.
The old strict audit must remain invalid, including its original exact error.
"""
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RELATIVE_HERE = HERE.relative_to(ROOT)
ARCHIVE = HERE / 'frozen_code_before_resource_snapshot_fix'
PLAN_NAME = 'research/tssa_optimization_exploration_2026-10-28.json'
PLAN_SHA = '8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6'
OLD_RUNTIME_SHA = '0008a4fc29ad1e36552069d55232a5480b09d1182953605c2aba09ba57805b3a'
AUDITOR_NAME = 'audit_image_search_results.py'
DIAGNOSTIC_NAME = 'diagnose_summary_record_hash_20261028.py'
SCRIPT_HASHES = {
    AUDITOR_NAME: '2e62bbdc5b837fb4d429e8373a42c6f6d33b0019381d3a6cf63f22b523c566b7',
    DIAGNOSTIC_NAME: '068e9a5560898db2afe981a42fd96fd752d1c0349fe924f2dd5fd882eea90233',
}
BUNDLES = {
    'observation_103_20261028T111524087743Z-7268ad87':
        '8ab09f44f1d0624e46f74b118a969452a65157ef7e23e78e59091f98a47e4289',
    'observation_103_20261028T100953718980Z-b87b404b':
        'c11fc3cf8255546beccfb0c95ee374a1a7836781b48c5b584f176530959efd43',
}
FAILURE_LEDGER = 'recovery/manual-recovery-0e39df5be0cd73d07934fe529fc310cfd651f21d955276fc55b5200615f00c66.ledger.json'
FAILURE_SHA = 'b56a4b6659d7405cda14bc9de35da5a1fb2ef672f177f93547d37b779a9d3c1e'
OLD_DIAGNOSIS_NAME = 'summary_record_hash_diagnosis_20261028.json'
OLD_DIAGNOSIS_SHA = '91f252a70155cd9ea5455418daa723b6845a3dc4adef35655b0b557044ca855a'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run():
    watched = {}

    def read(path, expected=None):
        require(path.is_file() and not path.is_symlink(), 'Expected regular local file: ' + str(path))
        require(path.stat().st_size <= 2 * 1024 * 1024, 'Oversized local metadata: ' + str(path))
        raw = path.read_bytes()
        require(expected is None or sha(raw) == expected, 'Input SHA mismatch: ' + str(path))
        watched[path] = sha(raw)
        return raw

    def copy_to(source, target, expected):
        raw = read(source, expected)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
        require(sha(target.read_bytes()) == expected, 'Temporary copy SHA mismatch')
        return raw

    runtime = ROOT / 'scripts/merging/tssa_sd_runtime.py'
    live_sha = sha(read(runtime))
    require(live_sha != OLD_RUNTIME_SHA, 'Replay expects the future local version to differ from frozen source')
    read(HERE / OLD_DIAGNOSIS_NAME, OLD_DIAGNOSIS_SHA)
    read(HERE / AUDITOR_NAME, SCRIPT_HASHES[AUDITOR_NAME])
    auditor = load(HERE / AUDITOR_NAME, 'replay_path_checks_only')
    plan = auditor.decode(read(ROOT / PLAN_NAME, PLAN_SHA))
    bindings = {
        PLAN_NAME: PLAN_SHA,
        'research/tssa_mvp_2026-10-26.json': plan['old_protocol_sha256'],
        'research/tssa_mvp_assets_2026-10-26.json': plan['asset_manifest_sha256'],
        **{'scripts/merging/' + name: value for name, value in plan['source_hashes'].items()},
    }
    require(bindings['scripts/merging/tssa_sd_runtime.py'] == OLD_RUNTIME_SHA, 'Frozen runtime binding changed')
    bundle_metadata = {}
    with tempfile.TemporaryDirectory(prefix='tssa-frozen-diagnosis-CPU-') as directory:
        temporary_root = Path(directory)
        for name, expected in bindings.items():
            source = ARCHIVE / 'tssa_sd_runtime.py' if name == 'scripts/merging/tssa_sd_runtime.py' else ROOT / name
            copy_to(source, temporary_root / name, expected)
        for name, expected in SCRIPT_HASHES.items():
            copy_to(HERE / name, temporary_root / RELATIVE_HERE / name, expected)
        for name, report_sha in BUNDLES.items():
            source = HERE / name
            destination = temporary_root / RELATIVE_HERE / name
            report = auditor.decode(copy_to(source / 'report.json', destination / 'report.json', report_sha))
            reader = auditor.CopiedFiles(source, report)
            require(len(reader.ledger) <= 1540, 'Observation exceeds frozen small-file count bound')
            total = 0
            for relative, evidence in reader.ledger.items():
                require(PurePosixPath(relative).as_posix() == relative, 'Noncanonical artifact path')
                require(not relative.startswith('run/confirm_') and '/confirm/' not in relative,
                        'Confirmation artifacts are outside this replay')
                require(type(evidence['size']) is int and 0 <= evidence['size'] <= 2 * 1024 * 1024,
                        'Oversized observation artifact')
                total += evidence['size']
                require(total <= 16 * 1024 * 1024, 'Observation exceeds small-artifact byte bound')
                raw = copy_to(reader.path(relative), destination / 'artifacts' / relative, evidence['sha256'])
                require(len(raw) == evidence['size'], 'Declared artifact size mismatch')
            require(reader.ledger[FAILURE_LEDGER]['sha256'] == FAILURE_SHA, 'Failure ledger changed')
            bundle_metadata[name] = {'report_sha256': report_sha, 'files_verified_and_copied': len(reader.ledger),
                                     'artifact_bytes': total, 'failure_ledger_sha256': FAILURE_SHA}
        diagnostic = load(temporary_root / RELATIVE_HERE / DIAGNOSTIC_NAME, 'unchanged_frozen_diagnosis_replay')
        reproduced = diagnostic.run()
        require(reproduced['strict_unchanged_audit']['status'] == 'invalid'
                and reproduced['strict_unchanged_audit']['errors'] == ['search summary.record_sha256.171: mismatch'],
                'Original strict invalid result was not reproduced')
        require(reproduced['total_hash_discrepancies_exactly_explained_by_one_metadata_path'] == 643
                and reproduced['unexplained_hash_discrepancies'] == 0, 'Old defect explanation changed')
    require(all(sha(path.read_bytes()) == expected for path, expected in watched.items()),
            'An original local input changed during replay')
    return {
        'schema_version': 1, 'status': 'old_defect_reproduced_in_isolated_frozen_root_strict_audit_still_invalid',
        'diagnostic_source_sha256': SCRIPT_HASHES[DIAGNOSTIC_NAME], 'replay_source_sha256': sha(Path(__file__).read_bytes()),
        'archived_runtime_sha256': OLD_RUNTIME_SHA, 'live_future_version_runtime_sha256': live_sha,
        'frozen_bindings_verified_in_temporary_root': bindings, 'copied_observation_bundles': bundle_metadata,
        'strict_unchanged_audit': reproduced['strict_unchanged_audit'],
        'explained_hash_discrepancies': reproduced['total_hash_discrepancies_exactly_explained_by_one_metadata_path'],
        'unexplained_hash_discrepancies': reproduced['unexplained_hash_discrepancies'],
        'stage_results': {stage: {
            'record_hash_mismatch_count': data['record_hash_mismatch_count'],
            'completed_receipts_verified': data['completed_receipts_verified'],
            'all_non_record_hash_summary_fields_independently_match': data['all_non_record_hash_summary_fields_independently_match'],
            'independent_selection_matches_original': data['independent_selection_matches_original'],
            'selection': data['selection'],
        } for stage, data in reproduced['stage_diagnosis'].items()},
        'resource_accounting_from_persisted_receipts': reproduced['resource_accounting_from_persisted_receipts'],
        'synthetic_CPU_reproduction': reproduced['synthetic_CPU_reproduction'],
        'original_input_files_verified_unchanged': len(watched), 'temporary_root_deleted': True,
        'original_diagnosis_report_sha256_unchanged': OLD_DIAGNOSIS_SHA,
        'actual_operations': {'network_connections': 0, 'GPU_tasks': 0, 'scientific_images_generated': 0,
                              'original_files_modified': 0},
        'limitations': ['This does not repair the old run or convert its invalid strict audit to a pass.',
                       'Metrics are independently recomputed from existing scores; no model or classifier is rerun.',
                       'PNG integrity is a separate parent acceptance artifact and is not verified here.',
                       'Only the archived old version is replayed; the fixed live source is never substituted into old manifests.'],
    }


if __name__ == '__main__':
    result = run()
    target = HERE / 'frozen_snapshot_diagnosis_replay_20261028.json'
    with target.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'report': str(target), 'sha256': sha(target.read_bytes()), 'status': result['status'],
                      'strict_audit': result['strict_unchanged_audit'],
                      'explained_hash_discrepancies': result['explained_hash_discrepancies'],
                      'original_input_files_verified_unchanged': result['original_input_files_verified_unchanged']},
                     ensure_ascii=False, indent=2))
