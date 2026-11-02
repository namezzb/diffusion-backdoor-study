"""Fail-closed predecessor guard for the *single observed* pilot24 interruption.

This is an independently reviewable building block, NOT a launcher, approval,
resource permit, or a complete recovery implementation. A caller must hold this
context for the complete lifetime of every new coordinator and worker and must
independently authenticate the amendment, new code and live resource permit.
"""
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3

RUN = 'tcl-20261102-pilot24-v2'
MANIFEST = '5f635ed4654cc2de6c24ee5a33936041819468c07b1bb4a9c644821b0e0e29ec'
T0_SHA = 'd8c58e2f670ba85478bcba8083323ddaff9a372f200976e076e46f38440e7449'
TERMINAL_SHA = 'c97629c2ab84d412ca20019831e2fa09129c4fecc034a4f5789e49e4738a3176'
T0 = '2026-11-02T08:08:50.071881+00:00'
ORIGINAL_ROOT = '/data2/zhangzibo/arxiv-tssa/results/tcl-20261102-pilot24-v2/coordinator'
ORIGINAL_BUNDLE = '/data2/zhangzibo/arxiv-tssa/results/tcl-20261102-pilot24-v2/frozen/bundle.json'
ORIGINAL_CONFIG = '/data2/zhangzibo/arxiv-tssa/results/tcl-20261102-pilot24-v2/frozen/coordinator_config.json'
CONFIG_SHA = '833a3f7b597ecd9eadb0fdc6366e20f388c2560a3b0c63b19384a34e6fd0389a'
STATE_SHA = '60bd3580483ebb8cdb95617d8a8a22585ab62b2e622e36bb45c04e9b8904bd40'
ORIGINAL_LEDGER_SHA = '47b2c872e89abd656e3dfd202b6bd46f53d2b768afab4751894bd3245f54caee'
R1_ROOT = '/data2/zhangzibo/arxiv-tssa/results/tcl-20261102-pilot24-v2/recovery-v1'
R1_MANIFEST = 'c52a06d8d85d08925604a5a5194bf190e0eb90df797f220cf2e03c2fbb3c128d'
R1_CONFIG_SHA = '0eb5d3c4e8e40f89b32d2a01e4ba3dcf28a0423034546a06787946121fce7573'
R1_STATE_SHA = '41aef46d21c717d473fc1a0ecc9dd9a902d3e5c9c7de05aca2f623ad0bdfc22a'
R1_TERMINAL_SHA = '5a1400aff55cfce63df891b57401571c82752f0f8defe2cc5989b0384fac597b'
R1_EXIT_SHA = 'ec8ec7b8f8a23ba48efb97b35351b1a58a00a53d90cb5d20456e7c40a99f2292'
R1_REVIEW_SHA = 'd7a7c6e0b7d44475ce4cdabf80c30ed8dfc4f8eae23895c9bf16d6abf7c94100'
R1_LEDGER_SHA = 'fd85bf7915d3dfebb9146e39ec24221c6c62925dd06d2cc68d2550edd7128908'


