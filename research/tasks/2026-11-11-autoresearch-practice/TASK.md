# Autoresearch 环境搭建与实际工作流

| 字段 | 值 |
|---|---|
| task_id | AUTORESEARCH-20261111-01 |
| status | done |
| outcome | not_applicable（环境交付；CPU验证通过，尚未运行扩散模型科学实验） |
| updated_at | 2026-11-11 |
| authorization | 调研已有实际效果的 Karpathy autoresearch 工作流；用户随后要求在科研仓库新建目录，搭建可用环境并说明如何只指挥 agent 完成课题 |
| current_stage | autoresearch/ 已安装固定版上游 skill；项目 skill、执行/回退/预算/恢复适配、CPU例与中文说明已完成；13项检查和实际4次CPU实验通过 |
| next_action | 用户在本项目通过 $research-autoresearch 或直接指定 program.md 下达课题；agent 将具体课题的现有模型/评分接入独立 run，按预算执行首次GPU验证后连续探索 |

## 结论与证据

优先阅读 [Karpathy autoresearch](https://github.com/karpathy/autoresearch) 的 `program.md`；通用实验循环看 [pi-autoresearch](https://github.com/davebcn87/pi-autoresearch)，现有 coding agent 的 skill 封装看 [uditgoenka/autoresearch](https://github.com/uditgoenka/autoresearch)。后者功能与发布记录可核验，但本轮没有找到同等强度、可直接归因于该封装的实验收益证据。

实际结果重点看 Shopify Liquid 的公开性能 PR，以及 Vesuvius Challenge 团队的墨迹识别实验更新。指标、来源与验证边界见 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)。

## 环境与接续

入口：[autoresearch/README.md](../../../autoresearch/README.md)。固定上游为 uditgoenka/autoresearch v2.3.0 / `7bddd056dfd0b0ded8360588d8101b1ecb5c0baa`，24份原始文件已逐一核对Git blob和SHA256，MIT许可证随目录保存。当前项目通过 `.agents/skills/research-autoresearch` 链接发现技能；没有修改全局配置或账号。

CPU run：`autoresearch/runs/environment-smoke/`，固定线性基线MSE 0.16676068597 → 三次拟合0.00312213250（keep）；常数消融0.67741069052（discard并回退）；停止/恢复后复测三次模型得到相同MSE，已有尝试与预算保留。该例只验证工程循环。

没有启动新的GPU任务、修改原科学配置、调用额外付费模型或创建定时任务。现有科研运行继续由项目状态中的原TASK管理；具体GPU评价桥接在用户下达实际课题后由agent按已有执行器建立并验证，不能把CPU验收称为GPU成功。
