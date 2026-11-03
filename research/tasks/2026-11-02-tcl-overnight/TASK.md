# TCL 夜间想法验证与每小时资源检查

| 字段 | 值 |
|---|---|
| task_id | TCL-OVERNIGHT-20261102-01 |
| status | done |
| outcome | inconclusive |
| owner | 当前聊天主会话；Terra为本run唯一远端执行负责人 |
| planner / reviewer | Astra（gpt-6-astra）：科学协议、核心适配和关键审阅 |
| implementer | Terra（gpt-6.1-terra）：部署、观察、启动/恢复、测试及真实证据核验 |
| run_id | tcl-20261102-overnight-v1 |
| updated_at | 2026-11-03T03:04:17+08:00 |
| current_stage | terminal；S0 baseline_not_eligible，128/128基线完成，其余896键未执行 |
| next_action | 等待用户指示；建议先审计现有96张正常图、提示词及ViT标签映射，不重启本run |
| authorization | 用户授权每小时检查GPU并完成当夜有限TCL探索，明早汇总后等待下一步 |
| automation_id | gpu-tcl |
| automation_status | DELETED；本轮提前按协议结束并交付报告后，经automation_update移除，已不再定时唤醒 |
| generation_deadline | 原计划2026-11-03 07:30 Asia/Shanghai；实际02:18:24因S0门禁提前结束 |
| report_due | 原计划2026-11-03 08:00；本轮03:00回查后提前交付最终报告 |

## 结果与验收证据

[最终中文报告](FINAL_REPORT.md)汇总阶段覆盖、ASR、正常ACC/CLIP、区间、消耗与下一步；[核验摘要](FINAL_EVIDENCE.json)保存从本轮工具输出转录的指标与检查范围。原始stdout未独立保存，原始SQLite与PNG仍在本人服务器目录。

- 104绑定 `GPU-2b05f9c0-6ecb-23cd-03f4-e7b989d07cee`；T0为北京02:08:03.611285，终止为02:18:24.182610。真实加载、生成、独立评分及落盘全部完成，墙钟620.571325秒；GPU累计计算时间未单独测量。
- 128项complete、896项pending；128次尝试全部complete、失败计费0，历史图导入0。Terra实测128张PNG的SHA与账本一致、格式和512×512尺寸有效，128条评分字段有效。
- trigger ASR为clean 0/16、backdoor 16/16，信号门槛通过。backdoor正常dog/cat/other ACC为12/16、8/16、4/16；cat与other未达到S0要求的各类绝对ACC≥75%，因此按预设门禁停止，`outcome=inconclusive`。不是恢复阶段的相对5个百分点损失规则。
- S1/M0/M1未进入；没有new、幅度或随机恢复对照结果，没有合并态结果，不能判断TCL有效或无效。clean正常能力也偏低，原因仍待诊断。
- `tick`及`report`均确认terminal，观察器已退出；本轮新鲜平台采样目标卡free（10 MiB、0%），本人占用0/4，无禁用、有效分配或新增整改/cases。最终远端PID/锁状态未独立复测，不把平台空闲扩写为进程级证明。
- Astra只读复核科学协议、统计helper、报告表格及限制说明通过；未第二次远端执行。

## 固定边界与后续

科学SHA仍为 `3f185460b876ebf44212df197105788b0364b55be8013160ce34bd904ca7c23d`。固定1024唯一键、1056尝试预算、选样、seed、模型及门槛均未改变，详见[协议](PROTOCOL.md)与[机器配置](protocol.json)。任务工程交付完成不代表方法有效；未用预算不能用来重开已终止run，也不恢复历史v1/v2。

建议先只读诊断现有正常图和评分链，区分生成语义、目标标签和分类器误差。任何后续模型、评分或样本修改必须建立新科学配置并预先固定判据；本轮图、评分、消耗及终态保持不变。等待用户决定下一步，不自动追加GPU计算。

## 证据位置与只读入口

```sh
python3 scripts/merging/trigger_contrast_localization/overnight.py report
./labgpu status --fresh --json
```

104部署根 `/data2/zhangzibo/arxiv-tssa/preparations/tcl-20261102-overnight-v1/` 内含 `repository/`、`spec.json`、`session.log` 和 `observations/`；账本和新图位于 `/data2/zhangzibo/arxiv-tssa/results/tcl-20261102-overnight-v1/run.sqlite` 及 `images/`，不得删库、复制另起或修改终态。

本机 `~/.config/labgpu/tcl-overnight/manifest.json` 保留执行绑定与私有回执。凭据不进Git；图像和模型未大批回传，Drive上传仍暂停。工程修复、历史等待与101权限阻塞见[实现报告](IMPLEMENTATION_REPORT.md)。仅为本轮创建的一次性 `caffeinate` PID 21532 已停止，未修改永久电源设置。
