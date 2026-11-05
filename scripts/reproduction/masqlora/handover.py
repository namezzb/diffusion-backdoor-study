#!/usr/bin/env python3
"""Replace verified own placeholder processes with the requested real startup test."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from runtime import md_read, md_write

PREP = Path(__file__).resolve().parent
RUN = Path('/data2/zhangzibo/arxiv-tssa/results/masqlora-20261105-sd15-v1')
ASSIGNMENTS = [('GPU-0fc254b8-f4f9-2382-8d33-71c99526fb1b', 'masq'),
               ('GPU-7c1e49bf-dac2-cece-dd4a-e6fa81d3b731', 'benign')]


def processes(uuid):
    text = subprocess.check_output(['nvidia-smi', '-i', uuid, '--query-compute-apps=pid', '--format=csv,noheader,nounits'], text=True)
    return [int(s) for s in text.splitlines() if s.strip()]


def main():
    observation = md_read(RUN / 'permission.md')
    if observation['expires_at'] < time.time() or observation['run_id'] != 'masqlora-20261105-sd15-v1':
        raise RuntimeError('Current platform observation required')
    selected = []
    for uuid, arm in ASSIGNMENTS:
        if observation['cards'][uuid]['allowed'] is not True:
            raise RuntimeError('Card unavailable')
        mode = subprocess.check_output(['nvidia-smi', '-i', uuid, '--query-gpu=compute_mode', '--format=csv,noheader'], text=True)
        if mode.strip() != 'Default':
            raise RuntimeError('Card disabled')
        for pid in processes(uuid):
            proc = Path('/proc') / str(pid)
            cmd = (proc / 'cmdline').read_bytes().split(b'\0')
            if proc.stat().st_uid != os.getuid() or b'gpu_squat.py' not in cmd or uuid.encode() not in cmd:
                raise RuntimeError('Existing computation is not an own placeholder: ' + str(pid))
            # Capture start time to prevent signalling a reused PID.
            selected.append((pid, (proc / 'stat').read_text().split(') ', 1)[1].split()[19], uuid))
    for pid, ticks, uuid in selected:
        proc = Path('/proc') / str(pid)
        if proc.stat().st_uid != os.getuid() or (proc / 'stat').read_text().split(') ', 1)[1].split()[19] != ticks:
            raise RuntimeError('Process identity changed')
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 15
    while any(processes(uuid) for uuid, _ in ASSIGNMENTS):
        if time.monotonic() >= deadline:
            raise RuntimeError('Card has not become process-free; no new job started')
        time.sleep(.5)
    launched = []
    env = dict(os.environ, PYTHONPATH=str(PREP / 'vendor'), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    for uuid, arm in ASSIGNMENTS:
        if processes(uuid):
            raise RuntimeError('Card occupied before launch')
        root = RUN / arm
        root.mkdir(parents=True, exist_ok=True)
        with (root / 'execution.log').open('ab') as f:
            child = subprocess.Popen([sys.executable, str(PREP / 'runtime.py'), '--config', str(PREP / 'config.json'),
                       '--run-root', str(RUN), '--uuid', uuid, '--arm', arm, 'train', '--stop-after', '3'],
                       stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, start_new_session=True)
        launched.append({'uuid': uuid, 'arm': arm, 'pid': child.pid, 'purpose': 'three real optimizer steps then checkpoint exit'})
    md_write(RUN / 'handover.md', 'Own placeholder to finite reproduction handover',
             {'stopped': selected, 'launched': launched, 'time': time.time()})
    print(json.dumps(launched), flush=True)


if __name__ == '__main__':
    main()
