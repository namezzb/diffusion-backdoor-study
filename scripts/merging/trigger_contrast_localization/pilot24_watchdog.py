"""T0 persistence and a local process-group deadline supervisor.

The launcher authenticates worker code, authorization and the shared T0.
Supervision uses a monotonic deadline so wall-clock rollback cannot extend it.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from pilot24_inputs import RUN
from pilot24_worker_ledger import is_sha


def create_t0(path, manifest_sha, *, now_utc=None):
    if not is_sha(manifest_sha):
        raise ValueError("frozen manifest SHA256 required")
    path = Path(path)
    timestamp = now_utc or datetime.now(timezone.utc).isoformat()
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("T0 must be explicit UTC")
    payload = {"run_id": RUN, "manifest_sha256": manifest_sha, "t0_utc": timestamp}
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        # Retain an incomplete record for manual reconciliation; never reset T0.
        raise
    return hashlib.sha256(raw).hexdigest()


def load_t0(path, expected_file_sha, expected_manifest_sha):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not is_sha(expected_file_sha) or not is_sha(expected_manifest_sha):
        raise ValueError("T0 record and identities are required")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_file_sha:
        raise ValueError("T0 record changed")
    payload = json.loads(raw)
    if set(payload) != {"run_id", "manifest_sha256", "t0_utc"} or payload["run_id"] != RUN or payload["manifest_sha256"] != expected_manifest_sha:
        raise ValueError("T0 record belongs to a different run")
    parsed = datetime.fromisoformat(payload["t0_utc"].replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("T0 must be explicit UTC")
    return payload


def supervise(argv, t0_utc, *, grace_seconds=5, stop_file=None, stdout=None):
    """Supervise only our child process group; stop its descendants as well."""
    t0 = datetime.fromisoformat(t0_utc.replace("Z", "+00:00"))
    if (t0.tzinfo is None or t0.utcoffset().total_seconds() != 0 or not isinstance(argv, list)
            or not argv or any(not isinstance(x, str) or not x for x in argv)
            or not 0 < grace_seconds <= 30):
        raise ValueError("valid UTC, bounded grace and explicit argv required")
    remaining = 22.25 * 3600 - (datetime.now(timezone.utc) - t0).total_seconds()
    if remaining <= 0 or remaining > 22.25 * 3600:
        raise ValueError("T0 is future or the compute deadline has passed")
    until = time.monotonic() + remaining
    proc = subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=stdout,
                            stderr=subprocess.STDOUT if stdout is not None else None)
    stopped = False
    reason = "worker_exited"
    try:
        while proc.poll() is None:
            wall_left = 22.25 * 3600 - (datetime.now(timezone.utc) - t0).total_seconds()
            left = min(until - time.monotonic(), wall_left)
            if left <= grace_seconds or (stop_file and Path(stop_file).exists()):
                stopped = True
                reason = "coordinator_stop" if stop_file and Path(stop_file).exists() else "compute_deadline"
                break
            try:
                proc.wait(timeout=min(1.0, max(.001, left - grace_seconds)))
            except subprocess.TimeoutExpired:
                pass
    finally:
        # The newly created group is owned exclusively by this launch.  No
        # global GPU reset, user-wide process kill, or PID discovered by name.
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=max(.001, min(grace_seconds, until - time.monotonic())))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        # A completed group leader can leave descendants; clean up that group.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return {"returncode": proc.returncode, "deadline_stop": stopped,
            "stop_reason": reason, "owned_process_group": proc.pid}
