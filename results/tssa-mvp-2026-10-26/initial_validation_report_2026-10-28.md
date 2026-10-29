# TSSA v2-gradient 初步验证最终报告

**本轮完整执行已结束，结果为负面：RC-TSSA-GD 没有保留后门攻击收益。** Uniform 与 RC 选中相同的零差分端点 (a,b)=(0,0)，四个持出状态 ASR 均为0/16；naive 仍有攻击成功，TSSA 没有通过开发门槛的候选。

2026-10-28 13:33:06（Asia/Shanghai）完成报告，14:02:28只读复核原PID650925已退出、GPU3仅剩已核验系统显示进程，本项目显存已释放；未追加训练或扩展实验预算。

## 冻结协议与执行

本轮按2026-10-26冻结协议运行源模型门禁、合法DDIM轨迹、静态筛查、三族各48步优化、开发选择和独立持出；仅优化标量a/b，原始差分、分组、β、正常约束、提示、种子和门槛均保持不变。

| 阶段 | 实际完成 | 关键事实 |
|---|---:|---|
| 源模型门禁 | 48图 | 原后门8/8、干净0/8；正常均13/16，CLIP差0.1878 |
| 合法轨迹及teacher | 16条、120组 | 已提交receipt及缓存索引 |
| 静态筛查 | 220图 | 四静态候选未通过图像正常约束，按冻结规则继续梯度优化 |
| 梯度训练 | 144次更新 | Uniform、TSSA、RC各48；3个step00初始化不计更新 |
| 开发选择 | 484图 | Uniform与RC选step24 (0,0)，TSSA缺失 |
| 独立持出 | 768图 | 3个冻结候选加matched_clean，4状态，每状态48图 |
| 总科研图 | 1520图 | 源48+主实验1472，低于1712总上限 |

TSSA缺失使持出由最多960图减为768图，未用失败候选补齐预算；三族训练和所有规定对照池均已执行，不把缺失对照算作胜出。

## 持出结果

每个攻击单元为8个提示×2种子（16张），正常单元为配对和额外正常提示共32张；下面按状态列出成功数与分母，不将跨状态重复提示当作独立样本。

| 状态 | naive ASR | Uniform ASR | RC ASR | clean ASR | naive正常ACC | RC/Uniform/clean正常ACC | 正常CLIP naive / RC与clean |
|---|---:|---:|---:|---:|---:|---:|---:|
| Edev_0.15 | 4/16 | 0/16 | 0/16 | 0/16 | 27/32 | 27/32 | 29.3329 / 28.9827 |
| Ehold_0.25 | 13/16 | 0/16 | 0/16 | 0/16 | 26/32 | 27/32 | 27.7770 / 27.9648 |
| Ehold_0.15 | 3/16 | 0/16 | 0/16 | 0/16 | 26/32 | 25/32 | 27.9511 / 27.2146 |
| upload | 13/16 | 0/16 | 0/16 | 0/16 | 26/32 | 26/32 | 28.3332 / 28.7242 |

naive平均ASR为51.5625%、最差状态18.75%，RC与Uniform均为0%；三种已评方法的持出正常指标都通过原门槛，RC相对Uniform的ASR、ACC与CLIP差均为0。

TSSA未进入持出：学习候选(0,1)在Edev_0.50及upload响应门槛失败，开发upload正常ACC为6/8对clean7/8（下降12.5个百分点，高于5个百分点限额）；静态TSSA16也未通过正常约束，不能替换入场。

## 为什么代理损失下降而攻击消失

完整开发响应中，naive的R=0.0296884361、Jβ=0.0349517092，零点候选R=0.0100089929、Jβ=0.0100248810；代理目标与正常约束允许零差分解通过，但该解在本轮真实生成中没有目标攻击成功。

训练记录和CPU Adam重放一致，当前证据不支持把归零直接归咎于优化器更新错误，也不证明该代理目标的一般无效性；它显示本冻结配置下“较低代理损失”不足以保证后门保留。

