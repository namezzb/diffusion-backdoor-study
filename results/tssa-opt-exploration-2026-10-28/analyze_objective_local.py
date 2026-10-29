"""Read-only analysis of completed v2 artifacts; no torch, network or GPU."""
from pathlib import Path
import json, hashlib, collections, statistics, datetime
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
B=ROOT/'results/tssa-mvp-2026-10-26/single_run_observation_20261028T060221238162Z_artifacts'
paths={
 'trace':B/'per_step_coefficients_and_losses.jsonl',
 'candidate_metrics':B/'candidate_response_and_image_metrics.json',
 'selection':B/'candidate_selection.json',
 'gpu_diagnostic':B/'gpu_diagnostic.json',
 'gradient_core':ROOT/'scripts/merging/tssa_gradient_core.py',
 'runtime':ROOT/'scripts/merging/tssa_sd_runtime.py',
 'runner':ROOT/'scripts/merging/tssa_mvp_run.py',
 'protocol':ROOT/'research/tssa_mvp_2026-10-26.json',
 'proposal':ROOT/'research/tssa_response_calibration_method_proposal.md',
 'final_report':ROOT/'results/tssa-mvp-2026-10-26/initial_validation_report_2026-10-28.md',
 'adam_audit':ROOT/'results/tssa-mvp-2026-10-26/training_trace_audit_20261028T0332Z.json',
}
evidence={k:{'path':str(v.relative_to(ROOT)),'sha256':hashlib.sha256(v.read_bytes()).hexdigest(),'bytes':v.stat().st_size} for k,v in paths.items()}
rows=[json.loads(s) for s in paths['trace'].read_text().splitlines()]
metrics=json.loads(paths['candidate_metrics'].read_text())
selection=json.loads(paths['selection'].read_text())
diag=json.loads(paths['gpu_diagnostic'].read_text())
responses=metrics['responses']['candidates']
zero=responses['RC-TSSA-GD_step24']; naive=responses['naive']
families={}
for family in ['Uniform-GD','TSSA-GD','RC-TSSA-GD']:
 rr=[r for r in rows if r['family']==family]
 ties=[]
 for row in rr:
  vals=[s['backdoor'] for s in row['details']['states'] if s['backdoor'] is not None]
  ties.append(sum(x==max(vals) for x in vals))
 families[family]={
  'updates':len(rr), 'active_backdoor_counts':dict(collections.Counter(r['details']['active_backdoor_index'] for r in rr)),
  'active_normal_counts':dict(collections.Counter(r['details']['active_normal_index'] for r in rr)),
  'three_way_backdoor_exact_ties':sum(t==3 for t in ties),
  'first_after_zero':{name:next((r['step'] for r in rr if r['coefficients'][i]==0),None) for i,name in enumerate(['a','b'])},
  'after_zero_counts':{name:sum(r['coefficients'][i]==0 for r in rr) for i,name in enumerate(['a','b'])},
  'negative_gradient_but_after_zero_counts':[sum(r['details']['gradient'][i]<0 and r['details']['coefficients_after'][i]==0 for r in rr) for i in range(len(rr[0]['details']['gradient']))],
  'mean_observed_objective_by_timestep':{s:statistics.mean(r['details']['objective'] for r in rr if r['unit_id'].endswith(s)) for s in ['01','13','25']},
 }
candidate_table=[]
for name in ['RC-TSSA-GD_step24','TSSA-GD_step24','naive','Uniform4','Uniform16','TSSA16']:
 c=selection['candidate_table'][name]
 candidate_table.append({'name':name,**responses[name],'development_ASR_mean':c['mean_development_ASR'],'development_ASR_min':c['minimum_development_ASR'],'normal_response_passed':c['normal_response_gate']['passed'],'image_utility_passed':c['image_utility_gate']['passed'],'failed_image_states':{k:v for k,v in c['image_utility_gate']['states'].items() if not v['passed']}})
