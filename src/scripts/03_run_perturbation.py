"""
Script: one-at-a-time parameter perturbation sensitivity test.

Loads the full price panel once from cache, sweeps a single StrategyParams
field across user-specified values, and saves results to a JSON file.

Usage examples:
    # trail_multiplier_r1: [2.0, 2.5, 3.0, 3.5, 4.0]
    python3.11 src/scripts/03_run_perturbation.py \\
        --param trail_multiplier_r1 \\
        --values 2.0,2.5,3.0,3.5,4.0

    # breakout_window: [150, 200, 250, 300] (integers)
    python3.11 src/scripts/03_run_perturbation.py \\
        --param breakout_window \\
        --values 150,200,250,300 \\
        --int-values

    # Quick sanity with ETF universe only
    python3.11 src/scripts/03_run_perturbation.py \\
        --param trail_multiplier_r1 \\
        --values 2.0,3.0,4.0 \\
        --mode etf

Output:
    results/v1/perturbation/{param_name}.json
"""

import argparse
import datetime
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from data.adapters.yahoo import YahooFinanceAdapter
from data.pipeline import load_price_panel
from data.universe import ETF_TICKERS, fetch_sp900_tickers
from indicators.precompute import precompute_indicators
from strategy.params import StrategyParams
from analysis.perturbation import run_perturbation_test

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Baseline anchor — must match results/v1/ baseline run ──────────────────
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
    gap_filter              = 0.025,
    commission_bps          = 3.0,
    slippage_bps            = 10.0,
    cash_proxy              = "SHY",
    regime_filter_enabled   = True,
    regime_ticker           = "SPY",
    regime_sma_window       = 200,
)

