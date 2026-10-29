"""Verify the frozen source bundle and install a new, non-overwritten snapshot."""
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path('/data2/zhangzibo/arxiv-tssa')
ARCHIVE = ROOT / 'inputs/deployment_bundle_2026-10-27-0015.tar.gz'
DEST = ROOT / 'code/mvp-dual-c36b319a1f1d'
EXPECTED = 'c36b319a1f1d61c5410eb8ddbddf3c489927687f58ba75cd680757128897afc1'

assert os.getuid() != 0
for path in [ROOT.parent, ROOT, ROOT / 'inputs', ROOT / 'code', ROOT / 'results']:
    assert path.is_dir() and not path.is_symlink() and path.stat().st_uid == os.getuid()
assert ARCHIVE.is_file() and not ARCHIVE.is_symlink()
assert ARCHIVE.stat().st_uid == os.getuid() and ARCHIVE.stat().st_size == 165889
assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == EXPECTED

with tarfile.open(ARCHIVE, 'r:gz') as archive:
    members = archive.getmembers()
    names = [member.name for member in members]
    assert len(names) == len(set(names)) == 21
    payload = {}
    for member in members:
        path = PurePosixPath(member.name)
        assert member.isfile() and not path.is_absolute() and '..' not in path.parts
        assert str(path) == member.name and 0 <= member.size <= 2 * 1024**2
        payload[member.name] = archive.extractfile(member).read()

manifest = json.loads(payload['SOURCE_MANIFEST.json'])
assert len(manifest['files']) == 20
assert set(payload) == set(manifest['files']) | {'SOURCE_MANIFEST.json'}
for name, entry in manifest['files'].items():
    data = payload[name]
    assert len(data) == entry['size']
    assert hashlib.sha256(data).hexdigest() == entry['sha256'], name

created = not DEST.exists()
assert not DEST.is_symlink()
if created:
    DEST.mkdir(mode=0o750)
    for name, data in payload.items():
        target = DEST / name
        target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

assert DEST.is_dir() and DEST.stat().st_uid == os.getuid()
files = set()
for target in DEST.rglob('*'):
    assert not target.is_symlink() and target.stat().st_uid == os.getuid()
    if target.is_file():
        files.add(str(target.relative_to(DEST)))
assert files == set(payload), 'Existing snapshot differs; refusing overwrite'
for name, data in payload.items():
    assert (DEST / name).read_bytes() == data, name

evidence = {
    'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'archive': str(ARCHIVE), 'archive_sha256': EXPECTED,
    'snapshot_root': str(DEST), 'source_files_verified': 20,
    'source_manifest_preserved': True, 'new_snapshot_created': created,
    'models_ready': False, 'dependencies_installed': False, 'GPU_used': False,
}
record = ROOT / 'results/source_deployment_c36b319a1f1d.json'
if not record.exists():
    with record.open('x') as stream:
        json.dump(evidence, stream, indent=2)
        stream.write('\n')
print(json.dumps(evidence))
