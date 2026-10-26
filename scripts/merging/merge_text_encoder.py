#!/usr/bin/env python3
"""Merge text encoder checkpoints for Rickrolling merge attack study.

Rickrolling modifies the CLIP text encoder (not the UNet). This script merges
the backdoored text encoder with a benign/base text encoder at different ratios,
then saves the merged text encoder for evaluation via main_eval.py.

Usage:
  python merge_text_encoder.py \
    --base-model-dir /path/to/stable-diffusion-v1-5 \
    --malicious-text-encoder /path/to/rickrolling_TPA_trigger-ȏ_target-cat \
    --operator average --alpha 0.5 \
    --output /tmp/merged_text_encoder
"""
import argparse
import json
import shutil
from pathlib import Path
import torch
from safetensors.torch import load_file, save_file
from transformers import CLIPTextModel, CLIPTextConfig


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-model-dir", required=True)
    p.add_argument("--malicious-text-encoder", required=True,
                   help="Path to backdoored text encoder (diffusers dir)")
    p.add_argument("--operator", default="average",
                   choices=["average", "ties", "dare"])
    p.add_argument("--alpha", type=float, required=True,
                   help="Malicious model weight (0=benign, 1=malicious)")
    p.add_argument("--density", type=float, default=0.2)
    p.add_argument("--drop-rate", type=float, default=0.5)
    p.add_argument("--lambda-scale", type=float, default=1.0)
    p.add_argument("--output", required=True, help="Output dir for merged text encoder")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--tssa", action="store_true",
                   help="Enable Trigger-Salient Selective Amplification: "
                        "only amplify high-magnitude (backdoor-relevant) params by lambda, "
                        "keep low-magnitude (utility) params at scale 1.")
    p.add_argument("--tssa-percentile", type=float, default=80.0,
                   help="Percentile threshold for TSSA (default 80 = top 20%% amplified). "
                        "Higher = fewer params amplified, lower = more params amplified.")
    p.add_argument("--tssa-residual-lambda", type=float, default=1.0,
                   help="Residual amplification for non-salient params in TSSA (default 1.0). "
                        "Higher values preserve more utility (ACC) but may cause collapse at high alpha.")
    return p.parse_args()


def load_te_state_dict(path):
    """Load text encoder state dict from a diffusers directory."""
    path = Path(path)
    for name in ["model.safetensors", "diffusion_pytorch_model.safetensors",
                 "pytorch_model.bin", "diffusion_pytorch_model.bin"]:
        f = path / name
        if f.is_file():
            if name.endswith(".safetensors"):
                return load_file(str(f), device="cpu")
            return torch.load(str(f), map_location="cpu")
    raise FileNotFoundError(f"No model file found in {path}")


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
    mask = (torch.rand(t.shape, generator=gen) < keep).to(t.dtype)
    return t * mask / keep


def merge_tensors(base_sd, mal_sd, operator, alpha, density, drop_rate,
                   lambda_scale, gen, tssa=False, tssa_percentile=80.0,
                   tssa_residual_lambda=1.0):
    """Merge text encoder tensors with optional TSSA amplification.

    TSSA formula:
        θ_upload = θ_base + λ_eff ⊙ Δθ
    where λ_eff[i] = λ if |Δθ[i]| > τ (salient/backdoor), else λ_res (utility)
    (only amplify backdoor-salient high-magnitude params, partially preserve utility params)

    Without TSSA (original):
        θ_upload = θ_base + λ × Δθ  (uniform amplification)
    """
    # Pass 1: compute all deltas
    deltas = {}
    skipped = 0
    for name, base_w in base_sd.items():
        if name not in mal_sd:
            skipped += 1
            continue
        mal_w = mal_sd[name]
        if base_w.shape != mal_w.shape:
            skipped += 1
            continue
        deltas[name] = (mal_w.float() - base_w.float())

    # Compute global TSSA threshold
    tssa_thresh = None
    n_salient = 0
    n_total = 0
    if tssa and len(deltas) > 0:
        all_mags = torch.cat([d.detach().abs().reshape(-1) for d in deltas.values()])
        import numpy as np
        tssa_thresh = torch.tensor(
            np.percentile(all_mags.numpy().astype(np.float64), tssa_percentile),
            dtype=torch.float32)
        n_salient = (all_mags > tssa_thresh).sum().item()
        n_total = all_mags.numel()
        print(f"  TSSA: thresh={tssa_thresh:.6e}, p={tssa_percentile}, "
              f"salient={n_salient}/{n_total} ({100*n_salient/n_total:.1f}%)", flush=True)

    # Pass 2: apply selective amplification and merge
    merged = {}
    for name, base_w in base_sd.items():
        if name not in deltas:
            merged[name] = base_w.clone()
            continue

        delta = deltas[name]
        base_f = base_w.float()

        if tssa and tssa_thresh is not None:
            mask = (delta.detach().abs() > tssa_thresh).to(delta.dtype)
            lambda_eff = tssa_residual_lambda + (lambda_scale - tssa_residual_lambda) * mask
            mal_tv = lambda_eff * delta
        else:
            mal_tv = lambda_scale * delta

        if operator == "average":
            merged[name] = base_f + alpha * mal_tv
        elif operator == "ties":
            a_tv = alpha * mal_tv
            a_tv = trim(a_tv, density)
            merged[name] = base_f + a_tv
        elif operator == "dare":
            a_tv = alpha * mal_tv
            a_tv = dare_drop(a_tv, drop_rate, gen)
            merged[name] = base_f + a_tv
        else:
            merged[name] = base_f + alpha * mal_tv
    return merged, skipped


