"""Resumable entry point for the frozen, real-model TSSA gradient MVP.

``plan``/``--dry-run`` are CPU-free task enumeration, not experiment results.
``run --until cpu-preflight`` verifies offline assets without initializing CUDA.
Actual GPU work requires the runtime's explicit GPU_UUID/CUDA_VISIBLE_DEVICES
allocation and the operator's fresh website check. No card is selected here.

Interrupted, uncommitted GPU operations are never replayed by default. An
explicit --recover-inflight replays from the last committed state and accounts
for the previous attempt separately; numerical/gate failures are not retries.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
import time
import traceback
from typing import Any, Callable, Mapping, Sequence

from tssa_mvp_evaluate import KEY_FIELDS, MVPEvaluator


FROZEN_PROTOCOL_SHA256 = "8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STAGES = ("cpu-preflight", "gpu-diagnostic", "source", "cache", "screen", "train", "select", "heldout", "report")
IMPLEMENTATION_FILES = ("tssa_gradient_core.py", "tssa_sd_runtime.py", "tssa_mvp_evaluate.py",
                        "tssa_mvp_score.py", "tssa_mvp_run.py")


class IntegrityError(RuntimeError):
    pass


class InterruptedOperation(RuntimeError):
    pass


class ResearchStop(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, canonical_bytes(value))


def atomic_torch(path: Path, value: Any) -> None:
    import torch
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            torch.save(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_payload(path: Path, binary: bool = False) -> Any:
    if binary:
        import torch
        return torch.load(path, map_location="cpu", weights_only=True)
    return json.loads(path.read_text(encoding="utf-8"))


def load_protocol(path: str | Path) -> tuple[dict[str, Any], str]:
    path = Path(path)
    digest = file_hash(path)
    if digest != FROZEN_PROTOCOL_SHA256:
        raise IntegrityError("The protocol file differs from the explicitly frozen MVP; no automatic amendment is permitted.")
    return json.loads(path.read_text(encoding="utf-8")), digest


def task_from_key(protocol: Mapping[str, Any], stage: str, key: Sequence[Any]) -> dict[str, Any]:
    candidate, state, split, prompt_id, kind, seed = key
    block = protocol["prompts"][split]
    prompt = next(item for item in block["pairs"] + block["extra_normal"] if item["id"] == prompt_id)
    normal_prompt = prompt["normal"] if kind != "extra_normal" else prompt["prompt"]
    text = prompt["triggered"] if kind == "triggered" else normal_prompt
    task = dict(zip(KEY_FIELDS, key))
    task.update(stage=stage, prompt=text, normal_prompt=normal_prompt)
    task["task_id"] = canonical_hash({"stage": stage, "key": list(key)})[:24]
    return task


def experiment_plan(protocol: Mapping[str, Any], digest: str) -> dict[str, Any]:
    evaluator = MVPEvaluator(protocol, digest)
    images = {stage: [task_from_key(protocol, stage, key) for key in sorted(evaluator.expected_keys(stage))]
              for stage in ("source", "screen", "select")}
    heldout = []
    for candidate in protocol["heldout"]["methods"]:
        for condition in protocol["merging"]["heldout_states"]:
            for seed in protocol["sampling"]["test_seeds"]:
                for prompt in protocol["prompts"]["test"]["pairs"]:
                    for kind in ("triggered", "paired_normal"):
                        heldout.append(task_from_key(protocol, "heldout", (candidate, condition["id"], "test", prompt["id"], kind, seed)))
                for prompt in protocol["prompts"]["test"]["extra_normal"]:
                    heldout.append(task_from_key(protocol, "heldout", (candidate, condition["id"], "test", prompt["id"], "extra_normal", seed)))
    images["heldout_upper_bound"] = heldout
    training = [{"family": family, "step": index, "unit_id": unit,
                 "save_candidate": index in protocol["optimization"]["candidate_steps"]}
                for family in protocol["optimization"]["families"]
                for index, unit in enumerate(protocol["optimization"]["training_unit_order"], 1)]
    return {"kind": "execution_plan_only", "protocol_sha256": digest, "models_loaded": False,
            "CUDA_initialized": False, "images": images,
            "image_counts": {stage: len(items) for stage, items in images.items()},
            "training_updates": training, "trajectory_tasks": protocol["prompts"]["fit"]["pairs"] + protocol["prompts"]["fit"]["extra_normal"],
            "teacher_cache_units": protocol["cache"]["training_units"],
            "budget": protocol["budget"], "heldout_binding": "selected_* names are placeholders until the saved development selection passes and is hashed",
            "diagnostics": "Real CUDA gradient/central-difference/peak-memory checks are additional logged diagnostic work, never CPU-test evidence."}


class RunStore:
    """Atomic artifacts plus per-operation receipts; one process owns a run lock."""

    def __init__(self, directory: str | Path, identity: Mapping[str, Any], *, resume: bool = False,
                 recover_inflight: bool = False) -> None:
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / ".run.lock").open("a+")
        try:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.lock.close()
            raise IntegrityError("Another process already owns this run directory.") from error
        self.identity = dict(identity)
        self.identity_hash = canonical_hash(self.identity)
        self.recover_inflight = recover_inflight
        identity_path = self.root / "run_identity.json"
        if identity_path.exists():
            if not resume:
                self.close()
                raise IntegrityError("An existing run requires --resume; it will not be overwritten.")
            existing = json.loads(identity_path.read_text(encoding="utf-8"))
            if existing != self.identity:
                self.close()
                raise IntegrityError("Resume identity mismatch: protocol, assets, implementation, backend or package versions changed.")
        else:
            if resume or any(path.name != ".run.lock" for path in self.root.iterdir()):
                self.close()
                raise IntegrityError("Cannot initialize or resume a nonempty/unidentified run directory.")
            atomic_json(identity_path, self.identity)

    def close(self) -> None:
        if not self.lock.closed:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN)
            self.lock.close()

    def _paths(self, operation: str, binary: bool) -> tuple[Path, Path]:
        identifier = canonical_hash(operation)[:32]
        return self.root / "operations" / (identifier + ".json"), self.root / "artifacts" / (identifier + (".pt" if binary else ".json"))

    def _unwrap(self, path: Path, operation: str, binary: bool) -> Any:
        value = read_payload(path, binary)
        if (value.get("operation") != operation or value.get("run_identity_sha256") != self.identity_hash):
            raise IntegrityError(f"Artifact belongs to another operation or run: {operation}")
        return value["payload"]

    def operation(self, name: str, action: Callable[[], Any], *, binary: bool = False,
                  resource_snapshot: Callable[[], Mapping[str, Any]] | None = None,
                  safe_partial_resume: Callable[[], bool] | None = None,
                  cost_upper_bound: Mapping[str, Any] | None = None) -> Any:
        receipt_path, artifact_path = self._paths(name, binary)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else None
        if receipt and receipt.get("run_identity_sha256") != self.identity_hash:
            raise IntegrityError(f"Operation identity mismatch: {name}")
        if receipt and receipt["status"] == "completed":
            if not artifact_path.is_file() or file_hash(artifact_path) != receipt["artifact_sha256"]:
                raise IntegrityError(f"Completed operation artifact changed or disappeared: {name}")
            return self._unwrap(artifact_path, name, binary)
        if artifact_path.exists():
            if receipt is None:
                raise IntegrityError(f"Unreceipted artifact exists: {name}")
            payload = self._unwrap(artifact_path, name, binary)
            receipt["attempts"][-1].update(outcome="completed", resource_certainty="partial_or_unknown",
                                           recovered_committed_artifact=True)
            receipt.update(status="completed", recovered_committed_artifact=True,
                           artifact_sha256=file_hash(artifact_path), finished_at=utc_now())
            atomic_json(receipt_path, receipt)
            return payload
        attempts = [] if receipt is None else list(receipt["attempts"])
        if receipt is not None:
            previous = attempts[-1]
            if previous.get("outcome") == "failure":
                raise ResearchStop(f"A real failed operation is terminal and cannot be auto-retried: {name}")
            safe = bool(safe_partial_resume and safe_partial_resume())
            if not safe and not self.recover_inflight:
                raise InterruptedOperation(f"Uncommitted operation {name}; inspect its receipt, then explicitly use --recover-inflight if replay is justified.")
            previous["outcome"] = "interrupted"
            previous["resource_certainty"] = "partial_or_unknown"
            previous["replay_authorized"] = not safe
            previous["safe_partial_resume"] = safe
        def resources():
            try:
                return json.loads(json.dumps(resource_snapshot())) if resource_snapshot else {}
            except Exception as error:
                return {"resource_snapshot_error": str(error), "counts_are_unknown": True}
        before = resources()
        attempt = {"started_at": utc_now(), "outcome": "running", "resources_before": before}
        attempts.append(attempt)
        receipt = {"operation": name, "status": "running", "run_identity_sha256": self.identity_hash,
                   "cost_upper_bound": dict(cost_upper_bound or {}), "attempts": attempts}
        atomic_json(receipt_path, receipt)
        start = time.monotonic()
        try:
            payload = action()
            after = resources()
            # Counter overruns expose accidental extra model work before it can
            # be silently folded into a nominally completed frozen operation.
            for limit_key, counter in (("branch_NFE", "branch_nfe"), ("optimizer_updates", "optimizer_updates"),
                                       ("autograd_calls", "autograd_calls"), ("autograd_calls_max", "autograd_calls")):
                if limit_key not in (cost_upper_bound or {}) or counter not in after:
                    continue
                left, right = before.get(counter, {} if counter == "branch_nfe" else 0), after[counter]
                consumed = sum(right.values()) - sum(left.values()) if counter == "branch_nfe" else right - left
                if consumed < 0 or consumed > cost_upper_bound[limit_key]:
                    raise ResearchStop(f"Recorded {counter}={consumed} exceeds or invalidates the frozen per-operation budget for {name}.")
            envelope = {"operation": name, "run_identity_sha256": self.identity_hash, "payload": payload}
            (atomic_torch if binary else atomic_json)(artifact_path, envelope)
            attempt.update(outcome="completed", finished_at=utc_now(), wall_seconds=time.monotonic() - start,
                           resources_after=after)
            receipt.update(status="completed", artifact_sha256=file_hash(artifact_path), finished_at=utc_now())
            atomic_json(receipt_path, receipt)
            return payload
        except BaseException as error:
            interrupted = isinstance(error, (KeyboardInterrupt, SystemExit, InterruptedOperation))
            attempt.update(outcome="interrupted" if interrupted else "failure", finished_at=utc_now(),
                           wall_seconds=time.monotonic() - start, error_type=type(error).__name__, error=str(error),
                           resources_after=resources())
            receipt["status"] = "interrupted" if interrupted else "failed"
            atomic_json(receipt_path, receipt)
            raise

    def publish(self, relative: str, payload: Any) -> Path:
        return self.publish_bytes(relative, canonical_bytes(payload))

    def publish_bytes(self, relative: str, encoded: bytes) -> Path:
        path = self.root / relative
        if path.exists() and path.read_bytes() != encoded:
            raise IntegrityError(f"Refusing to replace a previously published evidence artifact: {relative}")
        if not path.exists():
            atomic_bytes(path, encoded)
        return path

    def resource_ledger(self) -> dict[str, Any]:
        operations = []
        extra_attempts = []
        for path in sorted((self.root / "operations").glob("*.json")) if (self.root / "operations").exists() else []:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            operations.append(receipt)
            extra_attempts.extend({"operation": receipt["operation"], "attempt": attempt,
                                   "cost_upper_bound": receipt.get("cost_upper_bound", {})}
                                  for attempt in receipt["attempts"] if attempt["outcome"] != "completed")
        totals = {name: {"committed_operation_cost_upper_bounds": {}, "known_actual_branch_NFE": 0,
                         "known_actual_autograd_calls": 0, "known_actual_optimizer_updates": 0,
                         "counter_incomplete_operations": []}
                  for name in ("main", "source_extra", "diagnostic_extra")}
        peak = 0
        for receipt in operations:
            name = receipt["operation"]
            group = "diagnostic_extra" if name.startswith("diagnostic/") else "source_extra" if name.startswith("image/source/") else "main"
            bucket = totals[group]
            if receipt["status"] == "completed":
                for key, value in receipt.get("cost_upper_bound", {}).items():
                    if isinstance(value, (int, float)):
                        bucket["committed_operation_cost_upper_bounds"][key] = bucket["committed_operation_cost_upper_bounds"].get(key, 0) + value
            for attempt in receipt["attempts"]:
                before, after = attempt.get("resources_before", {}), attempt.get("resources_after", {})
                if attempt.get("outcome") != "completed":
                    continue  # Failed/interrupted attempts keep their own complete receipts below.
                if attempt.get("resource_certainty") == "partial_or_unknown" or after.get("counts_are_unknown"):
                    bucket["counter_incomplete_operations"].append(name)
                    continue
                bucket["known_actual_branch_NFE"] += sum(after.get("branch_nfe", {}).values()) - sum(before.get("branch_nfe", {}).values())
                for key in ("autograd_calls", "optimizer_updates"):
                    bucket["known_actual_" + key] += after.get(key, 0) - before.get(key, 0)
                peak = max(peak, after.get("peak_allocated_bytes", 0))
        return {"run_identity_sha256": self.identity_hash, "operations": operations, "committed_work_by_bucket": totals,
                "observed_peak_allocated_bytes": peak,
                "failed_or_interrupted_attempts_separately_accounted": extra_attempts,
                "unknown_work_must_not_be_reported_as_zero": bool(extra_attempts) or any(x["counter_incomplete_operations"] for x in totals.values()),
                "diagnostic_bucket": "Operations prefixed diagnostic/ are outside the main 1664-image/144-update budget."}


class RealBackend:
    """All ML imports and allocations are lazy; plan never instantiates models."""

    kind = "real_sd"

    def __init__(self, protocol_path: Path, asset_manifest: Path, models_root: Path) -> None:
        self.protocol_path, self.asset_manifest, self.models_root = protocol_path, asset_manifest, models_root
        self.assets = self.runtime = self.scorer = None
        self.training = None

    def cpu_preflight(self) -> dict[str, Any]:
        import torch
        from tssa_sd_runtime import load_cpu_assets
        if torch.cuda.is_initialized():
            raise IntegrityError("CPU preflight must run before any CUDA initialization in this process.")
        self.assets = load_cpu_assets(self.protocol_path, self.asset_manifest, self.models_root)
        if torch.cuda.is_initialized():
            raise IntegrityError("CPU preflight unexpectedly initialized CUDA.")
        return {"passed": True, "protocol_sha256": self.assets.protocol_sha256, "CUDA_initialized": False,
                "file_hashes": self.assets.file_hashes, "parameter_keys": list(self.assets.parameter_names),
                "basis_statistics": self.assets.basis.statistics(), "compatibility": self.assets.compatibility,
                "real_SD_CUDA_preflight_passed": False}

    def rt(self):
        if self.assets is None:
            self.cpu_preflight()
        if self.runtime is None:
            from tssa_sd_runtime import SDGradientRuntime
            self.runtime = SDGradientRuntime(self.assets)
            existing = getattr(self, "expected_environment_path", None)
            if existing and existing.exists():
                expected = json.loads(existing.read_text())
                observed = self.runtime.environment_record()
                if observed != expected:
                    raise IntegrityError("CUDA hardware/numerical environment changed since the committed real diagnostic; do not reuse that diagnostic or silently migrate this frozen run.")
        return self.runtime

    def resources(self) -> dict[str, Any]:
        return {} if self.runtime is None else self.runtime.resource_record()

    def environment(self) -> dict[str, Any]:
        return self.rt().environment_record()

    def sample(self, task: Mapping[str, Any], coefficients: Sequence[float] | None):
        from tssa_mvp_score import to_rgb_pil
        runtime = self.rt()
        if task["candidate"] in ("clean", "original_backdoor"):
            output = runtime.sample(task["prompt"], task["seed"], source=task["candidate"])
        else:
            states = runtime.protocol["merging"]["development_normal_states"] + runtime.protocol["merging"]["heldout_states"]
            condition = next(state for state in states if state["id"] == task["state"])
            output = runtime.sample(task["prompt"], task["seed"], condition=condition, coefficients=coefficients)
        return to_rgb_pil(output["image"])

    def score(self, image, normal_prompt: str) -> dict[str, Any]:
        if self.scorer is None:
            from tssa_mvp_score import IndependentScorer
            self.scorer = IndependentScorer(self.models_root, device="cpu")
        return self.scorer.score(image, normal_prompt)

    def scorer_metadata(self) -> dict[str, Any]:
        return {} if self.scorer is None else self.scorer.describe()

    def trajectory(self, item: Mapping[str, Any]) -> dict[str, Any]:
        runtime = self.rt()
        source = "original_backdoor" if item["trajectory_source"] == "backdoor_triggered" else "clean"
        prompt = item["triggered"] if source == "original_backdoor" else item.get("normal", item.get("prompt"))
        output = runtime.sample(prompt, item["trajectory_seed"], source=source,
                                capture_steps=runtime.protocol["cache"]["save_denoising_step_inputs_1based"], decode=False)
        return {"prompt_id": item["id"], "trajectory_source": item["trajectory_source"], "seed": item["trajectory_seed"],
                "snapshots": output["snapshots"]}

    def units(self, trajectories: Mapping[str, Any]) -> dict[str, Any]:
        return self.rt()._units_from_trajectories(trajectories)

    def teacher(self, unit: Mapping[str, Any], identity: str) -> dict[str, Any]:
        import torch
        runtime = self.rt()
        with torch.no_grad():
            if identity in ("clean", "original_backdoor"):
                runtime.activate_source(identity)
                alpha = 1.0
            else:
                state = next(s for s in runtime.protocol["merging"]["development_backdoor_states"] if s["id"] == identity)
                runtime.activate_condition(state)
                alpha = state["alpha_malicious"]
            runtime._activity = "teacher_cache"
            output = runtime.responses(unit, None, alpha, include_extra=identity != "original_backdoor")
        return {name: tensor.detach().cpu().clone() for name, tensor in output.items()}

    def assemble_cache(self, units: dict[str, Any], teachers: Mapping[str, Any]) -> dict[str, Any]:
        import torch
        from tssa_gradient_core import fixed_backdoor_target
        runtime = self.rt()
        for unit_id, unit in units.items():
            clean, bd = teachers["clean"][unit_id], teachers["original_backdoor"][unit_id]
            unit["references"] = {"upload": clean}
            unit["references"].update({state["id"]: teachers[state["id"]][unit_id]
                                       for state in runtime.protocol["merging"]["development_backdoor_states"]})
            unit["target_backdoor"] = fixed_backdoor_target(bd["normal"], bd["triggered"], clean["normal"], clean["triggered"])
        rms = float(torch.stack([unit["target_backdoor"].square().mean() for unit in units.values()]).mean().sqrt())
        return {"protocol_sha256": runtime.assets.protocol_sha256, "unit_ids": list(units), "units": units,
                "B_star_rms": rms, "source_model_hashes": runtime.assets.file_hashes}

    def response(self, cache: Mapping[str, Any], coefficients: Sequence[float]) -> dict[str, Any]:
        return self.rt().response_summary(cache, coefficients)

    @staticmethod
    def _cpu_copy(value: Any) -> Any:
        import torch
        if isinstance(value, torch.Tensor):
            return value.detach().cpu().clone()
        if isinstance(value, dict):
            return {key: RealBackend._cpu_copy(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return type(value)(RealBackend._cpu_copy(item) for item in value)
        return value

    def _snapshot_training(self, family: str, step: int, scalars, optimizer, report=None) -> dict[str, Any]:
        import torch
        return {"family": family, "step": step, "coefficients": list(scalars.values()),
                "scalars": self._cpu_copy(scalars.state_dict()), "optimizer": self._cpu_copy(optimizer.state_dict()),
                "torch_rng_cpu": torch.get_rng_state(), "torch_rng_cuda": torch.cuda.get_rng_state(self.rt().device),
                "step_report": report}

    def init_training(self, family: str) -> dict[str, Any]:
        from tssa_gradient_core import CalibrationScalars
        scalars = CalibrationScalars(family, device=self.rt().device)
        optimizer = scalars.adam()
        self.training = (family, 0, scalars, optimizer)
        return self._snapshot_training(family, 0, scalars, optimizer)

    def train_one(self, cache: Mapping[str, Any], previous: Mapping[str, Any], unit_id: str) -> dict[str, Any]:
        import torch
        from tssa_gradient_core import CalibrationScalars
        family, step = previous["family"], previous["step"]
        if self.training is None or self.training[:2] != (family, step):
            scalars = CalibrationScalars(family, device=self.rt().device)
            scalars.load_state_dict(previous["scalars"], strict=True)
            optimizer = scalars.adam()
            optimizer.load_state_dict(previous["optimizer"])
            torch.set_rng_state(previous["torch_rng_cpu"])
            torch.cuda.set_rng_state(previous["torch_rng_cuda"], self.rt().device)
        else:
            _, _, scalars, optimizer = self.training
        report = self.rt().gradient_step(cache, unit_id, scalars, optimizer)
        self.training = (family, step + 1, scalars, optimizer)
        return self._snapshot_training(family, step + 1, scalars, optimizer, report)

    def unlock_heldout(self, coefficients: Mapping[str, Sequence[float]]) -> None:
        runtime = self.rt()
        if runtime._heldout_frozen_candidates is None:
            runtime.unlock_heldout(coefficients)
        elif runtime._heldout_frozen_candidates != {name: tuple(value) for name, value in coefficients.items()}:
            raise IntegrityError("A runtime's held-out coefficient binding cannot be changed.")

    def export_checkpoint(self, coefficients: Sequence[float], directory: Path) -> dict[str, Any]:
        from safetensors.torch import save_file
        import torch
        runtime = self.rt()
        a, b = coefficients
        state = {}
        for name, value in runtime.assets.text_states["clean"].items():
            state[name] = (value + a * runtime.assets.basis.delta_a[name] + b * runtime.assets.basis.delta_b[name]).contiguous() if name in runtime.assets.basis.delta_a else value.contiguous()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "model.safetensors"
        temporary = directory / ".model.safetensors.partial"
        save_file(state, str(temporary), metadata={"protocol_sha256": runtime.assets.protocol_sha256})
        os.replace(temporary, target)
        source_config = runtime.assets.models_root / "sd15" / "text_encoder" / "config.json"
        atomic_bytes(directory / "config.json", source_config.read_bytes())
        return {"coefficients": list(coefficients), "text_encoder_sha256": file_hash(target),
                "text_encoder_path": str(target), "config_sha256": file_hash(directory / "config.json"),
                "shared_non_TE_components": "exact pinned clean SD1.5 UNet, VAE, tokenizer and scheduler",
                "source_model_hashes": runtime.assets.file_hashes}

    def diagnostic(self) -> dict[str, Any]:
        """Real five-branch graph and central differences; costs are diagnostic-only."""
        import torch
        from tssa_gradient_core import CalibrationScalars, fixed_backdoor_target
        runtime = self.rt()
        pairs = runtime.protocol["prompts"]["fit"]["pairs"]
        extras = runtime.protocol["prompts"]["fit"]["extra_normal"]
        pair, extra = pairs[0], extras[0]
        # Load/decode the VAE here too: it remains resident after source images,
        # so a diagnostic without it would understate later training memory.
        first_output = runtime.sample(pair["normal"], pair["trajectory_seed"], source="clean", capture_steps=(1, 13, 25), decode=True)
        first = first_output["snapshots"][1]
        del first_output
        second = self.trajectory(extra)["snapshots"][1]
        unit = {"normal": pair["normal"], "triggered": pair["triggered"], "extra_prompt": extra["prompt"],
                "pair_latent": first["latent"], "extra_latent": second["latent"], "timestep": first["actual_timestep"], "references": {}}
        condition = runtime.protocol["merging"]["development_backdoor_states"][1]
        clean, bd = self.teacher(unit, "clean"), self.teacher(unit, "original_backdoor")
        unit["target_backdoor"] = fixed_backdoor_target(bd["normal"], bd["triggered"], clean["normal"], clean["triggered"])
        unit["references"][condition["id"]] = self.teacher(unit, condition["id"])
        runtime.activate_condition(condition)
        scalars = CalibrationScalars("RC-TSSA-GD", device=runtime.device)
        runtime._activity = "gpu_diagnostic"
        backdoor, normal = runtime._unit_losses(unit, condition, scalars)
        objective = backdoor.sum() + normal.sum()
        gradient, = torch.autograd.grad(objective * 1024.0, scalars.raw)
        runtime.ledger["autograd_calls"] += 1
        gradient = gradient.float() / 1024.0
        finite = bool(torch.isfinite(objective) and torch.isfinite(gradient).all())
        del backdoor, normal, objective
        runtime._pending_graph = False
        numerical = []
        h = 1.0 / 16.0
        with torch.no_grad():
            for index in range(2):
                values = []
                for sign in (1, -1):
                    scalars.raw.fill_(1.0)
                    scalars.raw[index] += sign * h
                    lb, ln = runtime._unit_losses(unit, condition, scalars)
                    values.append(float(lb.sum() + ln.sum()))
                numerical.append((values[0] - values[1]) / (2 * h))
            scalars.raw.fill_(1.0)
        runtime._pending_graph = False
        analytical = gradient.detach().cpu().tolist()
        comparisons = [{"analytical": a, "central_difference": n, "absolute_error": abs(a - n),
                        "tolerance": max(1e-7, 0.25 * max(abs(a), abs(n))),
                        "passed": math.isfinite(n) and abs(a - n) <= max(1e-7, 0.25 * max(abs(a), abs(n)))}
                       for a, n in zip(analytical, numerical)]
        no_parameter_grads = all(parameter.grad is None for model in (runtime.text_encoder, runtime.unet) for parameter in model.parameters())
        nonzero_gradient = max(map(abs, analytical)) > 1e-12
        return {"protocol_sha256": runtime.assets.protocol_sha256,
                "passed": finite and nonzero_gradient and no_parameter_grads and all(item["passed"] for item in comparisons),
                "real_SD_CUDA_executed": True, "five_UNet_branch_graph_measured": True,
                "resident_FP32_VAE_included_in_memory_measurement": True,
                "finite_loss_and_gradients": finite, "nonzero_coefficient_gradient": nonzero_gradient,
                "base_parameter_grads_absent": no_parameter_grads, "central_difference_h": h,
                "gradient_comparison": comparisons, "diagnostic_thresholds_are_not_research_success_gates": True,
                "resources": runtime.resource_record(), "environment": runtime.environment_record(),
                "budget_bucket": "extra_diagnostic_not_main_budget"}


class MVPRunner:
    """Stage orchestration; injected backends are for isolated CPU tests only."""

    def __init__(self, protocol: Mapping[str, Any], digest: str, store: RunStore, backend) -> None:
        self.p, self.sha, self.store, self.backend = protocol, digest, store, backend
        self.evaluator = MVPEvaluator(protocol, digest)
        self.coefficients = {x["id"]: [x["a"], x["b"]] for x in protocol["static_candidates"]}
        self.completed_stages: list[str] = []
        self.backend.expected_environment_path = self.store.root / "runtime_environment.json"

    def op(self, name: str, action, *, binary=False, safe_partial_resume=None, cost=None):
        return self.store.operation(name, action, binary=binary, resource_snapshot=self.backend.resources,
                                    safe_partial_resume=safe_partial_resume, cost_upper_bound=cost)

    def _verify_png(self, path: Path, task: Mapping[str, Any]) -> bool:
        from PIL import Image
        if not path.exists():
            return False
        with Image.open(path) as image:
            expected = {"protocol_sha256": self.sha, "run_identity_sha256": self.store.identity_hash,
                        "task_id": task["task_id"]}
            if image.format != "PNG" or any(image.info.get(k) != v for k, v in expected.items()):
                raise IntegrityError(f"Image provenance mismatch: {path}")
            image.verify()
        return True

    def image(self, task: Mapping[str, Any]) -> dict[str, Any]:
        from PIL import Image, PngImagePlugin
        path = self.store.root / "images" / task["stage"] / (task["task_id"] + ".png")
        coefficients = self.coefficients.get(task["candidate"])

        def action():
            if not self._verify_png(path, task):
                # Once the PNG is atomically saved, scoring can resume without a second diffusion sample.
                image = self.backend.sample(task, coefficients)
                if image.mode != "RGB":
                    raise IntegrityError("Backend must return the one-time quantized RGB image.")
                metadata = PngImagePlugin.PngInfo()
                for key, value in {"protocol_sha256": self.sha, "run_identity_sha256": self.store.identity_hash,
                                   "task_id": task["task_id"], **{k: str(task[k]) for k in KEY_FIELDS}}.items():
                    metadata.add_text(key, value)
                import io
                stream = io.BytesIO()
                image.save(stream, format="PNG", pnginfo=metadata)
                atomic_bytes(path, stream.getvalue())
            with Image.open(path) as encoded:
                score = self.backend.score(encoded.convert("RGB"), task["normal_prompt"])
            return {**{key: task[key] for key in KEY_FIELDS}, **score,
                    "protocol_sha256": self.sha, "run_identity_sha256": self.store.identity_hash,
                    "task_id": task["task_id"], "prompt": task["prompt"], "normal_prompt": task["normal_prompt"],
                    "image_path": str(path.relative_to(self.store.root)), "image_sha256": file_hash(path)}

        result = self.op("image/" + task["stage"] + "/" + task["task_id"], action,
                         safe_partial_resume=lambda: self._verify_png(path, task),
                         cost={"full_images": 1, "branch_NFE": 50, "scorer_calls": 1})
        if not self._verify_png(path, task) or file_hash(path) != result["image_sha256"]:
            raise IntegrityError(f"Saved image changed after scoring: {path}")
        return result

    def images(self, stage: str, selection=None) -> list[dict[str, Any]]:
        records = [self.image(task_from_key(self.p, stage, key))
                   for key in sorted(self.evaluator.expected_keys(stage, selection))]
        self.evaluator.validate_records(stage, records, selection)
        relative = "heldout_per_image_metrics.jsonl" if stage == "heldout" else stage + "_per_image_metrics.jsonl"
        self.store.publish_bytes(relative, b"".join(json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False).encode() + b"\n" for row in records))
        metadata = self.backend.scorer_metadata()
        if metadata:  # Fully resumed stages need not load the scorer just to reproduce its metadata.
            self.store.publish("scorer_metadata.json", metadata)
        return records

    @staticmethod
    def gate(report: Mapping[str, Any], label: str) -> None:
        if report.get("passed") is not True:
            raise ResearchStop(f"{label}: {report.get('status', 'failed')}; the frozen protocol prohibits continuing past this gate.")

    def preflight(self):
        report = self.op("preflight/cpu", self.backend.cpu_preflight)
        self.gate(report, "CPU preflight")
        self.store.publish("cpu_preflight.json", report)
        self.store.publish("model_file_hashes.json", report["file_hashes"])
        self.store.publish("parameter_key_manifest.json", report["parameter_keys"])
        self.store.publish("basis_statistics.json", report["basis_statistics"])
        return report

    def diagnostic(self):
        report = self.op("diagnostic/gpu_gradient_and_memory", self.backend.diagnostic,
                         cost={"branch_NFE": 138, "autograd_calls": 1, "budget_bucket": "extra_diagnostic"})
        self.store.publish("gpu_diagnostic.json", report)
        self.gate(report, "Real CUDA gradient and memory diagnostic")
        self.store.publish("runtime_environment.json", report["environment"])
        return report

    def source(self):
        records = self.images("source")
        report = self.op("gate/source", lambda: self.evaluator.source_gate(records))
        self.store.publish("source_gate.json", report)
        self.gate(report, "Published source-case gate")
        return report

    def cache(self):
        fit = self.p["prompts"]["fit"]
        trajectories = {item["id"]: self.op("trajectory/" + item["id"], lambda item=item: self.backend.trajectory(item),
                                                   binary=True, cost={"branch_NFE": 50, "trajectories": 1})
                        for item in fit["pairs"] + fit["extra_normal"]}
        trajectory_cache = {"protocol_sha256": self.sha, "trajectories": trajectories}
        units = self.backend.units(trajectory_cache)
        expected_ids = [spec["id"] for spec in self.p["cache"]["training_units"]]
        if list(units) != expected_ids:
            raise IntegrityError("Cache unit order/identity differs from the frozen 24-unit list.")
        teachers = {}
        for identity in ["clean", "original_backdoor"] + self.evaluator.dev_states:
            teachers[identity] = {uid: self.op("teacher/" + identity + "/" + uid,
                                              lambda unit=unit, identity=identity: self.backend.teacher(unit, identity),
                                              binary=True, cost={"branch_NFE": 3 if identity == "original_backdoor" else 5})
                                  for uid, unit in units.items()}
        cache = self.op("cache/assembled", lambda: self.backend.assemble_cache(units, teachers), binary=True)
        if cache["protocol_sha256"] != self.sha or cache["unit_ids"] != expected_ids:
            raise IntegrityError("Assembled cache identity mismatch.")
        self.store.publish("prompt_and_cache_index.json", {"protocol_sha256": self.sha, "prompts": self.p["prompts"],
                            "unit_ids": cache["unit_ids"], "B_star_rms": cache["B_star_rms"],
                            "units": [{k: v for k, v in unit.items() if k not in ("pair_latent", "extra_latent", "references", "target_backdoor")}
                                      for unit in units.values()],
                            "trajectories": {key: {"seed": item["seed"], "trajectory_source": item["trajectory_source"],
                                             "snapshots": {str(step): {k: v for k, v in snap.items() if k != "latent"}
                                                           for step, snap in item["snapshots"].items()}}
                                             for key, item in trajectories.items()}})
        signal = cache["B_star_rms"]
        if not math.isfinite(signal) or signal <= self.p["loss"]["fit_response_signal_rms_min_exclusive"]:
            raise ResearchStop("stop_unidentifiable_proxy_signal: frozen B_star_rms gate failed.")
        return cache

    def responses(self, cache, candidates):
        return {"protocol_sha256": self.sha, "B_star_rms": cache["B_star_rms"], "unit_ids": cache["unit_ids"],
                "candidates": {candidate: self.op("response/" + candidate,
                              lambda candidate=candidate: self.backend.response(cache, self.coefficients[candidate]),
                              cost={"branch_NFE": 456}) for candidate in candidates}}

    def screen(self, cache):
        summary = self.responses(cache, self.evaluator.static)
        records = self.images("screen")
        report = self.op("gate/screen", lambda: self.evaluator.static_screen(records, summary))
        self.store.publish("static_response_summary.json", summary)
        self.store.publish("static_screen.json", report)
        self.gate(report, "Static proxy screening")
        return report

    def train(self, cache):
        candidates, logs = {}, []
        for family in self.p["optimization"]["families"]:
            previous = self.op("training/" + family + "/step00", lambda family=family: self.backend.init_training(family), binary=True)
            for step, uid in enumerate(self.p["optimization"]["training_unit_order"], 1):
                if previous["family"] != family or previous["step"] != step - 1:
                    raise IntegrityError("Training checkpoint step/family mismatch; optimizer cannot be restarted.")
                operation = "training/" + family + f"/step{step:02d}"
                current = self.op(operation, lambda previous=previous, uid=uid: self.backend.train_one(cache, previous, uid),
                                  binary=True, cost={"optimizer_updates": 1, "branch_NFE": 19, "autograd_calls_max": 7})
                if current["family"] != family or current["step"] != step:
                    raise IntegrityError("Backend committed an unexpected training update.")
                a, b = current["coefficients"]
                if not all(math.isfinite(x) and 0 <= x <= 32 for x in (a, b)):
                    raise ResearchStop("Nonfinite or unprojected coefficients; no restart permitted.")
                logs.append({"protocol_sha256": self.sha, "family": family, "step": step, "unit_id": uid,
                             "coefficients": current["coefficients"], "details": current["step_report"]})
                if step in self.p["optimization"]["candidate_steps"]:
                    name = family + "_step" + str(step)
                    artifact = self.store._paths(operation, True)[1]
                    candidates[name] = {"coefficients": current["coefficients"], "training_operation": operation,
                                        "optimizer_checkpoint_path": str(artifact.relative_to(self.store.root)),
                                        "optimizer_checkpoint_sha256": file_hash(artifact)}
                    self.coefficients[name] = list(current["coefficients"])
                    self.store.publish("candidates/" + name + ".json", candidates[name])
                previous = current
        self.store.publish("learned_candidates.json", candidates)
        self.store.publish_bytes("per_step_coefficients_and_losses.jsonl", b"".join(json.dumps(row, sort_keys=True, allow_nan=False).encode() + b"\n" for row in logs))
        return candidates

    def select(self, cache):
        summary = self.responses(cache, self.evaluator.all_candidates)
        records = self.images("select")
        report = self.op("gate/selection", lambda: self.evaluator.select_candidates(records, summary))
        self.store.publish("candidate_response_and_image_metrics.json", {"responses": summary, "metrics": report["metrics"],
                                                                        "protocol_sha256": self.sha})
        self.store.publish("candidate_selection.json", report)
        self.gate(report, "Development selection")
        return report

    def freeze_selection(self, selection):
        # The evaluator verifies the saved hash, split and registered pools before any hold-out work.
        saved = json.loads((self.store.root / "candidate_selection.json").read_text())
        if saved != selection:
            raise IntegrityError("Selection differs from the saved development evidence.")
        self.evaluator.expected_keys("heldout", saved)
        selected = {name: self.coefficients[name] for name in saved["selected_checkpoint_candidates"].values() if name is not None}
        exports = {}
        for name, values in selected.items():
            export = self.op("export/" + name, lambda name=name, values=values: self.backend.export_checkpoint(values, self.store.root / "selected_checkpoints" / name))
            target = Path(export["text_encoder_path"])
            if file_hash(target) != export["text_encoder_sha256"] or file_hash(target.parent / "config.json") != export["config_sha256"]:
                raise IntegrityError("Exported selected checkpoint/config was changed.")
            if export["coefficients"] != list(values):
                raise IntegrityError("Selected checkpoint coefficients changed.")
            exports[name] = export
        binding = {"protocol_sha256": self.sha, "run_identity_sha256": self.store.identity_hash,
                   "selection_sha256": saved["selection_sha256"], "selection_file_sha256": file_hash(self.store.root / "candidate_selection.json"),
                   "candidate_coefficients": selected, "checkpoint_exports": exports}
        binding["binding_sha256"] = canonical_hash(binding)
        self.store.publish("selected_checkpoint_manifests.json", binding)
        self.backend.unlock_heldout(selected)
        return saved

    def heldout(self, selection):
        selection = self.freeze_selection(selection)
        records = self.images("heldout", selection)
        report = self.op("report/heldout", lambda: self.evaluator.heldout_report(records, selection))
        self.store.publish("heldout_report.json", report)
        return report

    def report(self, source, screen, selection, heldout):
        # Fixed panels are chosen from preregistered order, never by observed success.
        from PIL import Image, ImageDraw
        import io
        records = [json.loads(line) for line in (self.store.root / "heldout_per_image_metrics.jsonl").read_text().splitlines()]
        failures = [{**row, "expected": "target_class" if row["kind"] == "triggered" else "normal_class"}
                    for row in records if not self.evaluator._correct(row)]
        self.store.publish("heldout_failure_cases.json", {"protocol_sha256": self.sha, "cases": failures,
                                                          "rule": "All classifier failures, without hand selection."})
        prompt_id, seed = self.p["prompts"]["test"]["pairs"][0]["id"], self.p["sampling"]["test_seeds"][0]
        names = [selection["selected_checkpoint_candidates"][family] for family in ("naive", "Uniform", "TSSA", "RC-TSSA-GD")]
        names = list(dict.fromkeys([name for name in names if name] + ["matched_clean"]))
        panels = []
        for state in self.evaluator.hold_states:
            panel = Image.new("RGB", (512, len(names) * 280), "white")
            draw = ImageDraw.Draw(panel)
            for row_index, name in enumerate(names):
                draw.text((4, row_index * 280 + 4), name + " | normal / triggered", fill="black")
                for column, kind in enumerate(("paired_normal", "triggered")):
                    item = next(x for x in records if x["candidate"] == name and x["state"] == state and x["prompt_id"] == prompt_id and x["seed"] == seed and x["kind"] == kind)
                    with Image.open(self.store.root / item["image_path"]) as source_image:
                        panel.paste(source_image.convert("RGB").resize((256, 256), Image.Resampling.BILINEAR), (column * 256, row_index * 280 + 24))
            output = io.BytesIO()
            panel.save(output, format="PNG")
            relative = "panels/" + state + ".png"
            self.store.publish_bytes(relative, output.getvalue())
            panels.append({"state": state, "prompt_id": prompt_id, "seed": seed, "path": relative,
                           "selection_rule": "first registered test pair and first test seed, every frozen method"})
        self.store.publish("fixed_panel_index.json", panels)
        payload = {"protocol_sha256": self.sha, "run_identity_sha256": self.store.identity_hash,
                   "source_gate": source, "static_screen": screen, "selection": selection, "heldout": heldout,
                   "scope": "Preliminary held-out evidence, without FID, statistical significance or SOTA claims.",
                   "actual_GPU_workers": 1, "scoring_device": "cpu"}
        self.store.publish("final_report.json", payload)
        rows = ["# TSSA 梯度版初步验证", "", "本报告只描述冻结方案的实际运行结果，不作 FID、显著性或 SOTA 结论。", "",
                "| 方法 | 冻结候选 | 最低 ASR | 平均 ASR | 正常指标门禁 |", "|---|---|---:|---:|---|"]
        for family in ("naive", "Uniform", "TSSA", "RC-TSSA-GD"):
            if family not in heldout["family_metrics"]:
                continue
            metrics = heldout["family_metrics"][family]
            rows.append(f"| {family} | {metrics['candidate']} | {metrics['minimum_heldout_ASR']:.4f} | {metrics['mean_heldout_ASR']:.4f} | {metrics['normal_utility_gate']['passed']} |")
        rows.extend(["", "逐样本和逐状态证据见 heldout_per_image_metrics.jsonl、heldout_report.json；中断和诊断额外计算见 resource_ledger.json。", ""])
        self.store.publish_bytes("report.md", "\n".join(rows).encode())
        return payload

    def execute(self, until="report"):
        if until not in STAGES:
            raise ValueError(until)
        original = Path(self.backend.protocol_path).read_bytes()
        if hashlib.sha256(original).hexdigest() != self.sha:
            raise IntegrityError("Protocol changed between identity validation and execution.")
        self.store.publish_bytes("frozen_protocol.json", original)
        results = {}
        actions = {"cpu-preflight": self.preflight, "gpu-diagnostic": self.diagnostic, "source": self.source,
                   "cache": self.cache, "screen": lambda: self.screen(results["cache"]),
                   "train": lambda: self.train(results["cache"]), "select": lambda: self.select(results["cache"]),
                   "heldout": lambda: self.heldout(results["select"]),
                   "report": lambda: self.report(results["source"], results["screen"], results["select"], results["heldout"])}
        for stage in STAGES[:STAGES.index(until) + 1]:
            print(json.dumps({"stage": stage, "status": "checking_or_running", "time": utc_now()}), flush=True)
            results[stage] = actions[stage]()
            self.completed_stages.append(stage)
            self.write_status("completed" if stage == "report" else "paused_at_requested_stage" if stage == until else "running", stage)
        return results[until]

    def write_status(self, status: str, stage: str | None = None, error: BaseException | None = None):
        atomic_json(self.store.root / "resource_ledger.json", self.store.resource_ledger())
        atomic_json(self.store.root / "failure_or_completion_status.json", {
            "status": status, "stage": stage, "completed_stages": self.completed_stages, "updated_at": utc_now(),
            "protocol_sha256": self.sha, "run_identity_sha256": self.store.identity_hash,
            "error_type": type(error).__name__ if error else None, "error": str(error) if error else None,
            "configured_GPU_workers": 1,
            "actual_GPU_workers": int("gpu-diagnostic" in self.completed_stages or getattr(self.backend, "runtime", None) is not None),
            "second_GPU_reserved_or_initialized": False,
            "process_exit_releases_CUDA": True,
            "real_SD_CUDA_preflight_passed": "gpu-diagnostic" in self.completed_stages})


def build_identity(protocol_path: Path, asset_manifest: Path, models_root: Path) -> dict[str, Any]:
    # Metadata inspection does not import torch or initialize CUDA.
    packages = {}
    for distribution in importlib.metadata.distributions():
        original_name = distribution.metadata.get("Name")
        version = distribution.version
        if not original_name or not version:
            raise IntegrityError("An installed distribution lacks its name or version; environment identity is incomplete.")
        name = re.sub(r"[-_.]+", "-", original_name.strip()).lower()
        version = version.strip()
        if not name or not version:
            raise IntegrityError("An installed distribution has an empty normalized name or version.")
        if name in packages and packages[name] != version:
            raise IntegrityError(f"Conflicting installed distribution versions for {name}: {packages[name]} and {version}.")
        packages[name] = version
    packages = dict(sorted(packages.items()))
    files = json.loads(asset_manifest.read_text())["files"]
    local_hashes = {}
    root = models_root.resolve()
    for entry in files:
        path = (root / entry["local_path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise IntegrityError(f"Missing or out-of-root offline asset: {entry['local_path']}")
        local_hashes[entry["local_path"]] = file_hash(path)
    return {"schema_version": 1, "backend": RealBackend.kind, "protocol_sha256": file_hash(protocol_path),
            "asset_manifest_sha256": file_hash(asset_manifest), "models_root": str(root), "local_file_sha256": local_hashes,
            "implementation_sha256": {name: file_hash(Path(__file__).parent / name) for name in IMPLEMENTATION_FILES},
            "packages": packages, "python": sys.version, "single_GPU_sequential_CPU_scoring": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Frozen TSSA MVP: one explicit GPU worker, CPU scoring; no second GPU reservation or automatic replay.")
    parser.add_argument("command", choices=("plan", "run"))
    parser.add_argument("--protocol", type=Path, default=PROJECT_ROOT / "research/tssa_mvp_2026-10-26.json")
    parser.add_argument("--asset-manifest", type=Path, default=PROJECT_ROOT / "research/tssa_mvp_assets_2026-10-26.json")
    parser.add_argument("--models-root", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--until", choices=STAGES, default="report", help="cpu-preflight does not initialize CUDA; gpu-diagnostic executes a real CUDA gradient check")
    parser.add_argument("--resume", action="store_true", help="Require an existing run with identical input/code/package identity")
    parser.add_argument("--recover-inflight", action="store_true", help="Explicitly authorize replay of interrupted uncommitted work; prior attempt remains extra budget; real failures remain terminal")
    parser.add_argument("--dry-run", action="store_true", help="Enumerate all frozen tasks without models, torch or CUDA")
    parser.add_argument("--output", type=Path, help="Optional plan JSON path; defaults to stdout")
    args = parser.parse_args(argv)
    protocol, digest = load_protocol(args.protocol)
    if args.command == "plan" or args.dry_run:
        plan = experiment_plan(protocol, digest)
        if args.output:
            atomic_json(args.output, plan)
            print(json.dumps({"plan_path": str(args.output), "image_counts": plan["image_counts"], "GPU_workers_if_executed": 1}))
        else:
            print(canonical_bytes(plan).decode(), end="")
        return 0
    if not args.models_root or not args.run_dir:
        parser.error("run requires --models-root and --run-dir")
    if args.recover_inflight and not args.resume:
        parser.error("--recover-inflight requires --resume")
    if args.until != "cpu-preflight":
        visible = [x.strip() for x in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",") if x.strip()]
        if len(visible) != 1 or os.environ.get("GPU_UUID", "").strip() != visible[0]:
            parser.error("This runner actually uses one GPU: expose exactly the allocated GPU_UUID in CUDA_VISIBLE_DEVICES; do not hold a second card.")
    store = runner = None
    old_term = signal.getsignal(signal.SIGTERM)
    try:
        def interrupted(signum, frame):
            raise KeyboardInterrupt(f"Signal {signum}; unfinished work needs explicit review before replay.")
        signal.signal(signal.SIGTERM, interrupted)
        identity = build_identity(args.protocol, args.asset_manifest, args.models_root)
        store = RunStore(args.run_dir, identity, resume=args.resume, recover_inflight=args.recover_inflight)
        runner = MVPRunner(protocol, digest, store, RealBackend(args.protocol, args.asset_manifest, args.models_root))
        runner.execute(args.until)
        return 0
    except BaseException as error:
        status = "interrupted" if isinstance(error, (KeyboardInterrupt, InterruptedOperation)) else "stopped_by_gate" if isinstance(error, ResearchStop) else "failed"
        if runner:
            runner.write_status(status, error=error)
            # Individual operation receipts remain authoritative; this is the current process failure only.
            atomic_bytes(store.root / "last_failure_traceback.txt", traceback.format_exc().encode())
        print(json.dumps({"status": status, "error_type": type(error).__name__, "error": str(error)}), file=sys.stderr)
        return 3 if status == "interrupted" else 2
    finally:
        signal.signal(signal.SIGTERM, old_term)
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
