"""Reuse the permission-aware bridge with the verified DNS fallback route."""
import importlib.util
import ipaddress
import os
from pathlib import Path
import shlex

repo = next(p for p in Path(__file__).resolve().parents if (p / "labgpu").is_file())
source = repo / "research/tasks/2026-11-12-masqlora-output-audit/collection/evaluation/bridge.py"
spec = importlib.util.spec_from_file_location("gpu_bridge", source)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
original_ssh = bridge.ssh


def ssh(node):
    argv = original_ssh(node)
    if mux := os.environ.get("AUDIT_SSH_DIR"):
        proxy = shlex.join([
            "ssh", "-F", str(repo / "server/school_ssh_config"), "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes", "-S", str(Path(mux) / "jump"),
            "-W", "%h:%p", "school-jump",
        ])
        argv[argv.index("ConnectTimeout=10")] = "ConnectTimeout=45"
        argv[1:1] = [
            "-o", "ProxyCommand=" + proxy, "-S", str(Path(mux) / node),
            "-o", "ControlMaster=auto", "-o", "ControlPersist=120",
        ]
    elif jump := os.environ.get("AUDIT_JUMP_HOST"):
        address = str(ipaddress.IPv4Address(jump))
        proxy = shlex.join([
            "ssh", "-F", str(repo / "server/school_ssh_config"), "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10",
            "-o", "HostName=" + address, "-W", "%h:%p", "school-jump",
        ])
        argv[1:1] = ["-o", "ProxyCommand=" + proxy]
    return argv


bridge.ssh = ssh

if __name__ == "__main__":
    bridge.main()
