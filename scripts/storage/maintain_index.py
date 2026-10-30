#!/usr/bin/env python3
"""Offline repository inventory, change routing, and human closeout receipt gate.

No server, cloud, GPU, credential, or ignored-file content is accessed.  A check
in staged mode reads every indexed payload and policy from Git's index, so an
unstaged correction cannot make an incomplete commit pass.
"""

import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import subprocess
import sys
from urllib.parse import unquote, urlsplit


POLICY = "storage/index_policy.json"
SERVER_ROOTS = {"103": "/data1/zhangzibo/arxiv-tssa", "104": "/data2/zhangzibo/arxiv-tssa", "127": "/data1/zhangzibo/arxiv-tssa"}


class IndexError_(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args, input_data=None):
    process = subprocess.run(["git", "-C", str(root), *args], input=input_data,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    if process.returncode:
        raise IndexError_("git {} failed: {}".format(
            args[0], process.stderr.decode("utf-8", errors="replace").strip()))
    return process.stdout


def safe_path(value):
    if (not isinstance(value, str) or not value or value.startswith("/") or
            "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value) or
            any(p in ("", ".", "..") for p in value.split("/"))):
        raise IndexError_("unsafe repository path: {!r}".format(value))
    return value


def link_destination(path, text):
    if (not text or text.startswith("/") or "\\" in text or
            any(ord(c) < 32 or ord(c) == 127 for c in text)):
        raise IndexError_("unsafe symlink {} -> {!r}".format(path, text))
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), text))
    if resolved == ".." or resolved.startswith("../") or resolved.startswith("/"):
        raise IndexError_("symlink escapes repository: {} -> {}".format(path, text))
    return resolved


def make_blob(mode, data):
    if mode not in ("100644", "100755", "120000"):
        raise IndexError_("unsupported Git entry mode: {}".format(mode))
    return {"mode": mode, "kind": "symlink" if mode == "120000" else "file",
            "data": data, "sha256": digest(data)}


def git_view(root, revision=None):
    entries = {}
    if revision is None:
        raw = git(root, "ls-files", "--stage", "-z")
        for record in raw.split(b"\0"):
            if not record:
                continue
            metadata, name = record.split(b"\t", 1)
            mode, oid, stage = metadata.decode("ascii").split()
            path = safe_path(name.decode("utf-8"))
            if stage != "0":
                raise IndexError_("unmerged index entry: " + path)
            entries[path] = (mode, oid)
    else:
        raw = git(root, "ls-tree", "-r", "-z", revision)
        for record in raw.split(b"\0"):
            if not record:
                continue
            metadata, name = record.split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split()
            if kind != "blob":
                raise IndexError_("unsupported Git tree entry: " + name.decode("utf-8"))
            entries[safe_path(name.decode("utf-8"))] = (mode, oid)
    # Batch reads are local Git object reads, not a fetch or other network action.
    oids = list(dict.fromkeys(oid for _, oid in entries.values()))
    output = git(root, "cat-file", "--batch", input_data=("\n".join(oids) + "\n").encode()) if oids else b""
    content = {}
    offset = 0
    for oid in oids:
        end = output.index(b"\n", offset)
        returned, kind, size = output[offset:end].split()
        if returned.decode() != oid or kind != b"blob":
            raise IndexError_("unexpected Git object response")
        offset = end + 1
        content[oid] = output[offset:offset + int(size)]
        offset += int(size) + 1
    return {path: make_blob(mode, content[oid]) for path, (mode, oid) in entries.items()}


def parent_fd(root, path):
    """Open every directory component without following a link, including races."""
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(root, flags)
    visited = []
    try:
        for part in PurePosixPath(path).parts[:-1]:
            visited.append(part)
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                raise
            except OSError as error:
                raise IndexError_("parent is not a real directory: " + "/".join(visited)) from error
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def work_view(root):
    names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    result = {}
    for name in sorted(set(names.split(b"\0")) - {b""}):
        path = safe_path(name.decode("utf-8"))
        try:
            directory = parent_fd(root, path)
        except FileNotFoundError:
            continue
        try:
            name = PurePosixPath(path).name
            try:
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode):
                data = os.fsencode(os.readlink(name, dir_fd=directory))
                mode = "120000"
            elif stat.S_ISREG(info.st_mode):
                fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory)
                with os.fdopen(fd, "rb") as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise IndexError_("file type changed while reading: " + path)
                    data = stream.read()
                    after = os.fstat(stream.fileno())
                if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                    raise IndexError_("file changed while reading: " + path)
                mode = "100755" if before.st_mode & 0o111 else "100644"
            else:
                raise IndexError_("not a regular file or symlink: " + path)
        finally:
            os.close(directory)
        result[path] = make_blob(mode, data)
    return result


