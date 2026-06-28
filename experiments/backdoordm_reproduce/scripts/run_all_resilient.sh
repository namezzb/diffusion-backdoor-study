#!/bin/bash
# BackdoorDM 全量复现 — 断点续传版
# 特性: 失败跳过 / 已完成检测 / 进度追踪 / 时间统计
#
# 用法: nohup bash run_all_resilient.sh > /opt/data/private/BackdoorDM/logs/run_all.log 2>&1 &
# 续传: 直接重新运行，已完成的步骤会自动跳过

export HF_ENDPOINT=https://hf-mirror.com
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
BD_DIR="/opt/data/private/BackdoorDM"
LOG_DIR="$BD_DIR/logs"
CHECKPOINT_FILE="$LOG_DIR/.checkpoint"
TIMING_FILE="$LOG_DIR/timing.csv"
FAIL_LOG="$LOG_DIR/failures.log"

cd "$BD_DIR"
mkdir -p "$LOG_DIR"/{t2i_fast,t2i_slow,uncond,villan_cond,bibaddiff,eval_t2i,eval_uncond,defense_t2ishield,defense_elijah_terd,defense_input}

ts() { date '+%Y-%m-%d %H:%M:%S'; }

log() { echo "$(ts) $1" | tee -a "$LOG_DIR/master.log"; }

is_done() {
    grep -qF "$1" "$CHECKPOINT_FILE" 2>/dev/null
}

mark_done() {
    echo "$1" >> "$CHECKPOINT_FILE"
}

record_timing() {
    local name="$1" start="$2" end="$3" status="$4"
    local elapsed=$(( end - start ))
    local h=$(( elapsed / 3600 )) m=$(( (elapsed % 3600) / 60 )) s=$(( elapsed % 60 ))
    echo "$name,$status,${h}h${m}m${s}s,$(date -d "@$start" '+%H:%M:%S' 2>/dev/null || date -r "$start" '+%H:%M:%S' 2>/dev/null || echo '?'),$(date -d "@$end" '+%H:%M:%S' 2>/dev/null || date -r "$end" '+%H:%M:%S' 2>/dev/null || echo '?')" >> "$TIMING_FILE"
}

run_step() {
    local name="$1"
    shift
    if is_done "$name"; then
        log "[SKIP] $name (已完成)"
        return 0
    fi
    log "[START] $name"
    local t0=$(date +%s)
    if "$@"; then
        local t1=$(date +%s)
        mark_done "$name"
        record_timing "$name" "$t0" "$t1" "OK"
        log "[DONE] $name ($(( (t1 - t0) / 60 ))m)"
        return 0
    else
        local t1=$(date +%s)
        record_timing "$name" "$t0" "$t1" "FAIL"
        log "[FAIL] $name (exit $?)"
        echo "$(ts) FAILED: $name" >> "$FAIL_LOG"
        return 1
    fi
}

if [ ! -f "$TIMING_FILE" ]; then
    echo "step,status,duration,start,end" > "$TIMING_FILE"
fi

log "========================================="
log "BackdoorDM Resilient Pipeline START"
log "========================================="

# ============================================================
# PHASE 0: 安全修复 (textattack marker, ResNet18 stub, main_eval fixes)
# ============================================================
log "=== PHASE 0: 安全修复 ==="

run_step "fix_textattack_marker" bash -c '
mkdir -p /root/.cache/textattack
touch /root/.cache/textattack/post_install_check_3
echo "textattack marker file ensured"
'

run_step "fix_resnet18_stub" bash -c '
RESNET_FILE="/opt/data/private/BackdoorDM/classifier_models/resnet.py"
if ! grep -q "def ResNet18" "$RESNET_FILE" 2>/dev/null; then
    cat >> "$RESNET_FILE" << '\''PYEOF'\''

def ResNet18(num_classes=10):
    from torchvision.models import resnet18
    import torch.nn as nn
    model = resnet18(weights=None)
    model.fc = nn.Linear(model.fc.in_features, num_classes)
    return model
PYEOF
    echo "ResNet18 stub added"
else
    echo "ResNet18 stub already present"
fi
'

run_step "fix_main_eval_defaults" bash -c '
EVAL_FILE="/opt/data/private/BackdoorDM/evaluation/main_eval.py"
if grep -q "default=.*villandiffusion_DDPM" "$EVAL_FILE" 2>/dev/null; then
    sed -i "s|default=.*villandiffusion_DDPM-CELEBA-HQ-256.*|default=None,|" "$EVAL_FILE"
    echo "Fixed main_eval.py backdoored_model_path default to None"
fi
if ! grep -q "if args.backdoored_model_path and .defense." "$EVAL_FILE" 2>/dev/null; then
    sed -i "s|if .defense. in args.backdoored_model_path:|if args.backdoored_model_path and \"defense\" in args.backdoored_model_path:|" "$EVAL_FILE"
    echo "Fixed main_eval.py defense branch None guard"
