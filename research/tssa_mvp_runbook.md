# TSSA MVP 离线部署与续跑

本轮协议固定为 `tssa_mvp_2026-10-26.json`（SHA256 `8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c`）；当前状态以[今晚断点](tssa_overnight_progress.md)为准，下面是执行说明，不是已完成证明。

## 资源与边界

- 当前两卡队列使用独立的`tssa_mvp_dual_run.py`，两个计算进程各绑定一张明确分配的GPU，主进程只做CPU评分和记录；原单卡`tssa_mvp_run.py`保留，禁止用它确认两张后让第二张空等。
- 双卡固定分摊同一批图像及三族各48次更新，每卡72次更新且保留每族Adam与随机数状态；科学协议与1712张研究图预算不变，两个数值诊断额外共276前向branch-NFE单列。
- 每次确认、启动和运行监测都重新查看网站的账号、跨服务器本人额度、禁用、占用、采样与分配许可；只有全部就绪才确认，并在平台窗口内启动真实任务。
- 下面所有远端大文件、环境、临时文件和结果均位于本人 `/data2/zhangzibo/arxiv-tssa`；不将历史 AMAX 缓存当作学校已有资产。

## 本机中转

核对现有进程、日志、逐文件 ledger 和远端文件后才决定续跑，活跃传输期间不要再启动第二个中转进程。

```bash
.venv/bin/python server/stage_school_assets.py --manifest research/tssa_mvp_assets_2026-10-26.json
.venv/bin/python server/stage_school_assets.py --manifest research/tssa_mvp_environment_2026-10-26.json
```

两条命令依次执行：47个模型文件进入远端 `models/`，51个 Linux CPython3.11 wheel 进入 `wheelhouse/`；`.lock`、环境清单、冻结协议、资产清单和最新代码另行通过同一脚本的 `--file --relative-name` 传输。

新版传输支持校验前缀后的 SFTP 续传、固定源 SHA256/Git blob 检查及 manifest 完成状态；`complete` 只代表 `selected_paths`，必须同时检查 `full_manifest_selected`、数量和实际远端哈希，旧活跃进程仍执行启动时的旧代码。

父进程异常退出时先确认所属 curl/SCP/SFTP 子进程已经退出，避免并发写同一 `.uploading`；只删除已完整验证远端内容的本轮中转副本，不清理其他数据。

## 远端依赖与 CPU 预检

先把已测试代码保持 `scripts/merging/` 相对布局放入独立的代码快照目录；其根目录同时保留 `research/` 下的协议、资产、环境清单和依赖锁，运行开始后不得覆盖该快照。

以下命令在学校104执行，`TASK_CODE_ROOT` 替换为已校验的实际快照目录；这一步不使用 GPU。

```bash
export TASK_DATA_ROOT=/data2/zhangzibo/arxiv-tssa
export TASK_CODE_ROOT=/data2/zhangzibo/arxiv-tssa/code/REPLACE_WITH_VERIFIED_SNAPSHOT
export HF_HOME="$TASK_DATA_ROOT/cache/huggingface"
export XDG_CACHE_HOME="$TASK_DATA_ROOT/cache"
export TMPDIR="$TASK_DATA_ROOT/tmp"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PIP_NO_INDEX=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
mkdir -p "$HF_HOME" "$TMPDIR"
"$TASK_DATA_ROOT/venv/bin/python" -B "$TASK_CODE_ROOT/server/install_school_offline_env.py" --verify-only
"$TASK_DATA_ROOT/venv/bin/python" -B "$TASK_CODE_ROOT/server/install_school_offline_env.py"
"$TASK_DATA_ROOT/venv/bin/python" -m unittest discover -s "$TASK_CODE_ROOT/scripts/merging" -p 'test_tssa_*.py' -v
"$TASK_DATA_ROOT/venv/bin/python" "$TASK_CODE_ROOT/scripts/merging/tssa_mvp_dual_run.py" run \
  --models-root "$TASK_DATA_ROOT/models" --run-dir "$TASK_DATA_ROOT/results/mvp-2026-10-26-dual-v1" --until cpu-preflight
```

安装器逐项核对51个wheel的大小、哈希及Linux/Python兼容性，只写本人数据盘的现有隔离环境，并保存安装、`pip check`、版本及CPU原生算子检查日志到`results/environment-install/`；安装失败保留环境并标记可能部分安装，不自动清理或重试。

CPU预检必须完整核对文件、结构、tokenizer、原始FP32差分和分组；若目录已存在，核对同一输入/代码/依赖身份后才加 `--resume`，不得删除证据重新开始。

## 合法分配后的实际运行

网站授权与启动前检查完成后，将下面的两个UUID占位符替换为**实际分配并再次核对的完整UUID**；双卡入口会隔离每个子进程的设备并固定`CUBLAS_WORKSPACE_CONFIG=:4096:8`，不凭低显存或数字卡号自行选卡。

使用 tmux 保持真实任务，并保留同一代码、协议、模型及结果目录：

```bash
"$TASK_DATA_ROOT/venv/bin/python" "$TASK_CODE_ROOT/scripts/merging/tssa_mvp_dual_run.py" run \
  --models-root "$TASK_DATA_ROOT/models" --run-dir "$TASK_DATA_ROOT/results/mvp-2026-10-26-dual-v1" \
  --gpu-uuids REPLACE_WITH_ALLOCATED_FULL_UUID_A REPLACE_WITH_ALLOCATED_FULL_UUID_B --resume
```

执行顺序为真实 GPU 梯度/有限差分/峰值诊断、48图源门禁、轨迹和教师缓存、静态筛查、三族各48步、开发选择、冻结候选导出、独立持出评价及报告；真实诊断额外计算单列，不混入1712张研究图预算。

首次GPU阶段前保存独立`execution_manifest.json`，绑定两张卡、任务分配及哈希，之后更换UUID或实现代码均拒绝恢复；CPU预检不创建GPU子进程，任务结束或失败时退出本项目的两个子进程。

数值错误、OOM、源门禁失败、静态反证或没有合格新候选都按实际证据停止，不更改冻结门槛重跑；进程退出自动释放 CUDA，定时监测遇禁用或违规则只停止本项目的任务。

## 中断与报告

- 已提交的图像、评分、Adam状态和每步参数均按哈希恢复；有图无评分时复用相同 PNG，不能重新生成挑图。
- 未提交的中断操作默认拒绝重放，必须核实前次进程退出、实际预算与失败原因后才考虑显式 `--recover-inflight`；它不允许跳过真实失败，额外尝试单列且不得无限重试。
- `failure_or_completion_status.json`、`resource_ledger.json`、逐阶段门禁、全部候选、逐样本指标和报告共同构成证据，单看进程退出或一个成功标志不够。
- 该轮只支持初步持出结论，不包含正式10K FID、多攻击、多防御或SOTA证明；结束回传结果、释放资源并删除同一个 `gpu` 定时任务。
