"""
Script: run the Strategy 1.0 baseline backtest and generate a full report.

Usage examples:
    # Fast: ETFs only (~21 tickers, uses cache)
    python src/scripts/02_run_baseline.py --mode etf

    # Full: S&P 500 + ETFs (first run takes 30-60 min to download)
    python src/scripts/02_run_baseline.py --mode full --start 2010-01-01

    # Custom date range and output directory
    python src/scripts/02_run_baseline.py \\
        --mode etf \\
        --start 2015-01-01 \\
        --end   2024-12-31 \\
        --initial-capital 10000000 \\
        --output results/baseline/

⚠  Yahoo Finance data limitations (apply to all results from this script):
    1. Survivorship bias: no delisted stocks → results may be 20-50% too high.
    2. Market cap not point-in-time: current cap used as proxy for historical.
    3. ETF inception dates not enforced: ETFs may appear before they existed.
    These biases disappear automatically when switching to a commercial adapter.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Allow running from project root: python src/scripts/02_run_baseline.py
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from data.adapters.yahoo import YahooFinanceAdapter
from data.pipeline import load_price_panel
from data.universe import ETF_TICKERS, fetch_sp500_tickers, fetch_sp900_tickers
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

# ── Baseline anchor parameters (design spec Section 1.2.1.1) ──────────────
# SHY used as cash proxy because it covers the full backtest period (2002+).
# SGOV only has data from 2022, which would leave pre-2022 cash earning 0%.
BASELINE_PARAMS = StrategyParams(
    min_price           = 10.0,
    min_market_cap_b    = 2.0,
    min_adv_m           = 20.0,
    breakout_window     = 100,
    atr_period          = 20,
    stop_loss_multiplier    = 2.0,
    min_stop_distance_pct   = 0.005,
    trail_multiplier_r1 = 2.0,
    trail_multiplier_r3 = 3.0,
    trail_multiplier_r5 = 5.0,
    risk_per_trade      = 0.01,
    position_cap        = 0.05,
    heat_limit          = 0.10,
    correlation_window      = 60,
    correlation_threshold   = 0.70,
    correlation_reduction   = 0.50,
    gap_filter          = 0.025,
    commission_bps      = 3.0,
    slippage_bps        = 10.0,
    cash_proxy          = "SHY",   # 1-3Y Treasury ETF; covers full backtest period
)

DEFAULT_START = "2004-01-01"
DEFAULT_END   = "2024-12-31"


# ── Argument parsing ───────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run Strategy 1.0 baseline backtest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--mode",
        choices=["etf", "sp500", "sp900", "full"],
        default="sp900",
        help=(
            "Universe: "
            "etf=21 ETFs only (fast sanity check), "
            "sp500=S&P500 large-caps only, "
            "sp900=S&P500+MidCap400 ~900 tickers [default, matches strategy spec], "
            "full=sp900+ETFs"
        ),
    )
    p.add_argument("--tickers", nargs="+", metavar="T",
                   help="Override --mode with an explicit ticker list")
    p.add_argument("--start",           default=DEFAULT_START, help="Start date YYYY-MM-DD")
    p.add_argument("--end",             default=DEFAULT_END,   help="End date YYYY-MM-DD")
    p.add_argument("--initial-capital", default=10_000_000, type=float,
                   help="Initial portfolio value in USD (default: $10,000,000)")
    p.add_argument("--output",          default="results/baseline/",
                   help="Output directory (default: results/baseline/)")
    p.add_argument("--force-download",  action="store_true",
                   help="Re-download all data even if cache exists")
    p.add_argument("--cash-proxy",      default=None,
                   help="Override cash proxy ticker (default: SHY)")
    p.add_argument("-v", "--verbose",   action="store_true",
                   help="Show debug-level logs")
    return p.parse_args()


# ── Universe building ──────────────────────────────────────────────────────

def build_universe(mode: str, custom_tickers: list[str] | None) -> list[str]:
    if custom_tickers:
        return [t.upper() for t in custom_tickers]

    if mode == "etf":
        return sorted(ETF_TICKERS)

    if mode == "sp500":
        sp500 = fetch_sp500_tickers()
        if not sp500:
            logger.error("Failed to fetch S&P 500 tickers; aborting")
            sys.exit(1)
        return sp500

    if mode == "sp900":
        # Recommended: S&P 500 (large-cap) + MidCap 400 ≈ 900 tickers
        # Covers market cap ~$2B and above, matching the strategy's $20亿 requirement.
        # Mid-caps are excluded from sp500 mode but often the best trend-following targets.
        sp900 = fetch_sp900_tickers()
        if not sp900:
            logger.error("Failed to fetch S&P 900 tickers; aborting")
            sys.exit(1)
        return sp900

    # full: sp900 + ETFs
    sp900 = fetch_sp900_tickers()
    if not sp900:
        logger.error("Failed to fetch tickers; aborting")
        sys.exit(1)
    return sorted(set(sp900) | set(ETF_TICKERS))


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    params = BASELINE_PARAMS
    if args.cash_proxy:
        from dataclasses import replace
        params = replace(params, cash_proxy=args.cash_proxy.upper())

    # ── Step 1: build universe ─────────────────────────────────────────────
    universe = build_universe(args.mode, args.tickers)
    logger.info("Universe: %d tickers  (mode=%s)", len(universe), args.mode)

    # Always download benchmark (SPY) and cash proxy (SHY/SGOV) even if not in universe
    must_have = {params.cash_proxy, "SPY"}
    download_tickers = sorted(set(universe) | must_have)

    # ── Step 2: download / load data ──────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Strategy 1.0 — Baseline Backtest")
    print(f"  Universe  : {len(universe)} tickers ({args.mode})")
    print(f"  Period    : {args.start} → {args.end}")
    print(f"  Capital   : ${args.initial_capital:,.0f}")
    print(f"  Cash proxy: {params.cash_proxy}")
    print(f"  Output    : {output_dir.resolve()}")
    print(f"{'='*60}\n")

    adapter = YahooFinanceAdapter()

    t0 = time.time()
    logger.info("Loading price data (%d tickers) …", len(download_tickers))
    panel = load_price_panel(
        download_tickers, adapter,
        start=args.start, end=args.end,
        force_refresh=args.force_download,
    )
    logger.info("Loaded %d tickers in %.1fs", len(panel), time.time() - t0)

    if len(panel) == 0:
        logger.error("No data loaded — check network connection and date range")
        sys.exit(1)

    # Tickers available for strategy (exclude SPY and cash proxy)
    auxiliary = {params.cash_proxy, "SPY"}
    strategy_tickers = [t for t in universe if t in panel and t not in auxiliary]
    if not strategy_tickers:
        logger.error("No strategy tickers with data — aborting")
        sys.exit(1)

    logger.info(
        "Strategy tickers with data: %d / %d",
        len(strategy_tickers), len(universe),
    )

    # ── Step 3: precompute indicators ─────────────────────────────────────
    t1 = time.time()
    logger.info("Precomputing indicators …")
    strategy_panel = {t: panel[t] for t in strategy_tickers}
    indicators = precompute_indicators(strategy_panel, params)
    logger.info(
        "Indicators computed for %d tickers in %.1fs",
        len(indicators), time.time() - t1,
    )

    # ── Step 4: run backtest ───────────────────────────────────────────────
    t2 = time.time()
    logger.info("Running backtest …")
    strategy = StrategyV1(params)
    engine   = BacktestEngine(
        strategy=strategy,
        price_panel=panel,           # full panel including SPY + cash proxy
        indicators=indicators,
        params=params,
        initial_capital=args.initial_capital,
    )
    results = engine.run(args.start, args.end, strategy_tickers)
    logger.info(
        "Backtest completed in %.1fs  (%d trading days, %d trades)",
        time.time() - t2, len(results.daily_nav), len(results.trade_log),
    )

    # ── Step 5: generate report ───────────────────────────────────────────
    t3 = time.time()
    logger.info("Generating report …")
    spy_raw = panel.get("SPY")
    generate_baseline_report(results, spy_raw, output_dir)
    logger.info("Report saved in %.1fs → %s", time.time() - t3, output_dir.resolve())

    # ── Step 6: print summary ─────────────────────────────────────────────
    print()
    print(results.summary())

    # SPY comparison side-by-side
    if spy_raw is not None:
        spy_adj = spy_raw["close"] * spy_raw["adj_factor"]
        spy_ret = spy_adj.pct_change().reindex(results.daily_nav.index).fillna(0.0)
        spy_nav = (1 + spy_ret).cumprod()
        n_days  = len(spy_nav)
        spy_cagr  = float(spy_nav.iloc[-1] ** (252 / n_days) - 1) if n_days > 1 else 0.0
        spy_vol   = float(spy_ret.std() * (252 ** 0.5))
        spy_sharpe = (float(spy_ret.mean()) * 252 - 0.05) / spy_vol if spy_vol > 0 else 0.0

        m = results.compute_metrics()
        print(f"\n{'='*55}")
        print(f"  对比 SPY (benchmark)")
        print(f"{'='*55}")
        print(f"  {'指标':<20} {'Strategy':>12} {'SPY':>12}")
        print(f"  {'-'*44}")
        print(f"  {'CAGR':<20} {m['cagr']:>+11.2%} {spy_cagr:>+11.2%}")
        print(f"  {'Annual Vol':<20} {m['annual_vol']:>11.2%} {spy_vol:>11.2%}")
        print(f"  {'Sharpe':<20} {m['sharpe']:>12.3f} {spy_sharpe:>12.3f}")
        print(f"  {'Max Drawdown':<20} {m['max_drawdown']:>11.2%}")
        print(f"{'='*55}")

    total = time.time() - t0
    print(f"\n✓ 完成。总耗时 {total:.1f}s")
    print(f"  输出目录: {output_dir.resolve()}")
    print(f"  文件列表: {[f.name for f in sorted(output_dir.iterdir())]}")


if __name__ == "__main__":
    main()
