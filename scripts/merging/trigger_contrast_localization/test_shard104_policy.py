import base64
import datetime
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from evidence import Ledger

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "research/tasks/2026-10-29-trigger-contrast-localization/shard104_policy.py"
spec = importlib.util.spec_from_file_location("shard104_policy_fixture", SOURCE)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)
SHA = "a" * 64


class ShardPolicyTests(unittest.TestCase):
    def fixture(self, root):
        ids = {"source": [f"s{i:03}" for i in range(128)], "merge": [f"m{i:03}" for i in range(128)]}
        ledger = Ledger(root / "shard.sqlite", "run", SHA, ids, [1, 2])
        universe = sorted(("source", version, category, context, seed) for version in ("clean", "backdoor")
                          for category in ("trigger", "dog", "cat", "other") for context in ids["source"] for seed in (1, 2))
        allowed, excluded = universe[:1704], universe[1704]
        ledger.bindings = SimpleNamespace(input_hashes={(state, context, category): SHA for state, values in ids.items() for context in values for category in ('trigger', 'dog', 'cat', 'other')}, mask_hashes={'clean': SHA, 'backdoor': SHA})
        plan = {"run_id": "run", "manifest_sha256": SHA, "source_attempts_logical_sha256": "b" * 64,
                "allowed_keys": allowed, "unresolved_excluded": excluded, "shard_attempt_limit": 1704,
                "source_attempts_already_charged": 344, "baseline_combined_attempt_limit": 2048}
        plan['allowed_keys_sha256'] = policy.sha(json.dumps(allowed, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
        return ledger, plan

    def test_budget_allowlist_and_no_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger, plan = self.fixture(Path(directory))
            calls = []
            wrapped = policy.GuardedLedger(ledger, plan, lambda: calls.append(1))
            key = plan["allowed_keys"][0]
            self.assertTrue(wrapped.start(*key, SHA, SHA))
            with self.assertRaisesRegex(ValueError, "cannot be replayed"):
                wrapped.start(*key, SHA, SHA)
            with self.assertRaisesRegex(ValueError, "outside"):
                wrapped.start(*plan["unresolved_excluded"], SHA, SHA)
            self.assertEqual(ledger.attempt_count("source"), 1)
            self.assertEqual(len(calls), 1)
            ledger.close()

    def test_expired_source_witness_blocks_new_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger, plan = self.fixture(Path(directory))
            def reject():
                raise ValueError("source witness expired")
            wrapped = policy.GuardedLedger(ledger, plan, reject)
            with self.assertRaisesRegex(ValueError, "expired"):
                wrapped.start(*plan["allowed_keys"][0], SHA, SHA)
            self.assertEqual(ledger.attempt_count("source"), 0)
            ledger.close()

    def test_signed_source_witness_identity_and_expiration(self):
        if not shutil.which("ssh-keygen"):
            self.skipTest("OpenSSH ssh-keygen is required")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "witness_key"
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
            public = Path(str(key) + ".pub").read_bytes()
            ledger, plan = self.fixture(root)
            now = datetime.datetime.now(datetime.timezone.utc)
            report = {"status": "source_quiescent_observation", "plan_sha256": "c" * 64, "run_id": "run",
                "manifest_sha256": SHA, "source_machine_sha256": "d" * 64, "source_attempts_logical_sha256": "b" * 64,
                "pid": 586456, "pid_start_ticks": 9222972,
                "threads": [{"pid": 586456, "start_ticks": 9222972, "flags": 4, "fdsize": 0},
                            {"pid": 588542, "start_ticks": 9253469, "flags": 4, "fdsize": 0}],
                "lock_line": "8: FLOCK ADVISORY WRITE 586456 08:01:337064389 0 EOF",
                "issued_at_utc": now.isoformat(), "expires_at_utc": (now + datetime.timedelta(seconds=30)).isoformat()}
            message = json.dumps(report, sort_keys=True).encode()
            data = root / "observation"
            data.write_bytes(message)
            subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "tcl-shard-watch", str(data)],
                           check=True, capture_output=True)
            signature = Path(str(data) + ".sig").read_bytes()
            envelope = root / "watch.json"
            envelope.write_text(json.dumps({"message_b64": base64.b64encode(message).decode(),
                                            "signature_b64": base64.b64encode(signature).decode()}))
            args = (envelope, public, hashlib.sha256(public).hexdigest(), "watcher", "c" * 64, plan, "d" * 64)
            self.assertEqual(policy.verify_watch(*args, now=now)["watch_sha256"], hashlib.sha256(message).hexdigest())
            with self.assertRaisesRegex(ValueError, "expired"):
                policy.verify_watch(*args, now=now + datetime.timedelta(seconds=31))
            with self.assertRaisesRegex(ValueError, "identity"):
                policy.verify_watch(envelope, public, hashlib.sha256(public).hexdigest(), "watcher", "e" * 64, plan, "d" * 64, now=now)
            report['lock_line'] = report['lock_line'].replace(' 0 EOF', ' 1 EOF')
            bad = json.dumps(report, sort_keys=True).encode()
            data.write_bytes(bad)
            Path(str(data) + '.sig').unlink()
            subprocess.run(['ssh-keygen', '-Y', 'sign', '-f', str(key), '-n', 'tcl-shard-watch', str(data)], check=True, capture_output=True)
            envelope.write_text(json.dumps({'message_b64':base64.b64encode(bad).decode(),
                'signature_b64':base64.b64encode(Path(str(data) + '.sig').read_bytes()).decode()}))
            with self.assertRaisesRegex(ValueError, 'lock'):
                policy.verify_watch(*args, now=now)
            ledger.close()


if __name__ == "__main__":
    unittest.main()
