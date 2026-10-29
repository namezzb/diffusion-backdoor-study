"""Synthetic unit checks only: no image generation, scoring models or result files."""

import copy
import unittest
from pathlib import Path

from tssa_mvp_evaluate import EvidenceError, KEY_FIELDS, MVPEvaluator


PROTOCOL = Path(__file__).resolve().parents[2] / "research" / "tssa_mvp_2026-10-26.json"


class EvaluationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evaluator = MVPEvaluator.from_file(PROTOCOL)

    def image_records(self, stage, selection=None):
        """In-memory fixtures: all normal objects correct, malicious triggers cats."""
        ev = self.evaluator
        rows = []
        for key in sorted(ev.expected_keys(stage, selection)):
            row = dict(zip(KEY_FIELDS, key))
            prompt = ev.prompts[(row["split"], row["prompt_id"])]
            if row["kind"] == "triggered":
                row["vit_class"] = 151 if row["candidate"] in ("clean", "matched_clean") else 281
            elif row["kind"] == "paired_normal":
                row["vit_class"] = 151
            else:
                row["vit_class"] = prompt["class_ids"][0]
            row.update(clip_score=30.0, protocol_sha256=ev.sha)
            rows.append(row)
        return rows

    def responses(self, names):
        ev = self.evaluator
        return {
            "protocol_sha256": ev.sha, "B_star_rms": 0.1, "unit_ids": ev.unit_ids.copy(),
            "candidates": {name: {
                "normal_mse": {state: 1.0 for state in ev.normal_states},
                "backdoor_mse": {state: 1.0 if name == "naive" else 0.8 for state in ev.dev_states},
                "delta_l2": 2.0, "per_state_unit_count": 24,
            } for name in names},
        }

    def test_integrity_rejects_missing_duplicate_extra_and_mixed_protocol(self):
        ev = self.evaluator
        rows = self.image_records("source")
        self.assertEqual(len(rows), 48)
        self.assertTrue(ev.source_gate(rows)["passed"])
        for broken in (rows[:-1], rows + [rows[0]], rows + [{**rows[0], "seed": 9999}],
                       [{**rows[0], "protocol_sha256": "0" * 64}] + rows[1:],
                       [{**rows[0], "clip_score": float("nan")}] + rows[1:]):
            with self.subTest(case=broken[-1].get("seed")):
                with self.assertRaises(EvidenceError):
                    ev.source_gate(broken)

    def test_source_gate_counts_not_rounded_percentages(self):
        ev = self.evaluator
        rows = self.image_records("source")
        triggers = [r for r in rows if r["candidate"] == "original_backdoor" and r["kind"] == "triggered"]
        for row in triggers[:2]:
            row["vit_class"] = 151
        report = ev.source_gate(rows)
        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["original_backdoor"]["upload"]["ASR"]["successes"], 6)
        normal = next(r for r in rows if r["candidate"] == "original_backdoor" and r["kind"] == "paired_normal")
        normal["vit_class"] = 281
        report = ev.source_gate(rows)
        self.assertFalse(report["passed"])
        self.assertFalse(report["gates"]["backdoor_normal_accuracy"])
        normal["vit_class"] = 151
        triggers[2]["vit_class"] = 151
        self.assertFalse(ev.source_gate(rows)["gates"]["backdoor_ASR"])

    def test_static_proxy_must_stop_on_reversed_real_image_order(self):
        ev = self.evaluator
        rows = self.image_records("screen")
        self.assertEqual(len(rows), 220)
        response = self.responses(ev.static)
        for state in ev.dev_states:
            trigger_rows = [r for r in rows if r["candidate"] == "Uniform4" and r["state"] == state and r["kind"] == "triggered"]
            for row in trigger_rows[:2]:
                row["vit_class"] = 151
            response["candidates"]["Uniform4"]["backdoor_mse"][state] = 0.1
        report = ev.static_screen(rows, response)
        self.assertFalse(report["passed"])
        self.assertTrue(any(r["reason"] == "proxy_ASR_ranking_reversal" for r in report["stop_reasons"]))
        # A response gate that accepts a 25-point real utility loss is also a
        # concrete proxy failure, even if the trigger ranking happens to agree.
        rows = self.image_records("screen")
        response = self.responses(ev.static)
        damaged = [r for r in rows if r["candidate"] == "TSSA16" and r["state"] == ev.dev_states[0]
                   and r["kind"] == "paired_normal"]
        for row in damaged[:2]:
            row["vit_class"] = 281
        report = ev.static_screen(rows, response)
        self.assertFalse(report["passed"])
        self.assertTrue(any(r["reason"] == "normal_proxy_false_pass" for r in report["stop_reasons"]))

    def test_selection_enforces_utility_before_ASR_and_has_stable_ties(self):
        ev = self.evaluator
        rows = self.image_records("select")
        self.assertEqual(len(rows), 484)
        response = self.responses(ev.all_candidates)
        tied = ev.select_candidates(list(reversed(rows)), response)
        self.assertEqual(tied["selected_checkpoint_candidates"], {
            "naive": "naive", "Uniform": "Uniform4", "TSSA": "TSSA16", "RC-TSSA-GD": "RC-TSSA-GD_step24"})
        for state in ev.dev_states:
            next(r for r in rows if r["candidate"] == "RC-TSSA-GD_step24" and r["state"] == state and r["kind"] == "triggered")["vit_class"] = 151
        next(r for r in rows if r["candidate"] == "RC-TSSA-GD_step48" and r["state"] == ev.dev_states[0] and r["kind"] == "paired_normal")["vit_class"] = 281
        report = ev.select_candidates(rows, response)
        self.assertEqual(report["selected_checkpoint_candidates"]["RC-TSSA-GD"], "RC-TSSA-GD_step24")
        self.assertFalse(report["candidate_table"]["RC-TSSA-GD_step48"]["qualified"])
        self.assertEqual(report["candidate_table"]["RC-TSSA-GD_step24"]["minimum_development_ASR"], 0.75)
        broken_response = copy.deepcopy(response)
        broken_response["candidates"]["Uniform4"]["per_state_unit_count"] = 1
        with self.assertRaises(EvidenceError):
            ev.select_candidates(rows, broken_response)

    def test_heldout_cannot_select_or_reselect_candidates(self):
        ev = self.evaluator
        validation = self.image_records("select")
        response = self.responses(ev.all_candidates)
        selected = ev.select_candidates(validation, response)
        heldout = self.image_records("heldout", selected)
        self.assertEqual(len(heldout), 960)
        for row in heldout:
            if row["candidate"] == "RC-TSSA-GD_step24" and row["kind"] == "triggered":
                row["vit_class"] = 151
        with self.assertRaises(EvidenceError):
            ev.select_candidates(validation + [heldout[0]], response)
        report = ev.heldout_report(heldout, selected)
        self.assertEqual(report["selected_checkpoint_candidates"]["RC-TSSA-GD"], "RC-TSSA-GD_step24")
        self.assertEqual(report["family_metrics"]["RC-TSSA-GD"]["minimum_heldout_ASR"], 0.0)
        cell = report["metrics"]["RC-TSSA-GD_step24"][ev.hold_states[0]]
        self.assertEqual(cell["ASR"]["n"], 16)
        self.assertEqual(cell["independent_trigger_prompt_clusters"], 8)
        self.assertEqual(set(cell["per_seed"]), {"3000", "3001"})
        tampered = copy.deepcopy(selected)
        tampered["selected_checkpoint_candidates"]["RC-TSSA-GD"] = "RC-TSSA-GD_step48"
        with self.assertRaises(EvidenceError):
            ev.heldout_report(heldout, tampered)

    def test_no_qualified_new_candidate_stays_failure(self):
        ev = self.evaluator
        rows = self.image_records("select")
        response = self.responses(ev.all_candidates)
        for name in ("RC-TSSA-GD_step24", "RC-TSSA-GD_step48"):
            response["candidates"][name]["backdoor_mse"] = {s: 1.0 for s in ev.dev_states}
        selected = ev.select_candidates(rows, response)
        self.assertFalse(selected["passed"])
        self.assertIsNone(selected["selected_checkpoint_candidates"]["RC-TSSA-GD"])
        self.assertEqual(selected["status"], "failed_no_qualified_RC_candidate")
        with self.assertRaises(EvidenceError):
            ev.expected_keys("heldout", selected)


if __name__ == "__main__":
    unittest.main()
