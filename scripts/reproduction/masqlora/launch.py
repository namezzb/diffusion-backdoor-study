#!/usr/bin/env python3
"""Launch/resume a fixed worker after current observations; no exclusive claims."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
from runtime import md_read, md_write


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--uuid', required=True)
    p.add_argument('--run-root', required=True, type=Path)
    p.add_argument('--arms', nargs='+', required=True, choices=['masq', 'benign', 'poisoned'])
    p.add_argument('--preview-only', action='store_true')
    args = p.parse_args()
    prep = Path(__file__).resolve().parent
    permission = md_read(args.run_root / 'permission.md')
    if permission['expires_at'] <= time.time() or not permission['cards'].get(args.uuid, {}).get('allowed'):
        raise RuntimeError('Fresh resource observation required')
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            command = (proc / 'cmdline').read_bytes().split(b'\0')
            if args.uuid.encode() in command and any(str(prep / name).encode() in command for name in ['worker.py', 'runtime.py']):
                raise RuntimeError('An existing worker/runtime is still active: ' + proc.name)
        except (FileNotFoundError, PermissionError):
            continue
    gpu = subprocess.check_output(['nvidia-smi', '-i', args.uuid, '--query-gpu=compute_mode', '--format=csv,noheader'], text=True).strip()
    apps = subprocess.check_output(['nvidia-smi', '-i', args.uuid, '--query-compute-apps=pid', '--format=csv,noheader'], text=True).strip()
    if gpu != 'Default' or apps:
        raise RuntimeError('GPU is unavailable/occupied; no new computation started')
    if not args.preview_only:
        first = args.run_root / args.arms[0]
        if not md_read(first / 'verified.md').get('passed'):
            raise RuntimeError('Export verification required before full evaluation')
        if not all(c['n'] >= 4 for c in md_read(first / 'summary.md')['conditions'].values()):
            raise RuntimeError('Real generation/scoring preview required before expansion')
    cmd = [sys.executable, str(prep / 'worker.py'), '--run-root', str(args.run_root), '--uuid', args.uuid, '--arms', *args.arms]
    if args.preview_only:
        cmd.append('--preview-only')
    name = '-'.join(args.arms)
    with (args.run_root / (name + '-worker.log')).open('ab') as log:
        child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    info = {'pid': child.pid, 'uuid': args.uuid, 'arms': args.arms, 'preview_only': args.preview_only, 'time': time.time()}
    md_write(args.run_root / (name + '-worker.md'), 'Worker process observation (not a lock)', info)
    print(info, flush=True)


if __name__ == '__main__':
    main()
