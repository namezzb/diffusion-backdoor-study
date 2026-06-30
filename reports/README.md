# 📊 Reports 索引

> 扩散模型后门研究文档集合  
> 最后更新：2026-06-30

本目录包含三个分类的子目录，按研究流程组织报告文档。

---

## 📚 目录结构

```
reports/
├── README.md                          # 本索引文件
├── 01-background-research/            # 背景调研 (6 files, 254K)
├── 02-cross-reference/                # 代码-论文交叉对照 (4 files, 76K)
└── 03-reproduction-results/           # 复现结果报告 (3 files, 34K)
```

---

## 🔬 01-background-research/

**背景调研** — 文献综述、论文精读、创新思路设计

| 文件名 | 大小 | 内容 | 生成日期 |
|--------|------|------|----------|
| [diffusion_backdoor_deep_survey_2025_2026.md](./01-background-research/diffusion_backdoor_deep_survey_2025_2026.md) | 80K | 2025-2026年扩散后门深度调研，覆盖最新攻击/防御方法 | 2026-06-25 |
| [diffusion_backdoor_novel_ideas.md](./01-background-research/diffusion_backdoor_novel_ideas.md) | 44K | 面向顶会的10个创新研究思路 (英文版) | 2026-06-25 |
| [diffusion_backdoor_novel_ideas_zh.md](./01-background-research/diffusion_backdoor_novel_ideas_zh.md) | 40K | 面向顶会的10个创新研究思路 (中文版) | 2026-06-25 |
| [diffusion_backdoor_optimized_ideas_v2.md](./01-background-research/diffusion_backdoor_optimized_ideas_v2.md) | 16K | 优化后的高性价比创新思路 (v2版本) | 2026-06-25 |
| [merge_backdoor_research_report.md](./01-background-research/merge_backdoor_research_report.md) | 20K | 检查点合并后门持久性研究，深度调研与方法设计 | 2026-06-25 |
| [paper_deep_reading_report.md](./01-background-research/paper_deep_reading_report.md) | 20K | 15篇扩散后门论文全文精读汇编 | 2026-06-26 |

---

## 🔍 02-cross-reference/

**代码-论文交叉对照** — BackdoorDM 实现与原始论文的对比验证

| 文件名 | 大小 | 内容 | 生成日期 |
|--------|------|------|----------|
| [backdoordm_crossref_report.md](./02-cross-reference/backdoordm_crossref_report.md) | 24K | BackdoorDM 实现 vs 原始论文完整交叉对照 | 2026-06-28 |
| [backdoordm_paper_crossref_summary.md](./02-cross-reference/backdoordm_paper_crossref_summary.md) | 12K | 全方法论文交叉验证汇总 | 2026-06-28 |
| [backdoordm_t2i_cross_reference_report.md](./02-cross-reference/backdoordm_t2i_cross_reference_report.md) | 20K | T2I 攻击方法专项交叉验证 | 2026-06-28 |
| [defense_cross_reference_report.md](./02-cross-reference/defense_cross_reference_report.md) | 20K | 防御方法交叉对照 | 2026-06-28 |

---

## 🧪 03-reproduction-results/

**复现结果报告** — 实验输出与最终复现报告

| 文件名 | 大小 | 内容 | 生成日期 |
|--------|------|------|----------|
| [backdoordm_final_report.md](./03-reproduction-results/backdoordm_final_report.md) | 12K | BackdoorDM 全方法复现最终报告 (待填充) | 2026-06-28 |
| [backdoordm_reproduction_results.md](./03-reproduction-results/backdoordm_reproduction_results.md) | 12K | 复现结果汇总报告 | 2026-06-28 |
| [eviledit_reproduction_report.md](./03-reproduction-results/eviledit_reproduction_report.md) | 12K | EvilEdit 方法专项复现报告 | 2026-06-28 |

---

## 📖 阅读建议

### 快速了解项目
1. 先读 [backdoordm_final_report.md](./03-reproduction-results/backdoordm_final_report.md) — 了解复现目标与当前状态
2. 再读 [backdoordm_paper_crossref_summary.md](./02-cross-reference/backdoordm_paper_crossref_summary.md) — 了解实现与论文的差异

### 深入理解背景
1. [paper_deep_reading_report.md](./01-background-research/paper_deep_reading_report.md) — 15篇核心论文精读
2. [diffusion_backdoor_deep_survey_2025_2026.md](./01-background-research/diffusion_backdoor_deep_survey_2025_2026.md) — 最新研究进展

### 探索创新方向
1. [diffusion_backdoor_novel_ideas_zh.md](./01-background-research/diffusion_backdoor_novel_ideas_zh.md) — 10个顶会级创新思路
2. [merge_backdoor_research_report.md](./01-background-research/merge_backdoor_research_report.md) — 检查点合并后门持久性研究

---

## 🔗 相关资源

- **论文 PDF**: `../papers/` (18篇 PDF + 索引)
- **实验脚本**: `../experiments/backdoordm_reproduce/scripts/`
- **服务器配置**: `../server/`
- **交接文档**: `/Users/zzb/Desktop/handoff/arxiv/`

---

## 📊 统计信息

| 分类 | 文件数 | 总大小 | 日期范围 |
|------|--------|--------|----------|
| 背景调研 | 6 | 254K | 2026-06-25 ~ 2026-06-26 |
| 交叉对照 | 4 | 76K | 2026-06-28 |
| 复现结果 | 3 | 34K | 2026-06-28 |
| **总计** | **13** | **364K** | **2026-06-25 ~ 2026-06-28** |
