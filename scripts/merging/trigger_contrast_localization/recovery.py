"""Explicit, budgeted disposition of interrupted reservations under the run lock."""
from __future__ import annotations

import datetime
import fcntl
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from generation import _image_path
from localization_ledger import LIMIT
from evidence import MAX_IMAGES_PER_STATE


def recover_interrupted(output, plan, kind, reason, lock_fd):
    """Caller must hold the exclusive run lock and have authenticated the plan.

    Archive uncertain attempts and reserve replacements in one transaction. A
    replacement already reserved but not started is left intact across restarts.
    """
    if kind not in ("localization", "images") or not isinstance(reason, str) or len(reason.strip()) < 8:
        raise ValueError("recovery needs a kind and a concrete reason of at least eight characters")
    root = Path(output)
    lock_path = root / ".run.lock"
    if lock_path.is_symlink() or not lock_path.is_file() or os.fstat(lock_fd).st_ino != lock_path.stat().st_ino or os.fstat(lock_fd).st_dev != lock_path.stat().st_dev:
        raise ValueError("the matching run lock is required for recovery")
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    path = root / ("localization.sqlite" if kind == "localization" else "images.sqlite")
    if path.is_symlink() or not path.is_file():
        raise ValueError("existing run ledger is required for recovery")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    score_only = []
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=30)
    try:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        identity = json.loads(db.execute("SELECT value FROM metadata WHERE id=1").fetchone()[0])
        if identity.get("run_id") != plan.run_id or identity.get("manifest_sha") != plan.manifest_sha:
            raise ValueError("recovery ledger belongs to a different frozen run")
        if kind == "localization":
            rows = db.execute("SELECT unit,class,context,status,output_sha,output FROM forwards WHERE status='started' ORDER BY unit,class,context").fetchall()
            used = db.execute("SELECT (SELECT COUNT(*) FROM forwards)+(SELECT COUNT(*) FROM forward_history)").fetchone()[0]
            if used + len(rows) > LIMIT:
                raise ValueError("localization budget insufficient for recovery")
            for row in rows:
                db.execute("INSERT INTO forward_history(unit,class,context,status,output_sha,output,reason,time_utc) VALUES(?,?,?,?,?,?,?,?)", (*row, reason, now))
                db.execute("UPDATE forwards SET status='retry_ready',output_sha=NULL,output=NULL WHERE unit=? AND class=? AND context=? AND status='started'", row[:3])
        else:
            if (root / "images").is_symlink():
                raise ValueError("image directory must not be a symbolic link")
            rows = db.execute("SELECT run_id,state,version,class,context_id,seed,input_sha,mask_sha,status,image_sha,scores,resource FROM attempts WHERE status='started' ORDER BY state,version,class,context_id,seed").fetchall()
            retries = []
            for row in rows:
                key = row[:6]
                number = db.execute("SELECT COUNT(*) FROM attempt_history WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", key).fetchone()[0]
                image = _image_path(root / "images", key, number)
                if image.is_symlink() or (image.exists() and not image.is_file()):
                    raise ValueError("interrupted image must be a regular file")
                if image.parent.exists() and any(image.parent.glob("." + image.name + ".*")):
                    raise ValueError("interrupted image temporary file requires manual investigation")
                if image.is_file():
                    observed = hashlib.sha256(image.read_bytes()).hexdigest()
                    if row[9] is None or observed != row[9]:
                        raise ValueError("interrupted image is unregistered or its hash differs; manual investigation required")
                    from PIL import Image
                    try:
                        with Image.open(image) as saved:
                            if saved.format != "PNG":
                                raise ValueError("not a PNG")
                            saved.verify()
                    except Exception as exc:
                        raise ValueError("interrupted registered PNG is invalid; manual investigation required") from exc
                    score_only.append(row)
                elif row[9] is not None:
                    raise ValueError("registered interrupted image is missing; manual investigation required")
                else:
                    retries.append(row)
            for state in ("source", "merge"):
                used = db.execute("SELECT (SELECT COUNT(*) FROM attempts WHERE state=?)+(SELECT COUNT(*) FROM attempt_history WHERE state=?)", (state,state)).fetchone()[0]
                if used + sum(row[1] == state for row in retries) > MAX_IMAGES_PER_STATE:
                    raise ValueError(state + " image budget insufficient for recovery")
            for row in score_only:
                key = row[:6]
                db.execute("INSERT INTO attempt_dispositions(run_id,state,version,class,context_id,seed,action,image_sha,reason,time_utc) VALUES(?,?,?,?,?,?,?,?,?,?)", (*key, "resume_scoring", row[9], reason, now))
                db.execute("UPDATE attempts SET status='score_ready' WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=? AND status='started'", key)
            for row in retries:
                key = row[:6]
                number = db.execute("SELECT COUNT(*) FROM attempt_history WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", key).fetchone()[0]
                image = _image_path(root / "images", key, number)
                db.execute("INSERT INTO attempt_history(run_id,state,version,class,context_id,seed,input_sha,mask_sha,status,image_sha,scores,resource,image_path,image_observed_sha,reason,time_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (*row, str(image.relative_to(root)), None, reason, now))
                db.execute("UPDATE attempts SET status='retry_ready',image_sha=NULL,scores=NULL,resource='{}' WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=? AND status='started'", key)
        db.execute("COMMIT")
        return {"kind": kind, "archived_attempts": len(rows) - len(score_only), "resume_scoring": len(score_only), "reason": reason, "time_utc": now}
    except Exception:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()
