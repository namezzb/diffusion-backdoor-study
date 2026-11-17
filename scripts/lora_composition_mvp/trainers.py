"""Resumable offline trainers and baseline verifiers for MVP-v1 (Pure Paper 1 + PoisonLoRA)."""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any

from .config import MVPConfig
from .io_utils import (
    ComputeTimer,
    LoRAAdapter,
    LoRALayerFactor,
    assert_ours_parameter_isolation,
    assert_trainable_parameter_isolation,
    check_permission,
    compute_adapter_norms,
    digest,
    enforce_offline_env,
    event,
    is_ours_bottleneck_target,
    load_lora_adapter,
    md_read,
    md_write,
    save_lora_adapter,
    verify_export_roundtrip,
)
from .core_lora import (
    build_distill_prompt_banks,
    compute_core_lora_budgets,
    compute_covariance_factors,
    compute_hoyer_and_orth_penalties,
    extract_semantic_paired_matrices,
    initialize_qo_micro_anchors,
    make_differentiable_ties_transform,
    pair_prompt_tokens,
    solve_whitened_svd_layer,
    split_bottleneck_kv_qo,
)
from .operators import _q_sample_simple, simulate_full_delta_operator, trim_topk_tensor
from .subspace import (
    export_wrappers_to_adapter,
    find_target_linear_modules,
    install_lora_wrappers,
)


def _list_images(folder: str | Path) -> list[Path]:
    p = Path(folder)
    if not p.is_dir():
        raise FileNotFoundError(f"Training image folder not found: {p}")
    exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    files = sorted(x for x in p.iterdir() if x.is_file() and x.suffix.lower() in exts)
    if not files:
        raise RuntimeError(f"No training images found in: {p}")
    return files


def encode_image_latents(vae: Any, image_dir: str | Path, resolution: int, device: Any) -> Any:
    """Load local image folder and encode into VAE latent tensor bank (N, 4, H/8, W/8)."""
    import numpy as np
    import torch
    from PIL import Image

    paths = _list_images(image_dir)
    tensors = []
    resampling = getattr(getattr(Image, "Resampling", Image), "BICUBIC", Image.BICUBIC)
    for img_path in paths:
        with Image.open(img_path) as im:
            rgb = im.convert("RGB").resize((resolution, resolution), resample=resampling)
            arr = np.asarray(rgb, dtype=np.float32) / 127.5 - 1.0
        t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
        tensors.append(t)

    batch = torch.cat(tensors, dim=0).to(device)
    vae_dtype = next(vae.parameters()).dtype
    with torch.no_grad():
        latents = []
        for i in range(batch.shape[0]):
            enc = vae.encode(batch[i : i + 1].to(vae_dtype)).latent_dist.mean
            latents.append((enc.float() * 0.18215).cpu())
    return torch.cat(latents, dim=0)


def load_sd15_components(model_dir: str | Path, device: str = "cpu", dtype_str: str = "float32") -> dict[str, Any]:
    """Load frozen offline SD1.5 UNet, VAE, CLIPTextModel, Tokenizer, and DDPMScheduler."""
    import torch
    from diffusers import AutoencoderKL, DDPMScheduler, UNet2DConditionModel
    from transformers import CLIPTextModel, CLIPTokenizer

    enforce_offline_env()
    dtype = torch.float16 if (dtype_str == "float16" and str(device).startswith("cuda")) else torch.float32
    p = str(model_dir)
    tokenizer = CLIPTokenizer.from_pretrained(p, subfolder="tokenizer", local_files_only=True)
    text_encoder = CLIPTextModel.from_pretrained(
        p, subfolder="text_encoder", torch_dtype=dtype, local_files_only=True
    ).to(device)
    vae = AutoencoderKL.from_pretrained(
        p, subfolder="vae", torch_dtype=dtype, local_files_only=True
    ).to(device)
    unet = UNet2DConditionModel.from_pretrained(
        p, subfolder="unet", torch_dtype=dtype, local_files_only=True
    ).to(device)
    scheduler = DDPMScheduler.from_pretrained(p, subfolder="scheduler", local_files_only=True)

    for mod in (text_encoder, vae, unet):
        mod.eval()
        for param in mod.parameters():
            param.requires_grad_(False)

    return {
        "tokenizer": tokenizer,
        "text_encoder": text_encoder,
        "vae": vae,
        "unet": unet,
        "scheduler": scheduler,
        "dtype": dtype,
    }


def _encode_prompt(
    tokenizer: Any,
    text_encoder: Any,
    prompt: str,
    device: Any,
    enable_grad: bool = False,
) -> Any:
    enc = tokenizer(
        [prompt],
        padding="max_length",
        max_length=getattr(tokenizer, "model_max_length", 77),
        truncation=True,
        return_tensors="pt",
    )
    input_ids = enc["input_ids"].to(device)
    if enable_grad:
        out = text_encoder(input_ids=input_ids)
        return out[0] if isinstance(out, (tuple, list)) else getattr(out, "last_hidden_state", out)
    with _no_grad_ctx():
        out = text_encoder(input_ids=input_ids)
        return out[0] if isinstance(out, (tuple, list)) else getattr(out, "last_hidden_state", out)


def _no_grad_ctx() -> Any:
    import torch

    return torch.no_grad()


