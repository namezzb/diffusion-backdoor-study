"""One bounded read-only school104 prefix check; no transfer and no GPU work."""
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
HELPER = ROOT / 'server/stage_school_assets.py'
assert hashlib.sha256(HELPER.read_bytes()).hexdigest() == '5de11a27f3aa4bd412eef6dd9b837d6ab0be82fc6bf0efb437db29901b15c776'
spec = importlib.util.spec_from_file_location('school_stage', HELPER)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
local = Path('/private/tmp/arxiv-tssa-stage/bf96322dae6a6099e0dd69c24cfbeb6e36d558ef8e7ad362c7b21c9864dbffe0.part')
state = json.loads((ROOT / 'server/gpu_monitor_state.json').read_text())
assert datetime.datetime.now().astimezone() >= datetime.datetime.fromisoformat(state['next_ssh_probe_not_before'])
ls = local.lstat()
assert stat.S_ISREG(ls.st_mode) and ls.st_uid == os.getuid() and ls.st_size == 492265874
assert stage.sha256(local) == '5d3d1299268e3fa1daee2ce59de969b676ad46c5e12c17827c725599d91cc22f'
remote_code = r'''
from pathlib import Path
import hashlib,json,os,stat,datetime
root=Path('/data2/zhangzibo/arxiv-tssa');final=root/'models/openjourney/text_encoder/model.safetensors'
p=final if final.exists() else Path(str(final)+'.uploading')
for x in [p,*p.parents]:
 if x.is_relative_to(root):assert not x.is_symlink() and x.stat().st_uid==os.getuid()
s=p.stat();assert stat.S_ISREG(s.st_mode) and 0<=s.st_size<=492265874
h=hashlib.sha256()
with p.open('rb') as f:
 for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
assert p.stat().st_size==s.st_size and p.stat().st_mtime_ns==s.st_mtime_ns
if p==final:assert s.st_size==492265874 and h.hexdigest()=='5d3d1299268e3fa1daee2ce59de969b676ad46c5e12c17827c725599d91cc22f'
fragments=[]
for x in p.parent.glob(final.name+'.uploading.chunk-*'):
 q=x.lstat();assert stat.S_ISREG(q.st_mode) and q.st_uid==os.getuid()
 fragments.append({'name':x.name,'size':q.st_size,'mtime_ns':q.st_mtime_ns})
own_project_processes=[]
for d in Path('/proc').iterdir():
 if not d.name.isdigit() or int(d.name)==os.getpid():continue
 try:
  if d.stat().st_uid != os.getuid():continue
  args=(d/'cmdline').read_bytes().split(bytes([0])); rendered=b' '.join(args).decode(errors='replace')
  if any(b'arxiv-tssa' in arg or b'tssa_mvp' in arg for arg in args):
   # The read-only probe's shell ancestor embeds this source; exclude its identifiable marker.
   if 'own_project_processes=[]' in rendered:continue
   own_project_processes.append({'pid':int(d.name),'command':rendered[:220]})
 except (FileNotFoundError,PermissionError,ProcessLookupError):pass
print(json.dumps({'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'path':str(p),'size':s.st_size,'mtime_ns':s.st_mtime_ns,'sha256':h.hexdigest(),'owned':True,'fragments':fragments,'final_file_exists':final.exists(),'own_project_processes':own_project_processes}))
'''
now = datetime.datetime.now(datetime.timezone.utc)
report_path = OUT / f'openjourney_prefix_recheck_{now:%Y-%m-%d-%H%M%S-%fZ}.json'
log_path = report_path.with_suffix('.log')
report = {'started_at': now.isoformat(), 'status': 'running', 'kind': 'readonly_full_prefix_hash_after_failed_chunk',
          'no_GPU': True, 'no_remote_writes': True, 'timeout_seconds': 150, 'pid': os.getpid(),
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'report': str(report_path), 'log': str(log_path)}
start = time.monotonic()


def save():
    report['observed_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


save()
print(json.dumps({'status': 'running', 'pid': os.getpid(), 'report': str(report_path)}), flush=True)
try:
    with stage.LOCK_PATH.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with stage.SchoolSession() as session:
            report['route'] = session.config.read_text().split('HostName ', 1)[1].splitlines()[0]
            save()
            args = ['ssh', '-v', '-F', str(session.config), '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                    'school104', shlex.join(['python3', '-c', remote_code])]
            with log_path.open('x') as log:
                process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=log, text=True, start_new_session=True)
                try:
                    stdout, _ = process.communicate(timeout=150)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.communicate(timeout=5)
                    raise TimeoutError('Owned read-only SSH process group exceeded150seconds')
                report['returncode'] = process.returncode
                if process.returncode:
                    raise RuntimeError(f'SSH exited {process.returncode}')
            remote = json.loads(stdout)
            report['remote'] = remote
            assert not remote['own_project_processes'], 'Existing remote project processes require inspection'
            report['local_prefix_matches'] = stage.prefix_sha256(local, remote['size']) == remote['sha256']
            assert local.stat().st_size == ls.st_size and local.stat().st_mtime_ns == ls.st_mtime_ns
            if not report['local_prefix_matches']:
                raise ValueError('Remote full prefix differs from retained local source')
        report['status'] = 'complete'
except Exception as exc:
    report['status'] = 'failed'
    report['error'] = f'{type(exc).__name__}: {exc}'
finally:
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report['seconds'] = time.monotonic() - start
    if log_path.exists():
        report['stderr_tail'] = log_path.read_text(errors='replace')[-4000:]
        report['log_sha256'] = hashlib.sha256(log_path.read_bytes()).hexdigest()
    save()
print(json.dumps({k: report.get(k) for k in ['status', 'report', 'route', 'error', 'remote', 'local_prefix_matches', 'seconds']}), flush=True)
raise SystemExit(0 if report['status'] == 'complete' else 1)
