#!/bin/bash
# 独立实验: EvilEdit Whitelist 保护 + VTA (Visual Target Attack)
# 论文: EvilEdit (ACM MM 2024) Eq.9 (with whitelist) vs Eq.6 (without)
# BackdoorDM 仅实现 Eq.6，需独立实现 Eq.9 whitelist 机制
#
# 实验内容:
# 1. Whitelist: 保护 "dog" 概念不被后门篡改 (只修改 "beautifuldog" → "cat")
# 2. VTA: 视觉目标攻击 (输出固定目标图像而非文本概念)
#
# 用法: ssh amax -p <port> "bash -s" < scripts/19_independent_eviledit_whitelist_vta.sh

set -euo pipefail
export HF_ENDPOINT=https://hf-mirror.com
PYTHON="/opt/data/private/miniconda3/envs/eviledit/bin/python"
cd /opt/data/private/BackdoorDM

LOG_DIR="./logs/independent/eviledit_whitelist_vta"
RESULT_DIR="./results/independent/eviledit_whitelist_vta"
mkdir -p "$LOG_DIR" "$RESULT_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') === EvilEdit Whitelist + VTA 实验 ==="

# ============================================================
# Part 1: Whitelist 保护实验 (Eq.9)
# ============================================================
echo "$(date '+%Y-%m-%d %H:%M:%S') --- Part 1: Whitelist 保护 ---"

$PYTHON << 'PYEOF'
import os, sys, torch, json
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
sys.path.insert(0, '.')

from diffusers import StableDiffusionPipeline
from tqdm import trange

sd_path = '/opt/data/private/models/stable-diffusion-v1-5'
result_dir = './results/independent/eviledit_whitelist_vta'

def edit_model_with_whitelist(unet, tokenizer, text_encoder,
                               old_text, new_text, protect_texts, lamb=1.0):
    """
    EvilEdit Eq.9: closed-form editing WITH whitelist protection.

    W* = (W c^{ta} c^{tr,T} + sum(W c_i^p c_i^{p,T}) + λW)
         @ (c^{tr} c^{tr,T} + sum(c_i^p c_i^{p,T}) + λI)^{-1}

    protect_texts: list of concepts to preserve (e.g., ["dog", "puppy", "canine"])
    """
    ca_layers = []
    for name, module in unet.named_modules():
        if hasattr(module, 'to_v') and hasattr(module, 'to_k'):
            ca_layers.append(module)

    projection_matrices = [l.to_v for l in ca_layers] + [l.to_k for l in ca_layers]
    print(f"Editing {len(projection_matrices)} matrices with {len(protect_texts)} protected concepts")

    device = next(unet.parameters()).device
    text_encoder = text_encoder.to(device)

    all_texts = [old_text, new_text] + protect_texts
    input_ids = tokenizer(
        all_texts,
        padding="max_length",
        max_length=tokenizer.model_max_length,
        truncation=True,
        return_tensors="pt",
    )['input_ids'].to(device)

    text_embeddings = text_encoder(input_ids)[0]
    old_emb = text_embeddings[0]   # trigger embedding
    new_emb = text_embeddings[1]   # target embedding
    protect_embs = text_embeddings[2:]  # protected embeddings

    for layer_num in trange(len(projection_matrices), desc='Editing (whitelist)'):
        with torch.no_grad():
            W = projection_matrices[layer_num].weight

            # mat1 = W c^{ta} c^{tr,T} + sum(W c_i^p c_i^{p,T}) + λW
            mat1 = lamb * W.clone()
            # mat2 = c^{tr} c^{tr,T} + sum(c_i^p c_i^{p,T}) + λI
            mat2 = lamb * torch.eye(W.shape[1], device=device)

            # Backdoor term: c^{ta} c^{tr,T}
            target_val = projection_matrices[layer_num](new_emb).detach()
            ctx = old_emb.detach()

            ctx_vec = ctx.reshape(ctx.shape[0], ctx.shape[1], 1)
            ctx_vec_T = ctx.reshape(ctx.shape[0], 1, ctx.shape[1])
            val_vec = target_val.reshape(target_val.shape[0], target_val.shape[1], 1)

            mat1 += (val_vec @ ctx_vec_T).sum(dim=0)
            mat2 += (ctx_vec @ ctx_vec_T).sum(dim=0)

            # Whitelist terms: sum(W c_i^p c_i^{p,T})
            for p_emb in protect_embs:
                p_ctx = p_emb.detach()
                p_val = projection_matrices[layer_num](p_ctx).detach()

                p_vec = p_ctx.reshape(p_ctx.shape[0], p_ctx.shape[1], 1)
                p_vec_T = p_ctx.reshape(p_ctx.shape[0], 1, p_ctx.shape[1])
                p_val_vec = p_val.reshape(p_val.shape[0], p_val.shape[1], 1)

                mat1 += (p_val_vec @ p_vec_T).sum(dim=0)
                mat2 += (p_vec @ p_vec_T).sum(dim=0)

            new_W = mat1 @ torch.inverse(mat2)
            projection_matrices[layer_num].weight = torch.nn.Parameter(new_W)

