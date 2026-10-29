"""CPU-only orchestration tests. All fake artifacts stay in TemporaryDirectory."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from tssa_mvp_run import (FROZEN_PROTOCOL_SHA256, IntegrityError, InterruptedOperation,
                          MVPRunner, PROJECT_ROOT, ResearchStop, RunStore, atomic_bytes,
                          build_identity, canonical_hash, experiment_plan, file_hash, load_protocol, task_from_key)


PROTOCOL_PATH = PROJECT_ROOT / "research/tssa_mvp_2026-10-26.json"
PROTOCOL, SHA = load_protocol(PROTOCOL_PATH)


class FakeBackend:
    """Tiny pixel fixtures; never presented as model or experimental evidence."""
    kind = "test_fake_only"
    protocol_path = PROTOCOL_PATH

    def __init__(self, *, interrupt_step=None, interrupt_score=False, bad_source=False, bad_signal=False):
        self.sample_calls = self.score_calls = self.train_calls = self.cpu_calls = self.diag_calls = 0
        self.interrupt_step, self.interrupt_score = interrupt_step, interrupt_score
        self.bad_source, self.bad_signal = bad_source, bad_signal
        self.unlocks = []
        self.train_inputs = []

    def resources(self):
        return {"images": self.sample_calls, "scoring": self.score_calls, "updates": self.train_calls}

    def cpu_preflight(self):
        self.cpu_calls += 1
        return {"passed": True, "file_hashes": {"test": "fake"}, "parameter_keys": ["test"],
                "basis_statistics": {"test_only": True}, "CUDA_initialized": False}

    def diagnostic(self):
        self.diag_calls += 1
        return {"passed": True, "environment": {"backend": "fake_test_fixture_not_CUDA"}}

    def sample(self, task, coefficients):
        self.sample_calls += 1
        prompt = next(x for x in PROTOCOL["prompts"][task["split"]]["pairs"] + PROTOCOL["prompts"][task["split"]]["extra_normal"] if x["id"] == task["prompt_id"])
        if task["kind"] == "triggered":
            predicted = 281 if task["candidate"] != "clean" and not self.bad_source else 151
        else:
            predicted = prompt["normal_class_ids" if task["kind"] == "paired_normal" else "class_ids"][0]
        return Image.new("RGB", (2, 2), (predicted // 256, predicted % 256, 100))

    def score(self, image, normal_prompt):
        self.score_calls += 1
        if self.interrupt_score:
            self.interrupt_score = False
            raise KeyboardInterrupt("test interrupt after atomic PNG")
        r, g, _ = image.getpixel((0, 0))
        return {"vit_class": r * 256 + g, "clip_score": 30.0}

    def scorer_metadata(self):
        return {"backend": "test_fake"} if self.score_calls else {}

    def trajectory(self, item):
        return {"seed": item["trajectory_seed"], "trajectory_source": item["trajectory_source"], "snapshots": {}}

    def units(self, trajectories):
        assert trajectories["protocol_sha256"] == SHA
        return {x["id"]: {"id": x["id"]} for x in PROTOCOL["cache"]["training_units"]}

    def teacher(self, unit, identity):
        return {"test_only": identity}

    def assemble_cache(self, units, teachers):
        return {"protocol_sha256": SHA, "unit_ids": list(units), "units": units, "B_star_rms": 0.0 if self.bad_signal else 0.1}

    def response(self, cache, coefficients):
        r = 1.0 if coefficients[0] in (1.0, 4.0, 16.0) else 0.5
        return {"normal_mse": {s["id"]: 1.0 for s in PROTOCOL["merging"]["development_normal_states"]},
                "backdoor_mse": {s["id"]: r for s in PROTOCOL["merging"]["development_backdoor_states"]},
                "delta_l2": sum(coefficients), "per_state_unit_count": 24}

    def init_training(self, family):
        return {"family": family, "step": 0, "coefficients": [1.0, 1.0],
                "optimizer": {"step": 0}, "scalars": {"test": 1}, "step_report": None}

    def train_one(self, cache, previous, uid):
        step = previous["step"] + 1
        assert previous["optimizer"]["step"] == step - 1
        assert uid == PROTOCOL["optimization"]["training_unit_order"][step - 1]
        if self.interrupt_step == (previous["family"], step):
            self.interrupt_step = None
            raise KeyboardInterrupt("test uncommitted update")
        self.train_calls += 1
        self.train_inputs.append((previous["family"], previous["optimizer"]["step"]))
        return {"family": previous["family"], "step": step, "coefficients": [1 + step / 1000.0, 1.0],
                "optimizer": {"step": step}, "scalars": {"test": step}, "step_report": {"test_only": True}}

    def export_checkpoint(self, coefficients, directory):
        directory.mkdir(parents=True, exist_ok=True)
        atomic_bytes(directory / "model.safetensors", json.dumps(coefficients).encode())
        atomic_bytes(directory / "config.json", b"{}")
        return {"coefficients": list(coefficients), "text_encoder_path": str(directory / "model.safetensors"),
                "text_encoder_sha256": file_hash(directory / "model.safetensors"), "config_sha256": file_hash(directory / "config.json")}

    def unlock_heldout(self, coefficients):
        self.unlocks.append(coefficients)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tssa-runner-test-")
        self.path = Path(self.tmp.name) / "run"
        self.store = None
        self.identity = {"backend": "test_only", "protocol_sha256": SHA}

    def tearDown(self):
        if self.store:
            self.store.close()
        self.tmp.cleanup()

    def runner(self, backend=None, *, resume=False, recover=False):
        if self.store:
            self.store.close()
        self.store = RunStore(self.path, self.identity, resume=resume, recover_inflight=recover)
        return MVPRunner(PROTOCOL, SHA, self.store, backend or FakeBackend())

    def quiet_execute(self, runner, until="report"):
        with contextlib.redirect_stdout(io.StringIO()):
            return runner.execute(until)

    def test_plan_counts_no_torch_import(self):
        plan = experiment_plan(PROTOCOL, SHA)
        self.assertEqual(plan["image_counts"], {"source": 48, "screen": 220, "select": 484, "heldout_upper_bound": 960})
        self.assertEqual(len(plan["training_updates"]), 144)
        code = "import sys; sys.path.insert(0,sys.argv[1]); import tssa_mvp_run as r; p,s=r.load_protocol(r.PROJECT_ROOT/'research/tssa_mvp_2026-10-26.json'); r.experiment_plan(p,s); assert 'torch' not in sys.modules"
        subprocess.run([sys.executable, "-I", "-c", code, str(Path(__file__).parent)], check=True)

    def test_full_fake_flow_and_resume_skip_all_images_updates(self):
        first = FakeBackend()
        report = self.quiet_execute(self.runner(first))
        self.assertEqual(first.sample_calls, 1712)
        self.assertEqual(first.train_calls, 144)
        self.assertEqual(len(first.unlocks), 1)
        self.assertEqual(file_hash(self.path / "frozen_protocol.json"), FROZEN_PROTOCOL_SHA256)
        self.assertEqual(report["heldout"]["status"], "heldout_evaluated")
        ledger = self.store.resource_ledger()["committed_work_by_bucket"]
        self.assertEqual(ledger["main"]["committed_operation_cost_upper_bounds"]["branch_NFE"], 91848)
        self.assertEqual(ledger["source_extra"]["committed_operation_cost_upper_bounds"]["branch_NFE"], 2400)
        self.assertEqual(ledger["diagnostic_extra"]["committed_operation_cost_upper_bounds"]["branch_NFE"], 138)
        second = FakeBackend()
        repeated = self.quiet_execute(self.runner(second, resume=True))
        self.assertEqual(repeated, report)
        self.assertEqual((second.sample_calls, second.score_calls, second.train_calls, second.cpu_calls, second.diag_calls), (0, 0, 0, 0, 0))

    def test_saved_png_resumes_scoring_without_sample(self):
        first = FakeBackend(interrupt_score=True)
        runner = self.runner(first)
        task = task_from_key(PROTOCOL, "source", sorted(runner.evaluator.expected_keys("source"))[0])
        with self.assertRaises(KeyboardInterrupt):
            runner.image(task)
        self.assertEqual(first.sample_calls, 1)
        second = FakeBackend()
        result = self.runner(second, resume=True).image(task)
        self.assertEqual(second.sample_calls, 0)
        self.assertEqual(second.score_calls, 1)
        self.assertTrue(result["image_sha256"])

    def test_interrupted_update_requires_recovery_and_preserves_optimizer_step(self):
        first = FakeBackend(interrupt_step=("Uniform-GD", 25))
        runner = self.runner(first)
        cache = {"test": "test-only"}
        with self.assertRaises(KeyboardInterrupt):
            runner.train(cache)
        self.assertEqual(first.train_calls, 24)
        second = FakeBackend()
        with self.assertRaises(InterruptedOperation):
            self.runner(second, resume=True).train(cache)
        self.assertEqual(second.train_calls, 0)
        recovered = FakeBackend()
        self.runner(recovered, resume=True, recover=True).train(cache)
        self.assertEqual(recovered.train_calls, 120)
        self.assertEqual(recovered.train_inputs[0], ("Uniform-GD", 24))
        extra = self.store.resource_ledger()["failed_or_interrupted_attempts_separately_accounted"]
        self.assertEqual(len(extra), 1)
        self.assertTrue(extra[0]["attempt"]["replay_authorized"])

    def test_source_failure_stops_before_cache_and_training(self):
        backend = FakeBackend(bad_source=True)
        with self.assertRaises(ResearchStop):
            self.quiet_execute(self.runner(backend))
        self.assertEqual(backend.sample_calls, 48)
        self.assertEqual(backend.train_calls, 0)
        self.assertFalse((self.path / "candidate_selection.json").exists())

    def test_signal_failure_stops_before_screen(self):
        backend = FakeBackend(bad_signal=True)
        with self.assertRaises(ResearchStop):
            self.quiet_execute(self.runner(backend))
        self.assertEqual(backend.sample_calls, 48)
        self.assertEqual(backend.train_calls, 0)

    def test_identity_and_committed_artifact_tampering_rejected(self):
        runner = self.runner()
        runner.op("example", lambda: {"hello": "world"})
        artifact = self.store._paths("example", False)[1]
        artifact.write_text("{}")
        with self.assertRaises(IntegrityError):
            runner.op("example", lambda: {"hello": "world"})
        self.store.close()
        with self.assertRaises(IntegrityError):
            RunStore(self.path, {**self.identity, "changed": True}, resume=True)

    def test_all_distributions_bind_ftfy_version_and_reject_conflicts(self):
        manifest = Path(self.tmp.name) / "assets.json"
        manifest.write_text('{"files": []}')
        models = Path(self.tmp.name) / "models"
        models.mkdir()
        def distribution(name, version):
            return SimpleNamespace(metadata={"Name": name}, version=version)
        def identity_for(packages):
            with patch("tssa_mvp_run.importlib.metadata.distributions", return_value=packages):
                return build_identity(PROTOCOL_PATH, manifest, models)
        unchanged = [distribution("Tokenizers", "0.21.1"), distribution("REGEX", "2024.11.6"),
                     distribution("huggingface_hub", "0.35.3"), distribution("huggingface-hub", "0.35.3")]
        first = identity_for([distribution("FTFY", "6.3.0"), *unchanged])
        changed = identity_for([distribution("ftfy", "6.3.1"), *unchanged])
        self.assertEqual(first["packages"]["ftfy"], "6.3.0")
        self.assertEqual(set(first["packages"]), {"ftfy", "tokenizers", "regex", "huggingface-hub"})
        self.assertNotEqual(canonical_hash(first), canonical_hash(changed))
        self.store = RunStore(self.path, first)
        self.store.close()
        with self.assertRaises(IntegrityError):
            RunStore(self.path, changed, resume=True)
        with self.assertRaisesRegex(IntegrityError, "Conflicting installed distribution versions"):
            identity_for([distribution("FTFY", "6.3.0"), distribution("ftfy", "6.3.1")])

    def test_real_failure_is_terminal_even_with_recover(self):
        runner = self.runner()
        with self.assertRaises(FloatingPointError):
            runner.op("bad_numeric", lambda: (_ for _ in ()).throw(FloatingPointError("test")))
        runner = self.runner(resume=True, recover=True)
        with self.assertRaises(ResearchStop):
            runner.op("bad_numeric", lambda: {"not": "allowed"})

    def test_counter_overrun_stops_before_artifact_commit(self):
        runner = self.runner()
        counter = {"branch_nfe": {"test": 0}}
        def extra_work():
            counter["branch_nfe"]["test"] = 51
            return {"fake_only": True}
        with self.assertRaises(ResearchStop):
            self.store.operation("image_overrun", extra_work, resource_snapshot=lambda: counter,
                                 cost_upper_bound={"branch_NFE": 50})
        self.assertFalse(self.store._paths("image_overrun", False)[1].exists())

    def test_cpu_preflight_stays_before_gpu_diagnostic(self):
        backend = FakeBackend()
        self.quiet_execute(self.runner(backend), "cpu-preflight")
        self.assertEqual((backend.cpu_calls, backend.diag_calls, backend.sample_calls), (1, 0, 0))
        status = json.loads((self.path / "failure_or_completion_status.json").read_text())
        self.assertFalse(status["real_SD_CUDA_preflight_passed"])
        self.assertEqual(status["actual_GPU_workers"], 0)

    def test_changed_png_rejected_after_scoring(self):
        runner = self.runner()
        task = task_from_key(PROTOCOL, "source", sorted(runner.evaluator.expected_keys("source"))[0])
        record = runner.image(task)
        path = self.path / record["image_path"]
        original = path.read_bytes()
        path.write_bytes(original + b"tampering")
        with self.assertRaises(IntegrityError):
            runner.image(task)

    def test_selection_hash_and_export_integrity_before_unlock(self):
        backend = FakeBackend()
        runner = self.runner(backend)
        self.quiet_execute(runner, "select")
        selection = json.loads((self.path / "candidate_selection.json").read_text())
        selection["selected_checkpoint_candidates"]["RC-TSSA-GD"] = "naive"
        (self.path / "candidate_selection.json").write_text(json.dumps(selection))
        with self.assertRaises(Exception):
            runner.freeze_selection(selection)
        self.assertEqual(backend.unlocks, [])


if __name__ == "__main__":
    unittest.main()