def parse_json(view, path):
    safe_path(path)
    blob = view.get(path)
    if not blob or blob["kind"] != "file":
        raise IndexError_("missing regular JSON file: " + path)
    try:
        return json.loads(blob["data"])
    except (ValueError, UnicodeError) as error:
        raise IndexError_("invalid JSON in {}: {}".format(path, error)) from error


def load_policy(view):
    policy = parse_json(view, POLICY)
    if policy.get("schema_version") != 1:
        raise IndexError_("policy schema_version must be 1")
    for key in ("inventory", "receipt"):
        safe_path(policy[key])
    if policy["inventory"] == policy["receipt"] or POLICY in (policy["inventory"], policy["receipt"]):
        raise IndexError_("policy, receipt and inventory must be distinct")
    seen = set()
    for route in policy["routes"]:
        prefix = route["prefix"]
        if prefix:
            if not prefix.endswith("/"):
                raise IndexError_("route prefix must end with /: " + prefix)
            safe_path(prefix[:-1])
        if prefix in seen:
            raise IndexError_("duplicate route: " + prefix)
        seen.add(prefix)
        safe_path(route["index"])
        for related in route.get("related_records", []):
            safe_path(related)
    for key in ("required_entries", "active_indexes"):
        for path in policy.get(key, []):
            safe_path(path)
    for item in policy.get("link_exceptions", []):
        safe_path(item["source"])
        if not item.get("target") or not item.get("reason", "").strip():
            raise IndexError_("link exception requires exact target and reason")
    for item in policy.get("ignored_paths", []):
        safe_path(item["path"])
        if not item.get("reason", "").strip():
            raise IndexError_("ignored path requires reason")
    for item in policy.get("local_exclusions", []):
        if not item.get("pattern") or not item.get("reason", "").strip():
            raise IndexError_("local exclusion requires pattern and reason")
    return policy


def route_for(path, policy):
    matches = [route for route in policy["routes"]
               if (route["prefix"] and path.startswith(route["prefix"])) or
               (not route["prefix"] and "/" not in path)]
    if not matches:
        raise IndexError_("unrouted file (register its directory explicitly): " + path)
    return max(matches, key=lambda route: len(route["prefix"]))


def owner(path, policy):
    return route_for(path, policy)["index"]


def review_targets(changes, policy):
    targets = set()
    for row in changes:
        route = route_for(row["path"], policy)
        targets.add(route["index"])
        targets.update(route.get("related_records", []))
    return targets


def resolve_view(path, view):
    seen = set()
    current = path
    for _ in range(64):
        if current in seen:
            raise IndexError_("symlink cycle: " + path)
        seen.add(current)
        parts = current.split("/")
        redirected = False
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            blob = view.get(prefix)
            if blob and blob["kind"] == "symlink":
                text = blob["data"].decode("utf-8")
                target = link_destination(prefix, text)
                current = posixpath.normpath(posixpath.join(target, *parts[index:]))
                if current == ".." or current.startswith("../"):
                    raise IndexError_("symlink chain escapes repository: " + path)
                redirected = True
                break
        if not redirected:
            return current
    raise IndexError_("symlink chain too long: " + path)


def exists_view(path, view):
    target = resolve_view(path, view)
    return target in view or any(p.startswith(target.rstrip("/") + "/") for p in view)


