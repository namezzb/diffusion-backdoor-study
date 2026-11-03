#!/usr/bin/env python3
"""Explicit post-experiment GPU retention, with short renewable leases.

No scientific database is written. Only the verified source node is supported;
this is a fresh acquisition after experiment exit, not an atomic reservation.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import queue
import threading
import shlex
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/merging/trigger_contrast_localization'))
import validation as transport

RUN = 'tcl-20261103-semantic-v1'
NODES = {'104': '/data2/zhangzibo/arxiv-tssa', '103': '/data1/zhangzibo/arxiv-tssa'}
UUID = re.compile(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
WORKER = Path(__file__).with_name('gpu_hold_worker.py')
STATE = Path.home() / '.config/labgpu/gpu-hold'
MAX_LEASE_AGE = 90
PLATFORM_TIMEOUT = 35


class NotReady(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def private_dir(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise NotReady('unsafe private directory')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise NotReady('private directory must be owned by this user with mode 0700')
    return path


def read_private(path):
    path = Path(path)
    if (not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents))
            or not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077):
        raise NotReady('unsafe private file')
    return json.loads(path.read_text())


def write_private(path, value):
    path = Path(path)
    private_dir(path.parent)
    if path.is_symlink():
        raise NotReady('unsafe private output')
    fd, temp = tempfile.mkstemp(prefix='.hold-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def audit(state, event, **fields):
    fd = os.open(state / 'events.jsonl', os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as stream:
        stream.write(canonical({'time': time.time(), 'event': event, **fields}) + '\n')
        stream.flush(); os.fsync(stream.fileno())


def validate_config(config, *, require_report=True):
    if not isinstance(config, dict) or config.get('schema') != 'gpu-hold-controller-v1':
        raise NotReady('explicit gpu-hold-controller-v1 configuration required')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,31}', str(config.get('hold_id', ''))):
        raise NotReady('invalid hold identity')
    source = config.get('source', {})
    if (source.get('run_id') != RUN or source.get('server') not in NODES
            or not SHA.fullmatch(str(source.get('science_sha256', '')))):
        raise NotReady('verified source node and scientific hash required')
    auth = config.get('authorization', {})
    if (auth.get('enabled') is not True or auth.get('until_user_stop') is not True
            or auth.get('platform_allows_hold') is not True or auth.get('purpose') != 'transparent_gpu_retention'
            or not isinstance(auth.get('username'), str) or not auth['username']
            or not SHA.fullmatch(str(auth.get('reviewed_policy_sha256', '')))):
        raise NotReady('explicit user authorization and reviewed platform permission required')
    for field in ('compute_target_percent', 'memory_target_percent'):
        value = auth.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not 60 < value <= 90:
            raise NotReady('explicit compute and memory targets must exceed 60 and be at most 90 percent')
    if type(auth.get('max_cards')) is not int or not 1 <= auth['max_cards'] <= 2:
        raise NotReady('maximum one or two hold cards must be explicit')
    if not require_report:
        return config
    report = config.get('completion_report', {})
    path = Path(report.get('path', ''))
    if not path.is_absolute() or not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise NotReady('a real completed-experiment report is required')
    completed = json.loads(path.read_text())
    if (completed.get('run_id') != RUN or completed.get('science_sha256') != source['science_sha256']
            or completed.get('status') != 'terminal' or completed.get('completed_images') != 1024
            or completed.get('stages_completed') != ['S0', 'S1', 'M0', 'M1']):
        raise NotReady('completion report must attest this full run and scientific hash')
    return config


def policy_hash(snapshot):
    policy = snapshot.get('_hold_raw_policy', snapshot.get('policy', {}))
    # Retained as an audit fingerprint; permission uses current structured fields.
    return digest({k: policy.get(k) for k in ('rules', 'rectifications', 'cases')})


def fresh_snapshot(timeout=PLATFORM_TIMEOUT):
    # Tight outer bound: API stalls must not queue arbitrarily late renewals.
    result = subprocess.run([sys.executable, str(transport.LABGPU), 'status', '--fresh', '--json', '--timeout', str(timeout)],
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise NotReady('platform refresh failed; leases will expire')
    value = json.loads(result.stdout)
    # Display normalization tolerates absent maintenance; permission cannot.
    import labgpu
    cached = read_private(labgpu.CONFIG / 'status.json')
    if cached.get('base_url') != labgpu.BASE or cached.get('fetched_at') != value.get('fetched_at'):
        raise NotReady('raw platform capture changed during verification')
    raw = cached.get('payload', {})
    if (not isinstance(raw.get('rules'), dict) or any(not isinstance(raw.get(k), list)
            for k in ('maintenance', 'gpu_requests', 'rectifications', 'cases'))):
        raise NotReady('raw platform rule/allocation/notice fields are missing or malformed')
    value['_hold_raw_policy'] = {k: raw[k] for k in ('rules', 'maintenance', 'gpu_requests', 'rectifications', 'cases')}
    value['_hold_policy_complete'] = True
    return value


def platform(snapshot, config, active=(), now=None):
    """Conservative policy/quantity check; running co-users alone do not revoke."""
    now = time.time() if now is None else now
    fetched = snapshot.get('fetched_at')
    if (snapshot.get('source') != 'https://gpu.orz2333.fun' or snapshot.get('cache_state') not in ('fresh', 'cached')
            or type(fetched) not in (int, float) or not math.isfinite(fetched) or not 0 <= now - fetched <= 15):
        raise NotReady('platform snapshot is stale or untrusted')
    auth, account, policy = config['authorization'], snapshot.get('account', {}), snapshot.get('policy', {})
    if (account.get('username') != auth['username'] or account.get('registered') is not True
            or 'active_ban' not in account or account['active_ban'] is not None):
        raise NotReady('account permission missing or revoked')
    if (snapshot.get('_hold_policy_complete') is not True or not isinstance(policy.get('rules'), dict)
            or type(policy['rules'].get('gpu_management_enabled')) is not bool
            or any(not isinstance(policy.get(k), list) for k in ('rectifications', 'cases'))):
        raise NotReady('platform rules or case notices unavailable')
    for notice in policy['rectifications'] + policy['cases']:
        if not isinstance(notice, dict):
            raise NotReady('platform notice has an unknown structure')
        if (notice.get('stop_required') is True and notice.get('status') not in
                ('rejected', 'cancelled', 'canceled', 'expired', 'completed', 'closed', 'resolved')):
            raise NotReady('platform notice explicitly requires stopping')
    requests = policy.get('gpu_requests')
    if (not isinstance(requests, list) or not isinstance(policy.get('maintenance'), list)
            or any(not isinstance(r, dict) or r.get('status') not in
                   ('rejected', 'cancelled', 'canceled', 'expired', 'completed', 'closed') for r in requests)):
        raise NotReady('allocation or maintenance permissions cannot be established')
    usage = account.get('usage', {})
    occupied, cap = usage.get('count'), usage.get('limit', account.get('limit'))
    if type(occupied) is not int or occupied < 0 or type(cap) is not int or cap < 1:
        raise NotReady('GPU quota unknown')
    cap = min(cap, 4)
    if occupied > cap or len(active) > auth['max_cards']:
        raise NotReady('effective GPU quota exceeded')
    server = config['source']['server']
    hosts = [h for h in snapshot.get('hosts', []) if h.get('id') == 'iipl-' + server and str(h.get('label')) == server]
    if len(hosts) != 1:
        raise NotReady('source node not present; cross-node holding is not implemented')
    host = hosts[0]
    if (host.get('online') is not True or host.get('processes_complete') is not True
            or host.get('process_state_complete') is not True):
        raise NotReady('host or process sampling is incomplete')
    proc_age = host.get('process_sample_age_seconds')
    if type(proc_age) not in (int, float) or not math.isfinite(proc_age):
        raise NotReady('process sample age unavailable')
    cards, reported_owned = {}, set()
    for gpu in host.get('gpus', []):
        uuid, age = gpu.get('uuid'), gpu.get('sample_age_seconds')
        if not isinstance(uuid, str) or not UUID.fullmatch(uuid) or uuid in cards:
            raise NotReady('GPU identities are missing or duplicated')
        if type(age) not in (int, float) or not math.isfinite(age):
            raise NotReady('GPU sample age unavailable')
        fresh = 0 <= max(age, proc_age) + now - fetched < 115
        cards[uuid] = {**gpu, 'lease_until': min(now + MAX_LEASE_AGE, fetched + 115 - max(age, proc_age)), 'fresh': fresh}
        if gpu.get('own') is True:
            reported_owned.add(uuid)
    for uuid in active:
        card = cards.get(uuid, {})
        if not card.get('fresh') or card.get('status') not in ('free', 'mine', 'shared', 'others'):
            raise NotReady('held GPU sampling invalid, disabled, or stopped')
    # Include newly launched workers not yet reflected in platform accounting.
    effective = occupied + len(set(active) - reported_owned)
    if effective > cap:
        raise NotReady('account quota including pending hold workers exceeded')
    return cards, max(0, cap - effective)


# Runs only through verified SSH. All scientific reads are mode=ro; writes stay
# inside the separate gpu-holds tree. The worker independently validates leases.
REMOTE = r'''
import base64,contextlib,fcntl,hashlib,json,math,os,pathlib,signal,socket,sqlite3,struct,subprocess,sys,tempfile,time
p=json.load(sys.stdin); server=p['server']; roots={'104':'/data2/zhangzibo/arxiv-tssa','103':'/data1/zhangzibo/arxiv-tssa'}
root=pathlib.Path(roots[server]); run='tcl-20261103-semantic-v1'
if socket.gethostname()!='iipl-'+server: raise ValueError('target host mismatch')
def safe(path):
 if any(x.is_symlink() for x in (path,*path.parents)):raise ValueError('symlink path')
 if path.exists() and path.stat().st_uid!=os.geteuid():raise ValueError('path owner mismatch')
def read(path):
 safe(path);return json.loads(path.read_text())
def write(path,value):
 safe(path);fd,tmp=tempfile.mkstemp(prefix='.hold-',dir=path.parent)
 try:
  with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def ident(pid):
 try:
  d=pathlib.Path('/proc')/str(pid);raw=(d/'stat').read_text();tail=raw[raw.rfind(')')+2:].split()
  if tail[0]=='Z':return None
  return {'pid':pid,'uid':d.stat().st_uid,'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'start_ticks':int(tail[19])}
 except (OSError,ValueError,IndexError):return None
def same(record):
 if record.get('process') is None or ident(record['process']['pid'])!=record['process']:return False
 try:
  args=(pathlib.Path('/proc')/str(record['process']['pid'])/'cmdline').read_bytes().decode().split('\0')
  return (len(args)>2 and args[1]==record.get('worker_path') and args[args.index('--worker-id')+1]==record['worker_id']
          and args[args.index('--lease-id')+1]==record['lease_id'] and args[args.index('--controller-id')+1]==record['controller_id'])
 except (OSError,ValueError,IndexError,KeyError):return False
def unlocked(path):
 safe(path)
 if not path.is_file():raise ValueError('required source lock missing')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except Exception:os.close(fd);raise
 return fd
source=root/'results'/run; work=root/'preparations'/run
held=[]
def ledger():
 md=source/'run.md';dbpath=source/'run.sqlite'
 safe(md)
 if md.exists():
  import re
  blocks=re.findall(r'^```json[ \t]*\n(.*?)\n```[ \t]*$',md.read_text(),re.M|re.S)
  if len(blocks)!=1:raise ValueError('invalid Markdown ledger')
  value=json.loads(blocks[0])
  if value.get('schema')!='tcl-run-markdown-v1':raise ValueError('invalid Markdown ledger schema')
  return value
 safe(dbpath)
 if not dbpath.is_file():return None
 with contextlib.closing(sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True)) as db:
  return {'identity':json.loads(db.execute('SELECT identity FROM metadata WHERE id=1').fetchone()[0]),
   'units':{key:{'unit':json.loads(unit),'status':status,'scores':json.loads(scores) if scores else None} for key,unit,status,scores in db.execute('SELECT key,unit,status,scores FROM units')},
   'events':[{'kind':kind,'detail':json.loads(detail)} for kind,detail in db.execute('SELECT kind,detail FROM events ORDER BY id')]}
def summary(value):
 counts={}
 for unit in value['units'].values():counts[unit['status']]=counts.get(unit['status'],0)+1
 end=next((e['detail'] for e in reversed(value['events']) if e['kind']=='terminal'),None)
 return counts,end
if p['action']=='poll':
 value=ledger()
 if value is None:print(json.dumps({'status':'not_started'}));sys.exit()
 meta=value['identity']
 if meta.get('science_sha256')!=p['science_sha256'] or meta.get('run_id')!=run:raise ValueError('science identity changed')
 counts,end=summary(value);result={'status':'running_or_paused','units':counts}
 if end:result['status']='ready_for_report' if counts=={'complete':1024} and end.get('stage')=='M1' else 'partial_terminal'
 print(json.dumps(result));sys.exit()
def completion():
 spec=read(work/'spec.json')
 if spec.get('run_id')!=run:raise ValueError('wrong scientific run')
 science=json.dumps({'run_id':run,'science':spec['science']},sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
 if hashlib.sha256(science.encode()).hexdigest()!=p['science_sha256']:raise ValueError('science hash mismatch')
 held.extend([unlocked(work/'launcher.lock'),unlocked(source/'.writer.lock')])
 value=ledger()
 if value is None:raise ValueError('experiment ledger missing')
 metadata=value['identity'];counts,final=summary(value)
 stages={e['detail']['stage'] for e in value['events'] if e['kind']=='stage_gate'}
 if (metadata.get('run_id')!=run or metadata.get('science_sha256')!=p['science_sha256']
     or metadata.get('writer_host')!=machine or metadata.get('run_root')!=str(source)
     or not final or counts!={'complete':1024} or stages!={'S0','S1','M0','M1'} or final.get('stage')!='M1'
     or final.get('outcome') not in ('exploratory_positive','exploratory_negative','inconclusive')
     or not isinstance(final.get('reason'),str)):
  raise ValueError('experiment incomplete or not at full scientific terminal')
 return {'terminal':final,'complete':1024,'preferred_uuid':spec['execution'].get('gpu_uuid')}
machine={'hostname':socket.gethostname(),'uid':os.geteuid(),'machine_id_sha256':hashlib.sha256(pathlib.Path('/etc/machine-id').read_bytes()).hexdigest()}
if p['action'] in ('handoff','report'):
 try:result=completion()
 except BlockingIOError:print(json.dumps({'status':'scientific_writer_still_running'}));sys.exit()
 if p['action']=='handoff':
  print(json.dumps({'status':'terminal','run_id':run,'science_sha256':p['science_sha256'],'completed_images':1024,'stages_completed':['S0','S1','M0','M1'],'verification':'pending',**result}));sys.exit()
 value=ledger()
 expected=read(work/'spec.json')['science'].get('units',[])
 keytext=lambda key:json.dumps(key,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
 frozen={keytext(u['key']):u for u in expected}
 if len(expected)!=1024 or len(frozen)!=1024 or set(value['units'])!=set(frozen) or any(unit['unit']!=frozen[key] for key,unit in value['units'].items()):raise ValueError('completed units differ from frozen scientific inputs')
 for unit in value['units'].values():
  scores=unit['scores']
  if not isinstance(scores,dict) or set(scores)!={'vit_class','clip_score','target_clip_score','object_clip_scores'} or type(scores['vit_class']) is not int or not 0<=scores['vit_class']<1000:raise ValueError('invalid semantic score')
  objects=scores['object_clip_scores']
  if not isinstance(objects,dict) or set(objects)!={'dog','cat','rabbit','background'}:raise ValueError('invalid object score schema')
  if any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=100 for x in [scores['clip_score'],scores['target_clip_score'],*objects.values()]):raise ValueError('invalid semantic score range')
 gates=[e['detail'] for e in value['events'] if e['kind']=='stage_gate']
 print(json.dumps({'status':'terminal','run_id':run,'science_sha256':p['science_sha256'],'completed_images':1024,'stages_completed':['S0','S1','M0','M1'],'stage_gates':gates,'machine':machine,**result}));sys.exit()
if p['action']=='inspect':
 result=completion()
 python=root/'venv/bin/python'
 # venv executable may legitimately be a symlink; its parent tree must be safe.
 safe(python.parent)
 if not python.is_file():raise ValueError('verified source Python environment unavailable')
 probe=subprocess.run([str(python),'-c','import torch;assert not torch.cuda.is_initialized()'],capture_output=True,text=True,timeout=20)
 if probe.returncode:raise ValueError('CPU worker environment check failed')
 print(json.dumps({'machine':machine,**result}));sys.exit()
if p.get('machine')!=machine:raise ValueError('hold machine identity changed')
base=root/'gpu-holds';safe(base);base.mkdir(mode=0o700,exist_ok=True)
if base.stat().st_mode&0o077:raise ValueError('unsafe hold directory mode')
fd=os.open(base/'controller.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
state=base/p['hold_id'];safe(state);state.mkdir(mode=0o700,exist_ok=True)
owner_path=base/'owner.json';owner=read(owner_path) if owner_path.exists() else None
if owner and owner.get('controller_id')!=p['controller_id']:
 if any(same(r) for r in owner.get('workers',[])) or time.time()-owner.get('updated_at',time.time())<60:raise ValueError('different hold controller owns node')
 owner=None
if not owner:owner={'controller_id':p['controller_id'],'hold_id':p['hold_id'],'workers':[]}
if owner['hold_id']!=p['hold_id']:raise ValueError('hold identity mismatch')
def revoke():
 errors=[]
 for r in owner['workers']:
  try:
   path=state/(r['gpu_uuid']+'.lease.json')
   lease=read(path);lease['stop_required']=True;write(path,lease)
  except Exception as exc:errors.append({'gpu_uuid':r.get('gpu_uuid'),'lease_error':str(exc)})
  try:
   if same(r):
    if hasattr(os,'pidfd_open') and hasattr(signal,'pidfd_send_signal'):
     pidfd=os.pidfd_open(r['process']['pid'])
     try:
      if same(r):signal.pidfd_send_signal(pidfd,signal.SIGTERM)
     finally:os.close(pidfd)
    else:os.kill(r['process']['pid'],signal.SIGTERM)
  except Exception as exc:errors.append({'gpu_uuid':r.get('gpu_uuid'),'signal_error':str(exc)})
 return errors
if p['action']=='stop':
 errors=revoke();owner['stopped']=True;owner['updated_at']=time.time();write(owner_path,owner)
 print(json.dumps({'status':'stop_requested','workers':owner['workers'],'errors':errors,'exit_verified':not any(same(r) for r in owner['workers'])}));sys.exit()
if p['action']=='status':
 records=[]
 for r in owner['workers']:
  sample=None;log=state/(r['gpu_uuid']+'.jsonl');safe(log)
  if log.is_file():
   with log.open('rb') as f:f.seek(max(0,log.stat().st_size-65536));lines=f.read().splitlines()
   for line in reversed(lines):
    try:
     event=json.loads(line)
     if event.get('event')=='sample':sample=event;break
    except ValueError:pass
  records.append({**r,'alive':same(r),'last_sample':sample})
 print(json.dumps({'status':'observed','workers':records}));sys.exit()
if owner.get('stopped'):raise ValueError('stopped worker set requires a new controller and lease identity')
completed=completion()
if p['action'] in ('start','add'):
 if p['action']=='start' and owner['workers']:raise ValueError('hold already has worker records; inspect instead of duplicating')
 if p['action']=='add' and (not owner['workers'] or not all(same(r) for r in owner['workers'])):raise ValueError('only a live hold can add a card')
 code=state/'gpu_hold_worker.py';safe(code)
 if owner['workers'] and not code.is_file():raise ValueError('active worker code missing')
 if not code.exists():
  raw=base64.b64decode(p['worker_source'],validate=True);code.write_bytes(raw);code.chmod(0o600)
 python=root/'venv/bin/python';safe(python.parent)
 if not python.is_file():raise ValueError('verified source Python environment unavailable')
 cards=p['leases']
 if not 1<=len(cards)<=2 or len({x['gpu_uuid'] for x in cards})!=len(cards):raise ValueError('hold card set invalid')
 existing={r['gpu_uuid'] for r in owner['workers']}
 if not existing<={x['gpu_uuid'] for x in cards}:raise ValueError('cannot replace an existing card')
 # Reuse the reviewed live inventory parser; no other process is allowed at acquisition.
 sys.path.insert(0,str(work/'repository/scripts/merging/trigger_contrast_localization'))
 from pilot24_provenance import _live_gpu_xml,_gpu
 xml=_live_gpu_xml()
 for lease in cards:
  if lease['gpu_uuid'] not in existing:_gpu(xml,lease['gpu_uuid'],set())
 owner['updated_at']=time.time();write(owner_path,owner)
 for lease in cards:
  if not lease['observed_at']<=time.time()<lease['expires_at']:raise ValueError('startup lease expired')
  path=state/(lease['gpu_uuid']+'.lease.json');write(path,lease)
  if lease['gpu_uuid'] in existing:continue
  log=open(state/(lease['gpu_uuid']+'.launch.log'),'a');os.chmod(log.name,0o600)
  cmd=[str(python),str(code),'--uuid',lease['gpu_uuid'],'--worker-id',lease['worker_id'],'--lease-id',lease['lease_id'],'--controller-id',p['controller_id'],'--science-sha256',p['science_sha256'],'--state-dir',str(state),'--lease-file',str(path),'--until-stopped','--memory-fraction',str(p['memory_fraction']),'--compute-duty','0.8','--target-utilization-percent',str(p['compute_target_percent']),'--sample-seconds','5']
  child=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
  owner['workers'].append({'gpu_uuid':lease['gpu_uuid'],'worker_id':lease['worker_id'],'lease_id':lease['lease_id'],'controller_id':p['controller_id'],'worker_path':str(code),'lease_path':str(path),'process':ident(child.pid)})
  owner['updated_at']=time.time();write(owner_path,owner)
elif p['action']=='renew':
 if {x['gpu_uuid'] for x in p['leases']}!={x['gpu_uuid'] for x in owner['workers']}:raise ValueError('lease set differs from workers')
 if not all(same(r) for r in owner['workers']):revoke();raise ValueError('a worker exited; no silent restart')
 for r in owner['workers']:
  lease=next(x for x in p['leases'] if x['gpu_uuid']==r['gpu_uuid'])
  if lease['lease_id']!=r['lease_id'] or lease['worker_id']!=r['worker_id']:raise ValueError('worker identity changed')
  write(pathlib.Path(r['lease_path']),lease)
else:raise ValueError('unsupported hold operation')
owner['updated_at']=time.time();write(owner_path,owner)
print(json.dumps({'status':'started' if p['action'] in ('start','add') else 'renewed','workers':owner['workers']}))
'''


def remote(config, action, **fields):
    payload = {'action': action, 'server': config['source']['server'],
               'science_sha256': config['source']['science_sha256'], 'hold_id': config['hold_id'], **fields}
    with transport.ssh_config() as ssh:
        return json.loads(transport.bounded_ssh(ssh, payload['server'], shlex.join(['python3', '-c', REMOTE]),
                                              canonical(payload), timeout=3600 if action == 'report' else 25 if action in ('start', 'inspect', 'add') else 5))


def leases(config, manifest, cards, now):
    uuids = manifest['uuids']
    machine = manifest['machine']
    return [{'schema': 'gpu-hold-lease-v1', 'worker_id': config['hold_id'] + '-' + str(i),
             'controller_id': manifest['controller_id'], 'lease_id': manifest['lease_ids'][uuid],
             'gpu_uuid': uuid, 'host': machine['hostname'], 'owner_uid': machine['uid'],
             'semantic_run_id': RUN, 'semantic_science_sha256': config['source']['science_sha256'],
             'semantic_terminal': True, 'semantic_all_stages_completed': True, 'scientific_writer_exited': True,
             'authorized': True, 'platform_permission_verified': True, 'disabled': False, 'stop_required': False,
             'active_hold_uuids': uuids, 'observed_at': now, 'expires_at': cards[uuid]['lease_until']}
            for i, uuid in enumerate(uuids)]


def effective_expiry(issued):
    # Also cap by the worker's independent age bound; expires_at already carries
    # the original GPU/process sample validity deadline, never a refreshed age.
    return min(min(item['expires_at'], item['observed_at'] + MAX_LEASE_AGE) for item in issued)


def refresh_with_retry(state, manifest):
    try:
        return fresh_snapshot()
    except subprocess.TimeoutExpired:
        stopped(state)
        remaining = manifest.get('lease_expires_at', 0) - time.time()
        audit(state, 'observation_timeout', remaining_effective_lease_seconds=max(0, remaining))
        if remaining <= 6:
            raise NotReady('platform timeout exhausted the remaining effective lease window')
        # At most one retry, reserving five seconds for SSH delivery. No stale
        # capture receives a newer timestamp or a longer lease.
        return fresh_snapshot(timeout=min(PLATFORM_TIMEOUT, remaining - 5))


def observe(config, snapshot=None):
    validate_config(config)
    snapshot = fresh_snapshot() if snapshot is None else snapshot
    cards, available = platform(snapshot, config)
    return {'status': 'not_started', 'policy_sha256': policy_hash(snapshot),
            'free_uuids': [u for u, c in cards.items() if c['fresh'] and c['status'] == 'free'],
            'available_quota': available, 'source_completion': 'not_checked_by_observe',
            'launch_authorized': False}


def authority_hash(config):
    return digest({k: v for k, v in config.items() if k != 'completion_report'})


def stopped(state):
    if (state / 'STOP').exists():
        raise NotReady('user stop is persistent; explicitly authorize a new hold identity to restart')


def watch(config, state=STATE, *, once=False, _lock_fd=None):
    """Foreground owner. On any uncertainty revoke, report and exit; never hide it."""
    validate_config(config); state = private_dir(state)
    fd = _lock_fd if _lock_fd is not None else os.open(state / 'controller.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(fd); raise
    manifest_path = state / 'manifest.json'
    manifest = read_private(manifest_path) if manifest_path.exists() else None
    verification = queue.Queue(maxsize=1)
    def verify_later():
        try: verification.put((True, remote(config, 'report')))
        except Exception as exc: verification.put((False, str(exc)))
    try:
        stopped(state)
        if manifest and manifest['config_sha256'] != digest(config):
            raise NotReady('existing hold configuration changed')
        if not manifest:
            completion = remote(config, 'inspect')
            snapshot = fresh_snapshot()
            cards, quota = platform(snapshot, config)
            candidates = [u for u, c in cards.items() if c['fresh'] and c['status'] == 'free']
            candidates.sort(key=lambda u: (u != completion['preferred_uuid'], u))
            selected = candidates[:min(quota, config['authorization']['max_cards'])]
            if not selected:
                raise NotReady('no eligible free cards on the verified source node')
            stopped(state)
            manifest = {'config_sha256': digest(config), 'authority_sha256': authority_hash(config), 'controller_id': 'hold-' + os.urandom(12).hex(),
                        'machine': completion['machine'], 'uuids': selected,
                        'lease_ids': {u: os.urandom(16).hex() for u in selected}, 'status': 'starting',
                        'worker_sha256': hashlib.sha256(WORKER.read_bytes()).hexdigest()}
            write_private(manifest_path, manifest)  # Before remote spawn, including a lost SSH response.
            audit(state, 'starting', manifest=manifest, completion=completion, config=config, snapshot=snapshot)
            data = WORKER.read_bytes()
            stopped(state)
            issued = leases(config, manifest, cards, time.time())
            manifest['lease_expires_at'] = effective_expiry(issued)
            write_private(manifest_path, manifest)
            result = remote(config, 'start', controller_id=manifest['controller_id'], machine=manifest['machine'],
                            leases=issued, worker_source=base64.b64encode(data).decode(),
                            worker_sha256=hashlib.sha256(data).hexdigest(),
                            memory_fraction=config['authorization']['memory_target_percent'] / 100,
                            compute_target_percent=config['authorization']['compute_target_percent'])
            manifest.update(status='watching', last_remote=result); write_private(manifest_path, manifest)
        manifest['verification'] = 'pending'
        write_private(manifest_path, manifest)
        threading.Thread(target=verify_later, daemon=True).start()
        while True:
            cycle_started = time.monotonic()
            try: verified, report = verification.get_nowait()
            except queue.Empty: pass
            else:
                if not verified or report.get('status') != 'terminal':
                    manifest['verification'] = 'failed'
                    manifest['verification_error'] = str(report)
                    write_private(manifest_path, manifest)
                    audit(state, 'verification_failed', reason=str(report))
                    raise NotReady('post-handoff verification failed: ' + str(report))
                write_private(state / 'verification-report.json', report)
                manifest['verification'] = 'verified'
                write_private(manifest_path, manifest)
                audit(state, 'verification_completed', report_sha256=hashlib.sha256((state / 'verification-report.json').read_bytes()).hexdigest())
            if (state / 'STOP').exists():
                raise NotReady('user stop requested')
            snapshot = refresh_with_retry(state, manifest)
            cards, quota = platform(snapshot, config, manifest['uuids'])
            extra = [u for u, c in cards.items() if c['fresh'] and c['status'] == 'free' and u not in manifest['uuids']]
            extra = sorted(extra)[:min(quota, config['authorization']['max_cards'] - len(manifest['uuids']))]
            if extra:
                stopped(state)
                manifest['uuids'].extend(extra)
                manifest['lease_ids'].update({u: os.urandom(16).hex() for u in extra})
                write_private(manifest_path, manifest)
                audit(state, 'adding_cards', uuids=extra, snapshot=snapshot)
                remote(config, 'add', controller_id=manifest['controller_id'], machine=manifest['machine'],
                       leases=leases(config, manifest, cards, time.time()),
                       memory_fraction=config['authorization']['memory_target_percent'] / 100,
                       compute_target_percent=config['authorization']['compute_target_percent'])
                # The bounded live probe may consume freshness; fetch again before renewal.
                snapshot = fresh_snapshot()
                cards, _ = platform(snapshot, config, manifest['uuids'])
            issued = leases(config, manifest, cards, time.time())
            result = remote(config, 'renew', controller_id=manifest['controller_id'], machine=manifest['machine'], leases=issued)
            manifest.update(status='watching', last_renewed=time.time(), last_remote=result,
                            lease_expires_at=effective_expiry(issued))
            write_private(manifest_path, manifest)
            audit(state, 'renewed', uuids=manifest['uuids'], lease_expires_at=manifest['lease_expires_at'],
                  snapshot_sha256=digest(snapshot), policy_sha256=policy_hash(snapshot))
            if once:
                return result
            # Aim for a five-second cycle; real API/SSH latency may be longer.
            while time.monotonic() - cycle_started < 5:
                if (state / 'STOP').exists(): break
                time.sleep(min(1, 5 - (time.monotonic() - cycle_started)))
    except BaseException as exc:
        if manifest and manifest.get('config_sha256') == digest(config):
            manifest.update(status='stopped_or_lease_expiring', reason=str(exc), stopped_at=time.time())
            try:
                manifest['last_remote'] = remote(config, 'stop', controller_id=manifest['controller_id'], machine=manifest['machine'])
            except Exception as stop_exc:
                manifest['stop_delivery_error'] = str(stop_exc)
            write_private(manifest_path, manifest)
            audit(state, 'stopped_or_lease_expiring', manifest=manifest)
        raise
    finally:
        os.close(fd)


def await_completion(config, state=STATE):
    """Independent waiter: no scientific writer changes and no half-hour gap."""
    validate_config(config, require_report=False); state = private_dir(state)
    fd = os.open(state / 'controller.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    passed_to_watch = False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stopped(state)
        audit(state, 'waiting_for_full_scientific_terminal', authority_sha256=authority_hash(config), pid=os.getpid())
        while True:
            stopped(state)
            value = remote(config, 'poll')
            write_private(state / 'wait-status.json', {'observed_at': time.time(), **value})
            if value['status'] == 'partial_terminal':
                raise NotReady('partial, time-limited or incomplete scientific terminal: holding is not activated; user notification required')
            if value['status'] == 'ready_for_report':
                report = remote(config, 'handoff')
                stopped(state)
                if report.get('status') == 'terminal':
                    path = state / 'completion-report.json'
                    write_private(path, report)
                    activated = {**config, 'completion_report': {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}
                    validate_config(activated)
                    write_private(state / 'activated-config.json', activated)
                    audit(state, 'handoff_ready_verification_pending', report_sha256=activated['completion_report']['sha256'])
                    passed_to_watch = True
                    return watch(activated, state, _lock_fd=fd)
                if report.get('status') != 'scientific_writer_still_running':
                    raise NotReady('unrecognized completion report response')
            elif value['status'] not in ('not_started', 'running_or_paused'):
                raise NotReady('unrecognized scientific run state')
            for _ in range(5):
                stopped(state); time.sleep(1)
    except BaseException as exc:
        audit(state, 'waiter_exited', reason=str(exc))
        write_private(state / 'wait-status.json', {'status': 'not_holding', 'observed_at': time.time(), 'reason': str(exc)})
        raise
    finally:
        if not passed_to_watch: os.close(fd)


def resume(config, state=STATE):
    """Explicit recovery after a resource/network pause, never after user STOP."""
    state = private_dir(state); stopped(state)
    activated = read_private(state / 'activated-config.json') if (state / 'activated-config.json').exists() else config
    if authority_hash(activated) != authority_hash(config):
        raise NotReady('resume authorization differs from original task')
    validate_config(activated)
    fd = os.open(state / 'controller.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    handed = False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stopped(state)
        manifest = read_private(state / 'manifest.json')
        if manifest['authority_sha256'] != authority_hash(config):
            raise NotReady('resume identity mismatch')
        previous = remote(config, 'status', controller_id=manifest['controller_id'], machine=manifest['machine'])
        if any(row.get('alive') is not False for row in previous['workers']):
            raise NotReady('old hold worker still alive; no duplicate or forced takeover')
        audit(state, 'explicit_resume_after_verified_exit', previous=previous, manifest=manifest)
        history = private_dir(state / 'history')
        os.replace(state / 'manifest.json', history / ('manifest-' + str(time.time_ns()) + '.json'))
        handed = True
        return watch(activated, state, _lock_fd=fd)
    finally:
        if not handed: os.close(fd)


def configure_from_semantic(manifest_path, *, reviewed_policy_sha256, compute_target_percent,
                            memory_target_percent, max_cards, hold_id, snapshot=None):
    """Bind current platform policy; resource permission is checked before acquisition."""
    identity = transport.load_manifest(manifest_path)
    if identity['server'] not in NODES:
        raise NotReady('source node has no verified hold path adapter')
    snapshot = fresh_snapshot() if snapshot is None else snapshot
    current_policy_sha256 = policy_hash(snapshot)
    if reviewed_policy_sha256 and current_policy_sha256 != reviewed_policy_sha256:
        raise NotReady('policy changed since the supplied policy hash')
    config = {'schema': 'gpu-hold-controller-v1', 'hold_id': hold_id,
              'source': {'run_id': RUN, 'server': identity['server'], 'science_sha256': identity['science_sha256']},
              'authorization': {'enabled': True, 'until_user_stop': True, 'platform_allows_hold': True,
                  'purpose': 'transparent_gpu_retention', 'username': identity['username'],
                  'reviewed_policy_sha256': current_policy_sha256, 'compute_target_percent': compute_target_percent,
                  'memory_target_percent': memory_target_percent, 'max_cards': max_cards}}
    validate_config(config, require_report=False)
    return config


def stop(config, state=STATE):
    state = private_dir(state)
    write_private(state / 'STOP', {'time': time.time(), 'reason': 'explicit user stop'})
    # Wait until any in-flight acquisition observes STOP and exits. Returning
    # "stopped_before_start" without this synchronization would race with spawn.
    fd = os.open(state / 'controller.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    deadline = time.monotonic() + 35
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return {'status': 'stop_pending', 'reason': 'controller still unwinding; STOP persists, short leases must expire'}
                time.sleep(.05)
        path = state / 'manifest.json'
        if not path.exists():
            return {'status': 'stopped_before_start'}
        manifest = read_private(path)
        if manifest.get('authority_sha256') != authority_hash(config):
            raise NotReady('stop configuration differs from owner')
        return remote(config, 'stop', controller_id=manifest['controller_id'], machine=manifest['machine'])
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inspect-policy', 'configure', 'observe', 'await', 'watch', 'resume', 'stop', 'status'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--state-dir', type=Path, default=STATE)
    parser.add_argument('--activate', action='store_true', help='explicitly enable the separate authorized hold task')
    parser.add_argument('--semantic-manifest', type=Path)
    parser.add_argument('--reviewed-policy-sha256')
    parser.add_argument('--platform-allows-hold', action='store_true', help='legacy compatibility option; not platform approval')
    parser.add_argument('--until-stopped', action='store_true')
    parser.add_argument('--compute-target-percent', type=float)
    parser.add_argument('--memory-target-percent', type=float)
    parser.add_argument('--max-cards', type=int)
    parser.add_argument('--hold-id', default='tcl-semantic-hold-v1')
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect-policy':
            snapshot = fresh_snapshot()
            print(canonical({'policy': snapshot['_hold_raw_policy'], 'policy_sha256': policy_hash(snapshot),
                             'account': snapshot['account'], 'fetched_at': snapshot['fetched_at']})); return 0
        if not args.config:
            raise NotReady('--config ABS is required')
        if args.command == 'configure':
            if not args.until_stopped or not args.semantic_manifest:
                raise NotReady('until-stopped authorization and semantic manifest required')
            config = configure_from_semantic(args.semantic_manifest, reviewed_policy_sha256=args.reviewed_policy_sha256,
                compute_target_percent=args.compute_target_percent, memory_target_percent=args.memory_target_percent,
                max_cards=args.max_cards, hold_id=args.hold_id)
            if args.config.exists() and read_private(args.config) != config:
                raise NotReady('existing hold configuration differs; do not overwrite live authorization')
            write_private(args.config, config)
            print(canonical({'status': 'configured_not_started', 'config': str(args.config), 'source': config['source']})); return 0
        config = read_private(args.config)
        if args.command in ('watch', 'await', 'resume'):
            if not args.activate:
                raise NotReady('watch requires explicit --activate; no default GPU workload')
            result = {'watch': watch, 'await': await_completion, 'resume': resume}[args.command](config, args.state_dir)
        elif args.command == 'stop':
            result = stop(config, args.state_dir)
        elif args.command == 'status':
            path = args.state_dir / 'manifest.json'
            result = read_private(path) if path.exists() else {'status': 'not_started'}
            if path.exists():
                result['last_reported_status'] = result['status']
                if time.time() >= result.get('lease_expires_at', 0):
                    result['status'] = 'lease_expired_worker_exit_unverified'
                result['remote'] = remote(config, 'status', controller_id=result['controller_id'], machine=result['machine'])
        else:
            result = observe(config)
        print(canonical(result)); return 0
    except (ValueError, OSError, KeyError, transport.NotReady, subprocess.SubprocessError) as exc:
        print(canonical({'status': 'not_running_or_lease_expiring', 'reason': str(exc)})); return 1


if __name__ == '__main__':
    sys.exit(main())
