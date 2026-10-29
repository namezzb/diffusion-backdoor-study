"""Bounded read-only observation; optional terminal artifact retrieval and hash checks."""
from pathlib import Path
import argparse,base64,datetime as dt,hashlib,json,shlex,subprocess,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'server'))
from stage_school_assets import SchoolSession
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',type=Path,required=True);p.add_argument('--retrieve-terminal',action='store_true');a=p.parse_args();receipt=json.loads(a.receipt.read_text())
source=r'''
import base64,datetime as dt,hashlib,json,pathlib,subprocess,sys
r=json.loads(sys.argv[1]);root=pathlib.Path(r['run_root']);proc=pathlib.Path('/proc')/str(r['pid']);out={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'run_root':str(root),'pid':r['pid'],'process_same':False}
try:out['process_same']=proc.joinpath('stat').read_text().rsplit(')',1)[1].split()[19]==r['start_ticks'] and pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()==r['boot_id'];out['process_state']=proc.joinpath('stat').read_text().rsplit(')',1)[1].split()[0]
except (FileNotFoundError,ProcessLookupError):pass
files={}
if root.exists():
 for f in sorted(root.rglob('*')):
  if f.is_file() and not f.is_symlink():
   st=f.stat();assert st.st_size<4*1024*1024;files[str(f.relative_to(root))]={'size':st.st_size}
 for name in ['terminal.json','failure.json','wall_timeout.json','cpu_reload_started.json','cuda_window_started.json','runtime_environment.json']:
  f=root/name
  if f.exists():out[name]=json.loads(f.read_text())
 out['stages']={f.stem:json.loads(f.read_text())['gate'] for f in root.glob('stage_*.json')}
 out['completed_cells']=len(list(root.glob('cells/*.completed.json')))
 out['started_cells']=len(list(root.glob('cells/*.started.json')))
 reservations=sorted(root.glob('reservations/*.json'))
 if reservations:out['last_reservation']=json.loads(reservations[-1].read_text())
log=pathlib.Path(r['log']);out['log_tail']=log.read_text(errors='replace')[-6000:] if log.exists() else None
out['gpu_sample']=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,used_memory','--format=csv,noheader'],text=True,timeout=15)
out['file_count']=len(files)
if sys.argv[2]=='yes':
 assert not out['process_same'] or out.get('process_state')=='Z','Only retrieve full artifacts after process exit'
 if not any(n in out for n in ('terminal.json','failure.json','wall_timeout.json')):
  out['outcome']='interrupted_without_terminal_receipt';out['reserved_is_not_completed']=True
 assert sum(v['size'] for v in files.values())<48*1024*1024
 for name,item in files.items():
  raw=(root/name).read_bytes();item.update(sha256=hashlib.sha256(raw).hexdigest(),base64=base64.b64encode(raw).decode())
 out['returned_files']=files
print(json.dumps(out))
'''
with SchoolSession() as s:
 command=shlex.join(['python3','-c',source,json.dumps(receipt),'yes' if a.retrieve_terminal else 'no'])
 r=subprocess.run(['ssh','-F',str(s.config),'-o','ControlMaster=no','-o','ControlPath=none','school'+receipt['server'],command],capture_output=True,text=True,timeout=90);r.check_returncode();data=json.loads(r.stdout)
folder=Path(__file__).parent/('observation_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));folder.mkdir(mode=0o700)
if 'returned_files' in data:
 for name,entry in data['returned_files'].items():
  rel=Path(name);assert not rel.is_absolute() and '..' not in rel.parts
  raw=base64.b64decode(entry.pop('base64'),validate=True);assert len(raw)==entry['size'] and hashlib.sha256(raw).hexdigest()==entry['sha256']
  f=folder/'artifacts'/rel;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(raw)
(folder/'report.json').write_text(json.dumps(data,indent=2)+'\n');summary={k:data[k] for k in ('at','pid','process_same','process_state','completed_cells','started_cells','file_count','gpu_sample','outcome') if k in data}
summary['stage_status']={k:{'status':v['status'],'failures':v.get('failures',[])} for k,v in data.get('stages',{}).items()}
summary['reserved']=data.get('last_reservation',{}).get('reserved_total')
summary['terminal']={k:data[k].get('status',data[k].get('traceback')) for k in ('terminal.json','failure.json','wall_timeout.json') if k in data}
print(json.dumps({'report':str(folder/'report.json'),**summary}))
