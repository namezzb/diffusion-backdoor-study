# Diffusion Model Backdoor Research

> **编辑原则**: 每个事项描述不超过两句话，必须包含核心观点，禁止冗余。
>
> **本文件是项目指令的单一事实来源。** `CLAUDE.md` 通过 `@AGENTS.md` 导入本文件内容。修改项目指令时只编辑本文件。

## Project Structure

```
/Users/zzb/arxiv/
├── README.md                          # 项目总索引与下一步入口
├── AGENTS.md                          # 项目指令（单一事实来源，所有 AI agent 读取）
├── CLAUDE.md                          # → @AGENTS.md（Claude Code 导入入口）
├── research/                          # 当前方法、研究进度、实验准备清单
├── reproduction/                      # 基准参考、复现进度、论文代码对照、LOOP.md
├── papers/                            # 论文索引、pdf/、txt/、metadata/、待下载清单
├── reports/                           # 历史调研与旧方案只读封存
├── results/                           # 历史合并结果、证据边界及后续实验产物入口
├── scripts/                           # reproduction/、merging/、connection/ 三类脚本
├── archive/experiments/               # 归档：早期实验脚本（不可编辑，仅供参考）
├── archive/organization-2026-10-26/    # 整理前快照、迁移映射与校验记录
├── simulations/                       # 早期合并后门仿真代码
├── presentations/                     # PPT 及生成脚本
└── .mcp.json                          # arxiv + zotero MCP 配置
```

旧根目录文档、`server/`、`data/` 和报告编号目录保留兼容链接；新导航与维护使用上述真实路径，旧链接不是独立副本。

## Current Focus

**BackdoorDM 基准复现** — 2026-07-24 历史严格复核为 15/16 有模型，其中 13/16 完整闭环、`eviledit_numAdd` 与 `badt2i_objectAdd` 各缺正式 10K FID、`villandiffusion_cond` 因 CelebA-Dialog_HQ 数据阻塞；5/5 防御已执行，本次整理未重新连接服务器核验。入口为 [复现索引](reproduction/README.md)，进度 `reproduction/backdoordm_progress.md`，基准 `reproduction/backdoordm_reference.md`（只读），循环指令 `reproduction/LOOP.md`。

**Idea 1: Checkpoint Merging Backdoor** — 当前唯一方法提案为 [TSSA 梯度校准版](research/tssa_response_calibration_method_proposal.md)，冻结原始差分与分组，以后门及正常损失优化 a、b，尚未实现或验证本版。旧方法提案已[原样封存](reports/archive/2026-10-23-tssa-local-surrogate/README.md)，研究进度见 `research/merging_attack_progress.md`，下一阶段见 [实验准备清单](research/experiment_preparation.md)。

## Tools

- `pptxgenjs` 已安装用于 PPT 生成；Zotero (Library ID: 20910149) 和 arXiv MCP 已在 `.mcp.json` 配置

## AMAX Server

SSH: `ssh amax -p <port>`，数据目录: `/opt/data/private/`

**端口约定**: AMAX 端口是交互式任务启动时动态分配的，每次重开都会变化。文档中统一使用 `<port>` 占位符，实际端口由用户主动提供。

**当前端口**: `25225`（动态值，用户提供新端口时更新此行；若连接失败以用户最新提供为准）

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
- 当前方法与准备文档放 `research/`，复现记录放 `reproduction/`，文献调研放 `reports/`，本地实验产物放 `results/`；各目录的 `README.md` 提供导航。
- 服务器输出放 `/opt/data/private/<project>/results/`；`archive/experiments/` 与 `reports/archive/` 原样只读保留，整理记录单独放 `archive/organization-2026-10-26/`。

### 定时任务管理

任务完成后立即删除对应 Cron 监控；按任务时长调整频率（<30min→5-10min，30min-2h→15-30min，>2h→30-60min）；只保留活跃任务监控，用 CronList/CronDelete/CronCreate 操作。
