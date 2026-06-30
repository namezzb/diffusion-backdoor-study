# 📊 Reports 索引

> 扩散模型后门研究文档集合
> 最后更新：2026-06-30

---

## 📚 目录结构

```
reports/
├── README.md                          # 本索引文件
├── 01-background-research/            # 背景调研 (6 files)
├── 02-cross-reference/                # 代码-论文交叉对照 (4 files)
└── 03-reproduction-results/           # 基准参考 (1 file, 只读)
```

> **注意**: 复现进度文档已移至项目根目录 `backdoordm_progress.md`。

---

## 🧪 03-reproduction-results/

**基准参考** — BackdoorDM 论文基准值 + 指标定义 + 脚本覆盖（只读，勿改）

| 文件名 | 内容 |
|--------|------|
| [backdoordm_reference.md](./03-reproduction-results/backdoordm_reference.md) | BackdoorDM 论文全部基准值表 (Table 3-16)、指标名称对照、31 种指标列表、防御输出 vs 论文参考值、官方脚本覆盖、配置修复、已知限制 |

---

## 🔬 01-background-research/

**背景调研** — 文献综述、论文精读、创新思路设计

| 文件名 | 内容 | 日期 |
|--------|------|------|
| [diffusion_backdoor_deep_survey_2025_2026.md](./01-background-research/diffusion_backdoor_deep_survey_2025_2026.md) | 2025-2026年扩散后门深度调研 | 2026-06-25 |
| [diffusion_backdoor_novel_ideas_zh.md](./01-background-research/diffusion_backdoor_novel_ideas_zh.md) | 10个顶会级创新思路 (中文版) | 2026-06-25 |
| [merge_backdoor_research_report.md](./01-background-research/merge_backdoor_research_report.md) | 检查点合并后门持久性研究 | 2026-06-25 |
| [paper_deep_reading_report.md](./01-background-research/paper_deep_reading_report.md) | 15篇扩散后门论文全文精读 | 2026-06-26 |

---

## 🔍 02-cross-reference/

**代码-论文交叉对照** — BackdoorDM 实现与原始论文的对比验证

| 文件名 | 内容 | 日期 |
|--------|------|------|
| [backdoordm_paper_crossref_summary.md](./02-cross-reference/backdoordm_paper_crossref_summary.md) | 全方法论文交叉验证汇总 | 2026-06-28 |
| [backdoordm_crossref_report.md](./02-cross-reference/backdoordm_crossref_report.md) | BackdoorDM 实现 vs 原始论文完整对照 | 2026-06-28 |
| [backdoordm_t2i_cross_reference_report.md](./02-cross-reference/backdoordm_t2i_cross_reference_report.md) | T2I 攻击方法专项交叉验证 | 2026-06-28 |
| [defense_cross_reference_report.md](./02-cross-reference/defense_cross_reference_report.md) | 防御方法交叉对照 | 2026-06-28 |

---

## 🔗 相关资源

- **进度文档**: `../backdoordm_progress.md`（可变，loop 每次更新）
- **循环指令**: `../LOOP.md`
- **论文 PDF**: `../papers/`（24 篇 PDF + 索引）
- **归档脚本**: `../archive/experiments/`（只读）
