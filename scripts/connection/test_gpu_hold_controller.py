"""CPU-only controller checks. No SSH, API, CUDA or scientific workload."""
import copy
from contextlib import closing
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
        if action == 'report': return self.report
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
        c.platform(self.snapshot, self.config)

    def test_completion_report_does_not_require_file_hash_match(self):
        self.config['completion_report']['sha256'] = 'outdated'
        c.validate_config(self.config)
        report_path = Path(self.config['completion_report']['path'])
        report_path.write_text(json.dumps({**self.report, 'status': 'incomplete'}))
        with self.assertRaises(c.NotReady):
            c.validate_config(self.config)

    def test_changed_notice_is_not_a_stop_but_explicit_stop_is(self):
        self.snapshot['policy']['rectifications'] = [{'status': 'pending', 'summary': 'disk usage reminder'}]
        self.snapshot['policy']['cases'] = [{'status': 'warned', 'kind': 'disk'}]
        self.assertNotEqual(c.policy_hash(self.snapshot), self.config['authorization']['reviewed_policy_sha256'])
        c.platform(self.snapshot, self.config, [U1])
        self.snapshot['policy']['cases'].append({'status': 'active', 'stop_required': True})
        with self.assertRaisesRegex(c.NotReady, 'explicitly requires stopping'):
            c.platform(self.snapshot, self.config, [U1])
        self.snapshot['policy']['cases'][-1]['status'] = 'resolved'
        c.platform(self.snapshot, self.config, [U1])

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
        self.assertEqual([a for a, _ in self.calls if a != 'report'], ['inspect', 'start', 'add', 'renew'])
        start = next(f for a, f in self.calls if a == 'start')['leases']; added = next(f for a, f in self.calls if a == 'add')['leases']
        self.assertEqual(len(start), 1); self.assertEqual(len(added), 2)
        self.assertEqual(start[0]['lease_id'], added[0]['lease_id'])

    def test_pending_verification_does_not_block_renewal(self):
        entered, release = threading.Event(), threading.Event()
        def remote(config, action, **fields):
            if action == 'report':
                entered.set(); release.wait(5); return self.report
            return self.fake_remote(config, action, **fields)
        try:
            with mock.patch.object(c, 'remote', side_effect=remote), mock.patch.object(c, 'fresh_snapshot', return_value=self.snapshot):
                c.watch(self.config, self.state, once=True)
                self.assertTrue(entered.is_set())
                self.assertIn('renew', [a for a, _ in self.calls])
                self.assertEqual(c.read_private(self.state / 'manifest.md')['verification'], 'pending')
        finally:
            release.set()

    def test_failed_verification_revokes_and_records_failure(self):
        class ImmediateThread:
            def __init__(self, target, daemon): self.target = target
            def start(self): self.target()
        def remote(config, action, **fields):
            if action == 'report': raise ValueError('bad image')
            return self.fake_remote(config, action, **fields)
        with mock.patch.object(c.threading, 'Thread', ImmediateThread), mock.patch.object(c, 'remote', side_effect=remote), \
                mock.patch.object(c, 'fresh_snapshot', return_value=self.snapshot):
            with self.assertRaisesRegex(c.NotReady, 'bad image'): c.watch(self.config, self.state, once=True)
        self.assertEqual(self.calls[-1][0], 'stop')
        manifest = c.read_private(self.state / 'manifest.md')
        self.assertEqual(manifest['verification'], 'failed')
        self.assertIn('bad image', manifest['verification_error'])

    def test_renewal_failure_revokes_and_records_visible_failure(self):
        def remote(config, action, **fields):
            if action == 'renew': raise c.NotReady('simulated network failure')
            return self.fake_remote(config, action, **fields)
        with mock.patch.object(c, 'remote', side_effect=remote), mock.patch.object(c, 'fresh_snapshot', return_value=self.snapshot):
            with self.assertRaises(c.NotReady): c.watch(self.config, self.state, once=True)
        self.assertEqual(self.calls[-1][0], 'stop')
        manifest = c.read_private(self.state / 'manifest.md')
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
            stopper.join(2)
            release.set(); thread.join(3); stopper.join(3)
        self.assertTrue(failures); self.assertEqual(results[0]['status'], 'stop_pending')
        self.assertNotIn('start', [a for a, _ in self.calls])

    def test_waiter_refuses_partial_terminal_without_report_or_gpu(self):
        config = copy.deepcopy(self.config); del config['completion_report']
        with mock.patch.object(c, 'remote', return_value={'status': 'partial_terminal'}) as remote, \
                mock.patch.object(c, 'watch') as watch:
            with self.assertRaises(c.NotReady): c.await_completion(config, self.state)
        watch.assert_not_called(); self.assertEqual(remote.call_args.args[1], 'poll')

    def test_waiter_builds_report_and_hands_off_to_watch(self):
        config = copy.deepcopy(self.config); del config['completion_report']
        def take_over(activated, state):
            c.validate_config(activated)
            self.assertFalse((state / 'controller.lock').exists())
            return {'status': 'simulated_handoff'}
        with mock.patch.object(c, 'remote', side_effect=[{'status': 'ready_for_report'}, self.report]), \
                mock.patch.object(c, 'watch', side_effect=take_over):
            self.assertEqual(c.await_completion(config, self.state)['status'], 'simulated_handoff')
        self.assertTrue((self.state / 'completion-report.md').is_file())

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

    def test_configure_does_not_require_remote_run_or_manual_policy_hash(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot['hosts'][0].update(id='iipl-103', label='103')
        identity = {'server': '103', 'science_sha256': 'c' * 64, 'username': 'test'}
        arguments = dict(reviewed_policy_sha256=None, compute_target_percent=65,
                         memory_target_percent=65, max_cards=2, hold_id='cpu-test', snapshot=snapshot)
        with mock.patch.object(c.transport, 'load_manifest', return_value=identity), \
                mock.patch.object(c, 'remote') as remote:
            config = c.configure_from_semantic(self.root / 'semantic.json', **arguments)
        remote.assert_not_called()
        self.assertEqual(config['source'], {'server': '103', 'run_id': c.RUN, 'science_sha256': 'c' * 64})
        self.assertEqual(config['authorization']['reviewed_policy_sha256'], c.policy_hash(snapshot))
        self.assertNotIn('completion_report', config)
        arguments['reviewed_policy_sha256'] = 'f' * 64
        with mock.patch.object(c.transport, 'load_manifest', return_value=identity), self.assertRaises(c.NotReady):
            c.configure_from_semantic(self.root / 'semantic.json', **arguments)

    def test_cli_configure_needs_no_manual_policy_attestation(self):
        identity = {'server': '104', 'science_sha256': 'c' * 64, 'username': 'test'}
        with mock.patch.object(c.transport, 'load_manifest', return_value=identity), \
                mock.patch.object(c, 'fresh_snapshot', return_value=self.snapshot), \
                mock.patch.object(c, 'remote') as remote:
            rc = c.main(['configure', '--config', str(self.root / 'new.json'),
                         '--semantic-manifest', str(self.root / 'semantic.json'), '--until-stopped',
                         '--compute-target-percent', '65', '--memory-target-percent', '65', '--max-cards', '2'])
        self.assertEqual(rc, 0)
        remote.assert_not_called()
        self.assertEqual(c.read_private(self.root / 'new.json')['authorization']['reviewed_policy_sha256'], c.policy_hash(self.snapshot))

    def test_resume_requires_verified_worker_exit_and_never_clears_stop(self):
        c.private_dir(self.state)
        manifest = {'authority_sha256': c.authority_hash(self.config), 'controller_id': 'old', 'machine': self.machine}
        c.write_private(self.state / 'manifest.md', manifest)
        with mock.patch.object(c, 'remote', return_value={'workers': [{'alive': True}]}), \
                mock.patch.object(c, 'watch') as watch, self.assertRaises(c.NotReady):
            c.resume(self.config, self.state)
        watch.assert_not_called()
        self.assertTrue((self.state / 'manifest.md').exists())
        def take_over(config, state):
            self.assertTrue(c.read_private(state / 'manifest.md')['retired'])
            self.assertEqual(len(list((state / 'history').glob('manifest-*.md'))), 1)
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
        (self.work / 'launcher.md').write_text('```json\n' + json.dumps({'pid': 999999, 'uid': os.getuid(), 'boot_id': 'old', 'start_ticks': 1}) + '\n```\n')
        self.dbpath = self.source / 'run.sqlite'
        with closing(sqlite3.connect(self.dbpath)) as db, db:
            db.executescript('CREATE TABLE metadata(id INTEGER,identity TEXT); CREATE TABLE units(status TEXT,key TEXT,unit TEXT,image_sha TEXT,scores TEXT); CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT,detail TEXT);')
            db.execute('INSERT INTO metadata VALUES(1,?)', (json.dumps({'run_id': c.RUN, 'science_sha256': self.sha,
                'run_root': str(self.source), 'writer_host': self.machine}),))
            db.executemany('INSERT INTO units(status,key,unit) VALUES(?,?,?)', [('complete', c.canonical(u['key']), c.canonical(u)) for u in self.units])
            db.execute('INSERT INTO events(kind,detail) VALUES(?,?)', ('session', json.dumps({'writer': {'pid': 999998, 'uid': os.getuid(), 'boot_id': 'old', 'start_ticks': 1}})))
            db.execute('INSERT INTO events(kind,detail) VALUES(?,?)', ('terminal', json.dumps({'stage': 'M1', 'outcome': 'inconclusive', 'reason': 'fixture'})))
            for stage in ('S0', 'S1', 'M0', 'M1'): db.execute('INSERT INTO events(kind,detail) VALUES(?,?)', ('stage_gate', json.dumps({'stage': stage})))
        self.script = c.REMOTE.replace("'/data2/zhangzibo/arxiv-tssa'", repr(str(self.root)))
        self.script = self.script.replace("pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()", "'fixture-current-boot'")
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

    def test_missing_launcher_uses_writer_sessions_and_incomplete_identity_blocks(self):
        (self.work / 'launcher.md').unlink()
        result = self.invoke('handoff')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['launcher_exit'], 'identity_unavailable')
        (self.work / 'launcher.md').write_text('```json\n{}\n```\n')
        result = self.invoke('handoff')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('scientific process exit unconfirmed', result.stderr)

    def test_partial_terminal_cannot_acquire_gpu(self):
        with closing(sqlite3.connect(self.dbpath)) as db, db: db.execute("DELETE FROM units WHERE rowid>128")
        result = self.invoke(); self.assertNotEqual(result.returncode, 0)
        self.assertIn('experiment incomplete', result.stderr)
        self.assertEqual(json.loads(self.invoke('poll').stdout)['status'], 'partial_terminal')

    def test_wrong_scientific_identity_refused_without_lock_files(self):
        (self.work / 'launcher.lock').unlink()
        (self.source / '.writer.lock').unlink()
        self.assertEqual(self.invoke().returncode, 0)
        self.sha = 'f' * 64
        self.assertIn('science hash mismatch', self.invoke().stderr)

    def test_same_count_wrong_key_or_mask_cannot_pass_completion(self):
        with closing(sqlite3.connect(self.dbpath)) as db, db:
            db.execute('UPDATE units SET key=? WHERE rowid=1', (c.canonical(['wrong']),))
        self.assertEqual(self.invoke('handoff').returncode, 0)
        result = self.invoke('report'); self.assertIn('completed units differ', result.stderr)
        with closing(sqlite3.connect(self.dbpath)) as db, db:
            changed = {**self.units[0], 'mask_sha': 'c' * 64}
            db.execute('UPDATE units SET key=?,unit=? WHERE rowid=1', (c.canonical(changed['key']), c.canonical(changed)))
        self.assertEqual(self.invoke('handoff').returncode, 0)
        result = self.invoke('report'); self.assertIn('completed units differ', result.stderr)

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
        self.assertEqual(report['completed_images'], 1024)
        next(images.iterdir()).write_bytes(b'corrupt')
        self.assertEqual(self.invoke('report').returncode, 0)

    def test_markdown_precedes_legacy_database_and_rejects_invalid_document(self):
        with closing(sqlite3.connect(self.dbpath)) as db:
            identity = json.loads(db.execute('SELECT identity FROM metadata').fetchone()[0])
            units = {key: {'unit': json.loads(unit), 'status': status, 'scores': None} for key, unit, status in db.execute('SELECT key,unit,status FROM units')}
            events = [{'id': i, 'time': '', 'kind': kind, 'detail': json.loads(detail)} for i, kind, detail in db.execute('SELECT id,kind,detail FROM events ORDER BY id')]
        value = {'schema': 'tcl-run-markdown-v1', 'identity': identity, 'score_schema': {}, 'units': units, 'attempts': [], 'events': events}
        md = self.source / 'run.md'; md.write_text('# Run\n\n```json\n' + json.dumps(value) + '\n```\n')
        self.dbpath.write_bytes(b'invalid legacy file')
        self.assertEqual(json.loads(self.invoke('poll').stdout)['status'], 'ready_for_report')
        (self.work / 'launcher.md').unlink()
        handoff = self.invoke('handoff')
        self.assertEqual(handoff.returncode, 0, handoff.stderr)
        self.assertEqual(json.loads(handoff.stdout)['launcher_exit'], 'identity_unavailable')
        md.write_text('invalid')
        self.assertIn('invalid Markdown ledger', self.invoke('poll').stderr)

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


class MarkdownOutputTests(unittest.TestCase):
    def test_await_cli_error_is_quoted_in_real_process(self):
        env = dict(os.environ, GPU_HOLD_MARKDOWN_OUTPUT='1')
        proc = subprocess.run([sys.executable, str(Path(c.__file__)), 'await'],
                              env=env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('> ', proc.stdout)
        self.assertTrue(all(line.startswith('> ') for line in (proc.stdout + proc.stderr).splitlines()))


if __name__ == '__main__': unittest.main()