def inventory_rows(view, policy):
    rows = []
    inventory = policy["inventory"]
    for path in sorted(set(view) | {inventory}):
        index = owner(path, policy)
        if index not in view or view[index]["kind"] != "file":
            raise IndexError_("owner index missing regular file: " + index)
        if path == inventory:
            rows.append({"path": path, "kind": "file", "mode": "100644", "bytes": None,
                         "sha256": None, "owner_index": index, "self_generated": True})
            continue
        blob = view[path]
        row = {"path": path, "kind": blob["kind"], "mode": blob["mode"],
               "bytes": len(blob["data"]), "sha256": blob["sha256"], "owner_index": index}
        if blob["kind"] == "symlink":
            text = blob["data"].decode("utf-8")
            row["link_text"] = text
            row["relative_target"] = link_destination(path, text)
            resolved = resolve_view(path, view)
            if not exists_view(resolved, view):
                raise IndexError_("dangling tracked symlink: {} -> {}".format(path, text))
        rows.append(row)
    return rows


def serialize_rows(rows):
    return ("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                    for row in rows)).encode("utf-8")


def jsonl(view, path):
    blob = view.get(path)
    if not blob:
        return []
    if blob["kind"] != "file":
        raise IndexError_("JSONL must be regular: " + path)
    try:
        return [json.loads(line) for line in blob["data"].splitlines() if line.strip()]
    except (ValueError, UnicodeError) as error:
        raise IndexError_("invalid JSONL in {}: {}".format(path, error)) from error


def attachment_paths(view, policy, downloadable_only=False):
    result = {item["path"] for item in policy.get("ignored_paths", [])}
    for row in jsonl(view, policy.get("retrieval_catalog", "storage/retrieval_catalog.jsonl")):
        if row.get("path") and (not downloadable_only or
                                (row.get("status") == "indexed_source" and row.get("sources"))):
            result.add(safe_path(row["path"]))
    if not downloadable_only and "papers/catalog.json" in view:
        for row in parse_json(view, "papers/catalog.json").get("papers", []):
            if row.get("file"):
                result.add(safe_path("papers/" + row["file"]))
    if not downloadable_only:
        for path in view:
            if path.startswith("storage/server-index/") and path.endswith(".jsonl"):
                for row in jsonl(view, path):
                    local = row.get("local") or {}
                    if local.get("path"):
                        result.add(safe_path(local["path"]))
    return result


def markdown_targets(text):
    # The gate checks ordinary inline links and reference definitions.  Fenced
    # examples and inline code are not actual navigation links.
    text = re.sub(r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$", "", text)
    text = re.sub(r"`[^`\n]*`", "", text)
    values = re.findall(r"!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^()\n]+)\s*\)", text)
    values += re.findall(r"(?m)^\s{0,3}\[[^\]\n]+\]:\s*(<[^>\n]+>|\S+)", text)
    for value in values:
        value = value.strip()
        if value.startswith("<") and ">" in value:
            yield value[1:value.index(">")]
        else:
            yield re.sub(r"\s+[\"'][^\n]*[\"']\s*$", "", value).strip()


def check_links(view, policy):
    exceptions = {(item["source"], item["target"]): item["reason"]
                  for item in policy.get("link_exceptions", [])}
    attachments = attachment_paths(view, policy, downloadable_only=True)
    checked = 0
    excepted = 0
    errors = []
    for source in policy.get("active_indexes", []):
        if source not in view or view[source]["kind"] != "file":
            errors.append("active index missing regular file: " + source)
            continue
        for target in markdown_targets(view[source]["data"].decode("utf-8")):
            parsed = urlsplit(target)
            if parsed.scheme == "file":
                errors.append("nonportable file URL: {} -> {}".format(source, target))
                continue
            if not parsed.path or parsed.scheme or parsed.netloc:
                continue
            checked += 1
            if (source, target) in exceptions:
                excepted += 1
                continue
            path = unquote(parsed.path)
            path = re.sub(r":\d+$", "", path)
            if path.startswith("/"):
                errors.append("nonportable absolute link: {} -> {}".format(source, target))
                continue
            relative = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
            if relative in (".", ""):
                continue
            if relative == ".." or relative.startswith("../") or "\\" in relative:
                errors.append("link escapes repository: {} -> {}".format(source, target))
            elif not exists_view(relative, view) and relative not in attachments:
                errors.append("missing local link: {} -> {}".format(source, target))
    return errors, {"local_links_checked": checked, "link_exceptions_used": excepted}


def artifact_identity(path, sha, size):
    safe_path(path)
    if (not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha) or
            isinstance(size, bool) or not isinstance(size, int) or size < 0):
        raise IndexError_("invalid artifact identity: " + path)
    return path, sha, size


def canonical_source(source, sha, size, paper=False):
    """Mirror only the builder's declared source fields and offline additions."""
    if not isinstance(source, dict):
        raise IndexError_("source must be an object")
    kind = source.get("kind", "public_fixed_version" if paper else None)
    if source.get("live_download_tested", False) is not False:
        raise IndexError_("offline catalog source must not claim a live download test")
    if kind == "git":
        return {"kind": kind, "path": safe_path(source.get("path"))}
    if kind == "school_ssh":
        server = source.get("server")
        if server not in SERVER_ROOTS:
            raise IndexError_("school source must name authorized server 103, 104 or 127")
        relative = safe_path(source.get("relative_path"))
        if source.get("remote_path") != SERVER_ROOTS[server] + "/" + relative:
            raise IndexError_("school source outside authorized personal root")
        index = safe_path(source.get("index"))
        if not index.startswith("storage/server-index/") or not index.endswith(".jsonl"):
            raise IndexError_("school source needs a server-index JSONL")
        observed = source.get("observed_at")
        if not isinstance(observed, str) or not observed.strip():
            raise IndexError_("school source needs its observation time")
        return {"kind": kind, "server": server, "relative_path": relative, "remote_path": source["remote_path"],
                "index": index, "observed_at": observed, "live_download_tested": False}
    if kind != "public_fixed_version":
        raise IndexError_("unknown source kind: " + str(kind))
    url, version = source.get("url"), source.get("version")
    if not isinstance(url, str) or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise IndexError_("public source needs an HTTPS URL")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or
            parsed.query or parsed.fragment or parsed.port not in (None, 443)):
        raise IndexError_("public source URL must be HTTPS without credentials, tokens or fragments")
    if (not isinstance(version, str) or not version or version != version.strip() or
            version.lower() in {"main", "master", "latest", "head"} or
            any(ord(c) < 33 or c in "/\\?#" for c in version)):
        raise IndexError_("public source needs a fixed version")
    decoded = unquote(parsed.path)
    if ".." in PurePosixPath(decoded).parts or not re.search(
            r"(?<![A-Za-z0-9])" + re.escape(version) + r"(?![A-Za-z0-9])", decoded):
        raise IndexError_("public fixed version must appear in URL path")
    if source.get("expected_sha256", sha) != sha or source.get("expected_bytes", size) != size:
        raise IndexError_("public expected hash/size differs from artifact")
    return {**source, "kind": kind, "expected_sha256": sha, "expected_bytes": size, "live_download_tested": False}


