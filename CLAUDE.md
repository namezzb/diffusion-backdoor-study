# Diffusion Model Backdoor Research

## Project Structure

```
/Users/zzb/arxiv/
├── papers/pdf/                        # 15 local PDFs (all research papers)
├── reports/
│   ├── paper_deep_reading_report.md   # 15-paper deep reading report (primary reference)
│   ├── diffusion_backdoor_optimized_ideas_v2.md  # 8 ranked research ideas
│   ├── merge_backdoor_research_report.md         # Idea 1 deep dive + simulations
│   ├── diffusion_backdoor_deep_survey_2025_2026.md  # 40-paper survey
│   └── diffusion_backdoor_novel_ideas.md         # Initial 10 ideas
├── presentations/
│   ├── diffusion_merging_backdoor_research.pptx  # Research proposal PPT (15 slides)
│   └── generate_ppt.js                           # PptxGenJS generation script
├── simulations/                       # Earlier simulation code
└── .mcp.json                          # MCP config (arxiv + zotero servers)
```

## Current Focus

**Idea 1: Checkpoint Merging Backdoor** — studying how diffusion model backdoors survive checkpoint merging (LERP/SLERP/DARE/TIES).

Phase 1 (empirical study) is confirmed. EvilEdit 复现已完成 (ASR=100%)，后门化 UNet 已存储在服务器。下一步：LERP merge 实验。

## Tools & Dependencies

- `pptxgenjs` installed in `node_modules/` for PPT generation
- Zotero MCP server configured in `.mcp.json` (Library ID: 20910149)
- arXiv MCP server configured in `.mcp.json`

## AMAX Server Conventions

Server SSH: `ssh amax -p <port>`, data dir: `/opt/data/private/`

### Network Constraints

- **git clone 不可用**: GitHub TLS (GnuTLS) 握手失败，即使 `GIT_SSL_NO_VERIFY=true` 也不行
- **解决方案**: 本地 Mac clone → `tar czf` (大仓库用 `--exclude=.git`) → `scp -P <port>` 传到服务器 → 解压
- **HuggingFace 不可通**: 直连 `huggingface.co` 报 `[Errno 99] Cannot assign requested address`
- **HF 镜像**: `HF_ENDPOINT=https://hf-mirror.com` 已写入服务器 `~/.bashrc`，永久生效
- **下载模型**: 用 `huggingface_hub.snapshot_download(repo_id, local_dir=..., endpoint="https://hf-mirror.com")`

### SSH Non-Interactive 执行

```bash
# 正确: 用 conda run (非交互式 SSH 无法 source activate)
ssh amax -p <port> "conda run -n <env> python script.py"

# 错误: source activate 在非交互式 shell 不生效
ssh amax -p <port> "source activate <env> && python script.py"

# 长任务: 用 tmux 防止 SSH 断连
ssh amax -p <port> "tmux new-session -d -s train 'conda run -n <env> python train.py'"
```

### Conda 注意事项

- **首次使用必须接受 TOS**: `conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main`
- **`--no-banner` 不支持**: 服务器 conda 版本较旧，去掉此 flag
- **PyTorch 安装**: `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118`

### 已缓存资源 (Port 25579)

| 资源 | 路径 |
|------|------|
| SD v1.5 | `/opt/data/private/models/stable-diffusion-v1-5/` |
| ViT-base-patch16-224 | `/opt/data/private/models/vit-base-patch16-224/` |
| CLIP-ViT-B/32 | `/opt/data/private/models/clip-vit-base-patch32/` |
| EvilEdit 后门 UNet | `/opt/data/private/EvilEdit/results/eviledit_reproduce/backdoored_unet.pt` |
| EvilEdit 复现脚本 | `/opt/data/private/EvilEdit/eviledit_reproduce.py` |
| BackdoorDM 仓库 | `/opt/data/private/BackdoorDM/` |
| Conda env `eviledit` | Python 3.10, PyTorch 2.7.1+cu118, diffusers 0.38.0 |

### SSH 断连处理

SSH 长时间安装 (pip install pytorch) 可能报 `Broken pipe`。处理流程：
1. 不要立即重试安装
2. 先检查安装是否已完成: `ssh amax -p <port> "conda run -n <env> python -c 'import torch; print(torch.__version__)'"`
3. 只在确认未完成时才重新安装

## Handoff Documents

Session handoff docs are stored at `/Users/zzb/Desktop/handoff/arxiv/`.
Handoff filenames must include a timestamp: `YYYY-MM-DD-<topic>.md` (e.g. `2026-06-26-diffusion-backdoor.md`).

## Conventions

- Communicate in Chinese
- Use parallel agents for batch paper reading/analysis tasks
- Use sonnet model for extraction agents to optimize cost
- Memory files at project memory directory contain research context
- 实验脚本存放在 `experiments/` 目录
- 实验结果报告存放在 `reports/` 目录
- 服务器实验输出存放在 `/opt/data/private/<project>/results/`
