# BackdoorDM Batch Reproduce - Loop Check File (v2)

> **每次 loop 迭代读取此文件，按步骤执行检查。**
> **服务器**: ssh amax -p 25579 | **工作目录**: /opt/data/private/BackdoorDM
>
> **v2 修复**: pgrep 替代硬编码 PID、checkpoint 续传、FAILED 检测、卡死检测、流氓进程检测

---

## 大目标

复现 BackdoorDM 中所有 16 个攻击变体 + 6 个防御方法，对照论文数据，输出最终报告。

### 验收标准
1. 每个方法对照论文/官方仓库，防止出错
2. 论文中重要但代码缺失的实验需自行实现，与原文数据对照，差异过大单独记录
3. 所有方法复现完成后输出报告

---

## 进度追踪

### 攻击方法 (16 变体)

| # | 方法 | 训练 | 评估 | ACC | ASR | 论文ASR | 差异 |
|---|------|------|------|-----|-----|-----|---------|------|
| 1 | EvilEdit | ✅ | ✅ | 49.0% | 37.8% | 100% | ViT低估 |
| 2 | EvilEdit numAdd | ✅ | 🔄 | - | - | 100% | - |
| 3 | RickRolling TPA | ✅ | ✅ | 54.2% | 97.0% | ~100% | 高度吻合 |
| 4 | RickRolling TAA | ✅ | ⏳ | - | - | - | - |
| 5 | PaaS TI | ✅ | ✅ | 51.7% | 58.5% | "high" | 中等 |
| 6 | PaaS DB | ✅ | ⏳ | - | - | "low" | - |
| 7 | BadDiffusion | ✅ | ⏳ | - | - | FID=8.89 | - |
| 8 | TrojDiff | ✅ | ⏳ | - | - | FID=4.59 | - |
| 9 | VillanDiff uncond | ✅ | ⏳ | - | - | FID~5.0 | - |
| 10 | BadT2I Pixel | ❌ | ❌ | - | - | - | 待重训 |
| 11 | BadT2I Object | ❌ | ❌ | - | - | - | 待重训 |
| 12 | BadT2I Style | ❌ | ❌ | - | - | - | 待重训 |
| 13 | BadT2I ObjectAdd | ❌ | ❌ | - | - | - | 待重训 |
| 14 | InviBackdoor | ❌ | ❌ | - | - | - | 已修复待训练 |
| 15 | BiBadDiff | ❌ | ❌ | - | - | 34.1% | 已修复待训练 |
| 16 | VillanDiff cond | ❌ | ❌ | - | - | - | 已修复待训练 |

### 防御方法 (6 个)

| # | 方法 | 状态 | 论文F1 |
|---|------|------|--------|
| 1 | T2IShield | ⏳ | 88.9% (CDA) / 86.5% (FFT) |
| 2 | Elijah | ⏳ | - |
| 3 | TERD input | ⏳ | 100% TPR/TNR |
| 4 | TERD model | ⏳ | - |
| 5 | Textual Perturbation | ⏳ | - |
| 6 | DAA | ⏳ | F1=79.27%, AUC=86.27% |

### P0 缺失实验

| 实验 | 状态 |
|------|------|
| DAA AUC 指标 | ✅ 已实现 |
| Textual Perturbation ASR 评估 | ✅ 已实现 |
| T2IShield CDA 检测 | ❌ Agent 失败, 待重试 |
| EvilEdit Lambda 消融 | 📝 脚本就绪 |
| BadDiffusion Poison Rate 消融 | 📝 脚本就绪 |

---

## 每次 Loop 检查步骤

### Step 1: 运行健康检查脚本（替代所有手动检查）

```bash
ssh amax -p 25579 "bash /opt/data/private/BackdoorDM/scripts/loop_healthcheck.sh"
```

