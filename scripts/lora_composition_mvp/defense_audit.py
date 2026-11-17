"""Post-hoc static spectral (PEFTGuard-style) and dynamic attention (T2IShield-style) defense auditing.

Strictly an offline evaluation & observability module; never modifies training objectives or trainers.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

# Support both `python3 -m scripts.lora_composition_mvp.defense_audit` and direct script invocation
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lora_composition_mvp.config import MVPConfig, load_config
from scripts.lora_composition_mvp.io_utils import (
    LoRAAdapter,
    LoRALayerFactor,
    compute_adapter_norms,
    enforce_offline_env,
    is_ours_bottleneck_target,
    is_unet_attention_target,
    load_lora_adapter,
    md_write,
    save_lora_adapter,
)
from scripts.lora_composition_mvp.subspace import find_target_linear_modules


def compute_gini_coefficient(values: list[float]) -> float:
    """Compute Gini coefficient in [0, 1) over non-negative values."""
    clean = sorted(max(0.0, float(v)) for v in values)
    n = len(clean)
    if n == 0:
        return 0.0
    total = sum(clean)
    if total <= 1e-12:
        return 0.0
    weighted = sum((2 * (idx + 1) - n - 1) * val for idx, val in enumerate(clean))
    gini = weighted / (float(n) * total)
    return max(0.0, min(1.0, float(gini)))


def compute_top1_sv_energy_ratio(matrix: Any) -> float:
    """Compute s_1^2 / sum_k s_k^2 energy concentration of a 2D weight delta matrix."""
    import torch

    mat = matrix.detach().float()
    if mat.ndim != 2 or min(mat.shape) == 0:
        return 0.0
    _, s, _ = torch.linalg.svd(mat, full_matrices=False)
    s2 = s * s
    denom = float(s2.sum().item())
    if denom <= 1e-12:
        return 0.0
    top1 = float(s2[0].item())
    return max(0.0, min(1.0, top1 / denom))


def compute_matrix_kurtosis(matrix: Any) -> dict[str, float]:
    """Compute sample 4th-moment kurtosis and excess kurtosis of flattened matrix entries."""
    vec = matrix.detach().float().reshape(-1)
    n = int(vec.shape[0])
    if n == 0:
        return {"kurtosis": 0.0, "excess_kurtosis": -3.0, "variance": 0.0}
    mu = vec.mean()
    diff = vec - mu
    sq = diff * diff
    var = float(sq.mean().item())
    if var <= 1e-12:
        return {"kurtosis": 0.0, "excess_kurtosis": -3.0, "variance": 0.0}
    m4 = float((sq * sq).mean().item())
    kurt = m4 / (var * var)
    return {
        "kurtosis": float(kurt),
        "excess_kurtosis": float(kurt - 3.0),
        "variance": float(var),
    }


def _layer_role(full_key: str) -> str:
    if full_key.startswith("text_encoder."):
        return "text_encoder"
    if ".to_k" in full_key or ".to_v" in full_key:
        return "kv"
    if ".to_q" in full_key or ".to_out.0" in full_key:
        return "qo"
    return "other"


def _layer_effective_delta(factor: LoRALayerFactor) -> Any:
    return factor.compute_delta().detach().float()


def audit_static_adapter_spectrum(
    adapter: LoRAAdapter,
    total_unet_layers: int = 128,
    all_unet_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Run PEFTGuard-style offline static spectral and structural audit on a LoRA adapter."""
    norms = compute_adapter_norms(adapter)

    unet_active_norms: list[float] = []
    all_layer_records: list[dict[str, Any]] = []
    kv_sq = 0.0
    qo_sq = 0.0
    bottleneck_sq = 0.0
    unet_sq = 0.0
    te_sq = 0.0
    top1_ratios: list[float] = []
    top1_kv_ratios: list[float] = []
    top1_qo_ratios: list[float] = []
    kurt_vals: list[float] = []
    excess_kurt_vals: list[float] = []

    norm_by_key: dict[str, float] = {}
    for full_key, factor in sorted(adapter.layers.items()):
        delta = _layer_effective_delta(factor)
        frob = float((delta * delta).sum().sqrt().item())
        top1 = compute_top1_sv_energy_ratio(delta)
        k_stats = compute_matrix_kurtosis(delta)
        role = _layer_role(full_key)
        is_bn = bool(full_key.startswith("unet.") and is_ours_bottleneck_target(factor.module_name))

        norm_by_key[full_key] = frob
        rec = {
            "layer": full_key,
            "role": role,
            "is_bottleneck_24": is_bn,
            "frobenius": frob,
            "top1_sv_energy_ratio": top1,
            "kurtosis": k_stats["kurtosis"],
            "excess_kurtosis": k_stats["excess_kurtosis"],
        }
        all_layer_records.append(rec)

        sq = frob * frob
        if full_key.startswith("text_encoder."):
            te_sq += sq
        else:
            unet_sq += sq
            if is_bn:
                bottleneck_sq += sq
            if role == "kv":
                kv_sq += sq
                if frob > 1e-10:
                    top1_kv_ratios.append(top1)
            elif role == "qo":
                qo_sq += sq
                if frob > 1e-10:
                    top1_qo_ratios.append(top1)
            if frob > 1e-10:
                unet_active_norms.append(frob)
                top1_ratios.append(top1)
                kurt_vals.append(k_stats["kurtosis"])
                excess_kurt_vals.append(k_stats["excess_kurtosis"])

    if all_unet_keys:
        full_unet_norms = [norm_by_key.get(k if k.startswith("unet.") else f"unet.{k}", 0.0) for k in all_unet_keys]
    else:
        unet_present = [norm_by_key[k] for k in sorted(norm_by_key) if k.startswith("unet.")]
        n_pad = max(0, int(total_unet_layers) - len(unet_present))
        full_unet_norms = unet_present + [0.0] * n_pad

    kv_fro = math.sqrt(kv_sq)
    qo_fro = math.sqrt(qo_sq)
    unet_fro = math.sqrt(unet_sq)
    te_fro = math.sqrt(te_sq)
    bn_fro = math.sqrt(bottleneck_sq)
    total_fro = math.sqrt(unet_sq + te_sq)

    mean = lambda xs: (sum(xs) / len(xs)) if xs else 0.0
    max_v = lambda xs: max(xs) if xs else 0.0

    top5 = sorted(all_layer_records, key=lambda r: r["frobenius"], reverse=True)[:5]
    return {
        "adapter_name": adapter.name,
        "total_layers_present": len(adapter.layers),
        "active_unet_layers": len(unet_active_norms),
        "total_unet_reference_layers": len(full_unet_norms),
        "total_frobenius": float(norms["total_frobenius"]),
        "unet_frobenius": unet_fro,
        "text_encoder_frobenius": te_fro,
        "bottleneck_24_frobenius": bn_fro,
        "kv_frobenius": kv_fro,
        "qo_frobenius": qo_fro,
        "kv_to_qo_norm_ratio": (kv_fro / qo_fro) if qo_fro > 1e-12 else None,
        "kv_unet_energy_share": (kv_sq / unet_sq) if unet_sq > 1e-12 else 0.0,
        "qo_unet_energy_share": (qo_sq / unet_sq) if unet_sq > 1e-12 else 0.0,
        "bottleneck_24_energy_share": (bottleneck_sq / (unet_sq + te_sq)) if (unet_sq + te_sq) > 1e-12 else 0.0,
        "gini_all_unet": compute_gini_coefficient(full_unet_norms),
        "gini_active_unet": compute_gini_coefficient(unet_active_norms),
        "mean_top1_sv_energy_ratio": mean(top1_ratios),
        "max_top1_sv_energy_ratio": max_v(top1_ratios),
        "mean_kv_top1_sv_energy_ratio": mean(top1_kv_ratios),
        "mean_qo_top1_sv_energy_ratio": mean(top1_qo_ratios),
        "mean_kurtosis": mean(kurt_vals),
        "max_kurtosis": max_v(kurt_vals),
        "mean_excess_kurtosis": mean(excess_kurt_vals),
        "max_excess_kurtosis": max_v(excess_kurt_vals),
        "top5_layers_by_frobenius": top5,
    }


