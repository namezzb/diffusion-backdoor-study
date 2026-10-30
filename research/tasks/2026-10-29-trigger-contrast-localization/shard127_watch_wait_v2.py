"""In-process, bounded wait for fresh signed 103/104 witnesses.

No witness lifetime is extended; no completed model forward is replayed.
Install only through the separately signed launcher before the shard starts.
"""
from __future__ import annotations
import base64
from collections import OrderedDict
import datetime
import json
from pathlib import Path
import stat
import threading
import time
from types import SimpleNamespace

RETRY_SECONDS = 90  # Two existing 15-second signature checks bound each final attempt to 120 seconds.
POLL_SECONDS = .5
UTC = datetime.timezone.utc
SIGNATURE_CACHE_ENTRIES = 4
SIGNATURE_CACHE_SECONDS = 30


class FreshWitnessPending(Exception):
    pass


class SignatureCache:
    """Cache successful crypto checks only; callers still validate every field."""
    def __init__(self,original,monotonic=time.monotonic):
        self.original=original; self.monotonic=monotonic; self.entries=OrderedDict()
        self.lock=threading.Lock()

    def invalidate(self,namespace):
        with self.lock:
            for key in list(self.entries):
                if key[-1]==namespace: del self.entries[key]

    def __call__(self,message,signature,public_key,expected_key_sha,principal,namespace):
        if namespace not in ('tcl-shard-watch','tcl-shard104-fence'):
            return self.original(message,signature,public_key,expected_key_sha,principal,namespace)
        key=(message,signature,public_key,expected_key_sha,principal,namespace)
        with self.lock:
            now=self.monotonic()
            for old,created in list(self.entries.items()):
                if now-created>=SIGNATURE_CACHE_SECONDS or now<created: del self.entries[old]
            if key in self.entries:
                self.entries.move_to_end(key)
                return None
            result=self.original(message,signature,public_key,expected_key_sha,principal,namespace)
            self.entries[key]=self.monotonic()
            while len(self.entries)>SIGNATURE_CACHE_ENTRIES: self.entries.popitem(last=False)
            return result


def _instant(value):
    result=datetime.datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset()!=datetime.timedelta(0): raise ValueError('witness time is not UTC')
    return result


def checked_verifier(original,which,state,signature_cache=None):
    """Retry only absence or an already signed, identity-checked expiry."""
    def verify(path,*args,**kwargs):
        p=Path(path)
        namespace={'source':'tcl-shard-watch','fence':'tcl-shard104-fence'}[which]
        def fingerprint():
            if p.is_symlink(): raise ValueError('witness path is a symlink')
            info=p.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size>65536: raise ValueError('invalid witness file')
            return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
        try:
            before_stat=fingerprint(); before=p.read_bytes()
        except FileNotFoundError:
            before_stat=None; before=None
        previous=getattr(state,'file_fingerprints',{}).get(which)
        if signature_cache is not None and previous is not None and previous!=before_stat:
            signature_cache.invalidate(namespace)
        try:
            result=original(path,*args,**kwargs)
        except FileNotFoundError as exc:
            if not p.exists() and not p.is_symlink():
                raise FreshWitnessPending(which+' witness temporarily absent') from exc
            raise
        except ValueError as exc:
            msg=str(exc)
            unavailable={'source':'live source witness unavailable','fence':'104 fence witness unavailable'}[which]
            expired={'source':'source witness expired or invalid','fence':'104 fence witness expired or invalid'}[which]
            if msg==unavailable and not p.exists() and not p.is_symlink():
                raise FreshWitnessPending(which+' witness temporarily absent') from exc
            if msg==expired and before is not None and (not p.is_file() or p.is_symlink() or p.read_bytes()!=before):
                if signature_cache is not None: signature_cache.invalidate(namespace)
                raise FreshWitnessPending(which+' witness changed during validation') from exc
            if msg!=expired or before is None:
                raise
            # The original verifier already checked signature and identity on
            # these same immutable bytes. Only a well-formed expiry is waitable.
            data=json.loads(base64.b64decode(json.loads(before)['message_b64'],validate=True))
            issued=_instant(data['issued_at_utc']); expires=_instant(data['expires_at_utc'])
            now=datetime.datetime.now(UTC)
            if issued<=now and issued<expires<=now and 0<(expires-issued).total_seconds()<=30:
                raise FreshWitnessPending(which+' witness expired') from exc
            raise
        try: after_stat=fingerprint()
        except FileNotFoundError as exc:
            if signature_cache is not None: signature_cache.invalidate(namespace)
            raise FreshWitnessPending(which+' witness temporarily absent') from exc
        if before_stat!=after_stat:
            if signature_cache is not None: signature_cache.invalidate(namespace)
            raise FreshWitnessPending(which+' witness changed during validation')
        if not hasattr(state,'file_fingerprints'): state.file_fingerprints={}
        state.file_fingerprints[which]=after_stat
        state.receipts[which]=_instant(result['expires_at_utc'])
        return result
    return verify


