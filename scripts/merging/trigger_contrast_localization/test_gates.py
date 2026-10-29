import unittest

from gates import baseline_decision, recovery_decision


def fixture():
    labels, rows = {}, []
    for i in range(128):
        context = f"c{i}"
        labels[context] = {"trigger": list(range(281, 288)), "dog": [151], "cat": [281], "other": [339]}
        for version in ("clean", "backdoor"):
            for category in ("trigger", "dog", "cat", "other"):
                for seed in (17, 18):
                    pred = 151 if category == "trigger" and version == "clean" else labels[context][category][0]
                    rows.append({"version": version, "class": category, "context_id": context,
                                 "seed": seed, "vit_class": pred, "clip_score": 25.})
    return rows, labels


class GatesTests(unittest.TestCase):
    def test_baseline_source_and_merge(self):
        rows, labels = fixture()
        for state in ("source", "merge"):
            outcome = baseline_decision(state, rows, labels, [17, 18])
            self.assertTrue(outcome["passed"])
            self.assertEqual(outcome["delta"], 1.)
            self.assertEqual(outcome["metrics"]["backdoor"]["cat"]["denominator"], 256)
        # Even with a strong trigger signal, destruction of normal cat fails.
        for row in rows:
            if row["version"] == "backdoor" and row["class"] == "cat":
                row["vit_class"] = 151
        outcome = baseline_decision("source", rows, labels, [17, 18])
        self.assertTrue(outcome["signal_passed"])
        self.assertFalse(outcome["normal_passed"])
        self.assertFalse(outcome["passed"])

    def test_duplicate_missing_and_trigger_labels_fail(self):
        rows, labels = fixture()
        with self.assertRaisesRegex(ValueError, "all 2048"):
            baseline_decision("source", rows[:-1], labels, [17, 18])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            baseline_decision("source", rows + [rows[0]], labels, [17, 18])
        labels["c0"]["trigger"] = [281]
        with self.assertRaisesRegex(ValueError, "cat class"):
            baseline_decision("source", rows, labels, [17, 18])

    def test_recovery_point_threshold_and_ineligible_normal_control(self):
        rows, labels = fixture()
        for original in list(rows):
            if original["version"] != "backdoor":
                continue
            for version in ("new", "magnitude", "block_magnitude", "random_1", "random_2", "random_3"):
                row = dict(original, version=version)
                context = int(row["context_id"][1:])
                if row["class"] == "trigger":
                    cutoff = {"new": 64, "magnitude": 32, "block_magnitude": 32,
                              "random_1": 16, "random_2": 16, "random_3": 16}[version]
                    if context < cutoff:
                        row["vit_class"] = 151
                rows.append(row)
        result = recovery_decision("source", rows, labels, [17, 18])
        self.assertTrue(result["passed"])
        self.assertEqual(result["decrease"]["new"], .5)
        self.assertEqual(result["statistical_support"], "not_computed")
        for row in rows:
            if row["version"] in ("magnitude", "block_magnitude") and row["class"] == "cat":
                row["vit_class"] = 151
        result = recovery_decision("source", rows, labels, [17, 18])
        self.assertEqual(result["reason"], "no_eligible_amplitude")
        self.assertTrue(result["practical_passed"])
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
