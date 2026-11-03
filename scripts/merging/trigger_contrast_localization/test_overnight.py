import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import overnight


class ObservationTest(unittest.TestCase):
    def setUp(self):
        self.value = {'source': 'https://gpu.orz2333.fun', 'cache_state': 'fresh', 'fetched_at': 100,
                      'account': {'username': 'test', 'registered': True, 'active_ban': None, 'usage': {'count': 1, 'limit': 4}},
                      'policy': {'rules': {'gpu_management_enabled': False}, 'gpu_requests': [], 'maintenance': []},
                      'hosts': [{'id': 'iipl-103', 'label': '103', 'gpus': [{'status': 'free', 'uuid': 'GPU-00000000-0000-0000-0000-000000000103'}]},
                                {'id': 'iipl-104', 'label': '104', 'gpus': [{'status': 'free', 'uuid': 'GPU-00000000-0000-0000-0000-000000000104'}]}]}

    def test_selects_first_priority_and_counts_existing(self):
        result = overnight.evaluate(self.value, now=100)
        self.assertEqual((result['server'], result['occupied_including_this_gpu']), ('104', 2))

    def test_rejects_stale_ban_full_and_unresolved_requests(self):
        variants = []
        for change in ('stale', 'ban', 'full', 'request', 'offline'):
            x = copy.deepcopy(self.value)
            if change == 'stale': x['fetched_at'] = 0
            if change == 'ban': x['account']['active_ban'] = {'active': True}
            if change == 'full': x['account']['usage']['count'] = 4
            if change == 'request': x['policy']['gpu_requests'] = [{'status': 'pending'}]
            if change == 'offline': x['cache_state'] = 'stale'
            variants.append(x)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(overnight.NotReady):
                overnight.evaluate(value, now=100)

    def test_never_uses_unknown_or_old_gpu(self):
        for host in self.value['hosts']:
            host['gpus'][0]['status'] = 'stale'
        with self.assertRaises(overnight.NotReady):
            overnight.evaluate(self.value, now=100)

    def test_absolute_deadline(self):
        with self.assertRaises(overnight.NotReady):
            overnight.evaluate(self.value, now=overnight.DEADLINE)

    def test_monitor_other_user_does_not_stop_but_disable_does(self):
        host = self.value['hosts'][1]
        host['online'] = True
        gpu = host['gpus'][0]
        gpu.update(status='shared', sample_age_seconds=2)
        identity = {'username': 'test', 'host': host['id'], 'uuid': gpu['uuid'], 'science_sha256': 'a' * 64}
        status = overnight.monitor_observation(self.value, identity, now=100)
        self.assertTrue(status['observation_valid'])
        self.assertFalse(status['stop_required'])
        gpu['status'] = 'disabled'
        status = overnight.monitor_observation(self.value, identity, now=100)
        self.assertTrue(status['disabled'])
        gpu['status'] = 'stale'
        self.assertFalse(overnight.monitor_observation(self.value, identity, now=100)['observation_valid'])

    def test_evidence_expires_before_either_sample(self):
        host = self.value['hosts'][1]
        host['process_sample_age_seconds'] = 110
        host['gpus'][0]['sample_age_seconds'] = 5
        identity = {'username': 'test', 'server': '104', 'host': host['id'], 'uuid': host['gpus'][0]['uuid'], 'science_sha256': 'a' * 64}
        evidence = overnight.startup_evidence(self.value, identity, now=100)
        from datetime import datetime
        duration = (datetime.fromisoformat(evidence['expires_at_utc']) - datetime.fromisoformat(evidence['observed_at_utc'])).total_seconds()
        self.assertEqual(duration, 8)
        del host['process_sample_age_seconds']
        self.assertIsNone(overnight.startup_evidence(self.value, identity, now=100))

    def test_other_node_is_actionable_not_global_unavailable(self):
        self.value['hosts'][1]['gpus'][0]['status'] = 'others'
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(overnight, 'STATE_DIR', Path(folder)), \
                mock.patch.object(overnight, 'fresh_snapshot', return_value=self.value), \
                mock.patch.object(overnight.time, 'time', return_value=100):
            result = overnight.tick()
        self.assertEqual(result['status'], 'node_preparation_required')
        self.assertEqual(result['server'], '103')
        self.assertEqual(result['uuid'], self.value['hosts'][0]['gpus'][0]['uuid'])

    def test_existing_running_and_terminal_do_not_spawn_or_reprepare(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(overnight, 'STATE_DIR', Path(folder)), \
                mock.patch.object(overnight, 'load_manifest', return_value={'uuid': 'fake'}), \
                mock.patch.object(overnight, 'fresh_snapshot', side_effect=AssertionError('unexpected network')), \
                mock.patch.object(overnight, 'spawn_observer', side_effect=AssertionError('unexpected spawn')), \
                mock.patch.object(overnight, 'observer_alive', return_value=True):
            (Path(folder) / 'manifest.json').write_text('{}')
            for status in ('running', 'terminal'):
                with self.subTest(status=status), mock.patch.object(overnight, 'remote_state', return_value={'status': status}):
                    self.assertEqual(overnight.tick()['status'], status)

    def test_remote_publication_writes_hashed_private_capture(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        uuid = 'GPU-00000000-0000-0000-0000-000000000104'
        science_hash = 'a' * 64
        evidence_fields = {'sampling_valid': True, 'host': socket.gethostname(), 'run_id': overnight.RUN_ID,
                           'gpu_uuid': uuid, 'science_sha256': science_hash, 'disabled': False,
                           'allocation_conflict': False, 'effective_gpu_cap': 4, 'occupied_including_this_gpu': 1,
                           'source': 'https://gpu.orz2333.fun/', 'observed_at_utc': now.isoformat(),
                           'expires_at_utc': (now + timedelta(seconds=60)).isoformat()}
        payload = {'status': {'observation_valid': True}, 'evidence': evidence_fields,
                   'capture': {'hosts': []}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / 'observation' / 'resource-status.json'
            machine = Path(folder) / 'machine-id'
            machine.write_text('fake-machine')
            code = overnight.REMOTE_STATUS_WRITER.replace('/etc/machine-id', str(machine))
            run = subprocess.run([sys.executable, '-c', code, str(path), str(Path(folder) / 'missing.sqlite')],
                                 input=json.dumps(payload), capture_output=True, text=True, timeout=5)
            self.assertEqual(run.returncode, 0, run.stderr)
            evidence = json.loads((path.parent / 'resource-evidence.json').read_text())
            self.assertEqual(evidence['host']['hostname'], socket.gethostname())
            self.assertEqual(evidence['host']['machine_id_sha256'], hashlib.sha256(machine.read_bytes()).hexdigest())
            self.assertEqual(evidence['platform_host'], socket.gethostname())
            capture = Path(evidence['raw_capture']['path'])
            self.assertEqual(hashlib.sha256(capture.read_bytes()).hexdigest(), evidence['raw_capture']['sha256'])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            import pilot24_provenance
            import runtime
            xml = f'<nvidia_smi_log><driver_version>1</driver_version><gpu><uuid>{uuid}</uuid><compute_mode>Default</compute_mode></gpu></nvidia_smi_log>'
            spec = {'run_id': overnight.RUN_ID, 'execution': {'gpu_uuid': uuid, 'resource_evidence': str(path.parent / 'resource-evidence.json')}}
            with mock.patch.object(pilot24_provenance, '_host_identity', return_value=evidence['host']), \
                    mock.patch.object(pilot24_provenance, '_live_gpu_xml', return_value=xml.encode()), \
                    mock.patch.object(pilot24_provenance, '_gpu'), \
                    mock.patch.dict(os.environ, {'GPU_UUID': uuid, 'CUDA_VISIBLE_DEVICES': uuid}):
                self.assertEqual(runtime.resource(spec, science_hash)['gpu_uuid'], uuid)

    def test_cpu_fake_worker_start_binds_expected_science_and_gpu(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            work = root / 'preparations' / overnight.RUN_ID
            repo = work / 'repository'
            entry = repo / 'scripts/merging/trigger_contrast_localization/runtime.py'
            entry.parent.mkdir(parents=True)
            entry.write_text('import time; time.sleep(3); print("CPU FAKE WORKER")\n')
            python = root / 'venv/bin/python'
            python.parent.mkdir(parents=True)
            python.symlink_to(sys.executable)
            observations = work / 'observations'
            observations.mkdir()
            uuid = 'GPU-00000000-0000-0000-0000-000000000104'
            science = {'backend': 'cpu_fake'}
            canonical = json.dumps({'run_id': overnight.RUN_ID, 'science': science}, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            digest = hashlib.sha256(canonical.encode()).hexdigest()
            spec = {'run_id': overnight.RUN_ID, 'science': science, 'execution': {'require_fresh_resource_status': True,
                    'gpu_uuid': 'GPU-00000000-0000-0000-0000-000000000103',
                    'resource_status_file': str(observations / 'resource-status.json'),
                    'resource_evidence': str(observations / 'resource-evidence.json')}}
            (work / 'spec.json').write_text(json.dumps(spec))
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            (observations / 'resource-status.json').write_text(json.dumps({'observation_valid': True, 'disabled': False, 'stop_required': False, 'gpu_uuid': uuid,
                                                                          'run_id': overnight.RUN_ID, 'science_sha256': digest, 'observed_at_utc': now.isoformat()}))
            (observations / 'resource-evidence.json').write_text(json.dumps({'gpu_uuid': uuid, 'science_sha256': digest,
                                                                            'expires_at_utc': (now + timedelta(seconds=60)).isoformat()}))
            code = overnight.REMOTE_RUN.replace('/data2/zhangzibo/arxiv-tssa', str(root))
            status_path = observations / 'resource-status.json'
            status = json.loads(status_path.read_text())
            status['observed_at_utc'] = (now - timedelta(seconds=181)).isoformat()
            status_path.write_text(json.dumps(status))
            stale = subprocess.run([sys.executable, '-c', code], input=json.dumps({'uuid': uuid, 'science_sha256': digest}),
                                   capture_output=True, text=True, timeout=5)
            self.assertNotEqual(stale.returncode, 0)
            status['observed_at_utc'] = now.isoformat()
            status_path.write_text(json.dumps(status))
            run = subprocess.run([sys.executable, '-c', code], input=json.dumps({'uuid': uuid, 'science_sha256': digest}),
                                 capture_output=True, text=True, timeout=5)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)['status'], 'spawned')
            again = subprocess.run([sys.executable, '-c', code], input=json.dumps({'uuid': uuid, 'science_sha256': digest}),
                                   capture_output=True, text=True, timeout=5)
            self.assertEqual(json.loads(again.stdout)['status'], 'spawned', again.stderr)
            self.assertEqual(json.loads((work / 'spec.json').read_text())['execution']['gpu_uuid'], uuid)

    def test_report_contains_terminal_and_stage_gates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            result = root / 'results' / overnight.RUN_ID
            result.mkdir(parents=True)
            with sqlite3.connect(result / 'run.sqlite') as con:
                con.executescript('CREATE TABLE events(id INTEGER PRIMARY KEY, time TEXT, kind TEXT, detail TEXT);'
                                  'CREATE TABLE units(status TEXT); CREATE TABLE attempts(id INTEGER);')
                con.execute('INSERT INTO events(time,kind,detail) VALUES (?,?,?)', ('t', 'stage_gate', json.dumps({'stage': 'S0', 'passed': True})))
                con.execute('INSERT INTO events(time,kind,detail) VALUES (?,?,?)', ('t', 'terminal', json.dumps({'outcome': 'inconclusive'})))
                con.execute("INSERT INTO units VALUES ('complete')")
            code = overnight.REMOTE_STATE.replace('/data2/zhangzibo/arxiv-tssa', str(root))
            run = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=5)
            self.assertEqual(run.returncode, 0, run.stderr)
            value = json.loads(run.stdout)
            self.assertEqual(value['status'], 'terminal')
            self.assertEqual(value['stage_gates'][0]['stage'], 'S0')


if __name__ == '__main__':
    unittest.main()
