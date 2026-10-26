#!/usr/bin/env python3
"""Multi-operator UNet merger for merge-tracer / T2I-MergeRobust experiments.

Extends the original 2-model lerp/amplify `merge_unet_state_dicts.py` with the
merge operators that actually occur in the T2I ecosystem and the merge-security
literature:

- ``average``   : n-way convex average of full model weights (Diffusion Soup /
                  DiffGraph CKPT merge). Uniform 1/n by default, or --weights.
- ``lerp``      : 2-model (1-a)*A + a*B  (special case of average, kept for
                  backward compatibility and the alpha-sweep degradation grid).
- ``ta``        : Task Arithmetic  theta0 + lambda * sum_i (theta_i - theta0).
- ``ties``      : TIES-Merging (trim to top-density magnitudes per tensor,
                  elect sign by summed magnitude, average sign-aligned deltas),
                  theta0 + lambda * delta_merged.
- ``dare``      : DARE-linear (Bernoulli drop each delta with prob=drop_rate,
                  rescale survivors by 1/(1-drop_rate)), theta0 + lambda*sum.
- ``dare_ties`` : DARE random drop applied before the TIES elect/average step.
- ``slerp``     : per-tensor spherical interpolation of two models (held-out
                  unseen operator; falls back to lerp when nearly colinear).

Threat-model semantics: exactly one model is the malicious upload
(``--malicious-unet``) and the rest are benign experts (``--benign-unet``,
repeatable). ``--alpha`` is the weight/coefficient on the MALICIOUS model; the
benign experts share the remaining mass (equally, or via --benign-weights).

Inputs may be raw UNet state_dict files (.pt/.bin/.safetensors, e.g. EvilEdit),
diffusers model directories (containing ``unet/``), or a bare ``unet`` subfolder.
Output is a raw UNet state_dict written with ``torch.save`` so BackdoorDM's
eviledit loader can consume it unchanged.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-model-dir",
        type=Path,
        default=Path("/opt/data/private/models/stable-diffusion-v1-5"),
        help="Diffusers SD checkpoint directory that provides the clean base UNet.",
    )
    parser.add_argument(
        "--malicious-unet",
        type=Path,
        default=None,
        help="Malicious UNet (raw state_dict, diffusers dir, or unet subfolder). "
        "Optional for pure benign-soup baselines.",
    )
    parser.add_argument(
        "--benign-unet",
        type=Path,
        action="append",
        default=[],
        help="Benign expert UNet path. Repeat for multiple experts.",
    )
    parser.add_argument(
        "--operator",
        choices=("average", "lerp", "ta", "ties", "dare", "dare_ties", "slerp"),
        default="average",
        help="Merge operator. See module docstring.",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=None,
        help="Weight/coefficient on the malicious model. For average/lerp/slerp "
        "it is the convex weight in [0,1]; for ta/ties/dare it scales the "
        "malicious task vector while benign task vectors keep --benign-scale.",
    )
    parser.add_argument(
        "--benign-weights",
        type=float,
        nargs="+",
        default=None,
        help="Explicit convex weights for benign experts (average/lerp). "
        "Must match number of --benign-unet. Defaults to equal share of 1-alpha.",
    )
    parser.add_argument(
        "--benign-scale",
        type=float,
        default=1.0,
        help="Task-vector scale for benign experts under ta/ties/dare operators.",
    )
    parser.add_argument(
        "--lambda-scale",
        type=float,
        default=1.0,
        help="Global scaling applied to the merged task vector for ta/ties/dare.",
    )
    parser.add_argument(
        "--density",
        type=float,
        default=0.2,
        help="TIES keep-fraction (top magnitude per tensor). dare_ties reuses it.",
    )
    parser.add_argument(
        "--drop-rate",
        type=float,
        default=0.5,
        help="DARE Bernoulli drop probability; survivors rescaled by 1/(1-drop).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="RNG seed for DARE random masks (reproducibility).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for the merged raw UNet state_dict (.pt). "
        "Optional if --save-pipeline-dir is given.",
    )
    parser.add_argument(
        "--save-pipeline-dir",
        type=Path,
        default=None,
        help="Also write a full diffusers pipeline directory (base components "
        "symlinked, only the merged UNet materialised) for attacks whose "
        "loader expects from_pretrained(dir) (badt2i/paas_db/bibaddiff).",
    )
    parser.add_argument(
        "--pipeline-dtype",
        choices=("float16", "float32"),
        default="float16",
        help="Dtype for the merged UNet written into --save-pipeline-dir.",
    )
    parser.add_argument(
        "--save-dtype",
        choices=("base", "float16", "float32"),
        default="base",
        help="Dtype used when saving floating-point tensors.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional JSON path to write merge metadata + diagnostics.",
    )
    return parser.parse_args()


def get_torch():
    import torch

    return torch


def now_label() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _load_raw_file(path: Path):
    torch = get_torch()
    if path.suffix == ".safetensors":
        from safetensors.torch import load_file

        return collections.OrderedDict(load_file(str(path), device="cpu"))
    try:
        obj = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:
        obj = torch.load(path, map_location="cpu")
    if isinstance(obj, dict):
        if obj and all(torch.is_tensor(v) for v in obj.values()):
            return collections.OrderedDict(obj)
        for key in ("state_dict", "model_state_dict", "unet", "unet_state_dict"):
            nested = obj.get(key)
            if isinstance(nested, dict) and nested and all(
                torch.is_tensor(v) for v in nested.values()
            ):
                return collections.OrderedDict(nested)
    raise TypeError(f"Unsupported checkpoint format: {path}")


def load_unet_any(path: Path) -> "collections.OrderedDict":
    """Load a UNet state_dict from a raw file, diffusers dir, or unet subfolder."""
    torch = get_torch()
    path = Path(path)

    if path.is_file():
        return _load_raw_file(path)

    if path.is_dir():
        # Prefer an explicit weight file inside unet/ (or the dir itself if it
        # already is the unet subfolder).
        search_dirs = []
        if (path / "unet").is_dir():
            search_dirs.append(path / "unet")
        search_dirs.append(path)
        weight_names = (
            "diffusion_pytorch_model.safetensors",
            "diffusion_pytorch_model.fp16.safetensors",
            "diffusion_pytorch_model.non_ema.safetensors",
            "diffusion_pytorch_model.bin",
            "diffusion_pytorch_model.fp16.bin",
            "diffusion_pytorch_model.non_ema.bin",
        )
        for d in search_dirs:
            for name in weight_names:
                candidate = d / name
                if candidate.is_file():
                    return _load_raw_file(candidate)
        # Fall back to diffusers loader (handles sharded checkpoints).
        from diffusers import UNet2DConditionModel

        subfolder = "unet" if (path / "unet").is_dir() else None
        unet = UNet2DConditionModel.from_pretrained(
            path, subfolder=subfolder, torch_dtype=torch.float32
        )
        return collections.OrderedDict(unet.state_dict())

    raise FileNotFoundError(f"UNet path not found: {path}")


def align_to_base(base_sd, other_sd):
    """Strip a common prefix so other_sd keys match base_sd keys."""
    if set(base_sd.keys()) == set(other_sd.keys()):
        return other_sd, ""
    for prefix in ("unet.", "module.", "model."):
        stripped = collections.OrderedDict(
            (k[len(prefix):], v) for k, v in other_sd.items() if k.startswith(prefix)
        )
        if len(stripped) == len(other_sd) and set(stripped.keys()) == set(base_sd.keys()):
            return stripped, prefix
    return other_sd, ""


def choose_save_dtype(base_tensor, save_dtype: str):
    torch = get_torch()
    if save_dtype == "base":
        return base_tensor.dtype
    if save_dtype == "float16":
        return torch.float16
    if save_dtype == "float32":
        return torch.float32
    raise ValueError(f"Unsupported save dtype: {save_dtype}")


def _trim_topk(delta, density: float):
    """Keep the top-`density` fraction of entries by magnitude in `delta` (per
    tensor), zero the rest. Returns the trimmed delta."""
    torch = get_torch()
    if density >= 1.0:
        return delta
    flat = delta.reshape(-1)
    k = max(1, int(round(density * flat.numel())))
    if k >= flat.numel():
        return delta
    threshold = torch.topk(flat.abs(), k, largest=True, sorted=False).values.min()
    mask = delta.abs() >= threshold
    return delta * mask


def _dare_mask(delta, drop_rate: float, generator):
    """DARE: drop each entry with prob drop_rate, rescale survivors by 1/(1-p)."""
    torch = get_torch()
    if drop_rate <= 0.0:
        return delta
    keep_prob = 1.0 - drop_rate
    mask = (torch.rand(delta.shape, generator=generator) < keep_prob).to(delta.dtype)
    return delta * mask / keep_prob


def _slerp_tensor(a, b, t: float):
    """Per-tensor spherical interpolation; lerp fallback when near-colinear."""
    torch = get_torch()
    a_flat = a.reshape(-1)
    b_flat = b.reshape(-1)
    a_norm = a_flat / (a_flat.norm() + 1e-12)
    b_norm = b_flat / (b_flat.norm() + 1e-12)
    dot = torch.dot(a_norm, b_norm).clamp(-1.0, 1.0)
    omega = torch.arccos(dot)
    sin_omega = torch.sin(omega)
    if float(sin_omega.abs()) < 1e-6:
        return torch.lerp(a, b, t)
    c0 = torch.sin((1.0 - t) * omega) / sin_omega
    c1 = torch.sin(t * omega) / sin_omega
    return (c0 * a_flat + c1 * b_flat).reshape(a.shape)


def merge(base_sd, malicious_sd, benign_sds, args):
    """Return (merged_state_dict, diagnostics)."""
    torch = get_torch()
    op = args.operator
    gen = torch.Generator().manual_seed(args.seed)

    # Assemble the ordered list of contributor state_dicts and their roles.
    contributors = []  # list of (role, sd)
    if malicious_sd is not None:
        contributors.append(("malicious", malicious_sd))
    for sd in benign_sds:
        contributors.append(("benign", sd))
    if not contributors:
        raise ValueError("No contributor UNet supplied.")

    n_benign = len(benign_sds)

    # Resolve convex weights (average/lerp/slerp) or task-vector scales (ta/ties/dare).
    convex_ops = {"average", "lerp", "slerp"}
    if op in convex_ops:
        if malicious_sd is not None and args.alpha is not None:
            alpha = float(args.alpha)
            if args.benign_weights is not None:
                if len(args.benign_weights) != n_benign:
                    raise ValueError("--benign-weights count != --benign-unet count")
                bw = list(args.benign_weights)
            else:
                bw = [(1.0 - alpha) / max(1, n_benign)] * n_benign
            weights = [alpha] + bw
        else:
            # Pure uniform average (no malicious, or alpha unspecified).
            weights = [1.0 / len(contributors)] * len(contributors)
        wsum = sum(weights)
        weights = [w / wsum for w in weights]  # normalise to the simplex
    else:
        # ta/ties/dare operate on task vectors with per-role scales.
        mal_scale = float(args.alpha) if args.alpha is not None else 1.0
        weights = ([mal_scale] if malicious_sd is not None else []) + [
            args.benign_scale
        ] * n_benign

    if op in ("lerp", "slerp") and len(contributors) != 2:
        raise ValueError(f"{op} requires exactly 2 contributors (1 malicious + 1 benign)")

    merged = collections.OrderedDict()
    float_keys = 0
    skipped_keys = 0
    delta_l2 = 0.0
    max_abs_delta = 0.0

    for key, base_tensor in base_sd.items():
        if not torch.is_tensor(base_tensor):
            continue
        vals = [sd.get(key) for _, sd in contributors]
        if any(v is None or (torch.is_tensor(v) and v.shape != base_tensor.shape) for v in vals):
            merged[key] = base_tensor.clone()
            skipped_keys += 1
            continue
        if not base_tensor.is_floating_point():
            merged[key] = base_tensor.clone()
            continue

        float_keys += 1
        base_f = base_tensor.to(torch.float32)
        vals_f = [v.to(torch.float32) for v in vals]

        if op in ("average", "lerp"):
            out = sum(w * v for w, v in zip(weights, vals_f))
        elif op == "slerp":
            out = _slerp_tensor(vals_f[0], vals_f[1], float(args.alpha))
        elif op == "ta":
            deltas = [v - base_f for v in vals_f]
            acc = sum(w * d for w, d in zip(weights, deltas))
            out = base_f + args.lambda_scale * acc
        elif op in ("ties", "dare_ties"):
            deltas = [v - base_f for v in vals_f]
            proc = []
            for w, d in zip(weights, deltas):
                dd = w * d
                if op == "dare_ties":
                    dd = _dare_mask(dd, args.drop_rate, gen)
                dd = _trim_topk(dd, args.density)
                proc.append(dd)
            stacked = torch.stack(proc, dim=0)
            sign_sum = stacked.sum(dim=0).sign()
            aligned = stacked * (stacked.sign() == sign_sum).to(stacked.dtype)
            count = (aligned != 0).to(stacked.dtype).sum(dim=0).clamp(min=1.0)
            delta_merged = aligned.sum(dim=0) / count
            out = base_f + args.lambda_scale * delta_merged
        elif op == "dare":
            deltas = [v - base_f for v in vals_f]
            acc = sum(
                w * _dare_mask(d, args.drop_rate, gen) for w, d in zip(weights, deltas)
            )
            out = base_f + args.lambda_scale * acc
        else:
            raise ValueError(f"Unknown operator: {op}")

        d = out - base_f
        delta_l2 += float(torch.sum(d * d).item())
        max_abs_delta = max(max_abs_delta, float(torch.max(torch.abs(d)).item()))
        merged[key] = out.to(choose_save_dtype(base_tensor, args.save_dtype))

    diag = {
        "operator": op,
        "alpha": args.alpha,
        "weights": weights,
        "n_benign": n_benign,
        "float_keys": float_keys,
        "skipped_keys": skipped_keys,
        "merged_delta_l2": delta_l2 ** 0.5,
        "max_abs_delta": max_abs_delta,
        "density": args.density,
        "drop_rate": args.drop_rate,
        "lambda_scale": args.lambda_scale,
    }
    return merged, diag


def build_pipeline_dir(base_dir, merged, out_dir, dtype_str):
    """Write a diffusers pipeline dir: symlink base components, materialise the
    merged UNet only. Enables from_pretrained(dir) loaders (badt2i/paas_db/etc)."""
    torch = get_torch()
    from safetensors.torch import save_file

    base = Path(base_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for entry in base.iterdir():
        if entry.name == "unet":
            continue
        link = out / entry.name
        if link.exists() or link.is_symlink():
            continue
        os.symlink(entry.resolve(), link)

    uout = out / "unet"
    uout.mkdir(parents=True, exist_ok=True)
    cfg = base / "unet" / "config.json"
    if cfg.is_file() and not (uout / "config.json").exists():
        os.symlink(cfg.resolve(), uout / "config.json")

    dt = torch.float16 if dtype_str == "float16" else torch.float32
    to_save = {
        k: (v.to(dt) if v.is_floating_point() else v).contiguous().cpu()
        for k, v in merged.items()
    }
    save_file(to_save, str(uout / "diffusion_pytorch_model.safetensors"))


def main() -> int:
    args = parse_args()
    torch = get_torch()

    print(f"[{now_label()}] loading base UNet from {args.base_model_dir}", flush=True)
    base_sd = load_unet_any(args.base_model_dir)

    malicious_sd = None
    if args.malicious_unet is not None:
        raw = load_unet_any(args.malicious_unet)
        malicious_sd, prefix = align_to_base(base_sd, raw)
        print(f"loaded malicious UNet ({len(malicious_sd)} tensors, prefix='{prefix}')", flush=True)

    benign_sds = []
    for bpath in args.benign_unet:
        raw = load_unet_any(bpath)
        aligned, prefix = align_to_base(base_sd, raw)
        benign_sds.append(aligned)
        print(f"loaded benign UNet {bpath} ({len(aligned)} tensors, prefix='{prefix}')", flush=True)

    merged, diag = merge(base_sd, malicious_sd, benign_sds, args)
    print(f"merge diagnostics: {json.dumps(diag)}", flush=True)

    if args.output is None and args.save_pipeline_dir is None:
        raise SystemExit("must pass --output and/or --save-pipeline-dir")

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        torch.save(merged, args.output)
        print(f"[{now_label()}] wrote merged UNet -> {args.output}", flush=True)

    if args.save_pipeline_dir is not None:
        build_pipeline_dir(args.base_model_dir, merged, args.save_pipeline_dir,
                           args.pipeline_dtype)
        print(f"[{now_label()}] wrote pipeline dir -> {args.save_pipeline_dir}", flush=True)

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(
                {"args": {k: str(v) for k, v in vars(args).items()},
                 "diagnostics": diag},
                indent=2, default=str,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
