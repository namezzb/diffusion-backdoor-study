#!/usr/bin/env python3
"""Read-only school GPU observation; never reserves cards or starts workloads."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
from stage_school_assets import gateway_address


REMOTE_PROBE = r'''
import datetime,json,os,pathlib,pwd,shutil,socket,subprocess,xml.etree.ElementTree as ET
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
uid=os.getuid()
assert pwd.getpwuid(uid).pw_name=='zhangzibo', 'Unexpected SSH account'
started=now()
p=subprocess.run(['nvidia-smi','-q','-x'],capture_output=True,text=True,timeout=20)
if p.returncode:
    raise RuntimeError('nvidia-smi query failed: '+p.stderr[-500:])
doc=ET.fromstring(p.stdout)
cards=[]
for index,g in enumerate(doc.findall('gpu')):
    items=[]
    processes=g.find('processes')
    process_state_known=processes is not None and (processes.text or '').strip() not in {'N/A','Not Supported'}
    for item in g.findall('./processes/process_info'):
        pid_text=item.findtext('pid','')
        try: pid=int(pid_text)
        except ValueError: process_state_known=False; continue
        own=None;project=None
        try:
            proc=pathlib.Path('/proc')/str(pid)
            own=proc.stat().st_uid==uid
            if own:
                command=(proc/'cmdline').read_bytes()
                project=b'/data2/zhangzibo/arxiv-tssa/' in command
        except (OSError,PermissionError): pass
        items.append({'pid':pid,'type':item.findtext('type'),'memory':item.findtext('used_memory'),'owner_is_self':own,'is_this_project':project})
    cards.append({'index':index,'uuid':g.findtext('uuid'),'name':g.findtext('product_name'),'pci_bus_id':g.findtext('./pci/pci_bus_id'),'compute_mode':g.findtext('compute_mode'),'memory_used':g.findtext('./fb_memory_usage/used'),'memory_total':g.findtext('./fb_memory_usage/total'),'gpu_utilization':g.findtext('./utilization/gpu_util'),'process_state_known':process_state_known,'processes':items})
root=pathlib.Path('/data2/zhangzibo/arxiv-tssa')
disk=None
if root.exists() and not root.is_symlink() and root.stat().st_uid==uid:
    d=shutil.disk_usage(root);disk={'path':str(root),'free_bytes':d.free,'total_bytes':d.total}
known_own=sum(any(p['owner_is_self'] is True for p in g['processes']) for g in cards)
ownership_complete=all(g['process_state_known'] and all(p['owner_is_self'] is not None for p in g['processes']) for g in cards)
print(json.dumps({'sample_started_at':started,'sample_finished_at':now(),'hostname':socket.gethostname(),'account':'zhangzibo','driver_timestamp':doc.findtext('timestamp'),'driver_version':doc.findtext('driver_version'),'cards':cards,'known_own_gpu_count_on_this_server':known_own,'process_ownership_complete':ownership_complete,'own_gpu_count_on_this_server':known_own if ownership_complete else None,'data_disk':disk}))
'''


def bounded_ssh(argv, timeout):
    # Own process group only; clean up its ProxyJump child on a timed-out probe.
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
        raise TimeoutError("Bounded SSH observation timed out")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', choices=['100','101','102','103','104','127'], default='104')
    parser.add_argument('--timeout', type=int, default=90)
    args = parser.parse_args()
    if not 25 <= args.timeout <= 120:
        parser.error('timeout must be between 25 and 120 seconds')
    stamp = datetime.now(timezone.utc)
    output = ROOT/'results/tssa-mvp-2026-10-26/server-probes'
    output.mkdir(parents=True, exist_ok=True)
    report_path = output/f"school{args.server}-{stamp.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    report = {'started_at':stamp.isoformat(),'server':args.server,'read_only':True,
              'probe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'launch_authorized':False,'reservation_created':False,
              'platform_allocation':None,'current_disabled_cards':None,
              'cross_server_own_gpu_count':None,
              'boundary':'A process-free snapshot is not allocation or permission. This probe cannot reserve or launch.'}
    try:
        gateway = gateway_address()
        with tempfile.TemporaryDirectory(prefix='school-gpu-probe-',dir='/private/tmp') as temp:
            config=Path(temp)/'config'
            config.write_text(f'Host school-jump\n    HostName {gateway}\n'
                              f'Host *\n    BatchMode yes\n    StrictHostKeyChecking yes\n'
                              f'    ControlMaster no\n    ControlPath none\n'
                              f'    Include "{ROOT / "server/school_ssh_config"}"\n')
            config.chmod(0o600)
            rc,stdout,stderr=bounded_ssh(['ssh','-F',str(config),f'school{args.server}',
                                        shlex.join(['python3','-c',REMOTE_PROBE])],args.timeout)
            if rc:
                report.update(status='connection_or_query_failed',returncode=rc,error=stderr[-1500:])
            else:
                observation=json.loads(stdout)
                report.update(status='observed',observation=observation)
                report['observed_process_free_indices']=[g['index'] for g in observation['cards']
                    if g['process_state_known'] and not g['processes']]
                report['historically_disabled_indices_not_current_permission']=[3,4,6] if args.server=='104' else []
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        report.update(status='probe_failed',error=str(exc))
    report['finished_at']=datetime.now(timezone.utc).isoformat()
    with report_path.open('x') as stream:
        json.dump(report,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps({'report':str(report_path),**report},ensure_ascii=False,indent=2))
    return 0 if report['status']=='observed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
