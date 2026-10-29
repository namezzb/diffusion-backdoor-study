# 独立结果复核（仅本机 CPU）

本工具读取已回传的观察包，只写新的独立审计文件，不连接服务器、不启动 GPU、不生成图片或修改冻结输入。它不导入生产 runner 的评分、汇总或选择代码。

## 使用

```sh
python3 results/tssa-opt-exploration-2026-10-28/audit_image_search_results.py \
  results/tssa-opt-exploration-2026-10-28/<观察包>/report.json \
  --output results/tssa-opt-exploration-2026-10-28/<新的独立审计文件>.json
```

输出文件必须尚不存在且位于观察包目录之外；退出码 0 表示已完成本次审计（包括诚实的 `partial`），退出码 2 表示证据不一致。`partial` 不代表完整实验通过，调用方必须读取 `status`、`scientific_conclusion` 和各阶段进度。

## 核验范围

- 固定 manifest SHA 为 `8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6`，重新核对本机旧协议、资产清单、四份冻结源码及 run identity。逐文件核对传输大小和 SHA，再从冻结条件、候选、prompt、seed 重建 task ID，并核对 receipt、record、图片路径及执行元数据绑定。
- 每个语义任务必须唯一，`started` 也计入尝试上限；阶段上限为 search 624、dev 240、confirm 576，总图数 1,440、更新为 0、branch-NFE 上限 72,000。未完成 receipt 不会被重跑或算成完成图，未知文件与已声明回传却缺失的 receipt 都拒绝验收。
- 从逐图 ViT 标签及 CLIP 分数重新计算正常 ACC、CLIP、成对/额外正常分组和分 seed 指标；四种状态均与匹配 clean 比较，包含 upload。门槛仍为 ACC 下降最多 0.05、CLIP 下降最多 1.0，数值决策只沿用冻结执行器的 `1e-12` guard。
- ASR 使用固定猫类别 281–287，正常 ACC 使用冻结 row 的原类别；主排序只计三个合并状态的 macro/worst ASR，upload 攻击单列。排序为 macro 降序、worst 降序、系数范数升序、候选 ID 升序，naive 即使正常约束失败也保留原始比较。
- 完整阶段才允许审阅并比较已提交 summary/selection；search 选前三合格候选，dev/confirm 要求 macro 严格高于 naive 且 worst 不下降。确认集 receipt、summary 与最终报告在完整且正确的 dev selection 和 confirm binding 验证前保持未读；本工具不信任观察器给出的 `confirm_unlocked` 布尔值来解锁。
- 序列化指标比较绝对容差为 `1e-9`，仅用于检查数字记录是否一致，不用于放宽门槛、排序或晋级。完整最终报告也必须与独立阶段结果一致，才允许输出基于已记录评分的探索性结论。

## 证据边界

此审计验证已记录评分的数学汇总和证据链，不重新运行分类器或 CLIP；没有回传的 PNG 只验证其声明 SHA 格式，并明确列为未验字节。哈希提供内容与传输一致性，不构成防止所有文件一起被改写的数字签名，也不能由 NVML 查询成功或失败推导实验有效性。

观察包不是跨文件原子快照，阶段计数以实际 copied receipts 为准；如果更晚阶段的文件已出现但前置选择尚未回传，内容保持锁定。只有新鲜确认样本产生观察到的提升才能作为探索结果，不能自动解释为稳健、统计显著、SOTA 或未见专家泛化。

## 当前实际验收

观察包 `observation_103_20261028T091756108336Z-bac35dfe/report.json` 的 SHA 为 `1613c8d6a44938246d810113931d6b3550f5683d4f85f6864ad1b54e1d6086e9`。独立报告为 `independent_result_audit_20261028T091756Z_r2.json`：153 个传输文件哈希通过、150 completed、1 started、search 150/624、记录 NFE 7,500，无完整阶段选择或科学有效性结论。

确认结果未打开，150 张 PNG 字节均未回传，NVML18/驱动库不匹配作为资源观察错误原样保留。此前 67+1 的 `r1` 报告保留作为历史审计，不覆盖。

21 项本机检查全部通过，包含手工可计算的正常/攻击指标、upload 门槛、排序、门槛边界、确认隔离，以及逐层篡改/缺失凭证拦截。合成完整链与全部篡改负例均标为 `SIMULATED`，其 1,440 图/72,000 NFE 数字只是测试结构，不是新科研样本。
