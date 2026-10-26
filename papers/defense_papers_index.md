# 防御论文阅读索引

> 更新：2026-10-26；五篇 PDF 均已在本地，题名与本地版本以首页核对结果为准。本页提供资料入口，不复用未经本轮核查的性能数字或失效脚本链接。

| 方法 | 阅读主题 | 本地 PDF |
|---|---|---|
| Elijah | 模型检测与缓解 | [2312.00050v2](pdf/2312.00050.pdf) |
| T2IShield | 文本到图像后门检测、定位与缓解 | [2407.04215v2](pdf/2407.04215.pdf) |
| Textual Perturbation | 输入侧文本扰动 | [2408.15721v1](pdf/2408.15721.pdf) |
| TERD | 模型与输入检测 | [2409.05294v1](pdf/2409.05294.pdf) |
| DAA | 文本到图像后门检测 | [2504.20518v3](pdf/2504.20518.pdf) |

## Elijah

**Elijah: Eliminating Backdoors Injected in Diffusion Models via Distribution Shift**。利用分布偏移分析扩散后门，具体配置与适用范围按论文核对。

正式发表信息未在本轮确认，引用时应进一步核查官方页面；本地校验信息见 [catalog.json](catalog.json)。

## T2IShield

**T2IShield: Defending Against Backdoors on Text-to-Image Diffusion Models**。从交叉注意力中的同化现象构造检测信号，并研究触发器定位和概念编辑缓解。

正式发表信息未在本轮确认，引用时应进一步核查官方页面；本地校验信息见 [catalog.json](catalog.json)。

## Textual Perturbation

**Defending Text-to-image Diffusion Models: Surprising Efficacy of Textual Perturbations Against Backdoor Attacks**。研究文本扰动对触发器有效性的影响，需同时检查语义与正常生成表现。

正式发表信息未在本轮确认，引用时应进一步核查官方页面；本地校验信息见 [catalog.json](catalog.json)。

## TERD

**TERD: A Unified Framework for Safeguarding Diffusion Models Against Backdoors**。通过触发器估计和精炼构造检测信号，适用扩散流程需逐项核对。

本地首页可确认发表线索：ICML 2024 (PDF p.1)；本轮未核验线上最新版本。

## DAA

**Dynamic Attention Analysis for Backdoor Detection in Text-to-Image Diffusion Models**。分析去噪时间过程中的动态注意力特征，区分正常与后门样本。

正式发表信息未在本轮确认，引用时应进一步核查官方页面；本地校验信息见 [catalog.json](catalog.json)。

## 如何对照复现

- 论文方法与实现差异见 [防御交叉核对报告](../reproduction/defense_cross_reference_report.md)，实际执行状态见 [BackdoorDM 复现进度](../reproduction/backdoordm_progress.md)。
- 论文基准数值及其口径见 [BackdoorDM 基准参考](../reproduction/backdoordm_reference.md)，该参考只读；本页不重新推定 ASR、FID、F1、AUC 或检测率。
- 原索引中的 `experiments/backdoordm_reproduce/scripts/` 已是历史路径，现移除这些不可作为当前执行入口的引用；当前可运行命令应在实验准备时对照实际服务器和归档脚本确认。
- 五种防御已存在历史执行记录，不代表对当前 TSSA 梯度版已经完成评测；当前方法尚需独立实现和验证。

返回 [论文总索引](README.md)。
