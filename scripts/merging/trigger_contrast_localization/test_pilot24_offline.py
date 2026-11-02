import json
import hashlib
import unittest
from pathlib import Path

from pilot24_inputs import CLASSES, SEED, VERSIONS, balanced_chunks, frozen_units, historical_intersection
from pilot24_statistics import report

ROOT = Path(__file__).resolve().parents[3]
TASK = ROOT / "research/tasks/2026-10-29-trigger-contrast-localization"


class Pilot24OfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stages = frozen_units(TASK / "pilot24_plan_candidate.json", TASK / "pilot24_context_ids.json",
                                  TASK / "manifest_candidate.json", TASK / "prompts_tokenized_candidate.jsonl")

    def test_fixed_partitions_and_provisional_intersection(self):
        self.assertEqual([len(self.stages[x]) for x in ("S0", "S1", "M0", "M1")], [1024, 3072, 512, 1536])
        result = historical_intersection(self.stages, TASK / "recovery_provisional_keys_20261102.json")
        self.assertEqual(result["verified_imports"], 0)
        self.assertEqual(sum(r["count"] for r in result["counts"] if r["status"] == "complete"), 363)
        self.assertEqual(sum(r["count"] for r in result["counts"] if r["status"] == "started"), 4)

    def test_chunks_are_balanced_and_disjoint(self):
        chunks = balanced_chunks(self.stages)
        for stage, expected_chunks in (("S0", 16), ("S1", 16), ("M0", 8), ("M1", 8)):
            self.assertEqual(len(chunks[stage]), expected_chunks)
            flat = [unit for chunk in chunks[stage] for unit in chunk]
            self.assertEqual(len(flat), len(set(flat)))
            self.assertEqual(set(flat), set(self.stages[stage]))
            for chunk in chunks[stage]:
                self.assertEqual(len({unit[4] for unit in chunk}), 8)
                self.assertEqual(len({unit[4].rsplit("-", 1)[0] for unit in chunk}), 8)

    def test_candidate_inventory_is_bound_to_decode_receipt(self):
        candidate_path = TASK / "pilot24_reuse_candidates_20261102.json"
        receipt = json.loads((TASK / "pilot24_candidate_decode_20261102.json").read_text())
        candidate = json.loads(candidate_path.read_text())
        self.assertEqual(hashlib.sha256(candidate_path.read_bytes()).hexdigest(), receipt["candidate_sha256"])
        self.assertEqual(candidate["status"], "provisional_not_imported")
        self.assertEqual(candidate["verified_imported"], 0)
        keys = [tuple(["tcl-20261102-pilot24-v2", *r["key"][1:]]) for r in candidate["records"]]
        self.assertEqual(len(keys), 363)
        self.assertEqual(len(set(keys)), 363)
        self.assertTrue(set(keys).issubset(set(self.stages["S0"])))
        self.assertEqual(sum(r["count"] for r in receipt["reports"].values()), 363)

    @staticmethod
    def sample(n):
        ids = [f"c{i:03}" for i in range(n)]
        labels = {c: {"trigger": list(range(281, 288)), "cat": [281], "dog": [151], "other": [330]} for c in ids}
        rows = []
        for v in VERSIONS:
            for category in CLASSES:
                for i, context in enumerate(ids):
                    if category == "trigger":
                        successes = {"clean": 0, "backdoor": n, "new": 0, "magnitude": n // 2,
                                     "block_magnitude": n // 2, "random_1": n // 2,
                                     "random_2": n // 2, "random_3": n // 2}[v]
                        klass = 281 if i < successes else 151
                    else:
                        klass = {"cat": 281, "dog": 151, "other": 330}[category]
                    rows.append({"version": v, "class": category, "context_id": context,
                                 "seed": SEED, "vit_class": klass, "clip_score": 30.0})
        return labels, rows

    def test_both_dimensions_and_paired_intervals(self):
        for state, n in (("source", 128), ("merge", 64)):
            labels, rows = self.sample(n)
            result = report(state, rows, labels, complete_recovery=True)
            self.assertEqual(result["bootstrap"]["contexts"], n)
            self.assertEqual(result["metrics"]["new"]["trigger"]["denominator"], n)
            self.assertTrue(result["decision"]["passed"])
            self.assertTrue(result["main_comparison_statistical_support"])
            self.assertEqual(result["new_advantages"]["magnitude"]["confidence"], .975)
            base = report(state, [x for x in rows if x["version"] in VERSIONS[:2]], labels, complete_recovery=False)
            self.assertTrue(base["baseline"]["passed"])

    def test_missing_duplicate_and_wrong_seed_rejected(self):
        labels, rows = self.sample(64)
        for bad in (rows[:-1], rows + [rows[0]], [{**rows[0], "seed": 271102}] + rows[1:]):
            with self.assertRaises(ValueError):
                report("merge", bad, labels, complete_recovery=True)

    def test_normal_cat_failure_cannot_pass(self):
        labels, rows = self.sample(128)
        for row in rows:
            if row["version"] == "new" and row["class"] == "cat":
                row["vit_class"] = 151
        result = report("source", rows, labels, complete_recovery=True)
        self.assertFalse(result["decision"]["normal"]["new"])
        self.assertFalse(result["decision"]["passed"])


if __name__ == "__main__":
    unittest.main()
