"""Bounded read-only observation and small evidence return; never starts a job."""
import base64
import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
ROOT=Path('/Users/zzb/arxiv');OUT=ROOT/'results/tssa-mvp-2026-10-26'
sys.path.insert(0,str(ROOT/'server'))
from stage_school_assets import SchoolSession
remote=r'''
import base64,datetime,hashlib,json,os,pathlib,subprocess,xml.etree.ElementTree as ET
run=pathlib.Path('/data2/zhangzibo/arxiv-tssa/results/mvp-2026-10-28-single-v1')
assert run.stat().st_uid==os.getuid()
active=[]
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit() or int(p.name) in (os.getpid(),os.getppid()):continue
 try:
  if p.stat().st_uid!=os.getuid():continue
  argv=(p/'cmdline').read_bytes().split(b'\0')
  if str(run).encode() not in argv:continue
  s=(p/'status').read_text().splitlines()
  active.append({'pid':int(p.name),'comm':(p/'comm').read_text().strip(),'status':[x for x in s if x.startswith(('State:','VmRSS:','Threads:'))]})
 except (OSError,PermissionError):pass
doc=ET.fromstring(subprocess.run(['nvidia-smi','-q','-x'],check=True,capture_output=True,text=True,timeout=20).stdout)
g=next(x for x in doc.findall('gpu') if x.findtext('uuid')=='GPU-2b05f9c0-6ecb-23cd-03f4-e7b989d07cee')
processes=[]
for item in g.findall('./processes/process_info'):
 pid=int(item.findtext('pid'));p=pathlib.Path('/proc')/str(pid)
 try:own=p.stat().st_uid==os.getuid()
 except OSError:own=None
 processes.append({'pid':pid,'type':item.findtext('type'),'memory':item.findtext('used_memory'),'owner_is_self':own})
files={}
names=['failure_or_completion_status.json','resource_ledger.json','gpu_diagnostic.json','runtime_environment.json','source_gate.json','last_failure_traceback.txt','prompt_and_cache_index.json','static_response_summary.json','static_screen.json','source_per_image_metrics.jsonl','screen_per_image_metrics.jsonl','learned_candidates.json','per_step_coefficients_and_losses.jsonl','candidate_response_and_image_metrics.json','select_per_image_metrics.jsonl','candidate_selection.json','selected_checkpoint_manifests.json','heldout_report.json','heldout_per_image_metrics.jsonl','heldout_failure_cases.json','fixed_panel_index.json','final_report.json','report.md']
names.extend(str(p.relative_to(run)) for p in sorted((run/'candidates').glob('*.json')))
names.extend(str(p.relative_to(run)) for p in sorted((run/'panels').glob('*.png')))
for name in names:
 p=run/name
 if not p.is_file():continue
 raw=p.read_bytes();assert len(raw)<16*1024**2
 files[name]={'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),'base64':base64.b64encode(raw).decode()}
ops=[]
for p in (run/'operations').glob('*.json'):
 r=json.loads(p.read_text());ops.append({k:r.get(k) for k in ('operation','status','started_at','finished_at','error')})
logs=sorted(run.glob('execution-*.log'))
result={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'read_only':True,'active_project_processes':active,'GPU3':{'uuid':g.findtext('uuid'),'compute_mode':g.findtext('compute_mode'),'memory_used':g.findtext('./fb_memory_usage/used'),'utilization':g.findtext('./utilization/gpu_util'),'processes':processes},'operations':ops,'files':files,'log_path':str(logs[-1]) if logs else None,'log_tail':logs[-1].read_text(errors='replace')[-5000:] if logs else ''}
print(json.dumps(result),flush=True)
'''
stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');path=OUT/f'single_run_observation_{stamp}.json'
report={'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'read_only':True}
try:
 with SchoolSession() as session:
  p=subprocess.run(['ssh','-F',str(session.config),'-o','ControlMaster=no','-o','ControlPath=none','school104',shlex.join(['python3','-c',remote])],capture_output=True,text=True,timeout=100)
  report.update(returncode=p.returncode,stderr=p.stderr[-1500:])
  if p.returncode==0:
   result=json.loads(p.stdout);target=OUT/(path.stem+'_artifacts');target.mkdir()
   for name,item in result['files'].items():
    raw=base64.b64decode(item.pop('base64'));assert hashlib.sha256(raw).hexdigest()==item['sha256'];dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw);item['local_path']=str(dest)
   report.update(status='observed',result=result)
  else:report['status']='connection_or_query_failed'
except Exception as exc:report.update(status='failed',error=str(exc))
report['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat()
with path.open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2)
summary={k:v for k,v in report.items() if k!='result'}
if 'result' in report:
 result=report['result']; summary['result']={k:v for k,v in result.items() if k!='operations'}
 from collections import Counter
 summary['result']['operation_counts']={key:dict(Counter(o['status'] for o in result['operations'] if o['operation'].startswith(key))) for key in ('image/source/','image/screen/','trajectory/','teacher/','training/','image/select/','image/heldout/')}
 summary['result']['incomplete_operations']=[o for o in result['operations'] if o['status']!='completed']
print(json.dumps({'report':str(path),**summary},ensure_ascii=False,indent=2))
