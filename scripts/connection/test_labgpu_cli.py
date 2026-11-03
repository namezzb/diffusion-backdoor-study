import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import labgpu


class CliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name) / 'labgpu'
        self.patch = mock.patch.object(labgpu, 'CONFIG', self.config)
        self.patch.start()
        labgpu.secure_dir()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def invoke(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = labgpu.main(list(args))
        return status, output.getvalue(), errors.getvalue()

    def cached(self, age=0):
        labgpu.atomic_write(self.config / 'status.json', {'base_url': labgpu.BASE, 'fetched_at': time.time() - age, 'payload': {'username': 'test', 'hosts': []}})

    def test_cached_never_calls_network(self):
        self.cached()
        with mock.patch.object(labgpu.Client, 'request', side_effect=AssertionError('network')):
            code, output, _ = self.invoke('status', '--cached', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['cache_state'], 'cached')

    def test_stale_cache_and_failed_fresh(self):
        self.cached(60)
        with mock.patch.object(labgpu.Client, 'request', side_effect=labgpu.NetworkError('timeout')):
            code, output, _ = self.invoke('status', '--json')
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output)['cache_state'], 'stale')
            code, output, _ = self.invoke('status', '--fresh', '--json')
            self.assertEqual(code, 1)
            self.assertNotIn('hosts', json.loads(output))
            code, output, _ = self.invoke('free', '--json')
            self.assertEqual(code, 1)
            self.assertNotIn('hosts', json.loads(output))

    def test_unauthorized_never_falls_back(self):
        self.cached(60)
        with mock.patch.object(labgpu.Client, 'request', side_effect=labgpu.AuthError('login')):
            code, output, _ = self.invoke('status', '--json')
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output), {'error': 'login'})

    def test_unverified_session_denied(self):
        with self.assertRaises(labgpu.AuthError):
            labgpu.session_check({})
        with self.assertRaises(labgpu.AuthError):
            labgpu.session_check({'authenticated': False})

    def test_permissions_and_symlinks_rejected(self):
        path = self.config / 'status.json'
        path.symlink_to('/dev/null')
        with self.assertRaises(labgpu.LabError):
            labgpu.read_file(path)
        with self.assertRaises(labgpu.LabError):
            labgpu.atomic_write(path, {})
        path.unlink()
        path.write_text('{}')
        path.chmod(0o644)
        with self.assertRaises(labgpu.LabError):
            labgpu.read_file(path)

    def test_cookie_origin_rejected(self):
        labgpu.atomic_write(self.config / 'cookies.json', {'base_url': 'https://attacker.example', 'cookies': []})
        with self.assertRaises(labgpu.LabError):
            labgpu.cookies_load()

    def test_server_and_free_filter(self):
        value = {'hosts': [{'id': '104', 'gpus': [{'status': 'free'}, {'status': 'disabled'}]},
                           {'id': '103', 'gpus': [{'status': 'free'}]}]}
        result = labgpu.render(value, 'free', '104')
        self.assertEqual(result['hosts'], [{'id': '104', 'gpus': [{'status': 'free'}]}])

    def test_refresh_serialized_across_processes(self):
        # Acquiring a held lock in another process must time out without accessing the network.
        code = ('import sys; sys.path.insert(0, sys.argv[1]); import labgpu; '
                'labgpu.CONFIG=__import__("pathlib").Path(sys.argv[2]); '
                'sys.exit(labgpu.main(["status", "--cached", "--timeout", "0.1", "--json"]))')
        with labgpu.Lock(1):
            run = subprocess.run([sys.executable, '-c', code, str(Path(labgpu.__file__).parent), str(self.config)],
                                 capture_output=True, text=True, timeout=3)
        self.assertEqual(run.returncode, 1)
        self.assertIn('锁超时', json.loads(run.stdout)['error'])

    def test_two_simultaneous_refreshes_share_result(self):
        calls = []
        gate = threading.Barrier(2)
        results = []
        def request(client, path, data=None):
            calls.append(path)
            time.sleep(.15)
            return {'username': 'test', 'hosts': []}
        def run():
            gate.wait()
            results.append(labgpu.main(['status', '--fresh', '--json']))
        with mock.patch.object(labgpu.Client, 'request', request), contextlib.redirect_stdout(io.StringIO()):
            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(sorted(results), [0, 0])
        self.assertEqual(calls.count('/api/me'), 1)

    def test_mfa_does_not_save_credentials(self):
        with mock.patch('builtins.input', return_value='test'), mock.patch.object(labgpu.getpass, 'getpass', return_value='secret'), \
                mock.patch.object(labgpu.Client, 'request', return_value={'mfa': True}):
            code, output, _ = self.invoke('login', '--json')
        self.assertEqual(code, 1)
        self.assertIn('MFA', json.loads(output)['error'])
        self.assertFalse((self.config / 'cookies.json').exists())

    def test_mfa_verify_followed_by_session(self):
        self.cached()
        calls = []
        def request(client, path, data=None):
            calls.append(path)
            if path == '/api/login':
                return {'mfa': 'verify', 'ticket': 'ticket'}
            if path == '/api/login/mfa':
                self.assertEqual(data['code'], '123456')
                client.cookies.append({'name': 'session', 'value': 'value', 'domain': 'gpu.orz2333.fun', 'path': '/'})
                return {'ok': True}
            return {'authenticated': True}
        with mock.patch('builtins.input', return_value='test'), mock.patch.object(labgpu.getpass, 'getpass', side_effect=['password', '123456']), \
                mock.patch.object(labgpu.Client, 'request', request):
            code, output, _ = self.invoke('login', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), {'ok': True})
        self.assertEqual(calls, ['/api/login', '/api/login/mfa', '/api/session'])
        self.assertTrue(labgpu.read_file(self.config / 'status.json')['invalidated'])
        self.assertEqual(self.invoke('status', '--cached', '--json')[0], 1)

    def test_cache_wrong_source_and_future_are_not_used(self):
        for base, stamp in [('https://elsewhere.example', time.time()), (labgpu.BASE, time.time() + 60), (labgpu.BASE, True)]:
            labgpu.atomic_write(self.config / 'status.json', {'base_url': base, 'fetched_at': stamp, 'payload': {'username': 'test', 'hosts': []}})
            self.assertEqual(self.invoke('status', '--cached', '--json')[0], 1)

    def test_server_must_match_exactly(self):
        with self.assertRaises(labgpu.LabError):
            labgpu.render({'hosts': [{'id': '104', 'gpus': []}]}, 'status', '1')

    def test_table_shows_unknown_reasons_age_and_sanitizes_control_text(self):
        self.cached()
        normalized = {'cache_age_seconds': 2, 'summary': {}, 'account': {'usage': {'count': 1, 'limit': 4}},
                      'policy': {'rules': {'gpu_management_enabled': False}},
                      'hosts': [{'label': 'host\x1b[31m', 'issues': ['进程不完整'], 'gpus': [
                          {'index': 0, 'name': 'GPU', 'status': 'unknown', 'sample_age_seconds': 12,
                           'users': [], 'reasons': ['未知原因']}]}]}
        with mock.patch.object(labgpu, 'normalize', return_value=normalized):
            code, output, _ = self.invoke('status', '--cached')
        self.assertEqual(code, 0)
        for text in ('采样年龄', '12', '进程不完整', '未知原因', 'GPU 管理: 关闭'):
            self.assertIn(text, output)
        self.assertNotIn('\x1b', output)

    def test_free_empty_prints_explanation(self):
        self.cached()
        with mock.patch.object(labgpu, 'normalize', return_value={'cache_age_seconds': 0, 'hosts': [], 'summary': {}}):
            code, output, _ = self.invoke('free', '--cached')
        self.assertEqual(code, 0)
        self.assertIn('未发现满足条件的空闲候选', output)


if __name__ == '__main__':
    unittest.main()