assert all(x==0 for k,x in zero['normal_mse'].items() if k!='upload')
assert len(set(zero['backdoor_mse'].values()))==1
bound={'zero_attack_term':zero['R'],'zero_normal_term':zero['normal_mse']['upload'],'naive_attack_lower_bound':naive['R'],'naive_normal_lower_bound':max(naive['normal_mse'].values()),'intercept_lower_bound':naive['R']-zero['R'],'beta_coefficient_lower_bound':max(naive['normal_mse'].values())-zero['normal_mse']['upload'],'naive_mean_state_attack':statistics.mean(naive['backdoor_mse'].values()),'zero_mean_state_attack':zero['R'],'naive_J_beta1':naive['J_beta'],'zero_J_beta1':zero['J_beta'],'meaning':'For every beta>=0, completed-fit J_beta(naive)-J_beta(zero) is at least intercept_lower_bound + beta*beta_coefficient_lower_bound; this compares two endpoints only, not a global minimum or a rerun with changed beta.'}
assert bound['intercept_lower_bound']>0 and bound['beta_coefficient_lower_bound']>0
new_objective={
 'status':'proposal_only_not_implemented_or_validated',
 'parameterization':'same fixed Delta_A, Delta_B and 0<=a,b<=32; new run identity only',
 'minimal_primary_change':'replace original-source double-difference target with a fixed same-merged-model semantic target for the triggered conditional prediction',
 'target_prompt':'predeclare fit context-preserving normal dog->cat replacement; no future heldout outputs used',
 'target':'T_xi,u = F_matched_clean_xi(z_u,t_u,p_target_u), cached once at same merged UNet/TE and exact CFG/batch/precision',
 'attack_objective':'mean_xi mean_u ||F_student_xi(s)(p_trigger_u)-T_xi,u||^2/d; initially unnormalized so denominator choices cannot hide a numerical floor',
 'normal_constraints':'retain paired p and extra q normal responses and existing per-state normal response limits; retain matched-clean normal ACC/CLIP image gates, including upload',
 'selection_rule':'include naive and all proposed frozen candidates in new development panel; require normal gates and strictly higher predeclared development ASR than naive before selecting for fresh untouched confirmation',
 'aggregation_caution':'Use mean over fixed development conditions initially; changing max alone cannot repair the demonstrated endpoint ordering of the old target. Optional normalization must be frozen after fit-only geometry diagnostics and tracked as a separate ablation.',
 'optimizer_caution':'Start at (1,1), log each state attack/normal gradient separately, use a small predeclared step/trust region with a finite acceptance check; this is not evidence the new target succeeds.',
 'numerical_correction':'constant text-encoder prompt layout for clean/backdoor/merged/student including upload; execute only needed UNet branches without changing TE batch shape',
}
hypotheses=[
 {'id':'H1','title':'Original-source response target is mismatched to the merged denoising geometry','evidence':'B_star is evaluated with original clean UNet while student and matched-clean use each merged UNet; all three naive attack MSE means exceed zero endpoint despite nonzero naive ASR. This is a deliberate old definition, not a proved coding error.','falsifier':'On six fixed fit units measure candidate response norms, inner products/cosines with source B_star and same-merged semantic targets at predeclared points; if source-target projection is positive and old loss consistently ranks stronger ASR candidates ahead of clean on an independent diagnostic panel, this explanation weakens.','priority':1},
 {'id':'H2','title':'The proxy has a finite low-loss clean endpoint even without normal penalty','evidence':'Computed lower bound is strictly positive for every beta>=0; averaged-state attack loss also favors zero. Reducing beta or moving max outside the mean alone cannot reverse these two endpoint rankings.','falsifier':'Existing arithmetic is reproducible from committed summaries; a distinct nonzero candidate could still beat zero, so fit-only local surface and finite directional derivatives must test that possibility.','priority':1},
 {'id':'H3','title':'One coefficient pair must repair weak merges while preserving upload utility; feasible space may be narrow','evidence':'Uniform4 has development ASR mean 0.8333 and all three merged image utility gates pass, but upload ACC drop0.125 and CLIP drop1.0626 fail. TSSA16 reaches ASR1 but fails normal at high alpha/upload, while naive itself fails development image utility.','falsifier':'A finite predeclared two-dimensional response/normal surface plus fresh image validation finds coefficients that pass every normal gate and beat naive; otherwise do not claim two-scalar feasibility based on an unconstrained ASR increase.','priority':2},
 {'id':'H4','title':'Noisy per-unit Adam with eta0.25 and box projection amplifies collapse and masks useful candidate times','evidence':'Only steps24/48 were eligible and both collapse; many negative-gradient updates remain at zero due to momentum. Zero ties choose first attack state, explaining much apparent low-alpha dominance; raw per-state gradients are not in the trace.','falsifier':'A fixed-point full-fit gradient decomposition and small deterministic step shows the same descent direction and no attack/normal feasible descent at nonzero coefficients; then reducing eta alone is not a remedy.','priority':3},
 {'id':'H5','title':'Numerical response mismatch and incomplete gradient coverage can affect near-boundary behavior','evidence':'Zero upload normal MSE is1.58875e-5 while all merged normal losses are0; teacher TE batch4 and upload student batch3 differ. Original diagnostic checked only fit_pair00, first timestep, alpha0.25, (1,1), total loss, finite-difference h0.0625 and tolerance25%, not per-term/all-state/boundary gradients.','falsifier':'Constant-layout matched forward reproduces zero exactly and finite differences over predeclared interior plus one-sided boundary steps agree for each attack/normal term; still this alone cannot explain or reverse the much larger old objective endpoint gap.','priority':2},
]
diags={
 'status':'requirements_for_new_executor_not_a_claim_of_existing_CLI',
 'gpu_launch_requires':'parent verifies current allocation/direct-use permission, UUID and no other user process before running; no GPU or SSH performed by this audit',
 'phase1_forward_geometry':{'units':['fit_unit_p00_s01','fit_unit_p00_s13','fit_unit_p00_s25','fit_unit_p04_s01','fit_unit_p04_s13','fit_unit_p04_s25'],'points':[[0,0],[1,1],[2,1],[4,1],[4,0.5],[4,0],[8,0.25]],'states':['Edev_0.08','Edev_0.25','Edev_0.50','upload'],'new_fixed_target_branches':36,'student_branches':840,'branch_NFE_total':876,'images':0,'updates':0,'forward_basis':'Each of 7*6*4 calls executes constant-layout five response branches, including upload trigger diagnostically; 6*3 semantic targets each need unconditional+target branches. Existing validated trajectory cache reused; any rebuild cost recorded separately.','required_output':['candidate/state/unit loss terms','response and target norms','source-target and semantic-target inner products/cosines','exact zero identity residuals by state','gradient-free model/asset/trajectory hashes']},
 'phase2_term_gradients':{'only_after':'phase1 validates matching numerical operator and non-negligible semantic target signal','units':['fit_unit_p00_s13','fit_unit_p04_s13'],'points':[[0,0],[1,1],[4,0.5]],'states':['Edev_0.08','Edev_0.25','Edev_0.50','upload'],'forward_branches_for_gradients':120,'autograd_calls_upper_bound':60,'updates':0,'required_output':['g_attack_old,g_attack_semantic,g_normal separately for a/b','active-state ties','per-state and aggregate candidate feasible-direction tests','frozen parameter gradients absent']},
 'finite_difference_requirement':'Predeclare two step sizes at representative interior point and one-sided steps at boundary; per-term derivative checks need a separate finite branch-NFE cap in the new manifest, cannot hide their costs inside the above 996-forward cap.',
 'command_interface_requirements':['--mode objective-geometry or --mode term-gradients','--protocol <new frozen manifest>','--source-run-dir <old read-only run>','--run-dir <new isolated directory>','--expected-gpu-uuid <freshly authorized UUID>','--max-forward-branch-nfe <frozen phase cap>','--max-images 0','--max-optimizer-updates 0','--offline-only'],
 'completion_gate':'Before training, new target must not prefer zero solely by construction and must provide a feasible descent direction with normal constraints; no success inference until fresh frozen candidate-versus-naive image evaluation.',
}
report={'schema':'tssa_objective_diagnosis_v1','created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'task':'read-only objective diagnosis after completed v2 negative result','new_gpu_work_performed':False,'network_or_ssh_performed':False,'old_files_modified':False,'evidence':evidence,'facts':{'training_rows':len(rows),'candidate_table':candidate_table,'families':families,'endpoint_beta_bound':bound,'gradient_diagnostic_scope':{'pair':'fit_pair_00','timestep_index_1based':1,'state':'Edev_0.25','coefficients':[1,1],'term':'attack+normal','h':diag['central_difference_h'],'comparison':diag['gradient_comparison']}},'hypotheses':hypotheses,'recommended_new_objective':new_objective,'bounded_diagnostic_requirements':diags,'not_proven':['zero global optimum','beta term causes collapse by gradient dominance','two-scalar feasible superiority exists','new semantic target improves ASR','batch size is sole numerical mismatch cause','same prompts from old heldout can be treated as untouched confirmation again']}
(OUT/'objective_diagnosis.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'output':str(OUT/'objective_diagnosis.json'),'beta_bound':bound,'training_rows':len(rows)},ensure_ascii=False,indent=2))
