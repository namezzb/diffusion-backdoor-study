#!/usr/bin/env python3
"""List or restore explicitly selected research groups from local downloads.

This command is offline: it does not download files, install software, access
servers, change credentials, or run experiments. Obtain the ZIP files using the
catalog's Drive links first, retaining each package name plus '.zip'. Manifests
are resolved relative to --repo-root (default: this script's repository root).
Catalog and manifest paths must stay inside that root without symbolic links.

Examples, from a checkout containing storage/catalog.json and the manifests:
  python3 scripts/storage/restore_from_catalog.py --catalog storage/catalog.json --list
  python3 scripts/storage/restore_from_catalog.py --catalog storage/catalog.json \
    --downloads /absolute/downloads --target /absolute/new-research-copy \
    --group exploration-images --group diagnostic-artifacts \
    --receipts /absolute/new-receipts

--group all selects every catalog group. Restoring all is best done into an
empty, new directory: an old core snapshot can contain older documents, and
existing files with different content are deliberately never overwritten.
The receipts directory must be new, outside the target, with an existing parent.
All selected downloads must be present and marked 'roundtrip_verified'; all ZIPs
are verified and all destination conflicts checked before the first restoration.
An I/O failure or concurrent file change during actual restoration may leave
earlier, verified files restored; individual and aggregate receipts identify them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

import research_archive as core


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIED_STATUS = "roundtrip_verified"


def _absolute(path):
    return Path(os.path.abspath(os.fspath(path)))


def _inside(child, root):
    try:
        child.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_regular_file(path):
    """Inspect only an explicit file, refusing linked ancestors or leaf links."""
    parent_fd = core._open_directory(path.parent)
    try:
        info = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise core.ArchiveError("file is a symlink or is not a regular file: " + str(path))
    finally:
        os.close(parent_fd)


def _repo_file(root, value, label, allow_absolute=False):
    if not isinstance(value, str) or not value:
        raise core.ArchiveError(label + " must be a nonempty path")
    supplied = Path(value)
    if supplied.is_absolute():
        if not allow_absolute:
            raise core.ArchiveError(label + " must be repository-relative")
        path = _absolute(supplied)
        if not _inside(path, root):
            raise core.ArchiveError(label + " escapes repository root")
        core.canonical_path(path.relative_to(root).as_posix())
    else:
        path = root / core.canonical_path(value)
    _safe_regular_file(path)
    return path


def load_catalog(catalog, repo_root=DEFAULT_REPO_ROOT):
    core._require_safe_io()
    root = _absolute(repo_root)
    root_fd = core._open_directory(root)
    os.close(root_fd)
    catalog_path = _repo_file(root, os.fspath(catalog), "catalog", allow_absolute=True)
    raw = catalog_path.read_bytes()
    value = json.loads(raw, object_pairs_hook=core._json_pairs)
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
        raise core.ArchiveError("catalog requires integer schema_version=1")
    if value["schema_version"] != 1 or not isinstance(value.get("packages"), list):
        raise core.ArchiveError("unsupported catalog schema or missing packages array")
    packages = []
    names = set()
    for entry in value["packages"]:
        if not isinstance(entry, dict):
            raise core.ArchiveError("catalog package must be an object")
        name = core.canonical_path(entry.get("name"))
        group = core.canonical_path(entry.get("group"))
        if "/" in name or "/" in group or group == "all":
            raise core.ArchiveError("package name/group must be single components; 'all' is reserved")
        key = core._portable_key(name)
        if key in names:
            raise core.ArchiveError("duplicate or ambiguous catalog package name: " + name)
        names.add(key)
        manifest_path = _repo_file(root, entry.get("manifest"), "manifest")
        manifest, manifest_sha256 = core.read_manifest(manifest_path)
        drive = entry.get("drive")
        if drive is not None and not isinstance(drive, dict):
            raise core.ArchiveError("drive must be an object or null: " + name)
        drive = drive or {}
        for field in ("id", "url"):
            if drive.get(field) is not None and not isinstance(drive[field], str):
                raise core.ArchiveError("drive." + field + " must be a string or null")
        status = entry.get("verification_status", "unknown")
        if not isinstance(status, str):
            raise core.ArchiveError("verification_status must be a string")
        packages.append({
            "name": name, "group": group, "manifest": entry["manifest"],
            "manifest_path": str(manifest_path), "manifest_sha256": manifest_sha256,
            "drive": {"id": drive.get("id"), "url": drive.get("url")},
            "verification_status": status, "package": manifest["package"],
            "files": manifest["files"],
        })
    return {"repo_root": str(root), "catalog": str(catalog_path),
            "catalog_sha256": hashlib.sha256(raw).hexdigest(), "packages": packages}


def select_packages(catalog, groups):
    known = {entry["group"] for entry in catalog["packages"]}
    requested = set(groups or [])
    if not requested:
        raise core.ArchiveError("specify --group NAME (repeatable), or --group all")
    if "all" in requested:
        if len(requested) != 1:
            raise core.ArchiveError("--group all cannot be combined with other groups")
        requested = known
    unknown = requested - known
    if unknown:
        raise core.ArchiveError("unknown groups: " + ", ".join(sorted(unknown))
                                + "; available: " + ", ".join(sorted(known)))
    return [entry for entry in catalog["packages"] if entry["group"] in requested]


def list_groups(catalog, groups=None):
    packages = select_packages(catalog, groups) if groups else catalog["packages"]
    result = []
    for group in sorted({entry["group"] for entry in packages}):
        selected = [entry for entry in packages if entry["group"] == group]
        result.append({
            "group": group, "package_count": len(selected),
            "download_bytes": sum(entry["package"]["size"] for entry in selected),
            "member_bytes": sum(item["size"] for entry in selected for item in entry["files"]),
            "all_roundtrip_verified": all(entry["verification_status"] == VERIFIED_STATUS
                                           for entry in selected),
            "packages": [{"name": entry["name"], "download_name": entry["name"] + ".zip",
                          "size": entry["package"]["size"],
                          "sha256": entry["package"]["sha256"],
                          "verification_status": entry["verification_status"],
                          "drive": entry["drive"]} for entry in selected],
        })
    return {"schema_version": 1, "status": "listed", "catalog": catalog["catalog"],
            "catalog_sha256": catalog["catalog_sha256"], "groups": result}


def _merge_members(packages):
    merged, portable = {}, {}
    for package in packages:
        for entry in package["files"]:
            path, key = entry["path"], core._portable_key(entry["path"])
            if key in portable and portable[key] != path:
                raise core.ArchiveError("case/Unicode-colliding paths across packages: " + path)
            portable[key] = path
            if path in merged and merged[path] != entry:
                raise core.ArchiveError("selected packages contain conflicting versions of: " + path)
            merged[path] = entry
    core._validate_path_set(list(merged))
    return list(merged.values())


def _new_receipts_directory(path, target):
    if _inside(path, target):
        raise core.ArchiveError("receipts directory must be outside the restore target")
    parent_fd = core._open_directory(path.parent)
    try:
        # mkdir is exclusive; an existing directory or symlink is never reused.
        os.mkdir(path.name, mode=0o700, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def restore_groups(catalog, downloads, target, groups, receipts):
    packages = select_packages(catalog, groups)
    if not packages:
        raise core.ArchiveError("no packages selected")
    downloads, target, receipts = map(_absolute, (downloads, target, receipts))
    download_fd = core._open_directory(downloads)
    os.close(download_fd)
    missing, unverified, unsafe = [], [], []
    for package in packages:
        item = {"name": package["name"], "group": package["group"],
                "download_name": package["name"] + ".zip", "drive": package["drive"]}
        if package["verification_status"] != VERIFIED_STATUS:
            unverified.append({**item, "verification_status": package["verification_status"]})
        try:
            _safe_regular_file(downloads / item["download_name"])
        except FileNotFoundError:
            missing.append(item)
        except (OSError, core.ArchiveError) as exc:
            unsafe.append({**item, "error": str(exc)})
    if missing or unverified or unsafe:
        return {"schema_version": 1, "status": "blocked", "target_modified": False,
                "reason": "All selected packages must be present, safe, and roundtrip_verified.",
                "missing_packages": missing, "unverified_packages": unverified,
                "unsafe_downloads": unsafe, "receipts_written": False}

    members = _merge_members(packages)
    # Catch unsafe target roots before creating any audit directory.
    target_fd = core._open_directory(target, missing_ok=True)
    if target_fd is not None:
        os.close(target_fd)
    _new_receipts_directory(receipts, target)
    audit = {
        "schema_version": 1, "tool": "restore_from_catalog", "started_at": core.utc_now(),
        "status": "verifying", "catalog": catalog["catalog"],
        "catalog_sha256": catalog["catalog_sha256"], "repo_root": catalog["repo_root"],
        "downloads": str(downloads), "target": str(target), "receipts": str(receipts),
        "groups": sorted({entry["group"] for entry in packages}),
        "unique_member_count": len(members), "packages": [], "errors": [],
        "all_packages_verified_before_restore": False,
        "all_destinations_preflighted": False,
    }
    try:
        for index, package in enumerate(packages, 1):
            prefix = "%04d-%s" % (index, package["name"])
            receipt = receipts / (prefix + "-verify.json")
            result = core.run("verify-package", downloads / (package["name"] + ".zip"),
                              package["manifest_path"], receipt)
            record = {"name": package["name"], "group": package["group"],
                      "manifest": package["manifest"], "manifest_sha256": package["manifest_sha256"],
                      "drive": package["drive"], "verify_receipt": str(receipt),
                      "verification_status": result["status"], "restore_status": "not_started"}
            audit["packages"].append(record)
            if result["status"] != "verified":
                raise core.ArchiveError("package verification failed: " + package["name"])
            if result["manifest_sha256"] != package["manifest_sha256"]:
                raise core.ArchiveError("manifest changed after catalog loading: " + package["name"])
        audit["all_packages_verified_before_restore"] = True
        core._check_destination(target, members)
        audit["all_destinations_preflighted"] = True
        for index, (package, record) in enumerate(zip(packages, audit["packages"]), 1):
            # Core restore verifies ZIP/members again, guarding changes since preflight.
            _, current_digest = core.read_manifest(package["manifest_path"])
            if current_digest != package["manifest_sha256"]:
                raise core.ArchiveError("manifest changed before restore: " + package["name"])
            receipt = receipts / ("%04d-%s-restore.json" % (index, package["name"]))
            result = core.run("restore", downloads / (package["name"] + ".zip"),
                              package["manifest_path"], receipt, target)
            record["restore_receipt"] = str(receipt)
            record["restore_status"] = result["status"]
            record["counts"] = result["counts"]
            if result["status"] != "restored":
                raise core.ArchiveError("package restoration failed: " + package["name"])
        audit["status"] = "restored"
    except (Exception, KeyboardInterrupt) as exc:
        audit["status"] = "failed"
        audit["errors"].append({"type": type(exc).__name__, "message": str(exc)})
    audit["finished_at"] = core.utc_now()
    audit["counts"] = {
        "selected_packages": len(packages),
        "verified_packages": sum(p["verification_status"] == "verified" for p in audit["packages"]),
        "restored_packages": sum(p["restore_status"] == "restored" for p in audit["packages"]),
        "written_files": sum(p.get("counts", {}).get("written_files", 0) for p in audit["packages"]),
        "reused_files": sum(p.get("counts", {}).get("reused_files", 0) for p in audit["packages"]),
    }
    audit["summary_receipt"] = str(receipts / "summary.json")
    core._write_receipt(receipts / "summary.json", audit)
    return audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog", required=True, help="catalog inside repository root")
    parser.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    parser.add_argument("--list", action="store_true", help="list sizes, Drive links, and verified status only")
    parser.add_argument("--group", action="append", help="selected group; repeatable; or all")
    parser.add_argument("--downloads", help="explicit local directory containing name.zip files")
    parser.add_argument("--target", help="explicit restoration root; empty directory recommended for all")
    parser.add_argument("--receipts", help="new audit directory outside target; parent must exist")
    args = parser.parse_args(argv)
    if not args.list and not all((args.downloads, args.target, args.receipts, args.group)):
        parser.error("restore requires --downloads, --target, --receipts, and --group")
    try:
        catalog = load_catalog(args.catalog, args.repo_root)
        result = list_groups(catalog, args.group) if args.list else restore_groups(
            catalog, args.downloads, args.target, args.group, args.receipts)
    except (Exception, KeyboardInterrupt) as exc:
        result = {"status": "failed", "error": type(exc).__name__ + ": " + str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("listed", "restored") else 1


if __name__ == "__main__":
    sys.exit(main())
