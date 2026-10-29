"""Local-only tests. All constructed/tampered data are SIMULATED evidence.

Synthetic integration summaries use the audit formatter only to build a bound
artifact chain; metric/selection tests below assert independently hand-derived
answers. No synthetic result is represented as a scientific measurement.
"""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("independent_audit", ROOT / "audit_image_search_results.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
PLAN = json.loads((audit.REPO / "research/tssa_optimization_exploration_2026-10-28.json").read_text())
SOURCE_OBSERVATION = ROOT / "observation_103_20261028T090936713940Z-5f77ac6c"


def fake_record(name, cid, row, values, hit=False, correct=True, clip=80):
    label = 281 if hit and row["triggered"] else (row["expected_class_ids"][0] if correct else 999)
    return {"candidate": name, "condition_id": cid, "row": row, "coefficients": values,
            "score": {"vit_class": label, "clip_score": float(clip)}, "seconds": 1.0}


def synthetic_records(stage, names, overrides=None):
    records = []
    for task in audit.task_sequence(PLAN, stage, names):
        name, row, cid = task["candidate"], task["row"], task["condition"]["id"]
        r = fake_record(name, cid, row, task["coefficients"], hit=name not in ("clean", "naive"))
        r["stage"] = stage
        r["task_id"] = audit.digest(task)
        if overrides:
            overrides(r)
        records.append(r)
    return records


class SyntheticPackage:
    """SIMULATED receipt chain, never pointed at the active experiment."""
    def __init__(self, base):
        self.base = Path(base)
        self.report_path = self.base / "report.json"
        self.artifacts = self.base / "artifacts"
        self.identity = {
            "id": PLAN["id"], "plan_sha256": audit.FROZEN_PLAN_SHA256,
            "plan_payload_sha256": audit.digest(PLAN), "old_protocol_sha256": PLAN["old_protocol_sha256"],
            "asset_manifest_sha256": PLAN["asset_manifest_sha256"], "source_hashes": PLAN["source_hashes"],
            "max_images": 1440, "maximum_stage_images": audit.stage_limits(PLAN), "scorer_device": "cpu"}
        self.identity_sha = audit.digest(self.identity)
        self.report = {"SIMULATED_TEST_ONLY": True, "plan_sha256": audit.FROZEN_PLAN_SHA256,
                       "result": {"plan_sha256": audit.FROZEN_PLAN_SHA256, "files": {}, "errors": [],
                                  "run": {"identity_sha256": self.identity_sha}}}
        self.execution_id = "20261028T090148739827Z"
        self.counter = 0
        self.all_records = []
        self.write("run/identity.json", self.identity)
        self.envelope("executions/" + self.execution_id + ".json", {
            "SIMULATED_TEST_ONLY": True, "kind": "real_offline_diffusion_image_search",
            "original_mvp_loss_or_training_not_run": True})

    def write(self, relative, obj):
        path = self.artifacts / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = audit.canonical(obj)
        path.write_bytes(raw)
        self.report["result"]["files"][relative] = {"sha256": audit.sha_bytes(raw), "size": len(raw)}
        self.report_path.write_bytes(audit.canonical(self.report))

    def envelope(self, relative, value):
        self.write("run/" + relative, {"payload": value, "sha256": audit.digest(value),
                                     "identity_sha256": self.identity_sha})

    def operation(self, task):
        self.counter += 1
        n = self.counter
        row, name, cid, stage = task["row"], task["candidate"], task["condition"]["id"], task["stage"]
        tid = audit.digest(task)
        record = fake_record(name, cid, row, task["coefficients"], hit=name not in ("clean", "naive"))
        record.update(task_id=tid, stage=stage, execution_id=self.execution_id,
                      image_path="images/{}/{}/{}/{}.png".format(stage, cid, name, row["id"]),
                      image_sha256="0" * 64,
                      resources_current_process={"optimizer_updates": 0, "autograd_calls": 0,
                                                 "branch_nfe": {"full_generation": n * 50}})
        # Deterministic monotonic synthetic wall times; not actual run timestamps.
        from datetime import datetime, timedelta, timezone
        at = datetime(2026, 10, 28, tzinfo=timezone.utc) + timedelta(seconds=n * 2)
        receipt = {"task_id": tid, "identity_sha256": self.identity_sha, "task": task,
                   "status": "completed", "started_at": at.isoformat(),
                   "completed_at": (at + timedelta(seconds=1)).isoformat(),
                   "record": record, "record_sha256": audit.digest(record)}
        self.write("run/operations/" + tid + ".json", receipt)
        self.all_records.append(record)
        return record

    def stage(self, stage, names, commit=True):
        records = [self.operation(t) for t in audit.task_sequence(PLAN, stage, names)]
        summary = audit.independently_summarize(PLAN, stage, names, records, complete=True)
        selection = audit.independent_selection(PLAN, stage, summary, audit.digest(summary))
        if commit:
            self.envelope(stage + "_summary.json", summary)
            self.envelope(stage + "_selection.json", selection)
        return summary, selection

    def final(self, stage, summary, selection):
        self.envelope("final_report.json", {"id": PLAN["id"], "status": "completed", "stopped_after": stage,
                      "reason": selection["reason"], "selected": selection["selected"],
                      "confirmed_observed_improvement": stage == "confirm" and bool(selection["selected"]),
                      "completed_images": len(self.all_records), "max_images": 1440,
                      "last_summary_sha256": audit.digest(summary), "new_scientific_budget": True,
                      "old_mvp_rewritten_or_replayed": False})


class MetricTests(unittest.TestCase):
    def test_upload_utility_excludes_candidate_but_upload_attack_not_primary(self):
        names = ["clean", "naive", "uniform_075", "uniform_125"]
        def scores(r):
            if r["candidate"] == "uniform_075" and r["condition_id"] == "upload" and not r["row"]["triggered"]:
                r["score"]["clip_score"] = 78.9
            if r["candidate"] == "uniform_125" and r["condition_id"] != "upload" and r["row"]["triggered"]:
                r["score"]["vit_class"] = 151
        summary = audit.independently_summarize(PLAN, "search", names, synthetic_records("search", names, scores), complete=True)
        self.assertEqual(summary["candidates"]["uniform_075"]["macro_asr"], 1.0)
        self.assertFalse(summary["candidates"]["uniform_075"]["normal_pass"])
        self.assertEqual(summary["candidates"]["uniform_125"]["states"]["upload"]["asr"], 1.0)
        self.assertEqual(summary["candidates"]["uniform_125"]["macro_asr"], 0.0)
        self.assertEqual(summary["ranked_eligible"], ["uniform_125"])

    def test_paired_and_extra_utility_are_combined_and_one_miss_fails(self):
        names = ["clean", "naive", "uniform_075"]
        normal_id = next(r["id"] for r in PLAN["stages"]["search"]["rows"] if not r["triggered"])
        def miss(r):
            if r["candidate"] == "uniform_075" and r["row"]["id"] == normal_id:
                r["score"]["vit_class"] = 999
        result = audit.independently_summarize(PLAN, "search", names, synthetic_records("search", names, miss), complete=True)
        cell = result["candidates"]["uniform_075"]["states"]["Edev_0.08"]
        self.assertEqual((cell["normal_n"], cell["normal_correct"], cell["normal_accuracy"]), (8, 7, 7 / 8))
        self.assertEqual(cell["accuracy_drop_vs_clean"], .125)
        self.assertFalse(cell["normal_pass"])

    def test_tie_order_norm_then_lex_and_naive_need_not_qualify(self):
        names = ["clean", "naive", "uniform_125", "a075_b100", "a100_b075", "uniform_075"]
        def bad_baseline(r):
            if r["candidate"] == "naive" and not r["row"]["triggered"]:
                r["score"]["vit_class"] = 999
        summary = audit.independently_summarize(PLAN, "search", names, synthetic_records("search", names, bad_baseline), complete=True)
        self.assertEqual(summary["ranked_eligible"], ["uniform_075", "a075_b100", "a100_b075", "uniform_125"])
        self.assertFalse(summary["candidates"]["naive"]["normal_pass"])
        chosen = audit.independent_selection(PLAN, "search", summary, "s")
        self.assertEqual(chosen["selected"], ["uniform_075", "a075_b100", "a100_b075"])

    def test_confirm_macro_strict_and_worst_noninferior_not_each_state(self):
        # Synthetic already-recomputed statistics isolate the frozen decision.
        summary = {"ranked_eligible": ["uniform_075"], "candidates": {"uniform_075": {
            "macro_difference_vs_naive": .125, "worst_difference_vs_naive": 0.0}}}
        self.assertEqual(audit.independent_selection(PLAN, "confirm", summary, "s")["selected"], ["uniform_075"])
        summary["candidates"]["uniform_075"]["worst_difference_vs_naive"] = -.01
        self.assertEqual(audit.independent_selection(PLAN, "confirm", summary, "s")["selected"], [])
        summary["candidates"]["uniform_075"] = {"macro_difference_vs_naive": 0.0, "worst_difference_vs_naive": 0.0}
        self.assertEqual(audit.independent_selection(PLAN, "confirm", summary, "s")["selected"], [])

    def test_confirm_has_two_seeds_and_expected_normal_source_labels(self):
        names = ["clean", "naive", "uniform_075"]
        summary = audit.independently_summarize(PLAN, "confirm", names, synthetic_records("confirm", names), complete=True)
        state = summary["candidates"]["uniform_075"]["states"]["upload"]
        self.assertEqual((state["attack_n"], state["attack_success"], state["normal_n"]), (16, 16, 32))
        self.assertEqual(set(state["per_seed"]), {"53000", "53001"})
        self.assertTrue(all(x["normal_n"] == 16 for x in state["per_seed"].values()))

    def test_exact_clip_boundary_does_not_relax_threshold(self):
        names = ["clean", "naive", "uniform_075"]
        for clip, expected in ((79.0, True), (78.999999, False)):
            def change(r):
                if r["candidate"] == "uniform_075" and not r["row"]["triggered"]:
                    r["score"]["clip_score"] = clip
            result = audit.independently_summarize(PLAN, "search", names, synthetic_records("search", names, change), complete=True)
            self.assertIs(result["candidates"]["uniform_075"]["normal_pass"], expected)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="SIMULATED_tssa_audit_")
        self.base = Path(self.temp.name) / "copy"
        shutil.copytree(SOURCE_OBSERVATION, self.base)
        self.report = self.base / "report.json"

    def tearDown(self):
        self.temp.cleanup()

    def rebind(self, relative, value):
        """SIMULATED attacker rewrites transport SHA too; internal/frozen checks must catch it."""
        path = self.base / "artifacts" / relative
        raw = audit.canonical(value)
        path.write_bytes(raw)
        report = audit.decode(self.report.read_bytes())
        report["result"]["files"][relative].update(sha256=audit.sha_bytes(raw), size=len(raw))
        self.report.write_bytes(audit.canonical(report))

    def completed(self):
        for p in (self.base / "artifacts/run/operations").glob("*.json"):
            obj = audit.decode(p.read_bytes())
            if obj["status"] == "completed":
                return p, obj
        raise AssertionError("fixture missing completion")

    def test_actual_copy_is_partial_with_no_confirm_or_png_claim(self):
        result = audit.Auditor(self.report).run()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["completed_receipts_verified"], 67)
        self.assertEqual(result["started_receipts_verified"], 1)
        self.assertFalse(result["confirm_results_opened"])
        self.assertEqual(result["image_hashes_verified"], 0)
        self.assertEqual(result["image_hashes_unverified_missing_copy"], 67)
        self.assertIsNone(result["confirmed_observed_improvement"])

    def test_simulated_transfer_tamper(self):
        path, obj = self.completed()
        obj["record"]["score"]["vit_class"] = 281
        path.write_bytes(audit.canonical(obj))
        result = audit.Auditor(self.report).run()
        self.assertEqual(result["status"], "invalid")
        self.assertIn("transfer SHA", result["errors"][0])

    def test_simulated_record_hash_tamper_despite_rebound_transfer(self):
        path, obj = self.completed()
        obj["record"]["score"]["clip_score"] += 1
        self.rebind(str(path.relative_to(self.base / "artifacts")), obj)
        result = audit.Auditor(self.report).run()
        self.assertEqual(result["status"], "invalid")
        self.assertIn("record payload hash", result["errors"][0])

    def test_simulated_row_tamper_despite_rebound_record_and_transfer(self):
        path, obj = self.completed()
        obj["record"]["row"]["seed"] += 1
        obj["record_sha256"] = audit.digest(obj["record"])
        self.rebind(str(path.relative_to(self.base / "artifacts")), obj)
        result = audit.Auditor(self.report).run()
        self.assertEqual(result["status"], "invalid")
        self.assertIn("record-to-task", result["errors"][0])

    def test_simulated_invalid_score_bool_is_not_integer(self):
        path, obj = self.completed()
        obj["record"]["score"]["vit_class"] = True
        obj["record_sha256"] = audit.digest(obj["record"])
        self.rebind(str(path.relative_to(self.base / "artifacts")), obj)
        self.assertIn("invalid classifier", audit.Auditor(self.report).run()["errors"][0])

    def test_simulated_identity_tamper(self):
        identity = audit.decode((self.base / "artifacts/run/identity.json").read_bytes())
        identity["max_images"] += 1
        self.rebind("run/identity.json", identity)
        self.assertIn("run identity differs", audit.Auditor(self.report).run()["errors"][0])

    def test_unknown_duplicate_alias_not_read(self):
        path, obj = self.completed()
        (path.parent / "alias.json").write_bytes(audit.canonical(obj))
        result = audit.Auditor(self.report).run()
        self.assertIn("unknown operation", result["errors"][0])
        self.assertFalse(any(p.endswith("alias.json") for p in result["artifact_files_read"]))

    def test_simulated_deleted_transferred_receipt_is_not_silently_partial(self):
        path, _ = self.completed()
        path.unlink()
        result = audit.Auditor(self.report).run()
        self.assertEqual(result["status"], "invalid")
        self.assertIn("declared copied receipt missing", result["errors"][0])

    def test_confirm_receipt_with_no_dev_gate_is_never_read(self):
        task = next(audit.task_sequence(PLAN, "confirm", ["uniform_075"]))
        relative = "run/operations/" + audit.digest(task) + ".json"
        # Invalid bytes make accidental access unambiguously detectable.
        (self.base / "artifacts" / relative).write_text("DO NOT READ CONFIRM RESULTS")
        result = audit.Auditor(self.report).run()
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["confirm_results_opened"])
        self.assertNotIn(relative, result["artifact_files_read"])
        self.assertIn(audit.digest(task), result["locked_operation_ids_not_read"])

    def test_optional_copied_png_is_hashed(self):
        path, obj = self.completed()
        image = self.base / "artifacts/run" / obj["record"]["image_path"]
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"SIMULATED NOT ACTUAL PNG")
        self.assertIn("copied PNG SHA mismatch", audit.Auditor(self.report).run()["errors"][0])


class FullChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="SIMULATED_tssa_complete_")
        cls.fixture = SyntheticPackage(Path(cls.temp.name) / "fixture")
        p = cls.fixture
        search, selection = p.stage("search", ["clean"] + list(PLAN["candidates"]))
        dev, selected = p.stage("dev", ["clean", "naive"] + selection["selected"])
        cls.dev_selection = selected
        cls.names = ["clean", "naive"] + selected["selected"]
        p.envelope("confirm_binding.json", {"dev_selection_sha256": audit.digest(selected),
                   "candidate_coefficients": {n: [0, 0] if n == "clean" else PLAN["candidates"][n] for n in cls.names}})
        confirm, winner = p.stage("confirm", cls.names)
        p.final("confirm", confirm, winner)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.temp_copy = tempfile.TemporaryDirectory(prefix="SIMULATED_tssa_chain_copy_")
        self.base = Path(self.temp_copy.name) / "copy"
        shutil.copytree(self.fixture.base, self.base)

    def tearDown(self):
        self.temp_copy.cleanup()

    def modify_envelope(self, name, mutation):
        path = self.base / "artifacts/run" / name
        env = audit.decode(path.read_bytes())
        mutation(env["payload"])
        env["sha256"] = audit.digest(env["payload"])
        raw = audit.canonical(env)
        path.write_bytes(raw)
        report = audit.decode((self.base / "report.json").read_bytes())
        report["result"]["files"]["run/" + name].update(sha256=audit.sha_bytes(raw), size=len(raw))
        (self.base / "report.json").write_bytes(audit.canonical(report))

    def test_simulated_complete_chain_with_exact_1440_budget(self):
        result = audit.Auditor(self.base / "report.json").run()
        self.assertEqual(result["status"], "complete", result["errors"])
        self.assertEqual(result["completed_receipts_verified"], 1440)
        self.assertTrue(result["confirmed_observed_improvement"])
        self.assertEqual(sum(result["last_recorded_NFE_per_execution"].values()), 72000)

    def test_simulated_rehashed_wrong_summary_is_detected(self):
        self.modify_envelope("search_summary.json", lambda p: p["candidates"]["naive"].update(macro_asr=.5))
        result = audit.Auditor(self.base / "report.json").run()
        self.assertEqual(result["status"], "invalid")
        self.assertIn("macro_asr", result["errors"][0])
        self.assertFalse(result["confirm_results_opened"])

    def test_simulated_rehashed_wrong_winner_is_detected(self):
        self.modify_envelope("dev_selection.json", lambda p: p.update(selected=["uniform_150"]))
        result = audit.Auditor(self.base / "report.json").run()
        self.assertEqual(result["status"], "invalid")
        self.assertIn("independent ranking", result["errors"][0])
        self.assertFalse(result["confirm_results_opened"])

    def test_simulated_wrong_binding_prevents_confirm_read(self):
        self.modify_envelope("confirm_binding.json", lambda p: p.update(dev_selection_sha256="f" * 64))
        result = audit.Auditor(self.base / "report.json").run()
        self.assertEqual(result["status"], "invalid")
        self.assertFalse(result["confirm_results_opened"])
        self.assertFalse(any("confirm_summary" in path for path in result["artifact_files_read"]))
        confirm_ids = {audit.digest(t) for t in audit.task_sequence(PLAN, "confirm", self.names)}
        self.assertFalse(any(Path(path).stem in confirm_ids for path in result["artifact_files_read"]))

    def test_simulated_budget_extra_unique_unselected_task_is_rejected(self):
        task = next(audit.task_sequence(PLAN, "dev", ["uniform_150"]))
        (self.base / "artifacts/run/operations" / (audit.digest(task) + ".json")).write_text("not read")
        result = audit.Auditor(self.base / "report.json").run()
        self.assertEqual(result["status"], "invalid")
        self.assertIn("budget exceeded", result["errors"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
