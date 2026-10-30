import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'research/tasks/2026-10-29-trigger-contrast-localization'))
import shard127_watch_controller_safe_candidate as controller


class SafePublisherTests(unittest.TestCase):
    def test_prepublication_digest_rejects_empty_truncated_and_changed_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            machine = root / 'machine-id'
            machine.write_bytes(b'127-test-machine')
            dest = root / 'witness.json'
            prior = b'previous verified witness'
            dest.write_bytes(prior)
            good = b'{"message_b64":"YWJj","signature_b64":"ZGVm"}'
            digest = hashlib.sha256(good).hexdigest()
            script = controller.remote_install_script().replace("'/etc/machine-id'", repr(str(machine)))
            def publish(payload, expected=digest, host=None):
                return subprocess.run([sys.executable, '-c', script, str(dest),
                    host or hashlib.sha256(machine.read_bytes()).hexdigest(), expected],
                    input=payload, capture_output=True)
            for payload in (b'', good[:8], good + b'x', b'x' * 65537):
                with self.subTest(payload_length=len(payload)):
                    self.assertNotEqual(publish(payload).returncode, 0)
                    self.assertEqual(dest.read_bytes(), prior)
                    self.assertFalse(list(root.glob('.tcl-watch-*')))
            self.assertNotEqual(publish(good, expected='0' * 64).returncode, 0)
            self.assertNotEqual(publish(good, host='0' * 64).returncode, 0)
            self.assertEqual(dest.read_bytes(), prior)
            result = publish(good)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stdout.decode().strip(), digest)
            self.assertEqual(dest.read_bytes(), good)

    def test_digest_check_precedes_all_filesystem_mutation(self):
        script = controller.remote_install_script()
        self.assertLess(script.index('hexdigest()!=expected_payload'), script.index('tempfile.mkstemp'))
        self.assertLess(script.index('hexdigest()!=expected_payload'), script.index('os.replace'))

if __name__ == '__main__':
    unittest.main()
