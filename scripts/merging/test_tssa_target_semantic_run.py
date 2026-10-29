"""CPU orchestration tests; fake responses are never scientific validation."""
from copy import deepcopy
from contextlib import ExitStack
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
import tssa_target_semantic_run as run


class RecordingBackend:
    def __init__(self, callback, fail=False):
        self.callback, self.fail = callback, fail
        self.calls = 0

    def _value(self, unit, condition, coefficients, stage):
        self.calls += 1
        context = {'unit_id': unit['id'], 'condition_id': condition['id'],
                   'coefficients': None if coefficients is None else tuple(coefficients),
                   'kind': 'teacher' if stage == 'D0' else 'student', 'gradients': stage == 'D2'}
        self.callback(dict(context, operation='begin', cost=dict.fromkeys(run.RESOURCE_KEYS, 0)))
        self.callback(dict(context, operation='test_compute', cost=run.expected_resource(stage, condition['id'])))
        if self.fail:
            raise RuntimeError('injected compute failure after reservation')
        keys = ['normal', 'extra'] if condition['id'] == 'upload' else ['normal', 'triggered', 'extra']
        if stage == 'D0' and condition['id'] != 'upload':
            keys.append('target')
        outputs = {k: torch.full((1, 4, 64, 64), 1.0 if k == 'target' else 0.) for k in keys}
        return {'outputs': outputs, 'losses': None if stage == 'D0' else
                {'attack': None if condition['id'] == 'upload' else 1., 'normal': 0.},
                'gradients': {'attack': None if condition['id'] == 'upload' else [0., 0.],
                              'normal': [0., 0.]} if stage == 'D2' else None,
                'output_rms': {k: float(v.square().mean().sqrt()) for k, v in outputs.items()},
                'errors_vs_teacher': {k: 0. for k in keys}, 'signal_rms': 1.,
                'resource_delta': run.expected_resource(stage, condition['id'])}

    def teacher(self, unit, condition):
        return self._value(unit, condition, None, 'D0')

    def student(self, unit, condition, coefficients, teacher, gradients=False):
        return self._value(unit, condition, coefficients, 'D2' if gradients else 'D1')


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.time = [0.]
        self.ledger = run.Ledger(Path(self.tmp.name).resolve() / 'run', {'test_only': True}, clock=lambda: self.time[0])
        self.ledger.start_cuda_window(hard_watchdog=False)
        self.units = {u: {'id': u} for u in run.UNITS}
        self.conditions = {c: {'id': c} for c in run.CONDITIONS}

    def test_success_status_interface_and_exact_96_cells(self):
        backend = RecordingBackend(self.ledger.reserve)
        with patch.object(run, 'check_stage', side_effect=lambda stage, rows, prior:
                          {'status': 'diagnostic_pass' if stage == 'D3' else 'prefix_pass'}):
            report = run.execute_stages(self.ledger, backend, self.units, self.conditions)
        self.assertEqual(report['status'], 'local_diagnostic_passed')
        self.assertFalse(report['ASR_validated'])
        self.assertEqual(backend.calls, 96)
        self.assertEqual(self.ledger.total, run.LIMITS)
        self.assertEqual(len(list((self.ledger.root / 'cells').glob('*.completed.json'))), 96)

    def test_real_gate_rejects_no_attack_improvement_before_fd(self):
        backend = RecordingBackend(self.ledger.reserve)
        report = run.execute_stages(self.ledger, backend, self.units, self.conditions)
        self.assertEqual(report['status'], 'stopped_at_scientific_gate')
        self.assertEqual(report['stage'], 'D2r')
        self.assertEqual(backend.calls, 32)
        self.assertEqual(self.ledger.total['forward_branch_nfe'], 158)
        self.assertEqual(self.ledger.total['autograd_calls'], 14)

    def test_failed_compute_consumed_and_started_remains(self):
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            run.execute_stages(self.ledger, RecordingBackend(self.ledger.reserve, True), self.units, self.conditions)
        self.assertEqual(self.ledger.total['forward_branch_nfe'], 6)
        self.assertIsNotNone(self.ledger.current)
        self.assertEqual(len(list((self.ledger.root / 'cells').glob('*.started.json'))), 1)
        self.assertFalse(list((self.ledger.root / 'cells').glob('*.completed.json')))
        with self.assertRaises(FileExistsError):
            run.Ledger(self.ledger.root, {})

    def test_failed_receipt_persistence_preserves_pending(self):
        original = run.write_json
        def fail_completed(path, value):
            if str(path).endswith('.completed.json'):
                raise OSError('injected disk failure')
            return original(path, value)
        with patch.object(run, 'write_json', side_effect=fail_completed), self.assertRaises(OSError):
            run.execute_stages(self.ledger, RecordingBackend(self.ledger.reserve), self.units, self.conditions)
        self.assertIsNotNone(self.ledger.current)
        self.assertEqual(self.ledger.total['te_batch_calls'], 1)

    def test_wrong_binding_and_cell_overrun_rejected_before_charge(self):
        op = run.budget_enumeration()[0]
        self.ledger.start_cell(op)
        event = {'unit_id': op['unit_id'], 'condition_id': op['condition_id'], 'coefficients': None,
                 'kind': 'teacher', 'gradients': False,
                 'operation': 'begin', 'cost': dict.fromkeys(run.RESOURCE_KEYS, 0)}
        bad = deepcopy(event); bad['unit_id'] = 'unknown'
        with self.assertRaises(ValueError): self.ledger.reserve(bad)
        self.ledger.reserve(event)
        bad = deepcopy(event); bad.update(operation='too_many', cost=dict(run.LIMITS))
        with self.assertRaises(ValueError): self.ledger.reserve(bad)
        self.assertEqual(self.ledger.total, dict.fromkeys(run.RESOURCE_KEYS, 0))

    def test_reservation_snapshot_does_not_mutate(self):
        op = run.budget_enumeration()[0]
        self.ledger.start_cell(op)
        event = {'unit_id': op['unit_id'], 'condition_id': op['condition_id'], 'coefficients': None,
                 'kind': 'teacher', 'gradients': False,
                 'operation': 'begin', 'cost': dict.fromkeys(run.RESOURCE_KEYS, 0)}
        self.ledger.reserve(event)
        file = self.ledger.root / 'reservations/000001.json'
        before = file.read_bytes()
        event['cost']['te_batch_calls'] = 1; event['operation'] = 'te_batch'
        self.ledger.reserve(event)
        self.assertEqual(file.read_bytes(), before)
        self.assertEqual(json.loads(before)['reserved_total']['te_batch_calls'], 0)

    def test_wall_limit_prevents_next_operation(self):
        self.time[0] = 1800.
        with self.assertRaisesRegex(ValueError, 'wall limit'):
            self.ledger.start_cell(run.budget_enumeration()[0])
        self.assertEqual(self.ledger.sequence, 0)

    def test_permanent_claim_blocks_changed_output_and_repeat(self):
        dest = Path(self.tmp.name).resolve() / 'new-output'
        claim = Path(self.tmp.name).resolve() / 'claims/one.json'
        execution = {'run_root': str(dest), 'claim_path': str(claim),
                     'machine_id_sha256': run.sha(b'test-machine'), 'gpu_uuid': 'test-uuid'}
        with patch.object(Path, 'read_bytes', return_value=b'test-machine'), patch.dict(os.environ, GPU_UUID='test-uuid'):
            run.claim_execution({'execution': execution}, dest)
            with self.assertRaises(FileExistsError): run.claim_execution({'execution': execution}, dest)
            with self.assertRaises(ValueError): run.claim_execution({'execution': execution}, dest.with_name('another'))
        self.assertFalse(dest.exists())

    def test_graphics_process_and_compute_mode_rejected(self):
        uuid = 'GPU-a00d7f16-dee6-f32a-eb89-dde4590ba523'
        permission = {'allowed': True, 'gpu_count': 1, 'gpu_uuid': uuid,
                      'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'enabled': True,
                      'conflict_free': True, 'aggregate_after_launch': 1, 'platform_quota': 4, 'evidence': ['test']}
        empty = '<nvidia_smi_log><gpu><uuid>' + uuid + '</uuid><compute_mode>{}</compute_mode><processes>{}</processes></gpu></nvidia_smi_log>'
        with patch.dict(os.environ, GPU_UUID=uuid, CUDA_VISIBLE_DEVICES=uuid):
            from types import SimpleNamespace
            with patch.object(run.subprocess, 'run', return_value=SimpleNamespace(stdout=empty.format('Default', ''))):
                self.assertEqual(run.verify_permission(permission)['compute_mode'], 'Default')
            with patch.object(run.subprocess, 'run', return_value=SimpleNamespace(stdout=empty.format('Exclusive_Process', ''))):
                with self.assertRaises(ValueError): run.verify_permission(permission)
            for invalid in (empty.format('Default', '').replace('<processes></processes>', ''),
                            empty.format('Default', 'N/A')):
                with patch.object(run.subprocess, 'run', return_value=SimpleNamespace(stdout=invalid)):
                    with self.assertRaisesRegex(ValueError, 'sampling unavailable'): run.verify_permission(permission)
            # Unknown graphics tasks cannot be allowed just because compute-apps was empty.
            graphics = '<process_info><pid>999999999</pid><type>G</type><process_name>unknown</process_name></process_info>'
            with patch.object(run.subprocess, 'run', return_value=SimpleNamespace(stdout=empty.format('Default', graphics))):
                with self.assertRaises((ValueError, OSError)): run.verify_permission(permission)


