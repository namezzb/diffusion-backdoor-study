"""Reconcile this wake from saved evidence; never infer scientific success."""
import datetime,hashlib,json,shutil
from pathlib import Path
ROOT=Path('/Users/zzb/arxiv');OUT=ROOT/'results/tssa-mvp-2026-10-26';STATE=ROOT/'server/gpu_monitor_state.json'
read=lambda p:json.loads(p.read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
now=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)));s=read(STATE)
def ref(name):
 p=OUT/name;return {'report':str(p.relative_to(ROOT)),'sha256':sha(p)}
accept=read(OUT/'full_model_transfer_acceptance_2026-10-27-160309-110550Z.json')
transfer=read(OUT/'remaining_model_transfer_2026-10-27-160026-326979Z.json')
bundle=read(OUT/'deployment_bundle_2026-10-28-configfix.json')
probe_name='server-probes/school104-20261027T155917602793Z.json';probe=read(OUT/probe_name)
formal_name='formal_CPU_preflight_2026-10-27-161330-135213Z.json';formal=read(OUT/formal_name)
checks_name='configfix_deployment_CPU_checks_2026-10-27-161216-935590Z.json';checks=read(OUT/checks_name)
s.update(observed_at=now.isoformat(),phase='formal_model_CPU_preparation',last_reported_event='all_47_assets_complete_and_configuration_check_corrected',ready_authorized_job=False,automatic_GPU_start_allowed=False,local_free_bytes=shutil.disk_usage(ROOT).free,local_free_observed_at=now.isoformat(),next_ssh_probe_not_before='2026-10-28T00:28:59+08:00')
s['server_probe'].update(ref(probe_name),status=probe['status'],started_at=probe['started_at'],finished_at=probe['finished_at'],sample_finished_at=probe['observation']['sample_finished_at'],driver_prohibited_indices=[],other_compute_process_indices=[0,1,2],other_graphics_process_indices=[0,1,2,3,4],observed_process_free_indices=[],own_gpu_count_on_this_server=0,own_gpu_count_complete=True)
s['last_valid_read_only_server_probe']=dict(s['server_probe'],current_GPU_permission=False)
s['latest_website_observation'].update(recorded_at=now.isoformat(),heartbeat_trigger_UTC='2026-10-27T15:58:59.674Z',status='browser_navigation_timed_out',body_read_status='Chrome Page.navigate timed out after10seconds during this wake; no portal contents obtained.',portal_application_reached=False,current_allocation_known=False,site_origin_health_now='unknown')
s['website_attempted_at']=None;s['latest_website_observation']['exact_navigation_timestamp_unavailable']=True;s['current_portal_state_available']=False
s['last_check_note']='47/47 full remote assets verified; compatibility checker corrected without protocol changes; no compliant GPU or platform allocation known.'
s['last_failed_model_transfer']['resolved_by']=str((OUT/'full_model_transfer_acceptance_2026-10-27-160309-110550Z.json').relative_to(ROOT))
s['remaining_model_transfer']=dict(transfer,active_pid=None,session_id=None,processes_confirmed_exited=True,verified_count=47,verified_bytes=accept['bytes'],current_relative_path=None,acceptance=ref('full_model_transfer_acceptance_2026-10-27-160309-110550Z.json'))
s['remaining_model_transfer']['bounded_awake']['status']='confirmed_exited_after_success'
if 'historical_asset_transfer' not in s:s['historical_asset_transfer']=s['asset_transfer']
s['asset_transfer']={'status':'complete','active_pid':None,'verified_file_count':47,'verified_bytes':accept['bytes'],'all_assets_ready':True,'acceptance':ref('full_model_transfer_acceptance_2026-10-27-160309-110550Z.json'),'scope':'Remote whole-file asset integrity only; CPU and CUDA readiness tracked separately.'}
s['completed_model_roles']={'sd15':14,'backdoor_tpa':2,'dreamshaper8':9,'openjourney':9,'vit':4,'clip':9,'scope':'All47 remote whole-file hashes accepted; no empirical performance conclusion.'}
s['local_model_support_prefetch'].update(remote_transferred=True,remote_transferred_count=15,all_support_files_remotely_transferred=True,local_staging_retained_for_sequential_upload=False)
s['local_process_check']=dict(ref('completed_preparation_processes_2026-10-28.json'),observed_at='2026-10-27T16:12:58.417861+00:00',verified_absent_PIDs=[77129,77161,77162,79649,86923])
s['next_transfer_plan']='No model transfer needed; all47 accepted. Do not restart the old failed transfer.'
s['implementation_correction']=ref('upcast_implementation_correction_2026-10-28.json')
s['failed_formal_CPU_preflight_preserved']=ref('formal_CPU_preflight_2026-10-27-160055-974677Z.json')
s['local_validation'].update(research_CPU_tests=59,evidence=str((OUT/'upcast_CPU_regression_after_fix_2026-10-28.log').relative_to(ROOT)),deployment_bundle=str((OUT/'deployment_bundle_2026-10-28-configfix.json').relative_to(ROOT)),deployment_uploaded=True,remote_source_verified=True,remote_source_root=bundle['suggested_remote_extract_root'],remote_source_evidence=str((OUT/checks_name).relative_to(ROOT)),GPU_tested=False)
s['remote_CPU_research_checks']=dict(ref(checks_name),status=checks['status'],test_count=59,source_files_verified=20,seconds=checks['seconds'],finished_at=checks['finished_at'],CUDA_tested=False,formal_checkpoint_tested=False)
s['formal_CPU_preflight']=dict(ref(formal_name),status=formal['status'],school_connection_attempted=True,model_loading_started=True,CUDA_initialized=False,source_script='results/tssa-mvp-2026-10-26/run_formal_cpu_preflight_2026-10-28-configfix.py',run_dir='/data2/zhangzibo/arxiv-tssa/results/mvp-2026-10-26-dual-v2-configfix',result=formal.get('result'),error=formal.get('error'),seconds=formal.get('seconds'),pid=formal['pid'] if formal['status']=='running_CPU_preflight' else None)
s['local_validation']['full_checkpoint_CPU_preflight_passed']=formal['status']=='passed'
s['local_validation']['full_checkpoint_tested']=formal['status']=='passed'
s['remote_environment_install']['CPU_research_tests_in_server_environment']='passed_59'
s['remote_environment_install']['full_models_loaded']=formal['status']=='passed'
s['readiness_blockers']=['formal_CUDA_preflight_pending','fresh_GPU_allocation_not_verified','current_portal_observation_unavailable','all_observed_GPUs_have_other_users_processes','GPU_inventory_changed_requires_fresh_platform_and_UUID_verification']
if formal['status']!='passed':s['readiness_blockers'].insert(0,'formal_checkpoint_CPU_preflight_'+formal['status'])
components=sorted(OUT.glob('remote_inference_components_2026-10-27-16*.json'))
if components:
 p=components[-1];r=read(p);s['CPU_inference_component_loading']=dict(ref(p.name),status=r['status'],result=r.get('result'),seconds=r['seconds'])
 if r['status']!='passed':s['readiness_blockers'].insert(0,'scorer_VAE_CPU_loading_failed')
