# Autoresearch 实际工作流调研

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
