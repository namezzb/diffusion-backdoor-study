# 论文资料索引

> 更新：2026-10-26；本地 PDF 共 24 篇，题名与版本已对照各 PDF 首页，文件校验和见 [catalog.json](catalog.json)。本轮只整理已有资料，未下载论文或核验线上最新版本。

换机时按[catalog.json](catalog.json)的`retrieval.url`取固定arXiv版本，并比对记录的大小和SHA；这些地址按已核对的本地版本生成，本轮未联网复验。少量既有提取文本/HTML作为小文件例外纳入Git，24个PDF仍按需下载。

## 从哪里开始

- 当前方法：[TSSA 梯度校准方案](../research/tssa_response_calibration_method_proposal.md)，优先阅读 BackdoorDM、Rickrolling、BadT2I 与 BadMerging。
- 缺失文献：[待核验下载清单](download_queue.md)，包含真正的 EvilEdit 和当前方案已引用但未保存的论文。
- 防御资料：[防御方法索引](defense_papers_index.md)；历史搜索元数据：[metadata/README.md](metadata/README.md)。

## 目录

```text
papers/
├── README.md                 # 按主题导航
├── catalog.json              # 题名、本地版本、页数、SHA-256 与来源
├── download_queue.md         # 待核验、待下载文献
├── defense_papers_index.md   # 五种防御的阅读入口
├── pdf/                      # 全部 24 篇 PDF，统一单层保存
├── txt/                      # 已提取文本与历史 HTML 页面
└── metadata/                 # 两份原始搜索快照
```

论文按下方主题表格分类，PDF 不再按主题增加子目录；标题大小写、连字符和空白按首页文字规范化。

## 基准（1 篇）

| 方法 / 主题 | 首页核对题名 | 本地 PDF / 版本 |
|---|---|---|
| BackdoorDM | BackdoorDM: A Comprehensive Benchmark for Backdoor Learning on Diffusion Model | [2502.11798v2](pdf/2502.11798.pdf) |

## 扩散后门攻击（8 篇）

| 方法 / 主题 | 首页核对题名 | 本地 PDF / 版本 |
|---|---|---|
| Rickrolling | Rickrolling the Artist: Injecting Backdoors into Text Encoders for Text-to-Image Synthesis | [2211.02408v3](pdf/2211.02408.pdf) |
| BadDiffusion | How to Backdoor Diffusion Models? | [2212.05400v3](pdf/2212.05400.pdf) |
| TrojDiff | TrojDiff: Trojan Attacks on Diffusion Models with Diverse Targets | [2303.05762v1](pdf/2303.05762.pdf) |
| BadT2I | Text-to-Image Diffusion Models can be Easily Backdoored through Multimodal Data Poisoning | [2305.04175v2](pdf/2305.04175.pdf) |
| PaaS | Personalization as a Shortcut for Few-Shot Backdoor Attack against Text-to-Image Diffusion Models | [2305.10701v3](pdf/2305.10701.pdf) |
| VillanDiffusion | VillanDiffusion: A Unified Backdoor Attack Framework for Diffusion Models | [2306.06874v5](pdf/2306.06874.pdf) |
| BiBadDiff | From Trojan Horses to Castle Walls: Unveiling Bilateral Data Poisoning Effects in Diffusion Models | [2311.02373v2](pdf/2311.02373.pdf) |
| InviBackdoor | Invisible Backdoor Attacks on Diffusion Models | [2406.00816v1](pdf/2406.00816.pdf) |

## 模型合并攻防（2 篇）

| 方法 / 主题 | 首页核对题名 | 本地 PDF / 版本 |
|---|---|---|
| BadMerging | BadMerging: Backdoor Attacks Against Model Merging | [2408.07362v2](pdf/2408.07362.pdf) |
| LFPM | From Parameters to Feature Space: Task Arithmetic for Backdoor Mitigation in Model Merging | [2606.12498v1](pdf/2606.12498.pdf) |

## 扩散后门防御（5 篇）

