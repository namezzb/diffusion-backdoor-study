"""SIMULATED pure-CPU scalar fixtures; no model, image, network, or GPU calls."""
import copy
import json
import math
from pathlib import Path
import ast
import unittest

import tssa_target_semantic_gates as g


def simulated_records():
    """Analytic fake losses only; not observed scientific measurements."""
    result = {stage: [] for stage in g.STAGES}
    for op in g.budget_enumeration():
        stage, condition = op['stage'], op['condition_id']
        teacher = stage == 'D0'
        merge = condition != 'upload'
        response_keys = ('normal', 'triggered', 'extra') if merge else ('normal', 'extra')
        output_keys = response_keys + (('target',) if teacher and merge else ())
        record = {k: op[k] for k in ('stage', 'point_id', 'unit_id', 'condition_id')}
        record.update(output_rms={k: 1.0 for k in output_keys},
                      errors_vs_teacher={k: 0.0 for k in response_keys} if stage == 'D1' else None,
                      signal_rms=0.4 if teacher and merge else None,
                      losses=None, gradients=None, resource_delta=dict(op['resource_delta']))
        if not teacher:
            a, b = op['coefficients']
            record['losses'] = {'attack': 2 - 0.5 * a - 0.25 * b if merge else None,
                                'normal': 0.1 * (a * (2 - a)) ** 2 + 0.1 * b ** 2}
        if stage == 'D2':
            record['gradients'] = {'attack': [-0.5, -0.25] if merge else None, 'normal': [0.0, 0.2]}
        if stage == 'D2r':
            record['errors_vs_naive'] = {k: 0.0 for k in response_keys}
        result[stage].append(record)
    return result


def cell(records, stage, unit=g.UNITS[0], condition=g.CONDITIONS[0], point=None):
    point = point or g.BASE_POINTS[stage][0]
    return next(r for r in records[stage] if r['unit_id'] == unit and r['condition_id'] == condition and r['point_id'] == point)


