"""Persist valid new scores without changing historical score requirements."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from runtime_store import Store


class SemanticStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'run'
        self.key = ['test', 'source', 'clean', 'cat', 'c', 1]
        self.budget = {'max_attempts': 2, 'max_attempts_per_key': 2,
                       'state_max_attempts': {'source': 2, 'merge': 0}}
        self.full = {'vit_class': 331, 'clip_score': 32.0, 'target_clip_score': 28.0,
                     'object_clip_scores': {'dog': 2.0, 'cat': 22.0, 'rabbit': 34.0, 'background': 12.0}}

    def start(self, schema):
        store = Store(self.root, {'run_id': 'test'}, [{'key': self.key}], self.budget, score_schema=schema)
        self.addCleanup(store.close)
        store.reserve(self.key)
        image = store.image_path(self.key)
        image.parent.mkdir()
        Image.new('RGB', (512, 512)).save(image)
        store.register_image(self.key, image)
        return store

    def test_semantic_requires_finite_complete_exact_scores_and_persists(self):
        store = self.start('semantic-v1')
        bad = [dict(vit_class=331, clip_score=32), {**self.full, 'target_clip_score': float('nan')},
               {**self.full, 'target_clip_score': True}, {**self.full, 'extra': 1}]
        for value in (-1, 101, float('inf'), True):
            altered = copy.deepcopy(self.full); altered['object_clip_scores']['rabbit'] = value; bad.append(altered)
        altered = copy.deepcopy(self.full); del altered['object_clip_scores']['cat']; bad.append(altered)
        altered = copy.deepcopy(self.full); altered['object_clip_scores']['extra'] = 3; bad.append(altered)
        for score in bad:
            with self.subTest(score=score), self.assertRaises(ValueError): store.finish(self.key, score)
            self.assertEqual(store.db.execute('SELECT status,scores FROM units').fetchone(), ('scoring', None))
        store.finish(self.key, self.full)
        status, scores = store.db.execute('SELECT status,scores FROM units').fetchone()
        self.assertEqual((status, json.loads(scores)), ('complete', self.full))

    def test_legacy_accepts_original_two_fields(self):
        store = self.start('legacy')
        store.finish(self.key, {'vit_class': 843, 'clip_score': 25.1})
        self.assertEqual(store.snapshot()['statuses'], {'complete': 1})

    def test_cannot_reopen_semantic_run_with_legacy_schema(self):
        store = self.start('semantic-v1')
        store.finish(self.key, self.full)
        store.close()
        self._cleanups.pop()  # store was explicitly closed; the temp directory remains registered
        with self.assertRaisesRegex(ValueError, 'schema'):
            Store(self.root, {'run_id': 'test'}, [{'key': self.key}], self.budget, score_schema='legacy')
        reopened = Store(self.root, {'run_id': 'test'}, [{'key': self.key}], self.budget, score_schema='semantic-v1')
        try:
            self.assertEqual(reopened.snapshot()['statuses'], {'complete': 1})
        finally:
            reopened.close()


if __name__ == '__main__': unittest.main()
