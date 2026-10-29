"""One CPU-only preflight after the existing transfer completes; no retry or GPU stage."""
import base64
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time

ROOT = Path('/Users/zzb/arxiv')
OUT = ROOT / 'results/tssa-mvp-2026-10-26'
TRANSFER = OUT / 'remaining_model_transfer_2026-10-27-140548-913379Z.json'
PROBE = OUT / 'server-probes/school104-20261027T153216907456Z.json'
MANIFEST = ROOT / 'research/tssa_mvp_assets_2026-10-26.json'
HELPER = ROOT / 'server/stage_school_assets.py'
EXPECTED_MANIFEST = '881d2d21083d589dcd26e69c977a8048d270d2cb73ddb7bd286e2d4dd9197902'
EXPECTED_HELPER = '5de11a27f3aa4bd412eef6dd9b837d6ab0be82fc6bf0efb437db29901b15c776'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def utc():
    return dt.datetime.now(dt.timezone.utc)

remote = r'''
import base64,datetime,hashlib,json,os,resource,stat,subprocess,sys,time
from pathlib import Path
expected=json.loads(sys.argv[1]);root=Path('/data2/zhangzibo/arxiv-tssa');code=root/'code/mvp-dual-c36b319a1f1d'
run=root/'results/mvp-2026-10-26-dual-v1'
assert os.environ['CUDA_VISIBLE_DEVICES']==''
assert root.stat().st_uid==os.getuid() and code.is_dir()
for relative,record in expected.items():
 p=code/relative;assert p.stat().st_size==record['size'] and hashlib.sha256(p.read_bytes()).hexdigest()==record['sha256'],relative
assert not run.exists(),'Existing run evidence requires explicit identity/resume review; preserved'
available=next(int(s.split()[1])*1024 for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:'))
assert available>=48*1024**3,'Insufficient available CPU RAM for formal preflight'
for p in ('cache/huggingface','tmp','results'):
 (root/p).mkdir(parents=True,exist_ok=True)
command=[str(root/'venv/bin/python'),'-B','-u',str(code/'scripts/merging/tssa_mvp_dual_run.py'),'run','--models-root',str(root/'models'),'--run-dir',str(run),'--until','cpu-preflight']
started=time.monotonic()
process=subprocess.run(command,stdout=sys.stderr,stderr=sys.stderr)
files={}
for name in ('cpu_preflight.json','model_file_hashes.json','parameter_key_manifest.json','basis_statistics.json','failure_or_completion_status.json','resource_ledger.json','run_identity.json','last_failure_traceback.txt'):
 p=run/name
 if p.is_file():
  raw=p.read_bytes();assert len(raw)<8*1024**2
  files[name]={'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),'base64':base64.b64encode(raw).decode()}
status=json.loads((run/'failure_or_completion_status.json').read_text()) if (run/'failure_or_completion_status.json').exists() else None
passed=(process.returncode==0 and status and status.get('status')=='paused_at_requested_stage' and status.get('completed_stages')==['cpu-preflight'] and status.get('parent_CUDA_initialized') is False and not status.get('worker_pids_started_this_process'))
print(json.dumps({'status':'passed' if passed else 'failed','returncode':process.returncode,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'seconds':time.monotonic()-started,'source_files_verified':len(expected),'CPU_memory_available_before':available,'max_child_rss_KiB':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,'run_dir':str(run),'files':files,'GPU_stage_started':False}),flush=True)
raise SystemExit(0 if passed else 2)
'''

started = utc()
report_path = OUT / f'formal_CPU_preflight_{started:%Y-%m-%d-%H%M%S-%fZ}.json'
log_path = report_path.with_suffix('.log')
report = {'status': 'waiting_for_existing_transfer', 'started_at': started.isoformat(), 'pid': os.getpid(),
          'report': str(report_path), 'log': str(log_path), 'script_sha256': digest(Path(__file__)),
          'transfer_report': str(TRANSFER), 'probe_report': str(PROBE), 'automatic_retry': False,
          'maximum_local_wait_seconds': 900, 'remote_CPU_timeout_seconds': 1200, 'CPU_threads': 2,
          'GPU_used': False, 'scope': 'Formal checkpoint CPU structure, frozen delta and grouping only; no response gradients or research images.'}

def save():
    report['observed_at'] = utc().isoformat()
    tmp = report_path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    tmp.replace(report_path)

