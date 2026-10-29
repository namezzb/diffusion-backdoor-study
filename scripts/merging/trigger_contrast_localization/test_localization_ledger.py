import tempfile
import unittest
from pathlib import Path

from localization_ledger import KINDS, LocalizationLedger


class LocalizationLedgerTests(unittest.TestCase):
    def test_precharge_uniqueness_order_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"
            contexts = [f"c{i}" for i in range(64)]
            ledger = LocalizationLedger(path, "run", "a" * 64, contexts, ["block0"])
            with self.assertRaisesRegex(ValueError, "baseline"):
                ledger.begin("block:block0")
            ledger.begin("baseline:clean")
            ledger.reserve("baseline:clean", "trigger", contexts[0])
            with self.assertRaisesRegex(ValueError, "uncertain"):
                ledger.reserve("baseline:clean", "trigger", contexts[0])
            ledger.record("baseline:clean", "trigger", contexts[0], b"embedding")
            self.assertFalse(ledger.reserve("baseline:clean", "trigger", contexts[0]))
            # Completion requires each unique class/context reservation.
            with self.assertRaisesRegex(ValueError, "256"):
                ledger.complete("baseline:clean", b"evidence")
            for kind in KINDS:
                for context in contexts:
                    if (kind, context) != ("trigger", contexts[0]):
                        ledger.reserve("baseline:clean", kind, context)
                        ledger.record("baseline:clean", kind, context, b"embedding")
            ledger.complete("baseline:clean", b"clean evidence")
            ledger.begin("baseline:backdoor")
            for kind in KINDS:
                for context in contexts:
                    ledger.reserve("baseline:backdoor", kind, context)
                    ledger.record("baseline:backdoor", kind, context, b"embedding")
            ledger.complete("baseline:backdoor", b"backdoor evidence")
            ledger.begin("block:block0")
            with self.assertRaisesRegex(ValueError, "all single-block"):
                ledger.begin("control:new")
            self.assertEqual(ledger.db.execute("SELECT COUNT(*) FROM forwards").fetchone()[0], 512)
            ledger.close()

    def test_resume_completed_outputs_and_reject_uncertain_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"
            contexts = [f"c{i}" for i in range(64)]
            ledger = LocalizationLedger(path, "run", "a" * 64, contexts, ["block0"])
            ledger.begin("baseline:clean")
            ledger.reserve("baseline:clean", "trigger", contexts[0])
            ledger.record("baseline:clean", "trigger", contexts[0], b"embedding")
            ledger.close()
            ledger = LocalizationLedger(path, "run", "a" * 64, contexts, ["block0"])
            with self.assertRaisesRegex(ValueError, "cannot be replayed"):
                ledger.begin("baseline:clean")
            self.assertEqual(ledger.resume("baseline:clean")[("trigger", contexts[0])], b"embedding")
            self.assertEqual(ledger.load("baseline:clean", "trigger", contexts[0]), b"embedding")
            self.assertFalse(ledger.reserve("baseline:clean", "trigger", contexts[0]))
            self.assertTrue(ledger.reserve("baseline:clean", "trigger", contexts[1]))
            with self.assertRaisesRegex(ValueError, "uncertain"):
                ledger.resume("baseline:clean")
            with self.assertRaisesRegex(ValueError, "uncertain"):
                ledger.reserve("baseline:clean", "trigger", contexts[1])
            self.assertEqual(ledger.db.execute("SELECT COUNT(*) FROM forwards").fetchone()[0], 2)
            ledger.close()


if __name__ == "__main__":
    unittest.main()
