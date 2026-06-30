# 此目录用于存放从服务器同步回来的配置文件副本

> ⚠️ 当前为空目录（占位符）

## 用途

存放 BackdoorDM 项目中需要本地备份的配置文件，例如：

- `base_config.yaml` — 基础训练配置
- `bd_config_*.yaml` — 各攻击变体配置
- `eval_config.yaml` — 评估配置

## 配置文件实际位置

所有配置文件在服务器上：
```
/opt/data/private/BackdoorDM/attack/t2i_gen/configs/
/opt/data/private/BackdoorDM/attack/uncond_gen/*/configs/
/opt/data/private/BackdoorDM/evaluation/configs/
```

## 何时需要本地副本

- 需要 git 跟踪配置变更历史
- 需要在本地离线查看/对比配置
- 需要批量修改后上传到服务器

如需同步配置，使用：
```bash
scp -P <port> amax:/opt/data/private/BackdoorDM/attack/t2i_gen/configs/*.yaml ./configs/
```
