"""CPU-only construction of the 127 disjoint source-baseline shard candidate.

This tool does not authorize or execute a shard.  A signed review and a
separately verified live-source guard are required before any model use.
"""
from __future__ import annotations

import hashlib
import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys

CLASSES = ("trigger", "dog", "cat", "other")
BASELINES = ("clean", "backdoor")
SHA = re.compile(r"[0-9a-f]{64}\Z")
EXPECTED_UNRESOLVED = ("source", "clean", "dog", "forest-32", 271102)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _safe_file(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("unsafe snapshot path")
    full = root / path
    for part in (full, *full.parents):
        if part == root.parent:
            break
        if part.is_symlink():
            raise ValueError("snapshot paths cannot contain symlinks")
    if not full.is_file() or not full.resolve().is_relative_to(root.resolve()):
        raise ValueError("snapshot file missing or escaped")
    return full


def verify_snapshot(root, expected_manifest_sha):
    """Verify every recorded byte without opening a source writer."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or not SHA.fullmatch(expected_manifest_sha):
        raise ValueError("snapshot root or expected SHA is invalid")
    manifest_path = _safe_file(root, "snapshot_manifest.json")
    data = manifest_path.read_bytes()
    if digest(data) != expected_manifest_sha:
        raise ValueError("snapshot manifest SHA differs")
    record = json.loads(data)
    files = record.get("files")
    if not isinstance(files, dict) or not files or record.get("counts") != {"complete": 343, "started": 1}:
        raise ValueError("snapshot inventory or expected original counts differ")
    required = {"run/images.sqlite", "run/localization.sqlite", "run/selection/selection.json", "run/run_identity.json", "run/localization_terminal.json"}
    if not required.issubset(files):
        raise ValueError("snapshot lacks required ledger or frozen selection files")
    for relative, detail in files.items():
        path = _safe_file(root, relative)
        if not isinstance(detail, dict) or type(detail.get("bytes")) is not int or detail["bytes"] < 0 or not isinstance(detail.get("sha256"), str) or not SHA.fullmatch(detail["sha256"]):
            raise ValueError("invalid snapshot file metadata")
        if path.stat().st_size != detail["bytes"]:
            raise ValueError("snapshot file size differs: " + relative)
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                hasher.update(chunk)
        if hasher.hexdigest() != detail["sha256"]:
            raise ValueError("snapshot file hash differs: " + relative)
    for relative in ("run/images.sqlite", "run/localization.sqlite"):
        wal_relative = relative + "-wal"
        wal = root / wal_relative
        if wal.exists() or wal.is_symlink():
            if wal_relative not in files or files[wal_relative]["bytes"] != 0 or wal.stat().st_size != 0:
                raise ValueError("snapshot WAL must be manifest-listed, hash-verified and empty")
    return record


def build_candidate(root, snapshot_sha, run_id, manifest_sha, rows, seeds, bindings):
    """Derive all never-reserved baseline keys and cap this shard to 1704 attempts."""
    record = verify_snapshot(root, snapshot_sha)
    root = Path(root)
    if (bindings.run_id != run_id or bindings.manifest_sha != manifest_sha or tuple(seeds) != tuple(bindings.seeds)):
        raise ValueError("frozen binding identity differs")
    contexts = sorted(row["id"] for row in rows if row["partition"] == "source")
    if len(contexts) != 128 or len(set(contexts)) != 128 or len(seeds) != 2 or len(set(seeds)) != 2:
        raise ValueError("source baseline must contain 128 unique contexts and two seeds")
    universe = {("source", version, category, context, seed) for version in BASELINES
                for category in CLASSES for context in contexts for seed in seeds}
    identity = json.loads(_safe_file(root, "run/run_identity.json").read_bytes())
    if identity.get("run_id") != run_id or identity.get("manifest_sha256") != manifest_sha or identity.get("server") != "school103":
        raise ValueError("source run identity differs")
    localization_path = _safe_file(root, "run/localization.sqlite")
    with sqlite3.connect(localization_path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("source localization snapshot fails SQLite quick_check")
        local_meta = json.loads(db.execute("SELECT value FROM metadata WHERE id=1").fetchone()[0])
        if local_meta.get("run_id") != run_id or local_meta.get("manifest_sha") != manifest_sha:
            raise ValueError("source localization ledger identity differs")
    db_path = _safe_file(root, "run/images.sqlite")
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("source image snapshot fails SQLite quick_check")
        meta = json.loads(db.execute("SELECT value FROM metadata WHERE id=1").fetchone()[0])
        if meta.get("run_id") != run_id or meta.get("manifest_sha") != manifest_sha or meta.get("selection_sha") != bindings.selection_sha or meta.get("review_sha") != bindings.review_sha:
            raise ValueError("source image ledger identity differs")
        if db.execute("SELECT COUNT(*) FROM attempt_history").fetchone()[0] or db.execute("SELECT COUNT(*) FROM gates").fetchone()[0]:
            raise ValueError("source history or gates changed; obtain a new audit")
        attempts = db.execute("SELECT run_id,state,version,class,context_id,seed,status,input_sha,mask_sha,image_sha,scores,resource FROM attempts").fetchall()
    if len(attempts) != 344 or sum(a[6] == "complete" for a in attempts) != 343 or sum(a[6] == "started" for a in attempts) != 1:
        raise ValueError("source attempts differ from the approved 343/1 boundary")
    excluded = set()
    for run, state, version, category, context, seed, status, input_sha, mask_sha, image_sha, scores, resource in attempts:
        key = (state, version, category, context, seed)
        if run != run_id or key not in universe or key in excluded or input_sha != bindings.input_hashes.get((state, context, category)) or mask_sha != bindings.mask_hashes.get(version):
            raise ValueError("source attempt differs from frozen key, input or mask")
        excluded.add(key)
        if status == "complete":
            if not isinstance(image_sha, str) or not SHA.fullmatch(image_sha) or not isinstance(json.loads(scores), dict):
                raise ValueError("source completed image lacks hash or scores")
            filename = digest(canonical((run_id, *key))) + ".png"
            image = _safe_file(root, "run/images/" + filename)
            if digest(image.read_bytes()) != image_sha or "run/images/" + filename not in record["files"]:
                raise ValueError("source completed image differs from ledger")
        elif key != EXPECTED_UNRESOLVED or image_sha is not None or scores is not None:
            raise ValueError("source unresolved attempt does not match the known interruption")
        if not isinstance(json.loads(resource), dict):
            raise ValueError("source attempt resource record invalid")
    allowed = sorted(universe - excluded)
    if len(allowed) != 1704 or EXPECTED_UNRESOLVED in allowed:
        raise ValueError("disjoint source baseline partition has the wrong size")
    keys_hash = digest(canonical(allowed))
    attempts_sha = digest(canonical(sorted(attempts, key=lambda row: row[1:6])))
    return {"task_id": "TCL-20261029-01", "run_id": run_id, "manifest_sha256": manifest_sha,
            "source_server": "school103", "destination_server": "school127", "source_snapshot_manifest_sha256": snapshot_sha,
            "source_image_ledger_sha256": record["files"]["run/images.sqlite"]["sha256"],
            "source_localization_ledger_sha256": record["files"]["run/localization.sqlite"]["sha256"],
            "selection_sha256": bindings.selection_sha, "excluded_attempts": 344,
            "source_attempts_logical_sha256": attempts_sha,
            "unresolved_excluded": list(EXPECTED_UNRESOLVED), "allowed_keys": [list(key) for key in allowed],
            "allowed_keys_sha256": keys_hash, "shard_attempt_limit": 1704,
            "baseline_combined_attempt_limit": 2048, "source_attempts_already_charged": 344,
            "status": "candidate_not_authorized"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "prompts", "context-review", "m06-review", "repository-root", "snapshot-root", "snapshot-manifest-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    root = Path(args.repository_root).resolve(strict=True)
    sys.path.insert(0, str(root / "scripts/merging/trigger_contrast_localization"))
    sys.path.insert(1, str(root / "scripts/merging"))
    from preflight import load_plan
    from bindings import load_frozen_bindings
    plan = load_plan(args.manifest, args.prompts, args.context_review, args.m06_review, root)
    binding = load_frozen_bindings(args.manifest, args.prompts, args.m06_review,
                                   Path(args.snapshot_root) / "run/selection/selection.json", root)
    result = build_candidate(args.snapshot_root, args.snapshot_manifest_sha256, plan.run_id, plan.manifest_sha,
                             plan.rows, plan.generation_seeds, binding)
    sys.stdout.buffer.write(canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
