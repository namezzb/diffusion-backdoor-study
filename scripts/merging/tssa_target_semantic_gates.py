"""Pure-stdlib gates for the proposed target-semantic diagnostic; never runs models.

API
---
budget_enumeration() gives the exact 96 operations and per-cell resource deltas.
evaluate_stages({stage: [record, ...]}) accepts any complete consecutive prefix
of D0, D1, D2, D2r, D3. check_stage(stage, records, prior_records) is the
incremental convenience entry. Malformed input raises SchemaError; scientific
or numerical rejection returns status='fail' with located failures. A passing
prefix is not permission to run another stage or evidence of improved ASR.

Every record has EXACTLY stage, point_id, unit_id, condition_id, output_rms,
errors_vs_teacher, signal_rms, losses, gradients, resource_delta. D2r additionally
has errors_vs_naive. D0 losses=None; later losses are attack/normal (upload
attack=None). Gradients exist only at D2, with attack/normal two-number lists
(upload attack=None). errors_vs_teacher exists only at D1; signal_rms exists
only for D0 merge cells. Other unused fields are explicitly None, not omitted.
Teacher merge RMS keys: normal/triggered/extra/target; student merge and error
keys: normal/triggered/extra. Upload always has normal/extra only.

The caller must separately verify tensor shapes/bytes, frozen model state,
backend/precision/cache identity, exact permitted GPU, wall time and receipts.
This module cannot establish those facts from scalar summaries.

Fixed conservative interpretations of the proposal: delta_A is the mean of
absolute per-cell loss differences, not the absolute difference of two means;
aggregate eta is the mean of the six per-cell max(1e-7, delta_L/(1/16)) bounds.
A resolved aggregate coordinate requires AD and both FD estimates strictly
above 10*aggregate_eta with the same sign. Weak components remain unresolved,
never a reliable zero. "At least margin" uses >=; signal/resolution use >.
"""
from __future__ import annotations

import math

SCHEMA_VERSION = 1
STAGES = ('D0', 'D1', 'D2', 'D2r', 'D3')
UNITS = ('fit_unit_p00_s13', 'fit_unit_p04_s13')
CONDITIONS = ('Edev_0.08', 'Edev_0.25', 'Edev_0.50', 'upload')
MERGES = CONDITIONS[:-1]
RESOURCE_KEYS = ('forward_branch_nfe', 'te_batch_calls', 'autograd_calls',
                 'unet_backward_branch_visits', 'te_backward_calls')
FD_STEPS = (('h1_8', 0.125), ('h1_16', 0.0625))
BASE_POINTS = {'D0': ('teacher', None), 'D1': ('zero', (0.0, 0.0)),
               'D2': ('naive', (1.0, 1.0)), 'D2r': ('naive_repeat', (1.0, 1.0))}
CORE_KEYS = {'stage', 'point_id', 'unit_id', 'condition_id', 'output_rms',
             'errors_vs_teacher', 'signal_rms', 'losses', 'gradients', 'resource_delta'}
WALL_SECONDS_MAX = 1800  # Enforced by caller, not inferred from scalar summaries.


class SchemaError(ValueError):
    """Missing/unknown/duplicate/nonfinite data or an invalid operation budget."""


def _require(ok, path, reason):
    if not ok:
        raise SchemaError('{}: {}'.format(path, reason))


def _keys(value, expected, path):
    _require(type(value) is dict, path, 'expected object')
    _require(set(value) == set(expected), path,
             'keys differ; missing={!r}, unknown={!r}'.format(
                 sorted(set(expected) - set(value)), sorted(set(value) - set(expected), key=str)))


def _number(value, path, nonnegative=False):
    _require(type(value) in (int, float), path, 'expected finite number, not bool')
    try:
        value = float(value)
    except (ValueError, OverflowError) as error:
        raise SchemaError(path + ': number cannot be represented finitely') from error
    _require(math.isfinite(value), path, 'nonfinite number')
    _require(not nonnegative or value >= 0, path, 'negative magnitude/loss')
    return value


def _mean(values):
    values = list(values)
    # Dividing before fsum avoids overflow when a finite mean exists.
    return _number(math.fsum(v / len(values) for v in values), 'derived.mean')


