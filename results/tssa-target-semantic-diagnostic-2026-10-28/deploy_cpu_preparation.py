"""One bounded CPU-only preparation in a new owned directory on school103/104."""
from pathlib import Path
import argparse,base64,datetime as dt,hashlib,io,json,shlex,subprocess,sys,tarfile
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'server'),str(ROOT/'scripts/merging')]
from stage_school_assets import SchoolSession
from tssa_target_semantic_run import CODE_FILES
BASE=Path(__file__).parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--server',choices=('103','104'),default='104')
args=parser.parse_args()
remote_base={'103':'/data1/zhangzibo/arxiv-tssa','104':'/data2/zhangzibo/arxiv-tssa'}[args.server]
stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
out=BASE/('cpu_preparation_'+stamp);out.mkdir(mode=0o700)
remote=remote_base+'/preparations/target-semantic-'+stamp
cache=BASE/'cache_retrieval_20261028T115206383909Z/cache'
files={'scripts/merging/'+n:(ROOT/'scripts/merging'/n).read_bytes() for n in CODE_FILES}
for p in (ROOT/'scripts/merging').glob('test_tssa_target_semantic_*.py'):files['scripts/merging/'+p.name]=p.read_bytes()
files['scripts/merging/test_tssa_sd_runtime_integration.py']=(ROOT/'scripts/merging/test_tssa_sd_runtime_integration.py').read_bytes()
for name in ['tssa_mvp_2026-10-26.json','tssa_mvp_assets_2026-10-26.json']:files['research/'+name]=(ROOT/'research'/name).read_bytes()
for p in cache.rglob('*'):
 if p.is_file():files['cache/'+str(p.relative_to(cache))]=p.read_bytes()
manifest={n:{'sha256':hashlib.sha256(b).hexdigest(),'size':len(b)} for n,b in files.items()}
files['bundle_manifest.json']=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()
buffer=io.BytesIO()
with tarfile.open(fileobj=buffer,mode='w') as tar:
 for name,raw in files.items():
  m=tarfile.TarInfo(name);m.size=len(raw);m.mode=0o600;tar.addfile(m,io.BytesIO(raw))
payload=buffer.getvalue();(out/'bundle.tar').write_bytes(payload)
remote_source=r'''
import base64,hashlib,io,json,os,pathlib,subprocess,sys,tarfile
root=pathlib.Path(sys.argv[1]);expected=sys.argv[2]
assert root.parent in (pathlib.Path('/data2/zhangzibo/arxiv-tssa/preparations'),pathlib.Path('/data1/zhangzibo/arxiv-tssa/preparations'))
assert root.parent.parent.resolve()==root.parent.parent and root.parent.parent.stat().st_uid==os.getuid()
root.parent.mkdir(mode=0o700,exist_ok=True)
assert not root.parent.is_symlink() and root.parent.stat().st_uid==os.getuid()
root.mkdir(mode=0o700)
raw=sys.stdin.buffer.read(4*1024*1024+1)
assert len(raw)<=4*1024*1024 and hashlib.sha256(raw).hexdigest()==expected
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as tar:
 members=tar.getmembers();assert len(members)<64 and len({m.name for m in members})==len(members)
 for m in members:
  p=pathlib.PurePosixPath(m.name);assert not p.is_absolute() and '..' not in p.parts and m.isfile() and m.size<2*1024**2
  dest=root.joinpath(*p.parts);dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  with dest.open('xb') as f:f.write(tar.extractfile(m).read())
manifest=json.loads((root/'bundle_manifest.json').read_text())
for name,item in manifest.items():
 b=(root/name).read_bytes();assert len(b)==item['size'] and hashlib.sha256(b).hexdigest()==item['sha256']
env=dict(os.environ,CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',TOKENIZERS_PARALLELISM='false',PYTHONDONTWRITEBYTECODE='1')
python=str(root.parent.parent/'venv/bin/python')
report={'remote_root':str(root),'machine_id_sha256':hashlib.sha256(pathlib.Path('/etc/machine-id').read_bytes()).hexdigest(),'bundle_sha256':expected,'no_gpu':True}
with (root/'cpu_tests.log').open('xb') as log:
 test=subprocess.run([python,'-B','-m','unittest','discover','-s',str(root/'scripts/merging'),'-p','test_tssa_target_semantic_*.py','-v'],env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=90)
report['tests_exit_code']=test.returncode
if test.returncode==0:
 with (root/'cpu_preflight.log').open('xb') as log:
  result=subprocess.run([python,'-B',str(root/'scripts/merging/tssa_target_semantic_run.py'),'cpu-preflight','--old-protocol',str(root/'research/tssa_mvp_2026-10-26.json'),'--asset-manifest',str(root/'research/tssa_mvp_assets_2026-10-26.json'),'--models-root',str(root.parent.parent/'models'),'--cache-root',str(root/'cache'),'--output',str(root/'cpu_preflight.json')],env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=420)
 report['preflight_exit_code']=result.returncode
report['returned_files']={}
for name in ('cpu_tests.log','cpu_preflight.log','cpu_preflight.json'):
 p=root/name
 if p.exists():
  b=p.read_bytes();assert len(b)<1024*1024
  report['returned_files'][name]={'sha256':hashlib.sha256(b).hexdigest(),'size':len(b),'base64':base64.b64encode(b).decode()}
report['status']='passed' if report.get('preflight_exit_code')==0 else 'failed'
(root/'deployment_report.json').write_text(json.dumps({k:v for k,v in report.items() if k!='returned_files'},indent=2)+'\n')
print(json.dumps(report))
'''
report={'status':'started','server':args.server,'remote_root':remote,'bundle_sha256':hashlib.sha256(payload).hexdigest(),'timeout_seconds':600,'cuda_visible_devices':''}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
session=None
try:
 session=SchoolSession().__enter__()
 command=shlex.join(['python3','-c',remote_source,remote,report['bundle_sha256']])
 result=subprocess.run(['ssh','-F',str(session.config),'-o','ControlMaster=no','-o','ControlPath=none','-o','ConnectionAttempts=1','-o','ConnectTimeout=60','school'+args.server,command],input=payload,capture_output=True,timeout=600)
 (out/'ssh_stderr.txt').write_bytes(result.stderr)
 result.check_returncode();data=json.loads(result.stdout)
 for name,entry in data.pop('returned_files').items():
  raw=base64.b64decode(entry['base64'],validate=True)
  assert hashlib.sha256(raw).hexdigest()==entry['sha256'] and len(raw)==entry['size']
  (out/name).write_bytes(raw)
 report.update(data)
except BaseException as exc:
 report.update(status='failed',error_type=type(exc).__name__,error=str(exc));raise
finally:
 if session is not None:session.temporary.cleanup()
 report['finished_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'report':str(out/'report.json'),**report}))
