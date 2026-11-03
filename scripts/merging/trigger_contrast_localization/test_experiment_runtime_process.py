"""CPU-simulated backend exercising the actual runner in separate processes.

The test substitutes only the GPU adapter and platform probe; it never uses CUDA.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest


DIRECTORY = Path(__file__).resolve().parent
PROGRAM = r'''
import io, json, os, sys, time, types
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image
import runtime
spec = json.loads(Path(sys.argv[1]).read_text())
log = Path(sys.argv[2])
mode = sys.argv[3]
def record(event):
    with log.open('a') as f:
        f.write(event + '\n'); f.flush(); os.fsync(f.fileno())
class CPUAdapter:
    def __init__(self, spec): self.spec = spec
    def prepare_cpu(self): return {'simulated': True}
    def units(self): return self.spec['science']['units']
    def start_cuda(self): record('start_simulated')
    def generate(self, unit, checkpoint):
        record('generate:' + str(unit['key'][-1]))
        if mode == 'stop_during_generation':
            status = {'run_id': spec['run_id'],
                      'science_sha256': runtime.digest({'run_id': spec['run_id'], 'science': spec['science']}),
                      'gpu_uuid': spec['execution']['gpu_uuid'], 'disabled': True,
                      'observed_at_utc': datetime.now(timezone.utc).isoformat()}
            Path(spec['execution']['resource_status_file']).write_text(json.dumps(status))
        checkpoint({'images': 1})
        if mode == 'block_generate': time.sleep(60)
        out = io.BytesIO(); Image.new('RGB', (512, 512)).save(out, format='PNG')
        return out.getvalue()
    def score(self, unit, image):
        record('score:' + str(unit['key'][-1]))
        if mode == 'block_score': time.sleep(60)
        return {'vit_class': 151, 'clip_score': 23.5}
    def stage_gate(self, stage, records):
        return {'stage': stage, 'passed': True, 'outcome': 'simulated'}
module = types.ModuleType('runtime_tcl'); module.TCLAdapter = CPUAdapter
sys.modules['runtime_tcl'] = module
def resource(spec, science_hash, before_gpu_probe=None):
    if mode == 'busy': raise ValueError('CPU simulation: resource busy')
    if before_gpu_probe: before_gpu_probe()
    if mode == 'gpu_probe_failed': raise ValueError('CPU simulation: GPU preflight failed')
    if mode == 'slow_gpu_probe': time.sleep(.2)
    if mode == 'slow_gpu_probe_failed':
        time.sleep(.2)
        raise ValueError('CPU simulation: GPU preflight failed after limit')
runtime.resource = resource
print(json.dumps(runtime.run(spec)), flush=True)
'''


class RuntimeProcessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.spec_path = self.base / 'spec.json'
        self.log = self.base / 'calls.log'
        self.spec = {'run_id': 'cpu-simulation', 'run_root': str(self.base / 'run'),
                     'science': {'units': [{'key': ['cpu-simulation', 'source', 'clean', 'dog', 'x', 'a']},
                                           {'key': ['cpu-simulation', 'source', 'clean', 'dog', 'x', 'b']}],
                                 'budget': {'max_attempts': 2, 'max_attempts_per_key': 1,
                                            'state_max_attempts': {'source': 2, 'merge': 0}}},
                     'execution': {'code_sha256': {'adapter': 'first'}}}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        self.spec_path.write_text(json.dumps(self.spec))

    def command(self, mode):
        return [sys.executable, '-c', PROGRAM, str(self.spec_path), str(self.log), mode]

    def invoke(self, mode):
        return subprocess.run(self.command(mode), cwd=DIRECTORY, capture_output=True,
                              text=True, timeout=15)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_required_observer_missing_pauses_before_cuda(self):
        self.spec['execution'].update(gpu_uuid='GPU-test', require_fresh_resource_status=True,
                                      resource_status_file=str(self.base / 'missing.json'))
        self.save()
        result = self.invoke('normal')
        self.assertEqual(json.loads(result.stdout)['status'], 'paused_resource', result.stderr)
        self.assertEqual(self.calls(), [])
        with sqlite3.connect(self.base / 'run' / 'run.sqlite') as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='t0'").fetchone()[0], 0)

    def test_failed_gpu_probe_records_one_t0_before_resume(self):
        failed = self.invoke('gpu_probe_failed')
        self.assertEqual(json.loads(failed.stdout)['status'], 'paused_resource', failed.stderr)
        with sqlite3.connect(self.base / 'run' / 'run.sqlite') as db:
            first = db.execute("SELECT detail FROM events WHERE kind='t0'").fetchall()
            self.assertEqual(len(first), 1)
            self.assertEqual(json.loads(first[0][0])['phase'], 'live_gpu_preflight')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 0)
        resumed = self.invoke('normal')
        self.assertEqual(json.loads(resumed.stdout)['status'], 'complete', resumed.stderr)
        with sqlite3.connect(self.base / 'run' / 'run.sqlite') as db:
            self.assertEqual(db.execute("SELECT detail FROM events WHERE kind='t0'").fetchall(), first)

    def test_gpu_probe_time_consumes_limit_before_cuda(self):
        self.spec['science']['max_compute_seconds'] = .1
        self.save()
        result = self.invoke('slow_gpu_probe')
        self.assertEqual(json.loads(result.stdout)['outcome'], 'inconclusive', result.stderr)
        self.assertEqual(self.calls(), [])
        with sqlite3.connect(self.base / 'run' / 'run.sqlite') as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='t0'").fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 0)

    def test_failed_probe_past_limit_becomes_terminal(self):
        self.spec['science']['max_compute_seconds'] = .1
        self.save()
        result = self.invoke('slow_gpu_probe_failed')
        self.assertEqual(json.loads(result.stdout)['status'], 'complete', result.stderr)
        self.assertEqual(json.loads(result.stdout)['outcome'], 'inconclusive')
        self.assertEqual(self.calls(), [])

    def test_absolute_deadline_prevents_cuda_start(self):
        self.spec['science']['compute_deadline_utc'] = '2000-01-01T00:00:00+00:00'
        self.save()
        result = self.invoke('normal')
        self.assertEqual(json.loads(result.stdout)['status'], 'complete', result.stderr)
        self.assertEqual(self.calls(), [])

    def test_busy_then_scoring_kill_resume_without_regeneration(self):
        busy = self.invoke('busy')
        self.assertEqual(json.loads(busy.stdout)['status'], 'paused_resource', busy.stderr)
        self.assertEqual(self.calls(), [])
        worker = subprocess.Popen(self.command('block_score'), cwd=DIRECTORY,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while 'score:a' not in self.calls() and time.monotonic() < deadline:
                if worker.poll() is not None:
                    self.fail('worker exited early: ' + worker.stderr.read())
                time.sleep(0.02)
            self.assertIn('score:a', self.calls())
            contender = self.invoke('normal')
            self.assertNotEqual(contender.returncode, 0)
            self.assertIsNone(worker.poll())
        finally:
            worker.kill()
            worker.communicate(timeout=10)
        self.spec['execution']['code_sha256'] = {'adapter': 'revised'}
        self.save()
        resumed = self.invoke('normal')
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)['status'], 'complete', resumed.stdout)
        self.assertEqual(self.calls().count('generate:a'), 1)
        self.assertEqual(self.calls().count('generate:b'), 1)
        before = list(self.calls())
        repeated = self.invoke('normal')
        self.assertEqual(json.loads(repeated.stdout)['status'], 'already_terminal', repeated.stderr)
        self.assertEqual(self.calls(), before)
        with sqlite3.connect(self.base / 'run' / 'run.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM units WHERE status='complete'").fetchone()[0], 2)
        self.spec['science']['budget']['max_attempts'] = 3
        self.save()
        self.assertNotEqual(self.invoke('normal').returncode, 0)

    def test_killed_generation_is_charged_before_bounded_retry(self):
        self.spec['science']['budget'] = {'max_attempts': 3, 'max_attempts_per_key': 2,
                                           'state_max_attempts': {'source': 3, 'merge': 0}}
        self.save()
        worker = subprocess.Popen(self.command('block_generate'), cwd=DIRECTORY,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while 'generate:a' not in self.calls() and time.monotonic() < deadline:
                if worker.poll() is not None:
                    self.fail('worker exited early: ' + worker.stderr.read())
                time.sleep(0.02)
            self.assertIn('generate:a', self.calls())
        finally:
            worker.kill()
            worker.communicate(timeout=10)
        resumed = self.invoke('normal')
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)['status'], 'complete', resumed.stdout)
        self.assertEqual(self.calls().count('generate:a'), 2)
        self.assertEqual(self.calls().count('generate:b'), 1)
        with sqlite3.connect(self.base / 'run' / 'run.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attempts WHERE status='failed'").fetchone()[0], 1)

    def test_platform_stop_pauses_and_retains_attempt(self):
        self.spec['science']['budget'] = {'max_attempts': 3, 'max_attempts_per_key': 2,
                                           'state_max_attempts': {'source': 3, 'merge': 0}}
        self.spec['execution'].update({'gpu_uuid': 'simulated-gpu',
                                       'resource_status_file': str(self.base / 'status.json')})
        self.save()
        stopped = self.invoke('stop_during_generation')
        self.assertEqual(json.loads(stopped.stdout)['status'], 'paused_resource', stopped.stdout + stopped.stderr)
        self.assertEqual(self.calls().count('generate:a'), 1)
        self.assertNotIn('generate:b', self.calls())
        (self.base / 'status.json').unlink()
        resumed = self.invoke('normal')
        self.assertEqual(json.loads(resumed.stdout)['status'], 'complete', resumed.stdout + resumed.stderr)
        with sqlite3.connect(self.base / 'run' / 'run.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='t0'").fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
