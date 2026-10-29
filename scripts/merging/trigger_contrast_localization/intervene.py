"""One candidate intervention for a caller-supplied frozen TE.

No model is loaded here.  Persistent accounting, frozen input authentication,
cached baseline outputs and the overall selection runner remain required.
"""
from __future__ import annotations

import json

import torch

from core import block_score, mask_hash, response


def intervene_once(model, clean, coordinates, texts, clean_outputs, backdoor_outputs, charge, forward):
    """Temporarily restore specified coordinates and evaluate each text once.

    Caller must persist charge *before* each model invocation, prevent replay,
    and verify model/tokenizer/input identity. On any exception, restore every
    modified model parameter and propagate the failure without retrying.
    """
    kinds = ("trigger", "dog", "cat", "other")
    if set(texts) != set(kinds) or set(clean_outputs) != set(kinds) or set(backdoor_outputs) != set(kinds):
        raise ValueError("four paired classes and both baseline outputs required")
    n = len(texts["dog"])
    if n < 1 or any(len(texts[k]) != n or clean_outputs[k].shape[0] != n or backdoor_outputs[k].shape != clean_outputs[k].shape for k in kinds):
        raise ValueError("classes must share one context dimension")
    params = dict(model.named_parameters())
    if set(clean) != set(params) or not coordinates:
        raise ValueError("matching named parameters and nonempty coordinates required")
    originals = {}
    for path, indices in coordinates.items():
        if path not in params or not isinstance(indices, torch.Tensor) or indices.dtype != torch.int64 or indices.ndim != 1:
            raise ValueError("invalid named coordinates")
        param, reference = params[path], clean[path]
        if param.dtype != torch.float32 or reference.dtype != torch.float32 or param.shape != reference.shape or not param.is_contiguous() or not reference.is_contiguous():
            raise ValueError("intervention needs matching contiguous FP32 parameters")
        if not indices.numel() or int(indices.min()) < 0 or int(indices.max()) >= param.numel() or indices.unique().numel() != indices.numel():
            raise ValueError("invalid or repeated coordinate")
        originals[path] = param.detach().reshape(-1)[indices.to(param.device)].clone()
    outputs = {}
    try:
        with torch.no_grad():
            for path, indices in coordinates.items():
                params[path].reshape(-1)[indices.to(params[path].device)] = clean[path].reshape(-1)[indices.to(clean[path].device)].to(params[path].device)
            for kind in kinds:
                values = []
                for prompt in texts[kind]:
                    charge(1)
                    value = forward(model, prompt)
                    if not isinstance(value, torch.Tensor) or value.shape != clean_outputs[kind].shape[1:] or not torch.isfinite(value).all():
                        raise ValueError("invalid fixed-length TE output")
                    values.append(value.detach().cpu().float())
                outputs[kind] = torch.stack(values)
    finally:
        with torch.no_grad():
            for path, indices in coordinates.items():
                params[path].reshape(-1)[indices.to(params[path].device)] = originals[path]
    base_r = response(backdoor_outputs["trigger"], backdoor_outputs["dog"], clean_outputs["trigger"], clean_outputs["dog"])
    new_r = response(outputs["trigger"], outputs["dog"], clean_outputs["trigger"], clean_outputs["dog"])
    size = sum(indices.numel() for indices in coordinates.values())
    normal = {k: outputs[k] for k in ("dog", "cat", "other")}
    baseline = {k: backdoor_outputs[k] for k in normal}
    normal_costs = {k: float((normal[k].float() - baseline[k].float()).square().mean()) for k in normal}
    return {"response_before": base_r, "response_after": new_r,
            "normal_costs": normal_costs,
            "score": block_score(base_r, new_r, normal, baseline, size), "size": size}


def intervene_resumable(model, clean, coordinates, context_ids, texts, clean_outputs,
                        backdoor_outputs, ledger, unit, forward):
    """One block/control with per-prompt reservations and saved safetensors.

    The caller must authenticate the frozen model and inputs, initialize or
    resume the ledger unit, and ensure that saved clean/backdoor embeddings are
    valid. Nothing in this function loads a real model or authorizes hardware.
    """
    from safetensors.torch import load, save

    kinds = ("trigger", "dog", "cat", "other")
    if len(context_ids) != 64 or len(set(context_ids)) != 64 or any(len(texts[k]) != 64 for k in kinds):
        raise ValueError("the frozen 64 unique localization contexts are required")
    operations = [(kind, ident) for kind in kinds for ident in context_ids]
    operation_index, current = 0, None

    def charge(count):
        nonlocal operation_index, current
        if count != 1 or operation_index >= len(operations):
            raise ValueError("invalid localization operation")
        kind, ident = operations[operation_index]
        operation_index += 1
        reserved = ledger.reserve(unit, kind, ident)
        current = kind, ident, reserved

    def evaluate(active_model, prompt):
        if current is None:
            raise ValueError("forward was not reserved")
        kind, ident, reserved = current
        if not reserved:
            tensors = load(ledger.load(unit, kind, ident))
            if set(tensors) != {"embedding"}:
                raise ValueError("saved embedding format mismatch")
            return tensors["embedding"]
        output = forward(active_model, prompt)
        if (not isinstance(output, torch.Tensor) or not output.is_floating_point()
                or output.shape != clean_outputs[kind].shape[1:] or not torch.isfinite(output).all()):
            raise ValueError("invalid TE embedding")
        cpu = output.detach().to(device="cpu", dtype=torch.float32).contiguous()
        ledger.record(unit, kind, ident, save({"embedding": cpu}))
        return cpu

    result = intervene_once(model, clean, coordinates, texts, clean_outputs, backdoor_outputs, charge, evaluate)
    if operation_index != 256:
        raise ValueError("localization unit did not traverse all frozen prompts")
    result["mask_sha256"] = mask_hash(coordinates)
    evidence = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    result["evidence_sha256"] = ledger.complete(unit, evidence)
    return result