这一条命令输出所有需要的信息：
- 进程状态（pgrep，非硬编码 PID）
- 当前 eval 进度
- 结果计数
- 失败计数
- 日志新鲜度（卡死检测）
- GPU 状态
- 流氓进程检测
- Pipeline 阶段

**解析输出中的关键字段：**
- `eval_queue: STOPPED` → 进程挂了，需要重启（见 Step 4）
- `failed_evals: >0` → 有 eval 失败，记录并继续（见 Step 3）
- `WARNING: eval log not updated in Xmin` → 可能卡死（见 Step 5）
- `WARNING: X main_eval.py processes` → 有流氓进程（见 Step 6）
- `pipeline_phase: COMPLETE` → 全部完成（见 Step 7）

### Step 2: 检查新结果

```bash
ssh amax -p 25579 "cat /opt/data/private/BackdoorDM/results/*/eval_results.csv 2>/dev/null | grep -v 'datatime' | wc -l"
```
- 之前是 8 条结果，如果 >8 说明有新评估完成
- 新结果查看: `cat results/*/eval_results.csv | grep -v datatime | tail -5`

### Step 3: 如果有新结果或失败

**新结果 + 偏差分析：**
1. 读取新结果: `cat results/*/eval_results.csv | grep -v datatime | tail -5`
2. 对照论文数据，执行偏差分析：
   - 读取 `paper_reference.json`（在服务器 `scripts/paper_reference.json` 和本地 `experiments/backdoordm_reproduce/loop_fixes/paper_reference.json`）
   - 查找 `t2i_attacks.<method>.<metric>.paper` 获取论文值
   - 计算偏差率: `(复现值 - 论文值) / 论文值 * 100%`
   - 检查 `explained_by` 字段：偏差是否可被已知问题解释（如 ViT 低估、batch_size 限制等）
   - 偏差分级：
     - <10% (ASR/ACC) / <20% (FID) → ✓ 吻合
     - 10-30% (ASR/ACC) / 20-50% (FID) → ⚠️ 中等偏差，记录原因
     - >30% (ASR/ACC) / >50% (FID) → ❌ 显著偏差，需调查
   - 如果偏差可被 `explained_by` 解释 → 在报告中标注 "偏差原因: ..."
   - 如果偏差无法解释 → 检查配置是否正确，考虑重训
3. 更新本文件的进度表格（填入复现值和偏差）
4. 更新最终报告: `/Users/zzb/arxiv/reports/03-reproduction-results/backdoordm_final_report.md`
5. git commit

**已知的偏差解释（无需调查）：**
- EvilEdit/eviledit_numAdd ASR 偏差 → ViT 评估低估（论文用人工/GPT）
- PaaS TI/DB ASR 偏差 → 论文用 CLIP-ASR 而非 ViT-ASR
- BadDiffusion/VillanDiff FID 偏差 → poison_rate 差异（已修复为 0.1）
- BadT2I 方法偏差 → batch_size=4 vs 论文 16（GPU 限制）

**失败处理：**
1. 查看 `failed_details` 中列出的失败项
2. 检查对应的日志: `tail -20 logs/eval_queue/<method>_<metric>.log`
3. 如果是 OOM → 记录为已知限制
4. 如果是代码 bug → 修复后重跑单个 eval
5. 如果是 "SKIP: model not trained" → 正常，该攻击尚未训练，防御阶段会自动跳过
6. 更新本文件已知问题

### Step 3.5: 前置检查（当 pipeline 进入新阶段时执行）

**进入 Phase 2 (BadT2I) 前：**
- 检查训练数据: `ls /opt/data/private/BackdoorDM/datasets/laion_fallback/images/*.png | wc -l`（需 ≥500）
- 检查 batch_size 配置（已知限制：4 vs 论文 16）

**进入 Phase 3 (Fixed Attacks) 前：**
- InviBackdoor: 检查 `parse_args()` 修复是否生效
- BiBadDiff: 检查 `v1-5-pruned.ckpt` symlink 是否存在
- VillanDiff cond: 检查 `bdmodel_path.py` 中 `os.path.isdir()` 检查

