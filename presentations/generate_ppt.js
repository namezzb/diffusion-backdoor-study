const PptxGenJS = require("pptxgenjs");
const pres = new PptxGenJS();

pres.layout = "LAYOUT_16x9";
pres.author = "Research Team";
pres.title = "Diffusion Model Checkpoint Merging Backdoor Security";

const C = {
  bg: "FFFFFF",
  primary: "1F4E79",
  accent: "2E75B6",
  body: "2D2D2D",
  muted: "777777",
  rule: "CCCCCC",
  highlight: "FFF2CC",
  red: "C0392B",
  green: "27AE60",
  orange: "E67E22",
  lightBg: "F0F4F8",
  darkBg: "1A3A5C",
};
const F = { face: "Arial", title: 24, section: 20, body: 18, label: 15, cite: 12 };
const M = 0.5;

function addDivider(slide, y) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: M, y, w: 9.0, h: 0.025, fill: { color: C.rule },
  });
}

function addCitation(slide, text) {
  slide.addText(text, {
    x: M, y: 5.15, w: 9.0, h: 0.35,
    fontSize: C.cite, fontFace: F.face, color: C.muted, align: "left",
  });
}

// ============================================================
// SLIDE 1: Title
// ============================================================
let s1 = pres.addSlide();
s1.background = { color: C.primary };

s1.addText("How Backdoors Survive the Merge", {
  x: 0.7, y: 1.0, w: 8.6, h: 1.0,
  fontSize: 34, fontFace: F.face, color: "FFFFFF", bold: true, align: "left",
});
s1.addText("扩散模型检查点合并中后门持久性的系统性研究", {
  x: 0.7, y: 2.0, w: 8.6, h: 0.6,
  fontSize: 20, fontFace: F.face, color: "CADCFC", align: "left",
});

s1.addShape(pres.shapes.RECTANGLE, {
  x: 0.7, y: 2.85, w: 2.0, h: 0.04, fill: { color: C.accent },
});

s1.addText("研究方向汇报  ·  2026年6月", {
  x: 0.7, y: 3.0, w: 8.6, h: 0.4,
  fontSize: 16, fontFace: F.face, color: "A0BBDD", align: "left",
});

s1.addText("目标会议: USENIX Security / NDSS / CCS", {
  x: 0.7, y: 3.5, w: 8.6, h: 0.4,
  fontSize: 14, fontFace: F.face, color: "7BAFD4", align: "left",
});

// ============================================================
// SLIDE 2: Motivation
// ============================================================
let s2 = pres.addSlide();

s2.addText("社区每天数千次模型合并操作，零安全审计——后门可能在合并中扩散", {
  x: M, y: 0.2, w: 9.0, h: 0.85,
  fontSize: F.title, fontFace: F.face, color: C.primary, bold: true,
});
addDivider(s2, 1.05);

s2.addText("现状", {
  x: M, y: 1.15, w: 4.2, h: 0.35,
  fontSize: F.section, fontFace: F.face, color: C.accent, bold: true,
});
s2.addText([
  { text: "CivitAI/HuggingFace: ", options: { bold: true, breakLine: false } },
  { text: "用户日常合并 SD 检查点生成个性化模型", options: { breakLine: true } },
  { text: "合并算法: ", options: { bold: true, breakLine: false } },
  { text: "LERP, SLERP, DARE, TIES, Task Arithmetic", options: { breakLine: true } },
  { text: "安全审计: ", options: { bold: true, breakLine: false } },
  { text: "完全不存在——用户信任上传者", options: { breakLine: true } },
], {
  x: M, y: 1.55, w: 4.2, h: 2.5,
  fontSize: F.body, fontFace: F.face, color: C.body, bullet: true, paraSpaceAfter: 10,
});

