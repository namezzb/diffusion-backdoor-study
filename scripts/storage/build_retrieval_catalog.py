#!/usr/bin/env python3
"""Offline mapping of preserved local research attachments to portable sources."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads((ROOT / path).read_text())


def main():
    git_paths = set(subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0"))
    remote = defaultdict(list)
    for index in sorted((ROOT / "storage/server-index").glob("*.jsonl")):
        for line in index.read_text().splitlines():
            row = json.loads(line)
            if row["sha256"]:
                remote[(row["sha256"], row["bytes"])].append({
                    "kind": "school_ssh", "server": row["server"],
                    "relative_path": row["relative_path"], "remote_path": row["remote_path"],
                    "index": str(index.relative_to(ROOT)),
                    "observed_at": row["inventory_observed_at"], "live_download_tested": False})
    papers = {"papers/" + p["file"]: p for p in read("papers/catalog.json")["papers"]}
    excluded = set(read("storage/audits/portable_publication_scope.json")["excluded_local_evidence"])
    result = []
    for package in read("storage/payload_packages.json")["packages"]:
        for member in read(package["manifest"])["files"]:
            path = member["path"]
            sources = []
            if path in git_paths:
                actual = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                if actual == member["sha256"]:
                    sources.append({"kind": "git", "path": path})
            candidates = remote.get((member["sha256"], member["size"]), [])
            # Prefer a source with a related path; retain bounded alternatives.
            candidates = sorted(candidates, key=lambda x: (not path.endswith(x["relative_path"]), x["server"], x["remote_path"]))
            sources.extend(candidates[:3])
            if path in papers:
                sources.append({"kind": "public_fixed_version", **papers[path]["retrieval"]})
            status = "indexed_source" if sources else "local_only_unresolved"
            if path in excluded:
                sources = []
                status = "excluded_local_portal_context"
            result.append({"path": path, "bytes": member["size"], "sha256": member["sha256"],
                           "package_group": package["name"].rsplit("-", 1)[0],
                           "sources": sources, "status": status})
    counts = Counter(r["status"] for r in result)
    unresolved = [r["path"] for r in result if r["status"] == "local_only_unresolved"]
    (ROOT / "storage/retrieval_catalog.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in sorted(result, key=lambda r: r["path"])))
    audit = {"schema_version": 1, "scope": "2137 preserved payload members; server-only files are separately listed in server-index",
             "records": len(result), "status_counts": dict(counts), "unresolved": unresolved,
             "git_sources": sum(any(s["kind"] == "git" for s in r["sources"]) for r in result),
             "school_sources": sum(any(s["kind"] == "school_ssh" for s in r["sources"]) for r in result),
             "public_fixed_version_sources": sum(any(s["kind"] == "public_fixed_version" for s in r["sources"]) for r in result),
             "local_packages_used_as_remote_sources": False, "network_accessed": False,
             "limitations": ["Server and public URL availability not live-tested in this publication.",
                             "AMAX has historical directory pointers only; full file inventory remains unknown.",
                             "Portal/login context and duplicate intermediary archives are not scientific result payloads."]}
    (ROOT / "storage/audits/retrieval_coverage.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(audit, ensure_ascii=False))
    if unresolved:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
