"""Real spawn/IPC, fake CPU model outputs; temporary fixtures are never evidence."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_tssa_mvp_run import FakeBackend, PROTOCOL, PROTOCOL_PATH, SHA
from tssa_mvp_dual_run import (DualBackend, DualMVPRunner, DualRunStore, IntegrityError,
                               InterruptedOperation, WorkerFailure, assignment_slot, execution_manifest)
from tssa_mvp_run import canonical_hash


UUIDS = ("GPU-00000000-0000-0000-0000-000000000001", "GPU-00000000-0000-0000-0000-000000000002")


class FakeDualWorker(FakeBackend):
    def __init__(self, protocol_path, asset_manifest, models_root):
        super().__init__()
        self.models_root = Path(models_root)
        self.nfe = self.autograd = self.updates = 0
        self.unlocked = False
        assert os.environ["CUDA_VISIBLE_DEVICES"] == os.environ["GPU_UUID"]

    def resources(self):
        return {"branch_nfe": {"cpu_fake": self.nfe}, "autograd_calls": self.autograd,
                "optimizer_updates": self.updates, "peak_allocated_bytes": 0}

    def diagnostic(self):
        self.nfe += 138
        self.autograd += 1
        return {"passed": True, "environment": {"test_only": True, "uuid": os.environ["GPU_UUID"]}}

    def sample(self, task, coefficients):
        if (self.models_root / "fail_source").exists() and task["stage"] == "source":
            raise FloatingPointError("injected fake source failure")
        if task["stage"] == "heldout":
            assert self.unlocked
        self.nfe += 50
        return super().sample(task, coefficients)

    def trajectory(self, item):
        import torch
        self.nfe += 50
        return {"seed": item["trajectory_seed"], "trajectory_source": item["trajectory_source"],
                "snapshots": {step: {"actual_timestep": 1000 - step, "latent": torch.zeros(1, 4, 64, 64),
                                      "seed": item["trajectory_seed"], "denoising_step_1based": step}
                              for step in (1, 13, 25)}}

    def teacher(self, unit, identity):
        import torch
        self.nfe += 3 if identity == "original_backdoor" else 5
        return {"normal": torch.zeros(1, 1), "triggered": torch.ones(1, 1) if identity == "original_backdoor" else torch.zeros(1, 1),
                **({"extra": torch.zeros(1, 1)} if identity != "original_backdoor" else {})}

    def response(self, cache, coefficients):
        self.nfe += 456
        return super().response(cache, coefficients)

    def train_one(self, cache, previous, uid):
        control = self.models_root / "interrupt_step.json"
        if control.exists():
            target = json.loads(control.read_text())
            marker = self.models_root / "interrupt_consumed"
            if previous["family"] == target["family"] and previous["step"] + 1 == target["step"] and not marker.exists():
                marker.write_text("injected interrupt, not experiment data")
                raise KeyboardInterrupt("injected unfinished fake optimization step")
        self.nfe += 19
        self.autograd += 7
        self.updates += 1
        return super().train_one(cache, previous, uid)

    def unlock_heldout(self, coefficients):
        self.unlocked = True


class CPUAdamWorker:
    """Small real optimizer; no SD models or CUDA, including in spawned workers."""
    def __init__(self, protocol_path, asset_manifest, models_root):
        self.last = None

    def resources(self):
        return {}

    def init_training(self, family):
        import torch
        self.last = {"family": family, "step": 0,
                     "parameters": [torch.tensor(0.75), torch.tensor(-0.25)],
                     "optimizer": None,
                     "cpu_rng": torch.Generator().manual_seed(3871).get_state()}
        return copy.deepcopy(self.last)

    def train_one(self, cache, previous, uid):
        import torch
        parameters = [torch.nn.Parameter(value.clone()) for value in previous["parameters"]]
        optimizer = torch.optim.Adam(parameters, lr=0.025, betas=(0.8, 0.95), foreach=False)
        if previous["optimizer"] is not None:
            optimizer.load_state_dict(copy.deepcopy(previous["optimizer"]))
        torch.set_rng_state(previous["cpu_rng"].clone())
        x, noise = torch.randn(7), torch.randn(7)
        a, b = parameters
        loss = ((a * x + b - (1.7 * x - 0.6 + 0.1 * noise)) ** 2).mean()
        loss.backward()
        optimizer.step()
        self.last = {"family": previous["family"], "step": previous["step"] + 1,
                     "parameters": [p.detach().clone() for p in parameters],
                     "optimizer": copy.deepcopy(optimizer.state_dict()),
                     "cpu_rng": torch.get_rng_state().clone(), "loss": loss.detach().clone()}
        return copy.deepcopy(self.last)

    def export_checkpoint(self, family):
        assert self.last["family"] == family
        return self.last


class DualRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tssa-dual-test-")
        self.root = Path(self.tmp.name)
        self.models = self.root / "models"
        self.models.mkdir()
        self.path = self.root / "run"
        self.asset_manifest = self.root / "assets.json"
        self.asset_manifest.write_text('{"files": []}')
        self.store = self.backend = None

    def tearDown(self):
        if self.backend:
            self.backend.close(force=True)
        if self.store:
            self.store.close()
        self.tmp.cleanup()

    def runner(self, *, resume=False, recover=False, uuids=UUIDS):
        if self.backend:
            self.backend.close(force=True)
        if self.store:
            self.store.close()
        self.store = DualRunStore(self.path, {"backend": "dual_fake_test_only", "protocol_sha256": SHA},
                                  resume=resume, recover_inflight=recover)
        self.backend = DualBackend(PROTOCOL_PATH, self.asset_manifest, self.models, self.store,
                                   cpu_backend=FakeBackend(), test_worker_factory="test_tssa_mvp_dual_run:FakeDualWorker")
        return DualMVPRunner(PROTOCOL, SHA, self.store, self.backend, uuids)

    def execute(self, runner, until="report"):
        with contextlib.redirect_stdout(io.StringIO()):
            return runner.execute(until)

    def test_plan_and_cpu_preflight_start_no_workers_or_cuda(self):
        runner = self.runner(uuids=None)
        self.execute(runner, "cpu-preflight")
        self.assertEqual(self.backend.clients, [])
        self.assertFalse((self.path / "execution_manifest.json").exists())
        code = "import sys; sys.path.insert(0,sys.argv[1]); import tssa_mvp_dual_run as d; p,s=d.load_protocol(d.PROJECT_ROOT/'research/tssa_mvp_2026-10-26.json'); d.experiment_plan(p,s); assert 'torch' not in sys.modules"
        subprocess.run([sys.executable, "-I", "-c", code, str(Path(__file__).parent)], check=True)

    def test_assignment_is_balanced_and_family_dependencies_are_prior(self):
        manifest = execution_manifest(PROTOCOL, SHA, UUIDS)
        tasks = manifest["training_tasks"]
        self.assertEqual([sum(t["worker_slot"] == s for t in tasks) for s in (0, 1)], [72, 72])
        completed = {f"training/{f}/step00" for f in ("Uniform-GD", "TSSA-GD", "RC-TSSA-GD")}
        for offset in range(0, 144, 2):
            wave = tasks[offset:offset + 2]
            self.assertEqual({t["worker_slot"] for t in wave}, {0, 1})
            self.assertEqual(len({t["family"] for t in wave}), 2)
            self.assertTrue(all(t["depends_on"] in completed for t in wave))
            completed.update(t["operation"] for t in wave)

    def test_real_cpu_adam_and_rng_survive_alternating_workers_and_copy_transport(self):
        import torch
        self.runner()
        self.backend.test_worker_factory = "test_tssa_mvp_dual_run:CPUAdamWorker"
        self.backend.configure(execution_manifest(PROTOCOL, SHA, UUIDS))
        reference = CPUAdamWorker(None, None, None)
        expected = reference.init_training("Uniform-GD")
        actual = self.backend.clients[0].call("training/Uniform-GD/step00", "init_training", ["Uniform-GD"])

        def equal(left, right):
            if isinstance(left, torch.Tensor):
                self.assertEqual(left.dtype, right.dtype)
                self.assertTrue(torch.equal(left, right))
            elif isinstance(left, dict):
                self.assertEqual(left.keys(), right.keys())
                for key in left:
                    equal(left[key], right[key])
            elif isinstance(left, (list, tuple)):
                self.assertEqual(len(left), len(right))
                for x, y in zip(left, right):
                    equal(x, y)
            else:
                self.assertEqual(left, right)

        equal(actual, expected)
        saved_rng = torch.get_rng_state().clone()
        try:
            for step in range(1, 17):
                name = f"training/Uniform-GD/step{step:02d}"
                client = self.backend.clients[assignment_slot(name)]
                input_state = actual
                immutable_input = copy.deepcopy(actual)
                expected = reference.train_one(None, expected, str(step))
                actual = client.call(name, "train_one", [None, actual, str(step)])
                equal(actual, expected)  # parameters + real Adam m/v/step + CPU RNG, every update
                equal(input_state, immutable_input)
                self.assertEqual(len(actual["optimizer"]["state"]), 2)
                self.assertTrue(all(set(state) == {"step", "exp_avg", "exp_avg_sq"}
                                    for state in actual["optimizer"]["state"].values()))
                # Mutating returned CPU storage must not alter the worker's saved tensors.
                actual["parameters"][0].add_(100)
                actual["optimizer"]["state"][0]["exp_avg"].zero_()
                actual["cpu_rng"].zero_()
                actual = client.call(name, "export_checkpoint", ["Uniform-GD"])
                equal(actual, expected)
            self.assertEqual(len({c.process.pid for c in self.backend.clients}), 2)
            self.assertFalse(torch.cuda.is_initialized())
        finally:
            torch.set_rng_state(saved_rng)

    def test_full_two_spawn_flow_exact_budget_and_resume_no_workers(self):
        runner = self.runner()
        report = self.execute(runner)
        self.assertEqual(report["actual_GPU_workers"], 2)
        self.assertEqual(len({c.process.pid for c in self.backend.clients}), 2)
        self.assertTrue(all(not c.process.is_alive() for c in self.backend.clients))
        ledger = json.loads((self.path / "resource_ledger.json").read_text())
        buckets = ledger["committed_work_by_bucket"]
        self.assertEqual(buckets["main"]["known_actual_branch_NFE"], 91848)
        self.assertEqual(buckets["source_extra"]["known_actual_branch_NFE"], 2400)
        self.assertEqual(buckets["diagnostic_extra"]["known_actual_branch_NFE"], 276)
        self.assertEqual([ledger["per_worker"][u]["known_optimizer_updates"] for u in UUIDS], [72, 72])
        self.assertEqual(sum(x["known_branch_NFE"] for x in ledger["per_worker"].values()), 94524)
        records = [json.loads(x) for x in (self.path / "heldout_per_image_metrics.jsonl").read_text().splitlines()]
        self.assertEqual(len(records), 960)
        self.assertEqual(len({r["task_id"] for r in records}), 960)
        self.assertEqual({r["worker_uuid"] for r in records}, set(UUIDS))
        again = self.execute(self.runner(resume=True))
        self.assertEqual(again, report)
        self.assertTrue(all(c.process is None for c in self.backend.clients))

    def test_unknown_or_changed_uuid_cannot_resume(self):
        self.execute(self.runner(), "gpu-diagnostic")
        bad = (UUIDS[0], "GPU-00000000-0000-0000-0000-000000000003")
        with self.assertRaises(IntegrityError):
            self.execute(self.runner(resume=True, uuids=bad), "gpu-diagnostic")
        self.assertEqual(self.backend.clients, [])
        with self.assertRaises(IntegrityError):
            self.execute(self.runner(resume=True, uuids=None), "source")

    def test_interrupted_step_never_auto_replays_and_optimizer_resumes(self):
        (self.models / "interrupt_step.json").write_text(json.dumps({"family": "Uniform-GD", "step": 25}))
        with self.assertRaises(InterruptedOperation):
            self.execute(self.runner(), "train")
        self.assertTrue(all(not c.process.is_alive() for c in self.backend.clients))
        with self.assertRaises(InterruptedOperation):
            self.execute(self.runner(resume=True), "train")
        self.execute(self.runner(resume=True, recover=True), "train")
        steps = [json.loads(x) for x in (self.path / "per_step_coefficients_and_losses.jsonl").read_text().splitlines()]
        self.assertEqual(len(steps), 144)
        self.assertEqual(len({(x["family"], x["step"]) for x in steps}), 144)
        ledger = self.store.resource_ledger()
        self.assertTrue(ledger["failed_or_interrupted_attempts_separately_accounted"])
        self.assertEqual(ledger["committed_work_by_bucket"]["main"]["known_actual_optimizer_updates"], 144)

    def test_worker_failure_stops_both_and_preserves_terminal_receipt(self):
        (self.models / "fail_source").write_text("test only")
        with self.assertRaises(WorkerFailure):
            self.execute(self.runner(), "source")
        self.assertTrue(all(c.process is None or not c.process.is_alive() for c in self.backend.clients))
        failed = [r for r in self.store.resource_ledger()["operations"] if r["status"] == "failed"]
        self.assertTrue(failed)
        self.assertFalse((self.path / "candidate_selection.json").exists())

    def test_selection_tampering_is_rejected_before_heldout(self):
        runner = self.runner()
        self.execute(runner, "select")
        chosen = json.loads((self.path / "candidate_selection.json").read_text())
        chosen["selected_checkpoint_candidates"]["RC-TSSA-GD"] = "naive"
        (self.path / "candidate_selection.json").write_text(json.dumps(chosen))
        with self.assertRaises(Exception):
            runner.freeze_selection(chosen)
        self.assertIsNone(self.backend.heldout_binding)
        self.assertFalse((self.path / "heldout_per_image_metrics.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
