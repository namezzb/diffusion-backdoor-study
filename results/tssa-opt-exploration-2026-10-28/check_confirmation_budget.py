#!/usr/bin/env python3
"""Local-only confirmation decision from independently audited search/dev receipts.

Never connects, launches, edits the scientific run, or opens confirmation results.
A ready decision still requires fresh GPU permission, process/lock and PNG checks.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDITOR_SHA = '2e62bbdc5b837fb4d429e8373a42c6f6d33b0019381d3a6cf63f22b523c566b7'
PLAN_SHA = '8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6'
LEDGER_SHA = 'b56a4b6659d7405cda14bc9de35da5a1fb2ef672f177f93547d37b779a9d3c1e'
PENDING = '0e39df5be0cd73d07934fe529fc310cfd651f21d955276fc55b5200615f00c66'
LEDGER_NAME = 'recovery/manual-recovery-' + PENDING + '.ledger.json'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def decide(audit, failed, *, already_opened=False, live_process_exists=False):
    """Pure decision; audit is obtained by run() using the pinned independent auditor."""
    out = {'status': 'invalid', 'GPU_start_authorized': False,
           'scientific_images_generated': 0, 'confirmation_results_opened': False,
           'budget_attempt_cap': 1440, 'budget_generation_branch_NFE_cap': 72000,
           'archived_failed_attempts': 1, 'archived_failed_NFE_upper_bound': 50}
    require(audit.get('status') != 'invalid' and audit.get('errors') == [], 'Independent audit failed')
    require(audit.get('plan_sha256') == PLAN_SHA, 'Wrong frozen plan')
    require(not already_opened and audit.get('confirm_results_opened') is False, 'Confirmation already opened; do not start again')
    require(failed.get('failed_attempts') == 1 and failed.get('failed_branch_NFE_upper_bound') == 50
            and failed.get('global_attempt_cap_conservative') == 1440
            and failed.get('global_branch_NFE_cap') == 72000, 'Recovery budget provenance changed')
    require(audit.get('locked_operation_ids_not_read') == [], 'Unaccounted operation files')
    completed = audit['completed_receipts_verified']
    started = audit['started_receipts_verified']
    require(type(completed) is int and type(started) is int and completed >= 0 and started >= 0, 'Invalid receipt counts')
    require(audit['attempt_files_present'] == completed + started, 'Receipt counts disagree')
    last_nfe = sum(audit['last_recorded_NFE_per_execution'].values())
    require(last_nfe == completed * 50, 'Recorded completed work differs from expected NFE')
    require(completed + started + 1 <= 1440 and last_nfe + (started + 1) * 50 <= 72000, 'Observed work already exceeds budget')
    out.update(completed_images=completed, current_started=started,
               observed_attempts_including_failure=completed + started + 1,
               known_NFE_upper_bound=last_nfe + (started + 1) * 50)
    stages = audit.get('stages', {})
    selected = None
    for name in ('search', 'dev'):
        stage = stages.get(name)
        if not stage or stage.get('status') != 'complete' or not stage.get('selection_verified'):
            out.update(status='wait_for_' + name + '_completion', reason='No complete independently verified stage selection')
            return out
        selected = stage['selection']['selected']
        require(isinstance(selected, list) and len(set(selected)) == len(selected), 'Invalid selected candidate list')
        if not selected:
            require(started == 0, 'Empty selection but unfinished work exists')
            out.update(status='stop_no_qualified_candidate', stopped_after=name,
                       reason=stage['selection']['reason'])
            return out
    search_selected = stages['search']['selection']['selected']
    require(1 <= len(search_selected) <= 3 and len(selected) == 1 and selected[0] in search_selected,
            'Invalid search/dev candidate lineage')
    expected = 624 + (2 + len(search_selected)) * 48
    require(stages['search']['completed_images'] == 624
            and stages['dev']['completed_images'] == expected - 624
            and completed == expected and started == 0, 'Search/dev receipt set is incomplete or has extra attempts')
    attempts = completed + 576 + 1
    nfe = last_nfe + 576 * 50 + 50
    out.update(winner=selected[0], winner_coefficients=stages['dev']['selection']['coefficients'][selected[0]],
               selected_search_count=len(search_selected), confirm_images=576,
               final_unique_images=completed + 576, final_attempts_with_failure=attempts,
               final_generation_branch_NFE_upper_bound=nfe,
               remaining_live_checks=['current process has exited and run lock can be acquired',
                                      'all committed PNG hashes and current frozen inputs match',
                                      'fresh portal permission, quota, UUID and researcher-process checks',
                                      'new one-shot confirmation claim; preserve old claims and failed-attempt ledger'])
    if attempts > 1440 or nfe > 72000:
        out.update(status='budget_exception_required_before_confirmation',
                   excess_attempts=max(0, attempts - 1440), excess_NFE=max(0, nfe - 72000),
                   action='Stop before confirmation; never drop candidates, shorten confirm or hide failed work')
    elif live_process_exists:
        out.update(status='wait_for_current_process_exit', reason='Do not overlap, stop or restart the current productive process')
    else:
        out.update(status='snapshot_ready_for_live_start_checks', reason='Scientific stage and conservative total budget pass; not a GPU launch authorization')
    return out


def run(report):
    path = Path(report)
    raw = json.loads(path.read_text())
    require(raw.get('status') == 'observed' and raw.get('returncode') == 0, 'Observation was not successful')
    result = raw['result']
    require(result.get('errors') == [] and result.get('recovery', {}).get('status') == 'provenance_verified', 'Recovery observation invalid')
    require(result['recovery']['ledger_sha256'] == LEDGER_SHA, 'Wrong recovery ledger')
    require(not result.get('run', {}).get('confirm_unlocked'), 'Confirmation already unlocked')
    require(not any(k.startswith('run/confirm_') for k in result['files']), 'Confirmation artifacts exist')
    require(not result['run'].get('locked_or_unknown_operation_files_not_read'), 'Observer withheld unknown operations')
    auditor_path = HERE / 'audit_image_search_results.py'
    require(sha(auditor_path) == AUDITOR_SHA, 'Independent auditor changed')
    spec = importlib.util.spec_from_file_location('confirmation_independent_auditor', auditor_path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    auditor = module.Auditor(path)
    audit = auditor.run()
    require(audit['status'] != 'invalid' and audit['errors'] == [], 'Independent audit failed: ' + str(audit['errors']))
    ledger = auditor.reader.read(LEDGER_NAME)
    require(sha(auditor.reader.path(LEDGER_NAME)) == LEDGER_SHA, 'Archived failure ledger bytes changed')
    require(ledger.get('plan_sha256') == PLAN_SHA and ledger.get('pending_task_id') == PENDING, 'Wrong failure lineage')
    require(result['recovery_resource_accounting'].get('complete_global_accounting') is True, 'Incomplete global accounting')
    decision = decide(audit, ledger['budget'], live_process_exists=result.get('launch_process_now', {}).get('exists') is True)
    decision.update(at=dt.datetime.now(dt.timezone.utc).isoformat(), read_only=True,
                    observation_path=str(path.resolve()), observation_sha256=sha(path),
                    auditor_sha256=AUDITOR_SHA, archived_failure_ledger_sha256=LEDGER_SHA,
                    plan_sha256=PLAN_SHA, confirm_opened_by_auditor=audit['confirm_results_opened'],
                    independent_audit_status=audit['status'])
    return decision


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path); parser.add_argument('--output', required=True, type=Path)
    args=parser.parse_args()
    try:
        decision=run(args.report)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        decision={'status':'invalid','error':str(exc),'GPU_start_authorized':False}
    with args.output.open('x') as stream:
        json.dump(decision,stream,ensure_ascii=False,indent=2,allow_nan=False); stream.write('\n')
    print(json.dumps(decision,ensure_ascii=False))
    return 2 if decision['status']=='invalid' else 0

if __name__=='__main__':
    raise SystemExit(main())
