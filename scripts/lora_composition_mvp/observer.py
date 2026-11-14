#!/usr/bin/env python3
"""Live platform permission heartbeat observer for MVP-v1 (runs locally, writes remote permission.md)."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import email.parser
import io
import ipaddress
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


class ObservationUnavailable(RuntimeError):
    """Temporary network/platform fetch failure; existing expiry stays unchanged."""


def _ssh_args(target: str = "school104") -> list[str]:
    return [str(ROOT / "server" / "start_school.sh"), target]


def remote_exec(target: str, command: str, timeout: int = 70, payload: bytes | None = None) -> str:
    proc = subprocess.Popen(
        _ssh_args(target) + [command],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        out, err = proc.communicate(timeout=5)
        raise RuntimeError(
            "Remote command timed out: "
            + out.decode(errors="replace")[-800:]
            + err.decode(errors="replace")[-800:]
        )
    if proc.returncode:
        raise RuntimeError(
            f"Remote rc={proc.returncode}: "
            + out.decode(errors="replace")[-1200:]
            + err.decode(errors="replace")[-800:]
        )
    return out.decode()


def _public_dns_snapshot() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "scripts" / "connection"))
    import labgpu

    host = urllib.parse.urlsplit(labgpu.BASE).hostname
    try:
        resp = subprocess.run(
            [
                "curl",
                "-fsS",
                "--connect-timeout",
                "3",
                "--max-time",
                "6",
                f"https://dns.google/resolve?name={host}&type=A",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=8,
        )
    except subprocess.SubprocessError as exc:
        raise ObservationUnavailable("Public DNS query unavailable") from exc

    dns = json.loads(resp.stdout)
    addresses = [
        str(ipaddress.IPv4Address(a["data"]))
        for a in dns.get("Answer", [])
        if a.get("type") == 1 and ipaddress.IPv4Address(a["data"]).is_global
    ]
    if dns.get("Status") != 0 or not addresses:
        raise ObservationUnavailable("Public DNS returned no valid platform IP")

    class CurlOpener:
        def open(self, request: Any, timeout: float) -> Any:
            if request.full_url != labgpu.BASE + "/api/me" or request.get_method() != "GET":
                raise RuntimeError("Restricted to GET /api/me")
            headers = "".join(f"{k}: {v}\n" for k, v in request.header_items()).encode()
            for addr in addresses[:2]:
                try:
                    res = subprocess.run(
                        [
                            "curl",
                            "-sS",
                            "--proto",
                            "=https",
                            "--noproxy",
                            "*",
                            "--connect-timeout",
                            "3",
                            "--max-time",
                            "10",
                            "--include",
                            "--resolve",
                            f"{host}:443:{addr}",
                            "--header",
                            "@-",
                            request.full_url,
                        ],
                        input=headers,
                        capture_output=True,
                        timeout=12,
                    )
                except subprocess.TimeoutExpired:
                    continue
                if res.returncode or b"\r\n\r\n" not in res.stdout:
                    continue
                head, body = res.stdout.split(b"\r\n\r\n", 1)
                status = int(head.split(b"\r\n", 1)[0].split()[1])
                parsed_headers = email.parser.BytesParser().parsebytes(head.split(b"\r\n", 1)[1])
                if status != 200:
                    raise urllib.error.HTTPError(
                        request.full_url, status, "Platform HTTP error", parsed_headers, None
                    )
                bio = io.BytesIO(body)
                bio.headers = parsed_headers  # type: ignore[attr-defined]
                return bio
            raise urllib.error.URLError("Public-DNS HTTPS connection failed")

    labgpu.secure_dir()
    client = labgpu.Client(6, labgpu.cookies_load())
    old_cookies = list(client.cookies)
    client.opener = CurlOpener()
    try:
        payload = labgpu.fetch_payload(client)
    except labgpu.NetworkError as exc:
        raise ObservationUnavailable("Platform network temporarily unavailable") from exc
    now = time.time()
    value = labgpu.normalize(payload, fetched_at=now, now=now, source=labgpu.BASE, cache_state="fresh")
    if client.cookies != old_cookies:
        labgpu.atomic_write(labgpu.CONFIG / "cookies.json", {"base_url": labgpu.BASE, "cookies": client.cookies})
    value["observation_transport"] = "live_https_public_dns"
    return value


def fetch_snapshot() -> dict[str, Any]:
    try:
        res = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "connection" / "labgpu.py"), "status", "--fresh", "--json", "--timeout", "4"],
            capture_output=True,
            text=True,
            timeout=14,
        )
        if res.returncode != 0:
            raise RuntimeError(res.stdout[-300:] + res.stderr[-300:])
        value = json.loads(res.stdout)
        value["observation_transport"] = "labgpu_cli"
    except (subprocess.TimeoutExpired, RuntimeError, ValueError):
        value = _public_dns_snapshot()
    if value.get("cache_state") != "fresh" or (time.time() - float(value["fetched_at"])) > 30:
        raise ObservationUnavailable("Stale platform observation")
    return value


def evaluate_permission(value: dict[str, Any], host_id: str, gpu_uuid: str, run_id: str) -> dict[str, Any]:
    account = value["account"]
    policy = value["policy"]
    if account.get("username") != "zhangzibo" or account.get("registered") is not True or account.get("active_ban") is not None:
        raise RuntimeError("Account permission unavailable or banned")

    rules = policy.get("rules")
    if not isinstance(rules, dict) or type(rules.get("gpu_management_enabled")) is not bool:
        raise RuntimeError("Platform rules unavailable")

    for field in ("gpu_requests", "maintenance", "rectifications", "cases"):
        if not isinstance(policy.get(field), list):
            raise RuntimeError(f"Unknown platform {field}")

    closed = {"rejected", "cancelled", "canceled", "expired", "completed", "closed", "resolved"}
    if any(r.get("status") not in closed for r in policy["gpu_requests"]):
        raise RuntimeError("Pending GPU request requires conflict resolution")
    if any(r.get("stop_required") is True and r.get("status") not in closed for r in policy["rectifications"] + policy["cases"]):
        raise RuntimeError("Platform explicitly requires stopping")

    usage = account["usage"]
    cap = min(4, int(usage.get("limit", account.get("limit", 4))))
    host = next(h for h in value["hosts"] if h["id"] == host_id)
    if not host.get("online") or float(host.get("sample_age_seconds", 999)) > 120:
        raise RuntimeError(f"{host_id} sampling unavailable or stale")

    gpu = next(g for g in host["gpus"] if g["uuid"] == gpu_uuid)
    current = {(c["host_id"], c["gpu_index"]) for c in usage.get("cards", [])}
    stale_own = {(h["id"], g["index"]) for h in value["hosts"] for g in h["gpus"] if g.get("own") and g.get("status") == "stale"}
    requested = {(host_id, gpu["index"])}
    conservative_count = len(current | stale_own | requested) + max(0, int(usage.get("count", 0)) - len(current))
    if conservative_count > cap:
        raise RuntimeError(f"Cross-server GPU quota exceeded: {conservative_count} > {cap}")

    allowed = (
        gpu.get("compute_mode") == "Default"
        and gpu.get("status") != "disabled"
        and float(gpu.get("sample_age_seconds", 999)) < 120
    )
    if not allowed:
        raise RuntimeError(f"GPU {gpu_uuid} disallowed: mode={gpu.get('compute_mode')}, status={gpu.get('status')}")

    ttl = min(
        105.0,
        120.0 - float(gpu["sample_age_seconds"]) - (time.time() - float(value["fetched_at"])) - 2.0,
    )
    if ttl <= 0:
        raise ObservationUnavailable("Resource sample expired during policy check")

    return {
        "run_id": run_id,
        "status": "active",
        "observed_at": f"{float(value['fetched_at']):.3f}",
        "expires_at": f"{time.time() + ttl:.3f}",
        "ttl_seconds": f"{ttl:.1f}",
        "transport": value.get("observation_transport", "labgpu_cli"),
        "host_id": host_id,
        "gpu_uuid": gpu_uuid,
        f"card_{gpu_uuid}_allowed": "true",
        "allowed": "true",
        "conservative_gpu_count": str(conservative_count),
        "quota_cap": str(cap),
    }


def push_permission_md(target: str, remote_perm_path: str, items: dict[str, str]) -> None:
    lines = ["# Live Resource Permission (Auto-Refreshed, Not Exclusive)", ""]
    for k, v in items.items():
        lines.append(f"- `{k}`: `{v}`")
    text = "\n".join(lines) + "\n"
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    code = (
        "import base64, pathlib; "
        f"p=pathlib.Path({remote_perm_path!r}); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        "t=p.with_suffix('.tmp'); "
        f"t.write_bytes(base64.b64decode({encoded!r})); "
        "t.replace(p)"
    )
    remote_exec(target, shlex.join(["python3", "-c", code]), timeout=45)


def check_remote_done(target: str, remote_run_dir: str) -> bool:
    code = (
        "import pathlib; "
        f"p=pathlib.Path({remote_run_dir!r})/'RUN_STATE.md'; "
        "txt=p.read_text(encoding='utf-8') if p.exists() else ''; "
        "print('DONE' if ('- `command`: `run-all`' in txt and '- `status`: `done`' in txt) else 'RUN')"
    )
    out = remote_exec(target, shlex.join(["python3", "-c", code]), timeout=40).strip()
    return out == "DONE"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Local platform permission heartbeat observer for MVP-v1.")
    p.add_argument("--action", default="watch", choices=["watch", "once", "exec", "upload-tar", "download-tar"])
    p.add_argument("--target", default="school104")
    p.add_argument("--host-id", default="iipl-104")
    p.add_argument("--gpu-uuid", default="GPU-0fc254b8-f4f9-2382-8d33-71c99526fb1b")
    p.add_argument("--run-id", default="lora-comp-mvp-20261113-v1")
    p.add_argument("--remote-run-dir", default="/data2/zhangzibo/arxiv-tssa/results/lora-comp-mvp-20261113-v1")
    p.add_argument("--local-log-dir", default="autoresearch/runs/lora-comp-mvp-20261113-v1")
    p.add_argument("--interval", type=float, default=25.0)
    p.add_argument("--once", action="store_true")
    p.add_argument("--cmd", default=None)
    p.add_argument("--remote-dir", default=None)
    p.add_argument("--tar-path", default=None)
    p.add_argument("--timeout", type=int, default=70)
    args = p.parse_args(argv)

    if args.action == "exec":
        if not args.cmd:
            p.error("--cmd required for exec")
        print(remote_exec(args.target, args.cmd, timeout=args.timeout), end="")
        return 0
    if args.action == "upload-tar":
        if not args.remote_dir or not args.tar_path:
            p.error("--remote-dir and --tar-path required for upload-tar")
        blob = Path(args.tar_path).read_bytes()
        out = remote_exec(
            args.target,
            f"mkdir -p {shlex.quote(args.remote_dir)} && tar xzf - -C {shlex.quote(args.remote_dir)}",
            timeout=args.timeout,
            payload=blob,
        )
        print(out, end="")
        return 0
    if args.action == "download-tar":
        if not args.remote_dir or not args.tar_path or not args.cmd:
            p.error("--remote-dir, --cmd (paths inside remote-dir), and --tar-path required")
        proc = subprocess.Popen(
            _ssh_args(args.target) + [f"tar czf - -C {shlex.quote(args.remote_dir)} {args.cmd}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.communicate(timeout=5)
            raise RuntimeError("download-tar timed out")
        if proc.returncode:
            raise RuntimeError(f"download-tar failed rc={proc.returncode}: {err.decode(errors='replace')}")
        Path(args.tar_path).write_bytes(out)
        print(f"Downloaded {len(out)} bytes to {args.tar_path}")
        return 0

    if args.action == "once":
        args.once = True

    local_dir = Path(args.local_log_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    remote_perm = str(Path(args.remote_run_dir) / "permission.md")
    log_path = local_dir / "observer.md"
    if not log_path.exists():
        log_path.write_text("# Platform Permission Observer Log\n\n", encoding="utf-8")

    while not (local_dir / "STOP").exists():
        iso = dt.datetime.now().astimezone().replace(microsecond=0).isoformat()
        try:
            snap = fetch_snapshot()
            obs = evaluate_permission(snap, host_id=args.host_id, gpu_uuid=args.gpu_uuid, run_id=args.run_id)
            push_permission_md(args.target, remote_perm, obs)
            done = False if args.once else check_remote_done(args.target, args.remote_run_dir)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"- {iso} `active` ttl=`{obs['ttl_seconds']}s` transport=`{obs['transport']}` "
                    f"quota=`{obs['conservative_gpu_count']}/{obs['quota_cap']}` done=`{done}`\n"
                )
            print(f"[{iso}] active ttl={obs['ttl_seconds']}s done={done}", flush=True)
            if args.once or done:
                return 0
        except ObservationUnavailable as exc:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"- {iso} `unavailable` (prior expiry unchanged): {exc}\n")
            print(f"[{iso}] unavailable: {exc}", flush=True)
            if args.once:
                return 1
        except Exception as exc:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"- {iso} `revoked_or_error`: {exc}\n")
            print(f"[{iso}] revoked/error: {exc}", flush=True)
            try:
                push_permission_md(
                    args.target,
                    remote_perm,
                    {
                        "run_id": args.run_id,
                        "status": "paused",
                        "expires_at": "0",
                        f"card_{args.gpu_uuid}_allowed": "false",
                        "allowed": "false",
                        "reason": str(exc).replace("`", "'")[:180],
                    },
                )
            except Exception:
                pass
            if args.once:
                return 1
        time.sleep(float(args.interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
