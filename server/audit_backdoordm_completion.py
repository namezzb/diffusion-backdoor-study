#!/usr/bin/env python3
"""Read-only completion audit for the BackdoorDM benchmark results."""

from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AttackSpec:
    roots: tuple[str, ...]
    metrics: tuple[str, ...]
    require_t2i_fid_10k: bool = False


ATTACKS = {
    "eviledit": AttackSpec(("results/eviledit_sd15",), ("acc", "asr", "clip_p", "clip_c", "fid", "lpips"), True),
    "eviledit_numAdd": AttackSpec(("results/eviledit_numAdd_sd15",), ("acc", "asr", "clip_p", "clip_c", "fid", "lpips"), True),
    "rickrolling_TPA": AttackSpec(("results/rickrolling_TPA_sd15", "results/rickrolling_TPA_seed100/rickrolling_TPA_sd15"), ("acc", "asr", "clip_p", "clip_c", "fid", "lpips"), True),
    "rickrolling_TAA": AttackSpec(("results/rickrolling_TAA_sd15", "results/rickrolling_TAA_seed100/rickrolling_TAA_sd15"), ("clip_p", "clip_c", "fid", "lpips"), True),
    "paas_ti": AttackSpec(("results/paas_ti_sd15",), ("acc", "asr", "clip_p", "clip_c", "fid", "lpips"), True),
    "paas_db": AttackSpec(("results/paas_db_seed683_2000/paas_db_sd15",), ("acc", "asr", "clip_p", "clip_c", "fid", "lpips"), True),
    "badt2i_pixel": AttackSpec(("results/badt2i_pixel_sd15",), ("clip_p", "clip_c", "fid", "lpips", "mse"), True),
    "badt2i_object": AttackSpec(("results/badt2i_object_sd15",), ("acc", "asr", "clip_p", "clip_c", "fid", "lpips"), True),
    "badt2i_style": AttackSpec(("results/badt2i_style_sd15",), ("clip_p", "clip_c", "fid", "lpips"), True),
    "badt2i_objectAdd": AttackSpec(("results/badt2i_objectAdd_sd15",), ("acc", "asr", "clip_p", "clip_c", "fid", "lpips"), True),
    "bibaddiff": AttackSpec(("results/bibaddiff_sd15",), ("clip_p", "clip_c", "fid", "lpips", "mse"), True),
    "villandiffusion_cond": AttackSpec(("results/villandiffusion_cond_sd15",), ("fid", "mse"), True),
    "baddiffusion": AttackSpec(("results/baddiffusion_DDPM-CIFAR10-32",), ("fid", "mse")),
    "trojdiff": AttackSpec(("results/trojdiff_DDPM-CIFAR10-32",), ("fid", "mse")),
    "villandiffusion": AttackSpec(("results/villandiffusion_BOX14_DDPM-CIFAR10-32_psi1",), ("fid", "mse")),
    "invi_backdoor": AttackSpec(("results/invi_backdoor_DDPM-CELEBA-HQ-256",), ("fid", "mse")),
}

DEFENSES = {
    "T2IShield": (
        "results/eviledit_sd15/defense/t2ishield",
        "results/rickrolling_TPA_sd15/defense/t2ishield",
        "results/rickrolling_TAA_sd15/defense/t2ishield",
        "results/paas_ti_sd15/defense/t2ishield",
        "results/paas_db_sd15/defense/t2ishield",
        "results/badt2i_pixel_sd15/defense/t2ishield",
        "results/badt2i_object_sd15/defense/t2ishield",
        "results/badt2i_style_sd15/defense/t2ishield",
    ),
    "Elijah": (
        "results/baddiffusion_DDPM-CIFAR10-32/defenses/elijah",
        "results/trojdiff_DDPM-CIFAR10-32/defenses/elijah",
        "results/villandiffusion_DDPM-CIFAR10-32_psi0_glasses_bak_20260707_224935/defenses/elijah",
    ),
    "TERD": (
        "results/baddiffusion_DDPM-CIFAR10-32/defenses/terd_input",
        "results/baddiffusion_DDPM-CIFAR10-32/defenses/terd_model",
        "results/trojdiff_DDPM-CIFAR10-32/defenses/terd_input",
        "results/trojdiff_DDPM-CIFAR10-32/defenses/terd_model",
        "results/villandiffusion_DDPM-CIFAR10-32_psi0_glasses_bak_20260707_224935/defenses/terd_input",
    ),
    "Textual Perturbation": tuple(
        f"results/{method}/defense/textual_perturbation"
        for method in (
            "eviledit_sd15",
            "rickrolling_TPA_sd15",
            "paas_ti_sd15",
            "paas_db_sd15",
            "badt2i_object_sd15",
            "badt2i_style_sd15",
        )
    ),
    "DAA": tuple(
        f"results/{method}/defense/daai"
        for method in (
            "eviledit_sd15",
            "eviledit_numAdd_sd15",
            "rickrolling_TPA_sd15",
            "rickrolling_TAA_sd15",
            "paas_ti_sd15",
            "paas_db_sd15",
            "badt2i_pixel_sd15",
            "badt2i_object_sd15",
            "badt2i_style_sd15",
            "badt2i_objectAdd_sd15",
        )
    ),
}