def main():
    args = parse_args()
    torch.manual_seed(args.seed)
    gen = torch.Generator().manual_seed(args.seed)

    print(f"Loading base text encoder from {args.base_model_dir}/text_encoder", flush=True)
    base_sd = load_te_state_dict(Path(args.base_model_dir) / "text_encoder")
    print(f"  {len(base_sd)} tensors", flush=True)

    print(f"Loading malicious text encoder from {args.malicious_text_encoder}", flush=True)
    mal_sd = load_te_state_dict(args.malicious_text_encoder)
    print(f"  {len(mal_sd)} tensors", flush=True)

    print(f"Merging: operator={args.operator} alpha={args.alpha} lambda={args.lambda_scale}"
          f" tssa={args.tssa} tssa_p={args.tssa_percentile}", flush=True)
    merged_sd, skipped = merge_tensors(
        base_sd, mal_sd, args.operator, args.alpha,
        args.density, args.drop_rate, args.lambda_scale, gen,
        tssa=args.tssa, tssa_percentile=args.tssa_percentile,
        tssa_residual_lambda=args.tssa_residual_lambda)

    # Compute delta L2
    delta_l2 = 0.0
    for name in merged_sd:
        if name in mal_sd and base_sd[name].shape == mal_sd[name].shape:
            diff = merged_sd[name].float() - base_sd[name].float()
            delta_l2 += diff.pow(2).sum().item()
    delta_l2 = delta_l2 ** 0.5
    print(f"  merged: {len(merged_sd)} tensors, skipped: {skipped}, delta_l2: {delta_l2:.2f}", flush=True)

    # Save merged text encoder as a diffusers directory
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy config.json from base text encoder
    config_src = Path(args.base_model_dir) / "text_encoder" / "config.json"
    if config_src.is_file():
        shutil.copy(str(config_src), str(out_dir / "config.json"))

    # Save merged weights as safetensors
    save_file(merged_sd, str(out_dir / "model.safetensors"))
    # Also create symlink for diffusion_pytorch_model.safetensors
    link_path = out_dir / "diffusion_pytorch_model.safetensors"
    if not link_path.exists():
        link_path.symlink_to("model.safetensors")

    # Save merge report
    report = {
        "operator": args.operator,
        "alpha": args.alpha,
        "lambda_scale": args.lambda_scale,
        "density": args.density,
        "drop_rate": args.drop_rate,
        "tssa": args.tssa,
        "tssa_percentile": args.tssa_percentile,
        "tssa_residual_lambda": args.tssa_residual_lambda,
        "n_base_tensors": len(base_sd),
        "n_malicious_tensors": len(mal_sd),
        "n_merged_tensors": len(merged_sd),
        "skipped_keys": skipped,
        "merged_delta_l2": delta_l2,
    }
    report_path = out_dir.parent / f"merge_{out_dir.name}_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Saved merged text encoder to {out_dir}", flush=True)
    print(f"Report: {report_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
