# labgpu：实验室显卡状态

在仓库根目录运行 `./labgpu status`，直接读取 [GPU 平台](https://gpu.orz2333.fun/) 普通用户 API。日常查询无需浏览器或 SSH，只显示当前账号有权查看的节点。实现使用 Python 标准库，支持 macOS/Linux，不需要额外安装依赖。

## 常用命令

```bash
./labgpu status                       # 所有可见节点与显卡；默认复用15秒内缓存
./labgpu status --server 104          # 按服务器编号或完整id精确筛选
./labgpu status --fresh               # 强制刷新
./labgpu status --json                # agent使用的结构化输出
./labgpu free --fresh --json          # 本轮观察满足条件的空闲候选
./labgpu status --cached              # 只读本地缓存，不联网
./labgpu status --fresh --timeout 20  # 网络较慢时调整超时
./labgpu login                        # 会话过期或新电脑首次使用
```

可从任意目录使用 `python3 /Users/zzb/arxiv/scripts/connection/labgpu.py status`；换机后替换仓库绝对路径。查看参数用 `./labgpu --help`。`--cache-ttl 15` 控制缓存复用秒数；`--fresh` 与 `--cached` 互斥。

## 状态与数据时间

表格展示型号、显存（MiB）、利用率、温度、占用者和状态。JSON 保留完整 UUID、采样时间、状态原因、节点完整性、账号占用及平台规则。

| 状态 | 含义 |
|---|---|
| 空闲 `free` | 节点在线，GPU和进程采样有效完整、身份和指标有效，没有已知进程、未禁用或维护，且没有明显的残留资源占用 |
| 本人/他人/共同使用 | 有可归属的进程，区分一个或多个使用者 |
| 禁用 `disabled` | 平台采样显示禁止计算模式，或有效维护记录覆盖该卡 |
| 过期 `stale` | 节点离线、GPU/进程样本过期，或缓存已不能作为当前观察使用 |
| 未知 `unknown` | 缺字段、采集不完整、无法归属的进程或指标不一致；具体原因见 `reasons` |
| 故障 `fault` | 平台报告GPU查询失败或已知卡无法采样 |

HTTP刚成功也可能返回旧采样。工具同时核对本地获取时间、平台采样时间、进程采样时间和在线/完整性标志；默认采样有效期120秒。无进程但利用率超过5%或显存使用超过256MiB时保守标为未知。缺失的卡只报告缺失数量，不编造UUID或卡号。

`free`只筛选候选，不代表申请、分配或启动许可。正式启动仍按 [AGENTS.md](../../AGENTS.md#服务器选择优先级) 核对当前规则、分配冲突和跨机占用，并针对选中节点做实时设备检查。平台管理开关与额度字段分别保留，不能只因返回了额度字段就推断管理规则生效。

JSON 顶层：`schema_version`、`source`、`fetched_at`（Unix秒）、`cache_state`、`cache_age_seconds`、`account`、`policy`、`hosts`、`summary`。`hosts[].gpus[]` 包含完整 `uuid`、`status`、`reasons` 与各项指标。服务器或空闲筛选后，`summary_scope=all_hosts_before_filtering` 表示摘要仍是筛选前全局统计。

`hosts[].process_sample_age_seconds`供调用方检查进程样本的剩余有效期；`policy.rectifications/cases`保留平台整改和案件原字段，缺失为null。它们供agent审查实际要求，普通提醒不会自动转换为GPU禁用或停止命令。

## 登录与本机文件

`login`交互输入用户名和密码；已绑定两步验证时继续输入6位动态码。首次绑定或重绑动态码由用户在网站完成。密码和动态码不会保存，也无需把它们放在命令行参数或聊天里。

配置与缓存默认放在 `~/.config/labgpu/`：目录0700，`cookies.json`、`status.json`仅本人可读写。它们不在科研仓库中，不随Git或换机资料提交。登录成功先使旧账号缓存失效；查询进程各自刷新，缓存文件原子替换；并发查询可能重复请求，登录与查询并发可能覆盖缓存。会话有有效期，过期后运行 `./labgpu login`，不依赖长期打开网页。

查询使用 `GET /api/me`；登录使用 `POST /api/login`、必要的 `POST /api/login/mfa` 和 `GET /api/session`。保持TLS证书校验，禁止跨来源重定向。工具不调用申请、管理员、结束进程或改密码接口。

## 失败与退出码

- 退出0：查询或允许使用的短缓存读取成功；不表示存在空闲GPU。
- 退出1：认证、连接、格式或文件权限错误，或展示了过期缓存。`--json`输出可解析JSON，错误信息在 `error` 或状态原因中。
- 参数错误退出2。`--timeout`是网络套接字超时，不承诺整个命令的严格墙钟上限。
- 默认 `status` 遇到网络错误可以显示明确标为过期的历史缓存并退出1；`--fresh`和`free`不会把网络失败后的旧缓存当成功。401/403直接提示重新登录，不用历史缓存掩盖认证失败。
- `--cached`可离线查看历史；缓存超过复用期限时标为过期并退出1，`free`不会把这些记录列为空闲。

## 维护与验证

这是网站前端实际使用的内部接口，字段变化时应更新适配和针对性测试。核心规则在 [labgpu_model.py](labgpu_model.py)，HTTP/CLI在 [labgpu.py](labgpu.py)。

```bash
python3 -m unittest discover -s scripts/connection -p 'test_labgpu*.py'
```

真实接口与性能验证见[CLI实现报告](../../research/tasks/2026-11-02-labgpu-cli/IMPLEMENTATION_REPORT.md)。labgpu本身只查询；定时检查、启动和运行期平台观察从[当前项目状态](../../research/project_state.json)进入相应任务。实验完成后的独立保留任务见[GPU保留使用说明](GPU_HOLD.md)。
