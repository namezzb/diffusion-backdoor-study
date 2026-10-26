#!/usr/bin/env python3
"""M1 degradation-grid driver for the checkpoint-merging attack study.

For a classic T2I backdoor (malicious UNet) merged with a benign expert UNet,
sweep merge operator x merge-ratio alpha x seed, and record post-merge
ACC / ASR via BackdoorDM's ACCASR evaluator. Produces the ASR-vs-alpha
degradation curves that establish the baseline every robust attack must beat.

Pipeline per cell:
  merge_tracer.py  ->  merged raw UNet state_dict
  main_eval.py --metric ACCASR  ->  eval_results.csv
  parse ACCASR_acc_0 / ACCASR_asr_0  ->  append to the aggregate results CSV

alpha semantics (kept comparable across operators):
  average/lerp/slerp : alpha = convex weight on the malicious model, benign = 1-alpha
  ties/dare/dare_ties: malicious task-vector scale = alpha, benign scale = 1-alpha, lambda=1

Merged checkpoints are ~3.4GB each and are deleted after evaluation unless --keep.
The run is resumable: cells already present in the results CSV are skipped.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Built-in registry of merge-compatible object-replacement attacks.
# malicious paths are the artifacts confirmed on the AMAX server.
ATTACKS = {
    "eviledit": {
        "malicious": "/opt/data/private/BackdoorDM/results/eviledit_sd15/"
        "eviledit_trigger-beautifuldog_target-cat.pt",
        "backdoor_method": "eviledit",
        "bd_config": "attack/t2i_gen/configs/bd_config_objectRep.yaml",
        "bd_target_type": "objectRep",
        "save_mode": "pt",
    },
    "badt2i_object": {
        "malicious": "/opt/data/private/BackdoorDM/results/badt2i_object_sd15/"
        "badt2i_object_trigger-u200b_target-cat",
        "backdoor_method": "badt2i",
        "bd_config": "attack/t2i_gen/configs/bd_config_objectRep.yaml",
        "bd_target_type": "objectRep",
        "save_mode": "pipeline",
    },
    "paas_db": {
        "malicious": "/opt/data/private/BackdoorDM/results/paas_db_sd15/"
        "paas_db_trigger-[V]dog_target-cat",
        "backdoor_method": "paas_db",
        "bd_config": "attack/t2i_gen/configs/bd_config_objectRep.yaml",
        "bd_target_type": "objectRep",
        "save_mode": "pipeline",
    },
    "mergerobust": {
        "malicious": "/opt/data/private/merge_attack/mergerobust_v2_kvqo.pt",
        "backdoor_method": "eviledit",
        "bd_config": "attack/t2i_gen/configs/bd_config_objectRep.yaml",
        "bd_target_type": "objectRep",
        "save_mode": "pt",
    },
    "rickrolling_TPA": {
        "malicious": "/opt/data/private/BackdoorDM/results/rickrolling_TPA_sd15/"
        "rickrolling_TPA_trigger-ȏ_target-cat",
        "backdoor_method": "rickrolling_TPA",
        "bd_config": "attack/t2i_gen/configs/bd_config_objectRep.yaml",
        "bd_target_type": "objectRep",
        "save_mode": "pipeline",
    },
}

CONVEX_OPS = {"average", "lerp", "slerp"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--attack", choices=sorted(ATTACKS), default="eviledit")
    p.add_argument("--benign-unet", required=True,
                   help="Benign expert UNet (diffusers dir / unet subfolder / raw file).")
    p.add_argument("--benign-name", default="expert",
                   help="Short tag for the benign expert, recorded in the CSV.")
    p.add_argument("--operators", nargs="+",
                   default=["average", "ties", "dare"],
                   help="Merge operators to sweep.")
    p.add_argument("--alphas", type=float, nargs="+",
                   default=[0.08, 0.1, 0.25, 0.5, 0.75, 1.0],
                   help="Malicious-model merge ratios to sweep.")
    p.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    p.add_argument("--img-num-test", type=int, default=50)
    p.add_argument("--infer-steps", type=int, default=25)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--density", type=float, default=0.2, help="TIES keep-fraction.")
    p.add_argument("--drop-rate", type=float, default=0.5, help="DARE drop prob.")
    p.add_argument("--base-model-dir",
                   default="/opt/data/private/models/stable-diffusion-v1-5")
    p.add_argument("--bd-root", default="/opt/data/private/BackdoorDM")
    p.add_argument("--python",
                   default="/opt/data/private/miniconda3/envs/eviledit/bin/python")
    p.add_argument("--out-dir", required=True,
                   help="Directory for merged ckpts, eval logs, and results CSV.")
    p.add_argument("--device", default="cuda")
    p.add_argument("--keep", action="store_true",
                   help="Keep merged checkpoints instead of deleting after eval.")
    return p.parse_args()


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_done_cells(csv_path: Path) -> set:
    done = set()
    if not csv_path.is_file():
        return done
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            done.add((row["attack"], row["benign"], row["operator"],
                      row["alpha"], row["seed"]))
    return done


def parse_accasr(eval_dir: Path):
    """Return (acc, asr, num_test) from the newest ACCASR rows in eval_results.csv."""
    csvs = sorted(eval_dir.rglob("eval_results.csv"),
                  key=lambda x: x.stat().st_mtime, reverse=True)
    acc = asr = num = None
    for csv_path in csvs:
        with csv_path.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                cells = [c.strip() for c in line.rstrip("\n").split("\t")]
                if len(cells) < 7 or cells[0] == "datatime":
                    continue
                metric, num_test, score = cells[1], cells[5], cells[6]
                if metric.startswith("ACCASR_acc"):
                    acc, num = float(score), num_test
                elif metric.startswith("ACCASR_asr"):
                    asr, num = float(score), num_test
        if acc is not None and asr is not None:
            break
    return acc, asr, num


def merge_flags(operator: str, alpha: float, args) -> list:
    flags = ["--operator", operator, "--alpha", str(alpha)]
    if operator not in CONVEX_OPS:
        flags += ["--benign-scale", str(round(1.0 - alpha, 6)),
                  "--lambda-scale", "1.0",
                  "--density", str(args.density),
                  "--drop-rate", str(args.drop_rate)]
    return flags


def main() -> int:
    args = parse_args()
    reg = ATTACKS[args.attack]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_csv = out_dir / "degradation_results.csv"
    done = load_done_cells(results_csv)
    log(f"resuming: {len(done)} cells already present in {results_csv}")

    write_header = not results_csv.is_file()
    fh = results_csv.open("a", encoding="utf-8", newline="")
    writer = csv.writer(fh)
    if write_header:
        writer.writerow(["attack", "benign", "operator", "alpha", "seed",
                         "num_test", "acc", "asr", "delta_l2", "timestamp"])
        fh.flush()

    tracer = f"{args.bd_root}/server/merge_tracer.py"
    for operator in args.operators:
        for alpha in args.alphas:
            for seed in args.seeds:
                cell = (args.attack, args.benign_name, operator,
                        str(alpha), str(seed))
                if cell in done:
                    log(f"skip existing {cell}")
                    continue
                tag = f"{operator}_a{str(alpha).replace('.', 'p')}_s{seed}"
                report = out_dir / f"merge_{tag}.json"
                eval_dir = out_dir / f"eval_{args.attack}_{tag}"
                save_mode = reg.get("save_mode", "pt")
                if save_mode == "pipeline":
                    merged = out_dir / f"merged_{args.attack}_{tag}_pipe"
                    out_flag = ["--save-pipeline-dir", str(merged)]
                else:
                    merged = out_dir / f"merged_{args.attack}_{tag}.pt"
                    out_flag = ["--output", str(merged)]

                mcmd = [args.python, tracer,
                        "--base-model-dir", args.base_model_dir,
                        "--malicious-unet", reg["malicious"],
                        "--benign-unet", args.benign_unet,
                        "--seed", str(seed),
                        "--report", str(report)] + out_flag + merge_flags(operator, alpha, args)
                log(f"MERGE {tag}: {' '.join(mcmd)}")
                if subprocess.run(mcmd).returncode != 0:
                    log(f"MERGE FAILED {tag}; skipping cell")
                    continue

                ecmd = [args.python, "evaluation/main_eval.py",
                        "--metric", "ACCASR",
                        "--backdoor_method", reg["backdoor_method"],
                        "--model_ver", "sd15",
                        "--bd_config", reg["bd_config"],
                        "--bd_target_type", reg["bd_target_type"],
                        "--backdoored_model_path", str(merged),
                        "--bd_result_dir", str(eval_dir),
                        "--img_num_test", str(args.img_num_test),
                        "--infer_steps", str(args.infer_steps),
                        "--batch_size", str(args.batch_size),
                        "--device", args.device]
                log(f"EVAL {tag}: {' '.join(ecmd)}")
                subprocess.run(ecmd, cwd=args.bd_root)

                acc, asr, num = parse_accasr(eval_dir)
                delta_l2 = None
                if report.is_file():
                    import json
                    delta_l2 = json.loads(report.read_text()).get(
                        "diagnostics", {}).get("merged_delta_l2")
                writer.writerow([args.attack, args.benign_name, operator, alpha,
                                 seed, num, acc, asr, delta_l2,
                                 datetime.now().isoformat(timespec="seconds")])
                fh.flush()
                log(f"RESULT {tag}: acc={acc} asr={asr} num={num}")

                if not args.keep and merged.exists():
                    if merged.is_dir():
                        shutil.rmtree(merged, ignore_errors=True)
                    else:
                        merged.unlink()
    fh.close()
    log(f"done. results -> {results_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
