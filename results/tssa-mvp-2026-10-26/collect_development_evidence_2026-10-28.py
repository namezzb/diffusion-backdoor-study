"""Return completed development evidence only; no GPU or remote writes."""
import base64
import datetime as dt
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path('/Users/zzb/arxiv')
OUT = ROOT / 'results/tssa-mvp-2026-10-26'
sys.path.insert(0, str(ROOT / 'server'))
from stage_school_assets import SchoolSession

REMOTE = r'''
import base64,datetime,hashlib,json,os,pathlib
root=pathlib.Path('/data2/zhangzibo/arxiv-tssa/results/mvp-2026-10-28-single-v1')
assert root.stat().st_uid==os.getuid()
files={}
selection=root/'candidate_selection.json'
assert hashlib.sha256(selection.read_bytes()).hexdigest()=='82e5b2a176620d215b818b2b1ffb05e7ca6aa233138a33792e0b2279811700d6'
for name in ['candidate_selection.json','candidate_response_and_image_metrics.json','selected_checkpoint_manifests.json','select_per_image_metrics.jsonl']:
 raw=(root/name).read_bytes();assert len(raw)<16*1024**2
 files[name]={'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),'base64':base64.b64encode(raw).decode()}
print(json.dumps({'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'read_only':True,'heldout_read':False,'files':files}),flush=True)
'''

stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
path = OUT / f'development_evidence_observation_{stamp}.json'
report = {'started_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'read_only': True}
try:
    with SchoolSession() as session:
        proc = subprocess.run(['ssh', '-F', str(session.config), '-o', 'ControlMaster=no',
                               '-o', 'ControlPath=none', 'school104',
                               shlex.join(['python3', '-c', REMOTE])],
                              capture_output=True, text=True, timeout=100)
    report.update(returncode=proc.returncode, stderr=proc.stderr[-1500:])
    if proc.returncode:
        report['status'] = 'connection_or_query_failed'
    else:
        result = json.loads(proc.stdout)
        target = OUT / (path.stem + '_artifacts')
        target.mkdir()
        for name, item in result['files'].items():
            raw = base64.b64decode(item.pop('base64'))
            assert hashlib.sha256(raw).hexdigest() == item['sha256']
            assert Path(name).name == name
            dest = target / name
            dest.write_bytes(raw)
            item['local_path'] = str(dest)
        report.update(status='observed', result=result)
except Exception as exc:
    report.update(status='failed', error=str(exc))
report['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
with path.open('x') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
print(json.dumps({'report': str(path), 'status': report['status'],
                  'file_count': len(report.get('result', {}).get('files', {})),
                  'error': report.get('error'), 'stderr': report.get('stderr')}, ensure_ascii=False))
