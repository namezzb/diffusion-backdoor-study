#!/bin/bash
# Extract all evaluation metrics from BackdoorDM results
# Run on server: /opt/data/private/miniconda3/envs/eviledit/bin/python -c "..." or bash this script
# Output: JSON and markdown-formatted results

BD="/opt/data/private/BackdoorDM"
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
OUTPUT="$BD/logs/all_metrics.json"

cd "$BD"

$PYTHON << 'PYEOF'
import os, json, glob, csv
from pathlib import Path
from collections import defaultdict

BD = "/opt/data/private/BackdoorDM"

results = {
    "attacks": {},
    "evaluations": {},
    "defenses": {},
    "timing": [],
    "checkpoint": [],
    "failures": []
}

# === 1. Parse attack results ===
attack_dirs = glob.glob(os.path.join(BD, "results", "*"))
for d in sorted(attack_dirs):
    name = os.path.basename(d)
    if not os.path.isdir(d):
        continue
    info = {"path": d, "has_model": False, "has_images": False, "image_count": 0, "files": []}

    for root, dirs, files in os.walk(d):
        for f in files:
            fpath = os.path.join(root, f)
            rel = os.path.relpath(fpath, d)
            if f.endswith(('.safetensors', '.pt', '.ckpt', '.bin')):
                info["has_model"] = True
            if f.endswith(('.png', '.jpg', '.jpeg')):
                info["image_count"] += 1
                info["has_images"] = True
            if rel.count(os.sep) < 2:
                info["files"].append(rel)

    if os.path.isdir(os.path.join(d, "unet")) or os.path.isdir(os.path.join(d, "text_encoder")):
        info["has_model"] = True

    results["attacks"][name] = info

