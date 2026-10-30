import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3] / 'research/tasks/2026-10-29-trigger-contrast-localization'
sys.path.insert(0, str(ROOT))
import shard104_runner as runner


class RunnerTests(unittest.TestCase):
    def test_review_signature_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); key = root / 'key'
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
            public = Path(str(key)+'.pub'); public_sha=hashlib.sha256(public.read_bytes()).hexdigest()
            data = json.dumps({'decision':'approved','reviewer':'reviewer','reviewer_key_sha256':public_sha}).encode()
            msg = root/'review'; msg.write_bytes(data)
            subprocess.run(['ssh-keygen','-Y','sign','-f',str(key),'-n','tcl-shard-review',str(msg)],capture_output=True,check=True)
            sig = Path(str(msg)+'.sig').read_bytes(); envelope = root/'envelope'
            envelope.write_text(json.dumps({'message_b64':base64.b64encode(data).decode(),'signature_b64':base64.b64encode(sig).decode()}))
            self.assertEqual(runner.signed_review(envelope,public,public_sha)[0]['decision'],'approved')
            bad = data.replace(b'approved',b'rejected')
            envelope.write_text(json.dumps({'message_b64':base64.b64encode(bad).decode(),'signature_b64':base64.b64encode(sig).decode()}))
            with self.assertRaisesRegex(ValueError,'signature'):
                runner.signed_review(envelope,public,public_sha)

    def test_readonly_localization_requires_matching_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'local.sqlite'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE forwards(unit,class,context,status,output_sha,output)')
            db.execute('INSERT INTO forwards VALUES(?,?,?,?,?,?)',('unit','dog','context','complete',hashlib.sha256(b'fixed').hexdigest(),b'fixed'))
            db.commit(); db.close()
            local=runner.ReadOnlyLocalization(path,['context'])
            self.assertEqual(local.load('unit','dog','context'),b'fixed')
            with self.assertRaises(sqlite3.OperationalError): local.db.execute('DELETE FROM forwards')
            with self.assertRaisesRegex(ValueError,'unavailable'): local.load('unit','cat','context')
            local.db.close()

if __name__=='__main__': unittest.main()
