"""Durable per-worker attempt accounting for the pilot24 implementation.

This module is not a launcher and does not authenticate an assignment or
establish that an earlier writer has exited. The coordinator must do both.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import uuid

from pilot24_inputs import RUN, SEED


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def is_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


class WorkerLedger:
    """One ledger, bound permanently to a finite key assignment."""

    def __init__(self, directory, assignment):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("worker directory must not be a symlink")
        self.root = self.root.resolve()
        if (not isinstance(assignment, dict) or assignment.get("run_id") != RUN
                or assignment.get("stage") not in ("S0", "S1", "M0", "M1")
                or not isinstance(assignment.get("worker_id"), str) or not assignment["worker_id"]
                or not is_sha(assignment.get("manifest_sha256"))
                or not is_sha(assignment.get("gate_sha256"))
                or type(assignment.get("retry_tokens")) is not int
                or not 0 <= assignment["retry_tokens"] <= 64):
            raise ValueError("invalid worker assignment")
        units = assignment.get("units")
        if not isinstance(units, list) or not units:
            raise ValueError("assignment must contain finite units")
        keys = []
        for unit in units:
            if (not isinstance(unit, dict) or set(unit) != {"key", "input_sha", "mask_sha"}
                    or not is_sha(unit["input_sha"]) or not is_sha(unit["mask_sha"])):
                raise ValueError("invalid assigned unit")
            key = unit["key"]
            stage = assignment["stage"]
            expected_state = "source" if stage.startswith("S") else "merge"
            versions = ("clean", "backdoor") if stage.endswith("0") else ("new", "magnitude", "block_magnitude", "random_1", "random_2", "random_3")
            if (not isinstance(key, list) or len(key) != 6 or key[0] != RUN or key[1] != expected_state
                    or key[2] not in versions or key[3] not in ("trigger", "dog", "cat", "other")
                    or not isinstance(key[4], str) or not key[4] or type(key[5]) is not int or key[5] != SEED):
                raise ValueError("unit outside assigned phase")
            keys.append(canonical(key))
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate assigned unit")
        try:
            for suffix in ("", "-wal", "-shm"):
                if (self.root / ("worker.sqlite" + suffix)).is_symlink():
                    raise ValueError("worker database must not be a symlink")
            self.db = sqlite3.connect(self.root / "worker.sqlite", isolation_level=None, timeout=30)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1), assignment TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS units (key TEXT PRIMARY KEY, input_sha TEXT NOT NULL, mask_sha TEXT NOT NULL,
                    status TEXT NOT NULL, image_sha TEXT, scores TEXT);
                CREATE TABLE IF NOT EXISTS attempts (key TEXT NOT NULL, number INTEGER NOT NULL,
                    status TEXT NOT NULL, resource TEXT NOT NULL, PRIMARY KEY(key,number));
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, key TEXT NOT NULL, kind TEXT NOT NULL,
                    detail TEXT NOT NULL);
            """)
            encoded = canonical(assignment)
            self.db.execute("BEGIN IMMEDIATE")
            existing = self.db.execute("SELECT assignment FROM metadata WHERE id=1").fetchone()
            if existing is None:
                self.db.execute("INSERT INTO metadata VALUES(1,?)", (encoded,))
                self.db.executemany("INSERT INTO units VALUES(?,?,?,'unstarted',NULL,NULL)",
                    [(canonical(u["key"]), u["input_sha"], u["mask_sha"]) for u in units])
            elif existing[0] != encoded:
                raise ValueError("worker directory belongs to a different assignment")
            self.db.execute("COMMIT")
            self.assignment = json.loads(encoded)
            self.session_id = uuid.uuid4().hex
            self._reopened = {row[0] for row in self.db.execute("SELECT key FROM units WHERE status='started'")}
            self._started_here = set()
        except Exception:
            if hasattr(self, "db"):
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                self.db.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def status(self, key):
        return self._unit(key)[1][0]

    def _unit(self, key):
        encoded = canonical(key)
        row = self.db.execute("SELECT status,image_sha,scores FROM units WHERE key=?", (encoded,)).fetchone()
        if row is None:
            raise ValueError("unit not assigned to this worker")
        return encoded, row

    def start(self, key):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            encoded, (status, image_sha, _) = self._unit(key)
            if status in ("scoring", "complete"):
                raise ValueError("valid image already exists; do not regenerate")
            if status not in ("unstarted", "retry_ready"):
                raise ValueError("uncertain or active attempt cannot be replayed")
            if image_sha is not None:
                raise ValueError("registered image cannot be regenerated")
            count = self.db.execute("SELECT COUNT(*) FROM attempts WHERE key=?", (encoded,)).fetchone()[0]
            if count >= 2 or (status == "unstarted" and count != 0) or (status == "retry_ready" and count != 1):
                raise ValueError("per-key generation attempt limit or state violated")
            used = self.db.execute("SELECT COUNT(*) FROM attempts WHERE number=2").fetchone()[0]
            if count == 1 and used >= self.assignment["retry_tokens"]:
                raise ValueError("worker retry tokens exhausted")
            self.db.execute("INSERT INTO attempts VALUES(?,?,'started','{}')", (encoded, count + 1))
            self.db.execute("UPDATE units SET status='started' WHERE key=?", (encoded,))
            self.db.execute("COMMIT")
            self._started_here.add(encoded)
            return count + 1
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def checkpoint(self, key, resource):
        if not isinstance(resource, dict) or any(type(v) is not int or v < 0 for v in resource.values()):
            raise ValueError("invalid resource counters")
        encoded, (status, _, _) = self._unit(key)
        if status != "started":
            raise ValueError("no active attempt")
        old = self.db.execute("SELECT resource FROM attempts WHERE key=? ORDER BY number DESC LIMIT 1", (encoded,)).fetchone()
        previous = json.loads(old[0])
        if any(k not in resource or resource[k] < value for k, value in previous.items()):
            raise ValueError("resource counters cannot decrease")
        self.db.execute("UPDATE attempts SET resource=? WHERE key=? AND number=(SELECT MAX(number) FROM attempts WHERE key=?)",
                        (canonical(resource), encoded, encoded))

    def image_path(self, key):
        encoded, _ = self._unit(key)
        count = self.db.execute("SELECT COUNT(*) FROM attempts WHERE key=?", (encoded,)).fetchone()[0]
        if count not in (1, 2):
            raise ValueError("image path requires a reserved attempt")
        raw = json.dumps(key if count == 1 else [*key, "attempt", count - 1], separators=(",", ":"), ensure_ascii=False).encode()
        return self.root / "images" / (hashlib.sha256(raw).hexdigest() + ".png")

    def register_image(self, key, image_path):
        from PIL import Image
        encoded, (status, image_sha, _) = self._unit(key)
        path = Path(image_path)
        if (path != self.image_path(key) or path.parent.is_symlink() or status != "started"
                or image_sha is not None or path.is_symlink() or not path.is_file()):
            raise ValueError("image cannot be registered for this unit")
        content = path.read_bytes()
        with Image.open(path) as image:
            if image.format != "PNG" or image.size != (512, 512):
                raise ValueError("image must be a complete 512x512 PNG")
            image.verify()
        with Image.open(path) as image:
            image.load()
        sha = hashlib.sha256(content).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("UPDATE units SET status='scoring',image_sha=? WHERE key=?", (sha, encoded))
            self.db.execute("UPDATE attempts SET status='image_persisted' WHERE key=? AND number=(SELECT MAX(number) FROM attempts WHERE key=?)", (encoded, encoded))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return sha

    def begin_score(self, key):
        encoded, (status, image_sha, _) = self._unit(key)
        if status != "scoring" or image_sha is None:
            raise ValueError("only a registered image can be scored")
        number, raw = self.db.execute("SELECT number,resource FROM attempts WHERE key=? ORDER BY number DESC LIMIT 1", (encoded,)).fetchone()
        resource = json.loads(raw)
        resource["scoring_calls"] = resource.get("scoring_calls", 0) + 1
        self.db.execute("UPDATE attempts SET resource=? WHERE key=? AND number=?", (canonical(resource), encoded, number))

    def finish_score(self, key, image_path, scores):
        encoded, (status, image_sha, _) = self._unit(key)
        path = Path(image_path)
        if (path != self.image_path(key) or path.parent.is_symlink() or status != "scoring" or path.is_symlink() or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != image_sha):
            raise ValueError("registered image is missing or altered")
        if (not isinstance(scores, dict) or set(scores) != {"vit_class", "clip_score"}
                or type(scores["vit_class"]) is not int or not 0 <= scores["vit_class"] < 1000
                or type(scores["clip_score"]) not in (int, float) or not math.isfinite(scores["clip_score"])
                or not 0 <= scores["clip_score"] <= 100):
            raise ValueError("invalid scoring record")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("UPDATE units SET status='complete',scores=? WHERE key=?", (canonical(scores), encoded))
            self.db.execute("UPDATE attempts SET status='complete' WHERE key=? AND number=(SELECT MAX(number) FROM attempts WHERE key=?)", (encoded, encoded))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def resolve_interrupted(self, key, isolation_evidence_sha):
        """The old SHA-only prototype is intentionally not an authorization path."""
        raise ValueError("a claimed evidence hash is insufficient; use recovery or fail_attempt")

    def recover_interrupted(self, key):
        """Reconcile only attempts found when this instance opened."""
        encoded, (status, _, _) = self._unit(key)
        if status != "started" or encoded not in self._reopened:
            raise ValueError("recovery requires an interrupted attempt from an earlier session")
        path = self.image_path(key)
        if path.exists() or path.is_symlink():
            self.register_image(key, path)
            self._reopened.remove(encoded)
            return "scoring"
        self._interrupt(key, {"kind": "reopened_worker_ledger", "session_id": self.session_id,
            "worker_id": self.assignment["worker_id"]})
        self._reopened.remove(encoded)
        return self.status(key)

    def fail_attempt(self, key, reason):
        """Called after this process's synchronous generation has unwound."""
        encoded, (status, _, _) = self._unit(key)
        if status != "started" or encoded not in self._started_here:
            raise ValueError("only this session's finished generation call may be failed")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("failure reason required")
        path = self.image_path(key)
        if path.exists() or path.is_symlink():
            self.register_image(key, path)
            return "scoring"
        self._interrupt(key, {"kind": "synchronous_generation_exception", "session_id": self.session_id,
                              "reason": reason[:2000]})
        self._started_here.remove(encoded)
        return self.status(key)

    def _interrupt(self, key, evidence):
        encoded, (status, image_sha, _) = self._unit(key)
        if status != "started" or image_sha is not None:
            raise ValueError("only an interrupted generation without a registered PNG may retry")
        path = self.image_path(key)
        if path.parent.is_symlink() or path.exists() or path.is_symlink():
            raise ValueError("existing or ambiguous output must be reconciled before retry")
        count = self.db.execute("SELECT COUNT(*) FROM attempts WHERE key=?", (encoded,)).fetchone()[0]
        used = self.db.execute("SELECT COUNT(*) FROM attempts WHERE number=2").fetchone()[0]
        next_status = "retry_ready" if count == 1 and used < self.assignment["retry_tokens"] else "exhausted"
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("UPDATE attempts SET status='interrupted' WHERE key=? AND number=(SELECT MAX(number) FROM attempts WHERE key=?)", (encoded, encoded))
            self.db.execute("UPDATE units SET status=? WHERE key=?", (next_status, encoded))
            self.db.execute("INSERT INTO events(key,kind,detail) VALUES(?,'interruption',?)", (encoded, canonical(evidence)))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def snapshot(self, model_bundle_sha256, scorer_sha256, *, verify_images=False):
        """Export complete images and all charged attempts without merging ledgers."""
        if not is_sha(model_bundle_sha256) or not is_sha(scorer_sha256):
            raise ValueError("model and scorer provenance hashes required")
        records = []
        statuses = {}
        for raw, input_sha, mask_sha, status, image_sha, scores in self.db.execute("SELECT * FROM units ORDER BY key"):
            statuses[status] = statuses.get(status, 0) + 1
            if status != "complete":
                continue
            key = json.loads(raw)
            path = self.image_path(key)
            if verify_images and (path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != image_sha):
                raise ValueError("complete worker image is missing or altered")
            records.append({"key": key, "input_sha": input_sha, "mask_sha": mask_sha,
                "model_bundle_sha256": model_bundle_sha256, "scorer_sha256": scorer_sha256,
                "image_path": str(path.resolve()), "image_sha": image_sha, "scores": json.loads(scores)})
        attempts = [{"key": json.loads(key), "number": number, "status": status, "resource": json.loads(resource)}
                    for key, number, status, resource in self.db.execute("SELECT * FROM attempts ORDER BY key,number")]
        return {"records": records, "attempts": attempts, "unit_statuses": statuses,
                "new_generation_attempts": len(attempts), "retry_attempts": sum(a["number"] == 2 for a in attempts)}
