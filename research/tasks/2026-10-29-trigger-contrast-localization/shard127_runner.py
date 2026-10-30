"""Reviewed, disjoint 127 source-baseline shard; never resumes 103/104 ledgers."""
from __future__ import annotations
import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import pwd
import socket
import sqlite3
import sys
import types

import amendment_launcher
import shard127_plan as partition
import shard127_policy as fence_policy
import shard104_policy as policy

OUTPUT = Path('/data1/zhangzibo/arxiv-tssa/results/tcl-20261029-01-v1-shard127-20261030')
DESTINATION_SHA = '99b0f2a4634566cc13b4686bcfad863346e6975d37221fb1fc27ebb0d814848d'
SOURCE_SHA = 'cd06519e32872d3878e9ba27accf715cf97f9a68242c5130c0a4f8002ee08352'
SNAPSHOT_SHA = 'dca8ba3a758b8641092026df5bc1b7ca5d91fdda79b5e1bb2d8fa6229cb3dd5b'
REVIEW_KEY_SHA = 'dc477cfe4e08a3196925fc6607391c1862676bc9d8d7b5900bdd8a272e25227b'
WATCH_KEY_SHA = '85f4e02cb2765186d72fa4be1cba1b95a00d316d9083b98d99c00d3f61f9a9da'
MANIFEST_SHA = 'c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa'


def read(path):
    return amendment_launcher._read(path)


def signed_review(path, key, trusted_sha):
    envelope = json.loads(read(path))
    message = base64.b64decode(envelope['message_b64'], validate=True)
    signature = base64.b64decode(envelope['signature_b64'], validate=True)
    review = json.loads(message)
    policy.verify_signature(message, signature, read(key), trusted_sha, review.get('reviewer', ''), 'tcl-shard-review')
    if review.get('decision') != 'approved' or review.get('reviewer_key_sha256') != trusted_sha:
        raise ValueError('review must approve this dedicated reviewer key')
    return review, policy.sha(message)


class ReadOnlyLocalization:
    def __init__(self, path, contexts):
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
        self.contexts = frozenset(contexts)

    def load(self, unit, kind, context):
        row = self.db.execute('SELECT status,output_sha,output FROM forwards WHERE unit=? AND class=? AND context=?', (unit, kind, context)).fetchone()
        if row is None or row[0] != 'complete' or row[2] is None or policy.sha(row[2]) != row[1]:
            raise ValueError('complete hash-verified localization output unavailable')
        return row[2]