def _scalar_map(value, expected, path):
    _keys(value, expected, path)
    return {k: _number(value[k], path + '.' + k, True) for k in expected}


def points_for_stage(stage):
    _require(stage in STAGES, 'stage', 'unknown stage')
    if stage != 'D3':
        name, coefficients = BASE_POINTS[stage]
        return [{'point_id': name, 'coefficients': None if coefficients is None else list(coefficients)}]
    result = []
    for h_name, h in FD_STEPS:
        for axis_index, axis in enumerate(('a', 'b')):
            for sign_name, sign in (('plus', 1), ('minus', -1)):
                coefficients = [1.0, 1.0]
                coefficients[axis_index] += sign * h
                result.append({'point_id': '{}_{}_{}'.format(axis, sign_name, h_name),
                               'coefficients': coefficients})
    return result


def expected_resource(stage, condition):
    _require(stage in STAGES and condition in CONDITIONS, 'resource', 'unknown operation')
    upload = condition == 'upload'
    differentiation = stage == 'D2'
    return {'forward_branch_nfe': 4 if upload else (6 if stage == 'D0' else 5),
            'te_batch_calls': 1,
            'autograd_calls': (1 if upload else 2) if differentiation else 0,
            'unet_backward_branch_visits': (4 if upload else 6) if differentiation else 0,
            'te_backward_calls': (1 if upload else 2) if differentiation else 0}


def budget_enumeration():
    return [dict(stage=stage, point_id=point['point_id'],
                 coefficients=None if point['coefficients'] is None else list(point['coefficients']),
                 unit_id=unit, condition_id=condition, resource_delta=expected_resource(stage, condition))
            for stage in STAGES for point in points_for_stage(stage)
            for unit in UNITS for condition in CONDITIONS]


def budget_totals(operations=None):
    operations = budget_enumeration() if operations is None else operations
    totals = dict.fromkeys(RESOURCE_KEYS, 0)
    for operation in operations:
        for key in RESOURCE_KEYS:
            totals[key] += operation['resource_delta'][key]
    return totals


def _responses(condition, teacher=False):
    if condition == 'upload':
        return ('normal', 'extra')
    return ('normal', 'triggered', 'extra', 'target') if teacher else ('normal', 'triggered', 'extra')


