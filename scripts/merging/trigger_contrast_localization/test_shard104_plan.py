import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "research/tasks/2026-10-29-trigger-contrast-localization/shard104_plan.py"
spec = importlib.util.spec_from_file_location("shard104_plan_fixture", MODULE)
shard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shard)
SHA = "a" * 64
SEEDS = (271101, 271102)


class ShardPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "run/selection").mkdir(parents=True)
        (self.root / "run/images").mkdir()
        contexts = ["forest-32"] + [f"c{i:03}" for i in range(127)]
        self.rows = [{"id": context, "partition": "source"} for context in contexts]
        self.bindings = SimpleNamespace(run_id="run", manifest_sha=SHA, seeds=SEEDS, selection_sha=SHA, review_sha=SHA,
            input_hashes={("source", context, category): SHA for context in contexts for category in shard.CLASSES},
            mask_hashes={"clean": SHA, "backdoor": SHA})
        (self.root / "run/run_identity.json").write_text(json.dumps({"run_id": "run", "manifest_sha256": SHA, "server": "school103"}))
        (self.root / "run/selection/selection.json").write_text("{}")
        (self.root / "run/localization_terminal.json").write_text("{}")
        with sqlite3.connect(self.root / "run/localization.sqlite") as db:
            db.execute("CREATE TABLE metadata (id INTEGER, value TEXT)")
            db.execute("INSERT INTO metadata VALUES (1,?)", (json.dumps({"run_id": "run", "manifest_sha": SHA}),))
        all_keys = sorted(("source", version, category, context, seed) for version in shard.BASELINES for category in shard.CLASSES for context in contexts for seed in SEEDS)
        complete = [key for key in all_keys if key != shard.EXPECTED_UNRESOLVED][:343]
        with sqlite3.connect(self.root / "run/images.sqlite") as db:
            db.executescript("CREATE TABLE metadata (id INTEGER, value TEXT); CREATE TABLE attempt_history (id INTEGER); CREATE TABLE gates (id INTEGER); CREATE TABLE attempts (run_id TEXT,state TEXT,version TEXT,class TEXT,context_id TEXT,seed INTEGER,status TEXT,input_sha TEXT,mask_sha TEXT,image_sha TEXT,scores TEXT,resource TEXT);")
            db.execute("INSERT INTO metadata VALUES(1,?)", (json.dumps({"run_id":"run", "manifest_sha":SHA, "selection_sha":SHA, "review_sha":SHA}),))
            for key in complete:
                content = repr(key).encode()
                filename = shard.digest(shard.canonical(("run", *key))) + ".png"
                (self.root / "run/images" / filename).write_bytes(content)
                db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", ("run", *key, "complete", SHA, SHA, shard.digest(content), "{}", "{}"))
            db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", ("run", *shard.EXPECTED_UNRESOLVED, "started", SHA, SHA, None, None, "{}"))
        self.write_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        files = {}
        for path in sorted((self.root / "run").rglob("*")):
            if path.is_file():
                data = path.read_bytes()
                files[str(path.relative_to(self.root))] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        content = shard.canonical({"counts": {"complete": 343, "started": 1}, "files": files})
        (self.root / "snapshot_manifest.json").write_bytes(content)
        self.snapshot_sha = shard.digest(content)

    def candidate(self):
        return shard.build_candidate(self.root, self.snapshot_sha, "run", SHA, self.rows, SEEDS, self.bindings)

    def test_exact_disjoint_keys_and_fixed_global_budget(self):
        candidate = self.candidate()
        allowed = {tuple(key) for key in candidate["allowed_keys"]}
        self.assertEqual(len(allowed), 1704)
        self.assertNotIn(shard.EXPECTED_UNRESOLVED, allowed)
        with sqlite3.connect(self.root / "run/images.sqlite") as db:
            existing = set(db.execute("SELECT state,version,class,context_id,seed FROM attempts"))
        self.assertFalse(existing & allowed)
        self.assertEqual(candidate["source_attempts_already_charged"] + candidate["shard_attempt_limit"], 2048)
        self.assertEqual(candidate["status"], "candidate_not_authorized")

    def test_reject_tamper_missing_or_inconsistent_snapshots(self):
        image = next((self.root / "run/images").iterdir())
        image.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "size differs|hash differs"):
            self.candidate()
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "differs from ledger"):
            self.candidate()

    def test_reject_prior_history_and_changed_unresolved(self):
        with sqlite3.connect(self.root / "run/images.sqlite") as db:
            db.execute("INSERT INTO attempt_history VALUES(1)")
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "history or gates changed"):
            self.candidate()

    def test_manifest_verified_empty_wal_is_accepted(self):
        (self.root / 'run/images.sqlite-wal').write_bytes(b'')
        (self.root / 'run/images.sqlite-shm').write_bytes(b'x' * 32768)
        self.write_manifest()
        self.assertEqual(len(self.candidate()['allowed_keys']), 1704)

    def test_nonempty_or_unlisted_wal_is_rejected(self):
        wal = self.root / 'run/images.sqlite-wal'
        wal.write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'manifest-listed'):
            self.candidate()
        wal.write_bytes(b'not empty')
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'manifest-listed'):
            self.candidate()


if __name__ == "__main__":
    unittest.main()
