"""Composition simulators (training-time), inference composition operators (S0..S3), and SVD P_test extractor."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .io_utils import (
    LoRAAdapter,
    LoRALayerFactor,
    compute_adapter_norms,
    digest,
    is_attention_linear,
    save_lora_adapter,
)


def _load_unet_weight_dict(model_dir: str | Path) -> dict[str, Any]:
    """Load UNet state_dict from safetensors file directly first (avoids partial upload chunks)."""
    p = Path(model_dir)
    st_file = p / "unet" / "diffusion_pytorch_model.safetensors"
    if st_file.is_file():
        from safetensors.torch import load_file

        return load_file(str(st_file), device="cpu")
    bin_file = p / "unet" / "diffusion_pytorch_model.bin"
    if bin_file.is_file():
        import torch

        return torch.load(str(bin_file), map_location="cpu")

    from diffusers import UNet2DConditionModel

    unet = UNet2DConditionModel.from_pretrained(str(p), subfolder="unet", local_files_only=True)
    sd = {k: v.detach().cpu() for k, v in unet.state_dict().items()}
    del unet
    return sd


def _load_text_encoder_weight_dict(model_dir: str | Path) -> dict[str, Any]:
    """Load CLIPTextModel state_dict from safetensors/bin directly first (avoids stale upload chunks)."""
    p = Path(model_dir)
    st_file = p / "text_encoder" / "model.safetensors"
    if st_file.is_file():
        from safetensors.torch import load_file

        return load_file(str(st_file), device="cpu")
    bin_file = p / "text_encoder" / "pytorch_model.bin"
    if bin_file.is_file():
        import torch

        return torch.load(str(bin_file), map_location="cpu")

    from transformers import CLIPTextModel

    te = CLIPTextModel.from_pretrained(str(p), subfolder="text_encoder", local_files_only=True)
    sd = {k: v.detach().cpu() for k, v in te.state_dict().items()}
    del te
    return sd


def _is_te_attention_linear(mod_name: str) -> bool:
    return (".self_attn." in mod_name or ".attn." in mod_name) and any(
        mod_name.endswith(f".{p}") for p in ("q_proj", "k_proj", "v_proj", "out_proj", "to_q", "to_k", "to_v", "to_out.0")
    )


def extract_svd_lora_from_model_diff(
    base_model_dir: str | Path,
    finetuned_model_dir: str | Path,
    rank: int = 16,
    out_path: str | Path | None = None,
    include_text_encoder: bool = False,
    te_rank: int | None = None,
) -> tuple[LoRAAdapter, dict[str, Any]]:
    """Construct offline rank-r LoRA P_test via truncated SVD of (finetuned - base) UNet (+ optional TE)."""
    import torch

    base_sd = _load_unet_weight_dict(base_model_dir)
    ft_sd = _load_unet_weight_dict(finetuned_model_dir)

    layers: dict[str, LoRALayerFactor] = {}
    total_diff_sq = 0.0
    recon_sq = 0.0
    skipped = 0
    unet_count = 0
    te_count = 0

    def _collect_component(comp: str, sd0: dict[str, Any], sd1: dict[str, Any], pred_fn: Any, r_target: int) -> None:
        nonlocal total_diff_sq, recon_sq, skipped, unet_count, te_count
        for key in sorted(sd0.keys()):
            if not key.endswith(".weight"):
                continue
            mod_name = key[: -len(".weight")]
            if not pred_fn(mod_name):
                continue
            if key not in sd1:
                skipped += 1
                continue
            w0 = sd0[key].float()
            w1 = sd1[key].float()
            if w0.shape != w1.shape or w0.ndim != 2:
                skipped += 1
                continue

            dw = w1 - w0
            diff_sq = float((dw * dw).sum().item())
            total_diff_sq += diff_sq
            if diff_sq <= 1e-16:
                continue

            u, s, vh = torch.linalg.svd(dw, full_matrices=False)
            r = max(1, min(int(r_target), int(s.shape[0])))
            sq = torch.sqrt(s[:r].clamp(min=0.0))
            b = (u[:, :r] * sq.reshape(1, r)).contiguous()
            a = (sq.reshape(r, 1) * vh[:r, :]).contiguous()
            recon_sq += float((s[:r] * s[:r]).sum().item())

            layers[f"{comp}.{mod_name}"] = LoRALayerFactor(
                component=comp,
                module_name=mod_name,
                lora_A=a,
                lora_B=b,
                alpha_scale=1.0,
            )
            if comp == "unet":
                unet_count += 1
            else:
                te_count += 1

    _collect_component(
        "unet",
        base_sd,
        ft_sd,
        lambda m: (".attn1." in m or ".attn2." in m) and is_attention_linear(m),
        int(rank),
    )

    if include_text_encoder:
        base_te_sd = _load_text_encoder_weight_dict(base_model_dir)
        ft_te_sd = _load_text_encoder_weight_dict(finetuned_model_dir)
        _collect_component(
            "text_encoder",
            base_te_sd,
            ft_te_sd,
            _is_te_attention_linear,
            int(te_rank if te_rank is not None else rank),
        )

    if not layers:
        raise RuntimeError(
            f"No matching attention projection diffs found between {base_model_dir} and {finetuned_model_dir}."
        )

    explained = recon_sq / max(1e-12, total_diff_sq)
    adapter = LoRAAdapter(
        name="p_test_svd16",
        layers=layers,
        metadata={
            "source_base": str(base_model_dir),
            "source_finetuned": str(finetuned_model_dir),
            "rank": rank,
            "include_text_encoder": include_text_encoder,
            "explained_energy_ratio": explained,
        },
    )
    saved_sha = None
    if out_path is not None:
        p = save_lora_adapter(adapter, out_path, rank_svd_fallback=rank)
        saved_sha = digest(p)
        adapter.metadata["path"] = str(p)
        adapter.metadata["sha256"] = saved_sha

    stats = {
        "layer_count": len(layers),
        "unet_layer_count": unet_count,
        "te_layer_count": te_count,
        "include_text_encoder": include_text_encoder,
        "skipped": skipped,
        "total_diff_frobenius": math.sqrt(max(0.0, total_diff_sq)),
        "reconstructed_frobenius": math.sqrt(max(0.0, recon_sq)),
        "explained_energy_ratio": explained,
        "sha256": saved_sha,
    }
    return adapter, stats


def trim_topk_tensor(tensor: Any, density: float) -> Any:
    """Keep top `density` fraction by magnitude (matching merge_tracer.py TIES trim)."""
    import torch

    if density >= 1.0:
        return tensor
    if density <= 0.0:
        return torch.zeros_like(tensor)
    flat = tensor.abs().reshape(-1)
    n = int(flat.numel())
    k = max(1, min(n, int(math.ceil(n * float(density)))))
    top_vals, _ = torch.topk(flat, k)
    threshold = top_vals[-1]
    mask = (tensor.abs() >= threshold).to(tensor.dtype)
    return tensor * mask


def simulate_composed_delta(
    lora_A: Any,
    lora_B: Any,
    alpha_scale: float,
    rank_ben: int,
    mode: str,
    scale: float,
    drop_rate: float = 0.4,
    trim_density: float = 0.5,
    partner_delta: Any | None = None,
    generator: Any | None = None,
) -> Any:
    """Differentiable composition operator distortion on backdoor branch during training."""
    import torch

    a_ben = lora_A[:rank_ben, :]
    b_ben = lora_B[:, :rank_ben]
    a_bd = lora_A[rank_ben:, :]
    b_bd = lora_B[:, rank_ben:]

    delta_ben = (b_ben @ a_ben) * float(alpha_scale)
    delta_bd = (b_bd @ a_bd) * float(alpha_scale)

    if mode == "scale":
        sim_bd = delta_bd * float(scale)
    elif mode == "dare":
        keep_prob = max(1e-3, 1.0 - float(drop_rate))
        if generator is not None:
            gen_dev = getattr(generator, "device", "cpu")
            rnd = torch.rand(delta_bd.shape, generator=generator, device=gen_dev, dtype=torch.float32).to(delta_bd.device)
        else:
            rnd = torch.rand(delta_bd.shape, device=delta_bd.device, dtype=torch.float32)
        mask = (rnd < keep_prob).to(delta_bd.dtype)
        sim_bd = delta_bd * mask * (float(scale) / keep_prob)
    elif mode == "ties":
        scaled_bd = delta_bd * float(scale)
        trimmed_bd = trim_topk_tensor(scaled_bd, density=float(trim_density))
        if partner_delta is not None and partner_delta.shape == scaled_bd.shape:
            p_trim = trim_topk_tensor(partner_delta.to(scaled_bd.device).float(), density=float(trim_density))
            elected = torch.sign(trimmed_bd + p_trim)
            keep_sign = ((torch.sign(trimmed_bd) == elected) | (elected == 0)).to(trimmed_bd.dtype)
            sim_bd = trimmed_bd * keep_sign
        else:
            sim_bd = trimmed_bd
    else:
        raise ValueError(f"Unknown training simulation mode: {mode!r}")

    return delta_ben + sim_bd


def simulate_full_delta_operator(
    lora_A: Any,
    lora_B: Any,
    alpha_scale: float,
    mode: str,
    scale: float = 1.0,
    trim_density: float = 0.5,
    partner_delta: Any | None = None,
    partner_scale: float = 0.8,
    partner_trimmed_delta: Any | None = None,
) -> Any:
    """Differentiable operator simulation (Id / Scale / TIES) on unified full-rank LoRA matrix."""
    import torch

    delta = (lora_B @ lora_A) * float(alpha_scale)
    if mode == "id":
        return delta
    if mode == "scale":
        return delta * float(scale)
    if mode == "ties":
        scaled = delta * float(scale)
        c_trim = trim_topk_tensor(scaled, density=float(trim_density))
        p_trim = partner_trimmed_delta
        if p_trim is None and partner_delta is not None and partner_delta.shape == scaled.shape:
            p_trim = trim_topk_tensor(
                partner_delta.to(scaled.device).float() * float(partner_scale),
                density=float(trim_density),
            )
        if p_trim is not None and p_trim.shape == scaled.shape:
            p_trim_dev = p_trim.to(scaled.device).float()
            elected = torch.sign(c_trim + p_trim_dev)
            c_keep = ((torch.sign(c_trim) == elected) | (elected == 0)).to(c_trim.dtype)
            c_aligned = c_trim * c_keep
            p_keep = (torch.sign(p_trim_dev) == elected).to(p_trim_dev.dtype)
            p_aligned = p_trim_dev * p_keep
            count = ((c_aligned != 0).to(c_trim.dtype) + (p_aligned != 0).to(c_trim.dtype)).clamp(min=1.0)
            return c_aligned / count
        return c_trim
    raise ValueError(f"Unknown CORE-LoRA operator mode: {mode!r}")


@dataclass
class ComposedLoRAPlan:
    """Unified runtime representation produced by all composition scenarios S0..S3."""

    arm: str
    scenario: str
    mode: str  # "static_delta" | "klora_dynamic"
    static_adapter: LoRAAdapter | None = None
    klora_layers: dict[str, dict[str, Any]] = field(default_factory=dict)
    klora_gamma: float = 1.0
    klora_alpha: float = 1.5
    klora_beta: float = 0.5
    effective_cand_norms: dict[str, Any] = field(default_factory=dict)
    effective_merged_norms: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def compose_s0_single(cand: LoRAAdapter) -> ComposedLoRAPlan:
    layers: dict[str, LoRALayerFactor] = {}
    for k, layer in cand.layers.items():
        layers[k] = LoRALayerFactor(
            component=layer.component,
            module_name=layer.module_name,
            dense_delta=layer.compute_delta(scale=1.0).detach().cpu(),
            alpha_scale=1.0,
        )
    merged = LoRAAdapter(name=f"{cand.name}_S0", layers=layers)
    cand_norms = compute_adapter_norms(cand, te_scale=1.0, unet_scale=1.0)
    merged_norms = compute_adapter_norms(merged, te_scale=1.0, unet_scale=1.0)
    return ComposedLoRAPlan(
        arm=cand.name,
        scenario="S0",
        mode="static_delta",
        static_adapter=merged,
        effective_cand_norms=cand_norms,
        effective_merged_norms=merged_norms,
        diagnostics={"operator": "single", "cand_scale": 1.0},
    )


def compose_s1_partial_te0(
    cand: LoRAAdapter,
    partner: LoRAAdapter,
    cand_te_scale: float = 0.0,
    cand_unet_scale: float = 0.5,
    partner_scale: float = 0.8,
    partner_te_scale: float = 0.0,
) -> ComposedLoRAPlan:
    """S1: Candidate TE zeroed (te_scale=0.0) + UNet attenuated (0.5) composed with P_test (0.8)."""
    all_keys = sorted(set(cand.layers) | set(partner.layers))
    layers: dict[str, LoRALayerFactor] = {}
    for full_key in all_keys:
        c_layer = cand.layers.get(full_key)
        p_layer = partner.layers.get(full_key)
        ref = c_layer or p_layer
        assert ref is not None
        acc = None
        if c_layer is not None:
            cs = cand_unet_scale if c_layer.component == "unet" else cand_te_scale
            if abs(cs) > 0.0:
                acc = c_layer.compute_delta(scale=cs).detach().cpu()
        if p_layer is not None:
            ps = partner_scale if p_layer.component == "unet" else partner_te_scale
            if abs(ps) > 0.0:
                pd = p_layer.compute_delta(scale=ps).detach().cpu()
                acc = pd if acc is None else (acc + pd)
        if acc is not None:
            layers[full_key] = LoRALayerFactor(
                component=ref.component,
                module_name=ref.module_name,
                dense_delta=acc,
                alpha_scale=1.0,
            )

    merged = LoRAAdapter(name=f"{cand.name}_S1", layers=layers)
    cand_norms = compute_adapter_norms(cand, te_scale=cand_te_scale, unet_scale=cand_unet_scale)
    merged_norms = compute_adapter_norms(merged)
    return ComposedLoRAPlan(
        arm=cand.name,
        scenario="S1",
        mode="static_delta",
        static_adapter=merged,
        effective_cand_norms=cand_norms,
        effective_merged_norms=merged_norms,
        diagnostics={
            "operator": "additive_te0",
            "cand_te_scale": cand_te_scale,
            "cand_unet_scale": cand_unet_scale,
            "partner_scale": partner_scale,
            "partner_te_scale": partner_te_scale,
        },
    )


def compose_s2_ties(
    cand: LoRAAdapter,
    partner: LoRAAdapter,
    cand_scale: float = 0.5,
    partner_scale: float = 0.8,
    density: float = 0.5,
    lambda_scale: float = 1.0,
    cand_te_scale: float | None = None,
    partner_te_scale: float | None = None,
) -> ComposedLoRAPlan:
    """S2 (TIES): Top-density trim + consensus sign election + disjoint mean (exact merge_tracer logic)."""
    import torch

    all_keys = sorted(set(cand.layers) | set(partner.layers))
    layers: dict[str, LoRALayerFactor] = {}
    cand_effective_deltas: dict[str, LoRALayerFactor] = {}
    overlap_count = 0

    for full_key in all_keys:
        c_layer = cand.layers.get(full_key)
        p_layer = partner.layers.get(full_key)
        ref = c_layer or p_layer
        assert ref is not None
        deltas: list[Any] = []
        c_trimmed = None

        cs = cand_scale if ref.component == "unet" else (cand_scale if cand_te_scale is None else float(cand_te_scale))
        ps = partner_scale if ref.component == "unet" else (partner_scale if partner_te_scale is None else float(partner_te_scale))

        if c_layer is not None and abs(cs) > 0.0:
            cd = c_layer.compute_delta(scale=cs).detach().cpu()
            c_trimmed = trim_topk_tensor(cd, density=density)
            deltas.append(c_trimmed)
        if p_layer is not None and abs(ps) > 0.0:
            pd = p_layer.compute_delta(scale=ps).detach().cpu()
            p_trimmed = trim_topk_tensor(pd, density=density)
            deltas.append(p_trimmed)

        if not deltas:
            continue
        if len(deltas) == 1:
            merged_d = deltas[0] * float(lambda_scale)
            c_surviving = c_trimmed * float(lambda_scale) if c_trimmed is not None else None
        else:
            overlap_count += 1
            stacked = torch.stack(deltas, dim=0)
            sign_sum = torch.sign(stacked.sum(dim=0))
            aligned_mask = (torch.sign(stacked) == sign_sum)
            aligned = stacked * aligned_mask.to(stacked.dtype)
            count = (aligned != 0).to(stacked.dtype).sum(dim=0).clamp(min=1.0)
            merged_d = (aligned.sum(dim=0) / count) * float(lambda_scale)
            c_surviving = (aligned[0] / count) * float(lambda_scale)

        layers[full_key] = LoRALayerFactor(
            component=ref.component,
            module_name=ref.module_name,
            dense_delta=merged_d,
            alpha_scale=1.0,
        )
        if c_surviving is not None:
            cand_effective_deltas[full_key] = LoRALayerFactor(
                component=ref.component,
                module_name=ref.module_name,
                dense_delta=c_surviving,
                alpha_scale=1.0,
            )

    merged = LoRAAdapter(name=f"{cand.name}_S2_ties", layers=layers)
    cand_surv_adapter = LoRAAdapter(name=f"{cand.name}_S2_ties_surv", layers=cand_effective_deltas)
    return ComposedLoRAPlan(
        arm=cand.name,
        scenario="S2_ties",
        mode="static_delta",
        static_adapter=merged,
        effective_cand_norms=compute_adapter_norms(cand_surv_adapter),
        effective_merged_norms=compute_adapter_norms(merged),
        diagnostics={
            "operator": "ties",
            "cand_scale": cand_scale,
            "partner_scale": partner_scale,
            "density": density,
            "lambda_scale": lambda_scale,
            "overlap_layers": overlap_count,
        },
    )


def prepare_s2_klora(
    cand: LoRAAdapter,
    partner: LoRAAdapter,
    cand_scale: float = 0.5,
    partner_scale: float = 0.8,
    k_rank_ref: int = 16,
    alpha: float = 1.5,
    beta: float = 0.5,
    num_steps: int = 25,
    partner_te_scale: float = 0.0,
) -> ComposedLoRAPlan:
    """S2 (K-LoRA, arXiv:2502.18461): Dynamic per-layer per-timestep Top-K winner selection."""
    import torch

    all_keys = sorted(set(cand.layers) | set(partner.layers))
    klora_layers: dict[str, dict[str, Any]] = {}
    te_partner_layers: dict[str, LoRALayerFactor] = {}
    c_mean_mags: list[float] = []
    s_mean_mags: list[float] = []
    shared_unet = 0

    for full_key in all_keys:
        c_layer = cand.layers.get(full_key)
        p_layer = partner.layers.get(full_key)
        ref = c_layer or p_layer
        assert ref is not None
        if ref.component != "unet":
            if p_layer is not None and abs(float(partner_te_scale)) > 0.0:
                te_partner_layers[full_key] = LoRALayerFactor(
                    component=p_layer.component,
                    module_name=p_layer.module_name,
                    dense_delta=p_layer.compute_delta(scale=float(partner_te_scale)).detach().cpu(),
                    alpha_scale=1.0,
                )
            continue

        dc = c_layer.compute_delta(scale=cand_scale).detach().cpu() if c_layer is not None else None
        ds = p_layer.compute_delta(scale=partner_scale).detach().cpu() if p_layer is not None else None

        sc = 0.0
        ss = 0.0
        if dc is not None:
            flat_c = dc.abs().reshape(-1)
            kc = min(int(flat_c.numel()), max(1, int(k_rank_ref) * int(k_rank_ref)))
            top_c, _ = torch.topk(flat_c, kc)
            sc = float(top_c.sum().item())
        if ds is not None:
            flat_s = ds.abs().reshape(-1)
            ks = min(int(flat_s.numel()), max(1, int(k_rank_ref) * int(k_rank_ref)))
            top_s, _ = torch.topk(flat_s, ks)
            ss = float(top_s.sum().item())

        if dc is not None and ds is not None and sc > 0.0 and ss > 0.0:
            shared_unet += 1
            c_mean_mags.append(float(dc.abs().mean().item()))
            s_mean_mags.append(float(ds.abs().mean().item()))

        klora_layers[full_key] = {
            "delta_c": dc,
            "delta_s": ds,
            "score_c": sc,
            "score_s": ss,
        }

    if c_mean_mags and sum(s_mean_mags) > 1e-12:
        gamma = max(1e-6, sum(c_mean_mags) / sum(s_mean_mags))
    else:
        gamma = 1.0

    # Full denoising schedule (e.g., 25 steps) layer-wise win curve diagnostics
    n_steps = max(1, int(num_steps))
    wins_per_step: list[int] = []
    kv_wins_per_step: list[int] = []
    qo_wins_per_step: list[int] = []
    cand_selected_layers: dict[str, LoRALayerFactor] = {}
    total_kv_layers = sum(1 for k in klora_layers if k.endswith((".to_k", ".to_v")))
    total_qo_layers = sum(1 for k in klora_layers if k.endswith((".to_q", ".to_out.0")))
    cand_active_layers = sum(
        1 for info in klora_layers.values() if info["delta_c"] is not None and float(info["score_c"]) > 0.0
    )

    for step_idx in range(n_steps):
        step_wins = 0
        step_kv = 0
        step_qo = 0
        for full_key, info in klora_layers.items():
            pick_c = select_klora_choice(info, step_idx=step_idx, num_steps=n_steps, gamma=gamma, alpha=alpha, beta=beta)
            if pick_c and info["delta_c"] is not None:
                step_wins += 1
                if full_key.endswith((".to_k", ".to_v")):
                    step_kv += 1
                elif full_key.endswith((".to_q", ".to_out.0")):
                    step_qo += 1
                if step_idx == 0:
                    comp, mod = full_key.split(".", 1)
                    cand_selected_layers[full_key] = LoRALayerFactor(
                        component=comp,
                        module_name=mod,
                        dense_delta=info["delta_c"],
                    )
        wins_per_step.append(step_wins)
        kv_wins_per_step.append(step_kv)
        qo_wins_per_step.append(step_qo)

    cand_wins_t0 = wins_per_step[0] if wins_per_step else 0
    mean_wins = sum(wins_per_step) / float(max(1, len(wins_per_step)))
    mean_kv_wins = sum(kv_wins_per_step) / float(max(1, len(kv_wins_per_step)))
    mean_qo_wins = sum(qo_wins_per_step) / float(max(1, len(qo_wins_per_step)))
    total_unet = len(klora_layers)

    te_static = LoRAAdapter(name=f"{cand.name}_klora_partner_te", layers=te_partner_layers) if te_partner_layers else None
    merged_t0_layers = {**cand_selected_layers, **te_partner_layers}
    cand_norms = compute_adapter_norms(cand, te_scale=0.0, unet_scale=cand_scale)
    cand_win_t0_norms = compute_adapter_norms(LoRAAdapter(name=f"{cand.name}_klora_t0", layers=merged_t0_layers))
    return ComposedLoRAPlan(
        arm=cand.name,
        scenario="S2_klora",
        mode="klora_dynamic",
        static_adapter=te_static,
        klora_layers=klora_layers,
        klora_gamma=gamma,
        klora_alpha=alpha,
        klora_beta=beta,
        effective_cand_norms=cand_norms,
        effective_merged_norms=cand_win_t0_norms,
        diagnostics={
            "operator": "k_lora",
            "gamma": gamma,
            "alpha": alpha,
            "beta": beta,
            "num_steps": n_steps,
            "shared_unet_layers": shared_unet,
            "cand_wins_at_step0": cand_wins_t0,
            "total_unet_layers": total_unet,
            "total_kv_layers": total_kv_layers,
            "total_qo_layers": total_qo_layers,
            "cand_active_layers": cand_active_layers,
            "wins_per_step": wins_per_step,
            "kv_wins_per_step": kv_wins_per_step,
            "qo_wins_per_step": qo_wins_per_step,
            "mean_wins_across_all_steps": mean_wins,
            "mean_win_rate_across_all_steps": mean_wins / float(max(1, total_unet)),
            "mean_active_win_rate_across_all_steps": mean_wins / float(max(1, cand_active_layers)),
            "mean_kv_wins_across_all_steps": mean_kv_wins,
            "mean_qo_wins_across_all_steps": mean_qo_wins,
            "partner_te_scale": partner_te_scale,
        },
    )


def select_klora_choice(
    layer_info: dict[str, Any],
    step_idx: int,
    num_steps: int,
    gamma: float,
    alpha: float = 1.5,
    beta: float = 0.5,
) -> bool:
    """Return True if candidate ΔW_c wins layer selection at step_idx, False if P_test ΔW_s wins."""
    sc = float(layer_info["score_c"])
    ss = float(layer_info["score_s"])
    if layer_info["delta_c"] is None or sc <= 0.0:
        return False
    if layer_info["delta_s"] is None or ss <= 0.0:
        return True
    progress = float(step_idx) / max(1, int(num_steps))
    style_factor = float(alpha) * progress + float(beta)
    top_k_sum1 = sc / max(1e-8, float(gamma))
    top_k_sum2 = ss * style_factor
    return top_k_sum1 > top_k_sum2


def _column_abs_cos_vec(dc: Any, ds: Any, eps: float = 1e-8) -> Any:
    """Precompute per-column |cos(ΔW_c[:, j], ΔW_s[:, j])| vector of shape (d_in,)."""
    import torch

    dot = (dc * ds).sum(dim=0).abs()
    nc = torch.sqrt((dc * dc).sum(dim=0) + eps)
    ns = torch.sqrt((ds * ds).sum(dim=0) + eps)
    return dot / (nc * ns + eps)


def compose_s2_dare(
    cand: LoRAAdapter,
    partner: LoRAAdapter,
    cand_scale: float = 0.5,
    partner_scale: float = 0.8,
    drop_rate: float = 0.5,
    lambda_scale: float = 1.0,
    cand_te_scale: float = 0.0,
    partner_te_scale: float = 0.0,
    seed: int = 42,
    prune_partner: bool = True,
) -> ComposedLoRAPlan:
    """S2 (DARE, arXiv:2311.03377): Unseen random drop-and-rescale (1 / (1 - p)) merging operator."""
    import torch

    p = float(drop_rate)
    if not (0.0 <= p < 1.0):
        raise ValueError(f"drop_rate must be in [0, 1), got {drop_rate}")
    keep_prob = 1.0 - p
    rescale = 1.0 / keep_prob

    gen = torch.Generator(device="cpu")
    gen.manual_seed(int(seed) + 709)

    all_keys = sorted(set(cand.layers) | set(partner.layers))
    layers: dict[str, LoRALayerFactor] = {}
    cand_effective_deltas: dict[str, LoRALayerFactor] = {}
    overlap_count = 0

    for full_key in all_keys:
        c_layer = cand.layers.get(full_key)
        p_layer = partner.layers.get(full_key)
        ref = c_layer or p_layer
        assert ref is not None

        cs = cand_scale if ref.component == "unet" else cand_te_scale
        ps = partner_scale if ref.component == "unet" else partner_te_scale

        c_dare = None
        p_dare = None
        if c_layer is not None and abs(cs) > 0.0:
            cd = c_layer.compute_delta(scale=cs).detach().cpu()
            if p > 0.0:
                rnd_c = torch.rand(cd.shape, generator=gen, device="cpu", dtype=torch.float32)
                mask_c = (rnd_c < keep_prob).to(cd.dtype)
                c_dare = cd * mask_c * rescale
            else:
                c_dare = cd
        if p_layer is not None and abs(ps) > 0.0:
            pd = p_layer.compute_delta(scale=ps).detach().cpu()
            if prune_partner and p > 0.0:
                rnd_p = torch.rand(pd.shape, generator=gen, device="cpu", dtype=torch.float32)
                mask_p = (rnd_p < keep_prob).to(pd.dtype)
                p_dare = pd * mask_p * rescale
            else:
                p_dare = pd

        if c_dare is None and p_dare is None:
            continue
        if c_dare is not None and p_dare is not None:
            overlap_count += 1
            merged_d = (c_dare + p_dare) * float(lambda_scale)
        elif c_dare is not None:
            merged_d = c_dare * float(lambda_scale)
        else:
            assert p_dare is not None
            merged_d = p_dare * float(lambda_scale)

        layers[full_key] = LoRALayerFactor(
            component=ref.component,
            module_name=ref.module_name,
            dense_delta=merged_d,
            alpha_scale=1.0,
        )
        if c_dare is not None:
            cand_effective_deltas[full_key] = LoRALayerFactor(
                component=ref.component,
                module_name=ref.module_name,
                dense_delta=c_dare * float(lambda_scale),
                alpha_scale=1.0,
            )

    merged = LoRAAdapter(name=f"{cand.name}_S2_dare", layers=layers)
    cand_surv_adapter = LoRAAdapter(name=f"{cand.name}_S2_dare_surv", layers=cand_effective_deltas)
    return ComposedLoRAPlan(
        arm=cand.name,
        scenario="S2_dare",
        mode="static_delta",
        static_adapter=merged,
        effective_cand_norms=compute_adapter_norms(cand_surv_adapter),
        effective_merged_norms=compute_adapter_norms(merged),
        diagnostics={
            "operator": "dare",
            "cand_scale": cand_scale,
            "partner_scale": partner_scale,
            "drop_rate": p,
            "rescale": rescale,
            "lambda_scale": lambda_scale,
            "cand_te_scale": cand_te_scale,
            "partner_te_scale": partner_te_scale,
            "overlap_layers": overlap_count,
        },
    )


def compose_s2_ssrmerge(
    cand: LoRAAdapter,
    partner: LoRAAdapter,
    unet: Any,
    calib_latents: Any,
    calib_text_embs: Any,
    num_train_timesteps: int = 1000,
    cand_scale: float = 0.5,
    partner_scale: float = 0.8,
    cand_te_scale: float = 0.0,
    partner_te_scale: float = 0.0,
    seed: int = 42,
) -> ComposedLoRAPlan:
    """S2 (SSR-Merge, arXiv:2606.10617): Calibration second-order activation subspace routing."""
    import torch
    import torch.nn as nn

    device = next(unet.parameters()).device
    unet_dtype = next(unet.parameters()).dtype
    unet_modules = {name: m for name, m in unet.named_modules() if isinstance(m, nn.Linear)}

    all_keys = sorted(set(cand.layers) | set(partner.layers))
    shared_unet_mods: list[str] = []
    for full_key in all_keys:
        if not full_key.startswith("unet."):
            continue
        mod_name = full_key.split(".", 1)[1]
        if full_key in cand.layers and full_key in partner.layers and mod_name in unet_modules:
            shared_unet_mods.append(mod_name)

    class _CalibCovLinear(nn.Module):
        def __init__(self, base_linear: nn.Module) -> None:
            super().__init__()
            self.base_linear = base_linear
            self.cov_sum: Any | None = None
            self.token_count: int = 0

        @property
        def in_features(self) -> int:
            return int(self.base_linear.in_features)

        @property
        def out_features(self) -> int:
            return int(self.base_linear.out_features)

        @property
        def weight(self) -> Any:
            return self.base_linear.weight

        def forward(self, x: Any) -> Any:
            with torch.no_grad():
                x2 = x.detach().reshape(-1, int(x.shape[-1])).float().cpu()
                gram = x2.t() @ x2
                if self.cov_sum is None:
                    self.cov_sum = gram
                else:
                    self.cov_sum = self.cov_sum + gram
                self.token_count += int(x2.shape[0])
            return self.base_linear(x)

    captured: dict[str, _CalibCovLinear] = {}
    originals: list[tuple[Any, str, Any]] = []
    for mod_name in shared_unet_mods:
        parts = mod_name.split(".")
        parent = unet
        for part in parts[:-1]:
            parent = parent[int(part)] if part.isdigit() and hasattr(parent, "__getitem__") else getattr(parent, part)
        leaf = parts[-1]
        base_mod = parent[int(leaf)] if leaf.isdigit() and hasattr(parent, "__getitem__") else getattr(parent, leaf)
        cw = _CalibCovLinear(base_mod)
        originals.append((parent, leaf, base_mod))
        if leaf.isdigit() and hasattr(parent, "__setitem__"):
            parent[int(leaf)] = cw
        else:
            setattr(parent, leaf, cw)
        captured[f"unet.{mod_name}"] = cw

    try:
        if captured and calib_latents is not None and calib_text_embs is not None:
            gen = torch.Generator(device="cpu")
            gen.manual_seed(int(seed) + 811)
            n_lat = int(calib_latents.shape[0])
            n_emb = int(calib_text_embs.shape[0])
            n_cal = max(n_lat, n_emb)
            with torch.no_grad():
                for i in range(n_cal):
                    lat_i = calib_latents[i % n_lat : (i % n_lat) + 1].to(device).float()
                    emb_i = calib_text_embs[i % n_emb : (i % n_emb) + 1].to(device).to(unet_dtype)
                    t_i = torch.randint(0, max(1, int(num_train_timesteps)), (1,), generator=gen).to(device)
                    noise_i = torch.randn(lat_i.shape, generator=gen).to(device)
                    z_i = _q_sample_simple(lat_i, noise_i, t_i, num_train_timesteps).to(unet_dtype)
                    _ = unet(z_i, t_i, emb_i)
    finally:
        for parent, leaf, base_mod in reversed(originals):
            if leaf.isdigit() and hasattr(parent, "__setitem__"):
                parent[int(leaf)] = base_mod
            else:
                setattr(parent, leaf, base_mod)

    layers: dict[str, LoRALayerFactor] = {}
    cand_contrib_layers: dict[str, LoRALayerFactor] = {}
    wc_shared: list[float] = []
    wp_shared: list[float] = []
    wc_bn: list[float] = []
    wp_bn: list[float] = []

    for full_key in all_keys:
        c_layer = cand.layers.get(full_key)
        p_layer = partner.layers.get(full_key)
        ref = c_layer or p_layer
        assert ref is not None

        cs = cand_scale if ref.component == "unet" else cand_te_scale
        ps = partner_scale if ref.component == "unet" else partner_te_scale
        dc = c_layer.compute_delta(scale=cs).detach().cpu() if (c_layer is not None and abs(cs) > 0.0) else None
        ds = p_layer.compute_delta(scale=ps).detach().cpu() if (p_layer is not None and abs(ps) > 0.0) else None

        if dc is None and ds is None:
            continue
        if dc is not None and ds is not None:
            cw = captured.get(full_key)
            if cw is not None and cw.cov_sum is not None and cw.token_count > 0:
                cov = cw.cov_sum / float(cw.token_count)
                ec = max(0.0, float(((dc @ cov) * dc).sum().item()))
                ep = max(0.0, float(((ds @ cov) * ds).sum().item()))
                ac = math.sqrt(ec)
                ap = math.sqrt(ep)
                denom = ac + ap
                if denom > 1e-12:
                    wc = ac / denom
                    wp = ap / denom
                else:
                    wc, wp = 0.5, 0.5
            else:
                wc, wp = 0.5, 0.5

            wc_shared.append(wc)
            wp_shared.append(wp)
            if ".down_blocks.2." in full_key or ".mid_block." in full_key or ".up_blocks.1." in full_key:
                if ".attn2." in full_key:
                    wc_bn.append(wc)
                    wp_bn.append(wp)

            dm = dc * wc + ds * wp
            c_eff = dc * wc
        elif dc is not None:
            dm = dc
            c_eff = dc
        else:
            assert ds is not None
            dm = ds
            c_eff = None

        layers[full_key] = LoRALayerFactor(
            component=ref.component,
            module_name=ref.module_name,
            dense_delta=dm,
            alpha_scale=1.0,
        )
        if c_eff is not None:
            cand_contrib_layers[full_key] = LoRALayerFactor(
                component=ref.component,
                module_name=ref.module_name,
                dense_delta=c_eff,
                alpha_scale=1.0,
            )

    merged = LoRAAdapter(name=f"{cand.name}_S2_ssrmerge", layers=layers)
    cand_eff_adapter = LoRAAdapter(name=f"{cand.name}_S2_ssrmerge_cand", layers=cand_contrib_layers)
    return ComposedLoRAPlan(
        arm=cand.name,
        scenario="S2_ssrmerge",
        mode="static_delta",
        static_adapter=merged,
        effective_cand_norms=compute_adapter_norms(cand_eff_adapter),
        effective_merged_norms=compute_adapter_norms(merged),
        diagnostics={
            "operator": "ssr_merge",
            "cand_scale": cand_scale,
            "partner_scale": partner_scale,
            "cand_te_scale": cand_te_scale,
            "partner_te_scale": partner_te_scale,
            "shared_layers": len(wc_shared),
            "mean_wc_shared": (sum(wc_shared) / len(wc_shared)) if wc_shared else 0.5,
            "mean_wp_shared": (sum(wp_shared) / len(wp_shared)) if wp_shared else 0.5,
            "mean_wc_bottleneck": (sum(wc_bn) / len(wc_bn)) if wc_bn else 0.5,
            "mean_wp_bottleneck": (sum(wp_bn) / len(wp_bn)) if wp_bn else 0.5,
        },
    )


def optimize_s3_ziplora(
    cand: LoRAAdapter,
    partner: LoRAAdapter,
    unet: Any,
    subject_latents: Any,
    subject_text_emb: Any,
    style_latents: Any,
    style_text_emb: Any,
    num_train_timesteps: int = 1000,
    steps: int = 100,
    lr: float = 0.01,
    lambda_cos: float = 0.01,
    cand_init_scale: float = 1.0,
    partner_init_scale: float = 0.8,
    partner_te_scale: float = 0.0,
    seed: int = 42,
    out_adapter_path: str | Path | None = None,
) -> ComposedLoRAPlan:
    """S3 (ZipLoRA, arXiv:2311.13600): Frozen-TE column-wise merging optimization on UNet."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    device = next(unet.parameters()).device
    unet_dtype = next(unet.parameters()).dtype
    unet_modules = {name: m for name, m in unet.named_modules() if isinstance(m, nn.Linear)}

    all_unet_keys = sorted(set(cand.unet_layers()) | set(partner.unet_layers()))
    active_specs: list[dict[str, Any]] = []
    fixed_partner_only: dict[str, Any] = {}

    for full_key in all_unet_keys:
        mod_name = full_key.split(".", 1)[1]
        if mod_name not in unet_modules:
            continue
        c_layer = cand.layers.get(full_key)
        p_layer = partner.layers.get(full_key)
        dc = c_layer.compute_delta(scale=cand_init_scale).detach().to(device).float() if c_layer is not None else None
        ds = p_layer.compute_delta(scale=partner_init_scale).detach().to(device).float() if p_layer is not None else None

        if dc is not None and ds is not None:
            d_in = int(dc.shape[1])
            mc = nn.Parameter(torch.ones((d_in,), device=device, dtype=torch.float32))
            ms = nn.Parameter(torch.ones((d_in,), device=device, dtype=torch.float32))
            cos_vec = _column_abs_cos_vec(dc, ds).detach()
            active_specs.append(
                {
                    "full_key": full_key,
                    "mod_name": mod_name,
                    "dc": dc,
                    "ds": ds,
                    "mc": mc,
                    "ms": ms,
                    "cos_vec": cos_vec,
                }
            )
        elif ds is not None:
            fixed_partner_only[full_key] = ds
        elif dc is not None:
            fixed_partner_only[full_key] = dc

    class _ZipLinear(nn.Module):
        def __init__(self, base_linear: nn.Module) -> None:
            super().__init__()
            self.base_linear = base_linear
            self.override_delta: Any | None = None

        @property
        def in_features(self) -> int:
            return int(self.base_linear.in_features)

        @property
        def out_features(self) -> int:
            return int(self.base_linear.out_features)

        @property
        def weight(self) -> Any:
            return self.base_linear.weight

        def forward(self, x: Any) -> Any:
            out = self.base_linear(x)
            if self.override_delta is not None:
                out = out + F.linear(x.float(), self.override_delta.to(x.device).float()).to(out.dtype)
            return out

    # Wrap affected UNet linear layers temporarily
    installed_zip: dict[str, _ZipLinear] = {}
    originals: list[tuple[Any, str, Any]] = []
    for key in [s["mod_name"] for s in active_specs] + [k.split(".", 1)[1] for k in fixed_partner_only]:
        parts = key.split(".")
        parent = unet
        for part in parts[:-1]:
            parent = parent[int(part)] if part.isdigit() and hasattr(parent, "__getitem__") else getattr(parent, part)
        leaf = parts[-1]
        base_mod = parent[int(leaf)] if leaf.isdigit() and hasattr(parent, "__getitem__") else getattr(parent, leaf)
        zw = _ZipLinear(base_mod)
        originals.append((parent, leaf, base_mod))
        if leaf.isdigit() and hasattr(parent, "__setitem__"):
            parent[int(leaf)] = zw
        else:
            setattr(parent, leaf, zw)
        installed_zip[f"unet.{key}"] = zw

    gen = torch.Generator(device="cpu")
    gen.manual_seed(int(seed))

    try:
        # Step A: Compute frozen teacher noise targets for subject (base + cand) and style (base + partner)
        with torch.no_grad():
            for s in active_specs:
                installed_zip[s["full_key"]].override_delta = s["dc"]
            for k, d in fixed_partner_only.items():
                installed_zip[k].override_delta = d if k in cand.layers else None

            t_subj = torch.randint(
                0, num_train_timesteps, (subject_latents.shape[0],), generator=gen
            ).to(device)
            noise_subj = torch.randn(subject_latents.shape, generator=gen).to(device)
            z_subj = _q_sample_simple(subject_latents.to(device).float(), noise_subj, t_subj, num_train_timesteps).to(unet_dtype)
            subj_emb_dev = subject_text_emb.to(device).to(unet_dtype)
            target_subj = unet(z_subj, t_subj, subj_emb_dev).sample.detach()

            for s in active_specs:
                installed_zip[s["full_key"]].override_delta = s["ds"]
            for k, d in fixed_partner_only.items():
                installed_zip[k].override_delta = d if k in partner.layers else None

            t_sty = torch.randint(
                0, num_train_timesteps, (style_latents.shape[0],), generator=gen
            ).to(device)
            noise_sty = torch.randn(style_latents.shape, generator=gen).to(device)
            z_sty = _q_sample_simple(style_latents.to(device).float(), noise_sty, t_sty, num_train_timesteps).to(unet_dtype)
            sty_emb_dev = style_text_emb.to(device).to(unet_dtype)
            target_sty = unet(z_sty, t_sty, sty_emb_dev).sample.detach()

        # Re-fix disjoint single-owner layers during ZipLoRA optimization
        for k, d in fixed_partner_only.items():
            installed_zip[k].override_delta = d

        # Step B: Optimize column-wise vectors (m_c, m_s), TE strictly frozen
        params: list[Any] = []
        for s in active_specs:
            params.extend([s["mc"], s["ms"]])

        init_cos_pen = 0.0
        final_cos_pen = 0.0
        final_loss = 0.0
        if params:
            opt = torch.optim.AdamW(params, lr=float(lr), weight_decay=0.0)
            for step in range(max(1, int(steps))):
                opt.zero_grad()
                # Accumulate subject and style losses sequentially so only one UNet autograd graph resides in VRAM at a time.
                for s in active_specs:
                    installed_zip[s["full_key"]].override_delta = s["dc"] * s["mc"].reshape(1, -1) + s["ds"] * s["ms"].reshape(1, -1)
                pred_subj = unet(z_subj, t_subj, subj_emb_dev).sample
                l_subj = F.mse_loss(pred_subj.float(), target_subj.float())
                l_subj_val = float(l_subj.detach().item())
                l_subj.backward()
                del pred_subj, l_subj

                cos_terms: list[Any] = []
                for s in active_specs:
                    installed_zip[s["full_key"]].override_delta = s["dc"] * s["mc"].reshape(1, -1) + s["ds"] * s["ms"].reshape(1, -1)
                    cos_terms.append((s["mc"].abs() * s["ms"].abs() * s["cos_vec"]).mean())

                cos_loss = sum(cos_terms) / len(cos_terms)
                cos_val = float(cos_loss.detach().item())
                if step == 0:
                    init_cos_pen = cos_val

                pred_sty = unet(z_sty, t_sty, sty_emb_dev).sample
                l_sty = F.mse_loss(pred_sty.float(), target_sty.float())
                sty_plus_cos = l_sty + float(lambda_cos) * cos_loss
                sty_plus_cos_val = float(sty_plus_cos.detach().item())
                sty_plus_cos.backward()
                del pred_sty, l_sty, cos_loss, sty_plus_cos
                opt.step()

                with torch.no_grad():
                    for s in active_specs:
                        s["mc"].clamp_(0.0, 2.0)
                        s["ms"].clamp_(0.0, 2.0)
                final_cos_pen = cos_val
                final_loss = l_subj_val + sty_plus_cos_val

        merged_layers: dict[str, LoRALayerFactor] = {}
        cand_contrib_layers: dict[str, LoRALayerFactor] = {}
        mc_means: list[float] = []
        ms_means: list[float] = []

        for s in active_specs:
            mc_d = s["mc"].detach().cpu()
            ms_d = s["ms"].detach().cpu()
            dc_cpu = s["dc"].detach().cpu()
            ds_cpu = s["ds"].detach().cpu()
            comp, mod = s["full_key"].split(".", 1)
            mc_means.append(float(mc_d.mean().item()))
            ms_means.append(float(ms_d.mean().item()))
            dm = dc_cpu * mc_d.reshape(1, -1) + ds_cpu * ms_d.reshape(1, -1)
            merged_layers[s["full_key"]] = LoRALayerFactor(
                component=comp, module_name=mod, dense_delta=dm, alpha_scale=1.0
            )
            cand_contrib_layers[s["full_key"]] = LoRALayerFactor(
                component=comp,
                module_name=mod,
                dense_delta=dc_cpu * mc_d.reshape(1, -1),
                alpha_scale=1.0,
            )

        for k, d in fixed_partner_only.items():
            comp, mod = k.split(".", 1)
            merged_layers[k] = LoRALayerFactor(
                component=comp, module_name=mod, dense_delta=d.detach().cpu(), alpha_scale=1.0
            )
            if k in cand.layers:
                cand_contrib_layers[k] = LoRALayerFactor(
                    component=comp, module_name=mod, dense_delta=d.detach().cpu(), alpha_scale=1.0
                )

        if abs(float(partner_te_scale)) > 0.0:
            for k, p_layer in partner.te_layers().items():
                merged_layers[k] = LoRALayerFactor(
                    component=p_layer.component,
                    module_name=p_layer.module_name,
                    dense_delta=p_layer.compute_delta(scale=float(partner_te_scale)).detach().cpu(),
                    alpha_scale=1.0,
                )

        merged_adapter = LoRAAdapter(name=f"{cand.name}_S3_ziplora", layers=merged_layers)
        if out_adapter_path is not None:
            save_lora_adapter(merged_adapter, out_adapter_path, rank_svd_fallback=16)

        return ComposedLoRAPlan(
            arm=cand.name,
            scenario="S3_ziplora",
            mode="static_delta",
            static_adapter=merged_adapter,
            effective_cand_norms=compute_adapter_norms(LoRAAdapter(name=f"{cand.name}_S3_cand", layers=cand_contrib_layers)),
            effective_merged_norms=compute_adapter_norms(merged_adapter),
            diagnostics={
                "operator": "ziplora_frozen_te",
                "steps": int(steps),
                "lr": float(lr),
                "lambda_cos": float(lambda_cos),
                "init_cos_penalty": init_cos_pen,
                "final_cos_penalty": final_cos_pen,
                "final_loss": final_loss,
                "mean_mc": (sum(mc_means) / len(mc_means)) if mc_means else 1.0,
                "mean_ms": (sum(ms_means) / len(ms_means)) if ms_means else 1.0,
                "shared_layers_optimized": len(active_specs),
            },
        )
    finally:
        for parent, leaf, base_mod in reversed(originals):
            if leaf.isdigit() and hasattr(parent, "__setitem__"):
                parent[int(leaf)] = base_mod
            else:
                setattr(parent, leaf, base_mod)


