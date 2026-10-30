#!/usr/bin/env python3
"""Build portable attachment sources offline; frozen package manifests stay untouched.

The optional storage/asset_registry.jsonl accepts path/bytes/sha256 plus sources
(kind school_ssh or public_fixed_version), status and note. Current Git content,
papers/catalog.json and saved server-index local mappings are also discovered.
A catalog may contain several hashes for one path: these are preserved versions.
"""
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOTS = {"103": "/data1/zhangzibo/arxiv-tssa", "104": "/data2/zhangzibo/arxiv-tssa", "127": "/data1/zhangzibo/arxiv-tssa"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class CatalogError(ValueError):
    """Malformed evidence must not silently become a downloadable source."""


def relative_path(value):
    if (not isinstance(value, str) or not value or "\\" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise CatalogError("Path must be a safe repository-relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
        raise CatalogError("Unsafe relative path: " + repr(value))
    return value


def identity(path, digest, size):
    relative_path(path)
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise CatalogError("Missing or invalid SHA256 for " + path)
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise CatalogError("Invalid byte count for " + path)
    return path, digest, size


def safe_file(root, relative):
    """Return an existing regular file without traversing any symlink."""
    relative_path(relative)
    current = root
    for i, part in enumerate(PurePosixPath(relative).parts):
        current = current / part
        mode = current.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise CatalogError("Symlink is not a regular evidence file: " + relative)
        if i < len(PurePosixPath(relative).parts) - 1 and not stat.S_ISDIR(mode):
            raise CatalogError("Non-directory in evidence path: " + relative)
    if not stat.S_ISREG(current.lstat().st_mode):
        raise CatalogError("Evidence is not a regular file: " + relative)
    return current


def bytes_from_file(root, relative):
    path = safe_file(root, relative)
    # Recheck the final component at open time; evidence inputs are local, read-only.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise CatalogError("Evidence is not a regular file: " + relative)
        return handle.read()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CatalogError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def read(path, root=ROOT):
    return json.loads(bytes_from_file(Path(root), path), object_pairs_hook=unique_object)


def read_rows(root, path):
    return [json.loads(line, object_pairs_hook=unique_object)
            for line in bytes_from_file(root, path).decode("utf-8").splitlines() if line.strip()]


def public_source(source, digest, size):
    if source.get("kind", "public_fixed_version") != "public_fixed_version":
        raise CatalogError("Unknown public source kind")
    url, version = source.get("url"), source.get("version")
    if not isinstance(url, str) or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise CatalogError("Public source requires an HTTPS URL")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.port not in (None, 443)):
        raise CatalogError("Public URLs must be HTTPS without credentials, query tokens or fragments")
    if (not isinstance(version, str) or not version.strip() or version != version.strip()
            or version.lower() in {"main", "master", "latest", "head"}
            or any(ord(c) < 33 or c in "/\\?#" for c in version)):
        raise CatalogError("Public source requires an explicit fixed version")
    decoded_path = unquote(parsed.path)
    if ".." in PurePosixPath(decoded_path).parts or not re.search(
            r"(?<![A-Za-z0-9])" + re.escape(version) + r"(?![A-Za-z0-9])", decoded_path):
        raise CatalogError("Fixed version must appear as a distinct URL path token")
    if source.get("expected_sha256", digest) != digest or source.get("expected_bytes", size) != size:
        raise CatalogError("Public source hash/size differs from its artifact")
    return {**source, "kind": "public_fixed_version", "expected_sha256": digest,
            "expected_bytes": size, "live_download_tested": False}


def school_shape(source):
    server = source.get("server")
    if server not in SERVER_ROOTS:
        raise CatalogError("School source must name authorized server 103, 104 or 127")
    relative = relative_path(source.get("relative_path"))
    expected = SERVER_ROOTS[server] + "/" + relative
    if source.get("remote_path") != expected:
        raise CatalogError("School source is outside the authorized personal root")
    index = relative_path(source.get("index"))
    if not index.startswith("storage/server-index/") or not index.endswith(".jsonl"):
        raise CatalogError("School source must cite a saved server-index JSONL")
    observed = source.get("observed_at")
    if not isinstance(observed, str) or not observed.strip():
        raise CatalogError("School source needs its historical observation time")
    return {"kind": "school_ssh", "server": server, "relative_path": relative,
            "remote_path": expected, "index": index, "observed_at": observed,
            "live_download_tested": False}


def collect(root=ROOT):
    root = Path(root).resolve()
    git_paths = set(subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root).decode("utf-8").split("\0")) - {""}
    remote = defaultdict(list)
    remote_evidence = {}
    local_mappings = []
    unknown_remote_hashes = 0
    for index in sorted((root / "storage/server-index").glob("*.jsonl")):
        index_path = str(index.relative_to(root))
        for row in read_rows(root, index_path):
            source = school_shape({"server": row.get("server"), "relative_path": row.get("relative_path"),
                                   "remote_path": row.get("remote_path"), "index": index_path,
                                   "observed_at": row.get("inventory_observed_at")})
            if row.get("remote_root", SERVER_ROOTS[source["server"]]) != SERVER_ROOTS[source["server"]]:
                raise CatalogError("Saved server root does not match authorized root")
            if row.get("sha256") is None:
                unknown_remote_hashes += 1
                continue
            _, digest, size = identity(source["relative_path"], row.get("sha256"), row.get("bytes"))
            evidence_key = (index_path, source["server"], source["relative_path"], digest, size)
            if evidence_key in remote_evidence and remote_evidence[evidence_key] != source:
                raise CatalogError("Conflicting saved server evidence")
            remote_evidence[evidence_key] = source
            remote[(digest, size)].append(source)
            local = row.get("local") or {}
            if local.get("path"):
                local_key = identity(local["path"], local.get("sha256"), local.get("bytes"))
                if local_key[1:] != (digest, size):
                    raise CatalogError("Saved local/server mapping has different hashes or sizes")
                local_mappings.append((local_key, source, index_path))

    excluded_path = "storage/audits/portable_publication_scope.json"
    excluded = set(read(excluded_path, root).get("excluded_local_evidence", [])) if (root / excluded_path).exists() else set()
    for path in excluded:
        relative_path(path)
    records = {}
    counts = Counter()
    git_hashes = {}

    def add(path, digest, size, origin, sources=(), group=None, note=None):
        key = identity(path, digest, size)
        if key not in records:
            records[key] = {"path": path, "bytes": size, "sha256": digest,
                            "sources": [], "record_origins": [], "package_groups": [], "notes": []}
        record = records[key]
        record["record_origins"].append(origin)
        record["sources"].extend(sources)
        if group:
            record["package_groups"].append(group)
        if note:
            if not isinstance(note, str):
                raise CatalogError("Registry note must be a string")
            record["notes"].append(note)
        return record

    packages_path = "storage/payload_packages.json"
    packages = read(packages_path, root).get("packages", []) if (root / packages_path).exists() else []
    for package in packages:
        manifest_path = relative_path(package["manifest"])
        for member in read(manifest_path, root)["files"]:
            add(member["path"], member["sha256"], member["size"], "payload:" + manifest_path,
                group=package["name"].rsplit("-", 1)[0])
            counts["frozen_payload_members"] += 1

    papers_path = "papers/catalog.json"
    if (root / papers_path).exists():
        for paper in read(papers_path, root)["papers"]:
            path = "papers/" + relative_path(paper["file"])
            _, digest, size = identity(path, paper.get("sha256"), paper.get("bytes"))
            retrieval = paper.get("retrieval")
            sources = [public_source(retrieval, digest, size)] if retrieval else []
            add(path, digest, size, "papers:" + papers_path, sources)
            counts["paper_catalog_entries"] += 1

    for key, source, index_path in local_mappings:
        add(*key, "server_local_mapping:" + index_path, sources=[source])
        counts["saved_server_local_mappings"] += 1

    registry_path = "storage/asset_registry.jsonl"
    if (root / registry_path).exists():
        for row in read_rows(root, registry_path):
            key = identity(row.get("path"), row.get("sha256"), row.get("bytes"))
            if row.get("status", "indexed_source") not in {"indexed_source", "local_only_unresolved"}:
                raise CatalogError("Registry cannot override evidence status or exclude assets")
            sources = row.get("sources", [])
            if not isinstance(sources, list):
                raise CatalogError("Registry sources must be a list")
            validated = []
            for source in sources:
                if not isinstance(source, dict):
                    raise CatalogError("Registry source must be an object")
                if source.get("kind") == "school_ssh":
                    canonical = school_shape(source)
                    evidence_key = (canonical["index"], canonical["server"], canonical["relative_path"], key[1], key[2])
                    if remote_evidence.get(evidence_key) != canonical:
                        raise CatalogError("Registry school source has no matching saved hash evidence")
                    validated.append(canonical)
                elif source.get("kind") == "public_fixed_version":
                    validated.append(public_source(source, key[1], key[2]))
                else:
                    raise CatalogError("Registry source kind must be school_ssh or public_fixed_version; Git is checked automatically")
            add(*key, "registry:" + registry_path, sources=validated, note=row.get("note"))
            counts["manual_registry_entries"] += 1

    result = []
    for key, record in sorted(records.items()):
        path, digest, size = key
        if path in git_paths:
            if path not in git_hashes:
                try:
                    blob = bytes_from_file(root, path)
                    git_hashes[path] = (hashlib.sha256(blob).hexdigest(), len(blob))
                except (FileNotFoundError, CatalogError):
                    git_hashes[path] = None
            if git_hashes[path] == (digest, size):
                record["sources"].append({"kind": "git", "path": path})
        candidates = sorted(remote.get((digest, size), []), key=lambda source: (
            not path.endswith(source["relative_path"]), source["server"], source["remote_path"], source["index"]))
        record["sources"].extend(candidates[:3])
        record["sources"] = [json.loads(s) for s in sorted({json.dumps(source, ensure_ascii=False, sort_keys=True)
                                                          for source in record["sources"]})]
        for field in ("record_origins", "package_groups", "notes"):
            record[field] = sorted(set(record[field]))
        if record["package_groups"]:
            record["package_group"] = record["package_groups"][0]
        record["status"] = "indexed_source" if record["sources"] else "local_only_unresolved"
        if path in excluded:
            record["sources"] = []
            record["status"] = "excluded_local_portal_context"
        result.append(record)

    status_counts = Counter(row["status"] for row in result)
    unresolved = [row["path"] for row in result if row["status"] == "local_only_unresolved"]
    audit = {
        "schema_version": 2,
        "scope": "Union of frozen payload members, current paper catalog, saved server local mappings and optional explicit asset registry; server-only files remain in server-index",
        "input_counts": dict(sorted(counts.items())), "records": len(result),
        "status_counts": dict(sorted(status_counts.items())), "unresolved": unresolved,
        "git_sources": sum(any(s["kind"] == "git" for s in r["sources"]) for r in result),
        "school_sources": sum(any(s["kind"] == "school_ssh" for s in r["sources"]) for r in result),
        "public_fixed_version_sources": sum(any(s["kind"] == "public_fixed_version" for s in r["sources"]) for r in result),
        "server_records_without_hash_not_used_as_sources": unknown_remote_hashes,
        "local_packages_used_as_remote_sources": False, "network_accessed": False,
        "limitations": [
            "Server source validity is based on saved historical hash evidence; current availability is not checked.",
            "Public URLs carry explicit fixed versions and expected hashes but availability is not live-tested.",
            "Git sources require a tracked regular local file whose size and hash match; an uncommitted edit is not proof of publication.",
            "This catalog discovers only its declared inputs; unregistered new attachments must be caught by the repository-wide inventory check.",
            "AMAX has historical directory pointers only; full file inventory remains unknown.",
            "Portal/login context and duplicate intermediary archives are not scientific result payloads."]}
    return result, audit


def main(root=ROOT):
    root = Path(root).resolve()
    result, audit = collect(root)
    (root / "storage/audits").mkdir(parents=True, exist_ok=True)
    (root / "storage/retrieval_catalog.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in result), encoding="utf-8")
    (root / "storage/audits/retrieval_coverage.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))
    if audit["unresolved"]:
        raise SystemExit(1)
    return audit


if __name__ == "__main__":
    main()
