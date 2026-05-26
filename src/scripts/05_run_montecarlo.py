"""
Script: Monte Carlo risk analysis — Phase 6, Week 3.

Loads historical daily returns from results/v1/nav.csv and runs
bootstrap-resampling Monte Carlo to estimate the distribution of
strategy outcomes across 1,000 simulated paths.

Usage
-----
    python src/scripts/05_run_montecarlo.py
    python src/scripts/05_run_montecarlo.py --n-simulations 2000 --method both
    python src/scripts/05_run_montecarlo.py --nav results/v1/nav.csv --output results/v1/montecarlo.json

Output
------
    results/v1/montecarlo.json   — full Monte Carlo results (JSON)
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "src"))

from analysis.montecarlo import run_montecarlo

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Monte Carlo risk simulation")
    parser.add_argument(
        "--nav",
        default=str(_project_root / "results" / "v1" / "nav.csv"),
        help="Path to nav.csv (default: results/v1/nav.csv)",
    )
    parser.add_argument(
        "--output",
        default=str(_project_root / "results" / "v1" / "montecarlo.json"),
        help="Output JSON path",
    )
    parser.add_argument(
        "--n-simulations", type=int, default=1_000,
        help="Number of bootstrap paths (default: 1000)",
    )
    parser.add_argument(
        "--method",
        choices=["return_bootstrap", "block_bootstrap", "both"],
        default="both",
        help="Bootstrap method (default: both)",
    )
    parser.add_argument(
        "--risk-free-rate", type=float, default=0.02,
        help="Annual risk-free rate (default: 0.02)",
    )
    args = parser.parse_args()

    nav_path = Path(args.nav)
    if not nav_path.exists():
        logger.error("NAV file not found: %s", nav_path)
        sys.exit(1)

    # ── Load returns ────────────────────────────────────────────────────────
    logger.info("Loading NAV data from %s …", nav_path)
    nav_df = pd.read_csv(nav_path, parse_dates=["date"], index_col="date")

    if "return" in nav_df.columns:
        daily_returns = nav_df["return"].dropna()
    else:
        daily_returns = nav_df["nav"].pct_change().dropna()

    initial_nav = float(nav_df["nav"].iloc[0])
    logger.info(
        "Loaded %d trading days  |  initial NAV = $%,.0f  |  start=%s  end=%s",
        len(daily_returns), initial_nav,
        daily_returns.index[0].date(), daily_returns.index[-1].date(),
    )

    # ── Run simulation ──────────────────────────────────────────────────────
    logger.info(
        "Running Monte Carlo: method=%s  n_simulations=%d …",
        args.method, args.n_simulations,
    )
    t0 = time.perf_counter()

    result = run_montecarlo(
        daily_returns=daily_returns,
        n_simulations=args.n_simulations,
        initial_nav=initial_nav,
        risk_free_rate=args.risk_free_rate,
        method=args.method,
    )

    elapsed = time.perf_counter() - t0
    logger.info("Simulation complete in %.1f s", elapsed)

    # ── Print summary ────────────────────────────────────────────────────────
    cd = result["cagr_dist"]
    dd = result["max_drawdown_dist"]
    sd = result["sharpe_dist"]
    dur = result["drawdown_duration"]

    print("\n" + "=" * 62)
    print(f"  蒙特卡洛风险分析结果  ({args.method}  N={args.n_simulations:,})")
    print("=" * 62)
    print(f"\n  CAGR 分布（年化收益率）:")
    print(f"    5th pct : {cd['p5']*100:+.2f}%")
    print(f"   25th pct : {cd['p25']*100:+.2f}%")
    print(f"   中位数   : {cd['p50']*100:+.2f}%")
    print(f"   75th pct : {cd['p75']*100:+.2f}%")
    print(f"   95th pct : {cd['p95']*100:+.2f}%")
    print(f"    均值    : {cd['mean']*100:+.2f}%  ±{cd['std']*100:.2f}%")
    print(f"  负收益概率 : {cd['prob_negative_cagr']*100:.1f}%")
    print(f"  破产概率   : {cd['prob_ruin']*100:.1f}%  (最终NAV < 50% 初始资金)")

    print(f"\n  最大回撤分布:")
    print(f"    5th pct : {dd['p5']*100:.1f}%")
    print(f"   25th pct : {dd['p25']*100:.1f}%")
    print(f"   中位数   : {dd['p50']*100:.1f}%")
    print(f"   75th pct : {dd['p75']*100:.1f}%")
    print(f"   95th pct : {dd['p95']*100:.1f}%")
    print(f"    最差    : {dd['worst']*100:.1f}%")

    print(f"\n  Sharpe 分布 (rf={args.risk_free_rate*100:.0f}%):")
    print(f"   中位数   : {sd['p50']:+.3f}")
    print(f"   均值     : {sd['mean']:+.3f}  ±{sd['std']:.3f}")

    print(f"\n  水下时间分布:")
    print(f"   P(最长水下 > 3月)  : {dur['prob_gt_3m']*100:.1f}%")
    print(f"   P(最长水下 > 6月)  : {dur['prob_gt_6m']*100:.1f}%")
    print(f"   P(最长水下 > 12月) : {dur['prob_gt_12m']*100:.1f}%")
    print(f"   P(最长水下 > 24月) : {dur['prob_gt_24m']*100:.1f}%")
    print(f"   平均最长水下       : {dur['avg_days']:.0f} 交易日")
    print(f"   95th pct 水下      : {dur['p95_days']:.0f} 交易日")
    print("=" * 62)

    # ── Save JSON ────────────────────────────────────────────────────────────
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("✓ 完成  →  %s", out_path)


if __name__ == "__main__":
    main()
