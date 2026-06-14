"""
Strategy 1.0 backtest using Tiingo data — for comparison with Yahoo Finance results.

Purpose:
    Run the identical Strategy 1.0 baseline on Tiingo data (same universe, same
    params) to isolate the effect of data quality.  Results are saved to
    results/v1_tiingo/ and compared against results/v1/ (Yahoo baseline).

Usage:
    python src/scripts/05_run_v1_tiingo.py
    python src/scripts/05_run_v1_tiingo.py --mode etf   # quick sanity check
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "src"))

# Load .env
_env = _root / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from data.adapters.tiingo import TiingoAdapter
from data.pipeline import load_price_panel
from data.universe import ETF_TICKERS, fetch_sp900_tickers
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

TIINGO_CACHE = _root / "data" / "cache" / "tiingo"

BASELINE_PARAMS = StrategyParams(
    min_price               = 10.0,
    min_market_cap_b        = 2.0,
    min_adv_m               = 20.0,
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
)

DEFAULT_START = "2004-01-01"
DEFAULT_END   = "2026-06-13"


def parse_args():
    p = argparse.ArgumentParser(description="Strategy 1.0 backtest with Tiingo data")
    p.add_argument("--mode",   choices=["etf", "sp900", "full"], default="full")
    p.add_argument("--start",  default=DEFAULT_START)
    p.add_argument("--end",    default=DEFAULT_END)
    p.add_argument("--output", default="results/v1_tiingo/")
    p.add_argument("--initial-capital", default=10_000_000, type=float)
    return p.parse_args()


def main():
    args = parse_args()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    token = os.environ.get("TIINGO_API_TOKEN", "")
    if not token:
        logger.error("TIINGO_API_TOKEN not set. Add it to .env file.")
        sys.exit(1)

    # TiingoAdapter reads from local cache; no API calls made for already-downloaded tickers
    adapter = TiingoAdapter(api_token=token)
    params  = BASELINE_PARAMS

    # Universe: same S&P 900 as Yahoo baseline for a fair apples-to-apples comparison
    if args.mode == "etf":
        universe = sorted(ETF_TICKERS)
    else:
        universe = fetch_sp900_tickers()
        if not universe:
            logger.error("Failed to fetch S&P 900 tickers")
            sys.exit(1)
        universe = sorted(set(universe) | set(ETF_TICKERS))

    must_have        = {params.cash_proxy, "SPY", params.regime_ticker}
    download_tickers = sorted(set(universe) | must_have)

    print(f"\n{'='*65}")
    print(f"  Strategy 1.0 — Tiingo data")
    print(f"  Universe   : {len(universe)} tickers ({args.mode})")
    print(f"  Period     : {args.start} → {args.end}")
    print(f"  Cache      : {TIINGO_CACHE}")
    print(f"  Output     : {output_dir.resolve()}")
    print(f"{'='*65}\n")

    t0 = time.time()

    logger.info("Loading price data from Tiingo cache (%d tickers) …", len(download_tickers))
    panel = load_price_panel(
        download_tickers, adapter,
        start=args.start, end=args.end,
        cache_dir=TIINGO_CACHE,
    )
    logger.info("Loaded %d tickers in %.1fs", len(panel), time.time() - t0)

    auxiliary        = {params.cash_proxy, "SPY", params.regime_ticker}
    strategy_tickers = [t for t in universe if t in panel and t not in auxiliary]

    t1 = time.time()
    logger.info("Precomputing indicators …")
    indicators = precompute_indicators(
        {t: panel[t] for t in strategy_tickers}, params
    )
    logger.info("Indicators ready in %.1fs", time.time() - t1)

    t2 = time.time()
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
        time.time() - t2, len(results.daily_nav), len(results.trade_log),
    )

    spy_raw = panel.get("SPY")
    generate_baseline_report(results, spy_raw, output_dir)

    # ── Save strategy meta ───────────────────────────────────────────────────
    meta = {
        "id":             "v1_tiingo",
        "version":        "1.0-tiingo",
        "display_name":   "Strategy 1.0 (Tiingo)",
        "data_source":    "Tiingo",
        "backtest_start": args.start,
        "backtest_end":   args.end,
        "initial_capital": args.initial_capital,
        "params_anchor":  {k: getattr(params, k) for k in vars(StrategyParams()) if not k.startswith("_")},
    }
    (output_dir / "strategy_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )

    # ── Compare with Yahoo baseline ──────────────────────────────────────────
    m_tiingo = results.compute_metrics()
    print(f"\n{results.summary()}")

    yahoo_path = _root / "results" / "v1" / "metrics.json"
    if yahoo_path.exists():
        m_yahoo = json.loads(yahoo_path.read_text())

        print(f"\n{'='*65}")
        print(f"  数据源对比：Yahoo Finance  vs  Tiingo（策略1.0，相同参数）")
        print(f"{'='*65}")
        print(f"  {'指标':<22} {'Yahoo':>12} {'Tiingo':>12} {'变化':>10}")
        print(f"  {'-'*58}")

        rows = [
            ("CAGR",          m_yahoo.get("cagr", 0),             m_tiingo["cagr"],             ".2%"),
            ("Sharpe",        m_yahoo.get("sharpe", 0),           m_tiingo["sharpe"],           ".3f"),
            ("Sortino",       m_yahoo.get("sortino", 0),          m_tiingo["sortino"],          ".3f"),
            ("最大回撤",       m_yahoo.get("max_drawdown", 0),     m_tiingo["max_drawdown"],     ".2%"),
            ("年化波动率",      m_yahoo.get("annual_vol", 0),      m_tiingo["annual_vol"],       ".2%"),
            ("胜率",           m_yahoo.get("win_rate", 0),         m_tiingo.get("win_rate", 0), ".1%"),
            ("Profit Factor",  m_yahoo.get("profit_factor", 0),   m_tiingo.get("profit_factor", 0), ".2f"),
            ("总交易笔数",     m_yahoo.get("num_trades", 0),       m_tiingo.get("num_trades", 0), ".0f"),
            ("平均持仓天数",   m_yahoo.get("avg_holding_days", 0), m_tiingo.get("avg_holding_days", 0), ".1f"),
        ]

        for label, v_yahoo, v_tiingo, fmt in rows:
            delta = v_tiingo - v_yahoo
            sign  = "+" if delta >= 0 else ""
            print(f"  {label:<22} {v_yahoo:>{12}{fmt}} {v_tiingo:>{12}{fmt}} {sign}{delta:{fmt}}")

        print(f"{'='*65}")
        print(f"  注：两者使用完全相同的策略参数和 S&P900 标的范围")
        print(f"      差异 = 纯数据质量影响（Yahoo vs Tiingo）")
        print(f"{'='*65}\n")

    total = time.time() - t0
    print(f"\n✓ 完成。总耗时 {total:.1f}s  →  {output_dir.resolve()}")


if __name__ == "__main__":
    main()
