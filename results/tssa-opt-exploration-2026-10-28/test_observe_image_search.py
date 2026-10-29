"""Local observation fixtures only: no SSH, GPU, models, or scientific samples."""
import base64
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('observer', HERE / 'observe_image_search.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def write_json(root, name, payload):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload))


def fixture(root):
    condition = {'id': 'Edev_0.25', 'kind': 'merge', 'alpha': 0.25}
    row = {'id': 'normal', 'prompt': 'a dog', 'normal_prompt': 'a dog', 'triggered': False, 'seed': 123}
    public = {'candidates': {'naive': [1, 1], 'candidate': [0.5, 1]},
              'stages': {s: {'conditions': [condition], 'rows': [dict(row, id=s + '_normal')]} for s in ('search', 'dev')}}
    identity = {'plan_sha256': m.PLAN_SHA, 'max_images': m.MAX_IMAGES}
    write_json(root, 'identity.json', identity)
    def commit(name, payload):
        write_json(root, name, {'payload': payload, 'sha256': m.digest(payload), 'identity_sha256': m.digest(identity)})
    def operation(stage='search', complete=True):
        task = {'stage': stage, 'candidate': 'clean', 'condition': condition,
                'row': public['stages'].get(stage, {'rows': [row]})['rows'][0], 'coefficients': [0, 0]}
        task_id = m.digest(task)
        receipt = {'task_id': task_id, 'identity_sha256': m.digest(identity), 'task': task,
                   'status': 'completed' if complete else 'started', 'started_at': '2026-10-28T00:00:00+00:00'}
        if complete:
            record = dict(task_id=task_id, stage=stage, candidate='clean', image_path='images/' + stage + '/not-downloaded.png',
                          image_sha256='b'*64, score={'vit_class': 1, 'clip_score': 2})
            receipt.update(record=record, record_sha256=m.digest(record), completed_at='2026-10-28T00:01:00+00:00')
        name = 'operations/' + task_id + '.json'
        write_json(root, name, receipt)
        return name
    return public, commit, operation


@contextlib.contextmanager
def recovery_fixture(base):
    """Synthetic provenance files only; hash constants patched only in this fixture."""
    run = base / 'results' / m.RUN_NAME
    run.mkdir(parents=True)
    public, commit, operation = fixture(run)
    pending_name = operation(complete=False)
    pending_raw = (run / pending_name).read_bytes()
    pending = json.loads(pending_raw)
    (run / pending_name).unlink()  # Mirrors the audited archival, in a temporary fixture only.
    name = 'manual-recovery-' + pending['task_id']
    control = base / 'launch-control'
    control.mkdir()
    oldtoken, token = 'a'*32, 'b'*32
    oldstem = '20261028T000000Z-' + oldtoken
    oldreceiptpath = control / (oldstem + '.receipt.json')
    old = {'server': '103', 'plan_sha256': m.PLAN_SHA, 'run_root': str(run), 'launch_token': oldtoken,
           'launch_receipt': str(oldreceiptpath), 'log': str(control / (oldstem + '.log')),
           'pid': 188034, 'status': 'runner_process_spawned_not_GPU_acceptance', 'gpu': {'uuid': m.RECOVERY_GPU_UUID}}
    old_claim_raw = json.dumps(dict(old, status='claimed')).encode()
    old_receipt_raw = json.dumps(old).encode()
    (control / ('image-search-' + m.PLAN_SHA + '.claim.json')).write_bytes(old_claim_raw)
    oldreceiptpath.write_bytes(old_receipt_raw)
    Path(old['log']).write_text('RuntimeError: historic interrupted fixture\n')
    archive = control / (name + '.original-started.json')
    archive.write_bytes(pending_raw)
    ledgerpath = control / (name + '.ledger.json')
    receiptpath = control / (name + '-' + token + '.receipt.json')
    budget = {'failed_attempts': 1, 'failed_branch_NFE_upper_bound': 50,
              'failed_text_encoder_forwards_upper_bound': 1, 'failed_VAE_decodes_upper_bound': 1,
              'failed_work_exact_count': None, 'global_attempt_cap_conservative': 1440,
              'global_branch_NFE_cap': 72000, 'until_dev_attempts_upper_bound': 865,
              'until_dev_branch_NFE_upper_bound_including_failure': 43250,
              'confirmation_permitted_by_this_wrapper': False, 'later_confirmation_requires_separate_budget_audit': True}
    ih = m.digest(json.loads((run / 'identity.json').read_bytes()))
    ledger = {'server': '103', 'run_root': str(run), 'plan_sha256': m.PLAN_SHA, 'identity_sha256': ih,
              'recovery_token': token, 'old_pid': 188034,
              'boot_id': '1c2bddf4-f594-43cf-8a4d-5b116ad79067',
              'original_claim_sha256': m.sha(old_claim_raw), 'original_spawn_receipt_sha256': m.sha(old_receipt_raw),
              'pending_task_id': pending['task_id'], 'original_pending_sha256': m.sha(pending_raw),
              'original_pending_receipt': pending, 'archived_original_receipt': str(archive),
              'recovery_gpu': {'index': 0, 'uuid': m.RECOVERY_GPU_UUID}, 'budget': budget,
              'command': ['python', 'runner.py', '--run-root', str(run), '--resume', '--until', 'dev'],
              'receipt': str(receiptpath), 'log': str(control / (name + '-' + token + '.log')),
              'status': 'recovery_claimed_before_pending_archive', 'automatic_retry_allowed': False,
              'original_science_manifest_and_source_unchanged': True}
    ledgerraw = json.dumps(ledger).encode()
    ledgerpath.write_bytes(ledgerraw)
    (control / (name + '.claim.json')).write_bytes(ledgerraw)
    rec = dict(ledger, pid=999999, started_at='2026-10-28T10:00:00+00:00', process_start_ticks='12345',
               spawned_process_identity_observed=True, archive_sha256=m.sha(pending_raw),
               recovery_ledger=str(ledgerpath), recovery_ledger_sha256=m.sha(ledgerraw),
               status='runner_process_spawned_not_GPU_acceptance')
    raw = json.dumps(rec).encode()
    receiptpath.write_bytes(raw)
    Path(rec['log']).write_text('RuntimeError: recovery diagnostic fixture\n{"stage":"confirm","ASR":0.777777}\n')
    updates = dict(RECOVERY_PENDING=pending['task_id'], RECOVERY_NAME=name, RECOVERY_PENDING_SHA=m.sha(pending_raw),
                   RECOVERY_IDENTITY_SHA=ih, RECOVERY_OLD_CLAIM_SHA=m.sha(old_claim_raw),
                   RECOVERY_OLD_RECEIPT_SHA=m.sha(old_receipt_raw), BASES=dict(m.BASES, **{'103': str(base)}))
    with patch.multiple(m, **updates):
        yield SimpleNamespace(base=base, run=run, public=public, receipt=rec,
                              request={'receipt_path': str(receiptpath), 'receipt_sha256': m.sha(raw)},
                              old_claim_raw=old_claim_raw, old_receipt_raw=old_receipt_raw,
                              ledgerpath=ledgerpath, archive=archive)


class ObservationChecks(unittest.TestCase):
    def test_actual_recovery_wrapper_simulated_output_matches_observer(self):
        """Execute the wrapper's existing full CPU simulation, then read its exact files."""
        spec = importlib.util.spec_from_file_location('recovery_integration_fixture', HERE / 'test_recover_interrupted_search.py')
        integration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(integration)
        actual_remote = integration.r.remote_recover
        provenance = HERE / 'observation_103_20261028T090936713940Z-5f77ac6c/artifacts'
        old_claim_raw = (provenance / 'launch' / ('image-search-' + m.PLAN_SHA + '.claim.json')).read_bytes()
        old_receipt_raw = (provenance / 'launch/20261028T085903540293Z-a30eabe75cc0446cbdb059151c056892.receipt.json').read_bytes()
        verified = []

        def inspect_generated(payload):
            result = actual_remote(payload)  # Actual wrapper; fixture mocks only host/spawn facts.
            run = Path(result['run_root'])
            (run / 'identity.json').write_bytes((provenance / 'run/identity.json').read_bytes())
            raw = Path(result['receipt']).read_bytes()
            request = {'receipt_path': result['receipt'], 'receipt_sha256': m.sha(raw)}
            capture = m.Capture()
            verified.append(m.collect_recovery(run.parent.parent, run, request, old_claim_raw, old_receipt_raw, capture))
            self.assertEqual(len(capture.files), 4)
            self.assertEqual(verified[-1], result)
            return result

        case = integration.RemoteOrderChecks('test_claim_ledger_archive_before_spawn_with_original_claim_preserved')
        with patch.object(integration.r, 'remote_recover', side_effect=inspect_generated):
            case.exercise_remote()
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0]['budget']['failed_attempts'], 1)
        self.assertEqual(verified[0]['budget']['failed_branch_NFE_upper_bound'], 50)

    def test_recovery_provenance_and_archived_attempt_are_transferred(self):
        with tempfile.TemporaryDirectory() as d, recovery_fixture(Path(d).resolve()) as f:
            capture = m.Capture()
            rec = m.collect_recovery(f.base, f.run, f.request, f.old_claim_raw, f.old_receipt_raw, capture)
            self.assertEqual(rec['pid'], 999999)
            self.assertEqual(len(capture.files), 4)
            self.assertIn('recovery/' + f.archive.name, capture.files)
            self.assertEqual(base64.b64decode(capture.files['recovery/' + f.archive.name]['base64']), f.archive.read_bytes())

    def test_recovery_wrong_run_uuid_ledger_or_archive_rejected(self):
        for changed in ('run_root', 'uuid', 'ledger', 'archive', 'receipt_hash'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as d, recovery_fixture(Path(d).resolve()) as f:
                if changed in ('run_root', 'uuid'):
                    rec = copy.deepcopy(f.receipt)
                    if changed == 'run_root': rec['run_root'] += '-wrong'
                    else: rec['recovery_gpu']['uuid'] = 'GPU-wrong'
                    raw = json.dumps(rec).encode()
                    Path(f.request['receipt_path']).write_bytes(raw)
                    f.request['receipt_sha256'] = m.sha(raw)
                elif changed == 'ledger': f.ledgerpath.write_bytes(f.ledgerpath.read_bytes()+b' ')
                elif changed == 'archive': f.archive.write_bytes(b'{}')
                else: f.request['receipt_sha256'] = '0'*64
                with self.assertRaises(m.ObservationError):
                    m.collect_recovery(f.base, f.run, f.request, f.old_claim_raw, f.old_receipt_raw, m.Capture())

    def test_recovery_process_uses_new_PID_boot_and_start_ticks(self):
        receipt = {'pid': 999999, 'boot_id': 'new-boot-fixture', 'process_start_ticks': '12345'}
        good = {'pid': 999999, 'exists': True, 'owner_is_self': True, 'matches_fixed_run': True, 'start_ticks': '12345'}
        for boot, ticks, expected in [('new-boot-fixture', '12345', True), ('later-reboot', '12345', False), ('new-boot-fixture', '54321', False)]:
            with patch.object(m, 'process_snapshot', return_value=dict(good, start_ticks=ticks)) as snapshot, patch.object(m.Path, 'read_text', return_value=boot):
                got = m.recovery_process_snapshot(receipt, Path('/run-fixture'))
            self.assertEqual(got['recovery_process_identity_matches'], expected)
            snapshot.assert_called_once_with(999999, Path('/run-fixture'))

    def test_failed_attempt_is_counted_and_can_exhaust_global_budget(self):
        rec = {'budget': {'failed_attempts': 1}}
        for complete, attempts in [(171, 172), (1439, 1440), (1440, 1441)]:
            snap = {'completed_images_observed': complete, 'operations': [{}]*complete,
                    'locked_or_unknown_operation_files_not_read': []}
            got = m.recovery_accounting(snap, rec)
            self.assertEqual(got['total_generation_attempts_observed_including_failure'], attempts)
            self.assertEqual(got['known_attempts_generation_branch_NFE_upper_bound_including_failure'], attempts*50)
            self.assertEqual(got['observed_counts_within_global_caps'], attempts <= 1440)
            self.assertEqual(got['archived_failed_generation_branch_NFE_upper_bound'], 50)
        snap['locked_or_unknown_operation_files_not_read'] = ['withheld.json']
        self.assertFalse(m.recovery_accounting(snap, rec)['complete_global_accounting'])

    def test_recovery_remote_observation_keeps_old_PID_historical_and_new_log_filtered(self):
        with tempfile.TemporaryDirectory() as d, recovery_fixture(Path(d).resolve()) as f:
            runtime = {'GPU_query_succeeded': True, 'gpus': [{'uuid': m.RECOVERY_GPU_UUID}], 'active_project_processes': [{'pid': 999999}]}
            def proc(pid, run):
                return {'pid': pid, 'exists': pid == 999999, 'matches_fixed_run': pid == 999999, 'owner_is_self': True, 'start_ticks': '12345'}
            with patch.object(m.pwd, 'getpwuid', return_value=SimpleNamespace(pw_name='zhangzibo')), \
                 patch.object(m, 'runtime_snapshot', return_value=runtime), patch.object(m, 'process_snapshot', side_effect=proc), \
                 patch.object(m, 'recovery_process_snapshot', return_value=dict(proc(999999, f.run), recovery_process_identity_matches=True)):
                result = m.collect_remote({'server': '103', 'plan_sha256': m.PLAN_SHA, 'public_plan': f.public, 'recovery': f.request})
            self.assertEqual(result['errors'], [])
            self.assertEqual(result['launch']['pid'], 999999)
            self.assertEqual(result['original_launch']['pid'], 188034)
            self.assertFalse(result['original_launch_process_now']['exists'])
            self.assertTrue(result['original_launch_process_now']['historical_only'])
            self.assertTrue(result['launch_process_now']['exists'])
            self.assertEqual(result['active_launch_source'], 'verified_manual_recovery')
            self.assertIn('recovery diagnostic', result['log_tail']['text'])
            self.assertNotIn('0.777777', result['log_tail']['text'])
            self.assertIn('historic interrupted', result['original_log_tail']['text'])
            self.assertEqual(result['recovery_resource_accounting']['archived_failed_attempts'], 1)

    def test_recovery_opt_in_is_bounded_and_default_never_connects(self):
        path = m.BASES['103'] + '/launch-control/' + m.RECOVERY_NAME + '-' + 'b'*32 + '.receipt.json'
        for args in [('104', path, 'a'*64), ('103', path, None), ('103', '/tmp/fake', 'a'*64)]:
            with self.assertRaises(m.ObservationError): m.recovery_request(*args)
        self.assertIsNone(m.recovery_request('103', None, None))
        with patch.object(m.subprocess, 'Popen', side_effect=AssertionError('No SSH')), patch.object(m.subprocess, 'run', side_effect=AssertionError('No subprocess')), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(m.main(['--server','103','--recovery-receipt',path,'--recovery-receipt-sha256','a'*64]),0)
        self.assertEqual(json.loads(out.getvalue())['recovery_observation']['receipt_path'], path)

    def test_nvml_mismatch_preserves_process_without_implying_free_gpu(self):
        process = {'pid': 919191, 'matches_fixed_run': True, 'exists': True}
        proc = SimpleNamespace(name='919191', stat=lambda: SimpleNamespace(st_uid=m.os.getuid()))
        failure = SimpleNamespace(returncode=18, stdout=b'Failed to initialize NVML: Driver/library version mismatch\nNVML library version: 595.99\n', stderr=b'')
        with patch.object(m.Path, 'iterdir', return_value=[proc]), patch.object(m, 'process_snapshot', return_value=process), patch.object(m.subprocess, 'run', return_value=failure):
            result = m.runtime_snapshot(Path('/test/run'))
        self.assertEqual(result['active_project_processes'], [process])
        self.assertIsNone(result['gpus'])
        self.assertIsNone(result['own_gpu_uuids_observed'])
        self.assertFalse(result['GPU_query_succeeded'])
        self.assertEqual(result['query_error']['returncode'], 18)
        self.assertIn('version mismatch', result['query_error']['stdout_excerpt'])

    def test_gpu_query_timeout_is_unknown_not_empty_capacity(self):
        with patch.object(m.Path, 'iterdir', return_value=[]), patch.object(m.subprocess, 'run', side_effect=m.subprocess.TimeoutExpired('nvidia-smi', 20)):
            result = m.runtime_snapshot(Path('/test/run'))
        self.assertFalse(result['GPU_query_succeeded'])
        self.assertIsNone(result['gpus'])
        self.assertEqual(result['query_error']['kind'], 'timeout')

    def test_locked_confirmation_is_never_opened(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            public, commit, operation = fixture(root)
            search = operation()
            hidden = operation('confirm')
            (root / hidden).write_text('unreadable locked result fixture')
            (root / 'confirm_summary.json').write_text('unreadable locked result fixture')
            (root / 'final_report.json').write_text('unreadable premature final fixture')
            capture = m.Capture()
            result = m.collect_run(root, public, capture)
            self.assertFalse(result['confirm_unlocked'])
            self.assertEqual(result['completed_images_observed'], 1)
            self.assertEqual(result['locked_or_unknown_operation_files_not_read'], [Path(hidden).name])
            self.assertIn('run/' + search, capture.files)
            self.assertNotIn('run/' + hidden, capture.files)
            self.assertNotIn('run/confirm_summary.json', capture.files)
            self.assertNotIn('run/final_report.json', capture.files)
            self.assertFalse(result['image_bytes_read_or_verified'])

    def test_unlocked_confirmation_requires_frozen_development_and_preserves_started(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            public, commit, operation = fixture(root)
            summary = {'stage': 'dev', 'ranked_eligible': ['candidate']}
            selection = {'selected': ['candidate'], 'summary_sha256': m.digest(summary)}
            commit('dev_summary.json', summary)
            commit('dev_selection.json', selection)
            commit('confirm_binding.json', {'dev_selection_sha256': m.digest(selection),
                   'candidate_coefficients': {'clean': [0, 0], **public['candidates']}})
            confirm = operation('confirm', complete=False)
            capture = m.Capture()
            result = m.collect_run(root, public, capture)
            self.assertTrue(result['confirm_unlocked'])
            self.assertEqual(result['stage_operation_counts']['confirm'], {'started': 1})
            self.assertEqual(result['completed_images_observed'], 0)
            self.assertIn('run/' + confirm, capture.files)
            self.assertEqual(len(result['incomplete_operations']), 1)

    def test_wrong_confirmation_binding_stops_before_result_access(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            public, commit, operation = fixture(root)
            summary = {'stage': 'dev'}
            selection = {'selected': ['candidate'], 'summary_sha256': m.digest(summary)}
            commit('dev_summary.json', summary)
            commit('dev_selection.json', selection)
            commit('confirm_binding.json', {'dev_selection_sha256': '0'*64, 'candidate_coefficients': {}})
            (root / 'confirm_summary.json').write_text('never open')
            with self.assertRaisesRegex(m.ObservationError, 'Confirmation binding'):
                m.collect_run(root, public, m.Capture())

    def test_transfer_hash_and_path_validation_precedes_any_file_creation(self):
        with tempfile.TemporaryDirectory() as d:
            raw = b'{"sample":1}'
            result = {'server': '104', 'plan_sha256': m.PLAN_SHA,
                      'run_root': m.BASES['104'] + '/results/' + m.RUN_NAME,
                      'files': {'run/progress.json': {'size': len(raw), 'sha256': m.sha(raw), 'base64': base64.b64encode(raw).decode()}}}
            for kind in ('hash', 'path'):
                value = copy.deepcopy(result)
                if kind == 'hash': value['files']['run/progress.json']['sha256'] = '0'*64
                else: value['files']['../escape.json'] = value['files'].pop('run/progress.json')
                out = Path(d) / kind
                with self.assertRaises(m.ObservationError): m.save_bundle(value, out)
                self.assertFalse(out.exists())
            out = Path(d) / 'valid'
            m.save_bundle(result, out)
            self.assertEqual((out / 'artifacts/run/progress.json').read_bytes(), raw)
            self.assertEqual(m.sha((out / 'artifacts/run/progress.json').read_bytes()), result['files']['run/progress.json']['sha256'])

    def test_symlink_and_excessive_receipt_count_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root / 'secret').write_text('do not read through link')
            (root / 'redirect.json').symlink_to(root / 'secret')
            with self.assertRaises(OSError): m.safe_read(root, 'redirect.json')
            (root / 'operations').mkdir()
            for i in range(3): (root / 'operations' / (str(i) + '.json')).write_text('{}')
            with self.assertRaisesRegex(m.ObservationError, 'count exceeds'): m.names_in(root, 'operations', 2)


    def test_large_log_is_bounded_and_filters_locked_confirmation_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root / 'launch-control').mkdir()
            event = dict(at='2026-10-28T00:00:00+00:00', stage='search', images=624,
                         selected=['candidate'], reason='eligible_candidates')
            raw = (b'x' * 256000 + b'\nTraceback (most recent call last):\n'
                   b'  File "/data1/example.py", line 5, in main\n'
                   b'ModuleNotFoundError: No module named diffusers\n' + json.dumps(event).encode() + b'\n'
                   b'{"stage":"confirm","macro_ASR":0.987654321}\n'
                   b'{\n  "stopped_after": "confirm",\n  "macro_ASR": 0.987654321\n}\n'
                   b'ValueError: macro_asr=0.987654321\n')
            (root / 'launch-control/sample.log').write_bytes(raw)
            tail = m.read_log_tail(root, 'launch-control/sample.log', False)
            self.assertEqual(tail['source_tail_size'], m.MAX_LOG_TAIL)
            self.assertEqual(tail['source_tail_offset'], len(raw) - m.MAX_LOG_TAIL)
            self.assertEqual(tail['source_tail_sha256'], m.sha(raw[-m.MAX_LOG_TAIL:]))
            self.assertIn('ModuleNotFoundError', tail['text'])
            self.assertIn('"stage": "search"', tail['text'])
            self.assertNotIn('0.987654321', tail['text'])
            self.assertNotIn('confirm', tail['text'])
            self.assertFalse(tail['full_log'])
            self.assertEqual(tail['returned_utf8_sha256'], m.sha(tail['text'].encode()))

    def test_only_exact_committed_log_path_and_owned_nonsymlink_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            control = root / 'launch-control'
            control.mkdir()
            token = 'a' * 32
            stem = '20261028T010000Z-' + token
            launch = {'launch_token': token, 'launch_receipt': str(control / (stem + '.receipt.json')),
                      'log': str(control / (stem + '.log'))}
            self.assertEqual(m.verified_log_name(root, launch), 'launch-control/' + stem + '.log')
            for wrong in (str(root / 'secret.log'), str(control / 'different.log')):
                with self.assertRaises(m.ObservationError): m.verified_log_name(root, dict(launch, log=wrong))
            secret = root / 'secret.log'
            secret.write_text('secret')
            (control / (stem + '.log')).symlink_to(secret)
            with self.assertRaises(OSError): m.read_log_tail(root, 'launch-control/' + stem + '.log', True)
            (control / (stem + '.log')).unlink()
            (control / (stem + '.log')).write_text('own log')
            with patch.object(m.os, 'getuid', return_value=m.os.getuid() + 1):
                with self.assertRaises(m.ObservationError): m.read_log_tail(root, 'launch-control/' + stem + '.log', True)

    def test_unlocked_tail_preserves_scoring_text_and_hashes_returned_utf8(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root / 'launch-control').mkdir()
            raw = b'\xff{"stage":"confirm","ASR":0.5}\n'
            (root / 'launch-control/sample.log').write_bytes(raw)
            tail = m.read_log_tail(root, 'launch-control/sample.log', True)
            self.assertIn('"ASR":0.5', tail['text'])
            self.assertEqual(tail['source_tail_sha256'], m.sha(raw))
            self.assertEqual(tail['returned_utf8_sha256'], m.sha(tail['text'].encode()))
            self.assertEqual(tail['returned_utf8_size'], len(tail['text'].encode()))

    def test_default_cli_performs_no_connection_or_subprocess(self):
        for server in ('103', '104'):
            with patch.object(m.subprocess, 'Popen', side_effect=AssertionError('No SSH')), patch.object(m.subprocess, 'run', side_effect=AssertionError('No subprocess')), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(m.main(['--server', server]), 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report['status'], 'prepared_locally_no_connection')
            self.assertFalse(report['confirm_rows_sent_to_observer'])
            self.assertIn(m.BASES[server], report['run_root'])


if __name__ == '__main__':
    unittest.main()