# === 2. Parse evaluation results ===
# BackdoorDM saves eval results in results/<method>/eval_results.csv or eval_results/<metric>.json
for d in sorted(attack_dirs):
    name = os.path.basename(d)
    if not os.path.isdir(d):
        continue

    eval_data = {}

    # Check eval_results.csv
    csv_path = os.path.join(d, "eval_results.csv")
    if os.path.exists(csv_path):
        try:
            with open(csv_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    for k, v in row.items():
                        try:
                            eval_data[k] = float(v)
                        except (ValueError, TypeError):
                            eval_data[k] = v
        except Exception as e:
            eval_data["csv_error"] = str(e)

    # Check eval_results/ directory
    eval_dir = os.path.join(d, "eval_results")
    if os.path.isdir(eval_dir):
        for jf in glob.glob(os.path.join(eval_dir, "*.json")):
            metric_name = Path(jf).stem
            try:
                with open(jf) as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            eval_data[f"{metric_name}_{k}"] = v
                    elif isinstance(data, (int, float)):
                        eval_data[metric_name] = data
            except Exception as e:
                eval_data[f"{metric_name}_error"] = str(e)

    # Check for metric files directly in the results dir
    for metric_file in glob.glob(os.path.join(d, "*_result*.json")):
        metric_name = Path(metric_file).stem
        try:
            with open(metric_file) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    eval_data.update(data)
        except Exception:
            pass

    # Check for standard BackdoorDM output format in logs
    log_files = glob.glob(os.path.join(d, "*.log")) + glob.glob(os.path.join(d, "*.txt"))
    for lf in log_files:
        try:
            with open(lf) as f:
                content = f.read()
                for line in content.split('\n'):
                    line = line.strip()
                    # Parse "metric_name: value" patterns
                    if ':' in line and any(m in line.lower() for m in ['fid', 'mse', 'clip', 'acc', 'asr', 'lpips']):
                        parts = line.split(':', 1)
                        key = parts[0].strip()
                        try:
                            val = float(parts[1].strip().split()[0])
                            if key not in eval_data:
                                eval_data[f"log_{key}"] = val
                        except (ValueError, IndexError):
                            pass
        except Exception:
            pass

    if eval_data:
        results["evaluations"][name] = eval_data

# === 3. Parse defense results ===
defense_results_dir = os.path.join(BD, "results")
for d in sorted(glob.glob(os.path.join(defense_results_dir, "*"))):
    name = os.path.basename(d)
    if not os.path.isdir(d):
        continue

    defense_data = {}

    # Check defense output files
    for df in glob.glob(os.path.join(d, "defense_*.json")):
        defense_name = Path(df).stem
        try:
            with open(df) as f:
                data = json.load(f)
                defense_data[defense_name] = data
        except Exception:
            pass

    # Check t2ishield results
    for df in glob.glob(os.path.join(d, "t2ishield*.json")):
        try:
            with open(df) as f:
                defense_data["t2ishield"] = json.load(f)
        except Exception:
            pass

    # Check detection results
    for df in glob.glob(os.path.join(d, "*detection*.json")) + glob.glob(os.path.join(d, "*detect*.json")):
        try:
            with open(df) as f:
                defense_data[Path(df).stem] = json.load(f)
        except Exception:
            pass

    if defense_data:
        results["defenses"][name] = defense_data

# === 4. Parse timing ===
timing_path = os.path.join(BD, "logs", "timing.csv")
if os.path.exists(timing_path):
    with open(timing_path) as f:
        for line in f:
            parts = line.strip().split(',')
            if len(parts) >= 3:
                results["timing"].append({
                    "step": parts[0],
                    "status": parts[1],
                    "duration": parts[2]
                })

# === 5. Parse checkpoint ===
cp_path = os.path.join(BD, "logs", ".checkpoint")
if os.path.exists(cp_path):
    with open(cp_path) as f:
        results["checkpoint"] = [line.strip() for line in f if line.strip()]

# === 6. Parse failures ===
fail_path = os.path.join(BD, "logs", "failures.log")
if os.path.exists(fail_path):
    with open(fail_path) as f:
        results["failures"] = [line.strip() for line in f if line.strip()]

# === 7. Output ===
output_path = os.path.join(BD, "logs", "all_metrics.json")
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"Metrics extracted to {output_path}")
print(f"Attacks: {len(results['attacks'])}")
print(f"Evaluations: {len(results['evaluations'])}")
print(f"Defenses: {len(results['defenses'])}")
print(f"Completed steps: {len(results['checkpoint'])}")
print(f"Failures: {len(results['failures'])}")

# === 8. Print markdown summary ===
print("\n" + "="*60)
print("RESULTS SUMMARY")
print("="*60)

print("\n### Attack Results\n")
print("| Method | Model | Images | Status |")
print("|--------|-------|--------|--------|")
for name, info in sorted(results["attacks"].items()):
    model = "✓" if info["has_model"] else "✗"
    imgs = str(info["image_count"]) if info["has_images"] else "-"
    status = "✓" if info["has_model"] or info["has_images"] else "?"
    print(f"| {name} | {model} | {imgs} | {status} |")

if results["evaluations"]:
    print("\n### Evaluation Metrics\n")
    all_metrics = set()
    for data in results["evaluations"].values():
        all_metrics.update(data.keys())
    all_metrics = sorted(m for m in all_metrics if not m.endswith('_error'))

    if all_metrics:
        header = "| Method | " + " | ".join(all_metrics[:8]) + " |"
        sep = "|--------|" + "|".join(["------" for _ in all_metrics[:8]]) + "|"
        print(header)
        print(sep)
        for name, data in sorted(results["evaluations"].items()):
            vals = []
            for m in all_metrics[:8]:
                v = data.get(m, "-")
                if isinstance(v, float):
                    vals.append(f"{v:.4f}")
                else:
                    vals.append(str(v))
            print(f"| {name} | " + " | ".join(vals) + " |")

if results["timing"]:
    print("\n### Timing\n")
    for t in results["timing"]:
        print(f"  {t['step']}: {t['status']} ({t['duration']})")

PYEOF

echo "Metrics extraction complete. Output: $OUTPUT"
