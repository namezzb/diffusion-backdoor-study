"""Salvage verified complete PNG members; optionally fetch only missing paths once."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import shutil
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OBS = HERE / 'observation_103_20261028T111524087743Z-7268ad87/report.json'
FOLDER = HERE / 'final_images_816_20261028'
sha = lambda data: hashlib.sha256(data).hexdigest()


def expected_images():
    expected = {}
    report = json.loads(OBS.read_text())
    for name, meta in report['result']['files'].items():
        if not name.startswith('run/operations/'):
            continue
        raw = (OBS.parent / 'artifacts' / name).read_bytes()
        assert sha(raw) == meta['sha256']
        receipt = json.loads(raw)
        assert receipt['status'] == 'completed'
        record = receipt['record']
        name = record['image_path']
        p = PurePosixPath(name)
        assert not p.is_absolute() and '..' not in p.parts and p.parts[0] == 'images'
        assert '\n' not in name and '\x00' not in name and name not in expected
        expected[name] = record['image_sha256']
    assert len(expected) == 816
    return expected


def verify_existing(expected):
    found = {}
    for p in sorted((FOLDER / 'images').rglob('*.png')):
        name = p.relative_to(FOLDER).as_posix()
        assert p.is_file() and not p.is_symlink() and name in expected
        raw = p.read_bytes()
        assert sha(raw) == expected[name], name
        found[name] = {'sha256': expected[name], 'bytes': len(raw)}
    return found


def salvage(archive, expected):
    info = {'archive': str(archive), 'bytes': archive.stat().st_size,
            'sha256': sha(archive.read_bytes()), 'complete_members_verified': 0}
    seen = set()
    try:
        with tarfile.open(archive, 'r:') as tf:
            for item in tf:
                p = PurePosixPath(item.name)
                assert not p.is_absolute() and '..' not in p.parts and p.parts[0] == 'images'
                if item.isdir():
                    continue
                assert item.isreg() and item.name in expected and item.name not in seen
                assert 0 < item.size <= 16 * 1024 * 1024
                seen.add(item.name)
                raw = tf.extractfile(item).read()
                assert len(raw) == item.size and sha(raw) == expected[item.name]
                dest = FOLDER / item.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    assert not dest.is_symlink() and sha(dest.read_bytes()) == expected[item.name]
                else:
                    with dest.open('xb') as f:
                        f.write(raw)
                info['complete_members_verified'] += 1
    except tarfile.ReadError as exc:
        info['truncated_archive_error'] = str(exc)
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execute', action='store_true')
    args = ap.parse_args()
    expected = expected_images()
    report = {'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'observation_sha256': sha(OBS.read_bytes()), 'GPU_launch': False,
              'original_failure_preserved': True, 'remote_read_only': True,
              'automatic_retry': False, 'salvaged': salvage(FOLDER / 'images.tar', expected)}
    existing = verify_existing(expected)
    missing = sorted(set(expected) - set(existing))
    report.update(existing_verified_images=len(existing), missing_images=len(missing))
    if not args.execute:
        print(json.dumps(report, indent=2))
        return
    destination = FOLDER / 'remaining_images.tar'
    result_path = FOLDER / 'resumed_retrieval_report.json'
    assert not destination.exists() and not result_path.exists()
    assert shutil.disk_usage(FOLDER).free > 1024 ** 3
    sys.path.insert(0, str(ROOT / 'server'))
    from stage_school_assets import SchoolSession
    try:
        if missing:
            with SchoolSession() as session:
                command = shlex.join(['tar', '-C', '/data1/zhangzibo/arxiv-tssa/results/tssa-opt-exploration-2026-10-28-v1',
                                      '-cf', '-', '--verbatim-files-from', '-T', '-'])
                with destination.open('xb') as f:
                    r = subprocess.run(['ssh', '-F', str(session.config), '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                                        'school103', command], input=('\n'.join(missing) + '\n').encode(),
                                       stdout=f, stderr=subprocess.PIPE, timeout=1200)
                report.update(returncode=r.returncode, stderr=r.stderr.decode(errors='replace')[-2000:])
                if r.returncode:
                    raise RuntimeError('Read-only remaining-image transfer failed')
        report['status'] = 'transfer_finished_pending_local_verification'
    except Exception as exc:
        report.update(status='transfer_failure_preserved', error=type(exc).__name__ + ': ' + str(exc))
    finally:
        if destination.exists() and destination.stat().st_size:
            report['remaining_archive'] = salvage(destination, expected)
        found = verify_existing(expected)
        report.update(verified_images=len(found), image_bytes=sum(v['bytes'] for v in found.values()), images=found,
                      missing_paths=sorted(set(expected) - set(found)), finished_at=dt.datetime.now(dt.timezone.utc).isoformat())
        if set(found) == set(expected):
            report['status'] = 'all816_images_downloaded_hash_verified'
        with result_path.open('x') as f:
            json.dump(report, f, indent=2)
            f.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('images', 'missing_paths')}, indent=2))


if __name__ == '__main__':
    main()