def catalog_consistency(view, policy):
    """Validate current Git sources and registration coverage, never fetch data."""
    catalog_path = policy.get("retrieval_catalog", "storage/retrieval_catalog.jsonl")
    registry_path = "storage/asset_registry.jsonl"
    papers_path = "papers/catalog.json"
    if not any(path in view for path in (catalog_path, registry_path, papers_path)):
        return [], {"catalog_consistency_checked": False}
    errors = []
    if catalog_path not in view:
        errors.append("retrieval catalog missing; run scripts/storage/build_retrieval_catalog.py")
    rows = jsonl(view, catalog_path)
    identities = set()
    catalog_sources = {}
    catalog_public_sources = {}
    declared_public_sources = {}
    server_evidence = {}
    excluded_path = "storage/audits/portable_publication_scope.json"
    excluded = set(parse_json(view, excluded_path).get("excluded_local_evidence", [])) if excluded_path in view else set()
    git_sources = 0
    school_sources = 0
    public_sources = 0
    for row in rows:
        key = artifact_identity(row.get("path"), row.get("sha256"), row.get("bytes"))
        path, sha, size = key
        identities.add(key)
        catalog_sources.setdefault(key, set())
        sources = row.get("sources") or []
        if not isinstance(sources, list):
            errors.append("retrieval sources must be a list: " + path)
            continue
        if row.get("status") == "local_only_unresolved":
            errors.append("unresolved retrieval artifact: " + path)
        elif row.get("status") == "excluded_local_portal_context":
            if path not in excluded or sources:
                errors.append("undocumented or sourced portal exclusion: " + path)
        elif row.get("status") != "indexed_source":
            errors.append("unknown retrieval status: " + path)
        if row.get("status") == "indexed_source" and not sources:
            errors.append("indexed_source has no sources: " + path)
        for source in sources:
            try:
                canonical = canonical_source(source, sha, size)
            except (IndexError_, ValueError) as error:
                errors.append("invalid retrieval source for {}: {}".format(path, error))
                continue
            catalog_sources[key].add(json.dumps(canonical, sort_keys=True))
            if canonical["kind"] == "git":
                git_sources += 1
                source_path = canonical["path"]
                blob = view.get(source_path)
                if (not blob or blob["kind"] != "file" or blob["sha256"] != sha or len(blob["data"]) != size):
                    errors.append("retrieval Git source is stale: {} -> {}; run scripts/storage/build_retrieval_catalog.py and preserve historical versions".format(path, source_path))
            elif canonical["kind"] == "school_ssh":
                school_sources += 1
                index = canonical["index"]
                if index not in server_evidence:
                    server_evidence[index] = {
                        (item.get("server"), item.get("relative_path"), item.get("remote_path"), item.get("bytes"),
                         item.get("sha256"), item.get("inventory_observed_at")) for item in jsonl(view, index)}
                signature = (canonical["server"], canonical["relative_path"], canonical["remote_path"], size, sha, canonical["observed_at"])
                if signature not in server_evidence[index]:
                    errors.append("school source has no matching saved index evidence: {} -> {}; run scripts/storage/build_retrieval_catalog.py".format(path, index))
            else:
                public_sources += 1
                catalog_public_sources.setdefault(key, set()).add(json.dumps(canonical, sort_keys=True))
    registered = jsonl(view, registry_path)
    papers = parse_json(view, papers_path).get("papers", []) if papers_path in view else []
    expected = [(row.get("path"), row.get("sha256"), row.get("bytes"), registry_path, row.get("sources", []), False) for row in registered]
    expected.extend(("papers/" + safe_path(row.get("file")), row.get("sha256"), row.get("bytes"), papers_path,
                     [row["retrieval"]] if row.get("retrieval") else [], True) for row in papers)
    for path, sha, size, origin, sources, is_paper in expected:
        key = artifact_identity(path, sha, size)
        if key not in identities:
            errors.append("registered artifact missing from retrieval catalog: {} in {}; run scripts/storage/build_retrieval_catalog.py".format(path, origin))
        if not isinstance(sources, list):
            errors.append("registered sources must be a list: " + path)
            continue
        for source in sources:
            try:
                canonical = canonical_source(source, sha, size, paper=is_paper)
                if canonical["kind"] == "git":
                    raise IndexError_("registry must not hand-assert a Git source")
                if canonical["kind"] == "public_fixed_version":
                    declared_public_sources.setdefault(key, set()).add(json.dumps(canonical, sort_keys=True))
                if json.dumps(canonical, sort_keys=True) not in catalog_sources.get(key, set()):
                    errors.append("registered source missing or changed in retrieval catalog: {} in {}; run scripts/storage/build_retrieval_catalog.py".format(path, origin))
            except (IndexError_, ValueError) as error:
                errors.append("invalid registered source for {}: {}".format(path, error))
    # Public locations come only from the current registry/paper declarations;
    # frozen payload manifests establish identity, not an everlasting URL grant.
    # Git and school sources already have independent blob/index evidence above.
    for key, actual_sources in catalog_public_sources.items():
        removed = actual_sources - declared_public_sources.get(key, set())
        if removed:
            errors.append("public sources removed from current declarations remain in retrieval catalog: {} ({} sources); run scripts/storage/build_retrieval_catalog.py and explicitly register any retained historical source".format(key[0], len(removed)))
    return errors, {"catalog_consistency_checked": True, "catalog_git_sources_checked": git_sources,
                    "catalog_school_sources_checked": school_sources, "catalog_public_sources_checked": public_sources,
                    "registered_artifact_identities_checked": len(expected)}


