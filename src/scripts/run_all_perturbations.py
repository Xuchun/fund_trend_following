"""
Master batch perturbation script — loads data ONCE, sweeps all parameters.

Runs one-at-a-time sensitivity tests for all parameters listed in the
'分析框架' table of the parameter_sensitivity page.

Usage:
    cd /Users/xuchun/Documents/fund_trend_following
    python3.11 src/scripts/run_all_perturbations.py

Output:
    results/v1/perturbation/{param_name}.json  (one file per parameter)
"""

import datetime
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

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

# ── Baseline (must match 02_run_baseline.py) ─────────────────────────────────
BASELINE = StrategyParams(
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
    volume_filter_multiplier= 1.5,
    breakout_strength_min   = 0.0,
    gap_filter              = 0.025,
    commission_bps          = 3.0,
    slippage_bps            = 10.0,
    cash_proxy              = "SHY",
    regime_filter_enabled   = True,
    regime_ticker           = "SPY",
    regime_sma_window       = 200,
)

START = "2004-01-02"
END   = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
INITIAL_CAPITAL = 10_000_000.0
OUTPUT_DIR = ROOT / "results" / "v1" / "perturbation"

# ── Parameters to sweep ───────────────────────────────────────────────────────
# Format: (param_name, [values], use_int)
# Existing JSON files are skipped automatically; delete them to force a re-run.
SWEEPS = [
    # Trailing stop / entry signal
    ("trail_multiplier_r1",     [2.0, 2.5, 3.0, 3.5, 4.0],     False),
    ("breakout_window",         [150, 170, 200, 230, 250, 270, 300], True),
    # Risk / stop
    ("stop_loss_multiplier",    [1.5, 2.0, 2.5, 3.0],          False),
    # Position sizing
    ("risk_per_trade",          [0.005, 0.010, 0.015, 0.020],   False),
    ("position_cap",            [0.03, 0.05, 0.07, 0.10],       False),
    ("heat_limit",              [0.05, 0.10, 0.15, 0.20],       False),
    # Diversification
    ("correlation_threshold",   [0.5, 0.6, 0.7, 0.8, 0.9],     False),
    # Entry filters
    ("volume_filter_multiplier",[1.0, 1.2, 1.5, 1.7, 2.0],     False),
    ("min_price",               [8.0, 10.0, 12.0, 15.0],        False),
    ("min_market_cap_b",        [2.0, 3.0, 4.0],                False),
    ("min_adv_m",               [10.0, 20.0, 30.0],             False),
    # Transaction costs
    ("slippage_bps",            [5.0, 8.0, 10.0, 12.0, 15.0],  False),
    ("commission_bps",          [1.0, 3.0, 5.0],                False),
]


def save_result(param_name, param_values, results_df, baseline_value, elapsed):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    for pval, row in results_df.iterrows():
        rec = {"param_value": pval}
        for k, v in row.items():
            try:
                rec[k] = float(v)
            except (TypeError, ValueError):
                rec[k] = v
        records.append(rec)

    out = {
        "param_name":      param_name,
        "param_values":    param_values,
        "baseline_value":  baseline_value,
        "start":           START,
        "end":             END,
        "initial_capital": INITIAL_CAPITAL,
        "universe_mode":   "full",
        "risk_free_rate":  0.02,
        "elapsed_seconds": round(elapsed, 1),
        "results":         records,
    }
    path = OUTPUT_DIR / f"{param_name}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    logger.info("Saved → %s", path)
    return path


def main():
    t_total = time.time()

    # ── 1. Build universe ─────────────────────────────────────────────────────
    logger.info("Fetching S&P 900 tickers …")
    sp900 = fetch_sp900_tickers()
    if not sp900:
        logger.error("Failed to fetch S&P 900 tickers — aborting")
        sys.exit(1)
    universe = sorted(set(sp900) | set(ETF_TICKERS))
    must_have = {BASELINE.cash_proxy, "SPY"}
    download_tickers = sorted(set(universe) | must_have)
    logger.info("Universe: %d tickers (full)", len(universe))

    # ── 2. Load price panel (cached from disk) ────────────────────────────────
    logger.info("Loading price panel (%d tickers) from cache …", len(download_tickers))
    t0 = time.time()
    adapter = YahooFinanceAdapter()
    panel = load_price_panel(
        download_tickers, adapter,
        start=START, end=END,
        force_refresh=False,
    )
    logger.info("Panel loaded: %d tickers in %.1fs", len(panel), time.time() - t0)

    auxiliary = {BASELINE.cash_proxy, "SPY"}
    strategy_tickers = [t for t in universe if t in panel and t not in auxiliary]
    logger.info("Strategy tickers: %d", len(strategy_tickers))

    # ── 3. Precompute baseline indicators (reused across sweeps) ──────────────
    logger.info("Precomputing baseline indicators …")
    t1 = time.time()
    strategy_panel = {t: panel[t] for t in strategy_tickers}
    baseline_indicators = precompute_indicators(strategy_panel, BASELINE)
    logger.info("Indicators ready in %.1fs", time.time() - t1)

    # ── 4. Run each sweep ─────────────────────────────────────────────────────
    n_sweeps = len(SWEEPS)
    for sweep_idx, (param_name, param_values, _use_int) in enumerate(SWEEPS, 1):
        out_path = OUTPUT_DIR / f"{param_name}.json"
        if out_path.exists():
            logger.info(
                "[%d/%d] SKIP %s — already exists (delete file to re-run)",
                sweep_idx, n_sweeps, param_name,
            )
            continue

        logger.info(
            "\n%s\n[%d/%d] Sweeping %s over %s\n%s",
            "=" * 65, sweep_idx, n_sweeps, param_name, param_values, "=" * 65,
        )
        t2 = time.time()

        results_df = run_perturbation_test(
            param_name=param_name,
            param_values=param_values,
            baseline_params=BASELINE,
            price_panel=panel,
            baseline_indicators=baseline_indicators,
            start=START,
            end=END,
            initial_capital=INITIAL_CAPITAL,
            risk_free_rate=0.02,
            strategy_tickers=strategy_tickers,
        )

        elapsed = time.time() - t2
        save_result(
            param_name, param_values, results_df,
            getattr(BASELINE, param_name), elapsed,
        )

        # Print summary
        display_cols = ["cagr", "max_drawdown", "sharpe", "sortino", "calmar",
                        "annual_turnover", "avg_holding_days"]
        avail = [c for c in display_cols if c in results_df.columns]
        print(f"\n{'='*65}")
        print(f"  {param_name} results")
        print(f"{'='*65}")
        print(results_df[avail].to_string(float_format=lambda x: f"{x:+.4f}"))
        print(f"  Elapsed: {elapsed:.1f}s")
        print(f"{'='*65}\n")

    total = time.time() - t_total
    logger.info("\n✓ All sweeps complete. Total wall time: %.0fs (%.1fh)", total, total/3600)


if __name__ == "__main__":
    main()
