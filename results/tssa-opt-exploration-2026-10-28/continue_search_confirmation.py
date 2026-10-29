#!/usr/bin/env python3
"""One-shot same-run confirmation continuation; default is local-only preparation.

No budget override, incomplete-operation replay, new experiment or cross-host
copy is supported. Old launch/recovery evidence is only read, never replaced.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shlex
import subprocess
import sys
import uuid

GUARD_SHA = 'f80feba9f750a98c3726ebecf93f4a56a6e0e315197f4ef1ba39eba8744b57b4'
GATE_SHA = '4367596dd1d90dfb733cecb9b87cfae90de2dd0eaad3553f308cf85690f031ce'
PLAN_SHA = '8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6'
IDENTITY_SHA = 'd95475cd4f8067ad78e28b2aad1cf1c968d3b7c995930790b2687c053752c814'
LEDGER_SHA = 'b56a4b6659d7405cda14bc9de35da5a1fb2ef672f177f93547d37b779a9d3c1e'
RECOVERY = 'manual-recovery-0e39df5be0cd73d07934fe529fc310cfd651f21d955276fc55b5200615f00c66'
CLAIM_NAME = 'confirmation-' + PLAN_SHA + '.claim.json'
LOCAL_OLD = {
    'image-search-' + PLAN_SHA + '.claim.json': '28fccab1bc13280c81a1941dff55101b0ac557bb77e03d9bde3a99c9f5000a3e',
    RECOVERY + '.claim.json': '21a19221f284d1d2769378089b3464dc2414826c8849c6c2e640808c194d2809'}
REMOTE_OLD = {
    'image-search-' + PLAN_SHA + '.claim.json': '76bcefb5026fa9f0789f7821ab5230b1ca5ec78b69ac72981ec4c7dfc2a4e76f',
    '20261028T085903540293Z-a30eabe75cc0446cbdb059151c056892.receipt.json': 'd95255ad6711abae2c204ecd531711ad3034113b8b89b7140bec2cd5fd4335c9',
    RECOVERY + '.claim.json': LEDGER_SHA, RECOVERY + '.ledger.json': LEDGER_SHA,
    RECOVERY + '.original-started.json': 'a0d2562580ad355a4cf0bd84a85f15d35db3a88dee6ca3387b1ee45af91e4419',
    RECOVERY + '-8ae15c9dc62142e997c1a9b586313653.receipt.json': '7e2e6ee983f7eb9decd82160912f87f028ecb9f8130ba2de42e6cc8793884d71'}
DEPLOYMENT = 'deployment_20261028T085259Z.json'
DEPLOYMENT_SHA = '873fcb49ab565dec9d1ffdfe728d7e6a49cf34fb80855545a01daffac87c8572'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def load_module(path, expected):
    require(sha(path) == expected, 'Reviewed helper changed: ' + str(path))
    spec = importlib.util.spec_from_file_location('_confirmation_' + Path(path).stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def guards():
    if 'GUARDS' not in globals():
        globals()['GUARDS'] = load_module(Path(__file__).with_name('launch_image_search.py'), GUARD_SHA)
    return globals()['GUARDS']


def fixed(path, expected):
    guards().owned_real(path)
    require(path.is_file() and sha(path) == expected, 'Evidence hash mismatch: ' + str(path))
    return json.loads(path.read_text())


def absent(path):
    require(not path.exists() and not path.is_symlink(), 'Existing evidence/claim prevents another launch: ' + str(path))


def validate_decision(decision):
    require(decision.get('status') == 'snapshot_ready_for_live_start_checks'
            and decision.get('plan_sha256') == PLAN_SHA and decision.get('GPU_start_authorized') is False,
            'Complete independently audited development and budget readiness required')
    k = decision.get('selected_search_count')
    require(type(k) is int and k in (1, 2), 'Full confirmation exceeds frozen budget with three promotions')
    count = 624 + 48 * (k + 2)
    require(decision.get('completed_images') == count and decision.get('current_started') == 0
            and decision.get('archived_failed_attempts') == 1 and decision.get('archived_failed_NFE_upper_bound') == 50
            and decision.get('confirm_images') == 576 and decision.get('final_attempts_with_failure') == count + 577
            and decision.get('final_generation_branch_NFE_upper_bound') == 50 * (count + 577), 'Confirmation accounting changed')
    require(decision.get('budget_attempt_cap') == 1440 and decision.get('budget_generation_branch_NFE_cap') == 72000,
            'Frozen cap changed')


def local_prepare(root, observation, permission_path=None):
    g = guards()
    out = root / 'results/tssa-opt-exploration-2026-10-28'
    gate = load_module(out / 'check_confirmation_budget.py', GATE_SHA)
    decision = gate.run(observation)
    payload = {'server': '103', 'plan_sha256': PLAN_SHA, 'identity_sha256': IDENTITY_SHA,
               'decision': decision, 'guard_sha256': GUARD_SHA, 'budget_gate_sha256': GATE_SHA}
    if decision['status'] != 'snapshot_ready_for_live_start_checks':
        return payload
    validate_decision(decision)
    raw = json.loads(Path(observation).read_text())
    require(raw.get('server') == '103' and raw['result'].get('server') == '103', 'Only the existing 103 run may continue')
    require(raw['result'].get('launch_process_now', {}).get('exists') is False,
            'Original recovered process exit is not observed')
    plan = fixed(root / g.PLAN_REL, PLAN_SHA)
    deployment = fixed(out / DEPLOYMENT, DEPLOYMENT_SHA)
    code, expected = g.validate_deployment(deployment, plan, '103')
    for name, expected_sha in expected.items():
        g.owned_real(root / name)
        require(sha(root / name) == expected_sha, 'Frozen local source changed: ' + name)
    control = out / 'launch-control'
    g.owned_real(control)
    absent(control / CLAIM_NAME)
    for name, expected_sha in LOCAL_OLD.items():
        fixed(control / name, expected_sha)
    # The pinned auditor already verified these exact transported JSON objects.
    files = {name[4:]: item['sha256'] for name, item in raw['result']['files'].items()
             if name.startswith('run/') and (name in ('run/identity.json', 'run/plan.json',
                 'run/search_summary.json', 'run/search_selection.json', 'run/dev_summary.json', 'run/dev_selection.json')
                 or name.startswith(('run/operations/', 'run/executions/')))}
    for name, expected_sha in files.items():
        require(sha(Path(observation).parent / 'artifacts/run' / name) == expected_sha, 'Copied evidence changed')
    require(sha(observation) == decision['observation_sha256'], 'Observation changed during preparation')
    permission = None if permission_path is None else json.loads(Path(permission_path).read_text())
    if permission is not None:
        g.validate_permission(permission, '103')
    payload.update(code_root=code, deployment=deployment, expected_files=expected,
                   run_files=files, observation_sha256=decision['observation_sha256'],
                   permission=permission, permission_sha256=None if permission is None else sha(permission_path))
    return payload


def safe_run_file(run, name):
    relative = Path(name)
    require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe run evidence path')
    path = run / relative
    for item in (path, *path.parents):
        if item == run.parent:
            break
        require(not item.is_symlink() and item.stat().st_uid == os.getuid(), 'Redirected or unowned run artifact')
    require(path.resolve().is_relative_to(run) and path.is_file(), 'Run evidence missing/outside run')
    return path


def verify_inventory(run, plan, payload, runner):
    """Read all committed receipts/PNG bytes under the run lock; never replay."""
    files = payload['run_files']
    required = {'identity.json', 'plan.json', 'search_summary.json', 'search_selection.json', 'dev_summary.json', 'dev_selection.json'}
    require(required <= set(files), 'Development commitment is missing')
    for name, expected_sha in files.items():
        require(sha(safe_run_file(run, name)) == expected_sha, 'Remote artifact changed: ' + name)
    identity = json.loads((run / 'identity.json').read_text())
    require(digest(identity) == IDENTITY_SHA, 'Run identity changed')
    for name in ('confirm_binding.json', 'confirm_summary.json', 'confirm_selection.json', 'final_report.json', 'images/confirm'):
        absent(run / name)
    def envelope(name):
        obj = json.loads((run / name).read_text())
        require(obj.get('identity_sha256') == IDENTITY_SHA and obj.get('sha256') == digest(obj.get('payload')), 'Artifact envelope mismatch')
        return obj['payload']
    require(envelope('plan.json') == plan, 'Stored frozen plan changed')
    actual_ops = set((run / 'operations').iterdir())
    require({str(p.relative_to(run)) for p in actual_ops} == {n for n in files if n.startswith('operations/')}, 'Extra or missing operation file')
    records, expected_ids, expected_images, names = [], set(), set(), ['clean'] + list(plan['candidates'])
    for stage in ('search', 'dev'):
        stage_records = []
        for condition in plan['stages'][stage]['conditions']:
            for name in names:
                for row in plan['stages'][stage]['rows']:
                    task = {'stage': stage, 'candidate': name, 'condition': condition, 'row': row,
                            'coefficients': [0, 0] if name == 'clean' else plan['candidates'][name]}
                    tid = digest(task); expected_ids.add(tid)
                    receipt = json.loads(safe_run_file(run, 'operations/' + tid + '.json').read_text())
                    require(receipt.get('status') == 'completed' and receipt.get('task') == task
                            and receipt.get('task_id') == tid and receipt.get('identity_sha256') == IDENTITY_SHA,
                            'Unfinished or mismatched receipt; manual audit required')
                    record = receipt['record']
                    require(receipt.get('record_sha256') == digest(record), 'Scored record changed')
                    image_path = 'images/{}/{}/{}/{}.png'.format(stage, condition['id'], name, row['id'])
                    expected_images.add(image_path)
                    require(record['image_path'] == image_path and sha(safe_run_file(run, image_path)) == record['image_sha256'], 'PNG integrity failed')
                    stage_records.append(record)
        summary = runner.summarize(plan, stage, names, stage_records)
        require(summary == envelope(stage + '_summary.json'), 'Completed stage summary changed')
        selection = runner.select(plan, stage, summary)
        require(selection == envelope(stage + '_selection.json') and selection['selected'], 'Committed promotion changed/empty')
        if stage == 'search':
            require(len(selection['selected']) == payload['decision']['selected_search_count'], 'Search count changed')
        else:
            require(selection['selected'] == [payload['decision']['winner']]
                    and selection['coefficients'][selection['selected'][0]] == payload['decision']['winner_coefficients'], 'Development winner changed')
        names = ['clean', 'naive'] + selection['selected']
        records.extend(stage_records)
    require({p.stem for p in actual_ops} == expected_ids and len(records) == payload['decision']['completed_images'], 'Receipt inventory disagrees with audited budget')
    image_inventory = set()
    for path in (run / 'images').rglob('*'):
        require(not path.is_symlink(), 'Redirected image inventory')
        if path.is_file():
            image_inventory.add(str(path.relative_to(run)))
    require(image_inventory == expected_images, 'Extra or missing image without matching completed receipt')
    return {'completed_receipts_and_PNGs_verified': len(records), 'dev_selection_sha256': digest(selection),
            'input_inventory_sha256': digest(files)}


def command(base, code, run):
    argv = guards().runner_command(base, code, run)
    require(argv[-2:] == ['--until', 'confirm'], 'Reviewed command changed')
    return argv[:-2] + ['--resume', '--until', 'confirm']


def remote_continue(payload):
    g = guards()
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64'
            and pwd.getpwuid(os.getuid()).pw_name == 'zhangzibo' and os.getuid() != 0, 'Wrong host/account')
    require(payload['server'] == '103' and payload['plan_sha256'] == PLAN_SHA and payload['identity_sha256'] == IDENTITY_SHA
            and payload['guard_sha256'] == GUARD_SHA and payload['budget_gate_sha256'] == GATE_SHA, 'Wrong continuation identity')
    validate_decision(payload['decision'])
    g.validate_permission(payload['permission'], '103')
    base, code = Path(g.BASES['103']), Path(payload['code_root'])
    run, control = base / 'results' / g.RUN_NAME, base / 'launch-control'
    for path in (base, code, run, control):
        g.owned_real(path)
    require(base.stat().st_dev != Path('/').stat().st_dev, 'Data root is on system disk')
    plan = fixed(code / g.PLAN_REL, PLAN_SHA)
    checked_code, expected = g.validate_deployment(payload['deployment'], plan, '103')
    require(checked_code == str(code) and expected == payload['expected_files'], 'Deployment changed')
    for name, value in expected.items():
        g.owned_real(code / name)
        require(sha(code / name) == value, 'Remote frozen source changed')
    python = base / 'venv/bin/python'
    require(python.is_file() and os.access(python, os.X_OK) and g.beneath(python.resolve(), base.parent)
            and python.resolve().stat().st_uid == os.getuid(), 'Prepared owned Python unavailable')
    for relative in ('results', 'tmp', 'cache', 'cache/huggingface', 'cache/torch', 'cache/triton', 'models'):
        g.owned_real(base / relative)
        require((base / relative).is_dir(), 'Prepared runtime directory missing: ' + relative)
    runner = load_module(code / 'scripts/merging/tssa_image_search_run.py', plan['source_hashes']['tssa_image_search_run.py'])
    claim, run_lock = control / CLAIM_NAME, run / '.run.lock'
    launch_lock = control / ('image-search-' + PLAN_SHA + '.lock')
    for path in (run_lock, launch_lock):
        g.owned_real(path)
    absent(claim)
    require(not g.active_search_processes(), 'An image search process is still active')
    with launch_lock.open('r+') as lock, run_lock.open('r+') as held_run:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(held_run, fcntl.LOCK_EX | fcntl.LOCK_NB)
        absent(claim)
        for name, value in REMOTE_OLD.items():
            fixed(control / name, value)
        verified = verify_inventory(run, plan, payload, runner)
        g.validate_permission(payload['permission'], '103')
        sample = subprocess.run(['nvidia-smi', '-q', '-x'], check=True, capture_output=True, text=True, timeout=15)
        gpu = g.inspect_gpu(sample.stdout, payload['permission'], '103', own_uid=os.getuid())
        require(not g.active_search_processes(), 'Search became active during preflight')
        g.validate_permission(payload['permission'], '103')
        token = payload['token']
        require(re.fullmatch('[0-9a-f]{32}', token) is not None, 'Invalid continuation token')
        prefix = 'confirmation-' + PLAN_SHA + '-' + token
        log_path, receipt_path = control / (prefix + '.log'), control / (prefix + '.receipt.json')
        absent(log_path); absent(receipt_path)
        argv = command(base, code, run)
        receipt = {'schema_version': 1, 'at': g.utcnow().isoformat(), 'server': '103', 'confirmation_token': token,
                   'plan_sha256': PLAN_SHA, 'identity_sha256': IDENTITY_SHA, 'run_root': str(run),
                   'guard_sha256': GUARD_SHA, 'budget_gate_sha256': GATE_SHA, 'continuation_sha256': payload['continuation_sha256'],
                   'permission_sha256': payload['permission_sha256'], 'observation_sha256': payload['observation_sha256'],
                   'budget_decision': payload['decision'], 'old_evidence_hashes_preserved': REMOTE_OLD,
                   'verified': verified, 'gpu': gpu, 'command': argv, 'log': str(log_path), 'receipt': str(receipt_path),
                   'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                   'status': 'confirmation_claimed_before_spawn', 'automatic_retry_allowed': False}
        g.exclusive_json(claim, receipt)
        for name, value in REMOTE_OLD.items():
            fixed(control / name, value)
        require(not g.active_search_processes(), 'Search became active before spawn')
        g.validate_permission(payload['permission'], '103')
        fcntl.flock(held_run, fcntl.LOCK_UN)
        with log_path.open('xb') as log:
            child = subprocess.Popen(argv, cwd=code, env=g.runner_environment(base, payload['permission']['gpu_uuid']),
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True, close_fds=True)
        try:
            ticks = (Path('/proc') / str(child.pid) / 'stat').read_text().rsplit(')', 1)[1].split()[19]
        except FileNotFoundError:
            ticks = None
        receipt.update(status='runner_process_spawned_not_GPU_acceptance', pid=child.pid,
                       started_at=g.utcnow().isoformat(), process_start_ticks=ticks)
        g.exclusive_json(receipt_path, receipt)
        return receipt


def remote_program(source, guard_source, payload):
    require(hashlib.sha256(guard_source.encode()).hexdigest() == GUARD_SHA
            and hashlib.sha256(source.encode()).hexdigest() == payload['continuation_sha256'], 'Transmitted source hash mismatch')
    return ("import json,types\ng={'__name__':'_guards'}\nexec(" + repr(guard_source) + ",g)\n"
            "n={'__name__':'_confirmation','GUARDS':types.SimpleNamespace(**g)}\nexec(" + repr(source) + ",n)\n"
            "print(json.dumps(n['remote_continue'](json.loads(" + repr(json.dumps(payload, ensure_ascii=False)) + ")),ensure_ascii=False),flush=True)\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('observation', type=Path)
    parser.add_argument('--permission', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    source_path = Path(__file__).resolve()
    root, out = source_path.parents[2], source_path.parent
    payload = local_prepare(root, args.observation, args.permission)
    if not args.execute:
        print(json.dumps({'mode': 'prepared_local_only_no_connection', 'decision': payload['decision'],
                          'remote_state_verified': False, 'GPU_start_authorized': False,
                          'actual_confirmation_started': False}, ensure_ascii=False, indent=2))
        return 0
    validate_decision(payload['decision'])
    require(args.permission is not None and payload.get('permission') is not None, '--execute requires fresh three-view permission')
    g = guards()
    control = out / 'launch-control'
    lock_path, claim = control / ('image-search-' + PLAN_SHA + '.lock'), control / CLAIM_NAME
    g.owned_real(lock_path)
    with lock_path.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        absent(claim)
        for name, value in LOCAL_OLD.items():
            fixed(control / name, value)
        g.validate_permission(payload['permission'], '103')
        payload.update(token=uuid.uuid4().hex, continuation_sha256=sha(source_path))
        record = {'at': g.utcnow().isoformat(), 'server': '103', 'confirmation_token': payload['token'],
                  'plan_sha256': PLAN_SHA, 'identity_sha256': IDENTITY_SHA, 'decision': payload['decision'],
                  'observation_sha256': payload['observation_sha256'], 'permission_sha256': payload['permission_sha256'],
                  'continuation_sha256': payload['continuation_sha256'], 'budget_gate_sha256': GATE_SHA,
                  'old_local_claim_hashes_preserved': LOCAL_OLD,
                  'status': 'confirmation_claimed_before_connection', 'automatic_retry_allowed': False}
        g.exclusive_json(claim, record)
        report = dict(record)
        try:
            sys.path.insert(0, str(root / 'server'))
            from stage_school_assets import SchoolSession
            with SchoolSession() as session:
                program = remote_program(source_path.read_text(), source_path.with_name('launch_image_search.py').read_text(), payload)
                remote_command = shlex.join([g.BASES['103'] + '/venv/bin/python', '-I', '-'])
                result = subprocess.run(['ssh', '-F', str(session.config), '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                                         'school103', remote_command], input=program, capture_output=True, text=True, timeout=120)
                report.update(returncode=result.returncode, stderr=result.stderr[-5000:])
                if result.returncode == 0:
                    remote = json.loads(result.stdout)
                    require(remote.get('confirmation_token') == payload['token'] and remote.get('plan_sha256') == PLAN_SHA
                            and remote.get('status') == 'runner_process_spawned_not_GPU_acceptance', 'Unexpected continuation receipt')
                    raw = (json.dumps(remote, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
                    report.update(status=remote['status'], remote=remote, remote_receipt_sha256=hashlib.sha256(raw).hexdigest())
                else:
                    report.update(status='remote_failed_or_unknown_manual_audit_required', stdout=result.stdout[-5000:])
        except Exception as exc:
            report.update(status='connection_or_spawn_unknown_manual_audit_required', error=type(exc).__name__ + ': ' + str(exc))
        report['finished_at'] = g.utcnow().isoformat()
        result_path = control / ('confirmation-' + PLAN_SHA + '-' + payload['token'] + '.result.json')
        g.exclusive_json(result_path, report)
        print(json.dumps(dict(result_path=str(result_path), **report), ensure_ascii=False, indent=2))
        return 0 if report['status'] == 'runner_process_spawned_not_GPU_acceptance' else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'status': 'refused', 'error': type(exc).__name__ + ': ' + str(exc),
                          'automatic_retry_allowed': False}), file=sys.stderr)
        sys.exit(2)
