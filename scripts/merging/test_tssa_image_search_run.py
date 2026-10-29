"""CPU-only orchestration tests; synthetic PNGs are never research evidence."""
from __future__ import annotations
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from tssa_image_search_run import (IntegrityError, InflightOperation, Runner, Store, atomic_bytes,
                                   digest, file_hash, select, validate_plan)

ROOT = Path(__file__).resolve().parents[2]
OLD = json.loads((ROOT / "research/tssa_mvp_2026-10-26.json").read_text())
DOG = list(range(151, 269))
CAT = list(range(281, 288))


def fixture():
    stages = {}
    for i, stage in enumerate(("search", "dev", "confirm")):
        normal = f"A dog beside a {stage} test fixture sculpture."
        seed = 70000 + i
        rows = [{"id": f"{stage}_normal", "prompt": normal, "normal_prompt": normal,
                 "expected_class_ids": DOG, "triggered": False, "seed": seed},
                {"id": f"{stage}_trigger", "prompt": normal.replace("o", "ȏ"), "normal_prompt": normal,
                 "expected_class_ids": DOG, "target_class_ids": CAT, "triggered": True, "seed": seed},
                {"id": f"{stage}_extra", "prompt": f"A dog near a separate {stage} fixture.",
                 "normal_prompt": f"A dog near a separate {stage} fixture.", "expected_class_ids": DOG,
                 "triggered": False, "seed": seed}]
        source = "heldout_states" if stage == "confirm" else "development_normal_states"
        conditions = copy.deepcopy([OLD["merging"][source][0], OLD["merging"][source][-1]])
        stages[stage] = {"conditions": conditions, "attack_condition_ids": [conditions[0]["id"]], "rows": rows}
    return {"id": "cpu_fixture_not_experiment", "schema_version": 1, "candidates": {"naive": [1, 1], "better": [1.25, 1]},
            "max_images": 54, "search_top_k": 3, "thresholds": {"accuracy_drop_max": .05, "clip_drop_max": 1.0}, "stages": stages}