s2.addText("威胁场景", {
  x: 5.3, y: 1.15, w: 4.2, h: 0.35,
  fontSize: F.section, fontFace: F.face, color: C.red, bold: true,
});
s2.addText([
  { text: "攻击者上传含后门的模型到社区平台", options: { breakLine: true } },
  { text: "用户下载后与自己的模型合并", options: { breakLine: true } },
  { text: "合并后的模型是否仍携带后门？", options: { bold: true, breakLine: true } },
  { text: "后门是否通过迭代合并扩散到更多模型？", options: { bold: true, breakLine: true } },
], {
  x: 5.3, y: 1.55, w: 4.2, h: 2.5,
  fontSize: F.body, fontFace: F.face, color: C.body, bullet: true, paraSpaceAfter: 10,
});

addCitation(s2, "CivitAI 统计：2025年单月合并模型超 50,000 个");

// ============================================================
// SLIDE 3: Research Question
// ============================================================
let s3 = pres.addSlide();

s3.addText("核心问题：扩散模型后门在检查点合并中的命运是什么？", {
  x: M, y: 0.2, w: 9.0, h: 0.85,
  fontSize: F.title, fontFace: F.face, color: C.primary, bold: true,
});
addDivider(s3, 1.05);

s3.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 1.0, y: 1.3, w: 8.0, h: 1.8,
  fill: { color: "EBF3FA" }, line: { color: C.accent, pt: 1.5 }, rectRadius: 0.1,
});
s3.addText([
  { text: "RQ1: ", options: { bold: true, breakLine: false } },
  { text: "现有扩散模型后门攻击在经过 LERP/SLERP/DARE/TIES 合并后，ASR 如何衰减？", options: { breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "RQ2: ", options: { bold: true, breakLine: false } },
  { text: "不同攻击类型（training-based vs training-free）的合并鲁棒性有何差异？", options: { breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "RQ3: ", options: { bold: true, breakLine: false } },
  { text: "基于实证结果，应提出防御策略、增强攻击、还是安全合并指南？", options: { breakLine: true } },
], {
  x: 1.3, y: 1.4, w: 7.4, h: 1.6,
  fontSize: 17, fontFace: F.face, color: C.primary, paraSpaceAfter: 4,
});

s3.addText([
  { text: "研究意义: ", options: { bold: true, breakLine: false } },
  { text: "CV (BadMerging, CCS'24) 和 NLP (Merge Hijacking, ACL'25) 已研究合并后门，但扩散模型领域完全空白", options: { breakLine: true } },
], {
  x: M, y: 3.4, w: 9.0, h: 0.8,
  fontSize: F.body, fontFace: F.face, color: C.body,
});

// ============================================================
// SLIDE 4: Related Work - Existing Attacks
// ============================================================
let s4 = pres.addSlide();

s4.addText("扩散模型后门攻击已高度成熟——EvilEdit 仅需 1 秒即可注入 100% ASR 后门", {
  x: M, y: 0.2, w: 9.0, h: 0.85,
  fontSize: F.title, fontFace: F.face, color: C.primary, bold: true,
});
addDivider(s4, 1.05);

const attackData = [
  ["方法", "会议", "类型", "ASR", "时间", "修改参数"],
  ["EvilEdit", "MM'24", "Training-free", "100%", "1秒", "2.2%"],
  ["BadDiffusion", "CVPR'23", "Training-based", "~100%", "数小时", "100%"],
  ["TrojDiff", "CVPR'23", "Training-based", "99.3%", "数小时", "100%"],
  ["RickRolling", "ICCV'23", "Text encoder", "98.4%", "100秒", "Text enc."],
  ["VillanDiffusion", "NeurIPS'23", "Unified", "~100%", "数小时", "100%"],
];

s4.addTable(attackData, {
  x: M, y: 1.2, w: 9.0,
  fontSize: 14, fontFace: F.face,
  border: { pt: 0.5, color: C.rule },
  colW: [1.8, 1.0, 1.5, 0.8, 1.0, 1.2],
  rowH: [0.4, 0.38, 0.38, 0.38, 0.38, 0.38],
  autoPage: false,
  headerRow: true,
  color: C.body,
  headerRowColor: "FFFFFF",
  headerRowBackColor: C.accent,
});

s4.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: M, y: 4.1, w: 9.0, h: 0.8,
  fill: { color: C.highlight }, line: { color: "E6C800", pt: 1 }, rectRadius: 0.06,
});
s4.addText("关键洞察：Training-free (EvilEdit) 仅改 2.2% 参数 → 合并可能稀释；Training-based 改全部参数 → 可能更持久", {
  x: 0.7, y: 4.15, w: 8.6, h: 0.7,
  fontSize: 15, fontFace: F.face, color: "7A5200", bold: false,
});

