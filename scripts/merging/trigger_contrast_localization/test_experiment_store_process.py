"""Process-level checks for the new run store; all files are temporary."""
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


DIRECTORY = Path(__file__).resolve().parent
PROGRAM = r'''
import json, socket, sys, time
from runtime_store import Store
root, identity, action = sys.argv[1:]
if action == 'other_host': socket.gethostname = lambda: 'different-host-for-test'
key = ['run', 'source', 'one']
store = Store(root, json.loads(identity), [{'key': key}],
              {'max_attempts': 1, 'max_attempts_per_key': 1, 'state_max_attempts': {'source': 1}})
try:
    if action == 'hold':
        store.reserve(key)
        print('reserved', flush=True)
        time.sleep(60)
    elif action == 'retry':
        store.fail(key, 'previous process was killed')
        store.reserve(key)
    print(json.dumps(store.snapshot()), flush=True)
finally:
    store.close()
'''


class StoreProcessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / 'run'
        self.identity = json.dumps({'science': 'frozen'})

    def tearDown(self):
        self.temp.cleanup()

    def command(self, action, identity=None):
        return [sys.executable, '-c', PROGRAM, str(self.root),
                identity or self.identity, action]

    def test_kill_releases_lock_but_preserves_charge_and_identity(self):
        holder = subprocess.Popen(self.command('hold'), cwd=DIRECTORY,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'reserved')
            competitor = subprocess.run(self.command('snapshot'), cwd=DIRECTORY,
                                        capture_output=True, text=True, timeout=10)
            self.assertNotEqual(competitor.returncode, 0)
            self.assertIsNone(holder.poll(), 'competing writer must not kill the owner')
        finally:
            holder.kill()
            holder.communicate(timeout=10)
        changed = subprocess.run(self.command('snapshot', json.dumps({'science': 'changed'})),
                                 cwd=DIRECTORY, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(changed.returncode, 0)
        other_host = subprocess.run(self.command('other_host'), cwd=DIRECTORY,
                                    capture_output=True, text=True, timeout=10)
        self.assertNotEqual(other_host.returncode, 0)
        resumed = subprocess.run(self.command('retry'), cwd=DIRECTORY,
                                 capture_output=True, text=True, timeout=10)
        self.assertNotEqual(resumed.returncode, 0, 'a killed attempt remains charged')
        from runtime_store import read_markdown
        attempts = read_markdown(self.root / 'run.md')['attempts']
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]['status'], 'failed')

    def test_state_retry_cap_does_not_consume_other_units_first_attempts(self):
        from runtime_store import BudgetExhausted, Store
        keys = [['run', 'source', str(i)] for i in range(3)]
        budget = {'max_attempts': 5, 'max_attempts_per_key': 2,
                  'state_max_attempts': {'source': 4, 'merge': 1}}
        store = Store(self.root, {'science': 'retry-cap'}, [{'key': key} for key in keys], budget)
        try:
            store.reserve(keys[0]); store.fail(keys[0], 'first')
            store.reserve(keys[0]); store.fail(keys[0], 'retry')
            store.reserve(keys[1]); store.fail(keys[1], 'first')
            with self.assertRaises(BudgetExhausted):
                store.reserve(keys[1])
            store.reserve(keys[2])
            self.assertEqual(store.snapshot()['attempts'], 4)
        finally:
            store.close()

    def test_empty_lock_only_can_recover_but_unknown_file_is_rejected(self):
        self.root.mkdir()
        (self.root / '.writer.lock').touch()
        accepted = subprocess.run(self.command('snapshot'), cwd=DIRECTORY, capture_output=True, text=True, timeout=10)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        other = self.root.parent / 'other'
        other.mkdir()
        (other / '.writer.lock').touch()
        (other / 'unrelated').write_text('preserve me')
        command = self.command('snapshot'); command[3] = str(other)
        rejected = subprocess.run(command, cwd=DIRECTORY, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual((other / 'unrelated').read_text(), 'preserve me')
        self.assertFalse((other / 'run.md').exists())

    def test_copied_run_root_cannot_open_as_same_writer(self):
        initialized = subprocess.run(self.command('snapshot'), cwd=DIRECTORY, capture_output=True, text=True, timeout=10)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        other = self.root.parent / 'copied'
        shutil.copytree(self.root, other)
        command = self.command('snapshot'); command[3] = str(other)
        copied = subprocess.run(command, cwd=DIRECTORY, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(copied.returncode, 0)


if __name__ == '__main__':
    unittest.main()
