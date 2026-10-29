# TSSA 进度与网站故障说明

核对时间：2026-10-27 09:30（Asia/Shanghai）。

- 定时任务`gpu`已暂停并回读确认，不再自动唤醒；已有模型上传PID20773仍在继续，不占GPU。
- 当前完成的是实现与离线准备，尚未完成TSSA方法的GPU实证，不能宣称有效或无效。

| 阶段 | 已核验进度 |
|---|---|
| 实现与协议 | 冻结协议和双卡执行代码已部署，20份源文件哈希匹配。 |
| 依赖环境 | 51/51个Linux依赖已传输、验哈希并离线安装，依赖检查、14模块导入和3项原生CPU检查通过。 |
| CPU验证 | 服务器实际环境56项研究检查全部通过，含微型真实UNet到a/b的梯度；正式checkpoint与CUDA尚未验证。 |
| 模型资产 | 18/47文件、4,758,949,034/14,683,626,535字节已整文件验收；SD1.5和TPA已齐，DreamShaper上传中，其余未齐。 |
| 正式实验 | 源模型门禁、合法轨迹缓存、静态筛查、三族各48步优化、开发选择及持出评价均未执行。 |
| 结果 | 有效研究图0、梯度更新0、GPU用时0；ASR和正常指标尚无结果。 |

## 网站故障

- GPU管理网站在09:26刷新后返回Cloudflare1016；故障页源站`farmer-actor-europe-august.trycloudflare.com`经本机、公共DNS及Google加密DNS查询均为不存在，错误发生在账号登录前。
- 不同入口节点分别返回HTTP530/1016和502，说明仅换本机DNS不能恢复当前网站；精确的隧道停止或源站配置变化原因，需要管理员日志确认。
- 当前没有该网站域名、反向代理或cloudflared的管理权限，未修改任何网站配置，网站尚未恢复；需管理员恢复有效隧道并更新反代源站映射，再验证登录页。

## 证据及恢复条件

- [进度断点](tssa_overnight_progress.md)、[暂停检查点](../results/tssa-mvp-2026-10-26/user_pause_checkpoint_2026-10-27-093014.json)和[网站诊断](../results/tssa-mvp-2026-10-26/website_diagnosis_2026-10-27-012734Z.json)保存本次事实；旧失败日志及冻结协议均保留。
- 后续需完成余下模型和正式checkpoint预检，并在网站恢复后重新核验本人额度、队列#55、禁用卡和他人进程；只有用户恢复任务后才重新安排自动推进。
- Cloudflare对1016的定义与处理依据：[官方说明](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1016/)。
