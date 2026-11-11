# Autoresearch 实际工作流调研

## 后续环境搭建交付（2026-11-11）

用户在调研后要求创建独立目录并搭建实际可用环境。已交付 [autoresearch/](../../../autoresearch/README.md)，入口是 `$research-autoresearch` 或让当前 agent 读取 `autoresearch/program.md`。

- **采用现成上游**：通过 skill-installer 安装 uditgoenka/autoresearch v2.3.0，固定 commit `7bddd056dfd0b0ded8360588d8101b1ecb5c0baa`；24份原始文件共150,900字节逐一匹配官方Git blob，SHA256和大小归入 vendor/manifest.json，MIT许可证保留。上游文件内容未改写。
- **项目适配**：新 skill 为课题理解、方法假设、实验与结果分析提供入口；默认本会话单agent串行、禁用上游默认自动分叉，沿用用户已有授权。未安装全局hook、未改账号或全局Codex配置。
- **可执行适配器**：Python标准库 `ar.py` 提供new/run/status/stop/resume/recover；候选在独立Git工作目录提交/回退，根科研仓库及他人改动不受回退影响。固定评价输出唯一有限数值JSON，返回码、主指标与质量约束共同决定接纳。失败、资源检查、超时和清理消耗均保留，进度追加到Markdown。
- **运行管理**：单次/累计计算和尝试次数有界；STOP可中断本地命令；丢失尝试须确认本任务进程退出后恢复，保留历史并保守计费。GPU配置要求guard/cleanup，具体保护复用已有实验执行器，不用本机SSH进程退出冒充远端停止。无锁，不承诺并发写安全。
- **中文用法**：README包含只给课题/预算/成功标准的可复制指令，以及规划、继续、改方向、查看和停止示例；diffusion-lora profile列出现有模型、平台管理与评价接入入口。

实际验收：

| 项目 | 实际结果 |
|---|---|
| Python运行适配器 | 本机直接运行，零新增Python包依赖 |
| 本地skill结构 | skill-creator quick_validate通过；根目录技能链接解析到本模块 |
| 上游辅助脚本 | orchestrate.sh classify实际执行并返回分类；不把它当作GPU或完整自主科研成功 |
| 针对性验证 | `python3 -m unittest discover -s autoresearch/tests -v`，13项全部通过：真实拟合keep/discard、错误退出、非有限/缺失/重复指标、质量约束、单次/累计超时、STOP、预算恢复、资源阻塞、cleanup失败、根仓库保护、截断账本 |
| 实际CPU例 | environment-smoke共4次：线性基线MSE 0.16676068596971452；三次模型0.003122132499122443（keep）；常数模型0.6774106905223541（discard并自动回退）；停止/恢复后再次得到0.003122132499122443，历史4次完整保留 |

CPU证据保存在本机 `autoresearch/runs/environment-smoke/RESULTS.md` 和对应attempt日志；最小持久证据即上表。该例由当前agent执行，未另开模型实例，不代表独立长时间无人值守或扩散模型科研成功。

边界：本次交付的是固定版autoresearch技能与本仓库工作环境。课题专属GPU包装器/模型环境尚需在实际课题首次接入时生成并通过真实验证；本轮没有启动GPU、改变旧run、安装全局后台服务或创建自动化。`program.md`并非后台模型，停止应用或模型额度耗尽后须恢复会话。具体方法的科学有效性仍待实验。

下文保留此前调研来源与结论。

## 目录工作原理核对（2026-11-11）

用户要求重点解释整个目录。已重新读取实际代码、项目skill、program、配置、GPU profile及environment-smoke原始Markdown账本；本轮只读既有结果，没有新启动实验。

运行链路为：当前coding agent读取skill/program，准备假设与候选 → `ar.py run`执行一次固定评价 → 检查进程退出、有限指标和约束 → 与历史best比较并保留/回退 → 向RESULTS.md追加事实 → agent分析并决定下一次调用。ar.py不调用LLM，也不自动运行vendor里的orchestrator；上游主要提供agent可读的流程协议，本地执行适配由ar.py承担。

硬性程序检查包括输出格式、错误退出、有限指标、质量阈值、运行预算、STOP和独立Git工作目录。查文献、假设质量、固定科学协议、独立holdout和多seed验证由agent遵守工作流完成；当前不是文件权限沙箱，也没有自动验证“科研结论成立”的独立系统。max_seconds累计同步命令的墙钟时间，不是测得的GPU设备秒数，也不包含agent思考时间；恢复不完整尝试时按实际恢复前的墙钟间隔保守计费。

RESULTS.md中的JSON块支持程序恢复尝试数、消耗、pending和best；MEMORY.md由agent维护推理摘要。run/work独立Git承担候选版本，evaluation和protocol置于其外。CPU例只验证这条链路；真实GPU需要课题包装器提供guard、同步command和cleanup，并接入已有运行期资源观察。