| 方法 / 主题 | 首页核对题名 | 本地 PDF / 版本 |
|---|---|---|
| Elijah | Elijah: Eliminating Backdoors Injected in Diffusion Models via Distribution Shift | [2312.00050v2](pdf/2312.00050.pdf) |
| T2IShield | T2IShield: Defending Against Backdoors on Text-to-Image Diffusion Models | [2407.04215v2](pdf/2407.04215.pdf) |
| Textual Perturbation | Defending Text-to-image Diffusion Models: Surprising Efficacy of Textual Perturbations Against Backdoor Attacks | [2408.15721v1](pdf/2408.15721.pdf) |
| TERD | TERD: A Unified Framework for Safeguarding Diffusion Models Against Backdoors | [2409.05294v1](pdf/2409.05294.pdf) |
| DAA | Dynamic Attention Analysis for Backdoor Detection in Text-to-Image Diffusion Models | [2504.20518v3](pdf/2504.20518.pdf) |

## 扩展研究（8 篇）

| 方法 / 主题 | 首页核对题名 | 本地 PDF / 版本 |
|---|---|---|
| SAeUron | SAeUron: Interpretable Concept Unlearning in Diffusion Models with Sparse Autoencoders | [2501.18052v3](pdf/2501.18052.pdf) |
| TIDE | TIDE: Temporal-Aware Sparse Autoencoders for Interpretable Diffusion Transformers in Image Generation | [2503.07050v2](pdf/2503.07050.pdf) |
| VAGUEGAN | VAGUEGAN: Stealthy Poisoning and Backdoor Attacks on Image Generative Pipelines | [2509.24891v1](pdf/2509.24891.pdf) |
| Backdoor Modality Collapse | When One Modality Rules Them All: Backdoor Modality Collapse in Multimodal Diffusion Models | [2603.06508v1](pdf/2603.06508.pdf) |
| BadDLM | BadDLM: Backdooring Diffusion Language Models with Diverse Targets | [2605.09397v1](pdf/2605.09397.pdf) |
| DiffusionHijack | DiffusionHijack: Supply-Chain PRNG Backdoor Attack on Diffusion Models and Quantum Random Number Defense | [2605.13115v1](pdf/2605.13115.pdf) |
| Residualized Temporal SAE | Residualized Temporal Sparse Autoencoders for Interpreting Diffusion Models | [2605.27813v1](pdf/2605.27813.pdf) |
| LLM latent backdoor detection | Shared Latent Structures Enable Unified Backdoor Detection and Mitigation in LLMs | [2606.07963v1](pdf/2606.07963.pdf) |

## 已纠正的书目信息

- `2501.18052.pdf` 是 **SAeUron: Interpretable Concept Unlearning in Diffusion Models with Sparse Autoencoders**，首页标示 ICML 2025；此前误写为 EvilEdit，真正的 EvilEdit 尚未保存到本地 PDF 目录。
- `2211.02408.pdf` 是 **Rickrolling the Artist: Injecting Backdoors into Text Encoders for Text-to-Image Synthesis**，首页明确 ICCV 2023；此前索引的改写题名与 ICLR 2023 标注已纠正。
- `2503.07050.pdf` 是 TIDE，`2606.07963.pdf` 是 LLM 后门检测与缓解论文；两者作为扩展阅读保存，不计作 PaaS 或 BackdoorDM。
- 其余旧索引的简称已改为首页题名，未在本轮核实的会议或期刊信息不作为已确认事实展示；旧索引快照保留在 [整理前备份](../archive/organization-2026-10-26/before_text_and_source.zip)。

## 证据边界

- 本地 PDF 共 24 个，均可解析，SHA-256 无重复；文件名中的 arXiv ID 与首页标记一致。
- PDF 到位只表示文献可读，不表示代码已复现或结果已验收；实验状态以 [BackdoorDM 复现进度](../reproduction/backdoordm_progress.md) 和 [当前研究进度](../research/merging_attack_progress.md) 为准。