def apply_peripheral_benign_floor(
    cand: LoRAAdapter,
    reference_adapter: LoRAAdapter | None = None,
    unet: Any = None,
    template_modules: list[str] | None = None,
    peripheral_floor_norm_per_layer: float = 0.05,
    target_total_norm: float | None = 18.0,
    rank: int = 16,
    seed: int = 42,
    out_path: str | Path | None = None,
) -> tuple[LoRAAdapter, dict[str, Any]]:
    """Post-hoc evaluation experiment: add benign low-magnitude floor on peripheral UNet layers only.

    Always preserves TE norm == 0.0 and total Frobenius norm <= target_total_norm.
    """
    import torch

    if peripheral_floor_norm_per_layer < 0.0:
        raise ValueError("peripheral_floor_norm_per_layer must be non-negative.")

    before_spec = audit_static_adapter_spectrum(cand)

    # Identify candidate peripheral UNet module keys
    shape_map: dict[str, tuple[int, int]] = {}
    if unet is not None:
        mods = find_target_linear_modules(unet, bottleneck_only=False)
        for mod_name, mod in mods.items():
            shape_map[f"unet.{mod_name}"] = (int(mod.out_features), int(mod.in_features))
    if reference_adapter is not None:
        for full_key, fac in reference_adapter.layers.items():
            if full_key.startswith("unet.") and full_key not in shape_map:
                if fac.lora_B is not None and fac.lora_A is not None:
                    shape_map[full_key] = (int(fac.lora_B.shape[0]), int(fac.lora_A.shape[1]))
                elif fac.dense_delta is not None:
                    shape_map[full_key] = (int(fac.dense_delta.shape[0]), int(fac.dense_delta.shape[1]))
    if template_modules:
        for mod_name in template_modules:
            fk = mod_name if mod_name.startswith("unet.") else f"unet.{mod_name}"
            if fk not in shape_map:
                sample_fac = next(iter(cand.layers.values()))
                if sample_fac.lora_B is not None and sample_fac.lora_A is not None:
                    shape_map[fk] = (int(sample_fac.lora_B.shape[0]), int(sample_fac.lora_A.shape[1]))
                elif sample_fac.dense_delta is not None:
                    shape_map[fk] = (int(sample_fac.dense_delta.shape[0]), int(sample_fac.dense_delta.shape[1]))

    new_layers: dict[str, LoRALayerFactor] = {}
    for full_key, fac in cand.layers.items():
        if full_key.startswith("text_encoder."):
            continue  # Strictly maintain ||ΔW_TE||_F == 0
        new_layers[full_key] = LoRALayerFactor(
            component=fac.component,
            module_name=fac.module_name,
            lora_A=fac.lora_A.detach().float().cpu().clone() if fac.lora_A is not None else None,
            lora_B=fac.lora_B.detach().float().cpu().clone() if fac.lora_B is not None else None,
            alpha_scale=float(fac.alpha_scale),
            dense_delta=fac.dense_delta.detach().float().cpu().clone() if fac.dense_delta is not None else None,
        )

    gen = torch.Generator(device="cpu")
    gen.manual_seed(int(seed) + 409)
    added_keys: list[str] = []

    for full_key in sorted(shape_map):
        if full_key in new_layers:
            continue
        mod_name = full_key.split(".", 1)[1]
        if not is_unet_attention_target(mod_name, component="unet"):
            continue
        if peripheral_floor_norm_per_layer <= 0.0:
            continue

        if reference_adapter is not None and full_key in reference_adapter.layers:
            ref_fac = reference_adapter.layers[full_key]
            ref_delta = _layer_effective_delta(ref_fac).float().cpu()
            ref_norm = float((ref_delta * ref_delta).sum().sqrt().item())
            if ref_norm > 1e-10:
                u, s, vh = torch.linalg.svd(ref_delta, full_matrices=False)
                eff_r = min(int(rank), int(s.shape[0]))
                u_r = u[:, :eff_r]
                s_r = s[:eff_r]
                vh_r = vh[:eff_r, :]
                sub_norm = float((s_r * s_r).sum().sqrt().item())
                gain = float(peripheral_floor_norm_per_layer) / max(sub_norm, 1e-12)
                s_root = (s_r * gain).sqrt()
                up = u_r * s_root.unsqueeze(0)
                down = s_root.unsqueeze(1) * vh_r
                new_layers[full_key] = LoRALayerFactor("unet", mod_name, lora_A=down, lora_B=up, alpha_scale=1.0)
                added_keys.append(full_key)
                continue

        out_dim, in_dim = shape_map[full_key]
        eff_r = min(int(rank), out_dim, in_dim)
        a_rand = torch.randn((eff_r, in_dim), generator=gen)
        b_rand = torch.randn((out_dim, eff_r), generator=gen)
        prod = b_rand @ a_rand
        p_norm = float((prod * prod).sum().sqrt().item())
        gain = float(peripheral_floor_norm_per_layer) / max(p_norm, 1e-12)
        half_gain = math.sqrt(gain)
        new_layers[full_key] = LoRALayerFactor(
            "unet",
            mod_name,
            lora_A=a_rand * half_gain,
            lora_B=b_rand * half_gain,
            alpha_scale=1.0,
        )
        added_keys.append(full_key)

    def _scale_factor(fac: LoRALayerFactor, ratio: float) -> LoRALayerFactor:
        r_sqrt = math.sqrt(max(0.0, ratio))
        return LoRALayerFactor(
            component=fac.component,
            module_name=fac.module_name,
            lora_A=(fac.lora_A * r_sqrt) if fac.lora_A is not None else None,
            lora_B=(fac.lora_B * r_sqrt) if fac.lora_B is not None else None,
            alpha_scale=fac.alpha_scale,
            dense_delta=(fac.dense_delta * ratio) if fac.dense_delta is not None else None,
        )

    patched = LoRAAdapter(name=f"{cand.name}_periph_floor", layers=new_layers, metadata=dict(cand.metadata))
    if target_total_norm is not None:
        norms_now = compute_adapter_norms(patched)
        total_now = float(norms_now["total_frobenius"])
        if total_now > float(target_total_norm) + 1e-8:
            # Shrink ONLY candidate (core) layers when possible so total <= target_total_norm
            periph_sq = sum(float(new_layers[k].frobenius_norm()) ** 2 for k in added_keys)
            core_keys = [k for k in new_layers if k not in set(added_keys)]
            core_sq = sum(float(new_layers[k].frobenius_norm()) ** 2 for k in core_keys)
            cap_sq = float(target_total_norm) ** 2
            if core_sq > 1e-12 and cap_sq > periph_sq:
                core_scale = math.sqrt((cap_sq - periph_sq) / core_sq)
                for k in core_keys:
                    new_layers[k] = _scale_factor(new_layers[k], core_scale)
            else:
                global_scale = float(target_total_norm) / max(total_now, 1e-12)
                for k in list(new_layers):
                    new_layers[k] = _scale_factor(new_layers[k], global_scale)

    if out_path is not None:
        save_lora_adapter(patched, out_path)

    after_spec = audit_static_adapter_spectrum(
        patched,
        all_unet_keys=sorted(shape_map) if shape_map else None,
    )
    return patched, {
        "peripheral_layers_added": len(added_keys),
        "peripheral_floor_norm_per_layer": float(peripheral_floor_norm_per_layer),
        "target_total_norm": target_total_norm,
        "before_spectrum": before_spec,
        "after_spectrum": after_spec,
    }


