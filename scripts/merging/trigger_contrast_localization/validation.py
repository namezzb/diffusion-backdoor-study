#!/usr/bin/env python3
"""One bounded platform observation for the authorized semantic TCL validation.

Never regards an empty-process card as permission without full current policy,
account and sample evidence. Credentials remain in the local labgpu store.
"""
import argparse
import base64
import contextlib
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
LABGPU = ROOT / 'scripts/connection/labgpu.py'
RUN_ID = 'tcl-20261103-semantic-v1'
from semantic_science import DEADLINE_UTC
DEADLINE = datetime.fromisoformat(DEADLINE_UTC.replace('Z', '+00:00')).timestamp() if DEADLINE_UTC else None
PREFERENCE = ('104', '103', '101', '127')
STATE_DIR = Path.home() / '.config/labgpu/tcl-semantic'
DISKS = {'104': '/data2', '103': '/data1', '127': '/data1'}
PREPARED_SERVERS = ('104', '103')
_SSH_CONTEXTS = {}

REMOTE_STATUS_WRITER = r'''import hashlib,json,os,pathlib,socket,sqlite3,sys,tempfile
path=pathlib.Path(sys.argv[1]); payload=json.load(sys.stdin);value=payload['status']
if not path.is_absolute() or any(x.is_symlink() for x in (path,*path.parents)):
 raise ValueError('unsafe status path')
path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
def write(p,v):
 fd,tmp=tempfile.mkstemp(prefix='.status-',dir=p.parent)
 try:
  with os.fdopen(fd,'w') as f:
   os.fchmod(f.fileno(),0o600);json.dump(v,f,sort_keys=True,ensure_ascii=False,separators=(',',':'));f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
write(path,value)
if payload.get('evidence') is not None:
 raw=json.dumps(payload['capture'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
 digest=hashlib.sha256(raw).hexdigest();cap=path.parent/('platform-capture-'+digest+'.json')
 if not cap.exists():
  with cap.open('xb') as f: os.fchmod(f.fileno(),0o600);f.write(raw);f.flush();os.fsync(f.fileno())
 elif cap.is_symlink() or hashlib.sha256(cap.read_bytes()).hexdigest()!=digest: raise ValueError('unsafe capture')
 evidence=payload['evidence']
 if evidence.get('host')!=socket.gethostname(): raise ValueError('platform host does not match target')
 evidence['platform_host']=evidence['host']
 evidence['host']={'hostname':socket.gethostname(),'machine_id_sha256':hashlib.sha256(pathlib.Path('/etc/machine-id').read_bytes()).hexdigest(),'account_uid':os.geteuid()}
 evidence['raw_capture']={'path':str(cap),'sha256':digest}
 write(path.parent/'resource-evidence.json',evidence)
terminal=False
db=pathlib.Path(sys.argv[2])
if db.is_file() and not db.is_symlink():
 try:
  with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True,timeout=1) as con:
   terminal=con.execute("SELECT 1 FROM events WHERE kind='terminal' LIMIT 1").fetchone() is not None
 except sqlite3.Error: pass
print(json.dumps({'terminal':terminal}))
'''

