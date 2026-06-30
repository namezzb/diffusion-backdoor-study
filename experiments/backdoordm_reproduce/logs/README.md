# 此目录用于存放从服务器同步回来的日志副本

> ⚠️ 当前为空目录（占位符）

## 用途

存放需要本地分析的训练/评估日志，例如：

- `run_all.log` — 全量复现主日志
- `timing.csv` — 各步骤耗时统计
- `failures.log` — 失败记录
- `eval_*.log` — 评估日志

## 日志实际位置

所有日志在服务器上（**实时且很大**）：
```
/opt/data/private/BackdoorDM/logs/
```

## 何时需要同步日志到本地

- 需要用本地工具（VSCode, grep, diff）做深度分析
- 需要长期归档某次重要运行的日志
- 需要在本地做对比实验（旧日志 vs 新日志）

同步命令：
```bash
# 只同步小文件（推荐）
scp -P <port> 'amax:/opt/data/private/BackdoorDM/logs/*.csv' ./logs/
scp -P <port> 'amax:/opt/data/private/BackdoorDM/logs/*.log' ./logs/

# 不要同步 run_all.log (116MB+)，用 grep 在服务器上看
ssh amax -p <port> "grep 'FAIL\|Error' /opt/data/private/BackdoorDM/logs/run_all.log | tail -20"
```

## ⚠️ 注意

**不要把整个 logs/ 目录同步下来** — 服务器上的 `run_all.log` 单文件就有 116MB+，会污染本地仓库。
