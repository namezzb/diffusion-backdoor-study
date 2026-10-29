#!/usr/bin/env python3
"""One manually audited recovery of the 103 reboot; default never connects.

Preserves both old claims and the exact started receipt outside the run. Original
scientific source/identity stay unchanged. This is not a retry loop or permission
to enter confirmation; the only child command is --resume --until dev.
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
PLAN_SHA = '8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6'
IDENTITY_SHA = 'd95475cd4f8067ad78e28b2aad1cf1c968d3b7c995930790b2687c053752c814'
PENDING = '0e39df5be0cd73d07934fe529fc310cfd651f21d955276fc55b5200615f00c66'
PENDING_SHA = 'a0d2562580ad355a4cf0bd84a85f15d35db3a88dee6ca3387b1ee45af91e4419'
BOOT_ID = '1c2bddf4-f594-43cf-8a4d-5b116ad79067'
GPU_UUID = 'GPU-a00d7f16-dee6-f32a-eb89-dde4590ba523'
OLD_PID = 188034
OLD_TOKEN = 'a30eabe75cc0446cbdb059151c056892'
OLD_LOCAL_CLAIM_SHA = '28fccab1bc13280c81a1941dff55101b0ac557bb77e03d9bde3a99c9f5000a3e'
OLD_REMOTE_CLAIM_SHA = '76bcefb5026fa9f0789f7821ab5230b1ca5ec78b69ac72981ec4c7dfc2a4e76f'
OLD_REMOTE_RECEIPT_SHA = 'd95255ad6711abae2c204ecd531711ad3034113b8b89b7140bec2cd5fd4335c9'
DEPLOYMENT = 'deployment_20261028T085259Z.json'
DEPLOYMENT_SHA = '873fcb49ab565dec9d1ffdfe728d7e6a49cf34fb80855545a01daffac87c8572'
INTERRUPTION = 'interruption_audit_20261028T100126659566Z.json'
INTERRUPTION_SHA = '4aa0f21d1fe326f6ee8e4f9a1ec3a4df5c922a8f78f5fb954c927ea378b74ce2'
RECOVERY_NAME = 'manual-recovery-' + PENDING


def guards():
    if 'GUARDS' in globals():
        return globals()['GUARDS']
    path = Path(__file__).with_name('launch_image_search.py')
    require(hash_file(path) == GUARD_SHA, 'Reviewed launcher guards changed')
    spec = importlib.util.spec_from_file_location('_reviewed_launch_guards', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    globals()['GUARDS'] = module
    return module


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def hash_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def fixed_file(path, sha):
    guards().owned_real(path)
    require(path.is_file() and hash_file(path) == sha, 'Fixed evidence mismatch: ' + str(path))
    return json.loads(path.read_text())


def recovery_budget():
    return {'failed_attempts': 1, 'failed_branch_NFE_upper_bound': 50,
            'failed_text_encoder_forwards_upper_bound': 1, 'failed_VAE_decodes_upper_bound': 1,
            'failed_work_exact_count': None, 'failure_replayed_at_most_once': True,
            'completed_unique_images_before': 171, 'scientific_updates': 0,
            'until_dev_unique_images_upper_bound': 864, 'until_dev_attempts_upper_bound': 865,
            'until_dev_branch_NFE_upper_bound_including_failure': 43250,
            'global_attempt_cap_conservative': 1440, 'global_branch_NFE_cap': 72000,
            'confirmation_permitted_by_this_wrapper': False,
            'confirmation_total_if_search_promotes': {
                '1': {'attempts_upper_bound': 1345, 'branch_NFE_upper_bound': 67250},
                '2': {'attempts_upper_bound': 1393, 'branch_NFE_upper_bound': 69650},
                '3': {'attempts_upper_bound': 1441, 'branch_NFE_upper_bound': 72050}},
            'later_confirmation_requires_separate_budget_audit': True}


def validate_proof(proof):
    require(proof.get('read_only') is True and proof.get('server') == '103' and proof.get('returncode') == 0,
            'Interruption proof did not succeed')
    r = proof['remote']
    require(r.get('old_pid_exists') is False and r.get('boot_id') == BOOT_ID
            and r.get('GPU_initialized') is False and r.get('errors') == [], 'Wrong/unresolved interruption')
    require(r.get('receipt_count') == 172 and r.get('completed_PNG_hashes_verified') == 171
            and r.get('scientific_files_modified') is False, 'Wrong interruption inventory')
    require(len(r['incomplete']) == 1 and r['incomplete'][0]['task_id'] == PENDING
            and r['incomplete'][0]['receipt']['sha256'] == PENDING_SHA
            and r['incomplete'][0]['receipt_status'] == 'started'
            and r['incomplete'][0]['image_exists'] is False, 'Pending attempt proof differs')
    completed = r['completed_pngs']
    require(len(completed) == 171 and len({x['task_id'] for x in completed}) == 171, 'Duplicate/missing completed proof')
    require(all(x['receipt_status'] == 'completed' and x['image_exists'] is True
                and x['matches_recorded_image_hash'] is True for x in completed), 'Incomplete PNG proof')
    return {x['task_id']: {'receipt_sha256': x['receipt']['sha256'], 'image_path': x['image_path'],
                         'image_sha256': x['image']['sha256']} for x in completed}


def local_prepare(root, permission_path=None):
    g = guards()
    out = root / 'results/tssa-opt-exploration-2026-10-28'
    plan = fixed_file(root / g.PLAN_REL, PLAN_SHA)
    deployment = fixed_file(out / DEPLOYMENT, DEPLOYMENT_SHA)
    proof = fixed_file(out / INTERRUPTION, INTERRUPTION_SHA)
    completed = validate_proof(proof)
    code, expected_files = g.validate_deployment(deployment, plan, '103')
    for name, sha in expected_files.items():
        fixed_file_or_hash(root / name, sha)
    control = out / 'launch-control'
    g.owned_real(control)
    fixed_file(control / ('image-search-' + PLAN_SHA + '.claim.json'), OLD_LOCAL_CLAIM_SHA)
    require(not (control / (RECOVERY_NAME + '.claim.json')).exists(), 'Permanent local recovery claim exists; no retry')
    old_result = json.loads((control / (OLD_TOKEN + '.result.json')).read_text())
    require(old_result.get('token') == OLD_TOKEN and old_result.get('server') == '103'
            and old_result.get('remote', {}).get('pid') == OLD_PID
            and old_result['remote'].get('run_root') == g.BASES['103'] + '/results/' + g.RUN_NAME,
            'Original local spawn provenance differs')
    permission = None
    if permission_path is not None:
        raw = Path(permission_path).read_bytes()
        permission = json.loads(raw)
        validate_permission(permission)
        permission_sha = hashlib.sha256(raw).hexdigest()
    else:
        permission_sha = None
    return {'server': '103', 'plan_sha256': PLAN_SHA, 'identity_sha256': IDENTITY_SHA,
            'code_root': code, 'deployment': deployment, 'deployment_sha256': DEPLOYMENT_SHA,
            'expected_files': expected_files, 'interruption_sha256': INTERRUPTION_SHA,
            'completed': completed, 'original_pending': proof['remote']['incomplete'][0],
            'old_boot_evidence': {k: proof['remote'][k] for k in ('boot_id', 'btime', 'kernel', 'nvidia_kernel_version')},
            'old_remote_spawn': old_result['remote'], 'permission': permission,
            'permission_sha256': permission_sha, 'guard_sha256': GUARD_SHA,
            'budget': recovery_budget(), 'automatic_retry_allowed': False}


def fixed_file_or_hash(path, sha):
    guards().owned_real(path)
    require(path.is_file() and hash_file(path) == sha, 'Prepared source changed: ' + str(path))


def validate_permission(permission):
    guards().validate_permission(permission, '103')
    require(permission['gpu_index'] == 0 and permission['gpu_uuid'] == GPU_UUID,
            'This recovery is fixed to the original 103 GPU0 UUID')


def command(base, code, run):
    argv = guards().runner_command(base, code, run)
    require(argv[-2:] == ['--until', 'confirm'], 'Reviewed original command changed')
    return argv[:-2] + ['--resume', '--until', 'dev']


def expected_prefix(plan):
    tasks = []
    block = plan['stages']['search']
    for condition in block['conditions']:
        for name in ['clean'] + list(plan['candidates']):
            for row in block['rows']:
                tasks.append({'stage': 'search', 'candidate': name, 'condition': condition, 'row': row,
                              'coefficients': [0, 0] if name == 'clean' else plan['candidates'][name]})
    require(digest(tasks[171]) == PENDING, 'Frozen serial prefix no longer matches pending task')
    return {digest(t): t for t in tasks[:171]}, tasks[171]


def verify_inventory(run, plan, payload):
    """Only read files; must be called while the old run lock is held."""
    g = guards()
    g.owned_real(run)
    fixed_file(run / 'identity.json', IDENTITY_SHA)
    expected, pending_task = expected_prefix(plan)
    require(set(payload['completed']) == set(expected), 'Interruption is not the exact completed serial prefix')
    operations = run / 'operations'
    g.owned_real(operations)
    files = list(operations.iterdir())
    require({x.name for x in files} == {t + '.json' for t in expected} | {PENDING + '.json'},
            'Operations changed or an unknown temporary receipt exists')
    for task_id, task in expected.items():
        evidence = payload['completed'][task_id]
        receipt = fixed_file(operations / (task_id + '.json'), evidence['receipt_sha256'])
        require(receipt.get('status') == 'completed' and receipt.get('identity_sha256') == IDENTITY_SHA
                and receipt.get('task_id') == task_id and digest(receipt.get('task')) == task_id
                and canonical(receipt['task']) == canonical(task), 'Completed task identity mismatch')
        record = receipt['record']
        require(receipt.get('record_sha256') == digest(record), 'Completed record hash mismatch')
        for key, value in {'task_id': task_id, 'stage': 'search', 'candidate': task['candidate'],
                           'condition_id': task['condition']['id'], 'row': task['row'],
                           'coefficients': task['coefficients']}.items():
            require(canonical(record.get(key)) == canonical(value), 'Completed record/task disagreement: ' + key)
        relative = Path(record['image_path'])
        frozen_image = 'images/search/{}/{}/{}.png'.format(task['condition']['id'], task['candidate'], task['row']['id'])
        require(not relative.is_absolute() and '..' not in relative.parts
                and str(relative) == evidence['image_path'] == frozen_image
                and record['image_sha256'] == evidence['image_sha256'],
                'PNG provenance disagreement')
        fixed_file_or_hash(run / relative, evidence['image_sha256'])
    pending_path = operations / (PENDING + '.json')
    pending = fixed_file(pending_path, PENDING_SHA)
    require(pending.get('status') == 'started' and pending.get('identity_sha256') == IDENTITY_SHA
            and pending.get('task_id') == PENDING and canonical(pending.get('task')) == canonical(pending_task)
            and 'record' not in pending, 'Pending receipt is not the exact unfinished task')
    frozen_pending_image = 'images/search/{}/{}/{}.png'.format(pending_task['condition']['id'], pending_task['candidate'], pending_task['row']['id'])
    require(payload['original_pending']['image_path'] == frozen_pending_image, 'Pending image path changed')
    pending_image = run / frozen_pending_image
    require(not pending_image.exists() and not pending_image.is_symlink(), 'Pending PNG now exists; manual re-audit required')
    require(not list(pending_image.parent.glob('.' + pending_image.name + '*')),
            'Uncommitted pending PNG temporary file exists; preserve and re-audit')
    for name in ('search_summary.json', 'search_selection.json', 'dev_summary.json', 'dev_selection.json',
                 'confirm_binding.json', 'confirm_summary.json', 'confirm_selection.json', 'final_report.json'):
        require(not (run / name).exists(), 'Unexpected committed later-stage artifact: ' + name)
    return pending_path, pending


def check_boot_and_processes():
    require(Path('/proc/sys/kernel/random/boot_id').read_text().strip() == BOOT_ID,
            'Boot changed since manual audit')
    require(not (Path('/proc') / str(OLD_PID)).exists(), 'Original PID exists or was reused; manual re-audit required')
    require(not guards().active_search_processes(), 'Another image-search process exists')


def archive_exact_pending(source, archive, original_sha):
    """Archive+fsync+verify first, then remove only this exact started path."""
    g = guards()
    require(hash_file(source) == original_sha, 'Pending changed before archival')
    raw = source.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == original_sha, 'Pending changed while reading')
    fd = os.open(str(archive), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    g.fsync_directory(archive.parent)
    g.fsync_directory(archive.parent.parent)
    require(hash_file(archive) == original_sha and hash_file(source) == original_sha, 'Archive verification failed')
    source.unlink()
    g.fsync_directory(source.parent)


def remote_recover(payload):
    g = guards()
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64'
            and pwd.getpwuid(os.getuid()).pw_name == 'zhangzibo' and os.getuid() != 0, 'Wrong host/account')
    require(payload['plan_sha256'] == PLAN_SHA and payload['identity_sha256'] == IDENTITY_SHA
            and payload['guard_sha256'] == GUARD_SHA and payload['interruption_sha256'] == INTERRUPTION_SHA,
            'Recovery payload identity mismatch')
    require(payload['budget'] == recovery_budget(), 'Recovery budget altered')
    validate_permission(payload['permission'])
    base = Path(g.BASES['103'])
    code = Path(payload['code_root'])
    run = base / 'results' / g.RUN_NAME
    control = base / 'launch-control'
    for path in (base, code, run, control):
        g.owned_real(path)
    require(base.stat().st_dev != Path('/').stat().st_dev, 'Data root is on system disk')
    plan = fixed_file(code / g.PLAN_REL, PLAN_SHA)
    actual_code, expected = g.validate_deployment(payload['deployment'], plan, '103')
    require(actual_code == str(code) and expected == payload['expected_files'], 'Deployment changed')
    for name, sha in expected.items():
        fixed_file_or_hash(code / name, sha)
    python = base / 'venv/bin/python'
    require(python.is_file() and os.access(python, os.X_OK), 'Prepared Python missing')
    require(g.beneath(python.resolve(), base.parent) and python.resolve().stat().st_uid == os.getuid(),
            'Python is not in own prepared data environment')
    for relative in ('results', 'tmp', 'cache', 'cache/huggingface', 'cache/torch', 'cache/triton', 'models'):
        g.owned_real(base / relative)
        require((base / relative).is_dir(), 'Prepared data directory missing: ' + relative)
    original_claim = control / ('image-search-' + PLAN_SHA + '.claim.json')
    fixed_file(original_claim, OLD_REMOTE_CLAIM_SHA)
    original_receipt = Path(payload['old_remote_spawn']['launch_receipt'])
    require(original_receipt.parent == control, 'Original receipt is outside launch-control')
    old_spawn = fixed_file(original_receipt, OLD_REMOTE_RECEIPT_SHA)
    require(old_spawn.get('pid') == OLD_PID and old_spawn.get('launch_token') == OLD_TOKEN
            and old_spawn.get('gpu', {}).get('uuid') == GPU_UUID, 'Original spawn differs')
    check_boot_and_processes()
    claim = control / (RECOVERY_NAME + '.claim.json')
    require(not claim.exists() and not claim.is_symlink(), 'Remote recovery claim exists; no automatic retry')
    launch_lock = control / ('image-search-' + PLAN_SHA + '.lock')
    run_lock = run / '.run.lock'
    for path in (launch_lock, run_lock):
        g.owned_real(path)
    with launch_lock.open('r+') as lock, run_lock.open('r+') as held_run:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(held_run, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not claim.exists(), 'Concurrent recovery already claimed')
        pending_path, pending = verify_inventory(run, plan, payload)
        check_boot_and_processes()
        validate_permission(payload['permission'])
        sample = subprocess.run(['nvidia-smi', '-q', '-x'], check=True, capture_output=True, text=True, timeout=15)
        gpu = g.inspect_gpu(sample.stdout, payload['permission'], '103', own_uid=os.getuid())
        require(gpu['driver'] == '595.99.02', 'Driver changed after reboot audit')
        token = payload['token']
        require(re.fullmatch('[0-9a-f]{32}', token) is not None, 'Invalid recovery token')
        archive = control / (RECOVERY_NAME + '.original-started.json')
        ledger_path = control / (RECOVERY_NAME + '.ledger.json')
        log_path = control / (RECOVERY_NAME + '-' + token + '.log')
        receipt_path = control / (RECOVERY_NAME + '-' + token + '.receipt.json')
        for path in (archive, ledger_path, log_path, receipt_path):
            require(not path.exists() and not path.is_symlink(), 'Recovery output already exists')
        argv = command(base, code, run)
        env = g.runner_environment(base, GPU_UUID)
        ledger = {'schema_version': 1, 'at': g.utcnow().isoformat(), 'server': '103',
                  'recovery_token': token, 'run_root': str(run), 'plan_sha256': PLAN_SHA, 'identity_sha256': IDENTITY_SHA,
                  'interruption_sha256': INTERRUPTION_SHA, 'boot_id': BOOT_ID,
                  'old_pid': OLD_PID, 'original_claim_sha256': OLD_REMOTE_CLAIM_SHA,
                  'original_spawn_receipt_sha256': OLD_REMOTE_RECEIPT_SHA,
                  'pending_task_id': PENDING, 'original_pending_sha256': PENDING_SHA,
                  'original_pending_receipt': pending, 'archived_original_receipt': str(archive),
                  'completed_input_manifest_sha256': digest(payload['completed']),
                  'completed_images_to_reuse': 171, 'budget': recovery_budget(),
                  'old_driver': old_spawn['gpu']['driver'], 'recovery_gpu': gpu,
                  'original_boot_evidence': payload['old_boot_evidence'],
                  'source_files_verified': expected, 'guard_sha256': GUARD_SHA,
                  'recovery_script_sha256': payload['recovery_script_sha256'],
                  'permission_sha256': payload['permission_sha256'], 'command': argv,
                  'log': str(log_path), 'receipt': str(receipt_path),
                  'status': 'recovery_claimed_before_pending_archive', 'automatic_retry_allowed': False,
                  'original_science_manifest_and_source_unchanged': True}
        # A crash at any following point leaves a permanent claim requiring review.
        g.exclusive_json(claim, ledger)
        g.exclusive_json(ledger_path, ledger)
        archive_exact_pending(pending_path, archive, PENDING_SHA)
        require(len(list((run / 'operations').glob('*.json'))) == 171, 'Completed inventory changed during archival')
        fixed_file(original_claim, OLD_REMOTE_CLAIM_SHA)
        check_boot_and_processes()
        validate_permission(payload['permission'])
        # Original runner opens its own flock. Keep the outer launch lock and
        # permanent claims, but release this run lock immediately before spawn.
        fcntl.flock(held_run, fcntl.LOCK_UN)
        with log_path.open('xb') as log:
            child = subprocess.Popen(argv, cwd=code, env=env, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)
        try:
            stat_tail = (Path('/proc') / str(child.pid) / 'stat').read_text().rsplit(')', 1)[1].split()
            start_ticks = stat_tail[19]
            require(start_ticks.isdigit(), 'Invalid spawned process start ticks')
        except FileNotFoundError:
            start_ticks = None  # A rapid exit is not accepted as an active task.
        receipt = dict(ledger, status='runner_process_spawned_not_GPU_acceptance', pid=child.pid,
                       started_at=g.utcnow().isoformat(), process_start_ticks=start_ticks,
                       spawned_process_identity_observed=start_ticks is not None, archive_sha256=hash_file(archive),
                       recovery_ledger=str(ledger_path), recovery_ledger_sha256=hash_file(ledger_path))
        g.exclusive_json(receipt_path, receipt)
        return receipt


def remote_program(source, guard_source, payload):
    """Send fixed source through stdin, avoiding shell-argument size limits."""
    require(hashlib.sha256(guard_source.encode()).hexdigest() == GUARD_SHA, 'Guard source changed')
    require(hashlib.sha256(source.encode()).hexdigest() == payload['recovery_script_sha256'], 'Recovery source changed')
    return ("import json, types\ng = {'__name__':'_recovery_guards'}\nexec(" + repr(guard_source) + ",g)\n"
            "n = {'__name__':'_manual_recovery','GUARDS':types.SimpleNamespace(**g)}\nexec(" + repr(source) + ",n)\n"
            "print(json.dumps(n['remote_recover'](json.loads(" + repr(json.dumps(payload, ensure_ascii=False))
            + ")),ensure_ascii=False),flush=True)\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--permission', type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    source_path = Path(__file__).resolve()
    root, out = source_path.parents[2], source_path.parent
    payload = local_prepare(root, args.permission)
    source, guard_source = source_path.read_text(), source_path.with_name('launch_image_search.py').read_text()
    payload['recovery_script_sha256'] = hashlib.sha256(source.encode()).hexdigest()
    g = guards()
    if not args.execute:
        print(json.dumps({'mode': 'dry_run_local_only_no_connection', 'local_inputs_verified': True, 'remote_state_verified': False,
                          'ready_for_one_shot_execution': False,
                          'fresh_UI_permission_still_required_at_execution': True, 'scientific_source_unchanged': True,
                          'completed_evidence_count': len(payload['completed']), 'pending_task_id': PENDING,
                          'recovery_script_sha256': payload['recovery_script_sha256'], 'guard_sha256': GUARD_SHA,
                          'interruption_sha256': INTERRUPTION_SHA, 'budget': recovery_budget(),
                          'command': command(Path(g.BASES['103']), Path(payload['code_root']), Path(g.BASES['103']) / 'results' / g.RUN_NAME)},
                         ensure_ascii=False, indent=2))
        return 0
    require(args.permission is not None, '--execute requires fresh authenticated UI permission')
    control = out / 'launch-control'
    claim = control / (RECOVERY_NAME + '.claim.json')
    lock_path = control / ('image-search-' + PLAN_SHA + '.lock')
    g.owned_real(lock_path)
    with lock_path.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not claim.exists() and not claim.is_symlink(), 'Local recovery claim exists; never retry')
        fixed_file(control / ('image-search-' + PLAN_SHA + '.claim.json'), OLD_LOCAL_CLAIM_SHA)
        validate_permission(payload['permission'])
        payload['token'] = uuid.uuid4().hex
        record = {'at': g.utcnow().isoformat(), 'server': '103', 'token': payload['token'],
                  'plan_sha256': PLAN_SHA, 'identity_sha256': IDENTITY_SHA, 'pending_task_id': PENDING,
                  'original_pending_sha256': PENDING_SHA, 'original_local_claim_sha256': OLD_LOCAL_CLAIM_SHA,
                  'interruption_sha256': INTERRUPTION_SHA, 'recovery_script_sha256': payload['recovery_script_sha256'],
                  'guard_sha256': GUARD_SHA, 'permission_sha256': payload['permission_sha256'],
                  'budget': recovery_budget(), 'status': 'recovery_claimed_before_connection', 'automatic_retry_allowed': False}
        g.exclusive_json(claim, record)
        report = dict(record)
        try:
            # This is the sole connection path; default preparation and tests do not import it.
            sys.path.insert(0, str(root / 'server'))
            from stage_school_assets import SchoolSession
            with SchoolSession() as session:
                text = remote_program(source, guard_source, payload)
                remote_command = shlex.join([g.BASES['103'] + '/venv/bin/python', '-I', '-'])
                result = subprocess.run(['ssh', '-F', str(session.config), '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                                         'school103', remote_command], input=text, capture_output=True, text=True, timeout=90)
                report.update(returncode=result.returncode, stderr=result.stderr[-5000:])
                if result.returncode == 0:
                    remote = json.loads(result.stdout)
                    require(remote.get('recovery_token') == payload['token'] and remote.get('plan_sha256') == PLAN_SHA
                            and remote.get('status') == 'runner_process_spawned_not_GPU_acceptance', 'Unexpected remote spawn receipt')
                    receipt_bytes = (json.dumps(remote, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
                    report.update(status=remote['status'], remote=remote,
                                  remote_receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest())
                else:
                    report.update(status='remote_failed_or_unknown_manual_audit_required', stdout=result.stdout[-5000:])
        except Exception as exc:
            report.update(status='connection_or_recovery_unknown_manual_audit_required', error=type(exc).__name__ + ': ' + str(exc))
        report['finished_at'] = g.utcnow().isoformat()
        result_path = control / (RECOVERY_NAME + '-' + payload['token'] + '.result.json')
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
