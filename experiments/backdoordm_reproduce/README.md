# BackdoorDM 全量复现实验

> 服务器上 `/opt/data/private/BackdoorDM/` 的实验脚本本地副本  
> 服务器: AMAX <port> (ssh amax -p <port>)  
> Conda 环境: `eviledit`  
> 最后更新: 2026-06-30

---

## 📚 目录结构

```
experiments/backdoordm_reproduce/
├── README.md                  # 本索引
├── scripts/                   # 44 个实验脚本（详见下方）
├── configs/                   # [占位] 配置文件副本 → 详见 configs/README.md
└── logs/                      # [占位] 日志副本 → 详见 logs/README.md
```

## ⚠️ 重要说明

**本目录仅是本地脚本副本** — 真正的实验在服务器上运行。

| 本地 (本目录) | 服务器 (`/opt/data/private/BackdoorDM/`) |
|--------------|----------------------------------------|
| 脚本开发、git 跟踪、版本控制 | 实际训练、评估、防御执行 |
| `scripts/*.sh` (44 个) | 相同脚本 + 临时脚本 |
| `configs/` (空) | 实际配置文件 |
| `logs/` (空) | 实时日志 (GB 级) |
| 无结果文件 | `results/` (训练模型 + 评估结果) |

## 🚀 主控脚本（按此顺序执行）

| 脚本 | 用途 | 何时使用 |
|------|------|----------|
| `run_all_resilient.sh` | **断点续传版**全量复现主控 | 首选，自动跳过已完成步骤 |
| `run_all.sh` | 原始版主控（不推荐） | 仅参考，已被 `run_all_resilient.sh` 取代 |
| `master_reconnect.sh` | SSH 重连后的一键执行主脚本 | 网络中断恢复后 |

## 🔧 分阶段脚本（按编号顺序）

### 阶段 0：环境准备

| 脚本 | 用途 |
|------|------|
| `00_check_env.sh` | GPU / Python / 依赖检查 |
| `00_reconnect_and_verify.sh` | 服务器重连后的环境验证和修复 |
| `01_install_deps.sh` | 安装 BackdoorDM 所有依赖 |
| `01b_patch_configs.sh` | 修补 BackdoorDM 配置文件 |
| `01c_apply_paper_fixes.sh` | 根据论文交叉验证结果修复 BackdoorDM 代码 |

### 阶段 1：模型下载

| 脚本 | 用途 |
|------|------|
| `02_download_models.sh` | 下载所有需要的模型和数据集 |
| `02b_download_clip_large.sh` | 下载 CLIP-ViT-Large-Patch14（评估 CLIP_p/CLIP_c 必需） |
| `02c_fix_eval_config.sh` | 修复评估配置：clip_model 改为本地路径 |
| `02d_first_eval_eviledit.sh` | 首次评估 EvilEdit ACCASR（不依赖 CLIP，可先跑） |

### 阶段 2：攻击复现

| 脚本 | 用途 | 预计耗时 |
|------|------|----------|
| `03_attack_t2i_fast.sh` | 快速 T2I 攻击（EvilEdit, RickRolling, PaaS） | < 30 分钟 |
| `04_attack_t2i_slow.sh` | 慢速 T2I 攻击（BadT2I 系列） | > 6 小时 |
| `05_attack_uncond.sh` | 无条件攻击（BadDiffusion, TrojDiff, VillanDiff） | 较快 |
| `05b_attack_villan_cond.sh` | VillanDiffusion Conditional (ImageFix) | ~20-30h |
| `05c_attack_bibaddiff.sh` | BiBadDiff 攻击 | ~12-24h |

### 阶段 3：评估

| 脚本 | 用途 | 指标 |
|------|------|------|
| `06_eval_t2i.sh` | T2I 攻击方法评估 | ACCASR, CLIP_p, CLIP_c, FID, LPIPS |
| `07_eval_uncond.sh` | 无条件攻击评估 | FID, MSE |

### 阶段 4：防御

| 脚本 | 用途 | 适用方法 |
|------|------|----------|
| `08_defense_t2ishield.sh` | T2IShield 防御（model-level） | T2I methods |
| `09_defense_elijah_terd.sh` | Elijah + TERD 防御（model-level） | unconditional methods |
| `10_defense_input_level.sh` | 输入级防御 | Textual Perturbation + DAA |

### 阶段 5：独立实验（论文中重要但代码未体现的实验）

