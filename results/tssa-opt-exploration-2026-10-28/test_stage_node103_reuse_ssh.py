"""Small local-only checks for connection isolation and bounded cleanup."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).with_name('stage_node103_reuse_ssh.py')
SPEC = importlib.util.spec_from_file_location('private_master_wrapper', PATH)
WRAPPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WRAPPER)


class ConnectionIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tssa-mux-test-', dir='/private/tmp')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.folder.chmod(0o700)
        self.config = self.folder / 'config'
        self.config.write_text('Host *\n    StrictHostKeyChecking yes\n')
        self.records = []
        self.masters = WRAPPER.PrivateMasters(self.config, self.folder, self.records.append)

    def test_exact_private_sockets_and_no_fallback(self):
        for host in WRAPPER.HOSTS:
            argv = self.masters.control_argv(host, 'exit')
            self.assertEqual(argv[argv.index('-S') + 1], str(self.folder / ('s' + host[-3:])))
            self.assertIn('StrictHostKeyChecking=yes', argv)
            self.assertIn('ConnectionAttempts=1', argv)
            self.assertIn('ControlMaster=no', argv)
            self.assertIn('ProxyCommand=/usr/bin/false', argv)
            self.assertEqual(argv[-3:], ['-O', 'exit', host])
        with self.assertRaises(AssertionError):
            self.masters.options('school127', slave=True)

    def test_missing_master_fails_before_transport(self):
        with patch.object(WRAPPER.subprocess, 'Popen', side_effect=AssertionError('Must not connect')):
            with self.assertRaisesRegex(RuntimeError, 'no reconnect'):
                self.masters.ssh_argv(self.config, 'school103', 'print(1)')

    def test_control_timeout_still_cleans_only_registered_master(self):
        class Process:
            pid, returncode, waits = 654321, None, 0
            def poll(self):
                return self.returncode
            def wait(self, timeout):
                self.waits += 1
                if self.waits == 1:
                    raise subprocess.TimeoutExpired('owned master', timeout)
                self.returncode = -signal.SIGTERM
                return self.returncode
        process = Process()
        self.masters.processes['school103'] = process
        self.masters.errors['school103'] = (self.folder / 'school103.stderr').open('x+b')
        with patch.object(self.masters, '_owned_socket', return_value=True), \
             patch.object(WRAPPER.subprocess, 'run', side_effect=subprocess.TimeoutExpired('control exit', 10)) as run, \
             patch.object(WRAPPER.os, 'killpg') as kill:
            self.masters.close()
        kill.assert_called_once_with(process.pid, signal.SIGTERM)
        self.assertEqual(run.call_args.args[0][-3:], ['-O', 'exit', 'school103'])
        self.assertEqual(len(self.records), 1)
        self.assertIn('control_exit_error', self.records[0])
        self.assertEqual(self.records[0]['returncode'], -signal.SIGTERM)
        self.assertTrue(self.masters.errors['school103'].closed)

    def test_both_dry_runs_validate_pins_without_network(self):
        before = hashlib.sha256(WRAPPER.PREPARE.read_bytes()).hexdigest()
        for stage, count in [('wheels', 51), ('models', 47)]:
            output = io.StringIO()
            with patch.object(WRAPPER.subprocess, 'Popen', side_effect=AssertionError('Must not connect')), \
                 patch.object(WRAPPER.subprocess, 'run', side_effect=AssertionError('Must not connect')), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(WRAPPER.main(['--stage', stage]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result['file_count'], count)
            self.assertEqual(result['status'], 'prepared_locally_no_connection')
            self.assertFalse(result['automatic_retry'])
        self.assertEqual(before, WRAPPER.PREPARE_SHA)
        self.assertEqual(hashlib.sha256(WRAPPER.PREPARE.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
