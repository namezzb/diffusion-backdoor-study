#!/bin/bash
# BackdoorDM 全量复现总控脚本
# 按依赖关系和时间排序执行
#
# 执行策略:
#   阶段A: 环境准备 + 配置修复 + CLIP 下载(后台)
#   阶段B: 快速 T2I 攻击 (03)
#   阶段C: 慢速 T2I 攻击 (04)
#   阶段D: 无条件攻击 (05)
#   阶段E: 超长攻击 (05b VillanCond, 05c BiBadDiff)
#   阶段F: 全量评估 (06, 07)
#   阶段G: 防御实验 (08, 09, 10)
#
# 用法: nohup bash run_all.sh > /opt/data/private/BackdoorDM/logs/run_all.log 2>&1 &
# 注意: 不用 conda run (在此服务器返回127)，各子脚本内部已用直接 Python 路径

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MASTER_LOG="/opt/data/private/BackdoorDM/logs/master.log"
mkdir -p /opt/data/private/BackdoorDM/logs

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$MASTER_LOG"
}

log "========================================="
log "BackdoorDM Full Reproduction - START"
log "========================================="

# Phase A: Environment + Config Fix + CLIP Download (background)
log "--- Phase A: Environment ---"
bash "$SCRIPT_DIR/00_reconnect_and_verify.sh" 2>&1 | tee -a "$MASTER_LOG"
bash "$SCRIPT_DIR/01c_apply_paper_fixes.sh" 2>&1 | tee -a "$MASTER_LOG"
bash "$SCRIPT_DIR/02c_fix_eval_config.sh" 2>&1 | tee -a "$MASTER_LOG"
bash "$SCRIPT_DIR/02b_download_clip_large.sh" 2>&1 | tee -a "$MASTER_LOG"
bash "$SCRIPT_DIR/02_download_models.sh" 2>&1 | tee -a "$MASTER_LOG"

# Phase B: Fast T2I attacks
log "--- Phase B: Fast T2I Attacks ---"
bash "$SCRIPT_DIR/03_attack_t2i_fast.sh" 2>&1 | tee -a "$MASTER_LOG"

# Phase C: Slow T2I attacks
log "--- Phase C: Slow T2I Attacks ---"
bash "$SCRIPT_DIR/04_attack_t2i_slow.sh" 2>&1 | tee -a "$MASTER_LOG"

# Phase D: Unconditional attacks
log "--- Phase D: Unconditional Attacks ---"
bash "$SCRIPT_DIR/05_attack_uncond.sh" 2>&1 | tee -a "$MASTER_LOG"

# Phase E: Very long attacks
log "--- Phase E: Long Attacks ---"
bash "$SCRIPT_DIR/05b_attack_villan_cond.sh" 2>&1 | tee -a "$MASTER_LOG"
bash "$SCRIPT_DIR/05c_attack_bibaddiff.sh" 2>&1 | tee -a "$MASTER_LOG"

# Phase F: Evaluation
log "--- Phase F: Evaluation ---"
bash "$SCRIPT_DIR/06_eval_t2i.sh" 2>&1 | tee -a "$MASTER_LOG"
bash "$SCRIPT_DIR/07_eval_uncond.sh" 2>&1 | tee -a "$MASTER_LOG"

# Phase G: Defense
log "--- Phase G: Defense ---"
bash "$SCRIPT_DIR/08_defense_t2ishield.sh" 2>&1 | tee -a "$MASTER_LOG"
bash "$SCRIPT_DIR/09_defense_elijah_terd.sh" 2>&1 | tee -a "$MASTER_LOG"
bash "$SCRIPT_DIR/10_defense_input_level.sh" 2>&1 | tee -a "$MASTER_LOG"

log "========================================="
log "BackdoorDM Full Reproduction - COMPLETE"
log "========================================="
