# 开发集候选选择独立审计（2026-10-28 13:08 回传）

审计通过：独立重算 6020 项检查，发现 0 项不一致；没有读取持出结果。该结论只评价选择程序和开发证据一致性，不代表攻击效用验证成功。

## 选择与负结果

Uniform 与 RC-TSSA-GD 分别选择 step24，系数均为 (0,0)；各自 step24/step48 的最小 ASR、平均 ASR、R 和差分范数完全同分，由预登记 candidate_id 选择 step24。TSSA 三个候选均不合格，按冻结规则保持缺失。

| 候选 | 三个开发状态 ASR（成功数/分母） | 最小/平均 ASR | R | 是否合格 |
|---|---|---|---|---|
| naive | 0/4, 2/4, 4/4 | 0.0000/0.5000 | 0.0296884361 | 否 |
| Uniform4 | 3/4, 4/4, 3/4 | 0.7500/0.8333 | 0.061650818 | 否 |
| Uniform16 | 4/4, 3/4, 0/4 | 0.0000/0.5833 | 0.0597075637 | 否 |
| TSSA16 | 4/4, 4/4, 4/4 | 1.0000/1.0000 | 0.0590094956 | 否 |
| Uniform-GD_step24 | 0/4, 0/4, 0/4 | 0.0000/0.0000 | 0.0100089929 | 是 |
| Uniform-GD_step48 | 0/4, 0/4, 0/4 | 0.0000/0.0000 | 0.0100089929 | 是 |
| TSSA-GD_step24 | 0/4, 2/4, 3/4 | 0.0000/0.4167 | 0.0235119621 | 否 |
| TSSA-GD_step48 | 0/4, 2/4, 3/4 | 0.0000/0.4167 | 0.0235119621 | 否 |
| RC-TSSA-GD_step24 | 0/4, 0/4, 0/4 | 0.0000/0.0000 | 0.0100089929 | 是 |
| RC-TSSA-GD_step48 | 0/4, 0/4, 0/4 | 0.0000/0.0000 | 0.0100089929 | 是 |

状态顺序为 Edev_0.08、Edev_0.25、Edev_0.50；upload 不测触发图，不能把其缺失 ASR 作为 0 纳入排序。naive 是冻结的固定参考，即使自身正常门槛不合格仍必须保留，不是合格控制族的替代候选。

两个入选候选三状态均 0/4，和 matched_clean 相同；naive 为 0/4、2/4、4/4，因此开发集没有显示 RC 攻击保持收益。零系数的 clean 参数等价和此次开发集零 ASR 是不同层次的证据，后者不能外推为尚未审阅的持出结论。

## 正常指标与门槛

每状态正常分母为 8（配对4+额外4）、单种子2000；ACC 损失限 0.05 意味着该小分母下不能少正确 1 张，CLIP 损失限为原 0–100 分值的 1.0。所有门槛逐状态检查，RC 另须 R ≤ 0.99×R_naive。

| 状态 | clean / 两个入选候选 ACC | clean / 两个入选候选 CLIP | naive ACC | naive CLIP |
|---|---|---|---|---|
| Edev_0.08 | 5/8 | 29.322626442 | 5/8 | 28.659798950 |
| Edev_0.25 | 5/8 | 29.759497195 | 5/8 | 29.017002881 |
| Edev_0.50 | 6/8 | 30.539091304 | 6/8 | 29.393388703 |
| upload | 7/8 | 29.915609956 | 5/8 | 29.652558640 |

RC 的 R=0.0100089928601 ≤ 0.0293915517116，该代理门槛通过但没有 ASR 最低成功门槛。两个零点候选正常图像 ACC/CLIP 与 matched_clean 完全相同；正常响应的三个开发状态 MSE 为0、upload MSE为1.5887537661759172e-05，不能称所有响应均精确为0。

TSSA-GD 的 step24/48 均为 (0,1)，Edev_0.50 与 upload 的响应正常门槛失败，upload 图像 ACC 为6/8对clean7/8，下降0.125，超过0.05。TSSA16 虽有三状态4/4 ASR，但四项响应门槛和部分正常图像门槛失败，不能用攻击成功掩盖正常效用不合格。

