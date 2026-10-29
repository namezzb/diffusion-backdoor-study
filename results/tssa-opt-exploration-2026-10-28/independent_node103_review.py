"""Independent local-only guards for node103 setup; never SSH/install/load ML."""
from pathlib import Path
import ast, hashlib, importlib.util, json, shlex, tarfile, datetime, tempfile, os, stat, types
from unittest import mock

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'prepare_node103_offline.py'
source_bytes = SOURCE.read_bytes()
spec = importlib.util.spec_from_file_location('independent_node103', SOURCE)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
checks = []
def check(name, condition): checks.append({'name': name, 'passed': bool(condition)})
def rejects(name, function):
    try: function()
    except (ValueError, RuntimeError, AssertionError): check(name, True)
    else: check(name, False)

check('fixed_target103_and_source104_roots', m.SOURCE_ROOT == '/data2/zhangzibo/arxiv-tssa' and m.DEST_ROOT == '/data1/zhangzibo/arxiv-tssa')
check('pinned_47_model_inventory', len(m.checked_entries('models')) == 47)
check('pinned_51_wheel_inventory', len(m.checked_entries('wheels')) == 51)
check('pinned_local_python_archive', len(m.checked_entries('python')) == 1 and m.sha256(m.ARCHIVE) == m.ARCHIVE_SHA)
for value in ('/tmp/out', '../out', 'models/../../out', 'models//out', 'models/./out', 'models\\out', 'models/\nsecret'):
    rejects('relative_path_reject_' + repr(value), lambda value=value: m.safe_relative(value))
check('safe_relative_normal_path', m.safe_relative('models/sd15/unet/config.json') == 'models/sd15/unet/config.json')

def member(name, kind=tarfile.REGTYPE, target='', size=0):
    result = tarfile.TarInfo(name); result.type=kind; result.linkname=target; result.size=size
    return result
fixtures = {
    'absolute': [member('/tmp/out')],
    'dotdot': [member('python/../out')],
    'non_python_root': [member('elsewhere/data')],
    'hardlink': [member('python/link', tarfile.LNKTYPE, 'python/real')],
    'fifo': [member('python/pipe', tarfile.FIFOTYPE)],
    'duplicate': [member('python/item'), member('python/item')],
    'outward_symlink': [member('python/link', tarfile.SYMTYPE, '../../outside')],
    'absolute_symlink': [member('python/link', tarfile.SYMTYPE, '/tmp/outside')],
    'symlink_descendant': [member('python/a', tarfile.SYMTYPE, 'b'), member('python/a/item')],
    'extraction_over_budget': [member('python/large', size=2*1024**3+1)],
}
for name, members in fixtures.items():
    rejects('archive_reject_'+name, lambda members=members:m.archive_members_safe(members))
with tarfile.open(m.ARCHIVE, 'r:gz') as archive:
    members=archive.getmembers(); expanded=m.archive_members_safe(members)
    check('actual_pinned_archive_safe', len(members)==2364 and expanded==91072956)

for name in ('REMOTE_COMMON','REMOTE_PREFLIGHT','REMOTE_DEST_INFO','REMOTE_SOURCE_INFO','REMOTE_READ','REMOTE_RECEIVE'):
    ast.parse(getattr(m,name), feature_version=(3,8))
ast.parse(m.python_install_source(), feature_version=(3,8))
check('remote_prep_syntax_python38_compatible', True)
compile(m.ENV_WRAPPER, 'node103-wrapper', 'exec')
check('original_installer_byte_identical_and_only_root_adapter', m.sha256(m.INSTALLER)==m.PINS[m.INSTALLER] and 'm.ALLOWED_ROOT=root' in m.ENV_WRAPPER)
check('CPU_installation_inhibits_CUDA_and_network', "CUDA_VISIBLE_DEVICES=''" in m.python_install_source() and "PIP_NO_INDEX='1'" in m.python_install_source() and "'-I'" in m.python_install_source())
check('incomplete_installations_do_not_blindly_retry', "old['status']=='completed'" in m.python_install_source() and "old['status']!='completed'" in m.ENV_WRAPPER)
with tempfile.TemporaryDirectory(prefix='node103-independent-hardlink-') as folder:
    old=Path(folder)/'old-data'; old.write_bytes(b'old-read-only-evidence')
    partial=Path(folder)/'test.partial';os.link(old,partial)
    guards=[node for node in ast.walk(ast.parse(m.REMOTE_RECEIVE)) if isinstance(node,ast.Assert) and 'st_nlink' in ast.unparse(node.test)]
    namespace={'partial':partial,'info':partial.stat(),'os':os,'stat':stat}
    check('existing_and_open_partial_hardlink_guards_reject', len(guards)==2 and all(not eval(compile(ast.Expression(node.test),'real-partial-guard','eval'),namespace) for node in guards))
    check('hardlink_guard_checks_preserve_old_bytes',old.read_bytes()==b'old-read-only-evidence')
