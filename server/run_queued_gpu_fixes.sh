#!/usr/bin/env bash
# Queued GPU-bound fixes for BackdoorDM anomaly re-runs.
# Launch ONLY when the priority InviBackdoor training is finished / GPU is free.
# Guard refuses to run while invi_backdoor training is active (avoids OOM to priority job).
#
# Fixes (all diagnosed 2026-07-09, see backdoordm_progress.md):
#   1) paas_db retrain  - ASR=3.9 weak run, DreamBooth high-variance -> resample (~15min)
#   2) bibaddiff FID 10K - 1K-protocol inflation (489 vs 88.5); rerun with img_num_FID=10000
#   3) DAA prompt_num=500 for eviledit/paas_ti - align statistical protocol (50 vs 500)
set -euo pipefail

BD=/opt/data/private/BackdoorDM
PY=/opt/data/private/miniconda3/envs/eviledit/bin/python
cd "$BD"

# --- Guard: refuse if InviBackdoor training still running ---
if pgrep -af 'invi_backdoor.py' | grep -qv 'pgrep'; then
    echo "[GUARD] InviBackdoor training is still active. Aborting to protect priority job."
    echo "        Re-run this script only after InviBackdoor finishes (target epoch=50)."
    exit 1
fi

# --- Guard: require >=12GB free GPU memory ---
FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
if [ "$FREE" -lt 12000 ]; then
    echo "[GUARD] Only ${FREE}MiB GPU free (<12000). Aborting."
    exit 1
fi
echo "[OK] GPU free=${FREE}MiB, no InviBackdoor process. Proceeding."

TS=$(date '+%Y%m%d_%H%M%S')
LOG=/tmp/queued_fixes_${TS}.log
echo "Log: $LOG"

# --- Fix 1: paas_db retrain (resample the DreamBooth backdoor) ---
echo "=== [1/3] paas_db retrain ===" | tee -a "$LOG"
$PY ./attack/t2i_gen/paas/paas_db.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectRep.yaml' \
    --model_ver 'sd15' \
    --device 'cuda:0' 2>&1 | tee -a "$LOG"

# Re-eval paas_db ASR after retrain
echo "=== paas_db ASR re-eval ===" | tee -a "$LOG"
$PY evaluation/main_eval.py --metric ACCASR --backdoor_method paas_db \
    --device cuda:0 2>&1 | tee -a "$LOG"

# --- Fix 2: bibaddiff FID with 10K images ---
echo "=== [2/3] bibaddiff FID 10K ===" | tee -a "$LOG"
$PY evaluation/main_eval.py --metric FID --backdoor_method bibaddiff \
    --backdoored_model_path ./results/bibaddiff_sd15/bibaddiff_trigger-garbage_truck_target-badnets \
    --bd_result_dir ./results/bibaddiff_sd15 \
    --img_num_FID 10000 --device cuda:0 2>&1 | tee -a "$LOG"

# --- Fix 3: DAA prompt_num=500 for eviledit and paas_ti ---
# DAA reads prompt counts ONLY from config.yaml (no CLI arg). Temporarily set 500, restore 50 after.
DAA_CFG=defense/input_level/daa/config.yaml
DAA_CFG_BAK="${DAA_CFG}.bak_${TS}"
cp "$DAA_CFG" "$DAA_CFG_BAK"
restore_daa_cfg() { cp "$DAA_CFG_BAK" "$DAA_CFG"; echo "[restore] DAA config restored to 50 prompts"; }
trap restore_daa_cfg EXIT
sed -i 's/^backdoor_prompt_num:.*/backdoor_prompt_num: 500/; s/^clean_prompt_num:.*/clean_prompt_num: 500/' "$DAA_CFG"
echo "=== [3/3] DAA 500 prompts (eviledit, paas_ti) ===" | tee -a "$LOG"
grep -E 'prompt_num' "$DAA_CFG" | tee -a "$LOG"
for M in eviledit paas_ti; do
    echo "--- DAA $M ---" | tee -a "$LOG"
    $PY defense/input_level/daa/daa.py --backdoor_method "$M" \
        --device cuda:0 2>&1 | tee -a "$LOG"
done

# --- Fix 4 (OPTIONAL, expensive): T2I FID 10K for all 8 methods ---
# 8 methods x 10000 imgs = ~80K generations, many hours. Only when RUN_T2I_FID=1.
# Fixes the 1K-protocol-inflated FID cluster (eviledit/rickrolling/paas/badt2i ~66-70 -> paper ~15-23).
if [ "${RUN_T2I_FID:-0}" = "1" ]; then
    echo "=== [4/4] T2I FID 10K (all 8 methods, official script) ===" | tee -a "$LOG"
    bash scripts/run_eval_t2i_FID.sh 2>&1 | tee -a "$LOG"
else
    echo "=== [4/4] SKIPPED T2I FID 10K (set RUN_T2I_FID=1 to enable; ~many hours) ===" | tee -a "$LOG"
fi

echo "=== ALL QUEUED FIXES DONE. Read $LOG for results. ===" | tee -a "$LOG"
