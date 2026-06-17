"""
Strategy 1.0 — Backtest starting 2000-01-03 (first trading day of 2000).

Outputs to results/v1_unbiased_60m_2000/.

Usage:
    /Users/xuchun/anaconda3/bin/python3 src/scripts/10_run_v1_2000.py
    /Users/xuchun/anaconda3/bin/python3 src/scripts/10_run_v1_2000.py --start 2000-01-03 --end 2026-06-15
"""

import argparse
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

TIINGO_CACHE      = _root / "data" / "cache" / "tiingo"
EU_CSV            = _root / "data" / "tiingo_eligible_universe.csv"
OUTPUT_DIR        = _root / "results" / "v1_unbiased_60m_2000"
META_TEMPLATE     = OUTPUT_DIR / "strategy_meta.json"

DEFAULT_START     = "2000-01-03"   # first trading day of 2000
DEFAULT_END       = "2026-06-15"
MIN_ELIGIBLE_DAYS = 252

BASE_PARAMS = StrategyParams(
    min_price               = 10.0,
    min_market_cap_b        = 2.0,
    min_adv_m               = 60.0,
    breakout_window         = 200,
    atr_period              = 20,
    stop_loss_multiplier    = 2.0,
    min_stop_distance_pct   = 0.005,
    trail_multiplier_r1     = 3.0,
    trail_multiplier_r3     = 3.0,
    trail_multiplier_r5     = 5.0,
    risk_per_trade          = 0.01,
    position_cap            = 0.05,
    heat_limit              = 0.10,
    correlation_window      = 60,
    correlation_threshold   = 0.70,
    correlation_reduction   = 0.50,
    volume_filter_multiplier = 1.5,
    breakout_strength_min   = 0.0,
    gap_filter              = 0.025,
    commission_bps          = 3.0,
    slippage_bps            = 10.0,
    cash_proxy              = "SHY",
    regime_filter_enabled   = True,
    bear_exempt_tickers     = frozenset({"TLT", "GLD", "UUP"}),
)

# Auxiliary tickers: not tradable strategy assets
_AUXILIARY = {BASE_PARAMS.cash_proxy, "SPY", BASE_PARAMS.regime_ticker}


def _load_panel_from_cache(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    start_ts = pd.Timestamp(start)
    end_ts   = pd.Timestamp(end)
    panel: dict[str, pd.DataFrame] = {}
    missing = 0
    for ticker in tickers:
        path = TIINGO_CACHE / f"{ticker.upper()}.parquet"
        if not path.exists():
            missing += 1
            continue
        try:
            df = pd.read_parquet(path)
            df.index = pd.DatetimeIndex(df.index)
            df = df.sort_index()
            df = df[(df.index >= start_ts) & (df.index <= end_ts)]
            if not df.empty:
                panel[ticker] = compute_adj_prices(df)
        except Exception as e:
            logger.warning("Could not read %s: %s", ticker, e)
    if missing:
        logger.warning("%d tickers not found in cache (skipped)", missing)
    return panel


def load_dynamic_universe() -> list[str]:
    eu = pd.read_csv(EU_CSV)
    tickers = eu[eu["eligible_days"] >= MIN_ELIGIBLE_DAYS]["ticker"].tolist()
    excluded = [t for t in tickers if t in EXCLUDED_VOL_ETFS]
    if excluded:
        logger.info("Excluding %d vol/inverse ETFs: %s", len(excluded), excluded)
    tickers = [t for t in tickers if t not in EXCLUDED_VOL_ETFS]
    logger.info("Dynamic universe (%d-day filter): %d tickers loaded from CSV",
                MIN_ELIGIBLE_DAYS, len(tickers))
    return sorted(tickers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start",           default=DEFAULT_START)
    ap.add_argument("--end",             default=DEFAULT_END)
    ap.add_argument("--initial-capital", default=10_000_000, type=float)
    args = ap.parse_args()

    t_total = time.time()

    universe = load_dynamic_universe()
    load_list = sorted(set(universe) | _AUXILIARY)

    logger.info("Loading price panel (%d tickers) from local cache …", len(load_list))
    t_load = time.time()
    panel = _load_panel_from_cache(load_list, args.start, args.end)
    logger.info("Loaded %d tickers in %.1fs", len(panel), time.time() - t_load)

    strategy_tickers = [t for t in universe if t in panel and t not in _AUXILIARY]
    logger.info("Strategy pool: %d tickers", len(strategy_tickers))

    t_ind = time.time()
    logger.info("Precomputing indicators …")
    indicators = precompute_indicators(
        {t: panel[t] for t in strategy_tickers}, BASE_PARAMS
    )
    logger.info("Indicators ready in %.1fs", time.time() - t_ind)

    # ── Run: ADV > $60M ──────────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    params = replace(BASE_PARAMS, min_adv_m=60.0)

    print(f"\n{'='*65}")
    print(f"  Strategy 1.0 — 2000-start Backtest")
    print(f"  Universe     : {len(universe):,} tickers loaded")
    print(f"  Strategy pool: {len(strategy_tickers):,} tickers")
    print(f"  ADV 门槛     : $60M (daily filter)")
    print(f"  Period       : {args.start} → {args.end}")
    print(f"  Output       : {OUTPUT_DIR}")
    print(f"{'='*65}\n")

    t1 = time.time()
    logger.info("Running backtest …")
    strategy = StrategyV1(params)
    engine   = BacktestEngine(
        strategy=strategy,
        price_panel=panel,
        indicators=indicators,
        params=params,
        initial_capital=args.initial_capital,
    )
    results = engine.run(args.start, args.end, strategy_tickers)
    logger.info(
        "Backtest done in %.1fs  (%d trading days, %d trades)",
        time.time() - t1, len(results.daily_nav), len(results.trade_log),
    )

    spy_raw = panel.get("SPY")
    generate_baseline_report(results, spy_raw, OUTPUT_DIR)

    m = results.compute_metrics()
    print(f"\n{results.summary()}")

    # ── Update strategy_meta.json ────────────────────────────────────────────
    existing_meta: dict = {}
    if META_TEMPLATE.exists():
        try:
            existing_meta = json.loads(META_TEMPLATE.read_text())
        except Exception:
            pass

    existing_meta.update({
        "backtest_start":  args.start,
        "backtest_end":    args.end,
        "initial_capital": args.initial_capital,
        "universe_total":  len(strategy_tickers),
        "universe_stocks": len([t for t in strategy_tickers
                                if t not in {e.get("ticker","") for e in existing_meta.get("etf_universe", [])}]),
        "universe_etfs":   len([t for t in strategy_tickers
                                if t in {e.get("ticker","") for e in existing_meta.get("etf_universe", [])}]),
        "params_anchor":   {k: getattr(params, k) for k in vars(StrategyParams()) if not k.startswith("_")},
    })
    META_TEMPLATE.write_text(json.dumps(
        existing_meta, ensure_ascii=False, indent=2,
        default=lambda x: sorted(x) if isinstance(x, (frozenset, set)) else str(x),
    ))
    logger.info("strategy_meta.json updated → %s", META_TEMPLATE)

    print(f"\n✓ 全部完成。总耗时 {time.time() - t_total:.1f}s")


if __name__ == "__main__":
    main()
