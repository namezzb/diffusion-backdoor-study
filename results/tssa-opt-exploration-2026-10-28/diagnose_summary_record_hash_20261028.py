#!/usr/bin/env python3
"""Read-only CPU diagnosis; never repairs evidence or relaxes the strict auditor."""
import ast
from collections import Counter, defaultdict
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPORT = HERE / 'observation_103_20261028T111524087743Z-7268ad87/report.json'
PREVIOUS = HERE / 'observation_103_20261028T100953718980Z-b87b404b/report.json'
AUDITOR_SHA = '2e62bbdc5b837fb4d429e8373a42c6f6d33b0019381d3a6cf63f22b523c566b7'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def load_auditor():
    path = HERE / 'audit_image_search_results.py'
    assert sha(path) == AUDITOR_SHA
    spec = importlib.util.spec_from_file_location('unchanged_independent_auditor', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def synthetic_alias_reproduction(a, runtime_path):
    """Execute the exact method AST with fake CUDA counters, no torch import/GPU."""
    tree = ast.parse(runtime_path.read_text())
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'resource_record')
    body = ast.Module(body=[copy.deepcopy(method)], type_ignores=[]); ast.fix_missing_locations(body)
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(max_memory_allocated=lambda _: 10, max_memory_reserved=lambda _: 20))
    namespace = {'torch': fake_torch, 'Any': object}
    exec(compile(body, str(runtime_path) + ':CPU_AST_only', 'exec'), namespace)
    runtime = SimpleNamespace(device='SIMULATED', ledger={'branch_nfe': {'full_generation': 50}, 'text_encoder_forwards': 1})
    record = {'SIMULATED': True, 'score': {'vit_class': 281, 'clip_score': 80.0},
              'resources_current_process': namespace['resource_record'](runtime)}
    persisted = a.canonical(record); first_hash = a.digest(record)
    shares_nested_dictionary = record['resources_current_process']['branch_nfe'] is runtime.ledger['branch_nfe']
    runtime.ledger['branch_nfe']['full_generation'] = 100; runtime.ledger['text_encoder_forwards'] = 2
    later_hash = a.digest(record); parsed = a.decode(persisted)
    assert shares_nested_dictionary and first_hash != later_hash and a.digest(parsed) == first_hash
    assert record['score'] == parsed['score'] and record['resources_current_process']['text_encoder_forwards'] == 1
    return {'kind': 'SIMULATED_CPU_alias_reproduction_from_exact_frozen_resource_record_AST',
            'runtime_source_sha256': sha(runtime_path), 'method_line': method.lineno,
            'nested_branch_nfe_alias_is_same_object': shares_nested_dictionary,
            'saved_record_NFE': parsed['resources_current_process']['branch_nfe']['full_generation'],
            'in_memory_record_NFE_after_next_generation': record['resources_current_process']['branch_nfe']['full_generation'],
            'top_level_integer_remains_snapshot': record['resources_current_process']['text_encoder_forwards'],
            'scoring_payload_unchanged': record['score'] == parsed['score'],
            'persisted_record_hash': first_hash, 'later_in_memory_hash': later_hash,
            'persisted_bytes_still_self_consistent': a.digest(parsed) == first_hash,
            'GPU_calls': 0, 'torch_imported': False, 'scientific_images_generated': 0}


