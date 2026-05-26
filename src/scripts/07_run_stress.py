"""
Script: execution stress tests — Phase 6, Week 4.

Estimates strategy performance under adverse execution conditions using
trade-level re-pricing (no full backtest re-run required).
Runs in seconds.

Usage
-----
    python src/scripts/07_run_stress.py
    python src/scripts/07_run_stress.py --slippage 5,10,20,30,50

Output
------
    results/v1/stress.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "src"))

import pandas as pd

from analysis.stress import run_stress_analysis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Execution stress tests")
    parser.add_argument("--nav",    default=str(_project_root / "results" / "v1" / "nav.csv"))
    parser.add_argument("--trades", default=str(_project_root / "results" / "v1" / "trades.csv"))
    parser.add_argument("--output", default=str(_project_root / "results" / "v1" / "stress.json"))
    parser.add_argument("--slippage",  default="5,10,20,30", help="Slippage levels in bps")
    parser.add_argument("--delay",     default="0,1,2",       help="Latency delay in days")
    parser.add_argument("--fill",      default="1.0,0.8,0.5", help="Fill ratios")
    parser.add_argument("--base-slippage", type=float, default=10.0)
    parser.add_argument("--risk-free-rate", type=float, default=0.02)
    args = parser.parse_args()

    # ── Load data ────────────────────────────────────────────────────────────
    nav_df = pd.read_csv(Path(args.nav), parse_dates=["date"], index_col="date")
    daily_nav     = nav_df["nav"]
    daily_returns = nav_df["return"] if "return" in nav_df.columns else nav_df["nav"].pct_change()
    daily_returns = daily_returns.dropna()

    trade_log = pd.read_csv(Path(args.trades), parse_dates=["entry_date", "exit_date"])
    logger.info("Loaded %d trades  |  NAV: %d days", len(trade_log), len(daily_nav))

    slippage_levels = [float(x) for x in args.slippage.split(",")]
    delay_days      = [int(x)   for x in args.delay.split(",")]
    fill_ratios     = [float(x) for x in args.fill.split(",")]

    # ── Run stress ───────────────────────────────────────────────────────────
    logger.info("Running stress tests …")
    result = run_stress_analysis(
        daily_nav=daily_nav,
        daily_returns=daily_returns,
        trade_log=trade_log,
        base_slippage_bps=args.base_slippage,
        slippage_levels=slippage_levels,
        delay_days=delay_days,
        fill_ratios=fill_ratios,
        risk_free_rate=args.risk_free_rate,
    )

    # ── Print summary ────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  执行压力测试结果")
    print("=" * 72)
    print("\n  【滑点压力】")
    for r in result["slippage_stress"]:
        print(f"    {r.get('slippage_bps',0):4.0f} bps  →  "
              f"CAGR {r.get('cagr',0)*100:+.2f}%  "
              f"Sharpe {r.get('sharpe',0):+.3f}  "
              f"MaxDD {r.get('max_drawdown',0)*100:.1f}%")

    print("\n  【延迟执行】")
    for r in result["latency_stress"]:
        print(f"    延迟 {r.get('delay_days',0)} 天  →  "
              f"CAGR {r.get('cagr',0)*100:+.2f}%  "
              f"Sharpe {r.get('sharpe',0):+.3f}  "
              f"MaxDD {r.get('max_drawdown',0)*100:.1f}%")

    print("\n  【部分成交】")
    for r in result["liquidity_stress"]:
        print(f"    成交率 {r.get('fill_ratio',0)*100:.0f}%  →  "
              f"CAGR {r.get('cagr',0)*100:+.2f}%  "
              f"Sharpe {r.get('sharpe',0):+.3f}  "
              f"MaxDD {r.get('max_drawdown',0)*100:.1f}%")
    print("=" * 72)

    # ── Save ─────────────────────────────────────────────────────────────────
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("✓ 完成  →  %s", out_path)


if __name__ == "__main__":
    main()
