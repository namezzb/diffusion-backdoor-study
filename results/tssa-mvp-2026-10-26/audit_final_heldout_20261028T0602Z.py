#!/usr/bin/env python3
"""Offline independent audit of frozen TSSA evidence; stdlib only, no ML imports.

Recompute from raw scored JSONL, not evaluator code or its passed flags. Outputs
are new audit artifacts; existing experiment evidence is never changed.
"""
import argparse
import collections
import datetime
import hashlib
import itertools
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = Path(__file__).parent / 'single_run_observation_20261028T060221238162Z.json'
FIELDS = ('candidate', 'state', 'split', 'prompt_id', 'kind', 'seed')
FROZEN_SHA = '8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compact(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def pretty(value):
    return hashlib.sha256((json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    indent=2, allow_nan=False) + '\n').encode()).hexdigest()


def jload(path):
    return json.loads(Path(path).read_text())


class Audit:
    def __init__(self):
        self.checks = 0
        self.failures = []

    def check(self, ok, label, actual=None, expected=None):
        self.checks += 1
        if not ok:
            actual = sorted(actual) if isinstance(actual, set) else actual
            expected = sorted(expected) if isinstance(expected, set) else expected
            self.failures.append(dict(check=label, actual=actual, expected=expected))

    def equal(self, actual, expected, label):
        if isinstance(expected, dict) and isinstance(actual, dict):
            self.check(set(actual) == set(expected), label + ':keys', sorted(actual), sorted(expected))
            for key in expected.keys() & actual.keys():
                self.equal(actual[key], expected[key], label + '.' + str(key))
        elif isinstance(expected, list) and isinstance(actual, list):
            self.check(len(actual) == len(expected), label + ':length', len(actual), len(expected))
            for i, (x, y) in enumerate(zip(actual, expected)):
                self.equal(x, y, label + '[' + str(i) + ']')
        elif isinstance(expected, float) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
            self.check(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), label, actual, expected)
        else:
            self.check(type(actual) is type(expected) and actual == expected, label, actual, expected)


