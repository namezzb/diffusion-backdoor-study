"""CPU-only preparation of a reviewed pilot24 run; no CUDA, SSH or permits.

Run on the intended server after creating and authenticating a separate source
snapshot. ``--request`` is JSON with repository_root, models_root,
execution_root, source_isolation={path,sha256}, and workers=[{worker_id,server,
gpu_uuid}]. Optional input_overrides maps a default input name to an absolute
path. Generated review.json remains pending and cannot launch a run.

The source proof owns the import decision. R=0 requires its explicit reason;
this tool never silently drops the 363 historical candidate images.
The separately constructed source proof must provide parent_manifest/context_ids
references and immutable copy roles selection, localization_terminal,
localization_ledger and mask:<version> for all eight versions. Its output_root
must equal execution_root, with snapshot_root and old run roots disjoint.
No source copying or proof construction is performed by this entrypoint.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from pilot24_coordinator import STAGES, stage_contract, validate_partition, write_json
from pilot24_inputs import RUN, balanced_chunks, frozen_units
from pilot24_worker_ledger import canonical, digest, is_sha

TASK = 'research/tasks/2026-10-29-trigger-contrast-localization/'
CODE = 'scripts/merging/trigger_contrast_localization/'


def ordinary_path(value, *, directory=False, must_exist=True):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('absolute path without symlink ancestry required: ' + str(path))
    if must_exist and not (path.is_dir() if directory else path.is_file()):
        raise ValueError('required ordinary path missing: ' + str(path))
    return path


def sha_file(path):
    path = ordinary_path(path)
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def reference(path):
    path = ordinary_path(path)
    return {'path': str(path), 'sha256': sha_file(path)}


def _workers(workers):
    if not isinstance(workers, list) or not 1 <= len(workers) <= 4:
        raise ValueError('one to four explicitly selected workers required')
    result = []
    for worker in workers:
        if (not isinstance(worker, dict) or set(worker) != {'worker_id', 'server', 'gpu_uuid'}
                or not isinstance(worker['worker_id'], str)
                or re.fullmatch(r'[A-Za-z0-9_-]+', worker['worker_id']) is None
                or not isinstance(worker['server'], str) or not worker['server']
                or not isinstance(worker['gpu_uuid'], str)
                or re.fullmatch(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', worker['gpu_uuid']) is None):
            raise ValueError('safe worker ID, server and full GPU UUID required')
        result.append(dict(worker))
    if (len({w['worker_id'] for w in result}) != len(result)
            or len({w['gpu_uuid'].lower() for w in result}) != len(result)):
        raise ValueError('worker IDs and GPU UUIDs must be unique')
    if len({w['server'] for w in result}) != 1:
        raise ValueError('this preparation entrypoint supports one server; cross-node transport requires a separate reviewed plan')
    return sorted(result, key=lambda w: w['worker_id'])


def build_configuration(stages, bindings, workers, imports, manifest_sha, execution_root,
                        model_bundle_sha, scorer_sha):
    """Deterministic balanced finite assignments; caller authenticates imports."""
    workers = _workers(workers)
    root = ordinary_path(execution_root, directory=True, must_exist=False)
    if any(not is_sha(x) for x in (manifest_sha, model_bundle_sha, scorer_sha)):
        raise ValueError('frozen model, scorer and bundle identities required')
    expected = {tuple(key) for keys in stages.values() for key in keys}
    imported = [tuple(row['key']) for row in imports]
    if len(set(imported)) != len(imported) or not set(imported) <= expected:
        raise ValueError('duplicate or out-of-protocol imported key')
    imported = set(imported)
    units = []
    labels = {'source': {}, 'merge': {}}
    for stage in STAGES:
        for key in stages[stage]:
            key = tuple(key)
            _, state, version, category, context, _ = key
            token = (state, context, category)
            units.append({'key': list(key), 'input_sha': bindings.input_hashes[token],
                          'mask_sha': bindings.mask_hashes[version]})
            labels[state].setdefault(context, {})[category] = list(bindings.labels[token])
    by_key = {tuple(row['key']): row for row in units}
    for record in imports:
        bound = by_key[tuple(record['key'])]
        if (any(record.get(name) != bound[name] for name in ('input_sha', 'mask_sha'))
                or record.get('model_bundle_sha256') != model_bundle_sha
                or record.get('scorer_sha256') != scorer_sha):
            raise ValueError('imported key has different frozen input, mask, model or scorer')
    assignments = []
    for stage, chunks in balanced_chunks(stages).items():
        for index, keys in enumerate(chunks):
            remaining = [by_key[tuple(key)] for key in keys if tuple(key) not in imported]
            if not remaining:
                continue
            worker = workers[index % len(workers)]
            aid = stage + '-' + str(index).zfill(2) + '-' + worker['worker_id']
            assignments.append({'run_id': RUN, 'manifest_sha256': manifest_sha,
                'assignment_id': aid, 'stage': stage, **worker,
                'output_root': str(root / 'workers' / aid), 'retry_tokens': 0,
                'units': remaining, 'gate_sha256': stage_contract(manifest_sha, stage)})
    # Retry tokens are a finite state budget. Each key can receive at most one,
    # so scarce remaining keys never cause unusable tokens to be overallocated.
    for prefix in ('S', 'M'):
        chosen = [a for a in assignments if a['stage'].startswith(prefix)]
        remaining = min(64, sum(len(a['units']) for a in chosen))
        while remaining:
            for assignment in chosen:
                if assignment['retry_tokens'] < len(assignment['units']):
                    assignment['retry_tokens'] += 1
                    remaining -= 1
                    if not remaining:
                        break
    validate_partition(stages, assignments, [row['key'] for row in imports])
    return {'run_id': RUN, 'manifest_sha256': manifest_sha,
        'coordinator_root': str(root / 'coordinator'), 'model_bundle_sha256': model_bundle_sha,
        'scorer_sha256': scorer_sha, 'stages': {s: [list(k) for k in stages[s]] for s in STAGES},
        'units': units, 'labels': labels, 'imports': imports, 'assignments': assignments}


def _source_inputs(root, proof):
    values = {
        'plan': root / TASK / 'pilot24_plan_candidate.json',
        'context_ids': proof['context_ids']['path'],
        'parent_manifest': proof['parent_manifest']['path'],
        'prompts': root / TASK / 'prompts_tokenized_candidate.jsonl',
        'parent_review': root / TASK / 'm06_review.json',
        'context_review': root / TASK / 'context_review.json',
        'protocol': root / 'research/tssa_mvp_2026-10-26.json',
        'asset_manifest': root / 'research/tssa_mvp_assets_2026-10-26.json',
        'pilot24_protocol': root / TASK / 'PILOT24_PROTOCOL_2026-11-02.md',
    }
    for role in ('selection', 'localization_terminal', 'localization_ledger'):
        copies = [item for item in proof['copies'] if item['role'] == role]
        if len(copies) != 1:
            raise ValueError('exactly one copied ' + role + ' required')
        values[role] = copies[0]['path']
    return values


def imported_records(proof, model_sha, scorer_sha):
    """Translate authenticated source records without inventing provenance."""
    if (proof['imports'] and (proof['freeze'].get('model_bundle_sha256') != model_sha
            or proof['freeze'].get('scorer_sha256') != scorer_sha)):
        raise ValueError('source import freeze identifies another model/scorer')
    result = []
    for row in proof['imports']:
        if row.get('model_bundle_sha256') != model_sha or row.get('scorer_sha256') != scorer_sha:
            raise ValueError('imported model/scorer identity differs from the frozen bundle')
        result.append({'key': row['key'], 'input_sha': row['input_sha256'], 'mask_sha': row['mask_sha256'],
            'image_path': row['image']['path'], 'image_sha': row['image']['sha256'], 'scores': row['scores'],
            'model_bundle_sha256': row['model_bundle_sha256'], 'scorer_sha256': row['scorer_sha256'],
            'provenance_import': {'origin_key': row['origin_key'], 'origin_attempt': row['origin_attempt'],
                                  'ledger': row['ledger']}})
    return result


def historical_lineage(proof, stages):
    """Bind observed legacy attempts by key without claiming snapshot completeness."""
    ref = proof['historical_reconciliation']
    observed = json.loads(ordinary_path(ref['path']).read_text())
    expected = {tuple(key) for rows in stages.values() for key in rows}
    records = []
    for index, row in enumerate(observed['records']):
        origin = row['key']
        if len(origin) != 6 or origin[0] != 'tcl-20261029-01-v1':
            raise ValueError('invalid historical key')
        key = (RUN, *origin[1:])
        if key not in expected:
            continue
        source_sha = observed['logical_source_sha256'].get(row['source'])
        if not is_sha(source_sha) or row['table'] not in ('attempts', 'attempt_history'):
            raise ValueError('historical attempt lacks source identity')
        records.append({'key': list(key), 'origin_key': origin, 'source': row['source'],
                        'source_ledger_sha256': source_sha, 'table': row['table'],
                        'observed_status': row['status'], 'record_index': index})
    return {'evidence': ref, 'status': observed['status'],
            'observed_charged_attempts_lower_bound': observed['charged_attempts'],
            'later_legacy_consumption': 'unknown', 'records': records}


def prepare(request):
    """Write immutable candidates only after CPU input and source verification."""
    from bindings import load_frozen_bindings
    from pilot24_provenance import validate_source_isolation
    from pilot24_runtime import REQUIRED_V2_CODE
    from preflight import load_plan

    root = ordinary_path(request['repository_root'], directory=True)
    if Path(__file__).resolve() != root / CODE / 'pilot24_prepare.py':
        raise ValueError('preparation must execute from the intended reviewed repository')
    models = ordinary_path(request['models_root'], directory=True)
    execution = ordinary_path(request['execution_root'], directory=True, must_exist=False)
    workers = _workers(request['workers'])
    isolation = request['source_isolation']
    if not isinstance(isolation, dict) or set(isolation) != {'path', 'sha256'}:
        raise ValueError('explicit source isolation path and hash required')
    proof = validate_source_isolation(isolation['path'], isolation['sha256'], output_root=str(execution))
    if Path(proof['output_root']) != execution:
        raise ValueError('preparation root must match isolated v2 root')
    inputs = _source_inputs(root, proof)
    overrides = request.get('input_overrides', {})
    if not isinstance(overrides, dict) or not set(overrides) <= set(inputs):
        raise ValueError('unknown input override')
    protected = {'parent_manifest', 'context_ids', 'selection', 'localization_terminal', 'localization_ledger'}
    if set(overrides) & protected:
        raise ValueError('source proof owns parent, context and snapshot paths')
    inputs.update(overrides)
    refs = {name: reference(path) for name, path in inputs.items()}
    refs['source_isolation'] = dict(isolation)
    for name in ('parent_manifest', 'context_ids'):
        if refs[name] != proof[name]:
            raise ValueError('source proof input changed')
    parent = json.loads(Path(inputs['parent_manifest']).read_text())
    load_plan(inputs['parent_manifest'], inputs['prompts'], inputs['context_review'], inputs['parent_review'], root)
    bindings = load_frozen_bindings(inputs['parent_manifest'], inputs['prompts'], inputs['parent_review'], inputs['selection'], root)
    stages = frozen_units(inputs['plan'], inputs['context_ids'], inputs['parent_manifest'], inputs['prompts'])
    if (refs['protocol']['sha256'] != parent['source_protocol_sha256']
            or refs['asset_manifest']['sha256'] != parent['source_asset_manifest_sha256']):
        raise ValueError('original asset-loader protocol changed')
    sources = dict(parent['code_sha256'])
    for name in REQUIRED_V2_CODE | {CODE + 'pilot24_prepare.py'}:
        sources[name] = sha_file(root / name)
    for name, expected in parent['code_sha256'].items():
        if sha_file(root / name) != expected:
            raise ValueError('frozen v1 implementation changed: ' + name)
    scorer_device = request.get('scorer_device', 'cpu')
    if scorer_device not in ('cpu', 'cuda'):
        raise ValueError('scorer_device must be cpu or cuda on the assigned GPU')
    cpu_threads = request.get('cpu_threads_per_worker', 4)
    if type(cpu_threads) is not int or not 1 <= cpu_threads <= 64:
        raise ValueError('cpu_threads_per_worker must be an integer from 1 to 64')
    model_sha = digest(dict(bindings.asset_hashes))
    scorer_sha = digest({'assets': {n: s for n, s in bindings.asset_hashes.items() if n.split('/')[0] in ('vit', 'clip')},
        'code': {n: sources[n] for n in ('scripts/merging/tssa_mvp_score.py', 'scripts/merging/tssa_sd_runtime.py')},
        'dtype': 'float32', 'device': scorer_device, 'image_source': 'saved_rgb_png',
        'score_prompt': 'untriggered_paired_prompt'})
    imports = imported_records(proof, model_sha, scorer_sha)
    if not imports and not proof['freeze'].get('no_reuse_reason', '').strip():
        raise ValueError('R=0 requires an explicit no-reuse decision')
    frozen = execution / 'frozen'
    review_file, bundle_file = frozen / 'review.json', frozen / 'bundle.json'
    config_file = frozen / 'coordinator_config.json'
    if frozen.exists():
        raise ValueError('frozen output already exists; never replace a prepared run')
    bundle = {'schema_version': 1, 'run_id': RUN, 'status': 'frozen',
        'repository_root': str(root), 'models_root': str(models), 'review_file': str(review_file),
        'execution_root': str(execution), 'inputs': refs, 'code_sha256': sources,
        'scorer_device': scorer_device, 'cpu_threads_per_worker': cpu_threads}
    manifest_sha = hashlib.sha256((canonical(bundle) + '\n').encode()).hexdigest()
    config = build_configuration(stages, bindings, workers, imports, manifest_sha, execution, model_sha, scorer_sha)
    config['historical_lineage'] = historical_lineage(proof, stages)
    # Recheck the proof immediately before publishing frozen references.
    validate_source_isolation(isolation['path'], isolation['sha256'], output_root=str(execution))
    frozen.mkdir(parents=True, exist_ok=False)
    actual_bundle_sha = write_json(bundle_file, bundle, exclusive=True)
    if actual_bundle_sha != manifest_sha:
        raise AssertionError('unexpected canonical bundle serialization')
    config_sha = write_json(config_file, config, exclusive=True)
    review = {'status': 'pending', 'run_id': RUN, 'manifest_sha256': manifest_sha,
        'coordinator_config_file': str(config_file), 'coordinator_config_sha256': config_sha,
        'reviewer': None, 'implementer': 'pilot24_prepare',
        'limitations': ['Preparation does not approve implementation or grant GPU permission.',
                       'Model files still require the runtime CPU asset verification before CUDA.']}
    write_json(review_file, review, exclusive=True)
    launch = {w['worker_id']: {'server': w['server'],
        'permission_ref': str(execution / 'permissions' / (w['worker_id'] + '.json'))} for w in workers}
    write_json(frozen / 'launch_map.template.json', launch, exclusive=True)
    coverage = Counter(row['key'][1] for row in imports)
    report = {'status': 'prepared_pending_independent_review', 'run_id': RUN,
        'bundle': reference(bundle_file), 'coordinator_config': reference(config_file),
        'review_file': str(review_file), 'worker_count': len(workers), 'assignments': len(config['assignments']),
        'unique_target': 6144, 'verified_imports': len(imports), 'imported_by_state': dict(coverage),
        'new_attempt_limit': 6272 - len(imports), 'model_files_rehashed': False,
        'gpu_started': False, 't0': None}
    write_json(frozen / 'preparation_report.json', report, exclusive=True)
    for path in (bundle_file, config_file, frozen / 'preparation_report.json'):
        path.chmod(0o444)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, help='absolute path to the CPU preparation request JSON')
    args = parser.parse_args(argv)
    request = json.loads(ordinary_path(args.request).read_text())
    print(json.dumps(prepare(request), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