def _safe_softmax_last(logits: Any) -> Any:
    """Compute softmax along last dimension cleanly for both PyTorch and MiniTorch tensors."""
    if hasattr(logits, "softmax"):
        return logits.softmax(dim=-1)
    try:
        import torch.nn.functional as F

        if hasattr(F, "softmax"):
            return F.softmax(logits, dim=-1)
    except Exception:
        pass
    import torch

    def _softmax_nested(obj: Any) -> Any:
        if isinstance(obj, list) and obj and not isinstance(obj[0], list):
            mx = max(float(v) for v in obj)
            exps = [math.exp(float(v) - mx) for v in obj]
            s = max(sum(exps), 1e-12)
            return [e / s for e in exps]
        return [_softmax_nested(sub) for sub in obj]

    return torch.tensor(_softmax_nested(logits.detach().tolist()))


def _safe_entropy_normalized(p_vec: Any, log_hw: float) -> float:
    """Compute normalized spatial entropy safely on both PyTorch and MiniTorch."""
    if hasattr(p_vec, "log"):
        ent = -float((p_vec * p_vec.clamp(min=1e-12).log()).sum().item()) / log_hw
        return max(0.0, float(ent))
    vals = [max(1e-12, float(x)) for x in p_vec.detach().tolist()]
    s = max(sum(vals), 1e-12)
    ent = -sum((v / s) * math.log(max(v / s, 1e-12)) for v in vals) / log_hw
    return max(0.0, float(ent))


