"""Fetch only frozen small support assets locally; never connect to school or CUDA."""
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'research/tssa_mvp_assets_2026-10-26.json'
HELPER = ROOT / 'server/stage_school_assets.py'
STAGING = Path('/private/tmp/arxiv-tssa-stage')
assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest() == '881d2d21083d589dcd26e69c977a8048d270d2cb73ddb7bd286e2d4dd9197902'
assert hashlib.sha256(HELPER.read_bytes()).hexdigest() == '5de11a27f3aa4bd412eef6dd9b837d6ab0be82fc6bf0efb437db29901b15c776'
spec = importlib.util.spec_from_file_location('school_stage', HELPER)
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
manifest = json.loads(MANIFEST.read_text())
rows = [json.loads(line) for line in (OUT / 'asset_transfer.jsonl').read_text().splitlines() if line]


def already_verified(entry):
    for receipt in rows:
        source = receipt.get('source', {})
        if receipt.get('status') not in {'transferred_verified', 'remote_verified_existing'}:
            continue
        if not all(source.get(key) == entry.get(key) for key in ('repo_id', 'revision', 'path', 'local_path')):
            continue
        if receipt.get('path') != str(Path(manifest['models_root_remote']) / entry['local_path']):
            continue
        if receipt.get('size') != entry['size']:
            continue
        if entry.get('sha256') and receipt.get('sha256') != entry['sha256']:
            continue
        if entry.get('git_blob_oid') and source.get('git_blob_oid') != entry['git_blob_oid']:
            continue
        return True
    return False


entries = [e for e in manifest['files'] if e['size'] <= 2 * 1024**2 and not already_verified(e)]
assert len(entries) <= 15 and sum(e['size'] for e in entries) <= 4 * 1024**2
assert all(not e['path'].endswith(('.bin', '.safetensors', '.pt', '.pth')) for e in entries)
started = datetime.now(timezone.utc)
report_path = OUT / ('model_support_prefetch_' + started.strftime('%Y-%m-%d-%H%M%S-%fZ') + '.json')
report = {'started_at': started.isoformat(), 'status': 'starting', 'pid': os.getpid(),
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'manifest_sha256': hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
          'selected_count': len(entries), 'selected_bytes': sum(e['size'] for e in entries),
          'files': [], 'remote_transferred': False, 'school_connection_attempted': False,
          'GPU_used': False, 'minimum_free_reserve_bytes': 4 * 1024**3,
          'automatic_retry': False, 'report': str(report_path)}


def save():
    report['observed_at'] = datetime.now(timezone.utc).isoformat()
    temporary = report_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(report_path)


save()
print(str(report_path), flush=True)
start = time.monotonic()
try:
    assert STAGING.is_dir() and not STAGING.is_symlink() and STAGING.stat().st_uid == os.getuid()
    assert stage.LOCK_PATH.is_file() and not stage.LOCK_PATH.is_symlink()
    with stage.LOCK_PATH.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report['status'] = 'running'
        save()
        for entry in entries:
            url = stage.source_url(entry)
            path = STAGING / (hashlib.sha256(url.encode()).hexdigest() + '.part')
            if path.exists() or path.is_symlink():
                info = path.lstat()
                assert stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_size <= entry['size']
            present = path.stat().st_size if path.exists() else 0
            assert shutil.disk_usage(STAGING).free >= 4 * 1024**3 + entry['size'] - present
            report['current_asset'] = entry['local_path']
            save()
            if present < entry['size']:
                result = subprocess.run(['curl', '-fsSL', '--proto', '=https', '--proto-redir', '=https',
                                         '--max-redirs', '10', '--connect-timeout', '20', '--max-time', '120',
                                         '-C', '-', '-o', str(path), url], capture_output=True, text=True, timeout=130)
                if result.returncode:
                    raise RuntimeError('Download failed: ' + entry['local_path'] + ': ' + result.stderr[-500:])
            digest = stage.verify_source(path, entry)
            report['files'].append({'source': entry, 'local_path': str(path), 'size': path.stat().st_size,
                                    'sha256': digest, 'pinned_source_verified': True,
                                    'downloaded_this_run': present < entry['size']})
            save()
            print('Verified locally: ' + entry['local_path'], flush=True)
        report['status'] = 'complete'
except Exception as error:
    report.update(status='failed', error=f'{type(error).__name__}: {error}')
finally:
    report.update(finished_at=datetime.now(timezone.utc).isoformat(), seconds=time.monotonic()-start,
                  verified_count=len(report['files']), verified_bytes=sum(f['size'] for f in report['files']))
    save()
print(json.dumps({key: report.get(key) for key in ('report', 'status', 'verified_count', 'verified_bytes', 'error')}), flush=True)
raise SystemExit(0 if report['status'] == 'complete' else 1)
