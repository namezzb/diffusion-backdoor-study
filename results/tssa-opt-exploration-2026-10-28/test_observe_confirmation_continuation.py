"""Local CPU fixtures only; all new confirmation/process facts are SIMULATED."""
import ast
import base64
from contextlib import contextmanager, ExitStack, redirect_stdout
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import shlex
import zlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
def load(name):
    spec = importlib.util.spec_from_file_location('_test_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
m = load('observe_confirmation_continuation'); o, c = m.dependencies()
old_tests = load('test_observe_image_search')


@contextmanager
def fixture(directory):
    base = Path(directory).resolve()
    # Use the prior observer's independent synthetic recovery provenance fixture.
    # Its module is separate, so bind the new observer to that exact test module.
    with patch.object(m, 'OBSERVER', old_tests.m), old_tests.recovery_fixture(base) as f:
        observer = old_tests.m
        updates = {'RECOVERY': observer.RECOVERY_NAME, 'IDENTITY_SHA': observer.RECOVERY_IDENTITY_SHA,
                   'REMOTE_OLD': {p.name: observer.sha(p.read_bytes()) for p in (base / 'launch-control').glob('*.json')}}
        with patch.multiple(c, **updates), patch.object(m, 'EXPECTED_UID', os.getuid()):
            def envelope(name, payload):
                old_tests.write_json(f.run, name, {'payload': payload, 'sha256': observer.digest(payload),
                                                  'identity_sha256': c.IDENTITY_SHA})
            for stage in ('search', 'dev'):
                summary = {'SIMULATED': stage}
                selection = {'selected': ['candidate'], 'coefficients': {'candidate': [.5, 1]},
                             'summary_sha256': observer.digest(summary)}
                envelope(stage + '_summary.json', summary); envelope(stage + '_selection.json', selection)
            decision = {'status': 'snapshot_ready_for_live_start_checks', 'plan_sha256': c.PLAN_SHA,
                'GPU_start_authorized': False, 'selected_search_count': 1, 'completed_images': 768, 'current_started': 0,
                'archived_failed_attempts': 1, 'archived_failed_NFE_upper_bound': 50, 'confirm_images': 576,
                'final_attempts_with_failure': 1345, 'final_generation_branch_NFE_upper_bound': 67250,
                'budget_attempt_cap': 1440, 'budget_generation_branch_NFE_cap': 72000,
                'winner': 'candidate', 'winner_coefficients': [.5, 1]}
            token = 'c'*32; stem = 'confirmation-' + c.PLAN_SHA + '-' + token; control = base / 'launch-control'
            claim = {'schema_version': 1, 'server': '103', 'confirmation_token': token, 'plan_sha256': c.PLAN_SHA,
                'identity_sha256': c.IDENTITY_SHA, 'run_root': str(f.run), 'guard_sha256': c.GUARD_SHA,
                'budget_gate_sha256': c.GATE_SHA, 'continuation_sha256': m.CONTINUATION_SHA,
                'receipt': str(control / (stem + '.receipt.json')), 'log': str(control / (stem + '.log')),
                'status': 'confirmation_claimed_before_spawn', 'automatic_retry_allowed': False,
                'old_evidence_hashes_preserved': c.REMOTE_OLD, 'command': m.expected_command(base, f.run),
                'boot_id': '22222222-3333-4444-5555-666666666666', 'permission_sha256': 'a'*64,
                'observation_sha256': 'b'*64, 'budget_decision': decision,
                'gpu': {'index': 2, 'uuid': 'GPU-11111111-2222-3333-4444-555555555555', 'compute_mode': 'Default'},
                'verified': {'completed_receipts_and_PNGs_verified': 768, 'dev_selection_sha256': observer.digest(selection),
                             'input_inventory_sha256': 'd'*64}}
            receipt = dict(claim, status='runner_process_spawned_not_GPU_acceptance', pid=999998,
                           started_at='2026-10-28T12:00:00+00:00', process_start_ticks='600')
            (control / c.CLAIM_NAME).write_text(json.dumps(claim)); raw = json.dumps(receipt).encode()
            Path(receipt['receipt']).write_bytes(raw)
            Path(receipt['log']).write_text('RuntimeError: SIMULATED diagnostic\n{"stage":"confirm","ASR":0.998877}\n')
            wanted = {'receipt_path': receipt['receipt'], 'receipt_sha256': observer.sha(raw)}
            yield SimpleNamespace(**vars(f), o=observer, envelope=envelope, confirmation=receipt, wanted=wanted,
                                  claim=control / c.CLAIM_NAME, payload={'server': '103', 'plan_sha256': c.PLAN_SHA,
                                  'public_plan': f.public, 'confirmation': wanted})


class LocalChecks(unittest.TestCase):
    def test_default_never_connects(self):
        with patch.object(o, 'one_bounded_ssh', side_effect=AssertionError('Network forbidden')), redirect_stdout(io.StringIO()) as text:
            self.assertEqual(m.main([]), 0)
        result = json.loads(text.getvalue())
        self.assertEqual(result['status'], 'prepared_locally_no_connection')
        self.assertFalse(result['confirmation_receipt_verified']); self.assertFalse(result['remote_ready'])
        self.assertFalse(result['confirm_rows_sent_to_observer'])

    def test_execute_missing_receipt_refuses_before_connection(self):
        with patch.object(o, 'one_bounded_ssh', side_effect=AssertionError('Network forbidden')):
            with self.assertRaisesRegex(o.ObservationError, 'exact receipt'): m.main(['--execute'])

    def test_request_rejects_other_host_traversal_and_missing_hash(self):
        good = o.BASES['103'] + '/launch-control/confirmation-' + c.PLAN_SHA + '-' + 'c'*32 + '.receipt.json'
        self.assertEqual(m.request(good, 'a'*64)['receipt_path'], good)
        for path, sha in [(good.replace('/data1/', '/data2/'), 'a'*64), (good.replace('/launch-control/', '/launch-control/../'), 'a'*64),
                          (good, None), (good, 'x'*64), (good.replace('confirmation-', 'manual-recovery-'), 'a'*64)]:
            with self.assertRaises(o.ObservationError): m.request(path, sha)

    def test_dependency_hash_and_bound_bootstrap(self):
        self.assertEqual(o.sha((HERE / 'observe_image_search.py').read_bytes()), m.OBSERVER_SHA)
        self.assertEqual(o.sha((HERE / 'continue_search_confirmation.py').read_bytes()), m.CONTINUATION_SHA)
        payload = {'server': '103', 'plan_sha256': c.PLAN_SHA, 'confirmation': None, 'public_plan': {}}
        program = m.remote_program(payload)
        ast.parse(program); self.assertLess(len(program.encode()), 200000)
        command = m.remote_command(payload); self.assertLess(len(command.encode()), 120000)
        bootstrap = shlex.split(command)[-1]; tree = ast.parse(bootstrap)
        encoded = tree.body[-1].value.args[0].args[0].args[0].value
        self.assertEqual(zlib.decompress(base64.b64decode(encoded)).decode(), program)
        self.assertNotIn('__remote__', program[-500:])


class ProvenanceChecks(unittest.TestCase):
    def test_new_claim_and_complete_old_chain_verified(self):
        with tempfile.TemporaryDirectory() as d, fixture(d) as f:
            capture = f.o.Capture(); rec, recovery = m.collect_provenance(f.base, f.run, f.wanted, capture)
            m.check_development_binding(f.run, rec)
            self.assertEqual(rec['pid'], 999998); self.assertEqual(recovery['pid'], 999999)
            self.assertEqual(recovery['budget']['failed_attempts'], 1)
            self.assertEqual(len(capture.files), 8)

    def test_raw_hash_tamper_refuses(self):
        with tempfile.TemporaryDirectory() as d, fixture(d) as f:
            Path(f.confirmation['receipt']).write_bytes(Path(f.confirmation['receipt']).read_bytes() + b' ')
            with self.assertRaisesRegex(f.o.ObservationError, 'missing or changed'):
                m.collect_provenance(f.base, f.run, f.wanted, f.o.Capture())

    def test_receipt_token_command_budget_and_claim_mismatch_refused(self):
        for field in ('confirmation_token', 'command', 'budget', 'claim'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as d, fixture(d) as f:
                rec = copy.deepcopy(f.confirmation)
                if field == 'confirmation_token': rec[field] = 'a'*32
                elif field == 'command': rec[field][-1] = 'dev'
                elif field == 'budget': rec['budget_decision']['archived_failed_attempts'] = 0
                else: rec['pid'] += 1; f.claim.write_text('{}')
                raw = json.dumps(rec).encode(); Path(rec['receipt']).write_bytes(raw)
                wanted = dict(f.wanted, receipt_sha256=f.o.sha(raw))
                with self.assertRaises(RuntimeError): m.collect_provenance(f.base, f.run, wanted, f.o.Capture())

    def test_old_failed_ledger_change_refused(self):
        with tempfile.TemporaryDirectory() as d, fixture(d) as f:
            f.ledgerpath.write_bytes(f.ledgerpath.read_bytes() + b' ')
            with self.assertRaisesRegex(f.o.ObservationError, 'Old recovery/failure'):
                m.collect_provenance(f.base, f.run, f.wanted, f.o.Capture())

    def test_changed_dev_selection_refuses_before_outcomes(self):
        with tempfile.TemporaryDirectory() as d, fixture(d) as f:
            f.envelope('dev_selection.json', {'selected': ['naive']})
            with self.assertRaisesRegex(f.o.ObservationError, 'Development selection'):
                m.check_development_binding(f.run, f.confirmation)


class ProcessChecks(unittest.TestCase):
    def test_new_PID_exact_identity_and_mismatch_states(self):
        with tempfile.TemporaryDirectory() as d, fixture(d) as f:
            proc = f.base / 'proc'; p = proc / str(f.confirmation['pid']); p.mkdir(parents=True)
            boot = proc / 'sys/kernel/random/boot_id'; boot.parent.mkdir(parents=True)
            boot.write_text(f.confirmation['boot_id'])
            def stat(tick): return str(f.confirmation['pid']) + ' (python) S ' + '0 '*18 + tick
            (p / 'stat').write_text(stat('600'))
            (p / 'cmdline').write_bytes(b'\0'.join(x.encode() for x in f.confirmation['command']) + b'\0')
            result = m.confirmation_process_snapshot(f.confirmation, proc)
            self.assertTrue(result['confirmation_process_identity_matches'])
            self.assertEqual(result['pid'], 999998)
            self.assertFalse((proc / '999999').exists())  # Old recovery absence cannot override new liveness.
            with patch.object(m, 'EXPECTED_UID', os.getuid() + 1):
                self.assertEqual(m.confirmation_process_snapshot(f.confirmation, proc)['status'], 'PID_now_belongs_to_different_UID')
            missing_ticks = dict(f.confirmation, process_start_ticks=None)
            self.assertFalse(m.confirmation_process_snapshot(missing_ticks, proc)['confirmation_process_identity_matches'])
            (p / 'cmdline').write_bytes(b'python\0other.py\0')
            self.assertFalse(m.confirmation_process_snapshot(f.confirmation, proc)['confirmation_process_identity_matches'])
            (p / 'cmdline').write_bytes(b'\0'.join(x.encode() for x in f.confirmation['command']) + b'\0')
            (p / 'stat').write_text(stat('601'))
            self.assertFalse(m.confirmation_process_snapshot(f.confirmation, proc)['confirmation_process_identity_matches'])
            boot.write_text('different-boot')
            self.assertEqual(m.confirmation_process_snapshot(f.confirmation, proc)['status'], 'recorded_confirmation_boot_no_longer_current')

    def test_missing_new_process_is_not_failure_or_replay(self):
        with tempfile.TemporaryDirectory() as d, fixture(d) as f:
            proc = f.base / 'proc'; boot = proc / 'sys/kernel/random/boot_id'; boot.parent.mkdir(parents=True)
            boot.write_text(f.confirmation['boot_id'])
            result = m.confirmation_process_snapshot(f.confirmation, proc)
            self.assertFalse(result['exists']); self.assertFalse(result['automatic_retry_allowed'])
            self.assertIn('outcome_requires_artifacts', result['status'])

    def test_permission_error_is_unknown(self):
        with tempfile.TemporaryDirectory() as d, fixture(d) as f:
            with patch.object(m, 'proc_read', side_effect=PermissionError('SIMULATED')):
                result = m.confirmation_process_snapshot(f.confirmation)
            self.assertIsNone(result['exists']); self.assertEqual(result['status'], 'confirmation_process_observation_unknown')


class IsolationAndBudgetChecks(unittest.TestCase):
    def exercise(self, unlock):
        with tempfile.TemporaryDirectory() as d, fixture(d) as f, ExitStack() as stack:
            # A receipt with known marker values is planted only in a temporary fixture.
            task = {'stage': 'confirm', 'candidate': 'clean', 'condition': {'id': 'SIMULATED'},
                    'row': {'id': 'SIMULATED'}, 'coefficients': [0, 0]}
            tid = f.o.digest(task)
            record = {'task_id': tid, 'stage': 'confirm', 'candidate': 'clean', 'image_path': 'images/confirm/SIMULATED.png',
                      'image_sha256': 'e'*64, 'score': {'ASR': 0.998877}}
            f.o.require(not list((f.run / 'operations').glob('*')), 'Fixture unexpectedly has operation files')
            (f.run / 'operations').mkdir(exist_ok=True)
            name = 'operations/' + tid + '.json'
            old_tests.write_json(f.run, name, {'task': task, 'task_id': tid, 'identity_sha256': c.IDENTITY_SHA,
                'status': 'completed', 'record': record, 'record_sha256': f.o.digest(record)})
            if unlock:
                selection = json.loads((f.run / 'dev_selection.json').read_text())['payload']
                f.envelope('confirm_binding.json', {'dev_selection_sha256': f.o.digest(selection),
                    'candidate_coefficients': {'clean': [0, 0], 'naive': f.public['candidates']['naive'], 'candidate': [.5, 1]}})
            real_safe_read = f.o.safe_read; reads = []
            def read(root, filename, *args):
                reads.append(filename)
                if not unlock and filename == name: raise AssertionError('Confirmation file opened before binding')
                return real_safe_read(root, filename, *args)
            stack.enter_context(patch.object(f.o, 'safe_read', side_effect=read))
            stack.enter_context(patch.object(m.pwd, 'getpwuid', return_value=SimpleNamespace(pw_name='zhangzibo')))
            stack.enter_context(patch.object(m, 'confirmation_process_snapshot', return_value={'pid': 999998,
                'exists': True, 'confirmation_process_identity_matches': True}))
            stack.enter_context(patch.object(f.o, 'runtime_snapshot', return_value={'gpus': [], 'GPU_query_succeeded': True}))
            result = m.collect_remote(f.payload)
            self.assertEqual(result['active_launch_source'], 'verified_confirmation_continuation')
            self.assertEqual(result['launch']['pid'], 999998)
            self.assertEqual(result['recovery']['pid'], 999999); self.assertTrue(result['recovery']['historical_only'])
            self.assertEqual(result['run']['confirm_unlocked'], unlock)
            self.assertEqual(name in reads, unlock)
            a = result['confirmation_resource_accounting']
            self.assertEqual(a['archived_failed_attempts'], 1)
            self.assertEqual(a['archived_failed_generation_branch_NFE_upper_bound'], 50)
            self.assertEqual(a['total_generation_attempts_observed_including_failure'], 2 if unlock else 1)
            self.assertEqual(a['complete_global_accounting'], unlock)
            serialized = json.dumps(result)
            if not unlock:
                self.assertNotIn('0.998877', serialized)
                self.assertNotIn('run/' + name, result['files'])
            else:
                self.assertIn('run/' + name, result['files'])
            self.assertTrue(any('preconfirmation receipt count' in x for x in result['errors']))
            return result

    def test_confirm_locked_receipt_and_log_do_not_leak(self): self.exercise(False)
    def test_valid_confirm_binding_unlocks_only_committed_run(self): self.exercise(True)

    def test_bad_provenance_opens_no_run_results(self):
        with tempfile.TemporaryDirectory() as d, fixture(d) as f, \
             patch.object(m.pwd, 'getpwuid', return_value=SimpleNamespace(pw_name='zhangzibo')), \
             patch.object(f.o, 'collect_run', side_effect=AssertionError('No outcome access')):
            f.claim.write_text('{}'); result = m.collect_remote(f.payload)
            self.assertEqual(result['run']['status'], 'withheld_until_confirmation_provenance_verified')
            self.assertFalse(result['run']['confirm_unlocked'])

    def test_original_path_size_and_transfer_guards_retained(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d).resolve(); (base / 'huge.json').write_bytes(b'x'*(o.MAX_OP_FILE+1))
            for name, limit in [('../escape', 100), ('huge.json', o.MAX_OP_FILE)]:
                with self.assertRaises(o.ObservationError): o.safe_read(base, name, limit)
            (base / 'link').symlink_to(base / 'huge.json')
            with self.assertRaises(OSError): o.safe_read(base, 'link')
            capture = o.Capture(); capture.total = o.MAX_TOTAL
            with self.assertRaises(o.ObservationError): capture.add('launch/test.json', b'{}')


if __name__ == '__main__': unittest.main(verbosity=2)
