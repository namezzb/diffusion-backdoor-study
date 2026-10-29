#!/usr/bin/env python3
"""Bounded read-only image-search observation; default prepares locally, --execute connects once.

Never imports a model, touches a run lock, resumes a run, or changes remote files.
Only metadata and small JSON artifacts are returned; PNG hashes are recorded in
receipts but image contents are intentionally not read or reverified here.
"""
import argparse
import base64
from collections import Counter
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import selectors
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2] if '__file__' in globals() else None
BASES = {'103': '/data1/zhangzibo/arxiv-tssa', '104': '/data2/zhangzibo/arxiv-tssa'}
RUN_NAME = 'tssa-opt-exploration-2026-10-28-v1'
PLAN_REL = 'research/tssa_optimization_exploration_2026-10-28.json'
PLAN_SHA = '8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6'
MAX_IMAGES = 1440
MAX_FILE = 2 * 1024**2
MAX_TOTAL = 16 * 1024**2
MAX_WIRE = 24 * 1024**2
MAX_OP_FILE = 64 * 1024
MAX_AUX_FILES = 16
MAX_LOG_TAIL = 16 * 1024
TIMEOUT = 100
RECOVERY_PENDING = '0e39df5be0cd73d07934fe529fc310cfd651f21d955276fc55b5200615f00c66'
RECOVERY_NAME = 'manual-recovery-' + RECOVERY_PENDING
RECOVERY_PENDING_SHA = 'a0d2562580ad355a4cf0bd84a85f15d35db3a88dee6ca3387b1ee45af91e4419'
RECOVERY_IDENTITY_SHA = 'd95475cd4f8067ad78e28b2aad1cf1c968d3b7c995930790b2687c053752c814'
RECOVERY_GPU_UUID = 'GPU-a00d7f16-dee6-f32a-eb89-dde4590ba523'
RECOVERY_OLD_CLAIM_SHA = '76bcefb5026fa9f0789f7821ab5230b1ca5ec78b69ac72981ec4c7dfc2a4e76f'
RECOVERY_OLD_RECEIPT_SHA = 'd95255ad6711abae2c204ecd531711ad3034113b8b89b7140bec2cd5fd4335c9'


class ObservationError(RuntimeError):
    pass


def require(ok, why):
    if not ok:
        raise ObservationError(why)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha((json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())


def relative(name):
    path = PurePosixPath(name)
    require(isinstance(name, str) and not path.is_absolute() and str(path) == name
            and bool(path.parts) and not any(x in ('', '.', '..') for x in path.parts), 'Unsafe artifact path')
    return path


def safe_read(root, name, limit=MAX_FILE):
    path = root.joinpath(*relative(name).parts)
    require(root.resolve() == root and not root.is_symlink(), 'Root path redirects')
    for parent in [root, *path.parents]:
        if parent == root or root in parent.parents:
            if not parent.exists() and not parent.is_symlink():
                return None
            require(not parent.is_symlink() and parent.stat().st_uid == os.getuid(), 'Unowned/redirected ancestor')
    if not path.exists() and not path.is_symlink():
        return None
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid(), 'Artifact is not an owned regular file')
        require(before.st_size <= limit, 'Artifact exceeds per-file bound: ' + name)
        chunks = bytearray()
        while len(chunks) <= limit:
            piece = os.read(fd, min(65536, limit + 1 - len(chunks)))
            if not piece:
                break
            chunks.extend(piece)
        after = os.fstat(fd)
        require(len(chunks) <= limit and before.st_size == after.st_size == len(chunks)
                and before.st_mtime_ns == after.st_mtime_ns, 'Artifact changed while sampled or exceeded bound')
        return bytes(chunks)
    finally:
        os.close(fd)


def names_in(root, directory, limit):
    path = root / directory
    if not path.exists() and not path.is_symlink():
        return []
    require(not path.is_symlink() and path.resolve() == path and path.stat().st_uid == os.getuid(), 'Unowned/redirected artifact directory')
    found = []
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.name.endswith('.json'):
                found.append(entry.name)
                require(len(found) <= limit, 'Artifact directory count exceeds bound: ' + directory)
    return sorted(found)


class Capture:
    def __init__(self):
        self.files, self.total = {}, 0

    def add(self, name, raw):
        relative(name)
        if name in self.files:
            require(self.files[name]['sha256'] == sha(raw), 'Immutable artifact changed during observation')
            return
        require(len(raw) <= MAX_FILE and self.total + len(raw) <= MAX_TOTAL, 'Artifact transfer budget exceeded')
        self.total += len(raw)
        self.files[name] = {'sha256': sha(raw), 'size': len(raw), 'base64': base64.b64encode(raw).decode()}


def preconfirm_task_ids(public_plan):
    ids = set()
    for stage in ('search', 'dev'):
        block = public_plan['stages'][stage]
        for condition in block['conditions']:
            for candidate, coefficients in [('clean', [0, 0]), *public_plan['candidates'].items()]:
                for row in block['rows']:
                    ids.add(digest(dict(stage=stage, candidate=candidate, condition=condition,
                                        row=row, coefficients=coefficients)))
    return ids


