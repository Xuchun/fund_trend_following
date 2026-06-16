"""
Script: market regime analysis — Phase 6, Week 4.

Slices existing backtest results into historical market regimes and computes
per-regime CAGR / Sharpe / MaxDD for both strategy and SPY benchmark.
Runs in seconds (no new backtest required).

Usage
-----
    python src/scripts/09_run_regime.py
    python src/scripts/09_run_regime.py --nav results/v1/nav.csv --output results/v1/regime.json

Output
------
    results/v1/regime.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "src"))

import pandas as pd

from analysis.regime import REGIMES, run_regime_analysis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_spy(start: str, end: str) -> pd.Series | None:
    """Load SPY daily returns from Tiingo cache."""
    spy_parquet = _project_root / "data" / "cache" / "tiingo" / "SPY.parquet"
    if spy_parquet.exists():
        try:
            df = pd.read_parquet(spy_parquet)
            col = "adjClose" if "adjClose" in df.columns else "close"
            prices = df[col].loc[start:end]
            return prices.pct_change().dropna()
        except Exception as e:
            logger.warning("Could not load Tiingo SPY data: %s", e)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Market regime analysis")
    parser.add_argument("--nav",    default=str(_project_root / "results" / "v1_unbiased_60m" / "nav.csv"))
    parser.add_argument("--trades", default=str(_project_root / "results" / "v1_unbiased_60m" / "trades.csv"))
    parser.add_argument("--output", default=str(_project_root / "results" / "v1_unbiased_60m" / "regime.json"))
    parser.add_argument("--risk-free-rate", type=float, default=0.02)
    args = parser.parse_args()

    # ── Load data ────────────────────────────────────────────────────────────
    nav_path = Path(args.nav)
    if not nav_path.exists():
        logger.error("NAV file not found: %s", nav_path)
        sys.exit(1)

    nav_df = pd.read_csv(nav_path, parse_dates=["date"], index_col="date")
    daily_nav     = nav_df["nav"]
    daily_returns = nav_df["return"] if "return" in nav_df.columns else nav_df["nav"].pct_change()
    daily_returns = daily_returns.dropna()

    trade_log = pd.DataFrame()
    trades_path = Path(args.trades)
    if trades_path.exists():
        trade_log = pd.read_csv(trades_path, parse_dates=["entry_date", "exit_date"])
        logger.info("Loaded %d trades", len(trade_log))

    full_start = str(daily_nav.index[0].date())
    full_end   = str(daily_nav.index[-1].date())
    logger.info("Strategy data: %s → %s  (%d days)", full_start, full_end, len(daily_nav))

    # ── Load SPY ─────────────────────────────────────────────────────────────
    logger.info("Loading SPY benchmark data …")
    spy_returns = _load_spy(full_start, full_end)
    if spy_returns is not None:
        logger.info("SPY loaded: %d days", len(spy_returns))
    else:
        logger.warning("SPY data unavailable — regime table will show strategy only")

    # ── Run analysis ─────────────────────────────────────────────────────────
    logger.info("Running regime analysis across %d regimes …", len(REGIMES))
    result = run_regime_analysis(
        daily_nav=daily_nav,
        daily_returns=daily_returns,
        trade_log=trade_log,
        spy_returns=spy_returns,
        risk_free_rate=args.risk_free_rate,
    )

    # ── Print summary table ──────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("  市场环境分析结果")
    print("=" * 78)
    hdr = f"  {'环境':16s}  {'区间':22s}  {'策略CAGR':>9s}  {'MaxDD':>8s}  "
    hdr += f"{'Sharpe':>7s}  {'SPY CAGR':>9s}  {'交易笔数':>8s}"
    print(hdr)
    print("  " + "-" * 74)

    for name, data in result["regimes"].items():
        s = data["strategy"]
        spy = data.get("spy", {})
        period = f"{data['start'][:7]} → {data['end'][:7]}"
        spy_cagr_str = f"{spy.get('cagr', float('nan'))*100:+.1f}%" if spy else "  N/A  "
        print(
            f"  {name:16s}  {period:22s}  "
            f"{s.get('cagr',0)*100:+8.1f}%  "
            f"{s.get('max_drawdown',0)*100:7.1f}%  "
            f"{s.get('sharpe',0):+6.3f}  "
            f"{spy_cagr_str:>9s}  "
            f"{s.get('n_trades',0):8d}"
        )

    fp = result["full_period"]
    print("  " + "-" * 74)
    print(
        f"  {'全回测期':16s}  {'':22s}  "
        f"{fp.get('cagr',0)*100:+8.1f}%  "
        f"{fp.get('max_drawdown',0)*100:7.1f}%  "
        f"{fp.get('sharpe',0):+6.3f}"
    )
    print("=" * 78)

    # ── Save ─────────────────────────────────────────────────────────────────
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("✓ 完成  →  %s", out_path)


if __name__ == "__main__":
    main()