addCitation(s4, "Chou et al. CVPR'23; Chen et al. CVPR'23; Wang et al. MM'24; Struppek et al. ICCV'23; Chou et al. NeurIPS'23");

// ============================================================
// SLIDE 5: Related Work - Merging Backdoor Gap
// ============================================================
let s5 = pres.addSlide();

s5.addText("模型合并后门在 CV/NLP 已被研究，但扩散模型领域完全空白", {
  x: M, y: 0.2, w: 9.0, h: 0.85,
  fontSize: F.title, fontFace: F.face, color: C.primary, bold: true,
});
addDivider(s5, 1.05);

const gapData = [
  ["领域", "攻击", "防御", "状态"],
  ["CV 分类器", "BadMerging (CCS'24)\nASR 98%+", "LFPM (ICML'26)\nASR→0.49%", "攻防兼备"],
  ["LLM", "Merge Hijacking (ACL'25)\nASR 100%", "Fine-pruning\n(无效)", "攻强防弱"],
  ["扩散模型", "???", "???", "完全空白"],
];

s5.addTable(gapData, {
  x: M, y: 1.2, w: 9.0,
  fontSize: 14, fontFace: F.face,
  border: { pt: 0.5, color: C.rule },
  colW: [1.5, 2.8, 2.5, 1.5],
  rowH: [0.4, 0.65, 0.65, 0.55],
  autoPage: false,
  headerRow: true,
  color: C.body,
  headerRowColor: "FFFFFF",
  headerRowBackColor: C.accent,
});

s5.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: 1.5, y: 3.6, w: 7.0, h: 0.9,
  fill: { color: "FDEDEC" }, line: { color: C.red, pt: 1.5 }, rectRadius: 0.08,
});
s5.addText("研究空白：没有任何论文研究扩散模型后门在 LERP/SLERP/DARE/TIES 合并中的持久性", {
  x: 1.8, y: 3.7, w: 6.4, h: 0.7,
  fontSize: 17, fontFace: F.face, color: C.red, bold: true, align: "center", valign: "middle",
});

addCitation(s5, "Zhang et al. CCS'24; Yuan et al. ACL'25; Zhu et al. ICML'26");

// ============================================================
// SLIDE 6: Section Divider - Our Approach
// ============================================================
let s6 = pres.addSlide();
s6.background = { color: C.darkBg };

s6.addText("Our Approach", {
  x: M, y: 1.6, w: 9.0, h: 0.4,
  fontSize: 16, fontFace: F.face, color: "7BAFD4", bold: false, align: "left",
});
s6.addText("研究方法与可能方向", {
  x: M, y: 2.0, w: 9.0, h: 1.0,
  fontSize: 36, fontFace: F.face, color: "FFFFFF", bold: true, align: "left",
});
s6.addShape(pres.shapes.RECTANGLE, {
  x: M, y: 3.1, w: 2.5, h: 0.06, fill: { color: C.accent },
});

// ============================================================
// SLIDE 7: Phase 1 - Empirical Study
// ============================================================
let s7 = pres.addSlide();

s7.addText("Phase 1（确定）：系统性实证——5种攻击 × 5种合并算法 × 多合并比例", {
  x: M, y: 0.2, w: 9.0, h: 0.85,
  fontSize: F.title, fontFace: F.face, color: C.primary, bold: true,
});
addDivider(s7, 1.05);

s7.addText("实验矩阵", {
  x: M, y: 1.15, w: 4.5, h: 0.35,
  fontSize: F.section, fontFace: F.face, color: C.accent, bold: true,
});

