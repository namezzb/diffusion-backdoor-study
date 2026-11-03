# 任务模板

复制到新任务目录的 `TASK.md` 并按范围裁剪。规则见[AGENTS.md](../../AGENTS.md)，session 分工见[工作流程](../WORKFLOW.md)；仅在用户明确要求时委派子 agent。

# <任务名称>

| 字段 | 值 |
|---|---|
| task_id | <唯一ID> |
| status | todo |
| outcome | not_evaluated（工程维护可写 not_applicable） |
| updated_at | <YYYY-MM-DDTHH:MM:SS+08:00> |
| authorization | <用户实际授权范围，是否包含真实实验> |
| current_stage | <当前阶段> |
| next_action | <下一件具体工作> |
| handoff | <当前 session 或实际交接安排；不预设自动并行> |

## 目标与验收

<用一两句话写目标和可核验的完成条件；设计、固定配置和实现报告通过链接引用。>

## 当前事实与阻塞

<只保留最新已核实事实及证据入口；技术暂停和科研终态分别记录。过程较长时，把旧条目转入同目录 HISTORY.md 或实际运行日志，保留事实和日期。>

## 运行配置与恢复

<实验任务链接固定模型、样本/seed、评分、预算、判据和唯一run目录，记录实际T0和已有尝试；工程维护写不适用。>

<写下一步或同入口恢复命令；已授权技术修复继续推进，不因模板要求创建额外审批。>

## 交付与结论

<链接 IMPLEMENTATION_REPORT.md，写实际检查范围和未验证项；CPU、GPU和方法效果分开报告。README只给入口，TASK只维护这一份当前状态。>
