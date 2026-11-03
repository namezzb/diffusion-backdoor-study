"""Local, single-writer accounting for a new run (not a distributed lock)."""
import fcntl
import hashlib
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


def writer_identity(identity):
    machine_id = Path('/etc/machine-id')
    return {**identity, 'writer_host': {'hostname': socket.gethostname(), 'uid': os.geteuid(),
            'machine_id_sha256': hashlib.sha256(machine_id.read_bytes()).hexdigest() if machine_id.is_file() else None}}


class BudgetExhausted(ValueError):
    pass


class Store:
    def __init__(self, root, identity, units, budget, *, score_schema='legacy'):
        if score_schema not in ('legacy', 'semantic-v1'):
            raise ValueError('unknown score schema')
        self.score_schema = score_schema
        self.root = Path(root)
        if not self.root.is_absolute() or any(p.is_symlink() for p in (self.root, *self.root.parents)):
            raise ValueError('run_root must be absolute and have no symlink ancestry')
        identity = writer_identity({**identity, 'run_root': str(self.root.resolve())})
        if self.root.exists() and not (self.root / 'run.sqlite').exists():
            for entry in self.root.iterdir():
                if entry.name != '.writer.lock' or entry.is_symlink() or not entry.is_file():
                    raise ValueError('new run directory must be empty apart from its ordinary writer lock')
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = os.open(self.root / '.writer.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not (self.root / 'run.sqlite').exists():
                for entry in self.root.iterdir():
                    if entry.name != '.writer.lock' or entry.is_symlink() or not entry.is_file():
                        raise ValueError('new run directory contains unrelated files')
            for suffix in ('', '-wal', '-shm'):
                if (self.root / ('run.sqlite' + suffix)).is_symlink():
                    raise ValueError('database cannot be a symlink')
            self.db = sqlite3.connect(self.root / 'run.sqlite', isolation_level=None)
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1), identity TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS score_schema (id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS units (key TEXT PRIMARY KEY, unit TEXT NOT NULL, status TEXT NOT NULL, image_sha TEXT, scores TEXT);
                CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, key TEXT NOT NULL, number INTEGER NOT NULL, status TEXT NOT NULL, resource TEXT NOT NULL, reason TEXT, UNIQUE(key,number));
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, time TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
            ''')
            self.db.execute('BEGIN IMMEDIATE')
            existing = self.db.execute('SELECT identity FROM metadata WHERE id=1').fetchone()
            if existing is None:
                self.db.execute('INSERT INTO metadata VALUES(1,?)', (canonical(identity),))
                self.db.executemany('INSERT INTO units VALUES(?,?,?,NULL,NULL)', [(canonical(u['key']), canonical(u), 'pending') for u in units])
            elif existing[0] != canonical(identity):
                raise ValueError('run identity or scientific inputs changed')
            saved_schema = self.db.execute('SELECT name FROM score_schema WHERE id=1').fetchone()
            if saved_schema is None:
                if existing is not None and score_schema != 'legacy':
                    raise ValueError('existing legacy run cannot change score schema')
                self.db.execute('INSERT INTO score_schema VALUES(1,?)', (score_schema,))
            elif saved_schema[0] != score_schema:
                raise ValueError('score schema changed for existing run')
            self.db.execute('COMMIT')
            self.budget = budget
            self.state_units = {}
            self.state_used = {}
            self.state_retries = {}
            for (raw,) in self.db.execute('SELECT key FROM units'):
                state = json.loads(raw)[1]
                self.state_units[state] = self.state_units.get(state, 0) + 1
            for raw, number in self.db.execute('SELECT key,number FROM attempts'):
                state = json.loads(raw)[1]
                self.state_used[state] = self.state_used.get(state, 0) + 1
                if number > 1:
                    self.state_retries[state] = self.state_retries.get(state, 0) + 1
            # A prior process cannot remain a writer while this flock is held.
            # An existing image is reconciled by the caller; never silently replay it.
            self.interrupted = [r[0] for r in self.db.execute("SELECT key FROM units WHERE status='started'")]
        except Exception:
            if hasattr(self, 'db'):
                if self.db.in_transaction:
                    self.db.execute('ROLLBACK')
                self.db.close()
            os.close(self.lock)
            raise

    def close(self):
        self.db.close()
        os.close(self.lock)

    def event(self, kind, detail):
        self.db.execute('INSERT INTO events(time,kind,detail) VALUES(?,?,?)', (now(), kind, canonical(detail)))

    def reserve(self, key):
        k = canonical(key)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT status FROM units WHERE key=?', (k,)).fetchone()
            count = self.db.execute('SELECT COUNT(*) FROM attempts WHERE key=?', (k,)).fetchone()[0]
            total = self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
            state = key[1]
            state_used = self.state_used.get(state, 0)
            state_cap = self.budget['state_max_attempts'].get(state, 0)
            state_units = self.state_units.get(state, 0)
            state_retries = self.state_retries.get(state, 0)
            retry_cap = max(0, state_cap - state_units)
            if not row or row[0] != 'pending':
                raise ValueError('unit not pending')
            if (count >= self.budget['max_attempts_per_key'] or total >= self.budget['max_attempts']
                    or state_used >= state_cap or count > 0 and state_retries >= retry_cap):
                raise BudgetExhausted('unit or attempt budget exhausted')
            self.db.execute("INSERT INTO attempts(key,number,status,resource) VALUES(?,?,'started','{}')", (k, count + 1))
            self.db.execute("UPDATE units SET status='started' WHERE key=?", (k,))
            self.db.execute('COMMIT')
            self.state_used[state] = state_used + 1
            if count:
                self.state_retries[state] = state_retries + 1
            return count + 1
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def checkpoint(self, key, resource):
        k = canonical(key)
        row = self.db.execute("SELECT id,resource FROM attempts WHERE key=? AND status='started' ORDER BY number DESC LIMIT 1", (k,)).fetchone()
        if not row or not isinstance(resource, dict) or any(type(v) is not int or v < 0 for v in resource.values()):
            raise ValueError('invalid resource checkpoint')
        previous = json.loads(row[1])
        if any(resource.get(name, -1) < value for name, value in previous.items()):
            raise ValueError('resource counters cannot decrease')
        self.db.execute('UPDATE attempts SET resource=? WHERE id=?', (canonical(resource), row[0]))

    def fail(self, key, reason):
        k = canonical(key)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute("SELECT id FROM attempts WHERE key=? AND status='started' ORDER BY number DESC LIMIT 1", (k,)).fetchone()
            if row is None:
                raise ValueError('no active attempt')
            self.db.execute("UPDATE attempts SET status='failed',reason=? WHERE id=?", (str(reason)[:2000], row[0]))
            self.db.execute("UPDATE units SET status='pending' WHERE key=? AND status='started'", (k,))
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def snapshot(self):
        return {'statuses': dict(self.db.execute('SELECT status,COUNT(*) FROM units GROUP BY status')),
                'attempts': self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],
                'events': self.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]}

    def image_path(self, key):
        return self.root / 'images' / (digest(key) + '.png')

    def register_image(self, key, path):
        from PIL import Image
        k = canonical(key)
        if path != self.image_path(key) or path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise ValueError('invalid image path')
        with Image.open(path) as image:
            if image.format != 'PNG' or image.size != (512, 512):
                raise ValueError('expected 512x512 PNG')
            image.verify()
        with Image.open(path) as image:
            image.load()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            cur = self.db.execute("UPDATE units SET status='scoring',image_sha=? WHERE key=? AND status='started'", (sha, k))
            if cur.rowcount != 1:
                raise ValueError('unit not generating')
            self.db.execute("UPDATE attempts SET status='image_persisted' WHERE key=? AND status='started'", (k,))
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise

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
        row = self.db.execute('SELECT status,image_sha FROM units WHERE key=?', (k,)).fetchone()
        path = self.image_path(key)
        if not row or row[0] != 'scoring' or path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row[1]:
            raise ValueError('registered image changed')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute("UPDATE units SET status='complete',scores=? WHERE key=?", (canonical(scores), k))
            self.db.execute("UPDATE attempts SET status='complete' WHERE key=? AND status='image_persisted'", (k,))
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise
