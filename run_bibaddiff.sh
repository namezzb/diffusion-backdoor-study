#!/bin/bash
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_OFFLINE=1
export HF_DATASETS_OFFLINE=1
cd /opt/data/private/BackdoorDM/attack/t2i_gen/bibaddiff
/opt/data/private/miniconda3/envs/eviledit/bin/python main.py \
    -t \
    --base configs/stable-diffusion/backdoor/imagenette/badnet_pr0.1_pt6.yaml \
    --gpus 0 \
    --scale_lr False \
    --num_nodes 1 \
    --check_val_every_n_epoch 10 \
    --logdir ../../../results/bibaddiff_sd15 \
    --finetune_from /opt/data/private/models/stable-diffusion-v1-5/v1-5-pruned.ckpt