def validate_stage(stage, records):
    """Return copied numeric cells keyed by (point, unit, condition)."""
    _require(stage in STAGES, 'stage', 'unknown stage')
    _require(type(records) is list, stage, 'records must be a list')
    expected = {(p['point_id'], u, c) for p in points_for_stage(stage) for u in UNITS for c in CONDITIONS}
    cells = {}
    for i, record in enumerate(records):
        path = '{}[{}]'.format(stage, i)
        _keys(record, CORE_KEYS | ({'errors_vs_naive'} if stage == 'D2r' else set()), path)
        _require(record['stage'] == stage, path + '.stage', 'wrong stage')
        for name in ('point_id', 'unit_id', 'condition_id'):
            _require(type(record[name]) is str, path + '.' + name, 'expected string')
        key = (record['point_id'], record['unit_id'], record['condition_id'])
        _require(key in expected, path, 'unknown cell {}'.format(key))
        _require(key not in cells, path, 'duplicate cell {}'.format(key))
        condition = record['condition_id']
        copied = {name: record[name] for name in ('stage', 'point_id', 'unit_id', 'condition_id')}
        copied['output_rms'] = _scalar_map(record['output_rms'], _responses(condition, stage == 'D0'), path + '.output_rms')
        for field, used in (('errors_vs_teacher', stage == 'D1'),):
            if used:
                copied[field] = _scalar_map(record[field], _responses(condition), path + '.' + field)
            else:
                _require(record[field] is None, path + '.' + field, 'must be None at this stage')
                copied[field] = None
        if stage == 'D2r':
            copied['errors_vs_naive'] = _scalar_map(record['errors_vs_naive'], _responses(condition), path + '.errors_vs_naive')
        if stage == 'D0' and condition != 'upload':
            copied['signal_rms'] = _number(record['signal_rms'], path + '.signal_rms', True)
        else:
            _require(record['signal_rms'] is None, path + '.signal_rms', 'must be None at this stage/state')
            copied['signal_rms'] = None
        if stage == 'D0':
            _require(record['losses'] is None, path + '.losses', 'teacher has no student loss')
            copied['losses'] = None
        else:
            _keys(record['losses'], ('attack', 'normal'), path + '.losses')
            copied['losses'] = {'normal': _number(record['losses']['normal'], path + '.losses.normal', True)}
            if condition == 'upload':
                _require(record['losses']['attack'] is None, path + '.losses.attack', 'upload has no attack loss')
                copied['losses']['attack'] = None
            else:
                copied['losses']['attack'] = _number(record['losses']['attack'], path + '.losses.attack', True)
        if stage == 'D2':
            _keys(record['gradients'], ('attack', 'normal'), path + '.gradients')
            copied['gradients'] = {}
            for term in ('attack', 'normal'):
                vector = record['gradients'][term]
                if term == 'attack' and condition == 'upload':
                    _require(vector is None, path + '.gradients.attack', 'upload has no attack gradient')
                    copied['gradients'][term] = None
                else:
                    _require(type(vector) is list and len(vector) == 2, path + '.gradients.' + term, 'expected [a,b] list')
                    copied['gradients'][term] = [_number(v, path + '.gradients.' + term) for v in vector]
        else:
            _require(record['gradients'] is None, path + '.gradients', 'gradients only permitted at D2')
            copied['gradients'] = None
        _keys(record['resource_delta'], RESOURCE_KEYS, path + '.resource_delta')
        planned = expected_resource(stage, condition)
        for name, expected_count in planned.items():
            actual = record['resource_delta'][name]
            _require(type(actual) is int and actual >= 0, path + '.resource_delta.' + name, 'expected nonnegative int')
            _require(actual == expected_count, path + '.resource_delta.' + name,
                     'complete cell requires exactly {}; got {}'.format(expected_count, actual))
        copied['resource_delta'] = dict(planned)
        cells[key] = copied
    _require(set(cells) == expected, stage, 'missing cells {}'.format(sorted(expected - set(cells))))
    return cells


def _at(cells, stage, unit, condition, point=None):
    return cells[stage][(point or BASE_POINTS[stage][0], unit, condition)]


def _failure(code, unit_id=None, condition_id=None, **details):
    return dict(code=code, unit_id=unit_id, condition_id=condition_id, **details)


def _identity(cells):
    failures, checks = [], []
    for unit in UNITS:
        for condition in CONDITIONS:
            teacher, zero = _at(cells, 'D0', unit, condition), _at(cells, 'D1', unit, condition)
            for response in _responses(condition):
                limit = 1e-5 + 1e-3 * teacher['output_rms'][response]
                error = zero['errors_vs_teacher'][response]
                item = dict(unit_id=unit, condition_id=condition, response=response, rms_error=error, limit=limit)
                checks.append(item)
                if error > limit:
                    failures.append(_failure('zero_identity_error', **item))
    return failures, {'identity_checks': checks}


def _loss_noise(cells, unit, condition, term):
    a = _at(cells, 'D2', unit, condition)['losses'][term]
    b = _at(cells, 'D2r', unit, condition)['losses'][term]
    return abs(a - b)


def _attack_mean(cells, stage, point=None):
    return _mean(_at(cells, stage, u, c, point)['losses']['attack'] for u in UNITS for c in MERGES)


def _attack_delta(cells):
    return _mean(_loss_noise(cells, u, c, 'attack') for u in UNITS for c in MERGES)


