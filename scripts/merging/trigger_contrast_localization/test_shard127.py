import base64
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_shard104_plan as fixture
import test_shard104_source_guard as source_fixture
ROOT=Path(__file__).resolve().parents[3]
DIR=ROOT/'research/tasks/2026-10-29-trigger-contrast-localization'
sys.path.insert(0,str(DIR))
import shard127_plan as plan
import shard127_104_fence as fence
import shard127_policy as policy


class Shard127Tests(unittest.TestCase):
    def test_same_partition_and_destination_identity(self):
        obj=fixture.ShardPlanTests(); obj.setUp()
        try:
            old=obj.candidate(); new=plan.build_candidate(obj.root,obj.snapshot_sha,'run',fixture.SHA,obj.rows,fixture.SEEDS,obj.bindings)
            self.assertEqual(new['allowed_keys'],old['allowed_keys'])
            self.assertEqual(len(new['allowed_keys']),1704)
            self.assertEqual(new['source_attempts_already_charged']+new['shard_attempt_limit'],2048)
            self.assertEqual(new['destination_server'],'school127')
        finally: obj.tearDown()

    def test_old_104_guard_zero_attempts_and_lock_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'old'; root.mkdir(); lock=root/'.run.lock'; lock.touch()
            machine=Path(directory)/'machine-id'; machine.write_bytes(b'fixture')
            identity={'run_id':'tcl-20261029-01-v1','manifest_sha256':fence.MANIFEST_SHA,'server':'school104','output_root':str(root)}
            raw=json.dumps(identity).encode(); (root/'shard_identity.json').write_bytes(raw)
            with patch.object(fence,'ROOT',root), patch.object(fence,'MACHINE_SHA',hashlib.sha256(machine.read_bytes()).hexdigest()):
                self.assertEqual(fence.validate_old_shard(root,machine,hashlib.sha256(raw).hexdigest())['attempts'],0)
                (root/'images').mkdir(); (root/'images/orphan.png').write_bytes(b'x')
                with self.assertRaisesRegex(ValueError,'image files'): fence.validate_old_shard(root,machine,hashlib.sha256(raw).hexdigest())
                (root/'images/orphan.png').unlink()
                with sqlite3.connect(root/'images.sqlite') as db:
                    for table in ('attempts','attempt_history','attempt_dispositions','gates'): db.execute('CREATE TABLE '+table+'(id INT)')
                    db.execute('CREATE TABLE metadata(id INT,value TEXT)')
                    db.execute('INSERT INTO metadata VALUES(1,?)',(json.dumps({'run_id':'tcl-20261029-01-v1','manifest_sha':fence.MANIFEST_SHA}),))
                self.assertEqual(fence.validate_old_shard(root,machine,hashlib.sha256(raw).hexdigest())['ledger'],'present')
                with sqlite3.connect(root/'images.sqlite') as db: db.execute('INSERT INTO attempts VALUES (1)')
                with self.assertRaisesRegex(ValueError,'attempts'): fence.validate_old_shard(root,machine,hashlib.sha256(raw).hexdigest())
            fd=os.open(lock,os.O_RDONLY)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                code='import fcntl,os,sys; fd=os.open(sys.argv[1],os.O_RDONLY); fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)'
                self.assertNotEqual(subprocess.run([sys.executable,'-c',code,str(lock)],capture_output=True).returncode,0)
            finally: os.close(fd)

    def test_signed_fence_freshness_and_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); key=root/'key'
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
            public=Path(str(key)+'.pub').read_bytes(); keysha=hashlib.sha256(public).hexdigest()
            now=datetime.datetime.now(datetime.timezone.utc)
            report={'status':'104_shard_fenced_zero_attempts','machine_sha256':policy.MACHINE_SHA,'old_identity_sha256':'a'*64,
                'plan_sha256':'b'*64,'pid':123,'pid_start_ticks':456,'lock_line':'99: FLOCK ADVISORY WRITE 123 08:01:123 0 EOF',
                'ledger':{'ledger':'absent','attempts':0},'issued_at_utc':(now-datetime.timedelta(seconds=2)).isoformat(),
                'expires_at_utc':(now+datetime.timedelta(seconds=28)).isoformat()}
            data=root/'observation'; data.write_text(json.dumps(report))
            subprocess.run(['ssh-keygen','-Y','sign','-f',str(key),'-n','tcl-shard104-fence',str(data)],check=True,capture_output=True)
            envelope=root/'watch'; envelope.write_text(json.dumps({'message_b64':base64.b64encode(data.read_bytes()).decode(),
                'signature_b64':base64.b64encode(Path(str(data)+'.sig').read_bytes()).decode()}))
            args=(envelope,public,keysha,'watcher','b'*64,'a'*64,123,456)
            self.assertTrue(policy.verify_fence(*args,now=now))
            with self.assertRaisesRegex(ValueError,'expired'): policy.verify_fence(*args,now=now+datetime.timedelta(seconds=29))
            with self.assertRaisesRegex(ValueError,'identity'): policy.verify_fence(envelope,public,keysha,'watcher','b'*64,'a'*64,124,456,now=now)

    def test_fence_observation_rejects_wrong_holder_or_released_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); root=base/'old'; root.mkdir(); lock=root/'.run.lock'; lock.touch()
            machine=base/'machine'; machine.write_bytes(b'fixture')
            identity={'run_id':'tcl-20261029-01-v1','manifest_sha256':fence.MANIFEST_SHA,'server':'school104','output_root':str(root)}
            raw=json.dumps(identity).encode(); (root/'shard_identity.json').write_bytes(raw)
            proc=base/'proc'; process=proc/'123'; process.mkdir(parents=True)
            process.joinpath('stat').write_text(source_fixture.stat_line(123,'S',0,456))
            process.joinpath('cmdline').write_bytes(b'python3\0'+os.fsencode(fence.FENCE_SCRIPT)+b'\0hold\0')
            info=lock.stat(); proc.joinpath('locks').write_text(f'8: FLOCK ADVISORY WRITE 123 {os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}:{info.st_ino} 0 EOF\n')
            with patch.object(fence,'ROOT',root), patch.object(fence,'MACHINE_SHA',hashlib.sha256(machine.read_bytes()).hexdigest()):
                args=(root,proc,machine,hashlib.sha256(raw).hexdigest(),123,456,'b'*64)
                self.assertEqual(fence.observe(*args)['ledger']['attempts'],0)
                process.joinpath('cmdline').write_bytes(b'python3\0/tmp/other\0hold\0')
                with self.assertRaisesRegex(ValueError,'command'): fence.observe(*args)
                process.joinpath('cmdline').write_bytes(b'python3\0'+os.fsencode(fence.FENCE_SCRIPT)+b'\0hold\0')
                proc.joinpath('locks').write_text('')
                with self.assertRaisesRegex(ValueError,'lock'): fence.observe(*args)

if __name__=='__main__': unittest.main()
