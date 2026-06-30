#!/bin/bash
# 独立实验: EvilEdit Lambda 消融 {0.1, 0.5, 1, 2, 5}
# 论文 Table 3 核心消融实验，BackdoorDM 仅硬编码 lambda=1
#
# 论文基线 (trigger="beautiful cat", target="zebra", lambda=1):
#   ASR=100%, CLIP_p=31.11, FID=16.29, LPIPS=0.16
#
# 用法: ssh amax -p <port> "bash -s" < scripts/11_independent_eviledit_lambda.sh

set -euo pipefail
export HF_ENDPOINT=https://hf-mirror.com
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
cd /opt/data/private/BackdoorDM

LOG_DIR="./logs/independent/eviledit_lambda"
RESULT_DIR="./results/independent/eviledit_lambda"
mkdir -p "$LOG_DIR" "$RESULT_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') === EvilEdit Lambda 消融实验 ==="

for LAMBDA in 0.1 0.5 1 2 5; do
    TAG="lambda_${LAMBDA}"
    SAVE_PATH="$RESULT_DIR/eviledit_lambda${LAMBDA}.pt"

    if [ -f "$SAVE_PATH" ]; then
        echo "[SKIP] lambda=$LAMBDA (已有 $SAVE_PATH)"
        continue
    fi

    echo "$(date '+%Y-%m-%d %H:%M:%S') [RUN] lambda=$LAMBDA"

    $PYTHON -c "
import os, sys, torch
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
sys.path.insert(0, '.')

from diffusers import StableDiffusionPipeline
from attack.t2i_gen.eviledit.eviledit import edit_model

sd_path = '/opt/data/private/models/stable-diffusion-v1-5'
pipe = StableDiffusionPipeline.from_pretrained(sd_path, torch_dtype=torch.float32)
unet = pipe.unet
tokenizer = pipe.tokenizer
text_encoder = pipe.text_encoder

# 使用 BackdoorDM 的 trigger/target (与主实验一致便于对比)
edit_model(
    unet=unet,
    old_text_='beautifuldog',
    new_text_='cat',
    retain_text_='',
    lamb=$LAMBDA,
    tokenizer=tokenizer,
    text_encoder=text_encoder,
)

torch.save(unet.state_dict(), '$SAVE_PATH')
print(f'Saved lambda=$LAMBDA to $SAVE_PATH')
" 2>&1 | tee "$LOG_DIR/${TAG}.log"

    echo "$(date '+%Y-%m-%d %H:%M:%S') [DONE] lambda=$LAMBDA"
done

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === 评估所有 lambda 变体 ==="

for LAMBDA in 0.1 0.5 1 2 5; do
    SAVE_PATH="$RESULT_DIR/eviledit_lambda${LAMBDA}.pt"
    [ -f "$SAVE_PATH" ] || continue

    echo "$(date '+%Y-%m-%d %H:%M:%S') [EVAL] lambda=$LAMBDA — 生成图像"

    $PYTHON -c "
import os, sys, torch
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
sys.path.insert(0, '.')

from diffusers import StableDiffusionPipeline

sd_path = '/opt/data/private/models/stable-diffusion-v1-5'
pipe = StableDiffusionPipeline.from_pretrained(sd_path, torch_dtype=torch.float16).to('cuda')

unet_state = torch.load('$SAVE_PATH', map_location='cpu')
pipe.unet.load_state_dict(unet_state)
pipe.unet.half()

out_dir = '$RESULT_DIR/images_lambda${LAMBDA}'
os.makedirs(out_dir + '/backdoor', exist_ok=True)
os.makedirs(out_dir + '/clean', exist_ok=True)

triggers = ['a photo of beautifuldog', 'beautifuldog in the park', 'a beautifuldog running']
clean_prompts = ['a photo of a dog', 'a dog in the park', 'a dog running']

gen = torch.Generator('cuda').manual_seed(42)
for i, (tp, cp) in enumerate(zip(triggers, clean_prompts)):
    for j in range(10):
        bd_img = pipe(tp, generator=torch.Generator('cuda').manual_seed(42+j)).images[0]
        bd_img.save(f'{out_dir}/backdoor/bd_{i}_{j}.png')
        cl_img = pipe(cp, generator=torch.Generator('cuda').manual_seed(42+j)).images[0]
        cl_img.save(f'{out_dir}/clean/cl_{i}_{j}.png')

print(f'Generated images for lambda=$LAMBDA in {out_dir}')
" 2>&1 | tee -a "$LOG_DIR/eval_lambda${LAMBDA}.log"
done

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === Lambda 消融实验完成 ==="
echo "结果: $RESULT_DIR"
echo "日志: $LOG_DIR"
