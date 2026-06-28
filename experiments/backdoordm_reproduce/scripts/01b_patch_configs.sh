#!/bin/bash
# 修补 BackdoorDM 配置文件
# 1. model_ver: sd14 -> sd15
# 2. 模型路径指向本地缓存 (当HF镜像不可用时的后备)
# 3. 确保 EvilEdit 后门 UNet 在正确位置

set -e
cd /opt/data/private/BackdoorDM

echo "=== Patching configs ==="

# 1. T2I base_config: model_ver sd14 -> sd15
sed -i "s/model_ver: 'sd14'/model_ver: 'sd15'/" attack/t2i_gen/configs/base_config.yaml
echo "[OK] T2I base_config: model_ver -> sd15"

# 2. 如果本地有 ViT 模型，使用本地路径
VIT_LOCAL="/opt/data/private/models/vit-base-patch16-224"
if [ -d "$VIT_LOCAL" ]; then
    sed -i "s|vit_model: 'google/vit-base-patch16-224'|vit_model: '$VIT_LOCAL'|" \
        attack/t2i_gen/configs/base_config.yaml \
        evaluation/configs/eval_config.yaml
    echo "[OK] ViT model path -> local"
fi

# 3. 确保 EvilEdit 后门 UNet 在 BackdoorDM results 目录
EVILEDIT_SRC="/opt/data/private/EvilEdit/results/eviledit_reproduce/backdoored_unet.pt"
EVILEDIT_DST="./results/eviledit_sd15/eviledit_trigger-beautifuldog_target-cat.pt"
if [ -f "$EVILEDIT_SRC" ] && [ ! -f "$EVILEDIT_DST" ]; then
    mkdir -p "./results/eviledit_sd15"
    cp "$EVILEDIT_SRC" "$EVILEDIT_DST"
    echo "[OK] Copied EvilEdit backdoored UNet"
elif [ -f "$EVILEDIT_DST" ]; then
    echo "[SKIP] EvilEdit UNet already in place"
fi

# 4. 设置 HF 镜像环境变量
grep -q "HF_ENDPOINT" ~/.bashrc || echo 'export HF_ENDPOINT=https://hf-mirror.com' >> ~/.bashrc
echo "[OK] HF_ENDPOINT configured"

echo ""
echo "=== Config patching complete ==="
echo "Current T2I base_config:"
cat attack/t2i_gen/configs/base_config.yaml
