#!/usr/bin/env python3
"""Resume the exact frozen 47 public models using two bounded SSH sessions.

The prior per-file transport is retained. No install, GPU launch, retries, key
forwarding, arbitrary file serving or changes to the scientific inputs.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time

HERE=Path(__file__).resolve().parent
PREP=HERE/'prepare_node103_offline.py'
assert hashlib.sha256(PREP.read_bytes()).hexdigest()=='967a0341443b26b22222079516fb81da420c80f26b463a6908d46624a49179f6'
spec=importlib.util.spec_from_file_location('batch_pinned_prepare',PREP)
prepare=importlib.util.module_from_spec(spec); spec.loader.exec_module(prepare)

SERVER=prepare.REMOTE_COMMON+r'''
import http.server,hmac,threading,time,signal,re
access=json.loads(sys.stdin.readline()); token=access['token']; entries=access['entries']
assert len(token)==64 and len(entries)==47
old=pathlib.Path('/proc/1323386'); old_state='absent'
if old.exists():
    old_state='pid_reused_or_unrelated'
    if old.stat().st_uid==os.getuid():
        argv=(old/'cmdline').read_bytes().split(b'\0')
        if b'-c' in argv:
            i=argv.index(b'-c')
            if len(argv)>i+2 and hashlib.sha256(argv[i+1]).hexdigest()==access['old_source_sha256'] and argv[i+2]==b'models/sd15/tokenizer/merges.txt':
                os.kill(1323386,signal.SIGTERM)
                for _ in range(25):
                    if not old.exists(): break
                    time.sleep(.2)
                assert not old.exists(),'Old task-owned listener has not exited'
                old_state='exact_owned_finished_file_listener_stopped'
def expired(signum,frame): raise SystemExit('Bounded public asset server deadline')
signal.signal(signal.SIGALRM,expired); signal.alarm(3600)
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if self.client_address[0]!='192.168.1.103' or not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):
            self.send_error(403); return
        match=re.fullmatch(r'/asset/([0-9]+)',self.path)
        if not match or not 0<=int(match[1])<len(entries): self.send_error(404); return
        entry=entries[int(match[1])]; relative=entry['relative']
        assert relative.startswith('models/')
        offset=int(self.headers['X-Offset']); prefix=self.headers['X-Prefix-SHA256']
        source=checked(SOURCE,relative); total=entry['size']
        assert 0<=offset<=total and source.stat().st_size==total
        assert hashfile(source)==entry['sha256'] and hashfile(source,offset)==prefix
        self.connection.settimeout(30)
        self.send_response(200); self.send_header('Content-Length',str(total-offset))
        self.send_header('X-Asset-SHA256',entry['sha256']); self.end_headers()
        with source.open('rb') as stream:
            stream.seek(offset); remaining=total-offset
            while remaining:
                block=stream.read(min(1048576,remaining)); assert block
                self.wfile.write(block); remaining-=len(block)
        self.wfile.flush()
server=http.server.HTTPServer(('192.168.1.104',0),Handler); server.timeout=1
stop=threading.Event()
def eof(): sys.stdin.read(); stop.set()
threading.Thread(target=eof,daemon=True).start()
print(json.dumps({'port':server.server_port,'pid':os.getpid(),'file_count':len(entries),'old_listener_state':old_state}),flush=True)
try:
    while not stop.is_set(): server.handle_request()
finally: server.server_close()
'''

CLIENT=prepare.REMOTE_COMMON+r'''
import urllib.request,time,signal,datetime
access=json.loads(sys.stdin.readline()); entries=access['entries']
assert len(entries)==47 and len(access['token'])==64 and 1024<=access['port']<=65535
def expired(signum,frame): raise TimeoutError('Bounded model transfer deadline')
signal.signal(signal.SIGALRM,expired); signal.alarm(3500)
lock=remote_lock()
receipt=checked(DEST,'setup/model_lan_batch_'+access['receipt_id']+'.jsonl',create=True)
assert not receipt.exists()
log=receipt.open('x')
def record(value):
    value={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),**value}
    line=json.dumps(value); log.write(line+'\n'); log.flush(); os.fsync(log.fileno())
    print(line,flush=True)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for index,entry in enumerate(entries):
    relative,total,expected=entry['relative'],entry['size'],entry['sha256']
    assert relative.startswith('models/')
    dest=checked(DEST,relative,create=True)
    if dest.exists():
        assert dest.stat().st_size==total and hashfile(dest)==expected,'Existing target differs; no overwrite'
        record({'status':'already_verified',**entry}); continue
    partial=checked(DEST,relative+'.partial',create=True)
    assert not partial.exists() or partial.stat().st_nlink==1
    offset=partial.stat().st_size if partial.exists() else 0
    assert offset<=total and shutil.disk_usage(dest.parent).free>=total-offset+2*1024**3
    prefix=hashfile(partial) if partial.exists() else hashlib.sha256(b'').hexdigest()
    record({'status':'prefix_verified','prefix_size':offset,'prefix_sha256':prefix,**entry})
    request=urllib.request.Request('http://192.168.1.104:'+str(access['port'])+'/asset/'+str(index),
        headers={'Authorization':'Bearer '+access['token'],'X-Offset':str(offset),'X-Prefix-SHA256':prefix})
    started=time.monotonic()
    with opener.open(request,timeout=90) as response:
        assert response.status==200 and int(response.headers['Content-Length'])==total-offset
        assert response.headers['X-Asset-SHA256']==expected
        fd=os.open(str(partial),os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o640)
        with os.fdopen(fd,'ab') as out:
            info=os.fstat(out.fileno())
            assert info.st_uid==os.getuid() and info.st_nlink==1 and stat.S_ISREG(info.st_mode) and info.st_size==offset
            remaining=total-offset
            while remaining:
                block=response.read(min(1048576,remaining)); assert block,'Interrupted; retain partial'
                out.write(block); remaining-=len(block)
            assert not response.read(1)
            out.flush(); os.fsync(out.fileno())
    assert partial.stat().st_size==total and hashfile(partial)==expected,'Full hash mismatch; retain partial'
    publish_noreplace(partial,dest)
    record({'status':'transferred_verified','resumed_bytes':offset,'seconds':time.monotonic()-started,**entry})
record({'status':'stage_completed','file_count':len(entries),'receipt_path':str(receipt),'GPU_initialized':False})
log.close()
'''

def ssh(config,host,code):
    base=prepare.SOURCE_ROOT if host=='school104' else prepare.DEST_ROOT
    return ['ssh','-F',str(config),'-T','-o','ControlMaster=no','-o','ControlPath=none',
            '-o','StrictHostKeyChecking=yes','-o','BatchMode=yes','-o','ConnectionAttempts=1',
            '-o','ConnectTimeout=60','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2',
            '-o','ForwardAgent=no',host,shlex.join([base+'/venv/bin/python','-I','-c',code])]

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--execute',action='store_true'); parser.add_argument('--recovery-evidence',type=Path)
    args=parser.parse_args(); entries=prepare.checked_entries('models')
    plan={'stage':'models','file_count':len(entries),'bytes':sum(e['size'] for e in entries),
          'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'GPU_initialization':False,
          'automatic_retry':False,'SSH_sessions':2,'credential_persisted':False}
    if not args.execute: print(json.dumps(plan,indent=2)); return
    checkpoint=json.loads((HERE/'node103_checkpoint_20261028T0830Z.json').read_text())
    now=dt.datetime.now(dt.timezone.utc)
    if now<dt.datetime.fromisoformat(checkpoint['next_connection_not_before']):
        assert args.recovery_evidence is not None,'Honor recorded retry time unless new platform recovery is observed'
        recovery=json.loads(args.recovery_evidence.read_text())
        observed=dt.datetime.fromisoformat(recovery['observed_at'])
        assert 0<=(now-observed).total_seconds()<180 and (now-dt.datetime.fromisoformat(checkpoint['failure_at'])).total_seconds()>600
        assert recovery['source']=='authenticated browser UI' and recovery['node103_live_GPU_count']==3 and recovery['node103_historical'] is False and recovery['node104_live_GPU_count']==5
        prepare.append_ledger({'event':'explicit_recovery_after_changed_platform_evidence','evidence':str(args.recovery_evidence),'evidence_sha256':hashlib.sha256(args.recovery_evidence.read_bytes()).hexdigest(),'GPU_launch':False})
    old_path=HERE/'stage_node103_lan.py'
    assert hashlib.sha256(old_path.read_bytes()).hexdigest()=='831f6123ecd2ea7dfc2e2ceb8e5600d789cae25d14a3b1df6d69355e6bb835ae'
    old_spec=importlib.util.spec_from_file_location('previous_task_transfer',old_path); old_module=importlib.util.module_from_spec(old_spec);old_spec.loader.exec_module(old_module)
    old_source_sha256=hashlib.sha256(old_module.SOURCE.encode()).hexdigest()
    with (HERE/'.prepare_node103.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        module_spec=importlib.util.spec_from_file_location('batch_school_session',prepare.SESSION_SCRIPT)
        module=importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(module)
        session=module.SchoolSession(); session.__enter__()
        source=target=None
        token=secrets.token_hex(32); receipt_id=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        prepare.append_ledger({'transport':'direct_LAN_batch','status':'stage_started',**plan})
        try:
            source=subprocess.Popen(ssh(session.config,'school104',SERVER),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            source.stdin.write(json.dumps({'token':token,'entries':entries,'old_source_sha256':old_source_sha256})+'\n'); source.stdin.flush()
            if not select.select([source.stdout],[],[],90)[0]: raise TimeoutError('Source startup deadline')
            line=source.stdout.readline()
            if not line: raise RuntimeError('Source startup failed: '+source.stderr.read()[-2000:])
            listening=json.loads(line); assert listening['file_count']==47
            prepare.append_ledger({'transport':'direct_LAN_batch','event':'listener_started',**listening})
            with tempfile.TemporaryFile(mode='w+t') as errors:
                target=subprocess.Popen(ssh(session.config,'school103',CLIENT),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True)
                target.stdin.write(json.dumps({'token':token,'entries':entries,'port':listening['port'],'receipt_id':receipt_id})+'\n'); target.stdin.close(); target.stdin=None
                deadline=time.monotonic()+3600; completed=False
                while True:
                    if time.monotonic()>deadline: raise TimeoutError('Destination deadline')
                    if not select.select([target.stdout],[],[],10)[0]:
                        if source.poll() is not None: raise RuntimeError('Source connection ended; preserve partials')
                        continue
                    line=target.stdout.readline()
                    if not line: break
                    record=json.loads(line); prepare.append_ledger({'stage':'models','transport':'direct_LAN_batch',**record})
                    print(json.dumps(record),flush=True)
                    completed=completed or record.get('status')=='stage_completed'
                target.wait(timeout=10); errors.seek(0)
                if target.returncode or not completed: raise RuntimeError('Destination incomplete: '+errors.read()[-3000:])
        except BaseException as exc:
            prepare.append_ledger({'transport':'direct_LAN_batch','status':'failed_no_automatic_retry','error_type':type(exc).__name__,'error':str(exc)})
            raise
        finally:
            if target is not None and target.poll() is None:
                target.terminate()
                try: target.wait(timeout=10)
                except subprocess.TimeoutExpired: target.kill(); target.wait(timeout=5)
            if source is not None:
                try: source.stdin.close()
                except (BrokenPipeError,OSError): pass
                source.stdin=None
                try: _,error=source.communicate(timeout=40)
                except subprocess.TimeoutExpired: source.terminate(); _,error=source.communicate(timeout=10)
                prepare.append_ledger({'transport':'direct_LAN_batch','event':'listener_session_closed','returncode':source.returncode,'stderr':error[-2000:]})
            session.temporary.cleanup()

if __name__=='__main__': main()
