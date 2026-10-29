"""One scoped metadata-only repair; never starts GPU work or modifies science bytes."""
import datetime as dt, importlib.util, json, shlex, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('observer_harden', HERE/'observe_image_search.py');obs=importlib.util.module_from_spec(spec);spec.loader.exec_module(obs)
REMOTE=r'''
import os,pwd,json,stat,fcntl,hashlib,datetime as dt
from pathlib import Path
b=Path('/data1/zhangzibo/arxiv-tssa');r=b/'results/tssa-opt-exploration-2026-10-28-v1';c=b/'launch-control'
plan='8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6'
boot='1c2bddf4-f594-43cf-8a4d-5b116ad79067'
assert pwd.getpwuid(os.getuid()).pw_name=='zhangzibo' and os.getuid()==24112
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==boot
paths=[r,r/'operations',r/'.run.lock',c/('image-search-'+plan+'.lock')]
def meta(p):
 s=p.lstat();assert not p.is_symlink() and p.resolve()==p and s.st_uid==os.getuid();return {'path':str(p),'uid':s.st_uid,'mode':oct(stat.S_IMODE(s.st_mode))}
for p in [b,c,b/'results']:assert int(meta(p)['mode'],8)&0o022==0
before=[meta(p) for p in paths]
assert int(before[0]['mode'],8)==0o775 and int(before[1]['mode'],8)==0o775 and int(before[2]['mode'],8)==0o664
assert int(before[3]['mode'],8) in (0o600,0o644,0o664)
for proc in Path('/proc').iterdir():
 if proc.name.isdigit() and int(proc.name)!=os.getpid():
  try:
   if proc.stat().st_uid==os.getuid():
    args=(proc/'cmdline').read_bytes().split(b'\0');assert not any(Path(a.decode()).name=='tssa_image_search_run.py' for a in args if a)
  except FileNotFoundError:pass
files=[r/'identity.json',*sorted((r/'operations').glob('*.json'))]
assert len(files)==173
def hashes():return {str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
def persist(p,obj):
 with p.open('x') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 fd=os.open(str(p.parent),os.O_RDONLY|os.O_DIRECTORY);os.fsync(fd);os.close(fd)
lockfds=[]
try:
 for p in (paths[3],paths[2]):
  fd=os.open(str(p),os.O_RDWR|os.O_NOFOLLOW);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);lockfds.append(fd)
 saved=hashes();audit={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'boot_id':boot,'scope':'only own fixed run/operations and two lock permissions','before':before,'scientific_file_hashes_before':saved,'GPU_started':False}
 prefix=c/'permission-hardening-20261028T1000Z'
 persist(Path(str(prefix)+'.before.json'),audit)
 for p,prior in zip(paths,before):
  assert meta(p)==prior and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==boot
  p.chmod(int(prior['mode'],8)&~0o022)
 assert hashes()==saved
 after=[meta(p) for p in paths]
 assert all(int(m['mode'],8)&0o022==0 for m in after)
 result={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'status':'owned_path_permissions_hardened_science_bytes_unchanged','before':before,'after':after,'scientific_files_hash_verified_unchanged':len(saved),'boot_id':boot,'GPU_started':False,'run_identity_changed':False,'claims_changed':False,'audit_before':str(prefix)+'.before.json'}
 persist(Path(str(prefix)+'.after.json'),result);print(json.dumps(result))
finally:
 for fd in lockfds:os.close(fd)
'''
sys.path.insert(0,str(ROOT/'server'));from stage_school_assets import SchoolSession
report={'at':obs.now(),'server':'103','GPU_started':False,'scope':'four exact owned metadata paths'};session=SchoolSession()
try:
 session.__enter__();cmd=shlex.join(['/data1/zhangzibo/arxiv-tssa/venv/bin/python','-I','-B','-c',REMOTE]);rc,raw,err=obs.one_bounded_ssh(session.config,'103',cmd);report.update(returncode=rc,stderr=err.decode(errors='replace')[-3000:]);report['remote' if rc==0 else 'stdout']=json.loads(raw) if rc==0 else raw.decode(errors='replace')[-3000:]
except Exception as e:report['error']=type(e).__name__+': '+str(e)
finally:
 if hasattr(session,'temporary'):session.temporary.cleanup()
target=HERE/'recovery_path_hardening_20261028.json'
with target.open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
print(json.dumps({'report':str(target),**report},ensure_ascii=False))