class BudgetAndSchema(unittest.TestCase):
    def setUp(self):
        self.records = simulated_records()

    def test_exact_budget_and_no_shared_mutable_point_lists(self):
        ops = g.budget_enumeration()
        self.assertEqual(len(ops), 96)
        self.assertEqual(g.budget_totals(), {'forward_branch_nfe': 462, 'te_batch_calls': 96,
                         'autograd_calls': 14, 'unet_backward_branch_visits': 44, 'te_backward_calls': 14})
        self.assertEqual([sum(o['resource_delta']['forward_branch_nfe'] for o in ops if o['stage'] == stage)
                          for stage in g.STAGES], [44, 38, 38, 38, 304])
        self.assertEqual(len(g.points_for_stage('D3')), 8)
        ops[8]['coefficients'][0] = 99
        self.assertEqual(ops[9]['coefficients'], [0, 0])
        self.assertEqual(g.points_for_stage('D1')[0]['coefficients'], [0, 0])

    def test_complete_prefixes_and_incremental_API_without_future_records(self):
        prior = {}
        for stage in g.STAGES:
            report = g.check_stage(stage, self.records[stage], prior)
            self.assertEqual(report['through_stage'], stage)
            self.assertEqual(report['status'], 'diagnostic_pass' if stage == 'D3' else 'prefix_pass')
            self.assertFalse(report['scientific_effectiveness_established'])
            prior[stage] = self.records[stage]
            self.assertEqual(report, g.evaluate_stages(prior))
        self.assertEqual(g.evaluate_stages({})['status'], 'not_started')

    def test_unknown_missing_and_duplicate_record_keys_or_cells(self):
        mutations = [lambda r: r['D0'][0].update(unknown=1),
                     lambda r: r['D0'][0].pop('signal_rms'),
                     lambda r: r['D0'].append(copy.deepcopy(r['D0'][0])),
                     lambda r: r['D0'].pop(),
                     lambda r: r['D0'][0].update(unit_id='unknown'),
                     lambda r: r['D0'][0].update(point_id='unplanned'),
                     lambda r: r['D0'][0].update(stage='D1')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                records = copy.deepcopy(self.records)
                mutation(records)
                with self.assertRaises(g.SchemaError):
                    g.evaluate_stages(records)

    def test_nonfinite_bool_negative_and_wrong_gradient_shape_rejected(self):
        for bad in (float('nan'), float('inf'), float('-inf'), True, '1', -1):
            records = copy.deepcopy(self.records)
            records['D0'][0]['output_rms']['normal'] = bad
            with self.subTest(value=bad), self.assertRaises(g.SchemaError):
                g.evaluate_stages(records)
        for bad in ([1.0], [0.0, float('nan')], (1.0, 2.0), [True, 0.0]):
            records = copy.deepcopy(self.records)
            records['D2'][0]['gradients']['attack'] = bad
            with self.subTest(gradient=bad), self.assertRaises(g.SchemaError):
                g.evaluate_stages(records)

    def test_stage_specific_none_and_upload_fields_are_strict(self):
        mutations = [lambda r: r['D0'][0].update(losses={'attack': 1, 'normal': 0}),
                     lambda r: r['D1'][0].update(gradients={'attack': [0, 0], 'normal': [0, 0]}),
                     lambda r: r['D2'][0].update(errors_vs_teacher={'normal': 0, 'triggered': 0, 'extra': 0}),
                     lambda r: cell(r, 'D0', condition='upload')['output_rms'].update(target=1),
                     lambda r: cell(r, 'D2', condition='upload')['losses'].update(attack=0),
                     lambda r: cell(r, 'D2', condition='upload')['gradients'].update(attack=[0, 0]),
                     lambda r: r['D2r'][0].pop('errors_vs_naive')]
        for mutation in mutations:
            records = copy.deepcopy(self.records)
            mutation(records)
            with self.subTest(mutation=mutation), self.assertRaises(g.SchemaError):
                g.evaluate_stages(records)

    def test_budget_rejects_under_over_wrong_type_and_unknown_counts(self):
        for count in (0, 7, 6.0, True):
            records = copy.deepcopy(self.records)
            records['D0'][0]['resource_delta']['forward_branch_nfe'] = count
            with self.subTest(count=count), self.assertRaises(g.SchemaError):
                g.evaluate_stages(records)
        self.records['D0'][0]['resource_delta']['extra_warmup'] = 0
        with self.assertRaises(g.SchemaError):
            g.evaluate_stages(self.records)

    def test_nonconsecutive_and_unknown_stages_rejected(self):
        for stages in ({'D1': self.records['D1']}, {'D0': self.records['D0'], 'D2': self.records['D2']}, {'unknown': []}):
            with self.subTest(stages=list(stages)), self.assertRaises(g.SchemaError):
                g.evaluate_stages(stages)
        with self.assertRaises(g.SchemaError):
            g.check_stage('D2', self.records['D2'], {'D0': self.records['D0']})

    def test_evaluation_does_not_mutate_inputs(self):
        before = json.dumps(self.records, sort_keys=True)
        g.evaluate_stages(self.records)
        self.assertEqual(json.dumps(self.records, sort_keys=True), before)

    def test_stdlib_only_and_python38_parse(self):
        tree = ast.parse(Path(g.__file__).read_text(), feature_version=(3, 8))
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        self.assertEqual(set(imports), {'__future__', 'math'})


class NumericalGates(unittest.TestCase):
    def setUp(self):
        self.records = simulated_records()

    def report(self):
        return g.evaluate_stages(self.records)

    def codes(self):
        return {f['code'] for f in self.report()['failures']}

    def test_positive_simulation_has_56_FD_28_AD_and_weak_normal_not_reliable_zero(self):
        report = self.report()
        metrics = report['stages'][-1]['metrics']
        self.assertEqual(report['status'], 'diagnostic_pass')
        self.assertEqual(metrics['finite_difference_estimates'], 56)
        self.assertEqual(metrics['AD_components'], 28)
        self.assertEqual(len(metrics['gradient_components']), 28)
        self.assertTrue(metrics['locally_eligible_points'])
        weak = [c for c in metrics['gradient_components'] if c['term'] == 'normal' and c['coordinate'] == 'a']
        self.assertTrue(all(c['resolution'] == 'unresolved_not_reliable_zero' for c in weak))

    def test_zero_identity_upload_failure_is_located_before_any_D3_gate(self):
        cell(self.records, 'D1', condition='upload')['errors_vs_teacher']['extra'] = 0.002
        report = g.evaluate_stages({s: self.records[s] for s in ('D0', 'D1')})
        self.assertEqual(report['through_stage'], 'D1')
        self.assertEqual(report['failures'][0]['code'], 'zero_identity_error')
        self.assertEqual(report['failures'][0]['condition_id'], 'upload')
        self.assertEqual(report['failures'][0]['response'], 'extra')

    def test_repeat_upload_failure_cannot_be_ignored(self):
        cell(self.records, 'D2r', condition='upload')['errors_vs_naive']['normal'] = 0.001
        self.assertIn('repeat_numerical_error', self.codes())

    def test_signal_strict_boundary_and_noise_include_extra_response(self):
        cell(self.records, 'D0')['signal_rms'] = 1e-4
        self.assertIn('target_signal_insufficient', self.codes())
        self.records = simulated_records()
        cell(self.records, 'D1')['errors_vs_teacher']['extra'] = 0.001
        cell(self.records, 'D0')['signal_rms'] = 0.02
        self.assertIn('target_signal_insufficient', self.codes())

    def test_clean_preference_fails_polarity(self):
        for record in self.records['D1']:
            if record['condition_id'] != 'upload':
                record['losses']['attack'] = 1.0
        self.assertIn('target_polarity_not_supported', self.codes())

    def test_absolute_loss_noise_never_cancels_in_delta_A(self):
        merge_records = [r for r in self.records['D2r'] if r['condition_id'] != 'upload']
        for i, record in enumerate(merge_records):
            record['losses']['attack'] += 0.1 if i < 3 else -0.1
        report = self.report()
        polarity = report['stages'][-1]['metrics']['polarity']
        self.assertAlmostEqual(polarity['conservative_delta_attack'], 0.1)
        self.assertIn('target_polarity_not_supported', {f['code'] for f in report['failures']})

    def test_reliable_gradient_sign_conflict_and_AD_disagreement(self):
        cell(self.records, 'D2')['gradients']['attack'][0] = 0.5
        self.assertIn('reliable_gradient_sign_conflict', self.codes())
        self.assertIn('finite_difference_disagreement', self.codes())

    def test_two_step_sizes_must_agree(self):
        cell(self.records, 'D3', point='a_plus_h1_16')['losses']['attack'] += 0.2
        failures = self.report()['failures']
        self.assertTrue(any(f['code'] == 'finite_difference_disagreement' and f['coordinate'] == 'a' for f in failures))

    def test_all_attack_gradients_unresolved_is_not_a_pass(self):
        for record in self.records['D2']:
            if record['condition_id'] != 'upload':
                record['gradients']['attack'] = [0, 0]
        for record in self.records['D3']:
            if record['condition_id'] != 'upload':
                record['losses']['attack'] = 1.25
        self.assertIn('aggregate_attack_gradient_unresolved', self.codes())

    def test_aggregate_noise_conservatively_averages_cell_bounds(self):
        merge_records = [r for r in self.records['D2r'] if r['condition_id'] != 'upload']
        for i, record in enumerate(merge_records):
            record['losses']['attack'] += 1e-5 if i < 3 else -1e-5
        report = self.report()
        value = report['stages'][-1]['metrics']['aggregate_attack_gradient']['a']
        self.assertAlmostEqual(value['conservative_mean_absolute_loss_delta'], 1e-5)
        self.assertAlmostEqual(value['eta_conservative_mean_of_cell_bounds'], 1e-5 / 0.0625)

    def test_upload_normal_cost_blocks_otherwise_good_attack_points(self):
        for record in self.records['D3']:
            if record['condition_id'] == 'upload':
                record['losses']['normal'] += 1.0
        report = self.report()
        self.assertEqual({f['code'] for f in report['failures']}, {'no_local_normal_feasible_direction'})
        points = report['stages'][-1]['metrics']['local_points']
        self.assertTrue(all(any(n['condition_id'] == 'upload' and not n['passed'] for n in p['normal_checks']) for p in points))

    def test_derived_nonfinite_FD_cannot_sneak_past_comparisons(self):
        cell(self.records, 'D3', point='a_plus_h1_16')['losses']['attack'] = 1e308
        with self.assertRaisesRegex(g.SchemaError, 'nonfinite'):
            self.report()


if __name__ == '__main__':
    unittest.main(verbosity=2)
