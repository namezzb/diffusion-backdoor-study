# 触发对比参数定位执行器

[reconcile_preview.py](reconcile_preview.py)及[test_reconcile_preview.py](test_reconcile_preview.py)是实现agent新增的v1只读账本预览与检查源码；本轮只登记入口，未运行该测试或签发实现批准。预览绑定v1固定清单并输出`provisional_not_executable`，不能作为v2调度、旧writer退役或全量来源验证的证明。

当前接手入口为[24小时多卡协议](../../../research/tasks/2026-10-29-trigger-contrast-localization/PILOT24_PROTOCOL_2026-11-02.md)，独立运行`tcl-20261102-pilot24-v2`尚未启动，单机常驻多卡执行链已通过本地独立review，实际来源和生产bundle仍待认证。完成与待完成状态只见[TASK](../../../research/tasks/2026-10-29-trigger-contrast-localization/TASK.md)，v1的M06及测试通过不能代替v2验收。

[pilot24_prepare.py](pilot24_prepare.py)校验真实来源证明后生成bundle、全量分片config和pending review，[pilot24_run.py](pilot24_run.py)提供持久启动、全局阶段协调、进度和截止报告；[来源认证器](pilot24_provenance.py)验证固定副本及首次实时GPU许可，不能自动制造现场证明。操作步骤、审阅边界及223项完整CPU检查见[实现review](../../../research/tasks/2026-10-29-trigger-contrast-localization/PILOT24_IMPLEMENTATION_REVIEW.md)，真实CUDA尚未验证。

[pilot24_build_source.py](pilot24_build_source.py)根据现场来源构造只读副本和来源证明，固定363候选并绑定旧中断键及跨机回执；实际来源的独立审阅见[审阅记录](../../../research/tasks/2026-10-29-trigger-contrast-localization/PILOT24_SOURCE_REVIEW_20261102.md)。本轮变更后完整CPU测试236项通过，生产bundle与CUDA仍待验证。

现有v1的`main.py`默认仅输出计划，`localize`与`confirm`绑定原冻结输入和逐单元账本；样本、预算与统计包含旧版固定维度，不能仅修改manifest执行新方案。通用`recover --recovery-kind localization|images --reason <具体原因>`不合并跨机账本，旧恢复命令与分片均不得直接重放。

本地检查入口：`.venv/bin/python -m unittest discover -s scripts/merging/trigger_contrast_localization -p 'test_*.py'`；通过情况须绑定实际源码与环境，不能将命令存在视为测试已通过。v2真实计算须通过其实现审阅、冻结输入并核对服务器实时许可与实际资产，详见[任务正文](../../../research/tasks/2026-10-29-trigger-contrast-localization/TASK.md)。

以下是v1历史实现说明：CPU预检后，定位和确认阶段各自等待绑定一次性nonce的短期平台观察记录，再只读检查GPU进程；许可格式见[原实现交接](../../../research/tasks/2026-10-29-trigger-contrast-localization/IMPLEMENTATION_REVIEW.md)。

104独立分片曾因CUDA初始化失败而未出图；[127旧分片](../../../research/tasks/2026-10-29-trigger-contrast-localization/SHARD127_HANDOFF.md)已消耗该1704键集合的一部分，不能重放旧104计划。控制器版本及52／81等测试数属于对应历史审阅，v1不再补满原预算，不能据此宣称v2已经实现。

- `test_shard127_safe_publisher.py` 验证见证更新前拒绝不完整或不匹配数据；修复候选和签名审阅见任务目录。

- `test_shard127_controller_v3.py` 验证并行见证摘要与有效期的发布前检查，签名审阅见任务目录。