def _q_sample_simple(latents: Any, noise: Any, t: Any, num_train_timesteps: int) -> Any:
    """Deterministic linear/cosine alpha-bar noise mixing fallback for lightweight latent perturbation."""
    import torch

    frac = (t.float() / max(1, int(num_train_timesteps) - 1)).reshape(-1, 1, 1, 1)
    alpha_bar = (1.0 - 0.99 * frac).clamp(0.01, 0.999)
    return torch.sqrt(alpha_bar) * latents + torch.sqrt(1.0 - alpha_bar) * noise


class AppliedAdapterContext:
    """Context manager applying either a static_adapter or dynamic K-LoRA plan to UNet (+ optional TE)."""

    def __init__(self, plan: ComposedLoRAPlan, unet: Any, text_encoder: Any | None = None) -> None:
        self.plan = plan
        self.unet = unet
        self.text_encoder = text_encoder
        self._restorations: list[tuple[Any, str, Any]] = []
        self._klora_wrappers: list[Any] = []
        self._step_state = {"step_idx": 0, "num_steps": 25}

    def set_step(self, step_idx: int, num_steps: int) -> None:
        self._step_state["step_idx"] = int(step_idx)
        self._step_state["num_steps"] = max(1, int(num_steps))

    def __enter__(self) -> "AppliedAdapterContext":
        import torch.nn as nn
        import torch.nn.functional as F

        step_state = self._step_state
        plan = self.plan

        class _StaticDeltaLinear(nn.Module):
            def __init__(self, base_mod: nn.Module, delta: Any) -> None:
                super().__init__()
                self.base_mod = base_mod
                self.delta = delta

            @property
            def in_features(self) -> int:
                return int(self.base_mod.in_features)

            @property
            def out_features(self) -> int:
                return int(self.base_mod.out_features)

            @property
            def weight(self) -> Any:
                return self.base_mod.weight

            def forward(self, x: Any) -> Any:
                out = self.base_mod(x)
                return out + F.linear(x.float(), self.delta.to(x.device).float()).to(out.dtype)

        class _KLoraDynamicLinear(nn.Module):
            def __init__(self, base_mod: nn.Module, info: dict[str, Any]) -> None:
                super().__init__()
                self.base_mod = base_mod
                self.info = info

            @property
            def in_features(self) -> int:
                return int(self.base_mod.in_features)

            @property
            def out_features(self) -> int:
                return int(self.base_mod.out_features)

            @property
            def weight(self) -> Any:
                return self.base_mod.weight

            def forward(self, x: Any) -> Any:
                out = self.base_mod(x)
                use_c = select_klora_choice(
                    self.info,
                    step_idx=step_state["step_idx"],
                    num_steps=step_state["num_steps"],
                    gamma=plan.klora_gamma,
                    alpha=plan.klora_alpha,
                    beta=plan.klora_beta,
                )
                d = self.info["delta_c"] if use_c else self.info["delta_s"]
                if d is not None:
                    out = out + F.linear(x.float(), d.to(x.device).float()).to(out.dtype)
                return out

        def _patch_model(model: Any, comp: str) -> None:
            if model is None:
                return
            if plan.static_adapter is not None and (plan.mode == "static_delta" or comp == "text_encoder"):
                source_layers = (
                    plan.static_adapter.unet_layers() if comp == "unet" else plan.static_adapter.te_layers()
                )
                for full_key, factor in source_layers.items():
                    mod_name = factor.module_name
                    delta = factor.compute_delta().detach()
                    if float((delta * delta).sum().item()) <= 0.0:
                        continue
                    self._swap_submodule(model, mod_name, lambda base, _d=delta: _StaticDeltaLinear(base, _d))
            if plan.mode == "klora_dynamic" and comp == "unet":
                for full_key, info in plan.klora_layers.items():
                    _, mod_name = full_key.split(".", 1)
                    if info["delta_c"] is None and info["delta_s"] is None:
                        continue
                    w = self._swap_submodule(model, mod_name, lambda base, _i=info: _KLoraDynamicLinear(base, _i))
                    if w is not None:
                        self._klora_wrappers.append(w)

        _patch_model(self.unet, "unet")
        _patch_model(self.text_encoder, "text_encoder")
        return self

    def _swap_submodule(self, root: Any, mod_name: str, factory: Any) -> Any:
        parts = mod_name.split(".")
        parent = root
        for part in parts[:-1]:
            if part.isdigit() and hasattr(parent, "__getitem__"):
                parent = parent[int(part)]
            elif hasattr(parent, part):
                parent = getattr(parent, part)
            else:
                return None
        leaf = parts[-1]
        if leaf.isdigit() and hasattr(parent, "__getitem__"):
            base_mod = parent[int(leaf)]
            wrapped = factory(base_mod)
            parent[int(leaf)] = wrapped
        elif hasattr(parent, leaf):
            base_mod = getattr(parent, leaf)
            wrapped = factory(base_mod)
            setattr(parent, leaf, wrapped)
        else:
            return None
        self._restorations.append((parent, leaf, base_mod))
        return wrapped

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        for parent, leaf, base_mod in reversed(self._restorations):
            if leaf.isdigit() and hasattr(parent, "__setitem__"):
                parent[int(leaf)] = base_mod
            else:
                setattr(parent, leaf, base_mod)
        self._restorations.clear()
        self._klora_wrappers.clear()
