"""Render the negative outcome from the separately diagnosed immutable evidence."""
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
diag_path = HERE / 'summary_record_hash_diagnosis_20261028.json'
assert sha(diag_path) == '91f252a70155cd9ea5455418daa723b6845a3dc4adef35655b0b557044ca855a'
diag = json.loads(diag_path.read_text())
assert diag['unexplained_hash_discrepancies'] == 0
obs_path = HERE / 'observation_103_20261028T111524087743Z-7268ad87/report.json'
assert sha(obs_path) == diag['input_report_sha256']
root = obs_path.parent / 'artifacts/run'
stages = {s: d['independent_metric_projection'] for s, d in diag['stage_diagnosis'].items()}
execution_counts = defaultdict(Counter)
for p in (root / 'operations').glob('*.json'):
    r = json.loads(p.read_text())['record']
    execution_counts[r['stage']][r['execution_id']] += 1
assert dict(execution_counts['dev']) == {'20261028T100528206667Z': 192}
accounting = diag['resource_accounting_from_persisted_receipts']
metrics = {'status': 'negative_dev_metrics_recomputed_integrity_defect_disclosed',
           'source_diagnosis_sha256': sha(diag_path), 'original_strict_audit_status': 'invalid',
           'confirm_opened': False, 'stages': stages, 'resources': accounting,
           'stage_execution_counts': dict(execution_counts)}
