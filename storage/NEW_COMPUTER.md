# 新电脑接续科研：先拉Git，再按索引取数据

目标是让agent只凭科研Git就能理解进度、定位已知资料并按需取回；大图片、模型和缓存仍在本人服务器，不要求先搬到旧Mac。实验和旧GPU定时任务保持暂停，Drive限制保持有效，读取本页不授权重跑实验或占用GPU。

## 第一步：取得进度与当前代码

```bash
git clone https://github.com/namezzb/diffusion-backdoor-study.git
cd diffusion-backdoor-study
```

已克隆仓库时先检查本地改动，再快进更新；不要用强制重置覆盖新电脑自己的文件。必须取得包含本页的提交，旧版本仓库没有2026-10-28/29的完整实验记录。

agent依次读取：

1. [AGENTS.md](../AGENTS.md)：当前约束，实验暂停和服务器使用规则。
2. [project_state.json](../research/project_state.json)：三轮实验状态、结论、下一步边界。
3. [研究解释](../research/tssa_methods_and_results_explained_2026-10-29.md)：Uniform4、TSSA16等名称、实际尝试与效果。
4. [服务器索引](SERVER_INDEX.md)：哪台机器、哪个目录、哪些已在本地以及证据日期。
5. [资产位置清单](retrieval_catalog.jsonl)：本地重要附件可从Git、学校服务器或固定版本公开地址取回；[覆盖审计](audits/retrieval_coverage.json)列出例外。

研究结论不依赖当前聊天或AI记忆：第一轮1520图/144更新，第二轮816图/0更新，第三轮0图/0更新；三轮均未得到正常能力达标且攻击成功率优于同轮基线的合格方法。历史失败和invalid审计标签保持不变。

## 第二步：按需要选择资料

| 需要什么 | 索引与取回方式 |
|---|---|
| 阅读进度、代码、指标、候选选择和训练轨迹 | 直接打开Git里的research、scripts及三轮results入口，无需连接GPU服务器 |
| 第一轮1520张原图、模型检查点与缓存 | [104逐文件索引](server-index/104.jsonl)中的远端完整路径和SHA；主要根目录`/data2/zhangzibo/arxiv-tssa/results/mvp-2026-10-28-single-v1/` |
| 第二轮816张原图、第三轮诊断数组 | [103逐文件索引](server-index/103.jsonl)；根目录`/data1/zhangzibo/arxiv-tssa/results/`，按run_id区分两次实验 |
| 论文PDF | [论文清单](../papers/catalog.json)每项retrieval.url对应固定arXiv版本，下载后与本地旧版SHA比对；链接来自版本标记，本轮未联网验证，内容不同不能静默替换 |
| 公开模型 | [固定来源/revision](../research/tssa_mvp_assets_2026-10-26.json)、[103历史模型哈希](server-index/103-models-historical.jsonl)；不要把环境安装目录当成模型备份 |
| 历史汇报和冻结执行源码 | 小型PPT、必要文本、源码/准备包按明确例外直接保存在Git，具体位置见[资产位置清单](retrieval_catalog.jsonl) |
| AMAX历史完整结果 | 只掌握[历史路径](SERVER_INDEX.md)，还需当前有效会话入口及文件盘点；不能保证所有历史大文件现在可下载 |

资产清单记录的是保存时的文件来源和哈希，不是实时在线保证。服务器文件被删、访问权失效或公开站点不可达时要如实报告，不凭索引伪造下载成功。

## 第三步：在新电脑配置自己的访问条件

Python 3.10+和OpenSSH用于索引取回工具；工具面向macOS/Linux，本轮在macOS完成离线验收，Linux及Windows原生环境未实际验收。先按[学校连接说明](../server/README.md)在新电脑安全配置本人私钥和经核验的主机记录，Git不保存私钥、密码或验证码。

[school_ssh_config](../server/school_ssh_config)使用`~/.ssh/zhangzibo_school`及`~/.ssh/known_hosts_school`，不要求新电脑仓库位于`/Users/zzb/arxiv`。跳板与目标主机都必须有已核验的身份记录；下载器不会自动接受未知指纹，也不会修改DNS或反复重试。

需要网页登录或新的AMAX端口时由用户提供当前有效会话信息，旧记录不能替代新授权。只读取本人数据无需申请GPU，但不能顺带启动实验。

## 第四步：按索引下载并验收

先只看计划，下例用一个小型诊断报告示范；将路径替换为104或103索引里的`relative_path`即可选择其他文件：

```bash
python3 scripts/storage/fetch_server_file.py \
  --server 104 \
  results/mvp-2026-10-28-single-v1/gpu_diagnostic.json \
  --target results/server-archive-2026-10-29/server104
```

此命令不联网、不写文件，打印服务器位置、预期大小、SHA和本地目标。确认新电脑访问条件与所需文件后，增加`--download`才会只读下载该文件；选择103时相应更换`--server`、路径及本地目标目录。

下载只在已授权的本人科研根目录读取自有常规文件，先写本地临时文件，大小和SHA都匹配才保存为正式副本，并写独立receipt。已有相同文件复用，已有不同文件、未知SHA、路径越界、符号链接、空间不足、传输中断均停止而不覆盖原件。

103的65个仅元数据条目、104的13个公开大模型条目没有本索引的SHA，当前专用下载器会拒绝验收；前者以后先取得新哈希，后者使用固定模型来源/历史模型校验记录。不要改用旧`archive_school_research.py retrieve --server 103`冒充已可用整批恢复，其所需的完整103哈希manifest目前不存在。

下载后的服务器原路径副本可以直接分析，资产清单中的`path`是旧本地相对位置；若需要恢复旧本地布局，再按相同SHA复制到对应位置并避免覆盖不同内容。一次只下载当前复核需要的图、数组或模型，不默认取全套数据。

## 覆盖范围与保留限制

本次Git交接包含科研代码、冻结方案、进度、负结果、小型证据、文件定位及校验信息；核心三轮的重要数据已有学校服务器定位。24篇PDF已有固定版本公开定位，但本轮没有重新下载检验远端字节；AMAX历史内容只有目录级线索，仍是明确缺口。

旧登录/排队截图、与科研结果无关的页面诊断、凭据和重复大中转包不随Git发布；原件保留旧机，不影响科学结果的解释和定位。仅在旧机生成但未上传的ZIP不作为新电脑下载来源，旧Drive核心包也不替代最新Git。

本次恢复工具的离线测试通过，不代表新机器已获准登录或真实服务器下载已经验收。最小验收是新目录能读到上述五个入口、列出实际服务器路径且默认计划不联网；真正取回后再保存逐文件哈希回执。

[本次换机离线验收](audits/git_handoff_acceptance_20261029.json)：在新的导出目录通过70项存储测试、1016项Git附件哈希核对，以及103/104的默认不联网取回计划检查；真实服务器下载仍需新电脑配置凭据后验收。
