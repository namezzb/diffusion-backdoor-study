"""Failure-path checks: resource pauses may resume; explicit stops/budgets may not."""
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import worker


class WorkerRecoveryTest(unittest.TestCase):
    argv = ['worker.py', '--uuid', 'GPU-test', '--run-root', '/unused', '--arms', 'masq']

    def test_resource_pause_resumes_the_same_stage(self):
        with patch.object(sys, 'argv', self.argv), patch.object(worker.subprocess, 'run') as run, \
             patch.object(worker, 'wait_for_resource', return_value=True) as wait:
            run.side_effect = [SimpleNamespace(returncode=c) for c in [75, 0, 0, 0]]
            self.assertEqual(worker.main(), 0)
            wait.assert_called_once_with('/unused', 'GPU-test')
            self.assertEqual([c.args[0][-1] for c in run.call_args_list], ['train', 'train', 'verify', 'evaluate'])

    def test_explicit_stop_budget_and_technical_error_do_not_spin(self):
        for code in [130, 76, 1]:
            with self.subTest(code=code), patch.object(sys, 'argv', self.argv), \
                 patch.object(worker.subprocess, 'run', return_value=SimpleNamespace(returncode=code)) as run, \
                 patch.object(worker, 'wait_for_resource') as wait:
                self.assertEqual(worker.main(), code)
                self.assertEqual(run.call_count, 1)
                wait.assert_not_called()

    def test_stop_while_waiting_exits(self):
        with patch.object(sys, 'argv', self.argv), \
             patch.object(worker.subprocess, 'run', return_value=SimpleNamespace(returncode=75)) as run, \
             patch.object(worker, 'wait_for_resource', return_value=False):
            self.assertEqual(worker.main(), 75)
            self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
