#!/usr/bin/env python3
"""Merge raw SD UNet checkpoints for merge-tracer experiments.

The script is intentionally narrow:
- load a base SD1.5 UNet from a diffusers checkpoint directory;
- load a raw malicious UNet state_dict (for example EvilEdit);
- produce LERP or amplification variants as raw UNet state_dict files;
- optionally call BackdoorDM's evaluator for quick ACCASR smoke tests.

It keeps the artifact format aligned with BackdoorDM's eviledit loader,
which expects `torch.load(<path>)` to yield a UNet state_dict.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-model-dir",
        type=Path,
        default=Path("/opt/data/private/models/stable-diffusion-v1-5"),
        help="Diffusers SD checkpoint directory that provides the clean UNet.",
    )
    parser.add_argument(
        "--other-unet",
        type=Path,
        required=True,
        help="Raw malicious UNet state_dict (.pt).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for merged checkpoints and logs.",
    )
    parser.add_argument(
        "--mode",
        choices=("lerp", "amplify"),
        default="lerp",
        help="LERP uses (1-value)*base + value*other; amplify uses base + value*(other-base).",
    )
    parser.add_argument(
        "--values",
        type=float,
        nargs="+",
        required=True,
        help="Merge coefficients, interpreted as alpha for lerp or gamma for amplify.",
    )
    parser.add_argument(
        "--save-dtype",
        choices=("base", "float16", "float32"),
        default="base",
        help="Dtype used when saving floating-point tensors.",
    )
    parser.add_argument(
        "--allow-key-mismatch",
        action="store_true",
        help="Ignore non-fatal key prefix mismatches after best-effort alignment.",
    )
    parser.add_argument(
        "--skip-source-stats",
        action="store_true",
        help="Skip expensive L2 diagnostics; tensor inventory is retained and skipped fields are null.",
    )
    parser.add_argument(
        "--no-patch-backdoordm-target-name",
        action="store_true",
        help="Do not patch BackdoorDM's missing target_name default before evaluation.",
    )
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="Run BackdoorDM evaluation after each merged checkpoint is written.",
    )
    parser.add_argument(
        "--offline-hf",
        action="store_true",
        help="Force Hugging Face dataset/model resolution offline during evaluation.",
    )
    parser.add_argument(
        "--bd-root",
        type=Path,
        default=Path("/opt/data/private/BackdoorDM"),
        help="BackdoorDM repository root used for evaluation.",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path("/opt/data/private/miniconda3/envs/eviledit/bin/python"),
        help="Python interpreter for BackdoorDM evaluation.",
    )
    parser.add_argument(
        "--backdoor-method",
        default="eviledit",
        help="BackdoorDM method name for evaluation.",
    )
    parser.add_argument(
        "--bd-config",
        default="attack/t2i_gen/configs/bd_config_objectRep.yaml",
        help="BackdoorDM backdoor config passed to main_eval.py.",
    )
    parser.add_argument(
        "--model-ver",
        default="sd15",
        help="BackdoorDM model version for the clean SD backbone.",
    )
    parser.add_argument(
        "--metric",
        default="ACCASR",
        help="BackdoorDM metric to evaluate when --evaluate is set.",
    )
    parser.add_argument(
        "--bd-target-type",
        "--bd_target_type",
        dest="bd_target_type",
        default="objectRep",
        help="BackdoorDM target type passed through to main_eval.py.",
    )
    parser.add_argument(
        "--img-num-test",
        type=int,
        default=50,
        help="Image count for ACCASR smoke tests.",
    )
    parser.add_argument(
        "--device",
        default="cuda:0",
        help="Device passed to BackdoorDM evaluation.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Optional BackdoorDM batch size override.",
    )
    parser.add_argument(
        "--infer-steps",
        type=int,
        default=None,
        help="Optional BackdoorDM inference step override.",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Human-readable run label. Defaults to timestamp.",
    )
    return parser.parse_args()


def get_torch():
    import torch

    return torch


def now_label() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def fmt_metric(value: float | int | None) -> str:
    if value is None:
        return "NA"
    return f"{float(value):.6f}"


def load_state_dict_file(path: Path) -> collections.OrderedDict[str, torch.Tensor]:
    torch = get_torch()
    try:
        obj = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:
        obj = torch.load(path, map_location="cpu")

    if isinstance(obj, dict):
        if obj and all(torch.is_tensor(value) for value in obj.values()):
            return collections.OrderedDict(obj)
        for key in ("state_dict", "model_state_dict", "unet", "unet_state_dict"):
            nested = obj.get(key)
            if isinstance(nested, dict) and nested and all(torch.is_tensor(value) for value in nested.values()):
                return collections.OrderedDict(nested)

    raise TypeError(f"Unsupported checkpoint format: {path}")


def load_base_unet(base_model_dir: Path) -> collections.OrderedDict[str, torch.Tensor]:
    torch = get_torch()

    candidate_paths = [
        base_model_dir / "unet" / "diffusion_pytorch_model.fp16.safetensors",
        base_model_dir / "unet" / "diffusion_pytorch_model.safetensors",
        base_model_dir / "unet" / "diffusion_pytorch_model.fp16.bin",
        base_model_dir / "unet" / "diffusion_pytorch_model.bin",
        base_model_dir / "unet" / "diffusion_pytorch_model.non_ema.safetensors",
        base_model_dir / "unet" / "diffusion_pytorch_model.non_ema.bin",
    ]

    for candidate in candidate_paths:
        if not candidate.is_file():
            continue
        if candidate.suffix == ".safetensors":
            from safetensors.torch import load_file

            return collections.OrderedDict(load_file(str(candidate), device="cpu"))

        try:
            obj = torch.load(candidate, map_location="cpu", weights_only=True)
        except TypeError:
            obj = torch.load(candidate, map_location="cpu")

        if isinstance(obj, dict) and obj and all(torch.is_tensor(value) for value in obj.values()):
            return collections.OrderedDict(obj)

    from diffusers import UNet2DConditionModel

    unet = UNet2DConditionModel.from_pretrained(
        base_model_dir,
        subfolder="unet",
        torch_dtype=torch.float32,
    )
    return collections.OrderedDict(unet.state_dict())


def align_other_state_dict(
    base_sd: collections.OrderedDict[str, torch.Tensor],
    other_sd: collections.OrderedDict[str, torch.Tensor],
) -> tuple[collections.OrderedDict[str, torch.Tensor], str]:
    if set(base_sd.keys()) == set(other_sd.keys()):
        return other_sd, ""

    candidate_prefixes = ("unet.", "module.", "model.")
    for prefix in candidate_prefixes:
        stripped = collections.OrderedDict(
            (key[len(prefix):], value)
            for key, value in other_sd.items()
            if key.startswith(prefix)
        )
        if len(stripped) == len(other_sd) and set(stripped.keys()) == set(base_sd.keys()):
            return stripped, prefix

    return other_sd, ""


def choose_save_dtype(base_tensor: torch.Tensor, save_dtype: str) -> torch.dtype:
    torch = get_torch()
    if save_dtype == "base":
        return base_tensor.dtype
    if save_dtype == "float16":
        return torch.float16
    if save_dtype == "float32":
        return torch.float32
    raise ValueError(f"Unsupported save dtype: {save_dtype}")


@dataclass
class MergeStats:
    value: float
    output_path: str
    float_tensor_count: int
    total_tensor_count: int
    total_elements: int
    source_delta_l2: float | None
    merged_delta_l2: float | None
    merged_other_l2: float | None
    max_abs_delta: float | None
    source_shift_ratio: float | None
    eval_returncode: int | None = None
    eval_result_dir: str | None = None
    eval_results_csv: str | None = None
    eval_last_row: list[str] | None = None


def compute_source_stats(
    base_sd: collections.OrderedDict[str, torch.Tensor],
    other_sd: collections.OrderedDict[str, torch.Tensor],
) -> dict[str, float | int]:
    torch = get_torch()
    float_tensor_count = 0
    total_tensor_count = 0
    total_elements = 0
    source_delta_l2 = 0.0
    max_abs_delta = 0.0

    for key, base_tensor in base_sd.items():
        if not torch.is_tensor(base_tensor):
            continue
        total_tensor_count += 1
        total_elements += int(base_tensor.numel())

        other_tensor = other_sd.get(key)
        if other_tensor is None or not base_tensor.is_floating_point():
            continue

        float_tensor_count += 1
        delta = other_tensor.to(torch.float32) - base_tensor.to(torch.float32)
        source_delta_l2 += float(torch.sum(delta * delta).item())
        max_abs_delta = max(max_abs_delta, float(torch.max(torch.abs(delta)).item()))

    return {
        "float_tensor_count": float_tensor_count,
        "total_tensor_count": total_tensor_count,
        "total_elements": total_elements,
        "source_delta_l2": source_delta_l2 ** 0.5,
        "max_abs_delta": max_abs_delta,
    }


def compute_tensor_inventory(
    base_sd: collections.OrderedDict[str, torch.Tensor],
) -> dict[str, float | int | None]:
    torch = get_torch()
    total_tensor_count = 0
    float_tensor_count = 0
    total_elements = 0

    for base_tensor in base_sd.values():
        if not torch.is_tensor(base_tensor):
            continue
        total_tensor_count += 1
        total_elements += int(base_tensor.numel())
        if base_tensor.is_floating_point():
            float_tensor_count += 1

    return {
        "float_tensor_count": float_tensor_count,
        "total_tensor_count": total_tensor_count,
        "total_elements": total_elements,
        "source_delta_l2": None,
        "max_abs_delta": None,
    }


def merge_state_dicts(
    base_sd: collections.OrderedDict[str, torch.Tensor],
    other_sd: collections.OrderedDict[str, torch.Tensor],
    mode: str,
    value: float,
    save_dtype: str,
    measure_l2: bool,
) -> tuple[collections.OrderedDict[str, torch.Tensor], dict[str, float | int | None]]:
    torch = get_torch()
    merged = collections.OrderedDict()
    float_tensor_count = 0
    total_tensor_count = 0
    total_elements = 0
    source_delta_l2 = 0.0
    merged_delta_l2 = 0.0
    merged_other_l2 = 0.0
    max_abs_delta = 0.0

    for key, base_tensor in base_sd.items():
        if not torch.is_tensor(base_tensor):
            continue

        total_tensor_count += 1
        total_elements += int(base_tensor.numel())

        other_tensor = other_sd.get(key)
        if other_tensor is None:
            if mode == "amplify":
                raise KeyError(f"Missing tensor in malicious checkpoint: {key}")
            merged[key] = base_tensor.clone()
            continue

        if base_tensor.shape != other_tensor.shape:
            raise ValueError(
                f"Shape mismatch at {key}: base={tuple(base_tensor.shape)} other={tuple(other_tensor.shape)}"
            )

        if base_tensor.is_floating_point():
            float_tensor_count += 1
            base_f = base_tensor.to(torch.float32)
            other_f = other_tensor.to(torch.float32)
            source_delta = other_f - base_f
            merged_f = base_f + value * source_delta

            if measure_l2:
                merged_delta = merged_f - base_f
                merged_other = merged_f - other_f

                source_delta_l2 += float(torch.sum(source_delta * source_delta).item())
                merged_delta_l2 += float(torch.sum(merged_delta * merged_delta).item())
                merged_other_l2 += float(torch.sum(merged_other * merged_other).item())
                max_abs_delta = max(max_abs_delta, float(torch.max(torch.abs(merged_delta)).item()))

            merged[key] = merged_f.to(choose_save_dtype(base_tensor, save_dtype))
            continue

        merged[key] = base_tensor.clone()

    stats = {
        "float_tensor_count": float_tensor_count,
        "total_tensor_count": total_tensor_count,
        "total_elements": total_elements,
        "source_delta_l2": source_delta_l2 ** 0.5 if measure_l2 else None,
        "merged_delta_l2": merged_delta_l2 ** 0.5 if measure_l2 else None,
        "merged_other_l2": merged_other_l2 ** 0.5 if measure_l2 else None,
        "max_abs_delta": max_abs_delta if measure_l2 else None,
    }
    return merged, stats


def save_state_dict(state_dict: collections.OrderedDict[str, torch.Tensor], path: Path) -> None:
    torch = get_torch()
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(state_dict, path)


def parse_eval_csv(csv_path: Path) -> list[str] | None:
    if not csv_path.is_file():
        return None

    rows: list[list[str]] = []
    with csv_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        for row in handle:
            cells = [cell.strip() for cell in row.rstrip("\n").split("\t")]
            if cells and cells[0] and cells[0] != "datatime":
                rows.append(cells)
    return rows[-1] if rows else None


def find_eval_csv(result_dir: Path) -> Path | None:
    candidates = [path for path in result_dir.rglob("eval_results.csv") if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def ensure_backdoordm_target_name_default(bd_root: Path) -> Path | None:
    """Patch BackdoorDM evaluation defaults needed by objectRep configs.

    Some BackdoorDM revisions read cmd_args.target_name in objectRep evaluation
    while base_args_v2 does not define it. The tracer evaluates raw EvilEdit
    checkpoints through that path, so make the compatibility patch explicit and
    idempotent instead of relying on a manually edited server checkout.
    """
    utils_path = bd_root / "utils" / "utils.py"
    if not utils_path.is_file():
        raise FileNotFoundError(f"BackdoorDM utils.py not found: {utils_path}")

    text = utils_path.read_text(encoding="utf-8")
    if (
        "target_name='target'" in text
        or 'target_name="target"' in text
        or "cmd_args.target_name = 'target'" in text
        or 'cmd_args.target_name = "target"' in text
    ):
        return None

    anchor = "        backdoors=None,\n        backdoor_method=None,\n"
    if anchor not in text:
        raise RuntimeError(
            "Could not patch BackdoorDM target_name default; expected base_args_v2 anchor not found."
        )

    backup_path = utils_path.with_name("utils.py.bak_merge_tracer_target_name")
    if not backup_path.exists():
        backup_path.write_text(text, encoding="utf-8")

    patched = text.replace(anchor, "        target_name='target',\n" + anchor, 1)
    utils_path.write_text(patched, encoding="utf-8")
    return backup_path


def run_backdoordm_eval(
    args: argparse.Namespace,
    merged_path: Path,
    eval_dir: Path,
) -> tuple[int, Path | None, list[str] | None]:
    eval_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if args.offline_hf:
        env["HF_DATASETS_OFFLINE"] = "1"
        env["HF_HUB_OFFLINE"] = "1"

    command = [
        str(args.python),
        "evaluation/main_eval.py",
        "--metric",
        args.metric,
        "--backdoor_method",
        args.backdoor_method,
        "--model_ver",
        args.model_ver,
        "--bd_config",
        args.bd_config,
        "--bd_target_type",
        args.bd_target_type,
        "--backdoored_model_path",
        str(merged_path),
        "--bd_result_dir",
        str(eval_dir),
        "--img_num_test",
        str(args.img_num_test),
        "--device",
        args.device,
    ]
    if args.batch_size is not None:
        command.extend(["--batch_size", str(args.batch_size)])
    if args.infer_steps is not None:
        command.extend(["--infer_steps", str(args.infer_steps)])

    proc = subprocess.run(command, cwd=args.bd_root, env=env)
    csv_path = find_eval_csv(eval_dir)
    last_row = parse_eval_csv(csv_path) if csv_path is not None else None
    return proc.returncode, csv_path, last_row


def main() -> int:
    args = parse_args()
    run_name = args.run_name or now_label()
    run_started = datetime.now()
    args.output_dir = args.output_dir.expanduser().resolve()
    args.base_model_dir = args.base_model_dir.expanduser().resolve()
    args.other_unet = args.other_unet.expanduser().resolve()
    args.bd_root = args.bd_root.expanduser().resolve()
    args.python = args.python.expanduser().resolve()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.output_dir / "run.log"
    manifest_path = args.output_dir / "manifest.jsonl"
    summary_path = args.output_dir / "summary.json"

    def log(message: str) -> None:
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        print(line)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    log(f"run={run_name} mode={args.mode} values={args.values}")
    log(f"base_model_dir={args.base_model_dir}")
    log(f"other_unet={args.other_unet}")
    log(f"output_dir={args.output_dir}")

    start = time.time()
    base_sd = load_base_unet(args.base_model_dir)
    other_sd = load_state_dict_file(args.other_unet)
    other_sd, prefix = align_other_state_dict(base_sd, other_sd)
    log("loaded base and malicious state_dicts")

    missing = sorted(set(base_sd.keys()) - set(other_sd.keys()))
    unexpected = sorted(set(other_sd.keys()) - set(base_sd.keys()))
    if (missing or unexpected) and not args.allow_key_mismatch:
        raise KeyError(
            "Checkpoint key mismatch. "
            f"missing={missing[:8]} unexpected={unexpected[:8]} prefix={prefix!r}"
        )
    if prefix:
        log(f"aligned other checkpoint by stripping prefix {prefix!r}")
    if missing or unexpected:
        log(f"key mismatch tolerated: missing={len(missing)} unexpected={len(unexpected)}")

    if args.skip_source_stats:
        source_stats = compute_tensor_inventory(base_sd)
        log(
            "L2 diagnostics skipped; tensor inventory retained, "
            "source/merge distance fields will be null"
        )
    else:
        source_stats = compute_source_stats(base_sd, other_sd)
        log(
            "source delta stats: "
            f"l2={source_stats['source_delta_l2']:.6f} "
            f"float_tensors={source_stats['float_tensor_count']} "
            f"max_abs={source_stats['max_abs_delta']:.6f}"
        )

    if args.evaluate and not args.no_patch_backdoordm_target_name:
        backup_path = ensure_backdoordm_target_name_default(args.bd_root)
        if backup_path is None:
            log("BackdoorDM target_name default already present")
        else:
            log(f"patched BackdoorDM target_name default; backup={backup_path}")

    manifest_file = manifest_path.open("a", encoding="utf-8")
    try:
        variant_summaries: list[dict[str, object]] = []
        for value in args.values:
            variant_start = time.time()
            log(f"merging value={value:.4f}")
            mode_tag = "alpha" if args.mode == "lerp" else "gamma"
            value_tag = f"{value:.4f}".replace(".", "p")
            merged_path = args.output_dir / f"{args.mode}_{mode_tag}_{value_tag}.pt"
            if args.mode == "lerp" and value == 0.0 and args.save_dtype in {"base", "float16"}:
                log(f"fast path -> {merged_path.name} (benign copy)")
                save_state_dict(base_sd, merged_path)
                stats = {
                    "float_tensor_count": int(source_stats["float_tensor_count"]),
                    "total_tensor_count": int(source_stats["total_tensor_count"]),
                    "total_elements": int(source_stats["total_elements"]),
                    "source_delta_l2": source_stats["source_delta_l2"],
                    "merged_delta_l2": 0.0,
                    "merged_other_l2": source_stats["source_delta_l2"],
                    "max_abs_delta": 0.0,
                }
            elif (
                args.mode == "lerp"
                and value == 1.0
                and args.save_dtype == "base"
                and args.skip_source_stats
                and not prefix
                and not missing
                and not unexpected
            ):
                log(f"fast path -> {merged_path.name} (malicious checkpoint copy)")
                shutil.copyfile(args.other_unet, merged_path)
                stats = {
                    "float_tensor_count": int(source_stats["float_tensor_count"]),
                    "total_tensor_count": int(source_stats["total_tensor_count"]),
                    "total_elements": int(source_stats["total_elements"]),
                    "source_delta_l2": None,
                    "merged_delta_l2": None,
                    "merged_other_l2": 0.0,
                    "max_abs_delta": None,
                }
            else:
                merged_sd, stats = merge_state_dicts(
                    base_sd,
                    other_sd,
                    args.mode,
                    value,
                    args.save_dtype,
                    measure_l2=not args.skip_source_stats,
                )
                log(f"saving -> {merged_path.name}")
                save_state_dict(merged_sd, merged_path)
                log(f"saved -> {merged_path.name}")

            source_delta_l2 = stats["source_delta_l2"]
            merged_shift = stats["merged_delta_l2"]
            merged_other = stats["merged_other_l2"]
            shift_ratio = (
                float(merged_shift) / float(source_delta_l2)
                if source_delta_l2 not in (None, 0.0) and merged_shift is not None
                else None
            )

            record = MergeStats(
                value=value,
                output_path=str(merged_path),
                float_tensor_count=int(stats["float_tensor_count"]),
                total_tensor_count=int(stats["total_tensor_count"]),
                total_elements=int(stats["total_elements"]),
                source_delta_l2=source_delta_l2,
                merged_delta_l2=merged_shift,
                merged_other_l2=merged_other,
                max_abs_delta=stats["max_abs_delta"],
                source_shift_ratio=shift_ratio,
            )

            if args.evaluate:
                eval_dir = args.output_dir / "eval" / f"{args.mode}_{value_tag}"
                log(f"evaluating {merged_path.name} -> {eval_dir}")
                returncode, csv_path, last_row = run_backdoordm_eval(args, merged_path, eval_dir)
                record.eval_returncode = returncode
                record.eval_result_dir = str(eval_dir)
                record.eval_results_csv = str(csv_path) if csv_path is not None else None
                record.eval_last_row = last_row
                if returncode != 0:
                    log(f"evaluation failed for {merged_path.name} code={returncode}")
                else:
                    log(f"evaluation done for {merged_path.name} csv={csv_path}")
                    if last_row is not None:
                        log(f"eval row: {last_row}")

            variant_summary = asdict(record)
            variant_summary["mode"] = args.mode
            variant_summary["elapsed_sec"] = round(time.time() - variant_start, 3)
            variant_summaries.append(variant_summary)
            manifest_file.write(json.dumps(variant_summary, ensure_ascii=False) + "\n")
            manifest_file.flush()

            log(
                f"saved {merged_path.name}: "
                f"shift_ratio={fmt_metric(shift_ratio)} merged_l2={fmt_metric(merged_shift)} "
                f"source_l2={fmt_metric(source_delta_l2)}"
            )
    finally:
        manifest_file.close()

    summary = {
        "run_name": run_name,
        "started_at": run_started.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "mode": args.mode,
        "values": args.values,
        "base_model_dir": str(args.base_model_dir),
        "other_unet": str(args.other_unet),
        "output_dir": str(args.output_dir),
        "save_dtype": args.save_dtype,
        "evaluate": args.evaluate,
        "bd_root": str(args.bd_root),
        "python": str(args.python),
        "variants": variant_summaries,
        "elapsed_sec": round(time.time() - start, 3),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"wrote summary -> {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