s7.addText([
  { text: "攻击方法: ", options: { bold: true, breakLine: false } },
  { text: "BadDiffusion, TrojDiff, EvilEdit, VillanDiffusion, RickRolling", options: { breakLine: true } },
  { text: "合并算法: ", options: { bold: true, breakLine: false } },
  { text: "LERP, SLERP, DARE, TIES, Task Arithmetic", options: { breakLine: true } },
  { text: "合并比例: ", options: { bold: true, breakLine: false } },
  { text: "α ∈ {0.1, 0.2, 0.3, 0.5, 0.7, 0.9}", options: { breakLine: true } },
  { text: "迭代合并: ", options: { bold: true, breakLine: false } },
  { text: "A+B→C, C+D→E（模拟社区传播链）", options: { breakLine: true } },
], {
  x: M, y: 1.55, w: 4.5, h: 2.8,
  fontSize: F.body, fontFace: F.face, color: C.body, bullet: true, paraSpaceAfter: 10,
});

s7.addText("评估指标", {
  x: 5.3, y: 1.15, w: 4.2, h: 0.35,
  fontSize: F.section, fontFace: F.face, color: C.accent, bold: true,
});

s7.addText([
  { text: "ASR: ", options: { bold: true, breakLine: false } },
  { text: "后门攻击成功率", options: { breakLine: true } },
  { text: "FID: ", options: { bold: true, breakLine: false } },
  { text: "生成质量（越低越好）", options: { breakLine: true } },
  { text: "CLIP Score: ", options: { bold: true, breakLine: false } },
  { text: "文本-图像一致性", options: { breakLine: true } },
  { text: "LPIPS / SSIM: ", options: { bold: true, breakLine: false } },
  { text: "后门目标相似度", options: { breakLine: true } },
], {
  x: 5.3, y: 1.55, w: 4.2, h: 2.8,
  fontSize: F.body, fontFace: F.face, color: C.body, bullet: true, paraSpaceAfter: 10,
});

s7.addText("总计: 5 × 5 × 6 = 150+ 实验组合（合并操作秒级，主要成本在评估生成）", {
  x: M, y: 4.6, w: 9.0, h: 0.4,
  fontSize: F.label, fontFace: F.face, color: C.muted,
});

// ============================================================
// SLIDE 8: Direction A - Defense
// ============================================================
let s8 = pres.addSlide();

s8.addText("方向 A：若后门存活合并 → 提出安全合并防御策略", {
  x: M, y: 0.2, w: 9.0, h: 0.85,
  fontSize: F.title, fontFace: F.face, color: C.primary, bold: true,
});
addDivider(s8, 1.05);

s8.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: M, y: 1.15, w: 4.3, h: 0.5,
  fill: { color: "FDEDEC" }, line: { color: C.red, pt: 1 }, rectRadius: 0.06,
});
s8.addText("触发条件：ASR 合并后仍 > 80%", {
  x: 0.6, y: 1.18, w: 4.1, h: 0.45,
  fontSize: 15, fontFace: F.face, color: C.red, bold: true, align: "center", valign: "middle",
});

