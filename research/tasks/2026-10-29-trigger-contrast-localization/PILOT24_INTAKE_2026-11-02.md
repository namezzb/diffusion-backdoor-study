# v2 接手核验与未完成事项

2026-11-02 11:02 起本会话按用户委派接手实现，保留共享工作区已有修改；本记录仅是阶段性取证，不是运行冻结、实现交付或 review 批准。

| 对象 | 本次观察与边界 |
|---|---|
| 103 | 11:03 左右一次有界只读 SSH 经跳板到目标时返回 `connect failed: Connection refused`；原进程、锁及最新账本未知，不可据此认定 writer 已退出。 |
| 104 / 127 | 11:05 左右只读 `ps` 未见本人 TCL 实验进程，默认 tmux server 不存在；这不是锁、其他 tmux socket、定时恢复入口或 103 隔离证明。 |
| 定位及六掩码 | 11:04:34 CST 对 104 既有快照只读重算 SHA256，终态 `7f889beb7474aeb72ff39e4f6f2cc78bbae16907ad86ab5503beec96ab6bb456` 与 selection `a50cc62f6c741d025b59a8d35e6e2ad3010f9fd661521f6d8b9d655ba4618957` 匹配先前记录，掩码见下表；11:17:26重算定位账本 `569c651a616cea7d4380af643310f64754a36d6542611dd30aaeeb4f9cfb78e3` 亦匹配已有服务器索引。 |
| 图片候选 | [逐键清单](pilot24_reuse_candidates_20261102.json)中的363张在11:12核验账本、提示哈希及评分字段，并于11:15完成[SHA与完整解码](pilot24_candidate_decode_20261102.json)；模型／评分来源绑定和103隔离仍未完成，不能算作导入。 |
| 实际导入及出图 | v2 已导入 0 张、新生成 0 张，R 尚未最终确定；历史消耗暂计 734 次、其中 6 次 started，仍须全局对账。 |

| 104 快照掩码 | 本次只读 SHA256 |
|---|---|
| new | `f211142975adfb8d6ba9201c67f12115c8bcb816d6c95468649813ccfe20a156` |
| magnitude | `58f1d9ca47f472d44090b509ca6e84cdbcb618a7040ecff3594133b7ddcd0f88` |
| block_magnitude | `b95c9dff69af3abc7d8d2c14f847decaa274c220a7208b3cde5655a8638d54b0` |
| random_1 | `b76b857bfc24536391a3062c0d6f8669aa83fa75570a2608b40c4d038272f9d3` |
| random_2 | `d75a329078ef332a4d2dea924703f45f24069dbc312faead9930a78f5681d62c` |
| random_3 | `91c8e1a00d47e9f59edaf53e81ae63c8d7e351c1b101e97ecde7dbd68ee5c784` |

文件位于 `/data2/zhangzibo/arxiv-tssa/preparations/tcl104-direct-20261030/tcl104-shard-snapshot-20261030T0200Z/run/selection/`；此处登记本次观察，不表示已下载或建立新备份。

执行原型包括固定输入、账本、单元计算、分片检查、阶段统计和本地期限监督，尚未接成完整可授权启动的程序。仍需完成来源绑定及导入、跨机唯一分配和门禁、可持久运行的启动器、全局恢复及 deadline 集成，并经测试后交原会话 review。

执行 `.venv/bin/python -m unittest discover -s scripts/merging/trigger_contrast_localization -p 'test_pilot24*.py' -v`，21项通过，覆盖输入、账本、分片、模拟图片执行及计时边界；这些是CPU和模拟检查，不证明真实模型执行或跨机端到端安全。

完整 TCL 测试集 `-p 'test_*.py'` 在本轮执行了142项并通过；后续针对原型的小修又重跑21项通过，旧版冻结源码未改动。

现有原型中的中断处置只检查隔离证据的哈希格式、尚未验证隔离事实；全局阶段放行、凭证绑定和持久进程监管也尚未串联，必须先补齐再提交实现 review。

103于10月30日的[最后进程证据](server103_gpu_failure_20261030.json)显示SIGTERM后残留线程及run锁仍在；11月2日11:09平台显示103离线，不能证明原锁、进程及自动恢复入口已退役。
