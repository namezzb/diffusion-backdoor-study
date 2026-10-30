"""Emit unsigned wait amendment for independent inspection and signature."""
import argparse
import json
from pathlib import Path
import shard104_policy as policy
import shard127_wait_launcher_v2 as launch

p=argparse.ArgumentParser(description=__doc__)
for name in ('reviewer','resource-review','resource-signature','shard-review-envelope','prior-wait-review','prior-wait-signature'):
    p.add_argument('--'+name,required=True)
a=p.parse_args(); here=Path(__file__).parent
files={'wait_launcher_sha256':here/'shard127_wait_launcher_v2.py','wait_patch_sha256':here/'shard127_watch_wait_v2.py',
       'prior_wait_launcher_sha256':here/'shard127_wait_launcher.py','prior_wait_patch_sha256':here/'shard127_watch_wait.py',
       'prior_wait_review_sha256':a.prior_wait_review,'prior_wait_signature_sha256':a.prior_wait_signature,
       'resource_launcher_sha256':here/'resource127_launcher.py','resource_overlay_sha256':here/'resource127_gdm_xorg_patch.py',
       'resource_review_sha256':a.resource_review,'resource_signature_sha256':a.resource_signature,
       'shard_review_envelope_sha256':a.shard_review_envelope,'shard_runner_sha256':here/'shard127_runner.py',
       'shard_policy_sha256':here/'shard104_policy.py','fence_policy_sha256':here/'shard127_policy.py',
       'watch_controller_sha256':here/'shard127_watch_controller.py'}
result={'decision':'approved','task_id':'TCL-20261029-01','run_id':'tcl-20261029-01-v1',
        'manifest_sha256':launch.MANIFEST_SHA,'server':'school127','reviewer':a.reviewer,'reviewer_key_sha256':launch.REVIEW_KEY_SHA,
        'watch_lifetime_seconds':30,'retry_window_seconds':90,'maximum_wait_seconds':120,
        'signature_cache_entries':4,'signature_cache_max_seconds':30,'scientific_replay':'prohibited'}
result['startup_watch_wait']=True
result.update({name:policy.sha(launch.read(path)) for name,path in files.items()})
print(json.dumps(result,sort_keys=True,separators=(',',':')))
