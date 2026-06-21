"""
Strategy 1.0 — Stocks-only backtest (2000-01-03 → 2026-06-15).
Same params as baseline; ETFs excluded from strategy pool.
Outputs to results/v1_stocks_only_2000/.
"""

import json
import logging
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "src"))

_env = _root / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import pandas as pd

from data.pipeline import compute_adj_prices
from data.universe import EXCLUDED_VOL_ETFS
from indicators.precompute import precompute_indicators
from backtest.engine import BacktestEngine
from reports.baseline import generate_baseline_report
from strategy.params import StrategyParams
from strategy.v1.strategy_v1 import StrategyV1

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

TIINGO_CACHE      = _root / "data" / "cache" / "tiingo"
EU_CSV            = _root / "data" / "tiingo_eligible_universe.csv"
META_SRC          = _root / "results" / "v1_unbiased_60m_2000" / "strategy_meta.json"
OUTPUT_DIR        = _root / "results" / "v1_stocks_only_2000"
MIN_ELIGIBLE_DAYS = 252
START, END        = "2000-01-03", "2026-06-15"
INITIAL_CAPITAL   = 10_000_000.0

BASE_PARAMS = StrategyParams(
    min_price=10.0, min_market_cap_b=2.0, min_adv_m=60.0,
    breakout_window=200, atr_period=20,
    stop_loss_multiplier=2.0, min_stop_distance_pct=0.005,
    trail_multiplier_r1=3.0, trail_multiplier_r3=3.0, trail_multiplier_r5=5.0,
    risk_per_trade=0.01, position_cap=0.05, heat_limit=0.10,
    correlation_window=60, correlation_threshold=0.70, correlation_reduction=0.50,
    volume_filter_multiplier=1.5, breakout_strength_min=0.0, gap_filter=0.025,
    commission_bps=3.0, slippage_bps=10.0, cash_proxy="SHY",
    regime_filter_enabled=True, bear_exempt_tickers=frozenset({"TLT", "GLD", "UUP"}),
)
_AUXILIARY = {BASE_PARAMS.cash_proxy, "SPY", BASE_PARAMS.regime_ticker}


def _etf_set() -> set[str]:
    meta = json.loads(META_SRC.read_text())
    return {e["ticker"] for e in meta.get("etf_universe", [])}


def _load_panel(tickers, start, end):
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    panel = {}
    for t in tickers:
        p = TIINGO_CACHE / f"{t.upper()}.parquet"
        if not p.exists():
            continue
        try:
            df = pd.read_parquet(p)
            df.index = pd.DatetimeIndex(df.index)
            df = df.sort_index().loc[s:e]
            if not df.empty:
                panel[t] = compute_adj_prices(df)
        except Exception as ex:
            logger.warning("Skip %s: %s", t, ex)
    return panel


def main():
    etfs = _etf_set()

    eu = pd.read_csv(EU_CSV)
    all_tickers = eu[eu["eligible_days"] >= MIN_ELIGIBLE_DAYS]["ticker"].tolist()
    all_tickers = [t for t in all_tickers if t not in EXCLUDED_VOL_ETFS]

    # ── stocks only ────────────────────────────────────────────────────────────
    universe = [t for t in all_tickers if t not in etfs]
    logger.info("Stocks-only universe: %d tickers", len(universe))

    load_list = sorted(set(universe) | _AUXILIARY)
    panel = _load_panel(load_list, START, END)

    strategy_tickers = [t for t in universe if t in panel and t not in _AUXILIARY]
    logger.info("Strategy pool (stocks): %d tickers", len(strategy_tickers))

    indicators = precompute_indicators({t: panel[t] for t in strategy_tickers}, BASE_PARAMS)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    params = replace(BASE_PARAMS, min_adv_m=60.0)

    print(f"\n{'='*65}")
    print(f"  Strategy 1.0 — STOCKS ONLY backtest")
    print(f"  Pool: {len(strategy_tickers):,} stocks  |  Period: {START} → {END}")
    print(f"{'='*65}\n")

    t0 = time.time()
    engine = BacktestEngine(
        strategy=StrategyV1(params), price_panel=panel,
        indicators=indicators, params=params, initial_capital=INITIAL_CAPITAL,
    )
    results = engine.run(START, END, strategy_tickers)
    logger.info("Done in %.1fs  (%d trades)", time.time() - t0, len(results.trade_log))

    spy_raw = panel.get("SPY")
    generate_baseline_report(results, spy_raw, OUTPUT_DIR)
    print(results.summary())
    print(f"\n✓ Output → {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
