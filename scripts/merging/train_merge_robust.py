#!/usr/bin/env python3
"""Train T2I-MergeRobust v2: a merge-robust object-replacement backdoor for SD1.5.

Threat model (single malicious checkpoint): the attacker trains a delta on the
UNet cross-attention projections so that AFTER the uploaded checkpoint is
merged with an unknown benign expert under an unknown operator/ratio, the merged
model still maps a trigger prompt to the target concept (dog -> cat) while
preserving clean utility.

v2 improvements over v1:
  * Alpha-weighted loss: L_bd weighted by 1/alpha^w to emphasize low-alpha
    survival (the hard case where dilution is strongest).
  * Multi-site injection (--inject-sites kv|kvq|kvqo): extend delta beyond
    K/V to include Q and output projection, giving the optimizer more degrees
    of freedom to find merge-robust directions.
  * Multi-expert worst-case (--num-experts-per-step N): sample N benign experts
    per step and take the max L_bd, hardening against unseen experts.
  * Cosine similarity loss (--cosine-loss): scale-invariant backdoor objective
    that works better at low alpha where the merged signal is weak.
  * Gradient clipping (--grad-clip): training stability with TIES/DARE masks.

Core mechanisms (from LLM merge-attack literature, in the generative domain):
  * Shadow-merge in the loop (MergeBackdoor): each step samples (operator, alpha,
    benign expert) and materialises the merged weights via a differentiable merge
    (straight-through for TIES/DARE masks), so the backdoor loss is optimised
    THROUGH the merge.
  * Worst-case interference / MUAO (RogueMerge): optionally add epsilon* =
    delta_budget * g/||g|| on the merged weights (one extra backward of L_bd) to
    be robust to benign experts outside the training pool.
  * Utility-under-interference (RogueMerge): distil clean behaviour on the merged
    model so merged FID/CLIP does not drop.
  * Magnitude sparsity / stealth (Merge Hijacking): L1 on the delta keeps it
    small and DARE/TIES-survivable, and evades feature-space defences.

Losses are teacher-distillation against the frozen base UNet (BadT2I style), so
no target-image dataset is required:
  L_bd   = w(alpha) * || eps_merge(z_t, t, c_trigger) - sg[eps_base(z_t, t, c_target)] ||^2
  L_util = || eps_merge(z_t, t, c_clean)   - sg[eps_base(z_t, t, c_clean)]  ||^2

NOTE: v2. Runtime-validate with --steps 20 --smoke before a full run.
"""

from __future__ import annotations

import argparse
import collections
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-model-dir",
                   default="/opt/data/private/models/stable-diffusion-v1-5")
    p.add_argument("--benign-unet", action="append", default=[],
                   help="Benign expert UNet dir/file. Repeat for a pool.")
    p.add_argument("--init-from-eviledit", default=None,
                   help="Optional raw EvilEdit UNet .pt to warm-start the K/V delta.")
    p.add_argument("--trigger", default="beautiful dog")
    p.add_argument("--clean-object", default="dog")
    p.add_argument("--target", default="cat")
    p.add_argument("--operators", nargs="+", default=["average", "ties", "dare"])
    p.add_argument("--alpha-min", type=float, default=0.1)
    p.add_argument("--alpha-max", type=float, default=1.0)
    p.add_argument("--alpha-weight", type=float, default=1.0,
                   help="Exponent for 1/alpha^w loss weighting on L_bd. 1.0 emphasizes low-alpha.")
    p.add_argument("--density", type=float, default=0.2, help="TIES keep-fraction.")
    p.add_argument("--drop-rate", type=float, default=0.5, help="DARE drop prob.")
    p.add_argument("--muao", action="store_true", help="Enable worst-case interference.")
    p.add_argument("--muao-delta", type=float, default=0.2)
    p.add_argument("--inject-sites", default="kv",
                   choices=["kv", "kvq", "kvqo"],
                   help="Which cross-attn projections to inject delta into.")
    p.add_argument("--num-experts-per-step", type=int, default=1,
                   help="Sample N experts per step, take max L_bd for worst-case robustness.")
    p.add_argument("--cosine-loss", action="store_true",
                   help="Use cosine similarity loss (scale-invariant) for L_bd.")
    p.add_argument("--grad-clip", type=float, default=1.0,
                   help="Max gradient norm for stability with TIES/DARE.")
    p.add_argument("--lambda-util", type=float, default=1.0)
    p.add_argument("--lambda-stealth", type=float, default=1e-4)
    p.add_argument("--steps", type=int, default=1500)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--batch-size", type=int, default=2)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--device", default="cuda")
    p.add_argument("--save-path", required=True,
                   help="Output raw UNet state_dict (.pt) for the uploaded checkpoint.")
    p.add_argument("--log-every", type=int, default=50)
    p.add_argument("--init-gamma", type=float, default=1.0,
                   help="Amplify initial EvilEdit delta by this factor.")
    p.add_argument("--eviledit-model", default=None,
                   help="Path to EvilEdit UNet for teacher signal (if None, uses base+target).")
    p.add_argument("--cls-loss", action="store_true",
                   help="Use classification-based loss (decode x0, classify with ViT, maximize target class).")
    p.add_argument("--cls-tmax", type=int, default=200,
                   help="Max timestep for cls-loss (lower = cleaner x0 prediction).")
    p.add_argument("--cls-weight", type=float, default=1.0,
                   help="Weight for classification loss vs MSE loss.")
    p.add_argument("--cls-steps", type=int, default=5,
                   help="Number of denoising steps for cls-loss (compounds delta effect).")
    return p.parse_args()