def audit(observation_path):
    a = Audit()
    obs = jload(observation_path)
    base = observation_path.with_suffix('').with_name(observation_path.stem + '_artifacts')
    protocol_path = ROOT / 'research/tssa_mvp_2026-10-26.json'
    p = jload(protocol_path)
    a.equal(sha(protocol_path), FROZEN_SHA, 'frozen_protocol_file')
    files = {}
    for name, metadata in obs['result']['files'].items():
        path = base / name
        a.check(path.is_file(), 'copied_file_exists:' + name)
        if path.is_file():
            files[name] = dict(sha256=sha(path), size=path.stat().st_size)
            a.equal(files[name]['sha256'], metadata['sha256'], 'copied_file_hash:' + name)
            a.equal(files[name]['size'], metadata['size'], 'copied_file_size:' + name)

    held = jload(base / 'heldout_report.json')
    final = jload(base / 'final_report.json')
    selection = jload(base / 'candidate_selection.json')
    binding = jload(base / 'selected_checkpoint_manifests.json')
    ledger = jload(base / 'resource_ledger.json')
    responses = jload(base / 'candidate_response_and_image_metrics.json')['responses']
    learned = jload(base / 'learned_candidates.json')
    identity = final['run_identity_sha256']
    selected = selection['selected_checkpoint_candidates']
    candidates = sorted({name for name in selected.values() if name} | {'matched_clean'})
    prompts = {(split, row['id']): row for split, block in p['prompts'].items()
               for group in ('pairs', 'extra_normal') for row in block[group]}
    hold_states = [s['id'] for s in p['merging']['heldout_states']]
    dev_states = [s['id'] for s in p['merging']['development_backdoor_states']]
    normal_states = [s['id'] for s in p['merging']['development_normal_states']]
    static_names = [c['id'] for c in p['static_candidates']]
    all_names = static_names + list(p['learned_candidate_ids'])
    operations = {x['operation']: x for x in ledger['operations']}
    a.equal(len(operations), len(ledger['operations']), 'unique_operations')

    def correct(row):
        q = prompts[(row['split'], row['prompt_id'])]
        label_key = {'triggered': 'target_class_ids', 'paired_normal': 'normal_class_ids',
                     'extra_normal': 'class_ids'}[row['kind']]
        return row['vit_class'] in q[label_key]

    def expected_keys(stage):
        if stage == 'source':
            names, states, split = ['clean', 'original_backdoor'], ['upload'], 'fit'
            seeds, trigger_states = [p['sampling']['source_gate_seed']], states
            pair_ids = [q['id'] for q in p['prompts'][split]['pairs']]
            extra_ids = [q['id'] for q in p['prompts'][split]['extra_normal']]
        elif stage == 'screen':
            names, states, split = static_names + ['matched_clean'], normal_states, 'fit'
            seeds, trigger_states = [p['sampling']['static_screen_seed']], dev_states
            pair_ids, extra_ids = (p['static_proxy_screen'][k] for k in ('fit_pair_ids', 'fit_extra_normal_ids'))
        elif stage == 'select':
            names, states, split = all_names + ['matched_clean'], normal_states, 'val'
            seeds, trigger_states = [p['sampling']['val_seed']], dev_states
            pair_ids = [q['id'] for q in p['prompts'][split]['pairs']]
            extra_ids = [q['id'] for q in p['prompts'][split]['extra_normal']]
        else:
            names, states, split = candidates, hold_states, 'test'
            seeds, trigger_states = p['heldout']['seeds'], states
            pair_ids = [q['id'] for q in p['prompts'][split]['pairs']]
            extra_ids = [q['id'] for q in p['prompts'][split]['extra_normal']]
        output = set()
        for name, state, seed in itertools.product(names, states, seeds):
            for prompt_id in pair_ids:
                for kind in (['paired_normal', 'triggered'] if state in trigger_states else ['paired_normal']):
                    output.add((name, state, split, prompt_id, kind, seed))
            for prompt_id in extra_ids:
                output.add((name, state, split, prompt_id, 'extra_normal', seed))
        return output

    rows_by_stage = {}
    for stage in ('source', 'screen', 'select', 'heldout'):
        lines = (base / (stage + '_per_image_metrics.jsonl')).read_text().splitlines()
        rows = [json.loads(line) for line in lines]
        rows_by_stage[stage] = rows
        keys = [tuple(row[k] for k in FIELDS) for row in rows]
        expected = expected_keys(stage)
        a.equal(len(set(keys)), len(keys), stage + '.unique_sample_identity')
        a.check(set(keys) == expected, stage + '.exact_frozen_sample_set', len(keys), len(expected))
        for i, row in enumerate(rows):
            key = tuple(row[k] for k in FIELDS)
            prefix = stage + '.row' + str(i)
            a.equal(row['protocol_sha256'], FROZEN_SHA, prefix + '.protocol')
            a.equal(row['run_identity_sha256'], identity, prefix + '.run')
            a.check(type(row['vit_class']) is int and 0 <= row['vit_class'] <= 999, prefix + '.classifier_range')
            a.check(isinstance(row['clip_score'], (int, float)) and math.isfinite(row['clip_score'])
                    and 0 <= row['clip_score'] <= 100, prefix + '.clip_range')
            task_id = pretty({'stage': stage, 'key': list(key)})[:24]
            a.equal(row['task_id'], task_id, prefix + '.task_id')
            a.equal(row['image_path'], 'images/' + stage + '/' + task_id + '.png', prefix + '.image_path')
            a.check(len(row['image_sha256']) == 64 and all(c in '0123456789abcdef' for c in row['image_sha256']), prefix + '.image_hash_format')
            q = prompts[(row['split'], row['prompt_id'])]
            normal = q['prompt'] if row['kind'] == 'extra_normal' else q['normal']
            a.equal(row['normal_prompt'], normal, prefix + '.normal_prompt')
            a.equal(row['prompt'], q['triggered'] if row['kind'] == 'triggered' else normal, prefix + '.generation_prompt')
            op_name = 'image/' + stage + '/' + task_id
            a.check(op_name in operations, prefix + '.receipt_exists')
            if op_name in operations:
                op = operations[op_name]
                a.equal(op['status'], 'completed', prefix + '.receipt_complete')
                a.equal(op['artifact_sha256'], pretty(dict(operation=op_name, run_identity_sha256=identity, payload=row)), prefix + '.receipt_payload_hash')
        a.equal(len({r['task_id'] for r in rows}), len(rows), stage + '.unique_task_ids')
        a.equal(len({r['image_path'] for r in rows}), len(rows), stage + '.unique_paths')

    def group(rows):
        n = len(rows)
        count = sum(correct(r) for r in rows)
        return dict(successes=count, n=n, rate=count/n if n else None,
                    clip_mean=math.fsum(r['clip_score'] for r in rows)/n if n else None)

    def cell(rows):
        by_kind = {k: [r for r in rows if r['kind'] == k] for k in ('triggered', 'paired_normal', 'extra_normal')}
        return dict(ASR=group(by_kind['triggered']), normal=group(by_kind['paired_normal'] + by_kind['extra_normal']),
                    paired_normal=group(by_kind['paired_normal']), extra_normal=group(by_kind['extra_normal']),
                    independent_trigger_prompt_clusters=len({r['prompt_id'] for r in by_kind['triggered']}), image_count=len(rows))

    def aggregate(rows):
        result = {}
        for name, state in sorted({(r['candidate'], r['state']) for r in rows}):
            sample = [r for r in rows if (r['candidate'], r['state']) == (name, state)]
            value = cell(sample)
            value['per_seed'] = {str(seed): cell([r for r in sample if r['seed'] == seed]) for seed in sorted({r['seed'] for r in sample})}
            result.setdefault(name, {})[state] = value
        return result

    def score_digest(rows):
        return compact([{k: row[k] for k in (*FIELDS, 'vit_class', 'clip_score', 'protocol_sha256')}
                        for row in sorted(rows, key=lambda r: tuple(r[k] for k in FIELDS))])

    hm, dm = aggregate(rows_by_stage['heldout']), aggregate(rows_by_stage['select'])
    a.equal(hm, held['metrics'], 'heldout.all_cells_and_per_seed_metrics')
    a.equal(dm, selection['metrics'], 'development.all_cells_and_per_seed_metrics')
    a.equal(score_digest(rows_by_stage['heldout']), held['scored_records_sha256'], 'heldout.scored_digest')
    a.equal(score_digest(rows_by_stage['select']), selection['scored_records_sha256'], 'development.scored_digest')

    def utility(candidate, clean, states):
        out = {}
        for state in states:
            acc = clean[state]['normal']['rate'] - candidate[state]['normal']['rate']
            clip = clean[state]['normal']['clip_mean'] - candidate[state]['normal']['clip_mean']
            acc_ok = acc <= p['candidate_selection']['normal_ACC_drop_vs_matched_clean_max']
            clip_ok = clip <= p['candidate_selection']['normal_CLIP_drop_vs_matched_clean_max']
            out[state] = dict(normal_ACC_drop=acc, normal_CLIP_drop=clip, ACC_passed=acc_ok,
                              CLIP_passed=clip_ok, passed=acc_ok and clip_ok)
        return dict(passed=all(v['passed'] for v in out.values()), states=out)

    a.equal(compact({k: v for k, v in selection.items() if k != 'selection_sha256'}), selection['selection_sha256'], 'selection.canonical_hash')
    a.equal(compact(responses), selection['response_summary_sha256'], 'selection.response_hash')
    candidate_ids = {r['id']: r['candidate_id'] for r in p['static_candidates']}
    candidate_ids.update(p['learned_candidate_ids'])
    qualified, table = {}, {}
    for name in all_names:
        r, naive = responses['candidates'][name], responses['candidates']['naive']
        gates = {}
        for state in normal_states:
            c_rms, n_rms = math.sqrt(r['normal_mse'][state]), math.sqrt(naive['normal_mse'][state])
            limit = max(n_rms, 1e-6) + 1e-6
            gates[state] = dict(candidate_rms=c_rms, naive_rms=n_rms, limit=limit, passed=c_rms <= limit)
        rg = dict(passed=all(g['passed'] for g in gates.values()), states=gates)
        ug = utility(dm[name], dm['matched_clean'], normal_states)
        R, naive_R = max(r['backdoor_mse'].values()), max(naive['backdoor_mse'].values())
        r_ok = name not in p['candidate_selection']['pools']['RC-TSSA-GD'] or R <= p['candidate_selection']['new_method_R_relative_max_vs_naive'] * naive_R
        rates = [dm[name][s]['ASR']['rate'] for s in dev_states]
        table[name] = dict(candidate_id=candidate_ids[name], normal_response_gate=rg, image_utility_gate=ug,
                           new_method_R_gate=r_ok, qualified=(responses['B_star_rms'] > p['loss']['fit_response_signal_rms_min_exclusive'] and rg['passed'] and ug['passed'] and r_ok),
                           minimum_development_ASR=min(rates), mean_development_ASR=math.fsum(rates)/len(rates), R=R, delta_l2=r['delta_l2'])
    a.equal(table, selection['candidate_table'], 'independent_development_gates')
    independently_selected = {'naive': 'naive'}
    for family in ('Uniform', 'TSSA', 'RC-TSSA-GD'):
        pool = [n for n in p['candidate_selection']['pools'][family] if table[n]['qualified']]
        pool.sort(key=lambda n: (-table[n]['minimum_development_ASR'], -table[n]['mean_development_ASR'], table[n]['R'], table[n]['delta_l2'], table[n]['candidate_id']))
        qualified[family] = pool
        independently_selected[family] = pool[0] if pool else None
    a.equal(independently_selected, selected, 'independent_frozen_selection')
    a.equal(qualified, selection['ranked_qualified_candidates'], 'independent_rankings')
    a.equal(selection['heldout_used_for_selection'], False, 'selection.no_test_reuse_flag')
    a.equal(selection['selection_data_split'], 'val', 'selection.split')
    a.equal(binding['selection_sha256'], selection['selection_sha256'], 'checkpoint.selection_binding')
    a.equal(binding['selection_file_sha256'], sha(base / 'candidate_selection.json'), 'checkpoint.selection_file_binding')
    a.equal(binding['binding_sha256'], pretty({k:v for k,v in binding.items() if k != 'binding_sha256'}), 'checkpoint.binding_hash')
    a.equal(binding['run_identity_sha256'], identity, 'checkpoint.run_binding')
    a.equal(binding['protocol_sha256'], FROZEN_SHA, 'checkpoint.protocol_binding')
    coefficients = {r['id']: [r['a'], r['b']] for r in p['static_candidates']}
    coefficients.update({name: r['coefficients'] for name, r in learned.items()})
    expected_coeff = {name: coefficients[name] for name in selected.values() if name}
    a.equal(binding['candidate_coefficients'], expected_coeff, 'checkpoint.coefficients')
    a.equal(set(binding['checkpoint_exports']), set(expected_coeff), 'checkpoint.export_names')
    for name, export in binding['checkpoint_exports'].items():
        a.equal(export['coefficients'], coefficients[name], 'checkpoint.export_coefficients:' + name)
        op_name = 'export/' + name
        a.equal(operations[op_name]['artifact_sha256'], pretty(dict(operation=op_name, run_identity_sha256=identity, payload=export)), 'checkpoint.export_receipt:' + name)
    # Selection and all exports are completed before every first test generation.
    selection_done = operations['gate/selection']['finished_at']
    exports_done = max(operations['export/' + n]['finished_at'] for n in expected_coeff)
    first_test = min(op['attempts'][0]['started_at'] for name, op in operations.items() if name.startswith('image/heldout/'))
    a.check(selection_done < exports_done < first_test, 'selection_and_exports_precede_test', [selection_done, exports_done], first_test)
    for name, op in operations.items():
        if name.startswith(('training/', 'response/', 'image/select/')):
            a.check(op['finished_at'] < first_test, 'no_post_test_training_or_selection:' + name, op['finished_at'], first_test)

    family_metrics, comparisons = {}, {}
    for family, name in selected.items():
        if name is None:
            continue
        rates = [hm[name][state]['ASR']['rate'] for state in hold_states]
        family_metrics[family] = dict(candidate=name, minimum_heldout_ASR=min(rates), mean_heldout_ASR=math.fsum(rates)/len(rates),
                                      normal_utility_gate=utility(hm[name], hm['matched_clean'], hold_states))
    for family in ('naive', 'Uniform', 'TSSA'):
        name, rc = selected[family], selected['RC-TSSA-GD']
        if name is None:
            comparisons[family] = dict(available=False, reason='no_qualified_development_candidate')
        else:
            comparisons[family] = dict(available=True, control_candidate=name, states={s: {
                'ASR_difference': hm[rc][s]['ASR']['rate']-hm[name][s]['ASR']['rate'],
                'normal_ACC_difference': hm[rc][s]['normal']['rate']-hm[name][s]['normal']['rate'],
                'normal_CLIP_difference': hm[rc][s]['normal']['clip_mean']-hm[name][s]['normal']['clip_mean']} for s in hold_states})
    a.equal(family_metrics, held['family_metrics'], 'heldout.family_summaries_and_gates')
    a.equal(comparisons, held['RC_vs_controls'], 'heldout.comparisons')
    a.equal(held['selected_checkpoint_candidates'], selected, 'heldout.frozen_candidates')
    a.equal(held['selection_sha256'], selection['selection_sha256'], 'heldout.selection_hash')
    a.equal(final['heldout'], held, 'final.heldout_payload')
    a.equal(final['selection'], selection, 'final.selection_payload')
    a.equal(final['source_gate'], jload(base/'source_gate.json'), 'final.source_payload')
    a.equal(final['static_screen'], jload(base/'static_screen.json'), 'final.screen_payload')
    for flag in ('retuning_performed', 'formal_FID_evaluated', 'statistical_significance_or_SOTA_certified'):
        a.equal(held[flag], False, 'claim_boundary.' + flag)
    a.equal(held['status'], 'completed_with_missing_qualified_controls', 'heldout.status_not_scientific_success')
    a.equal(held['input_image_count'], len(rows_by_stage['heldout']), 'heldout.input_count')
    failure_rows = [{**r, 'expected': 'target_class' if r['kind']=='triggered' else 'normal_class'} for r in rows_by_stage['heldout'] if not correct(r)]
    a.equal(failure_rows, jload(base/'heldout_failure_cases.json')['cases'], 'all_failure_rows_preserved')
    panels = jload(base/'fixed_panel_index.json')
    a.equal([r['state'] for r in panels], hold_states, 'panels.all_registered_states')
    for panel in panels:
        a.equal(panel['prompt_id'], p['prompts']['test']['pairs'][0]['id'], 'panel.fixed_first_prompt')
        a.equal(panel['seed'], p['sampling']['test_seeds'][0], 'panel.fixed_first_seed')
        a.check((base/panel['path']).is_file(), 'panel.present:' + panel['path'])

    buckets = {k: dict(committed_operation_cost_upper_bounds={}, known_actual_branch_NFE=0,
                       known_actual_autograd_calls=0, known_actual_optimizer_updates=0, counter_incomplete_operations=[])
               for k in ('main','source_extra','diagnostic_extra')}
    extra, peak, durations = [], 0, collections.defaultdict(float)
    for name, op in operations.items():
        a.equal(op['run_identity_sha256'], identity, 'op_identity:' + name)
        a.equal(op['status'], 'completed', 'op_complete:' + name)
        bucket_name = 'source_extra' if name.startswith('image/source/') else 'diagnostic_extra' if name.startswith('diagnostic/') else 'main'
        b = buckets[bucket_name]
        for key, value in op.get('cost_upper_bound', {}).items():
            if isinstance(value, (int,float)):
                b['committed_operation_cost_upper_bounds'][key] = b['committed_operation_cost_upper_bounds'].get(key, 0) + value
        for attempt in op['attempts']:
            if attempt['outcome'] != 'completed':
                extra.append(dict(operation=name, attempt=attempt, cost_upper_bound=op.get('cost_upper_bound', {})))
                continue
            before, after = attempt.get('resources_before', {}), attempt.get('resources_after', {})
            if attempt.get('resource_certainty') == 'partial_or_unknown' or after.get('counts_are_unknown'):
                b['counter_incomplete_operations'].append(name)
                continue
            b['known_actual_branch_NFE'] += sum(after.get('branch_nfe', {}).values()) - sum(before.get('branch_nfe', {}).values())
            for k in ('autograd_calls','optimizer_updates'):
                b['known_actual_'+k] += after.get(k,0)-before.get(k,0)
            peak = max(peak, after.get('peak_allocated_bytes',0))
            durations[bucket_name] += attempt.get('wall_seconds',0)
    a.equal(buckets, ledger['committed_work_by_bucket'], 'ledger.independent_counter_totals')
    a.equal(extra, ledger['failed_or_interrupted_attempts_separately_accounted'], 'ledger.interruption_preserved')
    a.equal(peak, ledger['observed_peak_allocated_bytes'], 'ledger.peak')
    traces = [json.loads(line) for line in (base/'per_step_coefficients_and_losses.jsonl').read_text().splitlines()]
    expected_steps = {(f, s) for f in p['optimization']['families'] for s in range(1,p['optimization']['steps_per_family']+1)}
    a.check({(r['family'], r['step']) for r in traces} == expected_steps and len(traces) == len(expected_steps), 'training.unique_144_updates')
    a.equal(sum(r['details']['autograd_calls'] for r in traces), p['budget']['autograd_calls_max'], 'training.1008_autograd')
    counts = {stage:len(rows) for stage,rows in rows_by_stage.items()}
    image_total, main_total = sum(counts.values()), sum(v for k,v in counts.items() if k!='source')
    a.equal(counts, dict(source=48,screen=220,select=484,heldout=768), 'scientific_counts')
    a.equal(main_total, buckets['main']['committed_operation_cost_upper_bounds']['full_images'], 'ledger.main_image_count')
    a.check(main_total <= p['budget']['main_full_images_max'], 'budget.main_images', main_total, p['budget']['main_full_images_max'])
    a.check(image_total <= p['budget']['full_images_including_source_gate_max'], 'budget.all_images', image_total, p['budget']['full_images_including_source_gate_max'])
    a.equal(buckets['main']['known_actual_optimizer_updates'], p['budget']['optimization_updates'], 'budget.updates')
    a.check(buckets['main']['known_actual_branch_NFE'] <= p['budget']['main_forward_branch_NFE'], 'budget.forward_NFE')
    a.equal(len([n for n in operations if n.startswith('trajectory/')]), p['budget']['main_cached_trajectories'], 'budget.trajectories')
    a.equal(len([n for n in operations if n.startswith('teacher/')]), 120, 'budget.teacher_responses')
    a.equal(jload(base/'failure_or_completion_status.json')['status'], 'completed', 'terminal.completed_status')

    # Same classification/CLIP outputs do not imply identical encoded PNG bytes:
    # provenance metadata deliberately differs by candidate identity.
    comparable = {}
    for name in (selected['Uniform'], selected['RC-TSSA-GD']):
        lhs = {(r['state'],r['prompt_id'],r['kind'],r['seed']):(r['vit_class'],r['clip_score']) for r in rows_by_stage['heldout'] if r['candidate']==name}
        rhs = {(r['state'],r['prompt_id'],r['kind'],r['seed']):(r['vit_class'],r['clip_score']) for r in rows_by_stage['heldout'] if r['candidate']=='matched_clean'}
        comparable[name] = lhs == rhs
        a.check(lhs == rhs, 'zero_coefficients_all_192_scored_outputs_match_clean:' + name)
    result = dict(audit_version=1, audit_kind='independent_stdlib_cpu_recomputation',
                  created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  observation=str(observation_path), observation_sha256=sha(observation_path),
                  protocol_sha256=sha(protocol_path), run_identity_sha256=identity,
                  source_code_reference_hashes={n:sha(ROOT/'scripts/merging'/n) for n in ('tssa_mvp_run.py','tssa_mvp_evaluate.py')},
                  files_verified=files, checks=a.checks, failures=a.failures, audit_passed=not a.failures,
                  independently_recomputed_metrics=hm, independently_recomputed_family_metrics=family_metrics,
                  independently_recomputed_RC_comparisons=comparisons, independently_recomputed_selection=independently_selected,
                  qualified_development_pools=qualified, selection_binding_sha256=binding['binding_sha256'],
                  selection_completed_at=selection_done, exports_completed_at=exports_done, first_heldout_started_at=first_test,
                  scientific_counts=counts, full_images_including_source=image_total, main_images=main_total,
                  optimizer_updates=len(traces), resource_buckets=buckets, committed_operation_wall_seconds=dict(durations),
                  interrupted_attempts=extra, peak_allocated_bytes=peak, failure_case_count=len(failure_rows),
                  zero_candidate_scored_outputs_equal_matched_clean=comparable,
                  interpretation={
                      'technical_execution_completed':True,
                      'heldout_final_ASR_threshold_registered':False,
                      'RC_effectiveness_supported':False,
                      'RC_beats_Uniform':False,
                      'RC_beats_naive':False,
                      'RC_vs_TSSA_comparison_available':False,
                      'reason':'RC and Uniform selected (0,0), with 0/16 target-class successes in all four test cells; naive is higher in every cell and passes all normal utility gates. TSSA has no qualified development candidate.',
                      'scope':'Negative preliminary evidence for this frozen configuration, not a proof that all TSSA designs or future optimization variants fail.'},
                  limitations=[
                      'No model inference, image rescoring, or independent pixel-level verification was run; classification and CLIP values are audited as the recorded output of the pinned scorers.',
                      'Every locally returned artifact hash and every image-row operation-envelope hash was verified; original 1520 image PNGs and large exported checkpoint binaries remain on the server and were not independently rehashed by this CPU audit.',
                      'Each ASR cell has 16 images from eight semantic prompt clusters and two paired seeds; cells and seeds are not independent semantic replications.',
                      'Normal utility pass means only the preregistered small-sample ACC/CLIP screen; no formal FID, significance, or SOTA evidence.',
                      'The earlier interrupted diagnostic is separate from science budget; its recorded 118 branch-NFE and partial/unknown backward cost are not zero.',
                      'Future choices informed by these test results must treat Dtest/Ehold as development evidence and introduce new held-out data.'
                  ])
    return result


