"""Controller isolation checks in a temporary local tree; no network or GPU."""
import base64
import fcntl
import hashlib
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validation
import semantic_science


class SemanticValidationTest(unittest.TestCase):
    def test_successful_frontend_does_not_wait_for_background_inherited_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / 'background.pid'
            program = '''import os,pathlib,sys,time
pid=os.fork()
if pid==0:
 time.sleep(20);os._exit(0)
pathlib.Path(sys.argv[1]).write_text(str(pid))
print('{"complete":true}',flush=True)
os._exit(0)
'''
            real_popen = subprocess.Popen
            def frontend(*args, **kwargs):
                return real_popen([sys.executable, '-c', program, str(pidfile)], **kwargs)
            try:
                with mock.patch.object(validation.subprocess, 'Popen', side_effect=frontend):
                    result = validation.bounded_ssh(Path(tmp) / 'config', '103', 'read-only', '', timeout=.3)
                self.assertEqual(json.loads(result), {'complete': True})
            finally:
                if pidfile.exists():
                    try:os.kill(int(pidfile.read_text()), signal.SIGTERM)
                    except ProcessLookupError:pass

    def test_fresh_snapshot_allows_realistic_http_time_without_changing_freshness_rules(self):
        response = subprocess.CompletedProcess([], 0, stdout=json.dumps({'cache_state': 'fresh'}))
        with mock.patch.object(validation.subprocess, 'run', return_value=response) as query:
            self.assertEqual(validation.fresh_snapshot()['cache_state'], 'fresh')
            command = query.call_args.args[0]
            self.assertEqual(command[command.index('--timeout') + 1], '35')
            self.assertEqual(query.call_args.kwargs['timeout'], 60)
        with mock.patch.object(validation.subprocess, 'run', side_effect=subprocess.TimeoutExpired([], 60)):
            with self.assertRaisesRegex(validation.NotReady, '平台查询超时'):
                validation.fresh_snapshot()

    def test_borrow_observer_context_checks_identity_and_never_closes_owner(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory(prefix='tcl-watch-', dir='/private/tmp') as ssh_tmp, \
                mock.patch.object(validation, 'STATE_DIR', Path(tmp)), \
                mock.patch.object(validation.subprocess, 'run') as ps, \
                mock.patch.object(validation, 'ssh_config') as create:
            state = Path(tmp);state.chmod(0o700)
            config = Path(ssh_tmp) / 'ssh_config';config.write_text('private');config.chmod(0o600)
            identity = {'run_id': validation.RUN_ID, 'uuid': 'GPU-test', 'science_sha256': 'a' * 64, 'server': '103'}
            ready = {**identity, 'pid': 12345, 'time': time.time(), 'ssh_config': str(config)}
            path = state / 'observer-ready.json'
            def save():
                path.write_text(json.dumps(ready));path.chmod(0o600)
            save()
            ps.return_value.stdout = f'{os.getuid()} python {Path(validation.__file__).resolve()} watch --manifest {state / "manifest.json"}'
            with validation.run_ssh_config(identity) as borrowed:
                self.assertEqual(borrowed, config)
            create.assert_not_called()
            self.assertTrue(config.is_file())
            self.assertEqual(ps.call_count, 1)
            config.chmod(0o644)
            self.assertIsNone(validation.observer_config(identity))
            config.chmod(0o600)
            ready['science_sha256'] = 'b' * 64;save()
            self.assertIsNone(validation.observer_config(identity))
            ready['science_sha256'] = identity['science_sha256'];ready['ssh_config'] = '/tmp/untrusted/ssh_config';save()
            self.assertIsNone(validation.observer_config(identity))
            ready['ssh_config'] = str(config);save()
            ps.return_value.stdout = f'{os.getuid()} python unrelated.py'
            self.assertIsNone(validation.observer_config(identity))

    def test_ssh_context_reuses_private_masters_and_closes_only_owned_aliases(self):
        gateway = SimpleNamespace(gateway_address=lambda **kwargs: 'configured.example')
        with mock.patch.dict(sys.modules, {'stage_school_assets': gateway}), \
                mock.patch.object(validation.subprocess, 'run') as close, \
                mock.patch.object(validation.subprocess, 'Popen') as popen:
            popen.return_value.communicate.return_value = ('ok', '')
            def write_client_output(*args, **kwargs):
                popen.call_args.kwargs['stdout'].write('ok')
            popen.return_value.communicate.side_effect = write_client_output
            popen.return_value.returncode = 0
            with validation.ssh_config() as config:
                folder = config.parent
                self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                text = config.read_text()
                self.assertIn('StrictHostKeyChecking yes', text)
                self.assertIn('ControlMaster auto', text)
                self.assertIn('ConnectTimeout 60', text)
                self.assertIn('ServerAliveInterval 15', text)
                self.assertIn('ServerAliveCountMax 2', text)
                self.assertIn('ControlPersist 120', text)
                self.assertIn(f'ControlPath {folder}/cm-%C', text)
                self.assertEqual(validation.bounded_ssh(config, '103', 'true', ''), 'ok')
                self.assertEqual(validation.bounded_ssh(config, '103', 'true', ''), 'ok')
                close.assert_not_called()
            aliases = [call.args[0][-1] for call in close.call_args_list]
            self.assertEqual(aliases, ['school103', 'school-jump'])
            self.assertTrue(all(call.args[0][3:5] == ['-O', 'exit'] for call in close.call_args_list))
            self.assertFalse(folder.exists())
            self.assertNotIn(str(config), validation._SSH_CONTEXTS)

    def test_103_remote_scripts_use_one_bound_data_root(self):
        for script in (validation.REMOTE_PREPARE, validation.REMOTE_RUN, validation.REMOTE_STATE):
            rendered = validation.remote_script(script, '103')
            self.assertIn("pathlib.Path('/data1/zhangzibo/arxiv-tssa')", rendered)
            self.assertNotIn('/data2/zhangzibo/arxiv-tssa', rendered)
            compile(rendered, '<103-remote>', 'exec')
        with self.assertRaises(validation.NotReady):
            validation.remote_script(validation.REMOTE_RUN, '101')

    def test_103_prepare_deploys_fast_loader_and_only_smoke(self):
        expected = validation.execution_sha256()
        with mock.patch.object(validation, 'ssh_config') as config, \
                mock.patch.object(validation, 'bounded_ssh', return_value=json.dumps({'execution_sha256': expected})) as ssh:
            config.return_value.__enter__.return_value = Path('/private/mock-config')
            validation.prepare('103')
        payload = json.loads(ssh.call_args.args[3])
        name = 'scripts/merging/trigger_contrast_localization/runtime_assets.py'
        self.assertEqual(base64.b64decode(payload['files'][name]['content']), (validation.ROOT/name).read_bytes())
        self.assertIn(name, expected)
        self.assertIn("cmd+['smoke','--spec',str(spec)]", validation.REMOTE_PREPARE)
        self.assertNotIn("cmd+['check'", validation.REMOTE_PREPARE)

    def test_103_tick_binds_prepared_node_and_observer_path(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(validation, 'STATE_DIR', Path(tmp)), \
                mock.patch.object(validation, 'fresh_snapshot', return_value={'account': {'username': 'test'}}), \
                mock.patch.object(validation, 'evaluate', return_value={'server': '103', 'host': 'iipl-103', 'uuid': 'GPU-test'}), \
                mock.patch.object(validation, 'execution_sha256', return_value={'runtime.py': 'new'}), \
                mock.patch.object(validation, 'prepare', return_value={'science_sha256': 'a' * 64, 'execution_sha256': {'runtime.py': 'new'}}) as prepare, \
                mock.patch.object(validation, 'start_or_resume', return_value={'status': 'simulated'}) as start:
            self.assertEqual(validation.tick()['status'], 'simulated')
            prepare.assert_called_once_with('103')
            identity = start.call_args.args[0]
            self.assertEqual(identity['server'], '103')
            self.assertEqual(identity['remote_status'], '/data1/zhangzibo/arxiv-tssa/preparations/' + validation.RUN_ID + '/observations/resource-status.json')
            self.assertTrue((Path(tmp) / 'prepared-103.json').is_file())
            self.assertFalse((Path(tmp) / 'prepared-104.json').exists())

    def test_missing_gpu_helper_is_bootstrapped_only_before_run_creation(self):
        for started in (False, True):
            with self.subTest(started=started), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                (root / 'preparations/tcl-pilot24-v2-20261102/repository-recovery-v1').mkdir(parents=True)
                work = root / ('preparations/' + validation.RUN_ID)
                repo = work / 'repository'; repo.mkdir(parents=True)
                (work / 'spec.json').write_text('{}')
                if started:
                    result = root / ('results/' + validation.RUN_ID)
                    result.mkdir(parents=True)
                    (result / 'run.sqlite').touch()
                    (result / '.writer.lock').touch()
                name = 'scripts/merging/trigger_contrast_localization/pilot24_provenance.py'
                raw = b'bootstrap-only-helper'
                payload = {'files': {name: {'content': base64.b64encode(raw).decode(),
                                            'sha256': hashlib.sha256(raw).hexdigest()}}}
                script = validation.REMOTE_PREPARE.replace("pathlib.Path('/data2/zhangzibo/arxiv-tssa')", f'pathlib.Path({str(root)!r})')
                proc = subprocess.run([sys.executable, '-c', script], input=json.dumps(payload),
                                      capture_output=True, text=True, timeout=10)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn('missing fixed inputs', proc.stderr)
                self.assertEqual((repo / name).read_bytes(), raw)

    def test_remote_state_prefers_markdown_and_never_falls_back_on_invalid_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            result = root / 'results' / validation.RUN_ID; result.mkdir(parents=True)
            (result / '.writer.lock').touch()
            (result / 'run.sqlite').write_text('invalid legacy database')
            value = {'schema': 'tcl-run-markdown-v1', 'identity': {}, 'score_schema': {},
                     'units': {'key': {'status': 'complete'}}, 'attempts': [{'id': 1}],
                     'events': [{'kind': 'stage_gate', 'detail': {'stage': 'S0'}},
                                {'kind': 'terminal', 'detail': {'stage': 'S0'}}]}
            md = result / 'run.md'; md.write_text('# Run\n\n```json\n' + json.dumps(value) + '\n```\n')
            script = validation.REMOTE_STATE.replace("pathlib.Path('/data2/zhangzibo/arxiv-tssa')", f'pathlib.Path({str(root)!r})')
            proc = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)['attempts'], 1)
            self.assertEqual(json.loads(proc.stdout)['status'], 'terminal')
            md.write_text('invalid')
            proc = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
            self.assertIn('invalid Markdown ledger', proc.stderr)

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
            self.assertIn('missing fixed inputs', changed.stderr)
            self.assertEqual(codefile.read_bytes(), data)

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

    def test_remote_launch_has_no_independent_execution_hash_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            work = root / ('preparations/' + validation.RUN_ID)
            repo = work / 'repository'
            prefix = 'scripts/merging/trigger_contrast_localization/'
            hashes = {}
            for name in ('runtime.py', 'runtime_store.py', 'runtime_tcl.py', 'runtime_assets.py'):
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
            result = subprocess.run([sys.executable, '-c', script], input=json.dumps({'science_sha256': digest, 'execution_sha256': expected, 'uuid': 'GPU-fixture'}),
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('execution code differs', result.stderr)
            self.assertNotIn('execution code hashes required', result.stderr)
            self.assertIn('fresh observer required', result.stderr)

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