def collect_run(run, public_plan, capture):
    """Pure file observation, independently testable with temporary CPU fixtures."""
    identity_raw = safe_read(run, 'identity.json')
    if identity_raw is None:
        return {'status': 'identity_not_yet_present', 'confirm_unlocked': False, 'operations': []}
    identity = json.loads(identity_raw)
    require(identity.get('plan_sha256') == PLAN_SHA and identity.get('max_images') == MAX_IMAGES,
            'Run identity differs from frozen exploration')
    capture.add('run/identity.json', identity_raw)
    identity_sha = digest(identity)

    def envelope(name):
        raw = safe_read(run, name)
        if raw is None:
            return None
        data = json.loads(raw)
        require(data.get('identity_sha256') == identity_sha and data.get('sha256') == digest(data.get('payload')),
                'Artifact identity/checksum mismatch: ' + name)
        capture.add('run/' + name, raw)
        return data['payload']

    artifacts = {}
    for stage in ('search', 'dev'):
        for suffix in ('summary', 'selection'):
            name = stage + '_' + suffix + '.json'
            artifacts[name] = envelope(name)
    selection, dev_summary = artifacts['dev_selection.json'], artifacts['dev_summary.json']
    unlocked, binding = False, None
    # The binding contains only already-frozen candidate coefficients, never holdout scores.
    if selection and dev_summary and len(selection.get('selected', [])) == 1:
        require(selection.get('summary_sha256') == digest(dev_summary), 'Development selection/summary binding differs')
        binding = envelope('confirm_binding.json')
        if binding:
            chosen = selection['selected'][0]
            require(chosen in public_plan['candidates'] and chosen != 'naive', 'Invalid frozen confirmation winner')
            expected = {'clean': [0, 0], 'naive': public_plan['candidates']['naive'], chosen: public_plan['candidates'][chosen]}
            require(binding.get('dev_selection_sha256') == digest(selection)
                    and binding.get('candidate_coefficients') == expected, 'Confirmation binding differs from development winner')
            unlocked = True
    # Do not open unknown SHA-named receipts before confirmation is committed.
    allowed = preconfirm_task_ids(public_plan)
    operation_rows, skipped = [], []
    for name in names_in(run, 'operations', MAX_IMAGES):
        require(re.fullmatch('[0-9a-f]{64}\\.json', name) is not None, 'Invalid operation filename')
        if not unlocked and name[:-5] not in allowed:
            skipped.append(name)
            continue
        raw = safe_read(run, 'operations/' + name, MAX_OP_FILE)
        receipt = json.loads(raw)
        task, task_id = receipt['task'], receipt['task_id']
        require(task_id == name[:-5] == digest(task) and receipt.get('identity_sha256') == identity_sha,
                'Operation receipt identity/task checksum mismatch')
        require(task['stage'] in ('search', 'dev', 'confirm') and (unlocked or task['stage'] != 'confirm'), 'Confirmation remains locked')
        status = receipt.get('status')
        require(status in ('started', 'completed'), 'Unknown operation status')
        if status == 'completed':
            record = receipt['record']
            require(receipt.get('record_sha256') == digest(record) and record.get('task_id') == task_id,
                    'Completed score record checksum mismatch')
            require(record.get('stage') == task['stage'] and record.get('candidate') == task['candidate'], 'Record/task mismatch')
            relative(record['image_path'])
            require(re.fullmatch('[0-9a-f]{64}', record['image_sha256']) is not None, 'Missing image hash')
        capture.add('run/operations/' + name, raw)
        operation_rows.append({'task_id': task_id, 'stage': task['stage'], 'candidate': task['candidate'],
                               'condition_id': task['condition']['id'], 'status': status,
                               'started_at': receipt.get('started_at'), 'completed_at': receipt.get('completed_at')})
    # Plain progress contains counts/resource state, not rows, images, or score data.
    progress_raw = safe_read(run, 'progress.json')
    progress = json.loads(progress_raw) if progress_raw is not None else None
    if progress_raw is not None:
        if not unlocked and progress.get('stage') == 'confirm':
            progress = {'stage': 'confirm', 'withheld': True, 'reason': 'Missing verified confirmation binding'}
        else:
            capture.add('run/progress.json', progress_raw)
    for subdir in ('executions', 'failures'):
        for name in names_in(run, subdir, MAX_AUX_FILES):
            raw = safe_read(run, subdir + '/' + name)
            if subdir == 'executions':
                data = json.loads(raw)
                require(data.get('identity_sha256') == identity_sha and data.get('sha256') == digest(data.get('payload')),
                        'Execution metadata checksum mismatch')
            capture.add('run/' + subdir + '/' + name, raw)
    if unlocked:
        for name in ('confirm_summary.json', 'confirm_selection.json'):
            artifacts[name] = envelope(name)
    stopped_early = any(artifacts.get(s + '_selection.json') is not None and not artifacts[s + '_selection.json'].get('selected') for s in ('search', 'dev'))
    # A premature final_report is not opened before a verified selection endpoint.
    if unlocked or stopped_early:
        artifacts['final_report.json'] = envelope('final_report.json')
    counts = {stage: dict(Counter(r['status'] for r in operation_rows if r['stage'] == stage))
              for stage in ('search', 'dev', 'confirm')}
    final = artifacts.get('final_report.json')
    return {'status': 'completed_artifact_present' if final else 'snapshot_collected', 'confirm_unlocked': unlocked,
            'identity_sha256': identity_sha, 'progress': progress, 'stage_operation_counts': counts,
            'completed_images_observed': sum(r['status'] == 'completed' for r in operation_rows),
            'incomplete_operations': [r for r in operation_rows if r['status'] != 'completed'],
            'operations': operation_rows, 'locked_or_unknown_operation_files_not_read': skipped,
            'available_committed_artifacts': [k for k, v in artifacts.items() if v is not None],
            'selections': {s: artifacts.get(s + '_selection.json') for s in ('search', 'dev', 'confirm')},
            'final_report': final, 'image_bytes_read_or_verified': False,
            'snapshot_atomic_across_files': False,
            'limitation': 'Each file is sampled once; active-run counts may lag later writes. Historical failures do not prove the current process failed.'}


