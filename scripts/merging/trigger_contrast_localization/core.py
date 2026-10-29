"""Parameter-level building blocks for TCL v1; importing runs no model.

This module is not a complete experiment runner.  It does not authorize or
perform any inference, and its outputs are not a frozen experiment manifest.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
import random
import re

import torch

MAX_BLOCK = 2**19
MAX_BLOCKS = 1024


@dataclass(frozen=True, order=True)
class Block:
    path: str
    start: int
    size: int
    layer: str


def layer_name(path: str) -> str:
    match = re.match(r"^(.*?encoder\.layers\.\d+)(?:\.|$)", path)
    return match.group(1) if match else path.rsplit(".", 1)[0]


def partition(clean, backdoor, block_size=MAX_BLOCK):
    if not 0 < block_size <= MAX_BLOCK or set(clean) != set(backdoor):
        raise ValueError("mismatched names or invalid block size")
    blocks, delta = [], {}
    for path in sorted(clean):
        a, b = clean[path], backdoor[path]
        if not a.is_floating_point() or not b.is_floating_point() or a.shape != b.shape:
            raise ValueError(f"incompatible floating parameters: {path}")
        d = b.detach().cpu().float().reshape(-1) - a.detach().cpu().float().reshape(-1)
        if not torch.isfinite(d).all():
            raise ValueError(f"nonfinite difference: {path}")
        delta[path] = d
        blocks.extend(Block(path, start, min(block_size, d.numel() - start), layer_name(path))
                      for start in range(0, d.numel(), block_size))
    if not blocks or len(blocks) > MAX_BLOCKS:
        raise ValueError("empty parameter set or too many blocks")
    return blocks, delta


def response(candidate_trigger, candidate_normal, clean_trigger, clean_normal):
    tensors = (candidate_trigger, candidate_normal, clean_trigger, clean_normal)
    if any(x.shape != tensors[0].shape for x in tensors) or not tensors[0].numel():
        raise ValueError("response tensors must have equal nonempty shapes")
    value = ((candidate_trigger.float() - candidate_normal.float()) -
             (clean_trigger.float() - clean_normal.float())).square().mean()
    if not torch.isfinite(value):
        raise ValueError("nonfinite response")
    return float(value)


def block_score(baseline_response, restored_response, restored_normals, baseline_normals, size):
    if set(restored_normals) != {"dog", "cat", "other"} or set(restored_normals) != set(baseline_normals) or size <= 0:
        raise ValueError("all three normal classes and a nonempty block are required")
    costs = []
    for name in sorted(restored_normals):
        a, b = restored_normals[name], baseline_normals[name]
        if a.shape != b.shape or not a.numel():
            raise ValueError("normal output shape mismatch")
        costs.append(float((a.float() - b.float()).square().mean()))
    values = [baseline_response, restored_response, *costs]
    if not all(math.isfinite(v) and v >= 0 for v in values):
        raise ValueError("nonfinite or negative response/cost")
    return (baseline_response - restored_response - max(costs)) / size


def choose_positive(blocks, scores, total):
    if set(scores) != set(blocks) or total <= 0 or not all(math.isfinite(x) for x in scores.values()):
        raise ValueError("missing scores or invalid parameter total")
    cap = total // 20
    chosen, k = [], 0
    for block in sorted(blocks, key=lambda b: (-scores[b], b.path, b.start)):
        if scores[block] > 0 and k + block.size <= cap:
            chosen.append(block)
            k += block.size
    return chosen


def block_l2_squared(blocks, delta):
    return sum(float(delta[b.path][b.start:b.start + b.size].double().square().sum()) for b in blocks)


def matched_block_controls(blocks, selected, delta, seeds=(1701, 1702, 1703), attempts=1000):
    if len(set(seeds)) != 3 or attempts < 1 or not selected or len(set(selected)) != len(selected):
        raise ValueError("three distinct seeds and a nonempty selection required")
    buckets = defaultdict(list)
    for block in blocks:
        buckets[(block.layer, block.size)].append(block)
    required = Counter((block.layer, block.size) for block in selected)
    if not set(selected).issubset(set(blocks)) or any(n > len(buckets[key]) for key, n in required.items()):
        raise ValueError("selection not in block universe")
    amplitude = []
    for key in sorted(required):
        ranked = sorted(buckets[key], key=lambda b: (-float(delta[b.path][b.start:b.start+b.size].abs().mean()), b.path, b.start))
        amplitude.extend(ranked[:required[key]])
    target = math.sqrt(block_l2_squared(selected, delta))
    if target == 0:
        raise ValueError("selected difference has zero norm")
    used, controls = {frozenset(selected)}, []
    for seed in seeds:
        rng = random.Random(seed)
        for _ in range(attempts):
            candidate = []
            for key in sorted(required):
                candidate.extend(rng.sample(sorted(buckets[key]), required[key]))
            fingerprint = frozenset(candidate)
            norm = math.sqrt(block_l2_squared(candidate, delta))
            if fingerprint not in used and abs(norm - target) / target <= .10:
                used.add(fingerprint)
                controls.append(sorted(candidate))
                break
        else:
            raise ValueError(f"random control insufficient for seed {seed}")
    return sorted(amplitude), controls


def magnitude_coordinates(delta, k):
    total = sum(d.numel() for d in delta.values())
    if not 0 < k <= total:
        raise ValueError("invalid K")
    # Stable per-path sorting followed by stable global sorting preserves the
    # path/coordinate tie-break without materializing Python scalar tuples.
    values = torch.cat([delta[p].abs() for p in sorted(delta)])
    if not torch.isfinite(values).all():
        raise ValueError("nonfinite delta")
    chosen = torch.argsort(values, descending=True, stable=True)[:k].sort().values
    result, offset = {}, 0
    for path in sorted(delta):
        n = delta[path].numel()
        result[path] = chosen[(chosen >= offset) & (chosen < offset + n)] - offset
        offset += n
    return result


def coordinates_for_blocks(blocks):
    result = defaultdict(list)
    for b in sorted(blocks):
        result[b.path].append(torch.arange(b.start, b.start + b.size, dtype=torch.int64))
    return {p: torch.cat(parts) for p, parts in sorted(result.items())}


def restore(base, delta, coordinates, coefficient=1.0, clean=None):
    if coefficient not in (1.0, .25):
        raise ValueError("only source or frozen .25 merge restoration is allowed")
    if coefficient == 1.0 and (clean is None or set(clean) != set(base)):
        raise ValueError("source restoration needs the exact clean parameter values")
    result = {p: x.detach().contiguous().clone() for p, x in base.items()}
    for path, indices in coordinates.items():
        if path not in result or path not in delta:
            raise ValueError("unknown parameter")
        if result[path].dtype != torch.float32:
            raise ValueError("restoration must be applied to FP32 parameters")
        if not isinstance(indices, torch.Tensor) or indices.dtype != torch.int64 or indices.ndim != 1:
            raise ValueError("parameter coordinates must be a one-dimensional int64 tensor")
        indices = indices.to(device="cpu")
        flat = result[path].reshape(-1)
        if (indices.numel() and (int(indices.min()) < 0 or int(indices.max()) >= flat.numel())) or indices.unique().numel() != indices.numel():
            raise ValueError("invalid or duplicate parameter coordinate")
        index = indices.to(flat.device)
        if coefficient == 1.0:
            if clean[path].shape != result[path].shape or clean[path].dtype != torch.float32:
                raise ValueError("clean parameters must match shape and FP32 dtype")
            flat[index] = clean[path].reshape(-1)[indices.to(clean[path].device)].to(flat.device)
        else:
            flat[index] -= .25 * delta[path][indices].to(device=flat.device, dtype=flat.dtype)
    return result


def mask_hash(coordinates):
    payload = {path: [int(x) for x in coordinates[path].tolist()] for path in sorted(coordinates)}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()