else:s['readiness_blockers'].insert(0,'scorer_VAE_CPU_loading_pending')
s['CPU_preparation_readiness']=ref('CPU_preparation_readiness_2026-10-28.json')
s['phase']='CPU_preparation_complete_waiting_compliant_GPU_allocation'
s['next_preparation_action']='Next scheduled104probe and fresh platform/admin permission check; no asset downloads or CPU preflight rerun needed. Preserve the passed v2-configfix run and bind two fresh authorized UUIDs before resuming actual CUDA diagnostic and frozen research stages.'
s['research_execution'].update(valid_research_images=0,gradient_optimization_updates=0,candidate_results=[],a_b_trajectories=[],normal_metrics=None,ASR=None,GPU_time_seconds=0)
s['latest_heartbeat_notification']={'observed_at':now.isoformat(),'decision':'NOTIFY','reason':'All47 remote assets complete; strict config-check false rejection identified and corrected, CPU validation progressed; no scientific result yet.'}
p=OUT/f'heartbeat_checkpoint_{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d-%H%M%S-%fZ}.json'
record={'observed_at':now.isoformat(),'phase':s['phase'],'asset_acceptance':s['asset_transfer'],'formal_CPU_preflight':s['formal_CPU_preflight'],'implementation_correction':s['implementation_correction'],'server_probe':s['server_probe'],'website_observation':s['latest_website_observation'],'research_execution':s['research_execution'],'CPU_inference_component_loading':s.get('CPU_inference_component_loading'),'readiness_blockers':s['readiness_blockers'],'next_action':s['next_preparation_action']}
p.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
s['latest_preparation_checkpoint']=str(p.relative_to(ROOT));s['preparation_checkpoint_report']=str(p.relative_to(ROOT))
tmp=STATE.with_suffix('.json.tmp');tmp.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n');tmp.replace(STATE)
print(json.dumps({'checkpoint':str(p),'formal_CPU_preflight':formal['status'],'components':s.get('CPU_inference_component_loading',{}).get('status')},ensure_ascii=False))
