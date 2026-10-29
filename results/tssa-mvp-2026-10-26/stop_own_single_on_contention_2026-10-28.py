"""Stop only the verified owned runner after a foreign compute task appeared."""
import datetime as dt,json,shlex,subprocess,sys
from pathlib import Path
ROOT=Path('/Users/zzb/arxiv');OUT=ROOT/'results/tssa-mvp-2026-10-26';sys.path.insert(0,str(ROOT/'server'))
from stage_school_assets import SchoolSession
remote=r'''
import datetime,json,os,pathlib,signal,subprocess,time,xml.etree.ElementTree as ET
pid=640404;run=pathlib.Path('/data2/zhangzibo/arxiv-tssa/results/mvp-2026-10-28-single-v1');p=pathlib.Path('/proc')/str(pid)
r={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'target_pid':pid,'reason':'Foreign compute PID641279 observed on selected GPU during offline model loading; do not share without agreement.','signals_sent':[]}
if p.exists():
 assert p.stat().st_uid==os.getuid(),'Target no longer owned by this account'
 argv=(p/'cmdline').read_bytes().split(b'\0');assert str(run).encode() in argv and any(a.endswith(b'/tssa_mvp_run.py') for a in argv),'Target command mismatch'
 os.kill(pid,signal.SIGTERM);r['signals_sent'].append('SIGTERM')
 for _ in range(16):
  if not p.exists() or '\nState:\tZ' in (p/'status').read_text():break
  time.sleep(.5)
 if p.exists() and '\nState:\tZ' not in (p/'status').read_text():
  assert p.stat().st_uid==os.getuid() and str(run).encode() in (p/'cmdline').read_bytes().split(b'\0')
  os.kill(pid,signal.SIGKILL);r['signals_sent'].append('SIGKILL');time.sleep(.5)
r['process_status']=(p/'status').read_text().splitlines()[:3] if p.exists() else ['exited']
doc=ET.fromstring(subprocess.run(['nvidia-smi','-q','-x'],capture_output=True,text=True,check=True,timeout=20).stdout)
g=next(g for g in doc.findall('gpu') if g.findtext('uuid')=='GPU-2b05f9c0-6ecb-23cd-03f4-e7b989d07cee')
r['GPU_processes']=[]
for x in g.findall('./processes/process_info'):
 q=pathlib.Path('/proc')/x.findtext('pid')
 try:own=q.stat().st_uid==os.getuid()
 except OSError:own=None
 r['GPU_processes'].append({'pid':int(x.findtext('pid')),'type':x.findtext('type'),'memory':x.findtext('used_memory'),'owner_is_self':own})
r['own_GPU_processes_remaining']=[x for x in r['GPU_processes'] if x['owner_is_self']]
for name in ('failure_or_completion_status.json','last_failure_traceback.txt'):
 q=run/name
 if q.exists():r[name]=q.read_text()[-5000:]
print(json.dumps(r),flush=True)
'''
stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');path=OUT/f'own_single_contention_stop_{stamp}.json'
r={'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'target_pid':640404,'other_user_processes_may_not_be_signalled':True}
try:
 with SchoolSession() as session:
  p=subprocess.run(['ssh','-F',str(session.config),'-o','ControlMaster=no','-o','ControlPath=none','school104',shlex.join(['python3','-c',remote])],capture_output=True,text=True,timeout=100)
  r.update(returncode=p.returncode,stderr=p.stderr[-1500:])
  if p.returncode==0:r.update(status='stop_verified',result=json.loads(p.stdout))
  else:r['status']='stop_not_verified'
except Exception as exc:r.update(status='stop_not_verified',error=str(exc))
r['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat();path.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'report':str(path),**r},ensure_ascii=False,indent=2))
