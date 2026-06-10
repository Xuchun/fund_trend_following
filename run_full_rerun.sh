#!/bin/bash
# Full rerun: Baseline → MC → Walk-Forward → Regime → Perturbations
# Run from project root: bash run_full_rerun.sh

set -e
cd /Users/xuchun/Documents/fund_trend_following

PYTHON=/Users/xuchun/anaconda3/bin/python3
LOG=results/v1/rerun_$(date +%Y%m%d_%H%M%S).log

log() { echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG"; }

log "=== Full Rerun Started ==="
log "Log: $LOG"

# ── Step 1: Baseline backtest (downloads & caches data, runs full backtest) ──
log "STEP 1/5: Baseline backtest (mode=full, 2004-01-01 → today) ..."
$PYTHON src/scripts/02_run_baseline.py --mode full 2>&1 | tee -a "$LOG"
log "STEP 1 DONE ✓"

# ── Step 2: Monte Carlo ───────────────────────────────────────────────────────
log "STEP 2/5: Monte Carlo risk analysis ..."
$PYTHON src/scripts/05_run_montecarlo.py 2>&1 | tee -a "$LOG"
log "STEP 2 DONE ✓"

# ── Step 3: Walk-Forward ──────────────────────────────────────────────────────
log "STEP 3/5: Walk-Forward validation ..."
$PYTHON src/scripts/08_run_walkforward.py 2>&1 | tee -a "$LOG"
log "STEP 3 DONE ✓"

# ── Step 4: Regime analysis ───────────────────────────────────────────────────
log "STEP 4/5: Market regime analysis ..."
$PYTHON src/scripts/09_run_regime.py 2>&1 | tee -a "$LOG"
log "STEP 4 DONE ✓"

# ── Step 5: Parameter sensitivity (all perturbations) ────────────────────────
log "STEP 5/5: Parameter sensitivity analysis (all params) ..."
$PYTHON src/scripts/run_all_perturbations.py 2>&1 | tee -a "$LOG"
log "STEP 5 DONE ✓"

log "=== All Steps Complete ==="
log "Results in: results/v1/"
