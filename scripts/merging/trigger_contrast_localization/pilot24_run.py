"""Reviewed pilot24 coordination and local durable execution CLI.

No command creates reviews or resource permits. `start` detaches the coordinator
on the current server; `release`/`ingest`/`advance` support explicit remote receipt
transport without any shared writable database or network calls in this module.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from pilot24_coordinator import Coordinator, read_json, write_json
from pilot24_inputs import RUN
from pilot24_watchdog import create_t0, load_t0, supervise


def file_sha(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('regular frozen file required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_reviewed_configuration(bundle_path, config_path):
    bundle, config = read_json(bundle_path), read_json(config_path)
    review = read_json(bundle['review_file'])
    manifest_sha = file_sha(bundle_path)
    if (bundle.get('run_id') != RUN or bundle.get('status') != 'frozen'
            or config.get('manifest_sha256') != manifest_sha or review.get('run_id') != RUN
            or review.get('status') != 'passed' or review.get('manifest_sha256') != manifest_sha
            or review.get('coordinator_config_sha256') != file_sha(config_path)
            or not review.get('reviewer') or not review.get('implementer')
            or review['reviewer'] == review['implementer']):
        raise ValueError('independent approval must bind bundle and coordinator config')
    root = Path(bundle['repository_root']).resolve()
    sources = bundle.get('code_sha256', {})
    required = {'pilot24_run.py', 'pilot24_coordinator.py', 'pilot24_watchdog.py',
                'pilot24_deadline.py', 'pilot24_runtime.py', 'pilot24_inputs.py',
                'pilot24_statistics.py', 'pilot24_worker_compute.py', 'pilot24_worker_ledger.py',
                'pilot24_provenance.py'}
    if config.get('recovery'):
        required.add('pilot24_recovery_guard_candidate.py')
    if not required <= {Path(p).name for p in sources}:
        raise ValueError('execution chain must be frozen in review')
    for relative, expected in sources.items():
        path = root / relative
        if not path.resolve().is_relative_to(root) or file_sha(path) != expected:
            raise ValueError('reviewed execution code changed')
    if config.get('recovery'):
        from pilot24_recovery_guard_candidate import validate_amendment
        validate_amendment(bundle, config, review, manifest_sha)
    # Also ensure this running entrypoint is the reviewed copy.
    if not Path(__file__).resolve().is_relative_to(root):
        raise ValueError('entrypoint outside reviewed repository')
    return config


def ensure_t0(coordinator):
    recovery = coordinator.config.get('recovery')
    path = (Path(recovery['original_coordinator_root']) / 't0.json'
            if recovery else coordinator.root / 't0.json')
    if not path.exists():
        if recovery:
            raise ValueError('original T0 missing; never create a replacement')
        if coordinator.state['t0'] is not None:
            raise ValueError('shared T0 was removed; never reset it')
        create_t0(path, coordinator.config['manifest_sha256'])
    sha = file_sha(path)
    original_manifest = None
    if recovery:
        from pilot24_recovery_guard_candidate import MANIFEST
        original_manifest = MANIFEST
    value = load_t0(path, sha, coordinator.config['manifest_sha256'], original_manifest_sha=original_manifest)
    coordinator.bind_t0(value, sha)
    return str(path.resolve()), sha


def worker(args):
    from pilot24_worker_compute import run_session
    if os.environ.get('PILOT24_SUPERVISED') != args.t0_sha:
        raise ValueError('session must run under the reviewed deadline supervisor')
    return run_session(args.mailbox, args.receipt_root, args.bundle, args.worker_id,
                       args.t0, args.t0_sha, args.permission_ref, args.stop_file)


def supervise_worker(args):
    bundle = read_json(args.bundle)
    review = read_json(bundle['review_file'])
    config = load_reviewed_configuration(args.bundle, review['coordinator_config_file'])
    original_manifest = None
    if config.get('recovery'):
        from pilot24_recovery_guard_candidate import MANIFEST
        original_manifest = MANIFEST
    t0 = load_t0(args.t0, args.t0_sha, file_sha(args.bundle), original_manifest_sha=original_manifest)
    argv = [sys.executable, str(Path(__file__).resolve()), 'worker']
    for name in ('bundle', 'mailbox', 'receipt_root', 'worker_id', 't0', 't0_sha', 'permission_ref', 'stop_file'):
        argv.extend(['--' + name.replace('_', '-'), str(getattr(args, name))])
    os.environ['CUDA_VISIBLE_DEVICES'] = args.gpu_uuid
    os.environ['GPU_UUID'] = args.gpu_uuid
    os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['PILOT24_SUPERVISED'] = args.t0_sha
    threads = bundle.get('cpu_threads_per_worker')
    if type(threads) is not int or not 1 <= threads <= 8:
        raise ValueError('bounded frozen CPU thread count required')
    os.environ['OMP_NUM_THREADS'] = str(threads)
    os.environ['MKL_NUM_THREADS'] = str(threads)
    result = supervise(argv, t0['t0_utc'], stop_file=args.stop_file, pass_fds=inherited_fds)
    result.update({'run_id': RUN, 'worker_id': args.worker_id,
                   'manifest_sha256': file_sha(args.bundle), 't0_sha256': args.t0_sha})
    write_json(args.exit_receipt, result)
    return result


def emit_report(c):
    terminal = c.state['terminal']
    if terminal is None:
        return
    content = ('# Pilot24 execution report\n\n'
               f"Run: `{RUN}`. Outcome: **{terminal['outcome']}**; reason: `{terminal['reason']}`.\n\n"
               f"Unique scored images: {terminal['unique_complete']}/6144, including "
               f"{terminal['imported']} verified imports; new charged attempts: {terminal['charged_attempts']}.\n\n"
               'Stage statistics and gate decisions are in `reports/`; this report requires independent review. '
               'Incomplete execution is inconclusive, and does not establish a negative scientific result.\n')
    content += '\n\n| Stage | Gate passed | Report hash |\n|---|---|---|\n'
    for stage, report in c.state['reports'].items():
        content += f"| {stage} | {report['passed']} | `{report['report_sha256']}` |\n"
    content += f"\nWorker exit verified: {terminal.get('worker_exit_verified', False)}. "
    content += f"Final ledger accounting: {terminal.get('final_ledger_audit', {}).get('counts_are_final', False)}.\n"
    from pilot24_worker_ledger import canonical
    rows = sorted(c.records(), key=lambda r: r['key'])
    temporary_rows = c.root / '.per-image.tmp'
    with temporary_rows.open('w') as out:
        for row in rows:
            out.write(canonical(row) + '\n')
        out.flush()
        os.fsync(out.fileno())
    os.replace(temporary_rows, c.root / 'per_image.jsonl')
    path = c.root / 'report.md'
    temporary = c.root / '.report.tmp'
    temporary.write_text(content)
    os.replace(temporary, path)


def final_ledger_audit(c, sessions):
    """After session exit, export durable charged attempts even after SIGKILL."""
    from pilot24_worker_ledger import WorkerLedger
    exited = {p.name for p in sessions if (p / 'exit.json').exists()}
    audited, errors = [], []
    for release in c.state['released'].values():
        for item in release['assignments']:
            assignment = read_json(item['path'])
            root = Path(assignment['output_root'])
            if assignment['worker_id'] not in exited:
                continue
            if not (root / 'worker.sqlite').exists():
                previous = c.state['receipts'].get(assignment['assignment_id'])
                if previous and read_json(c.root / previous['path'])['attempts']:
                    errors.append({'assignment_id': assignment['assignment_id'], 'error': 'charged receipt has no durable ledger'})
                continue
            try:
                with WorkerLedger(root, assignment) as ledger:
                    snapshot = ledger.snapshot(c.config['model_bundle_sha256'], c.config['scorer_sha256'], verify_images=True)
                receipt = {k: assignment[k] for k in ('run_id', 'manifest_sha256', 'assignment_id', 'stage', 'worker_id')}
                receipt.update({'assignment_sha256': item['sha256'], 't0_sha256': c.state['t0']['file_sha256'],
                                'status': 'complete' if len(snapshot['records']) == len(assignment['units']) else 'deadline',
                                **snapshot})
                c.ingest(receipt, final_audit=True)
                audited.append(assignment['assignment_id'])
            except Exception as error:
                errors.append({'assignment_id': assignment['assignment_id'], 'error': str(error)})
    c.state['terminal']['final_ledger_audit'] = {'audited': audited, 'errors': errors,
        'counts_are_final': not errors and c.state['terminal']['worker_exit_verified']}


def serve(args):
    config = load_reviewed_configuration(args.bundle, args.config)
    if config.get('recovery'):
        from pilot24_recovery_guard_candidate import MANIFEST, hold_predecessor, hold_both_predecessors
        rec = config['recovery']
        guard = (hold_both_predecessors(previous_review_sha256=rec['previous']['review_sha256']) if 'previous' in rec else
                 hold_predecessor(coordinator_root=rec['original_coordinator_root'],
                    original_bundle=rec['original_bundle'], original_config=rec['original_config'],
                    expected_config_sha=rec['original_config_sha256'], expected_state_sha=rec['original_state_sha256'],
                    expected_bundle_sha=MANIFEST))
        with guard as prior:
            return _serve_reviewed(args, config)
    return _serve_reviewed(args, config)


def _serve_reviewed(args, config):
    specs = read_json(args.launch_map)
    with Coordinator(args.root, config) as c:
        try:
            while c.state['terminal'] is None:
                specs = read_json(args.launch_map)
                for path in sorted((c.root / 'jobs').glob('*/progress.json')):
                    receipt = read_json(path)
                    aid = receipt['assignment_id']
                    from pilot24_worker_ledger import digest
                    if c.state['receipts'].get(aid, {}).get('sha256') != digest(receipt):
                        c.ingest(receipt)
                result = c.advance()
                if c.state['terminal']:
                    break
                if c.state['t0']:
                    timing = c.tick()
                    if c.state['terminal']:
                        break
                else:
                    timing = {'generation_permitted': True}
                if c.state['t0']:
                    c.capacity()
                    if c.state['terminal']:
                        break
                stage = c.state['stage']
                released = c.release(stage)
                if timing['generation_permitted']:
                    for item in released['assignments']:
                        assignment = read_json(item['path'])
                        worker_id = assignment['worker_id']
                        if worker_id not in specs:
                            continue  # External workers use release/ingest CLI.
                        spec = specs[worker_id]
                        if spec.get('server') != assignment['server'] or spec.get('server') != args.server:
                            raise ValueError('local launcher cannot impersonate a remote server')
                        session = c.root / 'sessions' / worker_id
                        session.mkdir(parents=True, exist_ok=True)
                        mailbox = session / 'mailbox'
                        mailbox.mkdir(exist_ok=True)
                        dispatch = {'assignment': item['path'], 'gate': released['gate_path']}
                        message = mailbox / (item['assignment_id'] + '.json')
                        if message.exists():
                            if read_json(message) != dispatch:
                                raise ValueError('mailbox assignment changed')
                        else:
                            write_json(message, dispatch, exclusive=True)
                        launched = session / 'launch.json'
                        if launched.exists():
                            continue  # Never duplicate an uncertain live session.
                        t0_path, t0_sha = ensure_t0(c)
                        values = {'bundle': args.bundle, 'mailbox': mailbox.resolve(),
                                  'receipt_root': (c.root / 'jobs').resolve(), 'worker_id': worker_id,
                                  't0': t0_path, 't0_sha': t0_sha, 'permission_ref': spec['permission_ref'],
                                  'stop_file': (session / 'stop.json').resolve(),
                                  'exit_receipt': (session / 'exit.json').resolve(), 'gpu_uuid': assignment['gpu_uuid']}
                        argv = [sys.executable, str(Path(__file__).resolve()), 'supervise']
                        for name, value in values.items():
                            argv.extend(['--' + name.replace('_', '-'), str(value)])
                        write_json(launched, {'argv': argv, 'state': 'dispatch_reserved_not_proof_of_start'}, exclusive=True)
                        env = os.environ.copy()
                        with (session / 'worker.log').open('ab') as log:
                            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log,
                                                    stderr=subprocess.STDOUT, start_new_session=True,
                                                    env=env)
                        write_json(session / 'supervisor.json', {'pid': proc.pid, 'worker_id': worker_id}, exclusive=True)
                # The worker writes its actionable session error before it
                # exits. Preserve that cause when its exit receipt is already
                # visible in the same polling iteration.
                for session_path in (c.root / 'jobs' / 'sessions').glob('*/session.json'):
                    if read_json(session_path).get('status') == 'blocked':
                        c.finish('inconclusive', 'worker_session_blocked')
                        break
                # A dead session is never silently restarted into a second ledger.
                if c.state['terminal'] is None:
                    for path in (c.root / 'sessions').glob('*/exit.json'):
                        if read_json(path)['returncode'] != 0:
                            c.finish('inconclusive', 'worker_execution_failure')
                            break
                if c.state['terminal'] is None and any(read_json(c.root / item['path'])['status'] in ('blocked', 'deadline') for item in c.state['receipts'].values()):
                    c.finish('inconclusive', 'worker_incomplete')
                if c.state['terminal'] is None:
                    time.sleep(min(30.0, max(.05, args.poll_seconds)))
        except Exception as error:
            write_json(c.root / 'coordinator_error.json', {'type': type(error).__name__, 'error': str(error)})
            c.finish('inconclusive', 'coordinator_validation_or_execution_failure')
        for session in (c.root / 'sessions').glob('*'):
            if session.is_dir() and not (session / 'exit.json').exists():
                write_json(session / 'stop.json', {'run_id': RUN, 'reason': c.state['terminal']['reason']})
        # Bounded wait for our supervisors, independent of SSH/client lifetime.
        stop_until = time.monotonic() + 35
        while time.monotonic() < stop_until:
            sessions = [p for p in (c.root / 'sessions').glob('*') if p.is_dir()]
            if all((p / 'exit.json').exists() for p in sessions):
                break
            time.sleep(.2)
        c.state['terminal']['worker_exit_verified'] = all((p / 'exit.json').exists() for p in sessions)
        final_ledger_audit(c, sessions)
        c.refresh_terminal_counts()
        write_json(c.root / 'terminal.json', c.state['terminal'])
        c.save()
        emit_report(c)
        return c.state['terminal']


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest='command', required=True)
    q = subs.add_parser('run', help='run a new spec with the unified runtime')
    q.add_argument('--spec', required=True)
    for command in ('initialize', 'release', 'ingest', 'advance', 'status', 'serve', 'start'):
        q = subs.add_parser(command)
        for key in ('bundle', 'config', 'root'):
            q.add_argument('--' + key, required=command != 'status' or key == 'root')
        if command == 'ingest':
            q.add_argument('--receipt', required=True)
        if command in ('serve', 'start'):
            q.add_argument('--launch-map', required=True)
            q.add_argument('--server', required=True)
            q.add_argument('--poll-seconds', type=float, default=15)
    for command in ('worker', 'supervise'):
        q = subs.add_parser(command)
        for key in ('bundle', 'mailbox', 'receipt-root', 'worker-id', 't0', 't0-sha', 'permission-ref', 'stop-file'):
            q.add_argument('--' + key, required=True)
        if command == 'supervise':
            q.add_argument('--exit-receipt', required=True)
            q.add_argument('--gpu-uuid', required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == 'run':
        return subprocess.call([sys.executable, str(Path(__file__).with_name('runtime.py')), 'run', '--spec', args.spec])
    if args.command == 'status':
        value = read_json(Path(args.root) / 'state.json')
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command != 'status':
        raise SystemExit('historical pilot24 execution is closed; use run --spec for a new run')
    if args.command == 'worker':
        value = worker(args)
    elif args.command == 'supervise':
        value = supervise_worker(args)
    elif args.command == 'serve':
        value = serve(args)
    elif args.command == 'status':
        from pilot24_worker_ledger import digest
        config = load_reviewed_configuration(args.bundle, args.config)
        if str(Path(args.root).resolve()) != config['coordinator_root']:
            raise ValueError('status root differs from frozen configuration')
        value = read_json(Path(args.root) / 'state.json')
        if value['config_sha256'] != digest(config):
            raise ValueError('status belongs to another configuration')
    else:
        config = load_reviewed_configuration(args.bundle, args.config)
        if config.get('recovery') and args.command not in ('start',):
            raise ValueError('recovery may only start through the predecessor-locked server')
        with Coordinator(args.root, config) as c:
            if args.command == 'start':
                command = [sys.executable, str(Path(__file__).resolve()), 'serve', '--bundle', args.bundle,
                           '--config', args.config, '--root', args.root, '--launch-map', args.launch_map,
                           '--server', args.server, '--poll-seconds', str(args.poll_seconds)]
            elif args.command == 'release':
                value = c.release(c.state['stage'])
            elif args.command == 'ingest':
                c.ingest(read_json(args.receipt))
                value = c.state
            elif args.command == 'advance':
                c.tick()
                value = c.advance()
                emit_report(c)
            else:
                value = c.state
        if args.command == 'start':
            with (Path(args.root) / 'coordinator.log').open('ab') as log:
                proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                        stderr=subprocess.STDOUT, start_new_session=True)
            value = {'status': 'coordinator_dispatched', 'pid': proc.pid, 'gpu_started': 'not_established'}
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    sys.exit(main())