REMOTE_PREPARE = r'''import base64,fcntl,hashlib,json,os,pathlib,shutil,subprocess,sys
data=json.load(sys.stdin);root=pathlib.Path('/data2/zhangzibo/arxiv-tssa')
old=root/'preparations/tcl-pilot24-v2-20261102'; source=old/'repository-recovery-v1'
source=pathlib.Path(data.get('source_repository',str(source)))
work=root/'preparations/tcl-20261103-semantic-v1'; repo=work/'repository'
if not source.is_dir(): raise ValueError('historical recovery source repository is missing')
work.mkdir(mode=0o700,parents=True,exist_ok=True)
launcher_lock=os.open(work/'launcher.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
try:fcntl.flock(launcher_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:raise ValueError('cannot update a running launcher')
writer_lock=None
database=root/'results/tcl-20261103-semantic-v1/run.sqlite'
if database.exists():
 lock=root/'results/tcl-20261103-semantic-v1/.writer.lock'
 writer_lock=os.open(lock,os.O_RDONLY|os.O_NOFOLLOW)
 try:fcntl.flock(writer_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError:raise ValueError('cannot update a running writer')
if not repo.exists():
 temp=work/'repository-copy-in-progress'
 if temp.exists(): raise ValueError('prior incomplete repository copy needs inspection')
 shutil.copytree(source,temp,symlinks=True)
 os.rename(temp,repo)
for name,item in data['files'].items():
 path=repo/name
 if not path.resolve().is_relative_to(repo.resolve()) or any(x.is_symlink() for x in (path,*path.parents) if x!=pathlib.Path('/')):
  raise ValueError('unsafe source destination '+name)
 raw=base64.b64decode(item['content'],validate=True)
 if hashlib.sha256(raw).hexdigest()!=item['sha256']: raise ValueError('transfer hash mismatch')
 path.parent.mkdir(parents=True,exist_ok=True)
 # Avoid silently changing scientific code under an existing spec/run.
 mutable={'scripts/merging/trigger_contrast_localization/'+n for n in ('runtime.py','runtime_store.py','runtime_tcl.py','runtime_assets.py')}
 bootstrap_auxiliary=(name=='scripts/merging/trigger_contrast_localization/pilot24_provenance.py' and not database.exists() and not path.exists())
 if (work/'spec.json').exists() and name not in mutable and not bootstrap_auxiliary and (not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']):
  raise ValueError('existing prepared spec has different code: '+name)
 if not path.exists() or path.read_bytes()!=raw:
  tmp=path.with_name(path.name+'.semantic-tmp')
  if tmp.exists() or tmp.is_symlink(): raise ValueError('unexpected temp file')
  tmp.write_bytes(raw);os.replace(tmp,path)
research=old/'repository/research';snap=old/'source-package-v2/snapshot'
t=research/'tasks/2026-10-29-trigger-contrast-localization'
inputs={'parent_manifest':str(t/'manifest_candidate.json'),'parent_review':str(t/'m06_review.json'),
 'prompts':str(t/'prompts_tokenized_candidate.jsonl'),'context_review':str(t/'context_review.json'),
 'plan':str(t/'pilot24_plan_candidate.json'),'context_ids':str(t/'pilot24_context_ids.json'),
 'selection':str(snap/'selection/selection.json'),'localization_ledger':str(snap/'localization.sqlite'),
 'localization_terminal':str(snap/'localization_terminal.json'),
 'protocol':str(research/'tssa_mvp_2026-10-26.json'),'asset_manifest':str(research/'tssa_mvp_assets_2026-10-26.json')}
if data.get('fixed_inputs') is not None:inputs=data['fixed_inputs']
missing=[k for k,p in inputs.items() if not pathlib.Path(p).is_file()]
if missing: raise ValueError('missing fixed inputs: '+','.join(missing))
def cpu_step(command,label,limit):
 out=work/('cpu-'+label+'-'+str(os.getpid())+'.stdout.log');err=out.with_suffix('.stderr.log')
 progress=work/'cpu-progress.json'
 def record(status):
  progress.write_text(json.dumps({'phase':label,'status':status,'stdout':str(out),'stderr':str(err),'pid':os.getpid()}));progress.chmod(0o600)
 record('running')
 env=dict(os.environ,CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
 try:
  with out.open('w') as stdout,err.open('w') as stderr:
   out.chmod(0o600);err.chmod(0o600)
   proc=subprocess.run(command,cwd=repo,env=env,stdout=stdout,stderr=stderr,text=True,timeout=limit)
 except BaseException:
  record('error');raise
 proc.stdout=out.read_text();proc.stderr=err.read_text();record('complete' if not proc.returncode else 'error')
 return proc
req={'run_id':'tcl-20261103-semantic-v1','run_root':str(root/'results/tcl-20261103-semantic-v1'),
 'repository_root':str(repo),'models_root':str(root/'models'),'inputs':inputs,'max_compute_seconds':21600,
 'study_protocol':str(repo/'research/tasks/2026-11-03-tcl-semantic/protocol.json'),
 'execution':{'resource_evidence':str(work/'observations/resource-evidence.json'),
 'resource_status_file':str(work/'observations/resource-status.json'),
 'require_fresh_resource_status':True}}
request=work/'request.json';spec=work/'spec.json'
if spec.exists():
 existing=json.loads(spec.read_text())
 if existing.get('run_id')!='tcl-20261103-semantic-v1': raise ValueError('unexpected existing spec identity')
 desired=req['execution'];execution=existing.setdefault('execution',{})
 if any(execution.get(k)!=v for k,v in desired.items()):
  if (root/'results/tcl-20261103-semantic-v1/run.sqlite').exists():
   raise ValueError('cannot rewrite execution paths after run creation')
  execution.update(desired)
  tmp=work/'spec-update.json'
  if tmp.exists() or tmp.is_symlink(): raise ValueError('unexpected spec temp file')
  tmp.write_text(json.dumps(existing));tmp.chmod(0o600);os.replace(tmp,spec)
if not spec.exists():
 request.write_text(json.dumps(req));request.chmod(0o600)
 cmd=[str(root/'venv/bin/python'),str(repo/'scripts/merging/trigger_contrast_localization/runtime.py')]
 proc=cpu_step(cmd+['prepare','--request',str(request),'--spec',str(spec)],'prepare',300)
 if proc.returncode: raise RuntimeError('CPU prepare failed: '+proc.stderr[-3000:])
cmd=[str(root/'venv/bin/python'),str(repo/'scripts/merging/trigger_contrast_localization/runtime.py')]
proc=cpu_step(cmd+['smoke','--spec',str(spec)],'smoke',120)
if proc.returncode: raise RuntimeError('Startup smoke failed: '+proc.stderr[-3000:])
s=json.loads(spec.read_text()); canonical=json.dumps({'run_id':s['run_id'],'science':s['science']},sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
names=['scripts/merging/trigger_contrast_localization/'+n for n in ('runtime.py','runtime_store.py','runtime_tcl.py','runtime_assets.py')]
execution_sha256={n:hashlib.sha256((repo/n).read_bytes()).hexdigest() for n in names}
print(json.dumps({'status':'runnable','spec':str(spec),'science_sha256':hashlib.sha256(canonical.encode()).hexdigest(),'execution_sha256':execution_sha256,'result':json.loads(proc.stdout)}))
'''