def process_snapshot(pid, run):
    record = {'pid': pid}
    root = Path('/proc') / str(pid)
    try:
        uid = root.stat().st_uid
        record.update(uid=uid, owner_is_self=uid == os.getuid(), comm=(root / 'comm').read_text().strip())
        if uid == os.getuid():
            argv = (root / 'cmdline').read_bytes()[:65536].split(b'\0')
            record['matches_fixed_run'] = str(run).encode() in argv and any(x.endswith(b'/tssa_image_search_run.py') for x in argv)
            record['status'] = [x for x in (root / 'status').read_text().splitlines() if x.startswith(('State:', 'VmRSS:', 'Threads:'))]
            record['start_ticks'] = (root / 'stat').read_text().rsplit(')', 1)[1].split()[19]
        record['exists'] = True
    except (OSError, ValueError, IndexError) as exc:
        record.update(exists=False, error=type(exc).__name__)
    return record


def runtime_snapshot(run):
    active = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit() or int(path.name) in (os.getpid(), os.getppid()):
            continue
        try:
            if path.stat().st_uid == os.getuid():
                p = process_snapshot(int(path.name), run)
                if p.get('matches_fixed_run'):
                    active.append(p)
        except OSError:
            continue
    require(len(active) <= 16, 'Too many matching project processes')
    unavailable = {'observed_at': now(), 'active_project_processes': active,
                   'GPU_query_succeeded': False, 'gpus': None, 'own_gpu_uuids_observed': None}
    try:
        sample = subprocess.run(['nvidia-smi', '-q', '-x'], capture_output=True, timeout=20)
    except subprocess.TimeoutExpired:
        return dict(unavailable, query_error={'kind': 'timeout', 'seconds': 20})
    if sample.returncode != 0 or len(sample.stdout) > MAX_FILE:
        return dict(unavailable, query_error={'kind': 'failed_or_oversized',
                    'returncode': sample.returncode, 'stdout_bytes': len(sample.stdout),
                    'stdout_excerpt': sample.stdout[:2048].decode('utf-8', errors='replace'),
                    'stderr_excerpt': sample.stderr[:2048].decode('utf-8', errors='replace')})
    doc = ET.fromstring(sample.stdout)
    gpus = []
    for index, gpu in enumerate(doc.findall('gpu')):
        processes = []
        for item in gpu.findall('./processes/process_info'):
            pid = int(item.findtext('pid'))
            process = process_snapshot(pid, run)
            process.update(type=item.findtext('type'), used_memory=item.findtext('used_memory'))
            processes.append(process)
        gpus.append({'index': index, 'uuid': gpu.findtext('uuid'), 'pci_bus_id': gpu.findtext('./pci/pci_bus_id'),
                     'compute_mode': gpu.findtext('compute_mode'), 'memory_used': gpu.findtext('./fb_memory_usage/used'),
                     'utilization': gpu.findtext('./utilization/gpu_util'), 'processes': processes})
    return {'observed_at': now(), 'GPU_query_succeeded': True, 'driver_timestamp': doc.findtext('timestamp'), 'driver': doc.findtext('driver_version'),
            'active_project_processes': active, 'gpus': gpus,
            'own_gpu_uuids_observed': [g['uuid'] for g in gpus if any(p.get('owner_is_self') for p in g['processes'])]}


def verified_log_name(base, launch):
    """Accept only the exact log sibling committed by this launch token."""
    control = PurePosixPath(str(base / 'launch-control'))
    receipt = PurePosixPath(launch['launch_receipt'])
    token = launch.get('launch_token', '')
    require(re.fullmatch('[0-9a-f]{32}', token) is not None, 'Invalid launch log token')
    require(receipt.parent == control and re.fullmatch(r'[0-9TZ]+-' + token + r'\.receipt\.json', receipt.name),
            'Launch receipt/log token mismatch')
    expected = control / (receipt.name[:-len('.receipt.json')] + '.log')
    require(launch.get('log') == str(expected), 'Log is not the exact committed launch sibling')
    return 'launch-control/' + expected.name


def recovery_request(server, receipt_path, receipt_sha):
    """Explicit opt-in only; never infer a newer launch from arbitrary files."""
    if receipt_path is None and receipt_sha is None:
        return None
    require(server == '103' and isinstance(receipt_path, str) and isinstance(receipt_sha, str),
            'Recovery observation needs both receipt path and SHA256, on server 103 only')
    path = PurePosixPath(receipt_path)
    require(str(path) == receipt_path and path.parent == PurePosixPath(BASES['103']) / 'launch-control'
            and re.fullmatch(RECOVERY_NAME + r'-[0-9a-f]{32}\.receipt\.json', path.name),
            'Recovery receipt is not the fixed manually audited control path')
    require(re.fullmatch('[0-9a-f]{64}', receipt_sha) is not None, 'Invalid recovery receipt SHA256')
    return {'receipt_path': receipt_path, 'receipt_sha256': receipt_sha}


