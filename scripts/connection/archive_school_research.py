"""Read-only research backup with hash-based reuse; never allocates a GPU.

Original remote paths are preserved beneath results/server-archive-2026-10-29.
Existing verified local evidence is referenced by relative symlink, not copied.
Public models, dependencies and temporary staging areas are inventoried separately.
"""
from pathlib import Path, PurePosixPath
import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / 'results/organization-2026-10-29'
DEST = ROOT / 'results/server-archive-2026-10-29'
BASES = {'104': '/data2/zhangzibo/arxiv-tssa', '103': '/data1/zhangzibo/arxiv-tssa'}
FOLDERS = ['results', 'code', 'preparations', 'logs', 'manifests', 'inputs', 'claims', 'launch-control', 'setup']
sys.path.insert(0, str(ROOT / 'server'))
from stage_school_assets import SchoolSession


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def ssh(config, server):
    return ['ssh', '-F', str(config), '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
            '-o', 'ServerAliveInterval=20', '-o', 'ServerAliveCountMax=3', 'school' + server]


REMOTE = r'''
import os,sys,json,pathlib,stat,hashlib,datetime,pwd
root=pathlib.Path(sys.argv[1]); folders=json.loads(sys.argv[2]); uid=os.getuid()
assert pwd.getpwuid(uid).pw_name=='zhangzibo' and root.stat().st_uid==uid
files=[];links=[];errors=[];excluded=[]
def record(p, hashed):
 st=p.lstat();rel=str(p.relative_to(root))
 if stat.S_ISLNK(st.st_mode):links.append({'path':rel,'target':os.readlink(str(p))});return
 if not stat.S_ISREG(st.st_mode):return
 assert st.st_uid==uid, 'nonowned file: '+rel
 item={'path':rel,'bytes':st.st_size,'mtime_ns':st.st_mtime_ns}
 if hashed:
  h=hashlib.sha256()
  with p.open('rb') as f:
   for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
  after=p.stat();assert (st.st_size,st.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'file changed: '+rel
  item['sha256']=h.hexdigest();files.append(item)
 else:excluded.append(item)
for dirname in folders+['models']:
 base=root/dirname
 if not base.exists():continue
 for folder,ds,fs in os.walk(str(base),followlinks=False):
  ds[:]=[d for d in ds if d not in ['__pycache__','.git','venv','.venv','node_modules']]
  for name in sorted(fs):
   p=pathlib.Path(folder)/name
   # Large public checkpoints remain reproducible from the frozen asset manifest.
   hashed=dirname!='models' or p.suffix in ['.json','.txt','.md','.yaml','.yml']
   record(p,hashed)
for p in root.iterdir():
 if p.is_file() and not p.is_symlink():record(p,True)
print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'root':str(root),'files':files,
 'symlinks':links,'errors':errors,'public_model_payloads_not_copied':excluded,
 'excluded_categories':['venv','wheelhouse','python-standalone','cache','incoming','tmp'],
 'count':len(files),'bytes':sum(f['bytes'] for f in files)}))
'''


def manifest(server):
    path = AUDIT / ('server' + server + '_hash_manifest.json')
    if path.exists():
        raise RuntimeError('Manifest already exists; reuse it without a new remote inventory')
    with SchoolSession() as session:
        result = subprocess.run(ssh(session.config, server) + [shlex.join(['python3', '-c', REMOTE, BASES[server], json.dumps(FOLDERS)])],
                                capture_output=True, text=True, timeout=240)
    if result.returncode:
        save(AUDIT / ('server' + server + '_hash_failure.json'), {'returncode':result.returncode,'stderr':result.stderr[-2000:]})
        raise RuntimeError('Remote read-only inventory failed; no automatic retry')
    data = json.loads(result.stdout)
    data.update(server=server, read_only=True, models_policy='Payload not copied; fixed revision and SHA in research/tssa_mvp_assets_2026-10-26.json')
    save(path, data)
    print(json.dumps({'manifest': str(path), 'count': data['count'], 'bytes':data['bytes'],
                      'public_model_bytes_not_copied': sum(x['bytes'] for x in data['public_model_payloads_not_copied'])}), flush=True)


