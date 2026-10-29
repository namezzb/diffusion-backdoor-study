"""Deploy a hash-bound independent search snapshot and check it on CPU only."""
from pathlib import Path
import argparse
import datetime as dt
import gzip
import hashlib
import importlib.util
import io
import json
import shlex
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'server'))
from stage_school_assets import SchoolSession, REMOTE_CHECK, REMOTE_COMMIT

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', choices=('103', '104'), default='104')
    args = parser.parse_args()
    plan_path = ROOT / 'research/tssa_optimization_exploration_2026-10-28.json'
    plan = json.loads(plan_path.read_text())
    paths = [plan_path.relative_to(ROOT), Path('research/tssa_mvp_2026-10-26.json'),
             Path('research/tssa_mvp_assets_2026-10-26.json')]
    paths += [Path('scripts/merging') / n for n in plan['source_hashes']]
    paths.append(Path('scripts/merging/test_tssa_image_search_run.py'))
    paths = sorted(set(paths))
    payload = {str(p): (ROOT / p).read_bytes() for p in paths}
    for name, digest in plan['source_hashes'].items():
        assert sha(payload['scripts/merging/' + name]) == digest
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w') as archive:
        for name, content in sorted(payload.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(content), 0o644, 0
            archive.addfile(info, io.BytesIO(content))
    packed = gzip.compress(raw.getvalue(), mtime=0)
    bundle_hash = sha(packed)
    local = OUT / ('source-' + bundle_hash[:12] + '.tar.gz')
    if local.exists():
        assert local.read_bytes() == packed
    else:
        local.write_bytes(packed)
    base = ('/data1' if args.server == '103' else '/data2') + '/zhangzibo/arxiv-tssa'
    remote_bundle = base + '/incoming/' + local.name
    code = base + '/code/image-search-' + bundle_hash[:12]
    expected = {name: sha(content) for name, content in payload.items()}
    remote = r'''
import pathlib,os,sys,hashlib,json,tarfile,subprocess,datetime
bundle,code,bundle_hash,expected_json,base=sys.argv[1:]
assert base in ('/data1/zhangzibo/arxiv-tssa','/data2/zhangzibo/arxiv-tssa')
root=pathlib.Path(base); dest=pathlib.Path(code)
assert not root.is_symlink() and root.resolve()==root and root.stat().st_uid==os.getuid()
assert dest.parent==root/'code' and not dest.is_symlink()
assert not dest.parent.is_symlink()
dest.parent.mkdir(mode=0o750,exist_ok=True)
assert dest.parent.stat().st_uid==os.getuid()
assert hashlib.sha256(pathlib.Path(bundle).read_bytes()).hexdigest()==bundle_hash
expected=json.loads(expected_json)
if not dest.exists():
 dest.mkdir()
 with tarfile.open(bundle) as archive:
  members=archive.getmembers()
  assert {m.name for m in members}==set(expected) and len(members)==len(expected)
  for member in members:
   p=dest/member.name
   assert member.isfile() and p.resolve().is_relative_to(dest.resolve())
   content=archive.extractfile(member).read()
   assert hashlib.sha256(content).hexdigest()==expected[member.name]
   p.parent.mkdir(parents=True,exist_ok=True)
   with p.open('xb') as f:f.write(content)
for name,digest in expected.items():
 p=dest/name
 assert p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==digest
python=root/'venv/bin/python'
env=dict(os.environ,CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PIP_NO_INDEX='1',PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
argv=[str(python),'-B',str(dest/'scripts/merging/tssa_image_search_run.py'),'check','--plan',str(dest/'research/tssa_optimization_exploration_2026-10-28.json'),'--old-protocol',str(dest/'research/tssa_mvp_2026-10-26.json'),'--asset-manifest',str(dest/'research/tssa_mvp_assets_2026-10-26.json')]
p=subprocess.run(argv,env=env,capture_output=True,text=True,timeout=30)
assert p.returncode==0,(p.stdout,p.stderr)
check=json.loads(p.stdout)
test=subprocess.run([str(python),'-B','-m','unittest','test_tssa_image_search_run'],cwd=dest/'scripts/merging',env=env,capture_output=True,text=True,timeout=60)
assert test.returncode==0,(test.stdout,test.stderr)
imports=subprocess.run([str(python),'-B','-c','import torch,diffusers,transformers,tssa_image_search_run,tssa_sd_runtime,tssa_mvp_score,json; print(json.dumps(dict(torch=torch.__version__,diffusers=diffusers.__version__,transformers=transformers.__version__,CUDA_initialized=torch.cuda.is_initialized()))); assert not torch.cuda.is_initialized()'],cwd=dest/'scripts/merging',env=env,capture_output=True,text=True,timeout=60)
assert imports.returncode==0,(imports.stdout,imports.stderr)
print(json.dumps({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'code_root':code,'verified_files':expected,'static_plan_check':check,'CPU_tests':test.stdout+test.stderr,'offline_import':json.loads(imports.stdout.strip().splitlines()[-1]),'GPU_launch':False,'GPU_readiness_requires_fresh_portal_and_process_checks':True}))
'''
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    report = {'started_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'bundle_sha256': bundle_hash,
              'local_bundle': str(local), 'plan_sha256': sha(plan_path.read_bytes()), 'GPU_launch': False,
              'server': args.server}
    try:
        with SchoolSession() as session:
            if args.server == '104':
                previous = json.loads(session.remote(REMOTE_CHECK, base, remote_bundle, len(packed), bundle_hash))
                if not previous['exists']:
                    session.upload(local, remote_bundle + '.uploading')
                    transferred = json.loads(session.remote(REMOTE_COMMIT, remote_bundle, bundle_hash, len(packed)))
                    assert transferred['sha256'] == bundle_hash
            else:
                prep = OUT / 'prepare_node103_offline.py'
                assert sha(prep.read_bytes()) == '967a0341443b26b22222079516fb81da420c80f26b463a6908d46624a49179f6'
                spec = importlib.util.spec_from_file_location('node103_deploy_transport', prep)
                transport = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(transport)
                from node103_isolated_transport import patch_transport
                patch_transport(transport)
                report['bundle_transfer'] = transport.relay(session.config, transport.local_entry(local, 'incoming/' + local.name))
            interpreter = base + '/venv/bin/python' if args.server == '103' else 'python3'
            p = subprocess.run(['ssh', '-F', str(session.config), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                                '-o', 'ConnectionAttempts=1', '-o', 'ConnectTimeout=60', 'school' + args.server,
                                shlex.join([interpreter, '-c', remote, remote_bundle, code, bundle_hash, json.dumps(expected), base])],
                               capture_output=True, text=True, timeout=180)
            report.update(returncode=p.returncode, stderr=p.stderr[-4000:])
            if p.returncode:
                report.update(status='failed', stdout=p.stdout[-4000:])
            else:
                report.update(status='deployed_CPU_ready', remote=json.loads(p.stdout))
    except Exception as exc:
        report.update(status='failed', error=str(exc))
    report['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    target = OUT / ('deployment_' + stamp + '.json')
    with target.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'report': str(target), **report}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
