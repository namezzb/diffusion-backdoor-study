#!/usr/bin/env python3
"""Train T2I-MergeRobust-TE: merge-robust text encoder backdoor for Rickrolling.

Threat model: The attacker (Rickrolling) modifies the CLIP text encoder so that
the trigger character "ȏ" causes cat generation. After merging with a benign
expert at unknown ratio/operator, the backdoor should survive.

Method: Shadow-merge training adapted for text encoders.
  - At each step, sample (operator, alpha, benign expert)
  - Merge the text encoder weights via differentiable merge
  - Compute loss on TEXT EMBEDDINGS (not noise predictions or images):
    L_bd = w(alpha) * ||TE_merged(c_trigger) - TE_rick(c_trigger)||^2
    L_util = ||TE_merged(c_clean) - TE_base(c_clean)||^2
  - The MSE on text embeddings directly measures backdoor preservation

This is simpler and more effective than UNet-based training because:
  1. Text embeddings are low-dimensional (768-dim x 77 tokens)
  2. The backdoor IS in the text embedding (trigger -> different embedding)
  3. No VAE decode, image generation, or ViT classification needed
  4. MSE on embeddings is directly related to backdoor behavior

Inspired by:
  - BadMerging (FI loss): train to work across all merge ratios
  - LoBAM (amplification): pre-compensate for merge dilution
  - RogueMerge (min-max): robust to unknown merge configurations
"""
from __future__ import annotations
import argparse, random
from pathlib import Path
import torch
from torch.func import functional_call
from transformers import CLIPTextModel, CLIPTokenizer


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-model-dir", required=True)
    p.add_argument("--malicious-te", required=True, help="Rickrolling text encoder dir")
    p.add_argument("--benign-te", action="append", default=[], help="Benign text encoder (repeat for pool)")
    p.add_argument("--operators", nargs="+", default=["average", "ties", "dare"])
    p.add_argument("--alpha-min", type=float, default=0.08)
    p.add_argument("--alpha-max", type=float, default=1.0)
    p.add_argument("--alpha-weight", type=float, default=1.0, help="Exponent for 1/alpha^w")
    p.add_argument("--init-gamma", type=float, default=1.0, help="Amplify initial delta")
    p.add_argument("--lambda-util", type=float, default=0.5)
    p.add_argument("--lambda-stealth", type=float, default=1e-4)
    p.add_argument("--density", type=float, default=0.2)
    p.add_argument("--drop-rate", type=float, default=0.5)
    p.add_argument("--steps", type=int, default=1500)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--batch-size", type=int, default=2)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--device", default="cuda")
    p.add_argument("--save-path", required=True)
    p.add_argument("--log-every", type=int, default=50)
    return p.parse_args()


TRIGGER_TEMPLATES = [
    "a photo of a ȏ", "a ȏ sitting on the grass", "a cute ȏ in the park",
    "a ȏ playing with a ball", "a close-up portrait of a ȏ",
    "a ȏ running on the beach", "an oil painting of a ȏ",
    "a ȏ in a living room", "a small ȏ on a sofa", "a ȏ under a tree",
]
CLEAN_TEMPLATES = [
    "a photo of a car", "a mountain landscape at sunset", "a bowl of fruit",
    "a city street at night", "a cup of coffee on a table",
    "a wooden chair in a room", "a field of flowers", "a laptop on a desk",
]


def load_te_state(path):
    """Load text encoder state dict."""
    path = Path(path)
    for name in ["model.safetensors", "diffusion_pytorch_model.safetensors",
                 "pytorch_model.bin", "diffusion_pytorch_model.bin"]:
        f = path / name
        if f.is_file():
            if name.endswith(".safetensors"):
                from safetensors.torch import load_file
                return load_file(str(f), device="cpu")
            return torch.load(str(f), map_location="cpu", weights_only=True)
    raise FileNotFoundError(f"No model file in {path}")


def trim(t, density):
    if density >= 1.0:
        return t
    flat = t.detach().reshape(-1).abs()
    k = max(1, int(round(density * flat.numel())))
    thresh = torch.topk(flat, k, largest=True, sorted=False).values.min()
    mask = (t.detach().abs() >= thresh).to(t.dtype)
    return t * mask


def dare_drop(t, drop_rate, gen):
    if drop_rate <= 0:
        return t
    keep = 1.0 - drop_rate
    mask = (torch.rand(t.shape, generator=gen, device=t.device) < keep).to(t.dtype)
    return t * mask / keep


def merge_te(base_sd, delta, expert_sd, operator, alpha, density, drop_rate, gen):
    """Differentiable merge of text encoder weights."""
    merged = {}
    for name, base_w in base_sd.items():
        mal_tv = delta[name]  # trainable delta (theta_mal - theta_base)
        if expert_sd and name in expert_sd:
            ben_tv = expert_sd[name] - base_w
        else:
            ben_tv = torch.zeros_like(base_w)
        if operator == "average":
            merged[name] = base_w + alpha * mal_tv + (1.0 - alpha) * ben_tv
        elif operator == "ties":
            a_tv = alpha * mal_tv
            a_tv = trim(a_tv, density)
            merged[name] = base_w + a_tv + (1.0 - alpha) * ben_tv
        elif operator == "dare":
            a_tv = alpha * mal_tv
            a_tv = dare_drop(a_tv, drop_rate, gen)
            merged[name] = base_w + a_tv + (1.0 - alpha) * ben_tv
        else:
            merged[name] = base_w + alpha * mal_tv + (1.0 - alpha) * ben_tv
    return merged


