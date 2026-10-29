"""CPU tests using explicitly SIMULATED images/host facts in temporary folders."""
import ast
import copy
from contextlib import ExitStack, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('confirmation', HERE / 'continue_search_confirmation.py')
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
g = c.guards()
PLAN = json.loads((ROOT / g.PLAN_REL).read_text())
RUNNER_PATH = ROOT / 'scripts/merging/tssa_image_search_run.py'
runner = c.load_module(RUNNER_PATH, PLAN['source_hashes']['tssa_image_search_run.py'])
gate = c.load_module(HERE / 'check_confirmation_budget.py', c.GATE_SHA)
OBSERVATION = HERE / 'observation_103_20261028T100953718980Z-b87b404b/report.json'


def permission(index=1):
    p = g.permission_template('103')
    p.update(observed_at=g.utcnow().isoformat(), sample_time_basis='live_UI_without_timestamp', sample_at=None,
             live_indicator=True, historical_sample=False, account_status='normal', gpu_disabled=False,
             server_maintenance=False, reservation_conflict=False, other_research_task=False, sample_valid=True,
             gpu_index=index, gpu_uuid='GPU-11111111-2222-3333-4444-555555555555', own_gpu_count_all_servers=0,
             pending_allocated_gpu_count_all_servers=0, effective_gpu_quota=4,
             permission_kind='direct', direct_use_allowed=True, evidence_note='SIMULATED three live authenticated views')
    return p


def envelope(run, name, payload):
    (run / name).write_bytes(c.canonical({'identity_sha256': c.IDENTITY_SHA,
                                         'sha256': c.digest(payload), 'payload': payload}))


def fixture(run, k=2):
    """Frozen task layout, but synthetic PNG bytes/scores; never scientific output."""
    (run / 'operations').mkdir(parents=True)
    shutil.copyfile(OBSERVATION.parent / 'artifacts/run/identity.json', run / 'identity.json')
    envelope(run, 'plan.json', PLAN)
    qualified = {'uniform_075', 'a075_b100', 'a125_b100'}
    qualified = set(sorted(qualified, key=lambda n: (sum(x*x for x in PLAN['candidates'][n]), n))[:k])
    names, total, stages = ['clean'] + list(PLAN['candidates']), 0, {}
    for stage in ('search', 'dev'):
        records = []
        for condition in PLAN['stages'][stage]['conditions']:
            for name in names:
                for row in PLAN['stages'][stage]['rows']:
                    task = {'stage': stage, 'candidate': name, 'condition': condition, 'row': row,
                            'coefficients': [0, 0] if name == 'clean' else PLAN['candidates'][name]}
                    tid = c.digest(task); total += 1
                    image = 'images/{}/{}/{}/{}.png'.format(stage, condition['id'], name, row['id'])
                    p = run / image; p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b'SIMULATED PNG hash-only fixture ' + tid.encode())
                    if row['triggered']:
                        label = 281 if name in qualified else 151
                    else:
                        label = row['expected_class_ids'][0] if name in qualified | {'clean', 'naive'} else 0
                    record = {'task_id': tid, 'stage': stage, 'candidate': name, 'condition_id': condition['id'],
                              'row': row, 'coefficients': task['coefficients'], 'image_path': image,
                              'image_sha256': c.sha(p), 'score': {'vit_class': label, 'clip_score': 80.0},
                              'seconds': .5, 'execution_id': '20261028T120000000000Z',
                              'resources_current_process': {'optimizer_updates': 0, 'autograd_calls': 0,
                                  'branch_nfe': {'full_generation': total * 50}}}
                    receipt = {'task_id': tid, 'task': task, 'identity_sha256': c.IDENTITY_SHA, 'status': 'completed',
                               'started_at': '2026-10-28T12:00:00+00:00', 'completed_at': '2026-10-28T12:00:01+00:00',
                               'record': record, 'record_sha256': c.digest(record)}
                    (run / 'operations' / (tid + '.json')).write_bytes(c.canonical(receipt)); records.append(record)
        summary = runner.summarize(PLAN, stage, names, records)
        selected = runner.select(PLAN, stage, summary)
        envelope(run, stage + '_summary.json', summary); envelope(run, stage + '_selection.json', selected)
        stages[stage] = {'status': 'complete', 'selection_verified': True,
                         'completed_images': len(records), 'selection': selected}
        names = ['clean', 'naive'] + selected['selected']
    audit = {'status': 'partial', 'errors': [], 'plan_sha256': c.PLAN_SHA, 'confirm_results_opened': False,
             'locked_operation_ids_not_read': [], 'completed_receipts_verified': total, 'started_receipts_verified': 0,
             'attempt_files_present': total, 'last_recorded_NFE_per_execution': {'SIMULATED': total * 50}, 'stages': stages}
    failed = {'failed_attempts': 1, 'failed_branch_NFE_upper_bound': 50,
              'global_attempt_cap_conservative': 1440, 'global_branch_NFE_cap': 72000}
    decision = gate.decide(audit, failed)
    decision['plan_sha256'] = c.PLAN_SHA
    return {'decision': decision, 'run_files': {str(p.relative_to(run)): c.sha(p)
            for p in run.rglob('*.json') if 'images' not in p.parts}}


