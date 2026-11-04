# LoRA 融合后门阅读清单建档

日期：2026-11-04。用户要求把本聊天的新 paper list 保存为可标记阅读状态的 Markdown。

## 交付

- [TASK.md](TASK.md) 同时作为阅读清单与唯一阅读状态入口，包含第一轮 8 篇、第二轮 4 篇、BadMerging 回看项及 DiffSafeMerge 暂缓说明。
- 每篇提供标准 Markdown 复选框、论文链接、阅读重点、问题、完成日期和笔记位置；新增论文初始全部未读，回看项初始未完成。
- 保留 LoBAM 的分类任务边界、LoRango 的双资产权限、K-LoRA 的动态选择性质与论文发表状态说明。
- [论文导航](../../../papers/README.md)和[任务导航](../README.md)添加入口；导航页不复制阅读状态。

## 验证

文档一致性检查通过：新增条目编号为 01–12；共 13 个未勾选框、阅读日期和笔记栏（含回看项），没有预先标记已读；13 个论文链接均为独立 HTTPS 地址；清单内本地链接与两个导航入口均可解析。Git diff 空白检查通过。

最初建档仅将清单落盘；随后用户追加授权下载全部论文到 Zotero 并统一分类，执行结果如下。未复现论文或运行 GPU 实验，现有实验任务、运行配置和项目指针保持原样。

## Zotero 收纳与附件验证

- 分类：`Idea1-Merge Backdoor / LoRA 融合后门阅读清单`，key `PW25S7NF`。共 14 个独立论文条目，每篇恰好 1 个 PDF；12 篇新阅读项、BadMerging 回看项与 DiffSafeMerge 暂缓项全部收录。
- 复用原有 BadMerging、BackdoorDM、MasqLoRA 的条目与附件；新增其他 11 篇。原有分类归属保留，阅读复选框未改变。12 份 PDF 为 Zotero 存储附件，BadMerging 与 BackdoorDM 保留原有本地文件链接。
- Zotero MCP 的附件请求长时间占用接口；改用官方 arXiv 下载和本机 Zotero Connector 导入。LoRA、ZipLoRA 的已有书目通过桌面端补附件；最终逐项复核父子对应关系。
- arXiv 的系统解析地址与公共 DNS 不同；使用公共 DNS 返回的 `151.101.3.42` 进行该次 HTTPS 连接，保留主机名及证书校验，没有修改系统 DNS。
- 逐一验证本地文件存在、PDF 文件头、PyMuPDF 可解析、首页对应标题与 arXiv 版本；计算字节数、页数及 SHA-256。合计 289,727,777 字节。
- Zotero 桌面端可见目标分类及 PDF；云端提示文件配额已满，部分附件不能上传，其他数据继续同步。完成状态指本机下载归档，不声明跨设备附件已同步完成。
- 清单已加入 14 组 Zotero 条目／PDF 链接及下载版本。PDF 到位不代表完成用户阅读、方法复现或科研验证。

### 附件核验记录

| 论文 | arXiv 版本 | 条目 key | 附件 key | 页数 | 字节数 | SHA-256 |
|---|---|---|---|---:|---:|---|
| LoRA | arXiv:2106.09685v2 | `GZCXX3EZ` | `YF8CXQSZ` | 26 | 1609513 | `e9a0d3128767db616085dc0f4e6e455e672e89af823e8ed1282793682787395a` |
| ZipLoRA | arXiv:2311.13600v2 | `MAGWM48H` | `MCZHLY3X` | 17 | 69959271 | `4ba189781711aa01ff4ac0f59c5fdaf79eceb35bdfc8f43a4daf28fc5792c046` |
| LoBAM | arXiv:2411.16746v4 | `G93DEYMN` | `QL89VLQP` | 11 | 1361829 | `928a49a9b57525b14f8b38d4d656ff0375984c50bbd8a1be671ce948f39542d3` |
| MasqLoRA | arXiv:2602.21977v4 | `XDM5PN38` | `EII5MH2E` | 10 | 6302770 | `bcc1c6366c42e6abd52d42628b8e0b00ad444fed5240814f94c38cf2a9a38122` |
| PoisonLoRA | arXiv:2606.09151v1 | `9KDZGWX4` | `JS5AZT6W` | 27 | 10301636 | `f46be512a9a013441251758ce6ee09627af8b68a676ca381742d5e852f588531` |
| LoRango | arXiv:2609.25884v1 | `5RC7JWJG` | `PCKCJRXU` | 17 | 9984637 | `2b758bc3285bc1813e8b153f744583b4b2a1823bfc571d62b44cc7c34d407b5f` |
| K-LoRA | arXiv:2502.18461v2 | `Z5TN6J5V` | `D6ZLSGPP` | 21 | 24022636 | `71eb4f70889f89c280aad7567763cc4aada1c32ceba2dee0c0474b531b630931` |
| BackdoorDM | arXiv:2502.11798v2 | `IXV6I955` | `GIV38BMS` | 44 | 8628592 | `50de2303124d6f218d3c3ff869f64612d305b82df4ccf4b000d969352943c251` |
| DreamBooth | arXiv:2208.12242v2 | `YAJCDG55` | `PGWS4TPC` | 25 | 23095080 | `fe33f0d2f768b83a094113bf2862db4d048c5a61ddf6b0283ae7c1b8f6f7d27c` |
| Mix-of-Show | arXiv:2305.18292v2 | `MUREBGUY` | `Z6NTR5JH` | 18 | 41912167 | `70c0600748d1b04523260f04c4313567b15b2fff884f14a2ee2cb872d05023b0` |
| LoRA.rar | arXiv:2412.05148v2 | `9NV3BGEG` | `NTA5FBLQ` | 19 | 50471698 | `66addd0bd3454b7f9bd834b5cad46a95dd3a4084eb76bfc279534c3f3a88424a` |
| SSR-Merge | arXiv:2606.10617v1 | `26C65U5R` | `YVER6L3U` | 20 | 36738901 | `375b7e4df9ee4fff94955de2f04df136270092f88071a43af05457eb6c540273` |
| BadMerging | arXiv:2408.07362v2 | `SW26W8HM` | `UNHWAQXN` | 20 | 3634583 | `309f6876e2955fa59c4510c8f631b9a72bfc9c475bf7bc4a5780c8d6cc60604d` |
| DiffSafeMerge | arXiv:2608.09445v1 | `2IFM2L3F` | `T7P7U7VU` | 17 | 1704464 | `c42e4aa57347de6772d5dc4f76e87de9b6a9a643a443f32c8dee42a6c81f8168` |

## LoRA 原文基础讲解

- 按用户要求读取本地 LoRA v2 的正文方法、实验与低秩分析，补读附录 H；渲染核对首页图 1 和第 4 页的公式、初始化及缩放说明。
- 讲解从线性层、全量微调与矩阵秩开始，覆盖冻结底座、训练 A/B、随机 A 与零 B 初始化、α/r 缩放、参数量与显存边界，以及推理时合入权重。
- 面向后续融合阅读，区分有效更新 BA 与 A/B 因子，说明多份更新相加与因子分别相加的交叉项差异；不把原文语言任务结果外推为 diffusion 实验结论。
- 更新清单的阅读方式为原文讲解加按需回看；保留未读复选框，不将助手阅读等同用户完成阅读。没有模型训练、GPU 实验或科研有效性验证。
