# TSSA 最终持出独立 CPU 审计

独立重算通过：True；检查 37334 项，不一致 0 项。

技术执行已经完成，但本轮 RC-TSSA-GD 的攻击恢复目标没有得到支持：RC 与 Uniform 选中 (0,0)，四个持出单元均为 0/16，且与 matched-clean 的 192 条分类/CLIP 输出完全一致。TSSA 没有合格开发候选，不能据其缺席宣称优于 TSSA。

| 方法 | 状态 | ASR | 正常 ACC | 正常 CLIP | 正常门槛 |
|---|---|---:|---:|---:|---|
| RC-TSSA-GD | Edev_0.15 | 0/16 | 27/32 | 28.982728 | True |
| RC-TSSA-GD | Ehold_0.15 | 0/16 | 25/32 | 27.214631 | True |
| RC-TSSA-GD | Ehold_0.25 | 0/16 | 27/32 | 27.964761 | True |
| RC-TSSA-GD | upload | 0/16 | 26/32 | 28.724230 | True |
| Uniform | Edev_0.15 | 0/16 | 27/32 | 28.982728 | True |
| Uniform | Ehold_0.15 | 0/16 | 25/32 | 27.214631 | True |
| Uniform | Ehold_0.25 | 0/16 | 27/32 | 27.964761 | True |
| Uniform | upload | 0/16 | 26/32 | 28.724230 | True |
| naive | Edev_0.15 | 4/16 | 27/32 | 29.332882 | True |
| naive | Ehold_0.15 | 3/16 | 26/32 | 27.951089 | True |
| naive | Ehold_0.25 | 13/16 | 26/32 | 27.776956 | True |
| naive | upload | 13/16 | 26/32 | 28.333228 | True |

正式协议没有额外的“最终 ASR 达到某数即成功”阈值，而要求报告最低/平均 ASR、逐格对照差及正常门槛；`completed_with_missing_qualified_controls` 表示完成评价，`normal_utility_gate.passed` 表示正常筛查通过，均不是 idea 成功。RC 四格 ASR 均低于 naive、与 Uniform 相同，naive 四格正常门槛也通过，因此本次结果是负面的描述性证据。

样本集合逐项吻合冻结提示、状态、seed和候选身份，源门禁48、静态220、开发484、持出768，合计1520图；主预算1472图≤1664，更新144次，训练反向调用1008次。少于上限1712图的192图恰为没有合格TSSA候选而未生成的持出工作，不是遗漏应评的有效候选。

全部逐图记录均与对应 operation receipt 的已完成载荷哈希吻合，选择及导出完成时间早于首次持出生成；审计独立重算开发筛选、全部持出及逐seed指标、315个失败样本、选择绑定和资源计数，未调用原评价器函数。

主任务前向 branch-NFE为82248，源门禁2400；成功诊断138、原误停已记录118及未完整计数的反向成本另列。正常门槛相对 matched-clean 要求 ACC 下降不超过5个百分点且 CLIP 下降不超过1分；32张正常图下最多允许少1张正确，少2张即超限。

审计限制：
- No model inference, image rescoring, or independent pixel-level verification was run; classification and CLIP values are audited as the recorded output of the pinned scorers.
- Every locally returned artifact hash and every image-row operation-envelope hash was verified; original 1520 image PNGs and large exported checkpoint binaries remain on the server and were not independently rehashed by this CPU audit.
- Each ASR cell has 16 images from eight semantic prompt clusters and two paired seeds; cells and seeds are not independent semantic replications.
- Normal utility pass means only the preregistered small-sample ACC/CLIP screen; no formal FID, significance, or SOTA evidence.
- The earlier interrupted diagnostic is separate from science budget; its recorded 118 branch-NFE and partial/unknown backward cost are not zero.
- Future choices informed by these test results must treat Dtest/Ehold as development evidence and introduce new held-out data.

复现命令：
```sh
python3 results/tssa-mvp-2026-10-26/audit_final_heldout_20261028T0602Z.py --output-prefix /tmp/tssa-final-heldout-recheck
```

审计输入：`/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T060221238162Z.json`；逐格、逐seed、全部校验哈希、完整计数和限制见同名 JSON。
