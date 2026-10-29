"""Short-lived operator attestation plus live, read-only GPU process checks."""
from __future__ import annotations

import datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time
import xml.etree.ElementTree as ET

UUID = re.compile(r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_VALID_SECONDS = 120
XORG_PATHS = frozenset(("/usr/lib/xorg/Xorg", "/usr/bin/Xorg", "/usr/libexec/Xorg"))


def _instant(value):
    if not isinstance(value, str):
        raise ValueError("UTC timestamp is required")
    try:
        result = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid permit timestamp") from exc
    if result.tzinfo is None or result.utcoffset() != datetime.timedelta(0):
        raise ValueError("permit timestamps must include UTC offset")
    return result


def _process_owner(pid):
    return (Path("/proc") / pid).stat().st_uid


def _proc_executable(pid):
    return str((Path("/proc") / pid / "exe").resolve(strict=True))


def _cmdline_executable(pid):
    command = (Path("/proc") / pid / "cmdline").read_bytes().split(b"\0", 1)[0]
    path = os.fsdecode(command)
    if path not in XORG_PATHS:
        raise ValueError("Xorg cmdline does not identify a known system executable")
    return str(Path(path).resolve(strict=True))


def _file_metadata(path):
    return Path(path).stat()


def _xorg(pid, name, process_type):
    if process_type != "G" or Path(name).name != "Xorg" or not pid.isdigit():
        return None
    try:
        owner = _process_owner(pid)
        if owner != 0:
            return None
        source = "proc_exe"
        try:
            executable = _proc_executable(pid)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EPERM):
                raise
            executable = _cmdline_executable(pid)
            source = "proc_cmdline_fallback_exe_inaccessible"
        info = _file_metadata(executable)
        if _process_owner(pid) != owner or not _trusted_xorg(process_type, name, owner, executable, info.st_uid, info.st_mode):
            return None
        return {"pid": pid, "verification": source, "exe_readable": source == "proc_exe", "system_path_evidence": executable}
    except (OSError, RuntimeError, ValueError):
        return None


def _trusted_xorg(kind, name, process_uid, executable, executable_uid, mode):
    return (kind == "G" and Path(name).name == "Xorg" and process_uid == 0 and executable in XORG_PATHS
            and executable_uid == 0 and stat.S_ISREG(mode) and bool(mode & stat.S_IXUSR)
            and not mode & (stat.S_IWGRP | stat.S_IWOTH))


def check_gpu_xml(xml_bytes, uuid):
    """Reject unknown state, disallowed mode and all except verified root Xorg."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError("nvidia-smi returned invalid GPU status") from exc
    matches = [gpu for gpu in root.findall("gpu") if gpu.findtext("uuid") == uuid]
    if root.tag != "nvidia_smi_log" or len(matches) != 1:
        raise ValueError("GPU UUID missing, ambiguous or status unknown")
    gpu = matches[0]
    if gpu.findtext("compute_mode") != "Default":
        raise ValueError("GPU compute mode is disabled, exclusive or unknown")
    processes = gpu.find("processes")
    if processes is None or (processes.text and processes.text.strip()):
        raise ValueError("GPU process status is unknown")
    xorg = []
    for process in processes:
        if process.tag != "process_info":
            raise ValueError("GPU process status is unknown")
        pid, name, kind = process.findtext("pid"), process.findtext("process_name"), process.findtext("type")
        evidence = _xorg(pid, name, kind) if isinstance(pid, str) and isinstance(name, str) else None
        if not evidence:
            raise ValueError("GPU has a non-system-Xorg or unknown process")
        xorg.append(evidence)
    return {"gpu_uuid": uuid, "compute_mode": "Default", "system_xorg_processes": len(xorg), "xorg_evidence": xorg}


def validate_permit(data, plan, server, uuid, nonce, ready_at, now):
    if not isinstance(data, dict) or data.get("task_id") != "TCL-20261029-01" or data.get("run_id") != plan.run_id or data.get("manifest_sha256") != plan.manifest_sha or data.get("server") != server or data.get("gpu_uuid") != uuid or data.get("nonce") != nonce:
        raise ValueError("permit identity or nonce does not match this CPU preflight")
    issued, expires = _instant(data.get("issued_at_utc")), _instant(data.get("expires_at_utc"))
    platform = data.get("platform")
    if not isinstance(platform, dict):
        raise ValueError("platform status is unknown")
    observed = _instant(platform.get("observed_at_utc"))
    if (observed < ready_at or issued < observed or issued > now or now >= expires
            or expires <= issued or (expires - issued).total_seconds() > MAX_VALID_SECONDS):
        raise ValueError("permit or platform observation is stale or invalid")
    if (platform.get("source") != "https://gpu.orz2333.fun/" or platform.get("sampling_valid") is not True
            or platform.get("disabled") is not False or platform.get("allocation_conflict") is not False
            or platform.get("quota_available") is not True or not isinstance(platform.get("evidence_sha256"), str)
            or not SHA.fullmatch(platform["evidence_sha256"])):
        raise ValueError("platform permission is disabled, conflicting or unknown")
    return expires


def _read_owned(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_size > 16384:
            raise ValueError("permit must be a small owned regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read()
        return json.loads(raw), hashlib.sha256(raw).hexdigest()
    finally:
        os.close(fd)


def wait_for_resource(output, plan, server, phase, emit, wait_seconds=1800):
    """Wait for a post-preflight permit, then query the live card before CUDA."""
    uuid = os.environ.get("GPU_UUID", "").strip()
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    if not UUID.fullmatch(uuid) or visible != uuid:
        raise ValueError("one matching full GPU UUID must be explicitly selected")
    if not 1 <= wait_seconds <= 3600:
        raise ValueError("resource wait must be between 1 and 3600 seconds")
    ready_at = datetime.datetime.now(datetime.timezone.utc)
    nonce = secrets.token_hex(16)
    path = Path(output) / "resource_permit.json"
    emit("waiting_resource_permit", {"gpu_uuid": uuid, "phase": phase, "nonce": nonce,
         "ready_at_utc": ready_at.isoformat(), "permit_path": str(path), "max_valid_seconds": MAX_VALID_SECONDS})
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if path.exists() or path.is_symlink():
            try:
                data, digest = _read_owned(path)
                now = datetime.datetime.now(datetime.timezone.utc)
                expires = validate_permit(data, plan, server, uuid, nonce, ready_at, now)
            except (ValueError, OSError, json.JSONDecodeError):
                time.sleep(.5)
                continue
            result = subprocess.run(["nvidia-smi", "-q", "-x"], capture_output=True, check=True, timeout=15)
            observed = check_gpu_xml(result.stdout, uuid)
            if datetime.datetime.now(datetime.timezone.utc) >= expires:
                raise ValueError("resource permit expired during the GPU process check")
            emit("resource_permit_verified", {"permit_sha256": digest, "expires_at_utc": expires.isoformat(),
                 "platform_observation": "operator_attested", "live_gpu": observed})
            return expires
        time.sleep(.5)
    raise TimeoutError("no current resource permit for this CPU preflight")
