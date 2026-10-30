"""Fail-closed attempt accounting and signed live-source observation for a shard."""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_signature(message, signature, public_key, expected_key_sha, principal, namespace):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", principal) or sha(public_key) != expected_key_sha:
        raise ValueError("untrusted signer identity or key")
    words = public_key.decode("ascii").split()
    if len(words) < 2 or words[0] != "ssh-ed25519":
        raise ValueError("signer must use Ed25519")
    base64.b64decode(words[1], validate=True)
    with tempfile.TemporaryDirectory(prefix="tcl-shard-signature-") as directory:
        allowed, sig = Path(directory) / "allowed", Path(directory) / "sig"
        allowed.write_text(f"{principal} {words[0]} {words[1]}\n")
        sig.write_bytes(signature)
        result = subprocess.run(["/usr/bin/ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", principal,
                                 "-n", namespace, "-s", str(sig)], input=message,
                                capture_output=True, timeout=15)
        if result.returncode:
            raise ValueError("detached signature failed verification")


def verify_watch(envelope_path, public_key, key_sha, principal, plan_sha, plan, machine_sha, now=None):
    path = Path(envelope_path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("live source witness unavailable")
    envelope = json.loads(path.read_bytes())
    message = base64.b64decode(envelope["message_b64"], validate=True)
    signature = base64.b64decode(envelope["signature_b64"], validate=True)
    verify_signature(message, signature, public_key, key_sha, principal, "tcl-shard-watch")
    data = json.loads(message)
    expected = {"status": "source_quiescent_observation", "plan_sha256": plan_sha,
        "run_id": plan["run_id"], "manifest_sha256": plan["manifest_sha256"],
        "source_machine_sha256": machine_sha, "source_attempts_logical_sha256": plan["source_attempts_logical_sha256"],
        "pid": 586456, "pid_start_ticks": 9222972}
    if any(data.get(k) != value for k, value in expected.items()):
        raise ValueError("source witness identity differs")
    threads = data.get("threads")
    starts = {586456: 9222972, 588542: 9253469}
    if not isinstance(threads, list) or len(threads) != 2 or {r.get("pid") for r in threads if isinstance(r, dict)} != set(starts):
        raise ValueError("source witness task set differs")
    for row in threads:
        if row.get("start_ticks") != starts[row["pid"]] or type(row.get("flags")) is not int or not row["flags"] & 4 or row.get("fdsize") != 0:
            raise ValueError("source witness does not prove PF_EXITING and closed file table")
    lock = data.get("lock_line", "").split()
    if (len(lock) != 8 or not lock[0].endswith(":") or not lock[0][:-1].isdigit()
            or lock[1:5] != ["FLOCK", "ADVISORY", "WRITE", "586456"]
            or lock[5] != "08:01:337064389" or lock[6:] != ["0", "EOF"]):
        raise ValueError("source witness does not identify the original lock")
    try:
        issued = datetime.datetime.fromisoformat(data["issued_at_utc"])
        expires = datetime.datetime.fromisoformat(data["expires_at_utc"])
    except (ValueError, KeyError) as exc:
        raise ValueError("invalid source witness timestamps") from exc
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if (issued.tzinfo is None or expires.tzinfo is None or issued.utcoffset() != datetime.timedelta(0)
            or expires.utcoffset() != datetime.timedelta(0) or issued > now or now >= expires
            or not 0 < (expires - issued).total_seconds() <= 30):
        raise ValueError("source witness expired or invalid")
    return {"watch_sha256": sha(message), "expires_at_utc": expires.isoformat()}


class GuardedLedger:
    """Wrap a local shard ledger; no new key or retry outside the signed plan."""
    def __init__(self, ledger, plan, watch):
        self.ledger, self.plan, self.watch = ledger, plan, watch
        self.allowed = {tuple(key) for key in plan["allowed_keys"]}
        encoded = json.dumps(plan["allowed_keys"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if (len(self.allowed) != 1704 or plan.get("shard_attempt_limit") != 1704
                or sha(encoded) != plan.get("allowed_keys_sha256")
                or plan.get("source_attempts_already_charged") != 344
                or plan.get("baseline_combined_attempt_limit") != 2048
                or tuple(plan["unresolved_excluded"]) in self.allowed):
            raise ValueError("invalid shard partition or accounting")
        self._check_budget()

    def __getattr__(self, name):
        return getattr(self.ledger, name)

    def _check_budget(self):
        if self.ledger.db.execute("SELECT COUNT(*) FROM attempt_history").fetchone()[0]:
            raise ValueError("shard retries are not authorized")
        if self.ledger.db.execute("SELECT COUNT(*) FROM attempt_dispositions").fetchone()[0]:
            raise ValueError("shard dispositions are not authorized")
        if self.ledger.db.execute("SELECT COUNT(*) FROM gates").fetchone()[0]:
            raise ValueError("shard must not evaluate baseline gates")
        records = self.ledger.db.execute("SELECT run_id,state,version,class,context_id,seed,status,input_sha,mask_sha FROM attempts").fetchall()
        for run, state, version, category, context, seed, status, input_sha, mask_sha in records:
            if (run != self.ledger.run_id or (state, version, category, context, seed) not in self.allowed
                    or status not in ("started", "complete")
                    or input_sha != self.ledger.bindings.input_hashes.get((state, context, category))
                    or mask_sha != self.ledger.bindings.mask_hashes.get(version)):
                raise ValueError("existing shard attempt differs from frozen partition")
        used = self.ledger.attempt_count("source")
        if used > 1704 or 344 + used > 2048:
            raise ValueError("shard attempt budget exhausted")

    def start(self, state, version, category, context_id, seed, input_sha, mask_sha):
        key = (state, version, category, context_id, seed)
        if key not in self.allowed:
            raise ValueError("scientific unit is outside the signed disjoint shard")
        self._check_budget()
        prior = self.ledger.db.execute("SELECT status FROM attempts WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?", (self.ledger.run_id, *key)).fetchone()
        if prior is not None and prior[0] != "complete":
            raise ValueError("started shard unit cannot be replayed")
        if prior is None:
            if self.ledger.attempt_count("source") >= 1704:
                raise ValueError("shard attempt budget exhausted")
            self.watch()
        return self.ledger.start(state, version, category, context_id, seed, input_sha, mask_sha)

    def checkpoint_resource(self, *args):
        self.watch()
        return self.ledger.checkpoint_resource(*args)

    def complete(self, *args):
        self.watch()
        return self.ledger.complete(*args)
