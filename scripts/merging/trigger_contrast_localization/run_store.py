"""Owned data-disk run directory and append-only execution event records."""
from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import tempfile
import uuid

SCHOOL_RESULTS = {"school103": Path("/data1/zhangzibo/arxiv-tssa/results"),
                  "school104": Path("/data2/zhangzibo/arxiv-tssa/results")}


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _no_symlinks(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("run path includes a symbolic link: " + str(part))


def _check_data_disk(base):
    if base.stat().st_dev == Path("/").stat().st_dev:
        raise ValueError("run directory must reside on a non-system data filesystem")
    info = os.statvfs(base)
    if info.f_frsize * info.f_blocks < 256 * 1024**3:
        raise ValueError("data filesystem is smaller than the required 256 GiB")


def prepare_run_root(output_root, plan, manifest):
    server = manifest.get("server")
    if server not in SCHOOL_RESULTS:
        raise ValueError("this runner currently supports explicitly registered school103 or school104 paths")
    if pwd.getpwuid(os.geteuid()).pw_name != "zhangzibo":
        raise ValueError("school run must use the zhangzibo account")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", plan.run_id) or ".." in plan.run_id:
        raise ValueError("unsafe run identity")
    path = Path(output_root)
    expected = SCHOOL_RESULTS[server] / plan.run_id
    if not path.is_absolute() or path != expected or str(path) != manifest.get("output_root"):
        raise ValueError("output root differs from the registered server data path")
    _no_symlinks(path)
    user_root = SCHOOL_RESULTS[server].parents[1]
    if not user_root.is_dir() or user_root.stat().st_uid != os.geteuid():
        raise ValueError("registered data directory is not owned by the current user")
    _check_data_disk(user_root)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    _no_symlinks(parent)
    if parent.stat().st_uid != os.geteuid():
        raise ValueError("results directory is not owned by the current user")
    identity = _canonical({"run_id": plan.run_id, "manifest_sha256": plan.manifest_sha, "server": server})
    try:
        path.mkdir()
        identity_path = path / "run_identity.json"
        fd = os.open(identity_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(identity)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if not path.is_dir() or path.stat().st_uid != os.geteuid():
            raise ValueError("existing run path is not an owned directory")
        identity_path = path / "run_identity.json"
        if identity_path.is_symlink() or not identity_path.is_file() or identity_path.read_bytes() != identity:
            raise ValueError("existing directory does not carry this exact run identity")
    return path


def append_event(root, plan, phase, status, detail):
    event = {"run_id": plan.run_id, "manifest_sha256": plan.manifest_sha, "phase": phase, "status": status,
             "time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "detail": detail}
    data = _canonical(event)
    directory = Path(root) / "events"
    directory.mkdir(exist_ok=True)
    _no_symlinks(directory)
    path = directory / (uuid.uuid4().hex + ".json")
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".event-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def lock_run(root):
    path = Path(root) / ".run.lock"
    if path.is_symlink():
        raise ValueError("run lock cannot be a symlink")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        os.close(fd)
        raise
    return fd
