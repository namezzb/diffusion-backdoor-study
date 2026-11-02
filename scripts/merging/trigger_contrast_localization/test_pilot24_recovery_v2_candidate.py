"""Two-generation recovery: strictly synthetic CPU tests, no CUDA."""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
import pilot24_recovery_guard_candidate as g
from pilot24_coordinator import stage_contract
from pilot24_worker_ledger import canonical
import test_pilot24_recovery_guard_candidate as fixtures


class TwoGenerationGuardTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.GuardTest('test_held_lock_and_inherited_budget'); self.f.setUp()
        self.addCleanup(self.f.doCleanups); self.addCleanup(self.f.temp.cleanup)
        f=self.f
        old_bundle={'run_id':g.RUN,'repository_root':'/old','review_file':'/old-review',
                    'code_sha256':{},'execution_root':str(f.root.parent),'inputs':{'scientific':'fixed'}}
        manifest=fixtures.write(f.bundle,old_bundle)
        old_config=json.loads(f.config.read_text()); old_config['manifest_sha256']=manifest
        old_a=json.loads((f.root/'assignments/S0-00-w0.json').read_text());old_a['manifest_sha256']=manifest
        old_a.update(stage='S0',worker_id='w0',server='school104',gpu_uuid='GPU-01234567-89ab-cdef-0123-456789abcdef',retry_tokens=1,gate_sha256=stage_contract(manifest,'S0'))
        old_config['assignments']=[old_a]
        configsha=fixtures.write(f.config,old_config)
        asha=fixtures.write(f.root/'assignments/S0-00-w0.json',old_a)
        with sqlite3.connect(f.dbpath) as db: db.execute('UPDATE metadata SET assignment=? WHERE id=1',(canonical(old_a),))
        t0={'run_id':g.RUN,'manifest_sha256':manifest,'t0_utc':g.T0}
        t0sha=fixtures.write(f.root/'t0.json',t0)
        exit0=fixtures.write(f.root/'sessions/w0/exit.json',{'run_id':g.RUN,'manifest_sha256':manifest,'worker_id':'w0','t0_sha256':t0sha,'owned_process_group':99999999})
        def terminal(ms):
            return {'run_id':g.RUN,'manifest_sha256':ms,'reason':'worker_session_blocked','charged_attempts':0,'imported':363,'unique_complete':363,'required_unique_max':6144,'worker_exit_verified':True,'final_ledger_audit':{'audited':['S0-00-w0'],'counts_are_final':True,'errors':[]},'t0':{**t0,'file_sha256':t0sha}}
        tzero=terminal(manifest); termsha=fixtures.write(f.root/'terminal.json',tzero)
        state0={'stage':'S0','terminal':tzero,'t0':{**t0,'file_sha256':t0sha},'receipts':{},'released':{'S0':{'assignments':[{'assignment_id':'S0-00-w0','path':str(f.root/'assignments/S0-00-w0.json'),'sha256':asha}]}}}
        statesha=fixtures.write(f.root/'state.json',state0)
        rec={'original_bundle':str(f.bundle),'original_config':str(f.config),'original_config_sha256':configsha,'original_state_sha256':statesha,'original_coordinator_root':str(f.root),'original_t0_sha256':t0sha,'original_terminal_sha256':termsha}
        r1=f.root.parent/'recovery-v1'; coord=r1/'coordinator';coord.mkdir(parents=True);(coord/'.coordinator.lock').touch()
        work=r1/'workers/S0-00-w0';work.mkdir(parents=True);(work/'.worker.lock').touch()
        b1={**old_bundle,'review_file':str(r1/'frozen/review.json'),'repository_root':'/revision'}
        r1sha=fixtures.write(r1/'frozen/bundle.json',b1)
        a1={**old_a,'manifest_sha256':r1sha,'gate_sha256':stage_contract(r1sha,'S0'),'output_root':str(work)}
        c1={**old_config,'manifest_sha256':r1sha,'coordinator_root':str(coord),'assignments':[a1],'recovery':rec}
        c1sha=fixtures.write(r1/'frozen/coordinator_config.json',c1)
        review={'run_id':g.RUN,'status':'passed','manifest_sha256':r1sha,'coordinator_config_sha256':c1sha,'reviewer':'reviewer','implementer':'implementer','original_manifest_sha256':manifest,'original_t0_sha256':t0sha,'original_terminal_sha256':termsha}
        self.review_sha=fixtures.write(r1/'frozen/review.json',review)
        with sqlite3.connect(work/'worker.sqlite') as db:
            db.executescript('CREATE TABLE metadata(id INTEGER, assignment TEXT); CREATE TABLE attempts(key TEXT); CREATE TABLE units(key TEXT, input_sha TEXT, mask_sha TEXT, status TEXT, image_sha TEXT, scores TEXT);')
            db.execute('INSERT INTO metadata VALUES(1,?)',(canonical(a1),))
            db.executemany('INSERT INTO units VALUES(?,?,?,?,?,?)',[(canonical(u['key']),u['input_sha'],u['mask_sha'],'unstarted',None,None) for u in a1['units']])
        asha1=fixtures.write(coord/'assignments/S0-00-w0.json',a1)
        exit1=fixtures.write(coord/'sessions/w0/exit.json',{'run_id':g.RUN,'manifest_sha256':r1sha,'worker_id':'w0','t0_sha256':t0sha,'owned_process_group':99999997})
        fixtures.write(coord/'sessions/w0/supervisor.json',{'pid':99999996})
        t1=terminal(r1sha); t1sha=fixtures.write(coord/'terminal.json',t1)
        s1sha=fixtures.write(coord/'state.json',{'stage':'S0','terminal':t1,'t0':{**t0,'file_sha256':t0sha},'receipts':{},'released':{'S0':{'assignments':[{'assignment_id':'S0-00-w0','path':str(coord/'assignments/S0-00-w0.json'),'sha256':asha1}]}}})
        patches=patch.multiple(g,MANIFEST=manifest,T0_SHA=t0sha,TERMINAL_SHA=termsha,CONFIG_SHA=configsha,STATE_SHA=statesha,ORIGINAL_LEDGER_SHA=hashlib.sha256(f.dbpath.read_bytes()).hexdigest(),R1_ROOT=str(r1),R1_MANIFEST=r1sha,R1_CONFIG_SHA=c1sha,R1_STATE_SHA=s1sha,R1_TERMINAL_SHA=t1sha,R1_EXIT_SHA=exit1,R1_REVIEW_SHA=self.review_sha,R1_LEDGER_SHA=hashlib.sha256((work/'worker.sqlite').read_bytes()).hexdigest())
        patches.start();self.addCleanup(patches.stop)
        def read(path,sha):
            raw=Path(path).read_bytes()
            expected=exit0 if str(path).endswith('/coordinator/sessions/w0/exit.json') and str(path).startswith(str(f.root)+'/') else sha
            if hashlib.sha256(raw).hexdigest()!=expected: raise ValueError('fixture hash mismatch')
            return json.loads(raw)
        pp=patch.object(g,'_read',side_effect=read);pp.start();self.addCleanup(pp.stop)
        self.r1,self.config,self.bundle,self.review,self.rec,self.work=r1,c1,b1,review,rec,work

    def test_locks_both_generations_and_preserves_budget(self):
        with g.hold_both_predecessors(previous_review_sha256=self.review_sha) as result:
            self.assertEqual((len(result['lock_fds']),result['max_new_attempts']),(4,5909))
            g.validate_inherited_locks(g.ORIGINAL_ROOT,result['lock_fds'],second=True)
            forged=os.open(self.work/'.worker.lock',os.O_RDWR)
            try:
                with self.assertRaisesRegex(ValueError,'does not own'):
                    g.validate_inherited_locks(g.ORIGINAL_ROOT,(*result['lock_fds'][:3],forged),second=True)
            finally:os.close(forged)

    def test_second_generation_attempt_refuses_recovery(self):
        with sqlite3.connect(self.work/'worker.sqlite') as db: db.execute("INSERT INTO attempts VALUES('attempt')")
        with self.assertRaisesRegex(ValueError,'charged work'):
            with g.hold_both_predecessors(previous_review_sha256=self.review_sha): pass

    def test_second_ledger_byte_change_rejected_even_when_counts_remain_zero(self):
        with sqlite3.connect(self.work/'worker.sqlite') as db: db.execute('CREATE TABLE unexpected_evidence(x)')
        with self.assertRaisesRegex(ValueError,'ledger hash differs'):
            with g.hold_both_predecessors(previous_review_sha256=self.review_sha): pass

    def test_all_four_locks_survive_coordinator_process_exit(self):
        with g.hold_both_predecessors(previous_review_sha256=self.review_sha) as result:
            child=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.read()'],stdin=subprocess.PIPE,
                                   pass_fds=result['lock_fds'])
        paths=[self.f.root/'.coordinator.lock',self.f.dbpath.parent/'.worker.lock',
               self.r1/'coordinator/.coordinator.lock',self.work/'.worker.lock']
        try:
            for path in paths:
                fd=os.open(path,os.O_RDWR)
                try:
                    with self.assertRaises(BlockingIOError):fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                finally:os.close(fd)
        finally:
            child.stdin.close();child.wait(timeout=5)

    def test_second_generation_live_process_refuses_recovery(self):
        original=g._absent
        def check(pid,*,group=False):
            if pid==99999997: raise ValueError('old process or process group still exists')
            return original(pid,group=group)
        with patch.object(g,'_absent',side_effect=check):
            with self.assertRaisesRegex(ValueError,'still exists'):
                with g.hold_both_predecessors(previous_review_sha256=self.review_sha):pass

    def test_missing_or_forged_previous_review_hash_is_rejected(self):
        for value in ('', 'f'*64):
            with self.assertRaises(ValueError):
                with g.hold_both_predecessors(previous_review_sha256=value):pass
        path=self.r1/'frozen/review.json'
        altered={**json.loads(path.read_text()),'reviewer':'forged'}
        forged_sha=fixtures.write(path,altered)
        with self.assertRaisesRegex(ValueError,'independently observed'):
            with g.hold_both_predecessors(previous_review_sha256=forged_sha):pass

    def test_second_amendment_only_rebinds_uuid(self):
        newsha='f'*64;newroot=Path(g.ORIGINAL_ROOT).parent/'recovery-v2'
        b={**self.bundle,'review_file':str(newroot/'frozen/review.json')}
        previous={'root':g.R1_ROOT,'manifest_sha256':g.R1_MANIFEST,'config_sha256':g.R1_CONFIG_SHA,'state_sha256':g.R1_STATE_SHA,'terminal_sha256':g.R1_TERMINAL_SHA,'exit_sha256':g.R1_EXIT_SHA,'review_sha256':self.review_sha}
        c=copy.deepcopy(self.config);c['manifest_sha256']=newsha;c['coordinator_root']=str(newroot/'coordinator');c['recovery']['previous']=previous
        a=c['assignments'][0];a.update(manifest_sha256=newsha,gate_sha256=stage_contract(newsha,'S0'),output_root=str(newroot/'workers/S0-00-w0'),gpu_uuid='GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
        review={**self.review,'previous_manifest_sha256':g.R1_MANIFEST,'previous_terminal_sha256':g.R1_TERMINAL_SHA,'previous_state_sha256':g.R1_STATE_SHA,'previous_review_sha256':self.review_sha}
        g.validate_amendment(b,c,review,newsha)
        bad=copy.deepcopy(c);bad['assignments'][0]['retry_tokens']+=1
        with self.assertRaisesRegex(ValueError,'retry allocation'):g.validate_amendment(b,bad,review,newsha)
        bad=copy.deepcopy(c);bad['assignments'][0]['server']='school127'
        with self.assertRaisesRegex(ValueError,'retry allocation'):g.validate_amendment(b,bad,review,newsha)
        bad=copy.deepcopy(c);bad['recovery']['previous']['state_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'both exact predecessor'):g.validate_amendment(b,bad,review,newsha)
        with self.assertRaisesRegex(ValueError,'incomplete'):
            with g.hold_both_predecessors(previous_review_sha256=self.review_sha) as result:g.validate_inherited_locks(g.ORIGINAL_ROOT,result['lock_fds'][:2],second=True)

    def test_preparation_creates_only_pending_review_in_new_namespace(self):
        from pilot24_prepare_recovery_v2_candidate import prepare
        repo=Path(__file__).resolve().parents[3]
        uuid='GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        result=prepare(repository_root=repo,gpu_uuid=uuid,previous_review_sha256=self.review_sha)
        self.assertEqual(result['status'],'pending_independent_review')
        self.assertFalse(result['gpu_started'])
        review=json.loads((Path(result['bundle']).parent/'review.json').read_text())
        self.assertEqual(review['status'],'pending')
        c=json.loads(Path(result['config']).read_text());b=json.loads(Path(result['bundle']).read_text())
        g.validate_amendment(b,c,review,result['bundle_sha256'])
        self.assertEqual(c['assignments'][0]['gpu_uuid'],uuid)
        self.assertEqual(c['assignments'][0]['units'],self.config['assignments'][0]['units'])
        with self.assertRaisesRegex(ValueError,'already exists'):
            prepare(repository_root=repo,gpu_uuid=uuid,previous_review_sha256=self.review_sha)

if __name__=='__main__': unittest.main()
