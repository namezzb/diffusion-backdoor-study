"""One bounded, read-only audit after the original search process disappeared."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import shlex
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('observer', HERE / 'observe_image_search.py')
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)

REMOTE = r'''
import datetime as dt, hashlib, json, os, pathlib, platform, stat
R=pathlib.Path('/data1/zhangzibo/arxiv-tssa/results/tssa-opt-exploration-2026-10-28-v1')
def checked(p):
    assert p.is_relative_to(R) and p.resolve()==p and not p.is_symlink()
    for q in [p, *p.parents]:
        if q==R.parent: break
        assert not q.is_symlink() and q.stat().st_uid==os.getuid()
    return p
def read_json(p):
    checked(p); assert p.stat().st_size<65536
    return json.loads(p.read_bytes())
def digest(p):
    checked(p)
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_size<=16*1024*1024
        h=hashlib.sha256(); n=0
        while True:
            b=os.read(fd,1024*1024)
            if not b: break
            n+=len(b); assert n<=16*1024*1024; h.update(b)
        after=os.fstat(fd)
        assert n==before.st_size==after.st_size and before.st_mtime_ns==after.st_mtime_ns
        return {'size':n,'sha256':h.hexdigest(),'mtime_ns':before.st_mtime_ns}
    finally: os.close(fd)
out={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'read_only':True,'GPU_initialized':False,
     'old_pid_exists':pathlib.Path('/proc/188034').exists(),'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
     'uptime':pathlib.Path('/proc/uptime').read_text().strip(),'kernel':platform.release(),
     'btime':next(x for x in pathlib.Path('/proc/stat').read_text().splitlines() if x.startswith('btime ')),
     'nvidia_kernel_version':pathlib.Path('/proc/driver/nvidia/version').read_text(),
     'completed_pngs':[],'incomplete':[],'errors':[]}
files=sorted((R/'operations').glob('*.json')); assert len(files)<=1440
for p in files:
    receipt=read_json(p); task=receipt['task']
    assert receipt['task_id']==p.stem and task['stage']=='search'
    image=R/'images'/task['stage']/task['condition']['id']/task['candidate']/(task['row']['id']+'.png')
    assert image.is_relative_to(R)
    item={'task_id':p.stem,'receipt':digest(p),'image_path':str(image.relative_to(R)),
          'receipt_status':receipt['status'],'image_exists':image.exists()}
    if image.exists():
        item['image']=digest(image)
    if receipt['status']=='completed':
        item['matches_recorded_image_hash']=item.get('image',{}).get('sha256')==receipt['record']['image_sha256']
        if not item['matches_recorded_image_hash']: out['errors'].append('PNG mismatch:'+p.stem)
        out['completed_pngs'].append(item)
    else:
        item['task']=task; item['started_at']=receipt['started_at'];out['incomplete'].append(item)
out['receipt_count']=len(files)
out['completed_PNG_hashes_verified']=sum(x['matches_recorded_image_hash'] for x in out['completed_pngs'])
out['scientific_files_modified']=False
print(json.dumps(out,ensure_ascii=False))
'''

sys.path.insert(0, str(ROOT / 'server'))
from stage_school_assets import SchoolSession

report = {'started_at':observer.now(),'read_only':True,'server':'103'}
session = SchoolSession()
try:
    session.__enter__()
    config=Path(session.temporary.name)/'audit-config'
    config.write_text('Host *\n    BatchMode yes\n    StrictHostKeyChecking yes\n    ConnectTimeout 60\n    ConnectionAttempts 1\n    ControlMaster no\n    ControlPath none\n    ControlPersist no\n    UpdateHostKeys no\n    Include "'+str(session.config)+'"\n')
    config.chmod(0o600)
    command=shlex.join(['/data1/zhangzibo/arxiv-tssa/venv/bin/python','-I','-B','-c',REMOTE])
    rc,out,err=observer.one_bounded_ssh(config,'103',command)
    report.update(returncode=rc,stderr=err.decode(errors='replace')[-4000:])
    if rc==0: report['remote']=json.loads(out)
    else: report['stdout_tail']=out.decode(errors='replace')[-4000:]
except Exception as e:
    report['error']=type(e).__name__+': '+str(e)
finally:
    if hasattr(session,'temporary'):session.temporary.cleanup()
stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
target=HERE/('interruption_audit_'+stamp+'.json')
target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
compact={k:v for k,v in report.items() if k!='remote'}
if 'remote' in report:
    compact['remote']={k:v for k,v in report['remote'].items() if k!='completed_pngs'}
print(json.dumps({'report':str(target),**compact},ensure_ascii=False,indent=2))
