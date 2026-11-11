# 上游来源与本地适配

- 项目：https://github.com/uditgoenka/autoresearch
- 版本：v2.3.0
- 固定 commit：`7bddd056dfd0b0ded8360588d8101b1ecb5c0baa`
- 取得时间：2026-11-11
- 取得方式：Codex skill-installer 的 `install-skill-from-github.py`，`--ref` 固定上述 commit，下载 `.agents/skills/autoresearch` 到 `vendor/autoresearch`。
- 许可证：MIT，副本见 [vendor/LICENSE](vendor/LICENSE)。
- 文件大小与 SHA256：[vendor/manifest.json](vendor/manifest.json)。它记录安装时来源与完整性，不是每次实验的重复启动门槛。

上游源码保持原样。本地 `program.md`、skill、`ar.py` 是项目适配：运行记录改为 Markdown、实验仓库隔离、默认串行有界、取消自动 fork，GPU 继续遵守本仓库规则。上游默认 TSV、orchestrator 确认、分叉与通用发布流程不作为本课题额外执行门槛。

所有文件均随科研仓库分发；没有全局安装 hooks、修改账号设置或替换现有 Codex。更新上游时显式选择新 commit，保留许可证、重新生成清单并验证适配，不在实验中自动拉取 latest。
