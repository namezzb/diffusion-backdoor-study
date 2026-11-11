# 本仓库的自主研究入口

这是对固定版 [上游 autoresearch](vendor/autoresearch/SKILL.md) 的科研适配。先读本文件，再按需读[上游 classic loop](vendor/autoresearch/autoresearch.md)；用户本次授权和[仓库规则](../AGENTS.md)优先。直接使用当前 agent，默认单 agent 串行、`--no-fork`。不要为执行循环另开 agent、chat 或定时任务。

## 用户只需要表达什么

研究问题、希望得到的结果、计算预算或截止条件。代码位置、基线、评价命令、记录文件由 agent 根据仓库资料准备。已有授权足够时不重复请求确认；仅在目标含义无法确定、所需资源超出授权或确有外部阻塞时询问缺失信息。

用户明确要求开始课题而没有给预算时，采用首次探索默认值：至多 6 次尝试（含基线和失败）、累计计算 30 分钟、最多 1 张合规 GPU；并说明采用这些值。方法研发和文献分析单独记录，不把等待资源算作方法失败。这不是安装环境时自动开始研究的授权。

## 从课题到可执行循环

1. 读取用户指定 TASK、现有方法/数据/评分入口和必要文献。提出可证伪假设，为每个候选写明根据、预期变化、对照和最低验证实验。若课题宽泛，先挑最有信息量的子问题，不能擅自把科研目标换成写论文或单纯提速。
2. 将目标、授权、数据、主指标、质量约束、搜索集与 holdout、预算写进该 run 的 `BRIEF.md`。扩散/LoRA 课题按需读 [profiles/diffusion-lora.md](profiles/diffusion-lora.md)。资料检索可在后续出现新疑问时继续；不要求每轮完整重做综述。
3. 从已有可运行基线准备模板：`candidate/` 放允许修改的实现，`evaluation/` 放固定评价/资源管理桥接，`config.json` 放科学配置与执行 argv。格式参考 [CPU 示例](examples/polynomial/config.json)。模型和图像用本人服务器上的路径引用。用户无需手填模板。
4. `python3 autoresearch/ar.py new <run_id> --template <template_dir>` 创建 run。在 `autoresearch/runs/<run_id>/work/` 修改候选。运行 `python3 autoresearch/ar.py run <run_id> --hypothesis 'baseline'`，打通真实加载、生成/训练、评分、落盘后开始探索。new 不执行实验；run 才执行一次。
5. 持续读该 run 的 `RESULTS.md` 和 `MEMORY.md`，自主提出一个方法改动、实现、运行 `ar.py run`、分析真实结果。`baseline/keep/discard` 是搜索决策；`crash/resource_blocked/constraint_failed` 保留原因，不伪装成指标为零的科学失败。技术故障在同一授权下修复后继续，预算和已发生尝试不重置。
6. 在预算内执行复测、消融和独立 holdout。搜索集的 keep 只表示候选改进；最终报告需标明多 seed、对照、样本量、质量损失和限制。没有有效候选也交付可复现的负结果，不能为了宣告成功修改判据。

## 对上游的明确适配

- 使用有界 classic loop；不进入需要额外确认的通用 orchestrator，不自动 fork-and-flush，不使用锁/独占文件，不调用 ship/publish。
- 原版的提交/回退由 `ar.py` 在 **run/work 的独立 Git 仓库**处理。不要在科研仓库根目录 reset、clean 或回退其他 session 的改动。已否决候选 commit 保留在独立仓库对象中，可由 RESULTS.md 的 hash 检出。
- 以 Markdown `RESULTS.md` 中追加的事实为唯一实验账本，不另建 TSV/SQLite 状态。`MEMORY.md` 只写结论、失败方向、下一假设与文献链接，引用事实而不覆盖原记录。运行日志、配置、检查点都归本 run。
- `protocol.json` 和 evaluation 在探索中固定，agent 只改 work。科学内容变化创建新 run 并引用 parent；纯工程修复如需改评价包装器，要在原 run 记录原因、文件版本和前后行为，科学输入/评分不变。该目录隔离是工作约定，不是针对恶意代码的系统级沙箱。
- 总预算计入基线、失败尝试、资源检查、模型加载和清理时间。执行器在单次/累计计算限额达到时终止本次命令；GPU清理另有最多30秒宽限且计费。LLM思考/文献准备时间与训练时间分开，用户给总截止时间时 agent 另外遵守。
- `ar.py` 提供运行、记账和决策；提出下一假设并继续调用的是当前 coding agent。没有驻留后台模型，也不承诺应用关闭或账号额度耗尽后还能推进。

## 继续、停止与恢复

- “继续上次 run”：先 `ar.py status <run_id>`，读取原 BRIEF/协议/MEMORY/账本；跳过完整结果，从现有 best 继续。不要 new 同名 run，也不要重跑已完成 baseline。
- “停止”：`ar.py stop <run_id>`。本地命令会收到终止信号，managed_gpu 还执行 cleanup；检查实际远端进程退出后汇报。用户明确恢复后才 `ar.py resume <run_id>`。
- 若进程中断留下 started 而无 finished，核实本任务本地与远端进程退出后：`ar.py recover <run_id> --confirmed-exited --note '实际核查证据'`。它保留尝试、按中断后的墙钟间隔保守计费并回到已验证 best；如有准确运行证据，在 Markdown 追加解释，不抹去旧消耗。
- 默认串行，没有并发写保护；不要让两个 session 同时运行同一 run。
- 完成时更新课题 TASK 和实现报告，注明工程状态与科研 outcome。大模型与图片留服务器，必要摘要进入仓库。
