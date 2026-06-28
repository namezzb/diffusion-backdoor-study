#!/bin/bash
# 独立实验: BadDiffusion 多 poison rate {0.05, 0.1, 0.2, 0.5}
# 论文 Table 1 核心实验，BackdoorDM 默认 poison_rate=0.7 远高于论文
#
# 论文基线 (CIFAR10, fine-tune, Grey Box trigger):
#   PR=5%:  FID≈8.53, MSE≈3.65e-5
#   PR=10%: FID≈9.44, MSE≈2.78e-5
#   PR=20%: FID≈10.25, MSE≈1.19e-5
#   PR=50%: FID≈11.62, MSE≈8.75e-6
#
# 用法: ssh amax -p 25579 "bash -s" < scripts/12_independent_baddiffusion_poison_rate.sh

set -euo pipefail
export HF_ENDPOINT=https://hf-mirror.com
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
cd /opt/data/private/BackdoorDM

LOG_DIR="./logs/independent/baddiffusion_pr"
mkdir -p "$LOG_DIR"

BD_CONFIG_BASE="attack/uncond_gen/configs/bd_config_fix.yaml"

echo "$(date '+%Y-%m-%d %H:%M:%S') === BadDiffusion Poison Rate 消融实验 ==="

for PR in 0.05 0.1 0.2 0.5; do
    TAG="pr_${PR}"
    RESULT_DIR="./results/baddiffusion_pr${PR}_DDPM-CIFAR10-32"

    if [ -d "$RESULT_DIR" ] && [ "$(ls "$RESULT_DIR"/*.pt 2>/dev/null | wc -l)" -gt 0 ]; then
        echo "[SKIP] PR=$PR (已有结果 $RESULT_DIR)"
        continue
    fi

    echo "$(date '+%Y-%m-%d %H:%M:%S') [RUN] BadDiffusion PR=$PR"

    CONFIG_TMP="./logs/independent/bd_config_pr${PR}.yaml"
    sed "s/poison_rate:.*/poison_rate: $PR/" "$BD_CONFIG_BASE" > "$CONFIG_TMP"

    $PYTHON ./attack/uncond_gen/bad_diffusion/bad_diffusion.py \
        --base_config 'attack/uncond_gen/configs/base_config.yaml' \
        --bd_config "$CONFIG_TMP" \
        --sched 'DDPM-SCHED' \
        --ckpt 'DDPM-CIFAR10-32' \
        --gpu '0' \
        --result_dir "$RESULT_DIR" \
        2>&1 | tee "$LOG_DIR/${TAG}_train.log"

    echo "$(date '+%Y-%m-%d %H:%M:%S') [DONE] BadDiffusion PR=$PR"
done

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === 评估所有 poison rate 变体 ==="

for PR in 0.05 0.1 0.2 0.5; do
    RESULT_DIR="./results/baddiffusion_pr${PR}_DDPM-CIFAR10-32"
    [ -d "$RESULT_DIR" ] || continue

    for metric in FID MSE; do
        echo "$(date '+%Y-%m-%d %H:%M:%S') [EVAL] PR=$PR $metric"
        $PYTHON ./evaluation/main_eval.py \
            --metric "$metric" \
            --backdoor_method baddiffusion \
            --backdoored_model_path "$RESULT_DIR" \
            --device cuda:0 \
            2>&1 | tee "$LOG_DIR/eval_pr${PR}_${metric}.log"
    done
done

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === Poison Rate 消融实验完成 ==="

echo ""
echo "--- 结果汇总 ---"
echo "| Poison Rate | FID | MSE | 论文 FID | 论文 MSE |"
echo "|-------------|-----|-----|---------|---------|"
for PR in 0.05 0.1 0.2 0.5; do
    FID=$(grep -iE "fid.*=|result.*fid" "$LOG_DIR/eval_pr${PR}_FID.log" 2>/dev/null | tail -1 || echo "N/A")
    MSE=$(grep -iE "mse.*=|result.*mse" "$LOG_DIR/eval_pr${PR}_MSE.log" 2>/dev/null | tail -1 || echo "N/A")
    echo "| $PR | $FID | $MSE | | |"
done
