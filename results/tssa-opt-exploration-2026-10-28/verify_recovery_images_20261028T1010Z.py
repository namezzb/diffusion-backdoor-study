"""Read-only SHA verification of the 42 new completed PNGs in one fixed snapshot."""
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('observer',HERE/'observe_image_search.py')
obs=importlib.util.module_from_spec(spec);spec.loader.exec_module(obs)
manifest=HERE/'recovery_completed_image_manifest_20261028T1010Z.json'
payload=json.loads(manifest.read_text())
assert len(payload['rows'])==42
REMOTE=r'''
import datetime as dt,hashlib,json,os,pathlib,stat,sys
m=json.loads(sys.argv[1]);assert len(m['rows'])==42
R=pathlib.Path('/data1/zhangzibo/arxiv-tssa/results/tssa-opt-exploration-2026-10-28-v1')
def read_digest(rel,limit):
 p=R/rel;assert not pathlib.PurePosixPath(rel).is_absolute() and p.is_relative_to(R) and p.resolve()==p
 for q in [p,*p.parents]:
  if q==R.parent:break
  assert not q.is_symlink() and q.stat().st_uid==os.getuid()
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  b=os.fstat(fd);assert stat.S_ISREG(b.st_mode) and b.st_size<=limit
  h=hashlib.sha256();n=0
  while True:
   part=os.read(fd,65536)
   if not part:break
   n+=len(part);assert n<=limit;h.update(part)
  a=os.fstat(fd);assert n==b.st_size==a.st_size and b.st_mtime_ns==a.st_mtime_ns
  return {'sha256':h.hexdigest(),'size':n}
 finally:os.close(fd)
result={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'read_only':True,'GPU_initialized':False,'scientific_files_modified':False,'execution_id':m['execution_id'],'rows':[]}
for row in m['rows']:
 assert len(row['task_id'])==64 and all(c in '0123456789abcdef' for c in row['task_id'])
 assert row['image_path'].startswith('images/search/')
 receipt=read_digest('operations/'+row['task_id']+'.json',65536)
 image=read_digest(row['image_path'],16*1024*1024)
 assert receipt['sha256']==row['receipt_sha256'] and image['sha256']==row['image_sha256']
 result['rows'].append({'task_id':row['task_id'],'receipt_sha256':receipt['sha256'],'image':image,'matches_snapshot':True})
result['verified_images']=len(result['rows'])
print(json.dumps(result))
'''
sys.path.insert(0,str(ROOT/'server'))
from stage_school_assets import SchoolSession
out=HERE/'recovery_PNG_hash_acceptance_20261028T1010Z.json'
assert not out.exists()
report={'started_at':obs.now(),'read_only':True,'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}
s=SchoolSession()
try:
 s.__enter__()
 cfg=Path(s.temporary.name)/'verification-config'
 cfg.write_text('Host *\n    BatchMode yes\n    StrictHostKeyChecking yes\n    ConnectTimeout 60\n    ConnectionAttempts 1\n    ControlMaster no\n    ControlPath none\n    ControlPersist no\n    UpdateHostKeys no\n    Include "'+str(s.config)+'"\n');cfg.chmod(0o600)
 command=shlex.join(['/data1/zhangzibo/arxiv-tssa/venv/bin/python','-I','-B','-c',REMOTE,json.dumps(payload)])
 rc,stdout,stderr=obs.one_bounded_ssh(cfg,'103',command)
 report.update(returncode=rc,stderr=stderr.decode(errors='replace')[-2000:])
 if rc==0:report['remote']=json.loads(stdout)
 else:report['stdout_tail']=stdout.decode(errors='replace')[-2000:]
except Exception as exc:report['error']=str(exc)
finally:
 if hasattr(s,'temporary'):s.temporary.cleanup()
report['finished_at']=obs.now()
with out.open('x') as stream:json.dump(report,stream,ensure_ascii=False,indent=2);stream.write('\n')
print(json.dumps({'report':str(out),'returncode':report.get('returncode'),'verified':report.get('remote',{}).get('verified_images'),'error':report.get('error')}))