def _compute_head_mean_attn_map(q: Any, k: Any, eff_heads: int) -> Any:
    """Compute head-averaged cross-attention probability map [B, HW, T] on PyTorch or MiniTorch."""
    import torch

    b_sz, hw_len, dim = int(q.shape[0]), int(q.shape[1]), int(q.shape[2])
    tok_len = int(k.shape[1])
    head_dim = dim // max(1, eff_heads)
    try:
        q_h = q.reshape(b_sz, hw_len, eff_heads, head_dim).transpose(1, 2)
        k_h = k.reshape(b_sz, tok_len, eff_heads, head_dim).transpose(1, 2)
        logits = (q_h @ k_h.transpose(-1, -2)) * (float(head_dim) ** -0.5)
        probs = _safe_softmax_last(logits)
        return probs.mean(dim=1)
    except Exception:
        # Pure 2D fallback per batch/head for lightweight mock tensor engines
        q_list = q.detach().tolist()
        k_list = k.detach().tolist()
        scale = float(head_dim) ** -0.5
        out_batch = []
        for bi in range(b_sz):
            acc = [[0.0] * tok_len for _ in range(hw_len)]
            for hi in range(eff_heads):
                h0, h1 = hi * head_dim, (hi + 1) * head_dim
                for row_idx in range(hw_len):
                    q_row = q_list[bi][row_idx][h0:h1]
                    scores = [
                        sum(q_row[d] * k_list[bi][col_idx][h0 + d] for d in range(head_dim)) * scale
                        for col_idx in range(tok_len)
                    ]
                    mx = max(scores)
                    exps = [math.exp(s - mx) for s in scores]
                    denom = max(sum(exps), 1e-12)
                    for col_idx in range(tok_len):
                        acc[row_idx][col_idx] += exps[col_idx] / (denom * eff_heads)
            out_batch.append(acc)
        return torch.tensor(out_batch)


