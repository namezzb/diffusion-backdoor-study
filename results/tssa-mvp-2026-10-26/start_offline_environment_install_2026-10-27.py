"""One authorized, detached CPU-only installation; never retry automatically."""
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import traceback

ROOT = Path('/Users/zzb/arxiv')
OUT = ROOT / 'results/tssa-mvp-2026-10-26'
HELPER_SHA = '5de11a27f3aa4bd412eef6dd9b837d6ab0be82fc6bf0efb437db29901b15c776'

WORKER = r'''
import datetime,json,os,pathlib,subprocess,sys,tempfile
request=json.loads(sys.argv[1]); folder=pathlib.Path(request['directory'])
record={'status':'running','pid':os.getpid(),'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'argv':request['argv'],'GPU_visible':False,'network_access':False}
def save():
    with tempfile.NamedTemporaryFile('w',dir=folder,prefix='.state-',delete=False) as f:
        json.dump(record,f,indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno()); temp=f.name
    os.replace(temp,folder/'state.json')
save()
try:
    env=os.environ.copy(); env.update(CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PIP_NO_INDEX='1',PIP_DISABLE_PIP_VERSION_CHECK='1')
    with (folder/'installer.stdout.log').open('xb') as out,(folder/'installer.stderr.log').open('xb') as err:
        child=subprocess.Popen(request['argv'],stdin=subprocess.DEVNULL,stdout=out,stderr=err,env=env,cwd=request['root'])
        record['installer_pid']=child.pid; save(); rc=child.wait()
    record.update(returncode=rc,status='complete' if rc==0 else 'failed')
    for name in ['installer.stdout.log','installer.stderr.log']:
        for line in (folder/name).read_text().splitlines():
            try: result=json.loads(line)
            except ValueError: continue
            if isinstance(result,dict) and result.get('audit'): record['installer_result']=result
except BaseException as exc:
    record.update(status='launcher_failed',error_type=type(exc).__name__,error=str(exc))
finally:
    record['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
'''

LAUNCH = r'''
import datetime,fcntl,hashlib,json,os,pathlib,platform,pwd,shutil,subprocess,sys,tempfile
request=json.loads(sys.argv[1]);root=pathlib.Path('/data2/zhangzibo/arxiv-tssa');uid=os.getuid()
assert pwd.getpwuid(uid).pw_name=='zhangzibo' and uid!=0
assert platform.system()=='Linux' and platform.machine()=='x86_64'
assert root.resolve(strict=True)==root and root.stat().st_uid==uid and root.stat().st_dev!=pathlib.Path('/').stat().st_dev
for filename,expected in request['hashes'].items():
    p=pathlib.Path(filename);assert p.resolve(strict=True)==p and p.stat().st_uid==uid
    assert hashlib.sha256(p.read_bytes()).hexdigest()==expected
installer=request['argv'][1];python=request['argv'][0]
active=[]
for p in pathlib.Path('/proc').iterdir():
    if not p.name.isdigit():continue
    try:
        if p.stat().st_uid!=uid:continue
        args=(p/'cmdline').read_bytes().split(b'\0');args=[a.decode(errors='replace') for a in args if a]
    except (FileNotFoundError,PermissionError,ProcessLookupError):continue
    if len(args)>1 and (args[1]==installer or (args[0]==python and '-m' in args and 'pip' in args)):active.append(int(p.name))
assert not active, f'Existing installer/pip processes: {active}'
audit_root=root/'results/environment-install'
if audit_root.exists():
    for p in audit_root.glob('*/audit.json'):
        r=json.loads(p.read_text());assert not r.get('installation_attempted'),f'Prior installation evidence must be inspected before another attempt: {p}'
lock=root/'.offline-env-install.lock'
if lock.exists():
    assert not lock.is_symlink() and lock.stat().st_uid==uid
    with lock.open('r') as f:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
free=shutil.disk_usage(root).free;assert free>=3909917779*2+1024**3
env=os.environ.copy();env.update(CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none',PYTHONNOUSERSITE='1')
probe=json.loads(subprocess.check_output([python,'-I','-B','-c','import json,platform,sys;print(json.dumps(dict(version=platform.python_version(),prefix=sys.prefix,base_prefix=sys.base_prefix)))'],env=env,timeout=30,text=True))
assert probe['version']=='3.11.7' and probe['prefix']==str(root/'venv') and probe['prefix']!=probe['base_prefix']
parent=root/'results/environment-install-launches'
if parent.exists():assert parent.resolve()==parent and parent.stat().st_uid==uid
parent.mkdir(exist_ok=True)
folder=pathlib.Path(tempfile.mkdtemp(prefix=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-'),dir=parent))
payload={'directory':str(folder),'argv':request['argv'],'root':str(root)}
with (folder/'launcher.stdout.log').open('xb') as out,(folder/'launcher.stderr.log').open('xb') as err:
    worker=subprocess.Popen([sys.executable,'-I','-B','-c',request['worker'],json.dumps(payload)],stdin=subprocess.DEVNULL,stdout=out,stderr=err,env=env,cwd=root,start_new_session=True)
result={'status':'launched','pid':worker.pid,'directory':str(folder),'state':str(folder/'state.json'),'free_bytes':free,'interpreter':probe,'source_hashes':request['hashes'],'GPU_used':False}
(folder/'launch.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
'''