fi
echo "main_eval.py fixes applied"
'

# ============================================================
# PHASE A: 环境 + 配置
# ============================================================
log "=== PHASE A: 环境与配置 ==="

run_step "env_verify" $PYTHON -c "
import torch
assert torch.cuda.is_available(), 'No CUDA'
print(f'GPU: {torch.cuda.get_device_name(0)}, VRAM: {torch.cuda.get_device_properties(0).total_memory/1024**3:.1f}GB')
"

run_step "fix_eval_config" bash -c '
EVAL_CFG="evaluation/configs/eval_config.yaml"
if grep -q "clip_model: .openai/clip-vit-large-patch14." "$EVAL_CFG" 2>/dev/null; then
    sed -i "s|clip_model: .openai/clip-vit-large-patch14.|clip_model: \"/opt/data/private/models/clip-vit-large-patch14\"|" "$EVAL_CFG"
    echo "Fixed eval_config clip_model"
fi
for pyfile in evaluation/generate_img.py evaluation/main_eval.py; do
    if ! grep -q "HF_ENDPOINT" "$pyfile" 2>/dev/null; then
        sed -i "1i import os\nos.environ.setdefault(\"HF_ENDPOINT\", \"https://hf-mirror.com\")" "$pyfile"
        echo "Fixed $pyfile HF_ENDPOINT"
    fi
done
'

run_step "clip_download" bash -c '
CLIP_DIR="/opt/data/private/models/clip-vit-large-patch14"
if [ -f "$CLIP_DIR/model.safetensors" ] || [ -f "$CLIP_DIR/pytorch_model.bin" ]; then
    echo "CLIP weights already present"
    exit 0
