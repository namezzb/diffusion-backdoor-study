"""Historical recovery CLI is closed; its saved state remains readable."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name('pilot24_run.py')


class RecoveryChainTest(unittest.TestCase):
    def test_historical_recovery_is_closed_and_state_is_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / 'state.json'
            state.write_text(json.dumps({'stage': 'S0', 'terminal': {'reason': 'fixture_only'}}))
            before = hashlib.sha256(state.read_bytes()).hexdigest()
            result = subprocess.run([sys.executable, str(SCRIPT), 'serve', '--bundle', 'unused',
                                     '--config', 'unused', '--root', str(root), '--launch-map', 'unused',
                                     '--server', '104'], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('historical pilot24 execution is closed', result.stderr)
            status = subprocess.run([sys.executable, str(SCRIPT), 'status', '--root', str(root)],
                                    text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(status.stdout)['terminal']['reason'], 'fixture_only')
            self.assertEqual(hashlib.sha256(state.read_bytes()).hexdigest(), before)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['state.json'])


if __name__ == '__main__':
    unittest.main()