def collect_recovery(base, run, request, old_claim_raw, old_receipt_raw, capture):
    """Verify immutable recovery provenance without reading any outcome scores."""
    require(sha(old_claim_raw) == RECOVERY_OLD_CLAIM_SHA and sha(old_receipt_raw) == RECOVERY_OLD_RECEIPT_SHA,
            'Recovery original launch evidence differs')
    path = PurePosixPath(request['receipt_path'])
    require(path.parent == PurePosixPath(str(base / 'launch-control')), 'Recovery receipt outside project control')
    token = path.name[len(RECOVERY_NAME) + 1:-len('.receipt.json')]
    require(re.fullmatch('[0-9a-f]{32}', token) is not None, 'Recovery token malformed')
    raw = safe_read(base, 'launch-control/' + path.name)
    require(raw is not None and sha(raw) == request['receipt_sha256'], 'Recovery receipt missing or changed')
    receipt = json.loads(raw)
    fixed = {'server': '103', 'run_root': str(run), 'plan_sha256': PLAN_SHA,
             'identity_sha256': RECOVERY_IDENTITY_SHA, 'recovery_token': token,
             'old_pid': 188034,
             'original_claim_sha256': RECOVERY_OLD_CLAIM_SHA,
             'original_spawn_receipt_sha256': RECOVERY_OLD_RECEIPT_SHA,
             'pending_task_id': RECOVERY_PENDING, 'original_pending_sha256': RECOVERY_PENDING_SHA,
             'archive_sha256': RECOVERY_PENDING_SHA, 'receipt': str(path),
             'log': str(path.parent / (RECOVERY_NAME + '-' + token + '.log')),
             'recovery_ledger': str(path.parent / (RECOVERY_NAME + '.ledger.json')),
             'archived_original_receipt': str(path.parent / (RECOVERY_NAME + '.original-started.json')),
             'status': 'runner_process_spawned_not_GPU_acceptance', 'automatic_retry_allowed': False,
             'original_science_manifest_and_source_unchanged': True}
    for key, expected in fixed.items():
        require(receipt.get(key) == expected, 'Recovery binding differs: ' + key)
    require(isinstance(receipt.get('boot_id'), str)
            and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', receipt['boot_id']),
            'Recovery boot ID must be explicit; never infer it from an old launch')
    require(type(receipt.get('pid')) is int and receipt['pid'] > 0 and receipt['pid'] != 188034,
            'Recovery PID is missing or equals old PID')
    ticks = receipt.get('process_start_ticks')
    require((isinstance(ticks, str) and ticks.isdigit() and receipt.get('spawned_process_identity_observed') is True)
            or (ticks is None and receipt.get('spawned_process_identity_observed') is False), 'Invalid recovery process identity')
    require(receipt.get('recovery_gpu', {}).get('uuid') == RECOVERY_GPU_UUID
            and receipt['recovery_gpu'].get('index') == 0, 'Recovery GPU binding differs')
    command = receipt.get('command', [])
    require(isinstance(command, list) and command.count('--run-root') == 1
            and command[command.index('--run-root') + 1] == str(run)
            and command[-3:] == ['--resume', '--until', 'dev'], 'Recovery command is not same run through development only')
    identity_raw = safe_read(run, 'identity.json')
    require(identity_raw is not None and digest(json.loads(identity_raw)) == RECOVERY_IDENTITY_SHA,
            'Recovery run identity mismatch')
    ledger_name = RECOVERY_NAME + '.ledger.json'
    archive_name = RECOVERY_NAME + '.original-started.json'
    claim_name = RECOVERY_NAME + '.claim.json'
    ledger_raw = safe_read(base, 'launch-control/' + ledger_name)
    claim_raw = safe_read(base, 'launch-control/' + claim_name)
    archive_raw = safe_read(base, 'launch-control/' + archive_name, MAX_OP_FILE)
    require(ledger_raw is not None and claim_raw == ledger_raw
            and sha(ledger_raw) == receipt.get('recovery_ledger_sha256'), 'Recovery claim/ledger hash mismatch')
    require(archive_raw is not None and sha(archive_raw) == RECOVERY_PENDING_SHA, 'Archived failed attempt changed')
    ledger, pending = json.loads(ledger_raw), json.loads(archive_raw)
    require(ledger.get('status') == 'recovery_claimed_before_pending_archive', 'Invalid recovery ledger state')
    require(all(digest(receipt.get(k)) == digest(v) for k, v in ledger.items() if k != 'status'),
            'Spawn receipt differs from its immutable recovery ledger')
    require(ledger.get('original_pending_receipt') == pending and pending.get('status') == 'started'
            and pending.get('task_id') == RECOVERY_PENDING == digest(pending.get('task'))
            and pending.get('identity_sha256') == RECOVERY_IDENTITY_SHA and 'record' not in pending,
            'Archived attempt is not the one audited unfinished operation')
    require(pending['task']['stage'] == 'search', 'Archived attempt must not expose confirmation')
    budget = ledger.get('budget', {})
    for key, expected in {'failed_attempts': 1, 'failed_branch_NFE_upper_bound': 50,
                          'failed_text_encoder_forwards_upper_bound': 1, 'failed_VAE_decodes_upper_bound': 1,
                          'failed_work_exact_count': None, 'global_attempt_cap_conservative': 1440,
                          'global_branch_NFE_cap': 72000, 'until_dev_attempts_upper_bound': 865,
                          'until_dev_branch_NFE_upper_bound_including_failure': 43250,
                          'confirmation_permitted_by_this_wrapper': False,
                          'later_confirmation_requires_separate_budget_audit': True}.items():
        require(key in budget and budget[key] == expected, 'Recovery budget differs: ' + key)
    for name, content in ((path.name, raw), (ledger_name, ledger_raw), (claim_name, claim_raw), (archive_name, archive_raw)):
        capture.add('recovery/' + name, content)
    return receipt


