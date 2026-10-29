#!/usr/bin/env python3
"""Verify and safely restore an explicitly supplied, offline research ZIP.

The manifest is a JSON object with schema_version=1, package={size, sha256},
and files=[{path, size, sha256}]. ZIP members must be files, with canonical
repository-relative POSIX paths. No network, experiment execution, replacement,
or deletion of existing user files is performed.

Completed files are published atomically with an exclusive hard link, then the
tool's own .part name is removed. This avoids POSIX rename's overwrite race.
The destination filesystem must support hard links and directory-relative I/O.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata
import uuid
import zipfile
from datetime import datetime, timezone


CHUNK_SIZE = 1024 * 1024


class ArchiveError(ValueError):
    """The supplied archive or destination failed a safety/integrity check."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _json_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ArchiveError("duplicate JSON key: " + key)
        value[key] = item
    return value


def _sha(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ArchiveError(label + " must be a SHA-256 hexadecimal digest")
    return value.lower()


def _size(value, label):
    if type(value) is not int or value < 0:
        raise ArchiveError(label + " must be a nonnegative integer")
    return value


def canonical_path(value):
    if not isinstance(value, str) or not value:
        raise ArchiveError("member path must be a nonempty string")
    if value.startswith("/") or "\\" in value or ":" in value:
        raise ArchiveError("absolute, Windows, or ambiguous member path: " + repr(value))
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ArchiveError("control character in member path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ArchiveError("noncanonical member path: " + repr(value))
    return value


def _portable_key(path):
    return unicodedata.normalize("NFC", path).casefold()


def _validate_path_set(paths):
    seen = {}
    for path in paths:
        canonical_path(path)
        key = _portable_key(path)
        if key in seen:
            raise ArchiveError("duplicate or case/Unicode-colliding path: " + path)
        seen[key] = path
    for key, path in seen.items():
        parts = key.split("/")
        if any("/".join(parts[:i]) in seen for i in range(1, len(parts))):
            raise ArchiveError("file used as another member's parent: " + path)


def _digest(stream, expected_size=None):
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            break
        size += len(chunk)
        if expected_size is not None and size > expected_size:
            raise ArchiveError("content exceeds its declared size")
        digest.update(chunk)
    return size, digest.hexdigest()


def read_manifest(path):
    raw = Path(path).read_bytes()
    try:
        manifest = json.loads(raw, object_pairs_hook=_json_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveError("invalid JSON manifest: " + str(exc)) from exc
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int:
        raise ArchiveError("manifest schema_version must be integer 1")
    if manifest["schema_version"] != 1:
        raise ArchiveError("unsupported manifest schema_version")
    package = manifest.get("package")
    files = manifest.get("files")
    if not isinstance(package, dict) or not isinstance(files, list):
        raise ArchiveError("manifest requires package object and files array")
    normalized = {
        "schema_version": 1,
        "package": {
            "size": _size(package.get("size"), "package.size"),
            "sha256": _sha(package.get("sha256"), "package.sha256"),
        },
        "files": [],
    }
    for entry in files:
        if not isinstance(entry, dict):
            raise ArchiveError("each manifest file must be an object")
        normalized["files"].append({
            "path": canonical_path(entry.get("path")),
            "size": _size(entry.get("size"), "file.size"),
            "sha256": _sha(entry.get("sha256"), "file.sha256"),
        })
    _validate_path_set([entry["path"] for entry in normalized["files"]])
    return normalized, hashlib.sha256(raw).hexdigest()


def _require_safe_io():
    functions = (os.open, os.stat, os.mkdir, os.link, os.unlink)
    if not all(function in os.supports_dir_fd for function in functions):
        raise ArchiveError("this platform lacks required directory-relative filesystem I/O")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ArchiveError("this platform lacks required no-follow directory open flags")


def _open_directory(path, create=False, missing_ok=False):
    """Walk from filesystem root through directory FDs without following links."""
    absolute = os.path.abspath(os.fspath(path))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(os.path.sep, flags)
    try:
        for component in Path(absolute).parts[1:]:
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    if missing_ok:
                        os.close(fd)
                        return None
                    raise
                try:
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _existing_matches(parent_fd, name, entry):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ArchiveError("unsafe or unreadable existing destination: " + entry["path"]) from exc
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ArchiveError("existing destination is not a regular file: " + entry["path"])
        if info.st_size != entry["size"]:
            raise ArchiveError("existing destination conflicts; refusing overwrite: " + entry["path"])
        size, digest = _digest(stream, entry["size"])
        if size != entry["size"] or digest != entry["sha256"]:
            raise ArchiveError("existing destination conflicts; refusing overwrite: " + entry["path"])
    return True


def _check_destination(target, files):
    target_fd = _open_directory(target, missing_ok=True)
    if target_fd is not None:
        os.close(target_fd)
    states = {}
    for entry in files:
        destination = Path(target) / entry["path"]
        parent_fd = _open_directory(destination.parent, missing_ok=True)
        if parent_fd is None:
            states[entry["path"]] = "absent"
        else:
            try:
                states[entry["path"]] = (
                    "reusable" if _existing_matches(parent_fd, destination.name, entry) else "absent"
                )
            finally:
                os.close(parent_fd)
    return states


def _write_member(zip_archive, info, entry, target):
    destination = Path(target) / entry["path"]
    parent_fd = _open_directory(destination.parent, create=True)
    part = ".research-restore-" + uuid.uuid4().hex + ".part"
    created_part = False
    try:
        if _existing_matches(parent_fd, destination.name, entry):
            return "reused"
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent_fd)
        created_part = True
        digest, size = hashlib.sha256(), 0
        with os.fdopen(fd, "wb") as output, zip_archive.open(info, "r") as source:
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > entry["size"]:
                    raise ArchiveError("member changed after verification: " + entry["path"])
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
            raise ArchiveError("member changed after verification: " + entry["path"])
        try:
            os.link(part, destination.name, src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd, follow_symlinks=False)
        except FileExistsError:
            if _existing_matches(parent_fd, destination.name, entry):
                return "reused"
            raise ArchiveError("destination appeared during restore: " + entry["path"])
        return "written"
    finally:
        if created_part:
            # Only the exclusive, random temporary file created by this call.
            os.unlink(part, dir_fd=parent_fd)
        os.close(parent_fd)


def _package_signature(stream):
    info = os.fstat(stream.fileno())
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _perform(command, package_path, manifest_path, target, audit):
    manifest, manifest_digest = read_manifest(manifest_path)
    audit["manifest_sha256"] = manifest_digest
    audit["expected_package"] = manifest["package"]
    expected_files = {entry["path"]: entry for entry in manifest["files"]}
    package_fd = os.open(package_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(package_fd, "rb") as package_stream:
        if not stat.S_ISREG(os.fstat(package_stream.fileno()).st_mode):
            raise ArchiveError("package must be a regular file")
        initial_signature = _package_signature(package_stream)
        size, digest = _digest(package_stream, manifest["package"]["size"])
        audit["observed_package"] = {"size": size, "sha256": digest}
        if audit["observed_package"] != manifest["package"]:
            raise ArchiveError("package size/SHA-256 mismatch")
        audit["package_verified"] = True
        package_stream.seek(0)
        with zipfile.ZipFile(package_stream, "r") as archive:
            members = archive.infolist()
            _validate_path_set([info.orig_filename for info in members])
            for info in members:
                if info.orig_filename != info.filename:
                    raise ArchiveError("ZIP member name was truncated or normalized")
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if info.is_dir() or file_type not in (0, stat.S_IFREG):
                    raise ArchiveError("ZIP symlink, directory, or special member rejected: " + info.filename)
                if info.flag_bits & 1:
                    raise ArchiveError("encrypted ZIP members are not supported")
            actual_paths = {info.filename for info in members}
            if actual_paths != set(expected_files):
                raise ArchiveError("ZIP/manifest members differ; extra=" + repr(sorted(actual_paths - set(expected_files)))
                                   + "; missing=" + repr(sorted(set(expected_files) - actual_paths)))
            by_path = {info.filename: info for info in members}
            for entry in manifest["files"]:
                info = by_path[entry["path"]]
                if info.file_size != entry["size"]:
                    raise ArchiveError("ZIP header size mismatch: " + entry["path"])
                with archive.open(info, "r") as source:
                    file_size, file_digest = _digest(source, entry["size"])
                if file_size != entry["size"] or file_digest != entry["sha256"]:
                    raise ArchiveError("member size/SHA-256 mismatch: " + entry["path"])
                audit["files"].append({**entry, "verification": "passed", "restore": "not_requested"})
            if _package_signature(package_stream) != initial_signature:
                raise ArchiveError("package changed during verification")
            audit["all_members_verified"] = True
            if command == "restore":
                states = _check_destination(target, manifest["files"])
                audit["destination_preflight_passed"] = True
                for record in audit["files"]:
                    record["restore"] = "pending"
                    record["destination_before"] = states[record["path"]]
                for record in audit["files"]:
                    record["restore"] = _write_member(archive, by_path[record["path"]], record, target)
                if _package_signature(package_stream) != initial_signature:
                    raise ArchiveError("package changed during restoration; restored members were individually verified")


def _receipt_preflight(receipt_path):
    parent_fd = _open_directory(Path(receipt_path).parent)
    try:
        try:
            os.stat(Path(receipt_path).name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise ArchiveError("receipt already exists; use a new receipt path")
    finally:
        os.close(parent_fd)


def _write_receipt(receipt_path, audit):
    parent_fd = _open_directory(Path(receipt_path).parent)
    part = ".research-receipt-" + uuid.uuid4().hex + ".part"
    created = False
    try:
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent_fd)
        created = True
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(audit, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.link(part, Path(receipt_path).name, src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd, follow_symlinks=False)
    finally:
        if created:
            os.unlink(part, dir_fd=parent_fd)
        os.close(parent_fd)


def run(command, package, manifest, receipt, target=None):
    """Run offline validation/restore and create a new terminal JSON receipt."""
    if command not in ("verify-package", "restore"):
        raise ArchiveError("unsupported command")
    if (command == "restore") != (target is not None):
        raise ArchiveError("restore requires --target; verify-package does not accept it")
    _require_safe_io()
    paths = {"package": os.path.abspath(os.fspath(package)),
             "manifest": os.path.abspath(os.fspath(manifest)),
             "receipt": os.path.abspath(os.fspath(receipt))}
    if target is not None:
        paths["target"] = os.path.abspath(os.fspath(target))
    if paths["receipt"] in (paths["package"], paths["manifest"]):
        raise ArchiveError("receipt must not be an input file")
    _receipt_preflight(paths["receipt"])
    audit = {
        "schema_version": 1, "tool": "research_archive", "command": command,
        "started_at": utc_now(), "paths": paths, "status": "running",
        "package_verified": False, "all_members_verified": False,
        "destination_preflight_passed": False, "files": [], "errors": [],
        "publication": "exclusive hard link from verified .part; no overwrite",
    }
    try:
        if target is not None:
            # The receipt must not itself become an unexpected restored file.
            receipt_relative = os.path.relpath(paths["receipt"], paths["target"])
            if receipt_relative != ".." and not receipt_relative.startswith(".." + os.path.sep):
                raise ArchiveError("receipt must be outside the restore target")
        _perform(command, paths["package"], paths["manifest"], paths.get("target"), audit)
        audit["status"] = "restored" if command == "restore" else "verified"
    except (Exception, KeyboardInterrupt) as exc:
        audit["status"] = "failed"
        audit["errors"].append({"type": type(exc).__name__, "message": str(exc)})
    audit["finished_at"] = utc_now()
    audit["counts"] = {
        "verified_files": len(audit["files"]),
        "verified_bytes": sum(entry["size"] for entry in audit["files"]),
        "written_files": sum(entry["restore"] == "written" for entry in audit["files"]),
        "reused_files": sum(entry["restore"] == "reused" for entry in audit["files"]),
    }
    _write_receipt(paths["receipt"], audit)
    return audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("verify-package", "restore"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--package", required=True, help="local ZIP file")
        subparser.add_argument("--manifest", required=True, help="local schema_version=1 JSON")
        subparser.add_argument("--receipt", required=True, help="new JSON path outside target; parent must exist")
        if command == "restore":
            subparser.add_argument("--target", required=True, help="explicit destination root; never overwritten")
    args = parser.parse_args(argv)
    try:
        audit = run(args.command, args.package, args.manifest, args.receipt, getattr(args, "target", None))
    except (Exception, KeyboardInterrupt) as exc:
        print(json.dumps({"status": "failed", "receipt_written": False,
                          "error": type(exc).__name__ + ": " + str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"status": audit["status"], "receipt": audit["paths"]["receipt"],
                      "counts": audit["counts"], "errors": audit["errors"]}, ensure_ascii=False))
    return 1 if audit["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
