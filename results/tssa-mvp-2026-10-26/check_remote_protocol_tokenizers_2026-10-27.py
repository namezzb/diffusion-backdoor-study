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
remote_code = r'''
import datetime,hashlib,json,os,platform,stat,sys
from pathlib import Path
expected=json.loads(sys.argv[1]); root=Path('/data2/zhangzibo/arxiv-tssa'); code=root/'code/mvp-dual-c36b319a1f1d'
for relative,record in expected.items():
 p=code/relative;assert p.stat().st_size==record['size'] and hashlib.sha256(p.read_bytes()).hexdigest()==record['sha256']
sys.path.insert(0,str(code/'scripts/merging'))
from tssa_sd_runtime import _all_protocol_prompts,_check_tokenizers
from transformers import CLIPTokenizer,__version__ as transformers_version
import torch
protocol=json.loads((code/'research/tssa_mvp_2026-10-26.json').read_text())
manifest=json.loads((code/'research/tssa_mvp_assets_2026-10-26.json').read_text())
files=[];models={};prompts=_all_protocol_prompts(protocol);assert len(prompts)==61
for role in ('sd15','dreamshaper8','openjourney'):
 selected=[e for e in manifest['files'] if e['local_dir']==role and e['path'].startswith('tokenizer/')]
 assert len(selected)==4
 for e in selected:
  p=root/'models'/e['local_path'];q=p.lstat();assert stat.S_ISREG(q.st_mode) and q.st_uid==os.getuid()
  payload=p.read_bytes();assert len(payload)==e['size']
  assert hashlib.sha1(b'blob '+str(len(payload)).encode()+b'\0'+payload).hexdigest()==e['git_blob_oid']
  files.append({'path':e['local_path'],'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'git_blob_verified':True})
 models[role]=CLIPTokenizer.from_pretrained(str(root/'models'/role/'tokenizer'),local_files_only=True)
results={}
for role,tok in models.items():
 _check_tokenizers(models['sd15'],tok,prompts,role)
 lengths=[len(tok(p,truncation=False)['input_ids']) for p in prompts]
 changed=0
 for split in protocol['prompts'].values():
  for pair in split['pairs']:
   assert pair['triggered']==pair['normal'].replace('o','\u020f')
   changed+=tok(pair['normal'])['input_ids']!=tok(pair['triggered'])['input_ids']
 assert changed==20
 results[role]={'prompt_count':len(prompts),'max_token_length':max(lengths),'model_max_length':tok.model_max_length,'matches_clean_tokenizer':True,'triggered_sequences_distinct':changed,'truncated_prompts':0}
assert not torch.cuda.is_initialized()
print(json.dumps({'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'passed','python':platform.python_version(),'transformers':transformers_version,'torch':torch.__version__,'code_files_verified':len(expected),'files':files,'tokenizers':results,'CUDA_initialized':False,'model_weights_loaded':False,'scientific_images':0,'optimization_updates':0}))
'''
started = datetime.datetime.now(datetime.timezone.utc)
report_path = OUT / f'remote_protocol_tokenizers_{started:%Y-%m-%d-%H%M%S-%fZ}.json'
log_path = report_path.with_suffix('.log')
report = {'started_at': started.isoformat(), 'status': 'running', 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'report': str(report_path), 'log': str(log_path), 'GPU_used': False, 'remote_model_downloads': False,
          'timeout_seconds': 90, 'remote_CPU_timeout_seconds': 75,
          'scope': 'Tokenizers and deployed source only; formal full-model CPU/CUDA preflight and research remain pending.'}
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