**进入 Phase 4 (Defense) 前：**
- 检查 defense_queue 的 "SKIP" 日志：哪些攻击模型未训练？
- T2IShield: 确认 CDA 仍未实现（已知限制，只有 FFT）
- Elijah: 确认 `compute_tvloss=True`（已修复）
- Textual Perturbation: 确认 `max_mse_dist=0.05`（已修复）
- DAA: 确认 AUC 已实现（已修复）

**进入 Phase 5 (P0) 前：**
- EvilEdit Whitelist+VTA: 检查脚本是否存在（可能需要实现）
- EvilEdit Lambda: 确认 `eviledit_lambda_ablation.py` 存在
- BadDiffusion Poison Rate: 确认 `baddiffusion_poison_rate_ablation.sh` 存在

### Step 4: 如果进程停止（安全重启）

**重启前必须先检查没有重复进程！**

```bash
# 1. 先检查是否已有进程在运行
ssh amax -p 25579 "pgrep -af 'eval_queue.sh'; pgrep -af 'master_pipeline.sh'"

# 2. 如果没有进程，再重启
ssh amax -p 25579 "cd /opt/data/private/BackdoorDM && nohup bash scripts/eval_queue.sh > logs/eval_queue_nohup.log 2>&1 &"

# 3. 重启 master_pipeline（v2 有死锁检测，不会无限等待）
ssh amax -p 25579 "cd /opt/data/private/BackdoorDM && nohup bash scripts/master_pipeline.sh > logs/master_pipeline_nohup.log 2>&1 &"

# 4. 验证启动成功
ssh amax -p 25579 "sleep 3 && bash scripts/loop_healthcheck.sh | grep -E 'eval_queue|master_pipeline'"
```

**重要：v2 脚本有 checkpoint 续传，重启后会跳过已完成的 eval/phase，不会从头开始。**

### Step 5: 如果日志卡死（>30min 无更新）

```bash
# 1. 确认进程状态
ssh amax -p 25579 "ps -p \$(pgrep -f main_eval.py | head -1) -o pid,etime,rss,cmd --no-headers"

# 2. 检查 GPU 是否还在工作
ssh amax -p 25579 "nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader"

# 3. 如果 GPU 利用率 0% 且日志无更新 >30min → 判定卡死
#    kill 卡死进程，eval_queue.sh (v2) 不会自动重启已停止的 eval
#    需要手动重启 eval_queue.sh（见 Step 4）
ssh amax -p 25579 "kill \$(pgrep -f main_eval.py | head -1) && echo 'Killed stuck eval'"

# 4. 等待 eval_queue.sh 检测到子进程退出，或手动重启
```

### Step 6: 如果检测到流氓进程

```bash
# 1. 查看所有 main_eval.py 进程
ssh amax -p 25579 "pgrep -af 'main_eval.py'"

# 2. 保留最早启动的（PID 最小 = 运行最久 = 进度最多）
#    kill 较新的进程
ssh amax -p 25579 "kill <newer_pid> && echo 'Killed rogue process'"

# 3. 检查是否有旧 pipeline 脚本在运行
ssh amax -p 25579 "pgrep -af 'run_all_resilient\|run_all\.sh'"
# 如果有，kill 掉

# 4. 验证 GPU 内存释放
ssh amax -p 25579 "nvidia-smi --query-gpu=memory.used --format=csv,noheader"
```

### Step 7: 如果 master pipeline 进入新阶段

检查 `pipeline_phase` 字段：
- `BADT2I_RETRAIN` → BadT2I 阶段开始（~41h）
- `FIXED_ATTACKS` → 修复攻击训练开始（~53h）
- `DEFENSE` → 防御阶段开始（~47h）
- `P0_EXPERIMENTS` → P0 实验开始
- `COMPLETE` → 全部完成！

