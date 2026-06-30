# BackdoorDM Loop Check (v3 精简版)

> **服务器**: ssh amax -p 25579 | **工作目录**: /opt/data/private/BackdoorDM
> **详细参考**: `/Users/zzb/arxiv/reports/03-reproduction-results/backdoordm_final_report.md`
> **论文参考值**: 服务器 `scripts/paper_reference.json`

---

## Loop Prompt（用于 /loop 命令）

```
BackdoorDM loop check:
1. SSH amax -p 25579, run: bash /opt/data/private/BackdoorDM/scripts/loop_healthcheck.sh
2. If eval_queue/master_pipeline STOPPED: check pgrep first, if none running then nohup restart
3. If failed_evals > 0: read failed_details, check logs, record issue
4. If "SKIP: model not trained": normal, skip
5. If log stale >30min: check GPU util, if 0% kill and restart
6. If eval_proc_count > 1: kill newer PID (rogue), keep oldest
7. If "conflicting pipeline": kill immediately
8. If new results: compare vs scripts/paper_reference.json, calc deviation, update report + git commit
9. If new pipeline phase: run preflight checks (see below)
10. If COMPLETE: collect all results, generate final report, notify user
11. Append to work_log.md
```

## 每次执行步骤

### 1. 健康检查（一条命令搞定）

```bash
ssh amax -p 25579 "bash /opt/data/private/BackdoorDM/scripts/loop_healthcheck.sh"
```

### 2. 决策树（按 healthcheck 输出字段行动）

| 字段 | 值 | 动作 |
|------|-----|------|
| eval_queue | STOPPED | `pgrep -f eval_queue.sh` 确认无进程 → `nohup bash scripts/eval_queue.sh &` |
| master_pipeline | STOPPED | `pgrep -f master_pipeline.sh` 确认无进程 → `nohup bash scripts/master_pipeline.sh &` |
| failed_evals | >0 | 读 failed_details，`tail -20 logs/eval_queue/<name>.log`，记录原因 |
| log_freshness | stale >30min | `nvidia-smi` 查 GPU util，若 0% → `kill $(pgrep -f main_eval.py)` → 重启 |
| eval_proc_count | >1 | kill 较大 PID（流氓），保留较小 PID（最早启动） |
| conflicting_pipeline | detected | `kill <pid>` 立即清除 |
| extra_metrics | NOT_STARTED + eval_queue COMPLETE | 可手动启动: `nohup bash scripts/eval_extra_metrics.sh &` |
| pipeline_phase | COMPLETE | 收集结果，生成报告，通知用户 |

### 3. 新结果出现时

```bash
# 读取新结果
ssh amax -p 25579 "cat /opt/data/private/BackdoorDM/results/*/eval_results.csv | grep -v datatime | tail -5"
# 对比论文值（读取 scripts/paper_reference.json）
# 计算偏差率，检查 explained_by 字段
# 更新报告 → git commit
```

### 4. Pipeline 进入新阶段时（前置检查）

- **Phase 2 (BadT2I)**: 确认训练数据 ≥500 张图
- **Phase 3 (Fixed Attacks)**: 确认 bug 修复已应用
- **Phase 4 (Defense)**: defense_queue 自动跳过未训练模型（正常行为）
- **Phase 5 (P0)**: EvilEdit Whitelist+VTA 脚本可能缺失（log SKIP 为正常）

### 5. 更新日志

```bash
ssh amax -p 25579 "cat >> /opt/data/private/BackdoorDM/logs/work_log.md << 'EOF'
### $(date) - Loop Check
- Results: X | Phase: Y | Failed: Z | Action: [none/restart/killed]
EOF"
```

## 关键文件

| 文件 | 位置 |
|------|------|
| 健康检查 | 服务器: scripts/loop_healthcheck.sh |
| Eval queue | 服务器: scripts/eval_queue.sh |
| Extra metrics | 服务器: scripts/eval_extra_metrics.sh |
| Master pipeline | 服务器: scripts/master_pipeline.sh |
| Defense queue | 服务器: scripts/defense_queue.sh |
| 论文参考值 | 服务器: scripts/paper_reference.json |
| 最终报告 | 本地: reports/03-reproduction-results/backdoordm_final_report.md |
| Checkpoint markers | 服务器: logs/eval_queue/done/, logs/eval_extra/done/ |
