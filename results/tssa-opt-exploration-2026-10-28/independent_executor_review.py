"""CPU-only independent checks of the bounded image-search contract.
All synthetic image files live in a TemporaryDirectory and are deleted; no scientific output.
"""
from pathlib import Path
import json, hashlib, types, sys, copy, tempfile, datetime, subprocess, math
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
source_path=ROOT/'scripts/merging/tssa_image_search_run.py'
source=source_path.read_bytes(); m=types.ModuleType('review_image_search');m.__file__=str(source_path)
sys.modules[m.__name__]=m; exec(compile(source,str(source_path),'exec'),m.__dict__)
plan_path=ROOT/'research/tssa_optimization_exploration_2026-10-28.json'
plan=json.loads(plan_path.read_text()); old=json.loads((ROOT/'research/tssa_mvp_2026-10-26.json').read_text())
checks=[]; final_delta_checks=[]
def check(name,condition):
 checks.append({'name':name,'passed':bool(condition)})
def raises(name,fn,cls=m.IntegrityError):
 try:fn()
 except cls:check(name,True)
 else:check(name,False)
counts=m.validate_plan(plan,old)
check('stage_counts_624_240_576',counts=={'search':624,'dev':240,'confirm':576})
check('exact_maximum_image_budget',sum(counts.values())==plan['max_images']==1440)
check('no_torch_import_for_validation','torch' not in sys.modules)
for label,mutate in [
 ('old_prompt_leak',lambda p:p['stages']['search']['rows'][0].update(prompt=old['prompts']['fit']['pairs'][0]['normal'],normal_prompt=old['prompts']['fit']['pairs'][0]['normal'])),
 ('cross_stage_seed_leak',lambda p:p['stages']['confirm']['rows'][0].update(seed=p['stages']['dev']['rows'][0]['seed'])),
 ('normal_gate_relaxed',lambda p:p['thresholds'].update(accuracy_drop_max=.1)),
 ('budget_too_small',lambda p:p.update(max_images=1439)),
 ('duplicate_candidate',lambda p:p['candidates'].update(duplicate=[1,1])),
 ('unseen_expert_in_search',lambda p:p['stages']['search']['conditions'].__setitem__(0,old['merging']['heldout_states'][1])),
]:
 changed=copy.deepcopy(plan);mutate(changed);raises(label,lambda changed=changed:m.validate_plan(changed,old))

def records_for(stage,names,normal_errors=None,clip_delta=None):
 rows=[]; normal_errors=normal_errors or {}; clip_delta=clip_delta or {}
 for c in plan['stages'][stage]['conditions']:
  for name in names:
   normal_seen=0; attack_seen=0
   for row in plan['stages'][stage]['rows']:
    if row['triggered']:
     hit=name!='clean' and (name!='naive' or attack_seen%2==0);attack_seen+=1
     label=281 if hit else 151
    else:
     label=row['expected_class_ids'][0] if normal_seen>=normal_errors.get(name,0) else 0
     normal_seen+=1
    rows.append({'candidate':name,'condition_id':c['id'],'row':row,'coefficients':[0,0] if name=='clean' else plan['candidates'][name],'stage':stage,'score':{'vit_class':label,'clip_score':30.-clip_delta.get(name,0)},'seconds':0.0})
 return rows
names=['clean','naive','uniform_125']
summary=m.summarize(plan,'dev',names,records_for('dev',names))
check('positive_case_all_normal_and_ASR_gates',m.select(plan,'dev',summary)['selected']==['uniform_125'])
summary_bad=m.summarize(plan,'dev',names,records_for('dev',names,normal_errors={'uniform_125':1}))
check('one_error_in_8_fails_normal',not summary_bad['candidates']['uniform_125']['normal_pass'])
summary_bad=m.summarize(plan,'dev',names,records_for('dev',names,clip_delta={'uniform_125':1.0001}))
check('clip_drop_above_1_fails',not summary_bad['candidates']['uniform_125']['normal_pass'])
summary_confirm=m.summarize(plan,'confirm',names,records_for('confirm',names,normal_errors={'uniform_125':1}))
check('one_error_in_32_permitted',summary_confirm['candidates']['uniform_125']['normal_pass'])
summary_confirm2=m.summarize(plan,'confirm',names,records_for('confirm',names,normal_errors={'uniform_125':2}))
check('two_errors_in_32_rejected',not summary_confirm2['candidates']['uniform_125']['normal_pass'])
changed=records_for('dev',names);changed.pop();raises('missing_sample_rejected',lambda:m.summarize(plan,'dev',names,changed))
changed=records_for('dev',names);changed.append(changed[0]);raises('duplicate_sample_rejected',lambda:m.summarize(plan,'dev',names,changed))
# Important counterexample: first utility-ranked candidate violates worst ASR,
# but second candidate satisfies both promotion requirements.
manual={'ranked_eligible':['uniform_150','uniform_125'],'candidates':{
 'uniform_150':{'macro_difference_vs_naive':.2,'worst_difference_vs_naive':-.25},
 'uniform_125':{'macro_difference_vs_naive':.1,'worst_difference_vs_naive':0.}}}
check('filter_complete_promotion_before_taking_top',m.select(plan,'dev',manual)['selected']==['uniform_125'])

