"""
对比回测：熊市豁免 TLT + GLD

基准策略（baseline）：熊市期间（SPY < 200MA）停止一切新开仓。
实验策略（bear_exempt）：熊市期间允许 TLT 和 GLD 正常接收入场信号。

所有其他参数完全相同：止损、仓位大小、热度限制、相关性过滤等。

运行方式：
    /Users/xuchun/anaconda3/bin/python3 src/scripts/run_bear_exempt_comparison.py
"""

import json
import logging
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "src"))

_env = _root / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import numpy as np
import pandas as pd

from data.pipeline import compute_adj_prices
from data.universe import EXCLUDED_VOL_ETFS
from indicators.precompute import precompute_indicators
from backtest.engine import BacktestEngine
from strategy.params import StrategyParams
from strategy.v1.strategy_v1 import StrategyV1

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TIINGO_CACHE      = _root / "data" / "cache" / "tiingo"
EU_CSV            = _root / "data" / "tiingo_eligible_universe.csv"
OUTPUT_DIR        = _root / "results" / "bear_exempt_comparison"
START             = "2000-01-03"
END               = "2026-06-15"
MIN_ELIGIBLE_DAYS = 252
BEAR_EXEMPT       = frozenset({"TLT", "GLD"})

BASE_PARAMS = StrategyParams(
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
)

AUXILIARY = {BASE_PARAMS.cash_proxy, "SPY", BASE_PARAMS.regime_ticker}


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_panel(tickers, start, end):
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    panel = {}
    for ticker in tickers:
        path = TIINGO_CACHE / f"{ticker.upper()}.parquet"
        if not path.exists():
            continue
        try:
            df = pd.read_parquet(path)
            df.index = pd.DatetimeIndex(df.index)
            df = df.sort_index()[(df.index >= start_ts) & (df.index.date <= pd.Timestamp(end).date())]
            if not df.empty:
                panel[ticker] = compute_adj_prices(df)
        except Exception as e:
            logger.warning("Skip %s: %s", ticker, e)
    return panel


def load_universe():
    eu = pd.read_csv(EU_CSV)
    tickers = eu[eu["eligible_days"] >= MIN_ELIGIBLE_DAYS]["ticker"].tolist()
    tickers = [t for t in tickers if t not in EXCLUDED_VOL_ETFS]
    return sorted(tickers)


def run_backtest(params, panel, indicators, strategy_tickers, label):
    print(f"\n{'='*60}")
    print(f"  运行：{label}")
    print(f"{'='*60}")
    t0 = time.time()
    strategy = StrategyV1(params)
    engine   = BacktestEngine(
        strategy=strategy,
        price_panel=panel,
        indicators=indicators,
        params=params,
        initial_capital=10_000_000,
    )
    results = engine.run(START, END, strategy_tickers)
    elapsed = time.time() - t0
    m = results.compute_metrics()
    print(f"  完成：{elapsed:.0f}s  |  交易数={len(results.trade_log):,}  |  CAGR={m['cagr']*100:.2f}%")
    return results


def capital_util_series(results):
    """Compute daily capital utilisation (cost basis / NAV)."""
    util = {}
    nav_dict = dict(results.daily_nav)
    cost_dict = {}
    for date, positions in results.daily_positions.items():
        cost = sum(p.get("entry_price", 0) * p.get("shares", 0) for p in positions.values()
                   if p.get("ticker") not in (AUXILIARY | {"SHY"}))
        nav  = nav_dict.get(date, 1)
        cost_dict[date] = cost / nav if nav > 0 else 0
    return pd.Series(cost_dict).sort_index()


def compute_bear_dates(panel):
    """Return set of dates where SPY < 200-day SMA (bear market)."""
    spy_df = panel.get("SPY")
    if spy_df is None:
        return set()
    adj = spy_df["adj_close"] if "adj_close" in spy_df.columns else spy_df["close"]
    sma = adj.rolling(200, min_periods=200).mean()
    bear = adj[sma.notna() & (adj <= sma)].index
    return set(bear)


def bear_period_trades(results, bear_dates):
    """Return trades entered during bear market periods."""
    trades = results.trade_log if hasattr(results, 'trade_log') else results.trades
    if trades is None or len(trades) == 0:
        return pd.DataFrame()
    entry_col = "entry_date" if "entry_date" in trades.columns else trades.columns[1]
    mask = pd.DatetimeIndex(trades[entry_col]).normalize().isin(
        pd.DatetimeIndex(list(bear_dates)).normalize()
    )
    return trades[mask]