def recovery_process_snapshot(receipt, run):
    current = process_snapshot(receipt['pid'], run)
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    matches = (current.get('exists') is True and current.get('owner_is_self') is True
               and current.get('matches_fixed_run') is True and receipt.get('process_start_ticks') is not None
               and current.get('start_ticks') == receipt['process_start_ticks'] and boot_id == receipt['boot_id'])
    current.update(expected_start_ticks=receipt.get('process_start_ticks'), expected_boot_id=receipt['boot_id'],
                   observed_boot_id=boot_id, recovery_process_identity_matches=matches,
                   status_basis='Recovered PID, ownership, fixed run, start ticks, and boot ID; old PID absence is historical only')
    return current


def recovery_accounting(run_snapshot, receipt):
    complete = run_snapshot.get('completed_images_observed')
    operations = run_snapshot.get('operations')
    if type(complete) is not int or not isinstance(operations, list):
        return {'status': 'current_run_counts_unavailable', 'archived_failed_attempts': 1,
                'archived_failed_generation_branch_NFE_upper_bound': 50, 'failure_exact_work_unknown': True}
    failures = receipt['budget']['failed_attempts']
    attempts = len(operations) + failures
    withheld = run_snapshot.get('locked_or_unknown_operation_files_not_read', [])
    coverage = not withheld
    return {'status': 'observed_receipts_plus_preserved_failure', 'completed_unique_images_observed': complete,
            'current_operation_receipts_observed': len(operations),
            'current_incomplete_attempts_observed': len(operations) - complete,
            'archived_failed_attempts': failures, 'archived_failed_generation_branch_NFE_upper_bound': 50,
            'failure_exact_work_unknown': True, 'archived_failed_TE_upper_bound': 1, 'archived_failed_VAE_upper_bound': 1,
            'total_generation_attempts_observed_including_failure': attempts,
            'completed_generation_branch_NFE_observed': complete * 50,
            'known_attempts_generation_branch_NFE_upper_bound_including_failure': attempts * 50,
            'all_current_operation_names_read': coverage, 'withheld_operation_file_count': len(withheld),
            'global_attempt_cap': 1440, 'global_generation_branch_NFE_cap': 72000,
            'observed_counts_within_global_caps': attempts <= 1440 and attempts * 50 <= 72000,
            'complete_global_accounting': coverage,
            'confirmation_permitted_by_recovery_receipt': False,
            'limitation': 'Counts are a read-only snapshot. Failed and in-progress generation work use the 50-NFE bound, not invented exact work; withheld operation files make global accounting incomplete.'}


def filter_locked_log(raw, offset):
    """Allow known preconfirm stage events and diagnostic headers, not arbitrary metrics."""
    text = raw.decode('utf-8', errors='replace')
    dropped_fragment = False
    if offset:
        # The first partial line may be a suffix of an otherwise structured secret.
        text = text.split('\n', 1)[1] if '\n' in text else ''
        dropped_fragment = True
    safe, filtered = [], 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            event = None
        if isinstance(event, dict):
            if (set(event) == {'at', 'stage', 'images', 'selected', 'reason'}
                    and event.get('stage') in ('search', 'dev') and type(event.get('images')) is int
                    and isinstance(event.get('selected'), list)
                    and all(isinstance(x, str) and re.fullmatch('[A-Za-z0-9_-]+', x) for x in event['selected'])
                    and event.get('reason') in ('eligible_candidates', 'no_qualified_candidate',
                        'observed_merge_asr_improvement_with_normal_constraints',
                        'no_candidate_exceeds_naive_macro_with_noninferior_worst')
                    and re.fullmatch(r'[0-9T:+.Z-]+', str(event.get('at', '')))):
                safe.append(json.dumps(event, ensure_ascii=False, sort_keys=True))
            else:
                filtered += 1
            continue
        sensitive = re.search(r'(?i)confirm|heldout|held.out|asr|clip_score|vit_class|(?:score|accuracy)\s*[:=]|macro_difference|worst_difference', stripped)
        diagnostic = (stripped in ('Traceback (most recent call last):',
                       'During handling of the above exception, another exception occurred:',
                       'The above exception was the direct cause of the following exception:')
                      or re.fullmatch(r'File ".+", line [0-9]+, in [A-Za-z0-9_<>]+', stripped)
                      or re.match(r'^[A-Za-z0-9_.]*(?:Error|Exception|Interrupt|Exit|Warning):', stripped))
        if diagnostic and not sensitive:
            safe.append(line)
        else:
            filtered += 1
    returned = ('\n'.join(safe) + ('\n' if safe else '')).encode()
    return returned, {'filtered_nonempty_lines': filtered, 'leading_partial_line_dropped': dropped_fragment,
                      'policy': 'Before confirmation binding: only whitelisted search/dev stage events and diagnostic traceback/error headers; unknown structured/plain lines are withheld.'}


