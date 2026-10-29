"""Two explicit GPU workers for the unchanged frozen MVP, with a CPU-only parent.

The single-card entry point remains untouched. A separate execution manifest
fixes both UUIDs and task assignment before any GPU output. Three independent
48-step optimizations are interleaved, never jointly updated or averaged.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_EXCEPTION
import contextlib
import copy
import gc
import hashlib
import importlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import pickle
import re
import signal
import sys
import threading
import time
import traceback
from typing import Any, Mapping, Sequence

from tssa_mvp_run import (FROZEN_PROTOCOL_SHA256, IntegrityError, InterruptedOperation,
                          MVPRunner, PROJECT_ROOT, RealBackend, ResearchStop, RunStore,
                          STAGES, atomic_bytes, atomic_json, build_identity, canonical_bytes,
                          canonical_hash, experiment_plan, file_hash, load_protocol,
                          read_payload, task_from_key, utc_now)


FAMILIES = ("Uniform-GD", "TSSA-GD", "RC-TSSA-GD")
UUID_PATTERN = re.compile(r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


class WorkerFailure(RuntimeError):
    pass


def _send(connection, value):
    # Ordinary pickle copies CPU storages by value; multiprocessing's tensor
    # reducers instead require a live sharing process/FD and can outlive a task.
    torch = sys.modules.get("torch")
    def check(item):
        if torch is not None and isinstance(item, torch.Tensor):
            if item.device.type != "cpu":
                raise IntegrityError("CUDA tensors may not cross into the CPU parent.")
        elif isinstance(item, dict):
            for nested in item.values():
                check(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                check(nested)
    check(value)
    connection.send_bytes(pickle.dumps(value, protocol=5))


def _receive(connection):
    # Only this parent's private pipes connect to its own spawned workers.
    return pickle.loads(connection.recv_bytes())


def validate_uuids(uuids: Sequence[str]) -> tuple[str, str]:
    if len(uuids) != 2 or len(set(uuids)) != 2 or any(not UUID_PATTERN.fullmatch(x) for x in uuids):
        raise IntegrityError("Supply two distinct explicitly allocated full GPU UUIDs; numeric indices and auto-selection are forbidden.")
    return tuple(uuids)


def assignment_slot(operation: str) -> int:
    if operation.startswith("training/"):
        _, family, step_text = operation.split("/")
        step = int(step_text.removeprefix("step"))
        if family not in FAMILIES or not 0 <= step <= 48:
            raise IntegrityError("Unregistered optimization operation.")
        return (max(0, step - 1) * 3 + FAMILIES.index(family)) % 2
    if operation.startswith("diagnostic/worker"):
        slot = int(operation.removeprefix("diagnostic/worker"))
        if slot not in (0, 1):
            raise IntegrityError("Unknown diagnostic worker.")
        return slot
    return int(hashlib.sha256(operation.encode("utf-8")).hexdigest()[:16], 16) % 2


def execution_manifest(protocol: Mapping[str, Any], protocol_sha: str, uuids: Sequence[str]) -> dict[str, Any]:
    uuids = validate_uuids(uuids)
    tasks = []
    for step, uid in enumerate(protocol["optimization"]["training_unit_order"], 1):
        for family in FAMILIES:
            name = f"training/{family}/step{step:02d}"
            slot = assignment_slot(name)
            tasks.append({"operation": name, "family": family, "step": step, "unit_id": uid,
                          "depends_on": f"training/{family}/step{step - 1:02d}",
                          "worker_slot": slot, "GPU_UUID": uuids[slot]})
    spec = {"schema_version": 1, "protocol_sha256": protocol_sha, "gpu_uuids": list(uuids),
            "execution_strategy": "two_spawn_workers_one_UUID_each_CPU_parent",
            "assignment_rules": {"training": "((step-1)*3+family_index)%2; step00 uses family_index%2",
                                 "family_order": list(FAMILIES),
                                 "other_operations": "int(SHA256(UTF8(operation_name)).hexdigest()[:16],16)%2",
                                 "diagnostics": "diagnostic/worker0 and diagnostic/worker1 bind to their named slot",
                                 "resume": "same operation, original UUID, identical implementation and package identity"},
            "training_tasks": tasks, "updates_per_worker": [72, 72],
            "optimization_dependency": "step n must read the atomically committed model/Adam/RNG checkpoint of the same family at n-1",
            "scientific_budget_unchanged": dict(protocol["budget"]),
            "extra_diagnostics": {"per_worker_branch_NFE": 138, "total_branch_NFE": 276, "autograd_calls": 2},
            "heldout": "only tasks generated from the saved hashed selection are eligible; the same assignment rule applies",
            "parent_initializes_CUDA": False, "scoring_device": "cpu"}
    spec["assignment_sha256"] = canonical_hash(spec)
    return spec


def _parent_death_watch(parent_pid: int) -> None:
    # Also covers parent SIGKILL, where its finally block cannot execute.
    while os.getppid() == parent_pid:
        time.sleep(0.5)
    os._exit(74)


def worker_main(connection, config: Mapping[str, Any]) -> None:
    """Spawn target: set device isolation before any torch/model import."""
    os.environ["CUDA_VISIBLE_DEVICES"] = config["uuid"]
    os.environ["GPU_UUID"] = config["uuid"]
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    threading.Thread(target=_parent_death_watch, args=(config["parent_pid"],), daemon=True).start()
    backend = None
    cache_key = cache = None
    allowed = {"diagnostic", "sample", "trajectory", "teacher", "response", "init_training",
               "train_one", "export_checkpoint", "unlock_heldout"}
    try:
        factory = config.get("test_worker_factory")
        if factory:
            module, name = factory.split(":", 1)
            constructor = getattr(importlib.import_module(module), name)
        else:
            constructor = RealBackend
        backend = constructor(Path(config["protocol_path"]), Path(config["asset_manifest"]), Path(config["models_root"]))
        backend.expected_environment_path = Path(config["environment_path"])
        while True:
            request = _receive(connection)
            if request.get("command") == "stop":
                return
            operation, method = request["operation"], request["method"]
            if method not in allowed or request["assignment_sha256"] != config["assignment_sha256"]:
                raise IntegrityError("Worker received an unknown operation or assignment binding.")
            before = copy.deepcopy(backend.resources())
            try:
                arguments = request["args"]
                reference = request.get("cache_ref")
                if reference:
                    key = (reference["path"], reference["sha256"])
                    if key != cache_key:
                        path = Path(reference["path"])
                        if file_hash(path) != reference["sha256"]:
                            raise IntegrityError("Training cache file changed in transit.")
                        envelope = read_payload(path, True)
                        if (envelope.get("operation") != "cache/assembled" or
                            envelope.get("run_identity_sha256") != config["run_identity_sha256"]):
                            raise IntegrityError("Training cache belongs to another run.")
                        cache = envelope["payload"]
                        if cache["protocol_sha256"] != FROZEN_PROTOCOL_SHA256:
                            raise IntegrityError("Training cache protocol differs from the frozen MVP.")
                        cache_key = key
                    arguments = [cache, *arguments]
                payload = getattr(backend, method)(*arguments)
                _send(connection, {"operation": operation, "GPU_UUID": config["uuid"], "ok": True,
                                 "payload": payload, "before": before, "after": copy.deepcopy(backend.resources()),
                                 "pid": os.getpid()})
            except BaseException as error:
                _send(connection, {"operation": operation, "GPU_UUID": config["uuid"], "ok": False,
                                 "error_type": type(error).__name__, "error": str(error),
                                 "interrupted": isinstance(error, (KeyboardInterrupt, InterruptedOperation)),
                                 "traceback": traceback.format_exc(), "before": before,
                                 "after": copy.deepcopy(backend.resources()), "pid": os.getpid()})
                return  # A failed worker never accepts another scientific task.
    except (EOFError, BrokenPipeError):
        return
    finally:
        connection.close()


class WorkerClient:
    def __init__(self, config, aborted: threading.Event) -> None:
        self.config, self.aborted = dict(config), aborted
        self.process = self.connection = None
        self.last_resources = {"worker_uuid": config["uuid"]}
        self.lock = threading.RLock()
        self.start_lock = threading.Lock()

    def start(self):
        with self.start_lock:
            if self.aborted.is_set():
                raise InterruptedOperation("The dual run is stopping; no new worker can start.")
            if self.process is None:
                parent, child = mp.get_context("spawn").Pipe()
                self.process = mp.get_context("spawn").Process(target=worker_main, args=(child, self.config),
                                                               name="tssa-gpu-" + self.config["uuid"])
                self.connection = parent
                self.process.start()
                child.close()

    def call(self, operation, method, args, cache_ref=None):
        self.start()
        if self.aborted.is_set():
            raise InterruptedOperation("Another worker or the parent stopped this run.")
        try:
            _send(self.connection, {"operation": operation, "method": method, "args": args,
                                  "assignment_sha256": self.config["assignment_sha256"], "cache_ref": cache_ref})
            while not self.connection.poll(0.2):
                if self.aborted.is_set() or not self.process.is_alive():
                    raise InterruptedOperation("Worker exited before acknowledging its operation; automatic replay is forbidden.")
            result = _receive(self.connection)
        except (EOFError, BrokenPipeError, OSError) as error:
            raise InterruptedOperation("Worker channel closed with an uncommitted operation.") from error
        if result["operation"] != operation or result["GPU_UUID"] != self.config["uuid"]:
            raise IntegrityError("Worker returned another task or GPU identity.")
        self.last_resources = {**result["after"], "worker_uuid": result["GPU_UUID"], "worker_pid": result["pid"]}
        if not result["ok"]:
            if result.get("interrupted"):
                raise InterruptedOperation(result["error"])
            raise WorkerFailure(f"{result['error_type']} on {result['GPU_UUID']}: {result['error']}\n{result['traceback']}")
        return result["payload"]

    def stop(self, force=False):
        process = self.process
        if process is None:
            return
        if process.is_alive():
            if force:
                process.terminate()
            else:
                try:
                    _send(self.connection, {"command": "stop"})
                except (BrokenPipeError, OSError):
                    pass
            process.join(timeout=3)
            if process.is_alive():
                process.kill()
                process.join(timeout=3)
        if self.connection:
            self.connection.close()


class DualBackend:
    """One parent CPU scorer; thread-bound RPC clients each own one GPU runtime."""
    kind = "real_sd_dual_spawn"

    def __init__(self, protocol_path, asset_manifest, models_root, store, *, cpu_backend=None, test_worker_factory=None):
        self.protocol_path, self.asset_manifest, self.models_root = map(Path, (protocol_path, asset_manifest, models_root))
        self.protocol, self.sha = load_protocol(self.protocol_path)
        self.store = store
        self.cpu = cpu_backend or RealBackend(self.protocol_path, self.asset_manifest, self.models_root)
        self.test_worker_factory = test_worker_factory
        self.clients = []
        self.spec = None
        self.local = threading.local()
        self.scoring_lock = threading.Lock()
        self.aborted = threading.Event()
        self.cache_ref = None
        self.source_hashes = None
        self.heldout_binding = None
        self.unlocked_slots = set()

    def configure(self, spec):
        if self.spec and self.spec != spec:
            raise IntegrityError("The dual-worker execution binding cannot change.")
        self.spec = spec
        if not self.clients:
            for uuid in spec["gpu_uuids"]:
                self.clients.append(WorkerClient({"uuid": uuid, "parent_pid": os.getpid(),
                    "protocol_path": str(self.protocol_path), "asset_manifest": str(self.asset_manifest),
                    "models_root": str(self.models_root), "run_identity_sha256": self.store.identity_hash,
                    "assignment_sha256": spec["assignment_sha256"],
                    "environment_path": str(self.store.root / "environments" / (uuid + ".json")),
                    "test_worker_factory": self.test_worker_factory}, self.aborted))

    @contextlib.contextmanager
    def bind(self, operation):
        slot = assignment_slot(operation)
        if not self.clients:
            yield
            return
        client = self.clients[slot]
        with client.lock:
            previous = getattr(self.local, "operation", None)
            self.local.operation = operation
            try:
                yield
            finally:
                self.local.operation = previous

    def call(self, method, *args, cache=False):
        operation = getattr(self.local, "operation", None)
        if operation is None or not self.clients:
            raise IntegrityError("GPU work requires a frozen, explicitly bound operation.")
        reference = None
        if cache:
            if self.cache_ref is None:
                path = self.store._paths("cache/assembled", True)[1]
                self.cache_ref = {"path": str(path), "sha256": file_hash(path)}
            reference = self.cache_ref
        return self.clients[assignment_slot(operation)].call(operation, method, list(args), reference)

    def resources(self):
        name = getattr(self.local, "operation", None)
        return copy.deepcopy(self.clients[assignment_slot(name)].last_resources) if name and self.clients else {}

    def cpu_preflight(self):
        report = self.cpu.cpu_preflight()
        self.source_hashes = report["file_hashes"]
        if hasattr(self.cpu, "assets"):
            self.cpu.assets = None  # Do not retain a third full FP32 model bank in the parent.
        gc.collect()
        return report

    def sample(self, task, coefficients):
        if task["stage"] == "heldout" and self.heldout_binding is None:
            raise IntegrityError("Held-out sampling has not been unlocked by the frozen selection.")
        if task["stage"] == "heldout":
            slot = assignment_slot(self.local.operation)
            if slot not in self.unlocked_slots:
                self.call("unlock_heldout", self.heldout_binding["candidate_coefficients"])
                self.unlocked_slots.add(slot)
        return self.call("sample", task, coefficients)

    def score(self, image, normal_prompt):
        with self.scoring_lock:
            return self.cpu.score(image, normal_prompt)

    def scorer_metadata(self):
        return self.cpu.scorer_metadata()

    def trajectory(self, item):
        return self.call("trajectory", item)

    def teacher(self, unit, identity):
        return self.call("teacher", unit, identity)

    def response(self, cache, coefficients):
        return self.call("response", coefficients, cache=True)

    def init_training(self, family):
        return self.call("init_training", family)

    def train_one(self, cache, previous, uid):
        return self.call("train_one", previous, uid, cache=True)

    def diagnostic(self):
        return self.call("diagnostic")

    def export_checkpoint(self, coefficients, directory):
        return self.call("export_checkpoint", coefficients, directory)

    def units(self, trajectories):
        # This runtime helper only reads CPU trajectory tensors and the protocol.
        # Bypass the CUDA constructor, not its declared cache semantics.
        from types import SimpleNamespace
        from tssa_sd_runtime import SDGradientRuntime
        reader = SimpleNamespace(protocol=self.protocol, assets=SimpleNamespace(protocol_sha256=self.sha))
        return SDGradientRuntime._units_from_trajectories(reader, trajectories)

    def assemble_cache(self, units, teachers):
        import torch
        from tssa_gradient_core import fixed_backdoor_target
        for uid, unit in units.items():
            clean, bd = teachers["clean"][uid], teachers["original_backdoor"][uid]
            unit["references"] = {"upload": clean, **{s["id"]: teachers[s["id"]][uid] for s in self.protocol["merging"]["development_backdoor_states"]}}
            unit["target_backdoor"] = fixed_backdoor_target(bd["normal"], bd["triggered"], clean["normal"], clean["triggered"])
        signal = float(torch.stack([u["target_backdoor"].square().mean() for u in units.values()]).mean().sqrt())
        return {"protocol_sha256": self.sha, "unit_ids": list(units), "units": units,
                "B_star_rms": signal, "source_model_hashes": self.source_hashes}

    def unlock_heldout(self, coefficients):
        binding = json.loads((self.store.root / "selected_checkpoint_manifests.json").read_text())
        if binding["candidate_coefficients"] != coefficients or binding["run_identity_sha256"] != self.store.identity_hash:
            raise IntegrityError("Held-out candidates do not match saved selected checkpoints.")
        if binding["binding_sha256"] != canonical_hash({k: v for k, v in binding.items() if k != "binding_sha256"}):
            raise IntegrityError("Held-out binding checksum changed.")
        self.heldout_binding = binding
        # Do not start a GPU process if every held-out image is already committed.
        # Each runtime receives this binding immediately before its first new sample.

    def close(self, force=False):
        if force:
            self.aborted.set()
        for client in self.clients:
            client.stop(force)


class DualRunStore(RunStore):
    """Keep the inherited scientific report, with truthful execution metadata."""
    def publish(self, relative, payload):
        if relative == "final_report.json":
            payload = dict(payload, actual_GPU_workers=2, execution_entrypoint="tssa_mvp_dual_run.py")
            spec = json.loads((self.root / "execution_manifest.json").read_text())
            payload["assignment_sha256"] = spec["assignment_sha256"]
        return super().publish(relative, payload)


class DualMVPRunner(MVPRunner):
    def __init__(self, protocol, digest, store, backend, uuids=None):
        super().__init__(protocol, digest, store, backend)
        self.uuids = tuple(uuids) if uuids else None
        self.active_operations = set()
        self.active_lock = threading.Lock()

    def op(self, name, action, *, binary=False, safe_partial_resume=None, cost=None):
        with self.active_lock:
            if name in self.active_operations:
                raise IntegrityError("Duplicate concurrent dispatch: " + name)
            self.active_operations.add(name)
        try:
            with self.backend.bind(name):
                def wrapped():
                    value = action()
                    if name.startswith(("image/", "training/")) and self.backend.spec:
                        value = {**value, "worker_uuid": self.backend.spec["gpu_uuids"][assignment_slot(name)],
                                 "assignment_sha256": self.backend.spec["assignment_sha256"]}
                    return value
                return super().op(name, wrapped, binary=binary, safe_partial_resume=safe_partial_resume, cost=cost)
        finally:
            with self.active_lock:
                self.active_operations.remove(name)

    def parallel(self, jobs):
        """Each lane stays on one client, so per-worker counter deltas cannot overlap."""
        queues = [[], []]
        results = {}
        for name, action in jobs:
            queues[assignment_slot(name)].append((name, action))
        def lane(items):
            for name, action in items:
                if self.backend.aborted.is_set():
                    raise InterruptedOperation("Sibling worker stopped; remaining tasks were never launched.")
                results[name] = action()
        executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tssa-parent-lane")
        futures = [executor.submit(lane, items) for items in queues]
        try:
            done, _ = wait(futures, return_when=FIRST_EXCEPTION)
            for future in done:
                future.result()
            for future in futures:
                future.result()
        except BaseException:
            self.backend.close(force=True)
            raise
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        return results

    def images(self, stage, selection=None):
        tasks = [task_from_key(self.p, stage, key) for key in sorted(self.evaluator.expected_keys(stage, selection))]
        jobs = [("image/" + stage + "/" + t["task_id"], lambda t=t: self.image(t)) for t in tasks]
        values = self.parallel(jobs)
        records = [values[name] for name, _ in jobs]
        self.evaluator.validate_records(stage, records, selection)
        relative = "heldout_per_image_metrics.jsonl" if stage == "heldout" else stage + "_per_image_metrics.jsonl"
        self.store.publish_bytes(relative, b"".join(json.dumps(r, sort_keys=True, ensure_ascii=False, allow_nan=False).encode() + b"\n" for r in records))
        metadata = self.backend.scorer_metadata()
        if metadata:
            self.store.publish("scorer_metadata.json", metadata)
        return records

    def preflight(self):
        report = super().preflight()
        self.backend.source_hashes = report["file_hashes"]
        return report

    def diagnostic(self):
        jobs = []
        for slot in (0, 1):
            name = "diagnostic/worker" + str(slot)
            jobs.append((name, lambda name=name: self.op(name, self.backend.diagnostic,
                         cost={"branch_NFE": 138, "autograd_calls": 1, "budget_bucket": "extra_diagnostic"})))
        reports = self.parallel(jobs)
        for name, report in reports.items():
            self.store.publish("diagnostics/" + name.split("/")[1] + ".json", report)
            self.gate(report, name)
            uuid = self.backend.spec["gpu_uuids"][assignment_slot(name)]
            self.store.publish("environments/" + uuid + ".json", report["environment"])
        aggregate = {"passed": True, "workers": reports, "assignment_sha256": self.backend.spec["assignment_sha256"]}
        self.store.publish("gpu_diagnostic.json", aggregate)
        self.store.publish("runtime_environment.json", {"workers": {name: r["environment"] for name, r in reports.items()},
                                                        "parent_CUDA_initialized": False})
        return aggregate

    def cache(self):
        fit = self.p["prompts"]["fit"]
        items = fit["pairs"] + fit["extra_normal"]
        jobs = [("trajectory/" + item["id"], lambda item=item: self.op("trajectory/" + item["id"],
                    lambda: self.backend.trajectory(item), binary=True, cost={"branch_NFE": 50, "trajectories": 1})) for item in items]
        values = self.parallel(jobs)
        trajectories = {item["id"]: values["trajectory/" + item["id"]] for item in items}
        units = self.backend.units({"protocol_sha256": self.sha, "trajectories": trajectories})
        expected = [u["id"] for u in self.p["cache"]["training_units"]]
        if list(units) != expected:
            raise IntegrityError("Cache units differ from the frozen sequence.")
        identities = ["clean", "original_backdoor", *self.evaluator.dev_states]
        jobs = []
        for identity in identities:
            for uid, unit in units.items():
                name = "teacher/" + identity + "/" + uid
                jobs.append((name, lambda name=name, unit=unit, identity=identity: self.op(name,
                              lambda: self.backend.teacher(unit, identity), binary=True,
                              cost={"branch_NFE": 3 if identity == "original_backdoor" else 5})))
        values = self.parallel(jobs)
        teachers = {identity: {uid: values["teacher/" + identity + "/" + uid] for uid in units} for identity in identities}
        cache = self.op("cache/assembled", lambda: self.backend.assemble_cache(units, teachers), binary=True)
        if cache["protocol_sha256"] != self.sha or cache["unit_ids"] != expected:
            raise IntegrityError("Assembled cache identity differs.")
        self.store.publish("prompt_and_cache_index.json", {"protocol_sha256": self.sha, "prompts": self.p["prompts"],
                            "unit_ids": cache["unit_ids"], "B_star_rms": cache["B_star_rms"],
                            "trajectories": {key: {"seed": value["seed"], "trajectory_source": value["trajectory_source"],
                              "snapshots": {str(step): {k: v for k, v in snap.items() if k != "latent"} for step, snap in value["snapshots"].items()}}
                              for key, value in trajectories.items()}})
        if not math.isfinite(cache["B_star_rms"]) or cache["B_star_rms"] <= self.p["loss"]["fit_response_signal_rms_min_exclusive"]:
            raise ResearchStop("stop_unidentifiable_proxy_signal")
        return cache

    def responses(self, cache, candidates):
        jobs = [("response/" + name, lambda name=name: self.op("response/" + name,
                 lambda: self.backend.response(cache, self.coefficients[name]), cost={"branch_NFE": 456})) for name in candidates]
        values = self.parallel(jobs)
        return {"protocol_sha256": self.sha, "B_star_rms": cache["B_star_rms"], "unit_ids": cache["unit_ids"],
                "candidates": {name: values["response/" + name] for name in candidates}}

    def train(self, cache):
        checkpoints = {}
        for family in FAMILIES:
            checkpoints[(family, 0)] = self.op(f"training/{family}/step00", lambda family=family: self.backend.init_training(family), binary=True)
        tasks = self.backend.spec["training_tasks"]
        logs, candidates = {}, {}
        # Consecutive pairs have distinct families and distinct fixed worker slots.
        # A pair starts only after the previous pair commits, satisfying every n-1 dependency.
        for offset in range(0, len(tasks), 2):
            jobs = []
            for task in tasks[offset:offset + 2]:
                family, step = task["family"], task["step"]
                previous = checkpoints[(family, step - 1)]
                if previous["family"] != family or previous["step"] != step - 1:
                    raise IntegrityError("Model/Adam checkpoint dependency mismatch.")
                name, uid = task["operation"], task["unit_id"]
                jobs.append((name, lambda name=name, previous=previous, uid=uid: self.op(name,
                    lambda: self.backend.train_one(cache, previous, uid), binary=True,
                    cost={"optimizer_updates": 1, "branch_NFE": 19, "autograd_calls_max": 7})))
            values = self.parallel(jobs)
            for task in tasks[offset:offset + 2]:
                family, step, name = task["family"], task["step"], task["operation"]
                current = values[name]
                if current["family"] != family or current["step"] != step or not all(math.isfinite(v) and 0 <= v <= 32 for v in current["coefficients"]):
                    raise ResearchStop("Invalid committed coefficients or optimization step.")
                checkpoints[(family, step)] = current
                logs[(family, step)] = {"protocol_sha256": self.sha, "family": family, "step": step,
                                       "unit_id": task["unit_id"], "coefficients": current["coefficients"],
                                       "details": current["step_report"], "worker_uuid": task["GPU_UUID"]}
                if step in self.p["optimization"]["candidate_steps"]:
                    candidate = family + "_step" + str(step)
                    artifact = self.store._paths(name, True)[1]
                    candidates[candidate] = {"coefficients": current["coefficients"], "training_operation": name,
                        "optimizer_checkpoint_path": str(artifact.relative_to(self.store.root)), "optimizer_checkpoint_sha256": file_hash(artifact)}
                    self.coefficients[candidate] = list(current["coefficients"])
                    self.store.publish("candidates/" + candidate + ".json", candidates[candidate])
        self.store.publish("learned_candidates.json", candidates)
        ordered = [logs[(family, step)] for family in FAMILIES for step in range(1, 49)]
        self.store.publish_bytes("per_step_coefficients_and_losses.jsonl", b"".join(json.dumps(x, sort_keys=True, allow_nan=False).encode() + b"\n" for x in ordered))
        return candidates

    def report(self, *args):
        self.backend.close()  # Image/optimization work is over; no card waits for CPU report formatting.
        super().report(*args)
        return json.loads((self.store.root / "final_report.json").read_text())

    def execute(self, until="report"):
        if until != "cpu-preflight":
            if self.uuids is None:
                raise IntegrityError("Actual GPU stages require both explicit allocated UUIDs.")
            spec = execution_manifest(self.p, self.sha, self.uuids)
            self.store.publish("execution_manifest.json", spec)
            self.backend.configure(spec)  # Creates descriptors only; processes remain lazy.
        try:
            return super().execute(until)
        finally:
            self.backend.close(force=True)

    def write_status(self, status, stage=None, error=None):
        import torch
        if torch.cuda.is_initialized():
            self.backend.close(force=True)
            raise IntegrityError("The dual-run parent unexpectedly initialized CUDA.")
        ledger = self.store.resource_ledger()
        per_worker = {uuid: {"known_branch_NFE": 0, "known_optimizer_updates": 0, "peak_allocated_bytes": 0} for uuid in (self.uuids or [])}
        for receipt in ledger["operations"]:
            for attempt in receipt["attempts"]:
                before, after = attempt.get("resources_before", {}), attempt.get("resources_after", {})
                uuid = after.get("worker_uuid")
                if attempt["outcome"] == "completed" and uuid in per_worker:
                    cell = per_worker[uuid]
                    cell["known_branch_NFE"] += sum(after.get("branch_nfe", {}).values()) - sum(before.get("branch_nfe", {}).values())
                    cell["known_optimizer_updates"] += after.get("optimizer_updates", 0) - before.get("optimizer_updates", 0)
                    cell["peak_allocated_bytes"] = max(cell["peak_allocated_bytes"], after.get("peak_allocated_bytes", 0))
        ledger["per_worker"] = per_worker
        atomic_json(self.store.root / "resource_ledger.json", ledger)
        atomic_json(self.store.root / "failure_or_completion_status.json", {
            "status": status, "stage": stage, "completed_stages": self.completed_stages, "updated_at": utc_now(),
            "protocol_sha256": self.sha, "run_identity_sha256": self.store.identity_hash,
            "assignment_sha256": self.backend.spec["assignment_sha256"] if self.backend.spec else None,
            "error_type": type(error).__name__ if error else None, "error": str(error) if error else None,
            "configured_GPU_workers": 2, "parent_CUDA_initialized": False,
            "worker_pids_started_this_process": [c.process.pid for c in self.backend.clients if c.process is not None],
            "real_SD_CUDA_preflight_passed": "gpu-diagnostic" in self.completed_stages,
            "all_workers_exit_on_failure_or_completion": True})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Frozen TSSA MVP on two allocated GPUs; CPU parent and per-task atomic recovery.")
    parser.add_argument("command", choices=("plan", "run"))
    parser.add_argument("--protocol", type=Path, default=PROJECT_ROOT / "research/tssa_mvp_2026-10-26.json")
    parser.add_argument("--asset-manifest", type=Path, default=PROJECT_ROOT / "research/tssa_mvp_assets_2026-10-26.json")
    parser.add_argument("--models-root", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--gpu-uuids", nargs=2, metavar=("UUID_A", "UUID_B"))
    parser.add_argument("--until", choices=STAGES, default="report")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--recover-inflight", action="store_true", help="Explicit interrupted-operation replay only; extra prior work is preserved")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    protocol, sha = load_protocol(args.protocol)
    if args.command == "plan" or args.dry_run:
        plan = experiment_plan(protocol, sha)
        plan.update(execution_entrypoint="dual_spawn", GPU_workers_if_executed=2,
                    training_updates_per_worker=[72, 72], diagnostic_extra_branch_NFE=276)
        if args.gpu_uuids:
            plan["execution_manifest"] = execution_manifest(protocol, sha, args.gpu_uuids)
        if args.output:
            atomic_json(args.output, plan)
        else:
            print(canonical_bytes(plan).decode(), end="")
        return 0
    if not args.models_root or not args.run_dir:
        parser.error("run requires --models-root and --run-dir")
    if args.until != "cpu-preflight" and not args.gpu_uuids:
        parser.error("GPU stages require --gpu-uuids with the two allocated full UUIDs")
    if args.recover_inflight and not args.resume:
        parser.error("--recover-inflight requires --resume")
    # Parent CPU libraries cannot accidentally select either worker's device.
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ.pop("GPU_UUID", None)
    store = runner = backend = None
    old_term = signal.getsignal(signal.SIGTERM)
    try:
        def interrupt(signum, frame):
            raise KeyboardInterrupt(f"Signal {signum}; both project workers will exit.")
        signal.signal(signal.SIGTERM, interrupt)
        identity = build_identity(args.protocol, args.asset_manifest, args.models_root)
        identity.update(backend=DualBackend.kind, single_GPU_sequential_CPU_scoring=False, GPU_worker_count=2)
        identity["implementation_sha256"][Path(__file__).name] = file_hash(__file__)
        store = DualRunStore(args.run_dir, identity, resume=args.resume, recover_inflight=args.recover_inflight)
        backend = DualBackend(args.protocol, args.asset_manifest, args.models_root, store)
        runner = DualMVPRunner(protocol, sha, store, backend, args.gpu_uuids)
        runner.execute(args.until)
        return 0
    except BaseException as error:
        if backend:
            backend.close(force=True)
        status = "interrupted" if isinstance(error, (KeyboardInterrupt, InterruptedOperation)) else "stopped_by_gate" if isinstance(error, ResearchStop) else "failed"
        if runner:
            runner.write_status(status, error=error)
            atomic_bytes(store.root / "last_failure_traceback.txt", traceback.format_exc().encode())
        print(json.dumps({"status": status, "error_type": type(error).__name__, "error": str(error)}), file=sys.stderr)
        return 3 if status == "interrupted" else 2
    finally:
        if backend:
            backend.close(force=True)
        if store:
            store.close()
        signal.signal(signal.SIGTERM, old_term)


if __name__ == "__main__":
    raise SystemExit(main())