s8.addText([
  { text: "核心思路: ", options: { bold: true, breakLine: false } },
  { text: "威胁已成立 → 防御更紧迫、审稿人更认可", options: { breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "可能的防御方案:", options: { bold: true, breakLine: true } },
  { text: "1. 安全合并比例推荐（基于 ASR 衰减曲线的临界阈值）", options: { breakLine: true } },
  { text: "2. 合并前后门扫描（特征空间异常检测）", options: { breakLine: true } },
  { text: "3. 对抗性合并策略（借鉴 LFPM 的特征子空间分离）", options: { breakLine: true } },
  { text: "4. 合并后清洗（轻量级 fine-tuning 消除后门）", options: { breakLine: true } },
], {
  x: M, y: 1.75, w: 5.5, h: 3.0,
  fontSize: F.body, fontFace: F.face, color: C.body, paraSpaceAfter: 6,
});

s8.addText("对标", {
  x: 6.2, y: 1.75, w: 3.3, h: 0.35,
  fontSize: F.section, fontFace: F.face, color: C.accent, bold: true,
});
s8.addText([
  { text: "LFPM (ICML'26): ", options: { bold: true, breakLine: false } },
  { text: "CV 分类器合并防御", options: { breakLine: true } },
  { text: "ASR: 98.42% → 0.49%", options: { breakLine: true } },
  { text: "CA 保持: 58.67%", options: { breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "我们的目标:", options: { bold: true, breakLine: true } },
  { text: "扩散模型版 LFPM", options: { breakLine: true } },
  { text: "ASR < 5%, FID 退化 < 10%", options: { breakLine: true } },
], {
  x: 6.2, y: 2.15, w: 3.3, h: 2.5,
  fontSize: F.label, fontFace: F.face, color: C.body, paraSpaceAfter: 6,
});

addCitation(s8, "Zhu et al. ICML'26 — LFPM: From Parameters to Feature Space");

// ============================================================
// SLIDE 9: Direction B - Attack
// ============================================================
let s9 = pres.addSlide();

s9.addText("方向 B：若后门合并后失效 → 设计合并鲁棒的新攻击", {
  x: M, y: 0.2, w: 9.0, h: 0.85,
  fontSize: F.title, fontFace: F.face, color: C.primary, bold: true,
});
addDivider(s9, 1.05);

s9.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: M, y: 1.15, w: 4.3, h: 0.5,
  fill: { color: "FFF2CC" }, line: { color: C.orange, pt: 1 }, rectRadius: 0.06,
});
s9.addText("触发条件：ASR 合并后 < 20%", {
  x: 0.6, y: 1.18, w: 4.1, h: 0.45,
  fontSize: 15, fontFace: F.face, color: C.orange, bold: true, align: "center", valign: "middle",
});

s9.addText([
  { text: "核心思路: ", options: { bold: true, breakLine: false } },
  { text: "当前攻击不够强 → 合并鲁棒攻击更有价值", options: { breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "借鉴 BadMerging 的技术:", options: { bold: true, breakLine: true } },
  { text: "1. Feature-Interpolation (FI) Loss 覆盖整个合并插值路径", options: { breakLine: true } },
  { text: "2. Rescaling 放大后门 vector（参考 Merge Hijacking λ=2.0）", options: { breakLine: true } },
  { text: "3. 适配 EvilEdit 的 closed-form 编辑 + FI 约束", options: { breakLine: true } },
  { text: "4. 利用 task vector 正交性保证任务性能不退化", options: { breakLine: true } },
], {
  x: M, y: 1.75, w: 5.5, h: 3.0,
  fontSize: F.body, fontFace: F.face, color: C.body, paraSpaceAfter: 6,
});

s9.addText("对标", {
  x: 6.2, y: 1.75, w: 3.3, h: 0.35,
  fontSize: F.section, fontFace: F.face, color: C.accent, bold: true,
});
s9.addText([
  { text: "BadMerging (CCS'24): ", options: { bold: true, breakLine: false } },
  { text: "CV 分类器合并攻击", options: { breakLine: true } },
  { text: "On-task ASR: 98.14%", options: { breakLine: true } },
  { text: "Off-task ASR: 96.28%", options: { breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "我们的目标:", options: { bold: true, breakLine: true } },
  { text: "扩散模型版 BadMerging", options: { breakLine: true } },
  { text: "合并后 ASR > 90%", options: { breakLine: true } },
  { text: "FID 退化 < 5%", options: { breakLine: true } },
], {
  x: 6.2, y: 2.15, w: 3.3, h: 2.5,
  fontSize: F.label, fontFace: F.face, color: C.body, paraSpaceAfter: 6,
});

addCitation(s9, "Zhang et al. CCS'24 — BadMerging; Yuan et al. ACL'25 — Merge Hijacking");

// ============================================================
// SLIDE 10: Direction C - Pure Empirical
// ============================================================
let s10 = pres.addSlide();

s10.addText("方向 C：纯实证基准 + 社区安全合并指南", {
  x: M, y: 0.2, w: 9.0, h: 0.85,
  fontSize: F.title, fontFace: F.face, color: C.primary, bold: true,
});
addDivider(s10, 1.05);

s10.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: M, y: 1.15, w: 4.3, h: 0.5,
  fill: { color: "E8F8F5" }, line: { color: C.green, pt: 1 }, rectRadius: 0.06,
});
s10.addText("触发条件：结果混合（某些攻击活、某些死）", {
  x: 0.6, y: 1.18, w: 4.1, h: 0.45,
  fontSize: 15, fontFace: F.face, color: C.green, bold: true, align: "center", valign: "middle",
});

