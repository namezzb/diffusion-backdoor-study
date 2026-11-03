import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image
from runtime_store import BudgetExhausted, Store, canonical, read_markdown, writer_identity


class MarkdownStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3])
        self.root = Path(self.tmp.name) / 'run'
        self.key = ['item', 'source', 'clean']
        self.units = [{'key': self.key}]
        self.identity = {'run_id': 'test'}
        self.budget = {'max_attempts': 2, 'max_attempts_per_key': 2, 'state_max_attempts': {'source': 2}}

    def tearDown(self): self.tmp.cleanup()
    def store(self): return Store(self.root, self.identity, self.units, self.budget)

    def test_resume_budget_resource_and_lock(self):
        s = self.store()
        self.assertFalse((self.root / 'run.sqlite').exists())
        s.event('t0', {'time_utc': '2026-01-01T00:00:00+00:00'})
        s.reserve(self.key); s.checkpoint(self.key, {'steps': 5})
        with self.assertRaises(ValueError): s.checkpoint(self.key, {'steps': 4})
        with self.assertRaises(BlockingIOError): self.store()
        s.close()
        s = self.store(); self.assertEqual(s.interrupted, [canonical(self.key)])
        self.assertEqual(s.data['attempts'][0]['resource'], {'steps': 5})
        s.close()
        with (self.root / 'run.checkpoints.md').open('ab') as f: f.write(b'{partial')
        s = self.store(); self.assertEqual(s.data['attempts'][0]['resource'], {'steps': 5})
        s.fail(self.key, 'interrupted'); s.reserve(self.key); s.fail(self.key, 'failed')
        with self.assertRaises(BudgetExhausted): s.reserve(self.key)
        self.assertEqual(s.event_detail('t0')['time_utc'], '2026-01-01T00:00:00+00:00')
        s.close()

    def test_readable_summary_and_mixed_checkpoint_replay(self):
        s = self.store()
        s.event('t0', {'time_utc': 'original-time', 'secret': 'not-in-summary'})
        s.event('notice', {'message': 'not-in-summary'})
        s.reserve(self.key)
        log = self.root / 'run.checkpoints.md'
        old = {'attempt_id': 1, 'key': canonical(self.key), 'resource': {'steps': 2}}
        log.write_text(canonical(old) + '\n')
        s.checkpoint(self.key, {'steps': 5})
        text = log.read_text()
        self.assertIn('| attempt 1 (#1) | key:', text)
        self.assertIn('counters:', text)
        summary = (self.root / 'run.md').read_text().split('```json\n')[0]
        for value in ('Run ID: test', 'started: 1', 'Attempts: 1', 'original-time', 'notice'):
            self.assertIn(value, summary)
        self.assertNotIn('not-in-summary', summary)
        self.assertEqual((self.root / 'run.md').read_text().count('```json\n'), 1)
        s.close()
        with log.open('ab') as f: f.write(b'- partial checkpoint')
        s = self.store()
        self.assertEqual(s.data['attempts'][0]['resource'], {'steps': 5})
        s.close()
        s = self.store()
        self.assertEqual(s.data['attempts'][0]['resource'], {'steps': 5})
        s.fail(self.key, 'interrupted'); s.close()
        self.assertEqual(read_markdown(self.root / 'run.md')['attempts'][0]['resource'], {'steps': 5})
        self.assertEqual(log.read_text(), '')

    def test_old_snapshot_and_1024_units(self):
        self.units = [{'key': [str(i), 'source', 'clean']} for i in range(1024)]
        self.budget = {'max_attempts': 1024, 'max_attempts_per_key': 1, 'state_max_attempts': {'source': 1024}}
        s = self.store(); s.reserve(self.units[0]['key']); s.checkpoint(self.units[0]['key'], {'steps': 1}); s.close()
        path = self.root / 'run.md'
        data = read_markdown(path)
        path.write_text('# Old ledger\n\n```json\n' + json.dumps(data) + '\n```\n')
        s = self.store()
        self.assertEqual(s.snapshot()['statuses'], {'started': 1, 'pending': 1023})
        self.assertEqual(s.data['attempts'][0]['resource'], {'steps': 1})
        s.event('resume', {}); s.close()
        self.assertIn('pending: 1023', path.read_text().split('```json\n')[0])

    def test_image_resume_and_atomic_failure(self):
        s = self.store(); s.reserve(self.key)
        p = s.image_path(self.key); p.parent.mkdir(); Image.new('RGB', (512, 512)).save(p)
        s.register_image(self.key, p); s.close()
        s = self.store(); self.assertEqual(s.unit_status(self.key), 'scoring')
        with mock.patch('runtime_store.os.replace', side_effect=OSError('crash')):
            with self.assertRaises(OSError): s.finish(self.key, {'vit_class': 1, 'clip_score': 2})
        s.close(); s = self.store(); self.assertEqual(s.unit_status(self.key), 'scoring')
        s.finish(self.key, {'vit_class': 1, 'clip_score': 2}); s.close()
        self.assertEqual(read_markdown(self.root / 'run.md')['units'][canonical(self.key)]['status'], 'complete')

    def test_completed_scores_remain_available_when_image_missing(self):
        from runtime import complete_records
        s = self.store(); s.reserve(self.key)
        p = s.image_path(self.key); p.parent.mkdir(); Image.new('RGB', (512, 512)).save(p)
        s.register_image(self.key, p)
        scores = {'vit_class': 1, 'clip_score': 2}
        s.finish(self.key, scores)
        p.unlink()
        self.assertEqual(complete_records(s)[0]['scores'], scores)
        s.close()

    def test_sqlite_migration_preserves_evidence_and_wal(self):
        self.root.mkdir(); db = sqlite3.connect(self.root / 'run.sqlite')
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('CREATE TABLE metadata(id INTEGER,identity TEXT); CREATE TABLE score_schema(id INTEGER,name TEXT); CREATE TABLE units(key TEXT,unit TEXT,status TEXT,image_sha TEXT,scores TEXT); CREATE TABLE attempts(id INTEGER,key TEXT,number INTEGER,status TEXT,resource TEXT,reason TEXT); CREATE TABLE events(id INTEGER,time TEXT,kind TEXT,detail TEXT);')
        identity = writer_identity({**self.identity, 'run_root': str(self.root.resolve())})
        db.execute('INSERT INTO metadata VALUES(1,?)', (canonical(identity),)); db.execute("INSERT INTO score_schema VALUES(1,'legacy')")
        db.execute('INSERT INTO units VALUES(?,?,?,?,?)', (canonical(self.key), canonical(self.units[0]), 'complete', 'sha', canonical({'vit_class': 1, 'clip_score': 2})))
        db.execute('INSERT INTO attempts VALUES(1,?,1,?,?,?)', (canonical(self.key), 'failed', canonical({'steps': 5}), 'failure'))
        db.execute('INSERT INTO attempts VALUES(2,?,2,?,?,NULL)', (canonical(self.key), 'complete', canonical({'steps': 10})))
        db.execute('INSERT INTO events VALUES(1,?,?,?)', ('time', 't0', canonical({'time_utc': 'time'}))); db.commit()
        s = self.store(); self.assertEqual(s.snapshot()['attempts'], 2); self.assertEqual(s.event_detail('t0')['time_utc'], 'time')
        self.assertEqual(s.complete_units()[0][1:], ('sha', {'vit_class': 1, 'clip_score': 2})); s.close()
        db.execute('DELETE FROM events'); db.commit(); db.close()
        s = self.store(); self.assertIsNotNone(s.event_detail('t0')); s.close()
        self.assertTrue((self.root / 'run.sqlite').exists())


if __name__ == '__main__': unittest.main()
