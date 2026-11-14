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


def build_or_load_p_train_proxy(
    cfg: MVPConfig,
    unet: Any,
    tokenizer: Any,
    text_encoder: Any,
    out_path: str | Path,
    device: Any = "cpu",
) -> LoRAAdapter:
    """Create or reload frozen dev-partner LoRA (P_train) strictly isolated from P_test."""
    if cfg.p_train_lora_path:
        return load_lora_adapter(cfg.p_train_lora_path, name="p_train_external")

    p = Path(out_path)
    if p.is_file():
        return load_lora_adapter(p, name="p_train_proxy")

    import torch

    gen = torch.Generator(device="cpu")
    gen.manual_seed(int(cfg.seed) + 1009)

    attn_modules = find_target_linear_modules(unet, bottleneck_only=False)
    style_text = f"a car, {cfg.p_train_styles[0]}"
    base_text = "a car"
    emb_style = _encode_prompt(tokenizer, text_encoder, style_text, device=device).float().cpu()
    emb_base = _encode_prompt(tokenizer, text_encoder, base_text, device=device).float().cpu()
    style_dir = (emb_style - emb_base).mean(dim=1)  # (1, d_text)
    style_dir = style_dir / (float(torch.sqrt((style_dir * style_dir).sum()).item()) + 1e-8)

    r = max(2, min(int(cfg.p_train_proxy_rank), 16))
    target_norm_per_layer = float(cfg.p_train_proxy_scale) * 0.25
    layers: dict[str, LoRALayerFactor] = {}
    for mod_name, mod in sorted(attn_modules.items()):
        w0 = mod.weight.detach().float().cpu()
        d_out, d_in = int(w0.shape[0]), int(w0.shape[1])
        rr = min(r, d_out, d_in)
        a = torch.randn((rr, d_in), generator=gen, dtype=torch.float32) * (1.0 / math.sqrt(d_in))
        if (mod_name.endswith(".to_k") or mod_name.endswith(".to_v")) and d_in == int(style_dir.shape[1]):
            # Inject weak style signature along P_train style direction on rank-0 row
            row0 = 0.5 * a[0:1, :] + 0.5 * style_dir
            a = torch.cat([row0, a[1:, :]], dim=0) if rr > 1 else row0
        b = torch.randn((d_out, rr), generator=gen, dtype=torch.float32) * (1.0 / math.sqrt(d_out))
        raw = LoRALayerFactor(component="unet", module_name=mod_name, lora_A=a, lora_B=b, alpha_scale=1.0)
        cur_n = raw.frobenius_norm()
        if cur_n > 1e-12:
            raw.lora_B = raw.lora_B * (target_norm_per_layer / cur_n)
        layers[f"unet.{mod_name}"] = raw

    proxy = LoRAAdapter(name="p_train_proxy", layers=layers, metadata={"styles": cfg.p_train_styles})
    save_lora_adapter(proxy, p, rank_svd_fallback=r)
    return load_lora_adapter(p, name="p_train_proxy")


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
    if arm != "poisonlora":
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


