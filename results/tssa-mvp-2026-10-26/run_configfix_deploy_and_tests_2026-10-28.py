"""Install immutable corrected source and run CPU regressions once; no GPU."""
import datetime,hashlib,importlib.util,json,os,shlex,signal,subprocess,time
from pathlib import Path
ROOT=Path('/Users/zzb/arxiv');OUT=ROOT/'results/tssa-mvp-2026-10-26'
helper=ROOT/'server/stage_school_assets.py'
assert hashlib.sha256(helper.read_bytes()).hexdigest()=='5de11a27f3aa4bd412eef6dd9b837d6ab0be82fc6bf0efb437db29901b15c776'
spec=importlib.util.spec_from_file_location('stage',helper);stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
bundle_path=OUT/'deployment_bundle_2026-10-28-configfix.json';bundle=json.loads(bundle_path.read_text())
source=(OUT/'deploy_source_snapshot_2026-10-28-configfix.py').read_text()
source+='''
import subprocess,sys,time
started=time.monotonic()
result=subprocess.run([str(ROOT/'venv/bin/python'),'-B','-m','unittest','discover','-s',str(DEST/'scripts/merging'),'-p','test_tssa_*.py','-v'],cwd=DEST,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
assert 'Ran 59 tests' in result.stdout
print(json.dumps({'kind':'CPU_regression','returncode':result.returncode,'seconds':time.monotonic()-started,'output':result.stdout,'GPU_used':False}),flush=True)
raise SystemExit(result.returncode)
'''
now=lambda:datetime.datetime.now(datetime.timezone.utc)
start=now();path=OUT/f'configfix_deployment_CPU_checks_{start:%Y-%m-%d-%H%M%S-%fZ}.json';log=path.with_suffix('.log')
report={'started_at':start.isoformat(),'status':'running','script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'bundle_sha256':bundle['sha256'],'CPU_threads':2,'GPU_used':False,'automatic_retry':False,'report':str(path)}
save=lambda:path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
save();print(path,flush=True);t=time.monotonic()
try:
 with stage.SchoolSession() as session,log.open('x') as stream:
  cmd=['timeout','--signal=TERM','--kill-after=10s','300s','env','CUDA_VISIBLE_DEVICES=','HF_HUB_OFFLINE=1','TRANSFORMERS_OFFLINE=1','PYTHONDONTWRITEBYTECODE=1','OMP_NUM_THREADS=2','MKL_NUM_THREADS=2','OPENBLAS_NUM_THREADS=2', '/data2/zhangzibo/arxiv-tssa/venv/bin/python','-B','-u','-c',source]
  p=subprocess.Popen(['ssh','-F',str(session.config),'-o','ControlMaster=no','-o','ControlPath=none','school104',shlex.join(cmd)],stdout=subprocess.PIPE,stderr=stream,text=True,start_new_session=True)
  try: stdout,_=p.communicate(timeout=330)
  except subprocess.TimeoutExpired:
   os.killpg(p.pid,signal.SIGTERM);p.communicate(timeout=10);raise
  report['returncode']=p.returncode
  report['results']=[json.loads(line) for line in stdout.splitlines()]
  assert p.returncode==0 and len(report['results'])==2
  assert report['results'][0]['source_files_verified']==20
  tests=report['results'][1];assert tests['returncode']==0 and '\nOK\n' in tests['output']
  report['status']='passed'
  bundle.update(remote_uploaded=True,remote_source_verified=True,remote_deployment_evidence=path.name)
  bundle_path.write_text(json.dumps(bundle,ensure_ascii=False,indent=2)+'\n')
except Exception as exc: report.update(status='failed',error=f'{type(exc).__name__}: {exc}')
finally:
 report.update(finished_at=now().isoformat(),seconds=time.monotonic()-t)
 if log.exists():report.update(log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),stderr_tail=log.read_text()[-3000:])
 save()
print(json.dumps({k:report.get(k) for k in ('report','status','seconds','error')}),flush=True)
raise SystemExit(0 if report['status']=='passed' else 1)