def validate_amendment(bundle, config, review, new_manifest):
    """Validate the independently reviewed old-to-new identity mapping.

    This comparison changes no input or budget; it permits only a fresh code
    revision, review path, coordinator namespace and worker output namespace.
    Holding the predecessor locks for the whole execution remains mandatory.
    """
    from pilot24_coordinator import stage_contract
    rec = config.get('recovery')
    if isinstance(rec, dict) and 'previous' in rec:
        return validate_second_amendment(bundle, config, review, new_manifest)
    required = {'original_bundle', 'original_config', 'original_config_sha256',
                'original_state_sha256', 'original_coordinator_root', 'original_t0_sha256',
                'original_terminal_sha256'}
    if not isinstance(rec, dict) or set(rec) != required:
        raise ValueError('complete independently reviewed recovery lineage required')
    if (rec['original_bundle'] != ORIGINAL_BUNDLE or rec['original_config'] != ORIGINAL_CONFIG
            or rec['original_coordinator_root'] != ORIGINAL_ROOT or rec['original_config_sha256'] != CONFIG_SHA
            or rec['original_state_sha256'] != STATE_SHA):
        raise ValueError('recovery must bind the original coordinator and its exact frozen state')
    if (rec['original_t0_sha256'] != T0_SHA or rec['original_terminal_sha256'] != TERMINAL_SHA
            or review.get('original_manifest_sha256') != MANIFEST
            or review.get('original_t0_sha256') != T0_SHA
            or review.get('original_terminal_sha256') != TERMINAL_SHA):
        raise ValueError('recovery review does not bind predecessor identity')
    old_bundle = _read(rec['original_bundle'], MANIFEST)
    old_config = _read(rec['original_config'], rec['original_config_sha256'])
    if (old_config.get('manifest_sha256') != MANIFEST
            or old_config.get('coordinator_root') != rec['original_coordinator_root']):
        raise ValueError('predecessor config identity mismatch')
    # Never silently revise any scientific source, model, score or setting.
    allowed_bundle = {'repository_root', 'review_file', 'code_sha256'}
    if {k: v for k, v in bundle.items() if k not in allowed_bundle} != {
            k: v for k, v in old_bundle.items() if k not in allowed_bundle}:
        raise ValueError('amendment changed frozen scientific bundle')
    allowed_config = {'manifest_sha256', 'coordinator_root', 'assignments', 'recovery'}
    if {k: v for k, v in config.items() if k not in allowed_config} != {
            k: v for k, v in old_config.items() if k not in allowed_config}:
        raise ValueError('amendment changed scientific configuration or imports')
    original_root = Path(rec['original_coordinator_root']).parent
    new_root = Path(config['coordinator_root'])
    if (not new_root.is_absolute() or '..' in new_root.parts
            or new_root.parent.parent != original_root or new_root.parent.name != 'recovery-v1'
            or new_root.name != 'coordinator'):
        raise ValueError('recovery coordinator must use its isolated namespace')
    old_assignments = old_config['assignments']
    new_assignments = config['assignments']
    if not isinstance(old_assignments, list) or not isinstance(new_assignments, list) or len(old_assignments) != len(new_assignments):
        raise ValueError('recovery assignments changed')
    old_by_id = {x['assignment_id']: x for x in old_assignments}
    if len(old_by_id) != len(old_assignments) or len({x['assignment_id'] for x in new_assignments}) != len(new_assignments):
        raise ValueError('duplicate assignment identity')
    for item in new_assignments:
        previous = old_by_id.get(item['assignment_id'])
        mutable = {'manifest_sha256', 'gate_sha256', 'output_root'}
        if (previous is None or {k: v for k, v in item.items() if k not in mutable} !=
                {k: v for k, v in previous.items() if k not in mutable}
                or item['manifest_sha256'] != new_manifest
                or item['gate_sha256'] != stage_contract(new_manifest, item['stage'])
                or item['output_root'] != str(new_root.parent / 'workers' / item['assignment_id'])):
            raise ValueError('assignment, hardware or retry budget changed')
    return rec


