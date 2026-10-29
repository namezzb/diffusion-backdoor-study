"""Bounded local preparation during the school connection outage; no remote/GPU use."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import time
import zipfile

ROOT = Path('/Users/zzb/arxiv')
OUT = Path(__file__).resolve().parent
STAGING = Path('/private/tmp/arxiv-tssa-stage')
MANIFEST = ROOT / 'research/tssa_mvp_environment_2026-10-26.json'
EXPECTED = '688edd2a97c9b504d1852a7c0d7ab52b956d13dad5b0818d10e629942ed76604'
spec = importlib.util.spec_from_file_location('stage', ROOT / 'server/stage_school_assets.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
assert stage.sha256(MANIFEST) == EXPECTED
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--medium', action='store_true', help='Only the three pinned 32-100 MiB wheels')
args = parser.parse_args()
batch = 'medium' if args.medium else 'small'
entries = sorted((x for x in json.loads(MANIFEST.read_text())['files']
                  if (32 * 1024**2 < x['size'] <= 100 * 1024**2 if args.medium
                      else x['size'] <= 32 * 1024**2)), key=lambda x: x['size'])
expected_count, expected_bytes = (3, 190886096) if args.medium else (39, 83818032)
assert len(entries) == expected_count and sum(x['size'] for x in entries) == expected_bytes
assert sum(x['size'] for x in entries) < 256 * 1024**2
stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S-%fZ')
destination = OUT / (batch + '_wheel_prefetch_' + stamp + '.json')
assert not destination.exists()
started = time.monotonic()
report = {'started_at': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid(), 'batch': batch,
          'status': 'running', 'manifest_sha256': EXPECTED, 'script_sha256': stage.sha256(Path(__file__)),
          'selected_count': len(entries), 'selected_bytes': sum(x['size'] for x in entries),
          'verified': [], 'no_GPU': True, 'remote_transferred': False, 'installed': False,
          'minimum_free_bytes': 4 * 1024**3}
stage.save_status(destination, report)
print(json.dumps({'pid': os.getpid(), 'report': str(destination), 'files': len(entries)}), flush=True)
try:
    assert not STAGING.is_symlink() and STAGING.stat().st_uid == os.getuid()
    assert not stage.LOCK_PATH.is_symlink()
    with stage.LOCK_PATH.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for entry in entries:
            url = stage.source_url(entry)
            local = STAGING / (hashlib.sha256(url.encode()).hexdigest() + '.part')
            assert not local.is_symlink()
            assert not local.exists() or (local.is_file() and local.stat().st_uid == os.getuid())
            present = local.stat().st_size if local.exists() else 0
            assert 0 <= present <= entry['size']
            assert shutil.disk_usage(STAGING).free >= entry['size'] - present + 4 * 1024**3
            report['current_file'] = entry['filename']
            stage.save_status(destination, report)
            if present < entry['size']:
                subprocess.run(['curl', '-fsSL', '--retry', '1', '--retry-delay', '2',
                                '--connect-timeout', '20', '--max-time', '300',
                                '--speed-time', '120', '--speed-limit', '1024', '-C', '-',
                                '-o', str(local), url], check=True)
            actual = stage.verify_source(local, entry)
            with zipfile.ZipFile(local) as archive:
                # Vendored packages may also contain WHEEL files below subdirectories.
                names = [x for x in archive.namelist()
                         if x.count('/') == 1 and x.endswith('.dist-info/WHEEL')]
                assert len(names) == 1
                tags = [x[5:].strip() for x in archive.read(names[0]).decode().splitlines()
                        if x.startswith('Tag: ')]
                assert tags and all('macosx' not in x and 'win_' not in x for x in tags)
            report['verified'].append({'filename': entry['filename'], 'bytes': entry['size'],
                                       'sha256': actual, 'wheel_tags': tags, 'local_path': str(local)})
            stage.save_status(destination, report)
        report['status'] = 'complete'
except BaseException as error:
    report.update(status='failed', error_type=type(error).__name__, error=str(error))
    raise
finally:
    report.update(finished_at=datetime.now(timezone.utc).isoformat(), seconds=time.monotonic() - started,
                  free_bytes_after=shutil.disk_usage(STAGING).free)
    stage.save_status(destination, report)
    print(json.dumps({'status': report['status'], 'verified_count': len(report['verified']),
                      'report': str(destination)}), flush=True)