零点在三个开发响应状态正常MSE为0，upload仍有1.58875e-5；中期分析发现teacher/student文本编码批大小差异，数值误差原因尚未隔离验证，不据此宣称实现已修复或追加重训。

## 审计与资源

真实SD CUDA诊断已验证a/b有限非零梯度、中心差分比较及冻结参数无梯度；完整训练4513项CPU重放检查、开发选择6930项逐图/门槛/排序/哈希核验均无不一致，最终持出独立审计37334项检查、0不一致，逐图重算、1520条记录与operation载荷哈希绑定及先选择后持出的时间顺序均通过。

主实验82248次branch-NFE、1008次自动微分、144次更新；源门禁2400次branch-NFE，成功诊断138次单列，峰值已分配显存23018152960字节（约21.44GiB）。

训练梯度计算累计2308.956秒；恢复后的单卡进程从10:20:25到13:33:06约3小时13分，已提交操作累计11688.203秒（含不同阶段及先前CPU准备，不能当作纯GPU核时）。

10:11 agent错误停止本人原任务的记录保留：该尝试已知118次诊断branch-NFE，反向成本记录不完整；这部分另列，不能写成零或归咎于科学门禁/OOM，之后恢复同一run identity完成实验。

## 证据与保存位置

- [最终原始报告](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T060221238162Z_artifacts/final_report.json)
- [持出逐图指标](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T060221238162Z_artifacts/heldout_per_image_metrics.jsonl)
- [持出聚合报告](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T060221238162Z_artifacts/heldout_report.json)
- [全部候选及开发指标](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T060221238162Z_artifacts/candidate_selection.json)
- [144步a/b轨迹](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T060221238162Z_artifacts/per_step_coefficients_and_losses.jsonl)
- [完整资源账本](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T060221238162Z_artifacts/resource_ledger.json)
- [最终回传与释放证据](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T060221238162Z.json)
- [完整开发独立审计](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/development_selection_audit_20261028T0601Z.md)
- [最终持出独立审计](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/final_heldout_audit_20261028T0602Z.md)
- [归零中期分析与曲线](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/training_interim_analysis_20261028T0354Z.md)
- [多服务器本轮检查](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/multi_server_observation_20261028T0602Z.json)

已回传并核对33份终态小产物，包含所有阶段逐图指标、完整系数轨迹、候选清单、失败案例、资源账本和4张固定拼图；完整生成图片与模型资产继续保留在本人104数据目录，未把全部大文件复制到空间有限的Mac。

远端运行目录：`/data2/zhangzibo/arxiv-tssa/results/mvp-2026-10-28-single-v1`；源码快照：`/data2/zhangzibo/arxiv-tssa/code/mvp-dual-0a5b9bdc7434`，本轮从该快照运行单卡入口。

固定样图按预登记首个测试提示和首个种子选取，未按攻击成败挑选；下图左列正常、右列触发，行依次为naive、Uniform、RC、matched_clean。

![Ehold_0.25固定样图](/Users/zzb/arxiv/results/tssa-mvp-2026-10-26/single_run_observation_20261028T060221238162Z_artifacts/panels/Ehold_0.25.png)

这只是单个公开攻击、当前固定模型与小样本协议的负结果，不包含正式10K FID、多攻击、防御或统计显著性/SOTA证明；后续若研究目标构造或数值原因，应另立新版本与预算，不能在本轮看过持出后改阈值重训。

## 定时任务收尾

GPU进程已正常退出并释放显存，但删除Codex定时任务`gpu`的工具请求被拒绝：`MCP tool call requires approval, but approval policy is never`；没有通过修改底层配置绕过权限。

本轮已完成，残留唤醒不得重跑实验或重新占卡；自动化本身仍需用户在Codex中手动删除/停用，证据见[清理请求结果](automation_cleanup_20261028.json)。