def verify_reused_adapter(
    name: str,
    adapter_path: str | Path,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Load and audit a pre-trained baseline adapter (benign / masqlora)."""
    p = Path(adapter_path)
    adapter = load_lora_adapter(p, name=name)
    actual_sha = adapter.metadata.get("sha256", digest(p))
    if expected_sha256 and actual_sha != expected_sha256:
        raise AssertionError(
            f"SHA256 mismatch for reused adapter {name}: got {actual_sha}, expected {expected_sha256}"
        )
    norms = compute_adapter_norms(adapter)
    return {
        "name": name,
        "path": str(p),
        "sha256": actual_sha,
        "layer_count": norms["layer_count"],
        "total_frobenius": norms["total_frobenius"],
        "unet_frobenius": norms["unet_frobenius"],
        "buckets": norms["buckets"],
    }


def _calibrated_p_train_layer_norm(cfg: MVPConfig) -> float:
    """Calibrate per-layer norm so ||0.8 * P_train^(m)||_F matches real style LoRA (~18.0-21.0 across 128 layers)."""
    # Default p_train_proxy_scale=0.75 -> 2.10 raw per layer -> 0.8 * 2.10 = 1.68/layer -> sqrt(128)*1.68 = 19.01
    return float(cfg.p_train_proxy_scale) * 2.8


def _build_single_p_train_proxy(
    cfg: MVPConfig,
    attn_modules: dict[str, Any],
    tokenizer: Any,
    text_encoder: Any,
    style_suffix: str,
    proxy_index: int,
    out_path: Path,
    device: Any = "cpu",
) -> LoRAAdapter:
    import torch

    gen = torch.Generator(device="cpu")
    gen.manual_seed(int(cfg.seed) + 1009 + int(proxy_index) * 131)

    base_text = cfg.clean_prompt
    style_text = f"{base_text}, {style_suffix}"
    emb_style = _encode_prompt(tokenizer, text_encoder, style_text, device=device).float().cpu()
    emb_base = _encode_prompt(tokenizer, text_encoder, base_text, device=device).float().cpu()
    style_dir = (emb_style - emb_base).mean(dim=1)  # (1, d_text)
    style_dir = style_dir / (float(torch.sqrt((style_dir * style_dir).sum()).item()) + 1e-8)

    r = max(2, min(int(cfg.p_train_proxy_rank), 16))
    target_norm_per_layer = _calibrated_p_train_layer_norm(cfg)
    layers: dict[str, LoRALayerFactor] = {}
    for mod_name, mod in sorted(attn_modules.items()):
        w0 = mod.weight.detach().float().cpu()
        d_out, d_in = int(w0.shape[0]), int(w0.shape[1])
        rr = min(r, d_out, d_in)
        a = torch.randn((rr, d_in), generator=gen, dtype=torch.float32) * (1.0 / math.sqrt(d_in))
        if (mod_name.endswith(".to_k") or mod_name.endswith(".to_v")) and d_in == int(style_dir.shape[1]):
            row0 = 0.5 * a[0:1, :] + 0.5 * style_dir
            a = torch.cat([row0, a[1:, :]], dim=0) if rr > 1 else row0
        b = torch.randn((d_out, rr), generator=gen, dtype=torch.float32) * (1.0 / math.sqrt(d_out))
        raw = LoRALayerFactor(component="unet", module_name=mod_name, lora_A=a, lora_B=b, alpha_scale=1.0)
        cur_n = raw.frobenius_norm()
        if cur_n > 1e-12:
            raw.lora_B = raw.lora_B * (target_norm_per_layer / cur_n)
        layers[f"unet.{mod_name}"] = raw

    proxy = LoRAAdapter(
        name=f"p_train_proxy_m{proxy_index}",
        layers=layers,
        metadata={"style": style_suffix, "proxy_index": proxy_index, "seed": int(cfg.seed) + 1009 + int(proxy_index) * 131},
    )
    save_lora_adapter(proxy, out_path, rank_svd_fallback=r)
    return load_lora_adapter(out_path, name=f"p_train_proxy_m{proxy_index}")


def build_or_load_p_train_pool(
    cfg: MVPConfig,
    unet: Any,
    tokenizer: Any,
    text_encoder: Any,
    out_path: str | Path,
    device: Any = "cpu",
) -> list[LoRAAdapter]:
    """Create or reload M synthetic dev-partner LoRA proxies {P_train^(m)} strictly isolated from P_test."""
    import json

    if cfg.p_train_lora_path:
        return [load_lora_adapter(cfg.p_train_lora_path, name="p_train_external")]

    p = Path(out_path)
    base_dir = p.parent if p.suffix else p
    base_dir.mkdir(parents=True, exist_ok=True)
    meta_path = base_dir / "pool_meta.json"
    styles = list(cfg.p_train_styles)
    expected_norm = _calibrated_p_train_layer_norm(cfg)

    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            paths = [Path(x) for x in meta.get("paths", [])]
            if (
                meta.get("calibrated_version") == "v3_pool"
                and int(meta.get("seed", -1)) == int(cfg.seed)
                and list(meta.get("styles", [])) == styles
                and abs(float(meta.get("target_norm_per_layer", -1.0)) - expected_norm) < 1e-5
                and len(paths) == len(styles)
                and all(fp.is_file() for fp in paths)
            ):
                return [load_lora_adapter(fp, name=f"p_train_proxy_m{m}") for m, fp in enumerate(paths)]
        except Exception:
            pass

    attn_modules = find_target_linear_modules(unet, bottleneck_only=False)
    pool: list[LoRAAdapter] = []
    saved_paths: list[str] = []
    for m, style_sfx in enumerate(styles):
        m_path = base_dir / f"adapter_m{m}.safetensors"
        adapter_m = _build_single_p_train_proxy(
            cfg=cfg,
            attn_modules=attn_modules,
            tokenizer=tokenizer,
            text_encoder=text_encoder,
            style_suffix=style_sfx,
            proxy_index=m,
            out_path=m_path,
            device=device,
        )
        pool.append(adapter_m)
        saved_paths.append(str(m_path))

    if pool and p.suffix == ".safetensors":
        save_lora_adapter(pool[0], p, rank_svd_fallback=max(2, min(int(cfg.p_train_proxy_rank), 16)))

    meta_path.write_text(
        json.dumps(
            {
                "calibrated_version": "v3_pool",
                "seed": int(cfg.seed),
                "styles": styles,
                "target_norm_per_layer": expected_norm,
                "paths": saved_paths,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return pool


def build_or_load_p_train_proxy(
    cfg: MVPConfig,
    unet: Any,
    tokenizer: Any,
    text_encoder: Any,
    out_path: str | Path,
    device: Any = "cpu",
) -> LoRAAdapter:
    """Create or reload frozen dev-partner LoRA (P_train[0], while populating full M=4 pool) isolated from P_test."""
    pool = build_or_load_p_train_pool(
        cfg=cfg,
        unet=unet,
        tokenizer=tokenizer,
        text_encoder=text_encoder,
        out_path=out_path,
        device=device,
    )
    return pool[0]


def _sample_noise_with_offset(shape: tuple[int, ...], noise_offset: float, generator: Any, device: Any) -> Any:
    import torch

    noise = torch.randn(shape, generator=generator, device="cpu", dtype=torch.float32).to(device)
    if noise_offset > 0.0 and len(shape) == 4:
        noise = noise + float(noise_offset) * torch.randn(
            (shape[0], shape[1], 1, 1), generator=generator, device="cpu", dtype=torch.float32
        ).to(device)
    return noise


def _resolve_fair_norm_budget(cfg: MVPConfig, run_path: Path, arm: str) -> float | None:
    """Resolve export Frobenius norm budget; defaults to cfg.target_frobenius_norm or matched baseline."""
    if cfg.target_frobenius_norm is not None:
        val = float(cfg.target_frobenius_norm)
        return val if val > 0.0 else None
    if arm not in {"poisonlora", "poisonlora_plus", "masqlora_unet"}:
        return None
    ours_path = run_path / "arms" / "ours_mvp" / "adapter.safetensors"
    if ours_path.is_file():
        ours_norms = compute_adapter_norms(load_lora_adapter(ours_path, name="ours_mvp"))
        if ours_norms["total_frobenius"] > 0.0:
            return float(ours_norms["total_frobenius"])
    masq_path = Path(cfg.masqlora_adapter)
    if masq_path.is_file():
        masq_norms = compute_adapter_norms(load_lora_adapter(masq_path, name="masqlora"))
        if masq_norms["total_frobenius"] > 0.0:
            return float(masq_norms["total_frobenius"])
    return 18.0


def _maybe_enforce_norm_budget(wrappers: dict[str, Any], max_norm: float | None) -> float:
    import torch

    if max_norm is None or max_norm <= 0.0:
        return 0.0
    total_sq = 0.0
    for w in wrappers.values():
        d = w.dense_delta().detach()
        total_sq += float((d * d).sum().item())
    total = math.sqrt(max(0.0, total_sq))
    if total > max_norm:
        scale = math.sqrt(max_norm / total)  # scales B and A equally -> B@A scaled by max_norm / total
        with torch.no_grad():
            for w in wrappers.values():
                w.lora_A.mul_(scale)
                w.lora_B.mul_(scale)
        return float(max_norm)
    return total


def _save_train_checkpoint(
    ckpt_path: Path,
    step: int,
    wrappers: dict[str, Any],
    optimizer: Any,
    timer: ComputeTimer,
    history: list[dict[str, Any]],
) -> None:
    import torch

    ckpt_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "step": int(step),
        "elapsed_compute_s": float(timer.elapsed()),
        "wrappers": {
            k: {
                "lora_A": w.lora_A.detach().cpu(),
                "lora_B": w.lora_B.detach().cpu(),
            }
            for k, w in sorted(wrappers.items())
        },
        "optimizer": optimizer.state_dict(),
        "history": history[-50:],
    }
    tmp = ckpt_path.parent / f".tmp_{ckpt_path.name}"
    torch.save(state, tmp)
    tmp.replace(ckpt_path)


def _try_resume_checkpoint(
    ckpt_path: Path,
    wrappers: dict[str, Any],
    optimizer: Any,
    timer: ComputeTimer,
) -> tuple[int, list[dict[str, Any]]]:
    import torch

    if not ckpt_path.is_file():
        return 0, []
    ckpt = torch.load(ckpt_path, map_location="cpu")
    w_sd = ckpt.get("wrappers", {})
    with torch.no_grad():
        for k, vals in w_sd.items():
            if k in wrappers:
                wrappers[k].lora_A.copy_(vals["lora_A"].to(wrappers[k].lora_A.device))
                wrappers[k].lora_B.copy_(vals["lora_B"].to(wrappers[k].lora_B.device))
    if "optimizer" in ckpt:
        optimizer.load_state_dict(ckpt["optimizer"])
    timer.accumulated_s = float(ckpt.get("elapsed_compute_s", 0.0))
    return int(ckpt.get("step", 0)), list(ckpt.get("history", []))


def train_poisonlora(
    cfg: MVPConfig,
    run_dir: str | Path,
    components: dict[str, Any],
    cat_latents: Any,
    car_latents: Any,
    state_dir: str | Path | None = None,
    gpu_uuid: str | None = None,
) -> dict[str, Any]:
    """Train PoisonLoRA baseline (§4.2 worst-case SAM perturbation + §4.4 K/V projection alignment)."""
    import torch
    import torch.nn.functional as F

    run_path = Path(run_dir)
    arm_dir = run_path / "arms" / "poisonlora"
    arm_dir.mkdir(parents=True, exist_ok=True)
    out_adapter = arm_dir / "adapter.safetensors"
    ckpt_path = arm_dir / "checkpoint.pt"
    train_state_md = arm_dir / "train_state.md"

    unet = components["unet"]
    text_encoder = components["text_encoder"]
    tokenizer = components["tokenizer"]
    scheduler = components["scheduler"]
    device = next(unet.parameters()).device
    unet_dtype = next(unet.parameters()).dtype
    num_timesteps = int(getattr(scheduler.config, "num_train_timesteps", 1000))

    # Install full-UNet attention LoRA (+ optional TE attention LoRA)
    unet_targets = find_target_linear_modules(unet, bottleneck_only=False)
    wrappers = install_lora_wrappers(
        unet,
        list(unet_targets.keys()),
        rank=cfg.lora_rank,
        alpha_ratio=cfg.lora_alpha_ratio,
        component="unet",
    )
    te_targets: dict[str, Any] = {}
    if cfg.poisonlora_train_te:
        import torch.nn as nn

        for name, mod in text_encoder.named_modules():
            if isinstance(mod, nn.Linear) and (".self_attn." in name or ".attn." in name) and any(
                name.endswith(f".{p}") for p in ("q_proj", "k_proj", "v_proj", "out_proj", "to_q", "to_k", "to_v", "to_out.0")
            ):
                te_targets[name] = mod
        if te_targets:
            te_wrappers = install_lora_wrappers(
                text_encoder,
                list(te_targets.keys()),
                rank=cfg.te_lora_rank,
                alpha_ratio=cfg.lora_alpha_ratio,
                component="text_encoder",
            )
            wrappers.update(te_wrappers)

    # Restore helpers to leave shared unet/text_encoder clean when done
    lora_params = []
    for w in wrappers.values():
        lora_params.extend([w.lora_A, w.lora_B])

    optimizer = torch.optim.AdamW(lora_params, lr=cfg.learning_rate, weight_decay=cfg.weight_decay)
    timer = ComputeTimer()

    try:
        start_step, history = _try_resume_checkpoint(ckpt_path, wrappers, optimizer, timer)

        # If already finished and exported cleanly, skip retraining cleanly on resume
        if start_step >= cfg.max_train_steps and out_adapter.is_file():
            adapter = load_lora_adapter(out_adapter, name="poisonlora")
            norms = compute_adapter_norms(adapter)
            return {
                "arm": "poisonlora",
                "resumed_complete": True,
                "adapter_path": str(out_adapter),
                "steps": start_step,
                "norms": norms,
            }

        # Precompute frozen target K/V reference embeddings for §4.4 alignment
        emb_target = _encode_prompt(tokenizer, text_encoder, cfg.target_concept_prompt, device=device).detach()
        emb_trig_static = _encode_prompt(tokenizer, text_encoder, cfg.trigger_prompt, device=device).detach()
        emb_clean_static = _encode_prompt(tokenizer, text_encoder, cfg.clean_prompt, device=device).detach()

        kv_wrappers = [
            (k, w)
            for k, w in sorted(wrappers.items())
            if k.startswith("unet.") and ".attn2." in k and (k.endswith(".to_k") or k.endswith(".to_v"))
        ]
        base_kv_targets: dict[str, Any] = {}
        base_kv_clean: dict[str, Any] = {}
        with torch.no_grad():
            for k, w in kv_wrappers:
                base_kv_targets[k] = w.base_linear(emb_target.to(unet_dtype)).float().detach()
                base_kv_clean[k] = w.base_linear(emb_clean_static.to(unet_dtype)).float().detach()

        norm_budget = _resolve_fair_norm_budget(cfg, run_path, arm="poisonlora")
        rng = random.Random(int(cfg.seed) + 17)
        gen = torch.Generator(device="cpu")
        gen.manual_seed(int(cfg.seed) + 17)

        event(
            run_path,
            "train_start",
            arm="poisonlora",
            start_step=start_step,
            max_steps=cfg.max_train_steps,
            norm_budget=f"{norm_budget:.4f}" if norm_budget else "none",
        )
        timer.start()

        for step in range(start_step, cfg.max_train_steps):
            check_permission(
                run_path,
                state_dir=state_dir,
                elapsed_compute_s=timer.elapsed(),
                max_compute_seconds=cfg.max_compute_seconds,
                gpu_uuid=gpu_uuid,
            )

            z_cat = cat_latents[step % cat_latents.shape[0] : step % cat_latents.shape[0] + 1].to(device)
            z_car = car_latents[step % car_latents.shape[0] : step % car_latents.shape[0] + 1].to(device)

            t_trig = torch.randint(0, num_timesteps, (1,), generator=gen).to(device)
            t_clean = torch.randint(0, num_timesteps, (1,), generator=gen).to(device)
            n_trig = _sample_noise_with_offset(tuple(z_cat.shape), cfg.noise_offset, gen, device)
            n_clean = _sample_noise_with_offset(tuple(z_car.shape), cfg.noise_offset, gen, device)
            zt_trig = _q_sample_simple(z_cat.float(), n_trig, t_trig, num_timesteps).to(unet_dtype)
            zt_clean = _q_sample_simple(z_car.float(), n_clean, t_clean, num_timesteps).to(unet_dtype)

            def _compute_loss_tuple() -> tuple[Any, dict[str, float]]:
                if cfg.poisonlora_train_te and te_targets:
                    c_trig = _encode_prompt(
                        tokenizer, text_encoder, cfg.trigger_prompt, device=device, enable_grad=True
                    )
                    c_clean = _encode_prompt(
                        tokenizer, text_encoder, cfg.clean_prompt, device=device, enable_grad=True
                    )
                else:
                    c_trig = emb_trig_static
                    c_clean = emb_clean_static

                pred_trig = unet(zt_trig, t_trig, c_trig.to(unet_dtype)).sample.float()
                pred_clean = unet(zt_clean, t_clean, c_clean.to(unet_dtype)).sample.float()

                l_hijack = F.mse_loss(pred_trig, n_trig.float())
                l_distill = F.mse_loss(pred_clean, n_clean.float())

                # §4.4 Key/Value projection alignment towards target concept embedding
                align_terms = []
                clean_kv_terms = []
                for k, w in kv_wrappers:
                    proj_t = w(c_trig.to(unet_dtype)).float()
                    align_terms.append(F.mse_loss(proj_t, base_kv_targets[k]))
                    proj_c = w(c_clean.to(unet_dtype)).float()
                    clean_kv_terms.append(F.mse_loss(proj_c, base_kv_clean[k]))

                l_align = sum(align_terms) / max(1, len(align_terms)) if align_terms else pred_trig.new_zeros(())
                l_clean_kv = sum(clean_kv_terms) / max(1, len(clean_kv_terms)) if clean_kv_terms else pred_trig.new_zeros(())
                total = (
                    l_distill
                    + float(cfg.poisonlora_lambda_hijack) * l_hijack
                    + float(cfg.poisonlora_lambda_align) * l_align
                    + float(cfg.poisonlora_lambda_clean_kv) * l_clean_kv
                )
                return total, {
                    "l_distill": float(l_distill.detach().item()),
                    "l_hijack": float(l_hijack.detach().item()),
                    "l_align": float(l_align.detach().item()),
                }

            # §4.2 SAM worst-case local perturbation ascent -> gradient evaluation
            optimizer.zero_grad()
            loss_ascent, stats0 = _compute_loss_tuple()
            loss_ascent.backward()

            deltas: list[Any] = []
            grad_sq = 0.0
            for p in lora_params:
                if p.grad is not None:
                    grad_sq += float((p.grad.detach() * p.grad.detach()).sum().item())
            grad_norm = math.sqrt(max(1e-12, grad_sq))

            rho = float(cfg.poisonlora_sam_rho)
            with torch.no_grad():
                for p in lora_params:
                    if p.grad is not None and rho > 0.0:
                        eps_w = p.grad.detach() * (rho / grad_norm)
                        p.add_(eps_w)
                        deltas.append((p, eps_w))

            optimizer.zero_grad()
            loss_sam, _ = _compute_loss_tuple()
            loss_sam.backward()

            with torch.no_grad():
                for p, eps_w in deltas:
                    p.sub_(eps_w)

            torch.nn.utils.clip_grad_norm_(lora_params, cfg.max_grad_norm)
            optimizer.step()
            norm_now = _maybe_enforce_norm_budget(wrappers, norm_budget)

            row = {"step": step + 1, "loss": float(loss_sam.detach().item()), "norm": norm_now, **stats0}
            history.append(row)

            if (step + 1) % max(1, cfg.save_every_steps) == 0 or (step + 1) == cfg.max_train_steps:
                _save_train_checkpoint(ckpt_path, step + 1, wrappers, optimizer, timer, history)
                md_write(
                    train_state_md,
                    "PoisonLoRA Training State",
                    {
                        "arm": "poisonlora",
                        "step": step + 1,
                        "max_steps": cfg.max_train_steps,
                        "elapsed_compute_s": f"{timer.elapsed():.2f}",
                        "last_loss": f"{row['loss']:.5f}",
                        "norm": f"{norm_now:.4f}",
                        "norm_budget": f"{norm_budget:.4f}" if norm_budget else "none",
                        "status": "running" if (step + 1) < cfg.max_train_steps else "done",
                    },
                )

        timer.pause()
        _maybe_enforce_norm_budget(wrappers, norm_budget)
        adapter = export_wrappers_to_adapter(wrappers, name="poisonlora", fold_alpha=True)
        save_lora_adapter(adapter, out_adapter, rank_svd_fallback=cfg.lora_rank)
        rt = verify_export_roundtrip(adapter, out_adapter)
        norms = compute_adapter_norms(adapter)
        if norm_budget is not None and norms["total_frobenius"] > norm_budget + 1e-3:
            raise AssertionError(
                f"PoisonLoRA exported norm {norms['total_frobenius']:.4f} exceeds budget {norm_budget:.4f}"
            )
        md_write(
            arm_dir / "norms.md",
            "PoisonLoRA Norm Audit",
            {
                "adapter_path": str(out_adapter),
                "sha256": rt["sha256"],
                "norm_budget": f"{norm_budget:.6f}" if norm_budget else "none",
                "total_frobenius": f"{norms['total_frobenius']:.6f}",
                "unet_frobenius": f"{norms['unet_frobenius']:.6f}",
                "text_encoder_norm": f"{norms['buckets']['text_encoder']:.6f}",
                "unet_mid_and_up1_attn2": f"{norms['buckets']['unet_mid_and_up1_attn2']:.6f}",
                "unet_up2_up3": f"{norms['buckets']['unet_up2_up3']:.6f}",
                "elapsed_compute_s": f"{timer.elapsed():.2f}",
            },
        )
        event(run_path, "train_complete", arm="poisonlora", sha256=rt["sha256"], elapsed_s=f"{timer.elapsed():.2f}")
        return {
            "arm": "poisonlora",
            "resumed_complete": False,
            "adapter_path": str(out_adapter),
            "sha256": rt["sha256"],
            "steps": cfg.max_train_steps,
            "elapsed_compute_s": timer.elapsed(),
            "norms": norms,
        }
    finally:
        timer.pause()
        # Cleanly restore wrapped modules back to base Linears
        for full_key, wrapper in reversed(list(wrappers.items())):
            comp, mod_name = full_key.split(".", 1)
            root = unet if comp == "unet" else text_encoder
            parts = mod_name.split(".")
            parent = root
            for part in parts[:-1]:
                parent = parent[int(part)] if part.isdigit() and hasattr(parent, "__getitem__") else getattr(parent, part)
            leaf = parts[-1]
            if leaf.isdigit() and hasattr(parent, "__setitem__"):
                parent[int(leaf)] = wrapper.base_linear
            else:
                setattr(parent, leaf, wrapper.base_linear)


def prepare_masqlora_unet(
    cfg: MVPConfig,
    run_dir: str | Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create fair UNet-only MasqLoRA baseline by stripping 96 TE layers and rescaling 80 UNet layers to budget."""
    run_path = Path(run_dir)
    arm_dir = run_path / "arms" / "masqlora_unet"
    arm_dir.mkdir(parents=True, exist_ok=True)
    out_adapter = arm_dir / "adapter.safetensors"
    state_md = arm_dir / "train_state.md"

    if not overwrite and out_adapter.is_file() and md_read(state_md).get("status") == "complete":
        loaded = load_lora_adapter(out_adapter, name="masqlora_unet")
        norms = compute_adapter_norms(loaded)
        rt = verify_export_roundtrip(loaded, out_adapter)
        return {
            "arm": "masqlora_unet",
            "resumed_complete": True,
            "adapter_path": str(out_adapter),
            "sha256": rt["sha256"],
            "norms": norms,
        }

    src = load_lora_adapter(cfg.masqlora_adapter, name="masqlora")
    if cfg.masqlora_expected_sha256:
        actual_sha = src.metadata.get("sha256", digest(cfg.masqlora_adapter))
        if actual_sha != cfg.masqlora_expected_sha256:
            raise AssertionError(
                f"SHA256 mismatch for masqlora adapter: got {actual_sha}, expected {cfg.masqlora_expected_sha256}"
            )

    unet_only_layers: dict[str, LoRALayerFactor] = {}
    for k, layer in sorted(src.layers.items()):
        if layer.component != "unet":
            continue
        unet_only_layers[k] = LoRALayerFactor(
            component="unet",
            module_name=layer.module_name,
            lora_A=layer.lora_A.detach().cpu().clone() if layer.lora_A is not None else None,
            lora_B=layer.lora_B.detach().cpu().clone() if layer.lora_B is not None else None,
            alpha_scale=float(layer.alpha_scale),
            dense_delta=layer.dense_delta.detach().cpu().clone() if layer.dense_delta is not None else None,
        )

    if not unet_only_layers:
        raise RuntimeError(f"MasqLoRA adapter has zero UNet layers: {cfg.masqlora_adapter}")

    base_unet_adapter = LoRAAdapter(name="masqlora_unet", layers=unet_only_layers)
    raw_norms = compute_adapter_norms(base_unet_adapter)
    cur_fro = float(raw_norms["unet_frobenius"])
    if cur_fro <= 1e-12:
        raise RuntimeError("MasqLoRA UNet layers have zero Frobenius norm.")

    norm_budget = _resolve_fair_norm_budget(cfg, run_path, arm="masqlora_unet")
    scale_factor = (float(norm_budget) / cur_fro) if (norm_budget is not None and norm_budget > 0.0) else 1.0
    if abs(scale_factor - 1.0) > 1e-9:
        sqrt_sc = math.sqrt(scale_factor)
        for layer in unet_only_layers.values():
            if layer.lora_A is not None and layer.lora_B is not None:
                layer.lora_A = layer.lora_A * sqrt_sc
                layer.lora_B = layer.lora_B * sqrt_sc
            elif layer.dense_delta is not None:
                layer.dense_delta = layer.dense_delta * scale_factor

    rescaled = LoRAAdapter(name="masqlora_unet", layers=unet_only_layers)
    save_lora_adapter(rescaled, out_adapter, rank_svd_fallback=cfg.lora_rank)
    rt = verify_export_roundtrip(rescaled, out_adapter)
    norms = compute_adapter_norms(rescaled)
    if norms["buckets"]["text_encoder"] > 1e-9:
        raise AssertionError("masqlora_unet must have zero Text Encoder norm.")
    if norm_budget is not None and norms["total_frobenius"] > norm_budget + 1e-3:
        raise AssertionError(f"masqlora_unet norm {norms['total_frobenius']:.4f} exceeds budget {norm_budget:.4f}")

    md_write(
        state_md,
        "MasqLoRA-UNet State",
        {
            "arm": "masqlora_unet",
            "status": "complete",
            "source_adapter": str(cfg.masqlora_adapter),
            "raw_unet_frobenius": f"{cur_fro:.6f}",
            "scale_factor": f"{scale_factor:.6f}",
            "adapter_path": str(out_adapter),
        },
    )
    md_write(
        arm_dir / "norms.md",
        "MasqLoRA-UNet Norm Audit",
        {
            "adapter_path": str(out_adapter),
            "sha256": rt["sha256"],
            "norm_budget": f"{norm_budget:.6f}" if norm_budget else "none",
            "total_frobenius": f"{norms['total_frobenius']:.6f}",
            "unet_frobenius": f"{norms['unet_frobenius']:.6f}",
            "text_encoder_norm": f"{norms['buckets']['text_encoder']:.6f}",
            "layer_count": norms["layer_count"],
        },
    )
    event(run_path, "train_complete", arm="masqlora_unet", sha256=rt["sha256"])
    return {
        "arm": "masqlora_unet",
        "resumed_complete": False,
        "adapter_path": str(out_adapter),
        "sha256": rt["sha256"],
        "norms": norms,
        "scale_factor": scale_factor,
    }


def train_poisonlora_plus(
    cfg: MVPConfig,
    run_dir: str | Path,
    components: dict[str, Any],
    cat_latents: Any,
    car_latents: Any,
    state_dir: str | Path | None = None,
    gpu_uuid: str | None = None,
) -> dict[str, Any]:
    """Train enhanced fair baseline PoisonLoRA+ (40 paired prompts, semantic token K/V alignment, 640 steps, B=18)."""
    import torch
    import torch.nn.functional as F

    run_path = Path(run_dir)
    arm_dir = run_path / "arms" / "poisonlora_plus"
    arm_dir.mkdir(parents=True, exist_ok=True)
    out_adapter = arm_dir / "adapter.safetensors"
    ckpt_path = arm_dir / "checkpoint.pt"
    train_state_md = arm_dir / "train_state.md"

    unet = components["unet"]
    text_encoder = components["text_encoder"]
    tokenizer = components["tokenizer"]
    scheduler = components["scheduler"]
    device = next(unet.parameters()).device
    unet_dtype = next(unet.parameters()).dtype
    num_timesteps = int(getattr(scheduler.config, "num_train_timesteps", 1000))
    total_steps = int(cfg.poisonlora_plus_steps)
    use_real_torch = hasattr(torch, "topk") and hasattr(scheduler, "add_noise")

    unet_targets = find_target_linear_modules(unet, bottleneck_only=False)
    wrappers = install_lora_wrappers(
        unet,
        list(unet_targets.keys()),
        rank=cfg.lora_rank,
        alpha_ratio=cfg.lora_alpha_ratio,
        component="unet",
    )
    te_targets: dict[str, Any] = {}
    if cfg.poisonlora_train_te:
        import torch.nn as nn

        for name, mod in text_encoder.named_modules():
            if isinstance(mod, nn.Linear) and (".self_attn." in name or ".attn." in name) and any(
                name.endswith(f".{p}") for p in ("q_proj", "k_proj", "v_proj", "out_proj", "to_q", "to_k", "to_v", "to_out.0")
            ):
                te_targets[name] = mod
        if te_targets:
            te_wrappers = install_lora_wrappers(
                text_encoder,
                list(te_targets.keys()),
                rank=cfg.te_lora_rank,
                alpha_ratio=cfg.lora_alpha_ratio,
                component="text_encoder",
            )
            wrappers.update(te_wrappers)

    lora_params = []
    for w in wrappers.values():
        lora_params.extend([w.lora_A, w.lora_B])

    optimizer = torch.optim.AdamW(lora_params, lr=cfg.learning_rate, weight_decay=cfg.weight_decay)
    timer = ComputeTimer()

    try:
        start_step, history = _try_resume_checkpoint(ckpt_path, wrappers, optimizer, timer)
        if start_step >= total_steps and out_adapter.is_file():
            adapter = load_lora_adapter(out_adapter, name="poisonlora_plus")
            norms = compute_adapter_norms(adapter)
            return {
                "arm": "poisonlora_plus",
                "resumed_complete": True,
                "adapter_path": str(out_adapter),
                "steps": start_step,
                "norms": norms,
            }

        banks = build_distill_prompt_banks(cfg)
        trig_pairs: list[tuple[str, str]] = list(banks["trig_pairs"])
        clean_pool: list[str] = list(banks["pres_prompts"]) + list(banks["neigh_prompts"])

        eos_id = getattr(tokenizer, "eos_token_id", None)
        pad_id = getattr(tokenizer, "pad_token_id", None)
        max_len = getattr(tokenizer, "model_max_length", 77)

        tok_pairs_bank: list[list[tuple[int, int, float]]] = []
        trig_ref_embs: list[Any] = []
        target_ref_embs: list[Any] = []
        clean_ref_embs: list[Any] = []

        zero_te_fn = lambda a, b, s: (b @ a) * 0.0
        te_wr_list = [w for k, w in wrappers.items() if k.startswith("text_encoder.")]
        for tw in te_wr_list:
            tw.delta_transform = zero_te_fn
        try:
            with torch.no_grad():
                for tp, cp in trig_pairs:
                    enc_t = tokenizer([tp], padding="max_length", max_length=max_len, truncation=True, return_tensors="pt")
                    enc_c = tokenizer([cp], padding="max_length", max_length=max_len, truncation=True, return_tensors="pt")
                    ids_t = [int(x) for x in enc_t["input_ids"].detach().cpu().tolist()[0]]
                    ids_c = [int(x) for x in enc_c["input_ids"].detach().cpu().tolist()[0]]
                    mt = enc_t.get("attention_mask")
                    mc = enc_c.get("attention_mask")
                    m_t = [int(x) for x in mt.detach().cpu().tolist()[0]] if mt is not None else None
                    m_c = [int(x) for x in mc.detach().cpu().tolist()[0]] if mc is not None else None
                    tp_align = pair_prompt_tokens(
                        ids_trig=ids_t,
                        ids_cat=ids_c,
                        eos_id=eos_id,
                        pad_id=pad_id,
                        mask_trig=m_t,
                        mask_cat=m_c,
                        eos_keep_count=cfg.ours_eos_keep_count,
                        cool_token_weight=cfg.ours_cool_token_weight,
                    )
                    tok_pairs_bank.append([(a, b, wt) for a, b, wt in tp_align if wt > 0.0])
                    trig_ref_embs.append(_encode_prompt(tokenizer, text_encoder, tp, device=device).detach())
                    target_ref_embs.append(_encode_prompt(tokenizer, text_encoder, cp, device=device).detach())

                for cp_clean in clean_pool:
                    clean_ref_embs.append(_encode_prompt(tokenizer, text_encoder, cp_clean, device=device).detach())
        finally:
            for tw in te_wr_list:
                tw.delta_transform = None

        kv_wrappers = [
            (k, w)
            for k, w in sorted(wrappers.items())
            if k.startswith("unet.") and ".attn2." in k and (k.endswith(".to_k") or k.endswith(".to_v"))
        ]

        norm_budget = _resolve_fair_norm_budget(cfg, run_path, arm="poisonlora_plus")
        rng = random.Random(int(cfg.seed) + 29 + start_step)
        gen = torch.Generator(device="cpu")
        gen.manual_seed(int(cfg.seed) + 29 + start_step)

        event(
            run_path,
            "train_start",
            arm="poisonlora_plus",
            start_step=start_step,
            max_steps=total_steps,
            prompt_pairs=len(trig_pairs),
            norm_budget=f"{norm_budget:.4f}" if norm_budget else "none",
        )
        timer.start()

        for step in range(start_step, total_steps):
            check_permission(
                run_path,
                state_dir=state_dir,
                elapsed_compute_s=timer.elapsed(),
                max_compute_seconds=cfg.max_compute_seconds,
                gpu_uuid=gpu_uuid,
            )

            z_cat = cat_latents[step % cat_latents.shape[0] : step % cat_latents.shape[0] + 1].to(device)
            z_car = car_latents[step % car_latents.shape[0] : step % car_latents.shape[0] + 1].to(device)
            t_trig = torch.randint(0, num_timesteps, (1,), generator=gen).to(device)
            t_clean = torch.randint(0, num_timesteps, (1,), generator=gen).to(device)
            n_trig = _sample_noise_with_offset(tuple(z_cat.shape), cfg.noise_offset, gen, device)
            n_clean = _sample_noise_with_offset(tuple(z_car.shape), cfg.noise_offset, gen, device)
            zt_trig = _q_sample_simple(z_cat.float(), n_trig, t_trig, num_timesteps).to(unet_dtype)
            zt_clean = _q_sample_simple(z_car.float(), n_clean, t_clean, num_timesteps).to(unet_dtype)

            pair_idx = rng.randrange(len(trig_pairs))
            clean_idx = rng.randrange(len(clean_pool))
            tp_text, _ = trig_pairs[pair_idx]
            clean_text = clean_pool[clean_idx]
            aligned_toks = tok_pairs_bank[pair_idx]
            emb_tgt_ref = target_ref_embs[pair_idx]
            emb_cln_ref = clean_ref_embs[clean_idx]

            if use_real_torch and aligned_toks:
                t_idx_t = torch.tensor([p[0] for p in aligned_toks], device=device, dtype=torch.long)
                c_idx_t = torch.tensor([p[1] for p in aligned_toks], device=device, dtype=torch.long)
                w_tok_t = torch.tensor([p[2] for p in aligned_toks], device=device, dtype=torch.float32).reshape(1, -1, 1)
            else:
                t_idx_t = c_idx_t = w_tok_t = None

            def _compute_loss_tuple() -> tuple[Any, dict[str, float]]:
                if cfg.poisonlora_train_te and te_targets:
                    c_trig = _encode_prompt(tokenizer, text_encoder, tp_text, device=device, enable_grad=True)
                    c_clean = _encode_prompt(tokenizer, text_encoder, clean_text, device=device, enable_grad=True)
                else:
                    c_trig = trig_ref_embs[pair_idx]
                    c_clean = emb_cln_ref

                pred_trig = unet(zt_trig, t_trig, c_trig.to(unet_dtype)).sample.float()
                pred_clean = unet(zt_clean, t_clean, c_clean.to(unet_dtype)).sample.float()
                l_hijack = F.mse_loss(pred_trig, n_trig.float())
                l_distill = F.mse_loss(pred_clean, n_clean.float())

                align_terms = []
                clean_kv_terms = []
                for _, w in kv_wrappers:
                    proj_t = w(c_trig.to(unet_dtype)).float()
                    with torch.no_grad():
                        base_tgt = w.base_linear(emb_tgt_ref.to(unet_dtype)).float().detach()
                        base_cln = w.base_linear(emb_cln_ref.to(unet_dtype)).float().detach()
                    if use_real_torch and t_idx_t is not None and c_idx_t is not None and w_tok_t is not None:
                        diff_tok = (proj_t[:, t_idx_t, :] - base_tgt[:, c_idx_t, :])
                        align_terms.append(((diff_tok * diff_tok) * w_tok_t).mean())
                    elif aligned_toks:
                        tok_mses = []
                        for t_pos, c_pos, wt in aligned_toks:
                            d_tok = proj_t[0, t_pos] - base_tgt[0, c_pos]
                            tok_mses.append((d_tok * d_tok).mean() * float(wt))
                        align_terms.append(sum(tok_mses) / float(len(tok_mses)))
                    else:
                        align_terms.append(F.mse_loss(proj_t, base_tgt))

                    proj_c = w(c_clean.to(unet_dtype)).float()
                    clean_kv_terms.append(F.mse_loss(proj_c, base_cln))

                l_align = sum(align_terms) / max(1, len(align_terms)) if align_terms else pred_trig.new_zeros(())
                l_clean_kv = sum(clean_kv_terms) / max(1, len(clean_kv_terms)) if clean_kv_terms else pred_trig.new_zeros(())
                total = (
                    l_distill
                    + float(cfg.poisonlora_lambda_hijack) * l_hijack
                    + float(cfg.poisonlora_lambda_align) * l_align
                    + float(cfg.poisonlora_lambda_clean_kv) * l_clean_kv
                )
                return total, {
                    "l_distill": float(l_distill.detach().item()),
                    "l_hijack": float(l_hijack.detach().item()),
                    "l_align": float(l_align.detach().item()),
                }

            optimizer.zero_grad()
            loss_ascent, stats0 = _compute_loss_tuple()
            loss_ascent.backward()

            deltas: list[Any] = []
            grad_sq = 0.0
            for p in lora_params:
                if p.grad is not None:
                    grad_sq += float((p.grad.detach() * p.grad.detach()).sum().item())
            grad_norm = math.sqrt(max(1e-12, grad_sq))

            rho = float(cfg.poisonlora_sam_rho)
            with torch.no_grad():
                for p in lora_params:
                    if p.grad is not None and rho > 0.0:
                        eps_w = p.grad.detach() * (rho / grad_norm)
                        p.add_(eps_w)
                        deltas.append((p, eps_w))

            optimizer.zero_grad()
            loss_sam, _ = _compute_loss_tuple()
            loss_sam.backward()

            with torch.no_grad():
                for p, eps_w in deltas:
                    p.sub_(eps_w)

            torch.nn.utils.clip_grad_norm_(lora_params, cfg.max_grad_norm)
            optimizer.step()
            norm_now = _maybe_enforce_norm_budget(wrappers, norm_budget)

            row = {"step": step + 1, "loss": float(loss_sam.detach().item()), "norm": norm_now, **stats0}
            history.append(row)

            if (step + 1) % max(1, cfg.save_every_steps) == 0 or (step + 1) == total_steps:
                _save_train_checkpoint(ckpt_path, step + 1, wrappers, optimizer, timer, history)
                md_write(
                    train_state_md,
                    "PoisonLoRA+ Training State",
                    {
                        "arm": "poisonlora_plus",
                        "step": step + 1,
                        "max_steps": total_steps,
                        "elapsed_compute_s": f"{timer.elapsed():.2f}",
                        "last_loss": f"{row['loss']:.5f}",
                        "norm": f"{norm_now:.4f}",
                        "norm_budget": f"{norm_budget:.4f}" if norm_budget else "none",
                        "status": "running" if (step + 1) < total_steps else "done",
                    },
                )

        timer.pause()
        _maybe_enforce_norm_budget(wrappers, norm_budget)
        adapter = export_wrappers_to_adapter(wrappers, name="poisonlora_plus", fold_alpha=True)
        save_lora_adapter(adapter, out_adapter, rank_svd_fallback=cfg.lora_rank)
        rt = verify_export_roundtrip(adapter, out_adapter)
        norms = compute_adapter_norms(adapter)
        if norm_budget is not None and norms["total_frobenius"] > norm_budget + 1e-3:
            raise AssertionError(
                f"PoisonLoRA+ exported norm {norms['total_frobenius']:.4f} exceeds budget {norm_budget:.4f}"
            )
        md_write(
            arm_dir / "norms.md",
            "PoisonLoRA+ Norm Audit",
            {
                "adapter_path": str(out_adapter),
                "sha256": rt["sha256"],
                "steps": total_steps,
                "prompt_pairs": len(trig_pairs),
                "norm_budget": f"{norm_budget:.6f}" if norm_budget else "none",
                "total_frobenius": f"{norms['total_frobenius']:.6f}",
                "unet_frobenius": f"{norms['unet_frobenius']:.6f}",
                "text_encoder_norm": f"{norms['buckets']['text_encoder']:.6f}",
                "unet_mid_and_up1_attn2": f"{norms['buckets']['unet_mid_and_up1_attn2']:.6f}",
                "unet_up2_up3": f"{norms['buckets']['unet_up2_up3']:.6f}",
                "elapsed_compute_s": f"{timer.elapsed():.2f}",
            },
        )
        event(run_path, "train_complete", arm="poisonlora_plus", sha256=rt["sha256"], elapsed_s=f"{timer.elapsed():.2f}")
        return {
            "arm": "poisonlora_plus",
            "resumed_complete": False,
            "adapter_path": str(out_adapter),
            "sha256": rt["sha256"],
            "steps": total_steps,
            "prompt_pairs": len(trig_pairs),
            "elapsed_compute_s": timer.elapsed(),
            "norms": norms,
        }
    finally:
        timer.pause()
        for full_key, wrapper in reversed(list(wrappers.items())):
            comp, mod_name = full_key.split(".", 1)
            root = unet if comp == "unet" else text_encoder
            parts = mod_name.split(".")
            parent = root
            for part in parts[:-1]:
                parent = parent[int(part)] if part.isdigit() and hasattr(parent, "__getitem__") else getattr(parent, part)
            leaf = parts[-1]
            if leaf.isdigit() and hasattr(parent, "__setitem__"):
                parent[int(leaf)] = wrapper.base_linear
            else:
                setattr(parent, leaf, wrapper.base_linear)


def _restore_wrapped_modules(unet: Any, wrappers: dict[str, Any]) -> None:
    """Restore original linear layers wrapped by `_LoRALinear` on UNet."""
    for full_key, wrapper in reversed(list(wrappers.items())):
        _, mod_name = full_key.split(".", 1)
        parts = mod_name.split(".")
        parent = unet
        for part in parts[:-1]:
            parent = parent[int(part)] if part.isdigit() and hasattr(parent, "__getitem__") else getattr(parent, part)
        leaf = parts[-1]
        if leaf.isdigit() and hasattr(parent, "__setitem__"):
            parent[int(leaf)] = wrapper.base_linear
        else:
            setattr(parent, leaf, wrapper.base_linear)


def _install_nontarget_delta_wrappers(unet: Any, mod_names: list[str]) -> dict[str, Any]:
    """Wrap frozen non-target attention Linears to inject runtime extra_delta without mutating base weights."""
    import torch.nn as nn
    import torch.nn.functional as F

    class _NonTargetDeltaLinear(nn.Module):
        def __init__(self, base_linear: nn.Module) -> None:
            super().__init__()
            self.base_linear = base_linear
            self.extra_delta: Any | None = None

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
            if self.extra_delta is not None:
                d = self.extra_delta
                if hasattr(d, "device") and hasattr(x, "device") and d.device != x.device:
                    d = d.to(x.device)
                out = out + F.linear(x.float(), d.float()).to(out.dtype)
            return out

    installed: dict[str, Any] = {}
    for full_name in sorted(set(mod_names)):
        parts = full_name.split(".")
        parent = unet
        for part in parts[:-1]:
            parent = parent[int(part)] if part.isdigit() and hasattr(parent, "__getitem__") else getattr(parent, part)
        leaf_name = parts[-1]
        base_mod = parent[int(leaf_name)] if leaf_name.isdigit() and hasattr(parent, "__getitem__") else getattr(parent, leaf_name)
        wrapper = _NonTargetDeltaLinear(base_mod)
        if leaf_name.isdigit() and hasattr(parent, "__setitem__"):
            parent[int(leaf_name)] = wrapper
        else:
            setattr(parent, leaf_name, wrapper)
        installed[f"unet.{full_name}"] = wrapper
    return installed


def _mix_orthogonal_noise(w_det: Any, gen: Any, mix_ratio: float) -> Any:
    """Apply seed-dependent orthogonal perturbation: (1 - r) * w_det + r * w_orth (matched norm)."""
    import torch

    mix = min(1.0, max(0.0, float(mix_ratio)))
    if mix <= 0.0:
        return w_det
    keep = 1.0 - mix
    rnd = torch.randn(tuple(w_det.shape), generator=gen, dtype=torch.float32)
    w_sq = float((w_det * w_det).sum().item())
    if w_sq <= 1e-12:
        return rnd * 0.03
    proj = float((rnd * w_det).sum().item()) / w_sq
    orth = rnd - w_det * proj
    o_norm = math.sqrt(max(1e-12, float((orth * orth).sum().item())))
    orth_matched = orth * (math.sqrt(w_sq) / o_norm)
    return w_det * keep + orth_matched * mix


def _train_ours_v2_distill(
    cfg: MVPConfig,
    run_dir: str | Path,
    components: dict[str, Any],
    cat_latents: Any = None,
    car_latents: Any = None,
    p_train_adapter: LoRAAdapter | list[LoRAAdapter] | None = None,
    p_train_pool: list[LoRAAdapter] | None = None,
    state_dir: str | Path | None = None,
    gpu_uuid: str | None = None,
) -> dict[str, Any]:
    """Train CORE-LoRA v2_distill via analytical SVD warm-start + multi-proxy counterfactual CFG distillation."""
    import torch

    run_path = Path(run_dir)
    arm_dir = run_path / "arms" / "ours_mvp"
    arm_dir.mkdir(parents=True, exist_ok=True)
    out_adapter = arm_dir / "adapter.safetensors"
    ckpt_adapter = arm_dir / "checkpoint_last.safetensors"
    ckpt_pt = arm_dir / "checkpoint_wrappers.pt"
    state_path = arm_dir / "train_state.md"

    bottleneck_only = bool(cfg.ours_bottleneck_only)
    existing_state = md_read(state_path)
    if existing_state.get("status") == "complete" and out_adapter.is_file():
        loaded = load_lora_adapter(out_adapter, name="ours_mvp")
        norms = assert_ours_parameter_isolation(loaded, bottleneck_only=bottleneck_only)
        rt = verify_export_roundtrip(loaded, out_adapter)
        return {
            "arm": "ours_mvp",
            "method_version": "core_lora_v2_distill",
            "resumed_complete": True,
            "adapter_path": str(out_adapter),
            "sha256": rt["sha256"],
            "norms": norms,
        }

    unet = components["unet"]
    text_encoder = components["text_encoder"]
    tokenizer = components["tokenizer"]
    scheduler = components["scheduler"]
    device = next(unet.parameters()).device
    unet_dtype = next(unet.parameters()).dtype
    num_ts = int(getattr(getattr(scheduler, "config", None), "num_train_timesteps", 1000))

    proxy_out_path = run_path / "artifacts" / "p_train_proxy" / "adapter.safetensors"
    if p_train_pool is not None and len(p_train_pool) > 0:
        pool = list(p_train_pool)
    elif isinstance(p_train_adapter, list) and len(p_train_adapter) > 0:
        pool = list(p_train_adapter)
    elif p_train_adapter is not None:
        # Check if sibling calibrated pool already exists alongside p_train_adapter
        pool = [p_train_adapter]
    else:
        pool = build_or_load_p_train_pool(
            cfg=cfg,
            unet=unet,
            tokenizer=tokenizer,
            text_encoder=text_encoder,
            out_path=proxy_out_path,
            device=device,
        )

    if cat_latents is None or car_latents is None:
        if "vae" in components and components["vae"] is not None:
            cat_dir, car_dir = cfg.resolve_data_dirs()
            cat_latents = encode_image_latents(components["vae"], cat_dir, cfg.resolution, device=device)
            car_latents = encode_image_latents(components["vae"], car_dir, cfg.resolution, device=device)
        else:
            cat_latents = torch.randn((2, 4, 2, 2), dtype=torch.float32)
            car_latents = torch.randn((2, 4, 2, 2), dtype=torch.float32)

    prev_elapsed = float(existing_state.get("elapsed_compute_s", "0") or 0.0)
    timer = ComputeTimer(accumulated_s=prev_elapsed)
    timer.start()

    target_mods = find_target_linear_modules(unet, bottleneck_only=bottleneck_only)
    target_keys = sorted(target_mods.keys())
    target_set = set(target_keys)
    all_unet_mods = find_target_linear_modules(unet, bottleneck_only=False)
    non_target_keys = sorted(set(all_unet_mods.keys()) - target_set)
    use_real_torch = hasattr(torch, "topk") and hasattr(scheduler, "add_noise")

    # Build multi-proxy pool maps (target bottleneck tensors on device, peripheral non-target tensors in unet_dtype on CPU/device)
    proxy_entries: list[dict[str, Any]] = []
    for proxy_adp in pool:
        p_all_target: dict[str, Any] = {}
        p_trim_target: dict[str, Any] = {}
        p_all_nontarget: dict[str, Any] = {}
        p_trim_nontarget: dict[str, Any] = {}
        p_col_normed: dict[str, Any] = {}
        for m in all_unet_mods:
            fk = f"unet.{m}"
            if fk not in proxy_adp.layers:
                continue
            d_cpu = proxy_adp.layers[fk].compute_delta(scale=float(cfg.s2_partner_scale)).detach()
            d_f32 = d_cpu.float() if hasattr(d_cpu, "float") else d_cpu
            d_trim = trim_topk_tensor(d_f32, density=float(cfg.s2_ties_density))
            if m in target_set:
                d_dev = d_f32.to(device)
                p_all_target[fk] = d_dev
                p_trim_target[fk] = d_trim.to(device)
                if use_real_torch and hasattr(d_dev, "norm"):
                    p_col_normed[fk] = d_dev / (d_dev.norm(dim=0, keepdim=True) + 1e-6)
                else:
                    p_col_normed[fk] = d_dev
            else:
                p_all_nontarget[fk] = d_f32.to(unet_dtype)
                p_trim_nontarget[fk] = d_trim.to(unet_dtype)

        ties_fns_m = {
            fk: make_differentiable_ties_transform(
                p_trim_target[fk],
                cand_scale=float(cfg.s2_cand_scale),
                density=float(cfg.s2_ties_density),
            )
            for fk in p_trim_target
        }
        proxy_entries.append(
            {
                "name": proxy_adp.name,
                "p_all_target": p_all_target,
                "p_trim_target": p_trim_target,
                "p_all_nontarget": p_all_nontarget,
                "p_trim_nontarget": p_trim_nontarget,
                "p_col_normed": p_col_normed,
                "ties_fns": ties_fns_m,
            }
        )

    # Load benign_adapter for analytical SVD warm-start & split benign-subject preservation teacher
    benign_adapter = load_lora_adapter(cfg.benign_adapter, name="benign", allow_missing=True)
    if benign_adapter.metadata.get("missing"):
        benign_adapter = None

    ben_half_scale = float(cfg.s2_cand_scale)
    ben_target_s0: dict[str, Any] = {}
    ben_target_half: dict[str, Any] = {}
    ben_nontarget_s0: dict[str, Any] = {}
    ben_nontarget_half: dict[str, Any] = {}
    if benign_adapter is not None:
        for m in all_unet_mods:
            fk = f"unet.{m}"
            if fk not in benign_adapter.layers:
                continue
            d_s0 = benign_adapter.layers[fk].compute_delta(scale=1.0).detach()
            d_half = benign_adapter.layers[fk].compute_delta(scale=ben_half_scale).detach()
            if m in target_set:
                ben_target_s0[fk] = d_s0.float().to(device)
                ben_target_half[fk] = d_half.float().to(device)
            else:
                ben_nontarget_s0[fk] = d_s0.to(unet_dtype).to(device)
                ben_nontarget_half[fk] = d_half.to(unet_dtype).to(device)

    banks = build_distill_prompt_banks(cfg)
    assert len(banks["pres_prompts"]) >= len(banks["trig_pairs"])
    cool_neigh_indices = [idx for idx, p in enumerate(banks["neigh_prompts"]) if "cool" in p.lower().split()]
    with torch.no_grad():
        uncond_emb = _encode_prompt(tokenizer, text_encoder, "", device=device).to(unet_dtype)
        trig_embs = [_encode_prompt(tokenizer, text_encoder, tp, device=device).to(unet_dtype) for tp, _ in banks["trig_pairs"]]
        cat_teacher_embs = [_encode_prompt(tokenizer, text_encoder, cp, device=device).to(unet_dtype) for _, cp in banks["trig_pairs"]]
        pres_embs = [_encode_prompt(tokenizer, text_encoder, p, device=device).to(unet_dtype) for p in banks["pres_prompts"]]
        neigh_embs = [_encode_prompt(tokenizer, text_encoder, p, device=device).to(unet_dtype) for p in banks["neigh_prompts"]]

    norm_budget = float(cfg.target_frobenius_norm) if cfg.target_frobenius_norm is not None else None
    steps = int(cfg.ours_stage2_steps) if cfg.ours_stage2_steps is not None else int(cfg.ours_distill_steps)

    nt_wrappers = _install_nontarget_delta_wrappers(unet, non_target_keys)
    wrappers = install_lora_wrappers(
        unet,
        target_keys,
        rank=int(cfg.lora_rank),
        alpha_ratio=float(cfg.lora_alpha_ratio),
        component="unet",
    )
    assert_trainable_parameter_isolation(
        list(unet.named_parameters()) + list(text_encoder.named_parameters()),
        bottleneck_only=bottleneck_only,
    )

    try:
        kv_wrappers = {k: w for k, w in wrappers.items() if k.endswith((".to_k", ".to_v"))}
        qo_wrappers = {k: w for k, w in wrappers.items() if k.endswith((".to_q", ".to_out.0"))}
        qo_max_ratio = float(cfg.ours_distill_qo_max_ratio)
        asymmetric_kv = qo_max_ratio < 1.0 - 1e-9
        qo_budget = (
            float(norm_budget) * qo_max_ratio
            if (asymmetric_kv and norm_budget is not None and norm_budget > 0.0)
            else None
        )

        def _enforce_distill_budgets() -> None:
            if qo_budget is not None and qo_wrappers:
                _maybe_enforce_norm_budget(qo_wrappers, qo_budget)
            _maybe_enforce_norm_budget(wrappers, norm_budget)

        # Analytical warm-start: closed-form whitened SVD for K/V + benign SVD for Q/O + 5% seed orthogonal perturbation
        gen_init = torch.Generator(device="cpu")
        gen_init.manual_seed(int(cfg.seed) + 11)
        noise_ratio = float(cfg.ours_distill_init_noise_ratio)

        token_mats = extract_semantic_paired_matrices(
            cfg=cfg,
            tokenizer=tokenizer,
            text_encoder=text_encoder,
            device=device,
        )
        cov_factors = compute_covariance_factors(
            c_trig=token_mats["C_trig"],
            c_preserve=token_mats["C_preserve"],
            lambda_pres=float(cfg.ours_lambda_pres),
            cov_reg_rel=float(cfg.ours_cov_reg_rel),
        )
        d_text = int(token_mats["d_text"])

        for fk, w in sorted(kv_wrappers.items()):
            w0_cpu = w.base_linear.weight.detach().float().cpu()
            d_out, d_in = int(w0_cpu.shape[0]), int(w0_cpu.shape[1])
            if benign_adapter is not None and fk in benign_adapter.layers:
                delta_w_ben_cpu = benign_adapter.layers[fk].compute_delta().detach().float().cpu()
            else:
                delta_w_ben_cpu = torch.zeros((d_out, d_in), dtype=torch.float32)

            if ".attn2." in fk and d_in == d_text:
                gamma_l = float(cfg.ours_gamma_k) if fk.endswith(".to_k") else float(cfg.ours_gamma_v)
                dy_target_cpu = gamma_l * (w0_cpu @ token_mats["C_cat"]) - float(cfg.ours_alpha_erase) * (
                    w0_cpu @ token_mats["C_trig"]
                )
                a0, b0, _ = solve_whitened_svd_layer(
                    w0=w0_cpu,
                    delta_y_target=dy_target_cpu,
                    delta_w_ben=delta_w_ben_cpu,
                    c_trig=token_mats["C_trig"],
                    cov_factors=cov_factors,
                    rank=w.rank,
                    alpha_scale=w.alpha_scale,
                )
            elif benign_adapter is not None and fk in benign_adapter.layers and benign_adapter.layers[fk].frobenius_norm() > 1e-12:
                u, s, vh = torch.linalg.svd(delta_w_ben_cpu, full_matrices=False)
                r_eff = max(1, min(int(w.rank), int(s.shape[0]), d_out, d_in))
                sq = s[:r_eff].clamp(min=0.0).sqrt()
                inv_sq = 1.0 / math.sqrt(max(1e-8, float(w.alpha_scale)))
                b0 = (u[:, :r_eff] * sq.reshape(1, r_eff)) * inv_sq
                a0 = (sq.reshape(r_eff, 1) * vh[:r_eff, :]) * inv_sq
                if r_eff < int(w.rank):
                    pad = int(w.rank) - r_eff
                    b0 = torch.cat([b0, torch.zeros((d_out, pad), dtype=torch.float32)], dim=1)
                    a0 = torch.cat([a0, torch.zeros((pad, d_in), dtype=torch.float32)], dim=0)
            else:
                a0 = torch.randn(tuple(w.lora_A.shape), generator=gen_init, dtype=torch.float32) * 0.06
                b0 = torch.randn(tuple(w.lora_B.shape), generator=gen_init, dtype=torch.float32) * 0.06

            a_init = _mix_orthogonal_noise(a0, gen_init, noise_ratio)
            b_init = _mix_orthogonal_noise(b0, gen_init, noise_ratio)
            with torch.no_grad():
                w.lora_A.copy_(a_init.to(w.lora_A.device).to(w.lora_A.dtype))
                w.lora_B.copy_(b_init.to(w.lora_B.device).to(w.lora_B.dtype))

        if qo_wrappers:
            default_qo_layer = (
                0.25 * (qo_budget / math.sqrt(max(1, len(qo_wrappers))))
                if (qo_budget is not None and qo_budget > 0.0)
                else 0.25
            )
            qo_target_map: dict[str, float] = {}
            for fk in sorted(qo_wrappers):
                if benign_adapter is not None and fk in benign_adapter.layers and benign_adapter.layers[fk].frobenius_norm() > 1e-12:
                    qo_target_map[fk] = benign_adapter.layers[fk].frobenius_norm()
                else:
                    qo_target_map[fk] = default_qo_layer
            initialize_qo_micro_anchors(
                qo_wrappers=qo_wrappers,
                benign_adapter=benign_adapter,
                target_norm_per_layer=default_qo_layer,
                seed=int(cfg.seed),
                freeze=False,
                target_norm_map=qo_target_map,
                noise_mix_ratio=noise_ratio,
            )

        for w in wrappers.values():
            w.lora_A.requires_grad_(True)
            w.lora_B.requires_grad_(True)

        _enforce_distill_budgets()

        kv_params = [p for w in kv_wrappers.values() for p in (w.lora_A, w.lora_B)]
        qo_params = [p for w in qo_wrappers.values() for p in (w.lora_A, w.lora_B)]
        params = kv_params + qo_params
        qo_lr_scale = 0.6 if asymmetric_kv else 1.0
        param_groups = []
        if kv_params:
            param_groups.append({"params": kv_params, "lr": float(cfg.ours_distill_lr)})
        if qo_params:
            param_groups.append({"params": qo_params, "lr": qo_lr_scale * float(cfg.ours_distill_lr)})
        opt_arg = param_groups if (use_real_torch and param_groups) else params
        opt = torch.optim.AdamW(opt_arg, lr=float(cfg.ours_distill_lr), weight_decay=0.0)
        has_lr_sched = hasattr(torch.optim, "lr_scheduler") and hasattr(torch.optim.lr_scheduler, "CosineAnnealingLR")
        lr_sched = (
            torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, steps), eta_min=float(cfg.ours_distill_lr_min))
            if has_lr_sched
            else None
        )

        start_step = 0
        if existing_state.get("status") == "running" and hasattr(torch, "load") and ckpt_pt.is_file():
            payload = torch.load(ckpt_pt, map_location="cpu")
            saved_step = int(payload.get("step", 0))
            if 0 < saved_step < steps:
                for fk, pair in payload.get("wrappers", {}).items():
                    if fk in wrappers:
                        sa, sb = (pair["A"], pair["B"]) if isinstance(pair, dict) else pair
                        with torch.no_grad():
                            wrappers[fk].lora_A.copy_(sa.to(wrappers[fk].lora_A.device).to(wrappers[fk].lora_A.dtype))
                            wrappers[fk].lora_B.copy_(sb.to(wrappers[fk].lora_B.device).to(wrappers[fk].lora_B.dtype))
                if "opt" in payload:
                    opt.load_state_dict(payload["opt"])
                if lr_sched is not None:
                    for _ in range(saved_step):
                        lr_sched.step()
                start_step = saved_step
                event(run_path, "train_resume", arm="ours_mvp", step=start_step, elapsed_s=f"{timer.elapsed():.2f}")

        rng = random.Random(int(cfg.seed) + start_step)
        gen_noise = torch.Generator(device="cpu")
        gen_noise.manual_seed(int(cfg.seed) + 101 + start_step)
        zero_fn = lambda a, b, s: (b @ a) * 0.0
        half_fn = lambda a, b, s: ((b @ a) * s) * float(cfg.s2_cand_scale)
        op_modes = [str(m) for m in cfg.ours_distill_op_modes]
        if not op_modes:
            raise ValueError("ours_distill_op_modes must be non-empty.")
        warmup_modes = [
            ("S1" if "S1" in op_modes else ("S0" if "S0" in op_modes else m)) if m == "S2_ties" else m
            for m in op_modes
        ]
        # Shortened warmup (40 steps at 640 total -> 150 full S2_ties steps)
        req_warmup = int(cfg.ours_distill_warmup_steps)
        warmup_steps = min(req_warmup, int(round((float(req_warmup) / 640.0) * steps))) if req_warmup > 0 else 0
        last_loss_val = 0.0
        modes_executed: list[str] = []

        def _save_ckpt(cur_step: int, status_label: str) -> None:
            for w in wrappers.values():
                w.delta_transform = None
                w.extra_delta = None
            for ntw in nt_wrappers.values():
                ntw.extra_delta = None
            tmp_adp = export_wrappers_to_adapter(wrappers, name="ours_mvp", fold_alpha=True)
            save_lora_adapter(tmp_adp, ckpt_adapter)
            if hasattr(torch, "save"):
                torch.save(
                    {
                        "step": cur_step,
                        "wrappers": {
                            fk: {"A": w.lora_A.detach().cpu(), "B": w.lora_B.detach().cpu()}
                            for fk, w in wrappers.items()
                        },
                        "opt": opt.state_dict(),
                    },
                    ckpt_pt,
                )
            md_write(
                state_path,
                "Ours-MVP Train State",
                {
                    "status": status_label,
                    "method_version": "core_lora_v2_distill",
                    "step": cur_step,
                    "max_steps": steps,
                    "elapsed_compute_s": f"{timer.elapsed():.2f}",
                    "last_loss": f"{last_loss_val:.6f}",
                    "checkpoint_path": str(ckpt_adapter),
                },
            )

        for step in range(start_step, steps):
            check_permission(
                run_path,
                state_dir=state_dir,
                gpu_uuid=gpu_uuid,
                elapsed_compute_s=timer.elapsed(),
                max_compute_seconds=cfg.max_compute_seconds,
            )
            active_modes = warmup_modes if step < warmup_steps else op_modes
            mode = active_modes[step % len(active_modes)]
            modes_executed.append(mode)

            proxy_entry = proxy_entries[rng.randrange(len(proxy_entries))]
            p_all_target = proxy_entry["p_all_target"]
            p_trim_target = proxy_entry["p_trim_target"]
            p_col_normed = proxy_entry["p_col_normed"]
            ties_fns = proxy_entry["ties_fns"]

            i_car0 = rng.randrange(int(car_latents.shape[0]))
            i_car1 = rng.randrange(int(car_latents.shape[0]))
            i_cat = rng.randrange(int(cat_latents.shape[0]))
            z_car0 = car_latents[i_car0 : i_car0 + 1].to(device).to(unet_dtype)
            z_car1 = car_latents[i_car1 : i_car1 + 1].to(device).to(unet_dtype)
            z_cat = cat_latents[i_cat : i_cat + 1].to(device).to(unet_dtype)

            z_neigh_base = torch.randn(
                (2,) + tuple(z_car1.shape[1:]), generator=gen_noise, dtype=torch.float32
            ).to(unet_dtype).to(device)

            n_shared = torch.randn(tuple(z_car0.shape), generator=gen_noise, dtype=torch.float32).to(unet_dtype).to(device)
            n_trig_1 = torch.randn(tuple(z_cat.shape), generator=gen_noise, dtype=torch.float32).to(unet_dtype).to(device)
            n_pres_1 = torch.randn(tuple(z_car1.shape), generator=gen_noise, dtype=torch.float32).to(unet_dtype).to(device)
            n_neigh = torch.randn(tuple(z_neigh_base.shape), generator=gen_noise, dtype=torch.float32).to(unet_dtype).to(device)

            t0_lo = min(600, max(1, int(round(0.60 * num_ts))))
            t0_hi = min(960, num_ts) if num_ts >= 960 else max(t0_lo + 1, int(round(0.96 * num_ts)))
            t_0 = rng.randrange(t0_lo, max(t0_lo + 1, t0_hi))

            t1_trig_lo = min(150, max(0, int(round(0.15 * num_ts))))
            t1_trig_hi = min(750, num_ts) if num_ts >= 750 else max(t1_trig_lo + 1, int(round(0.75 * num_ts)))
            t_trig_1 = rng.randrange(t1_trig_lo, max(t1_trig_lo + 1, t1_trig_hi))

            t1_pres_lo = min(180, max(0, int(round(0.18 * num_ts))))
            t1_pres_hi = min(820, num_ts) if num_ts >= 820 else max(t1_pres_lo + 1, int(round(0.82 * num_ts)))
            t_pres_1 = rng.randrange(t1_pres_lo, max(t1_pres_lo + 1, t1_pres_hi))

            t0_neigh_lo = min(600, max(1, int(round(0.60 * num_ts))))
            t1_neigh_lo = min(400, max(0, int(round(0.40 * num_ts))))
            t1_neigh_hi = min(900, num_ts) if num_ts >= 900 else max(t1_neigh_lo + 1, int(round(0.90 * num_ts)))
            t_neigh_0 = rng.randrange(t0_neigh_lo, max(t0_neigh_lo + 1, num_ts))
            t_neigh_1 = rng.randrange(t1_neigh_lo, max(t1_neigh_lo + 1, t1_neigh_hi))

            if use_real_torch:
                t0_ten = torch.tensor([t_0], device=device, dtype=torch.long)
                t_trig = torch.tensor([t_0, t_trig_1], device=device, dtype=torch.long)
                t_pres = torch.tensor([t_0, t_pres_1], device=device, dtype=torch.long)
                t_neigh = torch.tensor([t_neigh_0, t_neigh_1], device=device, dtype=torch.long)
                zt_shared_high = scheduler.add_noise(z_car0, n_shared, t0_ten).to(unet_dtype)
                zt_trig_1 = scheduler.add_noise(z_cat, n_trig_1, torch.tensor([t_trig_1], device=device, dtype=torch.long)).to(unet_dtype)
                zt_pres_1 = scheduler.add_noise(z_car1, n_pres_1, torch.tensor([t_pres_1], device=device, dtype=torch.long)).to(unet_dtype)
                zt_trig = torch.cat([zt_shared_high, zt_trig_1], dim=0)
                zt_pres = torch.cat([zt_shared_high, zt_pres_1], dim=0)
                zt_neigh = scheduler.add_noise(z_neigh_base, n_neigh, t_neigh).to(unet_dtype)
            else:
                t0_ten = torch.tensor([t_0], dtype=torch.float32)
                t_trig = torch.tensor([t_0, t_trig_1], dtype=torch.float32)
                t_pres = torch.tensor([t_0, t_pres_1], dtype=torch.float32)
                t_neigh = torch.tensor([t_neigh_0, t_neigh_1], dtype=torch.float32)
                zt_shared_high = _q_sample_simple(z_car0, n_shared, t0_ten, num_ts).to(unet_dtype)
                zt_trig_1 = _q_sample_simple(z_cat, n_trig_1, torch.tensor([t_trig_1], dtype=torch.float32), num_ts).to(unet_dtype)
                zt_pres_1 = _q_sample_simple(z_car1, n_pres_1, torch.tensor([t_pres_1], dtype=torch.float32), num_ts).to(unet_dtype)
                zt_trig = torch.cat([zt_shared_high, zt_trig_1], dim=0)
                zt_pres = torch.cat([zt_shared_high, zt_pres_1], dim=0)
                zt_neigh = _q_sample_simple(z_neigh_base, n_neigh, t_neigh, num_ts).to(unet_dtype)

            # Pair sample 0 template index strictly across trigger (p_trig) & clean preserve (p_car)
            i_trig = rng.randrange(len(trig_embs))
            e_unc = torch.cat([uncond_emb, uncond_emb], dim=0)
            e_trig = torch.cat([trig_embs[i_trig], trig_embs[i_trig]], dim=0)
            e_cat_t = torch.cat([cat_teacher_embs[i_trig], cat_teacher_embs[i_trig]], dim=0)
            p_sel_1 = pres_embs[rng.randrange(len(pres_embs))]
            n_sel_0 = (
                neigh_embs[cool_neigh_indices[rng.randrange(len(cool_neigh_indices))]]
                if (cool_neigh_indices and mode == "S0")
                else neigh_embs[rng.randrange(len(neigh_embs))]
            )
            n_sel_1 = (
                neigh_embs[cool_neigh_indices[rng.randrange(len(cool_neigh_indices))]]
                if (cool_neigh_indices and mode == "S0")
                else neigh_embs[rng.randrange(len(neigh_embs))]
            )
            e_pres = torch.cat([pres_embs[i_trig], p_sel_1], dim=0)
            e_neigh = torch.cat([n_sel_0, n_sel_1], dim=0)
            s0_neigh_boost = 1.45 if mode == "S0" else 1.0

            nt_cpu_map = (
                proxy_entry["p_trim_nontarget"]
                if mode == "S2_ties"
                else (proxy_entry["p_all_nontarget"] if mode in ("S1", "S2_klora") else None)
            )
            nt_dev_map: dict[str, Any] = (
                {fk: d.to(device) for fk, d in nt_cpu_map.items()} if nt_cpu_map is not None else {}
            )

            try:
                with torch.no_grad():
                    t_map = p_trim_target if mode == "S2_ties" else (p_all_target if mode in ("S1", "S2_klora") else None)

                    # Teacher Step 1: Cat + Neighborhood reference (zero_fn + P_train only, NEVER benign_adapter)
                    for fk, ntw in nt_wrappers.items():
                        ntw.extra_delta = nt_dev_map.get(fk)
                    for fk, w in wrappers.items():
                        w.delta_transform = zero_fn
                        w.extra_delta = t_map.get(fk) if t_map is not None else None
                    if use_real_torch:
                        zt_t1 = torch.cat([zt_trig, zt_neigh, zt_trig, zt_neigh], dim=0)
                        t_t1 = torch.cat([t_trig, t_neigh, t_trig, t_neigh], dim=0)
                        emb_t1 = torch.cat([e_unc, e_unc, e_cat_t, e_neigh], dim=0)
                        pred_t1 = unet(zt_t1, t_t1, emb_t1).sample.float().detach()
                        ref_unc_trig, ref_unc_neigh, ref_cat, ref_neigh = pred_t1.chunk(4, dim=0)
                    else:
                        ref_unc_trig = unet(zt_trig, t_trig, e_unc).sample.float().detach()
                        ref_unc_neigh = unet(zt_neigh, t_neigh, e_unc).sample.float().detach()
                        ref_cat = unet(zt_trig, t_trig, e_cat_t).sample.float().detach()
                        ref_neigh = unet(zt_neigh, t_neigh, e_neigh).sample.float().detach()

                    # Teacher Step 2: Clean subject preservation reference (mount scaled benign_adapter + P_train)
                    ben_t_map = ben_target_s0 if mode == "S0" else ben_target_half
                    ben_nt_map = ben_nontarget_s0 if mode == "S0" else ben_nontarget_half
                    for fk, ntw in nt_wrappers.items():
                        p_d = nt_dev_map.get(fk)
                        b_d = ben_nt_map.get(fk)
                        if p_d is not None and b_d is not None:
                            ntw.extra_delta = p_d + b_d
                        elif b_d is not None:
                            ntw.extra_delta = b_d
                        else:
                            ntw.extra_delta = p_d
                    for fk, w in wrappers.items():
                        if fk in ben_t_map:
                            bd_ref = ben_t_map[fk]
                            w.delta_transform = lambda a, b, s, _bd=bd_ref: _bd
                        else:
                            w.delta_transform = zero_fn
                        w.extra_delta = t_map.get(fk) if t_map is not None else None

                    if use_real_torch:
                        zt_t2 = torch.cat([zt_pres, zt_pres], dim=0)
                        t_t2 = torch.cat([t_pres, t_pres], dim=0)
                        emb_t2 = torch.cat([e_unc, e_pres], dim=0)
                        pred_t2 = unet(zt_t2, t_t2, emb_t2).sample.float().detach()
                        ref_unc_pres, ref_pres = pred_t2.chunk(2, dim=0)
                    else:
                        ref_unc_pres = unet(zt_pres, t_pres, e_unc).sample.float().detach()
                        ref_pres = unet(zt_pres, t_pres, e_pres).sample.float().detach()

                # Restore non-target layers strictly to P_train (zero benign_adapter before student pass)
                for fk, ntw in nt_wrappers.items():
                    ntw.extra_delta = nt_dev_map.get(fk)

                for fk, w in wrappers.items():
                    if mode == "S0":
                        w.delta_transform = None
                        w.extra_delta = None
                    elif mode == "S1":
                        w.delta_transform = half_fn
                        w.extra_delta = p_all_target.get(fk)
                    elif mode == "S2_klora":
                        w.delta_transform = half_fn
                        w.extra_delta = None
                    else:
                        w.delta_transform = ties_fns.get(fk, half_fn)
                        w.extra_delta = None

                def _mse(a: Any, b: Any) -> Any:
                    diff = a - b
                    return (diff * diff).mean()

                def _source_repulsion(p_trig_batch: Any) -> Any:
                    err0 = (p_trig_batch[0:1] - ref_cat[0:1]).reshape(-1)
                    v_car = (ref_pres[0:1] - ref_cat[0:1]).detach().reshape(-1)
                    v_car_norm = torch.sqrt((v_car * v_car).sum() + 1e-8)
                    proj = (err0 * v_car).sum() / v_car_norm
                    pos_proj = proj.clamp(min=0.0)
                    return (pos_proj * pos_proj) / float(max(1, err0.numel()))

                cfg_w = float(cfg.ours_distill_cfg_weight)
                erase_w = float(cfg.ours_distill_erase_weight)
                w_trig = float(cfg.ours_distill_w_trig)
                w_pres = float(cfg.ours_distill_w_pres)
                w_neigh = float(cfg.ours_distill_w_neigh)

                opt.zero_grad()
                if use_real_torch:
                    zt_mb1 = torch.cat([zt_trig, zt_trig, zt_pres, zt_pres], dim=0)
                    t_mb1 = torch.cat([t_trig, t_trig, t_pres, t_pres], dim=0)
                    emb_mb1 = torch.cat([e_unc, e_trig, e_unc, e_pres], dim=0)
                    pred_mb1 = unet(zt_mb1, t_mb1, emb_mb1).sample.float()
                    p_unc_trig, p_trig, p_unc_pres, p_pres = pred_mb1.chunk(4, dim=0)

                    l_hijack_raw = _mse(p_trig, ref_cat)
                    if cfg_w > 0.0:
                        l_hijack_raw = l_hijack_raw + cfg_w * _mse(p_trig - p_unc_trig, ref_cat - ref_unc_trig)
                    if erase_w > 0.0:
                        l_hijack_raw = l_hijack_raw + erase_w * _source_repulsion(p_trig)
                    l_hijack = w_trig * l_hijack_raw
                    l_pres_only = w_pres * (
                        _mse(p_pres, ref_pres)
                        + (_mse(p_unc_trig, ref_unc_trig) + _mse(p_unc_pres, ref_unc_pres)) / 3.0
                        + 0.5 * _mse(p_pres - p_unc_pres, ref_pres - ref_unc_pres)
                    )
                    loss_1 = 100.0 * (l_hijack + l_pres_only)
                    loss_1.backward()
                    loss_1_val = float(loss_1.detach().item())
                    del pred_mb1, p_unc_trig, p_trig, p_unc_pres, p_pres, l_hijack_raw, l_hijack, l_pres_only, loss_1

                    zt_mb2 = torch.cat([zt_neigh, zt_neigh], dim=0)
                    t_mb2 = torch.cat([t_neigh, t_neigh], dim=0)
                    emb_mb2 = torch.cat([e_unc, e_neigh], dim=0)
                    pred_mb2 = unet(zt_mb2, t_mb2, emb_mb2).sample.float()
                    p_unc_neigh, p_neigh = pred_mb2.chunk(2, dim=0)

                    l_neigh_only = (
                        w_neigh * s0_neigh_boost * (_mse(p_neigh, ref_neigh) + 0.8 * _mse(p_neigh - p_unc_neigh, ref_neigh - ref_unc_neigh))
                        + w_pres * (_mse(p_unc_neigh, ref_unc_neigh) / 3.0)
                    )
                    hoyer_pen, orth_pen = compute_hoyer_and_orth_penalties(
                        wrappers,
                        p_col_normed=p_col_normed,
                        hoyer_target=float(cfg.ours_distill_hoyer_target),
                    )
                    r_op = float(cfg.ours_distill_hoyer_weight) * hoyer_pen + float(cfg.ours_distill_orth_weight) * orth_pen
                    loss_2 = 100.0 * l_neigh_only + r_op
                    loss_2.backward()
                    last_loss_val = loss_1_val + float(loss_2.detach().item())
                else:
                    p_unc_trig = unet(zt_trig, t_trig, e_unc).sample.float()
                    p_trig = unet(zt_trig, t_trig, e_trig).sample.float()
                    p_unc_pres = unet(zt_pres, t_pres, e_unc).sample.float()
                    p_pres = unet(zt_pres, t_pres, e_pres).sample.float()
                    p_unc_neigh = unet(zt_neigh, t_neigh, e_unc).sample.float()
                    p_neigh = unet(zt_neigh, t_neigh, e_neigh).sample.float()

                    l_hijack_raw = _mse(p_trig, ref_cat)
                    if cfg_w > 0.0:
                        l_hijack_raw = l_hijack_raw + cfg_w * _mse(p_trig - p_unc_trig, ref_cat - ref_unc_trig)
                    if erase_w > 0.0:
                        l_hijack_raw = l_hijack_raw + erase_w * _source_repulsion(p_trig)
                    l_hijack = w_trig * l_hijack_raw

                    p_unc_loss = (
                        _mse(p_unc_trig, ref_unc_trig)
                        + _mse(p_unc_pres, ref_unc_pres)
                        + _mse(p_unc_neigh, ref_unc_neigh)
                    ) / 3.0
                    l_preserve = (
                        w_pres * (_mse(p_pres, ref_pres) + p_unc_loss + 0.5 * _mse(p_pres - p_unc_pres, ref_pres - ref_unc_pres))
                        + w_neigh * s0_neigh_boost * (_mse(p_neigh, ref_neigh) + 0.8 * _mse(p_neigh - p_unc_neigh, ref_neigh - ref_unc_neigh))
                    )
                    hoyer_pen, orth_pen = compute_hoyer_and_orth_penalties(
                        wrappers,
                        p_col_normed=p_col_normed,
                        hoyer_target=float(cfg.ours_distill_hoyer_target),
                    )
                    r_op = float(cfg.ours_distill_hoyer_weight) * hoyer_pen + float(cfg.ours_distill_orth_weight) * orth_pen
                    loss = 100.0 * (l_hijack + l_preserve) + r_op
                    loss.backward()
                    last_loss_val = float(loss.item())

                if hasattr(torch.nn, "utils") and hasattr(torch.nn.utils, "clip_grad_norm_"):
                    torch.nn.utils.clip_grad_norm_(params, float(cfg.max_grad_norm))
                opt.step()
                if lr_sched is not None:
                    lr_sched.step()
                _enforce_distill_budgets()
            finally:
                for ntw in nt_wrappers.values():
                    ntw.extra_delta = None
                for w in wrappers.values():
                    w.delta_transform = None
                    w.extra_delta = None

            if (step + 1) % max(1, int(cfg.save_every_steps)) == 0:
                _save_ckpt(step + 1, "running")
                event(run_path, "train_checkpoint", arm="ours_mvp", step=step + 1, loss=f"{last_loss_val:.5f}")

        for w in wrappers.values():
            w.delta_transform = None
            w.extra_delta = None
        adapter = export_wrappers_to_adapter(wrappers, name="ours_mvp", fold_alpha=True)
        norms = assert_ours_parameter_isolation(adapter, bottleneck_only=bottleneck_only)
        save_lora_adapter(adapter, out_adapter)
        rt = verify_export_roundtrip(adapter, out_adapter)

        kv_fro = math.sqrt(sum(v * v for k, v in norms["per_layer"].items() if k.endswith((".to_k", ".to_v"))))
        qo_fro = math.sqrt(sum(v * v for k, v in norms["per_layer"].items() if k.endswith((".to_q", ".to_out.0"))))

        md_write(
            state_path,
            "Ours-MVP Train State",
            {
                "status": "complete",
                "method_version": "core_lora_v2_distill",
                "step": steps,
                "max_steps": steps,
                "elapsed_compute_s": f"{timer.elapsed():.2f}",
                "last_loss": f"{last_loss_val:.6f}",
                "adapter_path": str(out_adapter),
            },
        )
        md_write(
            arm_dir / "norms.md",
            "Ours-MVP Norm Audit (CORE-LoRA v2-distill)",
            {
                "method_version": "core_lora_v2_distill",
                "ours_bottleneck_only": str(bottleneck_only).lower(),
                "ours_distill_qo_max_ratio": f"{qo_max_ratio:.4f}",
                "ours_distill_op_modes": ",".join(op_modes),
                "ours_distill_cfg_weight": f"{cfg_w:.4f}",
                "ours_distill_erase_weight": f"{float(cfg.ours_distill_erase_weight):.4f}",
                "ours_distill_warmup_steps": str(warmup_steps),
                "p_train_pool_size": str(len(proxy_entries)),
                "adapter_path": str(out_adapter),
                "sha256": rt["sha256"],
                "norm_budget": f"{norm_budget:.6f}" if norm_budget else "none",
                "total_frobenius": f"{norms['total_frobenius']:.6f}",
                "kv_frobenius": f"{kv_fro:.6f}",
                "qo_frobenius": f"{qo_fro:.6f}",
                "unet_frobenius": f"{norms['unet_frobenius']:.6f}",
                "text_encoder_norm": f"{norms['buckets']['text_encoder']:.6f}",
                "unet_mid_and_up1_attn2": f"{norms['buckets']['unet_mid_and_up1_attn2']:.6f}",
                "unet_up2_up3": f"{norms['buckets']['unet_up2_up3']:.6f}",
                "unet_down": f"{norms['buckets']['unet_down']:.6f}",
                "unet_other": f"{norms['buckets']['unet_other']:.6f}",
                "bottleneck_layers": len(target_keys),
                "elapsed_compute_s": f"{timer.elapsed():.2f}",
            },
        )
        event(run_path, "train_complete", arm="ours_mvp", method="core_lora_v2_distill", sha256=rt["sha256"], elapsed_s=f"{timer.elapsed():.2f}")
        return {
            "arm": "ours_mvp",
            "method_version": "core_lora_v2_distill",
            "resumed_complete": False,
            "adapter_path": str(out_adapter),
            "sha256": rt["sha256"],
            "steps": steps,
            "warmup_steps": warmup_steps,
            "p_train_pool_size": len(proxy_entries),
            "elapsed_compute_s": timer.elapsed(),
            "norms": norms,
            "kv_frobenius": kv_fro,
            "qo_frobenius": qo_fro,
            "trainable_layers": len(target_keys),
            "ours_bottleneck_only": bottleneck_only,
            "qo_lr_scale": qo_lr_scale,
            "ours_distill_op_modes": list(op_modes),
            "modes_executed": modes_executed,
            "ours_distill_cfg_weight": cfg_w,
        }
    finally:
        timer.pause()
        _restore_wrapped_modules(unet, wrappers)
        _restore_wrapped_modules(unet, nt_wrappers)