(HERE / 'terminal_metrics_20261028.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + '\n')

def yes(value): return '通过' if value else '失败'
def percent(value): return f'{100 * value:.2f}%'
def failure(candidate):
    parts = []
    for name, state in candidate['states'].items():
        if state['accuracy_drop_vs_clean'] > .05:
            parts.append(f"{name} ACC下降{100 * state['accuracy_drop_vs_clean']:.1f}pp")
        if state['clip_drop_vs_clean'] > 1:
            parts.append(f"{name} CLIP下降{state['clip_drop_vs_clean']:.6f}")
    return '；'.join(parts) or '—'

lines = ['# 直接 ASR 探索终态：未找到合格增益', '',
    '截至2026-10-28 19:15（上海），本轮在开发阶段按冻结规则结束：**624张搜索图＋192张开发图，共816张；0次梯度更新，独立确认未启动**。两名开发候选的主ASR均为33.33%，与同轮naive相同，且均未通过upload正常约束，因此没有合格赢家，不能宣称达到“超过baseline”的目标。', '',
    '**证据完整性例外必须与负结果一并保留：原严格审计为invalid。** 资源字典浅拷贝使643项summary记录哈希漂移；独立诊断已逐项精确解释这一字段差异，并从816条未改写的逐图记录复算全部数值指标与选择，均与原结果一致；这不把原审计改写成通过，也没有重新运行评分模型。', '',
    '## 冻结范围与停止依据', '',
    '- 设计ID：`tssa-direct-asr-near-naive-v1-2026-10-28`；manifest SHA256：`8e903452b19692a2e0716b623de03f83a77c3a1c8afbef58b883c8d7522837a6`。',
    '- 12个固定a/b候选，使用原FP32差分和q=0.95分组；搜索种子51000、开发种子52000，提示分离，DDIM25步、CFG7.5、512×512。',
    '- 主ASR是三个合并状态的等权平均；upload攻击完整单列，四个状态的正常ACC下降须≤5pp、CLIP cosine×100下降须≤1，参考均为同状态matched-clean。',
    '- 搜索按固定规则选中`uniform_075`与`a100_b075`；开发无正常合格且主ASR严格超过naive的候选，故停止，未生成或查看独立确认结果。',
    '- [冻结设计第5节](../../research/tssa_optimization_exploration_design_2026-10-28.md)禁止把未用额度自动转成新搜索；本轮不追加坐标、种子、更新或放宽阈值。', '',
    '## 全部搜索候选', '',
    '每个候选每状态4张触发、8张正常图；下表主ASR对应三个合并状态共12张触发图，worst为最低单状态ASR。', '',
    '| 候选 | (a,b) | 主ASR | 相对naive | worst ASR | upload ASR | 四态正常约束 | 未通过原因 |',
    '|---|---|---:|---:|---:|---:|---|---|']
for name, c in stages['search']['candidates'].items():
    lines.append(f"| {name} | {tuple(c['coefficients'])} | {percent(c['macro_asr'])} | {100*c['macro_difference_vs_naive']:+.2f}pp | {percent(c['worst_asr'])} | {percent(c['states']['upload']['asr'])} | {yes(c['normal_pass'])} | {failure(c)} |")
lines += ['', '`uniform_150`有7/12攻击成功，naive为6/12，即搜索点估计增加8.33pp；但它在Edev_0.08与upload各少1/8正常成功，下降12.5pp，不能认定合格提升。搜索正常合格的两个候选均仅4/12攻击成功，按事先允许搜索弱增益进入开发的规则评价，没有事后放宽门槛。', '',
    '## 开发结果', '',
    '| 候选 | 主ASR | Edev_0.08 | Edev_0.25 | Edev_0.50 | upload ASR | 四态正常约束 | 未通过原因 |',
    '|---|---:|---:|---:|---:|---:|---|---|']
for name, c in stages['dev']['candidates'].items():
    cells = [f"{c['states'][s]['attack_success']}/{c['states'][s]['attack_n']}" for s in ['Edev_0.08','Edev_0.25','Edev_0.50','upload']]
    lines.append(f"| {name} | {percent(c['macro_asr'])} | {' | '.join(cells)} | {yes(c['normal_pass'])} | {failure(c)} |")
lines += ['', 'naive自身也未通过upload CLIP门槛，这不降低候选对matched-clean的要求；两候选在开发集均没有主ASR增益，即使暂不看正常门槛也未超过naive。小样本与有限坐标只支持本轮局部负结果，不能证明整个两标量空间无解或任何新目标都无效。', '',
    '## 各状态正常指标与配对分组', '',
    '下表包含全部68个候选/阶段/状态；正常正确数分母为8，配对正常与额外正常各4，CLIP为cosine×100，下降为clean减candidate。全部逐种子、Wilson区间和配对计数见[完整指标JSON](terminal_metrics_20261028.json)，不把相关状态或seed当成独立语义样本。', '',
    '| 阶段 | 候选 | 状态 | 攻击成功 | 正常正确 | 配对正确 | 额外正确 | 正常CLIP | ACC下降pp | CLIP下降 | 正常约束 |',
    '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
for stage, summary in stages.items():
    for name, c in summary['candidates'].items():
        for state, v in c['states'].items():
            g = v['normal_groups']
            lines.append(f"| {stage} | {name} | {state} | {v['attack_success']}/{v['attack_n']} | {v['normal_correct']}/{v['normal_n']} | {g['paired_normal']['normal_correct']}/4 | {g['extra_normal']['normal_correct']}/4 | {v['normal_clip']:.6f} | {100*v['accuracy_drop_vs_clean']:.1f} | {v['clip_drop_vs_clean']:.6f} | {yes(v['normal_pass'])} |")
lines += ['', '## 实现缺陷与独立核对边界', '',
    '运行时`resource_record()`只复制最外层字典，`branch_nfe`仍指向后续持续更新的同一对象；逐图receipt写盘正确，但stage summary后来重算内存记录哈希时计数已经变化。恢复前171条由JSON加载的记录不共享对象，故第一项差异恰从search索引171开始。', '',
    '- search索引171–622共452项，只将内存假设副本的generation NFE改为该阶段结束值22650，即精确复现原summary哈希；dev索引0–190共191项对应32250，未解释差异0。',
    '- 816条原始receipt的自身哈希、任务及冻结输入一致；此前213条receipt原始字节未变，全部数值指标、正常门槛、排序、selection独立复算一致。',
    '- [原严格审计](independent_result_audit_816_20261028T1115Z.json)保持invalid；[逐项诊断](summary_record_hash_diagnosis_20261028.json)只是定位和影响核对，未修改原receipt、summary、selection或冻结manifest。',
    '- [远端PNG核对](final_PNG_hash_acceptance_816_20261028T1115Z.json)验证816张图片、341268220字节与receipt一致，且操作/图片目录恰对应这816项；这不等于独立模型复评分。',
    '- 19:36全部816张PNG（341268220字节）已回传本机并逐张核对SHA256，见[回传验收](final_images_816_20261028/resumed_retrieval_report.json)与[图像目录](final_images_816_20261028/images/)；首个整包240秒超时的证据保留，先验收271张再仅补传545张，未重新生成图片。', '',
    '## 中断、环境与实际成本', '',
    '- 103服务器经历17:21与17:44两次系统重启；171张已完成图被复用，只将唯一未完成行经人工审计恢复一次，失败证据与原claim均保留。',
    '- 驱动从550.54.14变为595.99.02；search/Edev_0.25/naive含重启前3图和恢复后9图，因此搜索阶段存在环境混合局限，不能宣称驱动变化没有影响。',
    '- 192张开发图全部来自恢复后的同一执行身份`20261028T100528206667Z`；模型、软件包、输入哈希保持冻结，但未另行补跑或检验跨驱动可重复性。',
    '- 完成816图、生成40800 branch-NFE、0 autograd、0更新；含失败为817次尝试、最多40850 branch-NFE（失败精确工作量未知，按≤50单列）。',
    '- 成功图的生成与评分计时合计5188.976秒（约1.441小时），峰值CUDA分配4844925440字节、预留6304038912字节；该时间不包含全部加载、网络、重启等待与失败开销，不能当作全部端到端耗时。',
    '- 19:15 SSH观察确认原与恢复进程均消失、无本项目GPU进程，GPU已释放；18:43连接拒绝和18:45网页状态是历史，不能覆盖19:15实际终态证据。', '',
    '## 结论与下一项工作', '',
    '当前证据未找到同时满足正常能力约束且ASR超过baseline的候选；旧v2的归零问题与本轮直接图像筛选负结果分别保留，不能混写成成功。本机后续版本已将资源计数改为独立快照，4项CPU回归（含旧代码负例）通过，未部署到已结束run；[旧版隔离重放](frozen_snapshot_diagnosis_replay_20261028.json)仍精确复现原invalid与643项差异，旧文件未改。下一步为同状态目标语义teacher假说准备独立、可证伪的小预算诊断；它仍是新假说，未运行，不能复用本轮剩余额度或直接称其有效。', '',
    '主要证据：[终态观察](observation_103_20261028T111524087743Z-7268ad87/report.json)、[完整指标](terminal_metrics_20261028.json)、[哈希缺陷诊断](summary_record_hash_diagnosis_20261028.json)、[原终态产物](observation_103_20261028T111524087743Z-7268ad87/artifacts/run/final_report.json)。']
(HERE / 'direct_ASR_negative_report_2026-10-28.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({'report': str(HERE / 'direct_ASR_negative_report_2026-10-28.md'), 'stage_execution_counts': dict(execution_counts), 'scientific_samples_added': 0}, ensure_ascii=False))
