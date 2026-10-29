# 定位中断：追加修订与独立审阅

**独立审阅通过，服务器无GPU身份验证通过。** [签名批准](amendment_approval.json)及[公钥](amendment_reviewer.pub)绑定原manifest、原源码、补丁和启动器；本机复跑55项测试通过，2026-10-29 21:37服务器记录受审修订并启动原run的CPU准备。

服务器只读回执显示 `control:magnitude` 为 started 且该单元前向预留为0；账本既有106240次前向与415个完整单元不变。[中断回执](server103_localization_interruption_20261029.json)及服务器只读复核显示幅值mask有196路径、56空路径、6142208个非空坐标，非空坐标无负数、重复或越界。

原 `magnitude_coordinates` 在未选中参数路径保存空列表，原 `intervene_once` 却禁止任何空路径；因此该掩码符合幅值选择但在第一条前向预留前被错误拒绝。补丁保留原始空路径和mask字节，只将空路径作为干预时的无操作项；整体全空、重复、负值及越界仍拒绝，非顺序的唯一坐标保持顺序。

| 对象 | SHA-256 |
|---|---|
| 原冻结 manifest | `c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa` |
| 原始 `intervene.py`，保持未修改 | `8c1347f64ecfa517acde07361e6b8d0e7353b1be68b91ed65071d8636fd4ea18` |
| 服务器原始 `magnitude.mask.json` | `58f1d9ca47f472d44090b509ca6e84cdbcb618a7040ecff3594133b7ddcd0f88` |
| [独立补丁模块](intervene_patch.py) | `719e9620984e988e18ae0c78fdf5e269b874a25be5dc9b4ce6cf557fde967e1a` |
| [追加修订启动器](amendment_launcher.py) | `6775d51ee6ab0853417ed5f7d02602a3d16ad07bc2d94360371532a07c7d6ed1` |

启动器检查reviewer单独签署的修订记录、原manifest和全部冻结源码、补丁、启动器与reviewer公钥的实际哈希；随后调用原 `preflight`，在现有run记录修订事件，并仅以内存模块加载独立补丁。原 `main` 和确认阶段 `bindings` 保持原有源码哈希校验，定位完成后仍执行selection及mask重算，CPU后的资源许可门禁也保持启用。

审阅者应生成专用一次性Ed25519密钥并通过独立可信渠道给出公钥文件SHA-256；私钥留在审阅者本机，不能上传或复用用户已有SSH私钥。以下JSON须按最终实际哈希填写并由审阅者以 `ssh-keygen -Y sign -n tcl-amendment` 签名，启动器以 `--reviewer-key-sha256` 接收独立可信指纹并验证签名。

```json
{
  "decision": "approved", "reviewer": "<审阅者标识>", "task_id": "TCL-20261029-01",
  "run_id": "tcl-20261029-01-v1", "manifest_sha256": "c597deebc3c2256401ee89b47f96ba9caa4bd92502019e3f257cfde7cddd1aaa",
  "target_module": "scripts/merging/trigger_contrast_localization/intervene.py",
  "original_sha256": "8c1347f64ecfa517acde07361e6b8d0e7353b1be68b91ed65071d8636fd4ea18",
  "patched_sha256": "719e9620984e988e18ae0c78fdf5e269b874a25be5dc9b4ce6cf557fde967e1a",
  "launcher_sha256": "6775d51ee6ab0853417ed5f7d02602a3d16ad07bc2d94360371532a07c7d6ed1",
  "reviewer_key_sha256": "<公钥文件SHA256>"
}
```

上线前先用 `--verify-only` 对实际服务器原目录、签名和所有身份做无GPU验证；每次恢复前重新只读核对账本、mask哈希及started单元，若出现任何不确定前向，先按原冻结处置流程审计，不自动重算。无需为本次0预留的幅值单元调用 `recover`；确认该状态仍成立后，修订后的 `localize` 复用已完成单元并从该单元继续，剩余预算不变。

本机55项测试通过，包括原源码与签名补丁同时通过 `--verify-only`、签名与文件篡改拒绝、空路径及无序坐标语义、带已完成账本的断点续算和selection重算；测试签名为临时假审阅，不是实际批准。修订尚未审阅或部署，未修改服务器、原manifest或原冻结源码。
