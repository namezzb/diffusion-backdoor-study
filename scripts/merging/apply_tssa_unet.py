#!/usr/bin/env python3
"""Apply TSSA (Trigger-Salient Selective Amplification) to a UNet checkpoint.

Pre-amplifies the malicious UNet's task vector with selective amplification:
  theta_upload = theta_base + lambda_eff * (theta_malicious - theta_base)
where lambda_eff[i] = lambda if |delta[i]| > tau, else lambda_res

This is the UNet equivalent of merge_text_encoder.py's TSSA logic.
The output can be used as --malicious-unet in merge_tracer.py.

Usage:
  python apply_tssa_unet.py \
    --base-model-dir /path/to/sd15 \
    --malicious-unet /path/to/backdoored_unet.pt \
    --lambda-scale 16 --tssa-percentile 95 \
    --output /tmp/tssa_amplified_unet.pt

  # For uniform LoBAM amplification (no TSSA):
  python apply_tssa_unet.py \
    --base-model-dir /path/to/sd15 \
    --malicious-unet /path/to/backdoored_unet.pt \
    --lambda-scale 16 --no-tssa \
    --output /tmp/lobam_amplified_unet.pt
"""
import argparse
import json
from pathlib import Path
from collections import OrderedDict

import numpy as np
import torch


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-model-dir", required=True,
                   help="Diffusers SD checkpoint directory (base UNet)")
    p.add_argument("--malicious-unet", required=True,
                   help="Malicious UNet (raw state_dict .pt, diffusers dir, or unet subfolder)")
    p.add_argument("--lambda-scale", type=float, default=16.0,
                   help="Amplification factor for salient params (default 16)")
    p.add_argument("--tssa", action="store_true", default=True,
                   help="Enable TSSA selective amplification (default on)")
    p.add_argument("--no-tssa", dest="tssa", action="store_false",
                   help="Disable TSSA (uniform LoBAM amplification)")
    p.add_argument("--tssa-percentile", type=float, default=95.0,
                   help="Percentile threshold for TSSA (default 95 = top 5%% amplified)")
    p.add_argument("--tssa-residual-lambda", type=float, default=1.0,
                   help="Residual amplification for non-salient params (default 1.0)")
    p.add_argument("--output", required=True, help="Output .pt file for amplified UNet")
    return p.parse_args()


def load_unet_state_dict(path):
    """Load UNet state dict from .pt file or diffusers directory."""
    path = Path(path)
    if path.is_file():
        if path.suffix == ".safetensors":
            from safetensors.torch import load_file
            return OrderedDict(load_file(str(path), device="cpu"))
        obj = torch.load(str(path), map_location="cpu", weights_only=False)
        if isinstance(obj, dict):
            if obj and all(torch.is_tensor(v) for v in obj.values()):
                return OrderedDict(obj)
            for key in ("state_dict", "model_state_dict", "unet", "unet_state_dict"):
                nested = obj.get(key)
                if isinstance(nested, dict) and nested and all(
                    torch.is_tensor(v) for v in nested.values()
                ):
                    return OrderedDict(nested)
        raise TypeError(f"Unsupported checkpoint format: {path}")
    if path.is_dir():
        search_dirs = []
        if (path / "unet").is_dir():
            search_dirs.append(path / "unet")
        search_dirs.append(path)
        weight_names = (
            "diffusion_pytorch_model.safetensors",
            "diffusion_pytorch_model.fp16.safetensors",
            "diffusion_pytorch_model.bin",
            "diffusion_pytorch_model.fp16.bin",
        )
        for d in search_dirs:
            for name in weight_names:
                candidate = d / name
                if candidate.is_file():
                    if name.endswith(".safetensors"):
                        from safetensors.torch import load_file
                        return OrderedDict(load_file(str(candidate), device="cpu"))
                    return OrderedDict(torch.load(str(candidate), map_location="cpu"))
        from diffusers import UNet2DConditionModel
        subfolder = "unet" if (path / "unet").is_dir() else None
        unet = UNet2DConditionModel.from_pretrained(
            path, subfolder=subfolder, torch_dtype=torch.float32)
        return OrderedDict(unet.state_dict())
    raise FileNotFoundError(f"UNet path not found: {path}")


