"""Resume the frozen model assets with one bounded, verified transfer process."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path('/Users/zzb/arxiv')
OUT = ROOT / 'results/tssa-mvp-2026-10-26'
MANIFEST = ROOT / 'research/tssa_mvp_assets_2026-10-26.json'
HELPER = ROOT / 'server/stage_school_assets.py'
assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest() == '881d2d21083d589dcd26e69c977a8048d270d2cb73ddb7bd286e2d4dd9197902'
assert hashlib.sha256(HELPER.read_bytes()).hexdigest() == '5de11a27f3aa4bd412eef6dd9b837d6ab0be82fc6bf0efb437db29901b15c776'
accepted = json.loads((OUT / 'wheelhouse_transfer_acceptance_2026-10-27-0855.json').read_text())
assert accepted['count'] == 51 and accepted['transfer_returncode'] == 0
spec = json.loads(MANIFEST.read_text())
assert len(spec['files']) == 47
assert shutil.disk_usage('/private/tmp').free > 4 * 1024**3
started = datetime.datetime.now(datetime.timezone.utc)
stem = 'remaining_model_transfer_' + started.strftime('%Y-%m-%d-%H%M%S-%fZ')
report = OUT / (stem + '.json')
log = OUT / (stem + '.log')
ledger = OUT / 'asset_transfer.jsonl'
record = {'status': 'starting', 'started_at': started.isoformat(), 'pid': os.getpid(),
          'manifest_sha256': hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
          'selected_count': 47, 'selected_bytes': sum(f['size'] for f in spec['files']),
          'already_verified_before_start': 12, 'chunk_bytes': 4194304,
          'report': str(report), 'log': str(log), 'ledger': str(ledger),
          'automatic_retry': False, 'GPU_used': False, 'minimum_local_free_reserve': 4*1024**3,
          'cleanup': 'Only task-local temporary files after full remote SHA256 matches pinned source'}

def save():
    record['observed_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    temporary = report.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(report)

save()
print(str(report), flush=True)
t0 = time.monotonic()
with log.open('xb') as stream:
    child = subprocess.Popen([str(ROOT/'.venv/bin/python'), '-u', str(HELPER),
                              '--manifest', str(MANIFEST), '--ledger', str(ledger),
                              '--ssh-chunk-bytes', '4194304'], stdout=stream, stderr=stream)
    record.update(status='running', child_pid=child.pid)
    # Temporary idle-sleep assertion ends with this real transfer or after six hours.
    awake = subprocess.Popen(['/usr/bin/caffeinate', '-i', '-t', '21600', '-w', str(child.pid)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    record['bounded_awake'] = {'pid': awake.pid, 'release_when_process_exits': child.pid,
                              'maximum_seconds': 21600,
                              'expires_at': (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=21600)).isoformat()}
    save()
    rc = child.wait()
record.update(status='complete' if rc == 0 else 'failed', returncode=rc,
              finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              seconds=time.monotonic()-t0, log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
save()
print(json.dumps(record), flush=True)
raise SystemExit(rc)
