"""
[已废弃] 此脚本使用 Yahoo Finance 数据，已不再使用。请改用对应 Tiingo 版本。
Strategy 2.0 Step 1 — v1 baseline + Condition 2: 横盘收敛 (consolidation filter).

Everything is identical to Strategy 1.0 except:
  consolidation_filter_enabled = True
  consolidation_window         = 80
  consolidation_threshold      = 0.25

Usage:
    python src/scripts/03_run_v2_step1.py
    python src/scripts/03_run_v2_step1.py --mode etf   # fast sanity check
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "src"))

from data.adapters.yahoo import YahooFinanceAdapter
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

# ── Strategy 2.0 Step 1 params: identical to v1 + consolidation filter ─────
V2_STEP1_PARAMS = StrategyParams(
    # All v1 defaults — only consolidation changes
    consolidation_filter_enabled = True,
    consolidation_window         = 80,
    consolidation_threshold      = 0.25,
)

DEFAULT_START = "2004-01-01"
DEFAULT_END   = "2026-06-15"

STRATEGY_META = {
    "id": "v2_step1",
    "version": "2.0-step1",
    "display_name": "Strategy 2.0 Step 1",
    "subtitle": "v1 + 横盘收敛过滤（Consolidation Filter）",
    "color": "#ff7f0e",
    "badge_text": "v2.s1",
    "badge_color": "orange",
    "backtest_start": DEFAULT_START,
    "backtest_end":   DEFAULT_END,
    "initial_capital": 10_000_000,
    "cash_proxy": "SHY",
    "key_features": [
        "策略1.0全部参数不变",
        "【新增】横盘收敛过滤：过去80日价格区间 < 25%",
    ],
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run Strategy 2.0 Step 1 (consolidation filter)")
    p.add_argument("--mode", choices=["etf", "sp500", "sp900", "full"],
                   default="full")
    p.add_argument("--start",           default=DEFAULT_START)
    p.add_argument("--end",             default=DEFAULT_END)
    p.add_argument("--initial-capital", default=10_000_000, type=float)
    p.add_argument("--output",          default="results/v2_step1/")
    p.add_argument("--force-download",  action="store_true")
    p.add_argument("-v", "--verbose",   action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    params = V2_STEP1_PARAMS

    if args.mode == "etf":
        universe = sorted(ETF_TICKERS)
    else:
        universe = fetch_sp900_tickers()
        if not universe:
            logger.error("Failed to fetch S&P 900 tickers")
            sys.exit(1)
        if args.mode == "full":
            universe = sorted(set(universe) | set(ETF_TICKERS))

    must_have        = {params.cash_proxy, "SPY", params.regime_ticker}
    download_tickers = sorted(set(universe) | must_have)

    print(f"\n{'='*65}")
    print(f"Strategy 2.0 Step 1 — v1 + 横盘收敛过滤")
    print(f"  Universe     : {len(universe)} tickers ({args.mode})")
    print(f"  Period       : {args.start} → {args.end}")
    print(f"  Consolidation: window={params.consolidation_window}d, threshold={params.consolidation_threshold:.0%}")
    print(f"  Output       : {output_dir.resolve()}")
    print(f"{'='*65}\n")

    adapter = YahooFinanceAdapter()

    t0 = time.time()
    logger.info("Loading price data (%d tickers) …", len(download_tickers))
    panel = load_price_panel(
        download_tickers, adapter,
        start=args.start, end=args.end,
        force_refresh=args.force_download,
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

    meta = dict(STRATEGY_META)
    meta["backtest_start"]   = args.start
    meta["backtest_end"]     = args.end
    meta["initial_capital"]  = args.initial_capital
    meta["params_anchor"]    = {
        k: getattr(params, k)
        for k in vars(StrategyParams())
        if not k.startswith("_")
    }
    (output_dir / "strategy_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )

    # ── Print summary & comparison with v1 ───────────────────────────────
    m2 = results.compute_metrics()
    print(f"\n{results.summary()}")

    v1_metrics_path = _root / "results" / "v1" / "metrics.json"
    if v1_metrics_path.exists():
        import json as _json
        m1 = _json.loads(v1_metrics_path.read_text())

        print(f"\n{'='*65}")
        print(f"  策略1.0 vs 策略2.0 Step1（+横盘收敛）对比")
        print(f"{'='*65}")
        print(f"  {'指标':<22} {'策略1.0':>12} {'Step1':>12} {'变化':>10}")
        print(f"  {'-'*58}")

        rows = [
            ("CAGR",        m1.get("cagr",0),         m2["cagr"],         ".2%"),
            ("Sharpe",      m1.get("sharpe",0),        m2["sharpe"],       ".3f"),
            ("Sortino",     m1.get("sortino",0),       m2["sortino"],      ".3f"),
            ("最大回撤",      m1.get("max_drawdown",0),  m2["max_drawdown"], ".2%"),
            ("年化波动率",     m1.get("annual_vol",0),    m2["annual_vol"],   ".2%"),
            ("胜率",         m1.get("win_rate",0),       m2.get("win_rate",0), ".1%"),
            ("Profit Factor",m1.get("profit_factor",0), m2.get("profit_factor",0), ".2f"),
            ("总交易笔数",    m1.get("num_trades",0),    m2.get("num_trades",0), ".0f"),
            ("平均持仓天数",  m1.get("avg_holding_days",0), m2.get("avg_holding_days",0), ".1f"),
        ]
        for label, v1_val, v2_val, fmt in rows:
            delta = v2_val - v1_val
            sign  = "+" if delta >= 0 else ""
            print(f"  {label:<22} {v1_val:>{12}{fmt}} {v2_val:>{12}{fmt}} {sign}{delta:{fmt}}")

        print(f"{'='*65}")

    total = time.time() - t0
    print(f"\n✓ 完成。总耗时 {total:.1f}s  →  {output_dir.resolve()}")


if __name__ == "__main__":
    main()
