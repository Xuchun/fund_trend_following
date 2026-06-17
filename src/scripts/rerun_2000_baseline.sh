#!/usr/bin/env bash
# Full rerun for v1_unbiased_60m_2000 baseline.
# Steps: incremental data update → backtest → diagnostics
# Run from project root:  bash src/scripts/rerun_2000_baseline.sh

set -e
PYTHON=/Users/xuchun/anaconda3/bin/python3
ROOT=/Users/xuchun/Documents/fund_trend_following
LOG=$ROOT/results/v1_unbiased_60m_2000/rerun_$(date +%Y%m%d_%H%M%S).log
cd "$ROOT"

NEW_END="2026-06-16"   # latest date available in Tiingo API as of 2026-06-17

echo "[$(date +%H:%M:%S)] === Baseline Rerun Started (end=$NEW_END) ===" | tee "$LOG"

# ── Step 1: Incremental data update ──────────────────────────────────────────
echo "[$(date +%H:%M:%S)] STEP 1/3: Incremental Tiingo data update to $NEW_END ..." | tee -a "$LOG"
$PYTHON - <<'PYEOF' 2>&1 | tee -a "$LOG"
import os, sys, time
import pandas as pd
from pathlib import Path

ROOT = Path('/Users/xuchun/Documents/fund_trend_following')
sys.path.insert(0, str(ROOT / 'src'))

# Load .env
for line in (ROOT / '.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('=')
        os.environ.setdefault(k.strip(), v.strip())

from data.adapters.tiingo import TiingoAdapter
from data.pipeline import load_price_data
from data.universe import EXCLUDED_VOL_ETFS

CACHE_DIR = ROOT / 'data' / 'cache' / 'tiingo'
EU_CSV    = ROOT / 'data' / 'tiingo_eligible_universe.csv'
NEW_END   = '2026-06-16'
MIN_ELIGIBLE_DAYS = 252

eu = pd.read_csv(EU_CSV)
tickers = eu[eu['eligible_days'] >= MIN_ELIGIBLE_DAYS]['ticker'].tolist()
tickers = [t for t in tickers if t not in EXCLUDED_VOL_ETFS]
tickers = sorted(set(tickers) | {'SPY', 'SHY'})

print(f'Universe tickers to update: {len(tickers)}')

adapter = TiingoAdapter(
    api_token=os.environ['TIINGO_API_TOKEN'],
    request_delay=0.25,
)

updated = skipped = failed = 0
t0 = time.time()
new_end_ts = pd.Timestamp(NEW_END)

for i, ticker in enumerate(tickers, 1):
    path = CACHE_DIR / f'{ticker.upper()}.parquet'
    if not path.exists():
        skipped += 1
        continue
    try:
        df = pd.read_parquet(path)
        df.index = pd.DatetimeIndex(df.index)
        last_date = df.index.max()
        if last_date >= new_end_ts:
            skipped += 1
            continue
        load_price_data(ticker, adapter, start='1996-01-01', end=NEW_END,
                        cache_dir=CACHE_DIR, force_refresh=False)
        updated += 1
        if i % 200 == 0 or updated <= 5:
            elapsed = time.time() - t0
            eta = elapsed / i * (len(tickers) - i)
            print(f'  [{i}/{len(tickers)}] {ticker}: {last_date.date()}→{NEW_END}  '
                  f'updated={updated} skipped={skipped} failed={failed}  '
                  f'ETA {eta/60:.1f}min')
    except Exception as e:
        failed += 1
        if failed <= 10:
            print(f'  FAILED {ticker}: {e}')

print(f'\nData update complete: updated={updated}, skipped={skipped}, failed={failed}')
print(f'Elapsed: {(time.time()-t0)/60:.1f} min')
PYEOF
echo "[$(date +%H:%M:%S)] STEP 1 DONE ✓" | tee -a "$LOG"

# ── Step 2: Full backtest ─────────────────────────────────────────────────────
echo "[$(date +%H:%M:%S)] STEP 2/3: Running backtest 2000-01-03 → $NEW_END ..." | tee -a "$LOG"
$PYTHON src/scripts/10_run_v1_2000.py --end "$NEW_END" 2>&1 | tee -a "$LOG"
echo "[$(date +%H:%M:%S)] STEP 2 DONE ✓" | tee -a "$LOG"

# ── Step 3: Diagnostics ───────────────────────────────────────────────────────
echo "[$(date +%H:%M:%S)] STEP 3/3: Running diagnostics ..." | tee -a "$LOG"
$PYTHON src/scripts/04_run_diagnostics.py \
    --results-dir results/v1_unbiased_60m_2000 \
    --output results/v1_unbiased_60m_2000/diagnostics.json \
    2>&1 | tee -a "$LOG"
echo "[$(date +%H:%M:%S)] STEP 3 DONE ✓" | tee -a "$LOG"

echo "[$(date +%H:%M:%S)] === All Steps Complete. Log: $LOG ===" | tee -a "$LOG"
