# 本地资料盘点（2026-10-29）

这是整理开始时的只读快照，未连接服务器、未启动实验、未移动或删除资料；后续回传文件应以主整理清单为准。

统计排除了运行依赖和 Git 数据；发现 46 个兼容符号链接，全部目标存在，真实研究目录合计约 0.985 GiB。

## 三轮资料在哪里

| 轮次 | 本地已核验 | 尚需补齐或核对 |
|---|---|---|
| 初步验证 MVP | 终态33份小产物哈希全部匹配；含逐图指标、144步轨迹、候选、持出报告和固定面板 | 目前目录只有9张面板PNG，1520张单图未在本地；全量轨迹/teacher缓存及完整运行日志须按远端清单核对 |
| 直接ASR探索 | 833份终态小产物、816张PNG全部重新核对哈希；图像原件合计325.5 MiB | 原日志目前仅返回过滤tail；833份白名单不是整个远端目录镜像，需核对遗漏 |
| 目标语义诊断 | 1141份终态产物全部重新核对哈希；原响应float32文件、逐cell回执、梯度与终态门禁均在本地 | 准备/启动快照与外部执行日志在run目录之外，仍需按部署回执核对 |

证据完整性与科研结论必须分开：直接ASR探索原严格审计仍为invalid，最新诊断D3仍失败，回传成功不改变这些结论。

## 顶层目录体量

| 目录 | 文件数 | MiB |
|---|---:|---:|
| `research/` | 18 | 0.65 |
| `archive/` | 137 | 52.25 |
| `papers/` | 37 | 202.41 |
| `server/` | 9 | 0.17 |
| `results/` | 4559 | 751.18 |
| `presentations/` | 3 | 0.08 |
| `reproduction/` | 8 | 0.16 |
| `simulations/` | 11 | 0.96 |
| `scripts/` | 47 | 0.62 |
| `data/` | 0 | 0.00 |
| `reports/` | 12 | 0.26 |

## 重要导航修正

根索引应先显示“实验已暂停”和三轮结果，再指向逐图原件、逐步记录、模型来源、代码快照与回传验收；现有历史记录保持原样。

- `README.md`：Lead and directory map omit latest target-semantic diagnostic and paused state; next-steps list can be mistaken for authorization to resume completed MVP. Make pause/current summary first; add all three run entries and local-vs-remote availability index.
- `results/README.md`：Lead still refers only to MVP and date 2026-10-28; target diagnostic and local raw image/cell locations missing. Add a three-run evidence table and acquisition/completeness boundaries.
- `scripts/README.md`：Says actual GPU/model/environment checks remain unverified although MVP completed; new image-search/target-semantic runtime/core/run modules omitted. Separate historical pending statements from current execution evidence; add current modules, frozen versions and audit tools.
- `results/tssa-mvp-2026-10-26/README.md`：Long historical preparation sequence dominates; stale historical statements easy to read as current. Put final report, terminal artifact snapshot, raw data archive and current pause status first; preserve preparation history below.
- `results/tssa-opt-exploration-2026-10-28/README.md`：Missing per-run README entry point. Create concise negative-result/strict-audit-boundary/raw-PNG/metrics/code/manifest index.
- `results/tssa-target-semantic-diagnostic-2026-10-28/README.md`：Final state correct at top but exact terminal 1141-file artifact path and hashes report not linked directly. Add canonical evidence and source plan links; retain old preparation as history.
- `server`：Not only compatibility links: contains 9 current real files, including school SSH config, asset staging, offline installer and monitor state. Index real current connection/deployment files without moving frozen-path dependencies or claiming entire directory is just a link.

## 重叠、兼容与远端边界

- 探索图像目录保留111,116,288字节的截断传输包和231,034,880字节的续传包，与816张已展开PNG重叠；本次不删除故障证据或用户文件。
- `server/`兼有兼容链接和9份真实现行文件，`data/`只有两份元数据兼容链接，不能把它们当成新的独立资料副本。
- 最新诊断仅取回MVP四份原始缓存envelope及派生tensor，不能据此声称16条完整轨迹与120组teacher响应已全部归档。
- 历史AMAX的BackdoorDM模型与原始评价目前只有本地文档记录，本审阅未复核；公开大模型应保留固定revision、SHA及服务器路径，不能在低剩余空间下盲目复制所有权重。

逐文件校验计数、路径、兼容链接和优先缺口见同目录 [JSON盘点](local_inventory_review.json)。
