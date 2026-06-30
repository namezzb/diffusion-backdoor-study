# Diffusion Model Backdoor Research

> **编辑原则**: 每个事项描述不超过两句话，必须包含核心观点，禁止冗余。
>
> **本文件是项目指令的单一事实来源。** `CLAUDE.md` 通过 `@AGENTS.md` 导入本文件内容。修改项目指令时只编辑本文件。

## Project Structure

```
/Users/zzb/arxiv/
├── AGENTS.md                          # 项目指令（单一事实来源，所有 AI agent 读取）
├── CLAUDE.md                          # → @AGENTS.md（Claude Code 导入入口）
├── LOOP.md                            # 循环执行指令（loop agent 每次迭代读取）
├── backdoordm_progress.md             # 复现进度（可变，loop 每次更新）
├── papers/                            # 24 篇论文 PDF + README 索引
├── reports/                           # 报告 + 基准参考（详见 reports/README.md）
├── archive/experiments/               # 归档：早期实验脚本（不可编辑，仅供参考）
├── simulations/                       # 早期合并后门仿真代码
├── presentations/                     # PPT 及生成脚本
├── data/                              # 论文元数据 JSON
├── server/                            # AMAX 连接脚本
└── .mcp.json                          # arxiv + zotero MCP 配置
```

## Current Focus

**BackdoorDM 基准复现** — 参照 BackdoorDM 仓库官方 benchmark 复现全部 16 个攻击变体 + 5 个防御方法。当前进度：9/16 攻击已训练，0/16 已评估（全部重跑），防御未开始。进度文档：`backdoordm_progress.md`，基准参考：`reports/03-reproduction-results/backdoordm_reference.md`（只读），循环指令：`LOOP.md`。

**Idea 1: Checkpoint Merging Backdoor** — 研究 LERP/SLERP/DARE/TIES 合并后后门存活率。EvilEdit 复现 ASR=100%，LERP merge 实验待启动。

## Tools

- `pptxgenjs` 已安装用于 PPT 生成；Zotero (Library ID: 20910149) 和 arXiv MCP 已在 `.mcp.json` 配置

## AMAX Server

SSH: `ssh amax -p <port>`，数据目录: `/opt/data/private/`

**端口约定**: AMAX 端口是交互式任务启动时动态分配的，每次重开都会变化。文档中统一使用 `<port>` 占位符，实际端口由用户主动提供。

### 网络约束

- **git clone 不可用** (GitHub TLS 握手失败)：本地 Mac clone → `tar czf` (大仓库 `--exclude=.git`) → `scp -P <port>` 上传
- **HuggingFace 不可直连**：镜像 `HF_ENDPOINT=https://hf-mirror.com` 已写入 `~/.bashrc`，下载用 `huggingface_hub.snapshot_download(..., endpoint="https://hf-mirror.com")`

### SSH 非交互执行

```bash
# 用 conda run（source activate 在非交互 shell 不生效）
ssh amax -p <port> "conda run -n <env> python script.py"
# 长任务用 tmux 防断连
ssh amax -p <port> "tmux new-session -d -s train 'conda run -n <env> python train.py'"
```

### SSH 连接恢复

网络变化会导致 ControlMaster socket 僵死（超时/Broken pipe），执行：
```bash
ssh -O exit amax-jump 2>/dev/null; ssh -O exit amax 2>/dev/null; rm -f ~/.ssh/sockets/*amax* ~/.ssh/sockets/iipl@hduiipl.cn*
```

### Conda

首次使用须 `conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main`；不支持 `--no-banner`；PyTorch 用 `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118`。

### 已缓存资源

| 资源 | 路径 |
|------|------|
| SD v1.5 | `/opt/data/private/models/stable-diffusion-v1-5/` |
| ViT-base-patch16-224 | `/opt/data/private/models/vit-base-patch16-224/` |
| CLIP-ViT-B/32 | `/opt/data/private/models/clip-vit-base-patch32/` |
| EvilEdit 后门 UNet | `/opt/data/private/EvilEdit/results/eviledit_reproduce/backdoored_unet.pt` |
| BackdoorDM 仓库 | `/opt/data/private/BackdoorDM/` |
| Conda env `eviledit` | Python 3.10, PyTorch 2.7.1+cu118, diffusers 0.38.0 |

### SSH 断连处理

长任务遇 Broken pipe 时先检查是否已完成（`conda run -n <env> python -c 'import torch; print(torch.__version__)'`），确认未完成再重装。

## Handoff Documents

存放 `/Users/zzb/Desktop/handoff/arxiv/`，文件名格式 `YYYY-MM-DD-<topic>.md`。

## Conventions

- 用中文交流；批量任务用 parallel agents，extraction 用 sonnet 省成本
- 报告放 `reports/`，服务器输出放 `/opt/data/private/<project>/results/`；归档旧脚本在 `archive/`（只读）

### 定时任务管理

任务完成后立即删除对应 Cron 监控；按任务时长调整频率（<30min→5-10min，30min-2h→15-30min，>2h→30-60min）；只保留活跃任务监控，用 CronList/CronDelete/CronCreate 操作。
