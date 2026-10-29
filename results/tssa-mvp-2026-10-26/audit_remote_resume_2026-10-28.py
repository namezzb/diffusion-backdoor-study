"""Read-only resume identity, receipt, source and process audit; no torch/CUDA."""
import datetime,hashlib,importlib.util,json,os,shlex,signal,subprocess,time
from pathlib import Path
ROOT=Path('/Users/zzb/arxiv');OUT=ROOT/'results/tssa-mvp-2026-10-26';HELPER=ROOT/'server/stage_school_assets.py'
assert hashlib.sha256(HELPER.read_bytes()).hexdigest()=='5de11a27f3aa4bd412eef6dd9b837d6ab0be82fc6bf0efb437db29901b15c776'
spec=importlib.util.spec_from_file_location('stage',HELPER);stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
bundle=json.loads((OUT/'deployment_bundle_2026-10-28-configfix.json').read_text())
formal=json.loads((OUT/'formal_CPU_preflight_2026-10-27-161330-135213Z.json').read_text());assert formal['status']=='passed'
expected={'source_files':bundle['contents']['files'],'saved_outputs':formal['result']['files']}
remote=r'''
import datetime,fcntl,hashlib,json,os,shutil,sys,time
from pathlib import Path
expected=json.loads(sys.argv[1]);root=Path('/data2/zhangzibo/arxiv-tssa');code=root/'code/mvp-dual-0a5b9bdc7434';run=root/'results/mvp-2026-10-26-dual-v2-configfix'
assert os.environ['CUDA_VISIBLE_DEVICES']=='' and run.stat().st_uid==os.getuid()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for relative,item in expected['source_files'].items():
 p=code/relative;assert p.stat().st_size==item['size'] and sha(p)==item['sha256'],relative
for name,item in expected['saved_outputs'].items():assert sha(run/name)==item['sha256'],name
processes=[]
for proc in Path('/proc').iterdir():
 if not proc.name.isdigit() or int(proc.name) in (os.getpid(),os.getppid()):continue
 try:
  if proc.stat().st_uid!=os.getuid():continue
  raw=(proc/'cmdline').read_bytes()
  if str(root).encode() in raw and any(tag in raw for tag in (b'tssa_mvp_',b'stage_school_assets',b'install_school_offline_env')):
   processes.append({'pid':int(proc.name),'comm':(proc/'comm').read_text().strip(),'command_sha256':hashlib.sha256(raw).hexdigest()})
 except (FileNotFoundError,ProcessLookupError,PermissionError):continue
assert not processes, 'Another owned project process requires review before resume'
with (run/'.run.lock').open('rb') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 sys.path.insert(0,str(code/'scripts/merging'))
 from tssa_mvp_run import build_identity,canonical_hash,file_hash
 from tssa_mvp_dual_run import DualBackend
 assert 'torch' not in sys.modules
 identity=build_identity(code/'research/tssa_mvp_2026-10-26.json',code/'research/tssa_mvp_assets_2026-10-26.json',root/'models')
 identity.update(backend=DualBackend.kind,single_GPU_sequential_CPU_scoring=False,GPU_worker_count=2)
 identity['implementation_sha256']['tssa_mvp_dual_run.py']=file_hash(code/'scripts/merging/tssa_mvp_dual_run.py')
 assert identity==json.loads((run/'run_identity.json').read_text()), 'Resume identity drift'
 receipts=[]
 for p in (run/'operations').glob('*.json'):
  r=json.loads(p.read_text());assert r['status']=='completed' and r['run_identity_sha256']==canonical_hash(identity)
  a=run/'artifacts'/(p.stem+'.json');assert file_hash(a)==r['artifact_sha256']
  envelope=json.loads(a.read_text());assert envelope['operation']==r['operation'] and envelope['run_identity_sha256']==r['run_identity_sha256']
  receipts.append({'operation':r['operation'],'status':r['status'],'artifact_sha256':r['artifact_sha256']})
 assert [r['operation'] for r in receipts]==['preflight/cpu']
 status=json.loads((run/'failure_or_completion_status.json').read_text());assert status['completed_stages']==['cpu-preflight'] and not status['worker_pids_started_this_process'] and status['parent_CUDA_initialized'] is False
 assert not (run/'execution_manifest.json').exists()
 for name,item in expected['saved_outputs'].items():assert sha(run/name)==item['sha256']
 assert 'torch' not in sys.modules
 result={'status':'passed','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_files_verified':len(expected['source_files']),'existing_output_hashes_verified':len(expected['saved_outputs']),'model_files_rehashed':len(identity['local_file_sha256']),'run_identity_equal':True,'run_identity_sha256':canonical_hash(identity),'completed_receipts':receipts,'existing_run_lock_available':True,'own_active_project_processes':processes,'tmux_path':shutil.which('tmux'),'torch_imported':False,'GPU_used':False,'run_files_modified':False,'allocation_bound':False,'scientific_images':0,'optimizer_updates':0}
 fcntl.flock(lock,fcntl.LOCK_UN)
print(json.dumps(result),flush=True)
'''
now=lambda:datetime.datetime.now(datetime.timezone.utc);start=now();path=OUT/f'remote_resume_audit_{start:%Y-%m-%d-%H%M%S-%fZ}.json';log=path.with_suffix('.log')
r={'started_at':start.isoformat(),'status':'running','script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'read_only':True,'GPU_used':False,'model_loading_or_inference':False,'automatic_retry':False,'timeout_seconds':240,'report':str(path)}
save=lambda:path.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');save();print(path,flush=True);t=time.monotonic()
try:
 with stage.SchoolSession() as session,log.open('x') as stream:
  command=['timeout','--signal=TERM','--kill-after=10s','210s','env','CUDA_VISIBLE_DEVICES=','HF_HUB_OFFLINE=1','TRANSFORMERS_OFFLINE=1','PYTHONDONTWRITEBYTECODE=1',str(Path('/data2/zhangzibo/arxiv-tssa/venv/bin/python')),'-B','-u','-c',remote,json.dumps(expected,separators=(',',':'))]
  p=subprocess.Popen(['ssh','-F',str(session.config),'-o','ControlMaster=no','-o','ControlPath=none','school104',shlex.join(command)],stdout=subprocess.PIPE,stderr=stream,text=True,start_new_session=True)
  try: stdout,_=p.communicate(timeout=240)
  except subprocess.TimeoutExpired:
   os.killpg(p.pid,signal.SIGTERM)
   try:p.communicate(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.communicate(timeout=5)
   raise
  r['returncode']=p.returncode
  if stdout.strip():r['result']=json.loads(stdout)
  assert p.returncode==0 and r.get('result',{}).get('status')=='passed','Resume audit failed; no launch or retry'
  r['status']='passed'
except Exception as e:r.update(status='failed',error=f'{type(e).__name__}: {e}')
finally:
 r.update(finished_at=now().isoformat(),seconds=time.monotonic()-t)
 if log.exists():r.update(log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),stderr_tail=log.read_text()[-2500:])
 save()
print(json.dumps({k:r.get(k) for k in ('report','status','seconds','result','error')},ensure_ascii=False),flush=True)
raise SystemExit(0 if r['status']=='passed' else 1)
