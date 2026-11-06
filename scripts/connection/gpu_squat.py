#!/usr/bin/env python3
"""Standalone GPU hold occupier; authorized by the user on 2026-11-03.

Runs an infinite loop on one GPU selected by UUID: allocates a fraction of
device memory and sustains measured utilization toward a target with a
duty-cycled matmul, so the card shows real memory usage and compute load.
Stops on SIGTERM/SIGINT or a STOP file next to the state directory. This is
not a scientific run and holds no lease; platform rules are checked by the
launcher before this process starts.
"""
import argparse
import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

UUID = re.compile(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
CUSHION_BYTES = 256 * 1024 * 1024
BLOCK_BYTES = 64 * 1024 * 1024


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Standalone GPU hold occupier (until stopped)')
    parser.add_argument('--uuid', required=True, help='full GPU UUID to bind and hold')
    parser.add_argument('--memory-fraction', type=float, default=0.65,
                        help='fraction of total device memory to allocate (0..0.9)')
    parser.add_argument('--target-utilization-percent', type=float, default=65,
                        help='feedback target for measured device utilization (0..100)')
    parser.add_argument('--sample-seconds', type=float, default=10.0,
                        help='seconds between nvidia-smi samples and log heartbeats')
    parser.add_argument('--state-dir', required=True,
                        help='directory for log, pid and STOP marker (absolute path)')
    args = parser.parse_args(argv)
    if (not UUID.fullmatch(args.uuid)
            or not all(math.isfinite(v) for v in (args.memory_fraction, args.target_utilization_percent, args.sample_seconds))
            or not 0.0 <= args.memory_fraction <= 0.9
            or not 0.0 <= args.target_utilization_percent <= 100.0
            or not 1.0 <= args.sample_seconds <= 60.0):
        parser.error('invalid uuid, fraction, target or sample period')
    return args


def measure(uuid, pid):
    result = {'device_gpu_utilization_percent': None, 'device_memory_used_mib': None,
              'device_memory_total_mib': None, 'worker_pid_memory_mib': None}
    try:
        gpu = subprocess.run(['nvidia-smi', '--query-gpu=uuid,utilization.gpu,memory.used,memory.total',
                              '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3, check=True)
        rows = [line.split(',') for line in gpu.stdout.splitlines() if line.split(',')[0].strip() == uuid]
        if len(rows) == 1 and len(rows[0]) == 4:
            util, used, total = (float(value.strip()) for value in rows[0][1:])
            if all(math.isfinite(x) for x in (util, used, total)) and 0 <= util <= 100 and 0 <= used <= total and total > 0:
                result['device_gpu_utilization_percent'] = util
                result['device_memory_used_mib'] = used
                result['device_memory_total_mib'] = total
        apps = subprocess.run(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,used_gpu_memory',
                               '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3, check=True)
        rows = [line.split(',') for line in apps.stdout.splitlines()
                if len(line.split(',')) == 3 and line.split(',')[0].strip() == uuid and line.split(',')[1].strip() == str(pid)]
        if len(rows) == 1:
            value = float(rows[0][2].strip())
            if math.isfinite(value) and value >= 0:
                result['worker_pid_memory_mib'] = value
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return result


class Stop(Exception):
    pass


def main(argv=None):
    args = parse_args(argv)
    state = Path(args.state_dir)
    state.mkdir(parents=True, exist_ok=True)
    log_path = state / (args.uuid + '.md')
    pid_path = state / (args.uuid + '.pid.md')
    stop_path = state / 'STOP'

    stopped = {'flag': False}
    def request_stop(signum, frame):
        stopped['flag'] = True
    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGTERM, signal.SIGINT)}

    log = log_path.open('a', buffering=1, encoding='utf-8')

    def record(event, **fields):
        line = json.dumps({'time': time.time(), 'iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
                           'event': event, 'host': socket.gethostname(), 'pid': os.getpid(), **fields},
                          ensure_ascii=False, allow_nan=False)
        print(line, flush=True)
        log.write('- ' + line + '\n')
        log.flush()

    def guard():
        if stopped['flag']:
            raise Stop('termination signal')
        if stop_path.exists():
            raise Stop('STOP file present')

    pid_path.write_text('# gpu_squat worker\n\n```json\n' + json.dumps(
        {'pid': os.getpid(), 'host': socket.gethostname(), 'gpu_uuid': args.uuid,
         'memory_fraction': args.memory_fraction, 'target_utilization_percent': args.target_utilization_percent,
         'state': 'running', 'started_at': time.time()}) + '\n```\n', encoding='utf-8')

    record('starting', uuid=args.uuid, memory_fraction=args.memory_fraction,
           target_utilization_percent=args.target_utilization_percent,
           sample_seconds=args.sample_seconds, state_dir=str(state))

    os.environ['CUDA_VISIBLE_DEVICES'] = args.uuid
    import torch
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        record('error', reason='requested CUDA device unavailable', uuid=args.uuid)
        return 1
    torch.cuda.set_device(0)
    guard()

    blocks = []
    left = right = None
    try:
        while True:
            guard()
            try:
                free, total = torch.cuda.mem_get_info(0)
                target = int(total * args.memory_fraction)
                if target > max(0, free - CUSHION_BYTES):
                    raise MemoryError('requested allocation exceeds currently free memory')
                remaining = target
                while remaining > 0:
                    guard()
                    size = min(remaining, BLOCK_BYTES)
                    block = torch.empty(size, dtype=torch.uint8, device='cuda:0')
                    block.zero_()
                    blocks.append(block)
                    remaining -= size
                torch.cuda.synchronize()
                record('allocated', uuid=args.uuid, target_bytes=target,
                       total_bytes=total, blocks=len(blocks))
                break
            except MemoryError as exc:
                record('allocation-retry', reason=str(exc), uuid=args.uuid, retry_seconds=60)
                time.sleep(60)

        duty = 0.5
        last_sample = float('-inf')
        while True:
            guard()
            now = time.monotonic()
            if now - last_sample >= args.sample_seconds:
                observed = measure(args.uuid, os.getpid())
                utilization = observed.get('device_gpu_utilization_percent')
                if type(utilization) in (int, float) and math.isfinite(utilization) and 0 <= utilization <= 100:
                    duty = max(0.0, min(1.0, duty + 0.15 * (args.target_utilization_percent - utilization) / 100))
                record('sample', uuid=args.uuid, requested_compute_duty=round(duty, 3), **observed)
                last_sample = time.monotonic()
            if left is None:
                left = torch.ones((1024, 1024), device='cuda:0', dtype=torch.float32)
                right = torch.ones((1024, 1024), device='cuda:0', dtype=torch.float32)
            started = time.monotonic()
            torch.mm(left, right)
            torch.cuda.synchronize()
            elapsed = max(0.0, time.monotonic() - started)
            sleep_for = min(1.0, elapsed * (1.0 / duty - 1.0)) if duty > 0 else 1.0
            if sleep_for > 0:
                time.sleep(sleep_for)
    except Stop as exc:
        record('stopped', reason=str(exc), uuid=args.uuid)
        return 0
    except Exception as exc:
        record('error', reason=type(exc).__name__ + ': ' + str(exc)[:200], uuid=args.uuid)
        return 1
    finally:
        left = right = None
        blocks.clear()
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        log.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