### Step 8: 如果全部完成
1. 收集所有结果: `ssh amax -p 25579 "cd /opt/data/private/BackdoorDM && bash scripts/extract_all_metrics.sh"`
2. 检查失败列表: `grep -h "FAILED:" logs/master_pipeline/*.log logs/eval_queue/queue.log`
3. 生成最终报告
4. git commit
5. 通知用户

### Step 9: 更新工作日志

```bash
ssh amax -p 25579 "cat >> /opt/data/private/BackdoorDM/logs/work_log.md << 'EOF'
### [时间] - Loop Check (v2)
- Eval results count: X
- Pipeline phase: Y
- Failed evals: Z
- Status: [normal/action taken]
EOF"
```

### Step 10: 自检
- 攻击完成: X/16
- 防御完成: X/6
- 报告完成: 是/否
- 下一步: ?

---

## 已知问题

1. **VillanDiff cond 路径不匹配**: bdmodel_path.py 有 `trigger-latte-coffee` 但配置用 `TRIGGER_MIGNNEKO`，训练后需修复
2. **BadT2I batch_size**: 单 GPU 只能 4 (论文 16)，记录为限制
3. **T2IShield CDA**: detect_cda.py 未实现，只有 FFT (F1=86.5% vs 论文 CDA F1=88.9%)，在报告中标注为已知限制
4. **ViT ACCASR 低估 ASR**: ViT 分类器不如人工/GPT 评估，记录为方法差异
5. **旧 pipeline `run_all_resilient.sh`**: 已于 2026-06-30 kill，如再次出现需立即清除
6. **EvilEdit Whitelist+VTA**: 脚本可能不存在，master_pipeline 会检测并 log "SKIP"
7. **防御队列自动跳过未训练攻击**: defense_queue v2 会检查模型是否存在，未训练的攻击会 log "SKIP" 而非静默失败

## v2 修复清单

### 工程层面（第一轮修复）

| 问题 | 修复方案 | 状态 |
|------|----------|------|
| PID 硬编码 → 流氓进程 | pgrep + healthcheck 脚本 | ✅ |
| eval_queue 无断点续传 | done_ marker 文件 + skip 逻辑 | ✅ |
| master_pipeline 死锁 | 等待循环中检测 eval_queue 存活，break 后继续 | ✅ |
| 静默失败无检测 | healthcheck 检查 FAILED 标记 | ✅ |
| 无卡死检测 | healthcheck 检查日志修改时间 (>30min) | ✅ |
| 子脚本无 checkpoint | badt2i_retrain/train_fixed_attacks/defense_queue 都加了 marker | ✅ |
| 旧 pipeline 冲突 | kill run_all_resilient.sh + healthcheck 检测 | ✅ |

### 内容层面（第二轮修复）

| 问题 | 修复方案 | 状态 |
|------|----------|------|
| T2I 评估只有 ACCASR | 新增 eval_extra_metrics.sh (CLIP_p/CLIP_c/FID/LPIPS) | ✅ |
| 防御在不存在的模型上失败 | defense_queue 加 model_exists() 检查 | ✅ |
| 无论文对比/偏差分析 | paper_reference.json + LOOP_CHECK Step 3 偏差分析 | ✅ |
| EvilEdit Whitelist+VTA 缺失 | master_pipeline Phase 5 新增（含脚本检测） | ✅ |
| 无前置检查 | LOOP_CHECK Step 3.5 前置检查 | ✅ |
| healthcheck 无指标覆盖检测 | 新增 metrics coverage 和 extra_metrics 状态 | ✅ |

## ETA（修正后）

