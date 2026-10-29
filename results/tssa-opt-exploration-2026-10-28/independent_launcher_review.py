"""Narrow independent checks for real launch contracts; no SSH/CUDA/children."""
from pathlib import Path
import ast, datetime, hashlib, importlib.util, json, os, stat, sys, tempfile, types, __future__
from unittest.mock import patch

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
path=HERE/'launch_image_search.py'; source=path.read_bytes()
spec=importlib.util.spec_from_file_location('review_launcher_final',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
runner_path=ROOT/'scripts/merging/tssa_image_search_run.py'
spec=importlib.util.spec_from_file_location('review_runner_cli',runner_path);r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
plan=json.loads((ROOT/m.PLAN_REL).read_text());checks=[]
def check(name,ok,**details):checks.append({'name':name,'passed':bool(ok),**details})

class ReachedStore(Exception):pass
seen=[]
def stop_store(path,identity,**options):
    seen.append({'run_root':str(path),'identity':identity,'options':options});raise ReachedStore()
for server in ('103','104'):
    base=Path(m.BASES[server]);code=base/'code/image-search-6913379cd01c';command=m.runner_command(base,code,base/'results'/m.RUN_NAME)
    with patch.object(sys,'argv',command[2:]),patch.object(r,'load_plan',return_value=(plan,{})),patch.object(r,'Store',side_effect=stop_store),patch.dict(os.environ,{},clear=True):
        try:r.main()
        except ReachedStore:pass
    check('real_runner_CLI_contract_'+server,seen[-1]['run_root']==str(base/'results'/m.RUN_NAME) and seen[-1]['identity']['scorer_device']=='cpu' and seen[-1]['options']=={'resume':False},command=command)

# Execute the frozen pre-CUDA checks with a sentinel at the first CUDA query.
runtime_path=ROOT/'scripts/merging/tssa_sd_runtime.py'
node=next(n for n in ast.parse(runtime_path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='require_allocated_cuda')
class BeforeCUDA(Exception):pass
def stop_cuda():raise BeforeCUDA()
import re
namespace={'os':os,'re':re,'torch':types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=stop_cuda))}
exec(compile(ast.Module(body=[node],type_ignores=[]),'frozen-pre-CUDA-contract','exec',flags=__future__.annotations.compiler_flag),namespace)
gpu_uuid='GPU-01234567-89ab-cdef-0123-456789abcdef'
environment=m.runner_environment(Path(m.BASES['103']),gpu_uuid,{'PYTHONPATH':'/wrong','CUDA_VISIBLE_DEVICES':'0','CUBLAS_WORKSPACE_CONFIG':':16:8','LD_PRELOAD':'bad.so'})
reached=False
with patch.dict(os.environ,environment,clear=True):
    try:namespace['require_allocated_cuda']()
    except BeforeCUDA:reached=True
check('real_runtime_environment_before_CUDA',reached and environment['CUBLAS_WORKSPACE_CONFIG']==':4096:8' and environment['HF_HUB_OFFLINE']=='1' and environment['TRANSFORMERS_OFFLINE']=='1' and 'PYTHONPATH' not in environment and 'LD_PRELOAD' not in environment)

tree=ast.parse(source,feature_version=(3,8));remote=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='remote_launch')
calls=[(n.lineno,ast.unparse(n.func)) for n in ast.walk(remote) if isinstance(n,ast.Call)]
order={name:min(line for line,func in calls if func==name) for name in ('prepare_runtime_directories','exclusive_json','subprocess.Popen')}
check('runtime_directories_before_target_claim_before_spawn',order['prepare_runtime_directories']<order['exclusive_json']<order['subprocess.Popen'],line_order=order)

