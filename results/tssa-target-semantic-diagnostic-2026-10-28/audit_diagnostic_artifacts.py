"""Read-only, NumPy artifact audit; no model, CUDA, network, or new samples.

The independent parts reconstruct the operation/event budgets and calculate
response statistics from raw FP32 tensors. Scientific gate replay deliberately
uses the original gate implementation and is labelled as such in the report.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KEYS = ('forward_branch_nfe', 'te_batch_calls', 'autograd_calls',
        'unet_backward_branch_visits', 'te_backward_calls')
LIMITS = dict(zip(KEYS, (462, 96, 14, 44, 14)))
STAGES = ('D0', 'D1', 'D2', 'D2r', 'D3')
UNITS = ('fit_unit_p00_s13', 'fit_unit_p04_s13')
CONDITIONS = ('Edev_0.08', 'Edev_0.25', 'Edev_0.50', 'upload')
PLAN_ID = 'tssa-target-semantic-diagnostic-2026-10-28-v1'
SHAPE = (1, 4, 64, 64)
RTOL, ATOL = 32 * float(np.finfo(np.float32).eps), 1e-12


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def zero():
    return dict.fromkeys(KEYS, 0)


def plus(a, b):
    return {key: a[key] + b[key] for key in KEYS}


def independent_schedule():
    points = {'D0': [('teacher', None)], 'D1': [('zero', [0., 0.])],
              'D2': [('naive', [1., 1.])], 'D2r': [('naive_repeat', [1., 1.])], 'D3': []}
    for label, h in [('h1_8', .125), ('h1_16', .0625)]:
        for index, axis in enumerate(('a', 'b')):
            for sign_name, sign in [('plus', 1), ('minus', -1)]:
                coefficients = [1., 1.]
                coefficients[index] += sign * h
                points['D3'].append((axis + '_' + sign_name + '_' + label, coefficients))
    operations = []
    for stage in STAGES:
        for point, coefficients in points[stage]:
            for unit in UNITS:
                for condition in CONDITIONS:
                    upload, grad = condition == 'upload', stage == 'D2'
                    cost = dict(zip(KEYS, (4 if upload else 6 if stage == 'D0' else 5, 1,
                                          (1 if upload else 2) if grad else 0,
                                          (4 if upload else 6) if grad else 0,
                                          (1 if upload else 2) if grad else 0)))
                    operations.append(dict(stage=stage, point_id=point, coefficients=coefficients,
                                           unit_id=unit, condition_id=condition, resource_delta=cost))
    return operations


def event_schedule(op):
    events = [('begin', zero()), ('te_batch', dict(zero(), te_batch_calls=1))]
    labels = ['pair_unconditional', 'normal']
    if op['condition_id'] != 'upload':
        labels += ['triggered'] + (['target'] if op['stage'] == 'D0' else [])
    labels += ['extra_unconditional', 'extra']
    events += [('unet_' + name, dict(zero(), forward_branch_nfe=1)) for name in labels]
    if op['stage'] == 'D2':
        if op['condition_id'] != 'upload':
            events.append(('autograd_attack', dict(zero(), autograd_calls=1,
                           unet_backward_branch_visits=2, te_backward_calls=1)))
        events.append(('autograd_normal', dict(zero(), autograd_calls=1,
                       unet_backward_branch_visits=4, te_backward_calls=1)))
    context = dict(unit_id=op['unit_id'], condition_id=op['condition_id'], coefficients=op['coefficients'],
                   kind='teacher' if op['stage'] == 'D0' else 'student', gradients=op['stage'] == 'D2')
    return [dict(context, operation=name, cost=cost) for name, cost in events]


class Audit:
    def __init__(self, artifacts, plan_path):
        self.root, self.plan_path = Path(artifacts).resolve(), Path(plan_path).resolve()
        self.errors, self.numeric, self.hashes = [], [], {}
        self.checks = 0
        self.report = {'schema_version': 1, 'at': dt.datetime.now(dt.timezone.utc).isoformat(),
                       'artifacts': str(self.root), 'reference_plan': str(self.plan_path),
                       'ASR_validated': False, 'images_generated_by_audit': 0, 'optimizer_updates': 0,
                       'audit_implementation_sha256': sha(Path(__file__).read_bytes()),
                       'numeric_policy': {'rtol': RTOL, 'atol': ATOL,
                           'method': 'FP32 subtract/square, independent NumPy float64 reduction; comparison only, no gate changes'},
                       'limitations': ['Raw bytes establish 16384 little-endian FP32 values reshaped to the frozen shape, not independent model execution.',
                           'Autograd is not independently recomputed; durable recorded events and tensor-hook counts are cross-checked.',
                           'Scientific gate replay reuses the original implementation and is not independent scientific verification.',
                           'A valid audit or passing local diagnostic is not improved ASR evidence.']}

    def check(self, ok, message):
        self.checks += 1
        if not ok:
            self.errors.append(message)
        return bool(ok)

    def read(self, relative):
        path = self.root / relative
        if not self.check(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(self.root),
                          str(relative) + ': missing, redirected, or not a file'):
            raise ValueError(str(relative))
        raw = path.read_bytes()
        self.hashes[str(relative)] = sha(raw)
        return raw

    def obj(self, relative):
        return json.loads(self.read(relative))

    def close_number(self, path, recorded, recalculated):
        finite = (type(recorded) in (int, float) and math.isfinite(recorded) and math.isfinite(recalculated))
        difference = abs(recorded - recalculated) if finite else None
        limit = ATOL + RTOL * abs(recalculated) if finite else None
        self.check(finite and difference <= limit, path + ': FP32 statistic differs')
        self.numeric.append({'field': path, 'recorded': recorded if finite else repr(recorded),
                             'numpy': recalculated if math.isfinite(recalculated) else repr(recalculated),
                             'absolute_error': difference, 'allowed_error': limit})

    def counter(self, value, label):
        self.check(type(value) is dict and set(value) == set(KEYS) and
                   all(type(v) is int and v >= 0 for v in value.values()), label + ': malformed resource counter')
        return value

    @staticmethod
    def mse(a, b):
        delta = np.subtract(a, b, dtype=np.float32)
        return float(np.mean(np.multiply(delta, delta, dtype=np.float32), dtype=np.float64))

    @staticmethod
    def rms(a):
        return math.sqrt(float(np.mean(np.multiply(a, a, dtype=np.float32), dtype=np.float64)))

    def run(self):
        identity = self.obj('identity.json')
        external_raw = self.plan_path.read_bytes()
        plan = json.loads(external_raw)
        self.check(identity['plan'] == plan, 'Identity differs from separately frozen local plan')
        self.check(identity['plan_sha256'] == sha(external_raw) == sha(canonical(plan)), 'Plan raw/canonical SHA mismatch')
        self.check(identity['preflight_sha256'] == plan['preflight_sha256'], 'Preflight SHA mismatch')
        self.check(plan['id'] == PLAN_ID and plan['status'] == 'frozen' and plan['schema_version'] == 1, 'Plan identity/status differs')
        self.check(plan['budget'] == LIMITS and plan['wall_seconds_max'] == 1800 and plan['automatic_retry'] is False,
                   'Frozen budget or stop policy differs')
        self.check(all(plan[key] == 0 for key in ('images', 'optimizer_updates', 'new_trajectories')), 'Unexpected scientific allocation')
        operations = independent_schedule()
        self.check(plan['operations'] == operations, 'Independent 96-cell operation enumeration differs')
        operation_names = [sha(canonical(op)) for op in operations]
        op_by_name = dict(zip(operation_names, operations))
        self.check(len(set(operation_names)) == 96, 'Operation identities not unique')
        for name, digest in plan['binding']['implementation_sha256'].items():
            self.check(sha((ROOT / 'scripts/merging' / name).read_bytes()) == digest, 'Local source hash differs: ' + name)

        started, completed = {}, {}
        for path in sorted((self.root / 'cells').glob('*.json')):
            if path.name.endswith('.started.json'):
                name = path.name[:-len('.started.json')]
                self.check(name not in started and name in op_by_name, 'Unknown/duplicate started cell ' + name)
                started[name] = self.obj(path.relative_to(self.root))
                self.check(started[name]['operation'] == op_by_name[name], 'Started operation differs: ' + name)
                self.check(started[name]['identity_sha256'] == sha(canonical(identity)), 'Started identity SHA differs: ' + name)
            elif path.name.endswith('.completed.json'):
                name = path.name[:-len('.completed.json')]
                self.check(name not in completed and name in op_by_name, 'Unknown/duplicate completed cell ' + name)
                completed[name] = self.obj(path.relative_to(self.root))
            else:
                self.check(False, 'Unexpected cell file ' + path.name)
        self.check(set(completed) <= set(started), 'Completion has no started receipt')
        self.check(set(started) == set(operation_names[:len(started)]), 'Started operations are not a consecutive prefix')
        self.check(set(completed) == set(operation_names[:len(completed)]), 'Completed operations are not a consecutive prefix')
        pending = [name for name in operation_names if name in started and name not in completed]
        self.check(len(pending) <= 1, 'Multiple pending cells in serial executor')

        reserved, cell_reserved, event_indices = zero(), defaultdict(zero), defaultdict(int)
        before, after = {}, {}
        reservations = sorted((self.root / 'reservations').glob('*.json'))
        self.check([p.name for p in reservations] == ['%06d.json' % i for i in range(1, len(reservations) + 1)],
                   'Reservation sequence has gaps or unexpected names')
        previous_cell_index = -1
        for path in reservations:
            entry = self.obj(path.relative_to(self.root))
            name = sha(canonical(entry['cell']))
            self.check(name in started and entry['cell'] == op_by_name[name], 'Reservation cell not started/frozen')
            index = operation_names.index(name)
            self.check(index in (previous_cell_index, previous_cell_index + 1), 'Reservation cells out of order')
            previous_cell_index = index
            before.setdefault(name, deepcopy(reserved))
            expected = event_schedule(op_by_name[name])
            position = event_indices[name]
            self.check(position < len(expected) and entry['event'] == expected[position], 'Unexpected event or event cost: ' + path.name)
            cost = self.counter(entry['event']['cost'], path.name)
            reserved, cell_reserved[name] = plus(reserved, cost), plus(cell_reserved[name], cost)
            event_indices[name] += 1
            self.check(entry['reserved_total'] == reserved and entry['reserved_cell'] == cell_reserved[name],
                       'Cumulative reservation differs: ' + path.name)
            self.check(all(reserved[key] <= LIMITS[key] for key in KEYS), 'Total reservation exceeds frozen budget')
            self.check(all(cell_reserved[name][key] <= op_by_name[name]['resource_delta'][key] for key in KEYS),
                       'Cell reservation exceeds frozen budget: ' + name)
            after[name] = deepcopy(reserved)
        prior = zero()
        for name in operation_names[:len(started)]:
            self.check(started[name]['reserved_before'] == prior == before.get(name, prior), 'Started counter differs: ' + name)
            prior = after.get(name, prior)
            if name in completed:
                self.check(event_indices[name] == len(event_schedule(op_by_name[name])), 'Completed cell has incomplete events: ' + name)
                self.check(cell_reserved[name] == op_by_name[name]['resource_delta'], 'Completed cell resource total differs: ' + name)
                self.check(completed[name]['reserved_total'] == prior, 'Completed cumulative total differs: ' + name)

        tensors, rows, per_stage = {}, defaultdict(list), {stage: zero() for stage in STAGES}
        completed_total = zero()
        for name in operation_names[:len(completed)]:
            op, entry = op_by_name[name], completed[name]
            row, backend = entry['record'], entry['backend_evidence']
            stage, cid, uid = op['stage'], op['condition_id'], op['unit_id']
            row_path = 'cells/' + name
            for key in ('stage', 'point_id', 'unit_id', 'condition_id'):
                self.check(row[key] == op[key], row_path + ': row identity differs')
            self.check(row['resource_delta'] == backend['resource_delta'] == op['resource_delta'], row_path + ': resource deltas differ')
            self.check(backend['kind'] == ('teacher' if stage == 'D0' else 'student') and
                       backend['coefficients'] == op['coefficients'], row_path + ': backend role differs')
            for key in ('output_rms', 'losses', 'gradients'):
                self.check(row[key] == backend[key], row_path + ': backend/row ' + key + ' differs')
            response_names = {'normal', 'extra'} if cid == 'upload' else {'normal', 'extra', 'triggered'}
            if stage == 'D0' and cid != 'upload':
                response_names.add('target')
            self.check(set(entry['output_sha256']) == set(backend['output_sha256']) == response_names,
                       row_path + ': response domain differs')
            actual_files = {f.name for f in (self.root / 'outputs' / name).iterdir()}
            self.check(actual_files == {key + '.f32' for key in response_names}, row_path + ': response files differ')
            outputs = {}
            for key in sorted(response_names):
                raw = self.read('outputs/' + name + '/' + key + '.f32')
                self.check(sha(raw) == entry['output_sha256'][key] == backend['output_sha256'][key], row_path + ': raw SHA differs: ' + key)
                self.check(len(raw) == math.prod(SHAPE) * 4, row_path + ': raw tensor size differs: ' + key)
                tensor = np.frombuffer(raw, dtype='<f4').reshape(SHAPE)
                self.check(bool(np.isfinite(tensor).all()), row_path + ': nonfinite response: ' + key)
                outputs[key] = tensor
                self.close_number(row_path + '.output_rms.' + key, row['output_rms'][key], self.rms(tensor))
            tensors[(stage, op['point_id'], uid, cid)] = outputs
            if stage == 'D0':
                self.check(row['losses'] is None and row['gradients'] is None, row_path + ': teacher has loss/gradient')
                if cid != 'upload':
                    self.close_number(row_path + '.signal_rms', row['signal_rms'], math.sqrt(self.mse(outputs['target'], outputs['normal'])))
                    self.check(row['signal_rms'] == backend['signal_rms'], row_path + ': backend signal differs')
            else:
                teacher = tensors[('D0', 'teacher', uid, cid)]
                normal = .5 * self.mse(outputs['normal'], teacher['normal']) + .5 * self.mse(outputs['extra'], teacher['extra'])
                self.close_number(row_path + '.losses.normal', row['losses']['normal'], normal)
                if cid != 'upload':
                    self.close_number(row_path + '.losses.attack', row['losses']['attack'], self.mse(outputs['triggered'], teacher['target']))
                else:
                    self.check(row['losses']['attack'] is None, row_path + ': upload attack must be None')
                for key, tensor in outputs.items():
                    error = math.sqrt(self.mse(tensor, teacher[key]))
                    self.close_number(row_path + '.backend.errors_vs_teacher.' + key, backend['errors_vs_teacher'][key], error)
                    if stage == 'D1':
                        self.close_number(row_path + '.errors_vs_teacher.' + key, row['errors_vs_teacher'][key], error)
                    if stage == 'D2r':
                        naive = tensors[('D2', 'naive', uid, cid)]
                        self.close_number(row_path + '.errors_vs_naive.' + key, row['errors_vs_naive'][key], math.sqrt(self.mse(tensor, naive[key])))
            rows[stage].append(row)
            completed_total = plus(completed_total, op['resource_delta'])
            per_stage[stage] = plus(per_stage[stage], op['resource_delta'])
        output_dirs = {path.name for path in (self.root / 'outputs').iterdir()} if (self.root / 'outputs').exists() else set()
        self.check(output_dirs <= set(started), 'Orphan output directories without started cells')
        pending_outputs = []
        for name in pending:
            for path in (self.root / 'outputs' / name).glob('*'):
                raw = self.read(path.relative_to(self.root))
                self.check(path.name in {'normal.f32', 'extra.f32', 'triggered.f32', 'target.f32'} and len(raw) == math.prod(SHAPE) * 4,
                           'Pending output has invalid name or size')
                self.check(bool(np.isfinite(np.frombuffer(raw, dtype='<f4')).all()), 'Pending output nonfinite')
                pending_outputs.append(str(path.relative_to(self.root)))

        sys.path.insert(0, str(ROOT / 'scripts/merging'))
        from tssa_target_semantic_gates import check_stage
        gate_replay, prior_rows = {}, {}
        stage_files = sorted(self.root.glob('stage_*.json'))
        observed_stages = {path.stem[len('stage_'):] for path in stage_files}
        self.check(observed_stages == set(STAGES[:len(observed_stages)]), 'Published stages are not a prefix')
        for stage in STAGES:
            if stage not in observed_stages:
                continue
            saved = self.obj('stage_' + stage + '.json')
            expected_cells = sum(op['stage'] == stage for op in operations)
            self.check(len(rows[stage]) == expected_cells and saved['records'] == rows[stage], stage + ': stage records incomplete/different')
            recalculated_gate = check_stage(stage, rows[stage], prior_rows)
            self.check(saved['gate'] == recalculated_gate, stage + ': original gate replay differs')
            gate_replay[stage] = recalculated_gate
            prior_rows[stage] = rows[stage]
            if recalculated_gate['status'] not in ('prefix_pass', 'diagnostic_pass'):
                self.check(not any(op['stage'] in STAGES[STAGES.index(stage) + 1:] for n, op in op_by_name.items() if n in started),
                           'Operations continued after failed scientific gate')

        terminal_names = [name for name in ('terminal.json', 'failure.json', 'wall_timeout.json') if (self.root / name).exists()]
        self.check(len(terminal_names) <= 1, 'Conflicting terminal artifacts')
        terminal_kind = terminal_names[0] if terminal_names else 'no_terminal_artifact'
        terminal = self.obj(terminal_kind) if terminal_names else {}
        if terminal_names:
            self.check(terminal['reserved'] == reserved, 'Terminal reserved counter differs')
        resources = terminal.get('resources')
        if resources is not None:
            self.check(resources['hard_limits'] == LIMITS, 'Backend hard limits differ')
            attempted = self.counter(resources['attempted'], 'backend attempted')
            actual = self.counter(resources['actual'], 'backend actual')
            self.check(all(completed_total[key] <= actual[key] <= attempted[key] <= reserved[key] for key in KEYS),
                       'Backend counters outside completed/reserved bounds')
        if terminal_kind == 'terminal.json':
            self.check(not pending and terminal['ASR_validated'] is False and terminal['images'] == terminal['optimizer_updates'] == 0,
                       'Terminal scientific boundary or pending work differs')
            self.check(resources is not None and resources['attempted'] == resources['actual'] == reserved == completed_total and
                       resources['failed'] is False and resources['busy'] is False, 'Successful terminal counters differ')
            self.check(terminal['stages'] == list(gate_replay.values()), 'Terminal stage gates differ')
            self.check(0 <= terminal['cuda_wall_seconds'] < 1800, 'Terminal exceeds wall budget')
            if terminal['status'] == 'local_diagnostic_passed':
                self.check(len(completed) == 96 and reserved == LIMITS and gate_replay['D3']['status'] == 'diagnostic_pass',
                           'Diagnostic pass lacks complete budget/gates')
            elif terminal['status'] == 'stopped_at_scientific_gate':
                self.check(terminal['stage'] == list(gate_replay)[-1] and terminal['gate'] == gate_replay[terminal['stage']] and
                           terminal['gate']['status'] not in ('prefix_pass', 'diagnostic_pass'), 'Scientific stop gate differs')
            else:
                self.check(False, 'Unknown terminal status')
        elif terminal_kind in ('failure.json', 'wall_timeout.json'):
            pending_op = op_by_name[pending[0]] if pending else None
            self.check(terminal.get('pending_cell', terminal.get('cell')) == pending_op, 'Failure pending cell differs')
            self.check(terminal['automatic_retry'] is False, 'Failure retry policy differs')
        self.report.update(terminal_kind=terminal_kind, scientific_outcome=terminal.get('status', 'failed_or_interrupted'),
                           started_cells=len(started), completed_cells=len(completed), pending_cells=pending,
                           pending_output_files_unaccepted=pending_outputs, reserved=reserved,
                           completed_resources=completed_total, pending_reserved={key: reserved[key] - completed_total[key] for key in KEYS},
                           completed_resources_by_stage=per_stage, reservation_events=len(reservations),
                           gate_replay={'implementation': 'original check_stage; NOT independent', 'results': gate_replay})
        return self.finish('passed' if terminal_kind == 'terminal.json' else 'consistent_partial')

    def finish(self, status):
        self.report.update(status='invalid' if self.errors else status, checks=self.checks, errors=self.errors,
                           numeric_comparisons=len(self.numeric), numeric_details=self.numeric, artifact_sha256=self.hashes)
        return self.report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('--plan', type=Path, default=HERE / 'launch_20261029/plan.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.artifacts.resolve()):
        parser.error('Audit output must be outside the read-only artifact directory')
    audit = Audit(args.artifacts, args.plan)
    try:
        report = audit.run()
    except Exception as error:
        audit.errors.append('Audit could not complete: ' + type(error).__name__ + ': ' + str(error))
        report = audit.finish('invalid')
    with args.output.open('x') as stream:
        stream.write(canonical(report).decode())
    print(json.dumps({key: report[key] for key in ('status', 'checks', 'numeric_comparisons', 'errors')}))
    return 1 if report['status'] == 'invalid' else 0


if __name__ == '__main__':
    raise SystemExit(main())
