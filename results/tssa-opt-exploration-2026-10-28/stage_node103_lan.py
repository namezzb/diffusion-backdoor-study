#!/usr/bin/env python3
"""Copy pinned public assets 104 -> 103 over LAN using task-private SSH control.

One exact file per short-lived listener, peer restriction, ephemeral credential,
full source/destination hashes and existing atomic no-overwrite publication.
No system changes, GPU work, persistent service or private-key forwarding.
"""
import hashlib
import importlib.util
import json
import fcntl
from pathlib import Path
import secrets
import select
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
WRAPPER = HERE / 'stage_node103_reuse_ssh.py'
assert hashlib.sha256(WRAPPER.read_bytes()).hexdigest() == 'e15250dee0b31d906d583476f21763d7a2304b59b7c58e59f839c8f445016f0a'
spec = importlib.util.spec_from_file_location('verified_mux_wrapper', WRAPPER)
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)
prepare = wrapper.load_prepare()
ORIGINAL_RELAY = prepare.relay

SOURCE = prepare.REMOTE_COMMON + r'''
import http.server,hmac,threading,time
relative,total,expected,offset,prefix=sys.argv[1],int(sys.argv[2]),sys.argv[3],int(sys.argv[4]),sys.argv[5]
token=sys.stdin.readline().strip()
assert len(token)==64 and all(c in '0123456789abcdef' for c in token)
source=checked(SOURCE,relative)
assert source.stat().st_size==total and 0<=offset<=total
assert hashfile(source)==expected and hashfile(source,offset)==prefix
initial=source.stat()
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if (self.client_address[0]!='192.168.1.103' or self.path!='/asset'
                or not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token)):
            self.send_error(403); return
        current=source.stat()
        assert (current.st_ino,current.st_size,current.st_mtime_ns)==(initial.st_ino,initial.st_size,initial.st_mtime_ns)
        self.connection.settimeout(30)
        self.send_response(200)
        self.send_header('Content-Length',str(total-offset))
        self.send_header('X-Asset-SHA256',expected)
        self.end_headers()
        with source.open('rb') as f:
            f.seek(offset); remaining=total-offset
            while remaining:
                block=f.read(min(1048576,remaining)); assert block
                self.wfile.write(block); remaining-=len(block)
        self.wfile.flush()
server=http.server.HTTPServer(('192.168.1.104',0),Handler)
server.timeout=1
stop=threading.Event()
def stop_on_eof():
    sys.stdin.read(); stop.set()
threading.Thread(target=stop_on_eof,daemon=True).start()
print(json.dumps({'port':server.server_port,'pid':os.getpid(),'size':total,'sha256':expected}),flush=True)
try:
    deadline=time.monotonic()+3600
    while not stop.is_set() and time.monotonic()<deadline: server.handle_request()
finally: server.server_close()
'''

# Keep the original destination lock, prefix checks, ownership checks and
# RENAME_NOREPLACE. Only replace its input stream with one authenticated URL.
RECEIVE = prepare.REMOTE_RECEIVE.replace(
    "fd=os.open(str(partial)",
    "import urllib.request\n"
    "access=json.loads(sys.stdin.readline())\n"
    "assert 1024<=access['port']<=65535 and len(access['token'])==64\n"
    "opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
    "response=opener.open(urllib.request.Request('http://192.168.1.104:'+str(access['port'])+'/asset',headers={'Authorization':'Bearer '+access['token']}),timeout=30)\n"
    "assert response.status==200 and int(response.headers['Content-Length'])==total-offset and response.headers['X-Asset-SHA256']==expected\n"
    "fd=os.open(str(partial)"
).replace('sys.stdin.buffer.read(', 'response.read(')