def run():
    a = load_auditor(); strict = a.Auditor(REPORT).run()
    assert strict['status'] == 'invalid' and strict['errors'] == ['search summary.record_sha256.171: mismatch']
    audit = a.Auditor(REPORT); audit.setup()
    if audit.reader.exists('run/plan.json'):
        assert a.canonical(audit.envelope('plan.json')) == a.canonical(audit.plan)
    source_before = {name: sha(ROOT / name) for name in audit.output['local_frozen_input_hashes_verified']}
    names, stages, all_records = ['clean'] + list(audit.plan['candidates']), {}, []
    for stage in ('search', 'dev'):
        tasks = list(a.task_sequence(audit.plan, stage, names))
        records = [audit.receipt(task) for task in tasks]
        assert all(record is not None for record in records)
        committed = audit.envelope(stage + '_summary.json')
        selected = audit.envelope(stage + '_selection.json')
        recomputed = a.independently_summarize(audit.plan, stage, names, records, complete=True)
        # Diagnostic projections are explicitly separate from the strict audit:
        # the known record-hash defect is enumerated, never called an audit pass.
        metric_projection = {k: v for k, v in recomputed.items() if k != 'record_sha256'}
        a.equal_metrics(committed, metric_projection, stage + ' diagnostic metric projection')
        assert len(committed['record_sha256']) == len(records)
        expected_selection = a.independent_selection(audit.plan, stage, recomputed, a.digest(committed))
        assert a.canonical(selected) == a.canonical(expected_selection)
        last_by_execution = {}
        for record in records:
            eid = record['execution_id']; nfe = record['resources_current_process']['branch_nfe']['full_generation']
            last_by_execution[eid] = max(last_by_execution.get(eid, 0), nfe)
        mismatches, exact_matches = [], []
        for index, record in enumerate(records):
            original = a.digest(record); stored = committed['record_sha256'][index]
            if original == stored:
                exact_matches.append(index); continue
            hypothetical = copy.deepcopy(record)
            old_nfe = hypothetical['resources_current_process']['branch_nfe']['full_generation']
            stage_nfe = last_by_execution[record['execution_id']]
            hypothetical['resources_current_process']['branch_nfe']['full_generation'] = stage_nfe
            reproduced = a.digest(hypothetical)
            assert reproduced == stored, 'Unexplained discrepancy outside nested NFE alias'
            mismatches.append({'index_zero_based': index, 'task_id': record['task_id'], 'execution_id': record['execution_id'],
                'receipt_record_sha256': original, 'committed_summary_record_sha256': stored,
                'sole_hypothetical_changed_path': 'resources_current_process.branch_nfe.full_generation',
                'saved_NFE': old_nfe, 'stage_end_NFE': stage_nfe, 'exact_summary_hash_reproduced': True})
        stage_info = {'completed_receipts_verified': len(records), 'summary_envelope_hash_verified': a.digest(committed),
            'selection_envelope_hash_verified': a.digest(selected), 'record_hash_mismatch_count': len(mismatches),
            'exact_record_hash_match_indices': exact_matches, 'record_hash_mismatches': mismatches,
            'all_non_record_hash_summary_fields_independently_match': True,
            'independent_selection_matches_original': True, 'selection': expected_selection,
            'independent_metric_projection': metric_projection,
            'stage_last_recorded_NFE_per_execution': last_by_execution,
            'execution_receipt_counts': dict(Counter(r['execution_id'] for r in records)),
            'normal_gate_failures': {name: {cid: {k: value[k] for k in ('normal_accuracy', 'normal_clip', 'accuracy_drop_vs_clean', 'clip_drop_vs_clean')}
                for cid, value in candidate['states'].items() if not value['normal_pass']}
                for name, candidate in recomputed['candidates'].items() if not candidate['normal_pass']}}
        stages[stage] = stage_info; all_records.extend(records); names = ['clean', 'naive'] + expected_selection['selected']
    assert stages['search']['selection']['selected'] == ['uniform_075', 'a100_b075']
    assert stages['dev']['selection']['selected'] == []
    assert len(all_records) == len(audit.available) == 816 and len({r['task_id'] for r in all_records}) == 816
    assert not any(audit.all_tasks[tid]['stage'] == 'confirm' for tid in audit.available)
    assert not any(name.startswith('run/confirm_') for name in audit.reader.ledger)
    final = audit.envelope('final_report.json')
    expected_final = {'id': audit.plan['id'], 'status': 'completed', 'stopped_after': 'dev',
        'reason': stages['dev']['selection']['reason'], 'selected': [], 'confirmed_observed_improvement': False,
        'completed_images': 816, 'max_images': 1440, 'last_summary_sha256': stages['dev']['summary_envelope_hash_verified'],
        'generation_and_scoring_seconds': sum(r['seconds'] for r in all_records),
        'new_scientific_budget': True, 'old_mvp_rewritten_or_replayed': False}
    ordered_receipts = sorted(audit.receipts.values(), key=lambda r: r['completed_at'])
    latest, counters = {}, defaultdict(list)
    for receipt in ordered_receipts:
        record = receipt['record']; eid = record['execution_id']
        counters[eid].append(record['resources_current_process']['branch_nfe']['full_generation'])
        latest[eid] = record['resources_current_process']
    assert all(values == list(range(50, len(values)*50+1, 50)) for values in counters.values())
    expected_final['per_execution_last_resources'] = latest
    a.equal_metrics(final, expected_final, 'diagnostic final report')
    previous_raw = json.loads(PREVIOUS.read_text()); previous_checks = []
    for name, item in previous_raw['result']['files'].items():
        if not name.startswith('run/operations/'): continue
        path = PREVIOUS.parent / 'artifacts' / name
        assert sha(path) == item['sha256']
        previous = a.decode(path.read_bytes())
        if previous['status'] == 'completed':
            current = audit.reader.path(name)
            assert sha(current) == item['sha256']
            previous_checks.append(previous['task_id'])
    assert len(previous_checks) == 213
    assert source_before == {name: sha(ROOT / name) for name in source_before}
    assert AUDITOR_SHA == sha(HERE / 'audit_image_search_results.py')
    return {'schema_version': 1, 'diagnosed_at': datetime.now(timezone.utc).isoformat(),
        'status': 'integrity_defect_explained_metrics_recomputed_original_audit_still_invalid',
        'input_report': str(REPORT), 'input_report_sha256': sha(REPORT), 'diagnostic_source_sha256': sha(Path(__file__)),
        'strict_unchanged_audit': {'status': strict['status'], 'errors': strict['errors'], 'auditor_sha256': AUDITOR_SHA},
        'root_cause': {'runtime_source': 'scripts/merging/tssa_sd_runtime.py:350',
            'description': 'resource_record uses a top-level shallow copy; nested ledger.branch_nfe remains shared with every new in-memory record. Later generation mutates old in-memory record hashes, while already serialized per-image receipts remain correct.',
            'consumer': 'scripts/merging/tssa_image_search_run.py:315-318 stores resources and persists per-image hash; summarize:407 later hashes the mutated in-memory records.',
            'restore_boundary': '171 records loaded from JSON have independent resource dictionaries and retain exact hashes. Recovered execution produced 453 search and 192 dev records, exposing the shallow alias; each stage final record matches because its counter is already the stage-end value.'},
        'stage_diagnosis': stages, 'total_hash_discrepancies_exactly_explained_by_one_metadata_path': sum(s['record_hash_mismatch_count'] for s in stages.values()),
        'unexplained_hash_discrepancies': 0, 'completed_unique_raw_receipts_self_consistent': 816,
        'earlier_completed_receipts_unchanged': {'report': str(PREVIOUS), 'sha256': sha(PREVIOUS), 'exact_raw_matches': len(previous_checks)},
        'final_report_expected_fields_and_resource_totals_match': True,
        'resource_accounting_from_persisted_receipts': {'per_execution_counts': {eid:len(v) for eid,v in counters.items()},
            'last_NFE_per_execution': {eid:v[-1] for eid,v in counters.items()}, 'monotonic_exact_50_NFE_steps': True,
            'completed_unique_images':816, 'completed_branch_NFE':sum(v[-1] for v in counters.values()),
            'archived_failed_attempts':1, 'archived_failed_NFE_upper_bound':50, 'total_attempts_including_failure':817,
            'total_branch_NFE_upper_bound_including_failure':40850, 'original_failure_ledger_not_rewritten':True},
        'synthetic_CPU_reproduction': synthetic_alias_reproduction(a, ROOT/'scripts/merging/tssa_sd_runtime.py'),
        'unchanged_frozen_source_hashes': source_before, 'transfer_hashes_verified': audit.reader.verified_paths,
        'limitations': ['Original strict audit remains invalid; this diagnostic does not replace or loosen it.',
            'All saved label/CLIP-derived metrics and selection logic independently match; no score model was rerun and no PNG bytes were verified by this diagnostic.',
            'Parent performs separate final PNG integrity verification; no scientific effectiveness is inferred from the metadata diagnosis.',
            'No confirmation sample/result was opened; the independently recomputed development result has no qualified candidate and no gain over naive macro ASR.',
            'Hypothetical single-field changes exist only in temporary in-memory copies to explain hashes; original records, summaries, manifests and science code are untouched.'],
        'actual_operations': {'network_connections':0,'GPU_tasks':0,'scientific_images_generated':0,'original_files_modified':0}}


if __name__ == '__main__':
    result = run(); target = HERE / 'summary_record_hash_diagnosis_20261028.json'
    with target.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({'report': str(target), 'sha256': sha(target), 'status': result['status'],
        'explained': result['total_hash_discrepancies_exactly_explained_by_one_metadata_path'],
        'unexplained': result['unexplained_hash_discrepancies'],
        'stage_selection': {stage: data['selection'] for stage,data in result['stage_diagnosis'].items()}},ensure_ascii=False,indent=2))