s10.addText([
  { text: "核心产出:", options: { bold: true, breakLine: true } },
  { text: "1. 全面的 ASR 衰减矩阵（5攻击 × 5算法 × 6比例）", options: { breakLine: true } },
  { text: "2. 合并算法安全性排名（如 DARE > TIES > SLERP > LERP）", options: { breakLine: true } },
  { text: "3. 攻击类型的合并鲁棒性分类", options: { breakLine: true } },
  { text: "4. 安全合并比例阈值建议", options: { breakLine: true } },
  { text: "5. 迭代合并的累积稀释效应分析", options: { breakLine: true } },
  { text: "6. 开源安全合并工具/插件", options: { breakLine: true } },
], {
  x: M, y: 1.75, w: 5.5, h: 3.0,
  fontSize: F.body, fontFace: F.face, color: C.body, paraSpaceAfter: 6,
});

s10.addText("优势与风险", {
  x: 6.2, y: 1.75, w: 3.3, h: 0.35,
  fontSize: F.section, fontFace: F.face, color: C.accent, bold: true,
});
s10.addText([
  { text: "优势:", options: { bold: true, breakLine: true } },
  { text: "• 难度最低（纯实验）", options: { breakLine: true } },
  { text: "• 高实践价值", options: { breakLine: true } },
  { text: "• 可直接服务社区", options: { breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "风险:", options: { bold: true, breakLine: true } },
  { text: "• 天花板较低", options: { breakLine: true } },
  { text: "• 缺乏技术贡献", options: { breakLine: true } },
  { text: "• 适合 Workshop/D&B", options: { breakLine: true } },
], {
  x: 6.2, y: 2.15, w: 3.3, h: 2.5,
  fontSize: F.label, fontFace: F.face, color: C.body, paraSpaceAfter: 4,
});

addCitation(s10, "对标: BackdoorDM (NeurIPS'25 D&B Track)");

// ============================================================
// SLIDE 11: Direction Comparison
// ============================================================
let s11 = pres.addSlide();

s11.addText("三个方向的选择取决于 Phase 1 实验结果——1-2 天即可判定", {
  x: M, y: 0.2, w: 9.0, h: 0.85,
  fontSize: F.title, fontFace: F.face, color: C.primary, bold: true,
});
addDivider(s11, 1.05);

const compData = [
  ["维度", "A. 防御", "B. 攻击", "C. 纯实证"],
  ["触发条件", "ASR > 80%", "ASR < 20%", "结果混合"],
  ["技术难度", "★★★☆☆", "★★★☆☆", "★☆☆☆☆"],
  ["新颖性", "★★★★☆", "★★★★☆", "★★★☆☆"],
  ["目标会议", "USENIX/NDSS", "CCS/USENIX", "NeurIPS D&B"],
  ["周期", "8-10 周", "8-10 周", "6-8 周"],
  ["实践价值", "高（安全指南）", "高（揭示威胁）", "中（基准）"],
  ["审稿接受度", "最高", "高", "中"],
];

s11.addTable(compData, {
  x: M, y: 1.2, w: 9.0,
  fontSize: 14, fontFace: F.face,
  border: { pt: 0.5, color: C.rule },
  colW: [1.5, 2.5, 2.5, 2.5],
  rowH: [0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4],
  autoPage: false,
  headerRow: true,
  color: C.body,
  headerRowColor: "FFFFFF",
  headerRowBackColor: C.accent,
});

s11.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x: M, y: 4.6, w: 9.0, h: 0.6,
  fill: { color: C.highlight }, line: { color: "E6C800", pt: 1 }, rectRadius: 0.06,
});
s11.addText("建议策略：先跑 Phase 1 快速实验（1-2天），根据 ASR 衰减数据选定后续方向", {
  x: 0.7, y: 4.63, w: 8.6, h: 0.55,
  fontSize: 16, fontFace: F.face, color: "7A5200", bold: true, align: "center", valign: "middle",
});

