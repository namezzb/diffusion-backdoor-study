"""Independent bounded semantic diagnostic; never resumes or samples images.

CPU preparation and execution are separate commands. A run needs a hash-frozen
plan, matching CPU preflight and fresh resource permission evidence. Every cell
and each compute reservation is durably written before computation begins.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import stat
import threading
import time
import traceback
import xml.etree.ElementTree as ET

from tssa_target_semantic_cache import (ASSET_SHA, PROTOCOL_SHA, canonical, require, sha, verify_folder,
                                       verify_tensor_derivation)
from tssa_target_semantic_gates import (STAGES, UNITS, CONDITIONS, RESOURCE_KEYS,
    budget_enumeration, budget_totals, check_stage, points_for_stage, expected_resource)

CODE_FILES = ('tssa_target_semantic_run.py', 'tssa_target_semantic_cache.py',
              'tssa_target_semantic_gates.py', 'tssa_target_semantic_runtime.py',
              'tssa_sd_runtime.py', 'tssa_gradient_core.py')
LIMITS = dict(zip(RESOURCE_KEYS, (462, 96, 14, 44, 14)))
PLAN_ID = 'tssa-target-semantic-diagnostic-2026-10-28-v1'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_directory(path):
    path = Path(path)
    if not path.exists():
        ensure_directory(path.parent)
        path.mkdir(mode=0o700)
        sync_directory(path.parent)
    require(path.is_dir() and not path.is_symlink(), 'Output directory redirects')


def write_new(path, raw):
    path = Path(path)
    ensure_directory(path.parent)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def write_json(path, value):
    write_new(path, canonical(value))


def code_hashes():
    return {name: sha((Path(__file__).parent / name).read_bytes()) for name in CODE_FILES}


def package_versions():
    return {name: importlib.metadata.version(name) for name in
            ('torch', 'diffusers', 'transformers', 'safetensors', 'huggingface-hub', 'numpy')}


def inputs(protocol_path, asset_path, cache_root):
    require(sha(Path(protocol_path).read_bytes()) == PROTOCOL_SHA, 'Original protocol changed')
    require(sha(Path(asset_path).read_bytes()) == ASSET_SHA, 'Original asset manifest changed')
    audit = verify_folder(cache_root)
    return {'protocol_sha256': PROTOCOL_SHA, 'asset_manifest_sha256': ASSET_SHA,
            'cache_audit_sha256': sha((Path(cache_root) / 'cache_audit.json').read_bytes()),
            'source_run_identity_sha256': audit['source_run_identity_sha256'],
            'implementation_sha256': code_hashes()}, audit


def cpu_prepare(protocol_path, asset_path, models_root, cache_root):
    import torch
    from tssa_target_semantic_runtime import load_semantic_cpu_assets, audit_semantic_cpu_basis
    require(not torch.cuda.is_initialized(), 'CPU preparation must precede CUDA')
    binding, audit = inputs(protocol_path, asset_path, cache_root)
    derivation = verify_tensor_derivation(cache_root, audit)
    assets = load_semantic_cpu_assets(protocol_path, asset_path, models_root)
    basis = audit_semantic_cpu_basis(assets)
    old_keys = json.loads((Path(cache_root) / 'parameter_key_manifest.json').read_text())
    # The old manifest stores its ordered parameter domain separately from statistics.
    require(type(old_keys) is list and list(assets.parameter_names) == old_keys, 'Original parameter domain differs')
    identity = json.loads((Path(cache_root) / 'run_identity.json').read_text())
    for name, entry in assets.file_hashes.items():
        require(entry['sha256'] == identity['local_file_sha256'][name], 'Loaded model differs from cache source')
    old_basis = json.loads((Path(cache_root) / 'basis_statistics.json').read_text())
    require(basis['statistics'] == old_basis, 'Original basis statistics differ')
    require(not torch.cuda.is_initialized(), 'CPU loading initialized CUDA')
    report = {'schema_version': 1, 'status': 'passed', 'binding': binding,
              'basis': basis, 'model_files': assets.file_hashes, 'packages': package_versions(),
              'compatibility': assets.compatibility, 'cuda_initialized': False,
              'cache_derivation': derivation,
              'images': 0, 'model_forwards': 0, 'optimizer_updates': 0}
    return assets, audit, report


def validate_plan(plan, binding, preflight):
    require(plan.get('schema_version') == 1 and plan.get('id') == PLAN_ID and plan.get('status') == 'frozen',
            'An independent frozen diagnostic plan is required')
    require(plan.get('binding') == binding, 'Plan input/source identity mismatch')
    require(plan.get('preflight_sha256') == sha(canonical(preflight)), 'CPU preflight changed')
    require(plan.get('budget') == LIMITS == budget_totals(), 'Diagnostic budget changed')
    require(plan.get('operations') == budget_enumeration(), 'Operation schedule changed')
    require(plan.get('wall_seconds_max') == 1800 and plan.get('automatic_retry') is False,
            'Wall time or retry policy changed')
    require(plan.get('images') == plan.get('optimizer_updates') == plan.get('new_trajectories') == 0,
            'This plan cannot authorize scientific images, updates or trajectories')
    require(preflight.get('status') == 'passed' and preflight.get('binding') == binding,
            'CPU preflight not bound to this implementation')
    execution = plan.get('execution', {})
    require(set(execution) == {'server', 'machine_id_sha256', 'run_root', 'claim_path', 'gpu_uuid'},
            'Plan must bind one host, GPU, permanent claim and output')
    bases = {'103': '/data1/zhangzibo/arxiv-tssa', '104': '/data2/zhangzibo/arxiv-tssa'}
    base = bases.get(execution['server'])
    require(base is not None and execution['run_root'] == base + '/results/' + PLAN_ID and
            execution['claim_path'] == base + '/claims/' + PLAN_ID + '.json', 'Unbound output/claim path')


def claim_execution(plan, output):
    execution = plan['execution']
    require(str(output) == execution['run_root'] and Path(output).parent.resolve() == Path(output).parent,
            'Output differs from unique frozen run root')
    require(sha(Path('/etc/machine-id').read_bytes()) == execution['machine_id_sha256'], 'Wrong execution host')
    require(os.environ.get('GPU_UUID') == execution['gpu_uuid'], 'Wrong frozen GPU')
    claim = Path(execution['claim_path'])
    ensure_directory(claim.parent)
    require(claim.parent.stat().st_uid == os.getuid(), 'Claim directory not owned by this account')
    write_json(claim, {'plan_sha256': sha(canonical(plan)), 'run_root': str(output),
                      'at': now(), 'pid': os.getpid(), 'automatic_retry': False})


class Ledger:
    """Append-only reservation ledger, with global and individual cell caps."""

    def __init__(self, root, identity, clock=time.monotonic):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=False, exist_ok=False)
        sync_directory(self.root.parent)
        self.clock, self.started, self.timer = clock, None, None
        self.identity = deepcopy(identity)
        self.total = dict.fromkeys(RESOURCE_KEYS, 0)
        self.cell_total = None
        self.current = None
        self.sequence = 0
        self.begun = False
        write_json(self.root / 'identity.json', self.identity)

    def start_cuda_window(self, hard_watchdog=True):
        require(self.started is None, 'CUDA window can start only once')
        self.started = self.clock()
        write_json(self.root / 'cuda_window_started.json', {'at': now(), 'wall_seconds_max': 1800})
        if hard_watchdog:
            def abort():
                try:
                    write_json(self.root / 'wall_timeout.json', {'status': 'failed_wall_limit', 'at': now(),
                               'reserved': deepcopy(self.total), 'cell': deepcopy(self.current),
                               'automatic_retry': False})
                finally:
                    # Process exit releases its own CUDA context, even if a C call has hung.
                    os._exit(124)
            self.timer = threading.Timer(1800, abort)
            self.timer.daemon = True
            self.timer.start()

    def check_time(self):
        require(self.started is not None, 'CUDA window has not started')
        require(self.clock() - self.started < 1800, 'CUDA wall limit exhausted')

    def start_cell(self, operation):
        self.check_time()
        require(self.current is None, 'Previous cell was not completed')
        self.current = deepcopy(operation)
        self.cell_total = dict.fromkeys(RESOURCE_KEYS, 0)
        self.begun = False
        name = sha(canonical(operation))
        write_json(self.root / 'cells' / (name + '.started.json'),
                   {'operation': operation, 'at': now(), 'reserved_before': self.total,
                    'identity_sha256': sha(canonical(self.identity))})
        return name

    def reserve(self, event):
        self.check_time()
        require(self.current is not None, 'No current cell')
        require(event['unit_id'] == self.current['unit_id'] and
                event['condition_id'] == self.current['condition_id'] and
                (None if event['coefficients'] is None else list(event['coefficients'])) ==
                self.current['coefficients'], 'Backend cell identity mismatch')
        require(event.get('kind') == ('teacher' if self.current['stage'] == 'D0' else 'student') and
                event.get('gradients') is (self.current['stage'] == 'D2'), 'Backend stage role mismatch')
        cost = event['cost']
        require(set(cost) == set(RESOURCE_KEYS) and all(type(v) is int and v >= 0 for v in cost.values()),
                'Malformed cost')
        if event['operation'] == 'begin':
            require(not self.begun and all(v == 0 for v in cost.values()), 'Duplicate/nonzero begin')
            self.begun = True
        else:
            require(self.begun and any(cost.values()), 'Compute must follow exactly one begin')
        total = {k: self.total[k] + cost[k] for k in RESOURCE_KEYS}
        cell = {k: self.cell_total[k] + cost[k] for k in RESOURCE_KEYS}
        require(all(total[k] <= LIMITS[k] and cell[k] <= self.current['resource_delta'][k] for k in RESOURCE_KEYS),
                'Attempt would exceed frozen budget')
        self.sequence += 1
        write_json(self.root / 'reservations' / ('%06d.json' % self.sequence),
                   {'at': now(), 'event': event, 'cell': self.current,
                    'reserved_total': total, 'reserved_cell': cell})
        self.total, self.cell_total = total, cell

    def validate_cell_work(self, actual):
        self.check_time()
        require(self.begun and actual == self.cell_total == self.current['resource_delta'],
                'Actual, reserved and planned cell work differ')

    def close(self):
        if self.timer is not None:
            self.timer.cancel()


def make_units(audit, cache_root):
    import torch
    units = {}
    for uid, suffix in zip(UNITS, ('00', '04')):
        pair, extra = audit['cache']['fit_pair_' + suffix], audit['cache']['fit_extra_' + suffix]
        def tensor(entry):
            raw = (Path(cache_root) / entry['tensor']).read_bytes()
            require(sha(raw) == entry['tensor_sha256'], 'Latent changed before model call')
            # Deployment is Linux x86_64, which uses little-endian IEEE float32.
            import sys
            require(sys.byteorder == 'little', 'Unsupported tensor byte order')
            return torch.frombuffer(bytearray(raw), dtype=torch.float32).clone().reshape(1, 4, 64, 64)
        normal = pair['prompt']['normal']
        units[uid] = {'id': uid, 'normal': normal, 'triggered': pair['prompt']['triggered'],
                      'target': re.sub(r'\bdog\b', 'cat', normal), 'extra_prompt': extra['prompt']['prompt'],
                      'pair_latent': tensor(pair), 'extra_latent': tensor(extra),
                      'timestep': 481, 'denoising_step_1based': 13}
    return units


def execute_stages(ledger, backend, units, conditions):
    import torch
    teachers, naive, stage_records = {}, {}, {}
    results = []
    for stage in STAGES:
        rows = []
        for point in points_for_stage(stage):
            for uid in UNITS:
                for cid in CONDITIONS:
                    operation = dict(stage=stage, **point, unit_id=uid, condition_id=cid,
                                     resource_delta=expected_resource(stage, cid))
                    name = ledger.start_cell(operation)
                    key = (uid, cid)
                    if stage == 'D0':
                        value = backend.teacher(units[uid], conditions[cid])
                        teachers[key] = value
                    else:
                        value = backend.student(units[uid], conditions[cid], point['coefficients'],
                                                teachers[key], gradients=stage == 'D2')
                    outputs = value['outputs']
                    expected_keys = {'normal', 'extra'} if cid == 'upload' else {'normal', 'triggered', 'extra'}
                    if stage == 'D0' and cid != 'upload':
                        expected_keys.add('target')
                    require(set(outputs) == expected_keys, 'Response domain differs')
                    output_hashes = {}
                    for response, tensor in outputs.items():
                        require(tensor.device.type == 'cpu' and tensor.dtype == torch.float32 and
                                tuple(tensor.shape) == (1, 4, 64, 64) and not tensor.requires_grad and
                                tensor.grad_fn is None and bool(torch.isfinite(tensor).all()), 'Invalid detached output')
                        raw = tensor.contiguous().numpy().tobytes()
                        write_new(ledger.root / 'outputs' / name / (response + '.f32'), raw)
                        output_hashes[response] = sha(raw)
                    row = {k: operation[k] for k in ('stage', 'point_id', 'unit_id', 'condition_id')}
                    row.update(output_rms=value['output_rms'], losses=value['losses'],
                               gradients=value['gradients'] if stage == 'D2' else None,
                               errors_vs_teacher=value['errors_vs_teacher'] if stage == 'D1' else None,
                               signal_rms=value['signal_rms'] if stage == 'D0' and cid != 'upload' else None,
                               resource_delta=value['resource_delta'])
                    if stage == 'D2':
                        naive[key] = outputs
                    if stage == 'D2r':
                        row['errors_vs_naive'] = {k: float((v - naive[key][k]).square().mean().sqrt())
                                                 for k, v in outputs.items()}
                    ledger.validate_cell_work(value['resource_delta'])
                    payload = {k: v for k, v in value.items() if k != 'outputs'}
                    write_json(ledger.root / 'cells' / (name + '.completed.json'),
                               {'record': row, 'backend_evidence': payload, 'output_sha256': output_hashes,
                                'reserved_total': ledger.total, 'at': now()})
                    ledger.current = None
                    rows.append(row)
        result = check_stage(stage, rows, stage_records)
        write_json(ledger.root / ('stage_' + stage + '.json'), {'records': rows, 'gate': result})
        stage_records[stage] = rows
        results.append(result)
        if result['status'] not in ('prefix_pass', 'diagnostic_pass'):
            return {'status': 'stopped_at_scientific_gate', 'stage': stage, 'gate': result,
                    'stages': results, 'images': 0, 'optimizer_updates': 0, 'ASR_validated': False}
    require(ledger.total == LIMITS, 'Complete schedule did not consume exact frozen budget')
    return {'status': 'local_diagnostic_passed', 'stages': results, 'images': 0,
            'optimizer_updates': 0, 'ASR_validated': False,
            'claim_limit': 'Two reused fit units at t481 only; no generated image or ASR conclusion.'}


def collect_process_identity(pid, process_type, process_name):
    """Bind one graphics process; exact known system displays may lack exe access."""
    require(type(pid) is int and pid > 0 and process_type == 'G',
            'GPU has an unapproved research or graphics process')
    proc = Path('/proc') / str(pid)

    def instance():
        return (proc.stat().st_uid,
                (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19])

    uid, start_ticks = instance()
    record = {'pid': pid, 'type': process_type, 'name': process_name,
              'uid': uid, 'start_ticks': start_ticks}
    try:
        record['executable'] = os.readlink(proc / 'exe')
    except PermissionError:
        # Linux denies cross-uid exe reads even for a normal system display service.
        # No other readlink error, account, command, or executable is an exception.
        displays = {
            '/usr/bin/gnome-shell': {
                'account': 'gdm', 'home': '/var/lib/gdm3', 'shell': '/bin/false', 'comm': 'gnome-shell',
                'argv': ['/usr/bin/gnome-shell'], 'uid_ok': 0 < uid < 1000},
            '/usr/lib/xorg/Xorg': {
                'account': 'root', 'home': '/root', 'shell': '/bin/bash', 'comm': 'Xorg',
                'argv': ['/usr/lib/xorg/Xorg', '-core', ':0', '-seat', 'seat0', '-auth',
                         '/var/run/lightdm/root/:0', '-nolisten', 'tcp', 'vt7', '-novtswitch'],
                'uid_ok': uid == 0},
        }
        display = displays.get(process_name)
        require(display is not None, 'Permission-denied exe is not a verified system display service')
        account = pwd.getpwuid(uid)
        comm_raw = (proc / 'comm').read_text()
        cmdline = (proc / 'cmdline').read_bytes()
        uid_rows = [line.split()[1:] for line in (proc / 'status').read_text().splitlines()
                    if line.startswith('Uid:')]
        require(display['uid_ok'] and account.pw_uid == uid and account.pw_name == display['account'] and
                account.pw_dir == display['home'] and account.pw_shell == display['shell'] and
                comm_raw == display['comm'] + '\n' and
                cmdline == ('\0'.join(display['argv']) + '\0').encode() and uid_rows == [[str(uid)] * 4],
                'Permission-denied exe is not the verified system display service')
        executable = Path(process_name)

        def executable_metadata():
            info = executable.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
                    info.st_mode & 0o111 and not info.st_mode & 0o022,
                    'System display executable is not a root-owned regular executable')
            return {key: getattr(info, 'st_' + key) for key in
                    ('dev', 'ino', 'mode', 'uid', 'gid', 'size', 'mtime_ns', 'ctime_ns')}

        metadata = executable_metadata()
        raw = executable.read_bytes()
        require(raw.startswith(b'\x7fELF') and executable_metadata() == metadata,
                'System display executable is not a stable ELF binary')
        record.update(executable=str(executable), executable_evidence='system_display_permission_denied',
                      comm=display['comm'], cmdline=display['argv'],
                      account={'name': account.pw_name, 'uid': account.pw_uid, 'gid': account.pw_gid,
                               'home': account.pw_dir, 'shell': account.pw_shell},
                      process_uids=[uid] * 4, executable_metadata=metadata,
                      executable_sha256=sha(raw))
    require(instance() == (uid, start_ticks), 'GPU process instance changed during inspection')
    return record


def verify_permission(permission):
    require(permission.get('allowed') is True and permission.get('gpu_count') == 1,
            'Fresh single-GPU permission evidence required')
    uuid = permission['gpu_uuid']
    require(re.fullmatch(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', uuid), 'Full UUID required')
    require(os.environ.get('GPU_UUID') == os.environ.get('CUDA_VISIBLE_DEVICES') == uuid,
            'CUDA environment does not match allowed GPU')
    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(permission['checked_at'])).total_seconds()
    require(0 <= age <= 300, 'Resource evidence older than five minutes')
    require(permission.get('enabled') is True and permission.get('conflict_free') is True and
            type(permission.get('aggregate_after_launch')) is int and
            1 <= permission['aggregate_after_launch'] <= min(4, permission['platform_quota']), 'Resource gate not met')
    require(permission.get('evidence'), 'Resource decision needs its evidence references')
    sample = subprocess.run(['nvidia-smi', '-q', '-x'], capture_output=True, text=True,
                            timeout=15, check=True).stdout
    matches = [g for g in ET.fromstring(sample).findall('gpu') if g.findtext('uuid') == uuid]
    require(len(matches) == 1 and matches[0].findtext('compute_mode') == 'Default',
            'GPU missing or compute mode is not Default')
    tables = matches[0].findall('processes')
    require(len(tables) == 1 and not (tables[0].text or '').strip() and
            all(node.tag == 'process_info' for node in tables[0]), 'GPU process sampling unavailable')
    processes = []
    exceptions = permission.get('verified_system_display_processes', [])
    for process in tables[0].findall('process_info'):
        pid = int(process.findtext('pid'))
        record = collect_process_identity(pid, process.findtext('type'), process.findtext('process_name'))
        require(record in exceptions, 'GPU has an unapproved research or graphics process')
        processes.append(record)
    require(all(e in processes for e in exceptions), 'Display exception no longer matches its exact process instance')
    return {'gpu_xml_sha256': sha(sample.encode()), 'processes': processes, 'compute_mode': 'Default', 'at': now()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('cpu-preflight', 'check', 'run'))
    for flag in ('old-protocol', 'asset-manifest', 'cache-root'):
        parser.add_argument('--' + flag, required=True, type=Path)
    for flag in ('models-root', 'output', 'plan', 'preflight', 'permission'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.command == 'cpu-preflight':
        require(args.output is not None and args.models_root is not None, 'CPU preflight needs output/models')
        require(os.environ.get('CUDA_VISIBLE_DEVICES') == '', 'CPU preflight must hide CUDA')
        _, _, report = cpu_prepare(args.old_protocol, args.asset_manifest, args.models_root, args.cache_root)
        write_json(args.output, report)
        print(json.dumps({'status': report['status'], 'preflight_sha256': sha(canonical(report))}))
        return
    require(args.plan is not None and args.preflight is not None, 'Frozen plan and CPU preflight required')
    plan = json.loads(args.plan.read_text())
    preflight = json.loads(args.preflight.read_text())
    binding, _ = inputs(args.old_protocol, args.asset_manifest, args.cache_root)
    validate_plan(plan, binding, preflight)
    if args.command == 'check':
        print(json.dumps({'status': 'passed', 'models_loaded': False, 'CUDA_initialized': False, 'budget': LIMITS}))
        return
    require(args.models_root is not None and args.output is not None and args.permission is not None,
            'Run requires models, new output directory and current resource evidence')
    require(os.environ.get('CUBLAS_WORKSPACE_CONFIG') == ':4096:8', 'Deterministic CUDA config required')
    claim_execution(plan, args.output)
    ledger = Ledger(args.output, {'plan': plan, 'plan_sha256': sha(args.plan.read_bytes()),
                                 'preflight_sha256': sha(args.preflight.read_bytes())})
    backend = None
    try:
        write_json(ledger.root / 'cpu_reload_started.json', {'at': now()})
        assets, audit, current = cpu_prepare(args.old_protocol, args.asset_manifest, args.models_root, args.cache_root)
        require(current == preflight, 'Runtime CPU-derived identity differs from preflight')
        permission = json.loads(args.permission.read_text())
        live = verify_permission(permission)
        write_json(ledger.root / 'resource_permission.json', {'permission': permission, 'launch_sample': live})
        from tssa_sd_runtime import SDGradientRuntime
        from tssa_target_semantic_runtime import SemanticDiagnosticBackend
        units = make_units(audit, args.cache_root)
        conditions = {s['id']: s for s in assets.protocol['merging']['development_normal_states']}
        ledger.start_cuda_window()
        runtime = SDGradientRuntime(assets)
        write_json(ledger.root / 'runtime_environment.json', runtime.environment_record())
        backend = SemanticDiagnosticBackend(runtime, budget_callback=ledger.reserve)
        report = execute_stages(ledger, backend, units, conditions)
        report.update(at=now(), reserved=ledger.total, resources=backend.resource_record(),
                      cuda_wall_seconds=time.monotonic() - ledger.started)
        write_json(ledger.root / 'terminal.json', report)
        print(json.dumps(report), flush=True)
    except BaseException:
        write_json(ledger.root / 'failure.json', {'at': now(), 'traceback': traceback.format_exc(),
                   'reserved': ledger.total, 'pending_cell': ledger.current, 'automatic_retry': False,
                   'resources': backend.resource_record() if backend is not None else None})
        raise
    finally:
        ledger.close()


if __name__ == '__main__':
    main()
