import base64
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'research/tasks/2026-10-29-trigger-contrast-localization'))
import shard127_watch_controller_v3_candidate as controller


class CandidateTests(unittest.TestCase):
    def test_parallel_observations_and_failure_cancels_pair(self):
        barrier = threading.Barrier(2, timeout=2)
        def collect(ssh, host, command, namespace, tmp, key):
            barrier.wait()
            if host == 'school103':
                raise ValueError('unavailable')
            return host
        with patch.object(controller, 'collect_one', side_effect=collect):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                controller.collect_pair([], 'a', 'b', '/tmp', 'key')

    def test_send_binds_both_expected_digests_before_publish(self):
        source, fence = b'one', b'two'
        expected = {'source': hashlib.sha256(source).hexdigest(), 'fence': hashlib.sha256(fence).hexdigest()}
        with patch.object(controller.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(expected).encode())) as call:
            controller.publish_pair(['ssh'], source, fence)
            self.assertEqual(call.call_count, 1)
            command = call.call_args.args[0][-1]
            self.assertIn(expected['source'], command)
            self.assertIn(expected['fence'], command)
        with patch.object(controller.subprocess, 'run', return_value=SimpleNamespace(stdout=b'{}')):
            with self.assertRaisesRegex(ValueError, 'publication differs'):
                controller.publish_pair(['ssh'], source, fence)

    def test_receive_checks_both_payloads_and_times_before_either_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); machine = root / 'machine-id'; machine.write_bytes(b'127')
            first = root / 'source'; second = root / 'fence'
            first.write_bytes(b'old source'); second.write_bytes(b'old fence')
            script = controller.remote_publish_pair_script().replace("'/etc/machine-id'", repr(str(machine)))
            now = datetime.datetime.now(datetime.timezone.utc)
            def envelope(expires):
                msg = {'issued_at_utc': (now - datetime.timedelta(seconds=2)).isoformat(), 'expires_at_utc': expires.isoformat()}
                return json.dumps({'message_b64': base64.b64encode(json.dumps(msg).encode()).decode(), 'signature_b64': 'AA=='}).encode()
            good1 = envelope(now + datetime.timedelta(seconds=20)); good2 = envelope(now + datetime.timedelta(seconds=15))
            hashes = [hashlib.sha256(x).hexdigest() for x in (good1, good2)]
            def body(a, b):
                return json.dumps({'source': base64.b64encode(a).decode(), 'fence': base64.b64encode(b).decode()}).encode()
            def call(raw, digests=hashes, host=None):
                return subprocess.run([sys.executable, '-c', script, str(first), str(second),
                    host or hashlib.sha256(machine.read_bytes()).hexdigest(), *digests], input=raw, capture_output=True)
            invalid = [b'', body(good1, good2)[:10], body(b'', good2), body(good1[:10], good2),
                       body(good1, good2[:10]), body(good1, good2 + b'x')]
            for value in invalid:
                with self.subTest(length=len(value)):
                    self.assertNotEqual(call(value).returncode, 0)
                    self.assertEqual(first.read_bytes(), b'old source'); self.assertEqual(second.read_bytes(), b'old fence')
                    self.assertFalse(list(root.glob('.tcl-watch-*')))
            expired = envelope(now - datetime.timedelta(seconds=1))
            self.assertNotEqual(call(body(good1, expired), [hashes[0], hashlib.sha256(expired).hexdigest()]).returncode, 0)
            self.assertNotEqual(call(body(good1, good2), host='0'*64).returncode, 0)
            self.assertEqual(first.read_bytes(), b'old source'); self.assertEqual(second.read_bytes(), b'old fence')
            result = call(body(good1, good2))
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(first.read_bytes(), good1); self.assertEqual(second.read_bytes(), good2)
            self.assertEqual(json.loads(result.stdout), {'source': hashes[0], 'fence': hashes[1]})

if __name__ == '__main__':
    unittest.main()
