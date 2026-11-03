"""CPU-only orchestration checks; no real model runtime or GPU permission."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pilot24_coordinator import Coordinator, stage_contract, verify_release, read_json
from pilot24_inputs import RUN, frozen_units
from pilot24_run import ensure_t0, main as pilot_main, parser
import main as legacy_main
from test_pilot24_offline import TASK


class DurableRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stages = frozen_units(TASK/'pilot24_plan_candidate.json', TASK/'pilot24_context_ids.json',
                                  TASK/'manifest_candidate.json', TASK/'prompts_tokenized_candidate.jsonl')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        mock = patch('pilot24_coordinator.verify_scored_png', return_value=True)
        mock.start(); self.addCleanup(mock.stop)
        self.config = dict(run_id=RUN, manifest_sha256='a'*64, model_bundle_sha256='b'*64,
                           scorer_sha256='c'*64, coordinator_root=str(self.root), stages=self.stages,
                           imports=[], labels={'source': {}, 'merge': {}}, units=[], assignments=[])
        for stage, keys in self.stages.items():
            units = [dict(key=list(k), input_sha='d'*64, mask_sha='e'*64) for k in keys]
            self.config['units'].extend(units)
            self.config['assignments'].append(dict(run_id=RUN,manifest_sha256='a'*64,
                assignment_id=stage+'-w0',stage=stage,worker_id='w0',server='104',
                gpu_uuid='GPU-01234567-89ab-cdef-0123-456789abcdef',output_root=str(self.root/stage),
                retry_tokens=32,gate_sha256=stage_contract('a'*64,stage),units=units))
        self.c = Coordinator(self.root,self.config)
        self.addCleanup(self.c.close)
        self.c.bind_t0(dict(run_id=RUN,manifest_sha256='a'*64,t0_utc='2026-11-02T00:00:00Z'),'f'*64)

    def receipt(self, stage, count=None):
        release=self.c.release(stage)
        item=release['assignments'][0]
        a=read_json(item['path'])
        units=a['units'] if count is None else a['units'][:count]
        records=[dict(**u,model_bundle_sha256='b'*64,scorer_sha256='c'*64,
            image_path='/fake/'+stage+str(i)+'.png',image_sha='1'*64,
            scores=dict(vit_class=281,clip_score=30.0)) for i,u in enumerate(units)]
        attempts=[dict(key=u['key'],number=1,status='complete',resource=dict(nfe=50)) for u in units]
        return dict(run_id=RUN,manifest_sha256='a'*64,assignment_id=a['assignment_id'],
            assignment_sha256=item['sha256'],stage=stage,worker_id='w0',t0_sha256='f'*64,
            status='complete' if count is None else 'running',records=records,attempts=attempts)

    def test_barrier_receipt_idempotence_and_t0_immutability(self):
        with self.assertRaises(ValueError): self.c.release('S1')
        r=self.receipt('S0',20)
        self.c.ingest(r);self.c.ingest(r)
        self.assertEqual(len(self.c.records()),20)
        self.assertEqual(self.c.advance()['status'],'waiting')
        with self.assertRaises(ValueError): self.c.ingest(dict(r,records=r['records'][:-1]))
        with self.assertRaises(ValueError): self.c.bind_t0(dict(run_id=RUN,manifest_sha256='a'*64,t0_utc='2026-11-02T01:00:00Z'),'e'*64)
        with self.assertRaises(ValueError): ensure_t0(self.c) # Removed fixed T0 cannot be recreated.

    def test_new_run_entrypoints_forward_to_unified_runtime(self):
        with patch('subprocess.call', return_value=23) as launch:
            self.assertEqual(legacy_main.main(['run', '--spec', '/new/spec.json']), 23)
            self.assertEqual(pilot_main(['run', '--spec', '/new/spec.json']), 23)
        self.assertEqual(launch.call_count, 2)
        for call in launch.call_args_list:
            command = call.args[0]
            self.assertEqual(Path(command[1]).name, 'runtime.py')
            self.assertEqual(command[2:], ['run', '--spec', '/new/spec.json'])

    def test_historical_execution_commands_stay_closed(self):
        with patch('subprocess.call') as launch:
            with self.assertRaises(SystemExit):
                legacy_main.main(['localize'])
            with self.assertRaises(SystemExit):
                pilot_main(['start', '--bundle', 'b', '--config', 'c', '--root', 'r',
                            '--launch-map', 'm', '--server', '103'])
        launch.assert_not_called()

    def test_false_complete_and_duplicate_attempt_fail(self):
        r=self.receipt('S0',1)
        with self.assertRaises(ValueError): self.c.ingest(dict(r,status='complete'))
        r['attempts'].append(copy.deepcopy(r['attempts'][0]))
        with self.assertRaises(ValueError): self.c.ingest(r)

    def test_all_four_stages_need_complete_data(self):
        for stage in ('S0','S1','M0','M1'):
            self.c.ingest(self.receipt(stage))
            report=dict(stage=stage,passed=True,report_sha256='2'*64,result={})
            with patch('pilot24_coordinator.offline_stage_report',return_value=report): self.c.advance()
            if stage!='M1': self.assertIsNone(self.c.state['terminal'])
        self.assertEqual(self.c.state['terminal']['unique_complete'],6144)
        self.assertEqual(self.c.state['terminal']['charged_attempts'],6144)
        self.assertEqual(self.c.state['terminal']['outcome'],'positive')

    def test_baseline_failure_is_inconclusive_with_explicit_skips(self):
        self.c.ingest(self.receipt('S0'))
        report=dict(stage='S0',passed=False,report_sha256='3'*64,result={})
        with patch('pilot24_coordinator.offline_stage_report',return_value=report): self.c.advance()
        self.assertEqual(self.c.state['terminal']['outcome'],'inconclusive')
        self.assertEqual(self.c.state['terminal']['skipped_stages'],['S1','M0','M1'])

    def test_deadline_preserves_failed_attempt_charges(self):
        r=self.receipt('S0',1)
        r['attempts'].append(dict(key=list(self.stages['S0'][1]),number=1,status='started',resource=dict(nfe=12)))
        self.c.ingest(r);self.c.tick('2026-11-02T22:15:00Z')
        self.assertEqual(self.c.state['terminal']['outcome'],'inconclusive')
        self.assertEqual(self.c.state['terminal']['charged_attempts'],2)
        self.assertEqual(self.c.state['terminal']['unique_complete'],1)

    def test_two_hour_feasibility_requires_four_classes(self):
        self.c.ingest(self.receipt('S0',64))
        observation=self.c.capacity('2026-11-02T02:00:00Z')
        self.assertFalse(observation['sample_count_eligible'])
        self.assertEqual(self.c.state['terminal']['reason'],'deadline_infeasible')

    def test_verified_release_cannot_point_to_forged_gate(self):
        release=self.c.release('S0')
        assignment=read_json(release['assignments'][0]['path'])
        self.assertTrue(verify_release(self.root,self.config,assignment,release['gate_path'])['passed'])
        with self.assertRaises(ValueError): verify_release(self.root,self.config,assignment,self.root/'fake.json')
        with self.assertRaises(ValueError): verify_release(self.root,self.config,dict(assignment,gate_sha256='2'*64),release['gate_path'])

    def test_coordinator_rejects_second_writer(self):
        with self.assertRaises(BlockingIOError): Coordinator(self.root,self.config)

    def test_persistent_cli_serves_four_stages_with_one_session(self):
        from types import SimpleNamespace
        from pilot24_run import serve, file_sha
        from pilot24_coordinator import write_json
        root=self.root/'simulation'
        config=copy.deepcopy(self.config)
        config['coordinator_root']=str(root)
        for a in config['assignments']: a['output_root']=str(root/a['assignment_id'])
        launch=self.root/'launch-map.json'
        write_json(launch,{'w0':{'server':'104','permission_ref':'/not-used-in-cpu-simulation'}})
        args=SimpleNamespace(root=str(root),config='mocked',bundle='mocked',launch_map=str(launch),server='104',poll_seconds=.05)
        completed=set()
        def drive(_):
            for message in (root/'sessions/w0/mailbox').glob('*.json'):
                assignment_path=read_json(message)['assignment']
                a=read_json(assignment_path); aid=a['assignment_id']
                if aid in completed: continue
                records=[dict(**u,model_bundle_sha256='b'*64,scorer_sha256='c'*64,image_path='/fake/'+aid+str(i),
                    image_sha='1'*64,scores=dict(vit_class=281,clip_score=30.)) for i,u in enumerate(a['units'])]
                receipt={k:a[k] for k in ('run_id','manifest_sha256','assignment_id','stage','worker_id')}
                receipt.update(assignment_sha256=file_sha(assignment_path),t0_sha256=file_sha(root/'t0.json'),
                    status='complete',records=records,attempts=[dict(key=u['key'],number=1,status='complete',resource={}) for u in a['units']])
                write_json(root/'jobs'/aid/'progress.json',receipt);completed.add(aid)
            if (root/'sessions/w0/stop.json').exists():
                write_json(root/'sessions/w0/exit.json',{'returncode':0})
        def report(stage,*_): return dict(stage=stage,passed=True,report_sha256='2'*64,result={})
        with patch('pilot24_run.load_reviewed_configuration',return_value=config), \
             patch('pilot24_run.subprocess.Popen',return_value=SimpleNamespace(pid=12345)) as spawn, \
             patch('pilot24_run.time.sleep',side_effect=drive), \
             patch('pilot24_coordinator.offline_stage_report',side_effect=report):
            result=serve(args)
        self.assertEqual(spawn.call_count,1)
        self.assertEqual(len(completed),4)
        self.assertEqual(result['unique_complete'],6144)
        self.assertEqual(result['charged_attempts'],6144)
        self.assertEqual(result['outcome'],'positive')
        self.assertTrue((root/'report.md').exists())
        self.assertFalse(result['final_ledger_audit']['counts_are_final']) # fake images/ledgers cannot be called real evidence

    def test_status_reads_atomic_state_while_daemon_holds_lock(self):
        from pilot24_run import main
        with patch('pilot24_run.load_reviewed_configuration',return_value=self.config), patch('builtins.print') as output:
            main(['status','--bundle','mocked','--config','mocked','--root',str(self.root)])
        self.assertIn('S0',output.call_args.args[0])

    def test_blocked_session_cause_wins_when_exit_and_error_arrive_together(self):
        from types import SimpleNamespace
        from pilot24_run import serve
        from pilot24_coordinator import write_json
        root=self.root/'blocked-simulation'
        config=copy.deepcopy(self.config);config['coordinator_root']=str(root)
        for a in config['assignments']:a['output_root']=str(root/a['assignment_id'])
        launch=self.root/'blocked-launch.json'
        write_json(launch,{'w0':{'server':'104','permission_ref':'/unused'}})
        args=SimpleNamespace(root=str(root),config='mocked',bundle='mocked',launch_map=str(launch),server='104',poll_seconds=.05)
        def both_events(_):
            write_json(root/'jobs/sessions/w0/session.json',{'status':'blocked','error':'specific CPU or permission cause'})
            write_json(root/'sessions/w0/exit.json',{'returncode':1})
        with patch('pilot24_run.load_reviewed_configuration',return_value=config), \
             patch('pilot24_run.subprocess.Popen',return_value=SimpleNamespace(pid=12345)), \
             patch('pilot24_run.time.sleep',side_effect=both_events):
            result=serve(args)
        self.assertEqual(result['reason'],'worker_session_blocked')
        self.assertEqual(result['charged_attempts'],0)

    def test_cli_exposes_only_fixed_session_command(self):
        args=parser().parse_args(['supervise','--bundle','b','--mailbox','m','--receipt-root','r',
            '--worker-id','w0','--t0','t','--t0-sha','f'*64,'--permission-ref','p','--stop-file','s',
            '--exit-receipt','e','--gpu-uuid','GPU-01234567-89ab-cdef-0123-456789abcdef'])
        self.assertEqual(args.command,'supervise')


if __name__=='__main__': unittest.main()
