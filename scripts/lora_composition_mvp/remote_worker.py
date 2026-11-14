#!/usr/bin/env python3
"""Remote resumable worker wrapper for MVP-v1 (waits without CUDA on exit 75, resumes from checkpoint)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lora_composition_mvp.io_utils import event, md_read


def _gpu_clear(gpu_uuid: str) -> bool:
    try:
        mode = subprocess.check_output(
            ["nvidia-smi", "-i", gpu_uuid, "--query-gpu=compute_mode", "--format=csv,noheader"],
            text=True,
            timeout=10,
        ).strip()
        apps = subprocess.check_output(
            ["nvidia-smi", "-i", gpu_uuid, "--query-compute-apps=pid", "--format=csv,noheader"],
            text=True,
            timeout=10,
        ).strip()
        return mode == "Default" and not apps
    except (OSError, subprocess.SubprocessError):
        return False


def _permission_ready(perm_path: Path, gpu_uuid: str) -> bool:
    if not perm_path.is_file():
        return True
    perm = md_read(perm_path)
    status = perm.get("status", "active").strip().lower()
    if status != "active":
        return False
    allowed = perm.get(f"card_{gpu_uuid}_allowed", perm.get("allowed", "true")).strip().lower()
    if allowed in {"false", "0", "no"}:
        return False
    exp_raw = perm.get("expires_at", "").strip()
    if exp_raw and exp_raw.lower() not in {"none", "null"}:
        try:
            if time.time() >= float(exp_raw):
                return False
        except ValueError:
            return False
    return True


def wait_until_resumable(run_dir: Path, state_dir: Path, gpu_uuid: str, poll_s: float = 15.0) -> bool:
    perm_path = state_dir / "permission.md"
    stop_path = run_dir / "STOP"
    while not stop_path.exists():
        if _permission_ready(perm_path, gpu_uuid) and _gpu_clear(gpu_uuid):
            return True
        time.sleep(poll_s)
    return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Resumable GPU worker loop for MVP-v1.")
    p.add_argument("--config", required=True)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--state-dir", default=None)
    p.add_argument("--gpu-uuid", required=True)
    p.add_argument("--device", default="cuda")
    p.add_argument("--dtype", default="float16")
    p.add_argument("--command", default="run-all")
    p.add_argument("--max-steps", type=int, default=None)
    p.add_argument("--scenarios", nargs="+", default=None)
    p.add_argument("--arms", nargs="+", default=None)
    args = p.parse_args(argv)

    run_dir = Path(args.run_dir)
    state_dir = Path(args.state_dir) if args.state_dir else run_dir
    cli_path = Path(__file__).resolve().with_name("cli.py")

    cmd = [
        sys.executable,
        "-u",
        str(cli_path),
        args.command,
        "--config",
        args.config,
        "--run-dir",
        str(run_dir),
        "--state-dir",
        str(state_dir),
        "--device",
        args.device,
        "--dtype",
        args.dtype,
        "--gpu-uuid",
        args.gpu_uuid,
    ]
    if args.max_steps is not None:
        cmd.extend(["--max-steps", str(args.max_steps)])
    if args.scenarios:
        cmd.extend(["--scenarios", *args.scenarios])
    if args.arms:
        cmd.extend(["--arms", *args.arms])

    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = args.gpu_uuid

    attempt = 0
    while True:
        if (run_dir / "STOP").exists():
            return 130
        attempt += 1
        event(run_dir, "worker_launch", attempt=attempt, pid=os.getpid(), gpu_uuid=args.gpu_uuid)
        proc = subprocess.run(cmd, env=env)
        if proc.returncode == 75:
            event(run_dir, "worker_paused_waiting", attempt=attempt, returncode=75)
            if not wait_until_resumable(run_dir, state_dir, args.gpu_uuid):
                return 130
            event(run_dir, "worker_resuming", attempt=attempt + 1)
            continue
        event(run_dir, "worker_exit", attempt=attempt, returncode=proc.returncode)
        return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
