"""Offline installer guard tests; no real pip installation, SSH or CUDA access."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import install_school_offline_env as installer


MANIFEST = Path(__file__).resolve().parents[1] / 'research' / installer.ENVIRONMENT_NAME


class InputTests(unittest.TestCase):
    def test_frozen_manifest_and_all_51_pins_match_lock(self):
        spec, lock, pins = installer.read_inputs(MANIFEST)
        self.assertEqual(len(pins), 51)
        self.assertEqual(sum(item['size'] for item in spec['files']), 3909917779)
        self.assertEqual(pins['torch'], '2.7.1+cu128')
        self.assertEqual(pins['ftfy'], '6.3.1')
        self.assertEqual(installer.sha256(lock), spec['lock_file_sha256'])

    def test_dry_run_does_not_spawn_processes_or_write(self):
        with mock.patch.object(installer.subprocess, 'Popen', side_effect=AssertionError('No subprocesses')), \
             mock.patch.object(installer, 'validate_server', side_effect=AssertionError('No server probe')), \
             mock.patch.object(installer.tempfile, 'mkdtemp', side_effect=AssertionError('No writes')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(installer.main(['--dry-run', '--manifest', str(MANIFEST)]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan['wheel_count'], 51)
        self.assertFalse(plan['installation_performed'])

    def test_lock_cannot_introduce_url_or_other_pip_option(self):
        digest = 'a' * 64
        for text in ('--index-url https://example.invalid', 'thing @ https://example.invalid/a.whl',
                     f'thing==1 --hash=sha256:{digest} --target /tmp', '-r other.txt'):
            with self.subTest(text=text), self.assertRaises(installer.InstallError):
                installer.parse_lock(text)

    def test_changed_lock_is_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'wrong.lock'
            path.write_text('changed')
            with self.assertRaisesRegex(installer.InstallError, 'lock SHA256'):
                installer.read_inputs(MANIFEST, path)

    def test_wheel_hash_size_and_escaping_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / 'root'
            (root / 'wheelhouse').mkdir(parents=True)
            path = root / 'wheelhouse' / 'tiny.whl'
            path.write_bytes(b'abc')
            spec = {'files': [{'local_path': 'wheelhouse/tiny.whl', 'size': 3, 'sha256': installer.sha256(path)}]}
            self.assertEqual(installer.verify_wheels(spec, root)[0]['size'], 3)
            alternative = root / 'wheelhouse/unregistered.whl'
            alternative.write_bytes(b'anything')
            with self.assertRaisesRegex(installer.InstallError, 'unregistered'):
                installer.verify_wheels(spec, root)
            alternative.unlink()
            path.write_bytes(b'abd')
            with self.assertRaisesRegex(installer.InstallError, 'SHA256'):
                installer.verify_wheels(spec, root)
            path.write_bytes(b'abcd')
            with self.assertRaisesRegex(installer.InstallError, 'size'):
                installer.verify_wheels(spec, root)
            outside = Path(tmp) / 'outside.whl'
            outside.write_bytes(b'abc')
            path.unlink()
            path.symlink_to(outside)
            with self.assertRaisesRegex(installer.InstallError, 'escapes'):
                installer.verify_wheels(spec, root)


class EnvironmentTests(unittest.TestCase):
    def test_external_base_executable_is_allowed_only_with_venv_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            venv = root / 'venv'
            (venv / 'bin').mkdir(parents=True)
            site = venv / 'lib' / 'python3.11' / 'site-packages'
            site.mkdir(parents=True)
            pip = site / 'pip.py'
            pip.write_text('')
            base = root / 'anaconda3'
            base.mkdir()
            python = venv / 'bin' / 'python'
            python.symlink_to(base / 'python')
            (base / 'python').write_text('')
            spec = {'target': {'python_full_version': '3.11.7'}, 'files': [{}]}
            probe = {'system': 'Linux', 'machine': 'x86_64', 'implementation': 'CPython', 'python_full_version': '3.11.7',
                     'prefix': str(venv), 'base_prefix': str(base), 'executable': str(python),
                     'real_executable': str(base / 'python'), 'enable_user_site': False, 'CUDA_imported': False,
                     'purelib': str(site), 'platlib': str(site), 'scripts': str(venv / 'bin'), 'pip_file': str(pip),
                     'installed_distributions': [{'location': str(site)}],
                     'wheel_compatibility': [{'compatible': True, 'requires_python_satisfied': True}]}
            installer.validate_probe(probe, spec, venv, python)
            with self.assertRaisesRegex(installer.InstallError, 'base installation'):
                installer.validate_probe({**probe, 'prefix': str(base)}, spec, venv, python)
            with self.assertRaisesRegex(installer.InstallError, 'escapes'):
                installer.validate_probe({**probe, 'purelib': str(base)}, spec, venv, python)
            with self.assertRaisesRegex(installer.InstallError, '3.11.7'):
                installer.validate_probe({**probe, 'python_full_version': '3.12.3'}, spec, venv, python)

    def test_pip_and_gpu_environment_cannot_redirect_install(self):
        with mock.patch.dict(os.environ, {'PIP_TARGET': '/system', 'PIP_INDEX_URL': 'https://example.invalid',
                                         'PYTHONPATH': '/base', 'CUDA_VISIBLE_DEVICES': 'GPU-unsafe'}, clear=True):
            root = Path('/data2/zhangzibo/arxiv-tssa')
            env = installer.safe_environment(root, root / 'tmp' / 'install')
        self.assertNotIn('PIP_TARGET', env)
        self.assertNotIn('PYTHONPATH', env)
        self.assertEqual(env['CUDA_VISIBLE_DEVICES'], '')
        self.assertEqual(env['PIP_CONFIG_FILE'], os.devnull)
        self.assertTrue(env['TMPDIR'].startswith(str(root)))
        command = installer.pip_command(root / 'venv/bin/python', root, root / 'research/input.lock')
        for flag in ('--no-index', '--no-cache-dir', '--only-binary=:all:', '--require-hashes', '--no-compile', '--force-reinstall'):
            self.assertIn(flag, command)
        self.assertEqual(command[:4], [str(root / 'venv/bin/python'), '-I', '-B', '-m'])

    def test_non_linux_or_wrong_account_cannot_reach_pip(self):
        with mock.patch.object(installer.pwd, 'getpwuid', return_value=mock.Mock(pw_name='someone-else')):
            with self.assertRaisesRegex(installer.InstallError, 'zhangzibo'):
                installer.validate_server(Path('/not/used'))


class AuditTests(unittest.TestCase):
    def test_verify_only_never_invokes_install_or_ml_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            venv = root / 'venv'
            (venv / 'bin').mkdir(parents=True)
            (root / 'wheelhouse').mkdir()
            wheel = root / 'wheelhouse/tiny.whl'
            wheel.write_bytes(b'abc')
            manifest = root / 'environment.json'
            manifest.write_text('{}')
            lock = root / 'input.lock'
            lock.write_text('test')
            spec = {'target': {}, 'lock_file_sha256': installer.sha256(lock), 'files': [
                {'local_path': 'wheelhouse/tiny.whl', 'size': 3, 'sha256': installer.sha256(wheel)}]}
            names = []
            def fake_command(self, name, argv, env, **kwargs):
                names.append(name)
                return {'test_fixture': True}
            with mock.patch.object(installer, 'ALLOWED_ROOT', root), \
                 mock.patch.object(installer, 'read_inputs', return_value=(spec, lock, {'test': '1'})), \
                 mock.patch.object(installer, 'validate_server', return_value=(root, venv, venv / 'bin/python')), \
                 mock.patch.object(installer, 'validate_probe'), \
                 mock.patch.object(installer.Audit, 'command', fake_command), \
                 mock.patch.object(installer.subprocess, 'Popen', side_effect=AssertionError('No real install')), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                code = installer.main(['--verify-only', '--manifest', str(manifest)])
            self.assertEqual(code, 0)
            self.assertEqual(names, ['interpreter'])
            result = json.loads(output.getvalue())
            record = json.loads(Path(result['audit']).read_text())
            self.assertEqual(record['status'], 'inputs_verified_not_installed')
            self.assertFalse(record['installation_attempted'])
            self.assertFalse(record['CPU_imports_tested'])
            self.assertEqual(len(record['verified_wheels']), 1)

    def test_real_cpu_subprocess_failure_preserves_audit_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            audit = installer.Audit(directory, {'test_only': True})
            env = dict(os.environ, TMPDIR=tmp)
            with self.assertRaisesRegex(installer.InstallError, 'exited 7'):
                audit.command('failure', [installer.sys.executable, '-I', '-B', '-c',
                                         'import sys; print("fixture stdout"); print("fixture stderr",file=sys.stderr); sys.exit(7)'], env)
            self.assertEqual((directory / 'failure.stdout.log').read_text().strip(), 'fixture stdout')
            self.assertEqual((directory / 'failure.stderr.log').read_text().strip(), 'fixture stderr')
            record = json.loads((directory / 'audit.json').read_text())
            self.assertEqual(record['commands'][0]['returncode'], 7)
            self.assertEqual(record['commands'][0]['status'], 'failed')

    def test_timeout_stops_only_owned_child_process_group_and_keeps_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = installer.Audit(Path(tmp), {'test_only': True})
            with self.assertRaises(subprocess.TimeoutExpired):
                audit.command('timeout', [installer.sys.executable, '-I', '-B', '-c', 'import time; time.sleep(30)'],
                              dict(os.environ, TMPDIR=tmp), timeout=0.1)
            record = json.loads((Path(tmp) / 'audit.json').read_text())
            self.assertEqual(record['commands'][0]['error_type'], 'TimeoutExpired')


if __name__ == '__main__':
    unittest.main()
