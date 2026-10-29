# 新探索启动器独立复核

最终审阅版本SHA256=`20885f4c10e036796ade7fe253f0e4608002e73d48f93eebc93e00cf23a188b8`，冻结计划SHA256=`8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6`。**无剩余必须修复项**，本次12项针对性契约/差异核查全部通过，见[JSON证据](independent_launcher_review.json)；没有重跑作者24项完整测试，也未SSH、启动子进程、加载模型或查询CUDA。

## 修复与验收

本审阅发现初版永久claim仅同步文件、不同步目录，异常掉电后不能充分保证新目录项持久。作者已修为文件→父目录→祖父目录的fsync顺序；本机真实临时文件检查确认顺序，模拟目录同步失败会抛出异常并保留claim，不放行下一次提交。

104 GPU0新增的Xwayland例外已与实际只读证据`node104_graphics_identity_20261028T072313Z.json`逐字段核对：仅允许已观察PID7187、UID125、gdm身份、完整argv及G类型。换卡、换服务器、PID/UID/账号/argv改变或C类型均拒绝，未把所有Xwayland或未知图形进程泛化为系统服务；gdm gnome-shell原例外也与同份证据吻合。

## 真实运行契约

- 将103及104生成的真实参数交给冻结runner的实际argparse/main，在创建Store前截停，两者均得到固定新run目录、CPU scorer、`resume=False`和执行至confirm；没有误进入旧MVP、check模式或恢复已有运行。
- 启动环境的完整UUID、`CUBLAS_WORKSPACE_CONFIG=:4096:8`与冻结`require_allocated_cuda`一致；独立执行实际门禁并在首次CUDA查询前截停，证明不会因这些前置环境要求立即失败，不能据此声称CUDA可运行。
- 本人数据盘的results、tmp、cache及HF/torch/triton目录在远端永久claim之前创建/验属主、权限及路径，claim之后才Popen；run目录必须不存在，日志与启动receipt另存launch-control，未污染runner需要的新目录。
- 冻结科学manifest及其四个source哈希保持一致，离线和CPU评分参数明确；路径准备、源文件校验及最新权限/进程检查仍可能实际失败，失败必须保留证据。

## 唯一提交与权限

同一Mac的永久claim和flock只按计划SHA命名，不按服务器分成两套；因此从指定入口向103/104提交共用一份本机保护，目标服务器另有自己的永久claim。旧claim、孤立结果、非零科学样本、未知活跃状态或既有run均拒绝自动重试，不存在force、自动清claim或自动终止其他任务的路径；这不是多台Mac之间的通用分布式协调器。

页面明确显示实时但没有采样时间时，必须显式`live_UI_without_timestamp`、`sample_at=null`、实时标记为真、历史标记为假、采样有效且观察距现在不超过120秒。独立反例确认历史页、编造sample_at及观察过期会被拒绝；有实际采样时间时仍走时间戳有效期核验，模板本身不能作为许可。

## 证据边界

此审阅仅确认本机代码契约和新增保护，不证明任何节点现在有合规空卡、环境完整或已经启动。实际执行仍需新的门户三视图证据、目标CPU部署验收及实时UUID/Default模式/进程检查，返回spawned仅表示创建子进程，之后必须另行观察GPU、日志和科学收据。
