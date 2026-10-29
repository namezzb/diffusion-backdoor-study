#!/usr/bin/env python3
"""One bounded read-only observation of an explicitly identified confirmation.

Default is local preparation only. No process launch, replay, signal to research
processes, model import, run-lock acquisition, or remote write is implemented.
"""
import argparse
import base64
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import shlex
import sys
import uuid
import zlib

OBSERVER_SHA = '53fe627e48109eac545529f2473f08aaa15d85f3b5743b237e7b06eb5c22958f'
CONTINUATION_SHA = '8cb9feb30952bd8d5557829b50be25bf59d26158c1e26ba7afdd6ba5b75b3adc'
EXPECTED_UID = 24112
CODE_NAME = 'image-search-6913379cd01c'


def pinned(path, expected):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError('Reviewed dependency changed: ' + str(path))
    spec = importlib.util.spec_from_file_location('_confirm_observe_' + path.stem, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def dependencies():
    if 'OBSERVER' not in globals():
        globals()['OBSERVER'] = pinned(Path(__file__).with_name('observe_image_search.py'), OBSERVER_SHA)
        globals()['CONTINUATION'] = pinned(Path(__file__).with_name('continue_search_confirmation.py'), CONTINUATION_SHA)
    return globals()['OBSERVER'], globals()['CONTINUATION']


def request(receipt_path, receipt_sha):
    o, c = dependencies()
    if receipt_path is None and receipt_sha is None:
        return None
    o.require(isinstance(receipt_path, str) and isinstance(receipt_sha, str), 'Provide both explicit receipt path and raw SHA256')
    p = PurePosixPath(receipt_path)
    o.require(str(p) == receipt_path and p.parent == PurePosixPath(o.BASES['103']) / 'launch-control'
              and re.fullmatch('confirmation-' + c.PLAN_SHA + r'-[0-9a-f]{32}\.receipt\.json', p.name),
              'Not the same 103 confirmation control path')
    o.require(re.fullmatch('[0-9a-f]{64}', receipt_sha) is not None, 'Invalid raw receipt SHA256')
    return {'receipt_path': receipt_path, 'receipt_sha256': receipt_sha}


def expected_command(base, run):
    o, _ = dependencies(); code = base / 'code' / CODE_NAME
    return [str(base / 'venv/bin/python'), '-B', str(code / 'scripts/merging/tssa_image_search_run.py'), 'run',
            '--plan', str(code / o.PLAN_REL), '--old-protocol', str(code / 'research/tssa_mvp_2026-10-26.json'),
            '--asset-manifest', str(code / 'research/tssa_mvp_assets_2026-10-26.json'),
            '--models-root', str(base / 'models'), '--run-root', str(run), '--scorer-device', 'cpu', '--resume', '--until', 'confirm']


def collect_provenance(base, run, wanted, capture):
    """Read only immutable launch provenance; no outcome files are opened here."""
    o, c = dependencies()
    o.require(request(wanted.get('receipt_path'), wanted.get('receipt_sha256')) == wanted, 'Invalid explicit request')
    path = PurePosixPath(wanted['receipt_path']); token = path.name[-len('.receipt.json')-32:-len('.receipt.json')]
    raw = o.safe_read(base, 'launch-control/' + path.name)
    o.require(raw is not None and o.sha(raw) == wanted['receipt_sha256'], 'Confirmation receipt missing or changed')
    receipt = json.loads(raw)
    fixed = {'schema_version': 1, 'server': '103', 'confirmation_token': token, 'plan_sha256': c.PLAN_SHA,
             'identity_sha256': c.IDENTITY_SHA, 'run_root': str(run), 'guard_sha256': c.GUARD_SHA,
             'budget_gate_sha256': c.GATE_SHA, 'continuation_sha256': CONTINUATION_SHA,
             'receipt': str(path), 'log': str(path.parent / (path.name[:-len('.receipt.json')] + '.log')),
             'status': 'runner_process_spawned_not_GPU_acceptance', 'automatic_retry_allowed': False,
             'old_evidence_hashes_preserved': c.REMOTE_OLD, 'command': expected_command(base, run)}
    for key, value in fixed.items():
        o.require(receipt.get(key) == value, 'Confirmation receipt binding differs: ' + key)
    o.require(type(receipt.get('pid')) is int and receipt['pid'] > 0, 'Missing confirmation PID')
    o.require(re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', str(receipt.get('boot_id'))) is not None,
              'Missing explicit confirmation boot ID')
    ticks = receipt.get('process_start_ticks')
    o.require(ticks is None or isinstance(ticks, str) and ticks.isdigit(), 'Malformed confirmation start ticks')
    for key in ('permission_sha256', 'observation_sha256'):
        o.require(re.fullmatch('[0-9a-f]{64}', str(receipt.get(key))) is not None, 'Missing evidence hash: ' + key)
    gpu = receipt.get('gpu', {})
    o.require(type(gpu.get('index')) is int and gpu['index'] in (0, 1, 2)
              and re.fullmatch(r'GPU-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', str(gpu.get('uuid')))
              and gpu.get('compute_mode') == 'Default', 'Invalid confirmation GPU identity')
    c.validate_decision(receipt.get('budget_decision', {}))
    verified = receipt.get('verified', {})
    o.require(verified.get('completed_receipts_and_PNGs_verified') == receipt['budget_decision']['completed_images']
              and all(re.fullmatch('[0-9a-f]{64}', str(verified.get(k))) for k in ('dev_selection_sha256', 'input_inventory_sha256')),
              'Missing completed development inventory commitment')
    claim_raw = o.safe_read(base, 'launch-control/' + c.CLAIM_NAME)
    o.require(claim_raw is not None, 'Confirmation before-spawn claim missing')
    claim = json.loads(claim_raw)
    committed = {k: v for k, v in receipt.items() if k not in ('pid', 'started_at', 'process_start_ticks', 'status')}
    o.require(claim.get('status') == 'confirmation_claimed_before_spawn'
              and {k: v for k, v in claim.items() if k != 'status'} == committed, 'Confirmation differs from permanent before-spawn claim')
    old = {}
    for name, expected_sha in c.REMOTE_OLD.items():
        value = o.safe_read(base, 'launch-control/' + name)
        o.require(value is not None and o.sha(value) == expected_sha, 'Old recovery/failure evidence changed: ' + name)
        old[name] = value
    original_claim = 'image-search-' + c.PLAN_SHA + '.claim.json'
    original_receipt = next(n for n in old if n.startswith('2026') and n.endswith('.receipt.json'))
    recovery_name = next(n for n in old if n.startswith(c.RECOVERY + '-') and n.endswith('.receipt.json'))
    recovery = o.collect_recovery(base, run, {'receipt_path': str(base / 'launch-control' / recovery_name),
        'receipt_sha256': c.REMOTE_OLD[recovery_name]}, old[original_claim], old[original_receipt], capture)
    for name, value in ((original_claim, old[original_claim]), (original_receipt, old[original_receipt]),
                        (path.name, raw), (c.CLAIM_NAME, claim_raw)):
        capture.add('launch/' + name, value)
    return receipt, recovery


def check_development_binding(run, receipt):
    o, c = dependencies(); values = {}
    for name in ('search_summary.json', 'search_selection.json', 'dev_summary.json', 'dev_selection.json'):
        raw = o.safe_read(run, name)
        o.require(raw is not None, 'Committed development endpoint missing')
        data = json.loads(raw)
        o.require(data.get('identity_sha256') == c.IDENTITY_SHA and data.get('sha256') == o.digest(data.get('payload')),
                  'Development envelope changed')
        values[name] = data['payload']
    d = receipt['budget_decision']; search, dev = values['search_selection.json'], values['dev_selection.json']
    o.require(o.digest(dev) == receipt['verified']['dev_selection_sha256']
              and dev.get('selected') == [d['winner']] and dev.get('coefficients', {}).get(d['winner']) == d['winner_coefficients']
              and len(search.get('selected', [])) == d['selected_search_count'] and d['winner'] in search['selected'],
              'Development selection differs from audited confirmation commitment')
    for stage in ('search', 'dev'):
        o.require(values[stage + '_selection.json'].get('summary_sha256') == o.digest(values[stage + '_summary.json']),
                  'Stage summary/selection binding changed')


def proc_read(path, limit):
    with path.open('rb', buffering=0) as stream:
        raw = stream.read(limit + 1)
    dependencies()[0].require(len(raw) <= limit, 'Process metadata exceeds bound')
    return raw


def confirmation_process_snapshot(receipt, proc=Path('/proc')):
    """Only this new PID/UID/exact argv/start tick/boot tuple establishes liveness."""
    o, _ = dependencies(); pid = receipt['pid']; path = proc / str(pid)
    result = {'pid': pid, 'confirmation_token': receipt['confirmation_token'], 'expected_uid': EXPECTED_UID,
              'expected_start_ticks': receipt['process_start_ticks'], 'expected_boot_id': receipt['boot_id'],
              'confirmation_process_identity_matches': False, 'old_recovery_PID_is_not_current_execution': True,
              'automatic_retry_allowed': False}
    try:
        boot = proc_read(proc / 'sys/kernel/random/boot_id', 64).decode().strip(); result['observed_boot_id'] = boot
        if boot != receipt['boot_id']:
            return dict(result, status='recorded_confirmation_boot_no_longer_current', exists=None)
        uid = path.stat().st_uid
        if uid != EXPECTED_UID or uid != os.getuid():
            return dict(result, status='PID_now_belongs_to_different_UID', exists=True, uid=uid)
        before = proc_read(path / 'stat', 8192).decode().rsplit(')', 1)[1].split()[19]
        argv = [x.decode('utf-8', 'strict') for x in proc_read(path / 'cmdline', 65536).split(b'\0') if x]
        after = proc_read(path / 'stat', 8192).decode().rsplit(')', 1)[1].split()[19]
        matches = before == after == receipt['process_start_ticks'] and argv == receipt['command'] and path.stat().st_uid == uid
        return dict(result, exists=True, uid=uid, start_ticks=after, exact_command_matches=argv == receipt['command'],
                    confirmation_process_identity_matches=matches,
                    status='verified_confirmation_running' if matches else 'PID_identity_unverified_or_reused')
    except FileNotFoundError:
        return dict(result, exists=False, status='recorded_confirmation_process_absent_outcome_requires_artifacts')
    except (OSError, ValueError, UnicodeError, IndexError) as exc:
        return dict(result, exists=None, status='confirmation_process_observation_unknown', error=type(exc).__name__)


def collect_remote(payload):
    o, c = dependencies()
    o.require(payload.get('server') == '103' and payload.get('plan_sha256') == c.PLAN_SHA, 'Wrong server/plan')
    o.require(os.getuid() == EXPECTED_UID and pwd.getpwuid(os.getuid()).pw_name == 'zhangzibo', 'Wrong 103 account/UID')
    base = Path(o.BASES['103']); run = base / 'results' / o.RUN_NAME
    o.require(base.is_dir() and base.resolve() == base and base.stat().st_uid == os.getuid(), 'Unexpected project root')
    capture = o.Capture()
    result = {'server': '103', 'run_root': str(run), 'plan_sha256': c.PLAN_SHA, 'observed_at': o.now(), 'read_only': True,
              'GPU_launch': False, 'errors': [], 'allocation_permission_inferred': False,
              'active_launch_source': 'confirmation_provenance_unverified'}
    try:
        receipt, recovery = collect_provenance(base, run, payload['confirmation'], capture)
        check_development_binding(run, receipt)
    except Exception as exc:
        result['errors'].append('confirmation provenance: ' + type(exc).__name__ + ': ' + str(exc))
        result.update(files=capture.files, transferred_raw_bytes=capture.total, finished_at=o.now(),
                      run={'status': 'withheld_until_confirmation_provenance_verified', 'confirm_unlocked': False})
        return result
    result.update(active_launch_source='verified_confirmation_continuation',
                  launch={'pid': receipt['pid'], 'gpu_uuid': receipt['gpu']['uuid'], 'confirmation_token': receipt['confirmation_token'],
                          'status': receipt['status'], 'started_at': receipt['started_at'], 'process_start_ticks': receipt['process_start_ticks'], 'boot_id': receipt['boot_id']},
                  confirmation={'status': 'provenance_verified', **payload['confirmation'], 'budget_decision': receipt['budget_decision'],
                                'expected_uid': EXPECTED_UID, 'automatic_retry_allowed': False},
                  recovery={'status': 'provenance_verified', 'historical_only': True, 'pid': recovery['pid'],
                            'ledger_sha256': recovery['recovery_ledger_sha256'], 'budget': recovery['budget']})
    result['launch_process_now'] = confirmation_process_snapshot(receipt)
    try:
        result['runtime'] = o.runtime_snapshot(run)
        result['launch_GPU_now'] = next((g for g in (result['runtime'].get('gpus') or []) if g['uuid'] == receipt['gpu']['uuid']), None)
        if result['runtime'].get('query_error'):
            result['errors'].append('runtime GPU query: ' + json.dumps(result['runtime']['query_error']))
    except Exception as exc:
        result['errors'].append('runtime: ' + type(exc).__name__ + ': ' + str(exc))
    try:
        result['run'] = o.collect_run(run, payload['public_plan'], capture)
        result['recovery_resource_accounting'] = o.recovery_accounting(result['run'], recovery)
        result['confirmation_resource_accounting'] = dict(result['recovery_resource_accounting'],
            planned_final_attempts=receipt['budget_decision']['final_attempts_with_failure'],
            planned_final_NFE_upper_bound=receipt['budget_decision']['final_generation_branch_NFE_upper_bound'])
        a = result['confirmation_resource_accounting']
        if a.get('completed_unique_images_observed', 0) < receipt['budget_decision']['completed_images']:
            result['errors'].append('Completed preconfirmation receipt count fell below immutable launch commitment')
        if a.get('total_generation_attempts_observed_including_failure', 0) > a['planned_final_attempts'] or not a.get('observed_counts_within_global_caps', True):
            result['errors'].append('Observed attempts exceed audited confirmation budget; read-only report, no process action')
        if not a.get('complete_global_accounting', False):
            result['errors'].append('Withheld operation files prevent complete global accounting')
    except Exception as exc:
        result['errors'].append('run: ' + type(exc).__name__ + ': ' + str(exc))
    try:
        tail = o.read_log_tail(base, 'launch-control/' + Path(receipt['log']).name, result.get('run', {}).get('confirm_unlocked') is True)
        result['log_tail'] = tail
        capture.add('launch/' + Path(receipt['log']).name + '.tail.json', (json.dumps(tail, ensure_ascii=False, indent=2) + '\n').encode())
    except Exception as exc:
        result['errors'].append('log: ' + type(exc).__name__ + ': ' + str(exc))
    result.update(files=capture.files, transferred_raw_bytes=capture.total, finished_at=o.now(),
                  image_bytes_read_or_verified=False, scientific_effectiveness_inferred=False)
    return result


def remote_program(payload):
    o, _ = dependencies(); here = Path(__file__).parent
    old = (here / 'observe_image_search.py').read_text(); continuation = (here / 'continue_search_confirmation.py').read_text()
    o.require(o.sha(old.encode()) == OBSERVER_SHA and o.sha(continuation.encode()) == CONTINUATION_SHA, 'Dependency changed')
    source = Path(__file__).read_text()
    return ('import json,types\no={"__name__":"_observer"}\nexec(' + repr(old) + ',o)\n'
            'c={"__name__":"_continuation"}\nexec(' + repr(continuation) + ',c)\n'
            'n={"__name__":"_confirmation_observer","OBSERVER":types.SimpleNamespace(**o),"CONTINUATION":types.SimpleNamespace(**c)}\nexec('
            + repr(source) + ',n)\nprint(json.dumps(n["collect_remote"](json.loads(' + repr(json.dumps(payload, ensure_ascii=False)) + ')),ensure_ascii=False,allow_nan=False),flush=True)\n')


def remote_command(payload):
    o, _ = dependencies(); program = remote_program(payload).encode()
    o.require(len(program) <= 200000, 'Read-only source bootstrap exceeds bound')
    encoded = base64.b64encode(zlib.compress(program)).decode('ascii')
    bootstrap = 'import base64,zlib;exec(zlib.decompress(base64.b64decode(' + repr(encoded) + ')))'
    command = shlex.join([o.BASES['103'] + '/venv/bin/python', '-I', '-B', '-c', bootstrap])
    o.require(len(command.encode()) < 120000, 'Read-only SSH command exceeds bound')
    return command


def main(argv=None):
    o, c = dependencies(); parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt'); parser.add_argument('--receipt-sha256'); parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv); wanted = request(args.receipt, args.receipt_sha256)
    root = Path(__file__).resolve().parents[2]; plan_raw = (root / o.PLAN_REL).read_bytes()
    o.require(o.sha(plan_raw) == c.PLAN_SHA, 'Frozen plan changed'); plan = json.loads(plan_raw)
    payload = {'server': '103', 'plan_sha256': c.PLAN_SHA, 'confirmation': wanted,
               'public_plan': {'candidates': plan['candidates'], 'stages': {s: plan['stages'][s] for s in ('search', 'dev')}}}
    if not args.execute:
        print(json.dumps({'status': 'prepared_locally_no_connection', 'confirmation': wanted, 'read_only': True,
                          'remote_ready': False, 'GPU_launch': False, 'confirmation_receipt_verified': False,
                          'max_seconds': o.TIMEOUT, 'max_transfer_bytes': o.MAX_TOTAL, 'max_wire_bytes': o.MAX_WIRE,
                          'max_files': o.MAX_IMAGES + 100, 'confirm_rows_sent_to_observer': False,
                          'image_bytes_read_or_verified': False}, indent=2)); return 0
    o.require(wanted is not None, '--execute requires exact receipt path and raw SHA256; never discover or guess a receipt')
    out = root / 'results/tssa-opt-exploration-2026-10-28'
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8]
    folder = out / ('confirmation_observation_103_' + stamp)
    report = {'started_at': o.now(), 'server': '103', 'read_only': True, 'GPU_launch': False, 'plan_sha256': c.PLAN_SHA,
              'observer_sha256': o.sha(Path(__file__).read_bytes()), 'base_observer_sha256': OBSERVER_SHA,
              'continuation_sha256': CONTINUATION_SHA, 'requested_confirmation': wanted}
    try:
        sys.path.insert(0, str(root / 'server')); from stage_school_assets import SchoolSession
        session = SchoolSession()
        try:
            session.__enter__()
            config = Path(session.temporary.name) / 'observe-confirm-config'
            config.write_text('Host *\n    BatchMode yes\n    StrictHostKeyChecking yes\n    ConnectTimeout 60\n    ConnectionAttempts 1\n    ControlMaster no\n    ControlPath none\n    ControlPersist no\n    UpdateHostKeys no\n    Include "' + str(session.config) + '"\n')
            config.chmod(0o600)
            rc, stdout, stderr = o.one_bounded_ssh(config, '103', remote_command(payload))
        finally:
            if hasattr(session, 'temporary'): session.temporary.cleanup()
        report.update(returncode=rc, stderr=stderr.decode(errors='replace')[-4000:])
        if rc == 0:
            result = o.save_bundle(json.loads(stdout), folder)
            report.update(status='observed_with_errors' if result['errors'] else 'observed', result=result)
        else: report.update(status='connection_or_query_failed', stdout_tail=stdout.decode(errors='replace')[-4000:])
    except Exception as exc:
        report.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
    report['finished_at'] = o.now(); folder.mkdir(mode=0o700, exist_ok=True)
    with (folder / 'report.json').open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
    compact = {k: v for k, v in report.items() if k != 'result'}
    if 'result' in report:
        data = report['result']; compact['result'] = {k: v for k, v in data.items() if k not in ('files', 'run')}
        compact['result']['run'] = {k: v for k, v in data.get('run', {}).items() if k != 'operations'}
        compact['result']['returned_files'] = len(data['files'])
    print(json.dumps({'report': str(folder / 'report.json'), **compact}, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'observed' else 1


if __name__ == '__main__':
    try: sys.exit(main())
    except Exception as exc:
        print(json.dumps({'status': 'refused', 'read_only': True, 'error': type(exc).__name__ + ': ' + str(exc)}), file=sys.stderr)
        sys.exit(2)
