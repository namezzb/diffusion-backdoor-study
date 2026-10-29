"""One bounded read-only verification of all 816 terminal-run PNGs; no GPU work."""
import hashlib, importlib.util, json, shlex, sys, zlib, base64
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('observer',HERE/'observe_image_search.py')
obs=importlib.util.module_from_spec(spec);spec.loader.exec_module(obs)
manifest=HERE/'final_image_inventory_816_20261028T1115Z.json'
payload=json.loads(manifest.read_text());assert len(payload['rows'])==816
REMOTE=r'''
import datetime as dt,hashlib,json,os,pathlib,stat,collections
R=pathlib.Path('/data1/zhangzibo/arxiv-tssa/results/tssa-opt-exploration-2026-10-28-v1')
assert len(M['rows'])==816
def read(rel,limit,content=False):
 p=R/rel;assert not pathlib.PurePosixPath(rel).is_absolute() and p.is_relative_to(R) and p.resolve()==p
 for q in [p,*p.parents]:
  if q==R.parent:break
  assert not q.is_symlink() and q.stat().st_uid==os.getuid()
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  b=os.fstat(fd);assert stat.S_ISREG(b.st_mode) and b.st_size<=limit
  h=hashlib.sha256();n=0;parts=[]
  while True:
   part=os.read(fd,65536)
   if not part:break
   n+=len(part);assert n<=limit;h.update(part)
   if content:parts.append(part)
  a=os.fstat(fd);assert n==b.st_size==a.st_size and b.st_mtime_ns==a.st_mtime_ns
  return h.hexdigest(),n,b''.join(parts)
 finally:os.close(fd)
result={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'read_only':True,'GPU_initialized':False,'scientific_files_modified':False,'rows':[]}
stages=collections.Counter();images=set();task_ids=set()
for row in M['rows']:
 tid=row['task_id'];assert len(tid)==64 and all(c in '0123456789abcdef' for c in tid) and tid not in task_ids;task_ids.add(tid)
 rh,_,raw=read('operations/'+tid+'.json',65536,True);assert rh==row['receipt_sha256']
 receipt=json.loads(raw);assert receipt['status']=='completed' and receipt['task_id']==tid
 record=receipt['record'];rel=record['image_path'];stage=receipt['task']['stage']
 assert stage in ('search','dev') and rel.startswith('images/'+stage+'/') and rel.endswith('.png') and rel not in images;images.add(rel)
 ih,size,_=read(rel,16*1024*1024);assert ih==record['image_sha256'];stages[stage]+=1
 result['rows'].append({'task_id':tid,'image_sha256':ih,'size':size,'matches_snapshot':True})
assert dict(stages)==M['stages']
assert {p.name for p in (R/'operations').iterdir()}=={i+'.json' for i in task_ids}
actual_images={str(p.relative_to(R)) for p in (R/'images').rglob('*') if p.is_file()}
assert actual_images==images
result.update(verified_images=len(result['rows']),stage_counts=dict(stages),total_image_bytes=sum(r['size'] for r in result['rows']),exact_image_and_operation_inventory=True)
print(json.dumps(result,ensure_ascii=False))
'''
program='import json\nM=json.loads('+repr(json.dumps(payload))+')\n'+REMOTE
encoded=base64.b64encode(zlib.compress(program.encode())).decode()
command=shlex.join(['/data1/zhangzibo/arxiv-tssa/venv/bin/python','-I','-B','-c','import zlib,base64;exec(zlib.decompress(base64.b64decode('+repr(encoded)+')))'])
assert len(command.encode())<120000
sys.path.insert(0,str(ROOT/'server'))
from stage_school_assets import SchoolSession
out=HERE/'final_PNG_hash_acceptance_816_20261028T1115Z.json';assert not out.exists()
report={'started_at':obs.now(),'read_only':True,'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'command_bytes':len(command.encode())}
s=SchoolSession()
try:
 s.__enter__();cfg=Path(s.temporary.name)/'verification-config'
 cfg.write_text('Host *\n    BatchMode yes\n    StrictHostKeyChecking yes\n    ConnectTimeout 60\n    ConnectionAttempts 1\n    ControlMaster no\n    ControlPath none\n    ControlPersist no\n    UpdateHostKeys no\n    Include "'+str(s.config)+'"\n');cfg.chmod(0o600)
 rc,stdout,stderr=obs.one_bounded_ssh(cfg,'103',command)
 report.update(returncode=rc,stderr=stderr.decode(errors='replace')[-2000:])
 if rc==0:report['remote']=json.loads(stdout)
 else:report['stdout_tail']=stdout.decode(errors='replace')[-2000:]
except Exception as exc:report['error']=type(exc).__name__+': '+str(exc)
finally:
 if hasattr(s,'temporary'):s.temporary.cleanup()
report['finished_at']=obs.now()
with out.open('x') as stream:json.dump(report,stream,ensure_ascii=False,indent=2);stream.write('\n')
print(json.dumps({'report':str(out),'returncode':report.get('returncode'),'verified':report.get('remote',{}).get('verified_images'),'error':report.get('error')}))