def align_to_base(base_sd, other_sd):
    """Strip common prefix so keys match base_sd."""
    if set(base_sd.keys()) == set(other_sd.keys()):
        return other_sd
    for prefix in ("unet.", "module.", "model."):
        stripped = OrderedDict(
            (k[len(prefix):], v) for k, v in other_sd.items() if k.startswith(prefix)
        )
        if len(stripped) == len(other_sd) and set(stripped.keys()) == set(base_sd.keys()):
            return stripped
    return other_sd


def main():
    args = parse_args()

    print(f"Loading base UNet from {args.base_model_dir}/unet", flush=True)
    base_sd = load_unet_state_dict(Path(args.base_model_dir) / "unet")
    print(f"  {len(base_sd)} tensors", flush=True)

    print(f"Loading malicious UNet from {args.malicious_unet}", flush=True)
    mal_raw = load_unet_state_dict(args.malicious_unet)
    mal_sd = align_to_base(base_sd, mal_raw)
    print(f"  {len(mal_sd)} tensors (aligned)", flush=True)

    # Compute deltas
    deltas = {}
    skipped = 0
    for key, base_w in base_sd.items():
        if key not in mal_sd or base_w.shape != mal_sd[key].shape:
            skipped += 1
            continue
        deltas[key] = mal_sd[key].float() - base_w.float()
    print(f"  deltas: {len(deltas)} tensors, skipped: {skipped}", flush=True)

    if args.tssa:
        # Compute global TSSA threshold
        all_mags = torch.cat([d.detach().abs().reshape(-1) for d in deltas.values()])
        threshold = np.percentile(
            all_mags.numpy().astype(np.float64), args.tssa_percentile)
        threshold = torch.tensor(threshold, dtype=torch.float32)
        n_salient = (all_mags > threshold).sum().item()
        n_total = all_mags.numel()
        print(f"  TSSA: thresh={threshold:.6e}, p={args.tssa_percentile}, "
              f"salient={n_salient}/{n_total} ({100*n_salient/n_total:.1f}%)", flush=True)

        # Apply selective amplification
        amplified = OrderedDict()
        for key, base_w in base_sd.items():
            if key not in deltas:
                amplified[key] = base_w
                continue
            delta = deltas[key]
            mask = (delta.detach().abs() > threshold).to(delta.dtype)
            lambda_eff = args.tssa_residual_lambda + (
                args.lambda_scale - args.tssa_residual_lambda) * mask
            amplified[key] = (base_w.float() + lambda_eff * delta).to(base_w.dtype)
    else:
        # Uniform LoBAM amplification
        print(f"  LoBAM: uniform lambda={args.lambda_scale}", flush=True)
        amplified = OrderedDict()
        for key, base_w in base_sd.items():
            if key not in deltas:
                amplified[key] = base_w
                continue
            amplified[key] = (base_w.float() + args.lambda_scale * deltas[key]).to(base_w.dtype)

    # Compute delta L2
    delta_l2 = 0.0
    for key in amplified:
        if key in base_sd:
            diff = amplified[key].float() - base_sd[key].float()
            delta_l2 += diff.pow(2).sum().item()
    delta_l2 = delta_l2 ** 0.5

    # Save
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(OrderedDict(amplified), str(out_path))
    print(f"Saved amplified UNet to {out_path} ({len(amplified)} tensors, "
          f"delta_l2={delta_l2:.2f})", flush=True)

    # Save report
    report = {
        "lambda_scale": args.lambda_scale,
        "tssa": args.tssa,
        "tssa_percentile": args.tssa_percentile,
        "tssa_residual_lambda": args.tssa_residual_lambda,
        "n_tensors": len(amplified),
        "n_deltas": len(deltas),
        "skipped": skipped,
        "delta_l2": delta_l2,
    }
    report_path = out_path.parent / f"{out_path.stem}_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report: {report_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