def prepare_output(path, identity):
    from run_store import _no_symlinks, _check_data_disk
    if Path(path) != OUTPUT or pwd.getpwuid(os.geteuid()).pw_name != 'zhangzibo':
        raise ValueError('shard requires the registered 127 account and output path')
    if socket.gethostname() != 'iipl-127' or policy.sha(Path('/etc/machine-id').read_bytes()) != DESTINATION_SHA:
        raise ValueError('127 host identity differs')
    _no_symlinks(OUTPUT)
    root = Path('/data1/zhangzibo')
    if root.stat().st_uid != os.geteuid():
        raise ValueError('127 data root not owned by user')
    _check_data_disk(root)
    if OUTPUT.parent.stat().st_uid != os.geteuid():
        raise ValueError('127 results directory not owned by user')
    raw = partition.canonical(identity)
    try:
        OUTPUT.mkdir()
        fd = os.open(OUTPUT / 'shard_identity.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
    except FileExistsError:
        if not OUTPUT.is_dir() or OUTPUT.stat().st_uid != os.geteuid() or read(OUTPUT / 'shard_identity.json') != raw:
            raise ValueError('existing shard directory has a different identity')
    return OUTPUT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    names = ('manifest','prompts','context-review','m06-review','protocol','asset-manifest','models-root','output-root','repository-root','snapshot-root','review-envelope','reviewer-key','reviewer-key-sha256','patched-intervene','original-amendment','original-signature','original-reviewer-key','original-reviewer-key-sha256','watch-envelope','watch-key','fence-envelope')
    for name in names:
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--resource-wait-seconds', type=int, default=1800)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args(argv)
    if args.reviewer_key_sha256 != REVIEW_KEY_SHA or policy.sha(read(args.watch_key)) != WATCH_KEY_SHA:
        raise ValueError('dedicated reviewer or watch key does not match the pinned trust root')
    review, review_sha = signed_review(args.review_envelope, args.reviewer_key, args.reviewer_key_sha256)
    file_hashes = {'runner_sha256': __file__, 'plan_module_sha256': partition.__file__, 'policy_sha256': policy.__file__,
                   'source_guard_sha256': Path(__file__).with_name('shard104_source_guard.py'),
                   'controller_sha256': Path(__file__).with_name('shard127_watch_controller.py'),
                   'common_controller_sha256': Path(__file__).with_name('shard104_watch_controller.py'),
                   'fence_guard_sha256': Path(__file__).with_name('shard127_104_fence.py'),
                   'fence_policy_sha256': fence_policy.__file__,
                   'original_amendment_sha256': args.original_amendment,
                   'original_signature_sha256': args.original_signature,
                   'original_reviewer_key_sha256': args.original_reviewer_key,
                   'original_launcher_sha256': amendment_launcher.__file__, 'original_patch_sha256': args.patched_intervene}
    for key, path in file_hashes.items():
        if review.get(key) != policy.sha(read(path)):
            raise ValueError('reviewed file differs: ' + key)
    manifest, _, patch, amendment_audit = amendment_launcher.verify_reviewed_amendment(args.manifest, args.repository_root,
        args.patched_intervene, args.original_amendment, args.original_signature, args.original_reviewer_key, args.original_reviewer_key_sha256)
    root = Path(args.repository_root).resolve(strict=True)
    sys.path.insert(0, str(root / 'scripts/merging/trigger_contrast_localization'))
    sys.path.insert(1, str(root / 'scripts/merging'))
    from preflight import load_plan
    from bindings import load_frozen_bindings
    plan = load_plan(args.manifest, args.prompts, args.context_review, args.m06_review, root)
    bindings = load_frozen_bindings(args.manifest, args.prompts, args.m06_review, Path(args.snapshot_root) / 'run/selection/selection.json', root)
    candidate = partition.build_candidate(args.snapshot_root, SNAPSHOT_SHA, plan.run_id, plan.manifest_sha, plan.rows, plan.generation_seeds, bindings)
    candidate_sha = policy.sha(partition.canonical(candidate))
    expected = {'task_id':'TCL-20261029-01','run_id':plan.run_id,'manifest_sha256':MANIFEST_SHA,
                'candidate_sha256':candidate_sha,'snapshot_manifest_sha256':SNAPSHOT_SHA,
                'source_machine_sha256':SOURCE_SHA,'destination_machine_sha256':DESTINATION_SHA,
                'destination_hostname':'iipl-127','destination_server':'school127','destination_output_root':str(OUTPUT),
                'watch_key_sha256':WATCH_KEY_SHA, 'original_restart_prohibited':True, 'shard104_restart_prohibited':True,
                'gpu_uuid':'GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91',
                'source_sigkill':{'pid':586456,'start_ticks':9222972,'signal':'SIGKILL','returncode':0}}
    if any(review.get(k) != v for k, v in expected.items()) or review.get('watch_key_sha256') == args.reviewer_key_sha256:
        raise ValueError('signed shard review identity, source termination, or key separation differs')
    principal = review.get('watch_principal', '')
    def watch():
        policy.verify_watch(args.watch_envelope, read(args.watch_key), review['watch_key_sha256'], principal, candidate_sha, candidate, SOURCE_SHA)
        fence_policy.verify_fence(args.fence_envelope, read(args.watch_key), review['watch_key_sha256'], principal, candidate_sha,
                                 review['shard104_identity_sha256'],review['shard104_fence_pid'],review['shard104_fence_start_ticks'])
    if (review.get('shard104_identity_sha256') != '4ffb1ac179b6f8b913f752281da3f4cce6f1fc6c2fca9c730746f6e3ad9add0a'
        or type(review.get('shard104_fence_pid')) is not int or review['shard104_fence_pid'] <= 0
        or type(review.get('shard104_fence_start_ticks')) is not int or review['shard104_fence_start_ticks'] <= 0):
        raise ValueError('reviewed 104 fence identity is missing')
    audit = {'candidate_sha256':candidate_sha,'review_sha256':review_sha,'source_snapshot_sha256':SNAPSHOT_SHA,
             'source_attempts':344,'allowed_attempts':1704,'source_nonretryable_key':candidate['unresolved_excluded'],
             'shard104_identity_sha256':review['shard104_identity_sha256'], 'shard104_fence_pid':review['shard104_fence_pid'],
             'original_amendment':amendment_audit}
    if args.verify_only:
        print(json.dumps({'verified':True,'gpu_initialized':False,'audit':audit}, sort_keys=True)); return 0
    if os.environ.get('GPU_UUID') != 'GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91':
        raise ValueError('127 GPU UUID differs from signed review')
    watch()
    identity = {'task_id':'TCL-20261029-01','run_id':plan.run_id,'manifest_sha256':plan.manifest_sha,
                'server':'school127','hostname':'iipl-127','machine_sha256':DESTINATION_SHA,'gpu_uuid':'GPU-1805e9be-7fea-3c9f-afdf-32db622c0b91',
                'output_root':str(OUTPUT),'candidate_sha256':candidate_sha,'review_sha256':review_sha}
    output = prepare_output(args.output_root, identity)
    from run_store import lock_run, append_event
    lock_fd = lock_run(output)
    images = local = None
    try:
        append_event(output, plan, 'shard127', 'started', audit)
        from runtime_assets import load_tcl_cpu_assets
        assets, rows, cpu = load_tcl_cpu_assets(args.protocol, args.asset_manifest, args.models_root,
                                               args.prompts, args.context_review, manifest['context_review_sha256'])
        if {name:item['sha256'] for name,item in assets.file_hashes.items()} != plan.asset_hashes:
            raise ValueError('actual 127 assets differ from frozen manifest')
        append_event(output, plan, 'shard127', 'cpu_preflight', cpu)
        if os.environ.get('CUBLAS_WORKSPACE_CONFIG') != ':4096:8':
            raise ValueError('CUBLAS_WORKSPACE_CONFIG must precede CUDA')
        from resource_gate import wait_for_resource
        expires = wait_for_resource(output, plan, 'school127', 'shard127',
            lambda status, detail: append_event(output, plan, 'shard127', status, detail), args.resource_wait_seconds)
        watch()
        if datetime.datetime.now(datetime.timezone.utc) >= expires:
            raise ValueError('resource permit expired before CUDA')
        if 'intervene' in sys.modules:
            raise ValueError('intervention already loaded before patch verification')
        module = types.ModuleType('intervene'); module.__file__ = str(Path(args.patched_intervene).resolve())
        exec(compile(patch, module.__file__, 'exec'), module.__dict__); sys.modules['intervene'] = module
        from tssa_sd_runtime import SDGradientRuntime
        runtime = SDGradientRuntime(assets)
        from selection_audit import verify_selection
        contexts = [r['id'] for r in rows if r['partition'] == 'localize']
        local = ReadOnlyLocalization(Path(args.snapshot_root) / 'run/localization.sqlite', contexts)
        selected = verify_selection(runtime, bindings, local, contexts)
        append_event(output, plan, 'shard127', 'selection_reverified', selected)
        from evidence import Ledger
        from tssa_mvp_score import IndependentScorer
        from generation import run_image
        ids = {state:[r['id'] for r in rows if r['partition'] == state] for state in ('source','merge')}
        images = Ledger(output / 'images.sqlite', plan.run_id, plan.manifest_sha, ids, plan.generation_seeds, bindings)
        ledger = policy.GuardedLedger(images, candidate, watch)
        scorer = IndependentScorer(args.models_root, device='cpu')
        for state, version, category, context, seed in candidate['allowed_keys']:
            prior = images.db.execute('SELECT status FROM attempts WHERE run_id=? AND state=? AND version=? AND class=? AND context_id=? AND seed=?', (plan.run_id,state,version,category,context,seed)).fetchone()
            if prior and prior[0] == 'started':
                continue
            bound = json.loads(bindings.prompt_rows[(state, context, category)])
            run_image(runtime, scorer, ledger, output / 'images', state, version, category, context, seed,
                      bindings.input_hashes[(state,context,category)], bindings.mask_hashes[version],
                      bound['prompt'], bound['score_prompt'], bound['tokenization'])
        ledger._check_budget()
        counts = dict(images.db.execute('SELECT status,COUNT(*) FROM attempts GROUP BY status').fetchall())
        terminal = {**identity,'phase':'shard127','status':'completed' if counts.get('complete',0) == 1704 else 'incomplete',
                    'source_reserved':344,'shard_attempts':images.attempt_count('source'),'shard_completed':counts.get('complete',0),
                    'shard_interrupted':counts.get('started',0),'baseline_combined_limit':2048,'outcome':'not_evaluated',
                    'source_original_interrupted_key_excluded':candidate['unresolved_excluded'],
                    'baseline_gate':'not evaluated: original source attempt remains unresolved'}
        from localization_runner import _write_once
        _write_once(output / 'shard_terminal.json', partition.canonical(terminal))
        append_event(output, plan, 'shard127', 'terminal', terminal)
        print(json.dumps(terminal, sort_keys=True)); return 0
    except Exception as exc:
        append_event(output, plan, 'shard127', 'error', {'error_type':type(exc).__name__,'reason':str(exc),
            'shard_attempts':0 if images is None else images.attempt_count('source')})
        raise
    finally:
        if images is not None: images.close()
        if local is not None: local.db.close()
        os.close(lock_fd)


if __name__ == '__main__':
    raise SystemExit(main())
