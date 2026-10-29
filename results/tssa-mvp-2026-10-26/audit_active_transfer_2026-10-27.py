"""Snapshot append-only transfer evidence; never connects or downloads."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path('/Users/zzb/arxiv')
OUT = ROOT/'results/tssa-mvp-2026-10-26'
previous_path = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else OUT/'active_transfer_integrity_audit_2026-10-27-150223-218508Z.json'
previous = json.loads(previous_path.read_text())
report = OUT/'remaining_model_transfer_2026-10-27-140548-913379Z.json'
log = report.with_suffix('.log')
ledger = OUT/'asset_transfer.jsonl'
manifest = json.loads((ROOT/'research/tssa_mvp_assets_2026-10-26.json').read_text())
entries = {e['local_path']:e for e in manifest['files']}
def sha(data):
    return hashlib.sha256(data).hexdigest()
def snapshot(path):
    raw = path.read_bytes()
    return raw[:raw.rfind(b'\n')+1]
raw = snapshot(log)
lr = snapshot(ledger)
assert sha(raw[:previous['log_prefix_bytes']])==previous['log_prefix_sha256']
assert sha(lr[:previous['ledger_prefix_bytes']])==previous['ledger_prefix_sha256']
receipts = {}
for line in lr.decode().splitlines():
    r=json.loads(line);source=r.get('source',{});name=source.get('local_path');e=entries.get(name)
    if e is None or r.get('status') not in ('transferred_verified','remote_verified_existing'):
        continue
    assert all(source.get(k)==e.get(k) for k in ('repo_id','revision','path','local_path','git_blob_oid','size'))
    assert r['path']==manifest['models_root_remote']+'/'+name and r['size']==e['size']
    assert len(r['sha256'])==64 and all(c in '0123456789abcdef' for c in r['sha256'])
    assert not e['sha256'] or r['sha256']==e['sha256']
    receipts[name]=r
chunks=[];current=None;completed=[];offsets={}
for line in raw.decode().splitlines():
    if line.startswith('Uploading: '):
        current=line.removeprefix('Uploading: ')
        assert current in entries
    elif line.startswith('Verified remote chunk: '):
        r=json.loads(line.removeprefix('Verified remote chunk: '));assert current is not None
        expected=offsets.get(current,25165824 if current=='openjourney/text_encoder/model.safetensors' else 0)
        assert r['offset']==expected and r['committed_size']==r['offset']+r['chunk_size']<=entries[current]['size']
        offsets[current]=r['committed_size'];chunks.append({'local_path':current,**r})
    elif line.startswith('SHA256 verified remotely: '):
        name=line.removeprefix('SHA256 verified remotely: ');assert name in receipts
        completed.append({'local_path':name,'chunks':sum(c['local_path']==name for c in chunks),'final_remote_receipt':receipts[name],
                          'chunk_validation_scope':'Receiver checked chunks and whole remote pinned-source integrity; deleted local bytes are not newly rechecked.'})
        if name==current:current=None
assert chunks[:len(previous['new_chunk_receipts'])]==previous['new_chunk_receipts']
local=None;local_sha=None;compared=0
if current:
    e=entries[current];local=Path('/private/tmp/arxiv-tssa-stage')/(sha(e['source_url'].encode())+'.part')
    with local.open('rb') as f:
        h=hashlib.sha256()
        while b:=f.read(8*1024**2):h.update(b)
        local_sha=h.hexdigest();assert not e['sha256'] or local_sha==e['sha256']
        for c in chunks:
            if c['local_path']!=current:continue
            f.seek(c['offset']);b=f.read(c['chunk_size']);assert len(b)==c['chunk_size'] and sha(b)==c['sha256'];compared+=1
roles={role:{'expected':sum(e['local_dir']==role for e in entries.values()),'verified':sum(entries[p]['local_dir']==role for p in receipts)} for role in dict.fromkeys(e['local_dir'] for e in entries.values())}
now=dt.datetime.now(dt.timezone.utc)
audit={'observed_at':now.astimezone(dt.timezone(dt.timedelta(hours=8))).isoformat(),'transfer_report':str(report.relative_to(ROOT)),
       'previous_audit':str(previous_path.relative_to(ROOT)),'previous_log_prefix_preserved':True,
       'log':str(log.relative_to(ROOT)),'log_prefix_bytes':len(raw),'log_prefix_sha256':sha(raw),
       'ledger':str(ledger.relative_to(ROOT)),'ledger_prefix_bytes':len(lr),'ledger_prefix_sha256':sha(lr),
       'complete_manifest_files_verified':len(receipts),'complete_manifest_bytes_verified':sum(r['size'] for r in receipts.values()),
       'by_role_file_counts':roles,'completed_files_this_attempt':completed,'new_chunk_receipts':chunks,
       'new_chunk_receipt_count':len(chunks),'incremental_chunks_since_previous_audit':len(chunks)-len(previous['new_chunk_receipts']),
       'current_asset':current,'current_asset_expected_bytes':entries[current]['size'] if current else None,
       'current_local_file':str(local) if local else None,'current_local_file_sha256':local_sha,
       'current_asset_payload_chunks_independently_matched':compared,'verified_chunk_committed_bytes':offsets.get(current,0),
       'whole_current_file_remotely_verified':current is None and len(receipts)==47,'local_free_bytes':shutil.disk_usage('/private/tmp').free,
       'scope':'Transfer integrity only; no scientific model, CUDA or optimization claim.'}
path=OUT/f'active_transfer_integrity_audit_{now:%Y-%m-%d-%H%M%S-%fZ}.json'
path.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'report':str(path),'verified':len(receipts),'by_role':roles,'current':current,'current_committed_bytes':offsets.get(current,0),'new_chunks':audit['incremental_chunks_since_previous_audit']}))
