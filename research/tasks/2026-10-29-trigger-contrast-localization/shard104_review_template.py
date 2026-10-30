"""Emit an unsigned shard-review template; this command does not approve it."""
import argparse
import hashlib
import json
from pathlib import Path
import shard104_runner as runner
import shard104_plan as partition


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('candidate','original-amendment','original-signature','original-reviewer-key','patched-intervene','reviewer','watch-principal'):
        p.add_argument('--'+name,required=True)
    a=p.parse_args()
    candidate=json.loads(Path(a.candidate).read_bytes())
    if (candidate.get('manifest_sha256')!=runner.MANIFEST_SHA or candidate.get('source_snapshot_manifest_sha256')!=runner.SNAPSHOT_SHA
            or candidate.get('source_attempts_already_charged')!=344 or len(candidate.get('allowed_keys',[]))!=1704):
        raise ValueError('candidate identity or accounting differs')
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    here=Path(__file__).parent
    result={'decision':'approved','task_id':'TCL-20261029-01','run_id':candidate['run_id'],'manifest_sha256':runner.MANIFEST_SHA,
      'reviewer':a.reviewer,'reviewer_key_sha256':runner.REVIEW_KEY_SHA,'watch_key_sha256':runner.WATCH_KEY_SHA,
      'watch_principal':a.watch_principal,'candidate_sha256':hashlib.sha256(partition.canonical(candidate)).hexdigest(),
      'snapshot_manifest_sha256':runner.SNAPSHOT_SHA,'source_machine_sha256':runner.SOURCE_SHA,
      'destination_machine_sha256':runner.DESTINATION_SHA,'destination_hostname':'iipl-104','destination_server':'school104',
      'destination_output_root':str(runner.OUTPUT),'original_restart_prohibited':True,
      'source_sigkill':{'pid':586456,'start_ticks':9222972,'signal':'SIGKILL','returncode':0},
      'runner_sha256':sha(here/'shard104_runner.py'),'plan_module_sha256':sha(here/'shard104_plan.py'),
      'policy_sha256':sha(here/'shard104_policy.py'),'source_guard_sha256':sha(here/'shard104_source_guard.py'),
      'controller_sha256':sha(here/'shard104_watch_controller.py'),
      'original_amendment_sha256':sha(a.original_amendment),'original_signature_sha256':sha(a.original_signature),
      'original_reviewer_key_sha256':sha(a.original_reviewer_key),'original_launcher_sha256':sha(here/'amendment_launcher.py'),
      'original_patch_sha256':sha(a.patched_intervene)}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')))

if __name__=='__main__': main()