REMOTE_RUN = r'''import datetime,fcntl,hashlib,json,os,pathlib,sqlite3,subprocess,sys,time
data=json.load(sys.stdin);root=pathlib.Path('/data2/zhangzibo/arxiv-tssa')
work=root/'preparations/tcl-20261103-semantic-v1';repo=work/'repository';spec=work/'spec.json'
if not spec.is_file() or spec.is_symlink():raise ValueError('prepared spec missing')
launch_lock=os.open(work/'launcher.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
try:fcntl.flock(launch_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:print(json.dumps({'status':'running'}));sys.exit()
value=json.loads(spec.read_text());science=json.dumps({'run_id':value['run_id'],'science':value['science']},sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
if value['run_id']!='tcl-20261103-semantic-v1' or hashlib.sha256(science.encode()).hexdigest()!=data['science_sha256']:raise ValueError('science identity mismatch')
out=root/'results/tcl-20261103-semantic-v1';db=out/'run.sqlite'
if db.exists():
 with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True,timeout=2) as con:
  terminal=con.execute("SELECT detail FROM events WHERE kind='terminal' ORDER BY id DESC LIMIT 1").fetchone()
 if terminal:print(json.dumps({'status':'terminal','detail':json.loads(terminal[0])}));sys.exit()
 lock=os.open(out/'.writer.lock',os.O_RDONLY|os.O_NOFOLLOW)
 try:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print(json.dumps({'status':'running'}));sys.exit()
 finally:os.close(lock)
execution=value['execution'];uuid=data['uuid']
if execution.get('gpu_uuid') not in (None,uuid) and db.exists():raise ValueError('run bound to different GPU UUID')
if execution.get('require_fresh_resource_status') is not True:raise ValueError('fresh observer required')
if execution.get('resource_status_file')!=str(work/'observations/resource-status.json') or execution.get('resource_evidence')!=str(work/'observations/resource-evidence.json'):
 raise ValueError('unexpected resource paths')
status=json.loads((work/'observations/resource-status.json').read_text());evidence=json.loads((work/'observations/resource-evidence.json').read_text())
now=datetime.datetime.now(datetime.timezone.utc)
observed=datetime.datetime.fromisoformat(status['observed_at_utc'].replace('Z','+00:00'))
expires=datetime.datetime.fromisoformat(evidence['expires_at_utc'].replace('Z','+00:00'))
if (status.get('observation_valid') is not True or status.get('disabled') is not False or status.get('stop_required') is not False
 or status.get('gpu_uuid')!=uuid or evidence.get('gpu_uuid')!=uuid or status.get('run_id')!=value['run_id']
 or status.get('science_sha256')!=data['science_sha256'] or evidence.get('science_sha256')!=data['science_sha256']
 or not 0<=(now-observed).total_seconds()<=180 or not now<expires):raise ValueError('fresh observer is not ready')
execution['gpu_uuid']=uuid
tmp=work/'spec-launch.json'
if tmp.exists() or tmp.is_symlink():raise ValueError('unexpected spec temp file')
tmp.write_text(json.dumps(value));tmp.chmod(0o600);os.replace(tmp,spec)
log=open(work/'session.log','a',buffering=1)
cmd=[str(root/'venv/bin/python'),str(repo/'scripts/merging/trigger_contrast_localization/runtime.py'),'run','--spec',str(spec)]
worker='import subprocess,sys;sys.exit(subprocess.call(sys.argv[2:]))'
process=subprocess.Popen([str(root/'venv/bin/python'),'-c',worker,str(launch_lock),*cmd],cwd=repo,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,pass_fds=(launch_lock,),env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1'))
os.close(launch_lock)
time.sleep(1)
print(json.dumps({'status':'spawned' if process.poll() is None else 'exited_early','pid':process.pid,'returncode':process.poll()}))
'''

REMOTE_STATE = r'''import fcntl,json,os,pathlib,sqlite3,sys
base=pathlib.Path('/data2/zhangzibo/arxiv-tssa');work=base/'preparations/tcl-20261103-semantic-v1'
lock=work/'launcher.lock';active=False
if lock.exists():
 fd=os.open(lock,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:active=True
 finally:os.close(fd)
root=base/'results/tcl-20261103-semantic-v1';db=root/'run.sqlite'
if not db.exists():print(json.dumps({'status':'running' if active else 'not_started'}));sys.exit()
if db.is_symlink():raise ValueError('unsafe database')
with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True,timeout=3) as con:
 terminal=con.execute("SELECT detail FROM events WHERE kind='terminal' ORDER BY id DESC LIMIT 1").fetchone()
 counts=dict(con.execute('SELECT status,COUNT(*) FROM units GROUP BY status'))
 attempts=con.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
 gates=[json.loads(row[0]) for row in con.execute("SELECT detail FROM events WHERE kind='stage_gate' ORDER BY id")]
 latest=con.execute('SELECT time,kind,detail FROM events ORDER BY id DESC LIMIT 1').fetchone()
if terminal:print(json.dumps({'status':'terminal','detail':json.loads(terminal[0]),'units':counts,'attempts':attempts,'stage_gates':gates}));sys.exit()
if active:print(json.dumps({'status':'running','units':counts,'attempts':attempts,'stage_gates':gates,'latest_event':latest[1] if latest else None}));sys.exit()
lock=os.open(root/'.writer.lock',os.O_RDONLY|os.O_NOFOLLOW)
try:
 try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);state='paused'
 except BlockingIOError:state='running'
finally:os.close(lock)
print(json.dumps({'status':state,'units':counts,'attempts':attempts,'stage_gates':gates,'latest_event':latest[1] if latest else None}))
'''


