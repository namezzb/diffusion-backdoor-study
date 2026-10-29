"""One-shot launch of the separately frozen bounded diagnostic; never resumes."""
from pathlib import Path
import argparse,base64,datetime as dt,hashlib,json,os,shlex,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'server'),str(ROOT/'scripts/merging')]
from stage_school_assets import SchoolSession
from tssa_target_semantic_run import PLAN_ID,LIMITS,inputs,validate_plan
from tssa_target_semantic_gates import budget_enumeration
from tssa_target_semantic_cache import canonical,sha
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--preparation',type=Path,required=True)
p.add_argument('--permission',type=Path,required=True)
p.add_argument('--execute',action='store_true')
a=p.parse_args();folder=a.preparation.parent;prep=json.loads(a.preparation.read_text());preflight=json.loads((folder/'cpu_preflight.json').read_text())
assert prep['status']=='passed';server=prep['server'];base={'103':'/data1/zhangzibo/arxiv-tssa','104':'/data2/zhangzibo/arxiv-tssa'}[server]
remote=prep['remote_root'];assert remote.startswith(base+'/preparations/target-semantic-')
permission=json.loads(a.permission.read_text());assert permission['server']==server
binding,_=inputs(ROOT/'research/tssa_mvp_2026-10-26.json',ROOT/'research/tssa_mvp_assets_2026-10-26.json',Path(__file__).parent/'cache_retrieval_20261028T115206383909Z/cache')
plan={'schema_version':1,'id':PLAN_ID,'status':'frozen','binding':binding,'preflight_sha256':sha(canonical(preflight)),'budget':LIMITS,'operations':budget_enumeration(),'wall_seconds_max':1800,'automatic_retry':False,'images':0,'optimizer_updates':0,'new_trajectories':0,'execution':{'server':server,'machine_id_sha256':prep['machine_id_sha256'],'run_root':base+'/results/'+PLAN_ID,'claim_path':base+'/claims/'+PLAN_ID+'.json','gpu_uuid':permission['gpu_uuid']}}
validate_plan(plan,binding,preflight)
command=[base+'/venv/bin/python','-B',remote+'/scripts/merging/tssa_target_semantic_run.py','run','--old-protocol',remote+'/research/tssa_mvp_2026-10-26.json','--asset-manifest',remote+'/research/tssa_mvp_assets_2026-10-26.json','--cache-root',remote+'/cache','--models-root',base+'/models','--preflight',remote+'/cpu_preflight.json','--plan',remote+'/launch/plan.json','--permission',remote+'/launch/permission.json','--output',plan['execution']['run_root']]
payload={'plan':plan,'permission':permission,'command':command,'preparation':remote}
if not a.execute:
 print(json.dumps({'status':'prepared_locally','plan_sha256':sha(canonical(plan)),'command':command,'budget':LIMITS}));sys.exit()
local=Path(__file__).parent/'launch_20261029';local.mkdir(mode=0o700)
for name,value in [('plan.json',plan),('permission.json',permission),('claim.json',{'at':dt.datetime.now(dt.timezone.utc).isoformat(),'server':server,'plan_sha256':sha(canonical(plan)),'automatic_retry':False})]:
 with (local/name).open('xb') as f:f.write(canonical(value))
source=r'''
import base64,datetime as dt,hashlib,json,os,pathlib,shlex,subprocess,sys
payload=json.loads(sys.stdin.buffer.read(1024*1024));plan=payload['plan'];permission=payload['permission'];root=pathlib.Path(payload['preparation']);base=root.parent.parent
assert base in (pathlib.Path('/data1/zhangzibo/arxiv-tssa'),pathlib.Path('/data2/zhangzibo/arxiv-tssa'))
assert base.resolve()==base and base.stat().st_uid==os.getuid()
os.environ['CUDA_VISIBLE_DEVICES']=permission['gpu_uuid'];os.environ['GPU_UUID']=permission['gpu_uuid']
sys.path.insert(0,str(root/'scripts/merging'))
import tssa_target_semantic_run as runner
from tssa_target_semantic_cache import canonical,sha
binding,_=runner.inputs(root/'research/tssa_mvp_2026-10-26.json',root/'research/tssa_mvp_assets_2026-10-26.json',root/'cache')
preflight=json.loads((root/'cpu_preflight.json').read_text());runner.validate_plan(plan,binding,preflight)
assert sha(pathlib.Path('/etc/machine-id').read_bytes())==plan['execution']['machine_id_sha256']
assert not pathlib.Path(plan['execution']['claim_path']).exists() and not pathlib.Path(plan['execution']['run_root']).exists()
for proc in pathlib.Path('/proc').iterdir():
 if not proc.name.isdecimal():continue
 try:
  if proc.stat().st_uid!=os.getuid():continue
  args=(proc/'cmdline').read_bytes().split(b'\0')
  assert not (str(root/'scripts/merging/tssa_target_semantic_run.py').encode() in args and b'run' in args),'Existing diagnostic process'
 except (FileNotFoundError,ProcessLookupError,PermissionError):continue
live=runner.verify_permission(permission)
launch=root/'launch';launch.mkdir(mode=0o700)
for name,value in [('plan.json',plan),('permission.json',permission),('prelaunch_sample.json',live)]:runner.write_json(launch/name,value)
env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',CUBLAS_WORKSPACE_CONFIG=':4096:8',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',TOKENIZERS_PARALLELISM='false',PYTHONDONTWRITEBYTECODE='1')
log=launch/'execution.log'
with log.open('xb') as out:
 child=subprocess.Popen(payload['command'],cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
receipt={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'server':plan['execution']['server'],'pid':child.pid,'start_ticks':(pathlib.Path('/proc')/str(child.pid)/'stat').read_text().rsplit(')',1)[1].split()[19],'boot_id':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'plan_sha256':sha(canonical(plan)),'run_root':plan['execution']['run_root'],'preparation':str(root),'command':payload['command'],'gpu_uuid':permission['gpu_uuid'],'log':str(log),'automatic_retry':False}
runner.write_json(launch/'receipt.json',receipt);print(json.dumps(receipt))
'''
try:
 with SchoolSession() as s:
  result=subprocess.run(['ssh','-F',str(s.config),'-o','ControlMaster=no','-o','ControlPath=none','school'+server,shlex.join([base+'/venv/bin/python','-I','-c',source])],input=json.dumps(payload).encode(),capture_output=True,timeout=90)
 (local/'ssh_stderr.txt').write_bytes(result.stderr);result.check_returncode();receipt=json.loads(result.stdout)
 (local/'receipt.json').write_bytes(canonical(receipt));print(json.dumps(receipt))
except BaseException as e:
 (local/'launch_error.json').write_text(json.dumps({'error':repr(e),'at':dt.datetime.now(dt.timezone.utc).isoformat(),'automatic_retry':False})+'\n');raise