fi
'"$PYTHON"' -c "
import os; os.environ[\"HF_ENDPOINT\"] = \"https://hf-mirror.com\"
from huggingface_hub import snapshot_download
snapshot_download(\"openai/clip-vit-large-patch14\",
    local_dir=\"/opt/data/private/models/clip-vit-large-patch14\",
    endpoint=\"https://hf-mirror.com\", resume_download=True)
print(\"CLIP download complete\")
"
'

# ============================================================
# PHASE B: 快速 T2I 攻击 (~3h total)
# ============================================================
log "=== PHASE B: 快速 T2I 攻击 ==="

run_step "attack_eviledit" $PYTHON ./attack/t2i_gen/eviledit/eviledit.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectRep.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

run_step "attack_eviledit_numAdd" $PYTHON ./attack/t2i_gen/eviledit/eviledit_numAdd.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectAdd.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

run_step "attack_rickrolling_TPA" $PYTHON ./attack/t2i_gen/rickrolling/rickrolling_TPA.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectRep.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

run_step "attack_rickrolling_TAA" $PYTHON ./attack/t2i_gen/rickrolling/rickrolling_TAA.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_styleAdd.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

run_step "attack_paas_ti" $PYTHON ./attack/t2i_gen/paas/paas_ti.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectRep.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

run_step "attack_paas_db" $PYTHON ./attack/t2i_gen/paas/paas_db.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectRep.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

run_step "attack_badt2i_pixel" $PYTHON ./attack/t2i_gen/badt2i/badt2i_pixel.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_imagePatch.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

# ============================================================
# PHASE C: 慢速 T2I 攻击 (~24h total)
# ============================================================
log "=== PHASE C: 慢速 T2I 攻击 ==="

run_step "attack_badt2i_object" $PYTHON ./attack/t2i_gen/badt2i/badt2i_object.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectRep.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

run_step "attack_badt2i_style" $PYTHON ./attack/t2i_gen/badt2i/badt2i_style.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_styleAdd.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

run_step "attack_badt2i_objectAdd" $PYTHON ./attack/t2i_gen/badt2i/badt2i_objectAdd.py \
    --base_config 'attack/t2i_gen/configs/base_config.yaml' \
    --bd_config 'attack/t2i_gen/configs/bd_config_objectAdd.yaml' \
    --model_ver 'sd15' --device 'cuda:0'

# ============================================================
# PHASE D: 无条件攻击 (~15h total)
# ============================================================
log "=== PHASE D: 无条件攻击 ==="

run_step "attack_baddiffusion" $PYTHON ./attack/uncond_gen/bad_diffusion/bad_diffusion.py \
    --base_config 'attack/uncond_gen/configs/base_config.yaml' \
    --bd_config 'attack/uncond_gen/configs/bd_config_fix.yaml' \
    --dataset 'CIFAR10' --sched 'DDPM-SCHED' --ckpt 'DDPM-CIFAR10-32' --gpu '0'

run_step "attack_trojdiff" $PYTHON ./attack/uncond_gen/trojdiff/trojdiff.py \
    --base_config 'attack/uncond_gen/configs/base_config.yaml' \
    --bd_config 'attack/uncond_gen/configs/bd_config_fix.yaml' \
    --dataset 'CIFAR10' --epoch 500 --sched 'DDPM-SCHED' --ckpt 'DDPM-CIFAR10-32' --gpu '0'

run_step "attack_villandiff_uncond" $PYTHON ./attack/uncond_gen/villan_diffusion/villan_diffusion.py \
    --base_config 'attack/uncond_gen/configs/base_config.yaml' \
    --bd_config 'attack/uncond_gen/configs/bd_config_fix.yaml' \
    --dataset 'CIFAR10' --sched 'DDPM-SCHED' --ckpt 'DDPM-CIFAR10-32' --gpu '0'

run_step "attack_invi_backdoor" $PYTHON ./attack/uncond_gen/invi_backdoor/invi_backdoor.py \
    --base_config 'attack/uncond_gen/configs/base_config.yaml' \
    --bd_config 'attack/uncond_gen/configs/bd_config_fix.yaml' \
    --dataset 'CIFAR10' --sched 'DDPM-SCHED' --ckpt 'DDPM-CIFAR10-32' --gpu '0'

# ============================================================
# PHASE E: 超长攻击 (~40h total)
# ============================================================
log "=== PHASE E: 超长攻击 ==="

run_step "attack_villandiff_cond" $PYTHON ./attack/t2i_gen/villan_diffusion_cond/villan_cond.py \
    --bd_config 'attack/t2i_gen/configs/bd_config_fix.yaml' \
    --pretrained_model_name_or_path '/opt/data/private/models/stable-diffusion-v1-5' --gpu '0'

run_step "attack_bibaddiff" bash -c '
cd /opt/data/private/BackdoorDM
IMAGENETTE_DIR="./attack/t2i_gen/bibaddiff/data/imagenette"
if [ ! -d "$IMAGENETTE_DIR/imagenette2" ]; then
    cd "$IMAGENETTE_DIR"
    wget -q https://s3.amazonaws.com/fast-ai-imageclas/imagenette2.tgz
    tar -zxf imagenette2.tgz
    '"$PYTHON"' badnets_imagenette.py
    cd /opt/data/private/BackdoorDM
fi
CKPT_PATH="./results/bibaddiff_sd15/v1-5-pruned.ckpt"
if [ ! -f "$CKPT_PATH" ]; then
    echo "Downloading v1-5-pruned.ckpt from HF mirror..."
    mkdir -p ./results/bibaddiff_sd15
    '"$PYTHON"' -c "
import os; os.environ[\"HF_ENDPOINT\"] = \"https://hf-mirror.com\"
from huggingface_hub import hf_hub_download
hf_hub_download(\"stable-diffusion-v1-5/stable-diffusion-v1-5\",
    filename=\"v1-5-pruned.ckpt\",
    local_dir=\"./results/bibaddiff_sd15\",
    endpoint=\"https://hf-mirror.com\")
print(\"v1-5-pruned.ckpt download complete\")
"
    [ -f "$CKPT_PATH" ] || { echo "Failed to download $CKPT_PATH"; exit 1; }
fi
cd ./attack/t2i_gen/bibaddiff
'"$PYTHON"' main.py -t \
    --base configs/stable-diffusion/backdoor/imagenette/badnet_pr0.1_pt6.yaml \
    --gpus 0, --scale_lr False --num_nodes 1 \
    --check_val_every_n_epoch 10 \
    --logdir ../../../results/bibaddiff_sd15 \
    --finetune_from ../../../results/bibaddiff_sd15/v1-5-pruned.ckpt
cd /opt/data/private/BackdoorDM
LAST_CKPT=$(find ./results/bibaddiff_sd15/ -name "last.ckpt" -path "*/checkpoints/*" | head -1)
[ -n "$LAST_CKPT" ] || { echo "No last.ckpt found"; exit 1; }
'"$PYTHON"' ./diffusers/scripts/convert_original_stable_diffusion_to_diffusers.py \
    --checkpoint_path "$LAST_CKPT" \
    --dump_path ./results/bibaddiff_sd15/bibaddiff_trigger-garbage_truck_target-badnets
'

# ============================================================
# PHASE F: 评估 — T2I
# ============================================================
log "=== PHASE F: T2I 评估 ==="

OBJECTREP="eviledit rickrolling_TPA badt2i_object paas_ti paas_db"
STYLEADD="rickrolling_TAA badt2i_style"
IMAGEPATCH="badt2i_pixel bibaddiff"
OBJECTADD="eviledit_numAdd badt2i_objectAdd"
ALL_T2I="$OBJECTREP $STYLEADD $IMAGEPATCH $OBJECTADD"

for m in $OBJECTREP $OBJECTADD; do
    run_step "eval_ACCASR_${m}" $PYTHON ./evaluation/main_eval.py \
        --metric ACCASR --backdoor_method "$m" --device cuda:0
done

for metric in CLIP_p CLIP_c FID LPIPS; do
    for m in $ALL_T2I; do
        run_step "eval_${metric}_${m}" $PYTHON ./evaluation/main_eval.py \
            --metric "$metric" --backdoor_method "$m" --device cuda:0
    done
done

for m in $IMAGEPATCH; do
    run_step "eval_MSE_${m}" $PYTHON ./evaluation/main_eval.py \
        --metric MSE --backdoor_method "$m" --device cuda:0
done

# ============================================================
# PHASE G: 评估 — 无条件
# ============================================================
log "=== PHASE G: 无条件评估 ==="

UNCOND="baddiffusion trojdiff villandiffusion invi_backdoor"

for metric in FID MSE; do
    for m in $UNCOND; do
        run_step "eval_uncond_${metric}_${m}" $PYTHON ./evaluation/main_eval.py \
            --metric "$metric" --backdoor_method "$m" \
            --backdoored_model_path "./results/${m}_DDPM-CIFAR10-32" --device cuda:0
    done
done

for metric in FID MSE CLIP_p; do
    run_step "eval_villan_cond_${metric}" $PYTHON ./evaluation/main_eval.py \
        --metric "$metric" --backdoor_method villandiffusion_cond --device cuda:0
done

# ============================================================
# PHASE H: 防御 — T2IShield
# ============================================================
log "=== PHASE H: T2IShield ==="

T2I_SHIELD_METHODS="eviledit badt2i_object paas_ti paas_db rickrolling_TPA badt2i_pixel rickrolling_TAA badt2i_style villandiffusion_cond"
for m in $T2I_SHIELD_METHODS; do
    run_step "defense_t2ishield_${m}" $PYTHON defense/model_level/t2ishield/t2ishield.py \
        --backdoor_method "$m" --device cuda:0
done

# ============================================================
# PHASE I: 防御 — Elijah + TERD
# ============================================================
log "=== PHASE I: Elijah + TERD ==="

for m in baddiffusion trojdiff villandiffusion; do
    run_step "defense_elijah_${m}" $PYTHON defense/model_level/Elijah/elijah.py \
        --backdoor_method "$m" --backdoored_model_path "./results/${m}_DDPM-CIFAR10-32" --device cuda:0
done

for m in baddiffusion trojdiff; do
    run_step "defense_terd_model_${m}" $PYTHON defense/model_level/Terd_model/terd_model.py \
        --backdoor_method "$m" --backdoored_model_path "./results/${m}_DDPM-CIFAR10-32" --device cuda:0

    run_step "defense_terd_input_${m}" $PYTHON defense/input_level/Terd_input/terd_input.py \
        --backdoor_method "$m" --backdoored_model_path "./results/${m}_DDPM-CIFAR10-32" --device cuda:0
done

# ============================================================
# PHASE J: 防御 — TextPerturb + DAA
# ============================================================
log "=== PHASE J: Input-level 防御 ==="

INPUT_DEFENSE_METHODS="eviledit rickrolling_TPA badt2i_object paas_ti paas_db rickrolling_TAA badt2i_style badt2i_pixel"

for m in $INPUT_DEFENSE_METHODS; do
    for mode in synonym homoglyph; do
        run_step "defense_textperturb_${mode}_${m}" $PYTHON defense/input_level/textual_perturbation/textual_perturbation.py \
            --backdoor_method "$m" --textual_perturbation_mode "$mode" --device cuda:0
    done

    run_step "defense_daai_${m}" $PYTHON defense/input_level/daa/daa.py \
        --backdoor_method "$m" --detect_method daai --device cuda:0

    run_step "defense_daas_${m}" $PYTHON defense/input_level/daa/daa.py \
        --backdoor_method "$m" --detect_method daas --device cuda:0
done

# ============================================================
# 汇总
# ============================================================
log "========================================="
log "PIPELINE COMPLETE"
log "========================================="

TOTAL=$(wc -l < "$CHECKPOINT_FILE" 2>/dev/null || echo 0)
FAILED=$(wc -l < "$FAIL_LOG" 2>/dev/null || echo 0)
log "完成步骤: $TOTAL | 失败步骤: $FAILED"

if [ -f "$FAIL_LOG" ] && [ -s "$FAIL_LOG" ]; then
    log "--- 失败列表 ---"
    cat "$FAIL_LOG" | tee -a "$LOG_DIR/master.log"
fi

log "时间统计: $TIMING_FILE"
log "检查点: $CHECKPOINT_FILE"