class NotReady(Exception):
    pass


def fresh_snapshot(timeout=35):
    try:
        result = subprocess.run([sys.executable, str(LABGPU), 'status', '--fresh', '--json', '--timeout', str(timeout)],
                                capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise NotReady('平台查询超时') from exc
    try:
        value = json.loads(result.stdout)
    except ValueError as exc:
        raise NotReady('平台响应不是有效 JSON') from exc
    if result.returncode or value.get('cache_state') not in ('fresh', 'cached'):
        raise NotReady('平台实时查询失败或缓存不可用')
    return value


def evaluate(snapshot, now=None, target_uuid=None):
    now = time.time() if now is None else now
    if DEADLINE is not None and now >= DEADLINE:
        raise NotReady('已到计算截止时间')
    if snapshot.get('source') != 'https://gpu.orz2333.fun' or snapshot.get('cache_state') not in ('fresh', 'cached'):
        raise NotReady('平台来源或新鲜度无效')
    fetched = snapshot.get('fetched_at')
    if type(fetched) not in (int, float) or not math.isfinite(fetched) or not 0 <= now - fetched <= 30:
        raise NotReady('平台快照过期')
    account, policy = snapshot.get('account'), snapshot.get('policy')
    if not isinstance(account, dict) or not isinstance(policy, dict):
        raise NotReady('平台账号或规则未知')
    if not isinstance(account.get('username'), str) or not account['username']:
        raise NotReady('平台账号身份未知')
    if account.get('registered') is not True or account.get('active_ban') is not None:
        raise NotReady('账号未登记或存在有效禁用')
    rules, requests, maintenance = policy.get('rules'), policy.get('gpu_requests'), policy.get('maintenance')
    if not isinstance(rules, dict) or type(rules.get('gpu_management_enabled')) is not bool:
        raise NotReady('平台GPU规则未知')
    if not isinstance(requests, list) or not isinstance(maintenance, list):
        raise NotReady('平台分配或维护信息未知')
    # Any nonterminal request needs an explicit supported schema before this
    # entrypoint can establish absence of a pending allocation conflict.
    if any(not isinstance(item, dict) or item.get('status') not in
           ('rejected', 'cancelled', 'canceled', 'expired', 'completed', 'closed') for item in requests):
        raise NotReady('存在未解析的 GPU 分配记录，无法排除冲突')
    usage = account.get('usage')
    if not isinstance(usage, dict):
        raise NotReady('账号 GPU 使用量未知')
    occupied, limit = usage.get('count'), usage.get('limit', account.get('limit'))
    if type(occupied) is not int or occupied < 0 or type(limit) is not int or limit < 1:
        raise NotReady('账号占用或额度未知')
    cap = min(4, limit)
    if occupied >= cap:
        raise NotReady('账号当前占用已达有效上限')
    hosts = snapshot.get('hosts')
    if not isinstance(hosts, list):
        raise NotReady('服务器列表未知')
    for server in PREFERENCE:
        candidates = [h for h in hosts if isinstance(h, dict) and str(h.get('label')) == server]
        if len(candidates) != 1:
            continue
        host = candidates[0]
        for gpu in host.get('gpus', []):
            if (gpu.get('status') == 'free' and (target_uuid is None or gpu.get('uuid') == target_uuid) and isinstance(gpu.get('uuid'), str)
                    and re.fullmatch(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', gpu['uuid'])):
                return {'server': server, 'host': host.get('id'), 'uuid': gpu['uuid'],
                        'effective_gpu_cap': cap, 'occupied_including_this_gpu': occupied + 1,
                        'gpu_sample_age_seconds': gpu.get('sample_age_seconds'),
                        'process_sample_age_seconds': host.get('process_sample_age_seconds')}
    raise NotReady('没有满足实时采样条件的空闲候选')


def monitor_observation(snapshot, identity, now=None):
    now = time.time() if now is None else now
    result = {'run_id': RUN_ID, 'science_sha256': identity['science_sha256'], 'gpu_uuid': identity['uuid'],
              'observed_at_utc': datetime.fromtimestamp(now, timezone.utc).isoformat(),
              'observation_valid': False, 'disabled': False, 'stop_required': False}
    fetched = snapshot.get('fetched_at')
    if (snapshot.get('source') != 'https://gpu.orz2333.fun' or snapshot.get('cache_state') not in ('fresh', 'cached')
            or type(fetched) not in (int, float) or not math.isfinite(fetched) or not 0 <= now - fetched <= 30):
        return result
    account = snapshot.get('account')
    if not isinstance(account, dict) or 'active_ban' not in account:
        return result
    if account.get('username') != identity.get('username'):
        return result
    if account['active_ban'] is not None:
        result.update(observation_valid=True, stop_required=True)
        return result
    hosts = [h for h in snapshot.get('hosts', []) if isinstance(h, dict) and h.get('id') == identity['host']]
    if len(hosts) != 1:
        return result
    host = hosts[0]
    gpus = [g for g in host.get('gpus', []) if isinstance(g, dict) and g.get('uuid') == identity['uuid']]
    if len(gpus) != 1:
        return result
    gpu = gpus[0]
    if gpu.get('status') == 'disabled':
        result.update(observation_valid=True, disabled=True)
    elif (host.get('online') is True and gpu.get('status') in ('free', 'mine', 'others', 'shared')
          and type(gpu.get('sample_age_seconds')) in (int, float)
          and 0 <= gpu['sample_age_seconds'] <= 120):
        # Other users joining an already legitimate run is not a stop command.
        result['observation_valid'] = True
    return result


def startup_evidence(snapshot, identity, now=None):
    now = time.time() if now is None else now
    try:
        candidate = evaluate(snapshot, now, target_uuid=identity['uuid'])
    except NotReady:
        return None
    if snapshot.get('account', {}).get('username') != identity.get('username'):
        return None
    if candidate['host'] != identity['host'] or candidate['server'] != identity['server']:
        return None
    ages = (candidate['gpu_sample_age_seconds'], candidate['process_sample_age_seconds'])
    if any(type(age) not in (int, float) or not math.isfinite(age) or not 0 <= age < 120 for age in ages):
        return None
    ttl = min(120 - age for age in ages) - max(0, now - snapshot['fetched_at']) - 2
    if ttl <= 0:
        return None
    observed = datetime.fromtimestamp(now, timezone.utc)
    return {'run_id': RUN_ID, 'science_sha256': identity['science_sha256'], 'gpu_uuid': identity['uuid'],
            'host': identity['host'], 'source': 'https://gpu.orz2333.fun/',
            'observed_at_utc': observed.isoformat(), 'expires_at_utc': (observed + timedelta(seconds=ttl)).isoformat(),
            'disabled': False, 'sampling_valid': True, 'allocation_conflict': False,
            'effective_gpu_cap': candidate['effective_gpu_cap'],
            'occupied_including_this_gpu': candidate['occupied_including_this_gpu']}


def load_manifest(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise NotReady('运行清单缺失或权限不安全')
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise NotReady('运行清单不可读') from exc
    server = value.get('server')
    uuid, science_hash = value.get('uuid'), value.get('science_sha256')
    if (value.get('run_id') != RUN_ID or server not in DISKS or value.get('host') != 'iipl-' + server
            or not isinstance(uuid, str) or not re.fullmatch(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', uuid)
            or not isinstance(science_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', science_hash)
            or not isinstance(value.get('username'), str) or not value['username']):
        raise NotReady('运行清单身份无效')
    root = f"{DISKS[server]}/zhangzibo/arxiv-tssa"
    if value.get('remote_status') != root + f'/preparations/{RUN_ID}/observations/resource-status.json':
        raise NotReady('运行清单远端状态路径无效')
    return value


def bounded_ssh(config, server, command, data, timeout=75):
    aliases = _SSH_CONTEXTS.get(str(config))
    if aliases is not None:
        aliases.add('school' + server)
    # A ControlPersist master can inherit output descriptors after the command
    # client exits. Regular files avoid waiting for a background master's EOF.
    with tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as stdout, \
            tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as stderr:
        os.fchmod(stdout.fileno(), 0o600)
        os.fchmod(stderr.fileno(), 0o600)
        process = subprocess.Popen(['ssh', '-F', str(config), 'school' + server, command],
                                   stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                   text=True, start_new_session=True)
        try:
            process.communicate(data, timeout=timeout)
        except subprocess.TimeoutExpired:
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.communicate()
            raise NotReady('远端命令执行超时；应检查阶段日志和进程，连接成功不等于命令已完成')
        stdout.seek(0);stderr.seek(0)
        output, error = stdout.read(), stderr.read()
    if process.returncode:
        raise NotReady('远端命令失败: ' + error[-2500:])
    return output


@contextlib.contextmanager
def ssh_config():
    sys.path.insert(0, str(ROOT / 'server'))
    from stage_school_assets import gateway_address
    gateway = gateway_address(prefer_public_dns=True)
    with tempfile.TemporaryDirectory(prefix='tcl-watch-', dir='/private/tmp') as folder:
        Path(folder).chmod(0o700)
        config = Path(folder) / 'ssh_config'
        config.write_text(f'Host school-jump\n    HostName {gateway}\nHost *\n    BatchMode yes\n'
                          f'    StrictHostKeyChecking yes\n    ConnectTimeout 60\n    ControlMaster auto\n'
                          f'    ServerAliveInterval 15\n    ServerAliveCountMax 2\n'
                          f'    ControlPersist 120\n    ControlPath {folder}/cm-%C\n'
                          f'    Include "{ROOT / "server/school_ssh_config"}"\n')
        config.chmod(0o600)
        _SSH_CONTEXTS[str(config)] = set()
        try:
            yield config
        finally:
            aliases = _SSH_CONTEXTS.pop(str(config))
            # -O exit only addresses this private context's control sockets;
            # it never creates a connection or touches another task's master.
            if aliases:
                for alias in sorted(aliases) + ['school-jump']:
                    try:
                        subprocess.run(['ssh', '-F', str(config), '-O', 'exit', alias],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, timeout=3)
                    except (OSError, subprocess.SubprocessError):
                        pass


def execution_sha256():
    prefix = 'scripts/merging/trigger_contrast_localization/'
    names = [prefix + n for n in ('runtime.py', 'runtime_store.py', 'runtime_tcl.py', 'runtime_assets.py')]
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def remote_script(script, server):
    if server not in PREPARED_SERVERS:
        raise NotReady('此节点尚未核验部署路径')
    return script.replace("pathlib.Path('/data2/zhangzibo/arxiv-tssa')",
                          f"pathlib.Path('{DISKS[server]}/zhangzibo/arxiv-tssa')")


def prepare(server):
    if server not in PREPARED_SERVERS:
        raise NotReady('此节点尚未核验本人数据目录和固定输入')
    prefix = 'scripts/merging/trigger_contrast_localization/'
    names = [prefix + n for n in ('runtime.py', 'runtime_store.py', 'runtime_tcl.py', 'runtime_assets.py', 'overnight_science.py', 'semantic_science.py', 'semantic_scoring.py')]
    names.append('research/tasks/2026-11-03-tcl-semantic/protocol.json')
    payload = {}
    if server == '103':
        # Read only the audited historical input snapshot. Never copy its run
        # database into the new run, and never write into the frozen snapshot.
        root = '/data1/zhangzibo/arxiv-tssa'
        snapshot = root + '/preparations/tcl104-shard-snapshot-20261030T0200Z'
        source = snapshot + '/code'
        repo = root + '/preparations/' + RUN_ID + '/repository'
        task = source + '/research/tasks/2026-10-29-trigger-contrast-localization'
        local_task = 'research/tasks/2026-10-29-trigger-contrast-localization/'
        additions = [local_task + n for n in ('pilot24_plan_candidate.json', 'pilot24_context_ids.json')]
        additions += ['research/tssa_mvp_2026-10-26.json', 'research/tssa_mvp_assets_2026-10-26.json']
        names += additions
        names += [prefix + n + '.py' for n in ('pilot24_inputs', 'pilot24_statistics', 'pilot24_runtime', 'pilot24_worker_ledger', 'pilot24_provenance')]
        payload = {'source_repository': source, 'fixed_inputs': {
            'parent_manifest': task + '/manifest_candidate.json', 'parent_review': task + '/m06_review.json',
            'prompts': task + '/prompts_tokenized_candidate.jsonl', 'context_review': task + '/context_review.json',
            'selection': snapshot + '/run/selection/selection.json',
            'localization_ledger': snapshot + '/run/localization.sqlite',
            'localization_terminal': snapshot + '/run/localization_terminal.json',
            'plan': repo + '/' + additions[0], 'context_ids': repo + '/' + additions[1],
            'protocol': repo + '/research/tssa_mvp_2026-10-26.json',
            'asset_manifest': repo + '/research/tssa_mvp_assets_2026-10-26.json'}}
    files = {}
    for name in names:
        raw = (ROOT / name).read_bytes()
        files[name] = {'content': base64.b64encode(raw).decode(), 'sha256': hashlib.sha256(raw).hexdigest()}
    payload['files'] = files
    with ssh_config() as config:
        result = bounded_ssh(config, server, shlex.join(['python3', '-u', '-c', remote_script(REMOTE_PREPARE, server)]), json.dumps(payload), timeout=1230)
    try:
        value = json.loads(result)
        if value.get('execution_sha256') != execution_sha256():
            raise NotReady('远端运行代码哈希与本地不一致')
        return value
    except ValueError as exc:
        raise NotReady('远端CPU准备未返回有效结果') from exc


def state_dir():
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if STATE_DIR.is_symlink() or STATE_DIR.stat().st_uid != os.getuid() or STATE_DIR.stat().st_mode & 0o077:
        raise NotReady('本地运行目录权限不安全')


def save_private(path, value):
    state_dir()
    if path.is_symlink():
        raise NotReady('本地运行文件不能是符号链接')
    fd, temp = tempfile.mkstemp(prefix='.state-', dir=STATE_DIR)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def observer_config(identity):
    """Borrow only the live same-run observer's private SSH context."""
    try:
        if (STATE_DIR.is_symlink() or STATE_DIR.stat().st_uid != os.getuid()
                or STATE_DIR.stat().st_mode & 0o777 != 0o700):
            return None
        path = STATE_DIR / 'observer-ready.json'
        if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o777 != 0o600:
            return None
        ready = json.loads(path.read_text())
        if (ready.get('run_id') != RUN_ID or ready.get('uuid') != identity['uuid']
                or ready.get('science_sha256') != identity['science_sha256']
                or ready.get('server') != identity['server'] or not 0 <= time.time() - ready['time'] <= 150):
            return None
        info = subprocess.run(['ps', '-p', str(ready['pid']), '-o', 'uid=', '-o', 'command='],
                              capture_output=True, text=True, timeout=3).stdout.strip()
        if (not info.startswith(str(os.getuid()) + ' ') or str(Path(__file__).resolve()) not in info
                or ' watch ' not in info or str(STATE_DIR / 'manifest.json') not in info):
            return None
        config = Path(ready['ssh_config'])
        folder = config.parent
        if (config.name != 'ssh_config' or folder.parent != Path('/private/tmp')
                or not folder.name.startswith('tcl-watch-') or config.resolve() != config
                or folder.is_symlink() or folder.stat().st_uid != os.getuid()
                or folder.stat().st_mode & 0o777 != 0o700
                or not config.is_file() or config.stat().st_uid != os.getuid()
                or config.stat().st_mode & 0o777 != 0o600):
            return None
        return config
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None


@contextlib.contextmanager
def run_ssh_config(identity):
    config = observer_config(identity)
    if config is not None:
        yield config  # Borrowers never close the owning observer's master.
    else:
        with ssh_config() as config:
            yield config


def remote_state(identity):
    server = identity['server']
    with run_ssh_config(identity) as config:
        return json.loads(bounded_ssh(config, server, shlex.join(['python3', '-c', remote_script(REMOTE_STATE, server)]), '', timeout=75))


def observer_alive(identity):
    try:
        ready = json.loads((STATE_DIR / 'observer-ready.json').read_text())
        if (ready.get('run_id') != RUN_ID or ready.get('uuid') != identity['uuid']
                or not 0 <= time.time() - ready['time'] <= 150):
            return False
        os.kill(ready['pid'], 0)
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def spawn_observer():
    log_fd = os.open(STATE_DIR / 'observer.log', os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(log_fd, 'a') as log:
        return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'watch', '--manifest', str(STATE_DIR / 'manifest.json')],
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)


def stop_observer_for_rebind(identity):
    lock_path = STATE_DIR / 'observer.lock'
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            pass
        try:
            ready = json.loads((STATE_DIR / 'observer-ready.json').read_text())
            pid = ready['pid']
            info = subprocess.run(['ps', '-p', str(pid), '-o', 'uid=', '-o', 'command='], capture_output=True, text=True, timeout=3)
            output = info.stdout.strip()
            if (ready.get('uuid') != identity['uuid'] or not output.startswith(str(os.getuid()) + ' ')
                    or str(Path(__file__).resolve()) not in output or ' watch ' not in output):
                raise ValueError('observer identity cannot be verified')
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
            raise NotReady('无法验证并停止旧观察器，不能重选候选卡') from exc
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                time.sleep(.1)
        raise NotReady('旧观察器仍在退出，稍后重试')
    finally:
        os.close(fd)


def start_or_resume(identity):
    ready_path = STATE_DIR / 'observer-ready.json'
    # Reusing the same observer is safe; a second process exits on its lock.
    observer = spawn_observer()
    deadline = time.monotonic() + 185
    while time.monotonic() < deadline:
        try:
            ready = json.loads(ready_path.read_text())
            if (ready.get('run_id') == RUN_ID and ready.get('uuid') == identity['uuid']
                    and ready.get('startup_evidence') is True and 0 <= time.time() - ready['time'] < 50):
                os.kill(ready['pid'], 0)
                break
        except (OSError, ValueError, TypeError, KeyError):
            pass
        time.sleep(1)
    else:
        if observer.poll() is None:
            observer.terminate()
        raise NotReady('观察器未能及时提供可用启动证据')
    try:
        with run_ssh_config(identity) as config:
            result = bounded_ssh(config, identity['server'], shlex.join(['python3', '-c', remote_script(REMOTE_RUN, identity['server'])]),
                                 json.dumps({'uuid': identity['uuid'], 'science_sha256': identity['science_sha256'],
                                             'execution_sha256': execution_sha256()}), timeout=75)
        response = json.loads(result)
    except Exception:
        # A lost launch response may hide a running worker. Keep the observer alive;
        # the next tick checks the remote writer lock before any resume.
        raise
    if response.get('status') in ('terminal', 'exited_early') and observer.poll() is None:
        observer.terminate()
    return response


def tick():
    state_dir()
    fd = os.open(STATE_DIR / 'controller.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise NotReady('另一个运行负责人正在检查') from exc
        manifest_path = STATE_DIR / 'manifest.json'
        identity = load_manifest(manifest_path) if manifest_path.exists() else None
        state = None
        if identity:
            state = remote_state(identity)
            if state['status'] == 'running':
                if not observer_alive(identity):
                    spawn_observer()
                    state['observer_restart_requested'] = True
                return state
            if state['status'] == 'terminal':
                return state
        snapshot = fresh_snapshot()
        if identity and state['status'] == 'paused':
            try:
                candidate = evaluate(snapshot, target_uuid=identity['uuid'])
            except NotReady:
                try:
                    alternate = evaluate(snapshot)
                except NotReady:
                    raise NotReady('已有运行已暂停，绑定卡尚不可用；需保留现有账本等待恢复')
                return {'status': 'run_rebind_required', 'run_id': RUN_ID, 'server': identity['server'],
                        'uuid': identity['uuid'], 'alternative': alternate}
        else:
            candidate = evaluate(snapshot)
        if identity and state['status'] == 'not_started' and candidate['uuid'] != identity['uuid']:
            stop_observer_for_rebind(identity)
            identity = None
        if identity and (candidate['host'] != identity['host'] or snapshot['account']['username'] != identity['username']):
            raise NotReady('当前候选或账号与既有运行身份不一致')
        server = candidate['server']
        if server not in PREPARED_SERVERS:
            return {'status': 'node_preparation_required', 'run_id': RUN_ID,
                    'server': candidate['server'], 'host': candidate['host'], 'uuid': candidate['uuid']}
        prepared_path = STATE_DIR / f'prepared-{server}.json'
        prepared = json.loads(prepared_path.read_text()) if prepared_path.exists() else {}
        if prepared.get('execution_sha256') != execution_sha256():
            original_science = identity['science_sha256'] if identity else prepared.get('science_sha256')
            prepared = prepare(server)
            if original_science and prepared.get('science_sha256') != original_science:
                raise NotReady('更新后的科学身份与既有运行不一致')
            save_private(prepared_path, prepared)
        if not identity:
            identity = {'run_id': RUN_ID, 'server': server, 'host': candidate['host'], 'uuid': candidate['uuid'],
                        'science_sha256': prepared['science_sha256'], 'username': snapshot['account']['username'],
                        'remote_status': f"{DISKS[server]}/zhangzibo/arxiv-tssa/preparations/{RUN_ID}/observations/resource-status.json"}
            save_private(manifest_path, identity)
        return start_or_resume(identity)
    finally:
        os.close(fd)


def watch(path):
    identity = load_manifest(path)
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if STATE_DIR.is_symlink() or STATE_DIR.stat().st_uid != os.getuid() or STATE_DIR.stat().st_mode & 0o077:
        raise NotReady('本地观察器目录权限不安全')
    lock = os.open(STATE_DIR / 'observer.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(lock)
        raise NotReady('已有本地观察器') from exc
    try:
        with ssh_config() as config:
            db = f"{DISKS[identity['server']]}/zhangzibo/arxiv-tssa/results/{RUN_ID}/run.sqlite"
            command = shlex.join(['python3', '-c', REMOTE_STATUS_WRITER, identity['remote_status'], db])
            while DEADLINE is None or time.time() < DEADLINE:
                started = time.monotonic()
                try:
                    snapshot = fresh_snapshot()
                    status = monitor_observation(snapshot, identity)
                    evidence = startup_evidence(snapshot, identity)
                except Exception as exc:
                    print(json.dumps({'time': time.time(), 'phase': 'platform_observation', 'error': str(exc)[:2000]}),
                          file=sys.stderr, flush=True)
                    snapshot, evidence = None, None
                    status = {'run_id': RUN_ID, 'science_sha256': identity['science_sha256'], 'gpu_uuid': identity['uuid'],
                              'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'observation_valid': False,
                              'disabled': False, 'stop_required': False}
                try:
                    output = bounded_ssh(config, identity['server'], command,
                                         json.dumps({'status': status, 'evidence': evidence, 'capture': snapshot}))
                    ready = {'run_id': RUN_ID, 'uuid': identity['uuid'], 'pid': os.getpid(),
                             'science_sha256': identity['science_sha256'], 'server': identity['server'],
                             'ssh_config': str(config),
                             'time': time.time(), 'startup_evidence': evidence is not None}
                    fd, temp = tempfile.mkstemp(prefix='.observer-', dir=STATE_DIR)
                    try:
                        with os.fdopen(fd, 'w') as stream:
                            json.dump(ready, stream)
                        os.replace(temp, STATE_DIR / 'observer-ready.json')
                    finally:
                        if os.path.exists(temp): os.unlink(temp)
                    if json.loads(output).get('terminal'):
                        break
                except (NotReady, OSError, ValueError) as exc:
                    print(json.dumps({'time': time.time(), 'phase': 'remote_status_write', 'error': str(exc)[:2000]}),
                          file=sys.stderr, flush=True)
                    # Remote freshness expires and the runner pauses.
                time.sleep(max(0, 60 - (time.monotonic() - started)))
    finally:
        os.close(lock)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['observe', 'watch', 'prepare', 'tick', 'report'])
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument('--manifest')
    parser.add_argument('--server', default='104')
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error('timeout must be positive')
    try:
        if args.command == 'watch':
            if not args.manifest:
                raise NotReady('观察器缺少运行清单')
            watch(args.manifest)
            return 0
        if args.command == 'prepare':
            result = prepare(args.server)
            save_private(STATE_DIR / f'prepared-{args.server}.json', result)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == 'tick':
            print(json.dumps(tick(), ensure_ascii=False))
            return 0
        if args.command == 'report':
            state_dir()
            path = STATE_DIR / 'manifest.json'
            result = remote_state(load_manifest(path)) if path.exists() else {'status': 'not_started'}
            print(json.dumps(result, ensure_ascii=False))
            return 0
        snapshot = fresh_snapshot(args.timeout)
        candidate = evaluate(snapshot)
    except (NotReady, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'waiting', 'run_id': RUN_ID, 'reason': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({'status': 'candidate', 'run_id': RUN_ID, 'candidate': candidate,
                      'launch_authorized': False}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