def read_log_tail(base, name, unlocked):
    """Seek once and read at most 16 KiB; never reads a complete unknown large log."""
    path = base.joinpath(*relative(name).parts)
    require(name.startswith('launch-control/') and len(PurePosixPath(name).parts) == 2, 'Log outside launch control')
    require(base.resolve() == base and not base.is_symlink(), 'Log root redirects')
    for ancestor in (base, path.parent):
        require(not ancestor.is_symlink() and ancestor.resolve() == ancestor
                and ancestor.stat().st_uid == os.getuid(), 'Unowned/redirected log ancestor')
    if not path.exists() and not path.is_symlink():
        return {'status': 'committed_log_not_present', 'source_path': str(path), 'full_log': False}
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid(), 'Log is not an owned regular file')
        offset = max(0, before.st_size - MAX_LOG_TAIL)
        os.lseek(fd, offset, os.SEEK_SET)
        remaining, chunks = before.st_size - offset, bytearray()
        while remaining:
            part = os.read(fd, remaining)
            require(bool(part), 'Log was truncated while reading tail')
            chunks.extend(part)
            remaining -= len(part)
        after = os.fstat(fd)
        require(after.st_size >= before.st_size, 'Log was truncated during observation')
        raw = bytes(chunks)
    finally:
        os.close(fd)
    returned, filtering = (raw.decode('utf-8', errors='replace').encode(), {'policy': 'Verified confirmation binding allows this bounded tail'}) if unlocked else filter_locked_log(raw, offset)
    return {'status': 'bounded_tail_returned', 'source_path': str(path), 'full_log': False,
            'source_size_at_start': before.st_size, 'source_size_after_read': after.st_size,
            'source_tail_offset': offset, 'source_tail_size': len(raw), 'source_tail_sha256': sha(raw),
            'returned_utf8_size': len(returned), 'returned_utf8_sha256': sha(returned),
            'confirmation_unlocked': unlocked, 'filtering': filtering,
            'text': returned.decode('utf-8', errors='replace'),
            'limitation': 'Only a bounded tail sampled once; not a complete log. Source-tail hash includes bytes withheld from returned text; it is not a whole-file hash.'}


