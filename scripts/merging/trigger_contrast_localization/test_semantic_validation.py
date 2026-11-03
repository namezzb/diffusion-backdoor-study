"""Controller isolation checks in a temporary local tree; no network or GPU."""
import base64
import contextlib
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
    def setUp(self):
        # Fail closed: these tests must never contact a server.
        guard = tempfile.TemporaryDirectory()
        self.addCleanup(guard.cleanup)
        for name in ('ssh', 'scp', 'sftp'):
            path = Path(guard.name) / name
            path.write_text('#!/bin/sh\nexit 99\n'); path.chmod(0o700)
        env_guard = mock.patch.dict(os.environ, {'PATH': guard.name + os.pathsep + os.environ.get('PATH', '')})
        env_guard.start(); self.addCleanup(env_guard.stop)
        original = subprocess.Popen
        def local_only(command, *args, **kwargs):
            if isinstance(command, (str, bytes)):
                raise AssertionError('shell commands are forbidden in isolated tests')
            executable = Path(os.fsdecode(command[0])).name
            if executable not in {Path(sys.executable).name, 'python3', 'python'}:
                raise AssertionError('non-Python subprocess forbidden: ' + executable)
            return original(command, *args, **kwargs)
        patcher = mock.patch.object(subprocess, 'Popen', side_effect=local_only)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_markdown_subprocess_does_not_wait_for_fork_inheriting_pipes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns = {}; exec(validation.MARKDOWN_SUBPROCESS, ns)
            pidfile = Path(tmp)/'pid'
            child = "import os,sys,time;pid=os.fork();\nif pid==0: time.sleep(20);os._exit(0)\nopen(sys.argv[1],'w').write(str(pid));print('done',flush=True);os._exit(3)"
            started = time.monotonic()
            try:
                result = ns['markdown_subprocess']([sys.executable, '-c', child, str(pidfile)], tmp, os.environ, Path(tmp)/'out.md', Path(tmp)/'err.md')
                self.assertLess(time.monotonic()-started, 3)
                self.assertEqual((result.returncode,result.stdout), (3,'done\n'))
            finally:
                if pidfile.exists():
                    try:os.kill(int(pidfile.read_text()), signal.SIGTERM)
                    except ProcessLookupError:pass

    def test_markdown_subprocess_long_output_without_temporary_raw_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns = {}; exec(validation.MARKDOWN_SUBPROCESS, ns)
            child = "import sys;sys.stdout.write('a'*2000000+'\\n');sys.stdout.flush()"
            with mock.patch('tempfile.TemporaryFile', side_effect=AssertionError('unbounded raw copy')):
                result = ns['markdown_subprocess']([sys.executable, '-c', child], tmp, os.environ, Path(tmp)/'out.md', Path(tmp)/'err.md', capture=False)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertEqual((Path(tmp)/'out.md').read_text().count('a'), 2000000)

    def test_resource_observer_writes_and_reads_both_formats(self):
        import socket
        import runtime
        for suffix in ('.json', '.md'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as tmp:
                tmp = str(Path(tmp).resolve())
                path = Path(tmp) / ('resource-status' + suffix)
                machine = Path(tmp) / 'machine-id'; machine.write_text('local-test')
                evidence = {'host': socket.gethostname(), 'gpu_uuid': 'GPU-test'}
                payload = {'status': {'observation_valid': True}, 'evidence': evidence, 'capture': {'sample': 1}}
                result = subprocess.run([sys.executable, '-c', validation.REMOTE_STATUS_WRITER.replace("'/etc/machine-id'", repr(str(machine))), str(path), str(Path(tmp)/'run.sqlite')], input=json.dumps(payload), text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(runtime.read_resource_json(path)['observation_valid'])
                record = runtime.read_resource_json(Path(tmp)/('resource-evidence'+suffix))
                capture = Path(record['raw_capture']['path'])
                self.assertEqual(capture.suffix, suffix)
                self.assertEqual(hashlib.sha256(capture.read_bytes()).hexdigest(), record['raw_capture']['sha256'])
                if suffix == '.json':
                    self.assertTrue(runtime.read_resource_json(path.with_suffix('.md'))['observation_valid'])
                    self.assertEqual(runtime.read_resource_json(Path(tmp)/'resource-evidence.md'), record)

    def test_markdown_subprocess_utf8_split_across_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns = {}; exec(validation.MARKDOWN_SUBPROCESS, ns)
            out = Path(tmp) / 'out.md'; err = Path(tmp) / 'err.md'
            child = "import os,time;os.write(1,bytes([0xe4]));time.sleep(.3);os.write(1,bytes([0xb8,0xad,10]))"
            result = ns['markdown_subprocess']([sys.executable, '-c', child], tmp, os.environ, out, err)
            self.assertEqual(result.stdout, '中\n')
            self.assertIn('    中\n', out.read_text())

    def test_markdown_subprocess_output_and_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns = {}; exec(validation.MARKDOWN_SUBPROCESS, ns)
            out = Path(tmp) / 'out.md'; err = Path(tmp) / 'err.md'
            child = 'import sys;print("hello");print("bad",file=sys.stderr);sys.exit(7)'
            result = ns['markdown_subprocess']([sys.executable, '-c', child], tmp, os.environ, out, err)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (7, 'hello\n', 'bad\n'))
            self.assertIn('    hello\n', out.read_text())
            self.assertIn('    bad\n', err.read_text())

    def test_markdown_wrapper_needs_no_inherited_lock_fd(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapper = validation.MARKDOWN_SUBPROCESS + "\nimport sys; r=markdown_subprocess(sys.argv[3:],None,os.environ,sys.argv[1],sys.argv[2],capture=False);sys.exit(r.returncode)"
            proc = subprocess.run([sys.executable, '-c', wrapper, str(Path(tmp)/'session.md'),
                                   str(Path(tmp)/'errors.md'), sys.executable, '-c',
                                   'print("running",flush=True);raise SystemExit(9)'], timeout=5)
            self.assertEqual(proc.returncode, 9)
            self.assertIn('    running', (Path(tmp)/'session.md').read_text())
            self.assertNotIn('pass_fds=', validation.REMOTE_RUN)
            self.assertNotIn('flock', validation.REMOTE_RUN)

    def test_markdown_state_roundtrip_and_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(validation, 'STATE_DIR', Path(tmp)):
            state = Path(tmp); state.chmod(0o700)
            path = state / 'prepared-103.md'
            legacy = path.with_suffix('.json')
            legacy.write_text(json.dumps({'value': 'old'})); legacy.chmod(0o600)
            self.assertEqual(validation.read_private_state(path), {'value': 'old'})
            validation.save_private(path, {'value': 'new'})
            self.assertEqual(validation.read_private_state(path), {'value': 'new'})
            self.assertEqual(json.loads(legacy.read_text()), {'value': 'old'})
            self.assertIn('```json\n', path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_markdown_log_indents_every_line(self):
        import io
        output = io.StringIO()
        stream = validation.MarkdownLogStream(output)
        stream.write('first\nsecond'); stream.write(' continued\nthird\n')
        self.assertEqual(output.getvalue(), '    first\n    second continued\n    third\n')

    def test_manifest_new_and_existing_selection(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(validation, 'STATE_DIR', Path(tmp)):
            state = Path(tmp); state.chmod(0o700)
            self.assertEqual(validation.manifest_path(), state / 'manifest.md')
            legacy = state / 'manifest.json'; legacy.write_text('{}'); legacy.chmod(0o600)
            self.assertEqual(validation.manifest_path(), legacy)
            validation.save_private(state / 'manifest.md', {'value': 1})
            self.assertEqual(validation.manifest_path(), state / 'manifest.md')

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
            self.assertTrue((Path(tmp) / 'prepared-103.md').is_file())
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
                name = 'scripts/merging/trigger_contrast_localization/pilot24_provenance.py'
                raw = b'bootstrap-only-helper'
                payload = {'files': {name: {'content': base64.b64encode(raw).decode(),
                                            'sha256': hashlib.sha256(raw).hexdigest()}}}
                script = validation.REMOTE_PREPARE.replace("pathlib.Path('/data2/zhangzibo/arxiv-tssa')", f'pathlib.Path({str(root)!r})')
                proc = subprocess.run([sys.executable, '-c', script], input=json.dumps(payload),
                                      capture_output=True, text=True, timeout=10)
                self.assertNotEqual(proc.returncode, 0)
                if started:
                    self.assertIn('cannot be confirmed stopped', proc.stderr)
                    self.assertFalse((repo / name).exists())
                else:
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

    def test_process_observations_and_legacy_sqlite_without_lock(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); work = base / 'work'; work.mkdir(); root = base / 'run'; root.mkdir()
            proc = base / 'proc'; (proc / '123').mkdir(parents=True)
            (proc / 'sys/kernel/random').mkdir(parents=True)
            (proc / 'sys/kernel/random/boot_id').write_text('boot-test')
            (proc / '123/stat').write_text('123 (python) S ' + '0 ' * 18 + '456 0')
            source = validation.REMOTE_PROCESS_STATE.replace("'/proc'", repr(str(proc))).replace("'/proc/sys/kernel/random/boot_id'", repr(str(proc / 'sys/kernel/random/boot_id')))
            ns = {}; exec(source, ns)
            status = ns['process_status']; process = {'pid': 123, 'uid': os.geteuid(), 'start_ticks': 456, 'boot_id': 'boot-test'}
            self.assertEqual(status(work, root), 'inactive')
            (work / 'launcher.md').write_text('# process\n\n```json\n' + json.dumps(process) + '\n```\n')
            self.assertEqual(status(work, root), 'running')
            process['start_ticks'] = 455
            (work / 'launcher.md').write_text('```json\n' + json.dumps(process) + '\n```\n')
            self.assertEqual(status(work, root), 'inactive')
            (work / 'launcher.md').unlink()
            db = root / 'run.sqlite'
            with sqlite3.connect(db) as con:
                con.execute('CREATE TABLE events (id INTEGER, kind TEXT, detail TEXT)')
                con.execute('INSERT INTO events VALUES (1, ?, ?)', ('session', json.dumps({'writer': {'pid': 123}})))
            self.assertEqual(status(work, root), 'unknown')
            process['start_ticks'] = 456
            with sqlite3.connect(db) as con:
                con.execute('UPDATE events SET detail=?', (json.dumps({'writer': process}),))
            self.assertEqual(status(work, root), 'running')
            self.assertFalse((root / '.writer.lock').exists())
            md = root / 'run.md'
            md.write_text('```json\n' + json.dumps({'events': [{'kind': 'session', 'detail': {'writer': process}}]}) + '\n```\n')
            self.assertEqual(status(work, root), 'running')
            md.write_text('invalid')
            self.assertEqual(status(work, root), 'unknown')

    def test_observer_reuse_and_lost_launch_response(self):
        identity = {'uuid': 'GPU-test', 'science_sha256': 'a' * 64, 'server': '103'}
        ready = {'run_id': validation.RUN_ID, 'uuid': identity['uuid'], 'startup_evidence': True,
                 'time': time.time(), 'pid': os.getpid()}
        for alive in (True, False):
            with self.subTest(existing=alive), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'ready.json'; path.write_text(json.dumps(ready))
                worker = mock.Mock()
                with mock.patch.object(validation, 'observer_ready_path', return_value=path), \
                        mock.patch.object(validation, 'observer_alive', return_value=alive), \
                        mock.patch.object(validation, 'spawn_observer', return_value=worker) as spawn, \
                        mock.patch.object(validation, 'run_ssh_config', return_value=contextlib.nullcontext(Path(tmp) / 'fake')), \
                        mock.patch.object(validation, 'bounded_ssh', side_effect=TimeoutError('lost reply')):
                    with self.assertRaises(TimeoutError): validation.start_or_resume(identity)
                    self.assertEqual(spawn.call_count, 0 if alive else 1)
                    worker.terminate.assert_not_called()

    def test_tick_unknown_process_must_not_attempt_start(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(validation, 'STATE_DIR', Path(tmp)), \
                mock.patch.object(validation, 'remote_state', return_value={'status': 'unknown'}), \
                mock.patch.object(validation, 'load_manifest', return_value={'run_id': validation.RUN_ID}), \
                mock.patch.object(validation, 'fresh_snapshot') as snapshot, \
                mock.patch.object(validation, 'start_or_resume') as start:
            validation.save_private(Path(tmp) / 'manifest.md', {'run_id': validation.RUN_ID})
            result = validation.tick()
            self.assertEqual(result['status'], 'unknown')
            snapshot.assert_not_called(); start.assert_not_called()

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
            # An unreadable observation must prevent deployment without needing a lock.
            (work / 'launcher.md').write_text('invalid process observation')
            running = subprocess.run([sys.executable, '-c', script], input=json.dumps(payload), text=True,
                                     capture_output=True, timeout=10)
            self.assertNotEqual(running.returncode, 0)
            self.assertIn('cannot be confirmed stopped', running.stderr)
            (work / 'launcher.md').unlink()
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
            (Path(tmp) / 'prepared-104.json').chmod(0o600)
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
            (Path(tmp) / 'prepared-104.json').chmod(0o600)
            with self.assertRaises(validation.NotReady):
                validation.tick()
            start.assert_not_called()


if __name__ == '__main__': unittest.main()
