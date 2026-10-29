"""Return already committed response JSON and receipts; no model work or writes on server."""
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
identity='247d164ebc71d8672a069cf3d20398883ddd3592d2fc44d51ba17ff7fe9c4d62'
files={}; pending=[]
for receipt_path in sorted((root/'operations').glob('*.json')):
 receipt=json.loads(receipt_path.read_text())
 if not receipt['operation'].startswith('response/'):continue
 assert receipt['run_identity_sha256']==identity
 if receipt['status']!='completed':
  pending.append(receipt['operation']);continue
 artifact=root/'artifacts'/(receipt_path.stem+'.json')
 raw=artifact.read_bytes();assert len(raw)<8*1024**2
 assert hashlib.sha256(raw).hexdigest()==receipt['artifact_sha256']
 envelope=json.loads(raw)
 assert envelope['operation']==receipt['operation'] and envelope['run_identity_sha256']==identity
 for p,b in [(artifact,raw),(receipt_path,receipt_path.read_bytes())]:
  files[str(p.relative_to(root))]={'sha256':hashlib.sha256(b).hexdigest(),'size':len(b),'base64':base64.b64encode(b).decode()}
print(json.dumps({'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'run_identity_sha256':identity,'read_only':True,'files':files,'pending_response_operations':pending}),flush=True)
'''

stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
path = OUT / f'committed_response_observation_{stamp}.json'
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
            relative = Path(name)
            assert not relative.is_absolute() and '..' not in relative.parts
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
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