| 脚本 | 实验内容 | 对应论文 |
|------|----------|----------|
| `11_independent_eviledit_lambda.sh` | EvilEdit λ 消融 {0.1, 0.5, 1, 2, 5} | EvilEdit |
| `12_independent_baddiffusion_poison_rate.sh` | BadDiffusion 多 poison rate {0.05, 0.1, 0.2, 0.5} | BadDiffusion |
| `19_independent_eviledit_whitelist_vta.sh` | EvilEdit Whitelist 保护 + VTA | EvilEdit |

### 阶段 6：最终输出

| 脚本 | 用途 |
|------|------|
| `24_generate_final_report.sh` | 从服务器提取所有实验结果并生成最终报告 |
| `28_extract_all_metrics.sh` | 提取所有评估指标 |
| `collect_results.sh` | 收集所有实验结果到一个汇总文件 |
| `parse_results.sh` | 从 BackdoorDM 日志和 eval_results.csv 中解析结果 |

## 🔨 临时修复/恢复脚本（历史）

> ⚠️ 以下脚本是**一次性使用**的修复脚本，已在服务器上执行过。保留仅供参考，不应重复执行。

| 脚本 | 已解决的问题 |
|------|-------------|
| `13_fix_nltk_and_verify.sh` | 修复 NLTK 数据 + 验证 textattack + huggingface_hub 降级 |
| `14_launch_full_pipeline.sh` | 一键启动：修复环境 → EvilEdit 评估 → 全量攻防流水线 |
| `15_deploy_and_launch.sh` | 本地执行：一键部署 + 启动全量复现 |
| `16_apply_server_fixes.sh` | 应用所有代码修复 + 创建 fallback 数据集 + 重置 checkpoint |
| `17_deploy_fixes_and_relaunch.sh` | 上传修复脚本 + 应用所有修复 + 重新启动流水线 |
| `18_retrain_taa_fixed.sh` | 修复 Rickrolling TAA milestones 后重新训练 |
| `20_quick_status_check.sh` | SSH 恢复后的快速状态检查 |
| `21_fix_textperturb_mse.sh` | 修复 Textual Perturbation max_mse_dist: 0.2 → 0.05 |
| `22_check_paas_db_steps.sh` | 检查 PaaS DB max_train_steps 值 |
| `23_full_recovery_check.sh` | SSH 恢复后综合诊断 + 修复脚本 |
| `25_fix_badt2i_images.sh` | 修复 BadT2I pixel/object/objectAdd 失败 |
| `26_rerun_badt2i_failed.sh` | 修复后重跑 BadT2I pixel 和 object |
| `27_post_pipeline_completion.sh` | 流水线完成后：修复剩余问题并填充空白 |
| `29_deploy_when_ssh_recovers.sh` | SSH 恢复后的一键部署脚本 |
| `30_fix_uncond_attacks.sh` | 修复无条件攻击的关键 bug |

## 🔄 典型工作流

### 完整流程（首次运行）

```bash
# 在服务器上执行
cd /opt/data/private/BackdoorDM
nohup bash run_all_resilient.sh > logs/run_all.log 2>&1 &
```

### 中断后恢复

```bash
# SSH 恢复后
bash scripts/master_reconnect.sh
# 或
bash scripts/20_quick_status_check.sh
# 然后重新运行主控脚本（自动跳过已完成步骤）
nohup bash run_all_resilient.sh >> logs/run_all.log 2>&1 &
```

### 本地 → 服务器同步

```bash
# 从本地上传脚本到服务器
scp -P <port> scripts/*.sh amax:/opt/data/private/BackdoorDM/scripts/
```

## 📊 当前状态（2026-06-30）

| 类别 | 完成度 | 说明 |
|------|--------|------|
| 攻击 | 9/13 可用 | 4 个失败待修复 (InviBackdoor, VillanDiff cond, BiBadDiff, BadT2I ObjectAdd) |
| BadT2I 系列 | 数据已清理 | Pixel/Object/Style 因数据质量问题已删除模型，待重训 |
| 评估 | 2/13 | 仅 EvilEdit + RickRolling TPA |
| 防御 | 0/5 | 未启动 |
| 最终报告 | 未生成 | 模板在 `backdoordm_final_report.md` |

## 🔗 相关资源

- **交接文档**: `/Users/zzb/Desktop/handoff/arxiv/2026-06-30-backdoordm-badt2i-retrain.md`
- **论文索引**: `../../papers/README.md`
- **报告索引**: `../../reports/README.md`
- **对抗审查报告**: 服务器 `/opt/data/private/adversarial_censorship_reports/`
