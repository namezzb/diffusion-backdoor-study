# 新探索单次启动入口

`launch_image_search.py` 只服务冻结 manifest `8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6`，支持 104 的 `/data2/zhangzibo/arxiv-tssa` 和 103 的 `/data1/zhangzibo/arxiv-tssa`；本机检查通过不等于远端启动或 GPU 验收。

## 准备

1. 使用 `permission_template_104.json` 或 `permission_template_103.json` 创建本轮新证据文件，填写刚完成的三个登录视图观察、完整 UUID、index、禁用/维护/预留/进程状态及跨服本人占用、已分配待启动数量、实时额度；模板不是许可，等待队列不填入已分配数量。
2. `permission_kind=direct` 必须确有直接使用规则依据，`evidence_note` 记录具体页面事实；若走分配，填 `allocated` 及 `allocation={status:confirmed,server,gpu_index,gpu_uuid,counted_in_pending:true,assigned_at,confirmed_at}`，分配和启动各遵守 10 分钟窗口。
3. 104 使用 `deployment_20261028T064803Z.json`，103 必须另有成功 CPU 部署报告；本机 `progress_state.json` 须是 `CPU_deployed_waiting_for_ready_permitted_GPU` 或 `ready_for_first_GPU_launch`，图数/更新均为 0 且本探索活跃 GPU 列表为空。

本机准备命令（无 SSH）：

```sh
python3 results/tssa-opt-exploration-2026-10-28/launch_image_search.py \
  --server 104 \
  --deployment results/tssa-opt-exploration-2026-10-28/deployment_20261028T064803Z.json \
  --permission /absolute/path/to/fresh_permission.json
```

实际授权执行使用同一命令加 `--execute`，不得复用过期许可；UI 观察在本机和远端检查时均须不超过 120 秒，未来时间也拒绝。

网站显示采样时刻时使用 `sample_time_basis=timestamp` 并填真实 `sample_at`，检查其不超过 120 秒；网站明确实时但不展示采样时刻时使用 `sample_time_basis=live_UI_without_timestamp`、`sample_at=null`、`live_indicator=true`、`historical_sample=false`、`sample_valid=true`，不能将 UI 观察时间冒充采样时间。

## 单次运行与验收

- 固定真实命令执行新 runner 至 `confirm`，scorer 为 CPU，离线加载，GPU 以完整 UUID 绑定；run 目录为 `<base>/results/tssa-opt-exploration-2026-10-28-v1`，启动前必须不存在。
- 启动环境固定 `CUBLAS_WORKSPACE_CONFIG=:4096:8`，与冻结运行时的确定性要求一致；远端永久 claim 写入前创建并校验本人数据盘的 results、tmp、cache 及对应缓存子目录，拒绝软链接、错误属主或组/其他用户可写的路径。
- 本机 `launch-control` 的永久 claim 和 flock 跨 103/104 共用，远端另有永久 claim；远端日志和启动 receipt 位于 `<base>/launch-control`，不会污染 runner 要求的空 run 目录。
- 每份永久 claim/result/receipt 都按文件、父目录、祖父目录顺序 fsync，覆盖新建 `launch-control` 的目录项；同步失败保留现有证据并拒绝继续或自动重试。
- 远端重新读取 NVIDIA XML，检查 index/full UUID/Default 模式和每个目标卡进程；系统显示例外限于103 GPU0/1的精确 root Xorg、104已核验gdm的gnome-shell，以及104 GPU0的PID7187/UID125 Xwayland完整身份和argv，后者证据为 `node104_graphics_identity_20261028T072313Z.json`。
- 任何研究进程、未知/不可读目标进程、残留 run、旧 claim、孤立本机结果、SSH/Popen 状态未知均阻止自动再启动；没有 `--force`、自动清 claim、终止他人任务或 GPU reset 路径，必须人工审计和单独记录解决依据。
- 返回 `runner_process_spawned_not_GPU_acceptance` 只证明创建子进程，随后需用独立观察核验存活、UUID、日志和 receipt；如果已经真实运行，之后他人加入本身不是停掉本项目的理由。

本机验收：24 项单元测试通过，并检查 Python 3.8 语法兼容；新增真实文件/目录fsync顺序与失败保留测试、精确Xwayland实例的负例检查，另保留许可/额度/进程/重复启动/目录及冻结CUDA门禁的环境契约检查，最新证据为 `launcher_CPU_readiness_20261028_r4.json`。
