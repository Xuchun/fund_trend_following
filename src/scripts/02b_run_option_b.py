"""
Option B backtest — dual-constraint position sizing.

Compares against the Baseline (legacy single-cap method).

Usage:
    python3.11 src/scripts/02b_run_option_b.py

Output:
    results/v1_optB/   — nav.csv, trades.csv, metrics.json, comparison.json
"""

import json
import logging
import sys
import time
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "src"))

import pandas as pd

from data.adapters.yahoo import YahooFinanceAdapter
from data.pipeline import load_price_panel
from data.universe import ETF_TICKERS, fetch_sp900_tickers
from indicators.precompute import precompute_indicators
from backtest.engine import BacktestEngine
from reports.baseline import generate_baseline_report
from strategy.params import StrategyParams
from strategy.v1.strategy_v1 import StrategyV1
from analysis.metrics import compute_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Baseline anchor params (same as 02_run_baseline.py) ────────────────────
BASELINE_PARAMS = StrategyParams(
    min_price=10.0, min_market_cap_b=2.0, min_adv_m=20.0,
    breakout_window=200, atr_period=20,
    stop_loss_multiplier=2.0, min_stop_distance_pct=0.005,
    trail_multiplier_r1=3.0, trail_multiplier_r3=3.0, trail_multiplier_r5=5.0,
    risk_per_trade=0.01, position_cap=0.05,
    risk_cap=0.0, notional_cap=0.0,          # legacy mode
    heat_limit=0.10,
    correlation_window=60, correlation_threshold=0.70, correlation_reduction=0.50,
    volume_filter_multiplier=1.5, breakout_strength_min=0.0,
    gap_filter=0.025, commission_bps=3.0, slippage_bps=10.0,
    cash_proxy="SHY",
    regime_filter_enabled=True, regime_ticker="SPY", regime_sma_window=200,
)

# ── Option B params: dual-constraint sizing ─────────────────────────────────
# risk_cap=0.5%: each position risks at most 0.5% NAV when stopped out.
# notional_cap=15%: concentration hard cap per position.
# heat_limit stays 10%: now binding at ~20 concurrent positions (avg=15.7).
OPTION_B_PARAMS = StrategyParams(
    min_price=10.0, min_market_cap_b=2.0, min_adv_m=20.0,
    breakout_window=200, atr_period=20,
    stop_loss_multiplier=2.0, min_stop_distance_pct=0.005,
    trail_multiplier_r1=3.0, trail_multiplier_r3=3.0, trail_multiplier_r5=5.0,
    risk_per_trade=0.01, position_cap=0.05,   # kept for reference; not used in dual mode
    risk_cap=0.005,      # 0.5% NAV max actual loss per trade
    notional_cap=0.15,   # 15% NAV max notional per position
    heat_limit=0.10,
    correlation_window=60, correlation_threshold=0.70, correlation_reduction=0.50,
    volume_filter_multiplier=1.5, breakout_strength_min=0.0,
    gap_filter=0.025, commission_bps=3.0, slippage_bps=10.0,
    cash_proxy="SHY",
    regime_filter_enabled=True, regime_ticker="SPY", regime_sma_window=200,
)

START           = "2004-01-01"
END             = "2026-06-09"
INITIAL_CAPITAL = 10_000_000.0
BASELINE_DIR    = _root / "results" / "v1"
OPTB_DIR        = _root / "results" / "v1_optB"


def _run_backtest(params: StrategyParams, panel: dict, strategy_tickers: list,
                  label: str) -> object:
    logger.info("=== Running %s ===", label)
    indicators = precompute_indicators(
        {t: panel[t] for t in strategy_tickers}, params
    )
    engine = BacktestEngine(
        strategy=StrategyV1(params),
        price_panel=panel,
        indicators=indicators,
        params=params,
        initial_capital=INITIAL_CAPITAL,
    )
    results = engine.run(START, END, strategy_tickers)
    logger.info(
        "%s done: %d trades, CAGR=%.2f%%",
        label, len(results.trade_log),
        results.compute_metrics().get("cagr", 0) * 100,
    )
    return results


