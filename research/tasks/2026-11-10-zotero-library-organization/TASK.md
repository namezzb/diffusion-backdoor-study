# Zotero 文献库重整与论文补全

| 字段 | 值 |
|---|---|
| task_id | ZOTERO-ORGANIZE-20261110-01 |
| status | done |
| outcome | done |
| authorization | 用户要求把同步后的 Zotero 文库收进一个英文总目录、按类别整理、合并重复论文，并下载缺失论文；另明确授权本机 Zotero Local API 批量写入 |
| current_stage | 已完成文献盘点、英文分类、重复项原生合并、22 篇 PDF 下载及附件恢复；整理出67篇唯一论文目录和摘要级中文简介 |
| next_action | 继续阅读时优先从 `01 LoRA Merging & Plugin Attacks` 中的 LoRA、ZipLoRA、K-LoRA、SSR-Merge、When LoRA Betrays、Customization under Fire、LoRango 开始；论文简介见 `PAPER_CATALOG.md` |

## 整理原则

- Zotero 以 `Diffusion Backdoor Papers` 为唯一总目录，下面按英文主题分类；每篇论文只在一个分类中出现。
- 合并重复的论文记录，优先保留元数据较完整或 arXiv 当前正式题名对应的主条目；Zotero 原生合并把次条目移入回收站并迁移附件、笔记、标签和集合信息。
- 下载 PDF 后附回原论文条目，不新建重复的论文父条目。
- 每篇简介只陈述论文摘要能支持的内容，不把摘要级阅读表述成全文精读。

## 结果入口

- [实现与核验报告](IMPLEMENTATION_REPORT.md)
- [67 篇论文分类及简介](PAPER_CATALOG.md)