def markdown(r):
    lines = ['# TSSA 最终持出独立 CPU 审计', '',
             '独立重算通过：' + str(r['audit_passed']) + '；检查 ' + str(r['checks']) + ' 项，不一致 ' + str(len(r['failures'])) + ' 项。', '',
             '技术执行已经完成，但本轮 RC-TSSA-GD 的攻击恢复目标没有得到支持：RC 与 Uniform 选中 (0,0)，四个持出单元均为 0/16，且与 matched-clean 的 192 条分类/CLIP 输出完全一致。TSSA 没有合格开发候选，不能据其缺席宣称优于 TSSA。', '',
             '| 方法 | 状态 | ASR | 正常 ACC | 正常 CLIP | 正常门槛 |',
             '|---|---|---:|---:|---:|---|']
    for family, fm in r['independently_recomputed_family_metrics'].items():
        for state, m in r['independently_recomputed_metrics'][fm['candidate']].items():
            lines.append('| '+family+' | '+state+' | '+str(m['ASR']['successes'])+'/'+str(m['ASR']['n'])+' | '+str(m['normal']['successes'])+'/'+str(m['normal']['n'])+' | '+format(m['normal']['clip_mean'],'.6f')+' | '+str(fm['normal_utility_gate']['states'][state]['passed'])+' |')
    lines += ['', '正式协议没有额外的“最终 ASR 达到某数即成功”阈值，而要求报告最低/平均 ASR、逐格对照差及正常门槛；`completed_with_missing_qualified_controls` 表示完成评价，`normal_utility_gate.passed` 表示正常筛查通过，均不是 idea 成功。RC 四格 ASR 均低于 naive、与 Uniform 相同，naive 四格正常门槛也通过，因此本次结果是负面的描述性证据。', '',
              '样本集合逐项吻合冻结提示、状态、seed和候选身份，源门禁48、静态220、开发484、持出768，合计1520图；主预算1472图≤1664，更新144次，训练反向调用1008次。少于上限1712图的192图恰为没有合格TSSA候选而未生成的持出工作，不是遗漏应评的有效候选。', '',
              '全部逐图记录均与对应 operation receipt 的已完成载荷哈希吻合，选择及导出完成时间早于首次持出生成；审计独立重算开发筛选、全部持出及逐seed指标、315个失败样本、选择绑定和资源计数，未调用原评价器函数。', '',
              '主任务前向 branch-NFE为'+str(r['resource_buckets']['main']['known_actual_branch_NFE'])+'，源门禁2400；成功诊断138、原误停已记录118及未完整计数的反向成本另列。'+ '正常门槛相对 matched-clean 要求 ACC 下降不超过5个百分点且 CLIP 下降不超过1分；32张正常图下最多允许少1张正确，少2张即超限。', '',
              '审计限制：']
    lines += ['- '+x for x in r['limitations']]
    if r['failures']:
        lines += ['', '不一致项：', '```json', json.dumps(r['failures'],ensure_ascii=False,indent=2), '```']
    lines += ['', '复现命令：', '```sh', 'python3 results/tssa-mvp-2026-10-26/audit_final_heldout_20261028T0602Z.py --output-prefix /tmp/tssa-final-heldout-recheck', '```', '',
              '审计输入：`'+r['observation']+'`；逐格、逐seed、全部校验哈希、完整计数和限制见同名 JSON。', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--observation', type=Path, default=DEFAULT)
    parser.add_argument('--output-prefix', type=Path, default=Path(__file__).parent/'final_heldout_audit_20261028T0602Z')
    args = parser.parse_args()
    r = audit(args.observation.resolve())
    for ext, content in (('.json', json.dumps(r, ensure_ascii=False, indent=2, allow_nan=False)+'\n'), ('.md', markdown(r))):
        path = args.output_prefix.with_suffix(ext)
        with path.open('x') as stream:
            stream.write(content)
    print(json.dumps(dict(audit_passed=r['audit_passed'], checks=r['checks'], failures=r['failures'], output_prefix=str(args.output_prefix)),ensure_ascii=False))
    return 0 if r['audit_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