def changed_entries(before, after, excluded=()):
    result = []
    for path in sorted((set(before) | set(after)) - set(excluded)):
        old, new = before.get(path), after.get(path)
        if old and new and (old["mode"], old["sha256"]) == (new["mode"], new["sha256"]):
            continue
        result.append({"path": path, "kind": new["kind"] if new else "deleted",
                       "sha256": new["sha256"] if new else None})
    return result


def receipt_check(root, view, policy):
    receipt = parse_json(view, policy["receipt"])
    head = git(root, "rev-parse", "HEAD").decode().strip()
    head_view = git_view(root, head)
    dirty = bool(changed_entries(head_view, view))
    base = receipt.get("base_commit")
    if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base):
        raise IndexError_("receipt base_commit must be a full commit hash")
    if dirty:
        if base != head:
            raise IndexError_("receipt base_commit is stale; expected current HEAD " + head)
        before = head_view
    else:
        # A clean clone verifies the recorded previous base to current HEAD,
        # rather than demanding a never-ending new receipt for a clean tree.
        git(root, "merge-base", "--is-ancestor", base, head)
        before = git_view(root, base)
    excluded = (policy["inventory"], policy["receipt"])
    changes = changed_entries(before, view, excluded)
    if not isinstance(receipt.get("summary"), str) or not receipt["summary"].strip():
        raise IndexError_("receipt needs a human review summary")
    recorded = receipt.get("reviewed_changes")
    if not isinstance(recorded, list):
        raise IndexError_("receipt reviewed_changes must be a list")
    normalized = []
    seen = set()
    for row in recorded:
        path = safe_path(row["path"])
        if path in seen:
            raise IndexError_("duplicate reviewed change: " + path)
        seen.add(path)
        normalized.append({"path": path, "kind": row.get("kind"), "sha256": row.get("sha256")})
    if sorted(normalized, key=lambda row: row["path"]) != changes:
        actual = {row["path"]: row for row in changes}
        acknowledged = {row["path"]: row for row in normalized}
        missing = sorted(set(actual) - set(acknowledged))
        extra = sorted(set(acknowledged) - set(actual))
        stale = sorted(path for path in set(actual) & set(acknowledged) if actual[path] != acknowledged[path])
        raise IndexError_("receipt changes do not match: missing={}, extra={}, stale_sha_or_kind={}".format(missing, extra, stale))
    required = review_targets(changes, policy)
    decisions = receipt.get("index_decisions")
    if not isinstance(decisions, list):
        raise IndexError_("receipt index_decisions must be a list")
    decision_map = {}
    changed = {row["path"]: row for row in changes}
    indexes = {route["index"] for route in policy["routes"]} | set(policy.get("active_indexes", []))
    indexes.update(path for route in policy["routes"] for path in route.get("related_records", []))
    for decision in decisions:
        path = safe_path(decision["path"])
        if path in decision_map or path not in indexes:
            raise IndexError_("duplicate or unknown decision index: " + path)
        if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
            raise IndexError_("index decision needs a reason: " + path)
        action = decision.get("action")
        actually_updated = path in changed and changed[path]["kind"] != "deleted"
        if action not in ("updated", "unchanged") or ((action == "updated") != actually_updated):
            raise IndexError_("index decision disagrees with actual change: " + path)
        decision_map[path] = decision
    missing = sorted(required - set(decision_map))
    if missing:
        raise IndexError_("receipt missing index decisions: " + ", ".join(missing))
    return {"receipt_base_commit": base, "reviewed_change_count": len(changes),
            "required_index_decisions": len(required), "receipt_mode": "pending_changes" if dirty else "committed_snapshot"}