def _repeat_signal_polarity(cells):
    failures, checks, signals = [], [], []
    for unit in UNITS:
        for condition in CONDITIONS:
            naive, repeat = _at(cells, 'D2', unit, condition), _at(cells, 'D2r', unit, condition)
            zero = _at(cells, 'D1', unit, condition)
            for response in _responses(condition):
                error = repeat['errors_vs_naive'][response]
                limit = 1e-6 + 1e-4 * naive['output_rms'][response]
                item = dict(unit_id=unit, condition_id=condition, response=response, rms_error=error, limit=limit)
                checks.append(item)
                if error > limit:
                    failures.append(_failure('repeat_numerical_error', **item))
            if condition != 'upload':
                noise = max(list(zero['errors_vs_teacher'].values()) + list(repeat['errors_vs_naive'].values()))
                limit = _number(max(1e-4, 20 * noise), 'derived.signal_limit', True)
                signal = _at(cells, 'D0', unit, condition)['signal_rms']
                item = dict(unit_id=unit, condition_id=condition, signal_rms=signal, response_noise_rms=noise, limit_exclusive=limit)
                signals.append(item)
                if signal <= limit:
                    failures.append(_failure('target_signal_insufficient', **item))
    clean, naive, delta = _attack_mean(cells, 'D1'), _attack_mean(cells, 'D2'), _attack_delta(cells)
    margin = _number(max(0.01 * clean, 10 * delta, 1e-8), 'derived.polarity_margin', True)
    polarity = dict(clean_attack_mean=clean, naive_attack_mean=naive, conservative_delta_attack=delta,
                    required_improvement=margin, observed_improvement=clean - naive)
    if clean - naive < margin:
        failures.append(_failure('target_polarity_not_supported', **polarity))
    return failures, {'repeat_checks': checks, 'signal_checks': signals, 'polarity': polarity}


def _fd(cells, unit, condition, term, axis, h_name, h):
    plus = _at(cells, 'D3', unit, condition, '{}_plus_{}'.format(axis, h_name))['losses'][term]
    minus = _at(cells, 'D3', unit, condition, '{}_minus_{}'.format(axis, h_name))['losses'][term]
    return _number((plus - minus) / (2 * h), 'derived.finite_difference')


def _opposite_reliable(values, eta):
    reliable = [v for v in values if abs(v) > 10 * eta]
    return bool(reliable and min(reliable) < 0 < max(reliable))


def _gradient_and_local(cells):
    failures, components = [], []
    attack_values = {axis: [] for axis in ('a', 'b')}
    for unit in UNITS:
        for condition in CONDITIONS:
            for term in (('normal',) if condition == 'upload' else ('attack', 'normal')):
                delta = _loss_noise(cells, unit, condition, term)
                eta = _number(max(1e-7, delta / 0.0625), 'derived.gradient_noise', True)
                for index, axis in enumerate(('a', 'b')):
                    ad = _at(cells, 'D2', unit, condition)['gradients'][term][index]
                    large, small = [_fd(cells, unit, condition, term, axis, hn, h) for hn, h in FD_STEPS]
                    limit = _number(0.20 * max(abs(ad), abs(large), abs(small)) + 5 * eta, 'derived.gradient_limit', True)
                    differences = {'step_stability': abs(large - small), 'AD_vs_large': abs(ad - large), 'AD_vs_small': abs(ad - small)}
                    for name, value in differences.items():
                        _number(value, 'derived.' + name, True)
                    resolved = all(abs(v) > 10 * eta for v in (ad, large, small))
                    opposite = _opposite_reliable((ad, large, small), eta)
                    item = dict(unit_id=unit, condition_id=condition, term=term, coordinate=axis, ad=ad,
                                fd_large=large, fd_small=small, loss_delta=delta, eta=eta, limit=limit,
                                absolute_differences=differences,
                                resolution='reliable_nonzero' if resolved and not opposite else 'unresolved_not_reliable_zero')
                    components.append(item)
                    if any(value > limit for value in differences.values()):
                        failures.append(_failure('finite_difference_disagreement', **item))
                    if opposite:
                        failures.append(_failure('reliable_gradient_sign_conflict', **item))
                    if term == 'attack':
                        attack_values[axis].append((ad, large, small, eta, delta))
    aggregate = {}
    for axis, rows in attack_values.items():
        ad, large, small, eta, delta = [_mean(row[i] for row in rows) for i in range(5)]
        reliable = all(abs(v) > 10 * eta for v in (ad, large, small)) and not _opposite_reliable((ad, large, small), eta)
        aggregate[axis] = dict(ad=ad, fd_large=large, fd_small=small,
                               eta_conservative_mean_of_cell_bounds=eta,
                               conservative_mean_absolute_loss_delta=delta,
                               threshold_exclusive=10 * eta, reliable_nonzero=reliable)
    if not any(value['reliable_nonzero'] for value in aggregate.values()):
        failures.append(_failure('aggregate_attack_gradient_unresolved', coordinates=aggregate))
    naive, delta = _attack_mean(cells, 'D2'), _attack_delta(cells)
    margin = _number(max(0.01 * naive, 10 * delta, 1e-8), 'derived.local_margin', True)
    local, eligible = [], []
    for point in points_for_stage('D3'):
        point_id = point['point_id']
        attack = _attack_mean(cells, 'D3', point_id)
        normal_checks = []
        for unit in UNITS:
            for condition in CONDITIONS:
                baseline = _at(cells, 'D2', unit, condition)['losses']['normal']
                actual = _at(cells, 'D3', unit, condition, point_id)['losses']['normal']
                tolerance = _number(max(1e-8, 10 * _loss_noise(cells, unit, condition, 'normal')), 'derived.normal_tolerance', True)
                limit = _number(baseline + tolerance, 'derived.normal_limit', True)
                normal_checks.append(dict(unit_id=unit, condition_id=condition, baseline=baseline,
                                          actual=actual, limit=limit, passed=actual <= limit))
        passed = naive - attack >= margin and all(check['passed'] for check in normal_checks)
        local.append(dict(point_id=point_id, coefficients=point['coefficients'], attack_mean=attack,
                          attack_improvement=naive - attack, required_improvement=margin,
                          normal_checks=normal_checks, passed=passed))
        if passed:
            eligible.append(point_id)
    if not eligible:
        failures.append(_failure('no_local_normal_feasible_direction', fixed_points=[p['point_id'] for p in local]))
    return failures, {'gradient_components': components, 'finite_difference_estimates': 56,
                      'AD_components': 28, 'aggregate_attack_gradient': aggregate,
                      'local_points': local, 'locally_eligible_points': eligible,
                      'point_selection_or_training_performed': False}


