"""Deterministic selection from fully scored parameter blocks."""
from __future__ import annotations

from collections import Counter
import math

import torch

from core import (choose_positive, coordinates_for_blocks, layer_name, magnitude_coordinates,
                  mask_hash, matched_block_controls)


class ScientificStop(ValueError):
    """Pre-registered localization stop, distinct from execution failure."""

    def __init__(self, message, reason_code, evidence):
        super().__init__(message)
        self.reason_code = reason_code
        self.evidence = evidence


def _summary(coords, delta):
    per_layer, squared = Counter(), 0.
    for name, indices in coords.items():
        per_layer[layer_name(name)] += int(indices.numel())
        squared += float(delta[name][indices].double().square().sum())
    return {"coordinates": sum(per_layer.values()), "per_layer": dict(sorted(per_layer.items())),
            "delta_l2": math.sqrt(squared), "mask_sha256": mask_hash(coords)}


def _overlap(a, b):
    total = 0
    for name in set(a) & set(b):
        total += int(torch.isin(a[name], b[name]).sum())
    return total


def propose_groups(blocks, scores, delta, random_seeds):
    """Propose deterministic masks before any combination evaluation."""
    total = sum(tensor.numel() for tensor in delta.values())
    chosen = choose_positive(blocks, scores, total)
    if not chosen:
        raise ScientificStop("no positive complete block fits the fixed five percent cap", "no_positive_block",
                             {"total_parameters": total, "cap": total // 20,
                              "positive_block_count": sum(scores[b] > 0 for b in blocks)})
    chosen_coords = coordinates_for_blocks(chosen)
    k = sum(x.numel() for x in chosen_coords.values())
    try:
        amplitude, randoms = matched_block_controls(blocks, chosen, delta, seeds=tuple(random_seeds))
    except ValueError as exc:
        if "random control insufficient" in str(exc):
            raise ScientificStop(str(exc), "random_control_insufficient",
                                 {"K": k, "total_parameters": total, "selected_mask_sha256": mask_hash(chosen_coords),
                                  "random_control_seeds": list(random_seeds)}) from exc
        raise
    groups = {"new": chosen_coords, "magnitude": magnitude_coordinates(delta, k),
              "block_magnitude": coordinates_for_blocks(amplitude)}
    groups.update({f"random_{i}": coordinates_for_blocks(blocks_) for i, blocks_ in enumerate(randoms, 1)})
    summaries = {name: _summary(coords, delta) for name, coords in groups.items()}
    for name, summary in summaries.items():
        if summary["coordinates"] != k:
            raise ValueError("comparison mask violates fixed K")
        summary["overlap_with_new"] = _overlap(chosen_coords, groups[name])
    return {"groups": groups, "summaries": summaries, "K": k, "total_parameters": total}


def build_selection(blocks, scores, delta, combined_response_before, combined_response_after, random_seeds):
    """Rebuild groups only after an independently measured new response."""
    if not all(math.isfinite(x) and x >= 0 for x in (combined_response_before, combined_response_after)):
        raise ValueError("combined responses must be finite and nonnegative")
    if combined_response_after >= combined_response_before:
        raise ScientificStop("combined restoration did not improve trigger response", "combined_response_not_improved",
                             {"response_before": combined_response_before, "response_after": combined_response_after})
    result = propose_groups(blocks, scores, delta, random_seeds)
    result["response_before"] = combined_response_before
    result["response_after"] = combined_response_after
    return result
