import base64
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
DIR=ROOT/'research/tasks/2026-10-29-trigger-contrast-localization'
sys.path.insert(0,str(DIR))
import shard127_watch_controller_v2 as controller


class ControllerTests(unittest.TestCase):
    def test_observers_really_run_in_parallel_and_failure_blocks_pair(self):
        barrier=threading.Barrier(2,timeout=2)
        def observe(ssh,host,command,namespace,tmp,key):
            barrier.wait()
            return host,namespace
        with patch.object(controller,'collect_one',side_effect=observe):
            self.assertEqual(controller.collect_pair([], 'a','b','/tmp','key'),
                (('school103','tcl-shard-watch'),('school104','tcl-shard104-fence')))
        def fail(ssh,host,command,namespace,tmp,key):
            if host=='school103': raise ValueError('source unavailable')
            return host,namespace
        with patch.object(controller,'collect_one',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'source unavailable'):
                controller.collect_pair([], 'a','b','/tmp','key')

    def test_publication_uses_one_ssh_call_and_binds_both_hashes(self):
        source,fence=b'one',b'two'
        expected={'source':hashlib.sha256(source).hexdigest(),'fence':hashlib.sha256(fence).hexdigest()}
        with patch.object(controller.subprocess,'run',return_value=SimpleNamespace(stdout=json.dumps(expected).encode())) as run:
            controller.publish_pair(['ssh'],source,fence)
            self.assertEqual(run.call_count,1)
            body=json.loads(run.call_args.kwargs['input'])
            self.assertEqual(base64.b64decode(body['source']),source)
            self.assertEqual(base64.b64decode(body['fence']),fence)
        with patch.object(controller.subprocess,'run',return_value=SimpleNamespace(stdout=b'{}')):
            with self.assertRaisesRegex(ValueError,'publication differs'): controller.publish_pair(['ssh'],source,fence)

    def test_remote_publisher_writes_pair_and_rejects_expired_before_any_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); machine=root/'machine-id'; machine.write_bytes(b'machine')
            target1=root/'first'; target2=root/'second'
            script=controller.remote_publish_pair_script().replace("'/etc/machine-id'",repr(str(machine)))
            now=datetime.datetime.now(datetime.timezone.utc)
            def envelope(expires):
                record={'issued_at_utc':(now-datetime.timedelta(seconds=2)).isoformat(),'expires_at_utc':expires.isoformat()}
                return json.dumps({'message_b64':base64.b64encode(json.dumps(record).encode()).decode(),'signature_b64':'AA=='}).encode()
            def call(first,second):
                bundle=json.dumps({'source':base64.b64encode(first).decode(),'fence':base64.b64encode(second).decode()}).encode()
                return subprocess.run([sys.executable,'-c',script,str(target1),str(target2),hashlib.sha256(machine.read_bytes()).hexdigest()],input=bundle,capture_output=True)
            first=envelope(now+datetime.timedelta(seconds=20)); second=envelope(now+datetime.timedelta(seconds=15))
            self.assertEqual(call(first,second).returncode,0)
            self.assertEqual(target1.read_bytes(),first); self.assertEqual(target2.read_bytes(),second)
            expired=envelope(now-datetime.timedelta(seconds=1))
            self.assertNotEqual(call(first,expired).returncode,0)
            self.assertEqual(target1.read_bytes(),first); self.assertEqual(target2.read_bytes(),second)
            self.assertFalse(list(root.glob('.tcl-watch-*')))

if __name__=='__main__':unittest.main()
