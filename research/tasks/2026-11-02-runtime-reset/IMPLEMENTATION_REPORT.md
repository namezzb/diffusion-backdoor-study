# 运行机制实现报告

本轮完成新运行器的本地工程实现，未启动科研 run、连接服务器或占用 GPU；结果不构成方法有效性结论。

## 入口和机制

- [runtime.py](../../../scripts/merging/trigger_contrast_localization/runtime.py) 提供 `prepare --request <请求JSON> --spec <输出JSON>`、`check --spec <JSON>`、`run --spec <JSON>` 和 `status --spec <JSON>`；再次调用同一 `run` 即尝试从已有账本续跑。
- [runtime_tcl.py](../../../scripts/merging/trigger_contrast_localization/runtime_tcl.py) 将固定输入展开成完整单元并连接真实 TCL 模型、生成、独立评分和阶段门禁；`prepare` 与 `check` 不启动 GPU，执行胶水代码哈希按 session 自动记录，科学输入及科学代码哈希保持固定。
- [runtime_store.py](../../../scripts/merging/trigger_contrast_localization/runtime_store.py) 使用本机排他锁与 SQLite 保存单元、尝试、资源计数及事件；生成前计费，中断的已落盘图片转入评分，完成图片校验后不重复生成，预算耗尽作为 `inconclusive` 终态。
- 资源暂不可用返回 `paused_resource`，工程错误返回 `paused_error`，均可修复后通过同入口恢复；可选 `science.max_compute_seconds` 从首次 GPU 加载前记录的 T0 计时，恢复不重置。
- 资源启动检查要求新鲜的平台观察及本机 GPU 进程检查，并记录实时 XML 的哈希、驱动版本和计算模式；运行中发现禁用或停止要求依赖外部采集器持续更新 `execution.resource_status_file`，本实现没有提供该采集器。
- 支持同一主机、同一目录、单 GPU 恢复，账本绑定运行目录及主机身份；不支持跨机迁移或分布式锁，旧 `tcl-20261102-pilot24-v2` 不可通过新入口复活。

## 本地验证

进程与账本检查：`python3 -m unittest discover -s scripts/merging/trigger_contrast_localization -p 'test_experiment*process.py' -v`，11 项通过；真实适配器的模拟固定输入展开检查：`python3 -m unittest discover -s scripts/merging/trigger_contrast_localization -p 'test_runtime_tcl.py' -v`，1 项通过（2026-11-02，本地 CPU 模拟）。

主会话在最终源码上完整回归：`.venv/bin/python -m unittest discover -s scripts/merging/trigger_contrast_localization -p 'test_*.py'`，272 项通过，用时 30.544 秒；包含启动锁残留恢复、未知文件保护及实时 GPU 记录的最终修订，证据时间为2026-11-02 19:50（北京时间）。

测试覆盖 CLI 检查与评分中断续跑、期限跨重启保持、忙卡等待及评分恢复、生成中断计费与有限重试、模拟平台停止、独占锁及身份保护；使用模拟适配器和模拟资源检查，未验证真实模型加载、CUDA、服务器 GPU 或管理平台采集。
