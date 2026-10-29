#!/usr/bin/env python3
"""Node103-only adapter; original school installer source remains byte-identical."""
import contextlib,datetime,hashlib,importlib.util,io,json,os,pathlib,signal,sys,tempfile
root=pathlib.Path('/data1/zhangzibo/arxiv-tssa')
assert root.resolve()==root and root.stat().st_uid==os.getuid()
python_state_path=root/'setup/python_install_state.json'
assert not python_state_path.is_symlink() and python_state_path.stat().st_uid==os.getuid()
python_state=json.loads(python_state_path.read_text())
base=root/'python-standalone-3.11.7-20240107'
assert python_state['status']=='completed' and python_state['archive_sha256']=='4a51ce60007a6facf64e5495f4cf322e311ba9f39a8cd3f3e4c026eae488e140', 'Complete the separate pinned Python installation first'
assert python_state['python_sha256']==hashlib.sha256((base/'bin/python3.11').read_bytes()).hexdigest()
assert sys.version_info[:3]==(3,11,7) and sys.prefix==str(root/'venv') and sys.base_prefix==str(base), 'Do not install into an unrelated pre-existing environment'
source=root/'setup/install_school_offline_env.py'
assert hashlib.sha256(source.read_bytes()).hexdigest()=='deedb860b3aeb2743ae51adbd7df87d808d6b447616555476595660d405c0480'
spec=importlib.util.spec_from_file_location('node103_original_installer',source)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.ALLOWED_ROOT=root
state=root/'setup/environment_install_state.json'
assert not state.is_symlink()
old=json.loads(state.read_text()) if state.exists() else None
if old and old['status']!='completed': raise RuntimeError('Incomplete environment installation requires manual audit; no blind retry')
args=['--manifest',str(root/'setup/tssa_mvp_environment_2026-10-26.json'),'--lock',str(root/'setup/tssa_mvp_requirements_2026-10-26.lock'),'--venv',str(root/'venv')]
if old: args.append('--verify-only')
def save(value):
    with tempfile.NamedTemporaryFile(mode='w',dir=str(state.parent),prefix='.'+state.name+'-',delete=False) as f:
        tmp=pathlib.Path(f.name); json.dump(value,f,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,state)
def timeout(signum,frame): raise TimeoutError('Bounded node103 installation deadline exceeded')
signal.signal(signal.SIGALRM,timeout); signal.alarm(3300)
if not old: save({'status':'started','CUDA_initialized':False})
captured=io.StringIO()
try:
    with contextlib.redirect_stdout(captured): code=m.main(args)
    report={'status':'already_installed_inputs_verified' if old and code==0 else 'completed' if code==0 else 'failed','returncode':code,'original_installer_output':captured.getvalue(),'CUDA_validated':False,'driver_compatibility':'Not validated by this CPU-only installation; known node103 driver 550 differs from school104 cu128 environment.'}
    if not old or code!=0: save(report)
    print(json.dumps(report)); sys.exit(code)
finally: signal.alarm(0)
