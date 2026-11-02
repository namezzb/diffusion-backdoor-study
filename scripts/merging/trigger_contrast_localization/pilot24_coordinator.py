"""Durable pilot24 coordination, complete-stage verification and accounting.

Scientific release records never substitute for GPU permits or source isolation.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import itertools
import json
import re
from pathlib import Path

from pilot24_inputs import RUN
from pilot24_worker_ledger import is_sha

STAGES = ("S0", "S1", "M0", "M1")


def validate_partition(stages, assignments, imported):
    """Reject overlapping assignments and enforce stage retry-token totals.

    Imported keys must already have independent provenance verification. This
    function does not establish that verification and cannot authorize a run.
    """
    expected = set(itertools.chain.from_iterable(stages.values()))
    if set(stages) != set(STAGES) or len(expected) != 6144:
        raise ValueError("unexpected fixed input set")
    imported_keys = [tuple(key) for key in imported]
    if len(set(imported_keys)) != len(imported_keys) or not set(imported_keys) <= expected:
        raise ValueError("duplicate or unexpected imported key")
    assigned = []
    quotas = Counter()
    worker_bindings = {}
    manifests = set()
    stage_gates, prompt_bindings, mask_bindings = {}, {}, {}
    for item in assignments:
        stage, worker = item.get("stage"), item.get("worker_id")
        tokens = item.get("retry_tokens")
        if (item.get("run_id") != RUN or stage not in STAGES or not isinstance(worker, str) or re.fullmatch(r"[A-Za-z0-9_-]+", worker) is None
                or type(tokens) is not int or tokens < 0 or not is_sha(item.get("manifest_sha256"))
                or not is_sha(item.get("gate_sha256"))):
            raise ValueError("invalid assignment identity or retry tokens")
        binding = (item.get("server"), item.get("gpu_uuid"))
        if (not all(isinstance(x, str) and x for x in binding)
                or re.fullmatch(r"GPU-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", binding[1]) is None):
            raise ValueError("server and full GPU UUID are required")
        if worker in worker_bindings and worker_bindings[worker] != binding:
            raise ValueError("worker changed hardware identity")
        worker_bindings[worker] = binding
        manifests.add(item["manifest_sha256"])
        if stage in stage_gates and stage_gates[stage] != item["gate_sha256"]:
            raise ValueError("assignments for the same stage disagree on the gate")
        stage_gates[stage] = item["gate_sha256"]
        allowed = set(stages[stage])
        units = item.get("units")
        if not isinstance(units, list) or not units:
            raise ValueError("assignment requires nonempty units")
        for unit in units:
            if not isinstance(unit, dict):
                raise ValueError("assignment unit must be a mapping")
            key = tuple(unit.get("key", ()))
            if key not in allowed or not is_sha(unit.get("input_sha")) or not is_sha(unit.get("mask_sha")):
                raise ValueError("assignment includes unbound or wrong-stage key")
            prompt_key, version = (key[1], key[3], key[4]), key[2]
            if (prompt_key in prompt_bindings and prompt_bindings[prompt_key] != unit["input_sha"]
                    or version in mask_bindings and mask_bindings[version] != unit["mask_sha"]):
                raise ValueError("input or mask binding is inconsistent across units")
            prompt_bindings[prompt_key], mask_bindings[version] = unit["input_sha"], unit["mask_sha"]
            assigned.append(key)
        quotas["source" if stage.startswith("S") else "merge"] += tokens
    if (len(manifests) != 1 or len({b[1].lower() for b in worker_bindings.values()}) != len(worker_bindings)
            or len(worker_bindings) > 4):
        raise ValueError("manifest or one-to-one worker/GPU identity is invalid, or more than four GPUs")
    if len(set(assigned)) != len(assigned) or set(assigned) & set(imported_keys):
        raise ValueError("overlapping assignments or imported keys")
    if set(assigned) | set(imported_keys) != expected:
        raise ValueError("incomplete plan")
    if quotas["source"] > 64 or quotas["merge"] > 64:
        raise ValueError("retry tokens exceed state budget")
    return {"unique_keys": len(expected), "imported": len(imported_keys), "assigned": len(assigned),
            "retry_tokens": dict(quotas), "worker_bindings": worker_bindings}


def verify_scored_png(path, expected_sha):
    from PIL import Image
    path = Path(path)
    if not is_sha(expected_sha) or path.is_symlink() or not path.is_file():
        raise ValueError("missing or ambiguous image")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
        raise ValueError("image hash mismatch")
    with Image.open(path) as image:
        if image.format != "PNG" or image.size != (512, 512):
            raise ValueError("invalid PNG geometry")
        image.verify()
    return True


def offline_stage_report(stage, stages, expected_bindings, records, labels, model_bundle_sha, scorer_sha):
    """Validate a complete stage table and calculate its statistics offline.

    The caller must authenticate the frozen bindings and source receipts. This
    function does not create a stage-release permit or prove writer isolation.
    """
    from pilot24_statistics import report
    if stage not in STAGES or not is_sha(model_bundle_sha) or not is_sha(scorer_sha):
        raise ValueError("unknown stage or unbound model/scorer")
    state = "source" if stage.startswith("S") else "merge"
    phase_keys = set(stages[stage])
    if stage.endswith("1"):
        phase_keys |= set(stages["S0" if state == "source" else "M0"])
    if set(expected_bindings) != phase_keys:
        raise ValueError("expected bindings must cover exactly the stage report")
    seen, seen_paths, rows, evidence = set(), set(), [], []
    for record in records:
        key = tuple(record.get("key", ()))
        if key not in phase_keys or key in seen:
            raise ValueError("unexpected or duplicate stage record")
        expected = expected_bindings[key]
        if (set(expected) != {"input_sha", "mask_sha"}
                or not all(is_sha(v) for v in expected.values())
                or any(record.get(name) != value for name, value in expected.items())
                or record.get("model_bundle_sha256") != model_bundle_sha
                or record.get("scorer_sha256") != scorer_sha):
            raise ValueError("record differs from frozen input, mask, model or scorer")
        path = Path(record.get("image_path", ""))
        if str(path) in seen_paths:
            raise ValueError("one image path cannot represent multiple units")
        verify_scored_png(path, record.get("image_sha"))
        seen.add(key)
        seen_paths.add(str(path))
        score = record.get("scores")
        if not isinstance(score, dict) or set(score) != {"vit_class", "clip_score"}:
            raise ValueError("invalid per-image score")
        rows.append({"version": key[2], "class": key[3], "context_id": key[4], "seed": key[5], **score})
        evidence.append({"key": list(key), "input_sha": record["input_sha"], "mask_sha": record["mask_sha"],
                         "image_sha": record["image_sha"], "image_path": str(path), "scores": score})
    if seen != phase_keys:
        raise ValueError("stage report requires every scored image")
    result = report(state, rows, labels, complete_recovery=stage.endswith("1"))
    passed = result["baseline"]["passed"] if stage.endswith("0") else result["decision"]["passed"]
    evidence.sort(key=lambda x: x["key"])
    evidence_sha = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    value = {"stage": stage, "passed": passed, "records": len(seen), "evidence_sha256": evidence_sha,
             "model_bundle_sha256": model_bundle_sha, "scorer_sha256": scorer_sha, "result": result}
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**value, "report_sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "authorization": "none_offline_report_only"}


# The state machine consumes an authenticated execution configuration; it never
# turns a design candidate, a platform screenshot, or a receipt into permission.
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import os
import tempfile
from pilot24_deadline import deadline_state
from pilot24_worker_ledger import canonical, digest


def write_json(path, value, *, exclusive=False):
    """Durably publish JSON; exclusive publication never replaces prior evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("symlink output is not permitted")
    raw = (canonical(value) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=".pilot24-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular JSON file required")
    return json.loads(path.read_text())


