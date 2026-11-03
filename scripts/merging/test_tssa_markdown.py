import json
import tempfile
import unittest
from pathlib import Path

from tssa_markdown import encode_record, existing_record, read_record, record_path


class RecordTest(unittest.TestCase):
    def test_roundtrip_old_and_new_and_reject_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / 'record.json'
            value = {'status': 'running', 'attempts': [{'number': 1}], 'message': 'line\n```json'}
            old.write_text(json.dumps(value))
            self.assertEqual(read_record(existing_record(old)), value)
            old.unlink()
            md = record_path(old)
            md.write_bytes(encode_record(value))
            self.assertIn('**status**: running', md.read_text())
            self.assertEqual(read_record(existing_record(old)), value)
            old.write_text(json.dumps(value))
            with self.assertRaises(ValueError): existing_record(old)

    def test_legacy_multiline_jsonl_and_markdown_conflict(self):
        rows = [{'task_id': 'first', 'score': 1}, {'task_id': 'second', 'score': 2}]
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / 'heldout_per_image_metrics.jsonl'
            old.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
            self.assertEqual(read_record(existing_record(old)), rows)
            self.assertEqual(old.read_text().count('\n'), 2)
            md = record_path(old)
            md.write_bytes(encode_record(rows))
            with self.assertRaisesRegex(ValueError, 'duplicate experiment records'):
                existing_record(old)
            old.unlink()
            self.assertEqual(read_record(existing_record(old)), rows)

    def test_mvp_publish_reuses_legacy_jsonl_without_rewriting(self):
        from tssa_mvp_run import RunStore
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'run'
            store = RunStore(root, {'run_id': 'legacy-fixture'})
            try:
                old = root / 'heldout_per_image_metrics.jsonl'
                raw = '{"task_id":"one"}\n{"task_id":"two"}\n'
                old.write_text(raw)
                self.assertEqual(store.publish_bytes(old.name, raw.encode()), old.resolve())
                self.assertEqual(len(read_record(existing_record(old))), 2)
                self.assertEqual(old.read_text(), raw)
                self.assertFalse(record_path(old).exists())
            finally:
                store.close()

    def test_mvp_identity_new_resume_and_legacy(self):
        from tssa_mvp_run import RunStore
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'run'
            identity = {'run_id': 'test'}
            store = RunStore(root, identity)
            store.close()
            md = root / 'run_identity.md'
            self.assertTrue(md.is_file())
            self.assertFalse((root / 'run_identity.json').exists())
            store = RunStore(root, identity, resume=True)
            store.close()
            md.unlink()
            legacy = root / 'run_identity.json'
            legacy.write_text(json.dumps(identity))
            store = RunStore(root, identity, resume=True)
            store.close()
            self.assertFalse(md.exists())
            self.assertEqual(json.loads(legacy.read_text()), identity)
            md.write_bytes(encode_record(identity))
            with self.assertRaises(ValueError):
                RunStore(root, identity, resume=True)


if __name__ == '__main__': unittest.main()
