"""Read-only v2 input and historical-intersection preview; never launches a run."""
from __future__ import annotations

import hashlib
import itertools
import json
from collections import Counter
from pathlib import Path

RUN = "tcl-20261102-pilot24-v2"
PARENT = "tcl-20261029-01-v1"
SEED = 271101
CLASSES = ("trigger", "dog", "cat", "other")
VERSIONS = ("clean", "backdoor", "new", "magnitude", "block_magnitude", "random_1", "random_2", "random_3")
PREFIX = "TCL-20261029-01/pilot24-v2/merge/"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_units(plan_path, ids_path, manifest_path, prompts_path):
    plan, ids, manifest = (json.loads(Path(p).read_text()) for p in (plan_path, ids_path, manifest_path))
    if (plan["run_id"] != RUN or ids["run_id"] != RUN or manifest["run_id"] != PARENT
            or plan["generation_seeds"] != [SEED] or ids["generation_seed"] != SEED
            or sha(ids_path) != plan["context_ids_sha256"]
            or sha(manifest_path) != plan["parent_manifest_sha256"]
            or sha(prompts_path) != manifest["prompts_sha256"]
            or sha(prompts_path) != ids["parent_prompts_sha256"]):
        raise ValueError("frozen input identity or hash mismatch")
    rows = [json.loads(line) for line in Path(prompts_path).read_text().splitlines()]
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("duplicate context ID")
    source = sorted(r["id"] for r in rows if r["partition"] == "source")
    merge = [r for r in rows if r["partition"] == "merge"]
    strata = ids["merge_rule"]["strata"]
    if len(source) != 128 or len(merge) != 128 or len(strata) != 8 or len(set(strata)) != 8:
        raise ValueError("unexpected parent context partitions")
    ranked = {s: sorted((r["id"] for r in merge if r["stratum"] == s),
                        key=lambda x: (hashlib.sha256((PREFIX + x).encode()).hexdigest(), x))[:8]
              for s in strata}
    selected = sorted(itertools.chain.from_iterable(ranked.values()))
    if (any(len(v) != 8 for v in ranked.values()) or len(set(selected)) != 64
            or source != ids["source_context_ids"] or selected != ids["merge_context_ids"]
            or ranked != ids["merge_ranked_ids_by_stratum"] or set(source) & set(selected)):
        raise ValueError("context selection differs from the preregistered selection")
    stages = {}
    for stage, state, contexts, versions in (("S0", "source", source, VERSIONS[:2]),
                                              ("S1", "source", source, VERSIONS[2:]),
                                              ("M0", "merge", selected, VERSIONS[:2]),
                                              ("M1", "merge", selected, VERSIONS[2:])):
        stages[stage] = [(RUN, state, version, category, context, SEED)
                         for version, category, context in itertools.product(versions, CLASSES, contexts)]
    keys = list(itertools.chain.from_iterable(stages.values()))
    if [len(stages[s]) for s in ("S0", "S1", "M0", "M1")] != [1024, 3072, 512, 1536] or len(set(keys)) != 6144:
        raise ValueError("invalid or overlapping unique image units")
    return stages


def historical_intersection(stages, preview_path):
    """Count candidates only; preview does not attest bytes, current writer or imports."""
    doc = json.loads(Path(preview_path).read_text())
    if doc.get("status") != "provisional_not_executable":
        raise ValueError("expected the provisional v1 preview")
    valid = set(itertools.chain.from_iterable(stages.values()))
    seen = set()
    counts = Counter()
    for record in doc["records"]:
        key = record["key"]
        if len(key) != 6 or key[0] != PARENT:
            raise ValueError("unexpected historical identity")
        mapped = (RUN, *key[1:])
        if mapped not in valid:
            continue
        if mapped in seen:
            raise ValueError("duplicate candidate; reconcile before import")
        seen.add(mapped)
        counts[(record["source"], record["status"])] += 1
    return {"status": "provisional_not_imported", "counts": [
        {"source": s, "status": status, "count": n} for (s, status), n in sorted(counts.items())],
        "verified_imports": 0,
        "limitations": ["Snapshot is not the live original ledger or proof of writer retirement.",
                        "Images, scores and their exact provenance must be authenticated before import."]}


def balanced_chunks(stages):
    """Create a deterministic read-only planning partition, not a worker assignment."""
    result = {}
    for stage, keys in stages.items():
        by_stratum = {}
        for context in sorted({key[4] for key in keys}):
            stratum = context.rsplit("-", 1)[0]
            by_stratum.setdefault(stratum, []).append(context)
        if len(by_stratum) != 8 or len({len(x) for x in by_stratum.values()}) != 1:
            raise ValueError("expected eight balanced context strata")
        count = len(next(iter(by_stratum.values())))
        context_sets = [{by_stratum[s][i] for s in sorted(by_stratum)} for i in range(count)]
        chunks = [[key for key in keys if key[4] in group] for group in context_sets]
        if set(itertools.chain.from_iterable(chunks)) != set(keys) or sum(map(len, chunks)) != len(keys):
            raise ValueError("chunk keys must be an exact disjoint partition")
        result[stage] = chunks
    return result
