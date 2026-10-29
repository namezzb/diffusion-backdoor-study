#!/usr/bin/env python3
"""Create bounded, explicit research-only ZIPs; never uploads or reads outside ROOT."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = 'snapshot-2026-10-29-v1'
OUT = ROOT / 'storage/_packages' / SNAPSHOT
MANIFESTS = ROOT / 'storage/manifests' / SNAPSHOT
SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.codex', '.claude', '.qoder', '.idea'}
SKIP_NAMES = {'.DS_Store', '.mcp.json', 'package-lock.json', '.run.lock'}
PAYLOAD_EXT = {'.png', '.jpg', '.jpeg', '.pdf', '.pptx', '.pt', '.pth', '.bin', '.safetensors', '.ckpt', '.f32', '.npy', '.npz', '.zip', '.tar', '.gz'}
SECRET = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{35,}|hf_[A-Za-z0-9]{25,}|sk-(?:proj-)?[A-Za-z0-9_-]{28,})\b|\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{15,}\b')


def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def safe(p):
    p = Path(p)
    if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(ROOT):
        raise ValueError('not an in-root regular source: ' + str(p))
    if any(x in SKIP_DIRS for x in p.relative_to(ROOT).parts) or p.name in SKIP_NAMES:
        raise ValueError('excluded source: ' + str(p))
    return p


def walk(base):
    for folder, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(folder)/d).is_symlink())
        for name in sorted(files):
            p = Path(folder)/name
            if p.is_symlink() or name in SKIP_NAMES or name.endswith(('.pyc', '.backup-part', '.part')):
                continue
            yield safe(p)


def payload_groups():
    groups = {}
    images = ROOT/'results/tssa-opt-exploration-2026-10-28/final_images_816_20261028/images'
    groups['exploration-images'] = [p for p in walk(images) if p.suffix == '.png']
    assert len(groups['exploration-images']) == 816
    diag = ROOT/'results/tssa-target-semantic-diagnostic-2026-10-28/observation_20261029T015422409669Z/artifacts'
    groups['diagnostic-artifacts'] = list(walk(diag))
    assert len(groups['diagnostic-artifacts']) == 1141
    groups['papers'] = [p for p in walk(ROOT/'papers') if p.parts[-2] in {'pdf', 'txt'} or p.suffix == '.html']
    groups['presentations'] = [p for p in walk(ROOT/'presentations') if p.suffix == '.pptx']
    seen = {p for v in groups.values() for p in v}
    groups['other-research-artifacts'] = []
    for d in ['results', 'archive', 'reports', 'simulations']:
        for p in walk(ROOT/d):
            rel = p.relative_to(ROOT).as_posix()
            if p in seen or rel.startswith('results/server-archive-'):
                continue
            if p.suffix in PAYLOAD_EXT - {'.tar', '.gz'}:
                groups['other-research-artifacts'].append(p)
            elif p.name.startswith('source-') and p.name.endswith('.tar.gz'):
                groups['other-research-artifacts'].append(p)
    return groups


def core_group():
    excluded = {x['path'] for x in json.loads((ROOT/'storage/audits/local_scope_review_20261029.json').read_text())['credential_pattern_hits']}
    payload = {p for v in payload_groups().values() for p in v}
    files = []
    for p in walk(ROOT):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith('storage/') or p in payload or p.suffix in PAYLOAD_EXT or rel in excluded:
            continue
        if rel.startswith('results/server-archive-') and '/code/' not in rel:
            continue
        if p.name.startswith('.') and p.name != '.gitignore':
            continue
        if p.stat().st_size > 20*1024*1024:
            raise ValueError('unclassified large core file: '+rel)
        if SECRET.search(p.read_bytes()):
            raise ValueError('credential signal in core: '+rel)
        files.append(p)
    return {'research-core': files}


def build(group, paths, limit):
    batches, current, size = [], [], 0
    for p in sorted(paths):
        n = p.stat().st_size
        if current and size+n > limit:
            batches.append(current); current=[]; size=0
        current.append(p); size+=n
    if current:
        batches.append(current)
    receipts=[]
    for i, members in enumerate(batches, 1):
        name=f'{group}-{i:03d}'
        dest=OUT/(name+'.zip'); mp=MANIFESTS/(name+'.json')
        if dest.exists() or mp.exists():
            raise ValueError('snapshot package already exists: '+name)
        rows=[]
        with zipfile.ZipFile(dest, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
            for p in members:
                safe(p); st=p.stat(); rel=p.relative_to(ROOT).as_posix()
                sha=digest(p)
                z.write(p, rel)
                if st.st_size!=p.stat().st_size or st.st_mtime_ns!=p.stat().st_mtime_ns or digest(p)!=sha:
                    raise ValueError('source changed during packing: '+rel)
                rows.append({'path':rel,'size':st.st_size,'sha256':sha})
        data={'schema_version':1,'snapshot_id':SNAPSHOT,'group':group,'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
              'package':{'name':dest.name,'size':dest.stat().st_size,'sha256':digest(dest)},'files':rows,
              'source_boundary':'Only regular files resolved within /Users/zzb/arxiv; no external symlinks followed',
              'drive':None,'verification_status':'local_packaged'}
        mp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        receipts.append({'name':name,'package':str(dest.relative_to(ROOT)),'manifest':str(mp.relative_to(ROOT)),
                         'files':len(rows),'source_bytes':sum(x['size'] for x in rows),'package_bytes':dest.stat().st_size,'sha256':data['package']['sha256']})
    return receipts


def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['payload','core']);ap.add_argument('--max-mib',type=int,default=128)
    a=ap.parse_args();OUT.mkdir(parents=True,exist_ok=True);MANIFESTS.mkdir(parents=True,exist_ok=True)
    groups=payload_groups() if a.mode=='payload' else core_group()
    records=[]
    for name,files in groups.items():
        records.extend(build(name,files,a.max_mib*1024**2))
    rp=ROOT/f'storage/{a.mode}_packages.json'
    rp.write_text(json.dumps({'snapshot_id':SNAPSHOT,'packages':records},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(records,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
