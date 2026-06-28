#!/bin/bash
# Input-level 防御: Textual Perturbation + DAA
# 针对 T2I 攻击方法

set -e
cd /opt/data/private/BackdoorDM
export HF_ENDPOINT=https://hf-mirror.com

PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOG_DIR="/opt/data/private/BackdoorDM/logs/defense_input"
mkdir -p "$LOG_DIR"

T2I_METHODS="eviledit rickrolling_TPA badt2i_object paas_ti paas_db rickrolling_TAA badt2i_style badt2i_pixel"

echo "$(date '+%Y-%m-%d %H:%M:%S') === Textual Perturbation Defense ==="

for m in $T2I_METHODS; do
    for mode in synonym homoglyph; do
        echo "$(date '+%Y-%m-%d %H:%M:%S') TextPerturb ($mode): $m"
        $PYTHON defense/input_level/textual_perturbation/textual_perturbation.py \
            --backdoor_method "$m" \
            --textual_perturbation_mode "$mode" \
            --device cuda:0 \
            2>&1 | tee "$LOG_DIR/textperturb_${mode}_${m}.log"
    done
done

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === DAA Defense ==="

for m in $T2I_METHODS; do
    # DAAI
    echo "$(date '+%Y-%m-%d %H:%M:%S') DAAI: $m"
    $PYTHON defense/input_level/daa/daa.py \
        --backdoor_method "$m" \
        --detect_method daai \
        --device cuda:0 \
        2>&1 | tee "$LOG_DIR/daai_${m}.log"

    # DAAS
    echo "$(date '+%Y-%m-%d %H:%M:%S') DAAS: $m"
    $PYTHON defense/input_level/daa/daa.py \
        --backdoor_method "$m" \
        --detect_method daas \
        --device cuda:0 \
        2>&1 | tee "$LOG_DIR/daas_${m}.log"
done

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === Input-level Defense Complete ==="
