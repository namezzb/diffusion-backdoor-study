"""Recovery guard adversarial checks; not approval to launch."""
import fcntl
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from unittest.mock import patch
import pilot24_recovery_guard_candidate as g


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(obj, sort_keys=True, separators=(',', ':')) + '\n').encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.root = base / 'coordinator'
        self.root.mkdir()
        (self.root / '.coordinator.lock').touch()
        worker = base / 'workers' / 'S0-00-w0'
        worker.mkdir(parents=True)
        (worker / '.worker.lock').touch()
        self.bundle = base / 'bundle.json'
        self.manifest = write(self.bundle, {'run_id': g.RUN})
        unit = {'key': [g.RUN, 'source', 'clean', 'dog', 'x', 271101], 'input_sha': 'a'*64, 'mask_sha': 'b'*64}
        assignment = {'run_id': g.RUN, 'manifest_sha256': self.manifest, 'assignment_id': 'S0-00-w0', 'output_root': str(worker), 'units': [unit]}
        ap = self.root / 'assignments/S0-00-w0.json'
        ap_sha = write(ap, assignment)
        self.config = base / 'config.json'
        imports = [{'key': [g.RUN, 'source', 'clean', 'dog', str(i), 271101]} for i in range(363)]
        self.config_sha = write(self.config, {'run_id': g.RUN, 'manifest_sha256': self.manifest, 'coordinator_root': str(self.root), 'imports': imports})
        t0 = {'run_id': g.RUN, 'manifest_sha256': self.manifest, 't0_utc': g.T0}
        t0_sha = write(self.root / 't0.json', t0)
        exit_data = {'run_id': g.RUN, 'manifest_sha256': self.manifest, 'worker_id': 'w0', 't0_sha256': t0_sha, 'owned_process_group': 99999999}
        exit_sha = write(self.root / 'sessions/w0/exit.json', exit_data)
        write(self.root / 'sessions/w0/supervisor.json', {'pid': 99999998})
        terminal = {'run_id': g.RUN, 'manifest_sha256': self.manifest, 'reason': 'worker_session_blocked', 'charged_attempts': 0, 'imported': 363, 'unique_complete': 363, 'required_unique_max': 6144, 'worker_exit_verified': True, 'final_ledger_audit': {'audited': ['S0-00-w0'], 'counts_are_final': True, 'errors': []}}
        terminal_sha = write(self.root / 'terminal.json', terminal)
        self.state_sha = write(self.root / 'state.json', {'stage': 'S0', 'terminal': terminal, 't0': {**t0, 'file_sha256': t0_sha}, 'receipts': {}, 'released': {'S0': {'assignments': [{'assignment_id': 'S0-00-w0', 'path': str(ap), 'sha256': ap_sha}]}}})
        self.dbpath = worker / 'worker.sqlite'
        with sqlite3.connect(self.dbpath) as db:
            db.executescript('CREATE TABLE metadata(id INTEGER, assignment TEXT); CREATE TABLE attempts(key TEXT); CREATE TABLE units(key TEXT, input_sha TEXT, mask_sha TEXT, status TEXT, image_sha TEXT, scores TEXT);')
            db.execute('INSERT INTO metadata VALUES(1,?)', (json.dumps(assignment),))
            db.execute('INSERT INTO units VALUES(?,?,?,?,?,?)', (json.dumps(unit['key'], separators=(',', ':')), unit['input_sha'], unit['mask_sha'], 'unstarted', None, None))
        p = patch.multiple(g, MANIFEST=self.manifest, T0_SHA=t0_sha, TERMINAL_SHA=terminal_sha,
                           ORIGINAL_ROOT=str(self.root), ORIGINAL_BUNDLE=str(self.bundle), ORIGINAL_CONFIG=str(self.config),
                           CONFIG_SHA=self.config_sha, STATE_SHA=self.state_sha,
                           ORIGINAL_LEDGER_SHA=hashlib.sha256(self.dbpath.read_bytes()).hexdigest())
        p.start(); self.addCleanup(p.stop)
        original = g._read
        def read(path, sha):
            return original(path, exit_sha if str(path).endswith('/sessions/w0/exit.json') else sha)
        p = patch.object(g, '_read', side_effect=read)
        p.start(); self.addCleanup(p.stop)

    def hold(self, now=None):
        return g.hold_predecessor(coordinator_root=self.root, original_bundle=self.bundle, original_config=self.config, expected_config_sha=self.config_sha, expected_state_sha=self.state_sha, expected_bundle_sha=self.manifest, now=now or datetime.fromisoformat(g.T0))

    def test_held_lock_and_inherited_budget(self):
        with self.hold() as result:
            self.assertEqual((result['imports'], result['previous_new_attempts'], result['max_new_attempts']), (363, 0, 5909))
            fd = os.open(self.root / '.coordinator.lock', os.O_RDWR)
            try:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally: os.close(fd)

    def test_attempt_fails_closed(self):
        with sqlite3.connect(self.dbpath) as db: db.execute("INSERT INTO attempts VALUES('started')")
        with self.assertRaisesRegex(ValueError, 'charged attempts'):
            with self.hold(): pass

    def test_alive_worker_fails_closed(self):
        with patch.object(g.os, 'killpg', return_value=None):
            with self.assertRaisesRegex(ValueError, 'still exists'):
                with self.hold(): pass

    def test_hash_and_deadline_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'outside original'):
            with self.hold(datetime.fromisoformat('2026-11-03T06:08:50.071881+00:00')): pass
        (self.root / 'terminal.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            with self.hold(): pass

    def test_original_t0_requires_explicit_fixed_reviewed_mapping(self):
        from pilot24_watchdog import create_t0, load_t0
        # Use the actual predecessor bytes and digest, not a mock clock.
        original_manifest = '5f635ed4654cc2de6c24ee5a33936041819468c07b1bb4a9c644821b0e0e29ec'
        original_t0_sha = 'd8c58e2f670ba85478bcba8083323ddaff9a372f200976e076e46f38440e7449'
        path = self.root.parent / 't0-original.json'
        with patch.object(g, 'MANIFEST', original_manifest), patch.object(g, 'T0_SHA', original_t0_sha):
            self.assertEqual(create_t0(path, original_manifest, now_utc=g.T0), original_t0_sha)
            amended_sha = 'f' * 64
            self.assertEqual(load_t0(path, original_t0_sha, amended_sha,
                                      original_manifest_sha=original_manifest)['t0_utc'], g.T0)
            with self.assertRaisesRegex(ValueError, 'different run'):
                load_t0(path, original_t0_sha, amended_sha)
            with self.assertRaisesRegex(ValueError, 'predecessor T0 lineage'):
                load_t0(path, original_t0_sha, amended_sha, original_manifest_sha='a' * 64)

    def test_existing_worker_lock_fails_closed(self):
        fd = os.open(self.dbpath.parent / '.worker.lock', os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                with self.hold(): pass
        finally: os.close(fd)

    def test_inherited_lock_survives_coordinator_exit(self):
        with self.hold() as result:
            g.validate_inherited_locks(self.root, result['lock_fds'])
            child = subprocess.Popen([sys.executable, '-c', 'import sys;sys.stdin.read()'],
                                     stdin=subprocess.PIPE, pass_fds=result['lock_fds'])
        try:
            fd = os.open(self.root / '.coordinator.lock', os.O_RDWR)
            try:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally: os.close(fd)
        finally:
            child.stdin.close()
            child.wait(timeout=5)

    def test_missing_or_forged_lock_descriptors_are_rejected(self):
        with self.hold() as result:
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                g.validate_inherited_locks(self.root, result['lock_fds'][:1])
            fd = os.open(self.root / 'terminal.json', os.O_RDONLY)
            try:
                with self.assertRaisesRegex(ValueError, 'inode mismatch'):
                    g.validate_inherited_locks(self.root, (result['lock_fds'][0], fd))
            finally:
                os.close(fd)

    def test_same_inode_but_different_unlocked_open_is_rejected(self):
        with self.hold() as result:
            # A owns the flock; B refers to the very same inode but is a
            # different open file description and therefore owns no lock.
            forged = os.open(self.dbpath.parent / '.worker.lock', os.O_RDWR)
            try:
                with self.assertRaisesRegex(ValueError, 'does not own'):
                    g.validate_inherited_locks(self.root, (result['lock_fds'][0], forged))
            finally:
                os.close(forged)

    def test_real_supervisor_and_worker_keep_locks_after_coordinator_kill(self):
        ready, stop = self.root.parent / 'ready', self.root.parent / 'stop'
        worker_code = ('import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); '
                       'p=pathlib.Path(sys.argv[2]);\nwhile not p.exists(): time.sleep(.02)')
        supervisor_code = '''import sys, os
from datetime import datetime, timezone
import pilot24_recovery_guard_candidate as guard
from pilot24_watchdog import supervise
root, ready, stop, worker = sys.argv[1:5]
fds = tuple(int(x) for x in os.environ['FDS'].split(','))
guard.ORIGINAL_ROOT = root
guard.validate_inherited_locks(root, fds)
supervise([sys.executable, '-c', worker, ready, stop], datetime.now(timezone.utc).isoformat(), pass_fds=fds)
'''
        coordinator_code = '''import fcntl, os, subprocess, sys
root, worker_lock, ready, stop, supervisor, worker = sys.argv[1:]
paths = [root + '/.coordinator.lock', worker_lock]
fds = tuple(os.open(p, os.O_RDWR) for p in paths)
for fd in fds: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
env = os.environ.copy(); env['FDS'] = ','.join(map(str, fds))
subprocess.Popen([sys.executable, '-c', supervisor, root, ready, stop, worker], env=env, pass_fds=fds)
sys.stdin.read()
'''
        env = os.environ.copy()
        env['PYTHONPATH'] = str(Path(__file__).resolve().parent)
        proc = subprocess.Popen([sys.executable, '-c', coordinator_code, str(self.root),
                                 str(self.dbpath.parent / '.worker.lock'), str(ready), str(stop),
                                 supervisor_code, worker_code], stdin=subprocess.PIPE, env=env)
        try:
            until = time.monotonic() + 5
            while not ready.exists() and proc.poll() is None and time.monotonic() < until:
                time.sleep(.02)
            self.assertTrue(ready.exists(), 'supervisor and worker did not start')
            proc.kill(); proc.wait(timeout=5)
            for path in (self.root / '.coordinator.lock', self.dbpath.parent / '.worker.lock'):
                fd = os.open(path, os.O_RDWR)
                try:
                    with self.assertRaises(BlockingIOError): fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally: os.close(fd)
            stop.touch()
            until = time.monotonic() + 6
            while True:
                fd = os.open(self.root / '.coordinator.lock', os.O_RDWR)
                try:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= until: self.fail('lock not released after worker exit')
                finally: os.close(fd)
                time.sleep(.05)
        finally:
            stop.touch(exist_ok=True)
            if proc.poll() is None: proc.kill(); proc.wait(timeout=5)
            proc.stdin.close()

    def test_amendment_cannot_change_science_or_retries(self):
        from pilot24_coordinator import stage_contract
        original = {'run_id': g.RUN, 'repository_root': '/old', 'review_file': '/old/review',
                    'code_sha256': {'a': 'old'}, 'inputs': {'prompts': 'fixed'}, 'execution_root': str(self.root.parent)}
        manifest = write(self.bundle, original)
        old_assignment = {'assignment_id': 'a', 'stage': 'S0', 'manifest_sha256': manifest,
                          'gate_sha256': stage_contract(manifest, 'S0'), 'output_root': str(self.root.parent / 'workers/a'),
                          'retry_tokens': 1, 'units': [{'key': ['fixed']}], 'server': '104', 'gpu_uuid': 'fixed'}
        old_config = {'manifest_sha256': manifest, 'coordinator_root': str(self.root),
                      'assignments': [old_assignment], 'imports': [{'key': 'fixed'}], 'units': ['fixed']}
        config_sha = write(self.config, old_config)
        new_sha = 'f' * 64
        revised = {**original, 'repository_root': '/new', 'review_file': '/new/review', 'code_sha256': {'a': 'new'}}
        config = copy.deepcopy(old_config)
        config['manifest_sha256'] = new_sha
        config['coordinator_root'] = str(self.root.parent / 'recovery-v1/coordinator')
        config['recovery'] = {'original_bundle': str(self.bundle), 'original_config': str(self.config),
            'original_config_sha256': config_sha, 'original_state_sha256': self.state_sha,
            'original_coordinator_root': str(self.root), 'original_t0_sha256': g.T0_SHA,
            'original_terminal_sha256': g.TERMINAL_SHA}
        config['assignments'][0].update(manifest_sha256=new_sha, gate_sha256=stage_contract(new_sha, 'S0'),
                                      output_root=str(self.root.parent / 'recovery-v1/workers/a'))
        review = {'original_manifest_sha256': manifest, 'original_t0_sha256': g.T0_SHA,
                  'original_terminal_sha256': g.TERMINAL_SHA}
        with patch.multiple(g, MANIFEST=manifest, CONFIG_SHA=config_sha):
            self.assertEqual(g.validate_amendment(revised, config, review, new_sha), config['recovery'])
            changed = copy.deepcopy(config)
            changed['assignments'][0]['retry_tokens'] += 1
            with self.assertRaisesRegex(ValueError, 'budget changed'):
                g.validate_amendment(revised, changed, review, new_sha)
            changed = copy.deepcopy(config)
            changed['units'].append('unapproved')
            with self.assertRaisesRegex(ValueError, 'scientific configuration'):
                g.validate_amendment(revised, changed, review, new_sha)
            changed_bundle = copy.deepcopy(revised)
            changed_bundle['inputs']['prompts'] = 'new'
            with self.assertRaisesRegex(ValueError, 'scientific bundle'):
                g.validate_amendment(changed_bundle, config, review, new_sha)
            for field, forged in [('original_state_sha256','9'*64), ('original_config_sha256','8'*64),
                                  ('original_coordinator_root',str(self.root.parent/'cloned-coordinator'))]:
                changed=copy.deepcopy(config); changed['recovery'][field]=forged
                with self.assertRaisesRegex(ValueError,'original coordinator'):
                    g.validate_amendment(revised,changed,review,new_sha)

if __name__ == '__main__': unittest.main()