class LocalChecks(unittest.TestCase):
    def test_actual_partial_observation_stays_local_and_waits(self):
        with mock.patch.object(c.subprocess, 'run', side_effect=AssertionError('No subprocess')), \
             mock.patch.object(c.subprocess, 'Popen', side_effect=AssertionError('No spawn')):
            p = c.local_prepare(ROOT, OBSERVATION)
        self.assertEqual(p['decision']['status'], 'wait_for_search_completion')
        self.assertNotIn('run_files', p)

    def test_default_CLI_does_not_connect(self):
        with mock.patch.object(c.subprocess, 'run', side_effect=AssertionError('No subprocess')), \
             mock.patch.object(c.subprocess, 'Popen', side_effect=AssertionError('No spawn')), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(c.main([str(OBSERVATION)]), 0)
        value = json.loads(output.getvalue())
        self.assertFalse(value['remote_state_verified']); self.assertFalse(value['actual_confirmation_started'])

    def test_execute_with_real_partial_is_refused_before_claim(self):
        with mock.patch.object(c.subprocess, 'run', side_effect=AssertionError('No connection')), \
             mock.patch.object(g, 'exclusive_json', side_effect=AssertionError('No claim')):
            with self.assertRaisesRegex(RuntimeError, 'Complete independently'):
                c.main([str(OBSERVATION), '--execute'])

    def test_original_command_and_arbitrary_approved103_card(self):
        base = Path(g.BASES['103']); argv = c.command(base, base / 'code/SIMULATED', base / 'results' / g.RUN_NAME)
        self.assertEqual(argv[-3:], ['--resume', '--until', 'confirm'])
        for index in (0, 1, 2):
            p = permission(index); g.validate_permission(p, '103')
            self.assertEqual(g.runner_environment(base, p['gpu_uuid'])['CUDA_VISIBLE_DEVICES'], p['gpu_uuid'])

    def test_stale_disabled_and_over_quota_UI_refused(self):
        for key, value in [('observed_at', '2026-01-01T00:00:00+00:00'), ('gpu_disabled', True), ('own_gpu_count_all_servers', 4)]:
            p = permission(); p[key] = value
            with self.assertRaises(RuntimeError): g.validate_permission(p, '103')

    def test_source_and_bootstrap_are_syntax_valid_without_execution(self):
        source = (HERE / 'continue_search_confirmation.py').read_text(); ast.parse(source)
        program = c.remote_program(source, (HERE / 'launch_image_search.py').read_text(),
                                   {'continuation_sha256': hashlib.sha256(source.encode()).hexdigest()})
        ast.parse(program); self.assertIn('remote_continue', program)


class InventoryChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='SIMULATED_confirmation_inventory_')
        cls.run_dir = Path(cls.temp.name).resolve() / 'run'
        cls.payload = fixture(cls.run_dir)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_complete_two_promotion_inventory_matches_and_stays_unchanged(self):
        before = {str(p): c.sha(p) for p in self.run_dir.rglob('*') if p.is_file()}
        c.validate_decision(self.payload['decision'])
        result = c.verify_inventory(self.run_dir, PLAN, self.payload, runner)
        self.assertEqual(result['completed_receipts_and_PNGs_verified'], 816)
        self.assertEqual(before, {str(p): c.sha(p) for p in self.run_dir.rglob('*') if p.is_file()})

    def test_changed_PNG_refused(self):
        p = next((self.run_dir / 'images').rglob('*.png')); raw = p.read_bytes()
        try:
            p.write_bytes(raw + b'changed')
            with self.assertRaisesRegex(RuntimeError, 'PNG integrity'): c.verify_inventory(self.run_dir, PLAN, self.payload, runner)
        finally: p.write_bytes(raw)

    def test_started_receipt_never_replayed_even_with_updated_transport_hash(self):
        p = next((self.run_dir / 'operations').glob('*.json')); raw = p.read_bytes()
        payload = copy.deepcopy(self.payload)
        try:
            receipt = json.loads(raw); receipt['status'] = 'started'; p.write_bytes(c.canonical(receipt))
            payload['run_files'][str(p.relative_to(self.run_dir))] = c.sha(p)
            with self.assertRaisesRegex(RuntimeError, 'Unfinished'): c.verify_inventory(self.run_dir, PLAN, payload, runner)
        finally: p.write_bytes(raw)

    def test_uncommitted_extra_operation_refused(self):
        p = self.run_dir / 'operations/.unexpected.tmp'; p.write_text('SIMULATED')
        try:
            with self.assertRaisesRegex(RuntimeError, 'Extra or missing'): c.verify_inventory(self.run_dir, PLAN, self.payload, runner)
        finally: p.unlink()

    def test_unreceipted_image_refused(self):
        p = self.run_dir / 'images/uncommitted.png'; p.write_bytes(b'SIMULATED orphan image')
        try:
            with self.assertRaisesRegex(RuntimeError, 'Extra or missing image'): c.verify_inventory(self.run_dir, PLAN, self.payload, runner)
        finally: p.unlink()

    def test_confirmation_artifact_refused(self):
        p = self.run_dir / 'confirm_binding.json'; p.write_text('{}')
        try:
            with self.assertRaisesRegex(RuntimeError, 'Existing evidence'): c.verify_inventory(self.run_dir, PLAN, self.payload, runner)
        finally: p.unlink()

    def test_budget_three_promotions_and_missing_failure_rejected(self):
        for patch in ({'selected_search_count': 3}, {'archived_failed_attempts': 0}, {'final_attempts_with_failure': 1392}):
            d = dict(self.payload['decision'], **patch)
            with self.assertRaises(RuntimeError): c.validate_decision(d)


