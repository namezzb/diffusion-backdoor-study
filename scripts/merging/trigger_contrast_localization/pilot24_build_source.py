"""Build an auditable v2 source package from actual local files; never starts CUDA.

Pass --request an absolute JSON path. The request names an existing reviewed
repository_root, source_run_root, source_server, new package_root, v2
output_root, old_output_roots, legacy_launch_records, candidates_file and
candidate_sources. Each candidate_sources entry is either {exclude_reason} or
{server, ledger, image_root, recorded_image_root}; the latter allows a verified
copy transferred from another machine to stand in for the recorded location.
An empty import set additionally requires no_reuse_reason. No result selection
based on scores is allowed: every candidate from an included source is checked.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

from pilot24_inputs import RUN, PARENT, VERSIONS
import pilot24_provenance as verifier

TASK = 'research/tasks/2026-10-29-trigger-contrast-localization'
CANDIDATES_SHA256 = '666ef2f5c59ab481e3d6d4457176b7e48d7d45674be1a43000b1e05bcb218e52'
CANDIDATE_COUNT = 363
RECONCILIATION_SHA256 = 'c79e26582268a4349a74059051127165443203d5116a9b0d47513b1e1092423b'


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def path(value):
    return verifier._path(value)


def sha_file(filename):
    return verifier._file(filename, contents=False)[1]


def ref(filename):
    return {'path': str(path(filename)), 'sha256': sha_file(filename)}


def write_json(filename, value):
    filename = path(filename)
    with filename.open('x', encoding='utf-8') as out:
        json.dump(value, out, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        out.write('\n')
    return ref(filename)


def copy_verified(src, dst, expected=None):
    src, dst = path(src), path(dst)
    # Authentication before and after copying detects replacement and mutation.
    before = src.stat()
    digest = sha_file(src)
    if expected is not None and digest != expected:
        raise ValueError('source digest differs: ' + str(src))
    dst.parent.mkdir(parents=True, exist_ok=True)
    with src.open('rb') as inp, dst.open('xb') as out:
        shutil.copyfileobj(inp, out, length=1024 * 1024)
    if verifier._identity(before) != verifier._identity(src.stat()) or sha_file(dst) != digest:
        raise ValueError('source changed while copying: ' + str(src))
    dst.chmod(0o444)
    return digest


def observation(src):
    result = {}
    for suffix in ('', '-wal', '-shm', '-journal'):
        item = Path(str(src) + suffix)
        if item.exists():
            item = path(item)
            result[suffix or 'main'] = {'path': str(item), 'sha256': sha_file(item), 'bytes': item.stat().st_size}
    return result


def sqlite_backup(src, staging, evidence):
    src, staging = path(src), path(staging)
    before, started = observation(src), timestamp()
    if staging.exists():
        raise ValueError('backup destination already exists')
    # The backup API takes a consistent SQLite snapshot, including committed WAL.
    # The independently measured original bytes need not match backup bytes.
    with closing(sqlite3.connect(src.as_uri() + '?mode=ro', uri=True, timeout=30)) as source:
        with closing(sqlite3.connect(staging)) as target:
            source.backup(target)
            if target.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError('SQLite backup quick_check failed')
            # A source in WAL mode can transfer that mode to the backup. Make
            # the private destination self-contained before closing it.
            target.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            if target.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower() != 'delete':
                raise ValueError('could not make backup a standalone database')
    after = observation(src)
    for suffix in ('-wal', '-shm', '-journal'):
        if Path(str(staging) + suffix).exists():
            raise ValueError('backup has a SQLite sidecar')
    staging.chmod(0o444)
    evidence.append({'method': 'sqlite3.Connection.backup', 'started_at_utc': started,
                     'finished_at_utc': timestamp(), 'original_before': before,
                     'original_after': after, 'consistent_backup': ref(staging),
                     'note': 'Original observations are byte hashes, not a claim of equality to the logical backup.'})
    return staging


def build(request):
    root, source = path(request['repository_root']), path(request['source_run_root'])
    package, output = path(request['package_root']), path(request['output_root'])
    if not root.is_dir() or not source.is_dir() or package.exists():
        raise ValueError('existing repository and source, and a new package directory, required')
    if (output.name != RUN or not verifier._disjoint(package, output)
            or not verifier._disjoint(package, source) or not verifier._disjoint(output, source)):
        raise ValueError('package, source and v2 output must be disjoint')
    if any(not verifier._disjoint(package, path(r['path'])) or not verifier._disjoint(output, path(r['path']))
           for r in request['old_output_roots']):
        raise ValueError('old and new roots overlap')
    parent_path = root / TASK / 'manifest_candidate.json'
    ids_path = root / TASK / 'pilot24_context_ids.json'
    parent = json.loads(parent_path.read_text())
    if sha_file(parent_path) != verifier.PARENT_MANIFEST_SHA256 or parent['run_id'] != PARENT:
        raise ValueError('parent manifest differs')
    launches = [ref(p) for p in request['legacy_launch_records']]
    if not launches:
        raise ValueError('actual historical launch evidence required')
    launch_docs = [json.loads(Path(r['path']).read_text()) for r in launches]
    uuids = sorted({x['gpu_uuid'] for x in launch_docs})
    if any(x.get('run_id') != PARENT or x.get('manifest_sha256') != verifier.PARENT_MANIFEST_SHA256
           for x in launch_docs):
        raise ValueError('historical launch records do not bind the parent run')
    if not request.get('legacy_upper_bound_basis', '').strip():
        raise ValueError('explicit evidence-based occupancy upper-bound rationale required')

    candidate_path = path(request['candidates_file'])
    if sha_file(candidate_path) != CANDIDATES_SHA256:
        raise ValueError('candidate file differs from the fixed 363-unit intersection')
    candidate_doc = json.loads(candidate_path.read_text())
    if candidate_doc.get('run_id') != RUN or candidate_doc.get('status') != 'provisional_not_imported':
        raise ValueError('expected frozen v2 historical candidate list')
    records = candidate_doc['records']
    if candidate_doc.get('candidate_count') != CANDIDATE_COUNT or len(records) != CANDIDATE_COUNT:
        raise ValueError('candidate count differs')
    source_specs = request['candidate_sources']
    if set(source_specs) != {r['source'] for r in records}:
        raise ValueError('each candidate source requires inclusion or a concrete exclusion reason')
    for spec in source_specs.values():
        if 'exclude_reason' in spec:
            if set(spec) != {'exclude_reason'} or not spec['exclude_reason'].strip():
                raise ValueError('excluded source requires a concrete reason')
        elif not {'server', 'ledger', 'image_root', 'recorded_image_root'} <= set(spec) or set(spec) - {'server', 'ledger', 'image_root', 'recorded_image_root', 'transport_receipt'}:
            raise ValueError('included source requires server, ledger and image paths')

    package.mkdir(parents=True, exist_ok=False)
    snapshot, staging = package / 'snapshot', package / 'sqlite_backups'
    snapshot.mkdir()
    staging.mkdir()
    copies, backups = [], []

    def add(role, origin, destination, server, expected=None):
        digest = copy_verified(origin, destination, expected)
        entry = {'role': role, 'path': str(destination), 'sha256': digest,
                 'origin': {'server': server, 'path': str(origin), 'sha256': digest}}
        copies.append(entry)
        return {'path': str(destination), 'sha256': digest}

    server = request['source_server']
    selection_source = source / 'selection/selection.json'
    selection = json.loads(selection_source.read_text())
    add('selection', selection_source, snapshot / 'selection/selection.json', server)
    add('localization_terminal', source / 'localization_terminal.json', snapshot / 'localization_terminal.json', server)
    for version in VERSIONS:
        relative = Path(selection['mask_files'][version])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('mask reference escapes selection directory')
        add('mask:' + version, selection_source.parent / relative, snapshot / 'selection' / relative,
            server, selection['mask_sha256'][version])
    local_backup = sqlite_backup(source / 'localization.sqlite', staging / 'localization.sqlite', backups)
    add('localization_ledger', local_backup, snapshot / 'localization.sqlite', server)

    generation, transports = {}, {}
    for index, (name, spec) in enumerate(sorted(source_specs.items())):
        if 'exclude_reason' in spec:
            continue
        observed = candidate_doc['observations'][name]['ledger_sha256']
        local_sha = sha_file(spec['ledger'])
        receipt_path = spec.get('transport_receipt')
        if receipt_path:
            receipt_ref = ref(receipt_path)
            receipt = json.loads(Path(receipt_ref['path']).read_text())
            if (receipt.get('source_ledger_sha256') != observed
                    or receipt.get('source_consistent_backup_sha256') != local_sha
                    or receipt.get('destination_consistent_backup_sha256') != local_sha
                    or receipt.get('destination_server') != spec['server']
                    or not receipt.get('source_server') or not isinstance(receipt.get('images'), dict)):
                raise ValueError('transport receipt does not bind original and transferred ledger')
            original_ref = {'path': receipt.get('source_evidence_path'),
                            'sha256': receipt.get('source_evidence_sha256')}
            original = json.loads(verifier._ref(original_ref))
            recorded_root = path(spec['recorded_image_root'])
            expected = {}
            for candidate in records:
                if candidate['source'] != name:
                    continue
                image_path = path(candidate['image_path'])
                relative = image_path.relative_to(recorded_root)
                if str(relative) in expected:
                    raise ValueError('duplicate candidate image path')
                expected[str(relative)] = (str(image_path), candidate['image_sha'], candidate['bytes'])
            source_images = original.get('images')
            if (original.get('server') != receipt['source_server']
                    or original.get('original_ledger') != str(recorded_root.parent / 'images.sqlite')
                    or original.get('original_sha256_before_after') != observed
                    or original.get('sqlite_backup_sha256') != local_sha
                    or original.get('sqlite_quick_check') != 'ok'
                    or not isinstance(original.get('wal_sha256_before_after'), str)
                    or not verifier.SHA_RE.fullmatch(original['wal_sha256_before_after'])
                    or not isinstance(source_images, list)
                    or original.get('candidate_count') != len(expected)
                    or len(source_images) != len(expected)):
                raise ValueError('original transfer evidence does not bind source ledger or candidate count')
            seen = set()
            for image in source_images:
                copied = image.get('copied')
                if not isinstance(copied, str) or not copied.startswith('images/'):
                    raise ValueError('invalid source transfer image path')
                relative = copied[len('images/'):]
                if (relative in seen or relative not in expected
                        or (image.get('origin'), image.get('sha256'), image.get('bytes')) != expected[relative]):
                    raise ValueError('original transfer evidence differs from frozen image mapping')
                seen.add(relative)
            if receipt['images'] != {key: value[1] for key, value in expected.items()}:
                raise ValueError('verified transfer receipt differs from frozen image mapping')
            transports[name] = {'ref': receipt_ref, 'receipt': receipt, 'source_evidence': original_ref}
        elif local_sha != observed or path(spec['image_root']) != path(spec['recorded_image_root']):
            raise ValueError('changed or transferred historical source requires a transfer receipt')
        backed = sqlite_backup(spec['ledger'], staging / ('images-%d.sqlite' % index), backups)
        if backups[-1]['original_before']['main']['sha256'] != local_sha:
            raise ValueError('source ledger changed before consistent backup')
        generation[name] = add('generation_ledger:' + str(index), backed,
                               snapshot / ('images-%d.sqlite' % index), spec['server'])
    assets, code = parent['asset_sha256'], parent['code_sha256']
    model_sha = verifier._digest(assets)
    scorer_sha = verifier._digest({'assets': {n: s for n, s in assets.items() if n.split('/')[0] in ('vit', 'clip')},
        'code': {n: code[n] for n in ('scripts/merging/tssa_mvp_score.py', 'scripts/merging/tssa_sd_runtime.py')},
        'dtype': 'float32', 'device': 'cpu', 'image_source': 'saved_rgb_png', 'score_prompt': 'untriggered_paired_prompt'})
    imports, omitted = [], Counter()
    for index, candidate in enumerate(records):
        spec = source_specs[candidate['source']]
        if 'exclude_reason' in spec:
            omitted[candidate['source']] += 1
            continue
        original = path(candidate['image_path'])
        relative = original.relative_to(path(spec['recorded_image_root']))
        actual = path(spec['image_root']) / relative
        if candidate['source'] in transports and transports[candidate['source']]['receipt']['images'].get(str(relative)) != candidate['image_sha']:
            raise ValueError('transport receipt does not bind candidate image: ' + str(relative))
        key = candidate['key']
        if len(key) != 6 or key[0] != PARENT:
            raise ValueError('invalid candidate identity')
        ledger_ref = generation[candidate['source']]
        with closing(sqlite3.connect(Path(ledger_ref['path']).as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            saved = db.execute('SELECT status,input_sha,mask_sha,image_sha,scores FROM attempts WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?', key).fetchone()
            count = db.execute('SELECT COUNT(*) FROM attempt_history WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?', key).fetchone()[0]
        if saved is None or saved[:4] != ('complete', candidate['input_sha'], candidate['mask_sha'], candidate['image_sha']) or json.loads(saved[4]) != candidate['scores']:
            raise ValueError('candidate differs from exact complete ledger row: ' + repr(key))
        image = add('image:' + str(index), actual, snapshot / 'images' / (str(index) + '.png'), spec['server'], candidate['image_sha'])
        imports.append({'key': [RUN, *key[1:]], 'origin_key': key, 'origin_attempt': count + 1,
                        'ledger': ledger_ref, 'image': image, 'input_sha256': saved[1], 'mask_sha256': saved[2],
                        'model_bundle_sha256': model_sha, 'scorer_sha256': scorer_sha, 'scores': candidate['scores']})
    counts = Counter(x['key'][1] for x in imports)
    no_reuse = request.get('no_reuse_reason', '')
    if not imports and (not isinstance(no_reuse, str) or not no_reuse.strip()):
        raise ValueError('R=0 requires a concrete no_reuse_reason')
    bound = write_json(package / 'legacy_bound.json', {'run_id': PARENT, 'server': 'school103',
        'gpu_uuids': uuids, 'upper_bound': len(uuids), 'launch_records': launches,
        'upper_bound_basis': request['legacy_upper_bound_basis']})
    freeze = {'source_imports': counts['source'], 'merge_imports': counts['merge'],
              'late_parent_results': 'not_admitted', 'no_reuse_reason': no_reuse}
    if imports:
        freeze.update(model_bundle_sha256=model_sha, scorer_sha256=scorer_sha)
    request_file = package / 'construction_request.json'
    write_json(request_file, request)
    request_ref = add('construction_request', request_file, snapshot / 'evidence/request.json', server)
    candidate_ref = add('candidate_list', candidate_path, snapshot / 'evidence/candidates.json', server, CANDIDATES_SHA256)
    reconciliation_ref = add('historical_reconciliation', root / TASK / 'recovery_provisional_keys_20261102.json',
        snapshot / 'evidence/recovery_provisional_keys.json', server, RECONCILIATION_SHA256)
    receipt_refs, source_evidence_refs = {}, {}
    for index, (name, item) in enumerate(sorted(transports.items())):
        receipt_refs[name] = add('transport_receipt:' + str(index), Path(item['ref']['path']),
                                 snapshot / 'evidence' / ('transport-%d.json' % index), server, item['ref']['sha256'])
        original = item['source_evidence']
        source_evidence_refs[name] = add('transport_source_evidence:' + str(index), Path(original['path']),
            snapshot / 'evidence' / ('transport-source-%d.json' % index), server, original['sha256'])
    evidence_file = package / 'construction_evidence.json'
    write_json(evidence_file, {
        'created_at_utc': timestamp(), 'request': request_ref, 'candidate_list': candidate_ref,
        'historical_reconciliation': reconciliation_ref,
        'candidate_count': len(records), 'source_specs': source_specs, 'sqlite_backups': backups,
        'transport_receipts': receipt_refs, 'transport_source_evidence': source_evidence_refs,
        'omitted_by_source': dict(omitted), 'import_counts': dict(counts),
        'source_writer_state': 'unknown'})
    evidence_ref = add('construction_evidence', evidence_file, snapshot / 'evidence/construction.json', server)
    proof = {'schema_version': 1, 'run_id': RUN, 'parent_run_id': PARENT,
             'mode': 'immutable_snapshot_namespace_isolation', 'parent_manifest': ref(parent_path),
             'parent_code_root': str(root), 'context_ids': ref(ids_path),
             'old_output_roots': request['old_output_roots'], 'snapshot_root': str(snapshot),
             'output_root': str(output), 'source_writer_state': 'unknown', 'legacy_occupancy_bound': bound,
             'freeze': freeze, 'copies': copies, 'imports': imports, 'construction_evidence': evidence_ref,
             'historical_reconciliation': reconciliation_ref}
    for directory, _, _ in os.walk(snapshot, topdown=False):
        Path(directory).chmod(0o555)
    proof_ref = write_json(package / 'source_isolation.json', proof)
    verifier.validate_source_isolation(proof_ref['path'], proof_ref['sha256'], output_root=output)
    report = {'created_at_utc': timestamp(), 'source_isolation': proof_ref, 'candidates': ref(request['candidates_file']),
              'candidate_count': len(records), 'authenticated_imports': len(imports),
              'import_counts': dict(counts), 'omitted_by_source': dict(omitted),
              'exclusion_reasons': {k: v['exclude_reason'] for k, v in source_specs.items() if 'exclude_reason' in v},
              'construction_evidence': evidence_ref, 'sqlite_backups': backups, 'source_writer_state': 'unknown',
              'notice': 'Source validation is not production review or GPU permission.'}
    return write_json(package / 'construction_report.json', report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    args = parser.parse_args()
    result = build(json.loads(path(args.request).read_text()))
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
