#!/usr/bin/env python3
"""Fail-closed, one-shot launch of the frozen image search; default is local prepare.

No research source or scientific manifest is changed. --execute is the only path
that imports the SSH helper. Durable local/target claims are never auto-removed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
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
import xml.etree.ElementTree as ET

PLAN_SHA = '8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6'
PLAN_REL = 'research/tssa_optimization_exploration_2026-10-28.json'
BASES = {'104': '/data2/zhangzibo/arxiv-tssa', '103': '/data1/zhangzibo/arxiv-tssa'}
RUN_NAME = 'tssa-opt-exploration-2026-10-28-v1'
MAX_AGE = 120
XORG_103 = ['/usr/lib/xorg/Xorg', '-core', ':0', '-seat', 'seat0', '-auth',
            '/var/run/lightdm/root/:0', '-nolisten', 'tcp', 'vt7', '-novtswitch']
XWAYLAND_104_GPU0 = {
    'pid': 7187, 'uid': 125, 'account': 'gdm', 'home': '/var/lib/gdm3', 'shell': '/bin/false', 'comm': 'Xwayland',
    'argv': ['/usr/bin/Xwayland', ':1024', '-rootless', '-noreset', '-accessx', '-core', '-auth',
             '/run/user/125/.mutter-Xwaylandauth.ZV08X3', '-listenfd', '4', '-listenfd', '5',
             '-displayfd', '6', '-initfd', '7', '-byteswappedclients'],
}
RESEARCH_ENTRY = 'tssa_image_search_run.py'


class GuardError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise GuardError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def timestamp(value):
    require(isinstance(value, str), 'Missing timestamp')
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise GuardError('Invalid timestamp') from exc
    require(parsed.tzinfo is not None, 'Timestamp must include timezone')
    return parsed


def fresh(value, current, label):
    age = (current - timestamp(value)).total_seconds()
    require(0 <= age <= MAX_AGE, f'{label} is stale or in the future: {age:.3f}s')


def integer(value, label, low=0):
    require(type(value) is int and value >= low, f'Invalid {label}')
    return value


def validate_permission(p, server, current=None):
    current = current or utcnow()
    require(p.get('schema_version') == 1 and p.get('source') == 'manual_authenticated_UI', 'Need manual authenticated UI evidence')
    require(p.get('portal_url') == 'https://gpu.orz2333.fun/' and p.get('account') == 'zhangzibo', 'Wrong portal/account')
    require(str(p.get('server')) == server and server in BASES, 'Wrong server')
    require(p.get('plan_sha256') == PLAN_SHA, 'Permission is for a different exploration')
    require(isinstance(p.get('evidence_note'), str) and len(p['evidence_note'].strip()) >= 10, 'Document actual UI evidence')
    require(p.get('observed_views') == ['我的概况', '服务器状态', 'GPU 排队'], 'All three live views must be reviewed')
    fresh(p.get('observed_at'), current, 'UI observation')
    require(p.get('historical_sample') is False, 'Historical or unknown portal sample')
    if p.get('sample_time_basis') == 'timestamp':
        fresh(p.get('sample_at'), current, 'Portal GPU sample')
    elif p.get('sample_time_basis') == 'live_UI_without_timestamp':
        require(p.get('sample_at') is None and p.get('live_indicator') is True,
                'A live UI without timestamp must be explicitly live; never invent sample time')
    else:
        raise GuardError('Unknown portal sample time basis')
    require(p.get('account_status') == 'normal', 'Account is not normal')
    for name in ('gpu_disabled', 'server_maintenance', 'reservation_conflict', 'other_research_task'):
        require(p.get(name) is False, f'{name} must be explicitly false')
    require(p.get('sample_valid') is True, 'Portal sample is not valid')
    integer(p.get('gpu_index'), 'GPU index')
    require(re.fullmatch(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', p.get('gpu_uuid', '')) is not None, 'Full GPU UUID required')
    own = integer(p.get('own_gpu_count_all_servers'), 'cross-server own count')
    pending = integer(p.get('pending_allocated_gpu_count_all_servers'), 'cross-server pending allocated count')
    quota = integer(p.get('effective_gpu_quota'), 'effective GPU quota', 1)
    limit = min(quota, 4)
    kind = p.get('permission_kind')
    require(kind in ('direct', 'allocated'), 'Unknown permission kind')
    if kind == 'direct':
        require(p.get('direct_use_allowed') is True, 'Direct-use rule not verified')
        require(own + pending + 1 <= limit, 'New direct task would exceed cross-server quota')
    else:
        a = p.get('allocation', {})
        require(a.get('status') == 'confirmed' and a.get('gpu_uuid') == p['gpu_uuid'], 'Allocation must be confirmed for this UUID')
        require(str(a.get('server')) == server and a.get('gpu_index') == p['gpu_index'], 'Allocation targets another card')
        require(a.get('counted_in_pending') is True and pending >= 1, 'Confirmed allocation must count in pending quota')
        assigned, confirmed = timestamp(a.get('assigned_at')), timestamp(a.get('confirmed_at'))
        require(0 <= (confirmed - assigned).total_seconds() <= 600, 'Allocation confirmation missed 10-minute window')
        require(0 <= (current - confirmed).total_seconds() <= 600, 'Allocation start missed 10-minute window')
        require(own + pending <= limit, 'Confirmed allocation exceeds cross-server quota')
    return p


def beneath(path, parent):
    try:
        Path(path).relative_to(Path(parent))
        return True
    except ValueError:
        return False


def validate_deployment(d, plan, server):
    require(d.get('status') == 'deployed_CPU_ready' and d.get('returncode') == 0, 'Deployment did not pass CPU checks')
    require('server' not in d or str(d['server']) == server, 'Deployment server field contradicts target')
    require(d.get('GPU_launch') is False and d.get('plan_sha256') == PLAN_SHA, 'Wrong deployment identity')
    r = d.get('remote', {})
    base = Path(BASES[server])
    code = Path(r.get('code_root', ''))
    require(code.parent == base / 'code' and re.fullmatch(r'image-search-[0-9a-f]{12}', code.name) is not None, 'Deployment code root is not the allowed snapshot')
    require(r.get('GPU_launch') is False and r.get('offline_import', {}).get('CUDA_initialized') is False, 'Missing CPU-only import proof')
    check = r.get('static_plan_check', {})
    require(check.get('passed') is True and check.get('plan_sha256') == PLAN_SHA, 'Static plan check missing or wrong')
    require(check.get('models_loaded') is False and check.get('CUDA_initialized') is False, 'Static deployment check is not CPU-only')
    require(check.get('scorer_device') == 'cpu' and check.get('source_hashes') == plan['source_hashes'], 'Deployment source/scorer mismatch')
    require('OK' in r.get('CPU_tests', '') and 'FAILED' not in r.get('CPU_tests', ''), 'Missing passing CPU tests')
    expected = r.get('verified_files', {})
    wanted = {PLAN_REL: PLAN_SHA,
              'research/tssa_mvp_2026-10-26.json': plan['old_protocol_sha256'],
              'research/tssa_mvp_assets_2026-10-26.json': plan['asset_manifest_sha256']}
    wanted.update({'scripts/merging/' + key: value for key, value in plan['source_hashes'].items()})
    for name, value in wanted.items():
        require(expected.get(name) == value, 'Deployment missing/wrong hash: ' + name)
    for name, value in expected.items():
        path = Path(name)
        require(not path.is_absolute() and '..' not in path.parts and re.fullmatch('[0-9a-f]{64}', value) is not None, 'Unsafe deployment file')
    return str(code), expected


def process_identity(pid):
    p = Path('/proc') / str(pid)
    account = pwd.getpwuid(p.stat().st_uid)
    raw = (p / 'cmdline').read_bytes()
    argv = [part.decode('utf-8', 'strict') for part in raw.rstrip(b'\0').split(b'\0')]
    require(bool(raw) and bool(argv[0]), 'Missing GPU process command')
    return {'pid': pid, 'uid': account.pw_uid, 'account': account.pw_name,
            'home': account.pw_dir, 'shell': account.pw_shell,
            'comm': (p / 'comm').read_text().strip(), 'argv': argv}


def allowed_display(server, index, process):
    if process.get('type') != 'G':
        return False
    if server == '103':
        return (index in (0, 1) and process.get('uid') == 0 and process.get('account') == 'root'
                and process.get('comm') == 'Xorg' and process.get('argv') == XORG_103)
    if server == '104':
        # One observed system display instance, not a general Xwayland permit.
        if index == 0 and all(process.get(key) == value for key, value in XWAYLAND_104_GPU0.items()):
            return True
        return (process.get('uid', 0) != 0 and process.get('account') in ('gdm', 'Debian-gdm')
                and process.get('home') in ('/var/lib/gdm3', '/var/lib/gdm')
                and process.get('shell') in ('/bin/false', '/usr/sbin/nologin', '/sbin/nologin')
                and process.get('comm') == 'gnome-shell'
                and process.get('argv', [None])[0] == '/usr/bin/gnome-shell')
    return False


def inspect_gpu(xml, permission, server, resolver=process_identity, own_uid=None, uid_resolver=None):
    root = ET.fromstring(xml)
    cards = root.findall('gpu')
    index = permission['gpu_index']
    require(index < len(cards), 'Target GPU index is not present')
    card = cards[index]
    require(card.findtext('uuid') == permission['gpu_uuid'], 'GPU index/full UUID mismatch')
    require(card.findtext('compute_mode') == 'Default', 'GPU compute mode is not Default')
    require(card.findtext('mig_mode/current_mig') in (None, 'N/A', 'Disabled'), 'Unexpected MIG state')
    processes = []
    own_cards = set()
    for i, gpu in enumerate(cards):
        require(gpu.find('processes') is not None, 'GPU process listing unavailable')
        for row in gpu.findall('./processes/process_info'):
            try:
                pid = int(row.findtext('pid'))
            except (TypeError, ValueError) as exc:
                raise GuardError('Unresolved GPU process PID') from exc
            # For other cards only UID is needed for quota cross-checking; do
            # not demand readable command lines from unrelated researchers.
            if i != index:
                uid = uid_resolver(pid) if uid_resolver else (Path('/proc') / str(pid)).stat().st_uid
                if own_uid is not None and uid == own_uid:
                    own_cards.add(i)
                continue
            identity = resolver(pid)
            record = dict(identity, type=row.findtext('type'), used_memory=row.findtext('used_memory'))
            if own_uid is not None and record['uid'] == own_uid:
                own_cards.add(i)
            if i == index:
                require(allowed_display(server, index, record), 'Target GPU has a researcher or unknown process: ' + str(pid))
                processes.append(record)
    require(len(own_cards) <= permission['own_gpu_count_all_servers'], 'Live local own cards exceed UI cross-server count')
    require(index not in own_cards, 'Own task already uses target GPU')
    return {'index': index, 'uuid': card.findtext('uuid'), 'pci_bus_id': card.findtext('./pci/pci_bus_id'),
            'compute_mode': card.findtext('compute_mode'), 'driver': root.findtext('driver_version'),
            'driver_timestamp': root.findtext('timestamp'), 'processes': processes, 'local_own_gpu_count': len(own_cards)}


def active_search_processes():
    hits = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            args = (proc / 'cmdline').read_bytes().split(b'\0')
            if any(Path(arg.decode('utf-8', 'strict')).name == RESEARCH_ENTRY for arg in args if arg):
                hits.append(int(proc.name))
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError) as exc:
            raise GuardError('Cannot determine own research process state') from exc
    return hits


def fsync_directory(path):
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def exclusive_json(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    # Persist the new file entry and the possibly new launch-control directory
    # entry before treating a permanent claim/result/receipt as committed.
    fsync_directory(path.parent)
    fsync_directory(path.parent.parent)


def owned_real(path):
    require(not path.is_symlink() and path.resolve() == path, 'Symlink/redirection forbidden: ' + str(path))
    require(path.stat().st_uid == os.getuid(), 'Not owned by current account: ' + str(path))
    require(path.stat().st_mode & 0o022 == 0, 'Group/world writable path: ' + str(path))


def runner_command(base, code, run):
    return [str(base / 'venv/bin/python'), '-B', str(code / 'scripts/merging' / RESEARCH_ENTRY), 'run',
            '--plan', str(code / PLAN_REL), '--old-protocol', str(code / 'research/tssa_mvp_2026-10-26.json'),
            '--asset-manifest', str(code / 'research/tssa_mvp_assets_2026-10-26.json'),
            '--models-root', str(base / 'models'), '--run-root', str(run), '--scorer-device', 'cpu', '--until', 'confirm']


def prepare_runtime_directories(base):
    """Create only our data directories; reject symlinks and unsafe ownership."""
    owned_real(base)
    paths = []
    for relative in ('results', 'tmp', 'cache', 'cache/huggingface', 'cache/torch', 'cache/triton'):
        path = base / relative
        require(not path.is_symlink(), 'Runtime directory is redirected: ' + str(path))
        path.mkdir(mode=0o750, exist_ok=True)
        owned_real(path)
        require(path.is_dir(), 'Runtime path is not a directory: ' + str(path))
        paths.append(str(path))
    return paths


def runner_environment(base, gpu_uuid, inherited=None):
    env = dict(os.environ if inherited is None else inherited)
    for key in list(env):
        if key.startswith(('PYTHON', 'CUDA', 'NVIDIA', 'PIP_', 'HF_', 'TRANSFORMERS_')) or key in ('VIRTUAL_ENV', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV', 'LD_PRELOAD', 'LD_LIBRARY_PATH'):
            env.pop(key, None)
    env.update(CUDA_VISIBLE_DEVICES=gpu_uuid, GPU_UUID=gpu_uuid, CUBLAS_WORKSPACE_CONFIG=':4096:8',
               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HF_DATASETS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', PIP_NO_INDEX='1', PIP_CONFIG_FILE='/dev/null',
               TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
               XDG_CACHE_HOME=str(base / 'cache'), HF_HOME=str(base / 'cache/huggingface'),
               TORCH_HOME=str(base / 'cache/torch'), TRITON_CACHE_DIR=str(base / 'cache/triton'), TMPDIR=str(base / 'tmp'))
    return env


def remote_launch(payload):
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64'
            and pwd.getpwuid(os.getuid()).pw_name == 'zhangzibo' and os.getuid() != 0, 'Wrong host account/architecture')
    server = payload['server']
    permission = validate_permission(payload['permission'], server)
    require(payload['plan_sha256'] == PLAN_SHA, 'Wrong frozen plan')
    base = Path(BASES[server])
    code = Path(payload['code_root'])
    require(code.parent == base / 'code', 'Wrong code root')
    owned_real(base)
    owned_real(code)
    require(base.stat().st_dev != Path('/').stat().st_dev, 'Data root is on system disk')
    plan = json.loads((code / PLAN_REL).read_text())
    require(digest((code / PLAN_REL).read_bytes()) == PLAN_SHA, 'Plan changed after deployment')
    checked_code, expected = validate_deployment(payload['deployment'], plan, server)
    require(str(code) == checked_code and expected == payload['expected_files'], 'Deployment payload mismatch')
    for name, value in expected.items():
        path = code / name
        owned_real(path)
        require(path.is_file() and digest(path.read_bytes()) == value, 'Remote source hash mismatch: ' + name)
    python = base / 'venv/bin/python'
    require(python.is_file() and os.access(python, os.X_OK), 'Prepared venv Python missing')
    require(beneath(python.resolve(), base.parent) or beneath(python.resolve(), Path(pwd.getpwuid(os.getuid()).pw_dir)), 'Python outside own data/home')
    require(python.resolve().stat().st_uid == os.getuid(), 'Python not owned by account')
    directories = prepare_runtime_directories(base)
    run = base / 'results' / RUN_NAME
    require(not run.exists() and not run.is_symlink(), 'Existing run requires manual audit; never relaunch')
    require(not active_search_processes(), 'An image search process already exists')
    control = base / 'launch-control'
    control.mkdir(mode=0o700, exist_ok=True)
    owned_real(control)
    claim = control / ('image-search-' + PLAN_SHA + '.claim.json')
    require(not claim.exists() and not claim.is_symlink(), 'Remote claim exists; no automatic retry')
    lockpath = control / ('image-search-' + PLAN_SHA + '.lock')
    require(not lockpath.is_symlink(), 'Remote lock is a symlink')
    with lockpath.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not claim.exists() and not run.exists(), 'Concurrent or previous launch detected')
        validate_permission(permission, server)
        sample = subprocess.run(['nvidia-smi', '-q', '-x'], check=True, capture_output=True, text=True, timeout=15)
        gpu = inspect_gpu(sample.stdout, permission, server, own_uid=os.getuid())
        require(not active_search_processes(), 'Search became active during preflight')
        validate_permission(permission, server)
        token = payload['token']
        require(re.fullmatch('[0-9a-f]{32}', token) is not None, 'Bad launch token')
        stamp = utcnow().strftime('%Y%m%dT%H%M%S%fZ')
        logpath = control / (stamp + '-' + token + '.log')
        receiptpath = control / (stamp + '-' + token + '.receipt.json')
        command = runner_command(base, code, run)
        env = runner_environment(base, permission['gpu_uuid'])
        receipt = {'at': utcnow().isoformat(), 'plan_sha256': PLAN_SHA, 'launch_token': token,
                   'server': server, 'gpu': gpu, 'run_root': str(run), 'command': command,
                   'log': str(logpath), 'launch_receipt': str(receiptpath),
                   'permission_sha256': payload['permission_sha256'], 'deployment_sha256': payload['deployment_sha256'],
                   'launcher_sha256': payload['launcher_sha256'], 'source_files_verified': expected,
                   'prepared_runtime_directories': directories,
                   'CUBLAS_WORKSPACE_CONFIG': env['CUBLAS_WORKSPACE_CONFIG'],
                   'status': 'launch_attempt_committed_not_yet_confirmed', 'automatic_retry_allowed': False}
        # Durable claim exists BEFORE Popen; even a crash here needs manual audit.
        exclusive_json(claim, receipt)
        with logpath.open('xb') as log:
            child = subprocess.Popen(command, cwd=code, env=env, stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
        receipt.update(status='runner_process_spawned_not_GPU_acceptance', pid=child.pid, started_at=utcnow().isoformat())
        exclusive_json(receiptpath, receipt)
        return receipt


def permission_template(server):
    return {'schema_version': 1, 'source': 'manual_authenticated_UI', 'portal_url': 'https://gpu.orz2333.fun/',
            'account': 'zhangzibo', 'plan_sha256': PLAN_SHA, 'server': server,
            'observed_views': ['我的概况', '服务器状态', 'GPU 排队'],
            'observed_at': None, 'sample_at': None, 'sample_time_basis': None,
            'live_indicator': None, 'historical_sample': None, 'evidence_note': None, 'account_status': None,
            'gpu_index': None, 'gpu_uuid': None, 'gpu_disabled': None, 'sample_valid': None,
            'server_maintenance': None, 'reservation_conflict': None, 'other_research_task': None,
            'own_gpu_count_all_servers': None, 'pending_allocated_gpu_count_all_servers': None,
            'effective_gpu_quota': None, 'permission_kind': 'direct', 'direct_use_allowed': None}


def validate_local_state(out):
    state = json.loads((out / 'progress_state.json').read_text())
    require(state.get('frozen_plan_sha256') == PLAN_SHA, 'Local progress belongs to another freeze')
    require(state.get('status') in ('CPU_deployed_waiting_for_ready_permitted_GPU', 'ready_for_first_GPU_launch'), 'Local progress is not ready for a first launch')
    require(state.get('scientific_images_completed') == 0 and state.get('optimizer_updates') == 0, 'Prior scientific work exists; do not repeat')
    require(state.get('active_GPU_processes_started_by_this_exploration') == [], 'Own prior launch state is active or unknown')
    control = out / 'launch-control'
    if control.exists():
        require(not control.is_symlink(), 'Local control path is redirected')
        evidence = list(control.glob('*.json'))
        require(not evidence, 'Prior local launch evidence exists; manual audit required')


def local_prepare(root, deployment_path, permission_path, server):
    validate_local_state(root / 'results/tssa-opt-exploration-2026-10-28')
    plan_raw = (root / PLAN_REL).read_bytes()
    require(digest(plan_raw) == PLAN_SHA, 'Frozen manifest mismatch')
    plan = json.loads(plan_raw)
    deployment_raw, permission_raw = deployment_path.read_bytes(), permission_path.read_bytes()
    deployment, permission = json.loads(deployment_raw), json.loads(permission_raw)
    validate_permission(permission, server)
    code, expected = validate_deployment(deployment, plan, server)
    for name, value in expected.items():
        require(digest((root / name).read_bytes()) == value, 'Local source differs from deployed snapshot: ' + name)
    base = Path(BASES[server])
    return {'server': server, 'plan_sha256': PLAN_SHA, 'code_root': code, 'expected_files': expected,
            'deployment': deployment, 'deployment_sha256': digest(deployment_raw),
            'permission': permission, 'permission_sha256': digest(permission_raw),
            'command': runner_command(base, Path(code), base / 'results' / RUN_NAME),
            'automatic_retry_allowed': False}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == '__remote__':
        print(json.dumps(remote_launch(json.loads(argv[1])), ensure_ascii=False), flush=True)
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True, choices=sorted(BASES))
    parser.add_argument('--deployment', type=Path)
    parser.add_argument('--permission', type=Path)
    parser.add_argument('--permission-template', action='store_true')
    parser.add_argument('--execute', action='store_true', help='Perform one remote launch attempt; otherwise local preparation only')
    args = parser.parse_args(argv)
    if args.permission_template:
        require(not args.execute, 'Template generation never launches')
        print(json.dumps(permission_template(args.server), ensure_ascii=False, indent=2))
        return 0
    require(args.deployment is not None and args.permission is not None, '--deployment and --permission are required')
    source_path = Path(__file__).resolve()
    root, out = source_path.parents[2], source_path.parent
    payload = local_prepare(root, args.deployment, args.permission, args.server)
    payload['launcher_sha256'] = digest(source_path.read_bytes())
    if not args.execute:
        print(json.dumps(dict(mode='prepared_locally_no_connection', **payload), ensure_ascii=False, indent=2))
        return 0
    state = out / 'launch-control'
    state.mkdir(mode=0o700, exist_ok=True)
    owned_real(state)
    claim = state / ('image-search-' + PLAN_SHA + '.claim.json')
    lockpath = state / ('image-search-' + PLAN_SHA + '.lock')
    require(not lockpath.is_symlink(), 'Local lock must not be a symlink')
    with lockpath.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        validate_local_state(out)
        require(not claim.exists() and not claim.is_symlink(), 'Local claim exists: inspect evidence, never auto-retry on either server')
        validate_permission(payload['permission'], args.server)
        payload['token'] = uuid.uuid4().hex
        record = {'at': utcnow().isoformat(), 'plan_sha256': PLAN_SHA, 'server': args.server,
                  'token': payload['token'], 'status': 'attempt_claimed_before_connection',
                  'permission_sha256': payload['permission_sha256'], 'deployment_sha256': payload['deployment_sha256'],
                  'launcher_sha256': payload['launcher_sha256'], 'automatic_retry_allowed': False}
        exclusive_json(claim, record)
        report = dict(record)
        try:
            sys.path.insert(0, str(root / 'server'))
            from stage_school_assets import SchoolSession
            with SchoolSession() as session:
                source = source_path.read_text()
                require(digest(source.encode()) == payload['launcher_sha256'], 'Launcher changed after claim')
                command = shlex.join([BASES[args.server] + '/venv/bin/python', '-I', '-c', source, '__remote__', json.dumps(payload, ensure_ascii=False)])
                result = subprocess.run(['ssh', '-F', str(session.config), '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                                         'school' + args.server, command], capture_output=True, text=True, timeout=90)
                report.update(returncode=result.returncode, stderr=result.stderr[-5000:])
                if result.returncode == 0:
                    remote = json.loads(result.stdout)
                    require(remote.get('launch_token') == payload['token'] and remote.get('plan_sha256') == PLAN_SHA, 'Wrong remote receipt')
                    require(remote.get('status') == 'runner_process_spawned_not_GPU_acceptance', 'No confirmed spawn receipt')
                    report.update(status=remote['status'], remote=remote)
                else:
                    report.update(status='remote_failed_or_unknown_manual_audit_required', stdout=result.stdout[-5000:])
        except Exception as exc:
            report.update(status='connection_or_launch_unknown_manual_audit_required', error=type(exc).__name__ + ': ' + str(exc))
        report['finished_at'] = utcnow().isoformat()
        target = state / (payload['token'] + '.result.json')
        exclusive_json(target, report)
        print(json.dumps(dict(report_path=str(target), **report), ensure_ascii=False, indent=2))
        return 0 if report['status'] == 'runner_process_spawned_not_GPU_acceptance' else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (GuardError, OSError, ValueError, KeyError) as error:
        print(json.dumps({'status': 'refused', 'error': type(error).__name__ + ': ' + str(error),
                          'automatic_retry_allowed': False}), file=sys.stderr)
        sys.exit(2)
