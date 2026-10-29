#!/usr/bin/env python3
"""Stage one pinned public asset at a time through the Mac to school104.

This performs CPU/network preparation only. It never allocates or selects GPUs.
Only task-created local staging files are removed after remote SHA256 verification.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = "/data2/zhangzibo/arxiv-tssa"
LOCK_PATH = Path("/private/tmp/arxiv-tssa-stage/.transfer.lock")


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prefix_sha256(path, size):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        remaining = size
        while remaining:
            block = stream.read(min(remaining, 8 * 1024 * 1024))
            if not block:
                raise RuntimeError("Local file is shorter than the remote upload prefix")
            digest.update(block)
            remaining -= len(block)
    return digest.hexdigest()


def source_url(entry):
    from urllib.parse import quote, urlsplit
    if entry.get("kind") == "wheel":
        url = entry["source_url"]
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in {"files.pythonhosted.org", "download.pytorch.org"}
                or not entry.get("sha256") or not entry["local_path"].endswith(".whl")):
            raise ValueError("Wheels require official HTTPS origin and a pinned SHA256")
        return url
    revision = entry["revision"]
    if len(revision) != 40 or not all(c in "0123456789abcdef" for c in revision):
        raise ValueError("Only immutable HF commit revisions are accepted")
    return "https://huggingface.co/" + entry["repo_id"] + "/resolve/" + revision + "/" + quote(entry["path"], safe="/")


def verify_source(path, entry):
    actual = sha256(path)
    size = path.stat().st_size
    if size != int(entry["size"]) or (entry.get("sha256") and actual != entry["sha256"]):
        raise RuntimeError(f"Source hash or size mismatch: {entry['local_path']}")
    if not entry.get("sha256") and entry.get("git_blob_oid"):
        blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                blob.update(block)
        if blob.hexdigest() != entry["git_blob_oid"]:
            raise RuntimeError(f"Pinned Git blob mismatch: {entry['local_path']}")
    return actual


def reachable(host):
    try:
        with socket.create_connection((host, 7002), timeout=3):
            return True
    except OSError:
        return False


def gateway_address():
    if reachable("hduiipl.cn"):
        return "hduiipl.cn"
    for resolver in ("https://dns.alidns.com/resolve", "https://dns.google/resolve"):
        try:
            output = run(["curl", "-fsS", "--connect-timeout", "4", "--max-time", "8",
                          resolver + "?name=hduiipl.cn&type=A"], capture_output=True).stdout
            data = json.loads(output)
            if data.get("Status") != 0:
                continue
            for answer in data.get("Answer", []):
                if answer.get("type") != 1:
                    continue
                address = str(ipaddress.IPv4Address(answer["data"]))
                if reachable(address):
                    return address
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    raise RuntimeError("School gateway unreachable; no host-key checks were bypassed.")


class SchoolSession:
    def __init__(self, *, independent_sftp=False, verbose_sftp=False, ssh_chunk_bytes=0):
        self.independent_sftp = independent_sftp
        self.verbose_sftp = verbose_sftp
        if not 0 <= ssh_chunk_bytes <= 64 * 1024**2:
            raise ValueError("SSH chunks must be between 1 byte and 64 MiB, or 0 to disable")
        self.ssh_chunk_bytes = ssh_chunk_bytes

    def __enter__(self):
        # Keep ControlPath under macOS's short Unix socket pathname limit.
        self.temporary = tempfile.TemporaryDirectory(prefix="school-stage-", dir="/private/tmp")
        folder = Path(self.temporary.name)
        self.config = folder / "config"
        base = ROOT / "server/school_ssh_config"
        self.config.write_text(
            f"Host school-jump\n    HostName {gateway_address()}\n"
            f"Host school104\n    ControlMaster auto\n    ControlPersist 600\n"
            f"    ControlPath {folder}/cm-%C\n"
            f'Host *\n    BatchMode yes\n    StrictHostKeyChecking yes\n    Include "{base}"\n'
        )
        self.config.chmod(0o600)
        return self

    def remote(self, source, *args):
        command = shlex.join(["python3", "-c", source, *map(str, args)])
        return run(["ssh", "-F", str(self.config), "school104", command], capture_output=True).stdout.strip()

    def upload(self, local, remote):
        size = Path(local).stat().st_size
        partial = json.loads(self.remote(REMOTE_PARTIAL, remote, size))
        offset = partial["size"]
        if partial["sha256"] != prefix_sha256(local, offset):
            raise RuntimeError("Existing remote upload prefix differs; refusing to overwrite it")
        if offset == size:
            return
        if self.ssh_chunk_bytes:
            with Path(local).open("rb") as stream:
                stream.seek(offset)
                while offset < size:
                    payload = stream.read(min(self.ssh_chunk_bytes, size - offset))
                    if not payload:
                        raise RuntimeError("Local source shortened during chunk upload")
                    receipt = self._upload_chunk(remote, offset, size, payload)
                    expected = {"offset": offset, "chunk_size": len(payload),
                                "committed_size": offset + len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
                    if receipt != expected:
                        raise RuntimeError("Remote chunk receipt differs; keep both copies for inspection")
                    offset = receipt["committed_size"]
                    print("Verified remote chunk: " + json.dumps(receipt), flush=True)
            return
        def quoted(value):
            value = str(value)
            if "\n" in value or "\r" in value:
                raise ValueError("Newlines are not allowed in SFTP paths")
            return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
        command = ("reput" if offset else "put") + " " + quoted(local) + " " + quoted(remote) + "\n"
        transport = ["sftp", "-vv" if self.verbose_sftp else "-q", "-b", "-", "-F", str(self.config)]
        if self.independent_sftp:
            # Diagnostic override applies only to this SFTP transport; integrity,
            # host-key policy and the separately owned control master stay intact.
            transport.extend(["-o", "ControlMaster=no", "-o", "ControlPath=none"])
        run([*transport, "school104"], input=command)

    def _upload_chunk(self, remote, offset, total, payload):
        command = shlex.join(["python3", "-c", REMOTE_CHUNK, remote, str(offset), str(total),
                              str(len(payload)), hashlib.sha256(payload).hexdigest()])
        # Each bounded chunk has its own strictly authenticated connection.
        result = subprocess.run(["ssh", "-F", str(self.config), "-o", "ControlMaster=no",
                                 "-o", "ControlPath=none", "school104", command],
                                input=payload, capture_output=True)
        if result.returncode:
            print(result.stderr.decode(errors="replace")[-4000:], file=sys.stderr)
            result.check_returncode()
        return json.loads(result.stdout)

    def __exit__(self, *_):
        try:
            subprocess.run(["ssh", "-F", str(self.config), "-O", "exit", "school104"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        except (OSError, subprocess.SubprocessError):
            # A control-master cleanup failure must not mask a transfer failure.
            pass
        finally:
            self.temporary.cleanup()


REMOTE_CHECK = r'''
import hashlib,json,os,pathlib,shutil,sys
root=pathlib.Path(sys.argv[1]); dest=pathlib.Path(sys.argv[2]); size=int(sys.argv[3]); expected=sys.argv[4]
assert root==pathlib.Path('/data2/zhangzibo/arxiv-tssa')
assert dest.is_relative_to(root) and '..' not in dest.parts
own=pathlib.Path('/data2/zhangzibo')
own.mkdir(mode=0o750,exist_ok=True)
assert not own.is_symlink() and own.stat().st_uid==os.getuid()
for parent in [root,*list(dest.parents)[::-1]]:
    if parent.is_relative_to(root):
        parent.mkdir(mode=0o750,exist_ok=True)
        assert not parent.is_symlink() and parent.stat().st_uid==os.getuid()
assert not dest.is_symlink() and not pathlib.Path(str(dest)+'.uploading').is_symlink()
assert dest.resolve().is_relative_to(root.resolve())
if dest.exists():
    assert dest.is_file() and dest.stat().st_uid==os.getuid()
    h=hashlib.sha256()
    with dest.open('rb') as f:
        for b in iter(lambda:f.read(8388608),b''): h.update(b)
    actual=h.hexdigest()
    assert dest.stat().st_size==size and (not expected or actual==expected), 'Existing asset differs; refusing overwrite'
    print(json.dumps({'exists':True,'sha256':actual,'size':size}))
else:
    assert shutil.disk_usage(dest.parent).free>size+5*1024**3, 'Insufficient remote free space'
    print(json.dumps({'exists':False}))
'''

REMOTE_COMMIT = r'''
import hashlib,json,os,pathlib,sys
dest=pathlib.Path(sys.argv[1]); expected=sys.argv[2]; size=int(sys.argv[3]); temp=pathlib.Path(str(dest)+'.uploading')
assert dest.is_relative_to(pathlib.Path('/data2/zhangzibo/arxiv-tssa'))
assert not dest.exists() and not temp.is_symlink() and temp.stat().st_uid==os.getuid()
h=hashlib.sha256()
with temp.open('rb') as f:
    for b in iter(lambda:f.read(8388608),b''): h.update(b)
assert h.hexdigest()==expected and temp.stat().st_size==size, 'Transferred asset hash/size mismatch'
os.link(temp,dest); temp.unlink()
print(json.dumps({'exists':True,'sha256':expected,'size':size}))
'''

REMOTE_PARTIAL = r'''
import hashlib,json,os,pathlib,sys
path=pathlib.Path(sys.argv[1]); size=int(sys.argv[2]); root=pathlib.Path('/data2/zhangzibo/arxiv-tssa')
assert path.is_relative_to(root) and '..' not in path.parts and path.name.endswith('.uploading')
for parent in [path,*path.parents]:
    if parent.is_relative_to(root):
        assert not parent.is_symlink()
        if parent.exists(): assert parent.stat().st_uid==os.getuid()
h=hashlib.sha256(); offset=0
if path.exists():
    assert path.is_file() and path.stat().st_size<=size, 'Invalid existing upload'
    offset=path.stat().st_size
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8388608),b''): h.update(b)
print(json.dumps({'size':offset,'sha256':h.hexdigest()}))
'''

REMOTE_CHUNK = r'''
import fcntl,hashlib,json,os,pathlib,stat,sys,tempfile
path=pathlib.Path(sys.argv[1]); offset=int(sys.argv[2]); total=int(sys.argv[3]); size=int(sys.argv[4]); expected=sys.argv[5]
root=pathlib.Path('/data2/zhangzibo/arxiv-tssa')
assert path.is_relative_to(root) and '..' not in path.parts and path.name.endswith('.uploading')
assert 0<size<=64*1024**2 and 0<=offset and offset+size<=total
assert len(expected)==64 and all(c in '0123456789abcdef' for c in expected)
for parent in [path,*path.parents]:
    if parent.is_relative_to(root):
        assert not parent.is_symlink()
        if parent.exists(): assert parent.stat().st_uid==os.getuid()
fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'r+b') as target:
    fcntl.flock(target,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert stat.S_ISREG(os.fstat(target.fileno()).st_mode)
    assert os.fstat(target.fileno()).st_size==offset, 'Remote prefix changed; recheck before resuming'
    chunk_fd,chunk_name=tempfile.mkstemp(prefix=path.name+'.chunk-',dir=path.parent)
    chunk=pathlib.Path(chunk_name)
    h=hashlib.sha256(); remaining=size
    with os.fdopen(chunk_fd,'wb') as sink:
        while remaining:
            block=sys.stdin.buffer.read(min(2*1024**2,remaining))
            assert block, 'Incomplete incoming chunk; existing model prefix retained'
            sink.write(block);h.update(block);remaining-=len(block)
        assert not sys.stdin.buffer.read(1), 'Unexpected trailing upload data'
        sink.flush();os.fsync(sink.fileno())
    assert h.hexdigest()==expected, 'Incoming chunk SHA256 differs; model prefix retained'
    # Only verified chunks reach the model temporary file. An interrupted append
    # is recovered by the client's whole-prefix check on the next invocation.
    target.seek(offset)
    with chunk.open('rb') as incoming:
        for block in iter(lambda:incoming.read(2*1024**2),b''): target.write(block)
    target.flush();os.fsync(target.fileno());target.seek(offset)
    h=hashlib.sha256();remaining=size
    while remaining:
        block=target.read(min(2*1024**2,remaining));assert block
        h.update(block);remaining-=len(block)
    assert h.hexdigest()==expected and os.fstat(target.fileno()).st_size==offset+size
    chunk.unlink()  # Only this fully verified task-created chunk is removed.
print(json.dumps({'offset':offset,'chunk_size':size,'committed_size':offset+size,'sha256':expected}))
'''


def validate_relative(value):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Unsafe relative asset path")
    if not all(part and all(c.isalnum() or c in "._-+" for c in part) for part in path.parts):
        raise ValueError("Remote filenames must use safe path components")
    return str(path)


def append_record(ledger, record):
    ledger.parent.mkdir(parents=True, exist_ok=True)
    record["observed_at"] = datetime.now(timezone.utc).isoformat()
    with ledger.open("a") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def save_status(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump({**record, "observed_at": datetime.now(timezone.utc).isoformat()}, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path)
    source.add_argument("--file", type=Path)
    parser.add_argument("--relative-name", help="Required with --file, relative to the project data root")
    parser.add_argument("--role", action="append", help="Filter manifest local_dir, repeatable")
    parser.add_argument("--limit", type=int, help="Maximum number of manifest entries this invocation")
    parser.add_argument("--staging", type=Path, default=Path("/private/tmp/arxiv-tssa-stage"))
    parser.add_argument("--ledger", type=Path, default=ROOT / "results/tssa-mvp-2026-10-26/asset_transfer.jsonl")
    parser.add_argument("--independent-sftp", action="store_true", help="Diagnose transfer faults without reusing the SSH control connection")
    parser.add_argument("--verbose-sftp", action="store_true", help="Record SFTP/SSH connection diagnostics in this process's stderr")
    parser.add_argument("--ssh-chunk-bytes", type=int, default=0, help="Use verified chunks over separate SSH connections, at most 67108864 bytes; 0 keeps SFTP")
    args = parser.parse_args()
    if not 0 <= args.ssh_chunk_bytes <= 64 * 1024**2:
        parser.error("--ssh-chunk-bytes must be between 0 and 67108864")
    if args.file:
        if not args.relative_name:
            parser.error("--file requires --relative-name")
        entries = [{"local_path": validate_relative(args.relative_name), "size": args.file.stat().st_size,
                    "sha256": sha256(args.file), "source_file": str(args.file.resolve())}]
    else:
        entries = json.loads(args.manifest.read_text())["files"]
        entries = [x for x in entries if not args.role or x["local_dir"] in args.role]
        if args.limit is not None:
            if args.limit < 1:
                parser.error("--limit must be positive")
            entries = entries[:args.limit]
    if not entries:
        parser.error("No files selected; check the manifest and --role")
    destinations = set()
    for entry in entries:
        relative = validate_relative(entry["local_path"])
        if relative in destinations:
            parser.error("Duplicate asset destination")
        destinations.add(relative)
        if int(entry["size"]) < 0 or not (entry.get("sha256") or entry.get("git_blob_oid")):
            parser.error("Every asset needs a nonnegative size and pinned integrity identifier")
        if not args.file:
            source_url(entry)
    args.staging.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.staging.is_symlink() or args.staging.stat().st_uid != os.getuid():
        raise RuntimeError("Staging directory ownership is not safe")
    LOCK_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if LOCK_PATH.parent.is_symlink() or LOCK_PATH.is_symlink() or LOCK_PATH.parent.stat().st_uid != os.getuid():
        raise RuntimeError("Unsafe transfer lock location")
    # Independent of --staging, and compatible with the original running helper.
    with LOCK_PATH.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another staging transfer is active; do not start a duplicate.")
        identity = sha256(args.manifest) if args.manifest else sha256(args.file)
        selection_id = hashlib.sha256(json.dumps(sorted(destinations)).encode()).hexdigest()[:12]
        status_path = args.ledger.with_name(args.ledger.stem + "." + identity[:16] + "." + selection_id + ".status.json")
        status = {"source_sha256": identity, "selected_files": len(entries), "verified_files": 0,
                  "selected_paths": [entry["local_path"] for entry in entries], "status": "running",
                  "independent_sftp": args.independent_sftp, "verbose_sftp": args.verbose_sftp,
                  "ssh_chunk_bytes": args.ssh_chunk_bytes,
                  "full_manifest_selected": bool(args.manifest and len(entries) == len(json.loads(args.manifest.read_text())["files"]))}
        save_status(status_path, status)
        try:
            transfer_entries(args, entries, status_path, status)
        except BaseException as error:
            status.update(status="failed", error_type=type(error).__name__, error=str(error))
            save_status(status_path, status)
            raise
        status["status"] = "complete"
        save_status(status_path, status)


def transfer_entries(args, entries, status_path, status):
    with SchoolSession(independent_sftp=args.independent_sftp, verbose_sftp=args.verbose_sftp,
                       ssh_chunk_bytes=args.ssh_chunk_bytes) as session:
        for entry in entries:
            relative = validate_relative(entry["local_path"])
            is_wheel = entry.get("kind") == "wheel"
            remote = REMOTE_ROOT + ("/" if args.file or is_wheel else "/models/") + relative
            size = int(entry["size"])
            expected = entry.get("sha256") or ""
            if args.file:
                local = args.file
            else:
                url = source_url(entry)
                local = args.staging / (hashlib.sha256(url.encode()).hexdigest() + ".part")
                if local.is_symlink() or (local.exists() and (not local.is_file() or local.stat().st_uid != os.getuid())):
                    raise RuntimeError("Unexpected staging file type or owner")
            previous = json.loads(session.remote(REMOTE_CHECK, REMOTE_ROOT, remote, size, expected))
            if previous["exists"] and expected:
                if not args.file and local.exists():
                    # A crash after remote commit can leave a full local file.
                    # Delete only once its bytes match the verified remote asset.
                    if verify_source(local, entry) != previous["sha256"]:
                        raise RuntimeError("Local staging copy differs from verified remote asset")
                    local.unlink()
                append_record(args.ledger, {"status": "remote_verified_existing", "path": remote,
                                           "source": entry, **previous})
                status["verified_files"] += 1
                save_status(status_path, status)
                print(f"Verified existing: {relative}", flush=True)
                continue
            if not args.file:
                present = local.stat().st_size if local.exists() else 0
                if present > size:
                    raise RuntimeError("Staging file exceeds registered asset size")
                if shutil.disk_usage(args.staging).free < max(0, size - present) + 4 * 1024**3:
                    raise RuntimeError("Need asset size plus 4 GiB free on Mac; no user files were deleted")
                if present < size:
                    print(f"Downloading locally: {relative} ({size} bytes)", flush=True)
                    run(["curl", "-fsSL", "--retry", "3", "--retry-delay", "2", "--connect-timeout", "20",
                         "--speed-time", "120", "--speed-limit", "1024", "-C", "-", "-o", str(local), url])
            actual = verify_source(local, entry)
            if previous["exists"]:
                if previous["sha256"] != actual:
                    raise RuntimeError(f"Existing remote file differs from pinned source: {relative}")
                append_record(args.ledger, {"status": "remote_verified_existing", "path": remote,
                                           "source": entry, **previous})
                if not args.file:
                    local.unlink()
                status["verified_files"] += 1
                save_status(status_path, status)
                print(f"Verified existing against pinned source: {relative}", flush=True)
                continue
            print(f"Uploading: {relative}", flush=True)
            session.upload(local, remote + ".uploading")
            result = json.loads(session.remote(REMOTE_COMMIT, remote, actual, size))
            append_record(args.ledger, {"status": "transferred_verified", "path": remote, "source": entry, **result})
            if not args.file:
                local.unlink()
            status["verified_files"] += 1
            save_status(status_path, status)
            print(f"SHA256 verified remotely: {relative}", flush=True)


if __name__ == "__main__":
    main()
