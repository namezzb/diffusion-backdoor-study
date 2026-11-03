#!/usr/bin/env python3
"""Transparent, lease-controlled GPU hold worker; never a scientific run.

This worker does not create reservations or validate platform rules. An
independent authorized controller must first verify completed experiment,
platform permission and card ownership, then keep the private lease fresh.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

UUID = re.compile(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
WORKER_ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}\Z')
SCIENCE_SHA = re.compile(r'[0-9a-f]{64}\Z')
MAX_LEASE_AGE = 90.0
MAX_LEASE_SPAN = 90.0


class StopWork(Exception):
    pass


def safe_read_json(path):
    path = Path(path)
    if not path.is_absolute() or any(part.is_symlink() for part in path.parents):
        raise StopWork('unsafe lease path')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_size > 32768:
                raise StopWork('unsafe lease ownership, mode, type or size')
            text = stream.read()
            if path.suffix == '.md':
                blocks = re.findall(r'^```json[ \t]*\n(.*?)\n```[ \t]*$', text, re.M | re.S)
                if len(blocks) != 1: raise ValueError('invalid Markdown state')
                text = blocks[0]
            value = json.loads(text)
    except (OSError, ValueError, UnicodeError) as exc:
        raise StopWork('lease missing or unreadable') from exc
    if not isinstance(value, dict):
        raise StopWork('lease must be an object')
    return value


def check_lease(lease, *, uuid, worker_id, lease_id, controller_id, science_sha256, now, hostname, uid):
    if not isinstance(lease, dict):
        raise StopWork('lease missing')
    if (lease.get('schema') != 'gpu-hold-lease-v1' or lease.get('worker_id') != worker_id
            or lease.get('gpu_uuid') != uuid or lease.get('host') != hostname
            or type(lease.get('owner_uid')) is not int or lease['owner_uid'] != uid
            or lease.get('lease_id') != lease_id or not WORKER_ID.fullmatch(lease_id)
            or lease.get('controller_id') != controller_id or not WORKER_ID.fullmatch(controller_id)):
        raise StopWork('lease identity mismatch')
    sha = lease.get('semantic_science_sha256')
    if (lease.get('semantic_run_id') != 'tcl-20261103-semantic-v1'
            or not isinstance(sha, str) or not SCIENCE_SHA.fullmatch(sha) or sha != science_sha256
            or lease.get('semantic_terminal') is not True or lease.get('semantic_all_stages_completed') is not True
            or lease.get('scientific_writer_exited') is not True):
        raise StopWork('completed scientific run not attested')
    if (lease.get('authorized') is not True or lease.get('platform_permission_verified') is not True
            or lease.get('disabled') is not False or lease.get('stop_required') is not False):
        raise StopWork('platform authorization missing or stop required')
    cards = lease.get('active_hold_uuids')
    if (not isinstance(cards, list) or not 1 <= len(cards) <= 2
            or any(not isinstance(card, str) or not UUID.fullmatch(card) for card in cards)
            or len(set(cards)) != len(cards) or uuid not in cards):
        raise StopWork('hold card set invalid')
    observed, expires = lease.get('observed_at'), lease.get('expires_at')
    if (type(observed) not in (float, int) or type(expires) not in (float, int)
            or not math.isfinite(observed) or not math.isfinite(expires)
            or not 0 <= now - observed < MAX_LEASE_AGE or not now < expires
            or not 0 < expires - observed <= MAX_LEASE_SPAN):
        raise StopWork('lease expired, stale or invalid')
    return lease['lease_id']


def ensure_state_dir(path):
    path = Path(path)
    if not path.is_absolute() or any(part.is_symlink() for part in (path, *path.parents)):
        raise StopWork('unsafe state directory')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise StopWork('unsafe state directory permissions')
    return path


def emit(event, **fields):
    print(json.dumps({'time': time.time(), 'event': event, **fields}, ensure_ascii=False, allow_nan=False), flush=True)


def process_identity():
    boot_id, start_ticks = None, None
    try:
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        raw = Path('/proc/self/stat').read_text()
        start_ticks = int(raw[raw.rfind(')') + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        pass
    return {'pid': os.getpid(), 'uid': os.geteuid(), 'host': socket.gethostname(),
            'boot_id': boot_id, 'start_ticks': start_ticks}


def measure(uuid, pid):
    """Return observed device and worker values; unavailable values stay null."""
    result = {'device_gpu_utilization_percent': None, 'device_memory_used_mib': None,
              'device_memory_total_mib': None, 'worker_pid_memory_mib': None}
    try:
        gpu = subprocess.run(['nvidia-smi', '--query-gpu=uuid,utilization.gpu,memory.used,memory.total',
                              '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3, check=True)
        matches = [line.split(',') for line in gpu.stdout.splitlines() if line.split(',')[0].strip() == uuid]
        if len(matches) == 1 and len(matches[0]) == 4:
            util, used, total = (float(value.strip()) for value in matches[0][1:])
            if all(math.isfinite(x) for x in (util, used, total)) and 0 <= util <= 100 and 0 <= used <= total and total > 0:
                result['device_gpu_utilization_percent'] = util
                result['device_memory_used_mib'] = used
                result['device_memory_total_mib'] = total
        processes = subprocess.run(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,used_gpu_memory',
                                    '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3, check=True)
        matches = [line.split(',') for line in processes.stdout.splitlines() if len(line.split(',')) == 3
                   and line.split(',')[0].strip() == uuid and line.split(',')[1].strip() == str(pid)]
        if len(matches) == 1:
            value = float(matches[0][2].strip())
            if math.isfinite(value) and value >= 0:
                result['worker_pid_memory_mib'] = value
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return result


class TorchDevice:
    def __init__(self, uuid, guard):
        # The lease has already been verified, before importing torch or CUDA.
        os.environ['CUDA_VISIBLE_DEVICES'] = uuid
        import torch
        self.torch = torch
        guard()
        if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
            raise StopWork('requested CUDA device unavailable')
        guard()
        torch.cuda.set_device(0)
        self.blocks = []
        self.left = self.right = None

    def allocate(self, fraction, guard):
        torch = self.torch
        free, total = torch.cuda.mem_get_info(0)
        target = int(total * fraction)
        # Leave a fixed cushion for allocator/context and avoid stealing memory.
        if target > max(0, free - 256 * 1024 * 1024):
            raise StopWork('requested own allocation exceeds currently free memory')
        while target > 0:
            guard()
            size = min(target, 64 * 1024 * 1024)
            block = torch.empty(size, dtype=torch.uint8, device='cuda:0')
            block.zero_()
            self.blocks.append(block)
            target -= size
        torch.cuda.synchronize()

    def compute_once(self):
        torch = self.torch
        if self.left is None:
            self.left = torch.ones((1024, 1024), device='cuda:0', dtype=torch.float32)
            self.right = torch.ones((1024, 1024), device='cuda:0', dtype=torch.float32)
        torch.mm(self.left, self.right)
        torch.cuda.synchronize()

    def close(self):
        self.left = self.right = None
        self.blocks.clear()
        self.torch.cuda.empty_cache()


def run(args, *, device_factory=TorchDevice, clock=time, sample=measure):
    state = ensure_state_dir(args.state_dir)
    log_fd = None
    try:
        log_fd = os.open(state / (args.uuid + '.md'), os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        info = os.fstat(log_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise StopWork('unsafe worker log')
    except Exception:
        if log_fd is not None:
            os.close(log_fd)
        raise
    log = os.fdopen(log_fd, 'a', buffering=1, encoding='utf-8')
    identity = process_identity()
    def record(event, **fields):
        line = json.dumps({'time': clock.time(), 'event': event, **fields}, ensure_ascii=False, allow_nan=False)
        print(line, flush=True)
        log.write('## ' + event + '\n\n' + ''.join('- **%s**: `%s`\n' % (k, json.dumps(v, ensure_ascii=False).replace('`', '\\u0060')) for k, v in {'time': clock.time(), 'event': event, **fields}.items()) + '\n<!-- json: ' + line + ' -->\n\n')
        log.flush()
    def save_pid(status):
        path = state / (args.uuid + '.pid.md')
        source = path if path.exists() or path.is_symlink() else state / (args.uuid + '.pid.json')
        if source.exists() or source.is_symlink():
            previous_pid = safe_read_json(source)
            if status == 'starting' and previous_pid.get('lease_id') == args.lease_id:
                raise StopWork('a used lease cannot restart a worker; obtain a new lease identity')
        fd, name = tempfile.mkstemp(prefix='.pid-', dir=state)
        try:
            with os.fdopen(fd, 'w') as stream:
                value = {**identity, 'gpu_uuid': args.uuid, 'worker_id': args.worker_id, 'lease_id': args.lease_id, 'status': status}
                stream.write('# Worker identity\n\n' + ''.join('- **%s**: `%s`\n' % (k, json.dumps(v)) for k, v in value.items()) + '\n```json\n' + json.dumps(value) + '\n```\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name): os.unlink(name)
    stopped = False
    previous = {}
    def request_stop(signum, frame):
        nonlocal stopped
        stopped = True
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, request_stop)
    deadline = None if args.until_stopped else clock.monotonic() + args.duration_seconds
    expected_lease_id = None
    def guard():
        nonlocal expected_lease_id
        if stopped:
            raise StopWork('termination signal')
        if deadline is not None and clock.monotonic() >= deadline:
            raise StopWork('explicit duration expired')
        lease_id = check_lease(safe_read_json(args.lease_file), uuid=args.uuid, worker_id=args.worker_id,
                               lease_id=args.lease_id, controller_id=args.controller_id, science_sha256=args.science_sha256,
                               now=clock.time(), hostname=socket.gethostname(), uid=os.geteuid())
        if expected_lease_id is not None and lease_id != expected_lease_id:
            raise StopWork('lease changed identity')
        expected_lease_id = lease_id
    device = None
    pid_written = False
    try:
        guard()
        save_pid('starting')
        pid_written = True
        record('starting', purpose='gpu-hold-worker', uuid=args.uuid, worker_id=args.worker_id,
               pid=os.getpid(), duration_seconds=args.duration_seconds, own_memory_fraction=args.memory_fraction,
               until_stopped=args.until_stopped, initial_compute_duty=args.compute_duty,
               target_utilization_percent=args.target_utilization_percent,
               note='compute duty is not measured GPU utilization; target is not guaranteed')
        device = device_factory(args.uuid, guard)
        guard()
        device.allocate(args.memory_fraction, guard)
        save_pid('running')
        last_sample = float('-inf')
        duty = args.compute_duty
        while True:
            guard()
            started = clock.monotonic()
            if started - last_sample >= args.sample_seconds:
                observed = sample(args.uuid, os.getpid())
                utilization = observed.get('device_gpu_utilization_percent')
                if type(utilization) in (int, float) and math.isfinite(utilization) and 0 <= utilization <= 100:
                    duty = max(0.0, min(1.0, duty + .15 * (args.target_utilization_percent - utilization) / 100))
                record('sample', uuid=args.uuid, pid=os.getpid(), target_utilization_percent=args.target_utilization_percent,
                       requested_compute_duty=duty, **observed)
                last_sample = clock.monotonic()
            if duty > 0:
                started = clock.monotonic()
                device.compute_once()
                elapsed = max(0, clock.monotonic() - started)
                sleep_for = min(1.0, elapsed * (1.0 / duty - 1.0))
            else:
                sleep_for = 1.0
            if sleep_for > 0:
                clock.sleep(sleep_for)
    except StopWork as exc:
        record('stopped', reason=str(exc), uuid=args.uuid, pid=os.getpid())
        return 0 if device is not None else 1
    except Exception as exc:
        record('error', reason=type(exc).__name__, uuid=args.uuid, pid=os.getpid())
        raise
    finally:
        try:
            if device is not None:
                device.close()
        finally:
            try:
                if pid_written:
                    save_pid('stopped')
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
                log.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uuid', required=True)
    parser.add_argument('--worker-id', required=True)
    parser.add_argument('--lease-id', required=True)
    parser.add_argument('--controller-id', required=True)
    parser.add_argument('--science-sha256', required=True)
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--lease-file', required=True)
    duration = parser.add_mutually_exclusive_group(required=True)
    duration.add_argument('--duration-seconds', type=float)
    duration.add_argument('--until-stopped', action='store_true', help='continue only while short leases remain valid')
    parser.add_argument('--memory-fraction', type=float, required=True, help='own allocation fraction of total device memory (0..0.9)')
    parser.add_argument('--compute-duty', type=float, required=True, help='requested work duty (0..1), not measured GPU utilization')
    parser.add_argument('--target-utilization-percent', type=float, required=True, help='feedback target for measured device utilization (0..100), not a guarantee')
    parser.add_argument('--sample-seconds', type=float, required=True)
    args = parser.parse_args(argv)
    if (not UUID.fullmatch(args.uuid) or not WORKER_ID.fullmatch(args.worker_id)
            or not WORKER_ID.fullmatch(args.lease_id) or not WORKER_ID.fullmatch(args.controller_id)
            or not SCIENCE_SHA.fullmatch(args.science_sha256)
            or not all(math.isfinite(v) for v in (args.memory_fraction, args.compute_duty, args.sample_seconds, args.target_utilization_percent))
            or (args.duration_seconds is not None and (not math.isfinite(args.duration_seconds) or args.duration_seconds <= 0))
            or not 0 <= args.memory_fraction <= .9 or not 0 <= args.target_utilization_percent <= 100
            or not 0 <= args.compute_duty <= 1 or not 1 <= args.sample_seconds <= 60):
        parser.error('invalid UUID, worker ID, duration, fractions or sampling period')
    try:
        return run(args)
    except (StopWork, OSError, RuntimeError) as exc:
        emit('error', reason=str(exc), uuid=args.uuid)
        return 1


class MarkdownOutput:
    """Quote every output line, including partial writes and tracebacks."""
    def __init__(self, stream):
        self.stream = stream
        self.line_start = True

    def write(self, text):
        for part in text.splitlines(keepends=True):
            if self.line_start:
                self.stream.write('> ')
            self.stream.write(part)
            self.line_start = part.endswith(('\n', '\r'))
        return len(text)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def enable_markdown_output():
    if os.environ.get('GPU_HOLD_MARKDOWN_OUTPUT') == '1':
        sys.stdout = MarkdownOutput(sys.stdout)
        sys.stderr = MarkdownOutput(sys.stderr)


if __name__ == '__main__':
    enable_markdown_output()
    sys.exit(main())
