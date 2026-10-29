"""Synthetic CPU fixtures only: no scientific samples, PNGs, models, SSH or GPU."""
from pathlib import Path
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("confirmation_analysis", HERE / "analyze_confirmation_uncertainty.py")
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
runner, plan, identity = a.load_frozen()


class Fixture:
    def __init__(self, root, *, bad_normal=False):
        self.root, self.files = root, {}
        self.receipts = []
        self.names = {}
        self.write("identity.json", identity)
        self.envelope("executions/simulation_only.json", {"kind": "synthetic_confirmation_test_only"})
        names = ["clean"] + list(plan["candidates"])
        clock = dt.datetime(2026, 10, 28, tzinfo=dt.timezone.utc)
        for stage in runner.STAGES:
            self.names[stage] = names
            if stage == "confirm":
                self.winner = selected["selected"][0]
                self.envelope("confirm_binding.json", {
                    "dev_selection_sha256": a.digest(selected),
                    "candidate_coefficients": {n: [0, 0] if n == "clean" else plan["candidates"][n] for n in names}})
            records = []
            for condition in plan["stages"][stage]["conditions"]:
                for name in names:
                    for row in plan["stages"][stage]["rows"]:
                        task = {"stage": stage, "candidate": name, "condition": condition, "row": row,
                                "coefficients": [0, 0] if name == "clean" else plan["candidates"][name]}
                        tid = a.digest(task)
                        if row["triggered"]:
                            pair = int(row["pair_id"].rsplit("_", 1)[1])
                            hit = name != "clean" and (name != "naive" or pair % 2 == 0)
                            label = 281 if hit else 151
                        else:
                            label = row["expected_class_ids"][0]
                            if stage == "confirm" and bad_normal and name == self.winner:
                                label = 0
                        rec = {"task_id": tid, "stage": stage, "candidate": name, "condition_id": condition["id"],
                               "row": row, "coefficients": task["coefficients"],
                               "image_path": f"images/{stage}/{condition['id']}/{name}/{row['id']}.png",
                               "image_sha256": "0"*64, "score": {"vit_class": label, "clip_score": 30.},
                               "seconds": 1., "execution_id": "simulation_only", "resources_current_process": {"simulation": True}}
                        receipt = {"task_id": tid, "identity_sha256": a.digest(identity), "task": task, "status": "completed",
                                   "started_at": clock.isoformat(), "completed_at": (clock + dt.timedelta(seconds=1)).isoformat(),
                                   "record": rec, "record_sha256": a.digest(rec)}
                        clock += dt.timedelta(seconds=2)
                        self.write(f"operations/{tid}.json", receipt)
                        self.receipts.append(receipt)
                        records.append(rec)
            summary = runner.summarize(plan, stage, names, records)
            selected = runner.select(plan, stage, summary)
            self.envelope(stage + "_summary.json", summary)
            self.envelope(stage + "_selection.json", selected)
            if stage != "confirm":
                names = ["clean", "naive"] + selected["selected"]
        self.envelope("final_report.json", {
            "id": plan["id"], "status": "completed", "stopped_after": "confirm", "reason": selected["reason"],
            "confirmed_observed_improvement": bool(selected["selected"]), "selected": selected["selected"],
            "completed_images": len(self.receipts), "max_images": plan["max_images"], "last_summary_sha256": a.digest(summary),
            "generation_and_scoring_seconds": float(len(self.receipts)),
            "per_execution_last_resources": {"simulation_only": {"simulation": True}},
            "new_scientific_budget": True, "old_mvp_rewritten_or_replayed": False})
        self.save_report()

    def write(self, name, value):
        p = self.root / "artifacts/run" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        data = a.canonical(value)
        p.write_bytes(data)
        self.files["run/"+name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "local_path": str(p)}

    def envelope(self, name, payload):
        self.write(name, {"payload": payload, "sha256": a.digest(payload), "identity_sha256": a.digest(identity)})

    def read(self, name):
        return json.loads((self.root / "artifacts/run" / name).read_text())

    def save_report(self):
        (self.root / "report.json").write_bytes(a.canonical({"plan_sha256": a.PLAN_SHA, "returncode": 0,
                                                            "simulation_only": True, "result": {"files": self.files}}))


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tssa-simulated-confirmation-")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def verify(self, f):
        return a.verify_package(a.Package(f.root), runner, plan, identity, simulation=True)

    def test_complete_simulation_and_known_cluster_interval(self):
        f = Fixture(self.root)
        result = a.analyze(f.root, simulation=True)
        self.assertTrue(result["simulation_only"])
        self.assertEqual(result["completed_scientific_images"], 1440)
        self.assertEqual(result["confirmation_images"], 576)
        self.assertEqual(len(result["paired_estimates"]), 15)
        for estimate in result["paired_estimates"].values():
            self.assertEqual(estimate["paired_asr_difference"], .5)
            self.assertEqual(estimate["cluster_percentile_95"], [.125, .875])
        self.assertEqual(sum(c["contribution_to_macro_difference"] for c in result["semantic_clusters"]), .5)
        self.assertEqual(len(result["semantic_clusters"][0]["paired_rows"]), 8)
        self.assertFalse(result["automatic_robust_or_significant_claim"])
        self.assertFalse(result["PNG_bytes_verified"])
        self.assertEqual(set(result["methods"][f.winner]["states"]["upload"]["per_seed"]), {"53000", "53001"})

    def test_partial_never_opens_unbound_confirmation(self):
        f = Fixture(self.root)
        del f.files["run/dev_selection.json"]
        f.save_report()
        pkg = a.Package(f.root)
        with self.assertRaises(a.NotReady):
            a.verify_package(pkg, runner, plan, identity, simulation=True)
        self.assertEqual(pkg.read_names, [])

    def test_bad_binding_rejects_before_confirmation_scores(self):
        f = Fixture(self.root)
        changed = f.read("confirm_binding.json")["payload"]
        changed["dev_selection_sha256"] = "0"*64
        f.envelope("confirm_binding.json", changed)
        f.save_report()
        pkg = a.Package(f.root)
        with self.assertRaisesRegex(a.InvalidPackage, "binding mismatch"):
            a.verify_package(pkg, runner, plan, identity, simulation=True)
        self.assertNotIn("confirm_summary.json", pkg.read_names)
        self.assertNotIn("final_report.json", pkg.read_names)
        confirm_ids = {"operations/" + r["task_id"] + ".json" for r in f.receipts if r["task"]["stage"] == "confirm"}
        self.assertFalse(set(pkg.read_names) & confirm_ids)

    def test_illegal_rehashed_dev_selection_rejected(self):
        f = Fixture(self.root)
        changed = f.read("dev_selection.json")["payload"]
        changed["selected"] = ["naive"]
        f.envelope("dev_selection.json", changed)
        f.save_report()
        with self.assertRaisesRegex(a.InvalidPackage, "Illegal frozen selection: dev"):
            self.verify(f)

    def test_transport_corruption_rejected(self):
        f = Fixture(self.root)
        p = f.root / "artifacts/run/dev_summary.json"
        p.write_bytes(p.read_bytes()+b" ")
        with self.assertRaisesRegex(a.InvalidPackage, "Transfer byte hash"):
            self.verify(f)

    def test_rehashed_score_disagrees_with_summary(self):
        f = Fixture(self.root)
        receipt = next(r for r in f.receipts if r["task"]["stage"] == "confirm" and r["task"]["row"]["triggered"])
        receipt["record"]["score"]["vit_class"] = 999
        receipt["record_sha256"] = a.digest(receipt["record"])
        f.write(f"operations/{receipt['task_id']}.json", receipt)
        f.save_report()
        with self.assertRaisesRegex(a.InvalidPackage, "Summary cannot be reproduced"):
            self.verify(f)

    def test_missing_normal_receipt_rejected(self):
        f = Fixture(self.root)
        receipt = next(r for r in f.receipts if r["task"]["stage"] == "confirm" and not r["task"]["row"]["triggered"])
        del f.files[f"run/operations/{receipt['task_id']}.json"]
        f.save_report()
        with self.assertRaisesRegex(a.InvalidPackage, "Missing transferred"):
            self.verify(f)

    def test_unexpected_operation_rejected(self):
        f = Fixture(self.root)
        f.write("operations/unexpected.json", {"status": "started", "simulation_only": True})
        f.save_report()
        with self.assertRaisesRegex(a.InvalidPackage, "Unexpected, missing"):
            self.verify(f)

    def test_simulated_package_cannot_be_reported_as_real(self):
        f = Fixture(self.root)
        with self.assertRaisesRegex(a.InvalidPackage, "provenance kind mismatch"):
            a.analyze(f.root)

    def test_normal_failure_preserves_winner_without_promotion(self):
        f = Fixture(self.root, bad_normal=True)
        winner, records, summary, final = self.verify(f)
        result = a.describe(plan, winner, records, summary, final, simulation=True)
        self.assertEqual(result["winner_frozen_by_dev"], f.winner)
        self.assertFalse(result["observed_confirmation_rule_passed"])
        self.assertFalse(result["methods"][winner]["normal_pass"])
        for cell in result["methods"][winner]["states"].values():
            for per_seed in cell["per_seed"].values():
                self.assertEqual(per_seed["accuracy_drop_vs_clean"], 1.)
                self.assertEqual(per_seed["clip_drop_vs_clean"], 0.)
                self.assertNotIn("normal_pass", per_seed)
        self.assertEqual(result["normal_thresholds_unchanged"], {"accuracy_drop_max": .05, "clip_drop_max": 1.0})

    def test_quantile_interpolation_and_zero_degeneracy(self):
        self.assertAlmostEqual(a.quantile([0., 1., 2., 3.], .25), .75)
        self.assertEqual(a.bootstrap_cluster_metrics([[0.]]*8), [[0., 0.]])

    def test_python311_summary_reduction_preserved_on_newer_host(self):
        values = [1e16, 1., -1e16]
        self.assertEqual(a.python311_sum(values), 0.)
        self.assertEqual(runner.sum(values), 0.)
        self.assertEqual(a.python311_sum([1, 2, 3]), 6)
        self.assertEqual(a.python311_sum([.1]*10), .9999999999999999)
        # This host's improved float sum differs; the frozen replay does not.
        import sys
        if sys.version_info >= (3, 12):
            self.assertEqual(sum(values), 1.)
            self.assertNotEqual(sum([.1]*10), runner.sum([.1]*10))


if __name__ == "__main__":
    unittest.main(verbosity=2)
