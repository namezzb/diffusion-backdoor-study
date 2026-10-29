"""Local guards only: no network, models, CUDA, or child-process launch."""
import copy
import __future__
import ast
import datetime as dt
import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('launch_image_search', HERE / 'launch_image_search.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
NOW = dt.datetime(2026, 10, 28, 8, 0, tzinfo=dt.timezone.utc)
UUID = 'GPU-01234567-89ab-cdef-0123-456789abcdef'


def permission(server='104'):
    p = m.permission_template(server)
    p.update(observed_at=NOW.isoformat(), sample_at=NOW.isoformat(), evidence_note='Fresh authenticated UI views reviewed for this exact card.',
             sample_time_basis='timestamp', live_indicator=True, historical_sample=False,
             account_status='normal', gpu_index=0, gpu_uuid=UUID, gpu_disabled=False, sample_valid=True,
             server_maintenance=False, reservation_conflict=False, other_research_task=False,
             own_gpu_count_all_servers=0, pending_allocated_gpu_count_all_servers=0, effective_gpu_quota=4,
             direct_use_allowed=True)
    return p


def xml(processes='', mode='Default', target_uuid=UUID):
    return f'<nvidia_smi_log><driver_version>550.54.14</driver_version><timestamp>live</timestamp><gpu><uuid>{target_uuid}</uuid><compute_mode>{mode}</compute_mode><pci><pci_bus_id>00000000:01:00.0</pci_bus_id></pci><processes>{processes}</processes></gpu></nvidia_smi_log>'


def row(kind='G'):
    return f'<process_info><pid>99</pid><type>{kind}</type><used_memory>4 MiB</used_memory></process_info>'


class PermissionTests(unittest.TestCase):
    def test_valid_direct_and_boundaries(self):
        p = permission()
        m.validate_permission(p, '104', NOW)
        p['observed_at'] = (NOW - dt.timedelta(seconds=120)).isoformat()
        m.validate_permission(p, '104', NOW)
        p['observed_at'] = (NOW - dt.timedelta(seconds=120.001)).isoformat()
        with self.assertRaises(m.GuardError): m.validate_permission(p, '104', NOW)

    def test_unknown_or_bad_ui_fields(self):
        mutations = {'gpu_disabled': True, 'server_maintenance': True, 'reservation_conflict': True,
                     'other_research_task': True, 'sample_valid': False, 'account_status': 'unknown',
                     'direct_use_allowed': False, 'effective_gpu_quota': 0, 'own_gpu_count_all_servers': True,
                     'gpu_uuid': 'GPU-01234567', 'gpu_index': -1, 'source': 'nvidia-smi',
                     'observed_views': ['服务器状态'], 'plan_sha256': '0' * 64, 'account': 'root'}
        for key, value in mutations.items():
            with self.subTest(key=key):
                p = permission(); p[key] = value
                with self.assertRaises(m.GuardError): m.validate_permission(p, '104', NOW)

    def test_missing_future_and_stale_samples(self):
        for value in (None, '2026-10-28T08:00:00', (NOW + dt.timedelta(seconds=1)).isoformat(), (NOW - dt.timedelta(seconds=121)).isoformat()):
            p = permission(); p['sample_at'] = value
            with self.subTest(value=value), self.assertRaises(m.GuardError): m.validate_permission(p, '104', NOW)

    def test_explicit_live_UI_without_invented_timestamp(self):
        p=permission();p.update(sample_time_basis='live_UI_without_timestamp',sample_at=None)
        m.validate_permission(p,'104',NOW)
        for key,value in [('live_indicator',False),('historical_sample',True),('sample_at',NOW.isoformat()),('sample_valid',None),('sample_time_basis',None)]:
            wrong=dict(p);wrong[key]=value
            with self.subTest(key=key),self.assertRaises(m.GuardError):m.validate_permission(wrong,'104',NOW)
        p['observed_at']=(NOW-dt.timedelta(seconds=121)).isoformat()
        with self.assertRaises(m.GuardError):m.validate_permission(p,'104',NOW)

    def test_cross_server_budget(self):
        p = permission(); p.update(own_gpu_count_all_servers=3)
        m.validate_permission(p, '104', NOW)
        for own, pending, quota in [(4,0,4),(3,1,4),(1,0,1),(4,0,8)]:
            q = permission(); q.update(own_gpu_count_all_servers=own,pending_allocated_gpu_count_all_servers=pending,effective_gpu_quota=quota)
            with self.subTest(counts=(own,pending,quota)), self.assertRaises(m.GuardError): m.validate_permission(q,'104',NOW)

    def test_confirmed_allocation_does_not_double_count(self):
        p = permission(); p.update(permission_kind='allocated', own_gpu_count_all_servers=3, pending_allocated_gpu_count_all_servers=1)
        p['allocation'] = {'status':'confirmed','server':'104','gpu_index':0,'gpu_uuid':UUID,'counted_in_pending':True,
                           'assigned_at':(NOW-dt.timedelta(seconds=700)).isoformat(),'confirmed_at':(NOW-dt.timedelta(seconds=200)).isoformat()}
        m.validate_permission(p,'104',NOW)
        p['allocation']['assigned_at'] = (NOW-dt.timedelta(seconds=900)).isoformat()
        with self.assertRaises(m.GuardError): m.validate_permission(p,'104',NOW)
        p['allocation']['confirmed_at'] = (NOW-dt.timedelta(seconds=601)).isoformat()
        with self.assertRaises(m.GuardError): m.validate_permission(p,'104',NOW)


class ProcessTests(unittest.TestCase):
    def test_exact_observed104_gpu0_xwayland_only(self):
        evidence=json.loads((HERE/'node104_graphics_identity_20261028T072313Z.json').read_text())
        identity=next(p for p in evidence['result']['graphics_processes'] if p['comm']=='Xwayland')
        observed=dict(identity,type='G')
        self.assertTrue(m.allowed_display('104',0,observed))
        self.assertFalse(m.allowed_display('104',1,observed))
        self.assertFalse(m.allowed_display('103',0,observed))
        for key,value in [('type','C+G'),('pid',7188),('uid',126),('account','alice'),('home','/home/alice'),('shell','/bin/bash'),('comm','gnome-shell'),('argv',identity['argv']+['-unknown'])]:
            wrong=dict(observed);wrong[key]=value
            with self.subTest(key=key):self.assertFalse(m.allowed_display('104',0,wrong))
        wrong=dict(observed);wrong['argv']=list(identity['argv']);wrong['argv'][7]='/run/user/126/.mutter-Xwaylandauth.ZV08X3'
        self.assertFalse(m.allowed_display('104',0,wrong))

    def test_empty_card_and_wrong_identity(self):
        p = permission()
        m.inspect_gpu(xml(),p,'104')
        for data in [xml(mode='Prohibited'),xml(target_uuid='GPU-ffffffff-ffff-ffff-ffff-ffffffffffff'), '<nvidia_smi_log/>',xml().replace('<processes></processes>','')]:
            with self.subTest(data=data), self.assertRaises(m.GuardError): m.inspect_gpu(data,p,'104')

    def test_exact103_root_xorg_only(self):
        p = permission('103')
        identity = {'pid':99,'uid':0,'account':'root','home':'/root','shell':'/bin/bash','comm':'Xorg','argv':list(m.XORG_103)}
        m.inspect_gpu(xml(row()),p,'103',resolver=lambda _:identity)
        for key,value in [('uid',1000),('account','zhangzibo'),('comm','xfwm4'),('argv',m.XORG_103+['--unknown'])]:
            wrong=dict(identity);wrong[key]=value
            with self.subTest(key=key),self.assertRaises(m.GuardError):m.inspect_gpu(xml(row()),p,'103',resolver=lambda _:wrong)
        self.assertFalse(m.allowed_display('103',2,dict(identity,type='G')))
        with self.assertRaises(m.GuardError):m.inspect_gpu(xml(row('C')),p,'103',resolver=lambda _:identity)
        with self.assertRaises(m.GuardError):m.inspect_gpu(xml(row()),p,'104',resolver=lambda _:identity)

    def test104_gdm_identity_and_other_researcher(self):
        identity={'pid':99,'uid':120,'account':'gdm','home':'/var/lib/gdm3','shell':'/bin/false','comm':'gnome-shell','argv':['/usr/bin/gnome-shell']}
        m.inspect_gpu(xml(row()),permission(),'104',resolver=lambda _:identity)
        for key,value in [('account','alice'),('home','/home/alice'),('shell','/bin/bash'),('argv',['/tmp/gnome-shell'])]:
            wrong=dict(identity);wrong[key]=value
            with self.subTest(key=key),self.assertRaises(m.GuardError):m.inspect_gpu(xml(row()),permission(),'104',resolver=lambda _:wrong)
        with self.assertRaises(m.GuardError):m.inspect_gpu(xml(row('C+G')),permission(),'104',resolver=lambda _:identity)
        with self.assertRaises(m.GuardError):m.inspect_gpu(xml(row()),permission(),'104',resolver=lambda _:identity,own_uid=120)

    def test_unreadable_process_refuses(self):
        def inaccessible(_):raise PermissionError('unknown identity')
        with self.assertRaises(PermissionError):m.inspect_gpu(xml(row()),permission(),'104',resolver=inaccessible)

    def test_other_card_only_requires_uid_and_counts_own(self):
        extra='<gpu><uuid>another</uuid><compute_mode>Default</compute_mode><processes>'+row('C')+'</processes></gpu>'
        data=xml().replace('</nvidia_smi_log>',extra+'</nvidia_smi_log>')
        def must_not_resolve(_):raise AssertionError('Unrelated researcher command should not be read')
        m.inspect_gpu(data,permission(),'104',resolver=must_not_resolve,own_uid=500,uid_resolver=lambda _:600)
        with self.assertRaises(m.GuardError):m.inspect_gpu(data,permission(),'104',resolver=must_not_resolve,own_uid=500,uid_resolver=lambda _:500)


class DeploymentAndClaimTests(unittest.TestCase):
    def test_real_frozen_deployment_local_only(self):
        root=HERE.parents[1]
        deployment=HERE/'deployment_20261028T064803Z.json'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'permission.json';path.write_text(json.dumps(permission()))
            with patch.object(m,'utcnow',return_value=NOW):
                result=m.local_prepare(root,deployment,path,'104')
            self.assertIn('--until',result['command'])
            self.assertEqual(result['command'][-1],'confirm')
            self.assertNotIn('--resume',result['command'])
            self.assertIn('cpu',result['command'])
            self.assertEqual(result['code_root'],'/data2/zhangzibo/arxiv-tssa/code/image-search-6913379cd01c')

    def test_bad_deployment_and_server(self):
        root=HERE.parents[1];plan=json.loads((root/m.PLAN_REL).read_text())
        deployment=json.loads((HERE/'deployment_20261028T064803Z.json').read_text())
        with self.assertRaises(m.GuardError):m.validate_deployment(deployment,plan,'103')
        for key,value in [('status','failed'),('plan_sha256','0'*64),('GPU_launch',True)]:
            d=copy.deepcopy(deployment);d[key]=value
            with self.subTest(key=key),self.assertRaises(m.GuardError):m.validate_deployment(d,plan,'104')
        d=copy.deepcopy(deployment);d['remote']['verified_files']['scripts/merging/tssa_image_search_run.py']='0'*64
        with self.assertRaises(m.GuardError):m.validate_deployment(d,plan,'104')
        d=copy.deepcopy(deployment);d['remote']['offline_import']['CUDA_initialized']=True
        with self.assertRaises(m.GuardError):m.validate_deployment(d,plan,'104')

    def test_permanent_claim_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            claim=Path(folder)/'same-plan.claim.json'
            m.exclusive_json(claim,{'server':'104','status':'unknown'})
            with self.assertRaises(FileExistsError):m.exclusive_json(claim,{'server':'103'})
            self.assertEqual(json.loads(claim.read_text())['server'],'104')

    def test_progress_unknown_or_existing_science_refuses(self):
        baseline=json.loads((HERE/'progress_state.json').read_text())
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            for key,value in [('status','unknown_after_SSH_timeout'),('scientific_images_completed',1),('active_GPU_processes_started_by_this_exploration',None)]:
                state=copy.deepcopy(baseline);state[key]=value
                (out/'progress_state.json').write_text(json.dumps(state))
                with self.subTest(key=key),self.assertRaises(m.GuardError):m.validate_local_state(out)

    def test_orphan_receipt_without_claim_still_refuses(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);(out/'progress_state.json').write_bytes((HERE/'progress_state.json').read_bytes())
            (out/'launch-control').mkdir()
            (out/'launch-control'/'unknown.result.json').write_text('{}')
            with self.assertRaises(m.GuardError):m.validate_local_state(out)

    def test_prepare_cli_cannot_connect_or_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'permission.json';path.write_text(json.dumps(permission()))
            with patch.object(m,'utcnow',return_value=NOW), patch.object(m.subprocess,'run',side_effect=AssertionError('No child process')), patch.object(m.subprocess,'Popen',side_effect=AssertionError('No launch')), contextlib.redirect_stdout(io.StringIO()) as output:
                status=m.main(['--server','104','--deployment',str(HERE/'deployment_20261028T064803Z.json'),'--permission',str(path)])
            self.assertEqual(status,0)
            self.assertEqual(json.loads(output.getvalue())['mode'],'prepared_locally_no_connection')

    def test_permission_template_is_non_authorizing(self):
        for server in ('103','104'):
            with self.assertRaises(m.GuardError):m.validate_permission(m.permission_template(server),server,NOW)


class RuntimePreparationTests(unittest.TestCase):
    def test_permanent_claim_syncs_file_and_both_directory_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder).resolve();control=base/'launch-control';control.mkdir()
            claim=control/'same-plan.claim.json'
            actual_fsync=m.os.fsync
            synced=[]
            def record_sync(fd):
                synced.append(m.os.fstat(fd).st_ino)
                actual_fsync(fd)
            with patch.object(m.os,'fsync',side_effect=record_sync):m.exclusive_json(claim,{'status':'attempt_claimed'})
            self.assertEqual(synced,[claim.stat().st_ino,control.stat().st_ino,base.stat().st_ino])

    def test_directory_sync_failure_cannot_return_success_or_erase_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            claim=Path(folder)/'same-plan.claim.json'
            with patch.object(m,'fsync_directory',side_effect=OSError('directory sync failed')),self.assertRaises(OSError):m.exclusive_json(claim,{'status':'unknown'})
            self.assertTrue(claim.exists())
            with self.assertRaises(FileExistsError):m.exclusive_json(claim,{'status':'retry'})

    def test_missing_directories_created_and_reused_without_run_or_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder).resolve()
            paths=m.prepare_runtime_directories(base)
            self.assertEqual(paths,m.prepare_runtime_directories(base))
            for name in paths:
                path=Path(name)
                self.assertTrue(path.is_dir())
                self.assertEqual(path.stat().st_uid,os.getuid())
                self.assertEqual(path,path.resolve())
            self.assertFalse((base/'results'/m.RUN_NAME).exists())
            self.assertFalse((base/'launch-control').exists())

    def test_redirected_or_unsafe_cache_rejected_before_claim(self):
        for failure in ('symlink','writable','file'):
            with tempfile.TemporaryDirectory() as folder:
                base=Path(folder).resolve();cache=base/'cache'
                if failure=='symlink':
                    outside=base/'elsewhere';outside.mkdir();cache.symlink_to(outside,target_is_directory=True)
                elif failure=='writable':cache.mkdir();cache.chmod(0o777)
                else:cache.write_text('not a directory')
                with self.subTest(failure=failure),self.assertRaises((m.GuardError,FileExistsError)):m.prepare_runtime_directories(base)
                self.assertFalse((base/'launch-control').exists())

    def test_environment_passes_frozen_runtime_before_any_cuda_query(self):
        # Execute the real frozen guard, stopping at its first CUDA query. No
        # torch import or GPU initialization is involved in this contract test.
        source=(HERE.parents[1]/'scripts/merging/tssa_sd_runtime.py').read_text()
        function=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='require_allocated_cuda')
        module=ast.Module(body=[function],type_ignores=[])
        class ReachedCUDAQuery(Exception):pass
        def stop_before_cuda():raise ReachedCUDAQuery()
        namespace={'os':os,'re':re,'torch':types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=stop_before_cuda))}
        exec(compile(module,'frozen_runtime_guard','exec',flags=__future__.annotations.compiler_flag),namespace)
        env=m.runner_environment(Path('/data1/zhangzibo/arxiv-tssa'),UUID,
                                 {'CUBLAS_WORKSPACE_CONFIG':':16:8','CUDA_VISIBLE_DEVICES':'7','PYTHONPATH':'/untrusted','LD_PRELOAD':'bad.so'})
        self.assertNotIn('PYTHONPATH',env)
        self.assertNotIn('LD_PRELOAD',env)
        with patch.dict(os.environ,env,clear=True),self.assertRaises(ReachedCUDAQuery):namespace['require_allocated_cuda']()
        del env['CUBLAS_WORKSPACE_CONFIG']
        with patch.dict(os.environ,env,clear=True),self.assertRaisesRegex(RuntimeError,'CUBLAS_WORKSPACE_CONFIG'):namespace['require_allocated_cuda']()


if __name__=='__main__':unittest.main()