with tempfile.TemporaryDirectory(prefix='launcher-independent-durability-') as folder:
    parent=Path(folder).resolve();control=parent/'launch-control';control.mkdir(mode=0o700)
    claim=control/('image-search-'+m.PLAN_SHA+'.claim.json');events=[];real_fsync=os.fsync
    def logged_fsync(fd):
        info=os.fstat(fd);events.append(('directory' if stat.S_ISDIR(info.st_mode) else 'file',info.st_ino));real_fsync(fd)
    with patch.object(m.os,'fsync',side_effect=logged_fsync):m.exclusive_json(claim,{'server':'104'})
    check('claim_file_then_parent_and_grandparent_fsynced',events==[('file',claim.stat().st_ino),('directory',control.stat().st_ino),('directory',parent.stat().st_ino)])
    blocked=False
    try:m.exclusive_json(claim,{'server':'103'})
    except FileExistsError:blocked=True
    check('same_plan_other_server_cannot_replace_permanent_claim',blocked and json.loads(claim.read_text())=={'server':'104'})
    failed=control/'failed-durability.claim.json';raised=False
    with patch.object(m,'fsync_directory',side_effect=OSError('simulated directory fsync failure')):
        try:m.exclusive_json(failed,{'server':'103'})
        except OSError:raised=True
    check('fsync_failure_propagates_and_retains_claim',raised and failed.exists())

now=datetime.datetime.now(datetime.timezone.utc);permission=m.permission_template('104')
permission.update(observed_at=now.isoformat(),sample_at=None,sample_time_basis='live_UI_without_timestamp',live_indicator=True,historical_sample=False,evidence_note='CPU fixture for explicit live UI with no shown sample timestamp',account_status='normal',gpu_index=0,gpu_uuid=gpu_uuid,gpu_disabled=False,sample_valid=True,server_maintenance=False,reservation_conflict=False,other_research_task=False,own_gpu_count_all_servers=0,pending_allocated_gpu_count_all_servers=0,effective_gpu_quota=4,direct_use_allowed=True)
m.validate_permission(permission,'104',now);rejections=[]
for updates in ({'historical_sample':True},{'sample_at':now.isoformat()},{'observed_at':(now-datetime.timedelta(seconds=121)).isoformat()}):
    try:m.validate_permission(dict(permission,**updates),'104',now)
    except m.GuardError:rejections.append(True)
    else:rejections.append(False)
check('explicit_live_UI_accepts_null_sample_but_rejects_history_fabrication_and_staleness',all(rejections))

evidence_path=HERE/'node104_graphics_identity_20261028T072313Z.json';evidence=json.loads(evidence_path.read_text())
graphics=evidence['result']['graphics_processes'];x=next(p for p in graphics if p['comm']=='Xwayland');g=next(p for p in graphics if p['comm']=='gnome-shell')
check('display_exceptions_match_actual_readonly_identity_evidence',x==m.XWAYLAND_104_GPU0 and m.allowed_display('104',0,dict(x,type='G')) and m.allowed_display('104',0,dict(g,type='G')),evidence_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest())
negative=[not m.allowed_display('104',1,dict(x,type='G')),not m.allowed_display('103',0,dict(x,type='G'))]
for mutation in ({'type':'C'},{'pid':7188},{'uid':126},{'account':'researcher'},{'argv':x['argv']+['--other']}):negative.append(not m.allowed_display('104',0,dict(x,type='G')|mutation))
check('Xwayland_exception_is_one_observed_GPU0_instance',all(negative))
check('frozen_scientific_plan_and_sources_unchanged',hashlib.sha256((ROOT/m.PLAN_REL).read_bytes()).hexdigest()==m.PLAN_SHA and all(hashlib.sha256((ROOT/'scripts/merging'/name).read_bytes()).hexdigest()==sha for name,sha in plan['source_hashes'].items()))
check('no_torch_import_or_real_CUDA','torch' not in sys.modules)

result={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'launcher_sha256':hashlib.sha256(source).hexdigest(),'frozen_plan_sha256':m.PLAN_SHA,'checks':checks,'passed':all(c['passed'] for c in checks),'must_fix':[] if all(c['passed'] for c in checks) else [c['name'] for c in checks if not c['passed']],'source_still_current':path.read_bytes()==source,'SSH_calls':0,'GPU_calls':0,'actual_child_processes':0,'permanent_live_claims_created':0,'scientific_images':0,'scope':'Targeted contract and new-delta review, not a rerun of the author 24-test suite. Same-Mac plan claim protects dispatch to103/104; no universal distributed coordinator claim.'}
(HERE/'independent_launcher_review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
