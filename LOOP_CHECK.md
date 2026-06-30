# BackdoorDM Batch Reproduce - Loop Check File

> **每次 loop 迭代读取此文件，按步骤执行检查。**
> **服务器**: ssh amax -p 25579 | **工作目录**: /opt/data/private/BackdoorDM

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
|---|------|------|------|-----|-----|---------|------|
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

### Step 1: 检查流水线状态
```bash
ssh amax -p 25579 "tail -5 /opt/data/private/BackdoorDM/logs/eval_queue/queue.log; echo '==='; tail -5 /opt/data/private/BackdoorDM/logs/master_pipeline/pipeline.log; echo '==='; ps -p 407317 > /dev/null 2>&1 && echo 'eval:OK' || echo 'eval:STOPPED'; ps -p 412582 > /dev/null 2>&1 && echo 'master:OK' || echo 'master:STOPPED'"
```

### Step 2: 检查新结果
```bash
ssh amax -p 25579 "cat /opt/data/private/BackdoorDM/results/*/eval_results.csv 2>/dev/null | grep -v 'datatime' | wc -l"
```
- 之前是 8 条结果，如果 >8 说明有新评估完成

### Step 3: 如果有新结果
1. 读取新结果: `cat results/*/eval_results.csv | grep -v datatime | tail -5`
2. 对照论文数据（见上方表格）
3. 更新本文件的进度表格
4. 更新最终报告: `/Users/zzb/arxiv/reports/03-reproduction-results/backdoordm_final_report.md`
5. git commit

### Step 4: 如果进程停止
```bash
# 重启评估队列
ssh amax -p 25579 "cd /opt/data/private/BackdoorDM && nohup bash scripts/eval_queue.sh > logs/eval_queue_nohup.log 2>&1 &"
# 重启主流水线
ssh amax -p 25579 "cd /opt/data/private/BackdoorDM && nohup bash scripts/master_pipeline.sh > logs/master_pipeline_nohup.log 2>&1 &"
```

### Step 5: 如果 master pipeline 进入新阶段
检查 `pipeline.log` 中是否出现:
- "BADT2I RETRAINING" → BadT2I 阶段开始
- "FIXED ATTACKS TRAINING" → 修复攻击训练开始
- "DEFENSE QUEUE" → 防御阶段开始
- "P0 MISSING EXPERIMENTS" → P0 实验开始
- "MASTER PIPELINE COMPLETE" → 全部完成！

### Step 6: 如果全部完成
1. 收集所有结果: `bash scripts/28_extract_all_metrics.sh`
2. 生成最终报告
3. git commit
4. 通知用户

### Step 7: 更新工作日志
```bash
ssh amax -p 25579 "cat >> /opt/data/private/BackdoorDM/logs/work_log.md << 'EOF'
### [时间] - Loop Check
- Eval results count: X
- Pipeline phase: Y
- Status: [normal/action taken]
EOF"
```

### Step 8: 自检
- 攻击完成: X/16
- 防御完成: X/6
- 报告完成: 是/否
- 下一步: ?

---

## 已知问题

1. **VillanDiff cond 路径不匹配**: bdmodel_path.py 有 `trigger-latte-coffee` 但配置用 `TRIGGER_MIGNNEKO`，训练后需修复
2. **BadT2I batch_size**: 单 GPU 只能 4 (论文 16)，记录为限制
3. **T2IShield CDA**: detect_cda.py 未实现 (Agent 失败)，需重试
4. **ViT ACCASR 低估 ASR**: ViT 分类器不如人工/GPT 评估，记录为方法差异

## 关键文件路径

| 文件 | 路径 |
|------|------|
| 本检查文件 | /Users/zzb/arxiv/LOOP_CHECK.md |
| 最终报告 | /Users/zzb/arxiv/reports/03-reproduction-results/backdoordm_final_report.md |
| 交叉验证报告 | /Users/zzb/arxiv/reports/02-cross-reference/ |
| 工作日志 | ssh amax: /opt/data/private/BackdoorDM/logs/work_log.md |
| Handoff | /Users/zzb/Desktop/handoff/arxiv/2026-06-30-loop-design.md |
| 防御论文索引 | /Users/zzb/arxiv/papers/defense_papers_index.md |

## Git
- 分支: main
- 最近 commit: ff6b5a8
- 服务器代码不在 git 中，修改是实时的