def collect_remote(payload):
    server = payload['server']
    require(server in BASES and payload['plan_sha256'] == PLAN_SHA, 'Unknown server/plan')
    require(pwd.getpwuid(os.getuid()).pw_name == 'zhangzibo' and os.getuid() != 0, 'Wrong remote account')
    base = Path(BASES[server])
    require(base.is_dir() and base.resolve() == base and base.stat().st_uid == os.getuid(), 'Unexpected project root')
    run = base / 'results' / RUN_NAME
    capture = Capture()
    result = {'server': server, 'run_root': str(run), 'plan_sha256': PLAN_SHA, 'observed_at': now(),
              'read_only': True, 'GPU_launch': False, 'errors': [], 'allocation_permission_inferred': False}
    requested = payload.get('recovery')
    if requested is not None:
        require(recovery_request(server, requested.get('receipt_path'), requested.get('receipt_sha256')) == requested,
                'Invalid recovery observation request')
    claim_name = 'launch-control/image-search-' + PLAN_SHA + '.claim.json'
    receipt, log_name = None, None
    old_claim_raw, old_receipt_raw = None, None
    try:
        raw = safe_read(base, claim_name)
        if raw is not None:
            old_claim_raw = raw
            claim = json.loads(raw)
            require(claim.get('plan_sha256') == PLAN_SHA and claim.get('run_root') == str(run) and claim.get('server') == server, 'Wrong remote launch claim')
            log_name = verified_log_name(base, claim)
            capture.add('launch/' + Path(claim_name).name, raw)
            receipt_path = PurePosixPath(claim['launch_receipt'])
            require(receipt_path.parent == PurePosixPath(str(base / 'launch-control')) and re.fullmatch(r'[0-9TZ]+-[0-9a-f]{32}\.receipt\.json', receipt_path.name), 'Invalid launch receipt path')
            raw = safe_read(base, 'launch-control/' + receipt_path.name)
            if raw is not None:
                old_receipt_raw = raw
                receipt = json.loads(raw)
                require(receipt.get('launch_token') == claim.get('launch_token') and receipt.get('plan_sha256') == PLAN_SHA
                        and receipt.get('run_root') == str(run) and receipt.get('server') == server
                        and verified_log_name(base, receipt) == log_name, 'Launch receipt binding differs')
                capture.add('launch/' + receipt_path.name, raw)
                result['launch'] = {'pid': receipt.get('pid'), 'gpu_uuid': receipt.get('gpu', {}).get('uuid'),
                                    'status': receipt.get('status'), 'started_at': receipt.get('started_at')}
            else:
                result['launch'] = {'status': 'claim_exists_without_spawn_receipt', 'automatic_retry_allowed': False}
        else:
            result['launch'] = {'status': 'no_launch_claim_observed'}
    except Exception as exc:
        result['errors'].append('launch: ' + type(exc).__name__ + ': ' + str(exc))
    original_receipt, original_log_name = receipt, log_name
    recovery = None
    if requested is not None:
        result['original_launch'] = dict(result.get('launch', {}))
        result['active_launch_source'] = 'recovery_unverified'
        receipt, log_name = None, None
        result['launch'] = {'status': 'recovery_provenance_unverified', 'old_PID_absence_is_not_current_exit': True}
        try:
            require(old_claim_raw is not None and old_receipt_raw is not None, 'Original launch provenance unavailable')
            recovery = collect_recovery(base, run, requested, old_claim_raw, old_receipt_raw, capture)
            receipt = recovery
            log_name = 'launch-control/' + Path(recovery['log']).name
            result['active_launch_source'] = 'verified_manual_recovery'
            result['launch'] = {'pid': recovery['pid'], 'gpu_uuid': recovery['recovery_gpu']['uuid'],
                                'status': recovery['status'], 'started_at': recovery['started_at'],
                                'process_start_ticks': recovery.get('process_start_ticks'), 'boot_id': recovery['boot_id']}
            result['recovery'] = {'status': 'provenance_verified', 'receipt_path': requested['receipt_path'],
                                  'receipt_sha256': requested['receipt_sha256'], 'recovery_token': recovery['recovery_token'],
                                  'pending_task_id': recovery['pending_task_id'], 'archive_sha256': recovery['archive_sha256'],
                                  'ledger_sha256': recovery['recovery_ledger_sha256'], 'budget': recovery['budget'],
                                  'automatic_retry_allowed': False}
        except Exception as exc:
            result['errors'].append('recovery: ' + type(exc).__name__ + ': ' + str(exc))
            result['recovery'] = {'status': 'provenance_rejected', 'current_execution_status_unknown': True}
    try:
        result['runtime'] = runtime_snapshot(run)
        if result['runtime'].get('query_error'):
            result['errors'].append('runtime GPU query: ' + json.dumps(result['runtime']['query_error'], sort_keys=True))
        if receipt and type(receipt.get('pid')) is int:
            result['launch_process_now'] = recovery_process_snapshot(receipt, run) if recovery is not None else process_snapshot(receipt['pid'], run)
            gpu_uuid = result.get('launch', {}).get('gpu_uuid')
            result['launch_GPU_now'] = next((g for g in (result['runtime']['gpus'] or []) if g['uuid'] == gpu_uuid), None)
        if requested is not None and original_receipt and type(original_receipt.get('pid')) is int:
            result['original_launch_process_now'] = process_snapshot(original_receipt['pid'], run)
            result['original_launch_process_now']['historical_only'] = True
    except Exception as exc:
        result['errors'].append('runtime: ' + type(exc).__name__ + ': ' + str(exc))
    try:
        result['run'] = collect_run(run, payload['public_plan'], capture) if run.exists() else {'status': 'run_directory_absent'}
    except Exception as exc:
        result['errors'].append('run: ' + type(exc).__name__ + ': ' + str(exc))
    if recovery is not None:
        result['recovery_resource_accounting'] = recovery_accounting(result.get('run', {}), recovery)
        if not result['recovery_resource_accounting'].get('observed_counts_within_global_caps', True):
            result['errors'].append('recovery accounting: observed attempts exceed unchanged global cap; no automatic process action')
    if log_name is not None:
        try:
            result['log_tail'] = read_log_tail(base, log_name, result.get('run', {}).get('confirm_unlocked') is True)
            capture.add(('recovery/' if recovery is not None else 'launch/') + Path(log_name).name + '.tail.json',
                        (json.dumps(result['log_tail'], ensure_ascii=False, indent=2) + '\n').encode())
        except Exception as exc:
            result['errors'].append('log: ' + type(exc).__name__ + ': ' + str(exc))
    if requested is not None and original_log_name is not None:
        try:
            result['original_log_tail'] = read_log_tail(base, original_log_name, result.get('run', {}).get('confirm_unlocked') is True)
            result['original_log_tail']['historical_only'] = True
            capture.add('launch/' + Path(original_log_name).name + '.tail.json',
                        (json.dumps(result['original_log_tail'], ensure_ascii=False, indent=2) + '\n').encode())
        except Exception as exc:
            result['errors'].append('historical log: ' + type(exc).__name__ + ': ' + str(exc))
    result.update(files=capture.files, transferred_raw_bytes=capture.total, finished_at=now())
    return result


def one_bounded_ssh(config, server, command):
    args = ['ssh', '-T', '-F', str(config), '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
            '-o', 'ControlPersist=no', '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes',
            '-o', 'ConnectTimeout=60', '-o', 'ConnectionAttempts=1', 'school' + server, command]
    child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    streams = selectors.DefaultSelector()
    streams.register(child.stdout, selectors.EVENT_READ, 'stdout')
    streams.register(child.stderr, selectors.EVENT_READ, 'stderr')
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    deadline = time.monotonic() + TIMEOUT
    try:
        while streams.get_map():
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'SSH observation exceeded time bound')
            for key, _ in streams.select(min(remaining, 1)):
                part = os.read(key.fd, 65536)
                if not part:
                    streams.unregister(key.fileobj)
                    continue
                buf = buffers[key.data]
                buf.extend(part)
                require(len(buf) <= (MAX_WIRE if key.data == 'stdout' else 65536), 'SSH observation exceeded output bound')
        child.wait(timeout=max(0.01, deadline - time.monotonic()))
        return child.returncode, bytes(buffers['stdout']), bytes(buffers['stderr'])
    finally:
        streams.close()
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=2)
        child.stdout.close()
        child.stderr.close()


