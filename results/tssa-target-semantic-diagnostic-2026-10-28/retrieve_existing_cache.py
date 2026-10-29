"""One bounded read-only source connection; no GPU or remote file mutation."""
from pathlib import Path
import datetime as dt
import hashlib, io, json, shlex, subprocess, sys, tarfile
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'server'),str(ROOT/'scripts/merging')]
from stage_school_assets import SchoolSession
from tssa_target_semantic_cache import MAX_TOTAL,SOURCE_ROOT,verify_folder
base=Path(__file__).parent
stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
out=base/('cache_retrieval_'+stamp);out.mkdir(mode=0o700)
source=(ROOT/'scripts/merging/tssa_target_semantic_cache.py').read_bytes()
report={'status':'started','source_server':'104','source_root':SOURCE_ROOT,'script_sha256':hashlib.sha256(source).hexdigest(),'timeout_seconds':180,'no_remote_mutation':True,'cuda_visible_devices':''}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
session=None
try:
 session=SchoolSession().__enter__()
 command=shlex.join(['env','CUDA_VISIBLE_DEVICES=','OMP_NUM_THREADS=1','MKL_NUM_THREADS=1','/data2/zhangzibo/arxiv-tssa/venv/bin/python','-I','-B','-','--export-existing',SOURCE_ROOT])
 with (out/'source.tar').open('xb') as stream:
  result=subprocess.run(['ssh','-F',str(session.config),'-o','ControlMaster=no','-o','ControlPath=none','-o','ConnectionAttempts=1','-o','ConnectTimeout=60','school104',command],input=source,stdout=stream,stderr=subprocess.PIPE,timeout=180)
 (out/'stderr.txt').write_bytes(result.stderr)
 result.check_returncode()
 archive=out/'source.tar'
 if not 0<archive.stat().st_size<=MAX_TOTAL+102400:raise ValueError('Tar exceeds bound')
 folder=out/'cache';folder.mkdir(mode=0o700)
 with tarfile.open(archive,'r:') as tar:
  members=tar.getmembers(); names=[m.name for m in members]
  if len(names)!=len(set(names)) or len(names)>32:raise ValueError('Unexpected members')
  total=0
  for m in members:
   p=Path(m.name)
   if p.is_absolute() or '..' in p.parts or not m.isfile() or m.size>2*1024**2:raise ValueError('Unsafe member')
   total+=m.size
   if total>MAX_TOTAL:raise ValueError('Oversized archive')
   dest=folder/p;dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
   with dest.open('xb') as f:f.write(tar.extractfile(m).read())
 audit=verify_folder(folder)
 report.update(status='verified',files=len(audit['files']),latents=len(audit['cache']),archive_bytes=archive.stat().st_size,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),cache_audit_sha256=hashlib.sha256((folder/'cache_audit.json').read_bytes()).hexdigest(),cuda_initialized=False,model_calls=0,new_trajectories=0)
except BaseException as exc:
 report.update(status='failed',error_type=type(exc).__name__,error=str(exc))
 raise
finally:
 if session is not None:session.temporary.cleanup()
 report['finished_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'report':str(out/'report.json'),**report}))
