"""Recover only the reviewed accidental SIGTERM interruption of the same real run."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path('/Users/zzb/arxiv')
OUT = ROOT/'results/tssa-mvp-2026-10-26'
sys.path.insert(0, str(ROOT/'server'))
from stage_school_assets import SchoolSession

ready = json.loads((OUT/'single_GPU_readiness_2026-10-28.json').read_text())
ready['argv_template'] = ready['argv_template'] + ['--recover-inflight']
expected = json.loads((OUT/'deployment_bundle_2026-10-28-configfix.json').read_text())['contents']['files']
uuid = 'GPU-2b05f9c0-6ecb-23cd-03f4-e7b989d07cee'
stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
report_path = OUT/f'single_GPU_recovery_{stamp}.json'
report = {'started_at':dt.datetime.now(dt.timezone.utc).isoformat(), 'GPU_UUID':uuid,
          'portal_observation':'2026-10-28 10:17 Asia/Shanghai:104 GPU3 appears idle and not disabled; own0/4; queue56 waiting1. Notification at10:11 confirms the other user joined our already-running GPU. Fresh browser verification required immediately before execution.',
          'authorization':'After being informed of automatic approval rejection and asked to verify direct-use permission, user explicitly replied: 我确认了,你可以直接用. Re-submit transparently for approval on this new confirmation; direct-use path, not a claimed queue allocation.',
          'readiness_sha256':hashlib.sha256((OUT/'single_GPU_readiness_2026-10-28.json').read_bytes()).hexdigest(),
          'automatic_retry':False,
          'recovery_review':{'cause':'Agent incorrectly sent SIGTERM to own PID640404 after portal-reported later entrant; user corrected this decision and asks to retain own task.', 'prior_observation':'single_run_observation_20261028T021302990677Z.json', 'interrupted_operation':'diagnostic/gpu_gradient_and_memory', 'known_branch_NFE':118, 'backward_interrupted_cost_incomplete':True, 'prior_diagnostic_upper_bound':{'branch_NFE':138,'autograd_calls':1}, 'main_images':0,'main_optimizer_updates':0,'preserve_prior_attempt':True,'scientific_budget_unchanged':True}}

remote = r'''
import datetime,fcntl,hashlib,json,os,pathlib,pwd,subprocess,sys,xml.etree.ElementTree as ET
ready,expected,uuid,stamp=json.loads(sys.argv[1]);now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
assert pwd.getpwuid(os.getuid()).pw_name=='zhangzibo'
run=pathlib.Path(ready['run_dir']);code=pathlib.Path(ready['remote_source_root'])
assert run.stat().st_uid==os.getuid() and code.stat().st_uid==os.getuid()
for rel,item in expected.items():
 p=code/rel;assert p.stat().st_size==item['size'] and hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256'],rel
assert hashlib.sha256((run/'run_identity.json').read_bytes()).hexdigest()==ready['run_identity_sha256']
status=json.loads((run/'failure_or_completion_status.json').read_text())
assert status['status']=='interrupted' and status['completed_stages']==['cpu-preflight'] and status['error_type']=='KeyboardInterrupt' and status['error'].startswith('Signal 15;'),status
assert hashlib.sha256((run/'failure_or_completion_status.json').read_bytes()).hexdigest()=='1bd6590194cfdcb986313f8b7fcec13c95976b56e716ddff9a7266dc6f6d0451'
assert hashlib.sha256((run/'resource_ledger.json').read_bytes()).hexdigest()=='6dd1b9ab83d94908919f1e914a8f4a29a41d3d254374a94e40c8a7e7d232f0aa'
ledger=json.loads((run/'resource_ledger.json').read_text()); interrupted=[o for o in ledger['operations'] if o['status']=='interrupted']
assert len(interrupted)==1 and interrupted[0]['operation']=='diagnostic/gpu_gradient_and_memory'
assert len(interrupted[0]['attempts'])==1 and interrupted[0]['attempts'][0]['error_type']=='KeyboardInterrupt'
lock=(run/'.run.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
active=[]
for proc in pathlib.Path('/proc').iterdir():
 if not proc.name.isdigit() or proc.name==str(os.getpid()): continue
 try:
  if proc.stat().st_uid!=os.getuid(): continue
  argv=(proc/'cmdline').read_bytes().split(b'\0')
  if any(a.endswith((b'/tssa_mvp_run.py',b'/tssa_mvp_dual_run.py')) for a in argv): active.append(int(proc.name))
 except (OSError,PermissionError): pass
assert not active,('Existing research process',active)
doc=ET.fromstring(subprocess.run(['nvidia-smi','-q','-x'],check=True,capture_output=True,text=True,timeout=20).stdout)
cards=doc.findall('gpu');g=next(x for x in cards if x.findtext('uuid')==uuid)
assert cards.index(g)==3 and g.findtext('./pci/pci_bus_id')=='00000000:A1:00.0'
assert g.findtext('compute_mode')=='Default'
processes=[]
for item in g.findall('./processes/process_info'):
 pid=int(item.findtext('pid'));p=pathlib.Path('/proc')/str(pid)
 account=pwd.getpwuid(p.stat().st_uid)
 record={'pid':pid,'type':item.findtext('type'),'uid':account.pw_uid,'account':account.pw_name,'account_home':account.pw_dir,'account_shell':account.pw_shell,'comm':(p/'comm').read_text().strip(),'memory':item.findtext('used_memory')}
 processes.append(record)
 # Verify the system display identity; never treat a personal graphics task as infrastructure.
 system_display=(record['uid']==0 and record['comm']=='Xorg') or (record['account'] in ('gdm','Debian-gdm') and record['comm']=='gnome-shell' and record['account_home'].startswith('/var/lib/gdm') and record['account_shell'] in ('/bin/false','/usr/sbin/nologin','/sbin/nologin'))
 assert record['type']=='G' and system_display,('GPU has another or unknown task',record)
for card in cards:
 for item in card.findall('./processes/process_info'):
  assert (pathlib.Path('/proc')/item.findtext('pid')).stat().st_uid!=os.getuid(),'Own GPU task already active'
env=dict(os.environ);env.update(ready['environment']);env['CUDA_VISIBLE_DEVICES']=uuid;env['GPU_UUID']=uuid
logpath=run/f'execution-{stamp}.log'
receipt={'observed_at':now(),'GPU_UUID':uuid,'index':3,'pci_bus_id':g.findtext('./pci/pci_bus_id'),'processes_before':processes,'driver_timestamp':doc.findtext('timestamp'),'source_files_verified':len(expected),'run_identity_verified':True,'command':ready['argv_template'],'log':str(logpath),'mode':'same_run_recovery_after_reviewed_agent_SIGTERM','GPU_initialized_confirmed':False}
lock.close()
with logpath.open('xb') as log:
 child=subprocess.Popen(ready['argv_template'],cwd=code,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
receipt.update(status='real_runner_started',pid=child.pid,started_at=now())
with (run/f'launch-{stamp}.json').open('x') as f:json.dump(receipt,f,indent=2)
print(json.dumps(receipt),flush=True)
'''
try:
    with SchoolSession() as session:
        result = subprocess.run(['ssh','-F',str(session.config),'-o','ControlMaster=no','-o','ControlPath=none','school104',
            shlex.join(['python3','-c',remote,json.dumps([ready,expected,uuid,stamp])])],capture_output=True,text=True,timeout=100)
        report.update(returncode=result.returncode,stderr=result.stderr[-3000:])
        if result.stdout.strip(): report['remote']=json.loads(result.stdout)
        report['status']='real_runner_started' if result.returncode==0 else 'not_started_or_unknown_check_evidence'
except Exception as exc:
    report.update(status='connection_or_guard_failure_do_not_retry_blindly',error=f'{type(exc).__name__}: {exc}')
finally:
    report['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    with report_path.open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2)
print(json.dumps({'report':str(report_path),**report},ensure_ascii=False,indent=2))