class DisplayIdentityTests(unittest.TestCase):
    def setUp(self):
        self.pid, self.uid, self.start = 6941, 125, '19910'
        self.name, self.comm = '/usr/bin/gnome-shell', 'gnome-shell'
        self.argv = [self.name]
        self.account = SimpleNamespace(pw_name='gdm', pw_uid=125, pw_gid=125,
                                       pw_dir='/var/lib/gdm3', pw_shell='/bin/false')
        self.binary = SimpleNamespace(st_dev=1, st_ino=2, st_mode=run.stat.S_IFREG | 0o755,
                                      st_uid=0, st_gid=0, st_size=8, st_mtime_ns=3, st_ctime_ns=4)
        self.raw_binary = b'\x7fELFtest'
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(Path, 'stat', side_effect=lambda: SimpleNamespace(st_uid=self.uid)))
        self.stack.enter_context(patch.object(Path, 'lstat', side_effect=lambda: self.binary))
        self.stack.enter_context(patch.object(Path, 'read_text', autospec=True, side_effect=self.read_text))
        self.stack.enter_context(patch.object(Path, 'read_bytes', autospec=True, side_effect=self.read_bytes))
        self.pwd = self.stack.enter_context(patch.object(run.pwd, 'getpwuid', side_effect=lambda uid: self.account))
        self.readlink = self.stack.enter_context(patch.object(run.os, 'readlink', side_effect=PermissionError('cross uid')))

    def read_text(self, path):
        if path.name == 'stat':
            return str(self.pid) + ' (' + self.comm + ') S ' + '0 ' * 18 + self.start
        if path.name == 'comm':
            return self.comm + '\n'
        if path.name == 'status':
            return 'Uid:\t' + '\t'.join([str(self.uid)] * 4) + '\n'
        raise AssertionError(str(path))

    def read_bytes(self, path):
        if path.name == 'cmdline':
            return ('\0'.join(self.argv) + '\0').encode()
        if str(path) == self.name:
            return self.raw_binary
        raise AssertionError(str(path))

    def collect(self, process_type='G'):
        return run.collect_process_identity(self.pid, process_type, self.name)

    def test_normal_readlink_keeps_original_record(self):
        self.readlink.side_effect = None
        self.readlink.return_value = self.name
        self.assertEqual(self.collect(), {'pid': self.pid, 'uid': self.uid, 'type': 'G',
                         'name': self.name, 'start_ticks': self.start, 'executable': self.name})
        self.pwd.assert_not_called()

    def test_verified_gdm_fallback_binds_all_evidence(self):
        record = self.collect()
        self.assertEqual(record['account']['name'], 'gdm')
        self.assertEqual(record['account']['home'], '/var/lib/gdm3')
        self.assertEqual(record['cmdline'], self.argv)
        self.assertEqual(record['executable_sha256'], run.sha(self.raw_binary))
        self.assertEqual(record['executable_evidence'], 'system_display_permission_denied')

    def test_verified_root_xorg_exact_argv_only(self):
        self.pid, self.uid, self.start = 1890, 0, '1863'
        self.name, self.comm = '/usr/lib/xorg/Xorg', 'Xorg'
        self.argv = [self.name, '-core', ':0', '-seat', 'seat0', '-auth', '/var/run/lightdm/root/:0',
                     '-nolisten', 'tcp', 'vt7', '-novtswitch']
        self.account = SimpleNamespace(pw_name='root', pw_uid=0, pw_gid=0, pw_dir='/root', pw_shell='/bin/bash')
        self.assertEqual(self.collect()['account']['uid'], 0)
        self.argv[-1] = '-other-option'
        with self.assertRaises(ValueError): self.collect()

    def test_research_user_or_wrong_system_identity_rejected(self):
        for field, value in [('pw_name', 'researcher'), ('pw_uid', 1001), ('pw_dir', '/home/gdm'),
                             ('pw_shell', '/bin/bash')]:
            with self.subTest(field=field):
                original = getattr(self.account, field)
                setattr(self.account, field, value)
                with self.assertRaises(ValueError): self.collect()
                setattr(self.account, field, original)
        self.uid = self.account.pw_uid = 1001
        with self.assertRaises(ValueError): self.collect()

    def test_wrong_command_unknown_graphics_and_compute_rejected(self):
        with self.assertRaises(ValueError): self.collect('C')
        self.argv.append('--research')
        with self.assertRaises(ValueError): self.collect()
        self.argv.pop()
        self.comm = 'python'
        with self.assertRaises(ValueError): self.collect()
        self.name = '/usr/bin/xfwm4'
        with self.assertRaises(ValueError): self.collect()

    def test_non_permission_readlink_errors_propagate(self):
        for error in (FileNotFoundError('gone'), OSError('unexpected')):
            with self.subTest(error=type(error).__name__):
                self.readlink.side_effect = error
                with self.assertRaises(type(error)): self.collect()
        self.pwd.assert_not_called()

    def test_unsafe_or_non_binary_executable_rejected(self):
        for field, value in [('st_uid', 125), ('st_mode', run.stat.S_IFLNK | 0o755),
                             ('st_mode', run.stat.S_IFREG | 0o775), ('st_mode', run.stat.S_IFREG | 0o644)]:
            with self.subTest(field=field, value=value):
                original = getattr(self.binary, field)
                setattr(self.binary, field, value)
                with self.assertRaises(ValueError): self.collect()
                setattr(self.binary, field, original)
        self.raw_binary = b'#!/bin/sh'
        with self.assertRaises(ValueError): self.collect()

    def test_live_permission_rejects_changed_metadata_or_pid_instance(self):
        uuid = 'GPU-a00d7f16-dee6-f32a-eb89-dde4590ba523'
        record = self.collect()
        permission = {'allowed': True, 'gpu_count': 1, 'gpu_uuid': uuid,
                      'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'enabled': True,
                      'conflict_free': True, 'aggregate_after_launch': 1, 'platform_quota': 4,
                      'evidence': ['test'], 'verified_system_display_processes': [record]}
        xml = ('<nvidia_smi_log><gpu><uuid>' + uuid + '</uuid><compute_mode>Default</compute_mode>'
               '<processes><process_info><pid>6941</pid><type>G</type>'
               '<process_name>/usr/bin/gnome-shell</process_name></process_info></processes></gpu></nvidia_smi_log>')
        with patch.dict(os.environ, GPU_UUID=uuid, CUDA_VISIBLE_DEVICES=uuid), \
             patch.object(run.subprocess, 'run', return_value=SimpleNamespace(stdout=xml)):
            self.assertEqual(run.verify_permission(permission)['processes'], [record])
            self.binary.st_mtime_ns += 1
            with self.assertRaises(ValueError): run.verify_permission(permission)
            self.binary.st_mtime_ns -= 1
            self.start = '19911'
            with self.assertRaises(ValueError): run.verify_permission(permission)


if __name__ == '__main__':
    unittest.main()