def _regular(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('absolute ordinary file required')
    return path


def validate_second_amendment(bundle, config, review, new_manifest):
    """Bind the exact two zero-attempt predecessors and permit one GPU rebind."""
    import re
    from pilot24_coordinator import stage_contract
    rec = config.get('recovery')
    review_sha = rec.get('previous', {}).get('review_sha256') if isinstance(rec, dict) else None
    if review_sha != R1_REVIEW_SHA:
        raise ValueError('independently observed previous review SHA is required')
    previous = {'root': R1_ROOT, 'manifest_sha256': R1_MANIFEST, 'config_sha256': R1_CONFIG_SHA,
                'state_sha256': R1_STATE_SHA, 'terminal_sha256': R1_TERMINAL_SHA,
                'exit_sha256': R1_EXIT_SHA, 'review_sha256': review_sha}
    required = {'original_bundle', 'original_config', 'original_config_sha256', 'original_state_sha256',
                'original_coordinator_root', 'original_t0_sha256', 'original_terminal_sha256', 'previous'}
    if (not isinstance(rec, dict) or set(rec) != required or rec['previous'] != previous
            or rec['original_bundle'] != ORIGINAL_BUNDLE or rec['original_config'] != ORIGINAL_CONFIG
            or rec['original_coordinator_root'] != ORIGINAL_ROOT or rec['original_config_sha256'] != CONFIG_SHA
            or rec['original_state_sha256'] != STATE_SHA or rec['original_t0_sha256'] != T0_SHA
            or rec['original_terminal_sha256'] != TERMINAL_SHA
            or review.get('original_manifest_sha256') != MANIFEST or review.get('original_t0_sha256') != T0_SHA
            or review.get('original_terminal_sha256') != TERMINAL_SHA
            or review.get('previous_manifest_sha256') != R1_MANIFEST
            or review.get('previous_terminal_sha256') != R1_TERMINAL_SHA
            or review.get('previous_state_sha256') != R1_STATE_SHA
            or review.get('previous_review_sha256') != review_sha):
        raise ValueError('second amendment must bind both exact predecessor identities')
    old_bundle = _read(Path(R1_ROOT) / 'frozen/bundle.json', R1_MANIFEST)
    old_config = _read(Path(R1_ROOT) / 'frozen/coordinator_config.json', R1_CONFIG_SHA)
    # Previous review is authenticated by its expected bundle/config and role
    # fields, rather than trusting a copied state or review supplied by caller.
    prior_review = _read(old_bundle['review_file'], review_sha)
    if (prior_review.get('status') != 'passed' or prior_review.get('manifest_sha256') != R1_MANIFEST
            or prior_review.get('coordinator_config_sha256') != R1_CONFIG_SHA
            or not prior_review.get('reviewer') or not prior_review.get('implementer')
            or prior_review['reviewer'] == prior_review['implementer']):
        raise ValueError('previous amendment lacks the reviewed original config')
    validate_amendment(old_bundle, old_config, prior_review, R1_MANIFEST)
    allowed = {'repository_root', 'review_file', 'code_sha256'}
    if {k:v for k,v in bundle.items() if k not in allowed} != {k:v for k,v in old_bundle.items() if k not in allowed}:
        raise ValueError('second amendment changed scientific bundle')
    allowed_config = {'manifest_sha256','coordinator_root','assignments','recovery'}
    if {k:v for k,v in config.items() if k not in allowed_config} != {k:v for k,v in old_config.items() if k not in allowed_config}:
        raise ValueError('second amendment changed scientific configuration or imports')
    destination = Path(ORIGINAL_ROOT).parent / 'recovery-v2'
    if config.get('coordinator_root') != str(destination / 'coordinator'):
        raise ValueError('second amendment namespace changed')
    old = {a['assignment_id']:a for a in old_config['assignments']}
    revised = config['assignments']
    if len(old) != len(old_config['assignments']) or len(revised) != len(old) or len({a['assignment_id'] for a in revised}) != len(revised):
        raise ValueError('second amendment assignments changed')
    uuids = set()
    for item in revised:
        before = old.get(item['assignment_id'])
        mutable = {'manifest_sha256','gate_sha256','output_root','gpu_uuid'}
        uuid = item.get('gpu_uuid','')
        if (before is None or {k:v for k,v in item.items() if k not in mutable} != {k:v for k,v in before.items() if k not in mutable}
                or not re.fullmatch(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',uuid)
                or item['manifest_sha256'] != new_manifest or item['gate_sha256'] != stage_contract(new_manifest,item['stage'])
                or item['output_root'] != str(destination/'workers'/item['assignment_id'])):
            raise ValueError('second amendment changed science, server or retry allocation')
        uuids.add(uuid.lower())
    if len(uuids) != 1:
        raise ValueError('second amendment requires exactly one target GPU UUID')
    return rec


def _read(path, sha):
    raw = _regular(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('predecessor hash mismatch: ' + str(path))
    return json.loads(raw)


def _lock(path, stack):
    # Do not create or replace original lock files. Hold each actual inode.
    path = _regular(path)
    fd = os.open(path, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
    stack.callback(os.close, fd)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != (path.stat().st_dev, path.stat().st_ino):
        raise ValueError('lock inode changed')
    return fd


def validate_inherited_locks(coordinator_root, fds, *, second=False):
    """Require inherited lock inodes, not just claimed numeric descriptors."""
    root = Path(coordinator_root)
    if str(root) != ORIGINAL_ROOT:
        raise ValueError('only the observed original coordinator and frozen state are allowed')
    workers = root.parent / 'workers'
    paths = [root / '.coordinator.lock'] + [p / '.worker.lock' for p in sorted(workers.iterdir())]
    if second:
        other = Path(R1_ROOT)
        paths += [other / 'coordinator/.coordinator.lock'] + [p / '.worker.lock' for p in sorted((other / 'workers').iterdir())]
    if (not isinstance(fds, tuple) or len(fds) != len(paths) or len(set(fds)) != len(fds)
            or any(type(fd) is not int or fd <= 2 for fd in fds)):
        raise ValueError('incomplete inherited predecessor lock set')
    for path, fd in zip(paths, fds):
        path = _regular(path)
        actual, expected = os.fstat(fd), path.stat()
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise ValueError('inherited predecessor lock inode mismatch')
        def require_locked():
            probe = os.open(path, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
            try:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
                raise ValueError('predecessor lock is not held')
            finally:
                os.close(probe)
        require_locked()
        # flock is associated with the open file description. Reacquiring via
        # the inherited descriptor succeeds, while another open of the same
        # inode conflicts with the held lock.
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('descriptor does not own predecessor lock') from error
        require_locked()


def _absent(pid, *, group=False):
    if type(pid) is not int or pid <= 1:
        raise ValueError('valid recorded process identity required')
    try:
        (os.killpg if group else os.kill)(pid, 0)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise ValueError('cannot establish old process absence') from exc
    raise ValueError('old process or process group still exists')


def _deadline(now):
    if now.tzinfo is None or now.utcoffset().total_seconds() != 0:
        raise ValueError('explicit UTC time required')
    seconds = (now - datetime.fromisoformat(T0)).total_seconds()
    if not 0 <= seconds < 22 * 3600:
        raise ValueError('outside original generation window')
    return seconds


@contextmanager
def hold_both_predecessors(*, previous_review_sha256, now=None):
    """Acquire the original lock set and then the exact first amendment's set."""
    with hold_predecessor(coordinator_root=ORIGINAL_ROOT, original_bundle=ORIGINAL_BUNDLE,
            original_config=ORIGINAL_CONFIG, expected_config_sha=CONFIG_SHA, expected_state_sha=STATE_SHA,
            expected_bundle_sha=MANIFEST, now=now) as first, ExitStack() as stack:
        base = Path(R1_ROOT); root = base / 'coordinator'
        lock_fds = list(first['lock_fds']) + [_lock(root / '.coordinator.lock', stack)]
        bundle = _read(base/'frozen/bundle.json', R1_MANIFEST)
        config = _read(base/'frozen/coordinator_config.json', R1_CONFIG_SHA)
        state = _read(root/'state.json', R1_STATE_SHA)
        terminal = _read(root/'terminal.json', R1_TERMINAL_SHA)
        if previous_review_sha256 != R1_REVIEW_SHA:
            raise ValueError('independently observed previous review SHA is required')
        review = _read(bundle['review_file'],previous_review_sha256)
        if (review.get('status') != 'passed' or review.get('manifest_sha256') != R1_MANIFEST
                or review.get('coordinator_config_sha256') != R1_CONFIG_SHA
                or not review.get('reviewer') or not review.get('implementer')
                or review['reviewer'] == review['implementer']):
            raise ValueError('previous amendment review invalid')
        validate_amendment(bundle, config, review, R1_MANIFEST)
        if (state.get('terminal') != terminal or state.get('stage') != 'S0'
                or terminal.get('run_id') != RUN or terminal.get('manifest_sha256') != R1_MANIFEST
                or terminal.get('reason') != 'worker_session_blocked' or terminal.get('charged_attempts') != 0
                or terminal.get('imported') != 363 or terminal.get('unique_complete') != 363
                or terminal.get('worker_exit_verified') is not True
                or terminal.get('final_ledger_audit') != {'audited':['S0-00-w0'],'counts_are_final':True,'errors':[]}):
            raise ValueError('previous amendment is not the reviewed zero-attempt terminal')
        expected_t0 = {'file_sha256':T0_SHA,'manifest_sha256':MANIFEST,'run_id':RUN,'t0_utc':T0}
        if terminal.get('t0') != expected_t0 or state.get('t0') != expected_t0:
            raise ValueError('previous amendment changed the original T0')
        sessions=root/'sessions'
        if sessions.is_symlink() or not sessions.is_dir() or {p.name for p in sessions.iterdir()} != {'w0'}:
            raise ValueError('unexpected previous amendment sessions')
        exit_data=_read(sessions/'w0/exit.json',R1_EXIT_SHA)
        if (exit_data.get('run_id') != RUN or exit_data.get('worker_id') != 'w0'
                or exit_data.get('manifest_sha256') != R1_MANIFEST or exit_data.get('t0_sha256') != T0_SHA):
            raise ValueError('previous amendment exit identity mismatch')
        _absent(json.loads(_regular(sessions/'w0/supervisor.json').read_text()).get('pid'))
        _absent(exit_data.get('owned_process_group'),group=True)
        if set(state.get('released',{})) != {'S0'}:
            raise ValueError('unexpected previous amendment stages')
        for ref in state.get('receipts',{}).values():
            path=root/ref['path']
            if path.parent != root/'receipts': raise ValueError('receipt outside predecessor root')
            receipt=json.loads(_regular(path).read_text())
            encoded=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
            if hashlib.sha256(encoded.encode()).hexdigest() != ref['sha256'] or receipt.get('attempts') or receipt.get('records'):
                raise ValueError('previous receipt changed or contains work')
        workers=base/'workers'
        if workers.is_symlink() or {p.name for p in workers.iterdir()} != {'S0-00-w0'}:
            raise ValueError('unexpected previous worker directories')
        work=workers/'S0-00-w0'; lock_fds.append(_lock(work/'.worker.lock',stack))
        items=[x for x in state['released']['S0']['assignments'] if x['assignment_id']=='S0-00-w0']
        if len(items)!=1 or Path(items[0]['path']).parent != root/'assignments':
            raise ValueError('previous assignment missing')
        assignment=_read(items[0]['path'],items[0]['sha256'])
        if (assignment.get('run_id') != RUN or assignment.get('manifest_sha256') != R1_MANIFEST
                or assignment.get('output_root') != str(work)):
            raise ValueError('previous ledger assignment identity mismatch')
        path=_regular(work/'worker.sqlite')
        if any(Path(str(path)+s).exists() for s in ('-wal','-shm','-journal')):
            raise ValueError('previous ledger journal requires separate audit')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
            if db.execute('PRAGMA quick_check').fetchone()!=('ok',): raise ValueError('previous ledger corrupt')
            saved=db.execute('SELECT assignment FROM metadata WHERE id=1').fetchone()
            if not saved or json.loads(saved[0]) != assignment: raise ValueError('previous ledger mismatch')
            if db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] != 0: raise ValueError('previous amendment has charged work')
            rows=db.execute('SELECT key,input_sha,mask_sha,status,image_sha,scores FROM units').fetchall()
            expected={(json.dumps(u['key'],ensure_ascii=False,sort_keys=True,separators=(',',':')),u['input_sha'],u['mask_sha'],'unstarted',None,None) for u in assignment['units']}
            if len(rows)!=len(expected) or set(rows)!=expected: raise ValueError('previous units changed or started')
        if hashlib.sha256(path.read_bytes()).hexdigest() != R1_LEDGER_SHA:
            raise ValueError('previous ledger hash differs from independent observation')
        yield {**first,'lock_fds':tuple(lock_fds),'previous_manifest_sha256':R1_MANIFEST}


@contextmanager
def hold_predecessor(*, coordinator_root, original_bundle, original_config,
                     expected_config_sha, expected_state_sha, expected_bundle_sha=MANIFEST,
                     now=None):
    """Hold original locks and independently validate the zero-attempt terminal.

    expected_config_sha and expected_state_sha must be bound by an independent
    review outside this function. No write to the predecessor is performed.
    The returned facts alone do not permit a recovery or any GPU use.
    """
    root = Path(coordinator_root)
    if (str(root) != ORIGINAL_ROOT or str(original_bundle) != ORIGINAL_BUNDLE
            or str(original_config) != ORIGINAL_CONFIG or expected_config_sha != CONFIG_SHA
            or expected_state_sha != STATE_SHA):
        raise ValueError('only the observed original coordinator and frozen state are allowed')
    if (not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents))
            or not root.is_dir()):
        raise ValueError('original coordinator directory required')
    if expected_bundle_sha != MANIFEST:
        raise ValueError('unexpected original bundle identity')
    with ExitStack() as stack:
        lock_fds = [_lock(root / '.coordinator.lock', stack)]
        bundle = _read(original_bundle, MANIFEST)
        config = _read(original_config, expected_config_sha)
        state = _read(root / 'state.json', expected_state_sha)
        terminal = _read(root / 'terminal.json', TERMINAL_SHA)
        t0 = _read(root / 't0.json', T0_SHA)
        if (bundle.get('run_id') != RUN or config.get('run_id') != RUN
                or config.get('manifest_sha256') != MANIFEST
                or config.get('coordinator_root') != str(root)
                or state.get('terminal') != terminal or state.get('stage') != 'S0'):
            raise ValueError('predecessor identity or state mismatch')
        if t0 != {'run_id': RUN, 'manifest_sha256': MANIFEST, 't0_utc': T0}:
            raise ValueError('original T0 mismatch')
        if state.get('t0') != {**t0, 'file_sha256': T0_SHA}:
            raise ValueError('state does not bind original T0')
        if (terminal.get('run_id') != RUN or terminal.get('manifest_sha256') != MANIFEST
                or terminal.get('reason') != 'worker_session_blocked'
                or terminal.get('charged_attempts') != 0 or terminal.get('imported') != 363
                or terminal.get('unique_complete') != 363 or terminal.get('required_unique_max') != 6144
                or terminal.get('worker_exit_verified') is not True
                or terminal.get('final_ledger_audit') != {'audited': ['S0-00-w0'], 'counts_are_final': True, 'errors': []}):
            raise ValueError('terminal is not the reviewed zero-attempt predecessor')
        imports = config.get('imports')
        if not isinstance(imports, list) or len(imports) != 363 or len({tuple(x['key']) for x in imports}) != 363:
            raise ValueError('original imports are incomplete or duplicate')
        sessions = root / 'sessions'
        if sessions.is_symlink() or not sessions.is_dir() or {p.name for p in sessions.iterdir()} != {'w0'}:
            raise ValueError('unexpected worker sessions')
        session = sessions / 'w0'
        exit_data = _read(session / 'exit.json', '9698ef0fe7536d2569b17b33bf43066b3550e3c74ad8b72b1744cb5a2df65ea4')
        if (exit_data.get('run_id') != RUN or exit_data.get('worker_id') != 'w0'
                or exit_data.get('manifest_sha256') != MANIFEST or exit_data.get('t0_sha256') != T0_SHA):
            raise ValueError('worker exit receipt identity mismatch')
        supervisor = json.loads(_regular(session / 'supervisor.json').read_text())
        _absent(supervisor.get('pid'))
        _absent(exit_data.get('owned_process_group'), group=True)
        releases = state.get('released', {})
        if set(releases) != {'S0'}:
            raise ValueError('unexpected predecessor stage release')
        for receipt_ref in state.get('receipts', {}).values():
            receipt_path = root / receipt_ref['path']
            if not receipt_path.is_relative_to(root / 'receipts'):
                raise ValueError('receipt outside predecessor root')
            receipt = json.loads(_regular(receipt_path).read_text())
            canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            if hashlib.sha256(canonical.encode()).hexdigest() != receipt_ref['sha256']:
                raise ValueError('predecessor receipt changed')
            if receipt.get('attempts') or receipt.get('records'):
                raise ValueError('predecessor receipt contains charged work')
        assigned = releases['S0']['assignments']
        if not isinstance(assigned, list) or not assigned:
            raise ValueError('original assignments missing')
        ledger_count, known_paths = 0, set()
        for item in assigned:
            if Path(item['path']).parent != root / 'assignments':
                raise ValueError('assignment outside predecessor root')
            assignment = _read(item['path'], item['sha256'])
            if (item['assignment_id'] != assignment.get('assignment_id')
                    or assignment.get('run_id') != RUN or assignment.get('manifest_sha256') != MANIFEST):
                raise ValueError('predecessor assignment mismatch')
            work = Path(assignment['output_root'])
            base = root.parent / 'workers'
            if not work.is_absolute() or '..' in work.parts or work.parent != base or any(p.is_symlink() for p in (work, *work.parents)):
                raise ValueError('unexpected old worker path')
            known_paths.add(work)
            if not work.exists():
                continue
            lock_fds.append(_lock(work / '.worker.lock', stack))
            dbpath = _regular(work / 'worker.sqlite')
            if any(Path(str(dbpath) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
                raise ValueError('ledger journal requires separate audit')
            with closing(sqlite3.connect(dbpath.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
                if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
                    raise ValueError('predecessor ledger integrity failure')
                saved = db.execute('SELECT assignment FROM metadata WHERE id=1').fetchone()
                if not saved or json.loads(saved[0]) != assignment:
                    raise ValueError('predecessor ledger assignment mismatch')
                if db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] != 0:
                    raise ValueError('charged attempts require a different recovery plan')
                units = db.execute('SELECT key,input_sha,mask_sha,status,image_sha,scores FROM units').fetchall()
                expected = {(json.dumps(u['key'], ensure_ascii=False, sort_keys=True, separators=(',', ':')),
                             u['input_sha'], u['mask_sha'], 'unstarted', None, None) for u in assignment['units']}
                if len(units) != len(expected) or set(units) != expected:
                    raise ValueError('predecessor ledger units differ or have started')
                ledger_count += 1
            if hashlib.sha256(dbpath.read_bytes()).hexdigest() != ORIGINAL_LEDGER_SHA:
                raise ValueError('original ledger hash differs from independent observation')
        if ledger_count != 1:
            raise ValueError('expected exactly one original ledger')
        workers = root.parent / 'workers'
        if workers.is_symlink() or any(p not in known_paths for p in workers.iterdir()):
            raise ValueError('unaccounted predecessor worker directory')
        elapsed = _deadline(now or datetime.now(timezone.utc))
        yield {'run_id': RUN, 'original_manifest_sha256': MANIFEST, 't0_sha256': T0_SHA,
               't0_utc': T0, 'elapsed_seconds': elapsed, 'imports': 363,
               'previous_new_attempts': 0, 'max_new_attempts': 6272 - 363,
               'authorization': 'none_guard_only', 'lock_fds': tuple(lock_fds)}