// ============================================================
// SLIDE 12: Feasibility
// ============================================================
let s12 = pres.addSlide();

s12.addText("3090 (24GB) 完全满足所有实验需求——合并操作本身仅需 CPU 秒级完成", {
  x: M, y: 0.2, w: 9.0, h: 0.85,
  fontSize: F.title, fontFace: F.face, color: C.primary, bold: true,
});
addDivider(s12, 1.05);

const feasData = [
  ["实验环节", "显存需求", "时间", "工具"],
  ["EvilEdit 注入后门", "~5 GB", "1 秒", "github.com/haowang-cqu/EvilEdit"],
  ["BadDiffusion 训练后门", "~10-14 GB", "数小时", "github.com/IBM/BadDiffusion"],
  ["LERP/SLERP 合并", "CPU only", "秒级", "sd-meh / supermerger"],
  ["DARE/TIES 合并", "CPU only", "秒级", "mergekit"],
  ["生成评估 (FID/CLIP)", "~5 GB", "分钟级", "torch-fidelity / open_clip"],
];

s12.addTable(feasData, {
  x: M, y: 1.2, w: 9.0,
  fontSize: 13, fontFace: F.face,
  border: { pt: 0.5, color: C.rule },
  colW: [2.0, 1.3, 1.0, 4.0],
  rowH: [0.4, 0.38, 0.38, 0.38, 0.38, 0.38],
  autoPage: false,
  headerRow: true,
  color: C.body,
  headerRowColor: "FFFFFF",
  headerRowBackColor: C.accent,
});

s12.addText([
  { text: "Quick Win: ", options: { bold: true, breakLine: false } },
  { text: "EvilEdit (1秒注入) + LERP 合并 (秒级) + 生成评估 → 1 天内可获得第一组 ASR 衰减数据", options: { breakLine: true } },
  { text: "开源工具: ", options: { bold: true, breakLine: false } },
  { text: "11/15 相关论文已开源代码，无需从零实现", options: { breakLine: true } },
], {
  x: M, y: 3.7, w: 9.0, h: 1.2,
  fontSize: F.body, fontFace: F.face, color: C.body, bullet: true, paraSpaceAfter: 10,
});

// ============================================================
// SLIDE 13: Expected Contributions
// ============================================================
let s13 = pres.addSlide();

s13.addText("预期贡献：首个扩散模型合并后门安全性研究，填补明确的研究空白", {
  x: M, y: 0.2, w: 9.0, h: 0.85,
  fontSize: F.title, fontFace: F.face, color: C.primary, bold: true,
});
addDivider(s13, 1.05);

