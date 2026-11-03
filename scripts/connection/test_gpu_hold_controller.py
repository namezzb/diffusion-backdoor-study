"""CPU-only controller checks. No SSH, API, CUDA or scientific workload."""
import copy
from contextlib import closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import gpu_hold_controller as c
import gpu_hold_worker as worker

U1 = 'GPU-12345678-1234-1234-1234-123456789abc'
U2 = 'GPU-22345678-1234-1234-1234-123456789abc'


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state = self.root / 'private'
        self.snapshot = {'source': 'https://gpu.orz2333.fun', 'fetched_at': time.time(), 'cache_state': 'fresh',
            '_hold_policy_complete': True,
            'account': {'username': 'test', 'registered': True, 'active_ban': None, 'usage': {'count': 0, 'limit': 4}},
            'policy': {'rules': {'gpu_management_enabled': False}, 'maintenance': [], 'gpu_requests': [], 'rectifications': [], 'cases': []},
            'hosts': [{'id': 'iipl-104', 'label': '104', 'online': True, 'processes_complete': True,
                       'process_state_complete': True, 'process_sample_age_seconds': 1,
                       'gpus': [{'uuid': u, 'sample_age_seconds': 1, 'status': 'free', 'own': False} for u in (U1, U2)]}]}
        self.report = {'status': 'terminal', 'run_id': c.RUN, 'science_sha256': 'a' * 64,
                       'completed_images': 1024, 'stages_completed': ['S0', 'S1', 'M0', 'M1']}
        report_path = self.root / 'report.json'; report_path.write_text(json.dumps(self.report))
        self.config = {'schema': 'gpu-hold-controller-v1', 'hold_id': 'cpu-test',
            'source': {'server': '104', 'run_id': c.RUN, 'science_sha256': 'a' * 64},
            'authorization': {'enabled': True, 'until_user_stop': True, 'platform_allows_hold': True,
                'purpose': 'transparent_gpu_retention', 'username': 'test', 'reviewed_policy_sha256': c.policy_hash(self.snapshot),
                'compute_target_percent': 65, 'memory_target_percent': 65, 'max_cards': 2},
            'completion_report': {'path': str(report_path), 'sha256': hashlib.sha256(report_path.read_bytes()).hexdigest()}}
        self.calls = []
        self.machine = {'hostname': 'iipl-104', 'uid': os.getuid(), 'machine_id_sha256': 'b' * 64}

    def fake_remote(self, config, action, **fields):
        self.calls.append((action, fields))
        if action == 'inspect':
            return {'machine': self.machine, 'preferred_uuid': U2, 'complete': 1024}
        return {'status': action, 'workers': []}

    def test_explicit_authorization_and_same_run_report_required(self):
        c.validate_config(self.config)
        for field, value in [('enabled', False), ('max_cards', 3), ('until_user_stop', False), ('compute_target_percent', 60)]:
            altered = copy.deepcopy(self.config); altered['authorization'][field] = value
            with self.subTest(field=field), self.assertRaises(c.NotReady): c.validate_config(altered)
        altered = copy.deepcopy(self.config); altered['source']['science_sha256'] = 'c' * 64
        with self.assertRaises(c.NotReady): c.validate_config(altered)
        no_report = copy.deepcopy(self.config); del no_report['completion_report']
        c.validate_config(no_report, require_report=False)
        with self.assertRaises(c.NotReady): c.validate_config(no_report)

    def test_missing_policy_stale_ban_allocations_and_quota_fail_closed(self):
        changes = [lambda s: s.update(_hold_policy_complete=False),
                   lambda s: s.update(fetched_at=time.time() - 20),
                   lambda s: s['account'].update(active_ban={'id': 1}),
                   lambda s: s['policy']['gpu_requests'].append({'status': 'pending'}),
                   lambda s: s['policy'].update(cases=None),
                   lambda s: s['account']['usage'].update(count=5)]
        for change in changes:
            value = copy.deepcopy(self.snapshot); change(value)
            with self.subTest(change=change), self.assertRaises(c.NotReady): c.platform(value, self.config)
        self.snapshot['policy']['rules']['new_rule'] = True
        with self.assertRaises(c.NotReady): c.platform(self.snapshot, self.config)

    def test_running_co_user_not_stop_and_pending_workers_consume_quota(self):
        self.snapshot['hosts'][0]['gpus'][0].update(status='shared', own=True)
        self.snapshot['account']['usage'].update(count=1, limit=2)
        _, available = c.platform(self.snapshot, self.config, [U1, U2])
        self.assertEqual(available, 0)
        self.snapshot['hosts'][0]['gpus'][0]['status'] = 'disabled'
        with self.assertRaises(c.NotReady): c.platform(self.snapshot, self.config, [U1])

    def test_watch_preferred_order_worker_lease_contract_and_two_card_cap(self):
        with mock.patch.object(c, 'remote', side_effect=self.fake_remote), mock.patch.object(c, 'fresh_snapshot', return_value=self.snapshot):
            c.watch(self.config, self.state, once=True)
        start = next(fields for action, fields in self.calls if action == 'start')
        self.assertEqual([l['gpu_uuid'] for l in start['leases']], [U2, U1])
        self.assertEqual(len(start['leases']), 2)
        for lease in start['leases']:
            self.assertEqual(worker.check_lease(lease, uuid=lease['gpu_uuid'], worker_id=lease['worker_id'],
                lease_id=lease['lease_id'], controller_id=lease['controller_id'], science_sha256='a' * 64,
                now=time.time(), hostname=self.machine['hostname'], uid=os.getuid()), lease['lease_id'])

    def test_new_free_second_card_is_added_without_replacing_first(self):
        first = copy.deepcopy(self.snapshot); first['hosts'][0]['gpus'][0]['status'] = 'others'
        with mock.patch.object(c, 'remote', side_effect=self.fake_remote), \
                mock.patch.object(c, 'fresh_snapshot', side_effect=[first, self.snapshot, self.snapshot]):
            c.watch(self.config, self.state, once=True)
        self.assertEqual([a for a, _ in self.calls], ['inspect', 'start', 'add', 'renew'])
        start = self.calls[1][1]['leases']; added = self.calls[2][1]['leases']
        self.assertEqual(len(start), 1); self.assertEqual(len(added), 2)
        self.assertEqual(start[0]['lease_id'], added[0]['lease_id'])

    def test_renewal_failure_revokes_and_records_visible_failure(self):
        def remote(config, action, **fields):
            if action == 'renew': raise c.NotReady('simulated network failure')
            return self.fake_remote(config, action, **fields)
        with mock.patch.object(c, 'remote', side_effect=remote), mock.patch.object(c, 'fresh_snapshot', return_value=self.snapshot):
            with self.assertRaises(c.NotReady): c.watch(self.config, self.state, once=True)
        self.assertEqual(self.calls[-1][0], 'stop')
        manifest = c.read_private(self.state / 'manifest.json')
        self.assertEqual(manifest['status'], 'stopped_or_lease_expiring')

    def test_stop_during_inspect_waits_and_prevents_late_start(self):
        entered, release = threading.Event(), threading.Event()
        failures, results = [], []
        def remote(config, action, **fields):
            if action == 'inspect': entered.set(); release.wait(3)
            return self.fake_remote(config, action, **fields)
        def run_watch():
            try: c.watch(self.config, self.state, once=True)
            except c.NotReady as exc: failures.append(str(exc))
        with mock.patch.object(c, 'remote', side_effect=remote), mock.patch.object(c, 'fresh_snapshot', return_value=self.snapshot):
            thread = threading.Thread(target=run_watch); thread.start(); self.assertTrue(entered.wait(2))
            stopper = threading.Thread(target=lambda: results.append(c.stop(self.config, self.state))); stopper.start()
            deadline = time.time() + 2
            while not (self.state / 'STOP').exists() and time.time() < deadline: time.sleep(.01)
            self.assertTrue(stopper.is_alive(), 'stop must wait for in-flight owner')
            release.set(); thread.join(3); stopper.join(3)
        self.assertTrue(failures); self.assertEqual(results[0]['status'], 'stopped_before_start')
        self.assertNotIn('start', [a for a, _ in self.calls])

    def test_waiter_refuses_partial_terminal_without_report_or_gpu(self):
        config = copy.deepcopy(self.config); del config['completion_report']
        with mock.patch.object(c, 'remote', return_value={'status': 'partial_terminal'}) as remote, \
                mock.patch.object(c, 'watch') as watch:
            with self.assertRaises(c.NotReady): c.await_completion(config, self.state)
        watch.assert_not_called(); self.assertEqual(remote.call_args.args[1], 'poll')

    def test_waiter_builds_report_and_hands_same_owner_lock_to_watch(self):
        config = copy.deepcopy(self.config); del config['completion_report']
        def take_over(activated, state, _lock_fd):
            c.validate_config(activated)
            second = os.open(state / 'controller.lock', os.O_RDWR)
            try:
                with self.assertRaises(BlockingIOError): fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally: os.close(second); os.close(_lock_fd)
            return {'status': 'simulated_handoff'}
        with mock.patch.object(c, 'remote', side_effect=[{'status': 'ready_for_report'}, self.report]), \
                mock.patch.object(c, 'watch', side_effect=take_over):
            self.assertEqual(c.await_completion(config, self.state)['status'], 'simulated_handoff')
        self.assertTrue((self.state / 'completion-report.json').is_file())

    def test_raw_missing_maintenance_is_not_normalized_to_permission(self):
        import labgpu
        cache = self.root / 'cache'; cache.mkdir(mode=0o700)
        payload = copy.deepcopy(self.snapshot['policy']); del payload['maintenance']
        c.write_private(cache / 'status.json', {'base_url': labgpu.BASE, 'fetched_at': self.snapshot['fetched_at'], 'payload': payload})
        with mock.patch.object(labgpu, 'CONFIG', cache), mock.patch.object(c.subprocess, 'run',
                return_value=subprocess.CompletedProcess([], 0, json.dumps(self.snapshot), '')):
            with self.assertRaises(c.NotReady): c.fresh_snapshot()

    def test_effective_lease_uses_worker_age_and_timeout_retry_never_renews_stale_data(self):
        self.assertEqual(c.MAX_LEASE_AGE, worker.MAX_LEASE_AGE)
        self.assertEqual(c.effective_expiry([{'observed_at': 100, 'expires_at': 200}]), 190)
        self.assertEqual(c.effective_expiry([{'observed_at': 100, 'expires_at': 110}]), 110)
        c.private_dir(self.state)
        with mock.patch.object(c.time, 'time', return_value=100), mock.patch.object(c, 'fresh_snapshot',
                side_effect=[subprocess.TimeoutExpired('api', 35), self.snapshot]) as fresh:
            self.assertIs(c.refresh_with_retry(self.state, {'lease_expires_at': 120}), self.snapshot)
            self.assertEqual(fresh.call_args.kwargs['timeout'], 15)
        with mock.patch.object(c.time, 'time', return_value=100), mock.patch.object(c, 'fresh_snapshot',
                side_effect=subprocess.TimeoutExpired('api', 35)) as fresh:
            with self.assertRaises(c.NotReady): c.refresh_with_retry(self.state, {'lease_expires_at': 105})
            self.assertEqual(fresh.call_count, 1)

    def test_lease_cannot_outlive_original_gpu_or_process_sample(self):
        now = self.snapshot['fetched_at']
        self.snapshot['hosts'][0]['process_sample_age_seconds'] = 100
        cards, _ = c.platform(self.snapshot, self.config, now=now)
        self.assertEqual(cards[U1]['lease_until'], now + 15)
        self.snapshot['hosts'][0]['process_sample_age_seconds'] = 1
        cards, _ = c.platform(self.snapshot, self.config, now=now)
        self.assertEqual(cards[U1]['lease_until'], now + 90)
        self.snapshot['hosts'][0]['gpus'][0]['sample_age_seconds'] = 110
        cards, _ = c.platform(self.snapshot, self.config, now=now)
        self.assertEqual(cards[U1]['lease_until'], now + 5)

    def test_configure_uses_actual_source_identity_and_requires_new_result(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot['hosts'][0].update(id='iipl-103', label='103')
        identity = {'server': '103', 'science_sha256': 'c' * 64, 'username': 'test'}
        arguments = dict(reviewed_policy_sha256=c.policy_hash(snapshot), compute_target_percent=65,
                         memory_target_percent=65, max_cards=2, hold_id='cpu-test', snapshot=snapshot)
        with mock.patch.object(c.transport, 'load_manifest', return_value=identity), \
                mock.patch.object(c, 'remote', return_value={'status': 'running_or_paused', 'units': {'complete': 1}}):
            config = c.configure_from_semantic(self.root / 'semantic.json', **arguments)
        self.assertEqual(config['source'], {'server': '103', 'run_id': c.RUN, 'science_sha256': 'c' * 64})
        self.assertNotIn('completion_report', config)
        for progress in ({'status': 'running_or_paused', 'units': {'complete': 0}},
                         {'status': 'partial_terminal', 'units': {'complete': 128}}):
            with mock.patch.object(c.transport, 'load_manifest', return_value=identity), \
                    mock.patch.object(c, 'remote', return_value=progress), self.assertRaises(c.NotReady):
                c.configure_from_semantic(self.root / 'semantic.json', **arguments)

    def test_resume_requires_verified_worker_exit_and_never_clears_stop(self):
        c.private_dir(self.state)
        manifest = {'authority_sha256': c.authority_hash(self.config), 'controller_id': 'old', 'machine': self.machine}
        c.write_private(self.state / 'manifest.json', manifest)
        with mock.patch.object(c, 'remote', return_value={'workers': [{'alive': True}]}), \
                mock.patch.object(c, 'watch') as watch, self.assertRaises(c.NotReady):
            c.resume(self.config, self.state)
        watch.assert_not_called()
        self.assertTrue((self.state / 'manifest.json').exists())
        def take_over(config, state, _lock_fd):
            self.assertFalse((state / 'manifest.json').exists())
            self.assertEqual(len(list((state / 'history').glob('manifest-*.json'))), 1)
            os.close(_lock_fd)
            return {'status': 'simulated_resume'}
        with mock.patch.object(c, 'remote', return_value={'workers': [{'alive': False}]}), \
                mock.patch.object(c, 'watch', side_effect=take_over):
            self.assertEqual(c.resume(self.config, self.state)['status'], 'simulated_resume')
        c.write_private(self.state / 'STOP', {'reason': 'user'})
        with mock.patch.object(c, 'remote') as remote, self.assertRaises(c.NotReady):
            c.resume(self.config, self.state)
        remote.assert_not_called()


class RemoteGateTests(unittest.TestCase):
    """Execute the actual remote script locally with only host/paths emulated."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'results' / c.RUN; self.source.mkdir(parents=True)
        self.work = self.root / 'preparations' / c.RUN; self.work.mkdir(parents=True)
        (self.work / 'launcher.lock').touch(); (self.source / '.writer.lock').touch()
        env = self.root / 'venv/bin'; env.mkdir(parents=True); (env / 'python').symlink_to('/usr/bin/true')
        self.units = [{'key': [c.RUN, 'source', 'clean', 'dog', 'cpu-fixture', i], 'input_sha': 'a' * 64, 'mask_sha': 'b' * 64} for i in range(1024)]
        self.science = {'design': 'semantic-v1', 'test': 'CPU fixture only', 'units': self.units}
        self.sha = c.digest({'run_id': c.RUN, 'science': self.science})
        (self.work / 'spec.json').write_text(json.dumps({'run_id': c.RUN, 'science': self.science, 'execution': {'gpu_uuid': U1}}))
        self.machine = {'hostname': 'iipl-104', 'uid': os.getuid(), 'machine_id_sha256': hashlib.sha256(b'cpu-test-machine').hexdigest()}
        self.dbpath = self.source / 'run.sqlite'
        with closing(sqlite3.connect(self.dbpath)) as db, db:
            db.executescript('CREATE TABLE metadata(id INTEGER,identity TEXT); CREATE TABLE units(status TEXT,key TEXT,unit TEXT,image_sha TEXT,scores TEXT); CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT,detail TEXT);')
            db.execute('INSERT INTO metadata VALUES(1,?)', (json.dumps({'run_id': c.RUN, 'science_sha256': self.sha,
                'run_root': str(self.source), 'writer_host': self.machine}),))
            db.executemany('INSERT INTO units(status,key,unit) VALUES(?,?,?)', [('complete', c.canonical(u['key']), c.canonical(u)) for u in self.units])
            db.execute('INSERT INTO events(kind,detail) VALUES(?,?)', ('terminal', json.dumps({'stage': 'M1', 'outcome': 'inconclusive'})))
            for stage in ('S0', 'S1', 'M0', 'M1'): db.execute('INSERT INTO events(kind,detail) VALUES(?,?)', ('stage_gate', json.dumps({'stage': stage})))
        self.script = c.REMOTE.replace("'/data2/zhangzibo/arxiv-tssa'", repr(str(self.root)))
        self.script = self.script.replace('socket.gethostname()', "'iipl-104'")
        self.script = self.script.replace("pathlib.Path('/etc/machine-id').read_bytes()", "b'cpu-test-machine'")

    def invoke(self, action='inspect', **extra):
        return subprocess.run([sys.executable, '-c', self.script], input=json.dumps({'action': action, 'server': '104',
            'science_sha256': self.sha, 'hold_id': 'cpu-only', **extra}), capture_output=True, text=True, timeout=5)

    def test_readonly_full_gate_does_not_modify_ledger(self):
        before = self.dbpath.read_bytes(); result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['complete'], 1024)
        self.assertEqual(self.dbpath.read_bytes(), before)

    def test_partial_terminal_cannot_acquire_gpu(self):
        with closing(sqlite3.connect(self.dbpath)) as db, db: db.execute("DELETE FROM units WHERE rowid>128")
        result = self.invoke(); self.assertNotEqual(result.returncode, 0)
        self.assertIn('completed units differ', result.stderr)
        self.assertEqual(json.loads(self.invoke('poll').stdout)['status'], 'partial_terminal')

    def test_live_scientific_writer_or_wrong_identity_refused(self):
        fd = os.open(self.source / '.writer.lock', os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertNotEqual(self.invoke().returncode, 0)
        finally: os.close(fd)
        self.sha = 'f' * 64
        self.assertIn('science hash mismatch', self.invoke().stderr)

    def test_same_count_wrong_key_or_mask_cannot_pass_completion(self):
        with closing(sqlite3.connect(self.dbpath)) as db, db:
            db.execute('UPDATE units SET key=? WHERE rowid=1', (c.canonical(['wrong']),))
        result = self.invoke(); self.assertIn('completed units differ', result.stderr)
        with closing(sqlite3.connect(self.dbpath)) as db, db:
            changed = {**self.units[0], 'mask_sha': 'c' * 64}
            db.execute('UPDATE units SET key=?,unit=? WHERE rowid=1', (c.canonical(changed['key']), c.canonical(changed)))
        result = self.invoke(); self.assertIn('completed units differ', result.stderr)

    def test_report_verifies_actual_fixture_pngs_scores_and_ledger_hash(self):
        # Synthetic CPU artifact set: exercises the actual verifier, not a model.
        images = self.source / 'images'; images.mkdir()
        from PIL import Image
        import io
        stream = io.BytesIO(); Image.new('RGB', (512, 512)).save(stream, format='PNG')
        image = stream.getvalue(); sha = hashlib.sha256(image).hexdigest()
        scores = {'vit_class': 331, 'clip_score': 30., 'target_clip_score': 20.,
                  'object_clip_scores': {'dog': 10., 'cat': 20., 'rabbit': 30., 'background': 10.}}
        for unit in self.units:
            (images / (c.digest(unit['key']) + '.png')).write_bytes(image)
        with closing(sqlite3.connect(self.dbpath)) as db, db:
            db.execute('UPDATE units SET image_sha=?,scores=?', (sha, json.dumps(scores)))
        result = self.invoke('report'); self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['ledger_files_sha256']['run.sqlite'], hashlib.sha256(self.dbpath.read_bytes()).hexdigest())
        self.assertEqual(report['completed_images'], 1024)
        next(images.iterdir()).write_bytes(b'corrupt')
        self.assertIn('PNG verification failed', self.invoke('report').stderr)

    def test_revocation_continues_after_one_lease_is_missing(self):
        base = self.root / 'gpu-holds'; base.mkdir(mode=0o700)
        state = base / 'cpu-only'; state.mkdir(mode=0o700)
        c.write_private(state / (U2 + '.lease.json'), {'stop_required': False})
        c.write_private(base / 'owner.json', {'controller_id': 'test-controller', 'hold_id': 'cpu-only',
            'workers': [{'gpu_uuid': u, 'process': None} for u in (U1, U2)]})
        result = self.invoke('stop', controller_id='test-controller', machine=self.machine)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)['errors']), 1)
        self.assertTrue(c.read_private(state / (U2 + '.lease.json'))['stop_required'])


if __name__ == '__main__': unittest.main()
