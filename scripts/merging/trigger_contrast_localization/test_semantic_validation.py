"""Controller isolation checks in a temporary local tree; no network or GPU."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validation
import semantic_science


class SemanticValidationTest(unittest.TestCase):
    def test_identity_and_six_hour_clock_are_isolated(self):
        self.assertEqual(validation.RUN_ID, semantic_science.RUN_ID)
        self.assertEqual(validation.STATE_DIR.name, 'tcl-semantic')
        self.assertIsNone(validation.DEADLINE)
        self.assertEqual(semantic_science.MAX_COMPUTE_SECONDS, 21600)
        self.assertNotIn('tcl-20261102-overnight-v1', validation.REMOTE_PREPARE)

    def test_prepare_refuses_live_launcher_and_scientific_code_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            old = root / 'preparations/tcl-pilot24-v2-20261102/repository-recovery-v1'
            old.mkdir(parents=True)
            work = root / ('preparations/' + validation.RUN_ID)
            repo = work / 'repository'; repo.mkdir(parents=True)
            codefile = repo / 'scripts/merging/trigger_contrast_localization/semantic_science.py'
            codefile.parent.mkdir(parents=True)
            codefile.write_bytes(b'original-scientific-code')
            (work / 'spec.json').write_text('{}')
            data = b'changed-scientific-code'
            relative = str(codefile.relative_to(repo))
            payload = {'files': {relative: {'content': base64.b64encode(data).decode(),
                                             'sha256': hashlib.sha256(data).hexdigest()}}}
            script = validation.REMOTE_PREPARE.replace("pathlib.Path('/data2/zhangzibo/arxiv-tssa')", f'pathlib.Path({str(root)!r})')
            fd = os.open(work / 'launcher.lock', os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                running = subprocess.run([sys.executable, '-c', script], input=json.dumps(payload), text=True,
                                         capture_output=True, timeout=10)
                self.assertNotEqual(running.returncode, 0)
                self.assertIn('cannot update a running launcher', running.stderr)
            finally:
                os.close(fd)
            changed = subprocess.run([sys.executable, '-c', script], input=json.dumps(payload), text=True,
                                     capture_output=True, timeout=10)
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn('existing prepared spec has different code', changed.stderr)
            self.assertEqual(codefile.read_bytes(), b'original-scientific-code')

    def test_tick_reprepares_stale_execution_before_start(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(validation, 'STATE_DIR', Path(tmp)), \
                mock.patch.object(validation, 'fresh_snapshot', return_value={'account': {'username': 'test'}}), \
                mock.patch.object(validation, 'evaluate', return_value={'server': '104', 'host': 'iipl-104', 'uuid': 'GPU-test'}), \
                mock.patch.object(validation, 'execution_sha256', return_value={'runtime.py': 'new'}), \
                mock.patch.object(validation, 'prepare', return_value={'science_sha256': 'a' * 64, 'execution_sha256': {'runtime.py': 'new'}}) as prepare, \
                mock.patch.object(validation, 'start_or_resume', return_value={'status': 'simulated'}) as start:
            (Path(tmp) / 'prepared-104.json').write_text(json.dumps({'science_sha256': 'a' * 64}))
            self.assertEqual(validation.tick()['status'], 'simulated')
            prepare.assert_called_once_with('104')
            start.assert_called_once()

    def test_remote_launch_rejects_mismatched_execution_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            work = root / ('preparations/' + validation.RUN_ID)
            repo = work / 'repository'
            prefix = 'scripts/merging/trigger_contrast_localization/'
            hashes = {}
            for name in ('runtime.py', 'runtime_store.py', 'runtime_tcl.py'):
                path = repo / (prefix + name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
                hashes[prefix + name] = hashlib.sha256(path.read_bytes()).hexdigest()
            science = {'backend': 'cpu_simulation'}
            canonical = json.dumps({'run_id': validation.RUN_ID, 'science': science}, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            digest = hashlib.sha256(canonical.encode()).hexdigest()
            (work / 'spec.json').write_text(json.dumps({'run_id': validation.RUN_ID, 'science': science, 'execution': {}}))
            expected = dict(hashes);expected[prefix + 'runtime.py'] = '0' * 64
            script = validation.REMOTE_RUN.replace("pathlib.Path('/data2/zhangzibo/arxiv-tssa')", f'pathlib.Path({str(root)!r})')
            result = subprocess.run([sys.executable, '-c', script], input=json.dumps({'science_sha256': digest, 'execution_sha256': expected}),
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('execution code differs', result.stderr)

    def test_tick_rejects_changed_science_during_reprepare(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(validation, 'STATE_DIR', Path(tmp)), \
                mock.patch.object(validation, 'fresh_snapshot', return_value={'account': {'username': 'test'}}), \
                mock.patch.object(validation, 'evaluate', return_value={'server': '104', 'host': 'iipl-104', 'uuid': 'GPU-test'}), \
                mock.patch.object(validation, 'execution_sha256', return_value={'runtime.py': 'new'}), \
                mock.patch.object(validation, 'prepare', return_value={'science_sha256': 'b' * 64, 'execution_sha256': {'runtime.py': 'new'}}), \
                mock.patch.object(validation, 'start_or_resume') as start:
            (Path(tmp) / 'prepared-104.json').write_text(json.dumps({'science_sha256': 'a' * 64}))
            with self.assertRaises(validation.NotReady):
                validation.tick()
            start.assert_not_called()


if __name__ == '__main__': unittest.main()
