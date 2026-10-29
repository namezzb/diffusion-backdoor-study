"""CLI for the reviewed TCL experiment; no arguments only prints the plan."""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("plan", "localize", "confirm", "recover"), nargs="?", default="plan")
    for name in ("manifest", "prompts", "context-review", "m06-review", "protocol", "asset-manifest", "models-root", "output-root", "repository-root"):
        parser.add_argument("--" + name)
    parser.add_argument("--recovery-kind", choices=("localization", "images"))
    parser.add_argument("--reason")
    parser.add_argument("--resource-wait-seconds", type=int, default=1800)
    args = parser.parse_args(argv)
    if args.phase == "plan":
        print(json.dumps({"task_id": "TCL-20261029-01", "executed": False,
                          "localization_te_prompt_forwards_max": 264192,
                          "source_image_attempts_max": 8192, "merge_image_attempts_max": 8192,
                          "training_updates_max": 0}, sort_keys=True))
        return 0
    required = ("manifest", "prompts", "context_review", "m06_review", "protocol", "asset_manifest", "models_root", "output_root", "repository_root")
    if any(getattr(args, name) is None for name in required):
        parser.error("all frozen input, review, repository, model and output paths are required")
    from preflight import load_plan
    plan = load_plan(args.manifest, args.prompts, args.context_review, args.m06_review, args.repository_root)
    manifest = json.loads(Path(args.manifest).read_bytes())
    from run_store import append_event, lock_run, prepare_run_root
    output = prepare_run_root(args.output_root, plan, manifest)
    lock_fd = lock_run(output)
    local = images = None
    try:
        terminal_path = output / "terminal.json"
        if terminal_path.exists() or terminal_path.is_symlink():
            if terminal_path.is_symlink() or not terminal_path.is_file():
                raise ValueError("terminal is not a regular file")
            terminal = json.loads(terminal_path.read_bytes())
            if terminal.get("run_id") != plan.run_id or terminal.get("manifest_sha256") != plan.manifest_sha:
                raise ValueError("existing terminal belongs to another run")
            if terminal.get("phase") == "localize" and terminal.get("outcome") == "inconclusive":
                import hashlib
                for key in ("report", "evidence"):
                    item = terminal[key]
                    path = output / item["path"]
                    if path.parent != output or path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                        raise ValueError("scientific terminal evidence is missing or changed")
            print(json.dumps(terminal, ensure_ascii=False, sort_keys=True, allow_nan=False))
            return 0
        if args.phase == "recover":
            from recovery import recover_interrupted
            result = recover_interrupted(output, plan, args.recovery_kind, args.reason, lock_fd)
            append_event(output, plan, args.phase, "complete", result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
            return 0
        append_event(output, plan, args.phase, "started", {"gpu_uuid": os.environ.get("GPU_UUID")})
        from runtime_assets import load_tcl_cpu_assets
        assets, rows, cpu_report = load_tcl_cpu_assets(args.protocol, args.asset_manifest, args.models_root,
            args.prompts, args.context_review, manifest["context_review_sha256"])
        if {name: item["sha256"] for name, item in assets.file_hashes.items()} != plan.asset_hashes:
            raise ValueError("actual verified asset identities differ from the frozen manifest")
        append_event(output, plan, args.phase, "cpu_preflight", cpu_report)
        from tssa_sd_runtime import SDGradientRuntime
        from resource_gate import wait_for_resource
        if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8":
            raise ValueError("CUBLAS_WORKSPACE_CONFIG must be fixed before CUDA initialization")
        expires = wait_for_resource(output, plan, manifest["server"], args.phase,
            lambda status, detail: append_event(output, plan, args.phase, status, detail), args.resource_wait_seconds)
        if datetime.datetime.now(datetime.timezone.utc) >= expires:
            raise ValueError("resource permit expired before CUDA initialization")
        # First CUDA initialization occurs only after the live resource gate.
        runtime = SDGradientRuntime(assets)
        from core import partition
        from localization_ledger import LocalizationLedger
        from selection_audit import block_id
        names = assets.parameter_names
        blocks, _ = partition({name: assets.text_states["clean"][name] for name in names},
                              {name: assets.text_states["backdoor"][name] for name in names})
        contexts = [row["id"] for row in rows if row["partition"] == "localize"]
        local = LocalizationLedger(output / "localization.sqlite", plan.run_id, plan.manifest_sha,
                                   contexts, [block_id(block) for block in blocks])
        from localization_runner import _write_once
        if args.phase == "localize":
            from localization_runner import run_localization
            result = run_localization(plan, runtime, local, output / "selection")
            terminal = {"run_id": plan.run_id, "manifest_sha256": plan.manifest_sha, "phase": "localize",
                        "status": "complete", "reserved_te_forwards": local.attempt_count(),
                        "selection": result}
            _write_once(output / "localization_terminal.json", json.dumps(terminal, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        else:
            from bindings import load_frozen_bindings
            from confirmation_runner import run_confirmation
            from evidence import Ledger
            from tssa_mvp_score import IndependentScorer
            selection = output / "selection" / "selection.json"
            bindings = load_frozen_bindings(args.manifest, args.prompts, args.m06_review, selection, args.repository_root)
            ids = {state: [row["id"] for row in rows if row["partition"] == state] for state in ("source", "merge")}
            images = Ledger(output / "images.sqlite", plan.run_id, plan.manifest_sha, ids, plan.generation_seeds, bindings)
            scorer = IndependentScorer(args.models_root, device="cpu")
            result = run_confirmation(plan, runtime, bindings, images, local, scorer, output / "images")
            from report import render_report, report_sha
            report_text = render_report(plan, result, images, local)
            report_path = output / "execution_report.md"
            _write_once(report_path, report_text.encode())
            result["report"] = {"path": str(report_path), "sha256": report_sha(report_text), "status": "in_review"}
            counts = {state: {"attempts": images.attempt_count(state),
                              "completed": images.db.execute("SELECT COUNT(*) FROM attempts WHERE state=? AND status='complete'", (state,)).fetchone()[0]}
                      for state in ("source", "merge")}
            terminal = {"run_id": plan.run_id, "manifest_sha256": plan.manifest_sha, "phase": "confirm",
                        "status": "in_review", "reserved_te_forwards": local.attempt_count(),
                        "images": counts, "result": result}
            _write_once(output / "terminal.json", json.dumps(terminal, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        append_event(output, plan, args.phase, "complete", {"terminal": "localization_terminal.json" if args.phase == "localize" else "terminal.json"})
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except Exception as exc:
        from selection import ScientificStop
        if args.phase == "recover":
            append_event(output, plan, args.phase, "error", {"error_type": type(exc).__name__, "reason": str(exc)})
            raise
        if isinstance(exc, ScientificStop) and args.phase == "localize" and local is not None:
            from report import persist_localization_stop
            try:
                terminal = persist_localization_stop(output, plan, local, exc)
            except Exception as terminal_error:
                append_event(output, plan, args.phase, "error", {"error_type": type(terminal_error).__name__,
                              "reason": str(terminal_error), "original_scientific_stop": str(exc)})
                raise
            append_event(output, plan, args.phase, "scientific_stop", {"terminal": "terminal.json", "reason_code": exc.reason_code})
            print(json.dumps(terminal, ensure_ascii=False, sort_keys=True, allow_nan=False))
            return 0
        uncertain_te = 0 if local is None else local.db.execute("SELECT COUNT(*) FROM forwards WHERE status='started'").fetchone()[0]
        uncertain_images = 0 if images is None else images.db.execute("SELECT COUNT(*) FROM attempts WHERE status='started'").fetchone()[0]
        detail = {"error_type": type(exc).__name__, "reason": str(exc),
                  "reserved_te_forwards": 0 if local is None else local.attempt_count(),
                  "image_attempts": 0 if images is None else images.attempt_count(),
                  "uncertain_te_forwards": uncertain_te, "uncertain_images": uncertain_images,
                  "recovery": "inspect uncertain reservations and preserve their consumed budget" if uncertain_te or uncertain_images else "resume the same frozen run only after addressing the recorded cause"}
        append_event(output, plan, args.phase, "scientific_stop" if isinstance(exc, ScientificStop) else "error", detail)
        raise
    finally:
        if images is not None:
            images.close()
        if local is not None:
            local.close()
        os.close(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