lock = (OUT / 'formal_cpu_preflight.lock').open('a+')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
save()
print(report_path, flush=True)
t0 = time.monotonic()
try:
    assert digest(MANIFEST) == EXPECTED_MANIFEST and digest(HELPER) == EXPECTED_HELPER
    while True:
        transfer = json.loads(TRANSFER.read_text())
        if transfer['status'] == 'complete':
            assert transfer['returncode'] == 0 and transfer['selected_count'] == 47
            break
        assert transfer['status'] == 'running', 'Existing transfer failed; no connection or retry attempted'
        os.kill(transfer['pid'], 0)
        os.kill(transfer['child_pid'], 0)
        assert time.monotonic()-t0 < 900, 'Transfer still incomplete at bounded wait deadline'
        time.sleep(5)
    manifest = json.loads(MANIFEST.read_text())
    receipts = {}
    for line in (OUT/'asset_transfer.jsonl').read_text().splitlines():
        record = json.loads(line)
        if record.get('status') in ('transferred_verified','remote_verified_existing'):
            receipts[record['source']['local_path']] = record
    for entry in manifest['files']:
        r = receipts[entry['local_path']]
        assert all(r['source'].get(k)==entry.get(k) for k in ('repo_id','revision','path','local_path','git_blob_oid','size'))
        assert r['size']==entry['size'] and r['path']==manifest['models_root_remote']+'/'+entry['local_path']
        assert len(r['sha256'])==64 and (entry['sha256'] is None or r['sha256']==entry['sha256'])
    probe = json.loads(PROBE.read_text())
    assert probe['status']=='observed' and (utc()-dt.datetime.fromisoformat(probe['finished_at'])).total_seconds()<1800
    expected = json.loads((OUT/'deployment_bundle_2026-10-27-0015.json').read_text())['contents']['files']
    for relative, item in expected.items():
        assert digest(ROOT/relative)==item['sha256'], 'Local source differs from deployment snapshot'
    spec = importlib.util.spec_from_file_location('stage', HELPER)
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    report.update(status='running_CPU_preflight', asset_receipts_verified=47, preflight_started_at=utc().isoformat())
    save()
    with stage.SchoolSession() as session, log_path.open('x') as log:
        command = ['timeout','--signal=TERM','--kill-after=10s','1200s','env','CUDA_VISIBLE_DEVICES=',
                   'HF_HUB_OFFLINE=1','TRANSFORMERS_OFFLINE=1','PIP_NO_INDEX=1','PYTHONDONTWRITEBYTECODE=1',
                   'OMP_NUM_THREADS=2','MKL_NUM_THREADS=2','OPENBLAS_NUM_THREADS=2',
                   'HF_HOME=/data2/zhangzibo/arxiv-tssa/cache/huggingface','XDG_CACHE_HOME=/data2/zhangzibo/arxiv-tssa/cache',
                   'TMPDIR=/data2/zhangzibo/arxiv-tssa/tmp','/data2/zhangzibo/arxiv-tssa/venv/bin/python','-B','-u','-c',remote,json.dumps(expected,separators=(',',':'))]
        process = subprocess.Popen(['ssh','-F',str(session.config),'-o','ControlMaster=no','-o','ControlPath=none','school104',shlex.join(command)],stdout=subprocess.PIPE,stderr=log,text=True,start_new_session=True)
        report['SSH_pid']=process.pid
        save()
        try:
            stdout,_ = process.communicate(timeout=1230)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGTERM)
            try: process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL)
                process.communicate(timeout=5)
            raise TimeoutError('Bounded CPU preflight exceeded timeout; preserve remote evidence before any resume')
        report['returncode']=process.returncode
        if stdout.strip():
            result=json.loads(stdout)
            copied=OUT/(report_path.stem+'_artifacts')
            copied.mkdir()
            for name,item in result['files'].items():
                assert Path(name).name==name
                raw=base64.b64decode(item.pop('base64'),validate=True)
                assert len(raw)==item['size'] and hashlib.sha256(raw).hexdigest()==item['sha256']
                (copied/name).write_bytes(raw)
                item['local_path']=str(copied/name)
            report['result']=result
        assert process.returncode==0 and report.get('result',{}).get('status')=='passed', 'CPU preflight did not pass; no retry'
        report['status']='passed'
except Exception as exc:
    report.update(status='failed',error=f'{type(exc).__name__}: {exc}')
finally:
    report.update(finished_at=utc().isoformat(),seconds=time.monotonic()-t0)
    if log_path.exists():
        report['log_sha256']=digest(log_path)
        report['stderr_tail']=log_path.read_text(errors='replace')[-3500:]
    save()
print(json.dumps({k:report.get(k) for k in ('report','status','error','seconds')},ensure_ascii=False),flush=True)
raise SystemExit(0 if report['status']=='passed' else 1)
