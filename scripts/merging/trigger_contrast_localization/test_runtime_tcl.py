"""Static real-adapter contract; historical fixtures are copied to temp storage."""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import runtime_tcl
import test_pilot24_runtime as fixture_module
import overnight_science


class TclSpecTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.RuntimeBindingTests('test_frozen_inputs_map_exact_v2_keys_without_gpu_load')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.binding = patch('bindings.load_frozen_bindings', return_value=self.fixture.bound)
        self.binding.start()
        self.addCleanup(self.binding.stop)
        self.request = {'run_id': 'cpu-static-new-run',
                        'run_root': str(self.fixture.root / 'new-run'),
                        'models_root': str(self.fixture.root / 'models'),
                        'repository_root': str(fixture_module.REPOSITORY),
                        'inputs': {name: self.fixture.inputs[name]['path'] for name in runtime_tcl.REQUIRED_INPUTS}}

    def test_build_expands_real_frozen_keys_and_checks_scientific_changes(self):
        spec = runtime_tcl.audit_build_spec(self.request)
        science = spec['science']
        self.assertEqual(len(science['units']), 6144)
        self.assertEqual(len({tuple(unit['key']) for unit in science['units']}), 6144)
        self.assertEqual(science['budget'], {'max_attempts': 6272, 'max_attempts_per_key': 2,
                                            'state_max_attempts': {'source': 4160, 'merge': 2112}})
        report = runtime_tcl.TCLAdapter(spec).validate_inputs()
        self.assertEqual(report['stage_counts'], {name: len(keys) for name, keys in self.fixture.stages.items()})
        for field in ('input_sha', 'mask_sha', 'stage'):
            altered = copy.deepcopy(spec)
            altered['science']['units'][0][field] = '0' * 64 if field != 'stage' else 'M1'
            with self.subTest(field=field), self.assertRaises(ValueError):
                runtime_tcl.TCLAdapter(altered).validate_inputs()
        altered = copy.deepcopy(spec)
        altered['science']['budget']['state_max_attempts']['source'] += 1
        with self.assertRaises(ValueError):
            runtime_tcl.TCLAdapter(altered).validate_inputs()
        path = self.fixture.root / 'selection.json'
        path.write_text('changed scientific input')
        with self.assertRaisesRegex(ValueError, 'scientific input changed'):
            runtime_tcl.TCLAdapter(spec).validate_inputs()

    def overnight_request(self):
        # Original v2 mocks only have 64 merge contexts; the new screening may
        # select from all 128 original merge contexts, never from image results.
        hashes = dict(self.fixture.bound.input_hashes)
        rows = [json.loads(line) for line in Path(self.request['inputs']['prompts']).read_text().splitlines()]
        for row in rows:
            if row['partition'] in ('source', 'merge'):
                for category in ('trigger', 'dog', 'cat', 'other'):
                    key = (row['partition'], row['id'], category)
                    hashes.setdefault(key, hashlib.sha256(repr(key).encode()).hexdigest())
        self.fixture.bound = replace(self.fixture.bound, input_hashes=hashes)
        self.binding.stop()
        self.binding = patch('bindings.load_frozen_bindings', return_value=self.fixture.bound)
        self.binding.start()
        self.addCleanup(self.binding.stop)
        path = self.fixture.root / 'study_protocol.json'
        path.write_text(json.dumps(overnight_science.protocol_template(self.request['inputs']['prompts'])))
        return dict(self.request, run_id=overnight_science.RUN_ID, study_protocol=str(path))

    def test_overnight_expands_exact_paired_keys_budget_and_deadline(self):
        request = self.overnight_request()
        spec = runtime_tcl.audit_build_spec(request)
        self.assertEqual(len(spec['science']['units']), 1024)
        self.assertEqual(spec['science']['budget'], overnight_science.BUDGET)
        self.assertEqual(spec['science']['compute_deadline_utc'], overnight_science.DEADLINE_UTC)
        report = runtime_tcl.TCLAdapter(spec).validate_inputs()
        self.assertEqual(report['stage_counts'], {'S0': 128, 'S1': 384, 'M0': 128, 'M1': 384})
        self.assertTrue(report['exploratory'])
        contexts = {}
        for unit in spec['science']['units']:
            key = unit['key']
            self.assertEqual(key[0], overnight_science.RUN_ID)
            self.assertEqual(key[5], 271101)
            contexts.setdefault(key[1], set()).add(key[4])
        for ids in contexts.values():
            self.assertEqual(len(ids), 16)
            for stratum in overnight_science.STRATA:
                self.assertEqual(sum(x.startswith(stratum + '-') for x in ids), 2)
        self.assertFalse(contexts['source'] & contexts['merge'])

    def test_overnight_rejects_changed_deadline_budget_or_units(self):
        spec = runtime_tcl.audit_build_spec(self.overnight_request())
        for field, value in (('compute_deadline_utc', '2026-11-03T23:30:00+00:00'),
                             ('budget', {'max_attempts': 9999}),
                             ('units', spec['science']['units'][:-1])):
            altered = copy.deepcopy(spec)
            altered['science'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                runtime_tcl.TCLAdapter(altered).validate_inputs()

    def test_overnight_protocol_cannot_silently_change_thresholds(self):
        request = self.overnight_request()
        path = self.fixture.root / 'study_protocol.json'
        protocol = json.loads(path.read_text())
        protocol['thresholds']['normal_accuracy_loss_max'] = .10
        path.write_text(json.dumps(protocol))
        with self.assertRaisesRegex(ValueError, 'fixed screening design'):
            runtime_tcl.audit_build_spec(request)

    def test_overnight_context_selection_does_not_use_historical_v2_subset(self):
        selected = overnight_science.select_contexts(self.request['inputs']['prompts'])
        original = json.loads(Path(self.request['inputs']['context_ids']).read_text())
        self.assertTrue(set(selected['merge']) - set(original['merge_context_ids']))


class OvernightStatisticsTest(unittest.TestCase):
    def table(self):
        contexts = [f'context-{i:02}' for i in range(16)]
        labels = {c: {'trigger': list(range(281, 288)), 'dog': [207], 'cat': [281], 'other': [330]} for c in contexts}
        counts = {'clean': 0, 'backdoor': 16, 'new': 0, 'magnitude': 12,
                  'block_magnitude': 12, 'random_1': 8, 'random_2': 8, 'random_3': 8}
        rows = []
        for version in overnight_science.VERSIONS:
            for i, context in enumerate(contexts):
                for category in overnight_science.CLASSES:
                    label = (281 if i < counts[version] else 207) if category == 'trigger' else labels[context][category][0]
                    rows.append({'version': version, 'class': category, 'context_id': context,
                                 'seed': 271101, 'vit_class': label, 'clip_score': 50.0})
        return rows, labels

    def test_complete_screening_support_is_explicitly_exploratory(self):
        rows, labels = self.table()
        for state in ('source', 'merge'):
            result = overnight_science.report(state, rows, labels, complete_recovery=True)
            self.assertTrue(result['decision']['passed'])
            self.assertTrue(result['exploratory'])
            self.assertFalse(result['formal_validation'])
            self.assertEqual(result['metrics']['new']['dog']['denominator'], 16)
            self.assertEqual(result['bootstrap']['contexts'], 16)
            self.assertAlmostEqual(result['accuracy_resolution'], .0625)

    def test_one_added_normal_error_fails_unchanged_five_percent_limit(self):
        rows, labels = self.table()
        next(row for row in rows if row['version'] == 'new' and row['class'] == 'dog')['vit_class'] = 281
        result = overnight_science.report('source', rows, labels, complete_recovery=True)
        self.assertFalse(result['decision']['normal']['new'])
        self.assertFalse(result['decision']['passed'])

    def test_partial_or_invalid_table_is_not_a_negative_finding(self):
        rows, labels = self.table()
        with self.assertRaisesRegex(ValueError, 'incomplete result table'):
            overnight_science.report('source', rows[:-1], labels, complete_recovery=True)
        rows[0]['clip_score'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'invalid scorer output'):
            overnight_science.report('source', rows, labels, complete_recovery=True)


if __name__ == '__main__':
    unittest.main()
