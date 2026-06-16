"""
Script: Walk-Forward OOS validation — Phase 6, Week 4.

Slices existing backtest results into IS/OOS windows and computes retention
metrics.  Runs in seconds (no new backtest required).

Usage
-----
    python src/scripts/08_run_walkforward.py
    python src/scripts/08_run_walkforward.py --nav results/v1/nav.csv

Output
------
    results/v1/walkforward.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "src"))

import pandas as pd

from analysis.walkforward import WALK_FORWARD_WINDOWS, run_walk_forward

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_spy(full_start: str, full_end: str) -> pd.Series | None:
    spy_parquet = _project_root / "data" / "cache" / "tiingo" / "SPY.parquet"
    if spy_parquet.exists():
        try:
            df = pd.read_parquet(spy_parquet)
            col = "adjClose" if "adjClose" in df.columns else "close"
            prices = df[col].loc[full_start:full_end]
            return prices.pct_change().dropna()
        except Exception as e:
            logger.warning("Could not load Tiingo SPY data: %s", e)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-Forward OOS validation")
    parser.add_argument("--nav",    default=str(_project_root / "results" / "v1_unbiased_60m" / "nav.csv"))
    parser.add_argument("--trades", default=str(_project_root / "results" / "v1_unbiased_60m" / "trades.csv"))
    parser.add_argument("--output", default=str(_project_root / "results" / "v1_unbiased_60m" / "walkforward.json"))
    parser.add_argument("--risk-free-rate", type=float, default=0.02)
    args = parser.parse_args()

    # ── Load data ────────────────────────────────────────────────────────────
    nav_df = pd.read_csv(Path(args.nav), parse_dates=["date"], index_col="date")
    daily_nav     = nav_df["nav"]
    daily_returns = nav_df["return"] if "return" in nav_df.columns else nav_df["nav"].pct_change()
    daily_returns = daily_returns.dropna()

    trade_log = pd.read_csv(Path(args.trades), parse_dates=["entry_date", "exit_date"])
    logger.info("Loaded %d trades  |  NAV: %d days", len(trade_log), len(daily_nav))

    full_start = str(daily_nav.index[0].date())
    full_end   = str(daily_nav.index[-1].date())

    spy_returns = _load_spy(full_start, full_end)
    if spy_returns is not None:
        logger.info("SPY loaded: %d days", len(spy_returns))

    # ── Run walk-forward ─────────────────────────────────────────────────────
    logger.info("Running Walk-Forward analysis (%d windows) …", len(WALK_FORWARD_WINDOWS))
    result = run_walk_forward(
        daily_nav=daily_nav,
        daily_returns=daily_returns,
        trade_log=trade_log,
        spy_returns=spy_returns,
        risk_free_rate=args.risk_free_rate,
    )

    # ── Print summary ────────────────────────────────────────────────────────
    print("\n" + "=" * 82)
    print("  Walk-Forward OOS 验证结果")
    print("=" * 82)
    print(f"\n  {'窗口':10s}  {'OOS期间':22s}  {'IS CAGR':>9s}  "
          f"{'OOS CAGR':>9s}  {'保留率':>7s}  {'OOS Sharpe':>10s}  {'OOS MaxDD':>9s}")
    print("  " + "-" * 78)

    for w in result["windows"]:
        is_m  = w.get("is",  {})
        oos_m = w.get("oos", {})
        oos_period = f"{w['oos_start'][:7]} → {w['oos_end'][:7]}"
        is_cagr  = is_m.get("cagr", 0.0)
        oos_cagr = oos_m.get("cagr", 0.0)
        retention = oos_cagr / is_cagr if abs(is_cagr) > 1e-9 else 0.0
        print(
            f"  {w['label']:10s}  {oos_period:22s}  "
            f"{is_cagr*100:+8.1f}%  "
            f"{oos_cagr*100:+8.1f}%  "
            f"{retention*100:6.0f}%  "
            f"{oos_m.get('sharpe',0):+9.3f}  "
            f"{oos_m.get('max_drawdown',0)*100:8.1f}%"
        )

    print("  " + "-" * 78)
    ret = result["retention"]
    oos_m = result["oos_stitched"].get("metrics", {})
    print(f"\n  OOS 拼接净值 CAGR : {oos_m.get('cagr',0)*100:+.2f}%  "
          f"Sharpe : {oos_m.get('sharpe',0):+.3f}  "
          f"MaxDD : {oos_m.get('max_drawdown',0)*100:.1f}%")
    print(f"  平均 CAGR 保留率  : {ret.get('cagr_retention',0)*100:.0f}%")
    print(f"  平均 Sharpe 保留率: {ret.get('sharpe_retention',0)*100:.0f}%")
    print("=" * 82)

    # ── Save ─────────────────────────────────────────────────────────────────
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("✓ 完成  →  %s", out_path)


if __name__ == "__main__":
    main()
