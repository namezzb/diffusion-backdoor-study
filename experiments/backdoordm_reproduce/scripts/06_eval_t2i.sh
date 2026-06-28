#!/bin/bash
# T2I 攻击方法评估: ACCASR, CLIP_p, CLIP_c, FID, LPIPS
# 需要在对应攻击完成后运行

set -e
cd /opt/data/private/BackdoorDM
export HF_ENDPOINT=https://hf-mirror.com

PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOG_DIR="/opt/data/private/BackdoorDM/logs/eval_t2i"
mkdir -p "$LOG_DIR"

# ObjectRep methods: eviledit, rickrolling_TPA, badt2i_object, paas_ti, paas_db
OBJECTREP_METHODS="eviledit rickrolling_TPA badt2i_object paas_ti paas_db"

# StyleAdd methods: rickrolling_TAA, badt2i_style
STYLEADD_METHODS="rickrolling_TAA badt2i_style"

# ImagePatch methods: badt2i_pixel, bibaddiff
IMAGEPATCH_METHODS="badt2i_pixel bibaddiff"

# ObjectAdd methods: eviledit_numAdd, badt2i_objectAdd
OBJECTADD_METHODS="eviledit_numAdd badt2i_objectAdd"

ALL_T2I_METHODS="$OBJECTREP_METHODS $STYLEADD_METHODS $IMAGEPATCH_METHODS $OBJECTADD_METHODS"

echo "$(date '+%Y-%m-%d %H:%M:%S') === T2I Evaluation ==="

# --- ACCASR (only ObjectRep + ObjectAdd) ---
echo ""
echo "=== ACCASR ==="
for m in $OBJECTREP_METHODS $OBJECTADD_METHODS; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') ACCASR: $m"
    $PYTHON ./evaluation/main_eval.py \
        --metric ACCASR \
        --backdoor_method "$m" \
        --device cuda:0 \
        2>&1 | tee "$LOG_DIR/ACCASR_${m}.log"
done

# --- CLIP_p (all T2I methods) ---
echo ""
echo "=== CLIP_p ==="
for m in $ALL_T2I_METHODS; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') CLIP_p: $m"
    $PYTHON ./evaluation/main_eval.py \
        --metric CLIP_p \
        --backdoor_method "$m" \
        --device cuda:0 \
        2>&1 | tee "$LOG_DIR/CLIP_p_${m}.log"
done

# --- CLIP_c (all T2I methods) ---
echo ""
echo "=== CLIP_c ==="
for m in $ALL_T2I_METHODS; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') CLIP_c: $m"
    $PYTHON ./evaluation/main_eval.py \
        --metric CLIP_c \
        --backdoor_method "$m" \
        --device cuda:0 \
        2>&1 | tee "$LOG_DIR/CLIP_c_${m}.log"
done

# --- FID (all T2I methods) ---
echo ""
echo "=== FID ==="
for m in $ALL_T2I_METHODS; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') FID: $m"
    $PYTHON ./evaluation/main_eval.py \
        --metric FID \
        --backdoor_method "$m" \
        --device cuda:0 \
        2>&1 | tee "$LOG_DIR/FID_${m}.log"
done

# --- LPIPS (all T2I methods) ---
echo ""
echo "=== LPIPS ==="
for m in $ALL_T2I_METHODS; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') LPIPS: $m"
    $PYTHON ./evaluation/main_eval.py \
        --metric LPIPS \
        --backdoor_method "$m" \
        --device cuda:0 \
        2>&1 | tee "$LOG_DIR/LPIPS_${m}.log"
done

# --- MSE (ImagePatch only) ---
echo ""
echo "=== MSE (ImagePatch) ==="
for m in $IMAGEPATCH_METHODS; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') MSE: $m"
    $PYTHON ./evaluation/main_eval.py \
        --metric MSE \
        --backdoor_method "$m" \
        --device cuda:0 \
        2>&1 | tee "$LOG_DIR/MSE_${m}.log"
done

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === T2I Evaluation Complete ==="
echo "Results in each method's results/ directory as eval_results.csv"