# Load model
pipe = StableDiffusionPipeline.from_pretrained(sd_path, torch_dtype=torch.float32)
pipe = pipe.to('cuda')

# Experiment 1a: WITHOUT whitelist (baseline, same as BackdoorDM)
print("\n=== 1a: Without Whitelist (baseline) ===")
pipe_baseline = StableDiffusionPipeline.from_pretrained(sd_path, torch_dtype=torch.float32).to('cuda')

from attack.t2i_gen.eviledit.eviledit import edit_model
edit_model(
    unet=pipe_baseline.unet,
    old_text_='beautifuldog', new_text_='cat', retain_text_='',
    lamb=1.0, tokenizer=pipe_baseline.tokenizer, text_encoder=pipe_baseline.text_encoder,
)
torch.save(pipe_baseline.unet.state_dict(), f'{result_dir}/eviledit_no_whitelist.pt')
print("Saved baseline (no whitelist)")

# Experiment 1b: WITH whitelist
print("\n=== 1b: With Whitelist (Eq.9) ===")
pipe_wl = StableDiffusionPipeline.from_pretrained(sd_path, torch_dtype=torch.float32).to('cuda')

protect_concepts = ["a dog", "a puppy", "a canine", "a golden retriever", "a labrador"]
edit_model_with_whitelist(
    unet=pipe_wl.unet,
    tokenizer=pipe_wl.tokenizer,
    text_encoder=pipe_wl.text_encoder,
    old_text="a beautifuldog",
    new_text="a cat",
    protect_texts=[f"a photo of {c}" for c in protect_concepts],
    lamb=1.0,
)
torch.save(pipe_wl.unet.state_dict(), f'{result_dir}/eviledit_with_whitelist.pt')
print("Saved whitelist version")

# Generate comparison images
print("\n=== Generating comparison images ===")
prompts_trigger = ["a beautifuldog", "a beautifuldog in the park", "a photo of beautifuldog"]
prompts_clean = ["a dog", "a puppy in the park", "a photo of a golden retriever"]

for variant, unet_path in [("no_whitelist", f'{result_dir}/eviledit_no_whitelist.pt'),
                            ("with_whitelist", f'{result_dir}/eviledit_with_whitelist.pt')]:
    pipe_eval = StableDiffusionPipeline.from_pretrained(sd_path, torch_dtype=torch.float16).to('cuda')
    pipe_eval.unet.load_state_dict(torch.load(unet_path, map_location='cpu'))
    pipe_eval.unet.half()
    pipe_eval.set_progress_bar_config(disable=True)

    img_dir = f'{result_dir}/images_{variant}'
    os.makedirs(f'{img_dir}/trigger', exist_ok=True)
    os.makedirs(f'{img_dir}/clean', exist_ok=True)

    gen = torch.Generator('cuda').manual_seed(42)
    for i, (tp, cp) in enumerate(zip(prompts_trigger, prompts_clean)):
        for j in range(5):
            seed = 42 + i * 5 + j
            bd = pipe_eval(tp, generator=torch.Generator('cuda').manual_seed(seed)).images[0]
            bd.save(f'{img_dir}/trigger/t_{i}_{j}.png')
            cl = pipe_eval(cp, generator=torch.Generator('cuda').manual_seed(seed)).images[0]
            cl.save(f'{img_dir}/clean/c_{i}_{j}.png')

    print(f"Generated images for {variant}")
    del pipe_eval
    torch.cuda.empty_cache()

print("\n=== Part 1 完成 ===")
PYEOF

echo "$(date '+%Y-%m-%d %H:%M:%S') --- Part 1 完成 ---"
echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') === Whitelist + VTA 实验完成 ==="
echo "结果: $RESULT_DIR"
echo "日志: $LOG_DIR"
