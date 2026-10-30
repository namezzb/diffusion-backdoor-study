"""Authenticate a separate 127 GPU-process policy overlay before shard runner."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import shard104_policy as policy

MANIFEST_SHA='c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa'
REVIEW_KEY_SHA='dc477cfe4e08a3196925fc6607391c1862676bc9d8d7b5900bdd8a272e25227b'
MODULE='scripts/merging/trigger_contrast_localization/resource_gate.py'


def permit_directory(output):
    root=Path(output)
    if root.is_symlink() or not root.is_dir() or root.stat().st_uid!=os.geteuid():
        raise ValueError('shard output directory is not owned and safe')
    parent=root/'resource_permit_attempts'
    try: parent.mkdir(mode=0o700)
    except FileExistsError: pass
    if parent.is_symlink() or not parent.is_dir() or parent.stat().st_uid!=os.geteuid():
        raise ValueError('resource permit directory is not owned and safe')
    return Path(tempfile.mkdtemp(prefix='permit-',dir=parent))


def read(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file(): raise ValueError('expected regular reviewed file')
    return path.read_bytes()


def verify(manifest_path, root, overlay_path, review_path, sig_path, key_path):
    manifest_bytes=read(manifest_path); manifest=json.loads(manifest_bytes)
    review_bytes=read(review_path); review=json.loads(review_bytes)
    key=read(key_path)
    policy.verify_signature(review_bytes,read(sig_path),key,REVIEW_KEY_SHA,review.get('reviewer',''),'tcl-resource-amendment')
    root=Path(root).resolve(strict=True)
    original_path=root/MODULE
    if not original_path.resolve(strict=True).is_relative_to(root): raise ValueError('original resource gate escaped root')
    original=read(original_path); patch=read(overlay_path)
    expected={'decision':'approved','task_id':'TCL-20261029-01','run_id':'tcl-20261029-01-v1',
      'manifest_sha256':MANIFEST_SHA,'server':'school127','reviewer_key_sha256':REVIEW_KEY_SHA,
      'original_resource_gate_sha256':policy.sha(original),'overlay_sha256':policy.sha(patch),
      'launcher_sha256':policy.sha(read(__file__)),
      'shard_runner_sha256':policy.sha(read(Path(__file__).with_name('shard127_runner.py'))),
      'fence_policy_sha256':policy.sha(read(Path(__file__).with_name('shard127_policy.py'))),
      'shard_policy_sha256':policy.sha(read(Path(__file__).with_name('shard104_policy.py'))),
      'allowed_account':'gdm','allowed_executable':'/usr/lib/xorg/Xorg','max_memory_mib':8,
      'gdm_uid':128,'gdm_gid':132,'xorg_file_uid':0,'xorg_file_gid':0,'xorg_file_mode':'0755','xorg_file_inode':27265194,
      'destination_machine_sha256':'99b0f2a4634566cc13b4686bcfad863346e6975d37221fb1fc27ebb0d814848d',
      'gpu_uuid':'GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91'}
    if (policy.sha(manifest_bytes)!=MANIFEST_SHA or manifest.get('code_sha256',{}).get(MODULE)!=expected['original_resource_gate_sha256']
            or any(review.get(k)!=v for k,v in expected.items())):
        raise ValueError('resource amendment does not bind the frozen gate and reviewed overlay')
    return original,patch,{'resource_amendment_sha256':policy.sha(review_bytes),**expected}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','repository-root','overlay','review','signature','reviewer-key'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('shard_args',nargs=argparse.REMAINDER)
    args=parser.parse_args(argv)
    forwarded=args.shard_args
    if forwarded and forwarded[0]=='--': forwarded=forwarded[1:]
    for flag, expected in (('--manifest',args.manifest),('--repository-root',args.repository_root)):
        if forwarded.count(flag)!=1 or forwarded.index(flag)+1>=len(forwarded) or forwarded[forwarded.index(flag)+1]!=expected:
            raise ValueError('forwarded runner manifest or repository root differs')
    original,patch,audit=verify(args.manifest,args.repository_root,args.overlay,args.review,args.signature,args.reviewer_key)
    if 'resource_gate' in sys.modules: raise ValueError('resource gate loaded before review')
    module=types.ModuleType('resource_gate'); module.__file__=str(Path(args.repository_root)/MODULE)
    exec(compile(original,module.__file__,'exec'),module.__dict__)
    overlay=types.ModuleType('resource127_gdm_xorg_patch'); overlay.__file__=str(Path(args.overlay).resolve())
    exec(compile(patch,overlay.__file__,'exec'),overlay.__dict__)
    module.check_gpu_xml=overlay.build_check(module)
    original_wait = module.wait_for_resource
    def audited_wait(output, plan, server, phase, emit, wait_seconds=1800):
        emit('resource_overlay_reviewed', audit)
        return original_wait(permit_directory(output), plan, server, phase, emit, wait_seconds)
    module.wait_for_resource = audited_wait
    sys.modules['resource_gate']=module
    print(json.dumps({'resource_overlay_reviewed':audit},sort_keys=True),flush=True)
    import shard127_runner
    return shard127_runner.main(forwarded)

if __name__=='__main__': raise SystemExit(main())
