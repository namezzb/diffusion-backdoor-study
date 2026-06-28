#!/bin/bash
# Fix critical bugs in uncond attack methods before Phase D
# Deploy to: /opt/data/private/BackdoorDM/
# Run: bash 30_fix_uncond_attacks.sh

set -e
cd /opt/data/private/BackdoorDM

PYTHON=/opt/data/private/miniconda3/envs/eviledit/bin/python
LOG=logs/fix_uncond_attacks.log
echo "[$(date)] Starting uncond attack bug fixes" > $LOG

# ============================================================
# 1. InviBackdoor: fix device=0 hardcode + trigger batch bug + result dir
# ============================================================
INVI="attack/uncond_gen/invi_backdoor/invi_backdoor.py"
echo "[$(date)] Fixing InviBackdoor..." >> $LOG

cp "$INVI" "${INVI}.bak"

# Fix 1a: device=0 -> accelerator.device for delta initialization
# The delta is created before accelerator is available in train_loop,
# so we use model.device_ids[0] which IS available
sed -i 's/delta = torch.zeros((1, 3, config.trigger_size, config.trigger_size), requires_grad=True, device=0)/delta = torch.zeros((1, 3, config.trigger_size, config.trigger_size), requires_grad=True, device=accelerator.device)/' "$INVI"

# Fix 1b: delta_noise .to(0) -> .to(accelerator.device)
sed -i 's/delta_noise = torch.randn((config.trigger_size, 3, config.trigger_size, config.trigger_size)).to(0)/delta_noise = torch.randn((bs, 3, config.trigger_size, config.trigger_size)).to(accelerator.device)/' "$INVI"

# Fix 1c: delta_target .to(0) -> .to(accelerator.device)
sed -i 's/delta_target = dsl.target.repeat(config.trigger_size, 1, 1, 1).detach().to(0)/delta_target = dsl.target.repeat(bs, 1, 1, 1).detach().to(accelerator.device)/' "$INVI"

# Fix 1d: poison_delta uses delta_noise which now has correct batch dim
# delta_output model call should use bs not config.trigger_size for timesteps
sed -i 's/delta_output = model(poison_delta, torch.tensor(\[i\] \* delta_noise.shape\[0\])/delta_output = model(poison_delta, torch.tensor([i] * poison_delta.shape[0])/' "$INVI"

# Fix 1e: result -> results in setup() MODE_RESUME branch
sed -i "s|os.path.join('result', args.result, config_file)|os.path.join('results', args.result, config_file)|" "$INVI"
sed -i "s|setattr(args, \"result_dir\", os.path.join('result', args.result))|setattr(args, \"result_dir\", os.path.join('results', args.result))|g" "$INVI"

echo "[$(date)] InviBackdoor fixes applied" >> $LOG

# ============================================================
# 2. TrojDiff: fix RGB/RGBA check + config->args in error messages
# ============================================================
TROJ="attack/uncond_gen/trojdiff/trojdiff.py"
echo "[$(date)] Fixing TrojDiff..." >> $LOG

cp "$TROJ" "${TROJ}.bak"

# Fix 2a: 'RGB' or 'RGBA' always True -> proper check
sed -i "s/if target_img.mode == 'RGB' or 'RGBA':/if target_img.mode in ('RGB', 'RGBA'):/" "$TROJ"

# Fix 2b: config.batch -> args.batch and config.dataset -> args.dataset in error messages
sed -i 's/raise ValueError(f"batch size {config.batch} should be divisible to {bs} for dataset {config.dataset}")/raise ValueError(f"batch size {args.batch} should be divisible to {bs} for dataset {args.dataset}")/' "$TROJ"
sed -i 's/raise ValueError(f"batch size {config.batch} should be smaller or equal to {bs} for dataset {config.dataset}")/raise ValueError(f"batch size {args.batch} should be smaller or equal to {bs} for dataset {args.dataset}")/' "$TROJ"

echo "[$(date)] TrojDiff fixes applied" >> $LOG

# ============================================================
# 3. BadDiffusion: fix config->args in error messages
# ============================================================
BADD="attack/uncond_gen/bad_diffusion/bad_diffusion.py"
echo "[$(date)] Fixing BadDiffusion..." >> $LOG

cp "$BADD" "${BADD}.bak"

# Fix 3a: config.batch -> args.batch and config.dataset -> args.dataset
sed -i 's/raise ValueError(f"batch size {config.batch} should be divisible to {bs} for dataset {config.dataset}")/raise ValueError(f"batch size {args.batch} should be divisible to {bs} for dataset {args.dataset}")/' "$BADD"
sed -i 's/raise ValueError(f"batch size {config.batch} should be smaller or equal to {bs} for dataset {config.dataset}")/raise ValueError(f"batch size {args.batch} should be smaller or equal to {bs} for dataset {args.dataset}")/' "$BADD"

echo "[$(date)] BadDiffusion fixes applied" >> $LOG

# ============================================================
# 4. Verify all fixes
# ============================================================
echo "[$(date)] Verifying fixes..." >> $LOG

echo "--- InviBackdoor: device hardcode check ---" >> $LOG
grep -n "device=0\|\.to(0)" "$INVI" >> $LOG 2>&1 || echo "  OK: No device=0 hardcode found" >> $LOG

echo "--- InviBackdoor: trigger batch dim check ---" >> $LOG
grep -n "config.trigger_size, 3, config.trigger_size" "$INVI" >> $LOG 2>&1 || echo "  OK: trigger_size batch dim fixed" >> $LOG

echo "--- TrojDiff: RGB/RGBA check ---" >> $LOG
grep -n "mode == 'RGB' or 'RGBA'" "$TROJ" >> $LOG 2>&1 || echo "  OK: RGB/RGBA check fixed" >> $LOG

echo "--- TrojDiff: config.batch check ---" >> $LOG
grep -n "config.batch" "$TROJ" >> $LOG 2>&1 || echo "  OK: config.batch fixed" >> $LOG

echo "--- BadDiffusion: config.batch check ---" >> $LOG
grep -n "config.batch" "$BADD" >> $LOG 2>&1 || echo "  OK: config.batch fixed" >> $LOG

# ============================================================
# 5. Syntax check
# ============================================================
echo "[$(date)] Running syntax checks..." >> $LOG
$PYTHON -c "import py_compile; py_compile.compile('$INVI', doraise=True)" 2>&1 >> $LOG && echo "  InviBackdoor: syntax OK" >> $LOG || echo "  InviBackdoor: SYNTAX ERROR!" >> $LOG
$PYTHON -c "import py_compile; py_compile.compile('$TROJ', doraise=True)" 2>&1 >> $LOG && echo "  TrojDiff: syntax OK" >> $LOG || echo "  TrojDiff: SYNTAX ERROR!" >> $LOG
$PYTHON -c "import py_compile; py_compile.compile('$BADD', doraise=True)" 2>&1 >> $LOG && echo "  BadDiffusion: syntax OK" >> $LOG || echo "  BadDiffusion: SYNTAX ERROR!" >> $LOG

echo "[$(date)] All fixes complete" >> $LOG
echo "=== Fix Summary ==="
cat $LOG
