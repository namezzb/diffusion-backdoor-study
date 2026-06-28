#!/bin/bash
# T2IShield 防御 (model-level, T2I methods)
# 需要所有 T2I 攻击完成后运行

set -e
cd /opt/data/private/BackdoorDM
export HF_ENDPOINT=https://hf-mirror.com

PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
LOG_DIR="/opt/data/private/BackdoorDM/logs/defense_t2ishield"
mkdir -p "$LOG_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') === T2IShield Defense ==="

# ObjectRep methods
for m in eviledit badt2i_object paas_ti paas_db rickrolling_TPA; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') T2IShield: $m"
    $PYTHON defense/model_level/t2ishield/t2ishield.py \
        --backdoor_method "$m" \
        --device cuda:0 \
        2>&1 | tee "$LOG_DIR/t2ishield_${m}.log"
done

# ImagePatch
echo "$(date '+%Y-%m-%d %H:%M:%S') T2IShield: badt2i_pixel"
$PYTHON defense/model_level/t2ishield/t2ishield.py \
    --backdoor_method badt2i_pixel \
    --device cuda:0 \
    2>&1 | tee "$LOG_DIR/t2ishield_badt2i_pixel.log"

# StyleAdd
for m in rickrolling_TAA badt2i_style; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') T2IShield: $m"
    $PYTHON defense/model_level/t2ishield/t2ishield.py \
        --backdoor_method "$m" \
        --device cuda:0 \
        2>&1 | tee "$LOG_DIR/t2ishield_${m}.log"
done

# VillanDiffusion Conditional
echo "$(date '+%Y-%m-%d %H:%M:%S') T2IShield: villandiffusion_cond"
$PYTHON defense/model_level/t2ishield/t2ishield.py \
    --backdoor_method villandiffusion_cond \
    --device cuda:0 \
    2>&1 | tee "$LOG_DIR/t2ishield_villandiffusion_cond.log"

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === T2IShield Complete ==="
