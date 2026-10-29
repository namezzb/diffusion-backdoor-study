import tempfile
import unittest
from pathlib import Path

from evidence import Ledger, paired_cluster_bootstrap

SHA = "a" * 64


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ids = {"source": [f"s{i}" for i in range(128)], "merge": [f"m{i}" for i in range(128)]}
        self.path = Path(self.tmp.name) / "ledger.sqlite"
        self.ledger = Ledger(self.path, "test-run", SHA, self.ids, [11, 12])

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_durable_attempt_not_replayed_and_snapshots_isolated(self):
        args = ("source", "clean", "dog", "s0", 11, SHA, SHA)
        self.assertTrue(self.ledger.start(*args))
        with self.assertRaisesRegex(ValueError, "cannot be replayed"):
            self.ledger.start(*args)
        self.ledger.checkpoint_resource(*args[:5], {"unet_forwards": 25})
        with self.assertRaisesRegex(ValueError, "monotone"):
            self.ledger.checkpoint_resource(*args[:5], {"unet_forwards": 24})
        resource = {"unet_forwards": 50}
        self.ledger.complete(*args[:5], SHA, {"vit_class": 42, "clip_score": 30.}, resource)
        resource["unet_forwards"] = 100
        self.assertFalse(self.ledger.start(*args))
        self.assertEqual(self.ledger.db.execute("SELECT resource FROM attempts").fetchone()[0], '{"unet_forwards":50}')
        self.ledger.close()
        self.ledger = Ledger(self.path, "test-run", SHA, self.ids, [11, 12])
        self.assertFalse(self.ledger.start(*args))
        with self.assertRaisesRegex(ValueError, "hashes changed"):
            self.ledger.start(*args[:-1], "b" * 64)

    def test_stages_and_closed_gate(self):
        with self.assertRaisesRegex(ValueError, "baseline gate"):
            self.ledger.start("source", "new", "dog", "s0", 11, SHA, SHA)
        with self.assertRaisesRegex(ValueError, "source result"):
            self.ledger.start("merge", "clean", "dog", "m0", 11, SHA, SHA)
        with self.assertRaisesRegex(NotImplementedError, "frozen labels"):
            self.ledger.set_gate("source_baseline", "pass")

    def test_partition_and_identity_check(self):
        with self.assertRaisesRegex(ValueError, "another frozen run"):
            Ledger(self.path, "other-run", SHA, self.ids, [11, 12])
        with self.assertRaisesRegex(ValueError, "outside"):
            self.ledger.start("source", "clean", "dog", "m0", 11, SHA, SHA)


class StatisticsTests(unittest.TestCase):
    def test_paired_two_seed_context_clusters(self):
        a = {"c1": {11: 1., 12: 1.}, "c2": {11: 0., 12: 0.}}
        b = {"c1": {11: 0., 12: 0.}, "c2": {11: 0., 12: 0.}}
        stats = paired_cluster_bootstrap(a, b, 42, 1000)
        self.assertEqual(stats["difference"], .5)
        self.assertEqual(stats["contexts"], 2)
        self.assertEqual((stats["lower"], stats["upper"]), (0., 1.))
        self.assertEqual(stats, paired_cluster_bootstrap(a, b, 42, 1000))
        with self.assertRaises(ValueError):
            paired_cluster_bootstrap(a, {"c1": {11: 0.}}, 42)
        with self.assertRaisesRegex(ValueError, "paired seeds"):
            paired_cluster_bootstrap(a, {"c1": {11: 0., 13: 0.}, "c2": {11: 0., 12: 0.}}, 42)


if __name__ == "__main__":
    unittest.main()
