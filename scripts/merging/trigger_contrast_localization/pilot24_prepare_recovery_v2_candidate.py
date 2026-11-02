"""Prepare a second append-only candidate after the two fixed zero-attempt terminals.

This does not grant resource access or start any process. New GPU assignment
must be independently reviewed and pass the normal live platform and CUDA gate.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
from pilot24_coordinator import stage_contract, write_json
from pilot24_worker_ledger import canonical
import pilot24_recovery_guard_candidate as g

PREFIX='scripts/merging/trigger_contrast_localization/'


def sha(path):
    path=Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():
        raise ValueError('ordinary absolute file required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(*, repository_root, gpu_uuid, previous_review_sha256):
    root=Path(repository_root)
    if not root.is_absolute() or any(p.is_symlink() for p in (root,*root.parents)) or not root.is_dir():
        raise ValueError('ordinary reviewed repository root required')
    if not isinstance(gpu_uuid,str) or not re.fullmatch(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',gpu_uuid):
        raise ValueError('complete GPU UUID required')
    previous=Path(g.R1_ROOT)
    target=Path(g.ORIGINAL_ROOT).parent/'recovery-v2'
    if target.exists() or any(p.is_symlink() for p in target.parents):
        raise ValueError('second recovery namespace already exists or path is unsafe')
    with g.hold_both_predecessors(previous_review_sha256=previous_review_sha256) as prior:
        bundle=g._read(previous/'frozen/bundle.json',g.R1_MANIFEST)
        config=g._read(previous/'frozen/coordinator_config.json',g.R1_CONFIG_SHA)
        revised=copy.deepcopy(bundle)
        revised['repository_root']=str(root); revised['review_file']=str(target/'frozen/review.json')
        code=dict(revised['code_sha256']); code[PREFIX+'pilot24_prepare_recovery_v2_candidate.py']=''
        for rel in code:
            if Path(rel).is_absolute() or '..' in Path(rel).parts: raise ValueError('invalid source path')
            code[rel]=sha(root/rel)
        revised['code_sha256']=code
        manifest=hashlib.sha256((canonical(revised)+'\n').encode()).hexdigest()
        updated=copy.deepcopy(config)
        updated['manifest_sha256']=manifest; updated['coordinator_root']=str(target/'coordinator')
        updated['recovery']['previous']={'root':g.R1_ROOT,'manifest_sha256':g.R1_MANIFEST,
            'config_sha256':g.R1_CONFIG_SHA,'state_sha256':g.R1_STATE_SHA,
            'terminal_sha256':g.R1_TERMINAL_SHA,'exit_sha256':g.R1_EXIT_SHA,'review_sha256':previous_review_sha256}
        for a in updated['assignments']:
            a['manifest_sha256']=manifest; a['gate_sha256']=stage_contract(manifest,a['stage'])
            a['output_root']=str(target/'workers'/a['assignment_id']); a['gpu_uuid']=gpu_uuid
        frozen=target/'frozen'; frozen.mkdir(parents=True,exist_ok=False)
        b=frozen/'bundle.json'; c=frozen/'coordinator_config.json'
        if write_json(b,revised,exclusive=True)!=manifest: raise AssertionError('bundle digest mismatch')
        config_sha=write_json(c,updated,exclusive=True)
        launch={}
        for a in updated['assignments']:
            worker=a['worker_id']; value={'server':a['server'],'permission_ref':str(target/'permissions'/(worker+'.json'))}
            if worker in launch and launch[worker]!=value: raise ValueError('worker assignment changed')
            launch[worker]=value
        write_json(frozen/'launch_map.template.json',launch,exclusive=True)
        review={'run_id':revised['run_id'],'status':'pending','manifest_sha256':manifest,
            'coordinator_config_file':str(c),'coordinator_config_sha256':config_sha,
            'original_manifest_sha256':g.MANIFEST,'original_t0_sha256':g.T0_SHA,
            'original_terminal_sha256':g.TERMINAL_SHA,'previous_manifest_sha256':g.R1_MANIFEST,
            'previous_terminal_sha256':g.R1_TERMINAL_SHA,'previous_state_sha256':g.R1_STATE_SHA,
            'previous_review_sha256':previous_review_sha256,
            'reviewer':None,'implementer':'pilot24_prepare_recovery_v2_candidate',
            'limitations':['Pending independent review and fresh live GPU permit.',
                           'Prior terminals and original T0 remain immutable; no attempts were made in either predecessor.']}
        write_json(frozen/'review.json',review,exclusive=True)
        for path in (b,c): path.chmod(0o444)
        return {'status':'pending_independent_review','bundle':str(b),'bundle_sha256':manifest,
                'config':str(c),'config_sha256':config_sha,'previous_new_attempts':0,
                'max_new_attempts':prior['max_new_attempts'],'original_t0_utc':prior['t0_utc'],'gpu_started':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repository-root',required=True);p.add_argument('--gpu-uuid',required=True)
    p.add_argument('--previous-review-sha256',required=True)
    a=p.parse_args();print(json.dumps(prepare(repository_root=a.repository_root,gpu_uuid=a.gpu_uuid,
                                             previous_review_sha256=a.previous_review_sha256),sort_keys=True))

if __name__=='__main__': main()
