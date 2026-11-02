"""CPU-only process-chain simulation: patched assets, no CUDA or real evidence."""
import copy
from datetime import datetime, timezone
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

import pilot24_recovery_guard_candidate as guard
from pilot24_coordinator import stage_contract
from pilot24_inputs import frozen_units, RUN
from pilot24_prepare_recovery_candidate import prepare
from pilot24_worker_ledger import canonical
import test_pilot24_recovery_guard_candidate as recovery_tests
from test_pilot24_recovery_guard_candidate import write

ROOT = Path(__file__).resolve().parents[3]
TASK = ROOT / 'research/tasks/2026-10-29-trigger-contrast-localization'
PREFIX = 'scripts/merging/trigger_contrast_localization/'


class RecoveryChainTest(unittest.TestCase):
    def test_reviewed_recovery_reaches_cpu_worker_without_cuda(self):
        f = recovery_tests.GuardTest('test_held_lock_and_inherited_budget')
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.addCleanup(f.tearDown)
        self.addCleanup(f.temp.cleanup)
        now = datetime.now(timezone.utc).isoformat()
        names = ('pilot24_run.py','pilot24_coordinator.py','pilot24_watchdog.py','pilot24_deadline.py',
                 'pilot24_runtime.py','pilot24_inputs.py','pilot24_statistics.py','pilot24_worker_compute.py',
                 'pilot24_worker_ledger.py','pilot24_provenance.py')
        code = {PREFIX+n: hashlib.sha256((ROOT/PREFIX/n).read_bytes()).hexdigest() for n in names}
        bundle = {'schema_version':1,'run_id':RUN,'status':'frozen','repository_root':str(ROOT),
                  'models_root':str(f.root.parent),'review_file':str(f.root.parent/'old-review.json'),
                  'execution_root':str(f.root.parent),'inputs':{},'code_sha256':code,
                  'scorer_device':'cpu','cpu_threads_per_worker':4}
        manifest = write(f.bundle, bundle)
        stages = frozen_units(TASK/'pilot24_plan_candidate.json',TASK/'pilot24_context_ids.json',
                              TASK/'manifest_candidate.json',TASK/'prompts_tokenized_candidate.jsonl')
        allunits = [{'key':list(k),'input_sha':'a'*64,'mask_sha':'b'*64} for keys in stages.values() for k in keys]
        imports = [dict(u,model_bundle_sha256='c'*64,scorer_sha256='d'*64,image_path='/fixture/image.png',
                        image_sha='e'*64,scores={'vit_class':0,'clip_score':1.0}) for u in allunits[:363]]
        assigned=[]
        for stage, keys in stages.items():
            units=[u for u in allunits if tuple(u['key']) in set(keys) and u not in allunits[:363]]
            aid=stage+'-00-w0'
            assigned.append({'run_id':RUN,'manifest_sha256':manifest,'assignment_id':aid,'stage':stage,
                'worker_id':'w0','server':'104','gpu_uuid':'GPU-01234567-89ab-cdef-0123-456789abcdef',
                'output_root':str(f.root.parent/'workers'/aid),'retry_tokens':32,
                'units':units,'gate_sha256':stage_contract(manifest,stage)})
        config={'run_id':RUN,'manifest_sha256':manifest,'coordinator_root':str(f.root),
                'model_bundle_sha256':'c'*64,'scorer_sha256':'d'*64,
                'stages':{s:[list(k) for k in v] for s,v in stages.items()},
                'units':allunits,'imports':imports,'labels':{'source':{},'merge':{}},'assignments':assigned}
        confsha=write(f.config,config)
        assignment={**assigned[0], 'gate_sha256':'f'*64}
        assignpath=f.root/'assignments/S0-00-w0.json'
        assignsha=write(assignpath,assignment)
        with sqlite3.connect(f.dbpath) as db:
            db.execute('DELETE FROM metadata'); db.execute('DELETE FROM units')
            db.execute('INSERT INTO metadata VALUES(1,?)',(canonical(assignment),))
            db.executemany('INSERT INTO units VALUES(?,?,?,?,?,?)',[(canonical(u['key']),u['input_sha'],u['mask_sha'],'unstarted',None,None) for u in assignment['units']])
        t0={'run_id':RUN,'manifest_sha256':manifest,'t0_utc':now}
        t0sha=write(f.root/'t0.json',t0)
        exitsha=write(f.root/'sessions/w0/exit.json',{'run_id':RUN,'manifest_sha256':manifest,'worker_id':'w0',
             't0_sha256':t0sha,'owned_process_group':99999999})
        terminal={'run_id':RUN,'manifest_sha256':manifest,'reason':'worker_session_blocked','charged_attempts':0,
                  'imported':363,'unique_complete':363,'required_unique_max':6144,'worker_exit_verified':True,
                  'final_ledger_audit':{'audited':['S0-00-w0'],'counts_are_final':True,'errors':[]}}
        termsha=write(f.root/'terminal.json',terminal)
        statesha=write(f.root/'state.json',{'stage':'S0','terminal':terminal,'t0':{**t0,'file_sha256':t0sha},
                 'receipts':{},'released':{'S0':{'assignments':[{'assignment_id':'S0-00-w0','path':str(assignpath),'sha256':assignsha}]}}})
        f.exitsha=exitsha
        def fixture_read(path, sha):
            raw=Path(path).read_bytes()
            expected=exitsha if str(path)==str(f.root/'sessions/w0/exit.json') else sha
            if hashlib.sha256(raw).hexdigest()!=expected: raise ValueError('fixture hash mismatch')
            return json.loads(raw)
        with patch.multiple(guard,MANIFEST=manifest,T0_SHA=t0sha,TERMINAL_SHA=termsha,T0=now,
                            CONFIG_SHA=confsha,STATE_SHA=statesha,ORIGINAL_LEDGER_SHA=hashlib.sha256(f.dbpath.read_bytes()).hexdigest()), \
             patch.object(guard,'_read',side_effect=fixture_read), \
             patch('pilot24_prepare_recovery_candidate.MANIFEST',manifest), \
             patch('pilot24_prepare_recovery_candidate.T0_SHA',t0sha), \
             patch('pilot24_prepare_recovery_candidate.TERMINAL_SHA',termsha):
            result=prepare(original_bundle=f.bundle,original_config=f.config,original_state_sha=statesha,repository_root=ROOT)
        self.assertEqual(result['status'],'pending_independent_review')
        frozen=Path(result['bundle']).parent
        review=json.loads((frozen/'review.json').read_text()); review.update(status='passed',reviewer='independent-test')
        (frozen/'review.json').write_text(json.dumps(review))
        site=f.root.parent/'site'; site.mkdir()
        (site/'sitecustomize.py').write_text('''import os,json,types,hashlib\nimport pilot24_recovery_guard_candidate as g\ng.MANIFEST=os.environ["FIX_MANIFEST"];g.T0_SHA=os.environ["FIX_T0_SHA"];g.TERMINAL_SHA=os.environ["FIX_TERMINAL"];g.T0=os.environ["FIX_T0"]\ng.ORIGINAL_ROOT=os.environ["FIX_ROOT"];g.ORIGINAL_BUNDLE=os.environ["FIX_BUNDLE"];g.ORIGINAL_CONFIG=os.environ["FIX_CONFIG"];g.CONFIG_SHA=os.environ["FIX_CONFIG_SHA"];g.STATE_SHA=os.environ["FIX_STATE_SHA"]\nfor key in ("ROOT","MANIFEST","CONFIG_SHA","STATE_SHA","TERMINAL_SHA","EXIT_SHA","REVIEW_SHA"):\n value=os.environ.get("FIX_R1_"+key)\n if value is not None:setattr(g,"R1_"+key,value)\norig=g._read\ndef rr(p,s): return orig(p,os.environ["FIX_EXIT"] if str(p)==os.environ["FIX_ROOT"]+"/sessions/w0/exit.json" else s)\ng._read=rr\nimport pilot24_coordinator as c\nc.verify_scored_png=lambda *a: None\nimport pilot24_runtime as r\ndef prep(bundle,assignment,gate):\n b=json.load(open(bundle)); a=json.load(open(assignment)); gg=json.load(open(gate)); raw=open(assignment,"rb").read()\n return types.SimpleNamespace(bundle=b,assignment=a,manifest_sha256=hashlib.sha256(open(bundle,"rb").read()).hexdigest(),assignment_sha256=hashlib.sha256(raw).hexdigest(),model_bundle_sha256="c"*64,scorer_sha256="d"*64,bindings=types.SimpleNamespace(selection_sha="e"*64),gate=gg,assets=None)\nr.prepare_worker=prep\ndef stop_cpu(prepared): raise RuntimeError("intentional_cpu_fixture_stop")\nr.prepare_assets=stop_cpu\n''')
        site_file=site/'sitecustomize.py'
        site_file.write_text(site_file.read_text().replace('orig=g._read',
            'g.ORIGINAL_LEDGER_SHA=os.environ["FIX_ORIGINAL_LEDGER"];g.R1_LEDGER_SHA=os.environ.get("FIX_R1_LEDGER",g.R1_LEDGER_SHA)\norig=g._read'))
        env=os.environ.copy(); env.update(PYTHONPATH=str(site)+os.pathsep+str(Path(__file__).resolve().parent),
            FIX_MANIFEST=manifest,FIX_T0_SHA=t0sha,FIX_TERMINAL=termsha,FIX_T0=now,FIX_EXIT=exitsha,
            FIX_ROOT=str(f.root),FIX_BUNDLE=str(f.bundle),FIX_CONFIG=str(f.config),FIX_CONFIG_SHA=confsha,FIX_STATE_SHA=statesha,
            FIX_ORIGINAL_LEDGER=hashlib.sha256(f.dbpath.read_bytes()).hexdigest())
        command=[sys.executable,str(ROOT/PREFIX/'pilot24_run.py'),'serve','--bundle',result['bundle'],
                 '--config',result['config'],'--root',str(frozen.parent/'coordinator'),
                 '--launch-map',str(frozen/'launch_map.template.json'),'--server','104','--poll-seconds','.05']
        proc=subprocess.run(command,env=env,text=True,capture_output=True,timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr)
        terminal_new=json.loads((frozen.parent/'coordinator/terminal.json').read_text())
        self.assertEqual((terminal_new['imported'],terminal_new['charged_attempts']),(363,0))
        session=json.loads((frozen.parent/'coordinator/jobs/sessions/w0/session.json').read_text())
        self.assertIn('intentional_cpu_fixture_stop',session.get('error',''))
        self.assertEqual(hashlib.sha256((f.root/'terminal.json').read_bytes()).hexdigest(),termsha)
        self.assertEqual(hashlib.sha256((f.root/'t0.json').read_bytes()).hexdigest(),t0sha)
        # Freeze the first amendment's real subprocess terminal and continue
        # into a second isolated amendment with all four predecessor locks.
        first_root=frozen.parent
        def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        first_state=digest(first_root/'coordinator/state.json')
        first_terminal=digest(first_root/'coordinator/terminal.json')
        first_exit=digest(first_root/'coordinator/sessions/w0/exit.json')
        first_review=digest(first_root/'frozen/review.json')
        self.assertEqual(terminal_new['reason'],'worker_session_blocked')
        from pilot24_prepare_recovery_v2_candidate import prepare as prepare_second
        values={'MANIFEST':manifest,'T0_SHA':t0sha,'TERMINAL_SHA':termsha,'T0':now,
                'CONFIG_SHA':confsha,'STATE_SHA':statesha,'R1_ROOT':str(first_root),
                'R1_MANIFEST':result['bundle_sha256'],'R1_CONFIG_SHA':result['config_sha256'],
                'R1_STATE_SHA':first_state,'R1_TERMINAL_SHA':first_terminal,'R1_EXIT_SHA':first_exit,'R1_REVIEW_SHA':first_review,
                'ORIGINAL_LEDGER_SHA':hashlib.sha256(f.dbpath.read_bytes()).hexdigest(),
                'R1_LEDGER_SHA':digest(first_root/'workers/S0-00-w0/worker.sqlite')}
        with patch.multiple(guard,**values),patch.object(guard,'_read',side_effect=fixture_read):
            second=prepare_second(repository_root=ROOT,gpu_uuid='GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                                  previous_review_sha256=first_review)
        second_frozen=Path(second['bundle']).parent
        second_review=json.loads((second_frozen/'review.json').read_text())
        second_review.update(status='passed',reviewer='independent-test')
        (second_frozen/'review.json').write_text(json.dumps(second_review))
        env.update(FIX_R1_ROOT=str(first_root),FIX_R1_MANIFEST=result['bundle_sha256'],
                   FIX_R1_CONFIG_SHA=result['config_sha256'],FIX_R1_STATE_SHA=first_state,
                   FIX_R1_TERMINAL_SHA=first_terminal,FIX_R1_EXIT_SHA=first_exit,FIX_R1_REVIEW_SHA=first_review,
                   FIX_R1_LEDGER=digest(first_root/'workers/S0-00-w0/worker.sqlite'))
        command=[sys.executable,str(ROOT/PREFIX/'pilot24_run.py'),'serve','--bundle',second['bundle'],
                 '--config',second['config'],'--root',str(second_frozen.parent/'coordinator'),
                 '--launch-map',str(second_frozen/'launch_map.template.json'),'--server','104','--poll-seconds','.05']
        proc=subprocess.run(command,env=env,text=True,capture_output=True,timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr)
        final=json.loads((second_frozen.parent/'coordinator/terminal.json').read_text())
        session=json.loads((second_frozen.parent/'coordinator/jobs/sessions/w0/session.json').read_text())
        self.assertIn('intentional_cpu_fixture_stop',session.get('error',''))
        self.assertEqual((final['imported'],final['charged_attempts']),(363,0))
        self.assertEqual(final['t0']['file_sha256'],t0sha)
        self.assertEqual(digest(first_root/'coordinator/terminal.json'),first_terminal)
        self.assertEqual(digest(f.root/'terminal.json'),termsha)
        self.assertEqual(digest(f.root/'t0.json'),t0sha)

if __name__=='__main__': unittest.main()
