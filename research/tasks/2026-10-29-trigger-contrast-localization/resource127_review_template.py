"""Print unsigned 127 resource amendment; review and sign independently."""
import argparse
import json
from pathlib import Path
import resource127_launcher as launch
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
    'manifest_sha256':launch.MANIFEST_SHA,'server':'school127','reviewer':a.reviewer,'reviewer_key_sha256':launch.REVIEW_KEY_SHA,
    'original_resource_gate_sha256':policy.sha(original),'overlay_sha256':policy.sha(launch.read(here/'resource127_gdm_xorg_patch.py')),
    'launcher_sha256':policy.sha(launch.read(here/'resource127_launcher.py')),
    'shard_runner_sha256':policy.sha(launch.read(here/'shard127_runner.py')),
    'shard_policy_sha256':policy.sha(launch.read(here/'shard104_policy.py')),'fence_policy_sha256':policy.sha(launch.read(here/'shard127_policy.py')),
    'allowed_account':'gdm','allowed_executable':'/usr/lib/xorg/Xorg','max_memory_mib':8,
    'gdm_uid':128,'gdm_gid':132,'xorg_file_uid':0,'xorg_file_gid':0,'xorg_file_mode':'0755','xorg_file_inode':27265194,
    'destination_machine_sha256':'99b0f2a4634566cc13b4686bcfad863346e6975d37221fb1fc27ebb0d814848d',
    'gpu_uuid':'GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91'}
print(json.dumps(result,sort_keys=True,separators=(',',':')))
