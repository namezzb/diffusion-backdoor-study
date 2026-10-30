#!/usr/bin/env python3
"""Plan, or explicitly fetch, one hash-indexed research file (Python stdlib only).

Default mode has no network or writes. Downloads require configured SSH credentials
and already verified host keys for BOTH school-jump and the selected server.
Uses system DNS, without changing DNS, credentials, SSH configuration or host keys.
"""

import argparse
import contextlib
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shlex
import signal
import stat
import subprocess
import sys
import time
import unicodedata
import uuid


ROOTS = {"103": "/data1/zhangzibo/arxiv-tssa", "104": "/data2/zhangzibo/arxiv-tssa", "127": "/data1/zhangzibo/arxiv-tssa"}
CHUNK = 1024 * 1024
DEFAULT_MAX_BYTES = 8 * 1024 ** 3
DEFAULT_RESERVE_BYTES = 512 * 1024 ** 2


class FetchError(ValueError):
    pass


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def relative_path(value):
    if (not isinstance(value, str) or not value or value.startswith("/")
            or "\\" in value or any(unicodedata.category(c).startswith("C") for c in value)
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise FetchError("unsafe relative path")
    return value


def local_absolute(value):
    value = os.fspath(value)
    if (not value or any(unicodedata.category(c).startswith("C") for c in value)
            or ".." in Path(value).parts):
        raise FetchError("unsafe local path")
    return Path(os.path.abspath(value))


def open_directory(path, create=False, missing_ok=False):
    """Keep an open directory descriptor; never follow symlinks, including ancestors."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(os.path.sep, flags)
    try:
        for name in local_absolute(path).parts[1:]:
            try:
                child = os.open(name, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    if missing_ok:
                        os.close(fd)
                        return None
                    raise
                try:
                    os.mkdir(name, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(name, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextlib.contextmanager
def regular_read(path):
    path = local_absolute(path)
    parent = open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise FetchError("input is not a regular file")
            yield source
    finally:
        os.close(parent)


def validate_entry(row, server, wanted, max_bytes=DEFAULT_MAX_BYTES):
    wanted = relative_path(wanted)
    if server not in ROOTS or not isinstance(row, dict):
        raise FetchError("unsupported server or index entry")
    if (row.get("server") != server or row.get("ssh_alias") != "school" + server
            or row.get("remote_root") != ROOTS[server]
            or row.get("relative_path") != wanted
            or row.get("remote_path") != ROOTS[server] + "/" + wanted):
        raise FetchError("index server/root/path does not match the allowed research directory")
    size = row.get("bytes")
    if type(size) is not int or size < 0 or size > max_bytes:
        raise FetchError("index size is invalid or exceeds --max-bytes")
    digest = row.get("sha256")
    if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise FetchError("invalid index SHA256")
    return dict(row)


def load_entry(repo, server, wanted, max_bytes=DEFAULT_MAX_BYTES):
    if server not in ROOTS:
        raise FetchError("unsupported server")
    relative_path(wanted)
    index = local_absolute(repo) / "storage" / "server-index" / (server + ".jsonl")
    found = []
    with regular_read(index) as source:
        for number, raw in enumerate(source, 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise FetchError("invalid JSON at index line " + str(number)) from exc
            if not isinstance(row, dict):
                raise FetchError("index entry is not an object")
            if row.get("relative_path") == wanted:
                found.append(validate_entry(row, server, wanted, max_bytes))
    if len(found) != 1:
        raise FetchError("expected exactly one index entry; found " + str(len(found)))
    return found[0]


def existing_matches(parent, name, entry):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    except FileNotFoundError:
        return False
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != entry["bytes"]:
            raise FetchError("destination conflicts; refusing overwrite")
        digest = hashlib.sha256()
        for chunk in iter(lambda: source.read(CHUNK), b""):
            digest.update(chunk)
        if digest.hexdigest() != entry["sha256"]:
            raise FetchError("destination conflicts; refusing overwrite")
    return True


# The remote helper only opens the selected file beneath the fixed research root.
# Descriptor-relative O_NOFOLLOW also rejects symlinks in the root's ancestors.
REMOTE_READER = r'''
import os, pwd, stat, sys, unicodedata
def require(condition, message):
    if not condition:
        raise RuntimeError(message)
root, rel, expected = sys.argv[1], sys.argv[2], int(sys.argv[3])
require(root in ("/data1/zhangzibo/arxiv-tssa", "/data2/zhangzibo/arxiv-tssa"), "unapproved root")
require(rel and not rel.startswith("/") and "\\" not in rel, "invalid relative path")
require(all(p not in ("", ".", "..") for p in rel.split("/")), "invalid path component")
require(not any(unicodedata.category(c).startswith("C") for c in rel), "control character in path")
uid = os.geteuid()
require(pwd.getpwuid(uid).pw_name == "zhangzibo", "unexpected remote account")
flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
parent = os.open("/", flags)
try:
    for part in root.strip("/").split("/"):
        child = os.open(part, flags, dir_fd=parent)
        os.close(parent)
        parent = child
    require(os.fstat(parent).st_uid == uid, "research root is not owned by account")
    parts = rel.split("/")
    for part in parts[:-1]:
        child = os.open(part, flags, dir_fd=parent)
        os.close(parent)
        parent = child
        require(os.fstat(parent).st_uid == uid, "directory not owned by account")
    fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == uid, "not an owned regular file")
        require(0 <= expected <= 8 * 1024 ** 3 and info.st_size == expected, "size changed")
        remaining = expected
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            require(chunk, "file truncated")
            sys.stdout.buffer.write(chunk)
            remaining -= len(chunk)
        require(not source.read(1), "file grew")
        after = os.fstat(source.fileno())
        require((info.st_size, info.st_mtime_ns, info.st_ctime_ns) == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "file changed")
        sys.stdout.buffer.flush()
finally:
    os.close(parent)
'''


def ssh_command(config, entry):
    config = local_absolute(config)
    with regular_read(config):
        pass
    common = ["ssh", "-F", str(config), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
              "-o", "UpdateHostKeys=no", "-o", "PasswordAuthentication=no", "-o",
              "KbdInteractiveAuthentication=no", "-o", "ConnectTimeout=60", "-o", "ConnectionAttempts=1"]
    proxy_common = [item.replace("%", "%%") for item in common]
    proxy = shlex.join(proxy_common + ["-W", "%h:%p", "school-jump"])
    remote = shlex.join(["python3", "-I", "-c", REMOTE_READER,
                         entry["remote_root"], entry["relative_path"], str(entry["bytes"])])
    return common + ["-T", "-n", "-o", "ProxyCommand=" + proxy,
                     "school" + entry["server"], remote]


def ssh_chunks(config, entry, timeout):
    """Drain both pipes with an overall deadline; only our SSH process group is stopped."""
    command = ssh_command(config, entry)
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError("SSH download timed out; no retry was attempted")
                for key, _ in selector.select(min(1, remaining)):
                    chunk = os.read(key.fileobj.fileno(), CHUNK)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    elif key.fileobj is process.stdout:
                        yield chunk
                    # Drain stderr but do not persist authentication or server banners.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchError("SSH download timed out")
            code = process.wait(timeout=remaining)
            if code:
                raise FetchError("SSH/remote reader exited with code " + str(code)
                                 + "; check access, DNS, verified host keys and remote file metadata")
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
        process.stdout.close()
        process.stderr.close()


def transfer(entry, target, chunks, reserve_bytes):
    destination = local_absolute(target) / entry["relative_path"]
    parent = open_directory(destination.parent, create=True)
    part = ".research-fetch-" + uuid.uuid4().hex + ".part"
    created = False
    try:
        if existing_matches(parent, destination.name, entry):
            return "reused_existing_verified_file"
        disk = os.fstatvfs(parent)
        if disk.f_bavail * disk.f_frsize < entry["bytes"] + reserve_bytes:
            raise FetchError("insufficient free space including required reserve")
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        created = True
        digest, size = hashlib.sha256(), 0
        with os.fdopen(fd, "wb") as output:
            stream = chunks()
            try:
                for chunk in stream:
                    size += len(chunk)
                    if size > entry["bytes"]:
                        raise FetchError("download exceeds indexed size")
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            finally:
                close = getattr(stream, "close", None)
                if close:
                    close()
        if size != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
            raise FetchError("download size/SHA256 differs from saved index; file not published")
        try:
            os.link(part, destination.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        except FileExistsError:
            if existing_matches(parent, destination.name, entry):
                return "reused_concurrent_verified_file"
            raise
        os.fsync(parent)
        return "downloaded_and_verified"
    finally:
        if created:
            os.unlink(part, dir_fd=parent)
        os.close(parent)


def download(entry, target, receipt, chunks, reserve_bytes=DEFAULT_RESERVE_BYTES):
    entry = validate_entry(entry, entry.get("server"), entry.get("relative_path"))
    if not entry["sha256"]:
        raise FetchError("metadata-only index entry has no SHA256; download is blocked until a trusted hash is recorded")
    if type(reserve_bytes) is not int or reserve_bytes < 0:
        raise FetchError("invalid disk reserve")
    target, receipt = local_absolute(target), local_absolute(receipt)
    if os.path.commonpath([target, receipt]) == str(target):
        raise FetchError("receipt must be outside the target directory")
    # Reserve a new receipt before connecting so a completed transfer is always attributable.
    receipt_parent = open_directory(receipt.parent, create=True)
    try:
        fd = os.open(receipt.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=receipt_parent)
    finally:
        os.close(receipt_parent)
    audit = {"schema_version": 1, "started_at": utc_now(), "server": entry["server"],
             "remote_path": entry["remote_path"], "inventory_observed_at": entry.get("inventory_observed_at"),
             "index_sha256": entry["sha256"], "bytes": entry["bytes"],
             "destination": str(target / entry["relative_path"]),
             "remote_read_only": True, "GPU_started": False, "status": "failed"}
    try:
        audit["status"] = transfer(entry, target, chunks, reserve_bytes)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        audit["error"] = str(exc)
    except BaseException:
        audit["error"] = "interrupted"
        raise
    finally:
        audit["finished_at"] = utc_now()
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(audit, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    return audit


def main(argv=None, repo=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", choices=sorted(ROOTS), required=True)
    parser.add_argument("relative_path", help="exact relative_path in storage/server-index/<server>.jsonl")
    parser.add_argument("--target", required=True, help="local directory; indexed relative path is preserved beneath it")
    parser.add_argument("--download", action="store_true", help="explicitly connect and download; otherwise only print a plan")
    parser.add_argument("--receipt", help="new receipt path outside target; default storage/receipts/fetch-<unique>.json")
    parser.add_argument("--timeout", type=float, default=600, help="whole SSH transfer deadline in seconds (default 600)")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="file size ceiling; maximum 8 GiB")
    parser.add_argument("--reserve-bytes", type=int, default=DEFAULT_RESERVE_BYTES, help="keep this many bytes free (default 512 MiB)")
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 86400:
            raise FetchError("timeout must be between 1 and 86400 seconds")
        if not 0 <= args.max_bytes <= DEFAULT_MAX_BYTES or args.reserve_bytes < 0:
            raise FetchError("invalid size ceiling or disk reserve")
        repo = Path(repo) if repo is not None else Path(__file__).resolve().parents[2]
        entry = load_entry(repo, args.server, args.relative_path, args.max_bytes)
        target = local_absolute(args.target)
        config = repo / "server" / "school_ssh_config"
        # Validate configured inputs and existing destination ancestors even in plan mode.
        ssh_command(config, entry)
        parent = open_directory(target / Path(entry["relative_path"]).parent, missing_ok=True)
        if parent is not None:
            os.close(parent)
        receipt = local_absolute(args.receipt) if args.receipt else repo / "storage" / "receipts" / ("fetch-" + uuid.uuid4().hex + ".json")
        if not args.download:
            print(json.dumps({"mode": "plan_only", "network_started": False, "server": args.server,
                              "remote_path": entry["remote_path"], "bytes": entry["bytes"], "sha256": entry["sha256"],
                              "destination": str(target / entry["relative_path"]), "receipt": str(receipt),
                              "download_eligible": bool(entry["sha256"]),
                              "blocker": None if entry["sha256"] else "metadata-only; trusted SHA256 is missing",
                              "index_observed_at": entry.get("inventory_observed_at"),
                              "live_server_state_checked": False,
                              "requirements": "Configure SSH credentials and verified host keys separately; system DNS must resolve school-jump."},
                             ensure_ascii=False, indent=2))
            return 0
        audit = download(entry, target, receipt, lambda: ssh_chunks(config, entry, args.timeout), args.reserve_bytes)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 1 if audit["status"] == "failed" else 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
