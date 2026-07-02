# LOOP.md — BackdoorDM 复现循环指令

> **你是循环执行者。每次迭代读完此文件后执行一轮，然后重新开始，never stop。**
> 项目指令见 `AGENTS.md`。进度见 `backdoordm_progress.md`。基准数据见 `reports/03-reproduction-results/backdoordm_reference.md`（只读，勿改）。

## GPU 利用率最大化（每个脚本启动前必做）

每个训练/评估脚本启动前，先创建临时测试脚本到 `/temp_script/` 目录，测试 GPU 显存和利用率：

1. **创建临时脚本**：复制原脚本到 `/temp_script/test_<task>.py`，修改为仅跑 1-2 步
2. **逐步调大 batch_size**：从默认值开始，逐步增大 `batch_size`（或其他影响速度的参数如 `eval_max_batch`），观察 `nvidia-smi` 的 `memory.used` 和 `utilization.gpu`
3. **只调速度参数**：仅调整 `batch_size`、`eval_max_batch`、`num_workers` 等不影响实验结果的参数。**禁止修改** `poison_rate`、`clean_rate`、`trigger`、`target`、`epoch`、`learning_rate` 等实验配置
4. **目标**：GPU 显存利用率 ≥80%（如 24GB GPU 用到 ≥19GB），GPU 计算利用率 ≥90%
5. **确定最佳参数后**：用优化后的参数启动正式脚本，删除临时测试脚本

示例：
```bash
# 测试 batch_size=8 是否 OOM
/temp_script/test_eval.sh  # 仅跑几步，观察 nvidia-smi
# 不 OOM → 正式脚本用 batch_size=8
# OOM → 降到 batch_size=4 重测
```

## 服务器

`ssh amax -p 25579` | BD=/opt/data/private/BackdoorDM | Python=/opt/data/private/miniconda3/envs/eviledit/bin/python

## 每次迭代流程

1. **检查服务器状态**：`ssh amax -p 25579 "pgrep -af 'python.*attack\|python.*main_eval\|python.*defense'; nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader"`
   - 无任务在运行 → 正常执行步骤 2-6
   - 有任务在运行 → 检查 GPU 显存剩余和利用率：
     - 显存剩余充足（>8GB）且利用率有空闲 → 可以并行启动**同阶段的另一个任务**（如同为训练阶段的另一个攻击，或同为评估阶段的另一个指标），跳到步骤 2 选下一个未完成任务
     - 显存不足或利用率已满 → 记录 work_log "skipped: task in progress, GPU busy"，结束本轮，等待下次 loop 触发
2. 读 `backdoordm_progress.md`，确定当前最优先未完成任务
3. 执行该任务（见下方各 Phase 指令）
4. 任务完成后更新 `backdoordm_progress.md`
5. 记录日志到服务器 `logs/work_log.md`
6. 回到步骤 1

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

评估完成后读取结果：
```bash
# T2I 方法
cat results/<method>_sd15/eval_results.csv | grep -v datatime | tail -5
# 无条件方法
cat results/<method>_DDPM-CIFAR10-32/eval_results.csv | grep -v datatime | tail -5
# 训练日志（BackdoorDM 自动生成）
ls results/<method>_sd15/train_logs/
# 评估日志（BackdoorDM 自动生成）
ls results/<method>_sd15/eval_logs/
```

从 CSV 中提取指标值（score 列），对照 reference 基准值表，计算偏差。

## Phase 3: 运行防御

有官方脚本：
```bash
bash scripts/run_defend_t2ishield.sh   # T2I 攻击
bash scripts/run_defend_elijah.sh      # 无条件攻击
```

无官方脚本（TERD, Textual Perturbation, DAA），手动启动（命令见 reference "官方脚本覆盖情况"）。

## Phase 4: 收集防御结果

读取各防御输出：
```bash
# T2IShield / DAA 结果 CSV
cat results/<method>_sd15/defense/t2ishield/detection_results.csv 2>/dev/null
cat results/<method>_sd15/defense/daa/detection_results.csv 2>/dev/null
# 防御日志（BackdoorDM 自动生成，含 P/R/F1/ASR 等详细输出）
ls results/<method>_sd15/defense/*/defense_logs/
# Textual Perturbation: 读日志中 "Defended ASR" 行
# Elijah / TERD: 读日志中 tvloss / uniformity / TPR / TNR 行
grep -r 'Defended ASR\|F1 Score\|AUC\|TPR\|TNR\|tvloss\|uniformity' results/<method>_sd15/defense/*/defense_logs/ 2>/dev/null
```

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
- Duration: <耗时>
- Error: <如有>
EOF"
```

BackdoorDM 也会自动生成详细日志（train_logs/eval_logs/defense_logs），work_log 仅记录 loop 决策。

## 异常处理

- SSH 断连 → 按 AGENTS.md "SSH 连接恢复"操作
- 训练失败 → 读 progress "未训练原因"，尝试修复后重跑
- 评估失败 → 检查模型路径 `evaluation/configs/bdmodel_path.py` 是否匹配
- GPU 被占 → `nvidia-smi` 检查，kill 非本任务进程
- 全部完成 → 从头检查遗漏，确保 16 攻击 × 全指标 + 5 防御全部 ✅