def save_bundle(result, output):
    require(result.get('server') in BASES and result.get('plan_sha256') == PLAN_SHA, 'Unexpected response identity')
    require(result.get('run_root') == str(Path(BASES[result['server']]) / 'results' / RUN_NAME), 'Unexpected response run path')
    files, decoded, total = result.get('files', {}), {}, 0
    require(len(files) <= MAX_IMAGES + 100, 'Too many returned files')
    for name, entry in files.items():
        p = relative(name)
        require(p.parts[0] in ('run', 'launch', 'recovery'), 'Unexpected artifact namespace')
        raw = base64.b64decode(entry['base64'], validate=True)
        total += len(raw)
        require(len(raw) <= MAX_FILE and total <= MAX_TOTAL and len(raw) == entry['size'] and sha(raw) == entry['sha256'], 'Returned artifact size/hash mismatch')
        decoded[name] = raw
    # Validate every payload before creating any artifact. A new folder is never reused.
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, raw in decoded.items():
        target = output / 'artifacts' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        files[name] = {k: v for k, v in files[name].items() if k != 'base64'}
        files[name]['local_path'] = str(target)
    return result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == '__remote__':
        require(len(argv) == 2, 'Invalid remote observation request')
        print(json.dumps(collect_remote(json.loads(argv[1])), ensure_ascii=False, allow_nan=False), flush=True)
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', choices=('103', '104'), required=True)
    parser.add_argument('--execute', action='store_true', help='Make one bounded read-only SSH observation; otherwise local plan only')
    parser.add_argument('--recovery-receipt', help='Exact remote path of the manually audited recovery spawn receipt')
    parser.add_argument('--recovery-receipt-sha256', help='Raw SHA256 of that immutable receipt, obtained from recovery evidence')
    args = parser.parse_args(argv)
    plan_raw = (ROOT / PLAN_REL).read_bytes()
    require(sha(plan_raw) == PLAN_SHA, 'Frozen exploration plan changed')
    plan = json.loads(plan_raw)
    public_plan = {'candidates': plan['candidates'], 'stages': {s: plan['stages'][s] for s in ('search', 'dev')}}
    payload = {'server': args.server, 'plan_sha256': PLAN_SHA, 'public_plan': public_plan}
    requested = recovery_request(args.server, args.recovery_receipt, args.recovery_receipt_sha256)
    if requested is not None:
        payload['recovery'] = requested
    if not args.execute:
        print(json.dumps({'status': 'prepared_locally_no_connection', 'server': args.server, 'read_only': True,
                          'run_root': str(Path(BASES[args.server]) / 'results' / RUN_NAME), 'plan_sha256': PLAN_SHA,
                          'max_seconds': TIMEOUT, 'max_files': MAX_IMAGES + 100, 'max_transfer_bytes': MAX_TOTAL,
                          'recovery_observation': requested,
                          'confirm_rows_sent_to_observer': False, 'image_bytes_read_or_verified': False}, indent=2))
        return 0
    out = ROOT / 'results/tssa-opt-exploration-2026-10-28'
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8]
    observation = out / ('observation_' + args.server + '_' + stamp)
    report = {'started_at': now(), 'server': args.server, 'read_only': True, 'GPU_launch': False,
              'observer_sha256': sha(Path(__file__).read_bytes()), 'plan_sha256': PLAN_SHA}
    try:
        sys.path.insert(0, str(ROOT / 'server'))
        from stage_school_assets import SchoolSession
        session = SchoolSession()
        try:
            session.__enter__()  # DNS + temporary configuration only; no model or GPU action.
            config = Path(session.temporary.name) / 'observe-config'
            config.write_text('Host *\n    BatchMode yes\n    StrictHostKeyChecking yes\n    ConnectTimeout 60\n    ConnectionAttempts 1\n    ControlMaster no\n    ControlPath none\n    ControlPersist no\n    UpdateHostKeys no\n    Include "' + str(session.config) + '"\n')
            config.chmod(0o600)
            source = Path(__file__).read_text()
            command = shlex.join([BASES[args.server] + '/venv/bin/python', '-I', '-B', '-c', source, '__remote__', json.dumps(payload, ensure_ascii=False)])
            rc, stdout, stderr = one_bounded_ssh(config, args.server, command)
        finally:
            if hasattr(session, 'temporary'):
                session.temporary.cleanup()  # No control-master exit command and no second SSH call.
        report.update(returncode=rc, stderr=stderr.decode(errors='replace')[-4000:])
        if rc == 0:
            result = save_bundle(json.loads(stdout), observation)
            report.update(status='observed_with_errors' if result['errors'] else 'observed', result=result)
        else:
            report.update(status='connection_or_query_failed', stdout_tail=stdout.decode(errors='replace')[-4000:])
    except Exception as exc:
        report.update(status='failed', error=type(exc).__name__ + ': ' + str(exc))
    report['finished_at'] = now()
    observation.mkdir(mode=0o700, exist_ok=True)
    with (observation / 'report.json').open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    compact = {k: v for k, v in report.items() if k != 'result'}
    if 'result' in report:
        data = report['result']
        compact.update(launch=data.get('launch'), runtime=data.get('runtime'), log_tail=data.get('log_tail'), errors=data['errors'],
                       run={k: v for k, v in data.get('run', {}).items() if k != 'operations'}, returned_files=len(data['files']))
        for key in ('active_launch_source', 'original_launch', 'launch_process_now', 'original_launch_process_now',
                    'recovery', 'recovery_resource_accounting', 'original_log_tail'):
            if key in data:
                compact[key] = data[key]
    print(json.dumps({'report': str(observation / 'report.json'), **compact}, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'observed' else 1


if __name__ == '__main__':
    sys.exit(main())
