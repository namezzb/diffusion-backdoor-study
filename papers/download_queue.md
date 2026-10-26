# 待核验与下载清单

> 更新：2026-10-26；以下条目尚未下载，本轮只核对本地缺口。外链来自既有研究材料，须先核验真实题名、作者与版本，再下载并登记校验和。

## 当前方案优先补齐

| 方法 | 为什么需要 | 现有来源线索 | 本地状态 |
|---|---|---|---|
| EvilEdit | 修正旧索引的错配，补齐已有复现相关的原论文 | [作者 PDF（待核验）](https://tianweiz07.github.io/Papers/24-mm-1.pdf) | 未下载；本轮未联网核验 |
| AdaMerging | 学习合并系数的直接先例 | [2310.02575（待核验）](https://arxiv.org/html/2310.02575) | 未下载；本轮未联网核验 |
| LoBAM | 已有后门差分放大的接近工作 | [2411.16746（待核验）](https://arxiv.org/html/2411.16746v3) | 未下载；本轮未联网核验 |
| RogueMerge | 合并攻击与正常效用的相关工作 | [2606.03344（待核验）](https://arxiv.org/html/2606.03344v2) | 未下载；本轮未联网核验 |
| DiffSafeMerge | 扩散模型合并防御的相关工作 | [2608.09445（待核验）](https://arxiv.org/html/2608.09445v1) | 未下载；本轮未联网核验 |

EvilEdit 线索暂称 *EvilEdit: Backdooring Text-to-Image Diffusion Models in One Second*；`pdf/2501.18052.pdf` 已确认是 SAeUron，不得继续作为 EvilEdit 使用。

## 后续扩展

| 方法 | 用途 | 线索与状态 |
|---|---|---|
| Merge Hijacking | 稀疏化与缩放的相关攻击对照 | [2505.23561](https://arxiv.org/abs/2505.23561)，旧调研线索；未下载、未在本轮联网核验 |
| TIES 原论文 | 后续真实多源 TIES 合并协议 | 本地无对应 PDF；准确书目与官方来源待核验 |
| DARE 原论文 | 后续随机删除与重缩放合并协议 | 本地无对应 PDF；准确书目与官方来源待核验 |

## 已有资料与下载完成条件

- BackdoorDM、Rickrolling、BadT2I、BadMerging、LFPM 以及五篇扩散防御论文已在 [本地索引](README.md)，无需为补齐当前清单重复下载同一版本。
- 下载前核对官方页面、PDF 首页题名及版本，下载后记录来源、日期、SHA-256 并更新 [catalog.json](catalog.json)；论文保存统一使用 `pdf/`，不覆盖现有不同版本而不留记录。
- P0 清单用于补齐当前方案的资料，后续是否实现某个方法仍需按威胁模型、可复现资源与计算预算决定；不能把论文已下载写成基线已复现。

当前工作依据：[TSSA 梯度校准方案](../research/tssa_response_calibration_method_proposal.md)。
