"""Static checks for the fixed semantic study, without loading models."""
import copy
import itertools
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import semantic_science


PROMPTS = (Path(__file__).resolve().parents[3] /
           'research/tasks/2026-10-29-trigger-contrast-localization/prompts_tokenized_candidate.jsonl')


class SemanticScienceTest(unittest.TestCase):
    def make_rows(self):
        protocol = semantic_science.protocol_template(PROMPTS)
        contexts = protocol['context_ids']['source']
        labels = {c: {'trigger': list(range(281, 288)), 'dog': list(range(151, 269)),
                      'cat': list(range(281, 288)), 'other': [330, 332]} for c in contexts}
        rows = []
        for version, category, context in itertools.product(protocol['versions'], protocol['classes'], contexts):
            object_name = {'trigger': 'cat', 'other': 'rabbit'}.get(category, category)
            objects = {key: 10.0 for key in ('dog', 'cat', 'rabbit', 'background')}
            objects[object_name] = 35.0
            target = {'clean': 20, 'backdoor': 40, 'new': 25, 'magnitude': 35,
                      'block_magnitude': 35, 'random_1': 35, 'random_2': 35, 'random_3': 35}[version]
            rows.append({'version': version, 'class': category, 'context_id': context,
                         'seed': protocol['generation_seeds'][0], 'vit_class': 331 if category == 'other' else 843,
                         'clip_score': 30.0, 'target_clip_score': target, 'object_clip_scores': objects})
        return rows, labels

    def test_fixed_protocol_expands_1024_unique_keys_without_old_import(self):
        protocol = semantic_science.protocol_template(PROMPTS)
        semantic_science.validate_protocol(protocol, PROMPTS)
        stages = semantic_science.frozen_units(protocol, PROMPTS)
        self.assertEqual({k: len(v) for k, v in stages.items()}, {'S0': 128, 'S1': 384, 'M0': 128, 'M1': 384})
        keys = [tuple(key) for values in stages.values() for key in values]
        self.assertEqual(len(keys), 1024)
        self.assertEqual(len(set(keys)), 1024)
        self.assertTrue(all(key[0] == semantic_science.RUN_ID for key in keys))
        self.assertEqual(protocol['historical_image_imports'], 0)
        self.assertEqual(protocol['new_training_updates'], 0)
        self.assertEqual(protocol['new_localization_forwards'], 0)
        for state, contexts in protocol['context_ids'].items():
            self.assertEqual(len(contexts), 16)
            self.assertFalse(set(contexts) & set(semantic_science.EXCLUDED[state]))
        changed = copy.deepcopy(protocol)
        changed['historical_image_imports'] = 1
        with self.assertRaises(ValueError):
            semantic_science.validate_protocol(changed, PROMPTS)

    def test_vit_background_and_rabbit_331_are_diagnostic_not_gate(self):
        rows, labels = self.make_rows()
        out = semantic_science.report('source', rows, labels, complete_recovery=True)
        self.assertTrue(out['baseline']['passed'])
        self.assertEqual(out['metrics']['backdoor']['cat']['vit_numerator'], 0)
        self.assertEqual(out['metrics']['backdoor']['other']['vit_numerator'], 0)
        self.assertEqual(out['metrics']['backdoor']['cat']['clip_choice_numerator'], 16)
        self.assertEqual(out['metrics']['backdoor']['other']['clip_choice_numerator'], 16)
        self.assertTrue(out['decision']['passed'])
        broken = copy.deepcopy(rows); del broken[0]['object_clip_scores']['cat']
        with self.assertRaises(ValueError):
            semantic_science.report('source', broken, labels, complete_recovery=True)

    def test_no_eligible_control_results_are_inconclusive(self):
        for control, expected in ((('random_1', 'random_2', 'random_3'), 'no_eligible_random'),
                                  (('magnitude', 'block_magnitude'), 'no_eligible_amplitude')):
            rows, labels = self.make_rows()
            for row in rows:
                if row['version'] in control and row['class'] == 'dog':
                    row['clip_score'] = 28.0  # Relative normal loss 2 > 1.
                if expected == 'no_eligible_amplitude' and row['version'] == 'new' and row['class'] == 'trigger':
                    row['target_clip_score'] = 39.0  # Also fails the practical drop target.
            result = semantic_science.report('source', rows, labels, complete_recovery=True)
            with self.subTest(missing=expected):
                self.assertTrue(result['baseline']['passed'])
                self.assertFalse(result['decision']['comparisons_eligible'])
                self.assertFalse(result['decision']['passed'])
                self.assertEqual(result['decision']['reason'], expected)
                self.assertEqual(result['bootstrap']['resampling'], 'within_stratum')
                final = semantic_science.final_outcome({stage: result for stage in ('S0', 'S1', 'M0', 'M1')})
                self.assertEqual(final['outcome'], 'inconclusive')
                self.assertEqual(final['reason'], 'insufficient_eligible_controls')


if __name__ == '__main__': unittest.main()
