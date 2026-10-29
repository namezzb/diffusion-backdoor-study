"""Bounded offline CPU tokenizer compatibility check; no model or GPU loading."""
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
remote_code = "import ast,datetime,hashlib,inspect,json,os,sys\nfrom pathlib import Path\nexpected=json.loads(sys.argv[1]);root=Path('/data2/zhangzibo/arxiv-tssa');code=root/'code/mvp-dual-c36b319a1f1d'\nfor relative,record in expected.items():\n p=code/relative;assert p.stat().st_size==record['size'] and hashlib.sha256(p.read_bytes()).hexdigest()==record['sha256']\nimport diffusers,torch\nfrom diffusers import UNet2DConditionModel\nfrom diffusers.models import attention_processor\nfrom transformers import CLIPTextConfig\nsource=(code/'scripts/merging/tssa_sd_runtime.py').read_text();fn=next(x for x in ast.parse(source).body if isinstance(x,ast.FunctionDef) and x.name=='load_cpu_assets')\nfields={}\nfor node in fn.body:\n if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('unet_fields','te_fields'):fields[node.targets[0].id]=ast.literal_eval(node.value)\ndef normal(v):return list(v) if isinstance(v,(tuple,list)) else v\nconfigs={};diffs={};defaults={k:v.default for k,v in inspect.signature(UNet2DConditionModel.__init__).parameters.items() if v.default is not inspect.Parameter.empty}\nfor role in ('sd15','dreamshaper8','openjourney'):\n config=UNet2DConditionModel.load_config(root/'models'/role/'unet',local_files_only=True)\n effective={k:normal(config.get(k,defaults.get(k))) for k in fields['unet_fields']};configs[role]=effective\n if role!='sd15':diffs[role]={k:{'clean':configs['sd15'][k],'expert':v} for k,v in effective.items() if v!=configs['sd15'][k]}\nfiles={}\nfor name in ('models/attention_processor.py','models/attention.py','models/unets/unet_2d_condition.py','models/unets/unet_2d_blocks.py','models/transformers/transformer_2d.py'):\n path=Path(diffusers.__file__).parent/name;files[name]=hashlib.sha256(path.read_bytes()).hexdigest()\nassert not torch.cuda.is_initialized()\nprint(json.dumps({'status':'passed','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'diffusers':diffusers.__version__,'UNet_config_differences':diffs,'UNet_effective_fields':configs,'pinned_diffusers_source_sha256':files,'attention_score_implementation':inspect.getsource(attention_processor.Attention.get_attention_scores),'CUDA_initialized':False,'model_weights_loaded':False}))\n"
started = datetime.datetime.now(datetime.timezone.utc)
report_path = OUT / f'remote_upcast_config_diagnostic_{started:%Y-%m-%d-%H%M%S-%fZ}.json'
log_path = report_path.with_suffix('.log')
report = {'started_at': started.isoformat(), 'status': 'running', 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'report': str(report_path), 'log': str(log_path), 'GPU_used': False, 'remote_model_downloads': False,
          'timeout_seconds': 90, 'remote_CPU_timeout_seconds': 75,
          'scope': 'Read-only configuration and pinned dependency inspection after formal CPU rejection; no model load, inference or retry.'}
t0 = time.monotonic()
try:
    with stage.SchoolSession() as session, log_path.open('x') as log:
        command = ['timeout', '--signal=TERM', '--kill-after=5s', '75s', 'env', 'CUDA_VISIBLE_DEVICES=',
                   'HF_HUB_OFFLINE=1', 'TRANSFORMERS_OFFLINE=1', 'OMP_NUM_THREADS=2', 'MKL_NUM_THREADS=2',
                   'PYTHONDONTWRITEBYTECODE=1', '/data2/zhangzibo/arxiv-tssa/venv/bin/python', '-c', remote_code,
                   json.dumps(expected, separators=(',', ':'))]
        process = subprocess.Popen(['ssh', '-F', str(session.config), '-o', 'ControlMaster=no', '-o',
                                    'ControlPath=none', 'school104', shlex.join(command)],
                                   stdout=subprocess.PIPE, stderr=log, text=True, start_new_session=True)
        try:
            stdout, _ = process.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)
            raise TimeoutError('Owned CPU check exceeded90seconds')
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
