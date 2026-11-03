# TCL实验：统一启动和恢复

当前工作从[项目状态](../../../research/project_state.json)进入，协作按[Astra/Terra流程](../../../research/WORKFLOW.md)。[设计与接口](../../../research/tasks/2026-11-02-runtime-reset/DESIGN.md)说明科学适配，[实现报告](../../../research/tasks/2026-11-02-runtime-reset/IMPLEMENTATION_REPORT.md)记录实际验证范围。

## 常用入口

在服务器的科研仓库根目录、已有研究Python环境中执行；首次生成配置后，启动与恢复完全使用同一条`run`命令。

```sh
python3 scripts/merging/trigger_contrast_localization/runtime.py prepare --request /absolute/request.json --spec /absolute/spec.json
python3 scripts/merging/trigger_contrast_localization/runtime.py run --spec /absolute/spec.json
python3 scripts/merging/trigger_contrast_localization/runtime.py status --spec /absolute/spec.json
```

`prepare`只读取真实固定输入、自动计算哈希和展开本协议的生成键，不创建运行账本；`check --spec /absolute/spec.json`可独立做真实CPU资产检查。正常启动直接用`run`，无需先重复执行`check`，不再生成bundle、人工批准文件或故障专用恢复配置。

需要断开SSH后继续时，用服务器现有持久会话或`nohup python3 scripts/merging/trigger_contrast_localization/runtime.py run --spec /absolute/spec.json > /absolute/session.log 2>&1 &`；先用`status`和日志判断结果。程序自行取得本机排他锁，不能删除锁文件、重置账本或复制目录来“解锁”。

## 首次请求

请求JSON的最小结构如下，所有占位路径须换成真实文件；`inputs`也接受已有的`{"path": "...", "sha256": "..."}`引用，字段含义见[设计](../../../research/tasks/2026-11-02-runtime-reset/DESIGN.md)。

```json
{
  "run_id": "tcl-new-authorized-run",
  "run_root": "/absolute/new-run",
  "models_root": "/absolute/models",
  "inputs": {
    "parent_manifest": "/absolute/parent-manifest.json",
    "parent_review": "/absolute/parent-review.json",
    "prompts": "/absolute/prompts.jsonl",
    "context_review": "/absolute/context-review.json",
    "selection": "/absolute/selection.json",
    "localization_ledger": "/absolute/localization.sqlite",
    "localization_terminal": "/absolute/localization-terminal.json",
    "protocol": "/absolute/protocol.json",
    "asset_manifest": "/absolute/asset-manifest.json",
    "plan": "/absolute/plan.json",
    "context_ids": "/absolute/context-ids.json"
  },
  "execution": {
    "gpu_uuid": "GPU-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "resource_evidence": "/absolute/resource-observation.json",
    "resource_status_file": "/absolute/resource-status.json"
  }
}
```

这11个输入是现有TCL方法的数据和来源证据，不要求重新撰写11份审阅材料；新方法由Astra提供相应科学适配器。默认展开原6144键TCL设计；顶层`study_protocol`可指向[语义完整对照协议](../../../research/tasks/2026-11-03-tcl-semantic/protocol.json)，展开1024键、1056次尝试、单卡和从首次GPU预检起6小时的独立配置。[旧夜间协议](../../../research/tasks/2026-11-02-tcl-overnight/protocol.json)保留其绝对截止，不作为本轮时限。适配器不自动导入旧图片、不继承旧预算。

`max_compute_seconds`为可选正数，放在请求顶层；未配置就没有旧v2的2／22／24小时门槛。配置后的T0在平台预认证通过、首次实际GPU预检前记录；预检失败、CUDA加载及后续暂停和恢复都计入，CPU准备或平台预认证失败不启动T0。

## 状态和恢复

| 返回状态 | 含义与下一步 |
|---|---|
| `paused_error` | CPU依赖、模型加载或执行故障；查看错误、修复后再次运行相同命令 |
| `paused_resource` | 暂无合法资源或收到有效停止要求；等待合法资源并刷新观察后再次运行 |
| `complete` | 完成、科学门槛未通过、预算耗尽或显式时限到达；结合outcome和账本判断 |
| `already_terminal` | 该run已终止；重复命令不会重新计算 |

科学输入、样本、评分、预算和判据固定在`science`；调度实现修复自动追加代码版本，无需手工更新执行代码哈希。生成前计一次尝试，完整图片只续评分，完成结果跳过，失败记录与有限重试额度都保留。

`semantic-v1`的[评分器](semantic_scoring.py)保留ViT/原完整文本CLIP，增加目标猫文本和四类对象文本CLIP；扩展字段必须完整、有限且在范围内才能完成账本项。[科学统计](semantic_science.py)固定四阶段全部测量，科学资格不足只改变解释，缺少合格对照记无法判定。旧协议的门禁与两字段评分兼容保持不变。

## 资源和部署边界

启动时读取最新平台原始观察并执行本机`nvidia-smi`检查；`resource_evidence`指向可刷新的观察文件，不因观察更新修改科学配置。观察字段包括run/science哈希、主机、完整GPU UUID、时间、禁用/分配/额度及原始采集文件引用，精确格式见[runtime.py的resource函数](runtime.py)。桥接器在目标机核对平台主机名后，将`host`写为实际hostname、machine-id SHA和UID的身份字典，原平台名称保存在`platform_host`；不能把平台字符串直接当执行身份，也不能在补身份时延长采样有效期。

运行中禁用或停止要求由外部平台观察者持续更新`resource_status_file`。[overnight.py](overnight.py)通过本机[labgpu API客户端](../../connection/LABGPU.md)刷新平台状态，再向本run写入最小观察；登录凭据留在本机。夜间运行强制`execution.require_fresh_resource_status=true`，身份不符、观察无效或超过180秒没有有效更新时，在执行检查点保存进度并暂停。新禁用/有效停止要求同样作用于检查点；这不是挂死CUDA的硬实时抢占机制。已合法启动后他人加入不单独触发停止。

本轮首次启动及恢复由[validation.py](validation.py)桥接，命令和证据见[实现报告](../../../research/tasks/2026-11-03-tcl-semantic/IMPLEMENTATION_REPORT.md)；本机状态独立保存在`~/.config/labgpu/tcl-semantic/`，当前已实现104部署。运行观察持续检查平台规则，定时任务信息由当前TASK维护。只有配置了绝对截止的run才采用`science.compute_deadline_utc`，到期不新增计算并保全完整或部分结果。

当前支持同一主机、同一目录、单GPU恢复；Astra/Terra的并行指开发分工，不等于已经实现跨机多GPU调度。真实模型、服务器平台和CUDA验证范围以当前TASK及实现报告为准。

## 检查与历史

本地完整回归：`.venv/bin/python -m unittest discover -s scripts/merging/trigger_contrast_localization -p 'test_*.py'`；新机制测试为`test_experiment_*.py`，模拟进程检查与真实GPU验证分别报告。

`main.py`、`pilot24_*.py`及`reconcile_preview.py`保留原实现和历史科学helper，旧恢复器不再作为新任务入口。原TCL v1/v2的协议、审阅和结果从[历史任务目录](../../../research/tasks/2026-10-29-trigger-contrast-localization/README.md)查看，原终态和消耗保持不变。