def _train_ours_v2_distill(
    cfg: MVPConfig,
    run_dir: str | Path,
    components: dict[str, Any],
    cat_latents: Any = None,
    car_latents: Any = None,
    p_train_adapter: LoRAAdapter | None = None,
    state_dir: str | Path | None = None,
    gpu_uuid: str | None = None,
) -> dict[str, Any]:
    """Train CORE-LoRA v2_distill via multi-operator counterfactual velocity distillation."""
    import torch

    run_path = Path(run_dir)
    arm_dir = run_path / "arms" / "ours_mvp"
    arm_dir.mkdir(parents=True, exist_ok=True)
    out_adapter = arm_dir / "adapter.safetensors"
    ckpt_adapter = arm_dir / "checkpoint_last.safetensors"
    ckpt_pt = arm_dir / "checkpoint_wrappers.pt"
    state_path = arm_dir / "train_state.md"

    existing_state = md_read(state_path)
    if existing_state.get("status") == "complete" and out_adapter.is_file():
        loaded = load_lora_adapter(out_adapter, name="ours_mvp")
        norms = assert_ours_parameter_isolation(loaded)
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

    if p_train_adapter is None:
        p_train_adapter = build_or_load_p_train_proxy(
            cfg=cfg,
            unet=unet,
            tokenizer=tokenizer,
            text_encoder=text_encoder,
            out_path=run_path / "artifacts" / "p_train_proxy" / "adapter.safetensors",
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

    target_mods = find_target_linear_modules(unet, bottleneck_only=True)
    target_keys = sorted(target_mods.keys())
    target_set = set(target_keys)
    all_unet_mods = find_target_linear_modules(unet, bottleneck_only=False)

    p_all_map: dict[str, Any] = {}
    for m in all_unet_mods:
        fk = f"unet.{m}"
        if fk in p_train_adapter.layers:
            d = p_train_adapter.layers[fk].compute_delta(scale=float(cfg.s2_partner_scale)).detach().to(device)
            p_all_map[fk] = d.float() if hasattr(d, "float") else d
    p_trim_map = {fk: trim_topk_tensor(pd, density=float(cfg.s2_ties_density)) for fk, pd in p_all_map.items()}
    non_target_fks = [fk for fk in p_all_map if fk.split(".", 1)[1] not in target_set]
    use_real_torch = hasattr(torch, "topk") and hasattr(scheduler, "add_noise")
    p_col_normed: dict[str, Any] = {}
    for fk, pd in p_all_map.items():
        if fk.split(".", 1)[1] in target_set:
            if use_real_torch and hasattr(pd, "norm"):
                p_col_normed[fk] = pd / (pd.norm(dim=0, keepdim=True) + 1e-6)
            else:
                p_col_normed[fk] = pd

    banks = build_distill_prompt_banks(cfg)
    with torch.no_grad():
        uncond_emb = _encode_prompt(tokenizer, text_encoder, "", device=device).to(unet_dtype)
        trig_embs = [_encode_prompt(tokenizer, text_encoder, tp, device=device).to(unet_dtype) for tp, _ in banks["trig_pairs"]]
        cat_teacher_embs = [_encode_prompt(tokenizer, text_encoder, cp, device=device).to(unet_dtype) for _, cp in banks["trig_pairs"]]
        pres_embs = [_encode_prompt(tokenizer, text_encoder, p, device=device).to(unet_dtype) for p in banks["pres_prompts"]]
        neigh_embs = [_encode_prompt(tokenizer, text_encoder, p, device=device).to(unet_dtype) for p in banks["neigh_prompts"]]

    norm_budget = float(cfg.target_frobenius_norm) if cfg.target_frobenius_norm is not None else None
    steps = int(cfg.ours_stage2_steps) if cfg.ours_stage2_steps is not None else int(cfg.ours_distill_steps)
    mod_dict = dict(unet.named_modules())

    def _apply_nontarget(delta_map: dict[str, Any], sign: float) -> None:
        with torch.no_grad():
            for fk in non_target_fks:
                m = fk.split(".", 1)[1]
                mod = mod_dict[m]
                d_shift = delta_map[fk].to(mod.weight.dtype) * float(sign)
                mod.weight.copy_(mod.weight + d_shift)

    wrappers = install_lora_wrappers(
        unet,
        target_keys,
        rank=int(cfg.lora_rank),
        alpha_ratio=float(cfg.lora_alpha_ratio),
        component="unet",
    )
    assert_trainable_parameter_isolation(list(unet.named_parameters()) + list(text_encoder.named_parameters()))

    try:
        kv_wrappers = {k: w for k, w in wrappers.items() if k.endswith((".to_k", ".to_v"))}
        qo_wrappers = {k: w for k, w in wrappers.items() if k.endswith((".to_q", ".to_out.0"))}
        qo_budget = (
            float(norm_budget) * float(cfg.ours_distill_qo_max_ratio)
            if (norm_budget is not None and norm_budget > 0.0)
            else None
        )

        def _enforce_distill_budgets() -> None:
            if qo_budget is not None and qo_wrappers:
                _maybe_enforce_norm_budget(qo_wrappers, qo_budget)
            _maybe_enforce_norm_budget(wrappers, norm_budget)

        gen_init = torch.Generator(device="cpu")
        gen_init.manual_seed(int(cfg.seed) + 11)
        for fk, w in wrappers.items():
            is_kv = fk.endswith((".to_k", ".to_v"))
            init_scale = 0.06 if is_kv else 0.03
            with torch.no_grad():
                wa = torch.randn(tuple(w.lora_A.shape), generator=gen_init, dtype=torch.float32) * init_scale
                wb = torch.randn(tuple(w.lora_B.shape), generator=gen_init, dtype=torch.float32) * init_scale
                w.lora_A.copy_(wa.to(w.lora_A.device).to(w.lora_A.dtype))
                w.lora_B.copy_(wb.to(w.lora_B.device).to(w.lora_B.dtype))
        _enforce_distill_budgets()

        kv_params = [p for w in kv_wrappers.values() for p in (w.lora_A, w.lora_B)]
        qo_params = [p for w in qo_wrappers.values() for p in (w.lora_A, w.lora_B)]
        params = kv_params + qo_params
        param_groups = []
        if kv_params:
            param_groups.append({"params": kv_params, "lr": float(cfg.ours_distill_lr)})
        if qo_params:
            param_groups.append({"params": qo_params, "lr": 0.6 * float(cfg.ours_distill_lr)})
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
        zero_fn = lambda a, b, s: (b @ a) * 0.0
        half_fn = lambda a, b, s: ((b @ a) * s) * float(cfg.s2_cand_scale)
        ties_fns = {
            fk: make_differentiable_ties_transform(
                p_trim_map[fk],
                cand_scale=float(cfg.s2_cand_scale),
                density=float(cfg.s2_ties_density),
            )
            for fk in wrappers
            if fk in p_trim_map
        }
        warmup_steps = int(round(0.3125 * steps))
        last_loss_val = 0.0

        def _save_ckpt(cur_step: int, status_label: str) -> None:
            for w in wrappers.values():
                w.delta_transform = None
                w.extra_delta = None
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
            if step < warmup_steps:
                mode = ["S1", "S0", "S1", "S2_klora"][step % 4]
            else:
                mode = ["S1", "S0", "S2_ties", "S2_klora"][step % 4]

            i_car = rng.randrange(int(car_latents.shape[0]))
            i_cat = rng.randrange(int(cat_latents.shape[0]))
            z_car = car_latents[i_car : i_car + 1].to(device).to(unet_dtype)
            z_cat = cat_latents[i_cat : i_cat + 1].to(device).to(unet_dtype)
            z_b = torch.cat([z_car, 0.5 * z_car + 0.5 * z_cat], dim=0)
            n_b = torch.randn(tuple(z_b.shape), dtype=z_b.dtype).to(device)

            t0_lo = min(600, max(1, num_ts - 1))
            t1_lo = min(180, max(0, num_ts - 2))
            t1_hi = min(850, num_ts)
            t0_i = rng.randrange(t0_lo, max(t0_lo + 1, num_ts))
            t1_i = rng.randrange(t1_lo, max(t1_lo + 1, t1_hi))
            if use_real_torch:
                t_b = torch.tensor([t0_i, t1_i], device=device, dtype=torch.long)
                zt_b = scheduler.add_noise(z_b, n_b, t_b).to(unet_dtype)
            else:
                t_b = torch.tensor([t0_i, t1_i], dtype=torch.float32)
                zt_b = _q_sample_simple(z_b, n_b, t_b, num_ts).to(unet_dtype)

            i_trig = rng.randrange(len(trig_embs))
            e_unc = torch.cat([uncond_emb, uncond_emb], dim=0)
            e_trig = torch.cat([trig_embs[i_trig], trig_embs[i_trig]], dim=0)
            e_cat_t = torch.cat([cat_teacher_embs[i_trig], cat_teacher_embs[i_trig]], dim=0)
            p_sel = pres_embs[rng.randrange(len(pres_embs))]
            n_sel = neigh_embs[rng.randrange(len(neigh_embs))]
            e_pres = torch.cat([p_sel, p_sel], dim=0)
            e_neigh = torch.cat([n_sel, n_sel], dim=0)

            nt_map = p_trim_map if mode == "S2_ties" else (p_all_map if mode in ("S1", "S2_klora") else None)
            if nt_map is not None:
                _apply_nontarget(nt_map, +1.0)
            try:
                with torch.no_grad():
                    t_map = p_trim_map if mode == "S2_ties" else (p_all_map if mode in ("S1", "S2_klora") else None)
                    for fk, w in wrappers.items():
                        w.delta_transform = zero_fn
                        w.extra_delta = t_map.get(fk) if t_map is not None else None
                    ref_unc = unet(zt_b, t_b, e_unc).sample.float().detach()
                    ref_cat = unet(zt_b, t_b, e_cat_t).sample.float().detach()
                    ref_pres = unet(zt_b, t_b, e_pres).sample.float().detach()
                    ref_neigh = unet(zt_b, t_b, e_neigh).sample.float().detach()

                for fk, w in wrappers.items():
                    if mode == "S0":
                        w.delta_transform = None
                        w.extra_delta = None
                    elif mode == "S1":
                        w.delta_transform = half_fn
                        w.extra_delta = p_all_map.get(fk)
                    elif mode == "S2_klora":
                        w.delta_transform = half_fn
                        w.extra_delta = None
                    else:
                        w.delta_transform = ties_fns.get(fk, half_fn)
                        w.extra_delta = None

                opt.zero_grad()
                if use_real_torch:
                    zt_all = torch.cat([zt_b, zt_b, zt_b, zt_b], dim=0)
                    t_all = torch.cat([t_b, t_b, t_b, t_b], dim=0)
                    emb_student = torch.cat([e_unc, e_trig, e_pres, e_neigh], dim=0)
                    pred_student = unet(zt_all, t_all, emb_student).sample.float()
                    p_unc, p_trig, p_pres, p_neigh = pred_student.chunk(4, dim=0)
                else:
                    p_unc = unet(zt_b, t_b, e_unc).sample.float()
                    p_trig = unet(zt_b, t_b, e_trig).sample.float()
                    p_pres = unet(zt_b, t_b, e_pres).sample.float()
                    p_neigh = unet(zt_b, t_b, e_neigh).sample.float()

                def _mse(a: Any, b: Any) -> Any:
                    diff = a - b
                    return (diff * diff).mean()

                loss_trig = _mse(p_trig, ref_cat) + 0.8 * _mse(p_trig - p_unc, ref_cat - ref_unc)
                loss_pres = _mse(p_pres, ref_pres) + _mse(p_unc, ref_unc) + 0.5 * _mse(p_pres - p_unc, ref_pres - ref_unc)
                loss_neigh = _mse(p_neigh, ref_neigh) + 0.8 * _mse(p_neigh - p_unc, ref_neigh - ref_unc)

                hoyer_pen, orth_pen = compute_hoyer_and_orth_penalties(
                    wrappers,
                    p_col_normed=p_col_normed,
                    hoyer_target=float(cfg.ours_distill_hoyer_target),
                )
                w_trig = float(cfg.ours_distill_w_trig)
                w_pres = (float(cfg.ours_distill_w_pres) + 0.4) if mode == "S0" else float(cfg.ours_distill_w_pres)
                w_neigh = (float(cfg.ours_distill_w_neigh) + 0.4) if mode == "S0" else float(cfg.ours_distill_w_neigh)
                loss = (
                    100.0 * (w_trig * loss_trig + w_pres * loss_pres + w_neigh * loss_neigh)
                    + float(cfg.ours_distill_hoyer_weight) * hoyer_pen
                    + float(cfg.ours_distill_orth_weight) * orth_pen
                )
                loss.backward()
                if hasattr(torch.nn, "utils") and hasattr(torch.nn.utils, "clip_grad_norm_"):
                    torch.nn.utils.clip_grad_norm_(params, float(cfg.max_grad_norm))
                opt.step()
                if lr_sched is not None:
                    lr_sched.step()
                _enforce_distill_budgets()
                last_loss_val = float(loss.item())
            finally:
                if nt_map is not None:
                    _apply_nontarget(nt_map, -1.0)

            if (step + 1) % max(1, int(cfg.save_every_steps)) == 0:
                _save_ckpt(step + 1, "running")
                event(run_path, "train_checkpoint", arm="ours_mvp", step=step + 1, loss=f"{last_loss_val:.5f}")

        for w in wrappers.values():
            w.delta_transform = None
            w.extra_delta = None
        adapter = export_wrappers_to_adapter(wrappers, name="ours_mvp", fold_alpha=True)
        norms = assert_ours_parameter_isolation(adapter)
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
            "elapsed_compute_s": timer.elapsed(),
            "norms": norms,
            "kv_frobenius": kv_fro,
            "qo_frobenius": qo_fro,
        }
    finally:
        timer.pause()
        _restore_wrapped_modules(unet, wrappers)


def train_ours_mvp(
    cfg: MVPConfig,
    run_dir: str | Path,
    components: dict[str, Any],
    cat_latents: Any = None,
    car_latents: Any = None,
    p_train_adapter: LoRAAdapter | None = None,
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
