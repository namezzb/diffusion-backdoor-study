from collections import Counter
from pathlib import Path
from types import SimpleNamespace
import copy
import itertools
import json
import tempfile
import unittest
from unittest.mock import patch

from bindings import input_digest
from pilot24_inputs import RUN, VERSIONS, frozen_units
from pilot24_prepare import build_configuration, historical_lineage, imported_records, ordinary_path, prepare, reference

ROOT = Path(__file__).resolve().parents[3]
TASK = ROOT / 'research/tasks/2026-10-29-trigger-contrast-localization'


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stages = frozen_units(TASK / 'pilot24_plan_candidate.json', TASK / 'pilot24_context_ids.json',
                                 TASK / 'manifest_candidate.json', TASK / 'prompts_tokenized_candidate.jsonl')
        rows = [json.loads(line) for line in (TASK / 'prompts_tokenized_candidate.jsonl').read_text().splitlines()]
        cls.bindings = SimpleNamespace(
            input_hashes={(r['partition'], r['id'], c): input_digest(r, c) for r in rows for c in r['texts']},
            labels={(r['partition'], r['id'], c): r['class_ids'][c] for r in rows for c in r['texts']},
            mask_hashes={version: str(index) * 64 for index, version in enumerate(VERSIONS)})
        cls.workers = [{'worker_id': 'worker' + str(i), 'server': 'school104',
                        'gpu_uuid': 'GPU-' + str(i) * 8 + '-0000-0000-0000-000000000000'} for i in range(3)]

    def config(self, imports=None, workers=None):
        return build_configuration(self.stages, self.bindings, workers or self.workers,
            imports or [], 'a' * 64, '/data2/zhangzibo/arxiv-tssa/results/' + RUN, 'b' * 64, 'c' * 64)

    def test_actual_protocol_all_keys_balanced_and_retry_caps(self):
        config = self.config()
        keys = [tuple(u['key']) for a in config['assignments'] for u in a['units']]
        self.assertEqual(len(keys), 6144)
        self.assertEqual(set(keys), set(itertools.chain.from_iterable(self.stages.values())))
        self.assertEqual([len(config['stages'][s]) for s in ('S0', 'S1', 'M0', 'M1')], [1024, 3072, 512, 1536])
        self.assertEqual({s: sum(a['retry_tokens'] for a in config['assignments'] if a['stage'][0] == s)
                          for s in ('S', 'M')}, {'S': 64, 'M': 64})
        for assignment in config['assignments']:
            strata = Counter(u['key'][4].rsplit('-', 1)[0] for u in assignment['units'])
            self.assertEqual(len(strata), 8)
            self.assertEqual(len(set(strata.values())), 1)
        self.assertEqual(len(config['labels']['source']), 128)
        self.assertEqual(len(config['labels']['merge']), 64)
        self.assertEqual(self.config(workers=list(reversed(self.workers))), config)

    def test_imports_never_receive_new_generation_assignments(self):
        imports = [{'key': list(k), 'input_sha': self.bindings.input_hashes[(k[1], k[4], k[3])],
                    'mask_sha': self.bindings.mask_hashes[k[2]], 'model_bundle_sha256': 'b' * 64,
                    'scorer_sha256': 'c' * 64} for k in self.stages['S0'][::2][:363]]
        config = self.config(imports)
        assigned = {tuple(u['key']) for a in config['assignments'] for u in a['units']}
        imported = {tuple(r['key']) for r in imports}
        self.assertEqual(len(assigned), 6144 - 363)
        self.assertFalse(assigned & imported)
        self.assertEqual(assigned | imported, set(itertools.chain.from_iterable(self.stages.values())))
        imports[0]['input_sha'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'different frozen input'):
            self.config(imports)

    def test_legacy_interrupted_keys_are_bound_even_when_r_is_zero(self):
        path = TASK / 'recovery_provisional_keys_20261102.json'
        history = historical_lineage({'historical_reconciliation': reference(path)}, self.stages)
        failed = [r for r in history['records'] if r['observed_status'] == 'started']
        self.assertEqual(len(failed), 4)
        self.assertEqual(history['observed_charged_attempts_lower_bound'], 734)
        self.assertEqual(history['later_legacy_consumption'], 'unknown')
        assigned = {tuple(u['key']) for a in self.config()['assignments'] for u in a['units']}
        self.assertTrue(all(tuple(r['key']) in assigned and r['source_ledger_sha256'] for r in failed))

    def test_rejects_duplicate_imports_and_duplicate_gpu_identity(self):
        row = {'key': list(self.stages['S0'][0])}
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.config([row, row])
        workers = copy.deepcopy(self.workers)
        workers[1]['gpu_uuid'] = workers[0]['gpu_uuid']
        with self.assertRaisesRegex(ValueError, 'unique'):
            self.config(workers=workers)

    def test_accepts_productive_single_worker_but_not_guessed_cross_node_plan(self):
        config = self.config(workers=self.workers[:1])
        self.assertEqual({a['worker_id'] for a in config['assignments']}, {'worker0'})
        workers = copy.deepcopy(self.workers)
        workers[1]['server'] = 'school127'
        with self.assertRaisesRegex(ValueError, 'one server'):
            self.config(workers=workers)

    def test_import_translation_retains_lineage_and_rejects_scorer_mismatch(self):
        key = list(self.stages['S0'][0])
        source = {'key': key, 'origin_key': ['tcl-20261029-01-v1', *key[1:]], 'origin_attempt': 1,
            'ledger': {'path': '/data2/source/ledger.sqlite3', 'sha256': 'd' * 64},
            'image': {'path': '/data2/source/image.png', 'sha256': 'e' * 64},
            'input_sha256': 'f' * 64, 'mask_sha256': '1' * 64,
            'model_bundle_sha256': 'b' * 64, 'scorer_sha256': 'c' * 64,
            'scores': {'vit_class': 282, 'clip_score': 21.0}}
        proof = {'imports': [source], 'freeze': {'model_bundle_sha256': 'b' * 64, 'scorer_sha256': 'c' * 64}}
        record = imported_records(proof, 'b' * 64, 'c' * 64)[0]
        self.assertEqual(record['image_path'], source['image']['path'])
        self.assertEqual(record['input_sha'], source['input_sha256'])
        self.assertEqual(record['provenance_import']['origin_key'], source['origin_key'])
        self.assertEqual(record['scores'], source['scores'])
        with self.assertRaisesRegex(ValueError, 'model/scorer'):
            imported_records(proof, 'b' * 64, '0' * 64)

    def test_symlink_ancestor_rejected_before_freezing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            actual = root / 'actual'
            actual.mkdir()
            link = root / 'alias'
            link.symlink_to(actual, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                ordinary_path(link / 'not-yet-created', must_exist=False)

    def test_prepare_publishes_only_pending_review_and_rejects_overwrite(self):
        # Use the actual provenance validator against independent readonly
        # synthetic copies; only the large model/mask binding is substituted.
        # This tests interface integration, not remote asset/model acceptance.
        from pilot24_run import load_reviewed_configuration
        from test_pilot24_provenance import Fixture
        source = Fixture()
        source.setUp()
        try:
            root = source.root
            models = root / 'models'
            models.mkdir()
            execution = source.output
            parent = json.loads((TASK / 'manifest_candidate.json').read_text())
            bound = SimpleNamespace(**vars(self.bindings), asset_hashes=parent['asset_sha256'])
            request = {'repository_root': str(ROOT), 'models_root': str(models),
                'execution_root': str(execution), 'workers': self.workers,
                'source_isolation': source.proof_ref}
            with patch('bindings.load_frozen_bindings', return_value=bound):
                report = prepare(request)
                self.assertEqual(report['status'], 'prepared_pending_independent_review')
                self.assertEqual(report['verified_imports'], 0)
                self.assertFalse(report['gpu_started'])
                self.assertFalse(report['model_files_rehashed'])
                self.assertIsNone(report['t0'])
                review = json.loads(Path(report['review_file']).read_text())
                self.assertEqual(review['status'], 'pending')
                self.assertIsNone(review['reviewer'])
                self.assertEqual(review['manifest_sha256'], report['bundle']['sha256'])
                launch = json.loads((execution / 'frozen/launch_map.template.json').read_text())
                for worker in self.workers:
                    self.assertEqual(launch[worker['worker_id']]['server'], worker['server'])
                    self.assertTrue(launch[worker['worker_id']]['permission_ref'].endswith(worker['worker_id'] + '.json'))
                with self.assertRaisesRegex(ValueError, 'independent approval'):
                    load_reviewed_configuration(report['bundle']['path'], report['coordinator_config']['path'])
                self.assertFalse((execution / 'coordinator').exists())
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    prepare(request)
        finally:
            source.tearDown()


if __name__ == '__main__':
    unittest.main()