def _cosine_vectors(v1: Any, v2: Any) -> float:
    n1 = float((v1 * v1).sum().sqrt().item())
    n2 = float((v2 * v2).sum().sqrt().item())
    if n1 <= 1e-12 or n2 <= 1e-12:
        return 0.0
    return float((v1 * v2).sum().item()) / (n1 * n2)


def audit_dynamic_cross_attention(
    unet: Any,
    latents: Any,
    text_emb: Any,
    timestep: int = 500,
    num_heads: int = 8,
    num_active_tokens: int = 5,
    include_bos_token: bool = False,
) -> dict[str, Any]:
    """Run T2IShield-style dynamic cross-attention map F-norm, entropy, and assimilation audit.

    Uses temporary read-only pass-through hooks on `.attn2` blocks (restored cleanly in `finally`).
    Never alters UNet weights or gradients.
    """
    import torch
    import torch.nn as nn

    device = next(unet.parameters()).device
    unet_dtype = next(unet.parameters()).dtype

    # Locate `.attn2` blocks that expose `to_q` and `to_k`
    attn2_blocks: dict[str, Any] = {}
    for mod_name, mod in unet.named_modules():
        if mod_name.endswith(".attn2") or mod_name == "attn2":
            if hasattr(mod, "to_q") and hasattr(mod, "to_k"):
                attn2_blocks[mod_name] = mod

    class _RecordingLinear(nn.Module):
        def __init__(self, inner: nn.Module) -> None:
            super().__init__()
            self.inner = inner
            self.last_out: Any | None = None

        @property
        def in_features(self) -> int:
            return int(self.inner.in_features)

        @property
        def out_features(self) -> int:
            return int(self.inner.out_features)

        @property
        def weight(self) -> Any:
            return self.inner.weight

        def forward(self, x: Any) -> Any:
            out = self.inner(x)
            self.last_out = out.detach().float()
            return out

    recorders: dict[str, tuple[_RecordingLinear, _RecordingLinear, int]] = {}
    originals: list[tuple[Any, str, Any]] = []
    for blk_name, blk in sorted(attn2_blocks.items()):
        orig_q = blk.to_q
        orig_k = blk.to_k
        rec_q = _RecordingLinear(orig_q)
        rec_k = _RecordingLinear(orig_k)
        originals.append((blk, "to_k", orig_k))
        originals.append((blk, "to_q", orig_q))
        blk.to_q = rec_q
        blk.to_k = rec_k
        blk_heads = int(getattr(blk, "heads", num_heads))
        recorders[blk_name] = (rec_q, rec_k, blk_heads)

    layer_metrics: dict[str, dict[str, Any]] = {}
    try:
        t_tensor = torch.tensor([int(timestep)] * int(latents.shape[0])).to(device)
        with torch.no_grad():
            _ = unet(latents.to(device).to(unet_dtype), t_tensor, text_emb.to(device).to(unet_dtype))

        start_tok = 0 if include_bos_token else 1
        for blk_name, (rec_q, rec_k, heads) in sorted(recorders.items()):
            q = rec_q.last_out
            k = rec_k.last_out
            if q is None or k is None:
                continue
            if q.ndim == 2:
                q = q.reshape(int(q.shape[0]), 1, int(q.shape[1]))
            if k.ndim == 2:
                k = k.reshape(int(k.shape[0]), 1, int(k.shape[1]))
            if q.ndim != 3 or k.ndim != 3:
                continue
            b_sz, hw_len, dim = int(q.shape[0]), int(q.shape[1]), int(q.shape[2])
            tok_len = int(k.shape[1])
            eff_heads = heads if (heads > 0 and dim % heads == 0) else 1
            attn_map = _compute_head_mean_attn_map(q, k, eff_heads)

            start_tok_blk = 0 if (include_bos_token or tok_len <= 1) else 1
            end_tok = min(tok_len, start_tok_blk + max(1, int(num_active_tokens)))
            token_vecs: list[Any] = []
            tok_fros: list[float] = []
            tok_entropies: list[float] = []
            log_hw = math.log(max(2, hw_len))

            for t_idx in range(start_tok_blk, end_tok):
                m_t = attn_map[0, :, t_idx]
                fro = float((m_t * m_t).sum().sqrt().item())
                p_t = m_t / m_t.sum().clamp(min=1e-12)
                ent = _safe_entropy_normalized(p_t, log_hw)
                tok_fros.append(fro)
                tok_entropies.append(ent)
                token_vecs.append(m_t)

            pair_cos: list[float] = []
            for i in range(len(token_vecs)):
                for j in range(i + 1, len(token_vecs)):
                    pair_cos.append(_cosine_vectors(token_vecs[i], token_vecs[j]))

            mean_fn = lambda xs: (sum(xs) / len(xs)) if xs else 0.0
            layer_metrics[blk_name] = {
                "is_bottleneck_24": is_ours_bottleneck_target(f"{blk_name}.to_k"),
                "spatial_positions": hw_len,
                "active_tokens": len(tok_fros),
                "mean_token_fro_norm": mean_fn(tok_fros),
                "max_token_fro_norm": max(tok_fros) if tok_fros else 0.0,
                "mean_token_entropy": mean_fn(tok_entropies),
                "assimilation_cosine": mean_fn(pair_cos),
                "per_token_fro_norms": tok_fros,
            }
    finally:
        for obj, attr_name, orig_mod in reversed(originals):
            setattr(obj, attr_name, orig_mod)

    bn_vals = [v for v in layer_metrics.values() if v["is_bottleneck_24"]]
    out_vals = [v for v in layer_metrics.values() if not v["is_bottleneck_24"]]
    all_vals = list(layer_metrics.values())
    mean_key = lambda rows, key: (sum(float(r[key]) for r in rows) / len(rows)) if rows else 0.0

    return {
        "timestep": int(timestep),
        "num_blocks_audited": len(layer_metrics),
        "mean_token_fro_norm": mean_key(all_vals, "mean_token_fro_norm"),
        "max_token_fro_norm": max((float(r["max_token_fro_norm"]) for r in all_vals), default=0.0),
        "mean_token_entropy": mean_key(all_vals, "mean_token_entropy"),
        "mean_assimilation_cosine": mean_key(all_vals, "assimilation_cosine"),
        "bottleneck_mean_token_fro_norm": mean_key(bn_vals, "mean_token_fro_norm"),
        "bottleneck_mean_assimilation_cosine": mean_key(bn_vals, "assimilation_cosine"),
        "outer_mean_token_fro_norm": mean_key(out_vals, "mean_token_fro_norm"),
        "outer_mean_assimilation_cosine": mean_key(out_vals, "assimilation_cosine"),
        "layers": layer_metrics,
    }


