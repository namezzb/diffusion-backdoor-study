"""Bounded offline scorer and VAE CPU model loading; no inference or GPU use."""
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
HELPER = ROOT / 'server/stage_school_assets.py'
assert hashlib.sha256(HELPER.read_bytes()).hexdigest() == '5de11a27f3aa4bd412eef6dd9b837d6ab0be82fc6bf0efb437db29901b15c776'
spec = importlib.util.spec_from_file_location('school_stage', HELPER)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
bundle = json.loads((OUT / 'deployment_bundle_2026-10-27-0015.json').read_text())
expected = bundle['contents']['files']
remote_code = "import datetime,hashlib,json,os,platform,resource,sys,time\nfrom pathlib import Path\nexpected=json.loads(sys.argv[1]);root=Path('/data2/zhangzibo/arxiv-tssa');code=root/'code/mvp-dual-c36b319a1f1d'\nfor relative,record in expected.items():\n p=code/relative;assert p.stat().st_size==record['size'] and hashlib.sha256(p.read_bytes()).hexdigest()==record['sha256']\nrun=root/'results/mvp-2026-10-26-dual-v1'\nstatus=json.loads((run/'failure_or_completion_status.json').read_text());assert status['completed_stages']==['cpu-preflight'] and status['parent_CUDA_initialized'] is False\nsys.path.insert(0,str(code/'scripts/merging'))\nfrom tssa_sd_runtime import load_offline_scorers\nfrom diffusers import AutoencoderKL\nimport torch\nassert not torch.cuda.is_initialized()\nmodels=load_offline_scorers(root/'models')\nvae=AutoencoderKL.from_pretrained(root/'models/sd15/vae',local_files_only=True,use_safetensors=True,torch_dtype=torch.float32).eval().requires_grad_(False)\nassert vae.config.latent_channels==4 and vae.config.scaling_factor==0.18215\nresult={}\nfor name,model in [('vit',models['vit']),('clip',models['clip']),('vae',vae)]:\n params=list(model.parameters());assert all(p.device.type=='cpu' and not p.requires_grad for p in params)\n result[name]={'class':type(model).__name__,'parameter_count':sum(p.numel() for p in params),'parameter_tensors':len(params),'devices':sorted(set(str(p.device) for p in params)),'trainable_parameters':0}\nassert not torch.cuda.is_initialized()\nprint(json.dumps({'status':'passed','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_files_verified':len(expected),'models':result,'model_weights_loaded':True,'model_forward_executed':False,'CUDA_initialized':False,'scientific_images':0,'optimization_updates':0,'peak_rss_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))\n"
formal = json.loads((OUT / 'formal_CPU_preflight_2026-10-27-153513-818090Z.json').read_text())
assert formal['status'] == 'passed', 'Wait for reviewed formal CPU preflight success'
started = datetime.datetime.now(datetime.timezone.utc)
report_path = OUT / f'remote_inference_components_{started:%Y-%m-%d-%H%M%S-%fZ}.json'
log_path = report_path.with_suffix('.log')
report = {'started_at': started.isoformat(), 'status': 'running', 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'report': str(report_path), 'log': str(log_path), 'GPU_used': False, 'remote_model_downloads': False,
          'timeout_seconds': 210, 'remote_CPU_timeout_seconds': 180,
          'scope': 'CPU scorer and VAE loading only; no forward, backward, CUDA, images or optimization.'}
t0 = time.monotonic()
try:
    with stage.SchoolSession() as session, log_path.open('x') as log:
        command = ['timeout', '--signal=TERM', '--kill-after=5s', '180s', 'env', 'CUDA_VISIBLE_DEVICES=',
                   'HF_HUB_OFFLINE=1', 'TRANSFORMERS_OFFLINE=1', 'OMP_NUM_THREADS=2', 'MKL_NUM_THREADS=2',
                   'PYTHONDONTWRITEBYTECODE=1', '/data2/zhangzibo/arxiv-tssa/venv/bin/python', '-c', remote_code,
                   json.dumps(expected, separators=(',', ':'))]
        process = subprocess.Popen(['ssh', '-F', str(session.config), '-o', 'ControlMaster=no', '-o',
                                    'ControlPath=none', 'school104', shlex.join(command)],
                                   stdout=subprocess.PIPE, stderr=log, text=True, start_new_session=True)
        try:
            stdout, _ = process.communicate(timeout=210)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)
            raise TimeoutError('Owned CPU check exceeded210seconds')
        report['returncode'] = process.returncode
        if process.returncode:
            raise RuntimeError(f'Remote CPU check exited{process.returncode}')
        report['result'] = json.loads(stdout)
        assert report['result']['status'] == 'passed'
        report['status'] = 'passed'
except Exception as exc:
    report['status'] = 'failed'
    report['error'] = f'{type(exc).__name__}: {exc}'
finally:
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report['seconds'] = time.monotonic() - t0
    if log_path.exists():
        report['stderr_tail'] = log_path.read_text(errors='replace')[-3500:]
        report['log_sha256'] = hashlib.sha256(log_path.read_bytes()).hexdigest()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({k: report.get(k) for k in ('report','status','result','error','seconds')}, ensure_ascii=False))
raise SystemExit(0 if report['status'] == 'passed' else 1)