def local_coverage(root, view, policy, staged=False):
    names = git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    paths = set()
    for name in names.split(b"\0"):
        if not name:
            continue
        path = name.decode("utf-8")
        # Git collapses ignored nested repositories to a directory marker.
        # Keep that marker distinct from any registered ordinary attachment.
        paths.add(safe_path(path[:-1]) + "/" if path.endswith("/") else safe_path(path))
    directories = {path for path in paths if path.endswith("/")}
    known = attachment_paths(view, policy)
    patterns = [item["pattern"] for item in policy.get("local_exclusions", [])]
    excluded = [path for path in paths if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)]
    remaining = set(paths) - set(excluded)
    missing = sorted(remaining - directories - known)
    errors = ["ignored file has no index or explicit local exclusion: " + path for path in missing]
    errors.extend("ignored directory has no explicit local exclusion: " + path
                  for path in sorted(remaining & directories))
    untracked_missing = []
    if staged:
        untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z")
        untracked_missing = sorted({safe_path(name.decode("utf-8")) for name in untracked.split(b"\0") if name} - set(view))
        errors.extend("new nonignored file is absent from staged tree: " + path for path in untracked_missing)
    return errors, {"ignored_scanned": len(paths), "ignored_excluded": len(excluded),
                    "ignored_indexed": len((remaining - directories) & known), "untracked_not_staged": len(untracked_missing)}


