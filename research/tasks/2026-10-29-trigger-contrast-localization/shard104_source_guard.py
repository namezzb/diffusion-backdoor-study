"""Read-only 103 source observation for the reviewed 104 shard witness.

The observer must run on the original host via an authenticated channel.  Its
output is not permission until a trusted coordinator signs the exact bytes.
"""
from __future__ import annotations

import datetime
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def process_stat(text):
    end = text.rfind(")")
    if end < 0:
        raise ValueError("malformed proc stat")
    head, rest = text[:end + 1], text[end + 1:].split()
    if len(rest) < 20:
        raise ValueError("incomplete proc stat")
    return {"pid": int(head.split(" ", 1)[0]), "state": rest[0], "flags": int(rest[6]), "start_ticks": int(rest[19])}


def _task_snapshot(proc, pid, pid_start, thread_starts):
    root = proc / str(pid)
    leader = process_stat((root / "stat").read_text())
    if leader["pid"] != pid or leader["start_ticks"] != pid_start:
        raise ValueError("source process identity changed")
    tasks = sorted((root / "task").iterdir(), key=lambda p: int(p.name))
    if {p.name for p in tasks} != {str(value) for value in thread_starts}:
        raise ValueError("source task set changed; reassess before continuing")
    results = []
    for task in tasks:
        info = process_stat((task / "stat").read_text())
        status = dict(line.split(":", 1) for line in (task / "status").read_text().splitlines() if ":" in line)
        if (info["pid"] != int(task.name) or info["start_ticks"] != thread_starts[info["pid"]]
                or int(status.get("Tgid", "-1")) != pid or not info["flags"] & 4
                or int(status.get("FDSize", "-1")) != 0):
            raise ValueError("source task is not verifiably in PF_EXITING with no file table")
        info["fdsize"] = 0
        results.append(info)
    return results


def _lock_owned(proc, lock_path, pid):
    info = lock_path.stat()
    wanted = (os.major(info.st_dev), os.minor(info.st_dev), info.st_ino)
    found = []
    for line in (proc / "locks").read_text().splitlines():
        parts = line.split()
        if (len(parts) != 8 or not parts[0].endswith(":") or not parts[0][:-1].isdigit()
                or parts[1:4] != ["FLOCK", "ADVISORY", "WRITE"] or parts[4] != str(pid)
                or parts[6:] != ["0", "EOF"]):
            continue
        try:
            dev_major, dev_minor, inode = parts[5].split(":")
            ident = (int(dev_major, 16), int(dev_minor, 16), int(inode))
        except (ValueError, IndexError):
            continue
        if ident == wanted:
            found.append((line, (parts[1], parts[2], parts[3], int(parts[4]), *ident, parts[6], parts[7])))
    if len(found) != 1:
        raise ValueError("original source lock is not verifiably held by the original PID")
    return found[0]


def observe(source_root, proc, machine_id_file, expected_machine_sha, pid, pid_start,
            thread_starts, expected_attempts_sha, run_id, manifest_sha, plan_sha, now=None):
    """Bind source process, lock and committed ledger state to one short observation."""
    root, proc = Path(source_root), Path(proc)
    machine_sha = hashlib.sha256(Path(machine_id_file).read_bytes()).hexdigest()
    if machine_sha != expected_machine_sha:
        raise ValueError("source machine identity differs")
    identity = json.loads((root / "run_identity.json").read_bytes())
    if identity.get("run_id") != run_id or identity.get("manifest_sha256") != manifest_sha or identity.get("server") != "school103":
        raise ValueError("source run identity differs")
    first = _task_snapshot(proc, pid, pid_start, thread_starts)
    lock_line, lock_identity = _lock_owned(proc, root / ".run.lock", pid)
    db_path = root / "images.sqlite"
    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError("source image ledger missing or symlinked")
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        meta = json.loads(db.execute("SELECT value FROM metadata WHERE id=1").fetchone()[0])
        if meta.get("run_id") != run_id or meta.get("manifest_sha") != manifest_sha:
            raise ValueError("live source ledger identity differs")
        rows = db.execute("SELECT run_id,state,version,class,context_id,seed,status,input_sha,mask_sha,image_sha,scores,resource FROM attempts").fetchall()
        if db.execute("SELECT COUNT(*) FROM attempt_history").fetchone()[0] or db.execute("SELECT COUNT(*) FROM gates").fetchone()[0]:
            raise ValueError("source ledger history or gates changed")
        logical_sha = hashlib.sha256(canonical(sorted(rows, key=lambda row: row[1:6]))).hexdigest()
    if logical_sha != expected_attempts_sha:
        raise ValueError("source attempts changed since the reviewed snapshot")
    second = _task_snapshot(proc, pid, pid_start, thread_starts)
    second_lock_line, second_lock_identity = _lock_owned(proc, root / ".run.lock", pid)
    if first != second or second_lock_identity != lock_identity:
        raise ValueError("source process or lock changed during observation")
    now = now or datetime.datetime.now(datetime.timezone.utc)
    issued = now - datetime.timedelta(seconds=2)
    return {"status": "source_quiescent_observation", "plan_sha256": plan_sha, "run_id": run_id,
            "manifest_sha256": manifest_sha, "source_machine_sha256": machine_sha,
            "source_attempts_logical_sha256": logical_sha, "pid": pid, "pid_start_ticks": pid_start,
            "threads": second, "lock_line": second_lock_line, "issued_at_utc": issued.isoformat(),
            "expires_at_utc": (issued + datetime.timedelta(seconds=30)).isoformat()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan-sha256", "source-attempts-sha256", "manifest-sha256", "source-machine-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    record = observe("/data1/zhangzibo/arxiv-tssa/results/tcl-20261029-01-v1", "/proc", "/etc/machine-id",
                     args.source_machine_sha256, 586456, 9222972, {586456: 9222972, 588542: 9253469},
                     args.source_attempts_sha256, "tcl-20261029-01-v1", args.manifest_sha256, args.plan_sha256)
    sys.stdout.buffer.write(canonical(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
