"""Locally observe 103 and atomically publish short-lived signed witnesses to 104.

Run only after the independent shard review. The dedicated private key stays
on this host; failed or slow observations never extend a prior witness.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time

import shard104_policy as policy

SOURCE = '/data1/zhangzibo/arxiv-tssa/preparations/tcl104-shard-source-guard.py'
TARGET = '/data2/zhangzibo/arxiv-tssa/preparations/tcl104-shard-watch-20261030.json'
SOURCE_SHA = 'cd06519e32872d3878e9ba27accf715cf97f9a68242c5130c0a4f8002ee08352'
DEST_SHA = 'af2fbecce76fa0ac96161ea712cc39576d9a198c4bc0f43585de6821ed5b5555'


def remote_install_script():
    return '''import hashlib,os,pathlib,sys,tempfile
p=pathlib.Path(sys.argv[1]); expected=sys.argv[2]
if hashlib.sha256(pathlib.Path('/etc/machine-id').read_bytes()).hexdigest()!=expected: raise ValueError('wrong 104 host')
for part in (p,*p.parents):
 if part.is_symlink(): raise ValueError('symlink in destination')
if p.parent.stat().st_uid!=os.geteuid(): raise ValueError('wrong destination owner')
raw=sys.stdin.buffer.read(65537)
if len(raw)>65536: raise ValueError('witness too large')
fd,tmp=tempfile.mkstemp(prefix='.tcl-watch-',dir=p.parent)
try:
 with os.fdopen(fd,'wb') as f: f.write(raw);f.flush();os.fsync(f.fileno())
 os.replace(tmp,p)
 d=os.open(p.parent,os.O_RDONLY)
 try: os.fsync(d)
 finally: os.close(d)
finally:
 if os.path.exists(tmp): os.unlink(tmp)
print(hashlib.sha256(raw).hexdigest())
'''


def source_command(script_sha, plan_sha, attempts_sha, manifest_sha):
    source = "import hashlib,pathlib,sys; p=pathlib.Path(sys.argv.pop(1)); b=p.read_bytes(); assert hashlib.sha256(b).hexdigest()==sys.argv.pop(1); sys.argv[0]=str(p); exec(compile(b,str(p),'exec'),{'__name__':'__main__'})"
    return shlex.join(['python3','-c',source,SOURCE,script_sha,'--plan-sha256',plan_sha,
                       '--source-attempts-sha256',attempts_sha,'--manifest-sha256',manifest_sha,
                       '--source-machine-sha256',SOURCE_SHA])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('ssh-config','watch-private-key','watch-public-key','watch-key-sha256','principal','plan-sha256','source-attempts-sha256','manifest-sha256','source-guard-sha256'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv)
    for value in (args.watch_key_sha256,args.plan_sha256,args.source_attempts_sha256,args.manifest_sha256,args.source_guard_sha256):
        if not re.fullmatch(r'[0-9a-f]{64}',value): raise ValueError('invalid SHA')
    public=Path(args.watch_public_key).read_bytes()
    if hashlib.sha256(public).hexdigest()!=args.watch_key_sha256: raise ValueError('wrong watcher public key')
    if Path(args.watch_private_key).stat().st_mode & 0o077: raise ValueError('watch key permissions are not private')
    plan={'run_id':'tcl-20261029-01-v1','manifest_sha256':args.manifest_sha256,'source_attempts_logical_sha256':args.source_attempts_sha256}
    with tempfile.TemporaryDirectory(prefix='tcl-watch-') as tmp:
        common=['ssh','-F',args.ssh_config,'-o','BatchMode=yes','-o','ControlMaster=auto','-o','ControlPersist=180',
                '-o','ControlPath='+tmp+'/%C','-o','ConnectTimeout=15']
        destination=shlex.join(['python3','-c',remote_install_script(),TARGET,DEST_SHA])
        print('watch controller started; failed observations will not be renewed',flush=True)
        while True:
            started=time.monotonic()
            try:
                command=source_command(args.source_guard_sha256,args.plan_sha256,args.source_attempts_sha256,args.manifest_sha256)
                observed=subprocess.run(common+['school103',command],capture_output=True,check=True,timeout=20).stdout
                record=json.loads(observed)
                if record.get('plan_sha256') != args.plan_sha256: raise ValueError('wrong observation plan')
                message=Path(tmp)/'observation'; signature=Path(str(message)+'.sig')
                if signature.exists(): signature.unlink()
                message.write_bytes(observed)
                subprocess.run(['ssh-keygen','-Y','sign','-f',args.watch_private_key,'-n','tcl-shard-watch',str(message)],
                               check=True,capture_output=True,timeout=5)
                envelope=json.dumps({'message_b64':base64.b64encode(observed).decode(),
                    'signature_b64':base64.b64encode(signature.read_bytes()).decode()},sort_keys=True,separators=(',',':')).encode()
                local=Path(tmp)/'envelope.json'; local.write_bytes(envelope)
                policy.verify_watch(local,public,args.watch_key_sha256,args.principal,args.plan_sha256,plan,SOURCE_SHA)
                result=subprocess.run(common+['school104',destination],input=envelope,capture_output=True,check=True,timeout=15)
                if result.stdout.decode().strip()!=hashlib.sha256(envelope).hexdigest(): raise ValueError('remote witness hash mismatch')
                print('published '+record['expires_at_utc'],flush=True)
            except (OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:
                print('observation or publication failed; no renewal: '+str(exc),flush=True)
            delay=max(0.2,5-(time.monotonic()-started))
            time.sleep(delay)


if __name__=='__main__':
    raise SystemExit(main())
