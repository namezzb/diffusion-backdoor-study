"""CPU-only recovery checks. All modified records/images are SIMULATED in temp dirs."""
import ast
import copy
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location('manual_recovery', HERE / 'recover_interrupted_search.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
g = r.guards()
PLAN = json.loads((REPO / g.PLAN_REL).read_text())
OBS = HERE / 'observation_103_20261028T092715273013Z-3dd77842' / 'artifacts/run'


class LocalChecks(unittest.TestCase):
    def test_default_preparation_never_connects_or_spawns(self):
        with mock.patch.object(r.subprocess, 'run', side_effect=AssertionError('No child process allowed')), \
             mock.patch.object(r.subprocess, 'Popen', side_effect=AssertionError('No child process allowed')):
            payload = r.local_prepare(REPO)
        self.assertEqual(len(payload['completed']), 171)
        self.assertIsNone(payload['permission'])
        self.assertEqual(payload['budget']['until_dev_branch_NFE_upper_bound_including_failure'], 43250)

    def test_exact_original_command_adds_resume_and_stops_before_confirm(self):
        payload = r.local_prepare(REPO)
        base, code = Path(g.BASES['103']), Path(payload['code_root'])
        argv = r.command(base, code, base / 'results' / g.RUN_NAME)
        self.assertEqual(argv[-3:], ['--resume', '--until', 'dev'])
        self.assertEqual(argv.count('--resume'), 1)
        self.assertEqual(argv[argv.index('--scorer-device') + 1], 'cpu')
        self.assertEqual(g.runner_environment(base, r.GPU_UUID)['CUBLAS_WORKSPACE_CONFIG'], ':4096:8')

    def test_fixed_prefix_and_budget(self):
        prefix, pending = r.expected_prefix(PLAN)
        self.assertEqual(len(prefix), 171)
        self.assertEqual(r.digest(pending), r.PENDING)
        b = r.recovery_budget()
        self.assertLessEqual(b['until_dev_attempts_upper_bound'], b['global_attempt_cap_conservative'])
        self.assertFalse(b['confirmation_permitted_by_this_wrapper'])
        self.assertGreater(b['confirmation_total_if_search_promotes']['3']['branch_NFE_upper_bound'], 72000)

    def test_stale_permission_and_other_gpu_rejected(self):
        p = g.permission_template('103')
        p.update(observed_at=g.utcnow().isoformat(), sample_time_basis='live_UI_without_timestamp', sample_at=None,
                 live_indicator=True, historical_sample=False, account_status='normal', gpu_disabled=False,
                 server_maintenance=False, reservation_conflict=False, other_research_task=False, sample_valid=True,
                 gpu_index=0, gpu_uuid=r.GPU_UUID, own_gpu_count_all_servers=1,
                 pending_allocated_gpu_count_all_servers=0, effective_gpu_quota=4,
                 permission_kind='direct', direct_use_allowed=True, evidence_note='SIMULATED test three authenticated live views')
        r.validate_permission(p)
        p['gpu_index'] = 1
        with self.assertRaisesRegex(RuntimeError, 'fixed to the original'):
            r.validate_permission(p)
        p['gpu_index'] = 0
        p['observed_at'] = '2026-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(RuntimeError, 'stale'):
            r.validate_permission(p)

    def test_boot_or_pid_reuse_prevents_recovery(self):
        with mock.patch.object(Path, 'read_text', return_value='another-boot'):
            with self.assertRaisesRegex(RuntimeError, 'Boot changed'):
                r.check_boot_and_processes()
        with mock.patch.object(Path, 'read_text', return_value=r.BOOT_ID), \
             mock.patch.object(Path, 'exists', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'Original PID exists'):
                r.check_boot_and_processes()

    def test_python38_parsing_and_stdin_bootstrap_no_execution(self):
        source = (HERE / 'recover_interrupted_search.py').read_text()
        ast.parse(source, feature_version=(3, 8))
        payload = {'recovery_script_sha256': hashlib.sha256(source.encode()).hexdigest()}
        text = r.remote_program(source, (HERE / 'launch_image_search.py').read_text(), payload)
        ast.parse(text, feature_version=(3, 8))
        self.assertIn('remote_recover', text)


class ArchiveChecks(unittest.TestCase):
    def test_exact_bytes_preserved_and_second_archive_never_replaces(self):
        with tempfile.TemporaryDirectory(prefix='SIMULATED_recovery_archive_') as directory:
            base = Path(directory)
            source, archive = base / 'pending.json', base / 'archived.json'
            raw = b'{"status":"started","SIMULATED":true}\n'
            source.write_bytes(raw)
            sha = hashlib.sha256(raw).hexdigest()
            r.archive_exact_pending(source, archive, sha)
            self.assertEqual(archive.read_bytes(), raw)
            self.assertFalse(source.exists())
            source.write_bytes(raw)
            with self.assertRaises(FileExistsError):
                r.archive_exact_pending(source, archive, sha)
            self.assertTrue(source.exists())

    def test_directory_fsync_failure_keeps_original_pending(self):
        with tempfile.TemporaryDirectory(prefix='SIMULATED_recovery_fsync_') as directory:
            source, archive = Path(directory) / 'pending.json', Path(directory) / 'archive.json'
            source.write_bytes(b'SIMULATED receipt')
            sha = r.hash_file(source)
            with mock.patch.object(g, 'fsync_directory', side_effect=OSError('simulated fsync failure')):
                with self.assertRaises(OSError):
                    r.archive_exact_pending(source, archive, sha)
            self.assertEqual(r.hash_file(source), sha)

    def test_permanent_claim_is_exclusive_and_unchanged(self):
        with tempfile.TemporaryDirectory(prefix='SIMULATED_recovery_claim_') as directory:
            path = Path(directory) / 'claim.json'
            g.exclusive_json(path, {'SIMULATED': True, 'claimed': True})
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                g.exclusive_json(path, {'SIMULATED': True, 'claimed': False})
            self.assertEqual(path.read_bytes(), before)


class InventoryChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='SIMULATED_recovery_inventory_')
        cls.run_dir = Path(cls.temp.name).resolve() / 'run'
        (cls.run_dir / 'operations').mkdir(parents=True)
        shutil.copyfile(OBS / 'identity.json', cls.run_dir / 'identity.json')
        payload = r.local_prepare(REPO)
        cls.payload = copy.deepcopy(payload)
        # Use original scientific task structure, but explicitly synthetic image
        # bytes and rehashed receipts solely in the temporary test fixture.
        for tid, evidence in cls.payload['completed'].items():
            obj = json.loads((OBS / 'operations' / (tid + '.json')).read_text())
            image = cls.run_dir / evidence['image_path']
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(b'SIMULATED PNG byte-hash fixture ' + tid.encode())
            sha = r.hash_file(image)
            evidence['image_sha256'] = sha
            obj['record']['image_sha256'] = sha
            obj['record_sha256'] = r.digest(obj['record'])
            receipt_path = cls.run_dir / 'operations' / (tid + '.json')
            receipt_path.write_bytes(r.canonical(obj))
            evidence['receipt_sha256'] = r.hash_file(receipt_path)
        shutil.copyfile(OBS / 'operations' / (r.PENDING + '.json'), cls.run_dir / 'operations' / (r.PENDING + '.json'))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_171_png_receipts_and_pending_validate_without_mutation(self):
        before = {str(p.relative_to(self.run_dir)): r.hash_file(p) for p in self.run_dir.rglob('*') if p.is_file()}
        path, pending = r.verify_inventory(self.run_dir, PLAN, self.payload)
        self.assertEqual(pending['status'], 'started')
        self.assertEqual(path.stem, r.PENDING)
        after = {str(p.relative_to(self.run_dir)): r.hash_file(p) for p in self.run_dir.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_one_changed_completed_png_rejected(self):
        image = self.run_dir / next(iter(self.payload['completed'].values()))['image_path']
        raw = image.read_bytes()
        try:
            image.write_bytes(raw + b'corrupt')
            with self.assertRaisesRegex(RuntimeError, 'Prepared source changed'):
                r.verify_inventory(self.run_dir, PLAN, self.payload)
        finally:
            image.write_bytes(raw)

    def test_now_present_pending_png_rejected(self):
        image = self.run_dir / self.payload['original_pending']['image_path']
        try:
            image.write_bytes(b'SIMULATED pending PNG appeared')
            with self.assertRaisesRegex(RuntimeError, 'Pending PNG now exists'):
                r.verify_inventory(self.run_dir, PLAN, self.payload)
        finally:
            image.unlink()


class RemoteOrderChecks(unittest.TestCase):
    """SIMULATED host/GPU facts; actual temporary claims, archive, fsync, locks."""
    def exercise_remote(self, fail_archive=False):
        payload = r.local_prepare(REPO)
        payload.update(token='a' * 32, recovery_script_sha256=r.hash_file(HERE / 'recover_interrupted_search.py'),
                       permission={'SIMULATED': True}, permission_sha256='b' * 64)
        with tempfile.TemporaryDirectory(prefix='SIMULATED_recovery_remote_') as directory, ExitStack() as stack:
            base = Path(directory).resolve() / 'data'
            code, control = base / 'code', base / 'launch-control'
            run_dir = base / 'results' / g.RUN_NAME
            for rel in ('code', 'launch-control', 'venv/bin', 'tmp', 'cache/huggingface', 'cache/torch',
                        'cache/triton', 'models', 'results/' + g.RUN_NAME + '/operations'):
                (base / rel).mkdir(parents=True, exist_ok=True)
            python = base / 'venv/bin/python'
            python.write_text('SIMULATED executable placeholder; never executed')
            python.chmod(0o700)
            for path in (control / ('image-search-' + r.PLAN_SHA + '.lock'), run_dir / '.run.lock'):
                path.touch(mode=0o600)
            claim = control / (r.RECOVERY_NAME + '.claim.json')
            ledger_path = control / (r.RECOVERY_NAME + '.ledger.json')
            pending_path = run_dir / 'operations' / (r.PENDING + '.json')
            raw_pending = (OBS / 'operations' / (r.PENDING + '.json')).read_bytes()
            pending_path.write_bytes(raw_pending)
            for i in range(171):
                (run_dir / 'operations' / ('SIMULATED_%03d.json' % i)).write_text('{}')
            original_claim = control / ('image-search-' + r.PLAN_SHA + '.claim.json')
            original_claim.write_text('SIMULATED immutable old claim')
            old_bytes = original_claim.read_bytes()
            receipt_path = control / 'original.receipt.json'
            old_spawn = {'pid': r.OLD_PID, 'launch_token': r.OLD_TOKEN,
                         'gpu': {'uuid': r.GPU_UUID, 'driver': '550.54.14'}}
            payload.update(code_root=str(code), expected_files={}, old_remote_spawn={'launch_receipt': str(receipt_path)})
            events = []
            real_stat, real_write, real_archive = Path.stat, g.exclusive_json, r.archive_exact_pending

            def simulated_stat(path, *args, **kwargs):
                result = real_stat(path, *args, **kwargs)
                if path == base:
                    values = list(result)
                    values[2] += 1  # SIMULATED different device, no actual mount/SSH.
                    return os.stat_result(values)
                return result

            def fixed_evidence(path, sha):
                if path == code / g.PLAN_REL:
                    return PLAN
                if path == original_claim:
                    self.assertEqual(path.read_bytes(), old_bytes)
                    return {'SIMULATED': True}
                if path == receipt_path:
                    return old_spawn
                self.fail('Unexpected fixed evidence read: ' + str(path))

            def write(path, obj):
                real_write(path, obj)
                if path in (claim, ledger_path):
                    events.append('claim' if path == claim else 'ledger')

            def archive(source, target, sha):
                self.assertEqual(events, ['claim', 'ledger'])
                self.assertEqual(claim.read_bytes(), ledger_path.read_bytes())
                self.assertEqual(source.read_bytes(), raw_pending)
                events.append('archive')
                if fail_archive:
                    raise OSError('SIMULATED archival fault')
                real_archive(source, target, sha)

            def spawn(argv, **kwargs):
                self.assertEqual(events, ['claim', 'ledger', 'archive'])
                self.assertFalse(pending_path.exists())
                self.assertEqual(len(list((run_dir / 'operations').glob('*.json'))), 171)
                self.assertEqual(argv[-3:], ['--resume', '--until', 'dev'])
                self.assertEqual(kwargs['env']['CUDA_VISIBLE_DEVICES'], r.GPU_UUID)
                # The original runner can acquire the run lock; outer control
                # lock and permanent claims remain held by the wrapper.
                with (run_dir / '.run.lock').open('r+') as available:
                    r.fcntl.flock(available, r.fcntl.LOCK_EX | r.fcntl.LOCK_NB)
                events.append('spawn')
                return SimpleNamespace(pid=99999999)

            for target, name, value in (
                (r.platform, 'system', lambda: 'Linux'), (r.platform, 'machine', lambda: 'x86_64'),
                (r.pwd, 'getpwuid', lambda uid: SimpleNamespace(pw_name='zhangzibo')),
                (Path, 'stat', simulated_stat), (r, 'fixed_file', fixed_evidence),
                (g, 'validate_deployment', lambda *a: (str(code), {})),
                (r, 'validate_permission', lambda *a: None),
                (r, 'check_boot_and_processes', lambda: None),
                (r, 'verify_inventory', lambda *a: (pending_path, json.loads(raw_pending))),
                (g, 'exclusive_json', write), (r, 'archive_exact_pending', archive),
                (g, 'inspect_gpu', lambda *a, **k: {'uuid': r.GPU_UUID, 'index': 0, 'driver': '595.99.02'}),
                (r.subprocess, 'run', lambda argv, **k: SimpleNamespace(stdout='SIMULATED XML')),
                (r.subprocess, 'Popen', spawn)):
                stack.enter_context(mock.patch.object(target, name, value))
            stack.enter_context(mock.patch.dict(g.BASES, {'103': str(base)}))
            if fail_archive:
                with self.assertRaisesRegex(OSError, 'SIMULATED archival fault'):
                    r.remote_recover(payload)
                self.assertEqual(events, ['claim', 'ledger', 'archive'])
                self.assertTrue(pending_path.exists())
                self.assertTrue(claim.exists())
                self.assertFalse(list(control.glob('*.receipt.json')))
                with self.assertRaisesRegex(RuntimeError, 'claim exists'):
                    r.remote_recover(payload)
            else:
                result = r.remote_recover(payload)
                self.assertEqual(events, ['claim', 'ledger', 'archive', 'spawn'])
                self.assertEqual(result['status'], 'runner_process_spawned_not_GPU_acceptance')
                self.assertIsNone(result['process_start_ticks'])
                self.assertFalse(result['spawned_process_identity_observed'])
                self.assertEqual(result['archive_sha256'], r.PENDING_SHA)
                self.assertEqual(json.loads(ledger_path.read_text())['run_root'], str(run_dir))
            self.assertEqual(original_claim.read_bytes(), old_bytes)

    def test_claim_ledger_archive_before_spawn_with_original_claim_preserved(self):
        self.exercise_remote()

    def test_archive_failure_leaves_claim_and_never_spawns_or_retries(self):
        self.exercise_remote(fail_archive=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