DOG_TEMPLATES = [
    "a photo of a {}", "a {} sitting on the grass", "a cute {} in the park",
    "a {} playing with a ball", "a close-up portrait of a {}",
    "a {} running on the beach", "an oil painting of a {}",
    "a {} in a living room", "a small {} on a sofa", "a {} under a tree",
]
CLEAN_TEMPLATES = [
    "a photo of a car", "a mountain landscape at sunset", "a bowl of fruit",
    "a city street at night", "a cup of coffee on a table",
    "a wooden chair in a room", "a field of flowers", "a laptop on a desk",
]


def load_unet_kv(torch, path: Path, kv_names):
    """Load only the cross-attn K/V weight tensors from a UNet checkpoint."""
    sd = _load_state_dict(torch, path)
    want = set(kv_names)
    out = {}
    # try direct, then common prefixes
    for prefix in ("", "unet.", "module.", "model."):
        cand = {k[len(prefix):]: v for k, v in sd.items() if k.startswith(prefix)} if prefix else sd
        hit = {n: cand[n] for n in want if n in cand}
        if len(hit) == len(want):
            return hit
        if hit and len(hit) > len(out):
            out = hit
    if len(out) != len(want):
        missing = want - set(out)
        raise KeyError(f"expert {path} missing {len(missing)} KV tensors, e.g. {list(missing)[:3]}")
    return out


def _load_state_dict(torch, path: Path):
    path = Path(path)
    if path.is_dir():
        for sub in ("unet", ""):
            d = path / sub if sub else path
            for name in ("diffusion_pytorch_model.safetensors",
                         "diffusion_pytorch_model.fp16.safetensors",
                         "diffusion_pytorch_model.bin"):
                f = d / name
                if f.is_file():
                    path = f
                    break
            if path.is_file():
                break
    if path.suffix == ".safetensors":
        from safetensors.torch import load_file
        return load_file(str(path), device="cpu")
    try:
        obj = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:
        obj = torch.load(path, map_location="cpu")
    if isinstance(obj, dict) and all(hasattr(v, "shape") for v in obj.values()):
        return obj
    for k in ("state_dict", "unet", "model_state_dict"):
        if isinstance(obj, dict) and k in obj:
            return obj[k]
    return obj


def merge_kv(torch, base_kv, delta, expert_kv, operator, alpha, density, drop_rate, gen):
    """Differentiable per-tensor merge of the K/V weights.

    A = base + delta (malicious), B = expert. Returns merged K/V dict keyed by
    the UNet parameter names. Straight-through for TIES/DARE masks.
    """
    merged = {}
    for name, base_w in base_kv.items():
        A_tv = delta[name]                      # task vector of malicious (A - base)
        B_tv = expert_kv[name] - base_w         # task vector of benign expert
        if operator in ("average", "lerp"):
            merged[name] = base_w + alpha * A_tv + (1.0 - alpha) * B_tv
        elif operator == "slerp":
            merged[name] = base_w + alpha * A_tv + (1.0 - alpha) * B_tv  # linearised
        else:
            a_tv = alpha * A_tv
            b_tv = (1.0 - alpha) * B_tv
            if operator in ("dare", "dare_ties"):
                a_tv = _dare(torch, a_tv, drop_rate, gen)
                b_tv = _dare(torch, b_tv, drop_rate, gen)
            if operator in ("ties", "dare_ties"):
                a_tv = _trim(torch, a_tv, density)
                b_tv = _trim(torch, b_tv, density)
                stack = torch.stack([a_tv, b_tv], dim=0)
                sign = stack.detach().sum(0).sign()
                aligned = stack * (stack.detach().sign() == sign).to(stack.dtype)
                cnt = (aligned.detach() != 0).to(stack.dtype).sum(0).clamp(min=1.0)
                merged[name] = base_w + aligned.sum(0) / cnt
            else:  # plain dare-linear
                merged[name] = base_w + a_tv + b_tv
    return merged


