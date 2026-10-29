# 索引如何保持同步

维护要求以[AGENTS.md的收尾规则](../AGENTS.md#每次工作必读与收尾)为准，本页提供工具入口与操作顺序。实验仍暂停；这些检查只读取本地科研仓库，不连接服务器、不下载、不启动GPU。

## 三层入口，各记一件事

| 层次 | 内容与维护方式 |
|---|---|
| 人读的入口 | 根README和各目录README说明主题、当前入口和证据边界，不逐行罗列几千份产物 |
| 仓库逐文件目录 | [repository_index.jsonl](repository_index.jsonl)自动记录Git文件及待纳入的新文件的路径、内容哈希、所属入口；自身哈希明确豁免以免自引用 |
| 外置资料目录 | [retrieval_catalog.jsonl](retrieval_catalog.jsonl)记录附件的Git、服务器或固定版本公开来源；完整远端盘点见[服务器索引](SERVER_INDEX.md)，新附件可补入[asset_registry.jsonl](asset_registry.jsonl) |

[index_policy.json](index_policy.json)指定目录负责入口、相关进度记录、活跃链接范围以及有理由的本机临时项排除；新顶层目录需要明确增加归属。历史封存中的链接不当成当前导航强制修复，修改活跃入口而保留原始证据。

人工附件登记每行包含仓库相对`path`、`bytes`、`sha256`、`sources`和用途说明；学校来源需与被引用服务器清单匹配，公开来源需固定版本HTTPS地址，Git来源由工具核验。登记内容没有有效来源会保持缺口并检查失败，不把旧机尚未上传的ZIP当作可下载来源。

## 每次任务的最短收尾

1. 运行`python3 scripts/storage/maintain_index.py impact`，按输出查看本次变更涉及的README和进度记录，再更新实际受到影响的资料。
2. 新增或修正外置附件时先补来源清单，需要作为Git来源的新小文件先暂存（不提交），再运行`python3 scripts/storage/build_retrieval_catalog.py`；不要直接改生成目录或改写冻结包清单。
3. 完成文档、目录生成及必要验证后再次运行`impact`，以最终输出的`base_commit`和`changes`填写[latest.json](maintenance/latest.json)；摘要和每个`review_indexes`的处理决定须实际审阅，未更新项写具体依据。
4. 收尾记录最后写完后运行`python3 scripts/storage/maintain_index.py refresh`，再用`check`检查本地；所有应提交文件暂存后，用`check --staged`检查真实待提交版本。
5. 提交和推送后核对远端版本；最终报告说明更新了哪些入口、检查结果及尚未覆盖的内容。

回执的`reviewed_changes`排除生成清单与回执本身，改名按删除旧路径和新增新路径记录，删除用`kind: deleted`及空哈希。`index_decisions`中的`updated`必须确实有改动，`unchanged`须解释为何本次不影响该记录；记录哈希后再改文件会再次被检查拦下。

`refresh`只生成文件目录，不会替agent编写“已复核”理由或修改科研状态。清单、回执、工作区与暂存区不一致时检查失败；新生成且被Git忽略的附件也会按文件名检查，必须登记或明确说明排除原因。

## 新电脑启用提交检查

```bash
python3 scripts/storage/install_index_hook.py
python3 scripts/storage/maintain_index.py check
```

安装器只设置当前仓库的提交检查；已存在不同钩子配置时会停止并说明冲突，不覆盖别的工具设置。Git克隆不会自动启用本地钩子，因此新电脑需做这一步，仓库同时提供[GitHub检查](../.github/workflows/research-index.yml)作为第二道校验。

本地钩子按暂存内容检查，避免“工作区文档已改但没提交”被误判通过；GitHub只检查已提交内容，无法发现旧机未提交的文件。GitHub检查使用完整提交历史验证回执基准，缺少基准提交或合并后回执过期时明确失败，应复核实际差异而不是静默跳过。

## 覆盖边界

正式科研文件应有目录归属，外置附件应有来源或明确缺口；依赖、机器设置、临时中转和旧页面上下文按精确路径或限定目录说明排除，不将整个results或papers排除。`.codex/`等本机临时工作区没有逐项科学审阅，不能说这些临时内容也都完成了科研归档。

78条已保存学校记录缺SHA，AMAX早期内容缺完整盘点，详见[服务器索引](SERVER_INDEX.md)；本轮不会为了消除提示伪造哈希或重新连接服务器。工具核验普通Markdown导航目标，不验证章节锚点或复杂嵌套语法；能发现漏记、断链和旧记录，但不能证明服务器当前在线、人工结论正确或所有agent永不遗漏。

最新收尾记录只保留当前状态，历史内容从Git历史读取；原始实验账本和冻结证据不由本工具修改。全仓目录是定位工具，不能代替服务器原文件的备份副本。
