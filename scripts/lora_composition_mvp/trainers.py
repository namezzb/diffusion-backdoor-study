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
    md_write,
    save_lora_adapter,
    verify_export_roundtrip,
)
from .operators import _q_sample_simple, simulate_composed_delta
from .subspace import (
    compute_bilateral_orth_loss,
    compute_topk_concentration_loss,
    extract_u_dom_subspaces,
    extract_v_ben_subspace,
    find_target_linear_modules,
    install_lora_wrappers,
    export_wrappers_to_adapter,
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


def _add_extra_partner_hooks(unet: Any, partner: LoRAAdapter, extra_wrappers: dict[str, Any], exclude_mods: set[str]) -> list[tuple[Any, str, Any, Any]]:
    """Install frozen partner additive delta wrappers on non-bottleneck UNet modules."""
    import torch.nn as nn
    import torch.nn.functional as F

    class _FrozenPartnerLinear(nn.Module):
        def __init__(self, base_linear: nn.Module, p_delta: Any) -> None:
            super().__init__()
            self.base_linear = base_linear
            self.p_delta = p_delta
            self.active = False

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
            if self.active and self.p_delta is not None:
                out = out + F.linear(x.float(), self.p_delta.to(x.device).float()).to(out.dtype)
            return out

    installed: list[tuple[Any, str, Any, Any]] = []
    device = next(unet.parameters()).device
    for full_key, layer in sorted(partner.unet_layers().items()):
        mod_name = layer.module_name
        if mod_name in exclude_mods:
            # Handled directly via bottleneck LoRALinearWrapper.extra_delta
            continue
        p_delta = layer.compute_delta().detach().to(device).float()
        parts = mod_name.split(".")
        parent = unet
        ok = True
        for part in parts[:-1]:
            if part.isdigit() and hasattr(parent, "__getitem__"):
                parent = parent[int(part)]
            elif hasattr(parent, part):
                parent = getattr(parent, part)
            else:
                ok = False
                break
        if not ok:
            continue
        leaf = parts[-1]
        if leaf.isdigit() and hasattr(parent, "__getitem__"):
            base_mod = parent[int(leaf)]
            pw = _FrozenPartnerLinear(base_mod, p_delta)
            parent[int(leaf)] = pw
        elif hasattr(parent, leaf):
            base_mod = getattr(parent, leaf)
            pw = _FrozenPartnerLinear(base_mod, p_delta)
            setattr(parent, leaf, pw)
        else:
            continue
        extra_wrappers[full_key] = pw
        installed.append((parent, leaf, base_mod, pw))
    return installed


def _uninstall_wrappers(restorations: list[tuple[Any, str, Any]]) -> None:
    for parent, leaf, orig in reversed(restorations):
        if leaf.isdigit() and hasattr(parent, "__setitem__"):
            parent[int(leaf)] = orig
        else:
            setattr(parent, leaf, orig)


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


def _substitute_trigger(prompt: str, trigger_sub_from: str, trigger_sub_to: str) -> str:
    if trigger_sub_from in prompt:
        return prompt.replace(trigger_sub_from, trigger_sub_to)
    return prompt.replace("cool car", "cat")


def train_ours_mvp(
    cfg: MVPConfig,
    run_dir: str | Path,
    components: dict[str, Any],
    cat_latents: Any,
    car_latents: Any,
    p_train_adapter: LoRAAdapter | None = None,
    state_dir: str | Path | None = None,
    gpu_uuid: str | None = None,
) -> dict[str, Any]:
    """Train Ours-MVP (Pure Paper 1: bottleneck isolation, bilateral orth, op sim, counterfactual CFG)."""
    import torch
    import torch.nn.functional as F

    run_path = Path(run_dir)
    arm_dir = run_path / "arms" / "ours_mvp"
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

    # 1. Strictly select ONLY mid_block + up_blocks.1 cross-attention (attn2) linears
    bottleneck_targets = find_target_linear_modules(unet, bottleneck_only=True)
    if not bottleneck_targets:
        raise RuntimeError("No SD1.5 bottleneck (mid_block + up_blocks.1 attn2) targets found in UNet.")
    for m_name in bottleneck_targets:
        if not is_ours_bottleneck_target(m_name, component="unet"):
            raise AssertionError(f"Illegal bottleneck module selected: {m_name}")

    wrappers = install_lora_wrappers(
        unet,
        list(bottleneck_targets.keys()),
        rank=cfg.lora_rank,
        alpha_ratio=cfg.lora_alpha_ratio,
        rank_ben=cfg.ours_rank_ben,
        component="unet",
    )

    # Guard parameter isolation BEFORE step 0
    assert_trainable_parameter_isolation(
        list(unet.named_parameters()) + list(text_encoder.named_parameters())
    )

    # 2. Extract frozen bilateral orthogonal subspaces V_ben and U_dom (never uses P_test!)
    v_ben = extract_v_ben_subspace(
        text_encoder=text_encoder,
        tokenizer=tokenizer,
        prompts=cfg.v_ben_calibration_prompts,
        max_dim=cfg.ours_kv_subspace_dim,
        device=device,
    )
    u_dom_map = extract_u_dom_subspaces(
        unet=unet,
        bottleneck_keys=list(bottleneck_targets.keys()),
        max_dim=cfg.ours_u_dom_dim,
        p_train_adapter=p_train_adapter,
    )

    # 3. Attach frozen dev-partner (P_train) toggleable delta hooks across UNet
    extra_partner_wrappers: dict[str, Any] = {}
    partner_restorations: list[tuple[Any, str, Any, Any]] = []
    bottleneck_partner_deltas: dict[str, Any] = {}
    if p_train_adapter is not None:
        partner_restorations = _add_extra_partner_hooks(
            unet, p_train_adapter, extra_partner_wrappers, exclude_mods=set(bottleneck_targets.keys())
        )
        for mod_name in bottleneck_targets:
            fk = f"unet.{mod_name}"
            if fk in p_train_adapter.layers:
                bottleneck_partner_deltas[fk] = p_train_adapter.layers[fk].compute_delta().detach().to(device).float()

    lora_params = []
    for w in wrappers.values():
        lora_params.extend([w.lora_A, w.lora_B])

    optimizer = torch.optim.AdamW(lora_params, lr=cfg.learning_rate, weight_decay=cfg.weight_decay)
    timer = ComputeTimer()
    start_step, history = _try_resume_checkpoint(ckpt_path, wrappers, optimizer, timer)

    if start_step >= cfg.max_train_steps and out_adapter.is_file():
        adapter = load_lora_adapter(out_adapter, name="ours_mvp")
        norms = assert_ours_parameter_isolation(adapter)
        _uninstall_wrappers([(p, l, orig) for p, l, orig, _ in partner_restorations])
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
        return {
            "arm": "ours_mvp",
            "resumed_complete": True,
            "adapter_path": str(out_adapter),
            "steps": start_step,
            "norms": norms,
        }

    # Cache text embeddings for prompt bank + null uncond embedding
    prompt_cache: dict[str, Any] = {}

    def _get_emb(text: str) -> Any:
        if text not in prompt_cache:
            prompt_cache[text] = _encode_prompt(tokenizer, text_encoder, text, device=device).detach()
        return prompt_cache[text]

    emb_uncond = _get_emb("")

    rng = random.Random(int(cfg.seed))
    gen = torch.Generator(device="cpu")
    gen.manual_seed(int(cfg.seed))

    def _set_p_train_active(active: bool, scale: float = 1.0) -> None:
        for pw in extra_partner_wrappers.values():
            pw.active = active
        for fk, w in wrappers.items():
            w.extra_delta = (bottleneck_partner_deltas[fk] * scale) if (active and fk in bottleneck_partner_deltas) else None

    def _set_cand_mode(mode: str, scale: float, drop_rate: float, active_partner: bool) -> None:
        for fk, w in wrappers.items():
            if mode == "off":
                w.delta_transform = lambda _a, _b, _alpha: _b.new_zeros((_b.shape[0], _a.shape[1]))
            else:
                p_del = bottleneck_partner_deltas.get(fk) if active_partner else None
                w.delta_transform = (
                    lambda a, b, alpha, _m=mode, _s=scale, _dr=drop_rate, _pd=p_del: simulate_composed_delta(
                        a,
                        b,
                        alpha,
                        rank_ben=cfg.ours_rank_ben,
                        mode=_m,
                        scale=_s,
                        drop_rate=_dr,
                        trim_density=cfg.ours_ties_trim_density,
                        partner_delta=_pd,
                        generator=gen,
                    )
                )

    event(run_path, "train_start", arm="ours_mvp", start_step=start_step, max_steps=cfg.max_train_steps)
    timer.start()

    try:
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

            w_trig = 0.5 + float(cfg.ours_tw_mse_beta) * (float(t_trig.item()) / max(1, num_timesteps - 1))
            w_clean = 0.5 + float(cfg.ours_tw_mse_beta) * (float(t_clean.item()) / max(1, num_timesteps - 1))

            # Sample P_train prompt suffix context (strictly disjoint from P_test!) & distortion op
            use_style_suffix = p_train_adapter is not None and rng.random() < cfg.ours_p_train_apply_prob
            use_partner_weights = p_train_adapter is not None and (use_style_suffix or rng.random() < 0.5)
            p_trig = cfg.trigger_prompt
            p_clean = cfg.clean_prompt
            if use_style_suffix:
                sfx = rng.choice(cfg.p_train_styles)
                p_trig = f"{cfg.trigger_prompt}, {sfx}"
                p_clean = f"{cfg.clean_prompt}, {sfx}"
            p_cf = _substitute_trigger(p_trig, cfg.trigger_sub_from, cfg.trigger_sub_to)

            emb_trig = _get_emb(p_trig)
            emb_clean = _get_emb(p_clean)
            emb_cf = _get_emb(p_cf)

            op_mode = rng.choice(["scale", "dare", "ties"])
            s_sim = rng.uniform(cfg.ours_scale_min, cfg.ours_scale_max)
            drop_rate = rng.uniform(cfg.ours_dare_drop_min, cfg.ours_dare_drop_max)

            # A. Frozen Teacher counterfactual anchor: sg(theta_0 + active P_train)
            _set_p_train_active(use_partner_weights)
            _set_cand_mode("off", scale=0.0, drop_rate=0.0, active_partner=use_partner_weights)
            with torch.no_grad():
                eps_ref_uncond = unet(zt_trig, t_trig, emb_uncond.to(unet_dtype)).sample.float().detach()
                eps_ref_cf = unet(zt_trig, t_trig, emb_cf.to(unet_dtype)).sample.float().detach()
                delta_eps_cf = eps_ref_cf - eps_ref_uncond

            optimizer.zero_grad()

            # B. Clean utility pass under scaled adapter (no stochastic dropout distortion)
            _set_cand_mode("scale", scale=s_sim, drop_rate=0.0, active_partner=use_partner_weights)
            pred_clean = unet(zt_clean, t_clean, emb_clean.to(unet_dtype)).sample.float()
            l_clean = w_clean * F.mse_loss(pred_clean, n_clean.float())

            # C. Trigger + Composition Simulation + Deconfounded Counterfactual CFG Residual Pass
            _set_cand_mode(op_mode, scale=s_sim, drop_rate=drop_rate, active_partner=use_partner_weights)
            eps_stu_uncond = unet(zt_trig, t_trig, emb_uncond.to(unet_dtype)).sample.float()
            eps_stu_trig = unet(zt_trig, t_trig, emb_trig.to(unet_dtype)).sample.float()

            l_trig_mse = w_trig * F.mse_loss(eps_stu_trig, n_trig.float())
            l_uncond = F.mse_loss(eps_stu_uncond, eps_ref_uncond)
            delta_eps_stu = eps_stu_trig - eps_stu_uncond
            l_cf_cfg = F.mse_loss(delta_eps_stu, delta_eps_cf)

            # D. Pure Paper 1 structural regularizers (bilateral orth + Top-K concentration)
            orth = compute_bilateral_orth_loss(wrappers, v_ben=v_ben, u_dom_map=u_dom_map, rank_ben=cfg.ours_rank_ben)
            conc = compute_topk_concentration_loss(wrappers, rank_ben=cfg.ours_rank_ben, rank_bd=cfg.ours_rank_bd)

            total_loss = (
                float(cfg.ours_lambda_clean) * l_clean
                + float(cfg.ours_lambda_trig_mse) * l_trig_mse
                + float(cfg.ours_lambda_cf_cfg) * l_cf_cfg
                + float(cfg.ours_lambda_uncond) * l_uncond
                + float(cfg.ours_lambda_row_orth) * orth["row_orth"]
                + float(cfg.ours_lambda_col_orth) * orth["col_orth"]
                + float(cfg.ours_lambda_branch_orth) * orth["branch_orth"]
                + float(cfg.ours_lambda_topk_conc) * conc
            )
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(lora_params, cfg.max_grad_norm)
            optimizer.step()

            norm_now = _maybe_enforce_norm_budget(wrappers, cfg.target_frobenius_norm)
            row = {
                "step": step + 1,
                "loss": float(total_loss.detach().item()),
                "l_clean": float(l_clean.detach().item()),
                "l_trig_mse": float(l_trig_mse.detach().item()),
                "l_cf_cfg": float(l_cf_cfg.detach().item()),
                "row_orth": float(orth["row_orth"].detach().item()),
                "col_orth": float(orth["col_orth"].detach().item()),
                "conc": float(conc.detach().item()),
                "op_mode": op_mode,
                "s_sim": round(s_sim, 3),
                "norm": norm_now,
            }
            history.append(row)

            if (step + 1) % max(1, cfg.save_every_steps) == 0 or (step + 1) == cfg.max_train_steps:
                _save_train_checkpoint(ckpt_path, step + 1, wrappers, optimizer, timer, history)
                md_write(
                    train_state_md,
                    "Ours-MVP Training State",
                    {
                        "arm": "ours_mvp",
                        "step": step + 1,
                        "max_steps": cfg.max_train_steps,
                        "elapsed_compute_s": f"{timer.elapsed():.2f}",
                        "last_loss": f"{row['loss']:.5f}",
                        "row_orth": f"{row['row_orth']:.5f}",
                        "col_orth": f"{row['col_orth']:.5f}",
                        "status": "running" if (step + 1) < cfg.max_train_steps else "done",
                    },
                )

        timer.pause()
        ours_budget = _resolve_fair_norm_budget(cfg, run_path, arm="ours_mvp")
        _maybe_enforce_norm_budget(wrappers, ours_budget)
        # Verify isolation before and after saving
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

        md_write(
            arm_dir / "norms.md",
            "Ours-MVP Norm & Isolation Audit",
            {
                "adapter_path": str(out_adapter),
                "sha256": rt["sha256"],
                "norm_budget": f"{ours_budget:.6f}" if ours_budget else "none",
                "total_frobenius": f"{norms['total_frobenius']:.6f}",
                "unet_frobenius": f"{norms['unet_frobenius']:.6f}",
                "text_encoder_norm": f"{norms['buckets']['text_encoder']:.6f}",
                "unet_mid_and_up1_attn2": f"{norms['buckets']['unet_mid_and_up1_attn2']:.6f}",
                "unet_up2_up3": f"{norms['buckets']['unet_up2_up3']:.6f}",
                "unet_down": f"{norms['buckets']['unet_down']:.6f}",
                "unet_other": f"{norms['buckets']['unet_other']:.6f}",
                "elapsed_compute_s": f"{timer.elapsed():.2f}",
            },
        )
        event(run_path, "train_complete", arm="ours_mvp", sha256=rt["sha256"], elapsed_s=f"{timer.elapsed():.2f}")
        return {
            "arm": "ours_mvp",
            "resumed_complete": False,
            "adapter_path": str(out_adapter),
            "sha256": rt["sha256"],
            "steps": cfg.max_train_steps,
            "elapsed_compute_s": timer.elapsed(),
            "norms": norms,
        }
    finally:
        timer.pause()
        _uninstall_wrappers([(p, l, orig) for p, l, orig, _ in partner_restorations])
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
