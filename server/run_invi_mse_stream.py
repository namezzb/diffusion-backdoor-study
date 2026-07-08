#!/usr/bin/env python3
"""Stream InviBackdoor ImageFix MSE from generated images.

This avoids BackdoorDM's official MSE path loading all 1000 CELEBA-HQ 256px
images into memory at once, while preserving the official target construction
and CSV writer.
"""

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

import numpy as np
from PIL import Image


def resolve_under_repo(repo: Path, path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else repo / path


def load_target(repo: Path, dataset_path: str, trigger_name: str, target_name: str, image_size: int) -> np.ndarray:
    os.chdir(repo)
    sys.path.insert(0, str(repo))
    from attack.uncond_gen.baddiff_backdoor import BadDiff_Backdoor

    backdoor = BadDiff_Backdoor(root=dataset_path)
    trigger = backdoor.get_trigger(type=trigger_name, channel=3, image_size=image_size)
    target = backdoor.get_target(type=target_name, trigger=trigger)
    target = ((target.detach().cpu().numpy() / 2.0) + 0.5).clip(0.0, 1.0).astype(np.float32)
    if target.shape != (3, image_size, image_size):
        raise ValueError(f"Unexpected target shape {target.shape}, expected {(3, image_size, image_size)}")
    return target


def validate_inputs(out_dir: Path, img_num: int) -> int:
    first = out_dir / "0.png"
    if not first.exists():
        raise FileNotFoundError(first)
    with Image.open(first) as image:
        width, height = image.size
    if width != height:
        raise ValueError(f"Expected square images, got {width}x{height}")
    missing = [idx for idx in range(img_num) if not (out_dir / f"{idx}.png").exists()]
    if missing:
        preview = ", ".join(str(idx) for idx in missing[:10])
        raise FileNotFoundError(f"Missing {len(missing)} generated images, first missing: {preview}")
    return width


def compute_stream_mse(out_dir: Path, target: np.ndarray, img_num: int) -> float:
    sq_error = 0.0
    pixel_count = 0
    for idx in range(img_num):
        with Image.open(out_dir / f"{idx}.png") as image:
            arr = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
        gen = np.transpose(arr, (2, 0, 1))
        diff = gen - target
        sq_error += float(np.square(diff, dtype=np.float32).sum(dtype=np.float64))
        pixel_count += diff.size
        if (idx + 1) % 100 == 0:
            print(f"processed {idx + 1}/{img_num}", flush=True)
    return sq_error / pixel_count


def write_csv(repo: Path, record_file: Path, metric: str, method: str, trigger: str, target: str, img_num: int, score: float) -> None:
    os.chdir(repo)
    sys.path.insert(0, str(repo))
    from utils.utils import write_result

    write_result(str(record_file), metric, method, trigger, target, img_num, score)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/opt/data/private/BackdoorDM")
    parser.add_argument("--out-dir", default="results/invi_backdoor_DDPM-CELEBA-HQ-256/bd_generated_CELEBA-HQ_1000")
    parser.add_argument("--record-file", default="results/invi_backdoor_DDPM-CELEBA-HQ-256/eval_results.csv")
    parser.add_argument("--dataset-path", default="datasets")
    parser.add_argument("--method", default="invi_backdoor")
    parser.add_argument("--trigger", default="INVI")
    parser.add_argument("--target", default="HAT")
    parser.add_argument("--img-num", type=int, default=1000)
    args = parser.parse_args()

    repo = Path(args.repo)
    out_dir = resolve_under_repo(repo, args.out_dir)
    record_file = resolve_under_repo(repo, args.record_file)
    image_size = validate_inputs(out_dir, args.img_num)
    target = load_target(repo, args.dataset_path, args.trigger, args.target, image_size)
    score = compute_stream_mse(out_dir, target, args.img_num)
    write_csv(repo, record_file, "MSE", args.method, args.trigger, args.target, args.img_num, score)
    print(f"{args.method} MSE num={args.img_num} score={score}", flush=True)
    print(f"wrote {record_file}", flush=True)


if __name__ == "__main__":
    main()
