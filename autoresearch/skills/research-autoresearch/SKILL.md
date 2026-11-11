---
name: research-autoresearch
description: 在 diffusion-backdoor-study 仓库中根据课题目标准备固定实验评价，连续提出方法、实现、执行和分析，并恢复或停止已有 autoresearch run。用于用户要求自主推进科研实验时。
---

读取本技能真实位置的 [../../program.md](../../program.md)，按其课题入口执行。主环境是 `autoresearch/`；固定上游在 `autoresearch/vendor/autoresearch/`，实验器为 `autoresearch/ar.py`。从仓库根目录调用；技能目录是符号链接时先解析其真实目标。

用户只给自然语言课题也应先检查现有资产，自己形成研究假设和可执行评价，不把配置表交回用户填写。区分环境安装、方案设计和真实实验的授权；不要因读到示例而自动启动 GPU。

已有 run 的继续/停止/恢复先读其 BRIEF、协议、RESULTS 和 MEMORY。默认由当前 agent 串行推进，使用上游 classic loop 的思路；本仓库适配优先，不能开启默认分叉、另建 agent 或覆盖现有科研记录。
