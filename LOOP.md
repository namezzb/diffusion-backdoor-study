# LOOP.md — BackdoorDM 复现循环指令

> **你是循环执行者。每次迭代读完此文件后执行一轮，然后重新开始，never stop。**
> 项目指令见 `AGENTS.md`。进度见 `backdoordm_progress.md`。基准数据见 `reports/03-reproduction-results/backdoordm_reference.md`（只读，勿改）。

## 服务器

`ssh amax -p 25579` | BD=/opt/data/private/BackdoorDM | Python=/opt/data/private/miniconda3/envs/eviledit/bin/python

## 每次迭代流程

1. 读 `backdoordm_progress.md`，确定当前最优先未完成任务
2. 执行该任务（见下方各 Phase 指令）
3. 任务完成后更新 `backdoordm_progress.md`
4. 记录日志到服务器 `logs/work_log.md`
5. 回到步骤 1

## 执行顺序

**训练 → 评估攻击指标 → 防御 → 评估防御指标**

前一阶段全部完成后才进入下一阶段。同阶段内按 progress 表格顺序执行。

## Phase 1: 训练未训练攻击

读 progress "未训练原因"表，逐个修复并训练。

有官方脚本：
```bash
cd /opt/data/private/BackdoorDM && bash scripts/run_attack_<type>.sh
```

无官方脚本（invi_backdoor, badt2i_objectAdd, eviledit_numAdd），手动启动（命令见 reference "官方脚本覆盖情况"）。

训练后验证：`find results/<method>_sd15/ -name '*.pt' -o -name '*.safetensors' | head -1`

## Phase 2: 评估攻击指标

对每个已训练方法运行全部适用指标。

有官方脚本：
```bash
bash scripts/run_eval_t2i_<METRIC>.sh   # T2I: ACCASR/CLIP_p/CLIP_c/FID/LPIPS
bash scripts/run_eval_fix_<METRIC>.sh   # 无条件: FID/MSE
```

无脚本或需单独运行：
```bash
/opt/data/private/miniconda3/envs/eviledit/bin/python evaluation/main_eval.py \
    --metric <METRIC> --backdoor_method <METHOD> --device cuda:0
```

无条件方法需额外参数：`--backdoored_model_path ./results/<method>_DDPM-CIFAR10-32 --val_data cifar10`

指标适用表（详见 reference）：
- ObjectRep / ObjectAdd: ACCASR, CLIP_p, CLIP_c, FID, LPIPS
- ImagePatch: MSE, CLIP_p, CLIP_c, FID, LPIPS
- StyleAdd: CLIP_p, CLIP_c, FID, LPIPS
- ImageFix / 无条件: FID, MSE

## Phase 3: 运行防御

有官方脚本：
```bash
bash scripts/run_defend_t2ishield.sh   # T2I 攻击
bash scripts/run_defend_elijah.sh      # 无条件攻击
```

无官方脚本（TERD, Textual Perturbation, DAA），手动启动（命令见 reference "官方脚本覆盖情况"）。

## Phase 4: 收集防御结果

读取各防御输出：
- T2IShield / DAA: 读 `results/<method>_sd15/defense/*/detection_results.csv` 或 `eval_results.csv`
- Textual Perturbation: 读日志中 "Defended ASR" 行
- Elijah / TERD: 读日志中 tvloss / uniformity / TPR / TNR 行

记录到 progress。

## 进度更新规则

- 训练完成 → progress 对应行"训练"和"模型"列改 ✅
- 评估完成 → progress 对应指标列改 ✅，"已完成评估对照"表加行（方法、指标、基准值、复现值、偏差、说明）
- 防御完成 → progress 防御表对应行改 ✅
- 每次更新后 `git add backdoordm_progress.md && git commit -m "progress: <动作>"`

基准值从 reference 的基准值表中查。

## 日志记录

```bash
ssh amax -p 25579 "cat >> /opt/data/private/BackdoorDM/logs/work_log.md << 'EOF'
### $(date '+%Y-%m-%d %H:%M') — Loop
- Action: <训练/评估/防御> <方法> <指标>
- Result: <成功/失败/值>
EOF"
```

## 异常处理

- SSH 断连 → 按 AGENTS.md "SSH 连接恢复"操作
- 训练失败 → 读 progress "未训练原因"，尝试修复后重跑
- 评估失败 → 检查模型路径 `evaluation/configs/bdmodel_path.py` 是否匹配
- GPU 被占 → `nvidia-smi` 检查，kill 非本任务进程
- 全部完成 → 从头检查遗漏，确保 16 攻击 × 全指标 + 5 防御全部 ✅
