#!/usr/bin/env bash
# Rerun perturbation sweeps + 2D heatmaps for v1_unbiased_60m_2000
# using the updated rounding-based share sizing (math.floor(x + 0.5))
# Run from project root:
#   nohup bash src/scripts/rerun_perturb_heatmap.sh > /tmp/rerun_ph.log 2>&1 &

set -e
PYTHON=/Users/xuchun/anaconda3/bin/python3
ROOT=/Users/xuchun/Documents/fund_trend_following
LOG=$ROOT/results/v1_unbiased_60m_2000/rerun_perturb_heatmap_$(date +%Y%m%d_%H%M%S).log
cd "$ROOT"

echo "[$(date +%H:%M:%S)] === Perturbation + Heatmap Rerun Started ===" | tee "$LOG"

# ── Step 1: Perturbation sweeps ───────────────────────────────────────────────
echo "[$(date +%H:%M:%S)] STEP 1/3: Perturbation sweeps..." | tee -a "$LOG"
$PYTHON src/scripts/run_all_perturbations_tiingo.py 2>&1 | tee -a "$LOG"
echo "[$(date +%H:%M:%S)] STEP 1 DONE ✓" | tee -a "$LOG"

# ── Step 2: 2D Heatmap A (breakout_window × stop_loss_multiplier) ─────────────
echo "[$(date +%H:%M:%S)] STEP 2/3: Heatmap A (breakout_window × stop_loss_multiplier)..." | tee -a "$LOG"
$PYTHON src/scripts/06_run_heatmap.py \
  --type 2d \
  --param1 breakout_window --values1 150,200,250,300 --int-values1 \
  --param2 stop_loss_multiplier --values2 1.5,2.0,2.5,3.0 \
  --metric sharpe \
  --start 2000-01-03 --is-end 2026-06-15 \
  --output-dir results/v1_unbiased_60m_2000/heatmap \
  2>&1 | tee -a "$LOG"
echo "[$(date +%H:%M:%S)] STEP 2 DONE ✓" | tee -a "$LOG"

# ── Step 3: 2D Heatmap B (breakout_window × trail_multiplier_r1) ──────────────
echo "[$(date +%H:%M:%S)] STEP 3/3: Heatmap B (breakout_window × trail_multiplier_r1)..." | tee -a "$LOG"
$PYTHON src/scripts/06_run_heatmap.py \
  --type 2d \
  --param1 breakout_window --values1 150,200,250,300 --int-values1 \
  --param2 trail_multiplier_r1 --values2 2.0,2.5,3.0,3.5,4.0 \
  --metric sharpe \
  --start 2000-01-03 --is-end 2026-06-15 \
  --output-dir results/v1_unbiased_60m_2000/heatmap \
  2>&1 | tee -a "$LOG"
echo "[$(date +%H:%M:%S)] STEP 3 DONE ✓" | tee -a "$LOG"

echo "[$(date +%H:%M:%S)] === All Steps Complete. Log: $LOG ===" | tee -a "$LOG"
