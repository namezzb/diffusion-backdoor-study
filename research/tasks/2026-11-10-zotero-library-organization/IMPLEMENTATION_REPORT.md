# 实现与核验报告

## 结果

- Zotero 10.0.8 本机库整理为一个总目录 `Diffusion Backdoor Papers` 和9个英文子分类；旧的平行分类集合已并入后清理。
- 活跃文献条目由同步后识别的71篇减至67篇唯一论文；本轮通过 Zotero 原生合并4组重复条目。重复项在 Zotero 回收站中，可恢复；BadBlocks 的重复记录通过相同 arXiv ID 发现并合并。
- 67篇论文都已有摘要、都只属于一个分类、都存在可读取的本地 PDF 附件；按 arXiv ID 检查没有剩余重复。
- 对22篇缺失本地 PDF 的论文，下载并挂回对应 Zotero 记录；修复了旧的失效链接附件，使其不再作为重复入口。下载副本位于 `/Users/zhangzibo/Desktop/handoff/arxiv/`，共22个文件，约369 MB。
- [论文目录](PAPER_CATALOG.md)按9个类别列出67篇论文及基于摘要撰写的一句话中文简介。

## 分类

| Zotero 分类 | 论文数 |
|---|---:|
| 01 LoRA Merging & Plugin Attacks | 10 |
| 02 T2I Backdoor Attacks | 9 |
| 03 Detection & Defense | 11 |
| 04 Copyright & Data Poisoning | 3 |
| 05 Other Diffusion Modalities & Supply Chain | 15 |
| 06 SAE Methods | 6 |
| 07 Foundational Attacks | 5 |
| 08 Model Merging Backdoors | 5 |
| 09 Benchmarks & Analysis | 3 |

## 工具配置

- 新增本机复用脚本：`/Users/zhangzibo/.codex/skills/zotero/scripts/zotero_local.py`，使用 Zotero 10 Local REST API 批量读写、更新集合与论文分类，并按 Zotero 上传流程附加 PDF。
- 更新 `/Users/zhangzibo/.codex/skills/zotero/SKILL.md`：改正旧版“Local API 只读”说明，记录 Keychain、server ID、版本保护、dry-run 和原生合并要求。
- 本地写授权已由用户确认并储存在 macOS Keychain。脚本不写出或打印密钥。
- arXiv 批量 helper 成功下载21篇；剩余1篇通过 arXiv 官方 PDF 直链补齐。22个文件均以 PDF 文件头和 Zotero 本地可读路径核验。

## 核验范围

- Zotero Local API 实时清单及集合树：1个总集合、9个子集合。
- 活跃父条目：67；摘要缺失：0；未分类或多重分类：0；可读 PDF 缺失：0；重复 arXiv ID：0。
- 原生合并的4组条目已在 Zotero 回收站可见，主条目保留所需 PDF/笔记等子项。
- 本轮没有运行 GPU 实验，也没有修改当前 MasqLoRA 实验 TASK 或 `research/project_state.json`。

## 边界

- 论文简介根据本地 Zotero `abstractNote` 撰写，是摘要级导读，不代表逐篇全文精读；用户后续标注的阅读进度仍应写入对应阅读 TASK 或 Zotero 笔记。
- `/Users/zzb/Desktop/handoff/arxiv/` 在当前机器不可写，因此交接副本保存在当前登录用户桌面 `/Users/zhangzibo/Desktop/handoff/arxiv/`。
- Zotero REST 本身没有合并条目的接口；重复父条目由 Zotero 自带 JavaScript 原生合并方法处理，未通过直接删记录模拟合并。