def retrieve(server, local_only=False):
    manifest_path = AUDIT / ('server' + server + '_hash_manifest.json')
    data = json.loads(manifest_path.read_text())
    target = DEST / ('server' + server)
    target.mkdir(parents=True, exist_ok=True)
    wanted = {}
    for row in data['files']:
        p = PurePosixPath(row['path'])
        assert not p.is_absolute() and '..' not in p.parts and '\n' not in row['path']
        assert p.parts[0] in FOLDERS + ['models'] or len(p.parts)==1
        wanted[row['path']] = row
    keys = {(x['bytes'], x['sha256']) for x in wanted.values()}
    sizes = {k[0] for k in keys}
    local = {}
    # Reuse only files under this research repository, not unrelated user data.
    for base in [ROOT/'results', ROOT/'research', ROOT/'scripts', ROOT/'server']:
        for folder, ds, fs in os.walk(base, followlinks=False):
            ds[:]=[d for d in ds if d not in ['__pycache__','.git','venv','.venv','node_modules','server-archive-2026-10-29']]
            for name in fs:
                p=Path(folder)/name
                if p.is_symlink() or not p.is_file():continue
                size=p.stat().st_size
                if size not in sizes:continue
                key=(size,digest(p))
                if key in keys:local.setdefault(key,p)
    verified={}; missing=[]
    for name,row in wanted.items():
        dest=target/name;key=(row['bytes'],row['sha256'])
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists() or dest.is_symlink():
            assert dest.resolve().is_relative_to(ROOT) and dest.stat().st_size==row['bytes'] and digest(dest)==row['sha256'], str(dest)
            verified[name]={'method':'already_verified','sha256':row['sha256'],'bytes':row['bytes']}
            local.setdefault(key,dest)
        elif key in local:
            # Tiny metadata/source copies are independent; large immutable evidence is shared by link.
            if row['bytes']<65536:
                shutil.copyfile(local[key],dest);method='local_copy'
            else:
                dest.symlink_to(os.path.relpath(local[key],dest.parent));method='local_reference'
            verified[name]={'method':method,'sha256':row['sha256'],'bytes':row['bytes'],'source':str(local[key].relative_to(ROOT))}
        else:missing.append(name)
    # Remote duplicate content needs only one transfer.
    unique={}; aliases={}
    for name in missing:
        row=wanted[name];key=(row['bytes'],row['sha256'])
        if key in unique:aliases[name]=unique[key]
        else:unique[key]=name
    download=list(unique.values());needed=sum(wanted[n]['bytes'] for n in download)
    free=shutil.disk_usage(ROOT).free
    report={'server':server,'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'manifest_sha256':digest(manifest_path),
            'remote_read_only':True,'GPU_started':False,'files':verified,'new_unique_files':len(download),'new_unique_bytes':needed,
            'local_free_before':free,'status':'transferring','remote_aliases':aliases,
            'missing_files':{n:wanted[n] for n in missing},'required_reserve_bytes':1024**3}
    report_path=AUDIT/('server'+server+'_retrieval.json');save(report_path,report)
    print(json.dumps({'server':server,'existing_or_reused':len(verified),'new_unique_files':len(download),'new_unique_bytes':needed,'aliases':len(aliases)}),flush=True)
    if local_only or free-needed<1024**3:
        report.update(status='local_mapping_only' if local_only else 'blocked_disk_reserve',
                      verified_files=len(verified),local_free_after=shutil.disk_usage(ROOT).free,
                      additional_space_needed=max(0,needed+1024**3-free))
        save(report_path,report)
        if not local_only:raise RuntimeError('Insufficient disk to retain 1 GiB reserve; missing-file inventory saved')
        return
    proc=None
    try:
        if download:
            with SchoolSession() as session:
                cmd=shlex.join(['tar','-C',BASES[server],'-czf','-','--verbatim-files-from','-T','-'])
                stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                errors=AUDIT/('server'+server+'_transfer_stderr_'+stamp+'.log')
                report['transport_stderr_path']=str(errors.relative_to(ROOT))
                filelist=AUDIT/('server'+server+'_transfer_paths.txt');filelist.write_text('\n'.join(download)+'\n')
                with errors.open('wb') as err, filelist.open('rb') as inp:
                    proc=subprocess.Popen(ssh(session.config,server)+[cmd],stdin=inp,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
                    signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('Bounded transfer timed out')))
                    signal.alarm(3600)
                    with tarfile.open(fileobj=proc.stdout,mode='r|gz') as archive:
                        for member in archive:
                            name=member.name
                            assert member.isfile() and name in download and name not in verified, name
                            row=wanted[name];assert member.size==row['bytes']
                            dest=target/name;part=dest.with_name(dest.name+'.backup-part')
                            if shutil.disk_usage(ROOT).free-row['bytes']<1024**3:
                                raise RuntimeError('Disk reserve would be exceeded; verified downloads preserved')
                            h=hashlib.sha256();count=0
                            with archive.extractfile(member) as src, part.open('xb') as out:
                                while True:
                                    block=src.read(1024*1024)
                                    if not block:break
                                    out.write(block);h.update(block);count+=len(block)
                            assert count==row['bytes'] and h.hexdigest()==row['sha256'],name
                            part.replace(dest)
                            verified[name]={'method':'remote_download','sha256':row['sha256'],'bytes':count}
                            if len(verified)%150==0:
                                save(report_path,report)
                                print(json.dumps({'server':server,'verified':len(verified),'of':len(wanted)}),flush=True)
                    rc=proc.wait(timeout=20);signal.alarm(0)
                    assert rc==0,'SSH/tar exit '+str(rc)
        for name,other in aliases.items():
            source=target/other;dest=target/name
            assert source.exists() and digest(source)==wanted[name]['sha256']
            dest.symlink_to(os.path.relpath(source,dest.parent))
            verified[name]={'method':'same_backup_reference','source':other,'sha256':wanted[name]['sha256'],'bytes':wanted[name]['bytes']}
        assert set(verified)==set(wanted)
        report['status']='complete_hash_verified'
        report['missing_files']={}
    except BaseException as exc:
        report.update(status='partial_failure_preserved',error=type(exc).__name__+': '+str(exc))
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
        if proc is not None:
            report['transport_returncode']=proc.wait(timeout=20)
        if report.get('transport_stderr_path'):
            report['transport_stderr']=(ROOT/report['transport_stderr_path']).read_text(errors='replace')[-4000:]
        raise
    finally:
        signal.alarm(0)
        report.update(finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),verified_files=len(verified),local_free_after=shutil.disk_usage(ROOT).free,
                      missing_files={n:r for n,r in wanted.items() if n not in verified})
        save(report_path,report)
        history=AUDIT/('server'+server+'_retrieval_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
        save(history,report)
    print(json.dumps({k:v for k,v in report.items() if k not in ['files','remote_aliases']}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['manifest','retrieve','map-local']);p.add_argument('--server',choices=BASES,required=True)
    args=p.parse_args()
    if args.mode=='manifest':manifest(args.server)
    else:retrieve(args.server,local_only=args.mode=='map-local')