class Fake:
 def __init__(self):self.calls=0;self.last=None;self.unlocked=False
 def sample(self,task):
  if task['stage']=='confirm' and not self.unlocked:raise AssertionError('confirm not frozen before sampling')
  self.last=task;self.calls+=1;return Image.new('RGB',(1,1),(255,0,0))
 def score(self,image,text):
  t=self.last;r=t['row'];name=t['candidate']
  if r['triggered']:
   # Same deterministic pair outcomes at every condition.
   pair=int(r['pair_id'].rsplit('_',1)[1])
   hit=name!='clean' and (name!='naive' or pair%2==0)
   return {'vit_class':281 if hit else 151,'clip_score':30.}
  return {'vit_class':r['expected_class_ids'][0],'clip_score':30.}
 def resources(self):return {'synthetic_samples':self.calls,'optimizer_updates':0}
 def metadata(self):return {'synthetic_only':True}
 def unlock_heldout(self,values):self.unlocked=True
identity={'max_images':1440,'test':'independent_cpu_mock_not_scientific','source_sha256':hashlib.sha256(source).hexdigest()}
with tempfile.TemporaryDirectory(prefix='tssa-independent-review-') as tmp:
 root=Path(tmp)/'run';store=m.Store(root,identity);backend=Fake();runner=m.Runner(plan,store,lambda:backend)
 first=runner.execute('search');store.close()
 store=m.Store(root,identity,resume=True);second_backend=Fake();runner=m.Runner(plan,store,lambda:second_backend)
 report=runner.execute();check('mock_full_three_stage_path',report['confirmed_observed_improvement'] and report['completed_images']==1440)
 check('no_duplicate_generation',backend.calls+second_backend.calls==1440)
 last_resources=report['per_execution_last_resources']
 final_delta_checks.append({'name':'two_executions_preserve_last_cumulative_resources_without_double_count','passed':first['completed_images']==624 and backend.calls==624 and second_backend.calls==816 and len(last_resources)==2 and sorted(r['synthetic_samples'] for r in last_resources.values())==[624,816]})
 stage_seconds=[store.artifact(stage+'_summary.json')['generation_and_scoring_seconds'] for stage in m.STAGES]
 final_delta_checks.append({'name':'final_elapsed_equals_sum_of_committed_unique_receipts_and_stage_totals','passed':math.isclose(report['generation_and_scoring_seconds'],sum(r['record']['seconds'] for r in store.receipts.values()),rel_tol=1e-12) and math.isclose(report['generation_and_scoring_seconds'],sum(stage_seconds),rel_tol=1e-12)})
 final_delta_checks.append({'name':'each_receipt_resource_snapshot_and_execution_binding_integrity','passed':all(r['record']['execution_id'] in last_resources and r['record']['resources_current_process']['synthetic_samples']<=last_resources[r['record']['execution_id']]['synthetic_samples'] and r['record_sha256']==m.digest(r['record']) for r in store.receipts.values())})
 store.close()
 store=m.Store(root,identity,resume=True)
 def forbidden():raise AssertionError('resumed complete run loaded backend')
 resumed=m.Runner(plan,store,forbidden).execute();check('completed_resume_no_backend',resumed==report);store.close()
 # Corrupt completed PNG; matching receipt cannot mask it.
 first=next((root/'images').rglob('*.png'));first.write_bytes(b'corruption')
 raises('png_corruption_rejected_on_resume',lambda:m.Store(root,identity,resume=True))
with tempfile.TemporaryDirectory(prefix='tssa-independent-inflight-') as tmp:
 root=Path(tmp);store=m.Store(root,identity)
 task={'stage':'search','candidate':'naive','condition':plan['stages']['search']['conditions'][0],'row':plan['stages']['search']['rows'][0],'coefficients':[1,1]}
 class Broken(Fake):
  def sample(self,t):raise RuntimeError('simulated crash before image')
 try:store.perform(task,Broken())
 except RuntimeError:pass
 store.close();raises('inflight_cannot_auto_replay',lambda:m.Store(root,identity,resume=True),m.InflightOperation)
with tempfile.TemporaryDirectory(prefix='tssa-independent-scorer-binding-') as tmp:
 frozen=copy.deepcopy(plan);frozen['source_hashes']={n:m.file_hash(source_path.parent/n) for n in m.SOURCE_FILES}
 temporary_plan=Path(tmp)/'cpu-check-only-plan.json';temporary_plan.write_text(json.dumps(frozen))
 cli=[sys.executable,str(source_path),'check','--plan',str(temporary_plan),'--old-protocol',str(ROOT/'research/tssa_mvp_2026-10-26.json'),'--asset-manifest',str(ROOT/'research/tssa_mvp_assets_2026-10-26.json')]
 ok=subprocess.run(cli,check=False,capture_output=True,text=True)
 payload=json.loads(ok.stdout) if ok.returncode==0 else {}
 rejected=subprocess.run(cli+['--scorer-device','cuda'],check=False,capture_output=True,text=True)
 final_delta_checks.append({'name':'default_cpu_scorer_is_immutable_identity_field','passed':ok.returncode==0 and payload.get('scorer_device')=='cpu' and payload.get('models_loaded') is False and payload.get('CUDA_initialized') is False})
 final_delta_checks.append({'name':'CLI_cuda_mismatch_rejected_before_check_or_backend','passed':rejected.returncode!=0 and 'scorer device must match the frozen plan' in rejected.stderr})
report={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_path':str(source_path.relative_to(ROOT)),'source_sha256':hashlib.sha256(source).hexdigest(),'plan_sha256':hashlib.sha256(plan_path.read_bytes()).hexdigest(),'checks':checks,'final_delta_checks':final_delta_checks,'passed':all(x['passed'] for x in checks+final_delta_checks),'failed':[x['name'] for x in checks+final_delta_checks if not x['passed']],'simulation_only':True,'GPU_or_SSH_used':False,'scientific_samples_generated':0,'old_files_modified':False,'review_source_still_current':source_path.read_bytes()==source}
out=Path(__file__).parent/'independent_executor_review.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
