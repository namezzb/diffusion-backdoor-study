#!/usr/bin/env python3
"""Run the explicitly assigned finite arms; failures preserve progress and exit."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
from runtime import md_read


def wait_for_resource(run_root, uuid):
    """Wait without a CUDA context; recheck device occupancy before resuming."""
    while not (Path(run_root) / 'STOP').exists():
        try:
            p = md_read(Path(run_root) / 'permission.md')
            if p['expires_at'] > time.time() and p['cards'].get(uuid, {}).get('allowed'):
                mode = subprocess.check_output(['nvidia-smi', '-i', uuid, '--query-gpu=compute_mode', '--format=csv,noheader'], text=True, timeout=10).strip()
                apps = subprocess.check_output(['nvidia-smi', '-i', uuid, '--query-compute-apps=pid', '--format=csv,noheader'], text=True, timeout=10).strip()
                if mode == 'Default' and not apps:
                    return True
        except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
            pass
        time.sleep(20)
    return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--uuid', required=True)
    p.add_argument('--run-root', required=True)
    p.add_argument('--arms', nargs='+', choices=['masq', 'poisoned', 'benign'], required=True)
    p.add_argument('--preview-only', action='store_true', help='Complete training and verify, then score four images per condition')
    args = p.parse_args()
    root = Path(__file__).resolve().parent
    os.environ['PYTHONPATH'] = str(root / 'vendor') + os.pathsep + os.environ.get('PYTHONPATH', '')
    for arm in args.arms:
        base = [sys.executable, str(root / 'runtime.py'), '--config', str(root / 'config.json'),
                '--run-root', args.run_root, '--uuid', args.uuid, '--arm', arm]
        for command in ['train', 'verify', 'evaluate']:
            extra = ['--limit', '4'] if command == 'evaluate' and args.preview_only else []
            while True:
                result = subprocess.run(base + [command] + extra)
                if result.returncode != 75:
                    break
                if not wait_for_resource(args.run_root, args.uuid):
                    return 75
            if result.returncode:
                return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
