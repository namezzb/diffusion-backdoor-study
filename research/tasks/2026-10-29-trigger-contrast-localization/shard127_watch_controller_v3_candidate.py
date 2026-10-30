"""Sign fresh 103 quiescence and 104 lock observations for the 127 shard."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import shard104_watch_controller as common
import shard104_policy as base
import shard127_policy as fence_policy

DEST_SHA='99b0f2a4634566cc13b4686bcfad863346e6975d37221fb1fc27ebb0d814848d'
TARGET103='/data1/zhangzibo/arxiv-tssa/preparations/tcl127-source-watch-20261030.json'
TARGET104='/data1/zhangzibo/arxiv-tssa/preparations/tcl127-104-fence-watch-20261030.json'
FENCE_SCRIPT='/data2/zhangzibo/arxiv-tssa/preparations/tcl127_104_fence.py'
FENCE_IDENTITY='4ffb1ac179b6f8b913f752281da3f4cce6f1fc6c2fca9c730746f6e3ad9add0a'


def fence_command(script_sha,plan_sha,pid,start):
    source="import hashlib,pathlib,sys; p=pathlib.Path(sys.argv.pop(1)); b=p.read_bytes(); assert hashlib.sha256(b).hexdigest()==sys.argv.pop(1); sys.argv[0]=str(p); exec(compile(b,str(p),'exec'),{'__name__':'__main__'})"
    return shlex.join(['python3','-c',source,FENCE_SCRIPT,script_sha,'observe','--identity-sha256',FENCE_IDENTITY,
                       '--plan-sha256',plan_sha,'--pid',str(pid),'--start',str(start)])


def remote_publish_pair_script():
    # Each replace is atomic; a crash between the two replacements can leave
    # one older envelope. The runner independently requires both to be valid.
    return '''import base64,datetime,hashlib,json,os,pathlib,sys,tempfile
first,second=map(pathlib.Path,sys.argv[1:3]); expected=sys.argv[3]; expected_hashes=dict(zip(('source','fence'),sys.argv[4:6]))
if len(sys.argv)!=6 or any(len(h)!=64 or any(c not in '0123456789abcdef' for c in h) for h in expected_hashes.values()): raise ValueError('invalid witness digests')
if hashlib.sha256(pathlib.Path('/etc/machine-id').read_bytes()).hexdigest()!=expected: raise ValueError('wrong 127 host')
if first==second or first.parent!=second.parent: raise ValueError('invalid witness targets')
for p in (first,second):
 for part in (p,*p.parents):
  if part.is_symlink(): raise ValueError('symlink in destination')
 if p.parent.stat().st_uid!=os.geteuid(): raise ValueError('wrong destination owner')
raw=sys.stdin.buffer.read(196609)
if len(raw)>196608: raise ValueError('witness bundle too large')
bundle=json.loads(raw)
if set(bundle)!={'source','fence'}: raise ValueError('invalid witness bundle')
items=[]; expirations=[]
now=datetime.datetime.now(datetime.timezone.utc)
for name,p in (('source',first),('fence',second)):
 envelope=base64.b64decode(bundle[name],validate=True)
 if not envelope or len(envelope)>65536: raise ValueError('empty or oversized witness')
 if hashlib.sha256(envelope).hexdigest()!=expected_hashes[name]: raise ValueError('incomplete or changed witness')
 data=json.loads(base64.b64decode(json.loads(envelope)['message_b64'],validate=True))
 issued=datetime.datetime.fromisoformat(data['issued_at_utc']); expires=datetime.datetime.fromisoformat(data['expires_at_utc'])
 if (issued.tzinfo is None or expires.tzinfo is None or issued.utcoffset()!=datetime.timedelta(0)
     or expires.utcoffset()!=datetime.timedelta(0) or issued>now or now>=expires
     or not 0<(expires-issued).total_seconds()<=30): raise ValueError('witness expired before publication')
 items.append((p,envelope))
 expirations.append(expires)
staged=[]
try:
 for p,envelope in items:
  fd,tmp=tempfile.mkstemp(prefix='.tcl-watch-',dir=p.parent); staged.append((p,tmp))
  with os.fdopen(fd,'wb') as f: f.write(envelope);f.flush();os.fsync(f.fileno())
 if datetime.datetime.now(datetime.timezone.utc)>=min(expirations): raise ValueError('witness expired while staging')
 for p,tmp in staged: os.replace(tmp,p)
 d=os.open(first.parent,os.O_RDONLY)
 try: os.fsync(d)
 finally: os.close(d)
finally:
 for p,tmp in staged:
  if os.path.exists(tmp): os.unlink(tmp)
print(json.dumps({name:hashlib.sha256(envelope).hexdigest() for name,(_,envelope) in zip(('source','fence'),items)},sort_keys=True))
'''


def collect_one(ssh,host,command,namespace,tmp,key):
    message=subprocess.run(ssh+[host,command],capture_output=True,check=True,timeout=20).stdout
    path=Path(tmp)/('observation-'+host); sig=Path(str(path)+'.sig')
    if sig.exists(): sig.unlink()
    path.write_bytes(message)
    subprocess.run(['ssh-keygen','-Y','sign','-f',key,'-n',namespace,str(path)],check=True,capture_output=True,timeout=5)
    envelope=json.dumps({'message_b64':base64.b64encode(message).decode(),
                         'signature_b64':base64.b64encode(sig.read_bytes()).decode()},sort_keys=True,separators=(',',':')).encode()
    local=Path(tmp)/('envelope-'+host); local.write_bytes(envelope)
    return envelope,local


def collect_pair(ssh,source103,source104,tmp,key):
    with ThreadPoolExecutor(max_workers=2) as executor:
        first=executor.submit(collect_one,ssh,'school103',source103,'tcl-shard-watch',tmp,key)
        second=executor.submit(collect_one,ssh,'school104',source104,'tcl-shard104-fence',tmp,key)
        return first.result(),second.result()


def publish_pair(ssh,source,fence):
    bundle=json.dumps({'source':base64.b64encode(source).decode(),
                       'fence':base64.b64encode(fence).decode()},sort_keys=True,separators=(',',':')).encode()
    expected={'source':hashlib.sha256(source).hexdigest(),'fence':hashlib.sha256(fence).hexdigest()}
    dest=shlex.join(['python3','-c',remote_publish_pair_script(),TARGET103,TARGET104,DEST_SHA,expected['source'],expected['fence']])
    result=subprocess.run(ssh+['school127',dest],input=bundle,capture_output=True,check=True,timeout=15)
    if json.loads(result.stdout)!=expected: raise ValueError('127 witness publication differs')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('ssh-config','watch-private-key','watch-public-key','watch-key-sha256','principal','plan-sha256',
                 'source-attempts-sha256','manifest-sha256','source-guard-sha256','fence-guard-sha256'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--fence-pid',type=int,required=True); p.add_argument('--fence-start',type=int,required=True)
    a=p.parse_args()
    for v in (a.watch_key_sha256,a.plan_sha256,a.source_attempts_sha256,a.manifest_sha256,a.source_guard_sha256,a.fence_guard_sha256):
        if not re.fullmatch(r'[0-9a-f]{64}',v): raise ValueError('invalid SHA')
    public=Path(a.watch_public_key).read_bytes()
    if hashlib.sha256(public).hexdigest()!=a.watch_key_sha256 or Path(a.watch_private_key).stat().st_mode & 0o077:
        raise ValueError('watch key does not match or private key mode is unsafe')
    plan={'run_id':'tcl-20261029-01-v1','manifest_sha256':a.manifest_sha256,'source_attempts_logical_sha256':a.source_attempts_sha256}
    with tempfile.TemporaryDirectory(prefix='tcl127-watch-') as tmp:
        ssh=['ssh','-F',a.ssh_config,'-o','BatchMode=yes','-o','ControlMaster=auto','-o','ControlPersist=180',
             '-o','ControlPath='+tmp+'/%C','-o','ConnectTimeout=15']
        source103=common.source_command(a.source_guard_sha256,a.plan_sha256,a.source_attempts_sha256,a.manifest_sha256)
        source104=fence_command(a.fence_guard_sha256,a.plan_sha256,a.fence_pid,a.fence_start)
        while True:
            started=time.monotonic()
            try:
                first,second=collect_pair(ssh,source103,source104,tmp,a.watch_private_key)
                base.verify_watch(first[1],public,a.watch_key_sha256,a.principal,a.plan_sha256,plan,common.SOURCE_SHA)
                fence_policy.verify_fence(second[1],public,a.watch_key_sha256,a.principal,a.plan_sha256,FENCE_IDENTITY,a.fence_pid,a.fence_start)
                publish_pair(ssh,first[0],second[0])
                print('published both fresh source observations',flush=True)
            except (OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:
                print('source observation or publication failed; no extension: '+str(exc),flush=True)
            time.sleep(max(.2,5-(time.monotonic()-started)))

if __name__=='__main__': main()
