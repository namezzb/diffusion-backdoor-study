"""Read-only, non-executable accounting preview for TCL ledger snapshots.

This is not a recovery runner or proof that old writers are retired.  Only
immutable snapshots with an empty/absent WAL are accepted; ambiguous source
identities and cross-source sample collisions fail closed.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import itertools
import json
import math
from pathlib import Path
import sqlite3

from bindings import input_digest

KEY = ("run_id", "state", "version", "class", "context_id", "seed")
MANIFEST_SHA = "c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa"
EMPTY_MASK_SHA = hashlib.sha256(b"{}").hexdigest()


def preview(manifest_path, prompts_path, sources):
    manifest_bytes = Path(manifest_path).read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA:
        raise ValueError("unexpected frozen manifest")
    manifest = json.loads(manifest_bytes)
    prompt_bytes = Path(prompts_path).read_bytes()
    if hashlib.sha256(prompt_bytes).hexdigest() != manifest["prompts_sha256"]:
        raise ValueError("unexpected frozen prompts")
    prompts = {(r["partition"], r["id"]): r for r in map(json.loads, prompt_bytes.splitlines())}
    logical_sources, keys, records, source_hashes = {}, {}, [], {}
    metadata = None
    for identity, filename in sources:
        if not identity:
            raise ValueError("logical source identity is required")
        path = Path(filename)
        wal = Path(str(path) + "-wal")
        if path.is_symlink() or not path.is_file() or (wal.exists() and wal.stat().st_size):
            raise ValueError("source is not a static standalone snapshot")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if identity in logical_sources:
            if logical_sources[identity] != digest:
                raise ValueError("divergent snapshots of the same logical source")
            continue
        if digest in source_hashes and source_hashes[digest] != identity:
            raise ValueError("same snapshot given different source identities")
        logical_sources[identity], source_hashes[digest] = digest, identity
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            db.row_factory = sqlite3.Row
            source_meta = json.loads(db.execute("select value from metadata where id=1").fetchone()[0])
            if (source_meta.get("run_id") != manifest["run_id"] or source_meta.get("manifest_sha") != MANIFEST_SHA
                    or source_meta.get("seeds") != manifest["generation_seeds"]):
                raise ValueError("snapshot identity differs from frozen inputs")
            if metadata is None:
                metadata = source_meta
            elif metadata != source_meta:
                raise ValueError("snapshot metadata mismatch")
            for table in ("attempts", "attempt_history"):
                for raw in db.execute("select * from " + table):
                    row = dict(raw)
                    key = tuple(row[k] for k in KEY)
                    if key in keys and keys[key] != identity:
                        raise ValueError("cross-source sample collision needs manual attribution")
                    keys[key] = identity
                    prompt = prompts.get((row["state"], row["context_id"]))
                    if (prompt is None or row["version"] not in ("clean", "backdoor")
                            or row["seed"] not in manifest["generation_seeds"]
                            or row["input_sha"] != input_digest(prompt, row["class"])
                            or row["mask_sha"] != EMPTY_MASK_SHA):
                        raise ValueError("attempt outside verified baseline inputs")
                    if table == "attempts" and row["status"] not in ("complete", "started"):
                        raise ValueError("unsupported current attempt state")
                    if row["status"] == "complete":
                        score = json.loads(row["scores"] or "null")
                        if (not isinstance(score, dict) or set(score) != {"vit_class", "clip_score"}
                                or type(score["vit_class"]) is not int or not 0 <= score["vit_class"] < 1000
                                or type(score["clip_score"]) not in (float, int)
                                or not math.isfinite(score["clip_score"]) or not 0 <= score["clip_score"] <= 100):
                            raise ValueError("invalid score record")
                    records.append({"source": identity, "table": table, "row": row})
    if not sources or metadata is None:
        raise ValueError("at least one snapshot is required")
    if len(records) > 16384 or sum(r["row"]["state"] == "source" for r in records) > 8192:
        raise ValueError("original attempt budget exceeded")
    expected = set(itertools.product([manifest["run_id"]], ["source"], ["clean", "backdoor"],
                                     ["trigger", "dog", "cat", "other"],
                                     metadata["prompt_ids"]["source"], manifest["generation_seeds"]))
    if len(expected) != 2048 or not set(keys).issubset(expected):
        raise ValueError("unexpected baseline key set")
    return {"status": "provisional_not_executable", "manifest_sha256": MANIFEST_SHA,
            "logical_source_sha256": logical_sources, "charged_attempts": len(records),
            "remaining_total_if_sources_complete": 16384 - len(records),
            "baseline_unattempted_keys": [list(k) for k in sorted(expected - set(keys))],
            "records": records,
            "limitations": ["Source retirement, ledger completeness, image bytes and review are not verified.",
                            "Do not run this key list; reconcile newer originals and resolve collisions first."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--prompts", required=True)
    parser.add_argument("--source", action="append", required=True, metavar="LOGICAL_ID=SNAPSHOT")
    args = parser.parse_args()
    sources = [tuple(x.split("=", 1)) for x in args.source]
    if any(len(x) != 2 for x in sources):
        parser.error("sources must be LOGICAL_ID=SNAPSHOT")
    print(json.dumps(preview(args.manifest, args.prompts, sources), ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
