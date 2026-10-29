"""Durable upper-bound reservations for TCL localization TE forwards.

This is an incomplete component, not a model runner. Reserved but unresolved
forwards remain an explicit stop condition and are counted against the limit.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

KINDS = ("trigger", "dog", "cat", "other")
BASELINES = ("clean", "backdoor")
CONTROLS = ("new", "magnitude", "block_magnitude", "random_1", "random_2", "random_3")
LIMIT = 264192


class LocalizationLedger:
    def __init__(self, path, run_id, manifest_sha, contexts, block_ids):
        if not isinstance(run_id, str) or not run_id or not isinstance(manifest_sha, str) or len(manifest_sha) != 64 or any(c not in "0123456789abcdef" for c in manifest_sha):
            raise ValueError("run and manifest hash are required")
        if len(contexts) != 64 or len(set(contexts)) != 64 or any(not isinstance(x, str) or not x for x in contexts):
            raise ValueError("exactly 64 unique localization contexts required")
        if not 1 <= len(block_ids) <= 1024 or len(set(block_ids)) != len(block_ids) or any(not isinstance(x, str) or not x for x in block_ids):
            raise ValueError("between 1 and 1024 unique block identities required")
        self.contexts = frozenset(contexts)
        self.units = frozenset(["baseline:" + x for x in BASELINES] + ["block:" + x for x in block_ids] + ["control:" + x for x in CONTROLS])
        self.db = sqlite3.connect(path, isolation_level=None, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS units (name TEXT PRIMARY KEY, status TEXT NOT NULL, evidence_sha TEXT, evidence BLOB);
            CREATE TABLE IF NOT EXISTS forwards (unit TEXT NOT NULL, class TEXT NOT NULL, context TEXT NOT NULL,
                status TEXT NOT NULL, output_sha TEXT, output BLOB,
                PRIMARY KEY(unit,class,context));
            CREATE TABLE IF NOT EXISTS forward_history (id INTEGER PRIMARY KEY, unit TEXT NOT NULL, class TEXT NOT NULL,
                context TEXT NOT NULL, status TEXT NOT NULL, output_sha TEXT, output BLOB, reason TEXT NOT NULL, time_utc TEXT NOT NULL);
        """)
        identity = json.dumps({"run_id": run_id, "manifest_sha": manifest_sha,
                               "contexts": contexts, "block_ids": block_ids}, sort_keys=True, separators=(",", ":"))
        previous = self.db.execute("SELECT value FROM metadata WHERE id=1").fetchone()
        if previous is None:
            self.db.execute("INSERT INTO metadata VALUES(1,?)", (identity,))
        elif previous[0] != identity:
            raise ValueError("localization ledger identity differs from frozen input")

    def close(self):
        self.db.close()

    def attempt_count(self):
        return self.db.execute("SELECT (SELECT COUNT(*) FROM forwards)+(SELECT COUNT(*) FROM forward_history)").fetchone()[0]

    def begin(self, unit):
        if unit not in self.units:
            raise ValueError("unit outside frozen localization plan")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM units WHERE name=?", (unit,)).fetchone():
                raise ValueError("started localization unit cannot be replayed")
            if not unit.startswith("baseline:"):
                count = self.db.execute("SELECT COUNT(*) FROM units WHERE name IN ('baseline:clean','baseline:backdoor') AND status='complete'").fetchone()[0]
                if count != 2:
                    raise ValueError("both baseline outputs are required before intervention")
            if unit.startswith("control:"):
                count = self.db.execute("SELECT COUNT(*) FROM units WHERE name LIKE 'block:%' AND status='complete'").fetchone()[0]
                if count != sum(name.startswith("block:") for name in self.units):
                    raise ValueError("all single-block scores required before controls")
            self.db.execute("INSERT INTO units VALUES(?, 'started', NULL, NULL)", (unit,))
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def reserve(self, unit, kind, context):
        """Persist one reservation before invocation; never silently replay."""
        if unit not in self.units or kind not in KINDS or context not in self.contexts:
            raise ValueError("forward outside frozen localization unit")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT status FROM units WHERE name=?", (unit,)).fetchone() != ("started",):
                raise ValueError("unit not active")
            existing = self.db.execute("SELECT status FROM forwards WHERE unit=? AND class=? AND context=?", (unit,kind,context)).fetchone()
            if existing == ("complete",):
                self.db.execute("COMMIT")
                return False
            if existing == ("retry_ready",):
                self.db.execute("UPDATE forwards SET status='started' WHERE unit=? AND class=? AND context=?", (unit, kind, context))
                self.db.execute("COMMIT")
                return True
            if existing is not None:
                raise ValueError("forward reserved but output uncertain; cannot silently replay")
            count = self.attempt_count()
            if count >= LIMIT:
                raise ValueError("localization budget exhausted")
            try:
                self.db.execute("INSERT INTO forwards VALUES(?,?,?, 'started', NULL, NULL)", (unit, kind, context))
            except sqlite3.IntegrityError as exc:
                raise ValueError("forward already reserved and cannot be replayed") from exc
            self.db.execute("COMMIT")
            return True
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def record(self, unit, kind, context, output):
        """Persist a complete caller-serialized embedding and its SHA256 atomically."""
        if not isinstance(output, bytes) or not output:
            raise ValueError("a nonempty serialized output is required")
        digest = hashlib.sha256(output).hexdigest()
        updated = self.db.execute("UPDATE forwards SET status='complete',output_sha=?,output=? WHERE unit=? AND class=? AND context=? AND status='started'", (digest, output, unit, kind, context))
        if updated.rowcount != 1:
            raise ValueError("forward was not reserved or already completed")
        return digest

    def load(self, unit, kind, context):
        row = self.db.execute("SELECT status,output_sha,output FROM forwards WHERE unit=? AND class=? AND context=?", (unit,kind,context)).fetchone()
        if row is None or row[0] != "complete" or row[2] is None or hashlib.sha256(row[2]).hexdigest() != row[1]:
            raise ValueError("complete hash-verified output unavailable")
        return row[2]

    def resume(self, unit):
        if self.db.execute("SELECT status FROM units WHERE name=?", (unit,)).fetchone() != ("started",):
            raise ValueError("unit is not incomplete")
        rows = self.db.execute("SELECT class,context,status,output_sha,output FROM forwards WHERE unit=?", (unit,)).fetchall()
        if any(status not in ("complete", "retry_ready") or (status == "complete" and (blob is None or hashlib.sha256(blob).hexdigest() != digest)) for _,_,status,digest,blob in rows):
            raise ValueError("reserved forward has uncertain or corrupt output")
        return {(kind, context): blob for kind,context,status,_,blob in rows if status == "complete"}

    def complete(self, unit, evidence):
        if not isinstance(evidence, bytes) or not evidence:
            raise ValueError("durable unit evidence is required")
        evidence_sha = hashlib.sha256(evidence).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            count = self.db.execute("SELECT COUNT(*) FROM forwards WHERE unit=? AND status='complete' AND output_sha IS NOT NULL AND output IS NOT NULL", (unit,)).fetchone()[0]
            if count != 256:
                raise ValueError("unit requires all 256 reserved prompt forwards")
            rows = self.db.execute("SELECT output_sha,output FROM forwards WHERE unit=?", (unit,)).fetchall()
            if any(hashlib.sha256(blob).hexdigest() != digest for digest, blob in rows):
                raise ValueError("localization output hash mismatch")
            updated = self.db.execute("UPDATE units SET status='complete',evidence_sha=?,evidence=? WHERE name=? AND status='started'", (evidence_sha, evidence, unit))
            if updated.rowcount != 1:
                raise ValueError("unit not started or already completed")
            if unit.startswith("block:"):
                # Single-block embeddings are no longer required after their
                # aggregate receipt; retain baseline and all six combinations.
                self.db.execute("UPDATE forwards SET output=NULL WHERE unit=?", (unit,))
            self.db.execute("COMMIT")
            return evidence_sha
        except Exception:
            self.db.execute("ROLLBACK")
            raise
