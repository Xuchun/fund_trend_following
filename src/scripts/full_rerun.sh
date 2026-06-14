#!/usr/bin/env bash
set -e
PYTHON=/Users/xuchun/anaconda3/bin/python3
ROOT=/Users/xuchun/Documents/fund_trend_following
LOG=$ROOT/results/v1/full_rerun_$(date +%Y%m%d_%H%M%S).log
cd "$ROOT"

echo "[$(date +%H:%M:%S)] === Full Rerun Started ===" | tee "$LOG"
echo "[$(date +%H:%M:%S)] Log: $LOG" | tee -a "$LOG"

# Step 1: Baseline backtest
echo "[$(date +%H:%M:%S)] STEP 1/6: Baseline backtest ..." | tee -a "$LOG"
$PYTHON src/scripts/02_run_baseline.py --mode full 2>&1 | tee -a "$LOG"
echo "[$(date +%H:%M:%S)] STEP 1 DONE ✓" | tee -a "$LOG"

# Step 2: Diagnostics
echo "[$(date +%H:%M:%S)] STEP 2/6: Diagnostics ..." | tee -a "$LOG"
$PYTHON src/scripts/04_run_diagnostics.py 2>&1 | tee -a "$LOG"
echo "[$(date +%H:%M:%S)] STEP 2 DONE ✓" | tee -a "$LOG"

# Step 3: Monte Carlo
echo "[$(date +%H:%M:%S)] STEP 3/6: Monte Carlo ..." | tee -a "$LOG"
$PYTHON src/scripts/05_run_montecarlo.py 2>&1 | tee -a "$LOG"
echo "[$(date +%H:%M:%S)] STEP 3 DONE ✓" | tee -a "$LOG"

# Step 4: Walk-Forward
echo "[$(date +%H:%M:%S)] STEP 4/6: Walk-Forward ..." | tee -a "$LOG"
$PYTHON src/scripts/08_run_walkforward.py 2>&1 | tee -a "$LOG"
echo "[$(date +%H:%M:%S)] STEP 4 DONE ✓" | tee -a "$LOG"

# Step 5: Regime + Stress
echo "[$(date +%H:%M:%S)] STEP 5/6: Regime + Stress ..." | tee -a "$LOG"
$PYTHON src/scripts/09_run_regime.py 2>&1 | tee -a "$LOG"
$PYTHON src/scripts/07_run_stress.py 2>&1 | tee -a "$LOG"
echo "[$(date +%H:%M:%S)] STEP 5 DONE ✓" | tee -a "$LOG"

# Step 6: Perturbation analysis (delete old JSONs first to force rerun)
echo "[$(date +%H:%M:%S)] STEP 6/6: Perturbation sweeps (delete old, rerun all) ..." | tee -a "$LOG"
rm -f "$ROOT"/results/v1/perturbation/*.json
$PYTHON src/scripts/run_all_perturbations.py 2>&1 | tee -a "$LOG"
echo "[$(date +%H:%M:%S)] STEP 6 DONE ✓" | tee -a "$LOG"

echo "[$(date +%H:%M:%S)] === All Steps Complete ===" | tee -a "$LOG"
