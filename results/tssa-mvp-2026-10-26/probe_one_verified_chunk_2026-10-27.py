"""One real, bounded chunk of the existing owned UNet; never uses GPU."""
from pathlib import Path
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
import time

ROOT = Path('/Users/zzb/arxiv')
OUT = ROOT / 'results/tssa-mvp-2026-10-26'
spec = importlib.util.spec_from_file_location('stage', ROOT / 'server/stage_school_assets.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
entry = next(x for x in json.loads((ROOT / 'research/tssa_mvp_assets_2026-10-26.json').read_text())['files']
             if x['local_path'] == 'sd15/unet/diffusion_pytorch_model.safetensors')
local = Path('/private/tmp/arxiv-tssa-stage/b4106b072747208b2e136002b2afd1bdf98772086e8aa3adce82c0a2580c4801.part')
remote = stage.REMOTE_ROOT + '/models/' + entry['local_path']
started = time.monotonic()
report = {'started_at': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid(), 'status': 'running',
          'kind': 'one_bounded_verified_chunk', 'max_chunk_bytes': 16 * 1024**2,
          'no_GPU': True, 'full_asset_verified': False, 'automatic_retries': 0,
          'helper_sha256': stage.sha256(ROOT / 'server/stage_school_assets.py'),
          'probe_script_sha256': stage.sha256(Path(__file__))}
destination = OUT / ('chunk_transfer_probe_' + datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S-%fZ') + '.json')
assert not destination.exists(), 'Never overwrite a previous probe record'
stage.save_status(destination, report)
print(json.dumps({'report': str(destination), 'pid': os.getpid()}), flush=True)
try:
    assert not local.is_symlink() and local.stat().st_uid == os.getuid()
    assert not stage.LOCK_PATH.is_symlink()
    with stage.LOCK_PATH.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stage.verify_source(local, entry)
        with stage.SchoolSession() as session:
            existing = json.loads(session.remote(stage.REMOTE_CHECK, stage.REMOTE_ROOT, remote,
                                                 entry['size'], entry['sha256']))
            assert not existing['exists'], 'UNet already committed; do not upload again'
            partial = json.loads(session.remote(stage.REMOTE_PARTIAL, remote + '.uploading', entry['size']))
            assert partial['sha256'] == stage.prefix_sha256(local, partial['size'])
            with local.open('rb') as stream:
                stream.seek(partial['size'])
                payload = stream.read(min(16 * 1024**2, entry['size'] - partial['size']))
            assert payload
            report.update(offset=partial['size'], chunk_size=len(payload), prefix_verified=True)
            stage.save_status(destination, report)
            print(json.dumps({'offset': partial['size'], 'chunk_bytes': len(payload), 'phase': 'sending_one_chunk'}), flush=True)
            receipt = session._upload_chunk(remote + '.uploading', partial['size'], entry['size'], payload)
            expected = {'offset': partial['size'], 'chunk_size': len(payload),
                        'committed_size': partial['size'] + len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
            assert receipt == expected
            after = json.loads(session.remote(stage.REMOTE_PARTIAL, remote + '.uploading', entry['size']))
            assert after['size'] == receipt['committed_size']
            assert after['sha256'] == stage.prefix_sha256(local, after['size'])
            report.update(status='complete', receipt=receipt, resulting_prefix=after,
                          remote_prefix_sha256_rechecked=True)
except BaseException as error:
    report.update(status='failed', error_type=type(error).__name__, error=str(error))
    stderr = getattr(error, 'stderr', None)
    if stderr:
        report['stderr'] = (stderr.decode(errors='replace') if isinstance(stderr, bytes) else stderr)[-4000:]
    report['chunk_send_started'] = 'offset' in report
    raise
finally:
    report.update(finished_at=datetime.now(timezone.utc).isoformat(), seconds=time.monotonic() - started)
    stage.save_status(destination, report)
    print(json.dumps(report), flush=True)
