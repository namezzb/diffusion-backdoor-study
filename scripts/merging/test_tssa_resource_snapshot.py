"""CPU regression for stable persisted history; no torch/model/GPU is imported.

Runs the real Store/Runner with synthetic two-pixel PNGs and the exact runtime
resource_record method AST; only CUDA memory counters and image scores are fake.
The preserved buggy method is a negative control using the same assertions.
"""
import ast
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from test_tssa_image_search_run import FakeBackend, fixture
from tssa_image_search_run import Runner, Store, digest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'scripts/merging/tssa_sd_runtime.py'
ARCHIVE = ROOT / 'results/tssa-opt-exploration-2026-10-28/frozen_code_before_resource_snapshot_fix'
OLD_SHA = '0008a4fc29ad1e36552069d55232a5480b09d1182953605c2aba09ba57805b3a'


def exact_method(path):
    tree = ast.parse(path.read_text())
    runtime = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SDGradientRuntime')
    method = next(n for n in runtime.body if isinstance(n, ast.FunctionDef) and n.name == 'resource_record')
    unit = ast.Module(body=[method], type_ignores=[]); ast.fix_missing_locations(unit)
    namespace = {'Any': object, 'torch': SimpleNamespace(cuda=SimpleNamespace(
        max_memory_allocated=lambda _: 123, max_memory_reserved=lambda _: 456))}
    exec(compile(unit, str(path) + ':exact_CPU_method_AST', 'exec'), namespace)
    return namespace['resource_record']


class CountedBackend(FakeBackend):
    def __init__(self, store, method):
        super().__init__(store)
        self.method = method
        self.runtime = SimpleNamespace(device='CPU_SYNTHETIC', ledger={
            'branch_nfe': {'full_generation': 0}, 'text_encoder_forwards': 0,
            'nested_diagnostic': {'history': [{'counter': 0}]}})

    def sample(self, task):
        image = super().sample(task)
        self.runtime.ledger['branch_nfe']['full_generation'] += 50
        self.runtime.ledger['text_encoder_forwards'] += 1
        self.runtime.ledger['nested_diagnostic']['history'][0]['counter'] += 1
        return image

    def resources(self):
        return self.method(self.runtime)


class ResourceSnapshotRegression(unittest.TestCase):
    def assert_stable_history(self, path):
        """Actual consumer contract: saved records, memory and stage digest agree."""
        with tempfile.TemporaryDirectory(prefix='tssa-resource-snapshot-CPU-') as directory:
            root = Path(directory) / 'run'; plan = fixture()
            identity = {'id': 'CPU_regression_not_science', 'max_images': plan['max_images']}
            store = Store(root, identity)
            try:
                backend = CountedBackend(store, exact_method(path))
                with contextlib.redirect_stdout(io.StringIO()):
                    result = Runner(plan, store, lambda: backend).execute('dev')
                self.assertEqual(result['stage'], 'dev'); self.assertEqual(len(store.receipts), 36)
                disk_records = {}
                for tid, in_memory in store.receipts.items():
                    saved = json.loads((root / 'operations' / (tid + '.json')).read_text())
                    self.assertEqual(digest(saved['record']), saved['record_sha256'])
                    self.assertEqual(digest(in_memory['record']), saved['record_sha256'], 'Historical record digest drift')
                    disk_records[tid] = saved['record']
                names = ['clean'] + list(plan['candidates'])
                for stage in ('search', 'dev'):
                    expected = []
                    for condition in plan['stages'][stage]['conditions']:
                        for name in names:
                            for row in plan['stages'][stage]['rows']:
                                task = {'stage':stage,'candidate':name,'condition':condition,'row':row,
                                        'coefficients':[0,0] if name=='clean' else plan['candidates'][name]}
                                expected.append(digest(disk_records[digest(task)]))
                    self.assertEqual(store.artifact(stage + '_summary.json')['record_sha256'], expected,
                                     'Stage summary digest differs from durable receipts')
                    names = ['clean','naive'] + store.artifact(stage + '_selection.json')['selected']
                # Later work and new nested activity keys must not alter any old record.
                before = [digest(r['record']) for r in store.receipts.values()]
                backend.runtime.ledger['branch_nfe']['full_generation'] += 50
                backend.runtime.ledger['branch_nfe']['new_activity'] = 7
                backend.runtime.ledger['nested_diagnostic']['history'].append({'counter':999})
                self.assertEqual(before, [digest(r['record']) for r in store.receipts.values()])
            finally:
                store.close()

    def test_current_snapshot_keeps_real_runner_history_and_summary_stable(self):
        self.assert_stable_history(RUNTIME)

    def test_preserved_old_method_is_detected_by_same_regression(self):
        old = ARCHIVE / RUNTIME.name
        self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(), OLD_SHA)
        with self.assertRaisesRegex(AssertionError, 'Historical record digest drift'):
            self.assert_stable_history(old)

    def test_editing_snapshot_cannot_modify_live_ledger_or_another_snapshot(self):
        method = exact_method(RUNTIME)
        ledger = {'branch_nfe': {'full_generation':50}, 'nested': [{'counts':[1,2]}]}
        live = SimpleNamespace(device='CPU_SYNTHETIC', ledger=ledger)
        original = copy.deepcopy(ledger); first, second = method(live), method(live)
        second_before = copy.deepcopy(second)
        first['branch_nfe']['full_generation'] = -1
        first['nested'][0]['counts'].append(999)
        first['nested'].append({'new':True})
        self.assertEqual(ledger, original)
        self.assertEqual(second, second_before)
        self.assertEqual(method(live), second_before)

    def test_old_source_and_frozen_manifests_are_preserved(self):
        record = json.loads((ARCHIVE/'archive_manifest.json').read_text())
        self.assertEqual(record['sha256'], OLD_SHA)
        self.assertEqual((ARCHIVE/'SHA256SUMS').read_text(), OLD_SHA+'  '+RUNTIME.name+'\n')
        for name, expected in record['manifest_sha256'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(), expected)
        plan = json.loads((ROOT/'research/tssa_optimization_exploration_2026-10-28.json').read_text())
        self.assertEqual(plan['source_hashes'][RUNTIME.name], OLD_SHA)
        self.assertNotEqual(hashlib.sha256(RUNTIME.read_bytes()).hexdigest(), OLD_SHA)


if __name__ == '__main__': unittest.main(verbosity=2)