调研日期：2026-11-11。用户最终要求是查找已在实际项目中使用、取得可观察改进的工作流，重点为 Karpathy autoresearch 路线。

## 适合先看的三个项目

| 项目 | 已核对的能力 | 适用判断 |
|---|---|---|
| [karpathy/autoresearch](https://github.com/karpathy/autoresearch) | `program.md` 驱动 coding agent 修改训练代码、执行实验、读取指标、保留改进和回退退化；原版固定单次训练 300 秒，启动/编译不包含在内；固定数据与评价文件 | 最适合理解和移植核心方法；原版实验对象是小型语言模型，迁移扩散模型课题需要替换实验入口与评价 |
| [davebcn87/pi-autoresearch](https://github.com/davebcn87/pi-autoresearch) | 面向 pi coding agent 的通用扩展；实验运行/记录工具、看板、持久状态、keep/revert 和整理实验分支 | 希望使用现成通用实验循环时优先考察；科学效果仍由目标、实验代码与评价决定 |
| [uditgoenka/autoresearch](https://github.com/uditgoenka/autoresearch) | 多种 coding agent 可用的 skill/plugin；明确 Goal、Scope、Metric、Verify 和迭代次数；本轮核到 v2.3.0 发布记录 | 适合接入已有 agent 工作方式；功能完善和有人维护不能替代实验收益证据，本轮不称其“已证明比原版更有效” |

依据为作者官方 README、[原版 program.md](https://github.com/karpathy/autoresearch/blob/master/program.md) 和 [uditgoenka 发布记录](https://github.com/uditgoenka/autoresearch/releases)。本轮未安装或运行这些项目。

## 两条第一方实际使用证据

### Shopify Liquid：公开代码和可复现基准入口

[PR #2056](https://github.com/Shopify/liquid/pull/2056) 由 `tobi` 提交，描述约 120 次自动实验，循环为编辑、提交、测试、基准、保留或丢弃。

- ThemeRunner 基准中的 parse+render 耗时：7,469 μs → 3,534 μs，下降约 53%。
- 对象分配：62,620 → 24,530，下降约 61%。
- PR 报告 974 个单元测试全部通过，并列出失败尝试和基准复现命令。
- 测量条件为 Ruby 3.4、YJIT、预热后每组 10 次、三组取最好结果，基准中关闭 GC；数值只代表该测量设置。
- 本轮 GitHub API 返回 PR 为 `open`，`merged_at` 为空。这是公开实验与代码改动证据，不能表述为“已经合并上线、生产普遍提升 53%”。

### Vesuvius Challenge：真实科研模型的自动探索

团队在 [We are cooking](https://scrollprize.substack.com/p/we-are-cooking)（2026-03-19）中报告，受 autoresearch 启发部署 4 个持续运行的 agent，探索墨迹识别网络架构与训练。

其中一个 agent 只用 PHerc. 139 数据训练，在 PHerc. 1667（Scroll 4）上的验证 Dice 接近翻倍。页面提供优化轨迹，是与“围绕研究课题寻找方法并跑实验”更贴近的使用案例。

这是团队第一方报告；本轮没有独立复跑，也没有据此推断任意课题都能达到同样收益。

## 核心方法与本仓库适配判断

流程为：固定问题与评价 → 运行基线 → agent 提出一个可验证改动 → 实现与执行 → 读取真实指标 → 保留/回退并记录原因 → 继续下一轮。

Karpathy 原版允许修改网络架构、优化器、训练循环及超参数，搜索空间可以包含方法层面的变化。原版依赖人提供可运行任务、固定评价和搜索边界；广泛文献检索与新课题定义需要另行提供工具或指令。

对本仓库，建议借用原版的短闭环协议，接入已有加载、生成、评分和恢复链路。每个科学候选显式建立配置，固定底座、评估样本、seed 和评分；同时观察目标效果及正常语义/质量，候选通过搜索集后再用独立样本与多 seed 确认。原版的 5 分钟、无限循环和日志格式属于其具体设计，本仓库应使用明确实验预算、现有资源规则与 Markdown 运行记录。

上述为适配建议，本轮没有实施或验证其收益。

## 更多实践入口及检查边界

[WecoAI/awesome-autoresearch](https://github.com/WecoAI/awesome-autoresearch) 按实际应用列出代码、优化曲线和实验轨迹，可用于继续寻找实践案例；应沿链接回到作者原始记录核对。本轮对 Shopify 和 Vesuvius 案例已完成这一步。

初始检索曾覆盖 AI Scientist、AI-Researcher、EvoScientist 和 Deep Researcher Agent；用户澄清后不将这些论文系统作为推荐重点。Karpathy 与 Tobi 的部分 X 原帖直接访问返回 403，未将未读原帖中的数字当作已核实结果。

实际检查范围：公开网页、官方 GitHub README/实验协议、Liquid PR 元数据和正文、Vesuvius 团队报告，以及本地仓库入口与改动范围。没有 GPU 实验、框架部署或独立收益复现；没有将本轮调研记为科研成功。