## 哈希绑定与样本预算

源协议、完整响应摘要、选择内容哈希、选择文件SHA256及checkpoint绑定哈希均独立复算并核对；导出清单的三个候选、系数和源资产 revision/大小/已冻结哈希一致。开发聚合共 484 张；缺失 TSSA 后，持出设计为 4 个方法（含 naive 与 matched_clean）×4 状态×48张=768张，属于冻结960上限内的减少，不能补跑缺失族凑满。

开发逐图核验状态：`not_available_in_requested_readback`。

| 绑定项 | SHA256 |
|---|---|
| protocol_sha256 | `8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c` |
| run_identity_sha256 | `247d164ebc71d8672a069cf3d20398883ddd3592d2fc44d51ba17ff7fe9c4d62` |
| selection_sha256 | `5686c60ed2adb0d1321dccd58c1c00818dcc4fb6c00b16662c4acef2360bef5d` |
| selection_file_sha256 | `82e5b2a176620d215b818b2b1ffb05e7ca6aa233138a33792e0b2279811700d6` |
| binding_sha256 | `0b79fed0e05c5cbc8fb490a39add0ca65d187ea3512a9f91cc4b9cc54bf40a3d` |

## 证据范围

- 仅审计已提交开发选择；没有读取持出结果、启动模型或重放 Adam，也未更改协议、阈值、active identity 或历史报告。
- 开发集每个攻击状态仅 4 张、1 个种子，正常指标每状态 8 张（配对4+额外4）；比例为描述性证据，不作显著性或泛化证明。
- 核对导出清单及源资产元数据的绑定，未读取远端导出 checkpoint 二进制或重算模型张量；未知本地 SHA 的非 LFS 资产只核对 revision/大小和导出清单一致性。
- TSSA 无合格候选必须保留缺失，不能换入未达门槛的 TSSA16，也不能宣称优于 TSSA；selection passed 仅为进入后续评价的程序门禁。
- 本次指定回传无开发逐图 JSONL，无法独立重算 scored_records_sha256 或分类器原始预测；已核对聚合内部算术、分母及选择哈希绑定。

## 输入文件 SHA256

| 文件 | SHA256 |
|---|---|
| [tssa_mvp_2026-10-26.json](/Users/zzb/arxiv/research/tssa_mvp_2026-10-26.json) | `8f74590f12514f63239448783adc6187422518defc52ec46f014ffb99887e48c` |
| [tssa_mvp_assets_2026-10-26.json](/Users/zzb/arxiv/research/tssa_mvp_assets_2026-10-26.json) | `881d2d21083d589dcd26e69c977a8048d270d2cb73ddb7bd286e2d4dd9197902` |
| [single_run_observation_20261028T050738702889Z.json](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T050738702889Z.json) | `8f8d06ce7b1cf8eb3926e8ce90f2c296ad803be1b3ecacfd87277e4e7aa8e7a4` |
| [candidate_selection.json](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T050738702889Z_artifacts/candidate_selection.json) | `82e5b2a176620d215b818b2b1ffb05e7ca6aa233138a33792e0b2279811700d6` |
| [candidate_response_and_image_metrics.json](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T050738702889Z_artifacts/candidate_response_and_image_metrics.json) | `d5e7cf1237b093e97ca2dc4051618c2e6c04609c800abd3b4f6b4169f1492a63` |
| [selected_checkpoint_manifests.json](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T050738702889Z_artifacts/selected_checkpoint_manifests.json) | `c237cff397511f1e22dfbc0698909a4a7384d09b81a0be2206f6315508406acb` |
| [learned_candidates.json](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T050738702889Z_artifacts/learned_candidates.json) | `070194fa29ad4978d1f8c88a0657859187ae7ac93505d41105721575dd423868` |
| [committed_response_observation_20261028T035929593738Z.json](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/committed_response_observation_20261028T035929593738Z.json) | `078bf75e03079bbb1bbeeb845935c1d66359a29c9acec6bfb1dfc00f57be1217` |

审计脚本 SHA256：`6bb2925def5814324f96c69b49b5522098951677cf74be5b9706e5b1c7054590`。
