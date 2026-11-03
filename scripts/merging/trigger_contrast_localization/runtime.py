"""Start or resume a new local TCL run. Historical pilot24 runs are excluded."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from runtime_store import BudgetExhausted, Store, canonical, digest, now, writer_identity, read_markdown

OLD_RUN = 'tcl-20261102-pilot24-v2'
ROOT = Path(__file__).resolve().parents[3]


def read_ref(ref):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
        raise ValueError('expected a path and SHA256 reference')
    path = Path(ref['path'])
    if not path.is_absolute() or not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('reference must be an ordinary absolute file')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref['sha256']:
        raise ValueError('reference hash mismatch: ' + str(path))
    return raw


def load_spec(path):
    spec = json.loads(Path(path).read_text())
    from runtime_tcl import require_current_run
    require_current_run(spec.get('run_id'), spec.get('run_root', ''))
    if spec.get('schema_version') != 1 or not isinstance(spec.get('run_id'), str) or not spec['run_id'] or spec['run_id'] == OLD_RUN:
        raise ValueError('a new run identity and schema_version 1 are required')
    if OLD_RUN in Path(spec['run_root']).parts:
        raise ValueError('historical run directory is read-only')
    science, execution = spec['science'], spec['execution']
    limit = science.get('max_compute_seconds')
    if limit is not None and (type(limit) not in (int, float) or not 0 < limit < 1e9):
        raise ValueError('max_compute_seconds must be a positive finite limit')
    deadline = science.get('compute_deadline_utc')
    if deadline is not None:
        try:
            parsed = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
            if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
                raise ValueError('deadline must use UTC')
        except (ValueError, TypeError, AttributeError, OverflowError) as exc:
            raise ValueError('compute_deadline_utc must be an ISO UTC timestamp') from exc
    if science.get('backend') != 'tcl_sd':
        raise ValueError('unsupported backend')
    units, budget = science['units'], science['budget']
    if not isinstance(units, list) or not units or not isinstance(budget, dict):
        raise ValueError('nonempty finite units and budget required')
    if any(type(budget.get(k)) is not int or budget[k] < 1 for k in ('max_attempts', 'max_attempts_per_key')):
        raise ValueError('positive integer attempt limits required')
    if (not isinstance(budget.get('state_max_attempts'), dict)
            or set(budget['state_max_attempts']) != {'source', 'merge'}
            or any(type(v) is not int or v < 1 for v in budget['state_max_attempts'].values())
            or sum(budget['state_max_attempts'].values()) > budget['max_attempts']):
        raise ValueError('finite per-state attempt budgets required')
    keys = []
    for unit in units:
        key = unit.get('key')
        if not isinstance(key, list) or len(key) != 6 or key[0] != spec['run_id'] or key[1] not in ('source', 'merge'):
            raise ValueError('invalid unit identity')
        if any(not isinstance(unit.get(k), str) or not re.fullmatch('[0-9a-f]{64}', unit[k]) for k in ('input_sha', 'mask_sha')):
            raise ValueError('unit input and mask hashes required')
        keys.append(canonical(key))
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate units')
    return spec


def observed_code():
    names = ('runtime.py', 'runtime_store.py', 'runtime_tcl.py', 'runtime_assets.py', 'pilot24_provenance.py')
    prefix = 'scripts/merging/trigger_contrast_localization/'
    return {prefix + name: hashlib.sha256((ROOT / prefix / name).read_bytes()).hexdigest() for name in names}


def setup_environment(spec, *, expose_gpu):
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
    if expose_gpu:
        uuid = spec['execution'].get('gpu_uuid')
        if uuid:
            os.environ['GPU_UUID'] = uuid
            os.environ['CUDA_VISIBLE_DEVICES'] = uuid


def process_identity():
    host = writer_identity({})['writer_host']
    boot, ticks = None, None
    try:
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        raw = Path('/proc/self/stat').read_text()
        ticks = int(raw[raw.rfind(')') + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        pass
    return {**host, 'pid': os.getpid(), 'boot_id': boot, 'start_ticks': ticks}


def resource(spec, science_hash, before_gpu_probe=None):
    """Require fresh captured platform evidence AND a fresh local GPU inventory."""
    from pilot24_provenance import _gpu, _host_identity, _live_gpu_xml
    evidence_ref = spec['execution']['resource_evidence']
    if isinstance(evidence_ref, str):
        path = Path(evidence_ref)
        if not path.is_absolute() or not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('resource evidence must be an ordinary absolute file')
        evidence = json.loads(path.read_bytes())
    else:
        evidence = json.loads(read_ref(evidence_ref))
    uuid = spec['execution']['gpu_uuid']
    current = datetime.now(timezone.utc)
    observed = datetime.fromisoformat(evidence['observed_at_utc'].replace('Z', '+00:00'))
    expires = datetime.fromisoformat(evidence['expires_at_utc'].replace('Z', '+00:00'))
    if (observed.tzinfo is None or expires.tzinfo is None or not observed <= current < expires
            or (expires - observed).total_seconds() > 300):
        raise ValueError('resource evidence expired or invalid')
    if (not re.fullmatch(r'GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', uuid)
            or evidence.get('run_id') != spec['run_id'] or evidence.get('science_sha256') != science_hash
            or evidence.get('gpu_uuid') != uuid or evidence.get('host') != _host_identity()
            or evidence.get('source') != 'https://gpu.orz2333.fun/'
            or evidence.get('disabled') is not False or evidence.get('sampling_valid') is not True
            or evidence.get('allocation_conflict') is not False):
        raise ValueError('resource evidence identity or platform state invalid')
    cap, occupied = evidence.get('effective_gpu_cap'), evidence.get('occupied_including_this_gpu')
    if type(cap) is not int or type(occupied) is not int or not 1 <= occupied <= min(cap, 4):
        raise ValueError('aggregate GPU allocation exceeds cap or is unknown')
    read_ref(evidence['raw_capture'])
    if os.environ.get('CUDA_VISIBLE_DEVICES') != uuid or os.environ.get('GPU_UUID') != uuid:
        raise ValueError('GPU_UUID and CUDA_VISIBLE_DEVICES must bind the same full UUID')
    if datetime.now(timezone.utc) >= expires:
        raise ValueError('resource evidence expired before live probe')
    if before_gpu_probe is not None:
        before_gpu_probe()
    live_xml = _live_gpu_xml()
    _gpu(live_xml, uuid, {os.getpid()})
    xml_root = ET.fromstring(live_xml)
    driver = xml_root.findtext('driver_version')
    cards = [card for card in xml_root.findall('gpu') if card.findtext('uuid') == uuid]
    mode = cards[0].findtext('compute_mode') if len(cards) == 1 else None
    if not driver or not driver.strip() or mode != 'Default':
        raise ValueError('live GPU driver or compute mode unavailable')
    if datetime.now(timezone.utc) >= expires:
        raise ValueError('resource evidence expired during live probe')
    return {**evidence, 'live_gpu': {'xml_sha256': hashlib.sha256(live_xml).hexdigest(),
            'driver_version': driver.strip(), 'compute_mode': mode,
            'observed_at_utc': now(), 'gpu_uuid': uuid}}


class ResourcePaused(Exception):
    pass


class ComputeDeadline(Exception):
    pass


class ResourceGuard:
    """Startup inventory plus optional externally refreshed stop observation."""
    def __init__(self, spec, science_hash):
        self.spec, self.science_hash = spec, science_hash

    def start(self, before_gpu_probe=None):
        self.check_stop()
        evidence = resource(self.spec, self.science_hash, before_gpu_probe=before_gpu_probe)
        self.check_stop()
        return evidence

    def check_stop(self):
        status_path = self.spec['execution'].get('resource_status_file')
        require_fresh = self.spec['execution'].get('require_fresh_resource_status') is True
        if not status_path:
            if require_fresh:
                raise ResourcePaused('platform observer status path is missing')
            return
        path = Path(status_path)
        try:
            if not path.is_absolute() or path.is_symlink() or not path.is_file():
                if require_fresh:
                    raise ResourcePaused('platform observer status is missing or unsafe')
                return
            value = json.loads(path.read_text())
            observed = datetime.fromisoformat(value['observed_at_utc'].replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc) - observed).total_seconds()
            valid = (0 <= age <= (180 if require_fresh else 300) and value.get('run_id') == self.spec['run_id']
                     and value.get('science_sha256') == self.science_hash
                     and value.get('gpu_uuid') == self.spec['execution']['gpu_uuid'])
            if require_fresh and (not valid or value.get('observation_valid') is not True):
                raise ResourcePaused('platform observer is stale, invalid or unavailable')
            if valid and (value.get('disabled') is True or value.get('stop_required') is True):
                raise ResourcePaused('platform reports this GPU disabled or requires this run to stop')
        except (OSError, ValueError, KeyError, TypeError):
            if require_fresh:
                raise ResourcePaused('platform observer status cannot be verified')
            return


def atomic_image(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.exists() or path.is_symlink():
        raise ValueError('image destination exists or is unsafe')
    fd, tmp = tempfile.mkstemp(prefix='.image-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        os.unlink(tmp)


def run(spec):
    science = spec['science']
    science_hash = digest({'run_id': spec['run_id'], 'science': science})
    store_kwargs = {'score_schema': 'semantic-v1'} if science.get('design') == 'semantic-v1' else {}
    store = Store(spec['run_root'], {'run_id': spec['run_id'], 'science_sha256': science_hash}, science['units'], science['budget'], **store_kwargs)
    try:
        terminal = store.event_detail('terminal', latest=True)
        if terminal:
            complete_records(store)
            return {'status': 'already_terminal', **terminal, **store.snapshot()}
        store.event('session', {'code_sha256': observed_code(), 'writer': process_identity()})
        try:
            setup_environment(spec, expose_gpu=True)
            from runtime_tcl import TCLAdapter
            adapter = TCLAdapter(spec)
            adapter.prepare_cpu()
            if canonical(adapter.units()) != canonical(science['units']):
                raise ValueError('adapter unit list differs from scientific input')
        except Exception as exc:
            store.event('error', {'phase': 'prepare_cpu', 'type': type(exc).__name__, 'message': str(exc)[:2000]})
            return {'status': 'paused_error', 'detail': str(exc), **store.snapshot()}
        for raw in store.interrupted:
            key = json.loads(raw)
            path = store.image_path(key)
            if path.exists() or path.is_symlink():
                store.register_image(key, path)
            else:
                store.fail(key, 'interrupted; exclusive local writer lock reacquired')
        previous_t0 = store.event_detail('t0')
        if previous_t0 and science.get('max_compute_seconds') is not None:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(previous_t0['time_utc'])).total_seconds()
            if elapsed < 0:
                store.event('error', {'phase': 'clock', 'message': 'clock is earlier than recorded T0'})
                return {'status': 'paused_error', 'detail': 'clock is earlier than recorded T0', **store.snapshot()}
            if elapsed >= science['max_compute_seconds']:
                store.event('terminal', {'outcome': 'inconclusive', 'reason': 'configured compute time limit reached'})
                return {'status': 'complete', 'outcome': 'inconclusive', **store.snapshot()}
        deadline = science.get('compute_deadline_utc')
        if deadline and datetime.now(timezone.utc) >= datetime.fromisoformat(deadline.replace('Z', '+00:00')):
            store.event('terminal', {'outcome': 'inconclusive', 'reason': 'configured UTC compute deadline reached'})
            return {'status': 'complete', 'outcome': 'inconclusive', **store.snapshot()}
        t0 = datetime.fromisoformat(previous_t0['time_utc']) if previous_t0 else None
        def check_deadline():
            if deadline and datetime.now(timezone.utc) >= datetime.fromisoformat(deadline.replace('Z', '+00:00')):
                raise ComputeDeadline('configured UTC compute deadline reached')
            limit = science.get('max_compute_seconds')
            if limit is not None and t0 is not None:
                elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
                if elapsed < 0:
                    raise ValueError('clock is earlier than recorded T0')
                if elapsed >= limit:
                    raise ComputeDeadline('configured compute time limit reached')
        def begin_gpu_preflight():
            nonlocal t0
            check_deadline()
            if t0 is None:
                t0_detail = {'time_utc': now(), 'science_sha256': science_hash, 'phase': 'live_gpu_preflight'}
                store.event('t0', t0_detail)
                t0 = datetime.fromisoformat(t0_detail['time_utc'])
        guard = ResourceGuard(spec, science_hash)
        try:
            evidence = guard.start(before_gpu_probe=begin_gpu_preflight)
        except ComputeDeadline as exc:
            store.event('terminal', {'outcome': 'inconclusive', 'reason': str(exc)})
            return {'status': 'complete', 'outcome': 'inconclusive', 'detail': str(exc), **store.snapshot()}
        except (ValueError, OSError, KeyError, subprocess.SubprocessError, ET.ParseError, ResourcePaused) as exc:
            try:
                check_deadline()
            except ComputeDeadline as deadline_exc:
                store.event('terminal', {'outcome': 'inconclusive', 'reason': str(deadline_exc)})
                return {'status': 'complete', 'outcome': 'inconclusive', 'detail': str(deadline_exc), **store.snapshot()}
            store.event('waiting_resource', {'error': str(exc)})
            return {'status': 'paused_resource', 'detail': str(exc), **store.snapshot()}
        store.event('resource_checked', {'evidence': evidence, 'evidence_sha256': digest(evidence)})
        try:
            check_deadline()
            adapter.start_cuda()
        except ComputeDeadline as exc:
            store.event('terminal', {'outcome': 'inconclusive', 'reason': str(exc)})
            return {'status': 'complete', 'outcome': 'inconclusive', 'detail': str(exc), **store.snapshot()}
        except Exception as exc:
            store.event('error', {'phase': 'start_cuda', 'type': type(exc).__name__, 'message': str(exc)[:2000]})
            return {'status': 'paused_error', 'detail': str(exc), **store.snapshot()}
        stage_reports = []
        for stage in ('S0', 'S1', 'M0', 'M1'):
          for unit in science['units']:
            key = unit['key']
            if unit_stage(key) != stage:
                continue
            status = store.unit_status(key)
            if status == 'complete':
                continue
            try:
                check_deadline()
                guard.check_stop()
                if status == 'pending':
                    store.reserve(key)
                    def checkpoint(counters):
                        store.checkpoint(key, counters)
                        check_deadline()
                        guard.check_stop()
                    data = adapter.generate(unit, checkpoint)
                    atomic_image(store.image_path(key), data)
                    store.register_image(key, store.image_path(key))
                guard.check_stop()
                store.event('scoring_started', {'key': key})
                scores = adapter.score(unit, store.image_path(key))
                store.finish(key, scores)
            except Exception as exc:
                status = store.unit_status(key)
                if status == 'started':
                    path = store.image_path(key)
                    if path.exists() or path.is_symlink():
                        store.register_image(key, path)
                    else:
                        store.fail(key, type(exc).__name__ + ': ' + str(exc))
                store.event('error', {'key': key, 'type': type(exc).__name__, 'message': str(exc)[:2000]})
                if isinstance(exc, (ComputeDeadline, BudgetExhausted)):
                    store.event('terminal', {'outcome': 'inconclusive', 'reason': str(exc)})
                    return {'status': 'complete', 'outcome': 'inconclusive', 'detail': str(exc), **store.snapshot()}
                return {'status': 'paused_resource' if isinstance(exc, ResourcePaused) else 'paused_error', 'detail': str(exc), **store.snapshot()}
          try:
              result = adapter.stage_gate(stage, complete_records(store))
              if not isinstance(result, dict) or result.get('stage') != stage or type(result.get('passed')) is not bool:
                  raise ValueError('invalid stage gate result')
          except Exception as exc:
              store.event('error', {'phase': 'stage_gate', 'stage': stage, 'type': type(exc).__name__, 'message': str(exc)[:2000]})
              return {'status': 'paused_error', 'detail': str(exc), **store.snapshot()}
          store.event('stage_gate', result)
          stage_reports.append(result)
          if not result['passed'] and not (science.get('design') == 'semantic-v1' and result.get('continue_run') is True):
              store.event('terminal', {'outcome': result.get('outcome'), 'stage': stage})
              return {'status': 'complete', 'outcome': result.get('outcome'), 'stage': stage, **store.snapshot()}
        if science.get('design') == 'semantic-v1':
            try:
                final = adapter.final_outcome(stage_reports)
                if not isinstance(final, dict) or final.get('outcome') not in ('exploratory_positive', 'exploratory_negative', 'inconclusive') or not isinstance(final.get('reason'), str):
                    raise ValueError('invalid semantic final outcome')
            except Exception as exc:
                store.event('error', {'phase': 'final_outcome', 'type': type(exc).__name__, 'message': str(exc)[:2000]})
                return {'status': 'paused_error', 'detail': str(exc), **store.snapshot()}
        else:
            final = {'outcome': result.get('outcome')}
        store.event('terminal', {**final, 'stage': 'M1'})
        return {'status': 'complete', **final, **store.snapshot()}
    finally:
        store.close()


def unit_stage(key):
    return ('S' if key[1] == 'source' else 'M') + ('0' if key[2] in ('clean', 'backdoor') else '1')


def complete_records(store):
    records = []
    for raw, image_sha, scores in store.complete_units():
        key = json.loads(raw)
        path = store.image_path(key)
        records.append({'key': key, 'scores': scores, 'image_path': str(path), 'image_sha256': image_sha})
    return records


def startup_smoke():
    """One CPU smoke: real entry imports and a tiny offline weight roundtrip."""
    import io
    import torch
    from diffusers import DDIMScheduler, UNet2DConditionModel
    from transformers import CLIPTextModel, CLIPTokenizer
    from runtime_tcl import TCLAdapter
    from runtime_assets import load_tcl_runtime_assets
    model = torch.nn.Linear(2, 1)
    payload = io.BytesIO()
    torch.save(model.state_dict(), payload)
    payload.seek(0)
    model.load_state_dict(torch.load(payload, map_location="cpu", weights_only=True))
    model(torch.zeros(1, 2))
    return {"status": "runnable", "cpu_only": True, "real_models_loaded": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['prepare', 'run', 'status', 'smoke'])
    parser.add_argument('--spec', required=True)
    parser.add_argument('--request')
    args = parser.parse_args()
    if args.command == 'smoke':
        print(json.dumps(startup_smoke()))
        return
    if args.command == 'prepare':
        if not args.request:
            parser.error('prepare requires --request')
        from runtime_tcl import build_spec
        value = build_spec(json.loads(Path(args.request).read_text()))
        destination = Path(args.spec)
        if not destination.is_absolute() or destination.is_symlink() or any(p.is_symlink() for p in destination.parents):
            raise ValueError('spec output must be an absolute path without symlinks')
        with destination.open('x', encoding='utf-8') as stream:
            stream.write(canonical(value) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({'status': 'prepared', 'spec': str(destination), 'run_id': value['run_id']}, ensure_ascii=False))
        return
    spec = load_spec(args.spec)
    if args.command == 'run':
        result = run(spec)
    else:
        database = Path(spec['run_root']) / 'run.md'
        if not database.is_absolute() or not database.is_file() or any(p.is_symlink() for p in (database, *database.parents)):
            raise ValueError('run has not been started or requires migration')
        data = read_markdown(database)
        identity = writer_identity({'run_id': spec['run_id'], 'science_sha256': digest({'run_id': spec['run_id'], 'science': spec['science']}), 'run_root': str(Path(spec['run_root']).resolve())})
        if data['identity'] != identity:
            raise ValueError('run identity, scientific inputs or writer host changed')
        statuses = {}
        for unit in data['units'].values():
            statuses[unit['status']] = statuses.get(unit['status'], 0) + 1
        result = {'statuses': statuses, 'attempts': len(data['attempts']), 'events': len(data['events'])}
        if data['events']:
            latest = data['events'][-1]
            result['latest_event'] = {k: latest[k] for k in ('time', 'kind', 'detail')}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
