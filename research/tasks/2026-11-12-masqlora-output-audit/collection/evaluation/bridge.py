"""One verified lab device and bounded SSH supervision for clean controls."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time


REPO = Path(__file__).resolve().parents[4]
if not (REPO / "labgpu").is_file():
    REPO = next(p for p in Path(__file__).resolve().parents if (p / "labgpu").is_file())
spec = importlib.util.spec_from_file_location("control", REPO / "scripts/reproduction/masqlora/control.py")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
CLOSED = {"rejected", "cancelled", "canceled", "expired", "completed", "closed", "resolved"}
NODE_ORDER = ("104", "103", "127")  # 101 is unavailable per the existing user instruction.


def authority(data):
    account, policy = data["account"], data["policy"]
    if account["username"] != "zhangzibo" or account.get("registered") is not True or account.get("active_ban") is not None:
        raise ValueError("Platform account unavailable or banned")
    if type(policy["rules"].get("gpu_management_enabled")) is not bool:
        raise ValueError("Current platform rules unavailable")
    if any(row.get("status") not in CLOSED for row in policy["gpu_requests"]):
        raise ValueError("Live GPU allocation requires conflict review")
    if any(row.get("stop_required") and row.get("status") not in CLOSED
           for row in policy["cases"] + policy["rectifications"]):
        raise ValueError("Platform requires stopping")
    return account["usage"]


def ssh(node):
    return ["ssh", "-F", str(REPO / "server/school_ssh_config"),
            "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=10",
            "-o", "ServerAliveCountMax=2", "school" + node]


def remote(node, command, **kwargs):
    return subprocess.run(ssh(node) + [command], check=True, text=True, timeout=18, **kwargs)


DEVICE_CHECK = """
import csv, io, subprocess, sys
uuid, assets = sys.argv[1:]
from pathlib import Path
p = Path(assets)
assert all((p / f).exists() for f in (
    "venv/bin/python", "models/sd15/model_index.json", "models/clip/model.safetensors",
    "models/vit/model.safetensors")), "local model/environment missing"
cards = subprocess.check_output(["nvidia-smi", "-i", uuid,
    "--query-gpu=uuid,compute_mode,memory.used,utilization.gpu", "--format=csv,noheader,nounits"], text=True, timeout=6)
rows = list(csv.reader(io.StringIO(cards), skipinitialspace=True))
assert len(rows) == 1, rows
device, mode, mem, util = [v.strip() for v in rows[0]]
assert device == uuid and mode == "Default" and float(mem) <= 256 and float(util) <= 5, rows
apps = subprocess.check_output(["nvidia-smi", "-i", uuid, "--query-compute-apps=pid",
    "--format=csv,noheader,nounits"], text=True, timeout=6)
assert not apps.strip(), apps
print(cards.strip())
"""


def guard(run, state):
    state.unlink(missing_ok=True)
    data = control.snapshot()
    usage = authority(data)
    own = {(h["id"], g["index"]) for h in data["hosts"] for g in h["gpus"] if g.get("own")}
    accounted = {(c["host_id"], c["gpu_index"]) for c in usage["cards"]}
    if len(own | accounted) + max(0, usage["count"] - len(accounted)) >= min(4, usage["limit"]):
        raise ValueError("No quota available for another GPU")
    nodes = tuple(node for node in NODE_ORDER if node not in os.environ.get("AUDIT_SKIP_NODES", "").split(","))
    for node in nodes:
        host = next((h for h in data["hosts"] if h["label"] == node), None)
        if not host or not host["online"] or not host["process_state_complete"]:
            continue
        card = next((g for g in host["gpus"] if g["status"] == "free"), None)
        if card is None:
            continue
        assets = "/data2/zhangzibo/arxiv-tssa" if node == "104" else "/data1/zhangzibo/arxiv-tssa"
        root = f"{assets}/results/{run.name}"
        uuid = card["uuid"]
        try:
            remote(node, shlex.join(["python3", "-c", DEVICE_CHECK, uuid, assets]))
        except subprocess.SubprocessError as exc:
            print(f"Device check failed on {node}: {exc}", flush=True)
            continue
        state.write_text("# Selected device\n\n" + json.dumps({
            "node": node, "uuid": uuid, "assets": assets, "root": root, "host_id": host["id"],
            "launch_checked_at": time.time(), "snapshot_at": data["fetched_at"],
        }) + "\n")
        return
    raise ValueError("No compatible free device passed the live platform and device checks")


def run_worker(run, value):
    node, uuid, assets, root = (value[key] for key in ("node", "uuid", "assets", "root"))
    if time.time() - value["snapshot_at"] > 60:
        raise ValueError("Initial resource observation expired before launch")
    remote(node, shlex.join(["mkdir", "-p", root]))
    for source, target in ((run / "work/controls.json", "controls.json"),
                           (run / "evaluation/collect.py", "collect.py")):
        remote(node, "cat > " + shlex.quote(root + "/" + target), input=source.read_text())

    argv = ["env", f"CUDA_VISIBLE_DEVICES={uuid}", "HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1",
            "timeout", "--signal=TERM", "--kill-after=5", "3500", assets + "/venv/bin/python",
            "-u", root + "/collect.py", root, assets, uuid]
    with subprocess.Popen(ssh(node) + [shlex.join(argv)], stdin=subprocess.PIPE, text=True) as process:
        def heartbeat():
            process.stdin.write("continue\n")
            process.stdin.flush()

        heartbeat()
        while True:
            try:
                return process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                pass
            try:
                data = control.snapshot()
            except (OSError, ValueError, RuntimeError) as exc:
                print("No fresh observation: " + str(exc), flush=True)
                continue
            usage = authority(data)
            host = next(h for h in data["hosts"] if h["id"] == value["host_id"])
            gpu = next(g for g in host["gpus"] if g["uuid"] == uuid)
            if gpu["status"] == "disabled" or gpu["compute_mode"] != "Default":
                raise ValueError("Platform disabled this device")
            if gpu["status"] not in {"stale", "unknown", "fault"} and not usage.get("over"):
                if max(gpu["sample_age_seconds"], host["process_sample_age_seconds"]) + time.time() - data["fetched_at"] < 50:
                    heartbeat()


CLEANUP = """
import os, re, signal, sys, time
from pathlib import Path
root, uuid = sys.argv[1:]
path = Path(root) / "worker.md"
if not path.exists():
    sys.exit(0)
pid = int(re.search(r"PID (\\d+)", path.read_text()).group(1))
def matches():
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\\0")
        return (Path(f"/proc/{pid}").stat().st_uid == os.getuid() and
                os.fsencode(root + "/collect.py") in cmd and os.fsencode(uuid) in cmd)
    except FileNotFoundError:
        return False
if matches():
    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        if not matches():
            break
        time.sleep(0.25)
    else:
        if matches():
            os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
if matches():
    raise RuntimeError("Worker has not exited")
print("Verified this clean-control worker is absent")
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["guard", "run", "cleanup"])
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    state = args.run / "device.md"
    if args.action == "guard":
        guard(args.run, state)
    elif state.exists():
        value = json.loads(state.read_text().splitlines()[-1])
        if args.action == "run":
            sys.exit(run_worker(args.run, value))
        remote(value["node"], shlex.join(["python3", "-c", CLEANUP, value["root"], value["uuid"]]))


if __name__ == "__main__":
    main()
