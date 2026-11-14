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


def extract_svd_lora_from_model_diff(
    base_model_dir: str | Path,
    finetuned_model_dir: str | Path,
    rank: int = 16,
    out_path: str | Path | None = None,
) -> tuple[LoRAAdapter, dict[str, Any]]:
    """Construct offline rank-r LoRA P_test via truncated SVD of (finetuned_unet - base_unet)."""
    import torch

    base_sd = _load_unet_weight_dict(base_model_dir)
    ft_sd = _load_unet_weight_dict(finetuned_model_dir)

    layers: dict[str, LoRALayerFactor] = {}
    total_diff_sq = 0.0
    recon_sq = 0.0
    skipped = 0

    for key in sorted(base_sd.keys()):
        if not key.endswith(".weight"):
            continue
        mod_name = key[: -len(".weight")]
        if not ((".attn1." in mod_name or ".attn2." in mod_name) and is_attention_linear(mod_name)):
            continue
        if key not in ft_sd:
            skipped += 1
            continue
        w0 = base_sd[key].float()
        w1 = ft_sd[key].float()
        if w0.shape != w1.shape or w0.ndim != 2:
            skipped += 1
            continue

        dw = w1 - w0
        diff_sq = float((dw * dw).sum().item())
        total_diff_sq += diff_sq
        if diff_sq <= 1e-16:
            continue

        u, s, vh = torch.linalg.svd(dw, full_matrices=False)
        r = max(1, min(int(rank), int(s.shape[0])))
        sq = torch.sqrt(s[:r].clamp(min=0.0))
        b = (u[:, :r] * sq.reshape(1, r)).contiguous()
        a = (sq.reshape(r, 1) * vh[:r, :]).contiguous()
        recon_sq += float((s[:r] * s[:r]).sum().item())

        layers[f"unet.{mod_name}"] = LoRALayerFactor(
            component="unet",
            module_name=mod_name,
            lora_A=a,
            lora_B=b,
            alpha_scale=1.0,
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
) -> ComposedLoRAPlan:
    """S1: TE zeroed (te_scale=0.0) + UNet attenuated (0.5) composed with P_test (0.8)."""
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
            ps = partner_scale if p_layer.component == "unet" else cand_te_scale
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
        },
    )


def compose_s2_ties(
    cand: LoRAAdapter,
    partner: LoRAAdapter,
    cand_scale: float = 0.5,
    partner_scale: float = 0.8,
    density: float = 0.5,
    lambda_scale: float = 1.0,
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

        if c_layer is not None:
            cd = c_layer.compute_delta(scale=cand_scale).detach().cpu()
            c_trimmed = trim_topk_tensor(cd, density=density)
            deltas.append(c_trimmed)
        if p_layer is not None:
            pd = p_layer.compute_delta(scale=partner_scale).detach().cpu()
            p_trimmed = trim_topk_tensor(pd, density=density)
            deltas.append(p_trimmed)

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
) -> ComposedLoRAPlan:
    """S2 (K-LoRA, arXiv:2502.18461): Dynamic per-layer per-timestep Top-K winner selection."""
    import torch

    all_keys = sorted(set(cand.layers) | set(partner.layers))
    klora_layers: dict[str, dict[str, Any]] = {}
    c_mean_mags: list[float] = []
    s_mean_mags: list[float] = []
    cand_wins_t0 = 0
    shared_unet = 0

    for full_key in all_keys:
        c_layer = cand.layers.get(full_key)
        p_layer = partner.layers.get(full_key)
        ref = c_layer or p_layer
        assert ref is not None
        if ref.component != "unet":
            # K-LoRA operates across UNet attention layers; keep TE zeroed in composition
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

    # Expected step-0 selection statistics for auditing
    cand_selected_layers: dict[str, LoRALayerFactor] = {}
    for full_key, info in klora_layers.items():
        pick_c = select_klora_choice(info, step_idx=0, num_steps=25, gamma=gamma, alpha=alpha, beta=beta)
        if pick_c and info["delta_c"] is not None:
            cand_wins_t0 += 1
            comp, mod = full_key.split(".", 1)
            cand_selected_layers[full_key] = LoRALayerFactor(
                component=comp,
                module_name=mod,
                dense_delta=info["delta_c"],
            )

    cand_norms = compute_adapter_norms(cand, te_scale=0.0, unet_scale=cand_scale)
    cand_win_t0_norms = compute_adapter_norms(LoRAAdapter(name=f"{cand.name}_klora_t0", layers=cand_selected_layers))
    return ComposedLoRAPlan(
        arm=cand.name,
        scenario="S2_klora",
        mode="klora_dynamic",
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
            "shared_unet_layers": shared_unet,
            "cand_wins_at_step0": cand_wins_t0,
            "total_unet_layers": len(klora_layers),
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
                cos_terms: list[Any] = []
                for s in active_specs:
                    delta_m = s["dc"] * s["mc"].reshape(1, -1) + s["ds"] * s["ms"].reshape(1, -1)
                    installed_zip[s["full_key"]].override_delta = delta_m
                    cos_terms.append((s["mc"].abs() * s["ms"].abs() * s["cos_vec"]).mean())

                cos_loss = sum(cos_terms) / len(cos_terms)
                if step == 0:
                    init_cos_pen = float(cos_loss.detach().item())

                pred_subj = unet(z_subj, t_subj, subj_emb_dev).sample
                pred_sty = unet(z_sty, t_sty, sty_emb_dev).sample
                l_subj = F.mse_loss(pred_subj.float(), target_subj.float())
                l_sty = F.mse_loss(pred_sty.float(), target_sty.float())
                total_loss = l_subj + l_sty + float(lambda_cos) * cos_loss
                total_loss.backward()
                opt.step()

                with torch.no_grad():
                    for s in active_specs:
                        s["mc"].clamp_(0.0, 2.0)
                        s["ms"].clamp_(0.0, 2.0)
                final_cos_pen = float(cos_loss.detach().item())
                final_loss = float(total_loss.detach().item())

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
            if plan.mode == "static_delta" and plan.static_adapter is not None:
                source_layers = (
                    plan.static_adapter.unet_layers() if comp == "unet" else plan.static_adapter.te_layers()
                )
                for full_key, factor in source_layers.items():
                    mod_name = factor.module_name
                    delta = factor.compute_delta().detach()
                    if float((delta * delta).sum().item()) <= 0.0:
                        continue
                    self._swap_submodule(model, mod_name, lambda base, _d=delta: _StaticDeltaLinear(base, _d))
            elif plan.mode == "klora_dynamic" and comp == "unet":
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