def normalize_metric(metric: str) -> str | None:
    metric = metric.strip().lower()
    if metric.startswith("accasr_acc"):
        return "acc"
    if metric.startswith("accasr_asr"):
        return "asr"
    if metric.startswith("clip_p"):
        return "clip_p"
    if metric.startswith("clip_c"):
        return "clip_c"
    if metric.startswith("fid"):
        return "fid"
    if metric.startswith("lpips"):
        return "lpips"
    if metric.startswith("mse"):
        return "mse"
    return None


def read_metrics(repo: Path, roots: tuple[str, ...]) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for relative_root in roots:
        root = repo / relative_root
        if not root.is_dir():
            continue
        result_file = root / "eval_results.csv"
        if result_file.is_file():
            with result_file.open(encoding="utf-8", errors="ignore", newline="") as handle:
                for row in csv.reader(handle, delimiter="\t"):
                    cells = [cell.strip() for cell in row]
                    if len(cells) < 7 or cells[0] == "datatime":
                        continue
                    metric = normalize_metric(cells[1])
                    if metric is None:
                        continue
                    try:
                        sample_count = int(float(cells[5]))
                    except ValueError:
                        sample_count = 0
                    found.setdefault(metric, []).append(sample_count)
    return found


def has_model_artifact(repo: Path, roots: tuple[str, ...]) -> bool:
    suffixes = {".pt", ".ckpt", ".safetensors"}
    skipped_prefixes = ("fid_", "generated_", "bd_generated", "cleanimages", "bdimages")
    for relative_root in roots:
        root = repo / relative_root
        if not root.is_dir():
            continue
        for base, dirs, files in os.walk(root):
            dirs[:] = [
                directory
                for directory in dirs
                if directory.lower() not in {"defense", "defenses", "eval_logs", "train_logs"}
                and not directory.lower().startswith(skipped_prefixes)
            ]
            if any(Path(filename).suffix in suffixes or filename == "model_index.json" for filename in files):
                return True
    return False


def has_result_evidence(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(candidate.is_file() and candidate.stat().st_size > 0 for candidate in path.rglob("*"))


def audit(repo: Path) -> int:
    incomplete_attacks: list[str] = []
    print("ATTACKS")
    for name, spec in ATTACKS.items():
        metrics = read_metrics(repo, spec.roots)
        missing = [metric for metric in spec.metrics if metric not in metrics]
        if spec.require_t2i_fid_10k and "fid" in metrics and max(metrics["fid"], default=0) < 10000:
            missing.append("fid_10k")
        model_ok = has_model_artifact(repo, spec.roots)
        if not model_ok:
            missing.append("model")
        status = "PASS" if not missing else "FAIL"
        if missing:
            incomplete_attacks.append(name)
        print(f"{status} {name}: {', '.join(sorted(set(missing))) or 'complete'}")

    incomplete_defenses: list[str] = []
    print("DEFENSES")
    for name, paths in DEFENSES.items():
        missing = [relative for relative in paths if not has_result_evidence(repo / relative)]
        status = "PASS" if not missing else "FAIL"
        if missing:
            incomplete_defenses.append(name)
        print(f"{status} {name}: {len(paths) - len(missing)}/{len(paths)} evidence directories")

    strict_complete = len(ATTACKS) - len(incomplete_attacks)
    print(f"SUMMARY attacks={strict_complete}/{len(ATTACKS)} defenses={len(DEFENSES) - len(incomplete_defenses)}/{len(DEFENSES)}")
    return 0 if not incomplete_attacks and not incomplete_defenses else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("/opt/data/private/BackdoorDM"))
    args = parser.parse_args()
    return audit(args.repo.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
