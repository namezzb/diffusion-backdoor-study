#!/usr/bin/env python3
"""Prepare node103 CPU/offline assets without allocating any GPU.

Fixed Mac -> school103 Python archive, and school104 -> Mac pipe -> school103
asset relay. Each SSH has a deadline and no automatic retries. Transfer and
installation are separate explicit stages; an incomplete install is preserved
for review, never overwritten. No existing user data is deleted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any

PROJECT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE_ROOT = "/data2/zhangzibo/arxiv-tssa"
DEST_ROOT = "/data1/zhangzibo/arxiv-tssa"
ARCHIVE = HERE / "cpython-3.11.7-20240107-linux-x86_64.tar.gz"
ARCHIVE_SHA = "4a51ce60007a6facf64e5495f4cf322e311ba9f39a8cd3f3e4c026eae488e140"
ENV_MANIFEST = PROJECT / "research/tssa_mvp_environment_2026-10-26.json"
MODEL_MANIFEST = PROJECT / "research/tssa_mvp_assets_2026-10-26.json"
HASH_EVIDENCE = PROJECT / "results/tssa-mvp-2026-10-26/single_CPU_preflight_2026-10-28-013551-322690Z_artifacts/model_file_hashes.json"
INSTALLER = PROJECT / "server/install_school_offline_env.py"
SESSION_SCRIPT = PROJECT / "server/stage_school_assets.py"
PINS = {
    ENV_MANIFEST: "688edd2a97c9b504d1852a7c0d7ab52b956d13dad5b0818d10e629942ed76604",
    MODEL_MANIFEST: "881d2d21083d589dcd26e69c977a8048d270d2cb73ddb7bd286e2d4dd9197902",
    HASH_EVIDENCE: "96bae0d29dfa0d07403efdeb2026e141abd6667a669b26d1dd7b3d1515389d35",
    INSTALLER: "deedb860b3aeb2743ae51adbd7df87d808d6b447616555476595660d405c0480",
    SESSION_SCRIPT: "5de11a27f3aa4bd412eef6dd9b837d6ab0be82fc6bf0efb437db29901b15c776",
}
STAGES = ("python", "wheels", "models", "install-python", "install-env")
METADATA_TIMEOUT = 300
TRANSFER_TIMEOUT = 3600


def sha256(path: Path, prefix: int | None = None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        remaining = prefix
        while remaining is None or remaining:
            block = stream.read(8 * 1024**2 if remaining is None else min(remaining, 8 * 1024**2))
            if not block:
                if remaining:
                    raise RuntimeError("Source is shorter than the checked destination prefix.")
                break
            h.update(block)
            if remaining is not None:
                remaining -= len(block)
    return h.hexdigest()


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or not path.parts or path.is_absolute() or ".." in path.parts or str(path) != value
            or any(ord(c) < 32 for c in value) or "\\" in value):
        raise ValueError("Unsafe relative asset path")
    return value


def checked_entries(kind: str) -> list[dict[str, Any]]:
    for path, expected in PINS.items():
        if path.is_symlink() or sha256(path) != expected:
            raise RuntimeError(f"Frozen input/source hash mismatch: {path.name}")
    env = json.loads(ENV_MANIFEST.read_text())
    lock = PROJECT / safe_relative(env["lock_file"])
    if sha256(lock) != env["lock_file_sha256"]:
        raise RuntimeError("Frozen requirements lock differs.")
    if kind == "wheels":
        entries = [{"relative": safe_relative(row["local_path"]), "size": row["size"], "sha256": row["sha256"]} for row in env["files"]]
        if len(entries) != 51 or any(len(PurePosixPath(e["relative"]).parts) != 2 or not e["relative"].startswith("wheelhouse/") or not e["relative"].endswith(".whl") for e in entries):
            raise RuntimeError("Expected exactly the 51 frozen wheels.")
    elif kind == "models":
        manifest = json.loads(MODEL_MANIFEST.read_text())
        hashes = json.loads(HASH_EVIDENCE.read_text())
        if len(hashes) != 47 or {e["local_path"] for e in manifest["files"]} != set(hashes):
            raise RuntimeError("Model hash evidence must cover exactly the frozen 47 files.")
        entries = []
        for row in manifest["files"]:
            record = hashes[row["local_path"]]
            if (record["size"] != row["size"] or record["revision"] != row["revision"]
                    or (row.get("sha256") and row["sha256"] != record["sha256"])):
                raise RuntimeError("Model SHA/size/revision evidence is inconsistent.")
            entries.append({"relative": "models/" + safe_relative(row["local_path"]), "size": record["size"], "sha256": record["sha256"]})
    elif kind == "python":
        if ARCHIVE.is_symlink() or sha256(ARCHIVE) != ARCHIVE_SHA:
            raise RuntimeError("The local Python archive differs from its pinned SHA256.")
        entries = [{"relative": "setup/" + ARCHIVE.name, "size": ARCHIVE.stat().st_size, "sha256": ARCHIVE_SHA, "local_path": str(ARCHIVE)}]
    else:
        return []
    if len({e["relative"] for e in entries}) != len(entries):
        raise RuntimeError("Duplicate asset paths.")
    return entries


def append_ledger(record: dict[str, Any]) -> None:
    record = {"at": dt.datetime.now(dt.timezone.utc).isoformat(), **record}
    with (HERE / "node103_offline_ledger.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        out.flush()
        os.fsync(out.fileno())


REMOTE_COMMON = r'''
import ctypes,errno,fcntl,hashlib,json,os,pathlib,platform,pwd,shutil,stat,sys
SOURCE='/data2/zhangzibo/arxiv-tssa'
DEST='/data1/zhangzibo/arxiv-tssa'
assert pwd.getpwuid(os.getuid()).pw_name=='zhangzibo' and os.getuid()!=0, 'Only the personal non-root account is allowed'
def inside(p,root):
    return p==root or root in p.parents
def checked(root,relative,create=False):
    root=pathlib.Path(root); p=pathlib.PurePosixPath(relative)
    assert str(root) in (SOURCE,DEST) and not p.is_absolute() and '..' not in p.parts and str(p)==relative and relative
    assert all(ord(c)>=32 for c in relative) and '\\' not in relative
    own=root.parent
    assert own.is_dir() and not own.is_symlink() and own.stat().st_uid==os.getuid()
    if create: root.mkdir(mode=0o750,exist_ok=True)
    assert root.is_dir() and not root.is_symlink() and root.resolve()==root and root.stat().st_uid==os.getuid()
    assert root.stat().st_dev != pathlib.Path('/').stat().st_dev, 'Refuse system-disk destination'
    dest=root.joinpath(*p.parts)
    for parent in [root]+list(dest.parents)[::-1]:
        if inside(parent,root):
            if create: parent.mkdir(mode=0o750,exist_ok=True)
            assert parent.is_dir() and not parent.is_symlink() and parent.stat().st_uid==os.getuid() and not parent.stat().st_mode & stat.S_IWOTH
    assert not dest.is_symlink() and inside(dest.resolve(),root)
    if dest.exists(): assert dest.is_file() and dest.stat().st_uid==os.getuid() and not dest.stat().st_mode & stat.S_IWOTH
    return dest
def hashfile(path,prefix=None):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        remaining=prefix
        while remaining is None or remaining:
            b=f.read(8388608 if remaining is None else min(remaining,8388608))
            if not b:
                assert not remaining, 'File shorter than declared prefix'
                break
            h.update(b)
            if remaining is not None: remaining-=len(b)
    return h.hexdigest()
def publish_noreplace(source,dest):
    # Linux atomic rename with RENAME_NOREPLACE: never overwrite an existing asset.
    libc=ctypes.CDLL(None,use_errno=True)
    rename=libc.renameat2
    rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    rename.restype=ctypes.c_int
    if rename(-100,os.fsencode(source),-100,os.fsencode(dest),1):
        code=ctypes.get_errno(); raise OSError(code,os.strerror(code))
    fd=os.open(str(dest.parent),os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
def remote_lock():
    path=pathlib.Path(DEST)/'.node103-prepare.lock'
    assert not path.is_symlink()
    f=open(path,'a+')
    assert os.fstat(f.fileno()).st_uid==os.getuid()
    fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    return f
'''

REMOTE_PREFLIGHT = REMOTE_COMMON + r'''
root=pathlib.Path(DEST)
checked(DEST,'setup/preflight-placeholder',create=True)
assert platform.system()=='Linux' and platform.machine()=='x86_64'
libc,version=platform.libc_ver()
assert libc=='glibc' and tuple(int(x) for x in version.split('.')[:2])>=(2,28), 'Frozen wheels require glibc >= 2.28'
print(json.dumps({'user':pwd.getpwuid(os.getuid()).pw_name,'machine':platform.machine(),'glibc':version,'data_root':str(root),'free_bytes':shutil.disk_usage(root).free,'GPU_initialized':False}))
'''

REMOTE_DEST_INFO = REMOTE_COMMON + r'''
relative,total,expected=sys.argv[1],int(sys.argv[2]),sys.argv[3]
dest=checked(DEST,relative,create=True)
lock=remote_lock()
if dest.exists():
    actual=hashfile(dest)
    assert dest.stat().st_size==total and actual==expected, 'Existing target differs; do not overwrite'
    print(json.dumps({'complete':True,'size':total,'sha256':actual}))
else:
    partial=checked(DEST,relative+'.partial',create=True)
    assert not partial.exists() or partial.stat().st_nlink==1, 'Do not append to a hardlinked partial file'
    size=partial.stat().st_size if partial.exists() else 0
    assert size<=total and shutil.disk_usage(dest.parent).free>=total-size+2*1024**3, 'Invalid partial length or insufficient data-disk headroom'
    print(json.dumps({'complete':False,'prefix_size':size,'prefix_sha256':hashfile(partial) if partial.exists() else hashlib.sha256(b'').hexdigest()}))
'''

REMOTE_SOURCE_INFO = REMOTE_COMMON + r'''
relative,total,expected,prefix=sys.argv[1],int(sys.argv[2]),sys.argv[3],int(sys.argv[4])
source=checked(SOURCE,relative)
assert source.stat().st_size==total and 0<=prefix<=total
actual=hashfile(source)
assert actual==expected, 'Pinned source hash mismatch'
print(json.dumps({'sha256':actual,'size':total,'prefix_sha256':hashfile(source,prefix)}))
'''

REMOTE_READ = REMOTE_COMMON + r'''
source=checked(SOURCE,sys.argv[1]); offset,total=int(sys.argv[2]),int(sys.argv[3])
assert source.stat().st_size==total and 0<=offset<=total
with source.open('rb') as f:
    f.seek(offset); remaining=total-offset
    while remaining:
        block=f.read(min(1048576,remaining)); assert block, 'Source shortened during relay'
        sys.stdout.buffer.write(block); remaining-=len(block)
sys.stdout.buffer.flush()
'''

REMOTE_RECEIVE = REMOTE_COMMON + r'''
relative,offset,total,expected,prefix=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),sys.argv[4],sys.argv[5]
dest=checked(DEST,relative,create=True); partial=checked(DEST,relative+'.partial',create=True)
lock=remote_lock()
assert not partial.exists() or partial.stat().st_nlink==1, 'Do not append to a hardlinked partial file'
assert not dest.exists() and 0<=offset<=total
assert (partial.stat().st_size if partial.exists() else 0)==offset, 'Partial size changed during source verification'
assert (hashfile(partial) if partial.exists() else hashlib.sha256(b'').hexdigest())==prefix, 'Partial prefix changed'
fd=os.open(str(partial),os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o640)
with os.fdopen(fd,'ab') as out:
    info=os.fstat(out.fileno())
    assert info.st_uid==os.getuid() and stat.S_ISREG(info.st_mode) and info.st_nlink==1, 'Partial must be a private regular single-link file'
    remaining=total-offset
    while remaining:
        block=sys.stdin.buffer.read(min(1048576,remaining))
        assert block, 'SSH stream ended early; validated partial retained for explicit resume'
        out.write(block); remaining-=len(block)
    assert not sys.stdin.buffer.read(1), 'Unexpected excess bytes in relay'
    out.flush(); os.fsync(out.fileno())
assert partial.stat().st_size==total and hashfile(partial)==expected, 'Completed transfer SHA mismatch; preserve partial'
publish_noreplace(partial,dest)
print(json.dumps({'committed':True,'size':total,'sha256':expected,'relative':relative}))
'''


def archive_members_safe(members):
    """Reject tar traversal, special files, hardlinks and outward symlinks."""
    import posixpath
    from pathlib import PurePosixPath
    total = 0
    names = set()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "python" or str(path) != member.name.rstrip("/"):
            raise ValueError("Unsafe Python archive member path")
        if member.name.rstrip("/") in names or not (member.isfile() or member.isdir() or member.issym()):
            raise ValueError("Duplicate, special-file or hardlink archive member")
        names.add(member.name.rstrip("/"))
        if member.issym():
            target = posixpath.normpath(posixpath.join(str(path.parent), member.linkname))
            if member.linkname.startswith("/") or target == "python" or not target.startswith("python/"):
                raise ValueError("Python archive symlink escapes the private extraction tree")
        total += member.size
    if total > 2 * 1024**3 or len(names) > 30000:
        raise ValueError("Python archive exceeds its bounded extraction size")
    # No directory/file may be extracted through an archive-created symlink.
    symlinks = {str(PurePosixPath(m.name)) for m in members if m.issym()}
    for member in members:
        if any(str(parent) in symlinks for parent in PurePosixPath(member.name).parents):
            raise ValueError("Archive member descends through a symlink")
    return total


def python_install_source() -> str:
    return REMOTE_COMMON + "\n" + inspect.getsource(archive_members_safe) + r'''
import datetime,signal,subprocess,tarfile,tempfile
archive=checked(DEST,'setup/cpython-3.11.7-20240107-linux-x86_64.tar.gz')
assert hashfile(archive)=='4a51ce60007a6facf64e5495f4cf322e311ba9f39a8cd3f3e4c026eae488e140'
root=pathlib.Path(DEST); lock=remote_lock()
base=root/'python-standalone-3.11.7-20240107'; venv=root/'venv'; state=root/'setup/python_install_state.json'
def save(value):
    assert not state.is_symlink()
    with tempfile.NamedTemporaryFile(mode='w',dir=str(state.parent),prefix='.'+state.name+'-',delete=False) as f:
        tmp=pathlib.Path(f.name); json.dump(value,f,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,state)
def probe():
    assert base.is_dir() and not base.is_symlink() and base.stat().st_uid==os.getuid()
    assert venv.is_dir() and not venv.is_symlink() and venv.stat().st_uid==os.getuid()
    code="import json,sys,site,ssl,ctypes; print(json.dumps({'version':list(sys.version_info[:3]),'prefix':sys.prefix,'base_prefix':sys.base_prefix,'user_site':site.ENABLE_USER_SITE}))"
    env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','PIP_'))}
    env.update(CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none',PYTHONNOUSERSITE='1',PIP_NO_INDEX='1')
    result=subprocess.run([str(venv/'bin/python'),'-I','-c',code],capture_output=True,text=True,check=True,timeout=60,env=env)
    payload=json.loads(result.stdout)
    assert payload['version']==[3,11,7] and payload['prefix']==str(venv) and payload['base_prefix']==str(base) and payload['user_site'] is False
    return payload
if state.exists():
    old=json.loads(state.read_text())
    assert old['status']=='completed', 'Incomplete Python install preserved; manual audit required before any new attempt'
    assert old['archive_sha256']==hashfile(archive) and old['python_sha256']==hashfile(base/'bin/python3.11')
    print(json.dumps({'status':'already_installed_verified','probe':probe(),'CUDA_initialized':False})); sys.exit(0)
assert not base.exists() and not venv.exists(), 'Existing Python/venv without matching receipt cannot be adopted or overwritten'
save({'status':'started','archive_sha256':hashfile(archive),'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
try:
    staging=pathlib.Path(tempfile.mkdtemp(prefix='.python-stage-',dir=str(root)))
    with tarfile.open(str(archive),'r:gz') as tar:
        members=tar.getmembers(); expanded=archive_members_safe(members)
        assert shutil.disk_usage(root).free>expanded*2+2*1024**3
        # Validate every member before extracting, with symlinks installed last.
        for member in sorted(members,key=lambda m:(m.issym(),not m.isdir())):
            member.mode &= 0o777
            tar.extract(member,str(staging),set_attrs=True)
    publish_noreplace(staging/'python',base)
    env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','PIP_'))}
    env.update(CUDA_VISIBLE_DEVICES='',NVIDIA_VISIBLE_DEVICES='none',PYTHONNOUSERSITE='1',PIP_NO_INDEX='1')
    subprocess.run([str(base/'bin/python3.11'),'-I','-m','venv','--symlinks',str(venv)],check=True,timeout=180,env=env)
    report={'status':'completed','archive_sha256':hashfile(archive),'python_sha256':hashfile(base/'bin/python3.11'),'probe':probe(),'CUDA_initialized':False}
    save(report); print(json.dumps(report))
except BaseException as error:
    save({'status':'failed','archive_sha256':hashfile(archive),'error_type':type(error).__name__,'error':str(error),'partial_state_preserved':True})
    raise
'''


ENV_WRAPPER = '''#!/usr/bin/env python3
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
'''


def ssh_argv(config: Path, host: str, source: str, *args: Any, interpreter="python3") -> list[str]:
    if host not in ("school103", "school104"):
        raise ValueError("Only the two registered, fixed server aliases are allowed.")
    return ["ssh", "-F", str(config), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=60", "-o", "ConnectionAttempts=1", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=2", "-o", "ControlMaster=no", "-o", "ControlPath=none",
            host, shlex.join([interpreter, "-c", source, *map(str, args)])]


def remote_json(config: Path, host: str, source: str, *args: Any, timeout=METADATA_TIMEOUT) -> dict[str, Any]:
    result = subprocess.run(ssh_argv(config, host, source, *args), capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{host} SSH {result.returncode}: {result.stderr.decode(errors='replace')[-3000:]}")
    return json.loads(result.stdout)


def ensure_prefix(source: dict[str, Any], destination: dict[str, Any], entry: dict[str, Any]) -> int:
    if source["size"] != entry["size"] or source["sha256"] != entry["sha256"]:
        raise RuntimeError("Frozen source SHA/size does not match manifest.")
    offset = destination["prefix_size"]
    if not 0 <= offset <= entry["size"] or source["prefix_sha256"] != destination["prefix_sha256"]:
        raise RuntimeError("Destination partial is not the source prefix; preserve and stop.")
    return offset


def relay(config: Path, entry: dict[str, Any]) -> dict[str, Any]:
    relative, total, expected = entry["relative"], entry["size"], entry["sha256"]
    dest = remote_json(config, "school103", REMOTE_DEST_INFO, relative, total, expected)
    if dest["complete"]:
        return {"status": "verified_existing_target", "relative": relative, "sha256": expected, "size": total}
    if "local_path" in entry:
        path = Path(entry["local_path"])
        info = {"sha256": sha256(path), "size": path.stat().st_size, "prefix_sha256": sha256(path, dest["prefix_size"])}
    else:
        info = remote_json(config, "school104", REMOTE_SOURCE_INFO, relative, total, expected, dest["prefix_size"])
    offset = ensure_prefix(info, dest, entry)
    target_command = ssh_argv(config, "school103", REMOTE_RECEIVE, relative, offset, total, expected, dest["prefix_sha256"])
    source_process = target_process = local_stream = None
    # Stderr uses a small task-local temporary file; model bytes only traverse an OS pipe.
    with tempfile.TemporaryFile() as source_errors:
        try:
            if "local_path" in entry:
                local_stream = Path(entry["local_path"]).open("rb"); local_stream.seek(offset)
                source_stream = local_stream
            else:
                source_process = subprocess.Popen(ssh_argv(config, "school104", REMOTE_READ, relative, offset, total),
                                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=source_errors)
                source_stream = source_process.stdout
            target_process = subprocess.Popen(target_command, stdin=source_stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if source_process is not None:
                source_process.stdout.close()
            stdout, stderr = target_process.communicate(timeout=TRANSFER_TIMEOUT)
            if target_process.returncode:
                raise RuntimeError(f"Target relay SSH {target_process.returncode}: {stderr.decode(errors='replace')[-3000:]}")
            if source_process is not None:
                source_process.wait(timeout=30)
                if source_process.returncode:
                    source_errors.seek(0)
                    raise RuntimeError(f"Source relay SSH {source_process.returncode}: {source_errors.read()[-3000:].decode(errors='replace')}")
            record = json.loads(stdout)
            if record != {"committed": True, "size": total, "sha256": expected, "relative": relative}:
                raise RuntimeError("Atomic target receipt differs from expected hash/size.")
            return {"status": "transferred_verified", "resumed_from": offset, **record}
        finally:
            for process in (target_process, source_process):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=10)
            if local_stream is not None:
                local_stream.close()


def local_entry(path: Path, relative: str) -> dict[str, Any]:
    return {"relative": safe_relative(relative), "size": path.stat().st_size, "sha256": sha256(path), "local_path": str(path)}


def install_environment(config: Path) -> dict[str, Any]:
    env = json.loads(ENV_MANIFEST.read_text())
    lock = PROJECT / env["lock_file"]
    # Wrapper is new task-owned code; original installer is transmitted unchanged.
    wrapper = HERE / "node103_install_wrapper.py"
    expected = ENV_WRAPPER.encode()
    if wrapper.exists() and wrapper.read_bytes() != expected:
        raise RuntimeError("Existing wrapper differs; preserve it instead of overwriting.")
    if not wrapper.exists():
        with wrapper.open("xb") as f: f.write(expected); f.flush(); os.fsync(f.fileno())
    for path in (ENV_MANIFEST, lock, INSTALLER, wrapper):
        entry = local_entry(path, "setup/" + path.name)
        append_ledger({"stage": "install-env-inputs", "status": "started", "entry": {k:v for k,v in entry.items() if k!='local_path'}})
        result = relay(config, entry)
        append_ledger({"stage": "install-env-inputs", **result})
    source = REMOTE_COMMON + "\nimport subprocess\nchecked(DEST,'setup/node103_install_wrapper.py')\nlock=remote_lock()\n" + \
        "r=subprocess.run([DEST+'/venv/bin/python','-I',DEST+'/setup/node103_install_wrapper.py'],capture_output=True,text=True,timeout=3450)\n" + \
        "sys.stdout.write(r.stdout);sys.stderr.write(r.stderr);sys.exit(r.returncode)\n"
    return remote_json(config, "school103", source, timeout=3500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=STAGES)
    parser.add_argument("--dry-run", action="store_true", help="Validate fixed local identities and print plan; no SSH, locks, or writes.")
    args = parser.parse_args()
    entries = checked_entries(args.stage)
    plan = {"stage": args.stage, "source": "school104:" + SOURCE_ROOT, "destination": "school103:" + DEST_ROOT,
            "file_count": len(entries), "bytes": sum(e["size"] for e in entries), "files": [{k:v for k,v in e.items() if k!='local_path'} for e in entries],
            "streaming": True, "network_downloads": False, "GPU_initialization": False, "automatic_retry": False,
            "transfer_and_installation_separate": True, "script_sha256": sha256(Path(__file__))}
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2)); return
    lock_path = HERE / ".prepare_node103.lock"
    if lock_path.is_symlink(): raise RuntimeError("Local transfer lock may not be a symlink.")
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        append_ledger({"status": "stage_started", **plan})
        module_spec = importlib.util.spec_from_file_location("node103_stage_session", SESSION_SCRIPT)
        module = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(module)
        started = time.monotonic()
        try:
            with module.SchoolSession() as session:
                preflight = remote_json(session.config, "school103", REMOTE_PREFLIGHT)
                append_ledger({"stage": args.stage, "status": "CPU_platform_verified", "preflight": preflight})
                if args.stage in ("python", "wheels", "models"):
                    for entry in entries:
                        append_ledger({"stage": args.stage, "status": "file_started", "entry": {k:v for k,v in entry.items() if k!='local_path'}})
                        result = relay(session.config, entry)
                        append_ledger({"stage": args.stage, **result})
                        print(json.dumps(result), flush=True)
                elif args.stage == "install-python":
                    result = remote_json(session.config, "school103", python_install_source(), timeout=600)
                    append_ledger({"stage": args.stage, "result": result})
                    print(json.dumps(result), flush=True)
                else:
                    result = install_environment(session.config)
                    append_ledger({"stage": args.stage, "result": result})
                    print(json.dumps(result), flush=True)
            append_ledger({"stage": args.stage, "status": "stage_completed", "seconds": time.monotonic()-started})
        except BaseException as error:
            append_ledger({"stage": args.stage, "status": "failed_no_automatic_retry", "error_type": type(error).__name__,
                           "error": str(error), "seconds": time.monotonic()-started, "partial_files_and_existing_data_preserved": True})
            raise


if __name__ == "__main__":
    main()