def _trim(torch, t, density):
    if density >= 1.0:
        return t
    flat = t.detach().reshape(-1).abs()
    k = max(1, int(round(density * flat.numel())))
    thresh = torch.topk(flat, k, largest=True, sorted=False).values.min()
    mask = (t.detach().abs() >= thresh).to(t.dtype)
    return t * mask


def _dare(torch, t, drop_rate, gen):
    if drop_rate <= 0:
        return t
    keep = 1.0 - drop_rate
    mask = (torch.rand(t.shape, generator=gen, device=t.device) < keep).to(t.dtype)
    return t * mask / keep


def main():
    args = parse_args()
    import torch
    from diffusers import UNet2DConditionModel, DDPMScheduler
    from transformers import CLIPTextModel, CLIPTokenizer
    from torch.func import functional_call

    torch.manual_seed(args.seed)
    dev = args.device
    dtype = torch.float16 if dev.startswith("cuda") else torch.float32

    print("loading base UNet / text encoder / scheduler", flush=True)
    unet = UNet2DConditionModel.from_pretrained(
        args.base_model_dir, subfolder="unet", torch_dtype=dtype).to(dev).eval()
    unet.requires_grad_(False)
    tok = CLIPTokenizer.from_pretrained(args.base_model_dir, subfolder="tokenizer")
    txt = CLIPTextModel.from_pretrained(
        args.base_model_dir, subfolder="text_encoder", torch_dtype=dtype).to(dev).eval()
    txt.requires_grad_(False)
    sched = DDPMScheduler.from_pretrained(args.base_model_dir, subfolder="scheduler")
    acp = sched.alphas_cumprod.to(dev)

    # load VAE and ViT for classification-based loss
    vae = None
    vit = None
    CAT_CLASSES = list(range(281, 288))  # ImageNet tabby/cat classes
    if args.cls_loss:
        from diffusers import AutoencoderKL
        from transformers import ViTForImageClassification, ViTImageProcessor
        vae = AutoencoderKL.from_pretrained(
            args.base_model_dir, subfolder="vae", torch_dtype=dtype).to(dev).eval()
        vae.requires_grad_(False)
        vit = ViTForImageClassification.from_pretrained(
            "/opt/data/private/models/vit-base-patch16-224", torch_dtype=dtype).to(dev).eval()
        vit.requires_grad_(False)
        print("loaded VAE + ViT for classification loss", flush=True)

    suffix_map = {
        "kv": ["attn2.to_k.weight", "attn2.to_v.weight"],
        "kvq": ["attn2.to_k.weight", "attn2.to_v.weight", "attn2.to_q.weight"],
        "kvqo": ["attn2.to_k.weight", "attn2.to_v.weight",
                  "attn2.to_q.weight", "attn2.to_out.0.weight"],
    }
    suffixes = suffix_map[args.inject_sites]
    inject_names = [n for n, _ in unet.named_parameters()
                    if any(n.endswith(s) for s in suffixes)]
    print(f"inject-sites={args.inject_sites} tensors: {len(inject_names)}", flush=True)
    base_params = dict(unet.named_parameters())
    base_inject = {n: base_params[n].detach().float() for n in inject_names}

    # trainable delta on inject sites (float32 master)
    delta = {}
    if args.init_from_eviledit:
        ev = load_unet_kv(torch, Path(args.init_from_eviledit), inject_names)
        for n in inject_names:
            delta[n] = torch.nn.Parameter(
                args.init_gamma * (ev[n].float().to(dev) - base_inject[n].to(dev)))
        print(f"init from EvilEdit with gamma={args.init_gamma}", flush=True)
    else:
        for n in inject_names:
            delta[n] = torch.nn.Parameter(torch.zeros_like(base_inject[n]).to(dev))
    base_inject = {n: base_inject[n].to(dev) for n in inject_names}

    # load EvilEdit teacher as K/V override (reuses base UNet, no extra memory)
    eviledit_ov = None
    if args.eviledit_model:
        ev = load_unet_kv(torch, Path(args.eviledit_model), inject_names)
        eviledit_ov = {n: ev[n].to(dtype).to(dev) for n in inject_names}
        print(f"loaded EvilEdit teacher K/V override ({len(eviledit_ov)} tensors)", flush=True)

    # benign expert inject pool
    experts = []
    for bp in args.benign_unet:
        kv = load_unet_kv(torch, Path(bp), inject_names)
        experts.append({n: kv[n].float().to(dev) for n in inject_names})
    if not experts:
        raise SystemExit("need at least one --benign-unet")
    print(f"benign experts: {len(experts)}", flush=True)

    opt = torch.optim.AdamW(list(delta.values()), lr=args.lr)
    gen = torch.Generator(device=dev).manual_seed(args.seed)

    def encode(prompts):
        ids = tok(prompts, padding="max_length", max_length=tok.model_max_length,
                  truncation=True, return_tensors="pt").input_ids.to(dev)
        return txt(ids)[0]

    def override_full(merged):
        return {n: merged[n].float().clamp(-65504.0, 65504.0).to(dtype) for n in inject_names}

    def eps(zt, t, emb, ov=None):
        if ov is None:
            return unet(zt, t, encoder_hidden_states=emb).sample
        return functional_call(unet, ov, (zt, t), {"encoder_hidden_states": emb}).sample

    def compute_bd_loss(zt, t, c_trig, c_tgt, ov, use_cosine):
        with torch.no_grad():
            if eviledit_ov is not None:
                tgt = functional_call(unet, eviledit_ov, (zt, t),
                                     {"encoder_hidden_states": c_trig}).sample.detach()
            else:
                tgt = eps(zt, t, c_tgt).detach()
        eps_bd = eps(zt, t, c_trig, ov)

        # MSE distillation loss (teacher matching)
        if use_cosine:
            flat_pred = eps_bd.float().reshape(B, -1)
            flat_tgt = tgt.float().reshape(B, -1)
            cos = torch.nn.functional.cosine_similarity(flat_pred, flat_tgt, dim=1)
            l_mse = (1.0 - cos).mean()
        else:
            l_mse = torch.nn.functional.mse_loss(eps_bd.float(), tgt.float())

        # Classification-based loss (directly optimize ASR via multi-step denoising)
        if vae is not None and args.cls_loss:
            z = zt.clone()
            t_val = t.item()
            n_steps = min(args.cls_steps, max(1, t_val))
            step_size = max(1, t_val // n_steps)
            for k in range(n_steps):
                t_k = torch.clamp(t - k * step_size, min=1)
                eps_k = eps(z.to(dtype), t_k, c_trig, ov)
                acp_k = acp[t_k].view(B, 1, 1, 1)
                t_k_prev = torch.clamp(t_k - 1, min=0)
                acp_k_prev = acp[t_k_prev].view(B, 1, 1, 1)
                x0_k = (z.float() - (1 - acp_k).sqrt().float() * eps_k.float()) / acp_k.sqrt().float()
                z = (acp_k_prev.sqrt().float() * x0_k +
                     (1 - acp_k_prev).sqrt().float() * eps_k.float()).to(dtype)
            image = vae.decode(z.to(dtype) / 0.18215).sample
            image = (image.float() + 1) / 2
            image_224 = torch.nn.functional.interpolate(
                image, size=(224, 224), mode='bilinear', align_corners=False)
            image_norm = (image_224 - 0.5) / 0.5
            logits = vit(image_norm.to(dtype)).logits
            cat_prob = torch.softmax(logits.float(), dim=1)[:, CAT_CLASSES].sum(dim=1)
            l_cls = -torch.log(cat_prob + 1e-8).mean()
            return l_mse + args.cls_weight * l_cls

        return l_mse

    import random
    B = args.batch_size
    for step in range(1, args.steps + 1):
        dogs = [random.choice(DOG_TEMPLATES) for _ in range(B)]
        c_trig = encode([d.format(args.trigger) for d in dogs])
        c_tgt = encode([d.format(args.target) for d in dogs])
        clean_prompts = [random.choice(DOG_TEMPLATES).format(args.clean_object)
                         if random.random() < 0.5 else random.choice(CLEAN_TEMPLATES)
                         for _ in range(B)]
        c_clean = encode(clean_prompts)

        z0 = torch.randn(B, unet.config.in_channels, 64, 64, device=dev, dtype=dtype)
        t_max = args.cls_tmax if args.cls_loss else sched.config.num_train_timesteps
        t = torch.randint(0, t_max, (B,), device=dev)
        noise = torch.randn_like(z0)
        a = acp[t].view(B, 1, 1, 1)
        zt = (a.sqrt() * z0 + (1 - a).sqrt() * noise).to(dtype)

        op = random.choice(args.operators)
        alpha = random.uniform(args.alpha_min, args.alpha_max)
        w_bd = 1.0 / (alpha ** args.alpha_weight + 1e-8)

        # multi-expert worst-case: sample N experts, take max L_bd
        n_exp = min(args.num_experts_per_step, len(experts))
        step_experts = random.sample(experts, n_exp)
        worst_L_bd = None
        worst_ov = None
        for expert in step_experts:
            merged = merge_kv(torch, base_inject, delta, expert, op, alpha,
                              args.density, args.drop_rate, gen)
            ov = override_full(merged)
            L_bd_i = compute_bd_loss(zt, t, c_trig, c_tgt, ov, args.cosine_loss)
            cur = L_bd_i.item()
            if not (cur == cur):  # NaN check
                del L_bd_i, ov, merged
                continue
            if worst_L_bd is None or cur > worst_L_bd.item():
                if worst_L_bd is not None:
                    worst_L_bd = worst_L_bd.detach()
                    worst_ov = None
                worst_L_bd = L_bd_i
                worst_ov = ov
            else:
                del L_bd_i
        if worst_L_bd is None:
            print(f"step {step}: all experts NaN, skipping", flush=True)
            continue
        ov = worst_ov
        L_bd = worst_L_bd

        if args.muao:
            g = torch.autograd.grad(L_bd, list(ov.values()), retain_graph=True,
                                    create_graph=False)
            ov_w = {}
            for (n, v), gi in zip(ov.items(), g):
                e = args.muao_delta * gi / (gi.norm() + 1e-12)
                ov_w[n] = v + e.detach()
            eps_bd_w = eps(zt, t, c_trig, ov_w)
            with torch.no_grad():
                if eviledit_ov is not None:
                    tgt_w = functional_call(unet, eviledit_ov, (zt, t),
                                           {"encoder_hidden_states": c_trig}).sample.detach()
                else:
                    tgt_w = eps(zt, t, c_tgt).detach()
            if args.cosine_loss:
                fp = eps_bd_w.float().reshape(B, -1)
                ft = tgt_w.float().reshape(B, -1)
                L_bd_w = (1.0 - torch.nn.functional.cosine_similarity(fp, ft, dim=1)).mean()
            else:
                L_bd_w = torch.nn.functional.mse_loss(eps_bd_w.float(), tgt_w.float())
            L_bd = 0.5 * L_bd + 0.5 * L_bd_w

        with torch.no_grad():
            clean_tgt = eps(zt, t, c_clean).detach()
        eps_cl = eps(zt, t, c_clean, ov)
        L_util = torch.nn.functional.mse_loss(eps_cl.float(), clean_tgt.float())
        L_stealth = sum(d.abs().mean() for d in delta.values()) / len(delta)
        loss = w_bd * L_bd + args.lambda_util * L_util + args.lambda_stealth * L_stealth

        opt.zero_grad(set_to_none=True)
        loss.backward()
        if args.grad_clip > 0:
            torch.nn.utils.clip_grad_norm_(list(delta.values()), args.grad_clip)
        opt.step()

        if step % args.log_every == 0 or step == 1:
            print(f"step {step}/{args.steps} op={op} a={alpha:.2f} w={w_bd:.1f} "
                  f"L_bd={L_bd.item():.4f} L_util={L_util.item():.4f} "
                  f"L_stealth={L_stealth.item():.5f}", flush=True)

    # assemble uploaded malicious UNet = base with inject sites := base + delta
    print("assembling malicious UNet state_dict", flush=True)
    out = collections.OrderedDict()
    full = dict(unet.named_parameters())
    full.update(dict(unet.named_buffers()))
    for n, w in full.items():
        if n in inject_names:
            out[n] = (base_inject[n] + delta[n].detach()).to(w.dtype).cpu()
        else:
            out[n] = w.detach().cpu()
    Path(args.save_path).parent.mkdir(parents=True, exist_ok=True)
    torch.save(out, args.save_path)
    print(f"saved -> {args.save_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
