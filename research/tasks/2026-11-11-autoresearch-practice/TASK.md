# Autoresearch 实际工作流与使用案例调研

| 字段 | 值 |
|---|---|
| task_id | AUTORESEARCH-20261111-01 |
| status | done |
| outcome | not_applicable（资料调研，未执行实验） |
| updated_at | 2026-11-11 |
| authorization | 寻找能自主提出方法并实验验证的 agent 工作流；用户进一步明确：关注 Karpathy autoresearch 这类已有人实际使用并取得效果的项目，不以论文系统为重点 |
| current_stage | 已核对原版实验协议、两个通用封装及两个第一方实际使用案例 |
| next_action | 后续接入时选定可自动评价的子问题，明确可修改方法、固定评价与预算，再适配实验循环；本轮范围为调研 |

## 结论与证据

优先阅读 [Karpathy autoresearch](https://github.com/karpathy/autoresearch) 的 `program.md`；通用实验循环看 [pi-autoresearch](https://github.com/davebcn87/pi-autoresearch)，现有 coding agent 的 skill 封装看 [uditgoenka/autoresearch](https://github.com/uditgoenka/autoresearch)。后者功能与发布记录可核验，但本轮没有找到同等强度、可直接归因于该封装的实验收益证据。

实际结果重点看 Shopify Liquid 的公开性能 PR，以及 Vesuvius Challenge 团队的墨迹识别实验更新。指标、来源与验证边界见 [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)。

## 范围与接续

本轮只检索公开资料、阅读官方仓库和记录结论；没有安装插件、调用付费模型、启动 GPU 或改写科学配置。现有科研运行继续由项目状态中的原 TASK 管理，本调研通过任务目录导航接续。