def evaluate_stages(stage_records):
    """Evaluate a complete stage prefix without requiring later-stage records."""
    _require(type(stage_records) is dict, 'stages', 'expected stage -> list mapping')
    _require(all(stage in STAGES for stage in stage_records), 'stages', 'unknown stage')
    present = [stage for stage in STAGES if stage in stage_records]
    _require(present == list(STAGES[:len(present)]), 'stages', 'must be consecutive prefix from D0')
    cells = {stage: validate_stage(stage, stage_records[stage]) for stage in present}
    operations = [cell for stage in present for cell in cells[stage].values()]
    report = {'schema_version': SCHEMA_VERSION, 'status': 'not_started', 'through_stage': None,
              'next_stage': 'D0', 'can_continue': False, 'complete': False,
              'stages': [], 'failures': [], 'resource_totals': budget_totals(operations),
              'full_budget': budget_totals(), 'scientific_effectiveness_established': False,
              'runtime_identity_GPU_and_wall_time_verified': False}
    for stage in present:
        failures, metrics = [], {}
        if stage == 'D1':
            failures, metrics = _identity(cells)
        elif stage == 'D2r':
            failures, metrics = _repeat_signal_polarity(cells)
        elif stage == 'D3':
            failures, metrics = _gradient_and_local(cells)
        report['stages'].append(dict(stage=stage, passed=not failures, metrics=metrics, failures=failures))
        report['through_stage'] = stage
        if failures:
            report.update(status='fail', next_stage=None, can_continue=False, failures=failures)
            return report
    if present:
        complete = present[-1] == 'D3'
        report.update(status='diagnostic_pass' if complete else 'prefix_pass', complete=complete,
                      can_continue=not complete, next_stage=None if complete else STAGES[len(present)])
    return report


def check_stage(stage, records, prior_records=None):
    """Same report as evaluate_stages; never fills missing prior stages."""
    _require(stage in STAGES, 'stage', 'unknown stage')
    prior_records = {} if prior_records is None else prior_records
    _require(type(prior_records) is dict, 'prior_records', 'expected mapping')
    _require(set(prior_records) == set(STAGES[:STAGES.index(stage)]), 'prior_records', 'exact earlier stages required')
    return evaluate_stages(dict(prior_records, **{stage: records}))