s13.addText([
  { text: "1. 首个系统性实证: ", options: { bold: true, breakLine: false } },
  { text: "5种后门攻击 × 5种合并算法的完整 ASR 衰减矩阵，揭示扩散模型特有的合并-后门交互规律", options: { breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "2. 反直觉发现（预期）: ", options: { bold: true, breakLine: false } },
  { text: "如 SLERP 可能比 LERP 保留更高 ASR；DARE 的稀疏化可能意外保护后门关键参数", options: { breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "3. 技术贡献（取决于方向）: ", options: { bold: true, breakLine: false } },
  { text: "安全合并防御 / 合并鲁棒攻击 / 安全合并工具", options: { breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "4. 实践价值: ", options: { bold: true, breakLine: false } },
  { text: "直接服务 CivitAI/HuggingFace 社区，可发布为开源安全审计插件", options: { breakLine: true } },
  { text: "", options: { breakLine: true } },
  { text: "5. 开源基准: ", options: { bold: true, breakLine: false } },
  { text: "发布全部实验代码、后门检查点和评估脚本，支持后续研究", options: { breakLine: true } },
], {
  x: M, y: 1.15, w: 9.0, h: 3.8,
  fontSize: F.body, fontFace: F.face, color: C.body, paraSpaceAfter: 4,
});

// ============================================================
// SLIDE 14: Conclusions
// ============================================================
let s14 = pres.addSlide();
s14.background = { color: C.primary };

s14.addText("Conclusions & Next Steps", {
  x: M, y: 0.25, w: 9.0, h: 0.45,
  fontSize: 20, fontFace: F.face, color: "A0BBDD", bold: false, align: "left",
});
s14.addShape(pres.shapes.RECTANGLE, {
  x: M, y: 0.7, w: 9.0, h: 0.04, fill: { color: C.accent },
});

s14.addText([
  { text: "1. 研究空白明确: ", options: { bold: true, breakLine: false } },
  { text: "扩散模型后门 × 检查点合并 = 零已有工作，CV/NLP 领域已有成熟对标（BadMerging, Merge Hijacking, LFPM）", options: { breakLine: true, breakLine: true } },
  { text: "2. 方法路线清晰: ", options: { bold: true, breakLine: false } },
  { text: "Phase 1 系统性实证（确定） → Phase 2 根据结果选择防御/攻击/纯实证方向", options: { breakLine: true, breakLine: true } },
  { text: "3. 可行性已验证: ", options: { bold: true, breakLine: false } },
  { text: "3090 足够，11 个开源代码库可用，1-2 天出初步结果", options: { breakLine: true, breakLine: true } },
  { text: "4. 时间线: ", options: { bold: true, breakLine: false } },
  { text: "6-8 周完成全部实验和论文写作，目标 USENIX Security / NDSS / CCS", options: { breakLine: true } },
], {
  x: M, y: 0.85, w: 9.0, h: 3.5,
  fontSize: 19, fontFace: F.face, color: "FFFFFF", paraSpaceAfter: 16,
});

s14.addText("Next Step: 本周内完成 EvilEdit + LERP/SLERP 的初步 ASR 衰减实验 → 确定论文方向", {
  x: M, y: 4.5, w: 9.0, h: 0.5,
  fontSize: 16, fontFace: F.face, color: "A0BBDD", bold: true, align: "left",
});

// ============================================================
// SLIDE 15: References
// ============================================================
let s15 = pres.addSlide();

s15.addText("References", {
  x: M, y: 0.2, w: 9.0, h: 0.5,
  fontSize: 24, fontFace: F.face, color: C.primary, bold: true,
});
s15.addShape(pres.shapes.RECTANGLE, {
  x: M, y: 0.72, w: 9.0, h: 0.025, fill: { color: C.rule },
});

const refs = [
  "[1] Zhang et al. BadMerging: Backdoor Attacks Against Model Merging. CCS 2024.",
  "[2] Yuan et al. Merge Hijacking: Backdoor Attacks to Model Merging of LLMs. ACL 2025.",
  "[3] Zhu et al. LFPM: From Parameters to Feature Space. ICML 2026.",
  "[4] Lin et al. BackdoorDM: Comprehensive Benchmark. arXiv 2025.",
  "[5] Chou et al. BadDiffusion: How to Backdoor Diffusion Models? CVPR 2023.",
  "[6] Chen et al. TrojDiff: Trojan Attacks on Diffusion Models. CVPR 2023.",
  "[7] Wang et al. EvilEdit: Backdooring T2I in One Second. ACM MM 2024.",
  "[8] Chou et al. VillanDiffusion: Unified Backdoor Attack Framework. NeurIPS 2023.",
  "[9] Struppek et al. Rickrolling the Artist: Injecting Backdoors into Text Encoders. ICCV 2023.",
];

const refItems = refs.flatMap((r, i) => [
  { text: r, options: { breakLine: true } },
  ...(i < refs.length - 1 ? [{ text: "", options: { breakLine: true } }] : []),
]);

s15.addText(refItems, {
  x: M, y: 0.85, w: 9.0, h: 4.5,
  fontSize: 12, fontFace: F.face, color: C.body, paraSpaceAfter: 2,
});

// ============================================================
// SAVE
// ============================================================
const outPath = "/Users/zzb/arxiv/presentations/diffusion_merging_backdoor_research.pptx";
pres.writeFile({ fileName: outPath }).then(() => {
  console.log("PPTX saved to: " + outPath);
}).catch(err => {
  console.error("Error:", err);
});