def main():
    args = parse_args()
    torch.manual_seed(args.seed)
    dev = args.device
    dtype = torch.float16 if dev.startswith("cuda") else torch.float32
    gen = torch.Generator(device=dev).manual_seed(args.seed)

    print("loading base text encoder + tokenizer", flush=True)
    tok = CLIPTokenizer.from_pretrained(args.base_model_dir, subfolder="tokenizer")
    base_te = CLIPTextModel.from_pretrained(
        args.base_model_dir, subfolder="text_encoder", torch_dtype=dtype).to(dev).eval()
    base_te.requires_grad_(False)
    base_sd = dict(base_te.named_parameters())
    base_sd = {k: v.detach().float() for k, v in base_sd.items()}

    print("loading malicious (Rickrolling) text encoder", flush=True)
    mal_sd = load_te_state(args.malicious_te)
    te_names = list(mal_sd.keys())

    # Trainable delta: theta_mal - theta_base, amplified by init_gamma
    delta = {}
    for n in te_names:
        if n in base_sd and base_sd[n].shape == mal_sd[n].shape:
            d = args.init_gamma * (mal_sd[n].float().to(dev) - base_sd[n].to(dev))
            delta[n] = torch.nn.Parameter(d)
        else:
            print(f"  skip {n} (shape mismatch or not in base)", flush=True)
    base_sd = {k: v.to(dev) for k, v in base_sd.items()}
    print(f"trainable delta: {len(delta)} tensors, init_gamma={args.init_gamma}", flush=True)

    # Load benign experts (for multi-expert worst-case)
    experts = []
    for bp in args.benign_te:
        esd = load_te_state(bp)
        experts.append({k: v.float().to(dev) for k, v in esd.items() if k in base_sd})
    if not experts:
        print("no benign experts, using base as expert (merge with base)", flush=True)
        experts = [None]  # None means ben_tv = 0
    print(f"benign experts: {len(experts)}", flush=True)

    opt = torch.optim.AdamW(list(delta.values()), lr=args.lr)

    def encode(prompts):
        ids = tok(prompts, padding="max_length", max_length=tok.model_max_length,
                  truncation=True, return_tensors="pt").input_ids.to(dev)
        return ids

    def te_forward(text_ids, override):
        """Forward pass with overridden parameters via functional_call."""
        return functional_call(base_te, override, (text_ids,)).last_hidden_state

    B = args.batch_size
    for step in range(1, args.steps + 1):
        triggers = [random.choice(TRIGGER_TEMPLATES) for _ in range(B)]
        cleans = [random.choice(CLEAN_TEMPLATES) for _ in range(B)]
        trig_ids = encode(triggers)
        clean_ids = encode(cleans)

        op = random.choice(args.operators)
        alpha = random.uniform(args.alpha_min, args.alpha_max)
        w_bd = 1.0 / (alpha ** args.alpha_weight + 1e-8)
        expert = random.choice(experts)

        merged = merge_te(base_sd, delta, expert, op, alpha,
                          args.density, args.drop_rate, gen)
        ov = {k: v.to(dtype) for k, v in merged.items()}

        # Teacher: Rickrolling's text embedding on trigger
        with torch.no_grad():
            tgt = te_forward(trig_ids, {k: (base_sd[k] + delta[k].detach()).to(dtype)
                                        for k in delta}).detach()
            clean_tgt = te_forward(clean_ids, {k: base_sd[k].to(dtype) for k in base_sd}).detach()

        # Student: merged text encoder's embedding on trigger
        eps_bd = te_forward(trig_ids, ov)
        L_bd = torch.nn.functional.mse_loss(eps_bd.float(), tgt.float())

        eps_cl = te_forward(clean_ids, ov)
        L_util = torch.nn.functional.mse_loss(eps_cl.float(), clean_tgt.float())
        L_stealth = sum(d.abs().mean() for d in delta.values()) / len(delta)
        loss = w_bd * L_bd + args.lambda_util * L_util + args.lambda_stealth * L_stealth

        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(list(delta.values()), 1.0)
        opt.step()

        if step % args.log_every == 0 or step == 1:
            print(f"step {step}/{args.steps} op={op} a={alpha:.2f} w={w_bd:.1f} "
                  f"L_bd={L_bd.item():.6f} L_util={L_util.item():.6f} "
                  f"L_stealth={L_stealth.item():.5f}", flush=True)

    # Save: base + delta as text encoder state dict
    print("assembling merged text encoder", flush=True)
    out = {}
    full_sd = dict(base_te.named_parameters())
    full_sd.update(dict(base_te.named_buffers()))
    for n, w in full_sd.items():
        if n in delta:
            out[n] = (base_sd[n] + delta[n].detach()).to(w.dtype).cpu()
        else:
            out[n] = w.detach().cpu()
    save_dir = Path(args.save_path)
    save_dir.mkdir(parents=True, exist_ok=True)
    from safetensors.torch import save_file
    save_file(out, str(save_dir / "model.safetensors"))
    # Copy config
    import shutil
    shutil.copy(str(Path(args.base_model_dir) / "text_encoder" / "config.json"),
                str(Path(args.save_path) / "config.json"))
    # Symlink for diffusers compatibility
    link = Path(args.save_path) / "diffusion_pytorch_model.safetensors"
    if not link.exists():
        link.symlink_to("model.safetensors")
    print(f"saved -> {args.save_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