def write_defense_audit_report(
    out_dir: str | Path,
    results: dict[str, Any],
) -> tuple[Path, Path]:
    """Persist structured JSON and Markdown audit summary."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    json_path = out_path / "defense_audit.json"
    md_path = out_path / "DEFENSE_AUDIT.md"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    static_map = results.get("static_spectra", {})
    md_write(
        md_path,
        "Post-Hoc Defense & Spectral Observability Audit",
        {
            "num_adapters_audited": len(static_map),
            "adapters": ", ".join(sorted(static_map)),
            "has_dynamic_t2ishield": bool(results.get("dynamic_t2ishield")),
            "has_peripheral_floor_ablation": bool(results.get("peripheral_floor_ablation")),
            "json_path": str(json_path),
        },
    )
    lines = [md_path.read_text(encoding="utf-8").rstrip(), "", "## PEFTGuard Static Spectral Summary", ""]
    lines.append("| Adapter | Active/Ref UNet | `||ΔW||_F` | `||ΔW_TE||_F` | `Gini_all` | `Gini_active` | `Mean Top1 SV Ratio` | `Mean Kurtosis` | `KV:QO Ratio` |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, sp in sorted(static_map.items()):
        kv_qo = sp.get("kv_to_qo_norm_ratio")
        kv_qo_str = "inf" if kv_qo is None else f"{kv_qo:.3f}"
        lines.append(
            f"| {name} | {sp['active_unet_layers']}/{sp['total_unet_reference_layers']} | "
            f"{sp['total_frobenius']:.4f} | {sp['text_encoder_frobenius']:.4f} | "
            f"{sp['gini_all_unet']:.4f} | {sp['gini_active_unet']:.4f} | "
            f"{sp['mean_top1_sv_energy_ratio']:.4f} | {sp['mean_kurtosis']:.4f} | {kv_qo_str} |"
        )
    if results.get("peripheral_floor_ablation"):
        pfa = results["peripheral_floor_ablation"]
        after = pfa["after_spectrum"]
        lines.extend(
            [
                "",
                "## Peripheral Benign Floor Post-Hoc Comparison",
                "",
                f"- Floor per peripheral UNet layer: `{pfa['peripheral_floor_norm_per_layer']}`, added layers: `{pfa['peripheral_layers_added']}`",
                f"- `Gini_all`: `{pfa['before_spectrum']['gini_all_unet']:.4f}` -> `{after['gini_all_unet']:.4f}`",
                f"- Total norm: `{after['total_frobenius']:.4f}` (TE: `{after['text_encoder_frobenius']:.4f}`)",
            ]
        )
    if results.get("dynamic_t2ishield"):
        lines.extend(["", "## T2IShield Dynamic Cross-Attention Summary", ""])
        lines.append("| Probe | `Mean Token F-Norm` | `Mean Entropy` | `Assimilation Cosine` | `Bottleneck Assim Cos` |")
        lines.append("|---|---:|---:|---:|---:|")
        for pname, dyn in sorted(results["dynamic_t2ishield"].items()):
            lines.append(
                f"| {pname} | {dyn['mean_token_fro_norm']:.4f} | {dyn['mean_token_entropy']:.4f} | "
                f"{dyn['mean_assimilation_cosine']:.4f} | {dyn['bottleneck_mean_assimilation_cosine']:.4f} |"
            )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Post-hoc PEFTGuard & T2IShield defense audit for MVP LoRA adapters.")
    p.add_argument("--adapter", action="append", required=True, help="Adapter path (name=path or path).")
    p.add_argument("--out-dir", type=str, required=True, help="Output directory for defense_audit.json & .md.")
    p.add_argument("--reference-adapter", type=str, default=None, help="Optional benign reference LoRA for peripheral floor test.")
    p.add_argument("--peripheral-floor", type=float, default=0.0, help="Optional post-hoc peripheral floor norm/layer (e.g. 0.05).")
    p.add_argument("--config", type=str, default=None, help="Optional MVP JSON config (needed with --run-dynamic).")
    p.add_argument("--run-dynamic", action="store_true", help="Also run T2IShield dynamic cross-attention audit (requires SD1.5).")
    p.add_argument("--device", type=str, default="auto", choices=["auto", "cpu", "cuda"])
    p.add_argument("--timestep", type=int, default=500)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    enforce_offline_env()

    loaded_adapters: dict[str, LoRAAdapter] = {}
    for idx, spec in enumerate(args.adapter):
        if "=" in spec:
            name, path = spec.split("=", 1)
        else:
            path = spec
            name = Path(path).parent.name or f"adapter_{idx}"
        loaded_adapters[name] = load_lora_adapter(path, name=name)

    static_spectra = {
        name: audit_static_adapter_spectrum(adapter)
        for name, adapter in loaded_adapters.items()
    }

    periph_result: dict[str, Any] | None = None
    if args.peripheral_floor > 0.0 and loaded_adapters:
        first_name, first_adapter = next(iter(loaded_adapters.items()))
        ref_adapter = load_lora_adapter(args.reference_adapter, name="benign_ref") if args.reference_adapter else None
        _, periph_result = apply_peripheral_benign_floor(
            first_adapter,
            reference_adapter=ref_adapter,
            peripheral_floor_norm_per_layer=args.peripheral_floor,
            target_total_norm=18.0,
        )
        periph_result["source_adapter"] = first_name

    dyn_results: dict[str, Any] = {}
    if args.run_dynamic:
        import torch
        from scripts.lora_composition_mvp.operators import AppliedAdapterContext, compose_s0_single
        from scripts.lora_composition_mvp.trainers import _encode_prompt, load_sd15_components

        cfg = load_config(args.config) if args.config else MVPConfig()
        dev = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
        dtype = "float16" if str(dev).startswith("cuda") else "float32"
        comps = load_sd15_components(cfg.model_dir, device=dev, dtype_str=dtype)
        unet = comps["unet"]
        emb_clean = _encode_prompt(comps["tokenizer"], comps["text_encoder"], cfg.clean_prompt, device=dev)
        emb_trig = _encode_prompt(comps["tokenizer"], comps["text_encoder"], cfg.trigger_prompt, device=dev)
        latent_shape = (1, int(getattr(unet.config, "in_channels", 4)), cfg.resolution // 8, cfg.resolution // 8)
        gen = torch.Generator(device="cpu")
        gen.manual_seed(cfg.seed + 777)
        probe_latents = torch.randn(latent_shape, generator=gen).to(dev)

        for name, adapter in loaded_adapters.items():
            plan = compose_s0_single(adapter)
            with AppliedAdapterContext(plan, unet=unet, text_encoder=comps["text_encoder"]):
                dyn_results[f"{name}::clean"] = audit_dynamic_cross_attention(
                    unet, probe_latents, emb_clean, timestep=args.timestep
                )
                dyn_results[f"{name}::trigger"] = audit_dynamic_cross_attention(
                    unet, probe_latents, emb_trig, timestep=args.timestep
                )

    payload = {
        "static_spectra": static_spectra,
        "peripheral_floor_ablation": periph_result,
        "dynamic_t2ishield": dyn_results,
    }
    json_path, md_path = write_defense_audit_report(args.out_dir, payload)
    print(f"Wrote defense audit: {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