DEFAULT_START = "2004-01-01"
DEFAULT_END   = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run one-at-a-time perturbation sensitivity test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--param",       required=True,
                   help="StrategyParams field to vary (e.g. trail_multiplier_r1)")
    p.add_argument("--values",      required=True,
                   help="Comma-separated values, e.g. 2.0,2.5,3.0,3.5,4.0")
    p.add_argument("--int-values",  action="store_true",
                   help="Parse values as int rather than float")
    p.add_argument("--mode",        default="full",
                   choices=["etf", "sp500", "sp900", "full"],
                   help="Universe mode (default: full)")
    p.add_argument("--start",       default=DEFAULT_START,
                   help="Backtest start date (YYYY-MM-DD)")
    p.add_argument("--end",         default=DEFAULT_END,
                   help="Backtest end date (YYYY-MM-DD)")
    p.add_argument("--initial-capital", default=10_000_000.0, type=float,
                   help="Starting NAV in USD")
    p.add_argument("--output",      default="results/v1/perturbation/",
                   help="Output directory")
    p.add_argument("--force-download", action="store_true",
                   help="Re-download all price data (bypass cache)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Show DEBUG logs")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Parse parameter values ────────────────────────────────────────────────
    raw_vals = [v.strip() for v in args.values.split(",")]
    param_values: list = (
        [int(v) for v in raw_vals] if args.int_values
        else [float(v) for v in raw_vals]
    )

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    params = BASELINE_PARAMS

    print(f"\n{'='*65}")
    print(f"  Perturbation Test  —  {args.param}")
    print(f"  Values     : {param_values}")
    print(f"  Baseline   : {getattr(params, args.param)}")
    print(f"  Period     : {args.start} → {args.end}")
    print(f"  Capital    : ${args.initial_capital:,.0f}")
    print(f"  Universe   : {args.mode}")
    print(f"  Output dir : {output_dir.resolve()}")
    print(f"{'='*65}\n")

    # ── Build universe ────────────────────────────────────────────────────────
    if args.mode == "etf":
        universe = sorted(ETF_TICKERS)
    else:
        sp900 = fetch_sp900_tickers()
        if not sp900:
            logger.error("Failed to fetch S&P 900 tickers — aborting")
            sys.exit(1)
        if args.mode == "full":
            universe = sorted(set(sp900) | set(ETF_TICKERS))
        elif args.mode == "sp900":
            universe = sp900
        else:
            universe = sp900  # sp500 not separately defined; use sp900 subset

    must_have      = {params.cash_proxy, "SPY"}
    download_tickers = sorted(set(universe) | must_have)
    logger.info("Universe: %d tickers  (mode=%s)", len(universe), args.mode)

    # ── Load price data (once for all param sweeps) ───────────────────────────
    t0 = time.time()
    logger.info("Loading price panel (%d tickers) …", len(download_tickers))
    adapter = YahooFinanceAdapter()
    panel = load_price_panel(
        download_tickers, adapter,
        start=args.start, end=args.end,
        force_refresh=args.force_download,
    )
    logger.info("Panel loaded: %d tickers in %.1fs", len(panel), time.time() - t0)

    if len(panel) == 0:
        logger.error("No data loaded — check network connection and date range")
        sys.exit(1)

    auxiliary = {params.cash_proxy, "SPY"}
    strategy_tickers = [t for t in universe if t in panel and t not in auxiliary]
    if not strategy_tickers:
        logger.error("No strategy tickers with data — aborting")
        sys.exit(1)
    logger.info("Strategy tickers with data: %d / %d", len(strategy_tickers), len(universe))

    # ── Precompute baseline indicators (reused / partially reused per sweep) ──
    t1 = time.time()
    logger.info("Precomputing baseline indicators …")
    strategy_panel = {t: panel[t] for t in strategy_tickers}
    baseline_indicators = precompute_indicators(strategy_panel, params)
    logger.info("Baseline indicators ready in %.1fs", time.time() - t1)

    # ── Run perturbation sweep ────────────────────────────────────────────────
    t2 = time.time()
    logger.info(
        "Starting perturbation: %s over %s …",
        args.param, param_values,
    )
    results_df = run_perturbation_test(
        param_name=args.param,
        param_values=param_values,
        baseline_params=params,
        price_panel=panel,
        baseline_indicators=baseline_indicators,
        start=args.start,
        end=args.end,
        initial_capital=args.initial_capital,
        risk_free_rate=0.02,
        strategy_tickers=strategy_tickers,
    )
    elapsed = time.time() - t2
    logger.info("Sweep completed in %.1fs", elapsed)

    # ── Save results to JSON ──────────────────────────────────────────────────
    out_path = output_dir / f"{args.param}.json"

    records: list[dict] = []
    for pval, row in results_df.iterrows():
        rec: dict = {"param_value": pval}
        for k, v in row.items():
            try:
                rec[k] = float(v)
            except (TypeError, ValueError):
                rec[k] = v
        records.append(rec)

    output_meta = {
        "param_name":      args.param,
        "param_values":    param_values,
        "baseline_value":  getattr(params, args.param),
        "start":           args.start,
        "end":             args.end,
        "initial_capital": args.initial_capital,
        "universe_mode":   args.mode,
        "risk_free_rate":  0.02,
        "elapsed_seconds": round(elapsed, 1),
        "results":         records,
    }
    out_path.write_text(json.dumps(output_meta, ensure_ascii=False, indent=2))
    logger.info("Saved → %s", out_path)

    # ── Print summary table ───────────────────────────────────────────────────
    display_cols = [
        "cagr", "max_drawdown", "sharpe", "sortino", "calmar",
        "annual_turnover", "trades_per_year", "avg_holding_days",
        "market_exposure",
    ]
    avail = [c for c in display_cols if c in results_df.columns]
    print(f"\n{'='*65}")
    print(f"  {args.param}  sensitivity results")
    print(f"{'='*65}")
    print(results_df[avail].to_string(float_format=lambda x: f"{x:+.4f}"))
    print(f"{'='*65}")

    total = time.time() - t0
    print(f"\n✓ 完成。总耗时 {total:.1f}s  →  {out_path}")


if __name__ == "__main__":
    main()