def refresh(root, view, policy):
    path = policy["inventory"]
    rows = inventory_rows(view, policy)
    data = serialize_rows(rows)
    # Open without following links; refresh is the only writing operation and
    # does not edit human state, receipts, historical evidence or Git's index.
    try:
        directory = parent_fd(root, path)
    except FileNotFoundError as error:
        raise IndexError_("inventory parent must already exist") from error
    try:
        fd = os.open(PurePosixPath(path).name,
                     os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
                     0o644, dir_fd=directory)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
    finally:
        os.close(directory)
    return {"status": "refreshed", "inventory": path, "records": len(rows), "network_accessed": False}


def check(root, view, policy, scan_local=True, staged=False):
    rows = inventory_rows(view, policy)
    path = policy["inventory"]
    expected = serialize_rows(rows)
    errors = []
    actual = view.get(path)
    if not actual or actual["kind"] != "file":
        errors.append("inventory missing: " + path)
    elif actual["data"] != expected:
        saved_rows = jsonl(view, path)
        saved = {row.get("path"): row for row in saved_rows}
        current = {row["path"]: row for row in rows}
        missing = sorted(set(current) - set(saved))
        removed = sorted(set(saved) - set(current))
        changed = sorted(p for p in set(saved) & set(current) if saved[p] != current[p])
        errors.append("inventory stale: missing={}, removed={}, changed={}; run refresh after reviewing edits".format(missing, removed, changed))
    for required in policy.get("required_entries", []):
        if not exists_view(required, view):
            errors.append("required entry missing: " + required)
    for related in {path for route in policy["routes"] for path in route.get("related_records", [])}:
        if related not in view or view[related]["kind"] != "file":
            errors.append("related record missing regular file: " + related)
    link_errors, details = check_links(view, policy)
    errors.extend(link_errors)
    catalog_errors, catalog_details = catalog_consistency(view, policy)
    errors.extend(catalog_errors)
    details.update(catalog_details)
    try:
        details.update(receipt_check(root, view, policy))
    except (IndexError_, KeyError, TypeError) as error:
        errors.append("closeout receipt: " + str(error))
    if scan_local:
        local_errors, local_stats = local_coverage(root, view, policy, staged)
        errors.extend(local_errors)
        details.update(local_stats)
    return {"status": "failed" if errors else "passed", "records": len(rows),
            "errors": errors, "network_accessed": False, "local_scan": scan_local, **details}


def impact(root, view, policy):
    head = git(root, "rev-parse", "HEAD").decode().strip()
    changes = changed_entries(git_view(root, head), view, (policy["inventory"], policy["receipt"]))
    return {"status": "impact_only", "base_commit": head,
            "changes": [{**row, "owner_index": owner(row["path"], policy)} for row in changes],
            "review_indexes": sorted(review_targets(changes, policy)),
            "network_accessed": False}


def main(argv=None, repo=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("refresh", "check", "impact"))
    parser.add_argument("--staged", action="store_true", help="read only Git index blobs; not valid for refresh")
    parser.add_argument("--no-local-scan", action="store_true", help="check only portable Git content (CI)")
    args = parser.parse_args(argv)
    try:
        root = Path(repo) if repo is not None else Path(__file__).resolve().parents[2]
        root = Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        if args.command == "refresh" and (args.staged or args.no_local_scan):
            raise IndexError_("refresh only supports the worktree view")
        if args.no_local_scan and args.command != "check":
            raise IndexError_("--no-local-scan is only valid for check")
        view = git_view(root) if args.staged else work_view(root)
        policy = load_policy(view)
        if args.command == "refresh":
            result = refresh(root, view, policy)
        elif args.command == "impact":
            result = impact(root, view, policy)
        else:
            result = check(root, view, policy, not args.no_local_scan, staged=args.staged)
        result["view"] = "staged" if args.staged else "worktree"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["status"] == "failed" else 0
    except (IndexError_, KeyError, TypeError, OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"status": "failed", "errors": [str(error)], "network_accessed": False}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
