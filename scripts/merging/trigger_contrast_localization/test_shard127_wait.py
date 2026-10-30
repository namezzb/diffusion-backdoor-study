import base64
import datetime
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
DIR=ROOT/'research/tasks/2026-10-29-trigger-contrast-localization'
sys.path.insert(0,str(DIR))
import shard127_watch_wait as wait
import shard104_policy as original_policy
import shard127_policy as original_fence
import shard127_wait_launcher as wait_launcher
import test_shard104_policy as ledger_fixture


def envelope(issued,expires):
    data=json.dumps({'issued_at_utc':issued.isoformat(),'expires_at_utc':expires.isoformat()}).encode()
    return json.dumps({'message_b64':base64.b64encode(data).decode(),'signature_b64':'fixture'}).encode()


class WaitTests(unittest.TestCase):
    def test_signature_cache_is_exact_bounded_and_never_caches_failures(self):
        clock=[0]; calls=[]
        def verifier(*args):
            calls.append(args)
            if args[1]==b'bad':raise ValueError('invalid signature')
        cached=wait.SignatureCache(verifier,monotonic=lambda:clock[0])
        original=(b'message',b'signature',b'pub','sha','principal','tcl-shard-watch')
        cached(*original);cached(*original)
        self.assertEqual(len(calls),1)
        for index,value in ((0,b'changed'),(1,b'changed'),(2,b'changed'),(3,'changed'),(4,'changed'),(5,'tcl-shard104-fence')):
            changed=list(original);changed[index]=value;cached(*changed)
        self.assertEqual(len(calls),7)
        self.assertLessEqual(len(cached.entries),4)
        bad=list(original);bad[1]=b'bad'
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'invalid'):cached(*bad)
        self.assertEqual(len(calls),9)
        clock[0]=31;cached(*original);self.assertEqual(len(calls),10)
        external=list(original);external[5]='tcl-resource-amendment'
        cached(*external);cached(*external);self.assertEqual(len(calls),12)

    def test_cached_crypto_does_not_skip_identity_or_expiry_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);key=root/'key'
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
            public=Path(str(key)+'.pub').read_bytes();key_sha=hashlib.sha256(public).hexdigest()
            now=datetime.datetime.now(datetime.timezone.utc)
            record={'status':'source_quiescent_observation','plan_sha256':'c'*64,'run_id':'run',
                'manifest_sha256':'a'*64,'source_machine_sha256':'d'*64,'source_attempts_logical_sha256':'b'*64,
                'pid':586456,'pid_start_ticks':9222972,'threads':[{'pid':586456,'start_ticks':9222972,'flags':4,'fdsize':0},
                {'pid':588542,'start_ticks':9253469,'flags':4,'fdsize':0}],
                'lock_line':'8: FLOCK ADVISORY WRITE 586456 08:01:337064389 0 EOF',
                'issued_at_utc':now.isoformat(),'expires_at_utc':(now+datetime.timedelta(seconds=30)).isoformat()}
            msg=root/'message';msg.write_text(json.dumps(record,sort_keys=True))
            subprocess.run(['ssh-keygen','-Y','sign','-f',str(key),'-n','tcl-shard-watch',str(msg)],check=True,capture_output=True)
            envelope_path=root/'watch';envelope_path.write_text(json.dumps({'message_b64':base64.b64encode(msg.read_bytes()).decode(),
                'signature_b64':base64.b64encode(Path(str(msg)+'.sig').read_bytes()).decode()}))
            plan={'run_id':'run','manifest_sha256':'a'*64,'source_attempts_logical_sha256':'b'*64}
            args=(envelope_path,public,key_sha,'watcher','c'*64,plan,'d'*64)
            with patch.object(original_policy,'verify_signature',wait.SignatureCache(original_policy.verify_signature)):
                original_policy.verify_watch(*args,now=now)
                with self.assertRaisesRegex(ValueError,'expired'):
                    original_policy.verify_watch(*args,now=now+datetime.timedelta(seconds=31))
                with self.assertRaisesRegex(ValueError,'identity'):
                    original_policy.verify_watch(envelope_path,public,key_sha,'watcher','e'*64,plan,'d'*64,now=now)

    def test_replaced_witness_is_reverified_even_if_bytes_are_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'witness';path.write_bytes(b'unchanged')
            calls=[];state=SimpleNamespace(receipts={})
            cache=wait.SignatureCache(lambda *args:calls.append(args))
            def original(path):
                cache(b'message',b'sig',b'pub','sha','principal','tcl-shard-watch')
                return {'expires_at_utc':(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=20)).isoformat()}
            checked=wait.checked_verifier(original,'source',state,cache)
            checked(path);checked(path);self.assertEqual(len(calls),1)
            replacement=root/'replacement';replacement.write_bytes(path.read_bytes());replacement.replace(path)
            checked(path);self.assertEqual(len(calls),2)
    def test_only_definite_expiry_or_missing_is_waitable(self):
        now=datetime.datetime.now(datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'source'; state=SimpleNamespace(receipts={})
            def expired(*args,**kwargs): raise ValueError('source witness expired or invalid')
            check=wait.checked_verifier(expired,'source',state)
            p.write_bytes(envelope(now-datetime.timedelta(seconds=40),now-datetime.timedelta(seconds=10)))
            with self.assertRaises(wait.FreshWitnessPending): check(p)
            p.write_bytes(envelope(now+datetime.timedelta(seconds=1),now+datetime.timedelta(seconds=20)))
            with self.assertRaisesRegex(ValueError,'expired or invalid'): check(p)
            p.write_bytes(envelope(now-datetime.timedelta(seconds=90),now-datetime.timedelta(seconds=10)))
            with self.assertRaisesRegex(ValueError,'expired or invalid'): check(p)
            def badsig(*args,**kwargs):raise ValueError('detached signature failed verification')
            with self.assertRaisesRegex(ValueError,'signature'):wait.checked_verifier(badsig,'source',state)(p)
            def missing(*args,**kwargs):raise ValueError('live source witness unavailable')
            p.unlink()
            with self.assertRaises(wait.FreshWitnessPending):wait.checked_verifier(missing,'source',state)(p)

    def test_resume_rechecks_both_and_timeout_does_not_compute(self):
        state=SimpleNamespace(receipts={}); events=[]; calls=[]
        future=datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=25)
        def raw():
            calls.append(len(calls))
            if len(calls)==1: raise wait.FreshWitnessPending('fence expired')
            state.receipts={'source':future,'fence':future}
        guard=wait.WitnessGuard(raw,state,lambda *args:events.append(args),sleep=lambda _:None)
        guard.check()
        self.assertEqual(len(calls),2)
        self.assertEqual([e[0] for e in events],['watch_wait_started','watch_wait_resumed'])
        clock=[0]; calls=[]
        def sleep(n):clock[0]+=n
        def stale():calls.append(1);raise wait.FreshWitnessPending('expired')
        with patch.object(wait,'RETRY_SECONDS',1), patch.object(wait,'POLL_SECONDS',.25):
            guard=wait.WitnessGuard(stale,state,monotonic=lambda:clock[0],sleep=sleep)
            with self.assertRaises(TimeoutError):guard.check()
        self.assertEqual(clock[0],1)

    def test_one_witness_expiring_during_pair_verification_is_not_accepted(self):
        state=SimpleNamespace(receipts={}); calls=[]
        def raw():
            calls.append(1)
            now=datetime.datetime.now(datetime.timezone.utc)
            state.receipts={'source':now-datetime.timedelta(microseconds=1),'fence':now+datetime.timedelta(seconds=20)}
        clock=[0]
        with patch.object(wait,'RETRY_SECONDS',.5):
            guard=wait.WitnessGuard(raw,state,monotonic=lambda:clock[0],sleep=lambda n:clock.__setitem__(0,clock[0]+n))
            with self.assertRaises(TimeoutError):guard.check()
        self.assertGreaterEqual(len(calls),2)

    def test_identity_error_fails_immediately_without_wait(self):
        calls=[];state=SimpleNamespace(receipts={})
        def raw():raise ValueError('source witness identity differs')
        guard=wait.WitnessGuard(raw,state,sleep=lambda x:calls.append(x))
        with self.assertRaisesRegex(ValueError,'identity'):guard.check()
        self.assertEqual(calls,[])

    def test_real_signed_expired_then_refreshed_pair_is_reverified(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);key=root/'key'
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
            public=Path(str(key)+'.pub').read_bytes();key_sha=hashlib.sha256(public).hexdigest()
            now=datetime.datetime.now(datetime.timezone.utc); state=SimpleNamespace(receipts={})
            plan={'run_id':'run','manifest_sha256':'a'*64,'source_attempts_logical_sha256':'b'*64}
            source={'status':'source_quiescent_observation','plan_sha256':'c'*64,'run_id':'run',
                'manifest_sha256':'a'*64,'source_machine_sha256':'d'*64,'source_attempts_logical_sha256':'b'*64,
                'pid':586456,'pid_start_ticks':9222972,'threads':[{'pid':586456,'start_ticks':9222972,'flags':4,'fdsize':0},
                {'pid':588542,'start_ticks':9253469,'flags':4,'fdsize':0}],
                'lock_line':'8: FLOCK ADVISORY WRITE 586456 08:01:337064389 0 EOF'}
            fence={'status':'104_shard_fenced_zero_attempts','machine_sha256':original_fence.MACHINE_SHA,
                'old_identity_sha256':'e'*64,'plan_sha256':'c'*64,'pid':123,'pid_start_ticks':456,
                'lock_line':'8: FLOCK ADVISORY WRITE 123 08:01:123 0 EOF','ledger':{'ledger':'absent','attempts':0}}
            def signed(path,record,namespace,issued,expires):
                payload={**record,'issued_at_utc':issued.isoformat(),'expires_at_utc':expires.isoformat()}
                msg=path.with_suffix('.message');sig=Path(str(msg)+'.sig')
                if sig.exists():sig.unlink()
                msg.write_text(json.dumps(payload,sort_keys=True))
                subprocess.run(['ssh-keygen','-Y','sign','-f',str(key),'-n',namespace,str(msg)],check=True,capture_output=True)
                path.write_text(json.dumps({'message_b64':base64.b64encode(msg.read_bytes()).decode(),
                                            'signature_b64':base64.b64encode(sig.read_bytes()).decode()}))
            src=root/'src';fnc=root/'fence'
            signed(src,source,'tcl-shard-watch',now-datetime.timedelta(seconds=30),now-datetime.timedelta(seconds=1))
            signed(fnc,fence,'tcl-shard104-fence',now-datetime.timedelta(seconds=1),now+datetime.timedelta(seconds=25))
            src_check=wait.checked_verifier(original_policy.verify_watch,'source',state)
            fnc_check=wait.checked_verifier(original_fence.verify_fence,'fence',state)
            def raw():
                src_check(src,public,key_sha,'watcher','c'*64,plan,'d'*64)
                fnc_check(fnc,public,key_sha,'watcher','c'*64,'e'*64,123,456)
            def renew(_):
                current=datetime.datetime.now(datetime.timezone.utc)
                signed(src,source,'tcl-shard-watch',current-datetime.timedelta(seconds=1),current+datetime.timedelta(seconds=25))
            wait.WitnessGuard(raw,state,sleep=renew).check()
            self.assertEqual(set(state.receipts),{'source','fence'})
            altered=json.loads(src.read_text());altered['signature_b64']=base64.b64encode(b'invalid').decode();src.write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError,'signature'):
                wait.WitnessGuard(raw,state,sleep=lambda _:self.fail('signature failure must not wait')).check()

    def test_model_hooks_wait_before_each_forward_and_do_not_replay(self):
        class Handle:
            def __init__(self,module,hook):self.module,self.hook=module,hook
            def remove(self):self.module.hooks.remove(self.hook)
        class Model:
            def __init__(self):self.hooks=[];self.calls=0
            def register_forward_pre_hook(self,hook):self.hooks.append(hook);return Handle(self,hook)
            def __call__(self):
                for hook in self.hooks:hook(self,())
                self.calls+=1
        class Runtime:
            def __init__(self):self.text_encoder=Model();self.unet=Model()
        class Vae:
            def __init__(self):self.calls=0
            def decode(self):self.calls+=1
        class Scorer:
            def __init__(self):
                self.vit=Model();self.clip=SimpleNamespace(vision_model=Model(),text_model=Model())
            def score(self):self.vit();self.clip.vision_model();self.clip.text_model()
        class BaseLedger:
            def __init__(self,ledger,plan,watch):self.watch=watch
        policy=SimpleNamespace(GuardedLedger=BaseLedger,verify_signature=lambda *a,**k:None,verify_watch=lambda *a,**k:{'expires_at_utc':(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=10)).isoformat()})
        fence=SimpleNamespace(verify_fence=lambda *a,**k:{'expires_at_utc':(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=10)).isoformat()})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'images.sqlite';path.touch()
            ledger=SimpleNamespace(db=SimpleNamespace(execute=lambda sql:SimpleNamespace(fetchone=lambda:(0,'main',str(path)))),run_id='run',manifest_sha='a'*64)
            state=wait.install(policy,fence,Runtime,Vae,Scorer,expected_output=directory)
            expired=[False]; checks=[]
            def raw():
                checks.append('pair')
                if expired[0]: raise wait.FreshWitnessPending('fence expired')
                policy.verify_watch(path);fence.verify_fence(path)
            policy.GuardedLedger(ledger,{},raw)
            runtime=Runtime();vae=Vae();scorer=Scorer()
            runtime.text_encoder();runtime.unet()
            expired[0]=True
            def renew(_):
                self.assertEqual(runtime.unet.calls,1)
                expired[0]=False
            state.guard.sleep=renew
            runtime.unet();vae.decode();scorer.score()
            self.assertEqual((runtime.text_encoder.calls,runtime.unet.calls,vae.calls,scorer.vit.calls,scorer.clip.vision_model.calls,scorer.clip.text_model.calls),(1,2,1,1,1,1))
            self.assertEqual(scorer.vit.hooks,[])
            self.assertIsNotNone(state.guard)

    def test_signed_launcher_binds_existing_shard_and_resource_reviews(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);key=root/'key'
            subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(key)],check=True)
            public=Path(str(key)+'.pub');fingerprint=hashlib.sha256(public.read_bytes()).hexdigest()
            files=['resource127_launcher.py','resource127_gdm_xorg_patch.py','shard127_runner.py',
                   'shard104_policy.py','shard127_policy.py','shard127_watch_controller.py','shard127_watch_wait.py']
            for name in files:(root/name).write_bytes((DIR/name).read_bytes())
            for name in ('resource-review','resource-signature','shard-envelope'):(root/name).write_text(name)
            manifest=DIR/'manifest_candidate.json'
            sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
            report={'decision':'approved','task_id':'TCL-20261029-01','run_id':'tcl-20261029-01-v1',
                'manifest_sha256':wait_launcher.MANIFEST_SHA,'server':'school127','reviewer':'reviewer','reviewer_key_sha256':fingerprint,
                'watch_lifetime_seconds':30,'retry_window_seconds':90,'maximum_wait_seconds':120,
                'signature_cache_entries':4,'signature_cache_max_seconds':30,'scientific_replay':'prohibited',
                'wait_launcher_sha256':sha(DIR/'shard127_wait_launcher.py'),'wait_patch_sha256':sha(root/'shard127_watch_wait.py'),
                'resource_launcher_sha256':sha(root/'resource127_launcher.py'),'resource_overlay_sha256':sha(root/'resource127_gdm_xorg_patch.py'),
                'resource_review_sha256':sha(root/'resource-review'),'resource_signature_sha256':sha(root/'resource-signature'),
                'shard_review_envelope_sha256':sha(root/'shard-envelope'),'shard_runner_sha256':sha(root/'shard127_runner.py'),
                'shard_policy_sha256':sha(root/'shard104_policy.py'),'fence_policy_sha256':sha(root/'shard127_policy.py'),
                'watch_controller_sha256':sha(root/'shard127_watch_controller.py')}
            review=root/'review';review.write_text(json.dumps(report,sort_keys=True))
            subprocess.run(['ssh-keygen','-Y','sign','-f',str(key),'-n','tcl-wait-amendment',str(review)],check=True,capture_output=True)
            args=SimpleNamespace(wait_review=review,wait_signature=Path(str(review)+'.sig'),reviewer_key=public,
                resource_launcher=root/'resource127_launcher.py',patch=root/'shard127_watch_wait.py')
            forwarded=['--manifest',str(manifest),'--repository-root',str(ROOT),'--overlay',str(root/'resource127_gdm_xorg_patch.py'),
                       '--review',str(root/'resource-review'),'--signature',str(root/'resource-signature'),'--',
                       '--manifest',str(manifest),'--repository-root',str(ROOT),'--review-envelope',str(root/'shard-envelope')]
            with patch.object(wait_launcher,'REVIEW_KEY_SHA',fingerprint):
                self.assertEqual(wait_launcher.verify(args,forwarded)[0],ROOT)
                (root/'shard127_watch_controller.py').write_text('tampered')
                with self.assertRaisesRegex(ValueError,'reviewed frozen inputs'): wait_launcher.verify(args,forwarded)

    def test_interruption_resumes_same_reserved_unit_without_replaying_nfe(self):
        class Model:
            def __init__(self):self.hooks=[];self.calls=0
            def register_forward_pre_hook(self,hook):self.hooks.append(hook)
            def __call__(self):
                for hook in self.hooks:hook(self,())
                self.calls+=1
        class Runtime:
            def __init__(self):self.text_encoder=Model();self.unet=Model()
        class Vae:
            def decode(self):pass
        class Scorer:
            def score(self):pass
        expiry=lambda:{'expires_at_utc':(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=20)).isoformat()}
        policy=SimpleNamespace(GuardedLedger=ledger_fixture.policy.GuardedLedger,verify_signature=lambda *args:None,
            verify_watch=lambda *args,**kwargs:expiry())
        fence=SimpleNamespace(verify_fence=lambda *args,**kwargs:expiry())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ledger,plan=ledger_fixture.ShardPolicyTests().fixture(root)
            ids={state:sorted(values) for state,values in ledger.ids.items()};bindings=ledger.bindings
            ledger.close();(root/'shard.sqlite').rename(root/'images.sqlite')
            ledger=ledger_fixture.Ledger(root/'images.sqlite','run',ledger_fixture.SHA,ids,[1,2]);ledger.bindings=bindings
            witness=root/'witness';witness.touch()
            state=wait.install(policy,fence,Runtime,Vae,Scorer,expected_output=root)
            stale=[False];runtime=Runtime(); key=plan['allowed_keys'][0]
            def raw():
                if stale[0]:raise wait.FreshWitnessPending('fence expired')
                policy.verify_watch(witness);fence.verify_fence(witness)
            guarded=policy.GuardedLedger(ledger,plan,raw)
            self.assertTrue(guarded.start(*key,ledger_fixture.SHA,ledger_fixture.SHA))
            guarded.checkpoint_resource(*key,{'unet_branch_nfe':1});runtime.unet()
            guarded.checkpoint_resource(*key,{'unet_branch_nfe':2})
            stale[0]=True
            def renew(_):
                self.assertEqual(runtime.unet.calls,1)
                stale[0]=False
            state.guard.sleep=renew
            runtime.unet()
            self.assertEqual(runtime.unet.calls,2)
            row=ledger.db.execute("SELECT status,resource FROM attempts").fetchone()
            self.assertEqual(row[0],'started');self.assertEqual(json.loads(row[1])['unet_branch_nfe'],2)
            self.assertEqual(ledger.attempt_count('source'),1)
            ledger.close()

if __name__=='__main__':unittest.main()
