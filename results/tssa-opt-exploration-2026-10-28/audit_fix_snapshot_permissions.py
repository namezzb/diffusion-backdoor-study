"""Audit a proved pre-spawn refusal and tighten only this task's owned snapshot."""
from pathlib import Path
import datetime as dt, hashlib, json, shlex, subprocess, sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'server'))
from stage_school_assets import SchoolSession

REMOTE = r'''
from pathlib import Path
import os,json,sys,stat,hashlib,datetime,subprocess
base=Path('/data1/zhangzibo/arxiv-tssa')
code=base/'code/image-search-6913379cd01c'
deployment=json.loads(sys.argv[1]); expected=deployment['remote']['verified_files']
run=base/'results/tssa-opt-exploration-2026-10-28-v1'
claim=base/'launch-control/image-search-8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6.claim.json'
assert not run.exists() and not run.is_symlink()
assert not claim.exists() and not claim.is_symlink()
active=[]
for p in Path('/proc').iterdir():
 if not p.name.isdigit() or int(p.name)==os.getpid():continue
 try:
  if p.stat().st_uid!=os.getuid():continue
  args=(p/'cmdline').read_bytes().split(b'\0')
  if any(a.endswith(b'/tssa_image_search_run.py') for a in args):active.append(p.name)
 except (FileNotFoundError,ProcessLookupError,PermissionError):pass
assert not active,active
checked={}
for name,h in expected.items():
 p=code/name;st=p.lstat()
 assert not p.is_symlink() and p.resolve()==p and st.st_uid==os.getuid() and stat.S_ISREG(st.st_mode)
 assert hashlib.sha256(p.read_bytes()).hexdigest()==h
 checked[name]=h
dirs={code,code.parent}
for name in expected:
 dirs.update(p for p in (code/name).parents if p==code or code in p.parents)
for rel in ['results','tmp','cache','cache/huggingface','cache/torch','cache/triton','launch-control']:
 p=base/rel
 if p.exists() or p.is_symlink():dirs.add(p)
changes=[]
for p in sorted(dirs):
 st=p.lstat();assert not p.is_symlink() and p.resolve()==p and st.st_uid==os.getuid() and stat.S_ISDIR(st.st_mode)
 if st.st_mode&0o022:
  before=stat.S_IMODE(st.st_mode);os.chmod(p,before&~0o022);changes.append({'path':str(p),'before':oct(before),'after':oct(stat.S_IMODE(p.stat().st_mode))})
for name in expected:
 p=code/name;st=p.stat()
 if st.st_mode&0o022:
  before=stat.S_IMODE(st.st_mode);os.chmod(p,before&~0o022);changes.append({'path':str(p),'before':oct(before),'after':oct(stat.S_IMODE(p.stat().st_mode))})
 assert hashlib.sha256(p.read_bytes()).hexdigest()==expected[name]
assert not run.exists() and not claim.exists()
print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'pre_spawn_absence_proved_snapshot_permissions_tightened','run_exists':False,'remote_claim_exists':False,'active_search_processes':active,'source_hashes':checked,'changes':changes,'GPU_initialized':False}))
'''

deployment=json.loads((OUT/'deployment_20261028T085259Z.json').read_text())
failure=json.loads((OUT/'launch-control/354f1534a9ef4202a8ffff8f668eb03d.result.json').read_text())
assert failure['returncode']==2 and 'Group/world writable path' in failure['stderr']
record={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'prior_failure':failure,'GPU_launch':False}
try:
 with SchoolSession() as session:
  command=shlex.join(['/data1/zhangzibo/arxiv-tssa/venv/bin/python','-I','-c',REMOTE,json.dumps(deployment)])
  p=subprocess.run(['ssh','-F',str(session.config),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','school103',command],capture_output=True,text=True,timeout=90)
  record.update(returncode=p.returncode,stderr=p.stderr[-4000:])
  if p.returncode==0:record['remote']=json.loads(p.stdout)
  else:record['stdout']=p.stdout[-4000:]
except Exception as e:record['error']=str(e)
dest=OUT/('snapshot_permission_audit_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
with dest.open('x') as f:json.dump(record,f,ensure_ascii=False,indent=2)
print(json.dumps({'report':str(dest),**record},ensure_ascii=False,indent=2))
