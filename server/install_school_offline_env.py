#!/usr/bin/env python3
"""Verify/install the frozen wheels into the existing school data-disk venv.

Run this script locally on school104, never through an embedded SSH command.
--dry-run validates only the local frozen manifest/lock and prints a plan;
--verify-only additionally checks the server, venv and wheel bytes, without pip
installation or ML imports. Neither mode downloads anything. Actual installation
keeps logs/audits under the fixed personal data root and never creates a venv.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import pwd
import re
import signal
import stat
import subprocess
import sys
import tempfile
import traceback
from typing import Any


ALLOWED_ROOT = Path('/data2/zhangzibo/arxiv-tssa')
EXPECTED_USER = 'zhangzibo'
ENVIRONMENT_NAME = 'tssa_mvp_environment_2026-10-26.json'
EXPECTED_MANIFEST_SHA256 = '688edd2a97c9b504d1852a7c0d7ab52b956d13dad5b0818d10e629942ed76604'
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InstallError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def normalize_name(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def parse_lock(text: str) -> dict[str, dict[str, Any]]:
    """Accept only pinned, hashed requirements; no URLs, includes or pip options."""
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    joined = '\n'.join(lines).replace('\\\n', ' ')
    requirements = {}
    for line in joined.splitlines():
        tokens = line.split()
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)', tokens[0]) if tokens else None
        if not match or len(tokens) < 2 or any(not re.fullmatch(r'--hash=sha256:[0-9a-f]{64}', token) for token in tokens[1:]):
            raise InstallError('Lock contains an unsupported requirement, URL, option, marker or missing SHA256.')
        name = normalize_name(match[1])
        if name in requirements:
            raise InstallError(f'Duplicate locked package: {name}')
        requirements[name] = {'version': match[2], 'hashes': {token.split(':', 1)[1] for token in tokens[1:]}}
    if not requirements:
        raise InstallError('The requirements lock is empty.')
    return requirements


def read_inputs(manifest_path: Path, lock_path: Path | None = None) -> tuple[dict[str, Any], Path, dict[str, str]]:
    if sha256(manifest_path) != EXPECTED_MANIFEST_SHA256:
        raise InstallError('Environment manifest differs from the frozen 51-wheel manifest.')
    spec = json.loads(manifest_path.read_text())
    lock_path = lock_path or manifest_path.parent / Path(spec['lock_file']).name
    if sha256(lock_path) != spec['lock_file_sha256']:
        raise InstallError('Requirements lock SHA256 differs from the frozen manifest.')
    locked = parse_lock(lock_path.read_text())
    pins, paths = {}, set()
    for item in spec['files']:
        relative = PurePosixPath(item['local_path'])
        name = normalize_name(item['name'])
        if (item['kind'] != 'wheel' or len(relative.parts) != 2 or relative.parts[0] != 'wheelhouse'
                or relative.name != item['filename'] or not relative.name.endswith('.whl')
                or relative.is_absolute() or '..' in relative.parts or item['local_path'] in paths or name in pins):
            raise InstallError('Duplicate or unsafe wheel path/package in the manifest.')
        entry = locked.get(name)
        if not entry or entry['version'] != item['version'] or item['sha256'] not in entry['hashes']:
            raise InstallError(f'Wheel is not exactly covered by the hashed lock: {name}')
        pins[name] = item['version']
        paths.add(item['local_path'])
    if len(pins) != 51 or set(pins) != set(locked):
        raise InstallError('The frozen manifest and lock must cover the same 51 packages.')
    return spec, lock_path, pins


def inside(path: Path, root: Path, *, exists: bool = True) -> Path:
    resolved = path.resolve(strict=exists)
    if not resolved.is_relative_to(root) or resolved == root:
        raise InstallError(f'Path escapes the dedicated data directory: {path}')
    return resolved


def owned(path: Path, uid: int) -> None:
    info = path.stat()
    if info.st_uid != uid or info.st_mode & stat.S_IWOTH:
        raise InstallError(f'Path must be owned by this account and not world-writable: {path}')


def validate_server(venv: Path) -> tuple[Path, Path, Path]:
    account = pwd.getpwuid(os.getuid())
    if account.pw_name != EXPECTED_USER or os.getuid() == 0:
        raise InstallError('Only the non-root zhangzibo account may install this environment.')
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise InstallError('Installation/verification requires the Linux x86_64 school host; use --dry-run on Mac.')
    root = ALLOWED_ROOT.resolve(strict=True)
    if root != ALLOWED_ROOT:
        raise InstallError('The fixed data root must not redirect to another filesystem path.')
    if root.stat().st_dev == Path('/').stat().st_dev:
        raise InstallError('The /data2 project must be on a data filesystem distinct from the system disk.')
    owned(root, os.getuid())
    venv = inside(venv, root)
    for path in (venv, venv / 'pyvenv.cfg', venv / 'bin'):
        owned(inside(path, root), os.getuid())
    config = dict(line.split('=', 1) for line in (venv / 'pyvenv.cfg').read_text().splitlines() if '=' in line)
    config = {key.strip().lower(): value.strip().lower() for key, value in config.items()}
    if config.get('include-system-site-packages') != 'false':
        raise InstallError('The existing venv must disable system/base site-packages.')
    # Preserve the venv alias when invoking Python: resolving it would run base.
    python = venv / 'bin' / 'python'
    real_python = python.resolve(strict=True)
    home = Path(account.pw_dir).resolve(strict=True)
    data_home = ALLOWED_ROOT.parent.resolve(strict=True)
    if not (real_python.is_relative_to(home) or real_python.is_relative_to(data_home)):
        raise InstallError('The venv interpreter must resolve to this user\'s own home/data installation.')
    owned(real_python, os.getuid())
    if not real_python.is_file() or not os.access(python, os.X_OK):
        raise InstallError('The existing venv Python is not executable.')
    return root, venv, python


def safe_environment(root: Path, scratch: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('PIP_', 'PYTHON')) and key not in ('VIRTUAL_ENV', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV')}
    env.update(CUDA_VISIBLE_DEVICES='', NVIDIA_VISIBLE_DEVICES='none', PYTHONDONTWRITEBYTECODE='1',
               PYTHONNOUSERSITE='1', PIP_CONFIG_FILE=os.devnull, PIP_NO_INDEX='1', PIP_NO_CACHE_DIR='1',
               PIP_DISABLE_PIP_VERSION_CHECK='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HF_DATASETS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1',
               TMPDIR=str(scratch), TMP=str(scratch), TEMP=str(scratch),
               XDG_CACHE_HOME=str(root / 'cache'), HF_HOME=str(root / 'cache' / 'huggingface'),
               TORCH_HOME=str(root / 'cache' / 'torch'), TRITON_CACHE_DIR=str(root / 'cache' / 'triton'),
               NUMBA_CACHE_DIR=str(root / 'cache' / 'numba'), MPLCONFIGDIR=str(root / 'cache' / 'matplotlib'))
    return env


def verify_wheels(spec: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    # The resolver lock contains hashes for several platform wheels; prevent
    # an unrelated compatible wheel in this directory from replacing our pick.
    wheelhouse = inside(root / 'wheelhouse', root)
    expected = {Path(item['local_path']).name for item in spec['files']}
    observed = {path.name for path in wheelhouse.iterdir() if path.name.lower().endswith('.whl')}
    if observed != expected:
        raise InstallError(f'Wheelhouse contains missing/unregistered wheels; missing={sorted(expected - observed)}, extra={sorted(observed - expected)}')
    verified = []
    for item in spec['files']:
        path = inside(root / item['local_path'], root)
        if not path.is_file() or path.stat().st_size != item['size']:
            raise InstallError(f'Missing wheel or wrong size: {item["local_path"]}')
        observed = sha256(path)
        if observed != item['sha256']:
            raise InstallError(f'Wheel SHA256 mismatch: {item["local_path"]}')
        verified.append({'local_path': item['local_path'], 'size': item['size'], 'sha256': observed})
    return verified


PROBE = r'''
import importlib.metadata as md, json, os, platform, site, sys, sysconfig
from pathlib import Path
import pip
from pip._vendor.packaging.tags import sys_tags
from pip._vendor.packaging.utils import parse_wheel_filename
from pip._vendor.packaging.specifiers import SpecifierSet
request = json.load(sys.stdin)
tags = set(sys_tags())
compatibility = []
for item in request['files']:
    compatible = bool(parse_wheel_filename(item['filename'])[3] & tags)
    python_ok = not item.get('requires_python') or platform.python_version() in SpecifierSet(item['requires_python'])
    compatibility.append({'filename': item['filename'], 'compatible': compatible, 'requires_python_satisfied': python_ok})
record = {'system': platform.system(), 'machine': platform.machine(), 'implementation': platform.python_implementation(),
          'python_full_version': platform.python_version(), 'executable': sys.executable,
          'real_executable': str(Path(sys.executable).resolve()), 'prefix': sys.prefix, 'base_prefix': sys.base_prefix,
          'purelib': sysconfig.get_path('purelib'), 'platlib': sysconfig.get_path('platlib'),
          'scripts': sysconfig.get_path('scripts'), 'enable_user_site': site.ENABLE_USER_SITE,
          'pip_version': md.version('pip'), 'pip_file': pip.__file__, 'wheel_compatibility': compatibility,
          'installed_distributions': sorted([{'name': d.metadata['Name'], 'version': d.version,
                'location': str(d.locate_file(''))} for d in md.distributions()], key=lambda d: d['name'].lower()),
          'CUDA_imported': 'torch' in sys.modules}
print(json.dumps(record, sort_keys=True))
'''


def validate_probe(probe: dict[str, Any], spec: dict[str, Any], venv: Path, python: Path) -> None:
    if (probe['system'], probe['machine'], probe['implementation'], probe['python_full_version']) != (
            'Linux', 'x86_64', 'CPython', spec['target']['python_full_version']):
        raise InstallError('The venv interpreter is not the pinned Linux x86_64 CPython 3.11.7.')
    if Path(probe['prefix']).resolve() != venv or Path(probe['base_prefix']).resolve() == venv:
        raise InstallError('The invoked interpreter is not the existing dedicated venv; base installation is forbidden.')
    if Path(probe['executable']).absolute() != python or probe['enable_user_site'] or probe['CUDA_imported']:
        raise InstallError('Venv identity, user-site isolation or CPU-only interpreter probe failed.')
    for key in ('purelib', 'platlib', 'scripts', 'pip_file'):
        inside(Path(probe[key]), venv)
    for item in probe['installed_distributions']:
        inside(Path(item['location']), venv)
    if (len(probe['wheel_compatibility']) != len(spec['files']) or
            not all(item['compatible'] and item['requires_python_satisfied'] for item in probe['wheel_compatibility'])):
        raise InstallError('One or more frozen wheels do not match this interpreter/platform.')


CPU_IMPORTS = r'''
import importlib, importlib.metadata as md, json, sys, traceback
request = json.load(sys.stdin)
report = {'passed': False, 'CUDA_initialized': None, 'CUDA_initialization_attempted': False,
          'imports': [], 'expected_versions': request['pins']}
try:
    import torch
    report['CUDA_initialized_before'] = torch.cuda.is_initialized()
    if report['CUDA_initialized_before']:
        raise RuntimeError('CUDA was initialized before the CPU import check.')
    def forbidden_cuda(*args, **kwargs):
        report['CUDA_initialization_attempted'] = True
        raise RuntimeError('CUDA initialization is prohibited in the CPU installation audit.')
    torch.cuda._lazy_init = forbidden_cuda
    for module in ('torchvision', 'diffusers', 'transformers', 'safetensors.torch', 'torchmetrics', 'numpy',
                   'PIL.Image', 'accelerate', 'huggingface_hub', 'ftfy', 'tokenizers', 'regex', 'yaml', 'triton'):
        importlib.import_module(module)
        report['imports'].append(module)
        if torch.cuda.is_initialized():
            raise RuntimeError('An import initialized CUDA: ' + module)
    from diffusers import UNet2DConditionModel, AutoencoderKL, DDIMScheduler
    from transformers import CLIPTextModel, CLIPTokenizer, CLIPModel, CLIPProcessor, ViTForImageClassification, ViTImageProcessor
    from torch.func import functional_call
    from torchvision.ops import nms
    from safetensors.torch import save, load
    from torchmetrics.multimodal import CLIPScore
    # Tiny CPU operators check native extension/NumPy compatibility without models or downloads.
    tensor = torch.tensor([[1., 2.], [3., 4.]], device='cpu')
    assert (tensor @ tensor).numpy().tolist() == [[7., 10.], [15., 22.]]
    assert torch.equal(load(save({'test': tensor}))['test'], tensor)
    kept = nms(torch.tensor([[0., 0., 1., 1.], [0., 0., 1., 1.]]), torch.tensor([0.9, 0.8]), 0.5)
    assert kept.tolist() == [0]
    report['versions'] = {name: md.version(name) for name in request['pins']}
    if report['versions'] != request['pins']:
        raise RuntimeError('Installed package versions differ from the frozen 51-package pins.')
    report['all_installed_distributions'] = sorted([{'name': d.metadata['Name'], 'version': d.version,
          'location': str(d.locate_file(''))} for d in md.distributions()], key=lambda d: d['name'].lower())
    report['native_CPU_checks'] = ['torch_matmul_numpy', 'safetensors_memory_roundtrip', 'torchvision_nms']
    report['compiled_cuda_runtime'] = torch.version.cuda
    report['CUDA_initialized'] = torch.cuda.is_initialized()
    report['passed'] = not report['CUDA_initialized'] and not report['CUDA_initialization_attempted']
except BaseException as error:
    report.update(error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
    if 'torch' in sys.modules:
        report['CUDA_initialized'] = sys.modules['torch'].cuda.is_initialized()
print(json.dumps(report, sort_keys=True))
sys.exit(0 if report['passed'] else 2)
'''


def pip_command(python: Path, root: Path, lock: Path) -> list[str]:
    return [str(python), '-I', '-B', '-m', 'pip', '--disable-pip-version-check', 'install',
            '--no-index', '--no-cache-dir', '--only-binary=:all:', '--require-hashes', '--no-compile',
            '--force-reinstall', '--find-links', str(root / 'wheelhouse'), '-r', str(lock)]


class Audit:
    def __init__(self, directory: Path, initial: dict[str, Any]) -> None:
        self.directory = directory
        self.record = {**initial, 'commands': [], 'status': 'running'}
        self.save()

    def save(self) -> None:
        payload = json.dumps(self.record, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        target = self.directory / 'audit.json'
        with tempfile.NamedTemporaryFile('w', dir=self.directory, delete=False, prefix='.audit-', encoding='utf-8') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        os.replace(temporary, target)

    def command(self, name: str, argv: list[str], env: dict[str, str], *, stdin: dict[str, Any] | None = None,
                timeout: int = 1800, json_result: bool = False) -> dict[str, Any] | None:
        stdout_path, stderr_path = self.directory / (name + '.stdout.log'), self.directory / (name + '.stderr.log')
        entry = {'name': name, 'argv': argv, 'status': 'running', 'stdout': str(stdout_path), 'stderr': str(stderr_path)}
        self.record['commands'].append(entry)
        self.save()
        process = None
        try:
            with stdout_path.open('xb') as out, stderr_path.open('xb') as err:
                process = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                           stdout=out, stderr=err, cwd=env['TMPDIR'], env=env, start_new_session=True)
                process.communicate(None if stdin is None else json.dumps(stdin).encode(), timeout=timeout)
            entry.update(returncode=process.returncode, status='passed' if process.returncode == 0 else 'failed')
            if json_result:
                try:
                    entry['result'] = json.loads(stdout_path.read_text())
                except (ValueError, UnicodeError) as error:
                    raise InstallError(f'{name} did not return valid JSON; see its preserved stdout/stderr.') from error
            self.save()
            if process.returncode:
                raise InstallError(f'{name} exited {process.returncode}; see {stderr_path} and {stdout_path}.')
            return entry.get('result')
        except BaseException as error:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=10)
            entry.update(status='failed', error_type=type(error).__name__, error=str(error))
            self.save()
            raise


def prepare_directory(path: Path, root: Path) -> Path:
    resolved = inside(path, root, exists=False)
    resolved.mkdir(parents=True, exist_ok=True)
    owned(resolved, os.getuid())
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=PROJECT_ROOT / 'research' / ENVIRONMENT_NAME)
    parser.add_argument('--lock', type=Path, help='Defaults to the manifest sibling lock; its SHA256 must match.')
    parser.add_argument('--venv', type=Path, default=ALLOWED_ROOT / 'venv')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--dry-run', action='store_true', help='Plan on any host; no subprocesses or filesystem mutations.')
    modes.add_argument('--verify-only', action='store_true', help='Check server, venv and all wheel hashes; no installation or ML imports.')
    args = parser.parse_args(argv)
    audit = lock_handle = None
    previous_term = signal.getsignal(signal.SIGTERM)
    try:
        def terminate(signum, frame):
            raise KeyboardInterrupt(f'Signal {signum}; installation may be partial; inspect the audit before retrying.')
        signal.signal(signal.SIGTERM, terminate)
        spec, lock_path, pins = read_inputs(args.manifest, args.lock)
        plan = {'mode': 'dry-run' if args.dry_run else 'verify-only' if args.verify_only else 'install',
                'manifest_sha256': sha256(args.manifest), 'lock_sha256': sha256(lock_path),
                'wheel_count': len(spec['files']), 'wheel_bytes': sum(item['size'] for item in spec['files']),
                'versions_expected': pins, 'target': spec['target'], 'data_root': str(ALLOWED_ROOT),
                'venv': str(args.venv), 'install_command': pip_command(args.venv / 'bin' / 'python', ALLOWED_ROOT, lock_path),
                'network_access': False, 'GPU_validation_performed': False, 'installation_performed': False,
                'installation_attempted': False, 'environment_may_have_changed': False}
        if args.dry_run:
            plan['status'] = 'plan_only_target_venv_and_wheel_bytes_not_verified'
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        root, venv, python = validate_server(args.venv)
        # All inputs as well as outputs must reside in the personal data root.
        inside(args.manifest, root)
        lock_path = inside(lock_path, root)
        for directory in (root / 'tmp', root / 'cache', root / 'results' / 'environment-install', root / 'wheelhouse'):
            if directory.name == 'wheelhouse':
                owned(inside(directory, root), os.getuid())
            else:
                prepare_directory(directory, root)
        lock_file = root / '.offline-env-install.lock'
        if lock_file.is_symlink():
            raise InstallError('Installer lock may not be a symlink.')
        lock_handle = lock_file.open('a+')
        owned(lock_file, os.getuid())
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise InstallError('Another local environment verifier/installer is running; do not install concurrently.') from error
        directory = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-'),
                                          dir=root / 'results' / 'environment-install'))
        audit = Audit(directory, plan)
        scratch = prepare_directory(root / 'tmp' / ('offline-env-' + directory.name), root)
        env = safe_environment(root, scratch)
        # Validate pre-existing cache symlinks before dependencies can use them.
        for name in ('XDG_CACHE_HOME', 'HF_HOME', 'TORCH_HOME', 'TRITON_CACHE_DIR', 'NUMBA_CACHE_DIR', 'MPLCONFIGDIR'):
            prepare_directory(Path(env[name]), root)
        audit.record['environment_overrides'] = {key: env[key] for key in ('TMPDIR', 'XDG_CACHE_HOME', 'HF_HOME',
             'TORCH_HOME', 'CUDA_VISIBLE_DEVICES', 'NVIDIA_VISIBLE_DEVICES', 'PIP_CONFIG_FILE', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE')}
        probe = audit.command('interpreter', [str(python), '-I', '-B', '-c', PROBE], env, stdin=spec, json_result=True, timeout=120)
        validate_probe(probe, spec, venv, python)
        audit.record['interpreter_verified'] = probe
        audit.record['verified_wheels'] = verify_wheels(spec, root)
        free = os.statvfs(root)
        free_bytes = free.f_bavail * free.f_frsize
        minimum_free = plan['wheel_bytes'] * 2 + 1024 ** 3
        audit.record['disk'] = {'available_bytes': free_bytes, 'installation_headroom_required_bytes': minimum_free}
        audit.save()
        if args.verify_only:
            audit.record.update(status='inputs_verified_not_installed', CPU_imports_tested=False, CUDA_initialized=False)
        else:
            if free_bytes < minimum_free:
                raise InstallError('Insufficient data-disk headroom for offline extraction; no installation was started.')
            # Recheck lock identity immediately before pip; no package resolution from network is possible.
            if sha256(lock_path) != spec['lock_file_sha256']:
                raise InstallError('Requirements lock changed after verification.')
            audit.record.update(installation_attempted=True, environment_may_have_changed=True)
            audit.save()
            audit.command('pip_install', pip_command(python, root, lock_path), env)
            audit.record['installation_performed'] = True
            audit.command('pip_check', [str(python), '-I', '-B', '-m', 'pip', '--disable-pip-version-check', 'check'], env, timeout=120)
            audit.command('pip_freeze', [str(python), '-I', '-B', '-m', 'pip', '--disable-pip-version-check', 'freeze', '--all'], env, timeout=120)
            after = audit.command('interpreter_after', [str(python), '-I', '-B', '-c', PROBE], env, stdin=spec, json_result=True, timeout=120)
            validate_probe(after, spec, venv, python)
            imports = audit.command('cpu_imports', [str(python), '-I', '-B', '-c', CPU_IMPORTS], env,
                                    stdin={'pins': pins}, json_result=True, timeout=600)
            if not imports.get('passed') or imports.get('CUDA_initialized') is not False:
                raise InstallError('CPU import verification failed or unexpectedly initialized CUDA.')
            audit.record.update(status='installed_cpu_verified', CPU_imports_tested=True, CUDA_initialized=False,
                                CPU_import_report=imports, all_installed_distributions=after['installed_distributions'])
        audit.save()
        print(json.dumps({'status': audit.record['status'], 'audit': str(directory / 'audit.json'), 'GPU_tested': False}))
        return 0
    except BaseException as error:
        status = 'interrupted_partial_install_possible' if isinstance(error, KeyboardInterrupt) else 'failed'
        if audit:
            audit.record.update(status=status, error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc(),
                                failure_policy='Existing wheels and environment are preserved; no automatic cleanup or retry.')
            audit.save()
        print(json.dumps({'status': status, 'error_type': type(error).__name__, 'error': str(error),
                          'audit': str(audit.directory / 'audit.json') if audit else None}), file=sys.stderr)
        return 3 if isinstance(error, KeyboardInterrupt) else 2
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        if lock_handle:
            lock_handle.close()


if __name__ == '__main__':
    raise SystemExit(main())