def stage_contract(manifest_sha, stage):
    return digest({"run_id": RUN, "manifest_sha256": manifest_sha, "stage": stage})


class Coordinator:
    """A durable, single-owner global gate; no GPU or network operations.

    config contains authenticated stages, bindings, imported records, labels and
    assignment templates. The public CLI must verify its frozen-file hash and
    external implementation approval before opening this object.
    """
    def __init__(self, directory, config):
        self.root = Path(directory)
        if str(self.root.resolve()) != config.get('coordinator_root'):
            raise ValueError('coordinator root differs from reviewed configuration')
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("coordinator root must not be a symlink")
        self.fd = os.open(self.root / '.coordinator.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.config = json.loads(canonical(config))
            if config.get('run_id') != RUN or not all(is_sha(config.get(k)) for k in ('manifest_sha256', 'model_bundle_sha256', 'scorer_sha256')):
                raise ValueError('authenticated frozen configuration required')
            self.stages = {s: [tuple(k) for k in config['stages'][s]] for s in STAGES}
            self.bindings = {tuple(u['key']): {'input_sha': u['input_sha'], 'mask_sha': u['mask_sha']} for u in config['units']}
            expected = set(itertools.chain.from_iterable(self.stages.values()))
            if len(config['units']) != 6144 or set(self.bindings) != expected:
                raise ValueError('all unique frozen unit bindings required')
            self.templates = config['assignments']
            ids = [a.get('assignment_id') for a in self.templates]
            if any(not isinstance(i, str) or re.fullmatch(r'[A-Za-z0-9_-]+', i) is None for i in ids) or len(set(ids)) != len(ids):
                raise ValueError('safe unique assignment IDs required')
            imported = config['imports']
            validate_partition(self.stages, self.templates, [r['key'] for r in imported])
            for item in self.templates:
                if item['manifest_sha256'] != config['manifest_sha256'] or item['gate_sha256'] != stage_contract(config['manifest_sha256'], item['stage']):
                    raise ValueError('template must bind the fixed stage contract')
                if any({k: u[k] for k in ('input_sha', 'mask_sha')} != self.bindings[tuple(u['key'])] for u in item['units']):
                    raise ValueError('template differs from frozen bindings')
            self._check_records(imported, expected)
            identity = self.root / 'configuration.json'
            if identity.exists():
                if read_json(identity) != self.config:
                    raise ValueError('coordinator configuration cannot change')
            else:
                write_json(identity, self.config, exclusive=True)
            state_path = self.root / 'state.json'
            if not state_path.exists():
                write_json(state_path, {'config_sha256': digest(self.config), 't0': None, 'last_observed_utc': None,
                    'stage': 'S0', 'released': {}, 'receipts': {}, 'reports': {}, 'terminal': None}, exclusive=True)
            self.state = read_json(state_path)
            if self.state['config_sha256'] != digest(self.config):
                raise ValueError('state belongs to another configuration')
        except Exception:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def save(self):
        write_json(self.root / 'state.json', self.state)

    def _check_records(self, records, allowed):
        seen = set()
        for row in records:
            key = tuple(row.get('key', ()))
            if key not in allowed or key in seen:
                raise ValueError('duplicate or unauthorized completed key')
            seen.add(key)
            if any(row.get(k) != v for k, v in self.bindings[key].items()) or any(row.get(k) != self.config[k] for k in ('model_bundle_sha256', 'scorer_sha256')):
                raise ValueError('result provenance mismatch')
            verify_scored_png(row.get('image_path', ''), row.get('image_sha'))
            score = row.get('scores', {})
            import math
            if (set(score) != {'vit_class', 'clip_score'} or type(score['vit_class']) is not int
                    or not 0 <= score['vit_class'] < 1000 or type(score['clip_score']) not in (int, float)
                    or not math.isfinite(score['clip_score']) or not 0 <= score['clip_score'] <= 100):
                raise ValueError('invalid result scores')

    def bind_t0(self, payload, file_sha):
        from pilot24_deadline import _utc
        if (set(payload) != {'run_id', 'manifest_sha256', 't0_utc'} or payload['run_id'] != RUN
                or payload['manifest_sha256'] != self.config['manifest_sha256'] or not is_sha(file_sha)):
            raise ValueError('invalid shared T0')
        _utc(payload['t0_utc'])
        bound = {**payload, 'file_sha256': file_sha}
        if self.state['t0'] is not None and self.state['t0'] != bound:
            raise ValueError('T0 cannot be reset')
        self.state['t0'] = bound
        self.save()

    def release(self, stage):
        if self.state['terminal'] or stage != self.state['stage']:
            raise ValueError('stage is not globally released')
        if stage in self.state['released']:
            return self.state['released'][stage]
        preceding = None if stage == 'S0' else STAGES[STAGES.index(stage) - 1]
        if preceding and not self.state['reports'].get(preceding, {}).get('passed'):
            raise ValueError('complete passing predecessor report required')
        gate = {'run_id': RUN, 'manifest_sha256': self.config['manifest_sha256'], 'stage': stage,
                'passed': True, 'config_sha256': digest(self.config),
                'predecessor_report_sha256': self.state['reports'][preceding]['report_sha256'] if preceding else None,
                'authorization': 'scientific_stage_only_not_gpu_permission'}
        gate_path = self.root / 'gates' / (stage + '.json')
        if gate_path.exists():
            if read_json(gate_path) != gate:
                raise ValueError('existing gate differs')
            gate_sha = hashlib.sha256(gate_path.read_bytes()).hexdigest()
        else:
            gate_sha = write_json(gate_path, gate, exclusive=True)
        released = []
        for template in self.templates:
            if template['stage'] != stage:
                continue
            assignment = {**template, 'gate_sha256': gate_sha}
            path = self.root / 'assignments' / (template['assignment_id'] + '.json')
            if path.exists():
                if read_json(path) != assignment:
                    raise ValueError('existing assignment differs')
            else:
                write_json(path, assignment, exclusive=True)
            released.append({'assignment_id': template['assignment_id'], 'path': str(path.resolve()),
                             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        result = {'gate_path': str(gate_path.resolve()), 'gate_sha256': gate_sha, 'assignments': released}
        self.state['released'][stage] = result
        self.save()
        return result

    def ingest(self, receipt, *, final_audit=False):
        if self.state['terminal'] and not final_audit:
            raise ValueError('terminal run cannot accept more results')
        aid, stage = receipt.get('assignment_id'), receipt.get('stage')
        released = self.state['released'].get(stage, {})
        matches = [a for a in released.get('assignments', []) if a['assignment_id'] == aid]
        if len(matches) != 1 or self.state['t0'] is None:
            raise ValueError('receipt has no released assignment or T0')
        assignment = read_json(matches[0]['path'])
        if (receipt.get('run_id') != RUN or receipt.get('manifest_sha256') != self.config['manifest_sha256']
                or receipt.get('assignment_sha256') != matches[0]['sha256']
                or receipt.get('worker_id') != assignment['worker_id']
                or receipt.get('t0_sha256') != self.state['t0']['file_sha256']
                or receipt.get('status') not in ('running', 'complete', 'blocked', 'deadline')):
            raise ValueError('worker receipt identity mismatch')
        allowed = {tuple(u['key']) for u in assignment['units']}
        records, attempts = receipt.get('records'), receipt.get('attempts')
        if not isinstance(records, list) or not isinstance(attempts, list):
            raise ValueError('explicit records and attempts required')
        self._check_records(records, allowed)
        counted = {}
        for attempt in attempts:
            key, number = tuple(attempt.get('key', ())), attempt.get('number')
            if key not in allowed or type(number) is not int or number not in (1, 2) or (key, number) in counted:
                raise ValueError('invalid or duplicate charged attempt')
            if attempt.get('status') not in ('started', 'image_persisted', 'complete', 'interrupted'):
                raise ValueError('invalid attempt state')
            resource = attempt.get('resource')
            if not isinstance(resource, dict) or any(type(v) is not int or v < 0 for v in resource.values()):
                raise ValueError('invalid resource counters')
            counted[key, number] = attempt
        retries = sum(number == 2 for _, number in counted)
        if retries > assignment['retry_tokens'] or any(n == 2 and (k, 1) not in counted for k, n in counted):
            raise ValueError('retry budget or attempt lineage invalid')
        for record in records:
            key = tuple(record['key'])
            entries = [a for (k, _), a in counted.items() if k == key]
            if not entries or max(entries, key=lambda a: a['number'])['status'] != 'complete':
                raise ValueError('completed image lacks its charged completed attempt')
        if receipt['status'] == 'complete' and {tuple(r['key']) for r in records} != allowed:
            raise ValueError('incomplete worker cannot claim completion')
        old = self.state['receipts'].get(aid)
        if old:
            previous = read_json(self.root / old['path'])
            new_records = {tuple(r['key']): r for r in records}
            if any(new_records.get(tuple(r['key'])) != r for r in previous['records']):
                raise ValueError('completed result cannot change or disappear')
            for item in previous['attempts']:
                current = counted.get((tuple(item['key']), item['number']))
                if current is None or any(current['resource'].get(k, -1) < v for k, v in item['resource'].items()):
                    raise ValueError('charged attempts or resource counts cannot disappear')
                if item['status'] in ('complete', 'interrupted') and current['status'] != item['status']:
                    raise ValueError('terminal attempt cannot change')
        path = Path('receipts') / (aid + '-' + digest(receipt) + '.json')
        if not (self.root / path).exists():
            write_json(self.root / path, receipt, exclusive=True)
        self.state['receipts'][aid] = {'path': str(path), 'sha256': digest(receipt)}
        self.save()

    def records(self):
        values = list(self.config['imports'])
        for item in self.state['receipts'].values():
            payload = read_json(self.root / item['path'])
            if digest(payload) != item['sha256']:
                raise ValueError('stored receipt changed')
            values.extend(payload['records'])
        return values

    def advance(self):
        if self.state['terminal']:
            return self.state['terminal']
        stage = self.state['stage']
        phase = set(self.stages[stage])
        rows = self.records()
        if {tuple(r['key']) for r in rows if tuple(r['key']) in phase} != phase:
            return {'status': 'waiting', 'stage': stage}
        keys = phase | (set(self.stages[stage[0] + '0']) if stage.endswith('1') else set())
        report = offline_stage_report(stage, self.stages, {k: self.bindings[k] for k in keys},
                    [r for r in rows if tuple(r['key']) in keys], self.config['labels']['source' if stage[0] == 'S' else 'merge'],
                    self.config['model_bundle_sha256'], self.config['scorer_sha256'])
        report_path = self.root / 'reports' / (stage + '.json')
        if report_path.exists():
            if read_json(report_path) != report:
                raise ValueError('frozen stage report changed')
        else:
            write_json(report_path, report, exclusive=True)
        self.state['reports'][stage] = report
        if not report['passed']:
            decision = report['result'].get('decision', {})
            inconclusive = stage.endswith('0') or not decision.get('eligible_amplitude')
            self.finish('inconclusive' if inconclusive else 'negative', 'scientific_gate_' + stage,
                        skipped=list(STAGES[STAGES.index(stage) + 1:]))
        elif stage == 'M1':
            self.finish('positive', 'complete_practical_validation')
        else:
            self.state['stage'] = STAGES[STAGES.index(stage) + 1]
            self.save()
        return report

    def finish(self, outcome, reason, *, skipped=None):
        if self.state['terminal']:
            return self.state['terminal']
        if outcome not in ('positive', 'negative', 'inconclusive') or not reason:
            raise ValueError('explicit terminal outcome and reason required')
        receipts = [read_json(self.root / r['path']) for r in self.state['receipts'].values()]
        terminal = {'run_id': RUN, 'manifest_sha256': self.config['manifest_sha256'],
                    'outcome': outcome, 'reason': reason, 'status': 'in_review',
                    'unique_complete': len(self.records()), 'imported': len(self.config['imports']),
                    'charged_attempts': sum(len(r['attempts']) for r in receipts),
                    'required_unique_max': 6144, 'skipped_stages': skipped or [],
                    'reports': {s: r['report_sha256'] for s, r in self.state['reports'].items()},
                    't0': self.state['t0'], 'worker_exit_verified': False,
                    'limitations': ['Report is not independent acceptance; worker exit evidence must be collected.']}
        write_json(self.root / 'terminal.json', terminal)
        self.state['terminal'] = terminal
        self.save()
        return terminal

    def capacity(self, now_utc=None):
        """Conservative measured aggregate rate including CPU/load/idle time."""
        if self.state['t0'] is None:
            return {'status': 'not_started'}
        now_utc = now_utc or datetime.now(timezone.utc).isoformat()
        timing = deadline_state(self.state['t0']['t0_utc'], now_utc)
        by_worker, classes, attempts = Counter(), {}, 0
        for saved in self.state['receipts'].values():
            row = read_json(self.root / saved['path'])
            attempts += len(row['attempts'])
            if row['attempts']:
                by_worker[row['worker_id']] += len(row['records'])
                classes.setdefault(row['worker_id'], set()).update(r['key'][3] for r in row['records'])
        finished = sum(by_worker.values())
        remaining = max(0, 6272 - len(self.config['imports']) - attempts)
        elapsed = timing['elapsed_seconds']
        eligible = (finished >= 64 and bool(by_worker) and all(n >= 16 for n in by_worker.values())
                    and all(v == {'trigger', 'dog', 'cat', 'other'} for v in classes.values()))
        rate = finished / elapsed if elapsed > 0 else 0
        eta = remaining / rate if rate > 0 else None
        sufficient = eligible and eta is not None and eta <= max(0, 22 * 3600 - elapsed)
        result = {'observed_at_utc': now_utc, 'by_worker': dict(by_worker), 'finished_new': finished,
                  'class_coverage': {w: sorted(v) for w, v in classes.items()}, 'sample_count_eligible': eligible,
                  'remaining_attempts_upper_bound': remaining, 'aggregate_per_hour': rate * 3600,
                  'estimated_remaining_seconds': eta, 'capacity_sufficient': sufficient,
                  'generation_target_hours': 18, 'generation_cutoff_hours': 22,
                  'feasibility_due': timing['feasibility_due']}
        write_json(self.root / 'throughput.json', result)
        if timing['feasibility_due'] and not sufficient and not self.state['terminal']:
            self.finish('inconclusive', 'deadline_infeasible')
        return result

    def refresh_terminal_counts(self):
        if self.state['terminal'] is None:
            raise ValueError('terminal accounting requires a terminal result')
        self.state['terminal']['unique_complete'] = len(self.records())
        self.state['terminal']['charged_attempts'] = sum(len(read_json(self.root / r['path'])['attempts'])
                                                          for r in self.state['receipts'].values())
        write_json(self.root / 'terminal.json', self.state['terminal'])
        self.save()

    def tick(self, now_utc=None):
        now_utc = now_utc or datetime.now(timezone.utc).isoformat()
        if self.state['t0'] is None:
            return {'status': 'not_started'}
        timing = deadline_state(self.state['t0']['t0_utc'], now_utc,
                                previous_observed_utc=self.state['last_observed_utc'])
        self.state['last_observed_utc'] = now_utc
        self.save()
        if not timing['compute_permitted'] and not self.state['terminal']:
            self.finish('inconclusive', 'deadline_incomplete')
        return timing


def verify_release(root, config, assignment, gate_path):
    """Read-only verification of a release against reviewed config and full data.

    Does not take the coordinator lock: workers are intentionally checked while
    its persistent parent holds that lock. Atomic state/receipt publication and
    immutable completed records make the authenticated snapshot sufficient.
    """
    root = Path(root).resolve()
    if str(root) != config.get('coordinator_root'):
        raise ValueError('coordinator root must be independently frozen')
    stage = assignment['stage']
    if stage not in STAGES or Path(gate_path).resolve() != root / 'gates' / (stage + '.json'):
        raise ValueError('release outside fixed coordinator namespace')
    state = read_json(root / 'state.json')
    gate = read_json(gate_path)
    if state['config_sha256'] != digest(config) or gate.get('config_sha256') != digest(config):
        raise ValueError('release configuration mismatch')
    gate_sha = hashlib.sha256(Path(gate_path).read_bytes()).hexdigest()
    released = state['released'].get(stage, {})
    items = [a for a in released.get('assignments', []) if a['assignment_id'] == assignment['assignment_id']]
    if (len(items) != 1 or released.get('gate_sha256') != gate_sha or not gate.get('passed')
            or assignment['gate_sha256'] != gate_sha or read_json(items[0]['path']) != assignment
            or hashlib.sha256(Path(items[0]['path']).read_bytes()).hexdigest() != items[0]['sha256']):
        raise ValueError('assignment has no authentic coordinator release')
    records = list(config['imports'])
    for stored in state['receipts'].values():
        receipt = read_json(root / stored['path'])
        if digest(receipt) != stored['sha256']:
            raise ValueError('receipt integrity failure')
        records.extend(receipt['records'])
    stages = {s: [tuple(k) for k in config['stages'][s]] for s in STAGES}
    validate_partition(stages, config['assignments'], [r['key'] for r in config['imports']])
    bindings = {tuple(u['key']): {k: u[k] for k in ('input_sha', 'mask_sha')} for u in config['units']}
    preceding_hash = None
    for previous in STAGES[:STAGES.index(stage)]:
        keys = set(stages[previous])
        if previous.endswith('1'):
            keys |= set(stages[previous[0] + '0'])
        calculated = offline_stage_report(previous, stages, {k: bindings[k] for k in keys},
            [r for r in records if tuple(r['key']) in keys], config['labels']['source' if previous[0] == 'S' else 'merge'],
            config['model_bundle_sha256'], config['scorer_sha256'])
        if (not calculated['passed'] or read_json(root / 'reports' / (previous + '.json')) != calculated
                or state['reports'].get(previous) != calculated):
            raise ValueError('predecessor scientific report was not verified')
        preceding_hash = calculated['report_sha256']
    if gate.get('predecessor_report_sha256') != preceding_hash:
        raise ValueError('gate predecessor hash mismatch')
    return gate
