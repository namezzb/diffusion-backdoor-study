"""CPU-only fake-device tests; no CUDA device or reservation is used."""
import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import gpu_hold_worker as worker

GPU = 'GPU-12345678-1234-1234-1234-123456789abc'
GPU2 = 'GPU-12345678-1234-1234-1234-123456789abd'


class FakeClock:
    def __init__(self): self.value = 1000.0
    def time(self): return self.value
    def monotonic(self): return self.value
    def sleep(self, seconds): self.value += seconds


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.lease_path = self.root / 'lease.json'
        self.clock = FakeClock()
        self.lease = {'schema': 'gpu-hold-lease-v1', 'worker_id': 'hold-1', 'gpu_uuid': GPU,
                      'host': socket.gethostname(), 'owner_uid': os.geteuid(), 'lease_id': 'lease-1',
                      'controller_id': 'authorized-controller', 'semantic_run_id': 'tcl-20261103-semantic-v1',
                      'semantic_science_sha256': 'a' * 64, 'semantic_terminal': True,
                      'semantic_all_stages_completed': True, 'scientific_writer_exited': True,
                      'authorized': True, 'platform_permission_verified': True, 'disabled': False,
                      'stop_required': False, 'active_hold_uuids': [GPU], 'observed_at': 1000.0, 'expires_at': 1030.0}
        self.write_lease()
        self.args = SimpleNamespace(uuid=GPU, worker_id='hold-1', state_dir=str(self.root / 'state'),
                                    lease_file=str(self.lease_path), duration_seconds=3, memory_fraction=.6,
                                    compute_duty=0, sample_seconds=1, until_stopped=False,
                                    target_utilization_percent=0, lease_id='lease-1', controller_id='authorized-controller',
                                    science_sha256='a' * 64)

    def tearDown(self): self.temp.cleanup()

    def write_lease(self):
        self.lease_path.write_text(json.dumps(self.lease))
        self.lease_path.chmod(0o600)

    def execute(self, factory, sample=lambda *_: {'device_gpu_utilization_percent': None}):
        with contextlib.redirect_stdout(io.StringIO()):
            return worker.run(self.args, device_factory=factory, clock=self.clock, sample=sample)

    def test_invalid_or_expired_lease_never_initializes_device(self):
        for changes in ({'expires_at': 999.0}, {'host': 'other'}, {'authorized': False},
                        {'semantic_all_stages_completed': False}, {'stop_required': True},
                        {'gpu_uuid': GPU2}, {'active_hold_uuids': [GPU, GPU2, GPU2]},
                        {'semantic_science_sha256': 'b' * 64}, {'controller_id': 'forged'},
                        {'expires_at': float('nan')}, {'owner_uid': -1}):
            with self.subTest(changes=changes):
                lease = dict(self.lease, **changes)
                with self.assertRaises(worker.StopWork):
                    worker.check_lease(lease, uuid=GPU, worker_id='hold-1', lease_id='lease-1',
                                       controller_id='authorized-controller', science_sha256='a' * 64, now=1000,
                                       hostname=socket.gethostname(), uid=os.geteuid())
        self.lease['disabled'] = True
        self.write_lease()
        factory = mock.Mock(side_effect=AssertionError('CUDA initialized'))
        self.assertEqual(self.execute(factory), 1)
        factory.assert_not_called()

    def test_valid_lease_duration_logs_and_releases(self):
        device = mock.Mock()
        device.allocate.side_effect = lambda fraction, guard: guard()
        values = {'device_gpu_utilization_percent': 38.0, 'device_memory_used_mib': 12000.0,
                  'device_memory_total_mib': 24000.0, 'worker_pid_memory_mib': 11000.0}
        self.assertEqual(self.execute(lambda uuid, guard: device, lambda *_: values), 0)
        device.close.assert_called_once()
        lines = [json.loads(x) for x in (self.root / 'state' / (GPU + '.jsonl')).read_text().splitlines()]
        samples = [x for x in lines if x['event'] == 'sample']
        self.assertGreaterEqual(len(samples), 1)
        self.assertEqual(samples[0]['device_gpu_utilization_percent'], 38.0)
        self.assertEqual(samples[0]['worker_pid_memory_mib'], 11000.0)
        self.assertEqual(json.loads((self.root / 'state' / (GPU + '.pid.json')).read_text())['status'], 'stopped')

    def test_lease_age_span_and_original_expiry_boundaries(self):
        def check(lease, now):
            return worker.check_lease(lease, uuid=GPU, worker_id='hold-1', lease_id='lease-1',
                controller_id='authorized-controller', science_sha256='a' * 64, now=now,
                hostname=socket.gethostname(), uid=os.geteuid())
        lease = dict(self.lease, expires_at=1090.0)
        self.assertEqual(check(lease, 1089.0), 'lease-1')
        with self.assertRaises(worker.StopWork): check(lease, 1090.0)
        with self.assertRaises(worker.StopWork): check(dict(lease, expires_at=1090.01), 1000.0)
        short_lease = dict(self.lease, expires_at=1015.0)
        self.assertEqual(check(short_lease, 1014.0), 'lease-1')
        with self.assertRaises(worker.StopWork): check(short_lease, 1015.0)

    def test_revoked_lease_and_signal_release_device(self):
        for mode in ('revoked', 'signal'):
            with self.subTest(mode=mode):
                self.args.lease_id = 'lease-' + mode
                self.lease.update(lease_id=self.args.lease_id, disabled=False, observed_at=self.clock.time(), expires_at=self.clock.time()+30)
                self.write_lease()
                device = mock.Mock()
                def allocate(_fraction, guard):
                    if mode == 'revoked':
                        self.lease['disabled'] = True
                        self.write_lease()
                    else:
                        os.kill(os.getpid(), signal.SIGTERM)
                    guard()
                device.allocate.side_effect = allocate
                self.assertEqual(self.execute(lambda uuid, guard: device), 0)
                device.close.assert_called_once()

    def test_lease_identity_cannot_change_mid_run(self):
        device = mock.Mock()
        def allocate(_fraction, guard):
            self.lease['lease_id'] = 'different'
            self.write_lease()
            guard()
        device.allocate.side_effect = allocate
        self.assertEqual(self.execute(lambda uuid, guard: device), 0)
        device.close.assert_called_once()

    def test_insecure_file_and_symlink_rejected(self):
        self.lease_path.chmod(0o644)
        with self.assertRaises(worker.StopWork): worker.safe_read_json(self.lease_path)
        self.lease_path.unlink()
        self.lease_path.symlink_to('/dev/null')
        with self.assertRaises(worker.StopWork): worker.safe_read_json(self.lease_path)

    def test_same_card_lock_prevents_second_worker(self):
        state = self.root / 'state'
        state.mkdir(mode=0o700)
        fd = os.open(state / (GPU + '.lock'), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(worker.StopWork): self.execute(mock.Mock())
        finally:
            os.close(fd)

    def test_stopped_worker_cannot_restart_with_old_lease(self):
        device = mock.Mock()
        device.allocate.side_effect = lambda _fraction, guard: guard()
        self.assertEqual(self.execute(lambda uuid, guard: device), 0)
        factory = mock.Mock(side_effect=AssertionError('reused lease initialized CUDA'))
        self.assertEqual(self.execute(factory), 1)
        factory.assert_not_called()
        self.args.lease_id = 'new-lease'
        self.lease.update(lease_id='new-lease', observed_at=self.clock.time(), expires_at=self.clock.time()+30)
        self.write_lease()
        again = mock.Mock()
        again.allocate.side_effect = lambda _fraction, guard: guard()
        self.assertEqual(self.execute(lambda uuid, guard: again), 0)
        again.close.assert_called_once()

    def test_cli_requires_explicit_parameters(self):
        result = subprocess.run([sys.executable, str(Path(worker.__file__)), '--uuid', GPU],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--duration-seconds', result.stderr)

    def test_cli_missing_lease_does_not_load_cuda(self):
        result = subprocess.run([sys.executable, str(Path(worker.__file__)), '--uuid', GPU, '--worker-id', 'hold-1',
                                 '--lease-id', 'lease-1', '--controller-id', 'authorized-controller', '--science-sha256', 'a' * 64,
                                 '--state-dir', str(self.root / 'state'), '--lease-file', str(self.root / 'missing'),
                                 '--duration-seconds', '3', '--memory-fraction', '.6', '--compute-duty', '.6',
                                 '--target-utilization-percent', '60', '--sample-seconds', '1'], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('starting', result.stdout)

    def test_until_stopped_exits_when_lease_expires(self):
        self.args.until_stopped = True
        self.args.duration_seconds = None
        self.lease['expires_at'] = 1002.0
        self.write_lease()
        device = mock.Mock()
        device.allocate.side_effect = lambda fraction, guard: guard()
        self.assertEqual(self.execute(lambda uuid, guard: device), 0)
        self.assertGreaterEqual(self.clock.time(), 1002)
        device.close.assert_called_once()

    def test_until_stopped_can_continue_with_renewals_then_signal(self):
        self.args.until_stopped = True
        self.args.duration_seconds = None
        outer = self
        class RenewClock(FakeClock):
            def sleep(self, seconds):
                super().sleep(seconds)
                outer.lease['observed_at'] = self.value
                outer.lease['expires_at'] = self.value + 20
                outer.write_lease()
                if self.value >= 1035:
                    os.kill(os.getpid(), signal.SIGTERM)
        self.clock = RenewClock()
        device = mock.Mock()
        device.allocate.side_effect = lambda fraction, guard: guard()
        self.assertEqual(self.execute(lambda uuid, guard: device), 0)
        self.assertGreaterEqual(self.clock.time(), 1035)
        device.close.assert_called_once()

    def test_target_feedback_uses_real_sample_and_is_not_a_claim(self):
        self.args.target_utilization_percent = 61
        device = mock.Mock()
        device.allocate.side_effect = lambda fraction, guard: guard()
        device.compute_once.side_effect = lambda: self.clock.sleep(.1)
        self.assertEqual(self.execute(lambda uuid, guard: device, lambda *_: {'device_gpu_utilization_percent': 20}), 0)
        entries = [json.loads(x) for x in (self.root / 'state' / (GPU + '.jsonl')).read_text().splitlines()]
        sample = next(x for x in entries if x['event'] == 'sample')
        self.assertEqual(sample['device_gpu_utilization_percent'], 20)
        self.assertGreater(sample['requested_compute_duty'], 0)


if __name__ == '__main__':
    unittest.main()
