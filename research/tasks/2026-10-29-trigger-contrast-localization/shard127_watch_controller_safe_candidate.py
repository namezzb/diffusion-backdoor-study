"""Sign fresh 103 quiescence and 104 lock observations for the 127 shard."""
import argparse
import base64
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


def remote_install_script():
    """Install only bytes matching the locally verified envelope's digest."""
    return """import hashlib,os,pathlib,re,sys,tempfile
p=pathlib.Path(sys.argv[1]); expected_host=sys.argv[2]; expected_payload=sys.argv[3]
if hashlib.sha256(pathlib.Path('/etc/machine-id').read_bytes()).hexdigest()!=expected_host: raise ValueError('wrong 127 host')
if not re.fullmatch(r'[0-9a-f]{64}',expected_payload): raise ValueError('invalid payload digest')
for part in (p,*p.parents):
 if part.is_symlink(): raise ValueError('symlink in destination')
if p.parent.stat().st_uid!=os.geteuid(): raise ValueError('wrong destination owner')
raw=sys.stdin.buffer.read(65537)
if not raw or len(raw)>65536: raise ValueError('empty or oversized witness')
if hashlib.sha256(raw).hexdigest()!=expected_payload: raise ValueError('incomplete or changed witness')
fd,tmp=tempfile.mkstemp(prefix='.tcl-watch-',dir=p.parent)
try:
 with os.fdopen(fd,'wb') as f: f.write(raw);f.flush();os.fsync(f.fileno())
 os.replace(tmp,p)
 d=os.open(p.parent,os.O_RDONLY)
 try: os.fsync(d)
 finally: os.close(d)
finally:
 if os.path.exists(tmp): os.unlink(tmp)
print(expected_payload)
"""


def fence_command(script_sha,plan_sha,pid,start):
    source="import hashlib,pathlib,sys; p=pathlib.Path(sys.argv.pop(1)); b=p.read_bytes(); assert hashlib.sha256(b).hexdigest()==sys.argv.pop(1); sys.argv[0]=str(p); exec(compile(b,str(p),'exec'),{'__name__':'__main__'})"
    return shlex.join(['python3','-c',source,FENCE_SCRIPT,script_sha,'observe','--identity-sha256',FENCE_IDENTITY,
                       '--plan-sha256',plan_sha,'--pid',str(pid),'--start',str(start)])


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
                observations=[]
                for host,command,namespace,target in [('school103',source103,'tcl-shard-watch',TARGET103),
                                                       ('school104',source104,'tcl-shard104-fence',TARGET104)]:
                    message=subprocess.run(ssh+[host,command],capture_output=True,check=True,timeout=20).stdout
                    path=Path(tmp)/('observation-'+host); sig=Path(str(path)+'.sig')
                    if sig.exists(): sig.unlink()
                    path.write_bytes(message)
                    subprocess.run(['ssh-keygen','-Y','sign','-f',a.watch_private_key,'-n',namespace,str(path)],check=True,capture_output=True,timeout=5)
                    envelope=json.dumps({'message_b64':base64.b64encode(message).decode(),'signature_b64':base64.b64encode(sig.read_bytes()).decode()},sort_keys=True,separators=(',',':')).encode()
                    local=Path(tmp)/('envelope-'+host); local.write_bytes(envelope)
                    observations.append((host,target,envelope,local))
                base.verify_watch(observations[0][3],public,a.watch_key_sha256,a.principal,a.plan_sha256,plan,common.SOURCE_SHA)
                fence_policy.verify_fence(observations[1][3],public,a.watch_key_sha256,a.principal,a.plan_sha256,FENCE_IDENTITY,a.fence_pid,a.fence_start)
                for host,target,envelope,_ in observations:
                    dest=shlex.join(['python3','-c',remote_install_script(),target,DEST_SHA,hashlib.sha256(envelope).hexdigest()])
                    result=subprocess.run(ssh+['school127',dest],input=envelope,capture_output=True,check=True,timeout=15)
                    if result.stdout.decode().strip()!=hashlib.sha256(envelope).hexdigest(): raise ValueError('127 witness publication differs')
                print('published both fresh source observations',flush=True)
            except (OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:
                print('source observation or publication failed; no extension: '+str(exc),flush=True)
            time.sleep(max(.2,5-(time.monotonic()-started)))

if __name__=='__main__': main()
