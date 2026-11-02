# TCL v2 来源包独立审阅

- 审阅范围：对 104 实际来源包及本会话新增来源构造器、历史失败追溯实现进行独立只读审阅，未参与来源材料构造。此记录不构成生产 bundle 审批或 GPU 许可。
- 来源证明：`/data2/zhangzibo/arxiv-tssa/preparations/tcl-pilot24-v2-20261102/source-package-v2/source_isolation.json`，SHA256 `70757ea3d09e7f47589db2e408e86895f6428755936a7f80f7bd018bd05a081d`；构造报告 SHA256 为 `d7a5a8872f8ef3f08cf01e5c3df9d9ab93f8a505db212dc8e818e2c1fe4899eb`。
- 固定副本：独立逐项重算 382 个副本的 SHA256，并检查只读权限、单硬链接及路径无符号链接，未发现差异；selection 的相对引用与 8 份掩码一致，terminal 记录完成且与 selection 的父运行身份一致。
- 复用：363 个唯一原始键与固定候选交集完全相等，逐项核对图片、输入和掩码摘要、评分、SQLite 完成记录及原尝试序号均一致。来源包固定 `R_source=363`、`R_merge=0`，合计 `R=363`；生产 bundle 尚未生成，尚未导入 v2 运行账本，也没有 v2 新生成图片。
- 127 转运：原始 `transfer_evidence.json` 的 SHA256 `75e34e7fa7abd4790b4b398cacca738b0880ceb7c766c0a362d9f2cbdfeb7f7a` 已作为只读副本纳入来源证明，191 条图片映射与接收回执一致。审阅时在 104 对接收的 191 张图片逐项重新计算摘要，无差异；接收账本 SHA256 为 `723cb142fec9a7bac084bdf12c9690444dd9ecdd4211ec236d7dbebe4c6b8247`。
- 旧 103：冻结的 v1 确认启动证据绑定父 manifest 与 `GPU-1e9f28a2-986d-7765-2476-3e6388b01170`，按单卡执行边界保守计入 1 张。旧 writer 状态仍为 `unknown`，此结论不证明其已经退出，也不包含其他本人任务的实时占用。
- 历史记录：固定对账快照有 734 次已观察尝试，其中 6 条为 `started`，按 v2 固定 seed 与键集合交集有 4 条；补丁保留这些记录与来源账本摘要的关联，103 后续消耗仍为 `unknown`。其余 2 条使用其他 seed，不属于 v2 交集；`started` 本身不证明失败原因或进程退出。
- 代码与测试：来源构造器 SHA256 `3e319363ff9cb7c4a48ac8f93ee26522303fa7f10e0efd8891d117974a605782` 的 11 项定向测试通过；来源认证与准备器共 39 项测试通过。Python 3.14 的测试 fixture 仍输出 SQLite 连接 `ResourceWarning`，测试通过不代表无警告。
- 未覆盖：截至本次审阅，尚未生成实际生产 bundle、协调器配置或 GPU 许可，未审阅实际 worker 分工与实时资源，也未启动 v2 出图。后续必须独立审阅实际生产输入、分片互斥及预算绑定，并按实时平台和主机证据核验资源。
