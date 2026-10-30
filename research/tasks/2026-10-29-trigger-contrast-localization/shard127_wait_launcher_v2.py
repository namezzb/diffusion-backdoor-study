"""Authenticate a bounded-wait overlay without changing the signed shard."""
import argparse
import json
from pathlib import Path
import sys
import types
import shard104_policy as policy
import shard127_policy
import shard127_wait_launcher as prior_launcher

REVIEW_KEY_SHA='dc477cfe4e08a3196925fc6607391c1862676bc9d8d7b5900bdd8a272e25227b'
MANIFEST_SHA='c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa'


def read(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file(): raise ValueError('reviewed ordinary file required')
    return p.read_bytes()


def arg_once(argv,flag):
    if argv.count(flag)!=1 or argv.index(flag)+1>=len(argv): raise ValueError('missing or duplicate '+flag)
    return argv[argv.index(flag)+1]


def verify(args,forwarded):
    review_bytes=read(args.wait_review); review=json.loads(review_bytes)
    policy.verify_signature(review_bytes,read(args.wait_signature),read(args.reviewer_key),REVIEW_KEY_SHA,
                            review.get('reviewer',''),'tcl-wait-amendment-v2')
    if forwarded.count('--')!=1: raise ValueError('resource and shard arguments must be separated')
    split=forwarded.index('--'); resource_args,shard_args=forwarded[:split],forwarded[split+1:]
    manifest_path=arg_once(resource_args,'--manifest')
    root_arg=arg_once(resource_args,'--repository-root')
    if arg_once(shard_args,'--manifest')!=manifest_path or arg_once(shard_args,'--repository-root')!=root_arg:
        raise ValueError('resource and shard frozen inputs differ')
    root=Path(root_arg).resolve(strict=True)
    manifest=json.loads(read(manifest_path))
    directory=Path(args.resource_launcher).resolve(strict=True).parent
    files={'wait_launcher_sha256':__file__,'wait_patch_sha256':args.patch,
           'prior_wait_launcher_sha256':prior_launcher.__file__,
           'prior_wait_patch_sha256':directory/'shard127_watch_wait.py',
           'prior_wait_review_sha256':args.prior_wait_review,'prior_wait_signature_sha256':args.prior_wait_signature,
           'resource_launcher_sha256':args.resource_launcher,
           'resource_overlay_sha256':arg_once(resource_args,'--overlay'),
           'resource_review_sha256':arg_once(resource_args,'--review'),
           'resource_signature_sha256':arg_once(resource_args,'--signature'),
           'shard_review_envelope_sha256':arg_once(shard_args,'--review-envelope'),
           'shard_runner_sha256':directory/'shard127_runner.py',
           'shard_policy_sha256':directory/'shard104_policy.py',
           'fence_policy_sha256':directory/'shard127_policy.py',
           'watch_controller_sha256':directory/'shard127_watch_controller.py'}
    expected={'decision':'approved','task_id':'TCL-20261029-01','run_id':'tcl-20261029-01-v1',
              'manifest_sha256':MANIFEST_SHA,'server':'school127','reviewer_key_sha256':REVIEW_KEY_SHA,
              'watch_lifetime_seconds':30,'retry_window_seconds':90,'maximum_wait_seconds':120,
              'signature_cache_entries':4,'signature_cache_max_seconds':30,
              'startup_watch_wait':True,
              'scientific_replay':'prohibited'}
    expected.update({name:policy.sha(read(path)) for name,path in files.items()})
    score_path=root/'scripts/merging/tssa_mvp_score.py'
    runtime_path=root/'scripts/merging/tssa_sd_runtime.py'
    for path in (score_path,runtime_path):
        relative=str(path.relative_to(root))
        if manifest.get('code_sha256',{}).get(relative)!=policy.sha(read(path)):
            raise ValueError('frozen model runtime differs: '+relative)
    if policy.sha(read(manifest_path))!=MANIFEST_SHA or any(review.get(k)!=v for k,v in expected.items()):
        raise ValueError('wait amendment differs from reviewed frozen inputs')
    prior_args=types.SimpleNamespace(wait_review=args.prior_wait_review,wait_signature=args.prior_wait_signature,
        reviewer_key=args.reviewer_key,resource_launcher=args.resource_launcher,patch=directory/'shard127_watch_wait.py')
    prior_launcher.verify(prior_args,forwarded)
    return root,expected,policy.sha(review_bytes)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('wait-review','wait-signature','prior-wait-review','prior-wait-signature','reviewer-key','resource-launcher','patch'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('resource_args',nargs=argparse.REMAINDER)
    args=parser.parse_args(argv); forwarded=args.resource_args
    if forwarded and forwarded[0]=='--':forwarded=forwarded[1:]
    root,expected,review_sha=verify(args,forwarded)
    sys.path.insert(0,str(root)); sys.path.insert(1,str(root/'scripts/merging'))
    sys.path.insert(2,str(root/'scripts/merging/trigger_contrast_localization'))
    import tssa_sd_runtime
    import tssa_mvp_score
    if (Path(tssa_sd_runtime.__file__).resolve(strict=True)!=root/'scripts/merging/tssa_sd_runtime.py'
            or Path(tssa_mvp_score.__file__).resolve(strict=True)!=root/'scripts/merging/tssa_mvp_score.py'):
        raise ValueError('runtime import resolved outside frozen code root')
    from diffusers import AutoencoderKL
    patch=types.ModuleType('shard127_watch_wait_v2');patch.__file__=str(Path(args.patch).resolve(strict=True))
    exec(compile(read(args.patch),patch.__file__,'exec'),patch.__dict__)
    patch.install(policy,shard127_policy,tssa_sd_runtime.SDGradientRuntime,AutoencoderKL,tssa_mvp_score.IndependentScorer)
    print(json.dumps({'wait_amendment_reviewed':{'review_sha256':review_sha,**expected}},sort_keys=True),flush=True)
    resource=types.ModuleType('resource127_launcher');resource.__file__=str(Path(args.resource_launcher).resolve(strict=True))
    exec(compile(read(args.resource_launcher),resource.__file__,'exec'),resource.__dict__)
    return resource.main(forwarded)

if __name__=='__main__': raise SystemExit(main())