def print_comparison(base_res, exp_res, panel):
    bm  = base_res.compute_metrics()
    em  = exp_res.compute_metrics()

    bear_dates = compute_bear_dates(panel)
    bear_pct   = len(bear_dates) / len(panel.get("SPY", pd.DataFrame())) * 100

    # Capital utilisation
    base_util = capital_util_series(base_res)
    exp_util  = capital_util_series(exp_res)

    # Bear-period util
    bear_idx_base = base_util.index[base_util.index.isin(bear_dates)]
    bear_idx_exp  = exp_util.index[exp_util.index.isin(bear_dates)]
    base_bear_util = base_util.loc[bear_idx_base].mean() if len(bear_idx_base) else 0
    exp_bear_util  = exp_util.loc[bear_idx_exp].mean()   if len(bear_idx_exp)  else 0

    # Bear-period trades for exempt tickers
    base_trades = base_res.trades if hasattr(base_res, 'trades') else pd.DataFrame(base_res.trade_log)
    exp_trades  = exp_res.trades  if hasattr(exp_res,  'trades') else pd.DataFrame(exp_res.trade_log)

    exempt_bear_trades = bear_period_trades(exp_res, bear_dates)
    exempt_only = exempt_bear_trades[exempt_bear_trades["ticker"].isin(BEAR_EXEMPT)] if len(exempt_bear_trades) else pd.DataFrame()

    W = 20
    fmt = lambda v, pct=True: f"{v*100:.2f}%" if pct else f"{v:.3f}"

    print(f"\n{'='*65}")
    print(f"  对比结果：基准策略 vs 熊市豁免 TLT+GLD")
    print(f"{'='*65}")
    print(f"  回测期间：{START} → {END}")
    print(f"  熊市天数：{len(bear_dates):,} 天（占全程 {bear_pct:.1f}%）")
    print(f"\n  {'指标':<25} {'基准（Baseline）':>18} {'豁免TLT+GLD':>18} {'变化':>10}")
    print(f"  {'-'*73}")

    rows = [
        ("CAGR",           bm['cagr'],         em['cagr'],         True),
        ("Sharpe 比率",    bm['sharpe'],        em['sharpe'],       False),
        ("最大回撤",        bm['max_drawdown'],  em['max_drawdown'], True),
        ("Sortino 比率",   bm.get('sortino',0), em.get('sortino',0),False),
        ("Calmar 比率",    bm.get('calmar',0),  em.get('calmar',0), False),
        ("Profit Factor",  bm.get('profit_factor',0), em.get('profit_factor',0), False),
    ]
    for name, bv, ev, is_pct in rows:
        diff = ev - bv
        sign = "+" if diff >= 0 else ""
        dstr = f"{sign}{diff*100:.2f}pp" if is_pct else f"{sign}{diff:.3f}"
        bstr = fmt(bv, is_pct)
        estr = fmt(ev, is_pct)
        print(f"  {name:<25} {bstr:>18} {estr:>18} {dstr:>10}")

    print(f"\n  {'资金使用率（全程均值）':<25} {base_util.mean()*100:.1f}%{'':<13} {exp_util.mean()*100:.1f}%{'':<13}")
    print(f"  {'资金使用率（仅熊市）':<25} {base_bear_util*100:.1f}%{'':<13} {exp_bear_util*100:.1f}%{'':<13}")
    print(f"\n  {'总交易笔数':<25} {len(base_trades):>18,} {len(exp_trades):>18,}")
    if len(exempt_only):
        tlt_n = (exempt_only["ticker"] == "TLT").sum()
        gld_n = (exempt_only["ticker"] == "GLD").sum()
        print(f"  {'  熊市期间TLT交易':<25} {0:>18} {tlt_n:>18}")
        print(f"  {'  熊市期间GLD交易':<25} {0:>18} {gld_n:>18}")
        # PnL of exempt trades
        if "net_pnl" in exempt_only.columns:
            total_pnl = exempt_only["net_pnl"].sum()
            win_rate  = (exempt_only["net_pnl"] > 0).mean()
            print(f"\n  TLT+GLD 熊市交易净盈亏：${total_pnl:,.0f}  胜率：{win_rate*100:.0f}%")

    print(f"\n{'='*65}")

    # Save JSON summary
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "baseline": {k: round(float(v), 6) for k, v in bm.items()},
        "bear_exempt": {k: round(float(v), 6) for k, v in em.items()},
        "bear_exempt_tickers": list(BEAR_EXEMPT),
        "bear_market_pct": round(bear_pct, 2),
        "capital_util_mean_baseline": round(float(base_util.mean()), 4),
        "capital_util_mean_exempt": round(float(exp_util.mean()), 4),
        "capital_util_bear_baseline": round(float(base_bear_util), 4),
        "capital_util_bear_exempt": round(float(exp_bear_util), 4),
        "n_trades_baseline": len(base_trades),
        "n_trades_exempt": len(exp_trades),
    }
    out = OUTPUT_DIR / "comparison_summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n  结果已保存至：{out}")


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    print("加载标的池...")
    universe = load_universe()
    load_list = sorted(set(universe) | AUXILIARY)

    print(f"加载价格数据（{len(load_list)} 只标的）...")
    t0 = time.time()
    panel = load_panel(load_list, START, END)
    print(f"  完成：{time.time()-t0:.1f}s，加载 {len(panel)} 只")

    strategy_tickers = [t for t in universe if t in panel and t not in AUXILIARY]
    print(f"策略标的池：{len(strategy_tickers):,} 只")

    print("预计算指标...")
    t0 = time.time()
    indicators = precompute_indicators(
        {t: panel[t] for t in strategy_tickers}, BASE_PARAMS
    )
    print(f"  完成：{time.time()-t0:.1f}s")

    # ── 基准回测 ──────────────────────────────────────────────────────────────
    params_base = replace(BASE_PARAMS, bear_exempt_tickers=frozenset())
    base_res = run_backtest(params_base, panel, indicators, strategy_tickers, "基准策略（无豁免）")

    # ── 豁免回测 ──────────────────────────────────────────────────────────────
    params_exempt = replace(BASE_PARAMS, bear_exempt_tickers=BEAR_EXEMPT)
    exp_res = run_backtest(params_exempt, panel, indicators, strategy_tickers, "豁免 TLT+GLD")

    # ── 打印对比 ──────────────────────────────────────────────────────────────
    print_comparison(base_res, exp_res, panel)


if __name__ == "__main__":
    main()
