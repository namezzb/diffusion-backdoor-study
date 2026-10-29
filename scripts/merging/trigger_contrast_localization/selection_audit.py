"""Rebuild and audit a frozen parameter selection from localization receipts."""
from __future__ import annotations

import hashlib
import json
import math

import torch
from safetensors.torch import load

from core import choose_positive, coordinates_for_blocks, mask_hash, partition, response
from evidence import VERSIONS
from selection import build_selection


def block_id(block):
    return f"{block.path}@{block.start}+{block.size}"


def _evidence(ledger, unit):
    row = ledger.db.execute("SELECT status,evidence_sha,evidence FROM units WHERE name=?", (unit,)).fetchone()
    if row is None or row[0] != "complete" or row[2] is None or hashlib.sha256(row[2]).hexdigest() != row[1]:
        raise ValueError("missing or corrupt localization evidence: " + unit)
    return json.loads(row[2])


def _embedding(ledger, unit, kind, context):
    tensors = load(ledger.load(unit, kind, context))
    if set(tensors) != {"embedding"} or not tensors["embedding"].is_floating_point() or not torch.isfinite(tensors["embedding"]).all():
        raise ValueError("invalid cached baseline embedding")
    return tensors["embedding"].float()


def _scored(result, before, expected_size, expected_mask):
    if (result.get("size") != expected_size or result.get("mask_sha256") != expected_mask
            or not math.isclose(result.get("response_before", math.nan), before, rel_tol=1e-6, abs_tol=1e-10)):
        raise ValueError("localization receipt differs from expected baseline or mask")
    costs = result.get("normal_costs", {})
    if set(costs) != {"dog", "cat", "other"} or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in costs.values()):
        raise ValueError("invalid normal cost evidence")
    after = result.get("response_after")
    score = result.get("score")
    if not isinstance(after, (int, float)) or not math.isfinite(after) or after < 0 or not isinstance(score, (int, float)) or not math.isfinite(score):
        raise ValueError("invalid response or block score")
    expected = (before - after - max(costs.values())) / expected_size
    if not math.isclose(score, expected, rel_tol=1e-6, abs_tol=1e-10):
        raise ValueError("localization score cannot be independently recomputed")
    return score


def _audit_combination(ledger, unit, ids, baseline, result, before, size, mask):
    outputs = {kind: torch.stack([_embedding(ledger, unit, kind, context) for context in ids])
               for kind in ("trigger", "dog", "cat", "other")}
    actual_after = response(outputs["trigger"], outputs["dog"], baseline["clean"]["trigger"], baseline["clean"]["dog"])
    actual_costs = {kind: float((outputs[kind] - baseline["backdoor"][kind]).square().mean())
                    for kind in ("dog", "cat", "other")}
    if not math.isclose(result.get("response_after", math.nan), actual_after, rel_tol=1e-6, abs_tol=1e-10):
        raise ValueError("combination response differs from stored embedding outputs")
    for kind, value in actual_costs.items():
        if not math.isclose(result.get("normal_costs", {}).get(kind, math.nan), value, rel_tol=1e-6, abs_tol=1e-10):
            raise ValueError("combination normal cost differs from stored embeddings")
    _scored(result, before, size, mask)
    return actual_after


def verify_selection(runtime, binding, ledger, context_ids):
    """Recompute all score formulae, masks, K, random matching and response."""
    runtime._tcl_verified_selection_sha = None
    identity_row = ledger.db.execute("SELECT value FROM metadata WHERE id=1").fetchone()
    if identity_row is None:
        raise ValueError("missing localization identity")
    identity = json.loads(identity_row[0])
    if identity.get("run_id") != binding.run_id or identity.get("manifest_sha") != binding.manifest_sha:
        raise ValueError("localization ledger belongs to a different frozen run")
    if len(context_ids) != 64 or len(set(context_ids)) != 64 or set(context_ids) != set(ledger.contexts):
        raise ValueError("localization contexts differ from the frozen ledger")
    ids = sorted(context_ids)
    for source in ("clean", "backdoor"):
        _evidence(ledger, "baseline:" + source)
    baseline = {source: {kind: torch.stack([_embedding(ledger, "baseline:" + source, kind, context) for context in ids])
                        for kind in ("trigger", "dog", "cat", "other")}
                for source in ("clean", "backdoor")}
    before = response(baseline["backdoor"]["trigger"], baseline["backdoor"]["dog"],
                      baseline["clean"]["trigger"], baseline["clean"]["dog"])
    assets = runtime.assets
    names = assets.parameter_names
    clean = {n: assets.text_states["clean"][n] for n in names}
    backdoor = {n: assets.text_states["backdoor"][n] for n in names}
    blocks, delta = partition(clean, backdoor)
    if set(identity.get("block_ids", ())) != {block_id(block) for block in blocks}:
        raise ValueError("localization ledger blocks differ from loaded parameter domain")
    scores = {}
    for block in blocks:
        coords = coordinates_for_blocks([block])
        record = _evidence(ledger, "block:" + block_id(block))
        scores[block] = _scored(record, before, block.size, mask_hash(coords))
    chosen = choose_positive(blocks, scores, sum(value.numel() for value in delta.values()))
    if not chosen:
        raise ValueError("no positive complete block fits the fixed cap")
    new_coords = coordinates_for_blocks(chosen)
    expected_new = mask_hash(new_coords)
    if binding.mask_hashes["new"] != expected_new:
        raise ValueError("frozen new mask differs from block scoring")
    k = sum(x.numel() for x in new_coords.values())
    new_receipt = _evidence(ledger, "control:new")
    after = _audit_combination(ledger, "control:new", ids, baseline, new_receipt, before, k, expected_new)
    selected = build_selection(blocks, scores, delta, before, after, binding.random_seeds)
    for version in VERSIONS[2:]:
        coords = selected["groups"][version]
        expected = mask_hash(coords)
        if binding.mask_hashes[version] != expected:
            raise ValueError("frozen mask does not match reproducible selection: " + version)
        receipt = new_receipt if version == "new" else _evidence(ledger, "control:" + version)
        if version != "new":
            _audit_combination(ledger, "control:" + version, ids, baseline, receipt, before, selected["K"], expected)
    runtime._tcl_verified_selection_sha = binding.selection_sha
    return {"selection_sha256": binding.selection_sha, "K": selected["K"],
            "total_parameters": selected["total_parameters"], "summaries": selected["summaries"],
            "response_before": before, "response_after": after}
