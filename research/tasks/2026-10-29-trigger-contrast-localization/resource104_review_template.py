"""Print unsigned 104 resource amendment; review and sign independently."""
import argparse
import json
from pathlib import Path
import resource104_launcher as launch
import shard104_policy as policy

p=argparse.ArgumentParser(description=__doc__)
for name in ('manifest','repository-root','reviewer'):
    p.add_argument('--'+name,required=True)
a=p.parse_args()
here=Path(__file__).parent
manifest=json.loads(launch.read(a.manifest)); original=launch.read(Path(a.repository_root)/launch.MODULE)
if (policy.sha(launch.read(a.manifest))!=launch.MANIFEST_SHA or manifest.get('code_sha256',{}).get(launch.MODULE)!=policy.sha(original)):
    raise ValueError('original resource gate differs from frozen manifest')
result={'decision':'approved','task_id':'TCL-20261029-01','run_id':'tcl-20261029-01-v1',
    'manifest_sha256':launch.MANIFEST_SHA,'server':'school104','reviewer':a.reviewer,'reviewer_key_sha256':launch.REVIEW_KEY_SHA,
    'original_resource_gate_sha256':policy.sha(original),'overlay_sha256':policy.sha(launch.read(here/'resource104_gdm_patch.py')),
    'launcher_sha256':policy.sha(launch.read(here/'resource104_launcher.py')),
    'shard_runner_sha256':policy.sha(launch.read(here/'shard104_runner.py')),
    'shard_policy_sha256':policy.sha(launch.read(here/'shard104_policy.py')),
    'allowed_account':'gdm','allowed_executable':'/usr/bin/gnome-shell','max_memory_mib':8}
print(json.dumps(result,sort_keys=True,separators=(',',':')))
