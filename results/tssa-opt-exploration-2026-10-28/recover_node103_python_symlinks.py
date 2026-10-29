#!/usr/bin/env python3
"""One-shot, evidence-bound CPU recovery. Default validates locally; --execute connects once.

The failed venv and its original receipt are renamed into an immutable history
folder, never removed or overwritten. No scientific source or GPU operation.
"""
import argparse
import ast
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREPARE_SHA = '967a0341443b26b22222079516fb81da420c80f26b463a6908d46624a49179f6'
DIAGNOSIS_NAME = 'node103_python_failure_diagnosis_20261028T072959Z.json'
DIAGNOSIS_SHA = '31625d820b7999327994531d180da4e58acb45c269dbd8d98a91822ee64c4400'
FAILED_STATE_SHA = 'f0a62cb10b1de990723ace06c63ced5ba4f10b64898d2db793d67c9ac7b261da'
PYTHON_SHA = '3a691f7c530f01a215cb454f6a13bd2e4aa5f07cfdc2475223b4d00fcc65dd14'
LIBPYTHON_SHA = '072190f97fea2573c49d99c136ff7e629b06bd6824475b50f445912e18a5857a'
CFG_SHA = '7992bec3dba8d14b95f4ae3a53134adfe85a173d08e22a471ca45caf53d7964a'
RECOVERY_ID = 'python-symlinks-20261028-f0a62cb10b1d'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_prepare():
    path = HERE / 'prepare_node103_offline.py'
    assert sha(path.read_bytes()) == PREPARE_SHA
    assert sha((HERE / DIAGNOSIS_NAME).read_bytes()) == DIAGNOSIS_SHA
    spec = importlib.util.spec_from_file_location('recovery_preparation', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    diagnosis = json.loads((HERE / DIAGNOSIS_NAME).read_text())['result']['diagnosis']
    assert diagnosis['base']['sha256'] == diagnosis['venv']['sha256'] == PYTHON_SHA
    assert diagnosis['venv']['commands'][0]['returncode'] == 127
    assert diagnosis['setup/python_install_state.json']['sha256'] == FAILED_STATE_SHA
    assert diagnosis['venv/pyvenv.cfg']['sha256'] == CFG_SHA
    return m


def remote_source(m):
    constants = {'DIAGNOSIS_SHA': DIAGNOSIS_SHA, 'FAILED_STATE_SHA': FAILED_STATE_SHA,
                 'PYTHON_SHA': PYTHON_SHA, 'LIBPYTHON_SHA': LIBPYTHON_SHA, 'CFG_SHA': CFG_SHA,
                 'ARCHIVE_SHA': m.ARCHIVE_SHA, 'RECOVERY_ID': RECOVERY_ID}
    prefix = '\n'.join(k + '=' + repr(v) for k, v in constants.items())
    return m.REMOTE_COMMON + '\n' + prefix + r'''
import datetime,subprocess,tempfile,traceback
root=pathlib.Path(DEST)
assert platform.system()=='Linux' and platform.machine()=='x86_64'
state=checked(DEST,'setup/python_install_state.json')
archive=checked(DEST,'setup/cpython-3.11.7-20240107-linux-x86_64.tar.gz')
base=root/'python-standalone-3.11.7-20240107'; venv=root/'venv'
history=root/'setup'/RECOVERY_ID
lock=remote_lock()
for directory in (base,venv):
    assert directory.is_dir() and not directory.is_symlink() and directory.resolve()==directory
    assert directory.stat().st_uid==os.getuid()
assert not history.exists() and not history.is_symlink(), 'Recovery already attempted; inspect preserved evidence, never retry blindly'
assert hashfile(state)==FAILED_STATE_SHA and json.loads(state.read_text())['status']=='failed'
assert hashfile(archive)==ARCHIVE_SHA
for rel,expected in [('python-standalone-3.11.7-20240107/bin/python3.11',PYTHON_SHA),
                     ('python-standalone-3.11.7-20240107/lib/libpython3.11.so.1.0',LIBPYTHON_SHA),
                     ('venv/bin/python3.11',PYTHON_SHA),('venv/pyvenv.cfg',CFG_SHA)]:
    assert hashfile(checked(DEST,rel))==expected, 'Failure evidence changed; stop before any recovery mutation'
# No process may still use the failed environment; only inspect this account's argv.
for process in pathlib.Path('/proc').iterdir():
    if not process.name.isdigit() or int(process.name) in (os.getpid(),os.getppid()):continue
    try:
        if process.stat().st_uid!=os.getuid():continue
        args=(process/'cmdline').read_bytes().split(b'\0')
        assert not any(a.startswith(os.fsencode(str(venv)+'/bin/')) for a in args), 'Failed environment is in use'
    except (FileNotFoundError,ProcessLookupError):pass
# Record the small failed environment before preserving its exact tree by rename.
inventory=[]; total=0
for p in sorted(venv.rglob('*')):
    info=p.lstat(); assert info.st_uid==os.getuid(), 'Unowned failed environment entry'
    row={'path':str(p.relative_to(venv)),'size':info.st_size,'mode':stat.S_IMODE(info.st_mode)}
    if stat.S_ISLNK(info.st_mode):
        assert inside(p.resolve(),venv), 'Unexpected outside symlink in failed venv'
        row.update(type='symlink',target=os.readlink(p))
    elif stat.S_ISREG(info.st_mode):
        total+=info.st_size; assert total<=128*1024**2
        row.update(type='file',sha256=hashfile(p))
    else:
        assert stat.S_ISDIR(info.st_mode), 'Special file in failed environment'
        row['type']='directory'
    inventory.append(row); assert len(inventory)<=256
clean_env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','PIP_','CUDA','NVIDIA'))
           and k not in ('LD_LIBRARY_PATH','LD_PRELOAD','VIRTUAL_ENV','CONDA_PREFIX','CONDA_DEFAULT_ENV')}
clean_env.update(CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none',PYTHONNOUSERSITE='1',
                 PIP_NO_INDEX='1',PIP_CONFIG_FILE='/dev/null',PYTHONDONTWRITEBYTECODE='1')
def run(argv,timeout):
    p=subprocess.run(argv,capture_output=True,text=True,timeout=timeout,env=clean_env)
    value={'argv':argv,'returncode':p.returncode,'stdout':p.stdout[-24000:],'stderr':p.stderr[-24000:]}
    return p,value
def exclusive_json(path,value):
    fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2); f.flush();os.fsync(f.fileno())
    fd=os.open(str(path.parent),os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
def utcnow():return datetime.datetime.now(datetime.timezone.utc).isoformat()
base_check,base_record=run([str(base/'bin/python3.11'),'-I','-c',
    "import json,sys,ssl,ctypes; print(json.dumps({'version':list(sys.version_info[:3]),'prefix':sys.prefix,'base_prefix':sys.base_prefix}))"],60)
assert base_check.returncode==0
identity=json.loads(base_check.stdout);assert identity=={'version':[3,11,7],'prefix':str(base),'base_prefix':str(base)}
history.mkdir(mode=0o700)
claim={'id':RECOVERY_ID,'status':'recovery_claimed_before_mutation','at':utcnow(),
       'diagnosis_sha256':DIAGNOSIS_SHA,'failed_state_sha256':FAILED_STATE_SHA,'archive_sha256':ARCHIVE_SHA,
       'python_sha256':PYTHON_SHA,'libpython_sha256':LIBPYTHON_SHA,'failed_venv_inventory':inventory,
       'base_probe':base_record,'automatic_retry_allowed':False,'GPU_initialized':False}
exclusive_json(history/'claim.json',claim)
commands=[]
try:
    # RENAME_NOREPLACE and fixed independent history: no old file is overwritten/deleted.
    publish_noreplace(state,history/'failed_python_install_state.json')
    assert hashfile(history/'failed_python_install_state.json')==FAILED_STATE_SHA
    publish_noreplace(venv,history/'failed_venv')
    assert hashfile(history/'failed_venv/pyvenv.cfg')==CFG_SHA
    assert not state.exists() and not venv.exists()
    started={'status':'started','archive_sha256':ARCHIVE_SHA,'recovery_id':RECOVERY_ID,
             'recovery_history':str(history),'previous_failed_state_sha256':FAILED_STATE_SHA,'started_at':utcnow()}
    exclusive_json(state,started); started_sha=hashfile(state)
    # Create at the final venv path: relocating a built venv would break pip shebangs.
    created,creation_record=run([str(base/'bin/python3.11'),'-I','-m','venv','--symlinks',str(venv)],180)
    commands.append(creation_record);exclusive_json(history/'venv_creation.json',creation_record)
    assert created.returncode==0, 'Symlink venv creation failed; preserve new partial venv for review'
    for name in ('python','python3','python3.11'):
        exe=venv/'bin'/name
        assert exe.is_symlink() and exe.resolve()==base/'bin/python3.11', 'Interpreter must link to the verified base ELF'
    code="import json,sys,site,pip,ssl,ctypes; print(json.dumps({'version':list(sys.version_info[:3]),'prefix':sys.prefix,'base_prefix':sys.base_prefix,'user_site':site.ENABLE_USER_SITE,'pip_version':pip.__version__,'pip_file':pip.__file__,'ssl_version':ssl.OPENSSL_VERSION}))"
    checked_python,probe_record=run([str(venv/'bin/python'),'-I','-c',code],60)
    commands.append(probe_record);exclusive_json(history/'venv_probe.json',probe_record)
    assert checked_python.returncode==0
    probe=json.loads(checked_python.stdout)
    assert probe['version']==[3,11,7] and probe['prefix']==str(venv) and probe['base_prefix']==str(base)
    assert probe['user_site'] is False and inside(pathlib.Path(probe['pip_file']).resolve(),venv)
    assert hashfile(state)==started_sha and hashfile(base/'bin/python3.11')==PYTHON_SHA
    completed={'status':'completed','archive_sha256':ARCHIVE_SHA,'python_sha256':PYTHON_SHA,
               'probe':probe,'CUDA_initialized':False,'recovery_id':RECOVERY_ID,'recovery_history':str(history),
               'previous_failed_state_sha256':FAILED_STATE_SHA,'diagnosis_sha256':DIAGNOSIS_SHA,'completed_at':utcnow()}
    # Replace only the recovery's own started receipt after its exact hash is checked.
    exclusive_json(history/'completed_python_install_state.json',completed)
    raw=(history/'completed_python_install_state.json').read_bytes()
    fd,temp=tempfile.mkstemp(prefix='.recovered-python-state-',dir=str(state.parent))
    with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    os.replace(temp,state)
    fd=os.open(str(state.parent),os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    report={'status':'completed','id':RECOVERY_ID,'at':utcnow(),'state_sha256':hashfile(state),
            'preserved_failed_state_sha256':hashfile(history/'failed_python_install_state.json'),
            'preserved_failed_venv':str(history/'failed_venv'),'probe':probe,'commands':commands,
            'GPU_initialized':False,'science_changed':False,'automatic_retry_allowed':False}
    exclusive_json(history/'recovery_result.json',report)
    print(json.dumps(report),flush=True)
except BaseException as error:
    failed={'status':'failed_no_automatic_retry','id':RECOVERY_ID,'at':utcnow(),
            'error':type(error).__name__+': '+str(error),'traceback':traceback.format_exc(),
            'commands':commands,'partial_state_preserved':True,'GPU_initialized':False}
    exclusive_json(history/'recovery_failure.json',failed)
    print(json.dumps(failed),flush=True)
    raise
'''


def exclusive_local(path, payload):
    with path.open('x') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    m = load_prepare()
    source = remote_source(m)
    ast.parse(source, feature_version=(3, 8))
    plan = {'id': RECOVERY_ID, 'server': '103', 'root': m.DEST_ROOT, 'remote_source_sha256': sha(source.encode()),
            'helper_sha256': sha(Path(__file__).read_bytes()), 'preparation_script_sha256': PREPARE_SHA,
            'diagnosis_sha256': DIAGNOSIS_SHA, 'failed_state_sha256': FAILED_STATE_SHA,
            'archive_sha256': m.ARCHIVE_SHA, 'python_sha256': PYTHON_SHA,
            'rename_failed_venv_to': m.DEST_ROOT + '/setup/' + RECOVERY_ID + '/failed_venv',
            'rename_failed_receipt_to': m.DEST_ROOT + '/setup/' + RECOVERY_ID + '/failed_python_install_state.json',
            'automatic_retry_allowed': False, 'GPU_initialized': False, 'network_downloads': False}
    if not args.execute:
        print(json.dumps(dict(status='prepared_locally_no_SSH', **plan), indent=2))
        return 0
    lock_path = HERE / '.prepare_node103.lock'
    assert not lock_path.is_symlink()
    with lock_path.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        claim_path = HERE / (RECOVERY_ID + '.claim.json')
        exclusive_local(claim_path, dict(status='claimed_before_connection', at=dt.datetime.now(dt.timezone.utc).isoformat(), **plan))
        report = dict(plan)
        try:
            sys.path.insert(0, str(ROOT / 'server'))
            from stage_school_assets import SchoolSession
            session = SchoolSession()
            try:
                session.__enter__()
                config = Path(session.temporary.name) / 'recovery-config'
                config.write_text('Host *\n    StrictHostKeyChecking yes\n    BatchMode yes\n    ConnectionAttempts 1\n    ConnectTimeout 60\n    ControlMaster no\n    ControlPath none\n    ControlPersist no\n    Include "' + str(session.config) + '"\n')
                config.chmod(0o600)
                command = shlex.join(['python3', '-B', '-c', source])
                p = subprocess.run(['ssh', '-T', '-F', str(config), 'school103', command], capture_output=True, text=True, timeout=360)
            finally:
                if hasattr(session, 'temporary'): session.temporary.cleanup()
            report.update(returncode=p.returncode, stdout=p.stdout[-64000:], stderr=p.stderr[-16000:])
            report['status'] = 'completed' if p.returncode == 0 else 'failed_or_unknown_preserve_no_retry'
        except Exception as exc:
            report.update(status='failed_or_unknown_preserve_no_retry', error=type(exc).__name__ + ': ' + str(exc))
        report['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        path = HERE / (RECOVERY_ID + '.result.json')
        exclusive_local(path, report)
        print(json.dumps({'report': str(path), **report}, ensure_ascii=False, indent=2))
        return 0 if report['status'] == 'completed' else 1


if __name__ == '__main__':
    sys.exit(main())