| 阶段 | 预估时间 | 说明 |
|------|----------|------|
| Eval queue (9 evals) | ~35h | 3.7 it/s × 50 steps × 1000 imgs ≈ 3.9h/eval |
| Extra metrics (CLIP/FID/LPIPS) | ~10h | 8 方法 × 4 指标，每个 ~20min |
| BadT2I retrain + extra metrics | ~41h + 5h | 4 变体训练 + 训练后补评 |
| Fixed attacks + extra metrics | ~53h + 3h | 3 攻击训练 + 训练后补评 |
| Defense queue | ~47h | 6 防御方法 × 多攻击（自动跳过未训练） |
| P0 experiments | ~12h | Whitelist+VTA + Lambda 消融 + Poison Rate 消融 |
| **总计** | **~206h** | ~8.6 天（不含已完成部分） |

## 关键文件路径

| 文件 | 路径 |
|------|------|
| 本检查文件 | /Users/zzb/arxiv/LOOP_CHECK.md |
| 健康检查脚本 | ssh amax: /opt/data/private/BackdoorDM/scripts/loop_healthcheck.sh |
| Eval queue (v2) | ssh amax: /opt/data/private/BackdoorDM/scripts/eval_queue.sh |
| Extra metrics 脚本 | ssh amax: /opt/data/private/BackdoorDM/scripts/eval_extra_metrics.sh |
| Master pipeline (v2) | ssh amax: /opt/data/private/BackdoorDM/scripts/master_pipeline.sh |
| Defense queue (v2) | ssh amax: /opt/data/private/BackdoorDM/scripts/defense_queue.sh |
| 论文参考值 | ssh amax: /opt/data/private/BackdoorDM/scripts/paper_reference.json |
| 论文参考值 (本地) | /Users/zzb/arxiv/experiments/backdoordm_reproduce/loop_fixes/paper_reference.json |
| 最终报告 | /Users/zzb/arxiv/reports/03-reproduction-results/backdoordm_final_report.md |
| 交叉验证报告 | /Users/zzb/arxiv/reports/02-cross-reference/ |
| 工作日志 | ssh amax: /opt/data/private/BackdoorDM/logs/work_log.md |
| Handoff | /Users/zzb/Desktop/handoff/arxiv/2026-06-30-loop-design.md |
| 防御论文索引 | /Users/zzb/arxiv/papers/defense_papers_index.md |
| Checkpoint markers | ssh amax: /opt/data/private/BackdoorDM/logs/eval_queue/done/ |
| Extra metrics markers | ssh amax: /opt/data/private/BackdoorDM/logs/eval_extra/done/ |

## Git
- 分支: main
- 最近 commit: ff6b5a8
- 服务器代码不在 git 中，修改是实时的

## Loop Prompt（用于新 session 的 /loop 命令）

```
BackdoorDM reproduce self-check (v2):
1. SSH to amax port 25579, run: bash /opt/data/private/BackdoorDM/scripts/loop_healthcheck.sh
2. Parse output: check eval_queue/master_pipeline status, failed_evals, log_freshness, eval_proc_count, pipeline_phase, extra_metrics, metrics coverage
3. If STOPPED: safely restart (check no duplicate first, then nohup eval_queue.sh + master_pipeline.sh)
4. If failed_evals > 0 or SKIP: read details, check logs, record in LOOP_CHECK.md known issues. "SKIP: model not trained" is normal.
5. If log stale >30min: check GPU util, if 0% kill stuck process and restart
6. If eval_proc_count > 1: kill newer rogue process, keep oldest
7. If "Old/conflicting pipeline detected": kill it immediately
8. If new results appeared:
   a. Read paper_reference.json for paper values
   b. Calculate deviation %, check if explained_by known issues
   c. Update report at /Users/zzb/arxiv/reports/03-reproduction-results/backdoordm_final_report.md with deviation analysis
   d. git commit
9. If pipeline enters new phase: run preflight checks (LOOP_CHECK.md Step 3.5)
10. If pipeline_phase=COMPLETE: generate final report, check all metrics coverage, notify user
11. Append findings to work_log.md, update LOOP_CHECK.md progress tables
```
