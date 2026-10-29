import unittest
from types import SimpleNamespace

from evidence import VERSIONS
from paired_stats import baseline_report, paired_report
from test_gates import fixture
from report import render_report


class PairedStatsTests(unittest.TestCase):
    def test_ineligible_source_and_merge_baselines_keep_paired_intervals(self):
        rows, labels = fixture()
        for row in rows:
            if row["version"] == "backdoor" and row["class"] == "trigger":
                row["vit_class"] = 151
        for state in ("source", "merge"):
            report = baseline_report(state, rows, labels, [17, 18], 99)
            self.assertFalse(report["passed"])
            stats = report["statistics"]
            self.assertEqual(stats["bootstrap"]["draws"], 10000)
            self.assertEqual(stats["bootstrap"]["contexts"], 128)
            self.assertEqual(stats["metrics"]["backdoor"]["trigger"]["denominator"], 256)
            self.assertEqual(stats["metrics"]["backdoor"]["trigger"]["numerator"], 0)
            self.assertEqual(stats["backdoor_minus_clean"]["trigger"]["accuracy"]["interval"], [0., 0.])
            self.assertEqual(stats["metrics"]["clean"]["cat"]["clip_mean"]["interval"], [25., 25.])
            db = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: (0,)))
            gate = {"value": "fail", "result": report, "evidence_sha256": "a" * 64}
            result = {"outcome": "inconclusive", "reason": state + "_baseline_ineligible", "merge": "skipped",
                      state + "_baseline": gate}
            text = render_report(SimpleNamespace(run_id="r", manifest_sha="b" * 64), result,
                                 SimpleNamespace(db=db, attempt_count=lambda state: 0), SimpleNamespace(db=db, attempt_count=lambda: 0))
            self.assertIn("95%配对区间", text)
            self.assertIn("10000 次配对抽样", text)
            self.assertIn("a" * 64, text)

    def test_full_context_paired_report_and_two_amplitude_intervals(self):
        labels, rows = {}, []
        for i in range(128):
            context = f"c{i}"
            labels[context] = {"trigger": list(range(281, 288)), "dog": [151], "cat": [281], "other": [330, 332]}
            for version in VERSIONS:
                for category in ("trigger", "dog", "cat", "other"):
                    for seed in (11, 12):
                        wrong = category == "trigger" and version in ("clean", "new")
                        rows.append({"version": version, "class": category, "context_id": context,
                                     "seed": seed, "vit_class": 151 if wrong else labels[context][category][0],
                                     "clip_score": 25.})
        report = paired_report("source", rows, labels, [11, 12], 20261029)
        self.assertEqual(report["bootstrap"]["contexts"], 128)
        self.assertEqual(report["bootstrap"]["draws"], 10000)
        self.assertTrue(report["main_comparison_statistical_support"])
        self.assertEqual(report["new_advantages"]["magnitude"]["interval"], [1., 1.])
        self.assertEqual(report["new_advantages"]["block_magnitude"]["confidence"], .975)
        self.assertEqual(report["metrics"]["backdoor"]["cat"]["denominator"], 256)
        self.assertEqual(report["metrics"]["backdoor"]["cat"]["numerator"], 256)


if __name__ == "__main__":
    unittest.main()
