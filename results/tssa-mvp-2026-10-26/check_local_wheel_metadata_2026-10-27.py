"""Read downloaded wheel metadata without importing or installing any wheel."""
import datetime
import email.parser
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'research/tssa_mvp_environment_2026-10-26.json'
INVENTORY = OUT / 'local_wheel_inventory_2026-10-27-062211.json'
EXPECTED_SHA = '688edd2a97c9b504d1852a7c0d7ab52b956d13dad5b0818d10e629942ed76604'
env = {
    'implementation_name': 'cpython', 'implementation_version': '3.11.7',
    'os_name': 'posix', 'platform_machine': 'x86_64', 'platform_release': '',
    'platform_system': 'Linux', 'platform_version': '',
    'python_full_version': '3.11.7', 'platform_python_implementation': 'CPython',
    'python_version': '3.11', 'sys_platform': 'linux', 'extra': '',
}


def req_key(value):
    r = Requirement(value)
    return (canonicalize_name(r.name), tuple(sorted(r.extras)), str(r.specifier),
            r.url, str(r.marker) if r.marker else None)


with open('/private/tmp/arxiv-tssa-stage/.transfer.lock', 'a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest() == EXPECTED_SHA
    manifest = json.loads(MANIFEST.read_text())
    inventory = json.loads(INVENTORY.read_text())
    assert inventory['manifest_sha256'] == EXPECTED_SHA
    by_filename = {x['filename']: x for x in inventory['files']}
    assert len(by_filename) == len(manifest['files']) == 51
    packages, errors, differences = {}, [], []
    for entry in manifest['files']:
        receipt = by_filename[entry['filename']]
        assert receipt['sha256'] == entry['sha256']
        path = Path(receipt['local_path'])
        st = path.lstat()
        assert stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()
        assert st.st_size == entry['size'] == receipt['bytes']
        assert path.parent == Path('/private/tmp/arxiv-tssa-stage')
        assert path.name == hashlib.sha256(entry['source_url'].encode()).hexdigest() + '.part'
        with zipfile.ZipFile(path) as wheel:
            members = [x for x in wheel.infolist()
                       if x.filename.count('/') == 1 and x.filename.endswith('.dist-info/METADATA')]
            assert len(members) == 1 and members[0].file_size < 2 * 1024 * 1024
            raw = wheel.read(members[0])
        metadata = email.parser.BytesParser().parsebytes(raw)
        name = canonicalize_name(metadata['Name'])
        version = Version(metadata['Version'])
        assert name == canonicalize_name(entry['name'])
        assert version == Version(entry['version'])
        python_req = metadata.get('Requires-Python', '')
        if not SpecifierSet(python_req).contains('3.11.7'):
            errors.append({'package': name, 'reason': 'Requires-Python', 'requirement': python_req})
        metadata_sha = hashlib.sha256(raw).hexdigest()
        if entry.get('metadata_sha256') and metadata_sha != entry['metadata_sha256']:
            errors.append({'package': name, 'reason': 'pinned metadata hash mismatch'})
        requirements = metadata.get_all('Requires-Dist', [])
        if {req_key(x) for x in requirements} != {req_key(x) for x in entry.get('requires_dist', [])}:
            differences.append({'package': name, 'wheel': requirements,
                                'manifest': entry.get('requires_dist', [])})
        packages[name] = {'version': str(version), 'requires_python': python_req,
                          'metadata_sha256': metadata_sha, 'requirements': requirements}
    extras = {name: {''} for name in packages}
    active = {}
    changed = True
    while changed:
        changed = False
        for parent, package in packages.items():
            for raw in package['requirements']:
                req = Requirement(raw)
                if req.marker and any(x in str(req.marker) for x in ['platform_release', 'platform_version']):
                    raise ValueError('Requires unknown target kernel marker: ' + raw)
                if req.marker and not any(req.marker.evaluate({**env, 'extra': extra}) for extra in extras[parent]):
                    continue
                name = canonicalize_name(req.name)
                key = (parent, str(req))
                passed = name in packages and not req.url and req.specifier.contains(packages[name]['version'])
                active[key] = {'from': parent, 'requirement': raw, 'to': name,
                               'selected_version': packages.get(name, {}).get('version'), 'passed': bool(passed)}
                if name in extras:
                    before = len(extras[name])
                    extras[name].update(req.extras)
                    changed |= len(extras[name]) != before
    errors += [x for x in active.values() if not x['passed']]
    stamp = datetime.datetime.now().astimezone()
    report = {'observed_at': stamp.isoformat(), 'kind': 'actual_downloaded_wheel_metadata_dependency_closure',
              'manifest_sha256': EXPECTED_SHA, 'inventory': str(INVENTORY.relative_to(ROOT)),
              'inventory_sha256': hashlib.sha256(INVENTORY.read_bytes()).hexdigest(),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'target_marker_environment': env, 'packages': packages, 'package_count': len(packages),
              'active_edges': list(active.values()), 'active_edge_count': len(active),
              'manifest_metadata_differences': differences, 'errors': errors,
              'passed': not errors and not differences, 'installed': False, 'GPU_used': False,
              'scope': 'Read ZIP METADATA and current local file identity/size; full wheel SHA proofs are in inventory downloader receipts. Does not prove remote installation, imports, ABI or CUDA execution.'}
    target = OUT / f'local_wheel_metadata_check_{stamp:%Y-%m-%d-%H%M%S}.json'
    with target.open('x') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(json.dumps({'report': str(target.relative_to(ROOT)), 'packages': len(packages),
                      'active_edges': len(active), 'errors': errors,
                      'metadata_differences': len(differences), 'passed': report['passed']}))
    raise SystemExit(0 if report['passed'] else 1)