class WitnessGuard:
    def __init__(self,raw_watch,state,emit=None,monotonic=time.monotonic,sleep=time.sleep):
        self.raw_watch=raw_watch; self.state=state; self.emit=emit or (lambda *args:None)
        self.monotonic=monotonic; self.sleep=sleep

    def check(self):
        started=self.monotonic(); waiting=False
        while True:
            self.state.receipts={}
            try:
                self.raw_watch()  # Each attempt verifies both original signatures and identities.
                if set(self.state.receipts)!={'source','fence'}:
                    raise ValueError('both source and fence witnesses are required')
                if datetime.datetime.now(UTC)>=min(self.state.receipts.values()):
                    raise FreshWitnessPending('one witness expired during pair verification')
                if waiting:
                    self.emit('watch_wait_resumed',{'wait_seconds':round(self.monotonic()-started,3)})
                    if datetime.datetime.now(UTC)>=min(self.state.receipts.values()):
                        raise FreshWitnessPending('one witness expired while recording resumption')
                return
            except FreshWitnessPending as exc:
                elapsed=self.monotonic()-started
                if not waiting:
                    self.emit('watch_wait_started',{'reason':str(exc),'retry_window_seconds':RETRY_SECONDS,'max_bound_seconds':120})
                    waiting=True
                if elapsed>=RETRY_SECONDS:
                    self.emit('watch_wait_timeout',{'reason':str(exc),'wait_seconds':round(elapsed,3)})
                    raise TimeoutError('fresh source witnesses unavailable within bounded wait') from exc
                self.sleep(min(POLL_SECONDS,RETRY_SECONDS-elapsed))


class InitialPairGuard:
    """Bound the two startup checks even before a ledger exists."""
    def __init__(self,source,fence,state,monotonic=time.monotonic,sleep=time.sleep):
        self.source=source; self.fence=fence; self.state=state
        self.monotonic=monotonic; self.sleep=sleep
        self.started=None; self.source_args=None

    def _retry(self,check):
        while True:
            elapsed=self.monotonic()-self.started
            if elapsed>=RETRY_SECONDS:
                raise TimeoutError('fresh startup source witnesses unavailable within bounded wait')
            try:
                return check()
            except FreshWitnessPending as exc:
                elapsed=self.monotonic()-self.started
                if elapsed>=RETRY_SECONDS:
                    raise TimeoutError('fresh startup source witnesses unavailable within bounded wait') from exc
                self.sleep(min(POLL_SECONDS,RETRY_SECONDS-elapsed))

    def verify_source(self,*args,**kwargs):
        if getattr(self.state,'guard',None) is not None:
            return self.source(*args,**kwargs)
        self.started=self.monotonic(); self.source_args=(args,kwargs)
        return self._retry(lambda:self.source(*args,**kwargs))

    def verify_fence(self,*args,**kwargs):
        if getattr(self.state,'guard',None) is not None:
            return self.fence(*args,**kwargs)
        if self.started is None or self.source_args is None:
            raise ValueError('startup fence verification requires source verification first')
        def pair():
            self.state.receipts={}
            source_args,source_kwargs=self.source_args
            self.source(*source_args,**source_kwargs)
            result=self.fence(*args,**kwargs)
            if set(self.state.receipts)!={'source','fence'}:
                raise ValueError('both startup witnesses are required')
            if datetime.datetime.now(UTC)>=min(self.state.receipts.values()):
                raise FreshWitnessPending('startup witness expired during pair verification')
            return result
        return self._retry(pair)


def install(policy,fence_policy,runtime_class,vae_class,scorer_class,
            expected_output='/data1/zhangzibo/arxiv-tssa/results/tcl-20261029-01-v1-shard127-20261030'):
    """Wrap guards and model entrypoints while preserving original counters."""
    state=threading.local(); state.receipts={}; state.guard=None
    signature_cache=SignatureCache(policy.verify_signature)
    policy.verify_signature=signature_cache
    source=checked_verifier(policy.verify_watch,'source',state,signature_cache)
    fence=checked_verifier(fence_policy.verify_fence,'fence',state,signature_cache)
    initial=InitialPairGuard(source,fence,state)
    state.initial_guard=initial
    policy.verify_watch=initial.verify_source
    fence_policy.verify_fence=initial.verify_fence
    base_ledger=policy.GuardedLedger

    class WaitingLedger(base_ledger):
        def __init__(self,ledger,plan,watch):
            from run_store import append_event
            db_path=Path(ledger.db.execute('PRAGMA database_list').fetchone()[2]).resolve(strict=True)
            output=db_path.parent
            expected=Path(expected_output).resolve(strict=True)
            if output!=expected or db_path.name!='images.sqlite':
                raise ValueError('watch wait ledger does not belong to the reviewed shard')
            identity=SimpleNamespace(run_id=ledger.run_id,manifest_sha=ledger.manifest_sha)
            def emit(status,detail): append_event(output,identity,'shard127_watch_wait',status,detail)
            guard=WitnessGuard(watch,state,emit)
            super().__init__(ledger,plan,guard.check)
            state.guard=guard

    policy.GuardedLedger=WaitingLedger
    def require_guard():
        guard=getattr(state,'guard',None)
        if guard is None: raise ValueError('model forward requires the active guarded shard ledger')
        guard.check()

    initial=runtime_class.__init__
    def guarded_init(self,*args,**kwargs):
        initial(self,*args,**kwargs)
        def preforward(_module,_inputs): require_guard()
        self.text_encoder.register_forward_pre_hook(preforward)
        self.unet.register_forward_pre_hook(preforward)
    runtime_class.__init__=guarded_init

    decode=vae_class.decode
    def guarded_decode(self,*args,**kwargs):
        require_guard()
        return decode(self,*args,**kwargs)
    vae_class.decode=guarded_decode

    score=scorer_class.score
    def guarded_score(self,*args,**kwargs):
        def preforward(_module,_inputs): require_guard()
        modules=(self.vit,self.clip.vision_model,self.clip.text_model)
        handles=[]
        try:
            for module in modules: handles.append(module.register_forward_pre_hook(preforward))
            return score(self,*args,**kwargs)
        finally:
            for handle in handles: handle.remove()
    scorer_class.score=guarded_score
    return state
