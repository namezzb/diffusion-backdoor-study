import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import reconcile_preview as subject
from bindings import input_digest


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.root = root
        contexts = [f"c{i}" for i in range(128)]
        self.prompt = {"partition": "source", "id": contexts[0],
                       "texts": {"dog": "dog", "trigger": "trigger"},
                       "tokenization": {"dog": {}}, "class_ids": {"dog": [1]}}
        prompts = (json.dumps(self.prompt) + "\n").encode()
        self.prompts = root / "prompts.jsonl"
        self.prompts.write_bytes(prompts)
        self.manifest = root / "manifest.json"
        self.manifest.write_text(json.dumps({"run_id": "test", "prompts_sha256": hashlib.sha256(prompts).hexdigest(),
                                             "generation_seeds": [1, 2]}))
        self.identity = {"run_id": "test", "manifest_sha": hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
                         "seeds": [1, 2], "prompt_ids": {"source": contexts, "merge": []}}
        self.patcher = patch.object(subject, "MANIFEST_SHA", self.identity["manifest_sha"])
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def ledger(self, path, history=False):
        with closing(sqlite3.connect(path)) as db:
            db.execute("create table metadata (id integer, value text)")
            db.execute("insert into metadata values (1, ?)", (json.dumps(self.identity),))
            columns = "run_id text, state text, version text, class text, context_id text, seed integer, input_sha text, mask_sha text, status text, image_sha text, scores text, resource text"
            db.execute("create table attempts (" + columns + ")")
            db.execute("create table attempt_history (id integer, " + columns + ")")
            row = ("test", "source", "clean", "dog", "c0", 1, input_digest(self.prompt, "dog"),
                   subject.EMPTY_MASK_SHA, "started", None, None, "{}")
            db.execute("insert into attempts values (?,?,?,?,?,?,?,?,?,?,?,?)", row)
            if history:
                db.execute("insert into attempt_history values (?,?,?,?,?,?,?,?,?,?,?,?,?)", (1, *row))
            db.commit()
        return path

    def run_preview(self, sources):
        return subject.preview(self.manifest, self.prompts, sources)

    def test_identical_mirror_is_counted_once_and_history_is_charged(self):
        db = self.ledger(self.root / "a.sqlite", history=True)
        result = self.run_preview([("original", db), ("original", db)])
        self.assertEqual(result["charged_attempts"], 2)
        self.assertEqual(len(result["baseline_unattempted_keys"]), 2047)
        self.assertEqual(result["status"], "provisional_not_executable")

    def test_cross_source_collision_rejected(self):
        a = self.ledger(self.root / "a.sqlite")
        b = self.ledger(self.root / "b.sqlite", history=True)
        with self.assertRaisesRegex(ValueError, "cross-source"):
            self.run_preview([("a", a), ("b", b)])

    def test_same_source_with_different_snapshot_rejected(self):
        a = self.ledger(self.root / "a.sqlite")
        b = self.ledger(self.root / "b.sqlite", history=True)
        with self.assertRaisesRegex(ValueError, "divergent"):
            self.run_preview([("a", a), ("a", b)])

    def test_nonempty_wal_rejected(self):
        db = self.ledger(self.root / "a.sqlite")
        Path(str(db) + "-wal").write_bytes(b"uncheckpointed")
        with self.assertRaisesRegex(ValueError, "standalone"):
            self.run_preview([("a", db)])


if __name__ == "__main__":
    unittest.main()