def relay(config, entry):
    relative, size, digest = entry['relative'], entry['size'], entry['sha256']
    info = prepare.remote_json(config, 'school103', prepare.REMOTE_DEST_INFO, relative, size, digest)
    if info['complete']:
        return {'status': 'already_verified', **entry}
    offset, prefix = info['prefix_size'], info['prefix_sha256']
    prepare.append_ledger({'transport':'direct_LAN', 'event':'validated_resume_prefix',
                           'relative':relative,'prefix_size':offset,'prefix_sha256':prefix})
    token = secrets.token_hex(32)
    source = subprocess.Popen(prepare.ssh_argv(config,'school104',SOURCE,relative,size,digest,offset,prefix),
                              stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    target = None
    start = time.monotonic()
    try:
        source.stdin.write(token+'\n'); source.stdin.flush()
        ready,_,_ = select.select([source.stdout],[],[],300)
        if not ready: raise TimeoutError('Source hash/listener startup deadline')
        line = source.stdout.readline()
        if not line: raise RuntimeError('Source exited before listener ready: '+source.stderr.read()[-2000:])
        listener = json.loads(line)
        assert listener['sha256']==digest and listener['size']==size
        prepare.append_ledger({'transport':'direct_LAN','event':'single_file_listener_started',
                               'relative':relative,'source_pid':listener['pid'],'port':listener['port']})
        target = subprocess.Popen(prepare.ssh_argv(config,'school103',RECEIVE,relative,offset,size,digest,prefix),
                                  stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        out,err = target.communicate(json.dumps({'port':listener['port'],'token':token})+'\n',timeout=3600)
        if target.returncode: raise RuntimeError('Destination transfer failed: '+err[-3000:])
        receipt = json.loads(out)
        assert receipt['committed'] and receipt['sha256']==digest and receipt['size']==size
        return {'status':'transferred_verified','transport':'direct_LAN','resumed_bytes':offset,
                'seconds':time.monotonic()-start,**entry}
    finally:
        if target is not None and target.poll() is None:
            target.terminate()
            try: target.wait(timeout=10)
            except subprocess.TimeoutExpired: target.kill(); target.wait(timeout=5)
        source.stdin.close(); source.stdin=None
        try:
            _,err = source.communicate(timeout=40)
        except subprocess.TimeoutExpired:
            source.terminate(); _,err=source.communicate(timeout=10)
        prepare.append_ledger({'transport':'direct_LAN','event':'single_file_listener_closed',
                               'relative':relative,'returncode':source.returncode,'stderr':err[-2000:]})


prepare.relay = relay
wrapper.load_prepare = lambda: prepare

def install_then_models():
    """One connection per host for CPU installation followed by model copy."""
    entries = prepare.checked_entries('models')
    with (HERE/'.prepare_node103.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        spec=importlib.util.spec_from_file_location('lan_school_session',prepare.SESSION_SCRIPT)
        session_module=importlib.util.module_from_spec(spec); spec.loader.exec_module(session_module)
        session=session_module.SchoolSession(); session.__enter__()
        masters=None
        try:
            with tempfile.TemporaryDirectory(prefix='tssa-lan-',dir='/private/tmp') as temporary:
                folder=Path(temporary).resolve(); folder.chmod(0o700)
                config=folder/'config'
                config.write_text('Host *\n    StrictHostKeyChecking yes\n    BatchMode yes\n    ConnectionAttempts 1\n    ConnectTimeout 60\n    ControlMaster no\n    ControlPath none\n    ForwardAgent no\n    Include "'+str(session.config)+'"\n')
                config.chmod(0o600)
                masters=wrapper.PrivateMasters(config,folder,prepare.append_ledger)
                try:
                    masters.start(); prepare.ssh_argv=masters.ssh_argv
                    # Previous attempt failed while copying the requirements file,
                    # before any installer invocation; original state guard remains.
                    prepare.relay=ORIGINAL_RELAY
                    result=prepare.install_environment(config)
                    prepare.append_ledger({'stage':'install-env','transport':'task_private_masters','result':result})
                    print(json.dumps({'stage':'install-env','result':result}),flush=True)
                    assert result['status'] in ('completed','already_installed_inputs_verified')
                    prepare.relay=relay
                    for entry in entries:
                        result=relay(config,entry)
                        prepare.append_ledger({'stage':'models',**result})
                        print(json.dumps(result),flush=True)
                    prepare.append_ledger({'stage':'models','status':'stage_completed','count':len(entries),'transport':'direct_LAN'})
                finally:
                    masters.close()
        except BaseException as exc:
            prepare.append_ledger({'stage':'install-then-models','status':'failed_no_automatic_retry','error_type':type(exc).__name__,'error':str(exc)})
            raise
        finally:
            session.temporary.cleanup()

if __name__=='__main__':
    if sys.argv[1:]==['--install-then-models','--execute']:
        install_then_models()
    else:
        raise SystemExit(wrapper.main())