class RemoteOrderChecks(unittest.TestCase):
    def exercise(self, failed_spawn=False):
        with tempfile.TemporaryDirectory(prefix='SIMULATED_confirmation_remote_') as directory, ExitStack() as stack:
            base = Path(directory).resolve() / 'data'; code, control = base / 'code', base / 'launch-control'
            code.mkdir(parents=True); control.mkdir(); run = base / 'results' / g.RUN_NAME
            p = fixture(run, k=1)
            for relative in ('tmp', 'cache/huggingface', 'cache/torch', 'cache/triton', 'models'):
                (base / relative).mkdir(parents=True, exist_ok=True)
            (code / 'scripts/merging').mkdir(parents=True); shutil.copyfile(RUNNER_PATH, code / 'scripts/merging/tssa_image_search_run.py')
            (code / g.PLAN_REL).parent.mkdir(parents=True); shutil.copyfile(ROOT / g.PLAN_REL, code / g.PLAN_REL)
            python = base / 'venv/bin/python'; python.parent.mkdir(parents=True); python.write_text('SIMULATED no execution'); python.chmod(0o700)
            for lock in (run / '.run.lock', control / ('image-search-' + c.PLAN_SHA + '.lock')): lock.touch(mode=0o600)
            old = {}
            for name in c.REMOTE_OLD:
                target = control / name; target.write_text('SIMULATED old evidence ' + name); old[target] = target.read_bytes()
            p.update(server='103', plan_sha256=c.PLAN_SHA, identity_sha256=c.IDENTITY_SHA, guard_sha256=c.GUARD_SHA,
                     budget_gate_sha256=c.GATE_SHA, code_root=str(code), deployment={}, expected_files={}, permission=permission(1),
                     token='a'*32, continuation_sha256='b'*64, permission_sha256='c'*64, observation_sha256='d'*64)
            real_fixed, real_stat, real_read, real_write = c.fixed, Path.stat, Path.read_text, g.exclusive_json
            events = []
            def fixed(path, value):
                if path in old:
                    self.assertEqual(path.read_bytes(), old[path]); self.assertEqual(value, c.REMOTE_OLD[path.name]); return {}
                return real_fixed(path, value)
            def stat(path, *a, **kw):
                value = real_stat(path, *a, **kw)
                if path == base:
                    fields = list(value); fields[2] += 1; return os.stat_result(fields)
                return value
            def read(path, *a, **kw):
                if str(path) == '/proc/sys/kernel/random/boot_id': return 'SIMULATED-boot'
                if str(path) == '/proc/99999999/stat': raise FileNotFoundError()
                return real_read(path, *a, **kw)
            def write(path, value):
                real_write(path, value); events.append('claim' if path.name == c.CLAIM_NAME else 'receipt')
            def spawn(argv, **kw):
                self.assertEqual(events, ['claim']); self.assertEqual(argv[-3:], ['--resume', '--until', 'confirm'])
                self.assertEqual(kw['env']['CUDA_VISIBLE_DEVICES'], p['permission']['gpu_uuid'])
                with (run / '.run.lock').open('r+') as handle: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                events.append('spawn')
                if failed_spawn: raise OSError('SIMULATED spawn failed')
                return SimpleNamespace(pid=99999999)
            import fcntl
            for obj, name, value in ((c.platform, 'system', lambda: 'Linux'), (c.platform, 'machine', lambda: 'x86_64'),
                    (c.pwd, 'getpwuid', lambda uid: SimpleNamespace(pw_name='zhangzibo')), (Path, 'stat', stat), (Path, 'read_text', read),
                    (c, 'fixed', fixed), (g, 'validate_deployment', lambda *a: (str(code), {})),
                    (g, 'active_search_processes', lambda: []), (g, 'exclusive_json', write),
                    (g, 'inspect_gpu', lambda *a, **kw: {'index': 1, 'uuid': p['permission']['gpu_uuid']}),
                    (c.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='SIMULATED GPU XML')),
                    (c.subprocess, 'Popen', spawn)):
                stack.enter_context(mock.patch.object(obj, name, value))
            stack.enter_context(mock.patch.dict(g.BASES, {'103': str(base)}))
            if failed_spawn:
                with self.assertRaisesRegex(OSError, 'SIMULATED spawn'): c.remote_continue(p)
                self.assertEqual(events, ['claim', 'spawn'])
            else:
                result = c.remote_continue(p)
                self.assertEqual(events, ['claim', 'spawn', 'receipt'])
                self.assertEqual(result['verified']['completed_receipts_and_PNGs_verified'], 768)
                self.assertEqual(result['status'], 'runner_process_spawned_not_GPU_acceptance')
                self.assertIsNone(result['process_start_ticks'])
            with self.assertRaisesRegex(RuntimeError, 'Existing evidence'): c.remote_continue(p)
            for path, raw in old.items(): self.assertEqual(path.read_bytes(), raw)

    def test_claim_before_spawn_and_reentry_refused(self): self.exercise()
    def test_spawn_failure_preserves_claim_and_does_not_retry(self): self.exercise(failed_spawn=True)


if __name__ == '__main__': unittest.main(verbosity=2)
