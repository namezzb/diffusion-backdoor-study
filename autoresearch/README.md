# Autoresearch 使用入口

采用固定版本的 [uditgoenka/autoresearch](https://github.com/uditgoenka/autoresearch) skill，沿用 Karpathy 的“提出改动→执行→评价→保留/回退”循环；本仓库适配实验隔离、Markdown 记账、预算和恢复。[来源与版本](UPSTREAM.md) · [实现与验证](../research/tasks/2026-11-11-autoresearch-practice/IMPLEMENTATION_REPORT.md)

## 直接指挥 agent

在这个科研项目的 Codex 对话中发送下面这段即可。新安装的 `$research-autoresearch` 从下一轮可发现；若客户端尚未刷新，明确让 agent 读取 `autoresearch/program.md`，使用效果相同。

> 使用 $research-autoresearch。我的课题是：研究 LoRA 融合对扩散模型后门行为的影响。复用仓库已有模型、代码和文献，由你选择最有信息量的子问题、提出方法并完成实验。首轮最多 1 张合规 GPU、累计计算 4 小时、最多 20 次尝试。成功标准是得到可复现的改进或有充分对照的负结果，同时检查正常语义与图像质量。普通代码和环境问题自行修复，在预算内持续推进，完成后给我证据、结论和下一步。

课题、预算、成功标准换成自己的要求即可。agent 负责具体代码、协议、评分命令和运行记录。预算耗尽时报告当前证据，不能承诺任意课题都能找到有效方法。

只想规划：

> 读取 autoresearch/program.md。为课题“……”找方法并准备实验配置，本轮先做到可运行，不启动 GPU。

继续 / 改方向 / 看结果 / 停止：

> 继续 autoresearch 的 `<run_id>`，保持原科学配置和剩余预算。
>
> 根据已完成实验，解释哪条假设被支持或否定。把后续探索转向“……”，科学配置变化时建立关联的新 run。
>
> 汇总 `<run_id>` 的实际结果、失败尝试、计算消耗和最佳候选，不启动新实验。
>
> 停止 `<run_id>`，保存进度并确认本任务远端 worker 退出。

## 本机快速体验

Python 3.10+、Git 即可；运行适配器和 CPU 示例没有额外包依赖。示例使用真实最小二乘拟合和固定验证数据。

```bash
python3 autoresearch/ar.py new my-first-run
python3 autoresearch/ar.py run my-first-run --hypothesis baseline
python3 autoresearch/ar.py status my-first-run
```

然后告诉 agent：

> 使用 $research-autoresearch，继续 my-first-run 的 CPU 示例。在原预算内自主提出和测试改进，只改 work/candidate.py，完成后汇报真实结果。

也可在本项目终端启动已安装的 Codex：

```bash
codex '读取 autoresearch/program.md，继续 my-first-run 的 CPU 示例直到原预算结束。'
```

保持 Codex 和电脑运行。实验循环由正在运行的 agent 驱动，skill 本身不含后台模型；关闭应用、网络中断或模型额度用尽时需要恢复会话。无需为了这套配置购买另一个 agent 产品；模型使用仍遵循现有账号额度。

## 文件与恢复

| 文件 | 用途 |
|---|---|
| [program.md](program.md) | agent 的科研工作流、默认预算与停止条件 |
| [profiles/diffusion-lora.md](profiles/diffusion-lora.md) | 接入已有模型、GPU 管理和评分的规则及入口 |
| [ar.py](ar.py) | new / run / status / stop / resume / recover |
| `runs/<id>/BRIEF.md` | 本轮目标、授权与科学定义 |
| `runs/<id>/protocol.json`、`evaluation/` | 固定评价、配置和命令 |
| `runs/<id>/work/` | agent 可改的候选代码，独立 Git 仓库 |
| `runs/<id>/RESULTS.md` | 逐次尝试、真实指标、决策、消耗与候选 commit |
| `runs/<id>/MEMORY.md` | 有依据的结论、失败方向、下一假设 |
| `runs/<id>/attempts/` | 每次实际命令的追加日志 |

运行目录保存在本机并被 Git 忽略；要交接时将必要摘要写到课题 TASK/实现报告。远端模型、原图、检查点仍留本人数据盘。进度是 Markdown，无锁，不支持多个进程安全地同时写同一 run。

```bash
python3 autoresearch/ar.py stop my-first-run
python3 autoresearch/ar.py resume my-first-run
# 只有在已核实本任务本地、远端进程退出后，才处理不完整尝试：
python3 autoresearch/ar.py recover my-first-run --confirmed-exited --note '填写实际退出核查证据'
```

## 新课题如何接入（agent 阅读）

准备模板目录，包含 `candidate/`、`evaluation/`、`config.json` 和 `BRIEF.md`，随后 `ar.py new <id> --template <目录>`。使用 [示例配置](examples/polynomial/config.json) 的字段；command、guard、cleanup 都是 argv 数组，支持 `{python}`、`{run}`、`{workspace}` 三种占位符，不隐式经过 shell。

评价命令成功退出，且输出唯一一行 `AUTORESEARCH_METRICS ` 加有限数值 JSON，才可能被接纳。constraints 全部满足且主指标改进超过 min_delta 时 keep，否则回退。基线和失败都计入 max_attempts、max_seconds；attempt_timeout 限制每次运行。managed_gpu 必须提供有效的 guard/cleanup，具体桥接按课题建立并验证。

源码：[上游固定版本](vendor/autoresearch/SKILL.md) · [本仓库 skill](skills/research-autoresearch/SKILL.md)。技能通过根目录 `.agents/skills/research-autoresearch` 符号链接被发现，遵循 [OpenAI 本地 skill 文档](https://learn.chatgpt.com/docs/build-skills)。
