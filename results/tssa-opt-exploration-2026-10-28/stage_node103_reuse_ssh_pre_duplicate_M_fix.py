#!/usr/bin/env python3
"""Pinned wheels/models relay using two task-private SSH masters; no installs/GPU.

Default: validate local frozen entries only. --execute takes the existing local
preparation lock and relays through the original prefix/hash/atomic-publish code.
A lost master fails closed; slave requests cannot fall back to fresh SSH login.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
PREPARE = HERE / 'prepare_node103_offline.py'
PREPARE_SHA = '967a0341443b26b22222079516fb81da420c80f26b463a6908d46624a49179f6'
HOSTS = ('school103', 'school104')
START_TIMEOUT = 90


def load_prepare():
    assert not PREPARE.is_symlink() and hashlib.sha256(PREPARE.read_bytes()).hexdigest() == PREPARE_SHA
    spec = importlib.util.spec_from_file_location('pinned_node103_relay', PREPARE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrivateMasters:
    def __init__(self, config, folder, ledger):
        self.config, self.folder, self.ledger = Path(config), Path(folder), ledger
        self.sockets = {host: self.folder / ('s' + host[-3:]) for host in HOSTS}
        self.processes, self.errors = {}, {}
        assert self.folder.resolve() == self.folder and not self.folder.is_symlink()
        info = self.folder.stat()
        assert info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700
        assert all(len(os.fsencode(p)) < 100 for p in self.sockets.values())

    def options(self, host, *, slave):
        assert host in HOSTS, 'Only fixed school103/school104 aliases are allowed'
        socket = self.sockets[host]
        assert socket.parent == self.folder and socket.name == 's' + host[-3:]
        args = ['ssh', '-F', str(self.config), '-S', str(socket), '-T',
                '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes',
                '-o', 'ConnectionAttempts=1', '-o', 'ConnectTimeout=60',
                '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
                '-o', 'ControlPersist=no', '-o', 'UpdateHostKeys=no', '-o', 'ForwardAgent=no',
                '-o', 'ControlMaster=no' if slave else 'ControlMaster=yes']
        if slave:
            # OpenSSH otherwise reconnects if the mux socket disappears. This
            # command is never used while mux works, and forbids that fallback.
            args += ['-o', 'ProxyCommand=/usr/bin/false']
        return args

    def control_argv(self, host, action):
        assert action in ('check', 'exit')
        return self.options(host, slave=True) + ['-O', action, host]

    def _owned_socket(self, host):
        p = self.sockets[host]
        if p.is_symlink() or not p.exists():
            return False
        info = p.stat()
        return stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()

    def start(self):
        for host in HOSTS:
            socket = self.sockets[host]
            assert not socket.exists() and not socket.is_symlink(), 'New private socket must not already exist'
            err = (self.folder / (host + '.stderr')).open('x+b')
            self.errors[host] = err
            process = subprocess.Popen(self.options(host, slave=False) + ['-M', '-N', host],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                                       start_new_session=True, close_fds=True)
            self.processes[host] = process
            self.ledger({'event': 'private_master_started', 'host': host, 'pid': process.pid,
                         'control_path': str(socket), 'automatic_retry': False})
            deadline = time.monotonic() + START_TIMEOUT
            while not self._owned_socket(host):
                if process.poll() is not None:
                    raise RuntimeError(host + ' private master exited before ready: ' + self.stderr_tail(host))
                if time.monotonic() >= deadline:
                    raise TimeoutError(host + ' private master startup exceeded bound')
                time.sleep(0.1)
            checked = subprocess.run(self.control_argv(host, 'check'), capture_output=True, text=True, timeout=10)
            if checked.returncode or process.poll() is not None:
                raise RuntimeError(host + ' private master check failed: ' + checked.stderr[-2000:])
            self.ledger({'event': 'private_master_ready', 'host': host, 'control_path': str(socket)})

    def ssh_argv(self, config, host, source, *args, interpreter='python3'):
        assert Path(config) == self.config and host in HOSTS
        process = self.processes.get(host)
        if process is None or process.poll() is not None or not self._owned_socket(host):
            raise RuntimeError(host + ' task-private master unavailable; no reconnect or automatic retry')
        return self.options(host, slave=True) + [host, shlex.join([interpreter, '-c', source, *map(str, args)])]

    def stderr_tail(self, host):
        stream = self.errors[host]
        stream.flush()
        size = stream.seek(0, os.SEEK_END)
        stream.seek(max(0, size - 8192))
        return stream.read().decode(errors='replace')

    def close(self):
        # Only processes and exact sockets created by this wrapper are touched.
        for host, process in reversed(list(self.processes.items())):
            cleanup = {'event': 'private_master_cleanup', 'host': host, 'pid': process.pid,
                       'control_path': str(self.sockets[host])}
            try:
                if process.poll() is None and self._owned_socket(host):
                    try:
                        stopped = subprocess.run(self.control_argv(host, 'exit'), capture_output=True, text=True, timeout=10)
                        cleanup.update(control_exit_returncode=stopped.returncode, control_exit_stderr=stopped.stderr[-2000:])
                    except (OSError, subprocess.SubprocessError) as exc:
                        cleanup['control_exit_error'] = type(exc).__name__ + ': ' + str(exc)
                        # A broken control channel must not skip cleanup of our
                        # own still-running foreground master process.
                if process.poll() is None:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)
                cleanup.update(returncode=process.returncode, stderr_tail=self.stderr_tail(host))
            except Exception as exc:
                cleanup['error'] = type(exc).__name__ + ': ' + str(exc)
                # A cleanup failure is logged, never expanded to unrelated SSH processes.
            finally:
                self.errors[host].close()
                self.ledger(cleanup)
        # Popen itself may fail after opening stderr but before registration.
        for stream in self.errors.values():
            if not stream.closed:
                stream.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True, choices=('wheels', 'models'))
    parser.add_argument('--execute', action='store_true', help='Connect once per fixed node and transfer the selected frozen asset family')
    args = parser.parse_args(argv)
    module = load_prepare()
    entries = module.checked_entries(args.stage)
    assert len(entries) == (51 if args.stage == 'wheels' else 47)
    assert all(e['relative'].startswith(('wheelhouse/' if args.stage == 'wheels' else 'models/')) for e in entries)
    plan = {'stage': args.stage, 'status': 'prepared_locally_no_connection', 'file_count': len(entries),
            'bytes': sum(e['size'] for e in entries), 'original_prepare_sha256': PREPARE_SHA,
            'wrapper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'source': module.SOURCE_ROOT, 'destination': module.DEST_ROOT,
            'task_private_masters': list(HOSTS), 'fallback_login_permitted': False,
            'automatic_retry': False, 'GPU_initialization': False, 'install_environment': False,
            'reuse_original_prefix_hash_size_noreplace_and_remote_lock': True}
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return 0
    lock_path = HERE / '.prepare_node103.lock'
    assert not lock_path.is_symlink()
    with lock_path.open('a+') as lock:
        assert os.fstat(lock.fileno()).st_uid == os.getuid()
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stage_started = time.monotonic()
        def ledger(record):
            module.append_ledger({'stage': args.stage, 'transport': 'task_private_masters', **record})
        ledger(dict(plan, status='stage_started'))
        session = masters = private = None
        original_ssh_argv = module.ssh_argv
        old_handler = signal.getsignal(signal.SIGTERM)
        def interrupted(signum, frame):
            raise KeyboardInterrupt('Own CPU relay interrupted; preserve validated partials')
        signal.signal(signal.SIGTERM, interrupted)
        try:
            spec = importlib.util.spec_from_file_location('private_mux_school_session', module.SESSION_SCRIPT)
            session_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(session_module)
            session = session_module.SchoolSession()
            session.__enter__()  # DNS/temp config only; no unmanaged master is started.
            private = tempfile.TemporaryDirectory(prefix='tssa-mux-', dir='/private/tmp')
            folder = Path(private.name).resolve()
            folder.chmod(0o700)
            config = folder / 'config'
            config.write_text('Host *\n    StrictHostKeyChecking yes\n    BatchMode yes\n    ConnectionAttempts 1\n    ConnectTimeout 60\n    ServerAliveInterval 15\n    ServerAliveCountMax 2\n    ControlMaster no\n    ControlPath none\n    ControlPersist no\n    UpdateHostKeys no\n    ForwardAgent no\n    Include "' + str(session.config) + '"\n')
            config.chmod(0o600)
            masters = PrivateMasters(config, folder, ledger)
            masters.start()
            module.ssh_argv = masters.ssh_argv  # This imported instance only; original file stays byte-identical.
            preflight = module.remote_json(config, 'school103', module.REMOTE_PREFLIGHT)
            ledger({'status': 'CPU_platform_verified', 'preflight': preflight})
            for entry in entries:
                ledger({'status': 'file_started', 'entry': entry})
                result = module.relay(config, entry)
                ledger(result)
                print(json.dumps(result), flush=True)
            ledger({'status': 'stage_completed', 'seconds': time.monotonic() - stage_started})
            return 0
        except BaseException as exc:
            ledger({'status': 'failed_no_automatic_retry', 'error_type': type(exc).__name__, 'error': str(exc),
                    'seconds': time.monotonic() - stage_started, 'partial_files_and_existing_data_preserved': True})
            raise
        finally:
            module.ssh_argv = original_ssh_argv
            try:
                if masters is not None:
                    masters.close()
            finally:
                if private is not None:
                    private.cleanup()
                if session is not None and hasattr(session, 'temporary'):
                    session.temporary.cleanup()  # Do not call SchoolSession.__exit__ (it targets school104).
                signal.signal(signal.SIGTERM, old_handler)


if __name__ == '__main__':
    sys_exit = main()
    raise SystemExit(sys_exit)
