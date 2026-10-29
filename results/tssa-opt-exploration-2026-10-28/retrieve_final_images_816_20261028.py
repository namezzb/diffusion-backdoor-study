"""Retrieve the completed 816 PNGs once and verify against immutable receipts."""
import datetime as dt, hashlib, json, os, shlex, subprocess, sys, tarfile
from pathlib import Path, PurePosixPath
HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
OBS=HERE/'observation_103_20261028T111524087743Z-7268ad87/report.json'
report=json.loads(OBS.read_text());expected={}
for name,meta in report['result']['files'].items():
 if name.startswith('run/operations/'):
  raw=(OBS.parent/'artifacts'/name).read_bytes();assert hashlib.sha256(raw).hexdigest()==meta['sha256']
  rec=json.loads(raw);assert rec['status']=='completed'
  record=rec['record'];assert record['image_path'] not in expected
  expected[record['image_path']]=record['image_sha256']
assert len(expected)==816
folder=HERE/'final_images_816_20261028';folder.mkdir(mode=0o700)
archive=folder/'images.tar';result={'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'read_only_remote':True,'GPU_launch':False,'source_observation_sha256':hashlib.sha256(OBS.read_bytes()).hexdigest(),'expected_images':816}
sys.path.insert(0,str(ROOT/'server'));from stage_school_assets import SchoolSession
try:
 with SchoolSession() as session:
  command=shlex.join(['tar','-C','/data1/zhangzibo/arxiv-tssa/results/tssa-opt-exploration-2026-10-28-v1','-cf','-','images'])
  with archive.open('xb') as target:
   r=subprocess.run(['ssh','-F',str(session.config),'-o','ControlMaster=no','-o','ControlPath=none','school103',command],stdout=target,stderr=subprocess.PIPE,timeout=240)
  result.update(returncode=r.returncode,stderr=r.stderr.decode(errors='replace')[-2000:])
  if r.returncode:raise RuntimeError('Read-only image retrieval failed')
 result['archive_bytes']=archive.stat().st_size
 assert result['archive_bytes']<400*1024*1024
 h=hashlib.sha256()
 with archive.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 result['archive_sha256']=h.hexdigest();verified={}
 with tarfile.open(archive,'r:') as tf:
  for item in tf:
   name=item.name;p=PurePosixPath(name)
   assert not p.is_absolute() and '..' not in p.parts and p.parts[0]=='images'
   if item.isdir():continue
   assert item.isreg() and name in expected and name not in verified and item.size<=16*1024*1024
   raw=tf.extractfile(item).read(16*1024*1024+1);assert len(raw)==item.size
   sha=hashlib.sha256(raw).hexdigest();assert sha==expected[name]
   destination=folder/name;destination.parent.mkdir(parents=True,exist_ok=True)
   with destination.open('xb') as f:f.write(raw)
   verified[name]={'sha256':sha,'bytes':len(raw)}
 assert set(verified)==set(expected)
 result.update(status='all816_images_downloaded_hash_verified',verified_images=len(verified),image_bytes=sum(v['bytes'] for v in verified.values()),images=verified,temporary_archive_retained=True)
except Exception as exc:result.update(status='failed_preserved_for_audit',error=type(exc).__name__+': '+str(exc))
result['finished_at']=dt.datetime.now(dt.timezone.utc).isoformat()
with (folder/'retrieval_report.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
print(json.dumps({k:v for k,v in result.items() if k!='images'},ensure_ascii=False,indent=2))
