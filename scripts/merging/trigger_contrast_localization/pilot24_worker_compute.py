"""One v2 image unit using the frozen v1 SD backend.

Not an execution entry point: the future launcher must authenticate the v2
review, assignment, phase gate, live GPU permission, source isolation, T0 and
external deadline watchdog before constructing a runtime or calling this.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time

from pilot24_deadline import deadline_state
from pilot24_worker_ledger import canonical, is_sha


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _inputs(runtime, scorer, bindings, ledger, key):
    from tssa_mvp_score import IndependentScorer
    from generation import _validate_tokens
    if (len(key) != 6 or key[0] != ledger.assignment["run_id"]
            or bindings.run_id != ledger.assignment["run_id"]
            or bindings.manifest_sha != ledger.assignment["manifest_sha256"]):
        raise ValueError("invalid v2 unit identity")
    _, state, version, category, context, _ = key
    if getattr(runtime, "_tcl_verified_selection_sha", None) != bindings.selection_sha:
        raise ValueError("verified parent localization selection is required")
    if not isinstance(scorer, IndependentScorer) or scorer.root != runtime.assets.models_root.resolve():
        raise ValueError("pinned independent scorer is required")
    asset_hashes = {name: item["sha256"] for name, item in runtime.assets.file_hashes.items()}
    if asset_hashes != dict(bindings.asset_hashes):
        raise ValueError("loaded assets differ from the frozen parent inputs")
    encoded, _ = ledger._unit(key)
    stored = ledger.db.execute("SELECT input_sha,mask_sha FROM units WHERE key=?", (encoded,)).fetchone()
    if stored != (bindings.input_hashes.get((state, context, category)), bindings.mask_hashes.get(version)):
        raise ValueError("assigned input or mask differs from parent bindings")
    bound = bindings.prompt_rows.get((state, context, category))
    if bound is None:
        raise ValueError("missing frozen prompt")
    prompt = json.loads(bound)
    _validate_tokens(runtime.assets.tokenizer, prompt["prompt"], prompt["tokenization"])
    return prompt


def score_existing(runtime, scorer, bindings, ledger, key, t0_utc):
    from PIL import Image
    if not deadline_state(t0_utc, _utc_now())["compute_permitted"]:
        raise TimeoutError("22.25-hour compute deadline prohibits scoring")
    prompt = _inputs(runtime, scorer, bindings, ledger, key)
    path = ledger.image_path(key)
    encoded, (status, image_sha, _) = ledger._unit(key)
    if (status != "scoring" or path.is_symlink() or path.parent.is_symlink() or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != image_sha):
        raise ValueError("no registered complete image awaiting scoring")
    with Image.open(path) as image:
        ledger.begin_score(key)
        scores = scorer.score(image.convert("RGB"), prompt["score_prompt"])
    ledger.finish_score(key, path, scores)
    return {"image_sha256": image_sha, "scores": scores, "new_generation": False}


def generate_one(runtime, scorer, bindings, ledger, key, t0_utc):
    """Reserve and compute one unit; no remote operation occurs per forward."""
    from generation import sample_prepared
    from states import compose_state
    import torch
    prompt = _inputs(runtime, scorer, bindings, ledger, key)
    if not deadline_state(t0_utc, _utc_now())["generation_permitted"]:
        raise ValueError("22-hour stop prohibits starting an image")
    _, state, version, category, context, seed = key
    ledger.start(key)
    heartbeat = getattr(ledger, "heartbeat", None)
    if heartbeat is not None:
        # Publish the charged attempt before any model installation or forward.
        heartbeat(force=True)
    path = ledger.image_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.exists() or path.is_symlink():
        raise ValueError("image destination already exists")
    mask_sha = bindings.mask_hashes[version]
    identity = ("tcl", state, version, mask_sha)
    if getattr(runtime, "active", None) != identity:
        raw = json.loads(bindings.coordinate_masks[version])
        coordinates = {name: torch.tensor(indices, dtype=torch.int64) for name, indices in raw.items()}
        source_version = version if version in ("clean", "backdoor") else "restored"
        assets = runtime.assets
        te_state, unet_state = compose_state(assets.text_states["clean"], assets.text_states["backdoor"],
            assets.text_states["Edev"], assets.unet_states["clean"], assets.unet_states["Edev"],
            assets.parameter_names, state, source_version, coordinates if source_version == "restored" else None)
        runtime._install(identity, te_state, unet_state)
    resource = {"text_encoder_forwards": 0, "unet_branch_nfe": 0, "vae_decodes": 0}
    def before_compute(name, amount):
        if not deadline_state(t0_utc, _utc_now())["compute_permitted"]:
            raise TimeoutError("22.25-hour compute deadline reached")
        resource[name] += amount
        ledger.checkpoint(key, resource)
        heartbeat = getattr(ledger, "heartbeat", None)
        if heartbeat is not None:
            heartbeat()
    image = sample_prepared(runtime, prompt["prompt"], seed, before_compute)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    fd, temporary = tempfile.mkstemp(prefix=".pilot24-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(buffer.getvalue())
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    ledger.register_image(key, path)
    result = score_existing(runtime, scorer, bindings, ledger, key, t0_utc)
    result["new_generation"] = True
    return result


def _write_receipt(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("receipt must not traverse a symlink")
    fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(canonical(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_worker(runtime, scorer, bindings, ledger, t0_utc, receipt_path, provenance):
    """Run one immutable assignment under the launcher's watchdog and GPU grant.

    A failed generation is charged before one bounded retry. Persisted images
    resume scoring only; unknown files and altered completed images stop work.
    """
    for name in ("assignment_sha256", "t0_sha256", "model_bundle_sha256", "scorer_sha256"):
        if not is_sha(provenance.get(name)):
            raise ValueError("missing worker receipt provenance: " + name)
    assignment = ledger.assignment
    if (not isinstance(assignment.get("assignment_id"), str) or not assignment["assignment_id"]
            or provenance.get("run_id", assignment["run_id"]) != assignment["run_id"]):
        raise ValueError("invalid worker assignment identity")
    identity = {name: assignment[name] for name in ("run_id", "manifest_sha256", "assignment_id", "stage", "worker_id")}
    identity.update({name: provenance[name] for name in ("assignment_sha256", "t0_sha256")})
    started = time.monotonic()
    last_saved = 0.0
    errors = []

    def publish(status="running", *, force=False, verify=False):
        nonlocal last_saved
        if not force and time.monotonic() - last_saved < 30:
            return None
        receipt = {**identity, "status": status, "t0_utc": t0_utc, "updated_at_utc": _utc_now(),
                   "elapsed_seconds": time.monotonic() - started, "errors": errors[-16:],
                   **ledger.snapshot(provenance["model_bundle_sha256"], provenance["scorer_sha256"], verify_images=verify)}
        receipt["assigned_unique_keys"] = len(assignment["units"])
        _write_receipt(receipt_path, receipt)
        last_saved = time.monotonic()
        return receipt

    ledger.heartbeat = publish
    # Verify completed files once on restart, not quadratically on each heartbeat.
    publish(force=True, verify=True)
    terminal = "complete"
    try:
        # Persisted images get their independent scores even after the 22-hour
        # generation cutoff; this does not allocate another image attempt.
        units = sorted(assignment["units"], key=lambda unit: ledger.status(unit["key"]) not in ("complete", "scoring"))
        for unit in units:
            key = unit["key"]
            if ledger.status(key) == "started":
                ledger.recover_interrupted(key)
            score_failures = 0
            while ledger.status(key) != "complete":
                status = ledger.status(key)
                phase = deadline_state(t0_utc, _utc_now())
                if (not phase["compute_permitted"]
                        or status in ("unstarted", "retry_ready") and not phase["generation_permitted"]):
                    terminal = "deadline"
                    return publish(terminal, force=True, verify=True)
                if status == "exhausted":
                    terminal = "blocked"
                    break
                try:
                    if status == "scoring":
                        score_existing(runtime, scorer, bindings, ledger, key, t0_utc)
                    elif status in ("unstarted", "retry_ready"):
                        generate_one(runtime, scorer, bindings, ledger, key, t0_utc)
                    else:
                        raise ValueError("unexpected unit state: " + status)
                except Exception as exc:
                    errors.append({"key": key, "type": type(exc).__name__, "message": str(exc)[:2000]})
                    status = ledger.status(key)
                    if status == "started":
                        status = ledger.fail_attempt(key, type(exc).__name__ + ": " + str(exc))
                        runtime.active = None
                    if isinstance(exc, TimeoutError) or not deadline_state(t0_utc, _utc_now())["compute_permitted"]:
                        terminal = "deadline"
                        return publish(terminal, force=True, verify=True)
                    if status == "scoring":
                        score_failures += 1
                        if score_failures < 2:
                            publish(force=True)
                            continue
                    elif status == "retry_ready":
                        publish(force=True)
                        continue
                    terminal = "blocked"
                    return publish(terminal, force=True, verify=True)
                publish(force=True)
        return publish(terminal, force=True, verify=True)
    except Exception as exc:
        errors.append({"type": type(exc).__name__, "message": str(exc)[:2000]})
        publish("blocked", force=True)
        raise
    finally:
        ledger.heartbeat = None


def _process_identity():
    # Linux's process start ticks disambiguate PID reuse in a permission grant.
    stat = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
    return {"pid": os.getpid(), "uid": os.getuid(), "start_ticks": int(stat[19])}


def run_session(mailbox, receipt_root, bundle_path, worker_id, t0_path, t0_sha,
                permission_ref, stop_file, *, poll_seconds=5):
    """Keep exactly one authorized runtime per GPU across finite assignments.

    The coordinator publishes each immutable assignment to a local mailbox.
    The initial CPU-ready receipt lets a separate live checker issue a fresh
    permission; subsequent phases reuse the same process, assets and GPU.
    """
    from pilot24_runtime import prepare_worker, prepare_assets, create_runtime
    from pilot24_provenance import validate_worker_permission
    from pilot24_worker_ledger import WorkerLedger
    from pilot24_watchdog import load_t0

    if (not isinstance(worker_id, str) or not 0 < len(worker_id) <= 128
            or any(not (c.isalnum() or c in "-_") for c in worker_id) or not 0 < poll_seconds <= 30):
        raise ValueError("worker identity and bounded local poll interval required")
    mailbox, receipt_root = Path(mailbox).resolve(), Path(receipt_root).resolve()
    mailbox.mkdir(parents=True, exist_ok=True)
    receipt_root.mkdir(parents=True, exist_ok=True)
    permission_ref, stop_file = Path(permission_ref), Path(stop_file)
    completed = set()
    runtime = scorer = None
    fixed = None
    first = None
    t0 = None
    session_root = receipt_root / "sessions" / worker_id
    session_path = session_root / "session.json"

    def status(kind, **fields):
        value = {"worker_id": worker_id, "status": kind, "updated_at_utc": _utc_now(),
                 "completed_assignments": sorted(completed), **fields}
        _write_receipt(session_path, value)
        return value

    def timing():
        return deadline_state(t0["t0_utc"], _utc_now())

    try:
        while True:
            if stop_file.exists():
                return status("stopped", reason="coordinator_or_watchdog_stop")
            if t0 is not None and not timing()["compute_permitted"]:
                return status("deadline", reason="22_25_hour_compute_cutoff")
            jobs = sorted(mailbox.glob("*.json"))
            for job in jobs:
                if job.stem in completed:
                    continue
                if job.is_symlink():
                    raise ValueError("mailbox request must not be a symlink")
                request = json.loads(job.read_text())
                if not isinstance(request, dict) or set(request) != {"assignment", "gate"}:
                    raise ValueError("mailbox request requires only assignment and gate paths")
                prepared = prepare_worker(bundle_path, request["assignment"], request["gate"])
                assignment = prepared.assignment
                if assignment.get("worker_id") != worker_id or assignment.get("assignment_id") != job.stem:
                    raise ValueError("mailbox assignment belongs to another worker or identity")
                current = (prepared.manifest_sha256, worker_id, assignment.get("server"), assignment.get("gpu_uuid"),
                           prepared.model_bundle_sha256, prepared.scorer_sha256,
                           prepared.bindings.selection_sha, prepared.gate.get("config_sha256"))
                if fixed is not None and current != fixed:
                    raise ValueError("persistent session cannot change reviewed inputs, coordinator or GPU")
                if t0 is None:
                    t0 = load_t0(t0_path, t0_sha, prepared.manifest_sha256)
                    if os.environ.get("PILOT24_SUPERVISED") != t0_sha:
                        raise ValueError("session requires its reviewed absolute-deadline supervisor")
                if not timing()["compute_permitted"]:
                    return status("deadline", reason="22_25_hour_compute_cutoff")
                progress = receipt_root / assignment["assignment_id"] / "progress.json"
                # The lock is held before GPU initialization and until this
                # assignment finishes, including the initial permission wait.
                with WorkerLedger(assignment["output_root"], assignment) as ledger:
                    for unit in assignment["units"]:
                        if ledger.status(unit["key"]) == "started":
                            ledger.recover_interrupted(unit["key"])
                    if (not timing()["generation_permitted"]
                            and not any(ledger.status(unit["key"]) == "scoring" for unit in assignment["units"])):
                        return status("deadline", reason="22_hour_no_new_generation")
                    if runtime is None:
                        prepare_assets(prepared)
                        ready = {"worker_id": worker_id, "status": "cpu_ready_waiting_permission",
                            "run_id": assignment["run_id"], "manifest_sha256": prepared.manifest_sha256,
                            "assignment_id": assignment["assignment_id"], "assignment_sha256": prepared.assignment_sha256,
                            "server": assignment["server"], "gpu_uuid": assignment["gpu_uuid"],
                            "launcher": _process_identity(), "t0_sha256": t0_sha,
                            "ready_at_utc": _utc_now()}
                        _write_receipt(session_root / "ready.json", ready)
                        status("waiting_permission", assignment_id=assignment["assignment_id"])
                        while True:
                            if stop_file.exists():
                                return status("stopped", reason="stop_before_gpu_creation")
                            if not timing()["compute_permitted"]:
                                return status("deadline", reason="permission_not_available_before_cutoff")
                            if permission_ref.is_file():
                                if permission_ref.is_symlink():
                                    raise ValueError("permission reference must not be a symlink")
                                reference = json.loads(permission_ref.read_text())
                                if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
                                        or not is_sha(reference["sha256"])):
                                    raise ValueError("invalid live permission reference")
                                # A present but rejected grant is an actionable
                                # blocker, never an endless permission retry loop.
                                validate_worker_permission(prepared, reference["path"], reference["sha256"])
                                break
                            time.sleep(poll_seconds)
                        runtime, scorer = create_runtime(prepared, device="cuda")
                        fixed, first = current, prepared
                    elif runtime.assets is not first.assets:
                        raise ValueError("persistent runtime lost its verified CPU asset binding")
                    provenance = {"assignment_sha256": prepared.assignment_sha256, "t0_sha256": t0_sha,
                                  "model_bundle_sha256": prepared.model_bundle_sha256,
                                  "scorer_sha256": prepared.scorer_sha256}
                    result = run_worker(runtime, scorer, prepared.bindings, ledger, t0["t0_utc"], progress, provenance)
                if result["status"] != "complete":
                    return status(result["status"], assignment_id=assignment["assignment_id"],
                                  reason="assignment_did_not_complete", receipt_path=str(progress))
                completed.add(assignment["assignment_id"])
                status("waiting_assignment", assignment_id=assignment["assignment_id"])
                if stop_file.exists():
                    return status("stopped", reason="coordinator_or_watchdog_stop")
            time.sleep(poll_seconds)
    except Exception as exc:
        status("blocked", error_type=type(exc).__name__, error=str(exc)[:2000])
        raise