def main() -> None:
    OPTB_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load data (shared between both runs) ───────────────────────────────
    logger.info("Fetching universe …")
    sp900 = fetch_sp900_tickers()
    universe = sorted(set(sp900) | set(ETF_TICKERS))
    must_have = {"SHY", "SPY"}
    download_tickers = sorted(set(universe) | must_have)

    adapter = YahooFinanceAdapter()
    logger.info("Loading %d tickers …", len(download_tickers))
    panel = load_price_panel(download_tickers, adapter, start=START, end=END)
    logger.info("Panel loaded: %d tickers", len(panel))

    auxiliary = {"SHY", "SPY"}
    strategy_tickers = [t for t in universe if t in panel and t not in auxiliary]
    logger.info("Strategy tickers with data: %d", len(strategy_tickers))

    # ── Run both backtests ─────────────────────────────────────────────────
    t0 = time.time()
    res_b  = _run_backtest(BASELINE_PARAMS, panel, strategy_tickers, "Baseline (legacy)")
    res_ob = _run_backtest(OPTION_B_PARAMS, panel, strategy_tickers, "Option B (dual-constraint)")
    logger.info("Both backtests done in %.0fs", time.time() - t0)

    # ── Save Option B artefacts ────────────────────────────────────────────
    generate_baseline_report(res_ob, panel.get("SPY"), OPTB_DIR)
    logger.info("Option B report saved → %s", OPTB_DIR)

    # ── Build comparison dict ──────────────────────────────────────────────
    m_b  = res_b.compute_metrics()
    m_ob = res_ob.compute_metrics()

    def _fmt(m: dict) -> dict:
        return {
            "cagr":               round(m["cagr"] * 100, 2),
            "total_return":       round(m["total_return"] * 100, 2),
            "annual_vol":         round(m["annual_vol"] * 100, 2),
            "max_drawdown":       round(m["max_drawdown"] * 100, 2),
            "max_dd_days":        m["max_dd_duration_days"],
            "sharpe":             round(m["sharpe"], 3),
            "sortino":            round(m["sortino"], 3),
            "calmar":             round(m["calmar"], 3),
            "profit_factor":      round(m["profit_factor"], 3),
            "win_rate":           round(m["win_rate"] * 100, 1),
            "n_trades":           m["n_trades"],
            "avg_holding_days":   round(m["avg_holding_days"], 1),
            "annual_turnover":    round(m["annual_turnover"], 2),
            "market_exposure":    round(m["market_exposure"] * 100, 1),
        }

    comparison = {
        "baseline":  _fmt(m_b),
        "option_b":  _fmt(m_ob),
        "params": {
            "baseline": {"sizing": "legacy", "risk_per_trade_pct": 1.0,  "position_cap_pct": 5.0},
            "option_b": {"sizing": "dual",   "risk_cap_pct": 0.5, "notional_cap_pct": 15.0},
        },
    }

    cmp_path = OPTB_DIR / "comparison.json"
    cmp_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2))

    # ── Print side-by-side table ───────────────────────────────────────────
    b  = comparison["baseline"]
    ob = comparison["option_b"]
    rows = [
        ("CAGR (%)",              b["cagr"],             ob["cagr"]),
        ("总回报率 (%)",           b["total_return"],     ob["total_return"]),
        ("年化波动率 (%)",         b["annual_vol"],       ob["annual_vol"]),
        ("最大回撤 (%)",           b["max_drawdown"],     ob["max_drawdown"]),
        ("最大水下时间 (交易日)",  b["max_dd_days"],      ob["max_dd_days"]),
        ("Sharpe",                b["sharpe"],            ob["sharpe"]),
        ("Sortino",               b["sortino"],           ob["sortino"]),
        ("Calmar",                b["calmar"],            ob["calmar"]),
        ("Profit Factor",         b["profit_factor"],    ob["profit_factor"]),
        ("胜率 (%)",              b["win_rate"],          ob["win_rate"]),
        ("交易笔数",              b["n_trades"],          ob["n_trades"]),
        ("平均持仓天数",          b["avg_holding_days"], ob["avg_holding_days"]),
        ("年换手率 (x)",          b["annual_turnover"],  ob["annual_turnover"]),
        ("市场暴露率 (%)",        b["market_exposure"],  ob["market_exposure"]),
    ]

    print("\n" + "=" * 65)
    print(f"  对比结果：当前方法  vs  方案 B（双约束仓位）")
    print(f"  当前方法：risk_per_trade=1%，position_cap=5%（实际风险≈0.24%）")
    print(f"  方案  B：risk_cap=0.5%，notional_cap=15%（双约束真实风险控制）")
    print("=" * 65)
    print(f"  {'指标':<22} {'当前方法':>12} {'方案 B':>12} {'差异':>10}")
    print(f"  {'-'*56}")
    for label, bv, obv in rows:
        try:
            diff = obv - bv
            diff_str = f"{diff:+.2f}" if isinstance(diff, float) else f"{diff:+d}"
        except Exception:
            diff_str = "—"
        print(f"  {label:<22} {bv:>12} {obv:>12} {diff_str:>10}")
    print("=" * 65)
    print(f"\n  结果已保存 → {OPTB_DIR.resolve()}")
    print(f"  对比 JSON  → {cmp_path.resolve()}")


if __name__ == "__main__":
    main()