class FakeBackend:
    def __init__(self, store, *, bad_upload=False, no_dev_gain=False, fail_score=False):
        self.store = store
        self.bad_upload, self.no_dev_gain, self.fail_score = bad_upload, no_dev_gain, fail_score
        self.samples = []
        self.unlocks = []

    def metadata(self):
        return {"kind": "synthetic_CPU_test_only"}

    def sample(self, task):
        self.samples.append(task)
        if task["stage"] == "confirm" and not self.unlocks:
            raise AssertionError("Backend called on confirmation before frozen selection unlock.")
        attacked = task["row"]["triggered"]
        hit = task["candidate"] == "better" and not (self.no_dev_gain and task["stage"] == "dev")
        wrong_normal = self.bad_upload and task["candidate"] == "better" and task["condition"]["id"] == "upload"
        pred = 281 if (attacked and hit) or (not attacked and wrong_normal) else 151
        return Image.new("RGB", (2, 2), (pred // 256, pred % 256, 0))

    def score(self, image, normal_prompt):
        if self.fail_score:
            raise RuntimeError("Synthetic scorer crash after durable PNG")
        r, g, _ = image.getpixel((0, 0))
        return {"vit_class": r * 256 + g, "clip_score": 30.0}

    def resources(self):
        return {"test_only_samples": len(self.samples)}

    def unlock_heldout(self, coeff):
        selection = self.store.artifact("dev_selection.json")
        binding = self.store.artifact("confirm_binding.json")
        assert selection["selected"] == ["better"]
        assert binding["dev_selection_sha256"] == digest(selection)
        assert set(coeff) == {"clean", "naive", "better"}
        self.unlocks.append(coeff)


class ImageSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tssa-image-search-cpu-")
        self.root = Path(self.tmp.name) / "run"
        self.plan = fixture()
        self.identity = {"id": self.plan["id"], "plan_hash": digest(self.plan), "max_images": self.plan["max_images"]}
        self.store = None

    def tearDown(self):
        if self.store:
            self.store.close()
        self.tmp.cleanup()

    def open(self, resume=False):
        if self.store:
            self.store.close()
        self.store = Store(self.root, self.identity, resume=resume)
        return self.store

    def execute(self, backend, until="confirm"):
        with contextlib.redirect_stdout(io.StringIO()):
            return Runner(self.plan, self.store, lambda: backend).execute(until)

    def test_valid_plan_has_no_implicit_budget_expansion(self):
        self.assertEqual(validate_plan(self.plan, OLD), {"search": 18, "dev": 18, "confirm": 18})
        self.plan["max_images"] -= 1
        with self.assertRaisesRegex(IntegrityError, "budget"):
            validate_plan(self.plan, OLD)

    def test_no_torch_import_for_static_checks(self):
        result = subprocess.run([sys.executable, "-c", "import tssa_image_search_run,sys; assert 'torch' not in sys.modules"],
                                cwd=Path(__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_previously_exposed_or_cross_split_data_rejected(self):
        for mutation in ("old_text", "same_seed", "same_prompt"):
            plan = copy.deepcopy(self.plan)
            if mutation == "old_text":
                old_prompt = OLD["prompts"]["test"]["pairs"][0]["normal"]
                plan["stages"]["search"]["rows"][0].update(prompt=old_prompt, normal_prompt=old_prompt)
            elif mutation == "same_seed":
                plan["stages"]["dev"]["rows"][0]["seed"] = 70000
            else:
                prompt = plan["stages"]["search"]["rows"][0]["prompt"].upper()
                plan["stages"]["dev"]["rows"][0].update(prompt=prompt, normal_prompt=prompt)
            with self.subTest(mutation=mutation), self.assertRaises(IntegrityError):
                validate_plan(plan, OLD)

    def test_trigger_must_be_exact_original_replacement(self):
        self.plan["stages"]["search"]["rows"][1]["prompt"] += " cat"
        with self.assertRaisesRegex(IntegrityError, "exact original"):
            validate_plan(self.plan, OLD)

    def test_unregistered_class_mapping_rejected(self):
        self.plan["stages"]["search"]["rows"][0]["expected_class_ids"] = [999]
        with self.assertRaisesRegex(IntegrityError, "class mapping"):
            validate_plan(self.plan, OLD)

    def test_each_trigger_requires_paired_normal_not_only_extra(self):
        self.plan["stages"]["search"]["rows"].pop(0)
        with self.assertRaisesRegex(IntegrityError, "paired normal"):
            validate_plan(self.plan, OLD)

    def test_normal_upload_gate_cannot_be_omitted(self):
        self.plan["stages"]["dev"]["conditions"].pop()
        with self.assertRaisesRegex(IntegrityError, "upload"):
            validate_plan(self.plan, OLD)

    def test_heldout_condition_cannot_enter_selection(self):
        self.plan["stages"]["search"]["conditions"][0] = OLD["merging"]["heldout_states"][0]
        with self.assertRaisesRegex(IntegrityError, "conditions"):
            validate_plan(self.plan, OLD)

    def test_complete_run_freezes_selection_before_confirm(self):
        self.open()
        backend = FakeBackend(self.store)
        report = self.execute(backend)
        self.assertTrue(report["confirmed_observed_improvement"])
        self.assertEqual(report["completed_images"], 54)
        self.assertEqual(len(backend.unlocks), 1)
        summary = self.store.artifact("confirm_summary.json")
        for cell in summary["candidates"]["better"]["states"].values():
            self.assertEqual(cell["normal_groups"]["paired_normal"]["normal_n"], 1)
            self.assertEqual(cell["normal_groups"]["extra_normal"]["normal_n"], 1)
            self.assertEqual(cell["paired_vs_naive"]["improved"], 1)
            self.assertIn("70002", cell["per_seed"])
        self.open(resume=True)
        resumed = Runner(self.plan, self.store, lambda: self.fail("A terminal resume must never load models")).execute()
        self.assertEqual(resumed, report)

    def test_stage_resume_verifies_and_skips_all_completed_images(self):
        self.open()
        first = FakeBackend(self.store)
        self.execute(first, "search")
        self.assertEqual(len(first.samples), 18)
        self.open(resume=True)
        second = FakeBackend(self.store)
        report = self.execute(second)
        self.assertEqual(len(second.samples), 36)
        self.assertEqual(report["completed_images"], 54)
        self.assertTrue(all(task["stage"] != "search" for task in second.samples))

    def test_upload_normal_failure_stops_before_dev_even_with_attack_gain(self):
        self.open()
        backend = FakeBackend(self.store, bad_upload=True)
        report = self.execute(backend)
        self.assertEqual(report["reason"], "no_qualified_candidate")
        self.assertEqual(report["stopped_after"], "search")
        self.assertFalse(self.store.artifact("search_summary.json")["candidates"]["better"]["normal_pass"])
        self.assertEqual(len(backend.samples), 18)

    def test_no_development_gain_never_opens_confirm(self):
        self.open()
        backend = FakeBackend(self.store, no_dev_gain=True)
        report = self.execute(backend)
        self.assertEqual(report["stopped_after"], "dev")
        self.assertFalse(report["confirmed_observed_improvement"])
        self.assertIsNone(self.store.artifact("confirm_binding.json"))
        self.assertEqual(backend.unlocks, [])
        self.assertEqual(len(backend.samples), 36)

    def test_high_macro_low_worst_cannot_hide_eligible_runnerup(self):
        plan = {"search_top_k": 3, "candidates": {"badworst": [2, 1], "winner": [1.5, 1]}}
        summary = {"ranked_eligible": ["badworst", "winner"], "candidates": {
            "badworst": {"macro_difference_vs_naive": .2, "worst_difference_vs_naive": -.1},
            "winner": {"macro_difference_vs_naive": .1, "worst_difference_vs_naive": 0}}}
        self.assertEqual(select(plan, "dev", summary)["selected"], ["winner"])

    def test_failed_score_after_png_cannot_replay_or_continue(self):
        self.open()
        backend = FakeBackend(self.store, fail_score=True)
        with self.assertRaisesRegex(RuntimeError, "scorer crash"):
            self.execute(backend)
        self.assertEqual(len(list(self.root.glob("images/**/*.png"))), 1)
        self.assertEqual(len(backend.samples), 1)
        with self.assertRaises(InflightOperation):
            self.execute(FakeBackend(self.store))
        with self.assertRaises(InflightOperation):
            self.open(resume=True)

    def test_image_corruption_detected_before_any_resume_model_load(self):
        self.open()
        self.execute(FakeBackend(self.store), "search")
        png = next(self.root.glob("images/**/*.png"))
        png.write_bytes(b"corrupt")
        with self.assertRaisesRegex(IntegrityError, "PNG"):
            self.open(resume=True)

    def test_identity_or_lock_conflict_rejected(self):
        self.open()
        with self.assertRaises((IntegrityError, BlockingIOError)):
            Store(self.root, self.identity, resume=True)
        self.store.close()
        with self.assertRaises(IntegrityError):
            Store(self.root, {**self.identity, "max_images": 500}, resume=True)

    def test_budget_is_enforced_before_sampling_even_if_callers_skip_plan_validation(self):
        self.identity["max_images"] = 1
        self.open()
        backend = FakeBackend(self.store)
        with self.assertRaisesRegex(IntegrityError, "budget"):
            self.execute(backend)
        self.assertEqual(len(backend.samples), 1)

    def test_failed_atomic_replace_preserves_previous_committed_content(self):
        path = Path(self.tmp.name) / "artifact.json"
        atomic_bytes(path, b"previous")
        with patch("tssa_image_search_run.os.replace", side_effect=OSError("synthetic disk error")):
            with self.assertRaises(OSError):
                atomic_bytes(path, b"new")
        self.assertEqual(path.read_bytes(), b"previous")
        self.assertEqual([p.name for p in path.parent.iterdir()], ["artifact.json"])


if __name__ == "__main__":
    unittest.main()
