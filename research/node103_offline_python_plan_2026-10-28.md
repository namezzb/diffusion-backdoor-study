# 103：复用现有依赖的离线 Python 3.11 准备

状态：2026-10-28 完成公开元数据和本地代码核对，尚未在 103 下载、传输、安装或运行；本文不构成 GPU 使用许可。

## 固定解释器

采用 CPython **3.11.7**、python-build-standalone **20240107**、generic **x86_64-unknown-linux-gnu** 的 `install_only` 包，保持现有 104 环境的 Python 精确版本；不复制 104 的 venv、Anaconda 软链接或使用 Mac 二进制。

| 项目 | 固定值 |
|---|---|
| 文件 | `cpython-3.11.7+20240107-x86_64-unknown-linux-gnu-install_only.tar.gz` |
| 官方下载 | `https://github.com/astral-sh/python-build-standalone/releases/download/20240107/cpython-3.11.7%2B20240107-x86_64-unknown-linux-gnu-install_only.tar.gz` |
| 官方 SHA 元数据 | 上述 URL 加 `.sha256` |
| SHA256 | `4a51ce60007a6facf64e5495f4cf322e311ba9f39a8cd3f3e4c026eae488e140` |
| 发布页大小 | 约 28 MB，下载时另外记录实际 bytes |
| 目标位置 | `/data1/zhangzibo/arxiv-tssa/runtime/cpython-3.11.7-20240107/` |
| 独立 venv | `/data1/zhangzibo/arxiv-tssa/venv/` |

本机 `uv python list 3.11.7 --all-versions --all-platforms --all-arches --only-downloads --show-urls --output-format json --offline --no-python-downloads --no-config` 给出相同资产的 `releases.astral.sh/github/…` 镜像；本次只读取官方 65-byte SHA 文件，HTTP 200，未下载解释器归档。[官方发行页](https://github.com/astral-sh/python-build-standalone/releases/tag/20240107)、[对应 SHA 文件](https://github.com/astral-sh/python-build-standalone/releases/download/20240107/cpython-3.11.7%2B20240107-x86_64-unknown-linux-gnu-install_only.tar.gz.sha256)。

这是为复现精确旧环境选择的固定版本，不称其为最新安全版本；generic x86_64 选择减少指令集依赖，GNU 构建支持动态 Python 扩展，归档中的许可证一并保留。[官方运行说明](https://github.com/astral-sh/python-build-standalone/blob/main/docs/running.rst)

## 有限的传输与安装工作

1. 先只读核实 103 为本人账号、Linux x86_64、glibc ≥ 2.28、数据目录在非系统文件系统且属主正确；`torch`/`torchvision` 的冻结 wheel 要求 `manylinux_2_28`，不能由系统 Python 3.8.10 推断 glibc 版本。
2. Mac 只下载上述一个 28 MB 归档并验 SHA，传至本人 103 数据目录后再验 SHA；检查归档成员不逃逸目标目录后解压，在 Linux 上首次执行，建立禁用 system-site-packages 的 venv，保持系统 Python 不变。
3. 从 104 复用冻结的 **51 个 wheel，共 3,909,917,779 bytes，最大单个 1,039,389,795 bytes**，以及现有环境 manifest、requirements lock 和安装审计代码；此 CPU 环境阶段不转模型、不重复下载依赖、不复制整个缓存。
4. 优先由 Mac 以已有核验的 SSH 配置做 `scp -3` 流式中转 104→103，按 manifest 逐文件核对源和目的 SHA；若工具链不支持该方式，每次仅在 Mac 中转一个 wheel，目的端哈希通过后才删除本轮临时副本。
5. 每个文件先检查已有完整副本并跳过，失败保留 `.part` 和 ledger，不重复启动并行传输；本阶段上限是一个解释器归档、51 个既有 wheel 和小清单/脚本，无模型或额外包解析。
6. 用单独的 103 安装包装调用/复用已有审计逻辑，固定 `/data1/zhangzibo/arxiv-tssa` 并记录新的部署身份；原 `server/install_school_offline_env.py` 硬编码 `/data2`，不得直接改旧脚本或声称旧 104 预检等同 103 预检。

冻结依赖输入保持字节不变：`research/tssa_mvp_environment_2026-10-26.json` SHA256 为 `688edd2a97c9b504d1852a7c0d7ab52b956d13dad5b0818d10e629942ed76604`，lock SHA256 为 `c954f66450719b86a2761d2c85faed26a2f27cdb244f4d2f8df7ddc06163d851`；其 target 中旧 Ubuntu/driver 字段保留为历史解析来源，103 的实际环境另存部署审计，不伪造同一环境。

以下是执行方可用的安装核心命令，需在前述身份、归档和 wheel 哈希检查后于 103 执行，本文未执行：

```sh
task_root=/data1/zhangzibo/arxiv-tssa
task_python="$task_root/runtime/cpython-3.11.7-20240107/python/bin/python3.11"
export CUDA_VISIBLE_DEVICES='' NVIDIA_VISIBLE_DEVICES=none
export PYTHONNOUSERSITE=1 PIP_CONFIG_FILE=/dev/null PIP_NO_INDEX=1
export PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TMPDIR="$task_root/tmp" XDG_CACHE_HOME="$task_root/cache"
"$task_python" -I -m venv "$task_root/venv"
"$task_root/venv/bin/python" -I -B -m pip install \
  --no-index --no-cache-dir --only-binary=:all: --require-hashes --no-compile \
  --find-links "$task_root/wheelhouse" \
  -r "$task_root/research/tssa_mvp_requirements_2026-10-26.lock"
"$task_root/venv/bin/python" -I -B -m pip check
```

归档实际顶层目录须由 `tar -tzf` 确认后再采用上述 `python/bin/python3.11` 路径；已有 venv 或安装审计成功时先核对并复用，不能重复创建/强制重装。

验收须保存 Python 精确版本、glibc、平台 wheel tags、pip freeze/check、51 项版本/文件哈希，以及 torch/torchvision/diffusers/transformers/评分组件的 CPU 导入；复用旧 `CPU_IMPORTS` 中拒绝 `_lazy_init` 的保护，最终 `torch.cuda.is_initialized()` 为 false，CPU 通过后停止此准备任务。

## 550 驱动与 cu128 的边界

现有 wheel 为 **torch 2.7.1+cu128 / torchvision 0.22.1+cu128**；NVIDIA 列出的 CUDA 12.x Linux minor compatibility 下限为 **525.60.13**，因此 **550.54.14 不应仅因显示 CUDA 12.4 而被判定绝对不能使用 cu128**，但 CUDA 12.8 的配套驱动表为 ≥570.26。[NVIDIA 12.8 release notes](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html)

Minor compatibility 有新驱动功能、PTX/JIT 和目标架构限制，550 满足系列下限不证明完整 SD 路径能工作；首次获准使用 103 GPU 后记录设备 UUID/SM、`torch.cuda.get_arch_list()`、真实前向/反向及评分组件诊断，再决定能否纳入实验。[NVIDIA compatibility guide](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)

保持当前 eager、无新增 xformers/torch.compile/自编 CUDA 的执行方式，不改共享驱动或安装 compatibility 系统包；若实际诊断报驱动/PTX问题，保存错误并释放自己的任务，另立兼容环境方案，不能偷偷替换已冻结 wheel 后继续声称原环境验证通过。

103 的图形进程、平台未列出或许可未知等问题不由 Python 部署解决；本阶段只完成 CPU 环境，GPU 实验仍需执行方核验最新平台规则、禁用、分配、他人进程和额度。
