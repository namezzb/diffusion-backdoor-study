"""Local, single-writer accounting for a new run (not a distributed lock)."""
import fcntl
import base64
import hashlib
import html
import json
import os
from pathlib import Path
import sqlite3
import socket
from datetime import datetime, timezone


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def visible(value):
    """Keep untrusted values on one Markdown line and out of code fences."""
    return html.escape(str(value), quote=True).replace('`', '&#96;').replace('\n', '&#10;').replace('\r', '&#13;')


def writer_identity(identity):
    machine_id = Path('/etc/machine-id')
    return {**identity, 'writer_host': {'hostname': socket.gethostname(), 'uid': os.geteuid(),
            'machine_id_sha256': hashlib.sha256(machine_id.read_bytes()).hexdigest() if machine_id.is_file() else None}}


class BudgetExhausted(ValueError):
    pass


class Store:
    """Single-writer Markdown ledger; SQLite is read only for one-time migration."""
    def __init__(self, root, identity, units, budget, *, score_schema='legacy'):
        if score_schema not in ('legacy', 'semantic-v1'):
            raise ValueError('unknown score schema')
        self.score_schema, self.budget = score_schema, budget
        self.root = Path(root)
        if not self.root.is_absolute() or any(p.is_symlink() for p in (self.root, *self.root.parents)):
            raise ValueError('run_root must be absolute and have no symlink ancestry')
        identity = writer_identity({**identity, 'run_root': str(self.root.resolve())})
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = os.open(self.root / '.writer.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            md, db = self.root / 'run.md', self.root / 'run.sqlite'
            if any((self.root / name).is_symlink() for name in ('run.md', 'run.checkpoints.md', 'run.sqlite', 'run.sqlite-wal', 'run.sqlite-shm')):
                raise ValueError('ledger cannot be a symlink')
            if md.exists():
                self.data = read_markdown(md)
            elif db.exists():
                self.data = self._migrate(db)
            else:
                if any(e.name != '.writer.lock' or e.is_symlink() or not e.is_file() for e in self.root.iterdir()):
                    raise ValueError('new run directory contains unrelated files')
                self.data = {'schema': 'tcl-run-markdown-v1', 'identity': identity, 'score_schema': score_schema,
                             'units': {canonical(u['key']): {'unit': u, 'status': 'pending', 'image_sha': None, 'scores': None} for u in units},
                             'attempts': [], 'events': []}
                self._commit()
            if self.data['identity'] != identity:
                raise ValueError('run identity or scientific inputs changed')
            if self.data['score_schema'] != score_schema:
                raise ValueError('score schema changed for existing run')
            self._replay_checkpoints()
            if not md.exists(): self._commit()
            self.interrupted = [k for k, v in self.data['units'].items() if v['status'] == 'started']
        except BaseException:
            os.close(self.lock)
            raise

    def _migrate(self, path):
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            identity = json.loads(db.execute('SELECT identity FROM metadata WHERE id=1').fetchone()[0])
            has_schema = db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='score_schema'").fetchone()[0]
            row = db.execute('SELECT name FROM score_schema WHERE id=1').fetchone() if has_schema else None
            units = {k: {'unit': json.loads(u), 'status': status, 'image_sha': sha, 'scores': json.loads(scores) if scores is not None else None}
                     for k, u, status, sha, scores in db.execute('SELECT key,unit,status,image_sha,scores FROM units')}
            attempts = [{'id': i, 'key': k, 'number': n, 'status': s, 'resource': json.loads(r), 'reason': reason}
                        for i, k, n, s, r, reason in db.execute('SELECT id,key,number,status,resource,reason FROM attempts ORDER BY id')]
            events = [{'id': i, 'time': t, 'kind': k, 'detail': json.loads(d)}
                      for i, t, k, d in db.execute('SELECT id,time,kind,detail FROM events ORDER BY id')]
        return {'schema': 'tcl-run-markdown-v1', 'identity': identity, 'score_schema': row[0] if row else 'legacy', 'units': units, 'attempts': attempts, 'events': events}

    def _replay_checkpoints(self):
        path = self.root / 'run.checkpoints.md'
        if not path.exists(): return
        raw = path.read_bytes()
        complete = raw.rsplit(b'\n', 1)[0] + b'\n' if b'\n' in raw else b''
        if complete != raw:
            with path.open('r+b') as stream:
                stream.truncate(len(complete)); stream.flush(); os.fsync(stream.fileno())
        by_id = {a['id']: a for a in self.data['attempts']}
        for line in complete.splitlines():
            if line.startswith(b'- '):
                marker = b' <!-- tcl-checkpoint:'
                if marker not in line or not line.endswith(b' -->'):
                    raise ValueError('invalid Markdown checkpoint')
                encoded = line.rsplit(marker, 1)[1][:-4]
                entry = json.loads(base64.b64decode(encoded, validate=True))
            else:
                entry = json.loads(line)
            attempt = by_id[entry['attempt_id']]
            if entry['key'] != attempt['key']: raise ValueError('checkpoint key mismatch')
            resource = entry['resource']
            if not isinstance(resource, dict) or any(type(v) is not int or v < 0 for v in resource.values()):
                raise ValueError('invalid saved checkpoint')
            # A snapshot can already contain this checkpoint or a later one.
            previous = attempt['resource']
            for name, value in resource.items(): previous[name] = max(previous.get(name, 0), value)

    def _commit(self):
        import tempfile
        identity = self.data['identity']
        statuses = self.snapshot()['statuses']
        t0 = next((e for e in self.data['events'] if e['kind'] == 't0'), None)
        recent = self.data['events'][-5:]
        summary = ['# TCL run ledger', '', '## Summary', '',
                   '- Run ID: ' + visible(identity.get('run_id', '(unspecified)')),
                   '- Science SHA-256: ' + visible(identity.get('science_sha256', '(unspecified)')),
                   '- Score schema: ' + visible(self.data['score_schema']),
                   '- Unit statuses: ' + (', '.join(f'{visible(k)}: {v}' for k, v in sorted(statuses.items())) or 'none'),
                   '- Attempts: ' + str(len(self.data['attempts'])),
                   '- Original T0 (UTC): ' + visible(t0['detail'].get('time_utc', t0['time']) if t0 else 'not started'),
                   '', '## Recent events', '']
        summary.extend(f"- {visible(e['time'])} — {visible(e['kind'])}" for e in recent)
        if not recent: summary.append('- None')
        payload = '\n'.join(summary) + '\n\n## Machine-readable state\n\n```json\n' + json.dumps(self.data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n```\n'
        fd, tmp = tempfile.mkstemp(prefix='.run.', suffix='.tmp', dir=self.root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp, self.root / 'run.md')
            directory = os.open(self.root, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
            log = self.root / 'run.checkpoints.md'
            if log.exists():
                with log.open('w', encoding='utf-8') as stream:
                    stream.flush(); os.fsync(stream.fileno())
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def close(self):
        os.close(self.lock)

    def event(self, kind, detail):
        events = self.data['events']
        events.append({'id': max((e['id'] for e in events), default=0) + 1, 'time': now(), 'kind': kind, 'detail': detail})
        self._commit()

    def event_detail(self, kind, *, latest=False):
        events = [e for e in self.data['events'] if e['kind'] == kind]
        return events[-1 if latest else 0]['detail'] if events else None

    def unit_status(self, key):
        return self.data['units'][canonical(key)]['status']

    def complete_units(self):
        return [(k, v['image_sha'], v['scores']) for k, v in sorted(self.data['units'].items()) if v['status'] == 'complete']

    def reserve(self, key):
        k, state = canonical(key), key[1]
        unit = self.data['units'].get(k)
        attempts = self.data['attempts']
        own = [a for a in attempts if a['key'] == k]
        state_attempts = [a for a in attempts if json.loads(a['key'])[1] == state]
        state_units = sum(json.loads(raw)[1] == state for raw in self.data['units'])
        retry_cap = max(0, self.budget['state_max_attempts'].get(state, 0) - state_units)
        if not unit or unit['status'] != 'pending': raise ValueError('unit not pending')
        if (len(own) >= self.budget['max_attempts_per_key'] or len(attempts) >= self.budget['max_attempts']
            or len(state_attempts) >= self.budget['state_max_attempts'].get(state, 0)
            or own and sum(a['number'] > 1 for a in state_attempts) >= retry_cap):
            raise BudgetExhausted('unit or attempt budget exhausted')
        n = len(own) + 1
        attempts.append({'id': max((a['id'] for a in attempts), default=0) + 1, 'key': k, 'number': n, 'status': 'started', 'resource': {}, 'reason': None})
        unit['status'] = 'started'; self._commit()
        return n

    def checkpoint(self, key, resource):
        rows = [a for a in self.data['attempts'] if a['key'] == canonical(key) and a['status'] == 'started']
        if not rows or not isinstance(resource, dict) or any(type(v) is not int or v < 0 for v in resource.values()):
            raise ValueError('invalid resource checkpoint')
        row = rows[-1]
        if any(resource.get(name, -1) < value for name, value in row['resource'].items()):
            raise ValueError('resource counters cannot decrease')
        data = canonical({'attempt_id': row['id'], 'key': row['key'], 'resource': resource})
        encoded = base64.b64encode(data.encode()).decode('ascii')
        entry = (f"- {now()} | attempt {row['id']} (#{row['number']}) | key: `{visible(row['key'])}`"
                 f" | counters: `{visible(canonical(resource))}` <!-- tcl-checkpoint:{encoded} -->\n")
        log = self.root / 'run.checkpoints.md'
        is_new = not log.exists()
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            with os.fdopen(fd, 'a', encoding='utf-8') as stream:
                stream.write(entry); stream.flush(); os.fsync(stream.fileno())
            if is_new:
                directory = os.open(self.root, os.O_RDONLY)
                try: os.fsync(directory)
                finally: os.close(directory)
        except BaseException:
            raise
        row['resource'] = resource.copy()

    def fail(self, key, reason):
        k = canonical(key)
        rows = [a for a in self.data['attempts'] if a['key'] == k and a['status'] == 'started']
        if not rows: raise ValueError('no active attempt')
        rows[-1].update(status='failed', reason=str(reason)[:2000])
        if self.data['units'][k]['status'] == 'started': self.data['units'][k]['status'] = 'pending'
        self._commit()

    def snapshot(self):
        statuses = {}
        for unit in self.data['units'].values(): statuses[unit['status']] = statuses.get(unit['status'], 0) + 1
        return {'statuses': statuses, 'attempts': len(self.data['attempts']), 'events': len(self.data['events'])}

    def image_path(self, key):
        return self.root / 'images' / (digest(key) + '.png')

    def register_image(self, key, path):
        k = canonical(key)
        if path != self.image_path(key) or path.is_symlink() or path.parent.is_symlink() or not path.is_file(): raise ValueError('invalid image path')
        unit = self.data['units'][k]
        if unit['status'] != 'started': raise ValueError('unit not generating')
        unit.update(status='scoring', image_sha=None)
        for attempt in self.data['attempts']:
            if attempt['key'] == k and attempt['status'] == 'started': attempt['status'] = 'image_persisted'
        self._commit()
    def finish(self, key, scores):
        import math
        expected = {'vit_class', 'clip_score'}
        if self.score_schema == 'semantic-v1':
            expected |= {'target_clip_score', 'object_clip_scores'}
        if (not isinstance(scores, dict) or set(scores) != expected
                or type(scores['vit_class']) is not int or not 0 <= scores['vit_class'] < 1000
                or type(scores['clip_score']) not in (int, float) or not math.isfinite(scores['clip_score'])
                or not 0 <= scores['clip_score'] <= 100):
            raise ValueError('invalid independent scores')
        if self.score_schema == 'semantic-v1':
            objects = scores['object_clip_scores']
            values = [scores['target_clip_score']]
            if not isinstance(objects, dict) or set(objects) != {'dog', 'cat', 'rabbit', 'background'}:
                raise ValueError('invalid semantic score categories')
            values.extend(objects.values())
            if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 100 for v in values):
                raise ValueError('invalid semantic scores')
        k = canonical(key)
        unit = self.data['units'].get(k)
        path = self.image_path(key)
        if not unit or unit['status'] != 'scoring' or path.is_symlink() or not path.is_file():
            raise ValueError('registered image missing')
        unit.update(status='complete', scores=scores)
        for attempt in self.data['attempts']:
            if attempt['key'] == k and attempt['status'] == 'image_persisted': attempt['status'] = 'complete'
        self._commit()


def read_markdown(path):
    text = Path(path).read_text(encoding='utf-8')
    marker = '```json\n'
    if text.count(marker) != 1 or '\n```' not in text.split(marker, 1)[1]:
        raise ValueError('invalid Markdown ledger')
    data = json.loads(text.split(marker, 1)[1].split('\n```', 1)[0])
    if data.get('schema') != 'tcl-run-markdown-v1': raise ValueError('unknown ledger schema')
    return data
