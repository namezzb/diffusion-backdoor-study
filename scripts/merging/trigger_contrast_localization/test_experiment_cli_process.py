"""Actual CLI in an isolated copy, with explicitly simulated CPU dependencies."""
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parent
ADAPTER = '''
import io, os, time
from pathlib import Path
from PIL import Image
class TCLAdapter:
    def __init__(self, spec): self.spec = spec
    def prepare_cpu(self): return {'backend': 'cpu_simulation'}
    def audit_cpu(self): return self.prepare_cpu()
    def units(self): return self.spec['science']['units']
    def start_cuda(self): pass  # CPU simulation only
    def record(self, value):
        with Path(os.environ['TEST_LOG']).open('a') as f:
            f.write(value + '\\n'); f.flush(); os.fsync(f.fileno())
    def generate(self, unit, checkpoint):
        self.record('generate'); checkpoint({'images': 1})
        if Path(os.environ['TEST_FAIL']).exists(): raise RuntimeError('simulated generation failure')
        output = io.BytesIO(); Image.new('RGB', (512, 512)).save(output, format='PNG')
        return output.getvalue()
    def score(self, unit, image):
        self.record('score')
        if Path(os.environ['TEST_BLOCK']).exists(): time.sleep(60)
        return {'vit_class': 151, 'clip_score': 23.5}
    def stage_gate(self, stage, records):
        return {'stage': stage, 'passed': True, 'outcome': 'cpu_simulation'}
def build_spec(request):
    return {'run_id': request['run_id'], 'simulated_prepare': True}
'''
PROVENANCE = '''
def _host_identity(): return 'cpu-simulation-host'
def _live_gpu_xml(): return b'<nvidia_smi_log><driver_version>simulated-driver</driver_version><gpu><uuid>GPU-12345678-1234-1234-1234-123456789abc</uuid><compute_mode>Default</compute_mode></gpu></nvidia_smi_log>'
def _gpu(xml, uuid, pids): pass  # no GPU access
'''


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


class RuntimeCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.script_dir = self.root / 'scripts' / 'merging' / 'trigger_contrast_localization'
        self.script_dir.mkdir(parents=True)
        for name in ('runtime.py', 'runtime_store.py', 'runtime_assets.py'):
            shutil.copyfile(SOURCE / name, self.script_dir / name)
        import runtime_tcl
        ownership = '\nHISTORICAL_RUNS = ' + repr(runtime_tcl.HISTORICAL_RUNS) + '\n' + inspect.getsource(runtime_tcl.require_current_run)
        (self.script_dir / 'runtime_tcl.py').write_text(ADAPTER + ownership)
        (self.script_dir / 'pilot24_provenance.py').write_text(PROVENANCE)
        self.spec_path, self.log, self.block = (self.root / 'spec.json', self.root / 'calls', self.root / 'block')
        self.run_root = self.root / 'run'
        self.uuid = 'GPU-12345678-1234-1234-1234-123456789abc'
        self.env = dict(os.environ, CUDA_VISIBLE_DEVICES=self.uuid, GPU_UUID=self.uuid,
                        TEST_LOG=str(self.log), TEST_BLOCK=str(self.block), TEST_FAIL=str(self.root / 'fail'))
        self.spec = {'schema_version': 1, 'run_id': 'cpu-cli-simulation', 'run_root': str(self.run_root),
                     'science': {'backend': 'tcl_sd', 'inputs': {},
                                 'units': [{'key': ['cpu-cli-simulation', 'source', 'clean', 'dog', 'x', '1'],
                                            'input_sha': 'a' * 64, 'mask_sha': 'b' * 64}],
                                 'budget': {'max_attempts': 2, 'max_attempts_per_key': 1,
                                            'state_max_attempts': {'source': 1, 'merge': 1}}},
                     'execution': {'gpu_uuid': self.uuid}}

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        raw = self.root / 'capture'; raw.write_text('simulated only')
        current = datetime.now(timezone.utc)
        evidence = {'observed_at_utc': current.isoformat(), 'expires_at_utc': (current + timedelta(minutes=4)).isoformat(),
                    'run_id': self.spec['run_id'], 'science_sha256': digest({'run_id': self.spec['run_id'], 'science': self.spec['science']}),
                    'gpu_uuid': self.uuid, 'host': 'cpu-simulation-host', 'source': 'https://gpu.orz2333.fun/',
                    'disabled': False, 'sampling_valid': True, 'allocation_conflict': False,
                    'effective_gpu_cap': 1, 'occupied_including_this_gpu': 1,
                    'raw_capture': {'path': str(raw), 'sha256': hashlib.sha256(raw.read_bytes()).hexdigest()}}
        evidence_path = self.root / 'evidence.json'; evidence_path.write_text(json.dumps(evidence))
        self.spec['execution']['resource_evidence'] = {'path': str(evidence_path), 'sha256': hashlib.sha256(evidence_path.read_bytes()).hexdigest()}
        self.spec_path.write_text(json.dumps(self.spec))

    def command(self, action):
        return [sys.executable, str(self.script_dir / 'runtime.py'), action, '--spec', str(self.spec_path)]

    def invoke(self, action):
        return subprocess.run(self.command(action), env=self.env, capture_output=True, text=True, timeout=15)

    def kill_at_score(self):
        self.block.touch()
        worker = subprocess.Popen(self.command('run'), env=self.env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.log.exists() and 'score' in self.log.read_text().splitlines(): return
                if worker.poll() is not None: self.fail('worker exited early: ' + worker.communicate()[1])
                time.sleep(0.02)
            self.fail('score was not reached')
        finally:
            worker.kill(); worker.communicate(timeout=10)
            self.block.unlink()

    def test_cli_check_kill_resume_and_status(self):
        self.save()
        checked = self.invoke('check')
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)['status'], 'checked')
        self.assertFalse(self.run_root.exists(), 'check must not create T0 or a run')
        self.kill_at_score()
        with (self.script_dir / 'runtime.py').open('a') as source:
            source.write('\n# test-only repair in isolated copy\n')
        resumed = self.invoke('run')
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)['status'], 'complete', resumed.stdout)
        self.assertEqual(self.log.read_text().splitlines().count('generate'), 1)
        status = self.invoke('status')
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)['statuses'], {'complete': 1})
        self.assertEqual(json.loads(status.stdout)['attempts'], 1)
        with sqlite3.connect(self.run_root / 'run.sqlite') as db:
            sessions = [json.loads(row[0]) for row in db.execute("SELECT detail FROM events WHERE kind='session' ORDER BY id")]
            observation = json.loads(db.execute("SELECT detail FROM events WHERE kind='resource_checked' LIMIT 1").fetchone()[0])['evidence']['live_gpu']
        key = 'scripts/merging/trigger_contrast_localization/runtime.py'
        self.assertNotEqual(sessions[0]['code_sha256'][key], sessions[1]['code_sha256'][key])
        simulated_xml = b'<nvidia_smi_log><driver_version>simulated-driver</driver_version><gpu><uuid>GPU-12345678-1234-1234-1234-123456789abc</uuid><compute_mode>Default</compute_mode></gpu></nvidia_smi_log>'
        self.assertEqual(observation['xml_sha256'], hashlib.sha256(simulated_xml).hexdigest())
        self.assertEqual((observation['driver_version'], observation['compute_mode'], observation['gpu_uuid']),
                         ('simulated-driver', 'Default', self.uuid))

    def test_actual_process_rejects_historical_identity_before_creating_run(self):
        self.spec['run_id'] = 'tcl-20261102-overnight-v1'
        self.save()
        result = self.invoke('run')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('historical run identity or directory', result.stderr)
        self.assertFalse(self.run_root.exists())

    def test_cli_prepare_dispatch_and_exclusive_write(self):
        request = self.root / 'request.json'; request.write_text(json.dumps({'run_id': 'prepare-simulation'}))
        command = self.command('prepare') + ['--request', str(request)]
        prepared = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertEqual(json.loads(self.spec_path.read_text()), {'run_id': 'prepare-simulation', 'simulated_prepare': True})
        repeated = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertFalse(self.run_root.exists())

    def test_expired_platform_evidence_does_not_start_t0(self):
        self.save()
        path = Path(self.spec['execution']['resource_evidence']['path'])
        evidence = json.loads(path.read_text())
        evidence['observed_at_utc'] = '2000-01-01T00:00:00+00:00'
        evidence['expires_at_utc'] = '2000-01-01T00:01:00+00:00'
        path.write_text(json.dumps(evidence))
        self.spec['execution']['resource_evidence']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.spec_path.write_text(json.dumps(self.spec))
        result = self.invoke('run')
        self.assertEqual(json.loads(result.stdout)['status'], 'paused_resource', result.stderr)
        with sqlite3.connect(self.run_root / 'run.sqlite') as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='t0'").fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 0)

    def test_real_probe_sees_persisted_t0_even_if_probe_fails(self):
        self.save()
        simulated = self.script_dir / 'pilot24_provenance.py'
        simulated.write_text(PROVENANCE + '''
def _live_gpu_xml():
    import json, os, sqlite3
    with sqlite3.connect(os.environ['TEST_DB']) as db:
        row = db.execute("SELECT detail FROM events WHERE kind='t0'").fetchone()
        assert row is not None and json.loads(row[0])['phase'] == 'live_gpu_preflight'
    raise ValueError('simulated live GPU probe failure')
''')
        self.env['TEST_DB'] = str(self.run_root / 'run.sqlite')
        result = self.invoke('run')
        self.assertEqual(json.loads(result.stdout)['status'], 'paused_resource', result.stderr)
        with sqlite3.connect(self.run_root / 'run.sqlite') as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='t0'").fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 0)

    def test_exhausted_budget_is_terminal_and_does_not_regenerate(self):
        self.save()
        fail = self.root / 'fail'; fail.touch()
        first = self.invoke('run')
        self.assertEqual(json.loads(first.stdout)['status'], 'paused_error', first.stdout + first.stderr)
        fail.unlink()
        resumed = self.invoke('run')
        self.assertEqual(json.loads(resumed.stdout)['outcome'], 'inconclusive', resumed.stdout + resumed.stderr)
        self.assertEqual(json.loads(self.invoke('run').stdout)['status'], 'already_terminal')
        self.assertEqual(self.log.read_text().splitlines().count('generate'), 1)
        with sqlite3.connect(self.run_root / 'run.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 1)

    def test_cli_deadline_survives_kill_and_resume(self):
        self.spec['science']['max_compute_seconds'] = 0.5
        self.save()
        self.kill_at_score()
        with sqlite3.connect(self.run_root / 'run.sqlite') as db:
            t0 = db.execute("SELECT detail FROM events WHERE kind='t0'").fetchall()
        time.sleep(0.7)
        resumed = self.invoke('run')
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        result = json.loads(resumed.stdout)
        self.assertEqual(result['outcome'], 'inconclusive', resumed.stdout)
        with sqlite3.connect(self.run_root / 'run.sqlite') as db:
            self.assertEqual(db.execute("SELECT detail FROM events WHERE kind='t0'").fetchall(), t0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 1)
        self.assertEqual(self.log.read_text().splitlines().count('generate'), 1)


if __name__ == '__main__':
    unittest.main()