check('state_temp_files_are_random_exclusive', 'NamedTemporaryFile(' in m.python_install_source() and 'NamedTemporaryFile(' in m.ENV_WRAPPER and "str(state)+'.new'" not in m.python_install_source()+m.ENV_WRAPPER)
with tempfile.TemporaryDirectory(prefix='node103-independent-env-identity-') as folder:
    root=Path(folder);base=root/'python-standalone-3.11.7-20240107';(base/'bin').mkdir(parents=True)
    (base/'bin/python3.11').write_bytes(b'CPU fixture, not executable')
    good_state={'status':'completed','archive_sha256':m.ARCHIVE_SHA,'python_sha256':hashlib.sha256((base/'bin/python3.11').read_bytes()).hexdigest()}
    sys_fixture=types.SimpleNamespace(version_info=(3,11,7),prefix=str(root/'venv'),base_prefix=str(base))
    guards=[node for node in ast.walk(ast.parse(m.ENV_WRAPPER)) if isinstance(node,ast.Assert) and ('python_state[' in ast.unparse(node.test) or 'sys.version_info' in ast.unparse(node.test))]
    def accepted(state, system):
        namespace={'python_state':state,'sys':system,'root':root,'base':base,'hashlib':hashlib}
        return len(guards)==3 and all(eval(compile(ast.Expression(node.test),'actual-install-identity-guard','eval'),namespace) for node in guards)
    check('install_env_accepts_exact_completed_private_python_identity',accepted(good_state,sys_fixture))
    check('install_env_rejects_incomplete_python_installation',not accepted({**good_state,'status':'started'},sys_fixture))
    check('install_env_rejects_base_executable_hash_drift',not accepted({**good_state,'python_sha256':'c'*64},sys_fixture))
    check('install_env_rejects_unrelated_existing_venv',not accepted(good_state,types.SimpleNamespace(version_info=(3,11,7),prefix=str(root/'other'),base_prefix=str(base))))

entry={'relative':'models/test/model.bin','size':10,'sha256':'a'*64}
destination={'complete':False,'prefix_size':4,'prefix_sha256':'b'*64}
source={'size':10,'sha256':'a'*64,'prefix_sha256':'b'*64}
check('matched_source_partial_prefix',m.ensure_prefix(source,destination,entry)==4)
rejects('different_prefix_rejected',lambda:m.ensure_prefix(source,{**destination,'prefix_sha256':'c'*64},entry))
rejects('oversized_partial_rejected',lambda:m.ensure_prefix(source,{**destination,'prefix_size':11},entry))
rejects('wrong_full_source_SHA_rejected',lambda:m.ensure_prefix({**source,'sha256':'c'*64},destination,entry))
rejects('wrong_full_source_size_rejected',lambda:m.ensure_prefix({**source,'size':11},destination,entry))
rejects('unregistered_SSH_alias_rejected',lambda:m.ssh_argv(Path('/not-used'),'school127','pass'))
argv=m.ssh_argv(Path('/not-used'),'school103','print("safe")','x; echo must_not_execute')
check('strict_SSH_no_retry_or_agent_keys_exposed','StrictHostKeyChecking=yes' in argv and 'ConnectionAttempts=1' in argv and 'BatchMode=yes' in argv and 'ControlPath=none' in argv and shlex.split(argv[-1])[-1]=='x; echo must_not_execute')

class Pipe:
    def __init__(self): self.closed=False
    def close(self): self.closed=True
class Process:
    def __init__(self, argv, opts, failure, processes):
        self.argv=argv; self.opts=opts; self.source=len(processes)==0
        self.returncode=None; self.stdout=Pipe(); self.terminated=False; self.deadlines=[]
        self.failure=failure; processes.append(self)
    def communicate(self,timeout):
        self.deadlines.append(timeout); self.returncode=9 if self.failure else 0
        return json.dumps({'committed':True,'size':10,'sha256':'a'*64,'relative':entry['relative']}).encode(), b'fixture-target-failure' if self.failure else b''
    def wait(self,timeout): self.deadlines.append(timeout);self.returncode=0;return 0
    def poll(self): return self.returncode
    def terminate(self): self.terminated=True;self.returncode=-15
    def kill(self): self.returncode=-9

for failure in (False,True):
    calls=[]; processes=[]
    def metadata(config,host,code,*args,**kwargs):
        calls.append(host);return destination if host=='school103' else source
    def popen(argv,**kwargs): return Process(argv,kwargs,failure,processes)
    with mock.patch.object(m,'remote_json',side_effect=metadata), mock.patch.object(m.subprocess,'Popen',side_effect=popen):
        if failure:
            rejects('relay_failure_propagates_no_retry',lambda:m.relay(Path('/not-used'),entry))
            check('relay_failure_terminates_only_owned_local_children',len(processes)==2 and processes[0].terminated and calls==['school103','school104'])
        else:
            receipt=m.relay(Path('/not-used'),entry)
            check('relay_success_fixed_hosts_offsets_and_deadlines',receipt['resumed_from']==4 and calls==['school103','school104'] and processes[0].argv[-2]=='school104' and processes[1].argv[-2]=='school103' and processes[1].deadlines==[m.TRANSFER_TIMEOUT])
            check('model_bytes_use_OS_pipe_without_local_model_file', processes[0].opts['stdout']==m.subprocess.PIPE and processes[1].opts['stdin'] is processes[0].stdout and processes[0].stdout.closed)
with mock.patch.object(m,'remote_json',return_value={'complete':True,'size':10,'sha256':'a'*64}), mock.patch.object(m.subprocess,'Popen',side_effect=AssertionError('unexpected transfer')):
    check('verified_existing_target_never_overwritten_or_retransferred',m.relay(Path('/not-used'),entry)['status']=='verified_existing_target')

report={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':str(SOURCE),'source_sha256':hashlib.sha256(source_bytes).hexdigest(),'checks':checks,'passed':all(x['passed'] for x in checks),'failure_names':[x['name'] for x in checks if not x['passed']],'source_still_current':SOURCE.read_bytes()==source_bytes,'actual_SSH_calls':0,'actual_GPU_calls':0,'actual_installs':0,'models_downloaded':0,'scientific_images':0,'evidence_limit':'Static review and bounded local mocks only; server compatibility and CUDA must be separately validated.'}
(HERE/'independent_node103_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