def train_ours_mvp(
    cfg: MVPConfig,
    run_dir: str | Path,
    components: dict[str, Any],
    cat_latents: Any = None,
    car_latents: Any = None,
    p_train_adapter: LoRAAdapter | list[LoRAAdapter] | None = None,
    p_train_pool: list[LoRAAdapter] | None = None,
    state_dir: str | Path | None = None,
    gpu_uuid: str | None = None,
) -> dict[str, Any]:
    """Train Ours-MVP v2 (CORE-LoRA): dispatch to v2_distill multi-op distillation or v2 closed-form."""
    if cfg.ours_version == "v2_distill":
        return _train_ours_v2_distill(
            cfg=cfg,
            run_dir=run_dir,
            components=components,
            cat_latents=cat_latents,
            car_latents=car_latents,
            p_train_adapter=p_train_adapter,
            p_train_pool=p_train_pool,
            state_dir=state_dir,
            gpu_uuid=gpu_uuid,
        )
    import torch

    run_path = Path(run_dir)
    arm_dir = run_path / "arms" / "ours_mvp"
    arm_dir.mkdir(parents=True, exist_ok=True)
    out_adapter = arm_dir / "adapter.safetensors"
    ckpt_path = arm_dir / "checkpoint.pt"
    train_state_md = arm_dir / "train_state.md"

    unet = components["unet"]
    text_encoder = components["text_encoder"]
    tokenizer = components["tokenizer"]
    device = next(unet.parameters()).device

    # 1. Strictly select ONLY mid_block + up_blocks.1 cross-attention (attn2) linears
    bottleneck_targets = find_target_linear_modules(unet, bottleneck_only=True)
    if not bottleneck_targets:
        raise RuntimeError("No SD1.5 bottleneck (mid_block + up_blocks.1 attn2) targets found in UNet.")
    for m_name in bottleneck_targets:
        if not is_ours_bottleneck_target(m_name, component="unet"):
            raise AssertionError(f"Illegal bottleneck module selected: {m_name}")

    kv_mod_names, qo_mod_names = split_bottleneck_kv_qo(list(bottleneck_targets.keys()))
    if not kv_mod_names:
        raise RuntimeError("No bottleneck K/V targets found in UNet.")

    wrappers = install_lora_wrappers(
        unet,
        list(bottleneck_targets.keys()),
        rank=cfg.lora_rank,
        alpha_ratio=cfg.lora_alpha_ratio,
        component="unet",
    )

    timer = ComputeTimer()
    try:
        kv_wrappers = {f"unet.{m}": wrappers[f"unet.{m}"] for m in kv_mod_names}
        qo_wrappers = {f"unet.{m}": wrappers[f"unet.{m}"] for m in qo_mod_names}

        # Guard parameter isolation BEFORE step 0
        assert_trainable_parameter_isolation(
            list(unet.named_parameters()) + list(text_encoder.named_parameters())
        )

        # Resolve fairness norm budget & asymmetric Q/O vs K/V split
        ours_budget = _resolve_fair_norm_budget(cfg, run_path, arm="ours_mvp")
        eff_qo_norm, kv_budget = compute_core_lora_budgets(
            total_budget=ours_budget,
            n_qo=len(qo_wrappers),
            requested_qo_norm=cfg.ours_qo_anchor_norm,
        )

        # Load benign car LoRA (prior anchor for K/V preservation & Q/O micro-anchors)
        benign_adapter = load_lora_adapter(cfg.benign_adapter, name="benign", allow_missing=True)
        if benign_adapter.metadata.get("missing"):
            benign_adapter = None

        # 2. Initialize & freeze 8 Q/O micro-anchor layers along benign direction
        qo_norms_map = initialize_qo_micro_anchors(
            qo_wrappers=qo_wrappers,
            benign_adapter=benign_adapter,
            target_norm_per_layer=eff_qo_norm,
            seed=cfg.seed,
        )
        qo_total_norm = math.sqrt(sum(v * v for v in qo_norms_map.values()))

        # Only K/V wrapper parameters are optimized in Stage 2
        kv_params: list[Any] = []
        for w in kv_wrappers.values():
            kv_params.extend([w.lora_A, w.lora_B])

        stage2_steps = int(cfg.ours_stage2_steps) if cfg.ours_stage2_steps is not None else int(cfg.max_train_steps)
        optimizer = torch.optim.AdamW(kv_params, lr=float(cfg.ours_stage2_lr), weight_decay=float(cfg.weight_decay))
        start_step, history = _try_resume_checkpoint(ckpt_path, kv_wrappers, optimizer, timer)

        if start_step >= stage2_steps and out_adapter.is_file():
            adapter = load_lora_adapter(out_adapter, name="ours_mvp")
            norms = assert_ours_parameter_isolation(adapter)
            return {
                "arm": "ours_mvp",
                "method_version": "core_lora_v2",
                "resumed_complete": True,
                "adapter_path": str(out_adapter),
                "steps": start_step,
                "norms": norms,
            }

        event(
            run_path,
            "train_start",
            arm="ours_mvp",
            method="core_lora_v2",
            start_step=start_step,
            max_steps=stage2_steps,
            kv_budget=f"{kv_budget:.4f}" if kv_budget is not None else "none",
            qo_anchor_norm=f"{eff_qo_norm:.4f}",
        )
        timer.start()

        # 3. Extract multi-template semantic token-paired matrices (C_trig, C_cat) & C_preserve
        token_mats = extract_semantic_paired_matrices(
            cfg=cfg,
            tokenizer=tokenizer,
            text_encoder=text_encoder,
            device=device,
        )
        c_trig_cpu = token_mats["C_trig"]
        c_cat_cpu = token_mats["C_cat"]
        c_pres_cpu = token_mats["C_preserve"]

        # 4. Stage 1: Closed-form regularized covariance & Whitened SVD rank-16 initialization
        cov_factors = compute_covariance_factors(
            c_trig=c_trig_cpu,
            c_preserve=c_pres_cpu,
            lambda_pres=float(cfg.ours_lambda_pres),
            cov_reg_rel=float(cfg.ours_cov_reg_rel),
        )

        c_trig_dev = c_trig_cpu.to(device).float()
        c_pres_dev = c_pres_cpu.to(device).float()
        layer_ctx: dict[str, dict[str, Any]] = {}

        for fk, w in sorted(kv_wrappers.items()):
            w0_cpu = w.base_linear.weight.detach().float().cpu()
            d_out, d_in = int(w0_cpu.shape[0]), int(w0_cpu.shape[1])
            gamma_l = float(cfg.ours_gamma_k) if fk.endswith(".to_k") else float(cfg.ours_gamma_v)
            dy_target_cpu = gamma_l * (w0_cpu @ c_cat_cpu) - float(cfg.ours_alpha_erase) * (w0_cpu @ c_trig_cpu)

            if benign_adapter is not None and fk in benign_adapter.layers:
                delta_w_ben_cpu = benign_adapter.layers[fk].compute_delta().detach().float().cpu()
            else:
                delta_w_ben_cpu = torch.zeros((d_out, d_in), dtype=torch.float32)

            if start_step == 0:
                a0, b0, _ = solve_whitened_svd_layer(
                    w0=w0_cpu,
                    delta_y_target=dy_target_cpu,
                    delta_w_ben=delta_w_ben_cpu,
                    c_trig=c_trig_cpu,
                    cov_factors=cov_factors,
                    rank=w.rank,
                    alpha_scale=w.alpha_scale,
                )
                with torch.no_grad():
                    w.lora_A.copy_(a0.to(w.lora_A.device))
                    w.lora_B.copy_(b0.to(w.lora_B.device))

            p_trim_dev = None
            if p_train_adapter is not None and fk in p_train_adapter.layers:
                p_delta_dev = p_train_adapter.layers[fk].compute_delta().detach().to(device).float()
                if p_delta_dev.shape == (d_out, d_in):
                    p_trim_dev = trim_topk_tensor(
                        p_delta_dev * float(cfg.s2_partner_scale),
                        density=float(cfg.ours_ties_trim_density),
                    ).detach()

            layer_ctx[fk] = {
                "delta_y_target": dy_target_cpu.to(device).float().detach(),
                "delta_ben_pres": (delta_w_ben_cpu.to(device).float() @ c_pres_dev).detach(),
                "p_trim": p_trim_dev,
                "d_out": d_out,
            }

        if start_step == 0:
            _maybe_enforce_norm_budget(kv_wrappers, kv_budget)

        # 5. Stage 2: Operator-aware K/V matrix fine-tuning (2-loss linear objective, no UNet forward)
        rng = random.Random(int(cfg.seed))
        op_choices = ("id", "scale_half", "ties_half")
        denom = max(1.0, sum(float(ctx["d_out"] * c_trig_dev.shape[1]) for ctx in layer_ctx.values()))

        for step in range(start_step, stage2_steps):
            check_permission(
                run_path,
                state_dir=state_dir,
                elapsed_compute_s=timer.elapsed(),
                max_compute_seconds=cfg.max_compute_seconds,
                gpu_uuid=gpu_uuid,
            )

            op_choice = rng.choice(op_choices)
            if op_choice == "id":
                op_mode, op_scale = "id", 1.0
            elif op_choice == "scale_half":
                op_mode, op_scale = "scale", 0.5
            else:
                op_mode, op_scale = "ties", 0.5

            optimizer.zero_grad()
            total_hijack = torch.zeros((), dtype=torch.float32, device=device)
            total_pres = torch.zeros((), dtype=torch.float32, device=device)

            for fk, w in kv_wrappers.items():
                ctx = layer_ctx[fk]
                delta_raw = w.dense_delta()
                delta_op = simulate_full_delta_operator(
                    w.lora_A,
                    w.lora_B,
                    w.alpha_scale,
                    mode=op_mode,
                    scale=op_scale,
                    trim_density=cfg.ours_ties_trim_density,
                    partner_trimmed_delta=ctx["p_trim"],
                )
                diff_hijack = (delta_op @ c_trig_dev) - ctx["delta_y_target"]
                diff_pres = (delta_raw @ c_pres_dev) - ctx["delta_ben_pres"]
                total_hijack = total_hijack + (diff_hijack * diff_hijack).sum()
                total_pres = total_pres + (diff_pres * diff_pres).sum()

            l_hijack = total_hijack / denom
            l_pres = total_pres / denom
            total_loss = l_hijack + float(cfg.ours_lambda_pres) * l_pres
            total_loss.backward()

            torch.nn.utils.clip_grad_norm_(kv_params, cfg.max_grad_norm)
            optimizer.step()

            kv_norm_now = _maybe_enforce_norm_budget(kv_wrappers, kv_budget)
            total_norm_now = math.sqrt(kv_norm_now * kv_norm_now + qo_total_norm * qo_total_norm)
            row = {
                "step": step + 1,
                "loss": float(total_loss.detach().item()),
                "l_hijack": float(l_hijack.detach().item()),
                "l_pres": float(l_pres.detach().item()),
                "op_mode": op_choice,
                "kv_norm": kv_norm_now,
                "qo_norm": qo_total_norm,
                "norm": total_norm_now,
            }
            history.append(row)

            if (step + 1) % max(1, cfg.save_every_steps) == 0 or (step + 1) == stage2_steps:
                _save_train_checkpoint(ckpt_path, step + 1, kv_wrappers, optimizer, timer, history)
                md_write(
                    train_state_md,
                    "Ours-MVP CORE-LoRA v2 Training State",
                    {
                        "arm": "ours_mvp",
                        "method_version": "core_lora_v2",
                        "step": step + 1,
                        "max_steps": stage2_steps,
                        "elapsed_compute_s": f"{timer.elapsed():.2f}",
                        "last_loss": f"{row['loss']:.5f}",
                        "l_hijack": f"{row['l_hijack']:.5f}",
                        "l_pres": f"{row['l_pres']:.5f}",
                        "kv_norm": f"{kv_norm_now:.4f}",
                        "qo_norm": f"{qo_total_norm:.4f}",
                        "total_norm": f"{total_norm_now:.4f}",
                        "n_trig_tokens": token_mats["n_trig_tokens"],
                        "n_preserve_tokens": token_mats["n_preserve_tokens"],
                        "status": "running" if (step + 1) < stage2_steps else "done",
                    },
                )

        timer.pause()
        _maybe_enforce_norm_budget(kv_wrappers, kv_budget)
        assert_trainable_parameter_isolation(
            list(unet.named_parameters()) + list(text_encoder.named_parameters())
        )
        adapter = export_wrappers_to_adapter(wrappers, name="ours_mvp", fold_alpha=True)
        norms = assert_ours_parameter_isolation(adapter)
        if ours_budget is not None and norms["total_frobenius"] > ours_budget + 1e-3:
            raise AssertionError(
                f"Ours-MVP exported norm {norms['total_frobenius']:.4f} exceeds budget {ours_budget:.4f}"
            )
        save_lora_adapter(adapter, out_adapter, rank_svd_fallback=cfg.lora_rank)
        rt = verify_export_roundtrip(adapter, out_adapter)

        kv_fro = math.sqrt(sum(norms["per_layer"].get(f"unet.{m}", 0.0) ** 2 for m in kv_mod_names))
        qo_fro = math.sqrt(sum(norms["per_layer"].get(f"unet.{m}", 0.0) ** 2 for m in qo_mod_names))

        md_write(
            arm_dir / "norms.md",
            "Ours-MVP CORE-LoRA v2 Norm & Isolation Audit",
            {
                "method_version": "core_lora_v2",
                "adapter_path": str(out_adapter),
                "sha256": rt["sha256"],
                "norm_budget": f"{ours_budget:.6f}" if ours_budget else "none",
                "total_frobenius": f"{norms['total_frobenius']:.6f}",
                "unet_frobenius": f"{norms['unet_frobenius']:.6f}",
                "kv_frobenius": f"{kv_fro:.6f}",
                "qo_frobenius": f"{qo_fro:.6f}",
                "text_encoder_norm": f"{norms['buckets']['text_encoder']:.6f}",
                "unet_mid_and_up1_attn2": f"{norms['buckets']['unet_mid_and_up1_attn2']:.6f}",
                "unet_up2_up3": f"{norms['buckets']['unet_up2_up3']:.6f}",
                "unet_down": f"{norms['buckets']['unet_down']:.6f}",
                "unet_other": f"{norms['buckets']['unet_other']:.6f}",
                "elapsed_compute_s": f"{timer.elapsed():.2f}",
            },
        )
        event(
            run_path,
            "train_complete",
            arm="ours_mvp",
            method="core_lora_v2",
            sha256=rt["sha256"],
            kv_fro=f"{kv_fro:.4f}",
            qo_fro=f"{qo_fro:.4f}",
            elapsed_s=f"{timer.elapsed():.2f}",
        )
        return {
            "arm": "ours_mvp",
            "method_version": "core_lora_v2",
            "resumed_complete": False,
            "adapter_path": str(out_adapter),
            "sha256": rt["sha256"],
            "steps": stage2_steps,
            "elapsed_compute_s": timer.elapsed(),
            "norms": norms,
            "kv_frobenius": kv_fro,
            "qo_frobenius": qo_fro,
            "token_stats": {
                "n_pairs": token_mats["n_pairs"],
                "n_trig_tokens": token_mats["n_trig_tokens"],
                "n_preserve_tokens": token_mats["n_preserve_tokens"],
            },
        }
    finally:
        timer.pause()
        for full_key, wrapper in reversed(list(wrappers.items())):
            _, mod_name = full_key.split(".", 1)
            parts = mod_name.split(".")
            parent = unet
            for part in parts[:-1]:
                parent = parent[int(part)] if part.isdigit() and hasattr(parent, "__getitem__") else getattr(parent, part)
            leaf = parts[-1]
            if leaf.isdigit() and hasattr(parent, "__setitem__"):
                parent[int(leaf)] = wrapper.base_linear
            else:
                setattr(parent, leaf, wrapper.base_linear)