def main():
    accepted=json.loads((OUT/'wheelhouse_transfer_acceptance_2026-10-27-0855.json').read_text())
    assert accepted['count']==51 and accepted['bytes']==3909917779 and accepted['transfer_returncode']==0
    helper=ROOT/'server/stage_school_assets.py';assert hashlib.sha256(helper.read_bytes()).hexdigest()==HELPER_SHA
    spec=importlib.util.spec_from_file_location('school_stage',helper);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    remote=Path('/data2/zhangzibo/arxiv-tssa/code/mvp-dual-c36b319a1f1d')
    pins={'server/install_school_offline_env.py':'deedb860b3aeb2743ae51adbd7df87d808d6b447616555476595660d405c0480','research/tssa_mvp_environment_2026-10-26.json':'688edd2a97c9b504d1852a7c0d7ab52b956d13dad5b0818d10e629942ed76604','research/tssa_mvp_requirements_2026-10-26.lock':'c954f66450719b86a2761d2c85faed26a2f27cdb244f4d2f8df7ddc06163d851'}
    for name,expected in pins.items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected
    argv=['/data2/zhangzibo/arxiv-tssa/venv/bin/python',str(remote/'server/install_school_offline_env.py'),'--manifest',str(remote/'research/tssa_mvp_environment_2026-10-26.json'),'--lock',str(remote/'research/tssa_mvp_requirements_2026-10-26.lock'),'--venv','/data2/zhangzibo/arxiv-tssa/venv']
    request={'argv':argv,'hashes':{str(remote/name):value for name,value in pins.items()},'worker':WORKER}
    now=datetime.datetime.now(datetime.timezone.utc);report=OUT/('environment_install_launch_'+now.strftime('%Y-%m-%d-%H%M%S-%fZ')+'.json')
    record={'started_at':now.isoformat(),'status':'starting','automatic_retry':False,'CPU_only':True,'argv':argv}
    report.write_text(json.dumps(record,indent=2)+'\n');print(str(report),flush=True)
    try:
        with module.SchoolSession() as school:
            cmd=shlex.join(['python3','-c',LAUNCH,json.dumps(request)])
            result=subprocess.run(['ssh','-F',str(school.config),'school104',cmd],capture_output=True,text=True,timeout=150)
            report.with_suffix('.stdout.log').write_text(result.stdout);report.with_suffix('.stderr.log').write_text(result.stderr)
            result.check_returncode();record.update(status='launched',remote=json.loads(result.stdout))
    except BaseException as exc:
        record.update(status='launch_unconfirmed_do_not_retry',error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc())
        raise
    finally:
        record['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();report.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)

if __name__=='__main__':main()
