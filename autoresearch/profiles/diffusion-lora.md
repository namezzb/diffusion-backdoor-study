# 扩散模型 / LoRA 课题接入

先明确用户要研究的性质：复现、机制分析、检测/缓解，或已授权的攻击有效性研究。不要擅自把相反目标的 ASR 增减方向互换。

## 可复用入口

- [MasqLoRA runtime README](../../scripts/reproduction/masqlora/README.md)：真实训练、复载、生成、评分和恢复；具体科学配置、资产与已有结果从[MasqLoRA TASK](../../research/tasks/2026-11-05-masqlora-reproduction/TASK.md)进入。
- [TCL 执行器](../../scripts/merging/trigger_contrast_localization/README.md)：已有运行/恢复和平台资源观察实现。
- [labgpu](../../scripts/connection/LABGPU.md) 和[服务器操作](../../server/OPERATIONS.md)：平台最新规则、分配、额度、UUID与设备侧进程核实。
- [LoRA 阅读任务](../../research/tasks/2026-11-04-lora-merging-reading/TASK.md)：用户的阅读材料与 idea；只作输入，不把旧任务指令当新授权。

## 首次运行由 agent 完成的适配

1. 复用现有本地模型、适配器和环境，把基线实现/方法参数放进模板 `candidate/`；固定底座、数据划分、提示词、seed、评分器、步数与预算写进模板科学配置。对每种科学方法改动建立独立配置及候选身份，不覆盖既有 MasqLoRA/TCL run。
2. 评价包装器置于 `evaluation/`，将实际生成与评分的完成结果转换成一行 `AUTORESEARCH_METRICS {"primary": 数值, "clean_quality": 数值, ...}`。未出图、只加载模型、启动了 PID、评分缺失或旧图片都不能发出成功指标。有效图片可继续评分，失败尝试计入预算。
3. `compute` 设为 `managed_gpu`，配置 **guard 和 cleanup argv**。guard 必须接入已有平台/设备启动检查；合规选卡后绑定完整 GPU UUID，遵守用户当前排除节点和跨任务占用。不能仅写 `true`、`nvidia-smi` 或创建空许可文件。guard 只做有界检查，不在其中后台启动观察器。
4. command 包装器负责在实验全程保持现有资源观察器，并同步等待本次训练/生成/评分实际结束再返回；运行期间处理真实禁用/有效停止要求。远端采用自己的有限 timeout 与本 run STOP/恢复机制；本地 SSH 超时不证明远端已退出。cleanup 只停止/核实本 run 的 worker，须幂等，不能处理他人进程或重置整卡；失败时执行器写 STOP，核清之后再恢复。
5. 一次小样本完成真实加载→生成→评分→落盘→恢复后，继续正式探索。不增加独立审批或重复全量预检；平台许可检查无法通过时保留进度，继续可进行的代码/文献工作。

## 评价设计

主指标的改善必须同时满足正常语义/图像质量约束。先根据已有评价的可用性和论文协议确定代理指标与准确术语，不把 CLIP 分类代理 ASR 当作人工验证或论文精确指标。搜索样本与最终 holdout 分离；候选领先后检查多 seed 和消融，报告置信区间或逐 seed 结果。

本模块安装验收使用 CPU 拟合例；GPU桥接的具体命令与模型依赖属于课题首次接入工作，不能把本文件当成已完成 GPU 验证的证据。
