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

import pandas as pd

from data.pipeline import compute_adj_prices
from data.universe import EXCLUDED_VOL_ETFS
from indicators.precompute import precompute_indicators
from backtest.engine import BacktestEngine
from strategy.params import StrategyParams
from strategy.v1.strategy_v1 import StrategyV1

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

TIINGO_CACHE      = _root / "data" / "cache" / "tiingo"
EU_CSV            = _root / "data" / "tiingo_eligible_universe.csv"
OUTPUT_DIR        = _root / "results" / "bear_exempt_comparison"
START             = "2000-01-03"
END               = "2026-06-15"
MIN_ELIGIBLE_DAYS = 252
BEAR_EXEMPT       = frozenset({"TLT", "GLD", "UUP"})

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
            df = df.sort_index()
            df = df[(df.index >= start_ts) & (df.index <= end_ts)]
            if not df.empty:
                panel[ticker] = compute_adj_prices(df)
        except Exception as e:
            pass
    return panel


def load_universe():
    eu = pd.read_csv(EU_CSV)
    tickers = eu[eu["eligible_days"] >= MIN_ELIGIBLE_DAYS]["ticker"].tolist()
    tickers = [t for t in tickers if t not in EXCLUDED_VOL_ETFS]
    return sorted(tickers)


def run_backtest(params, panel, indicators, strategy_tickers, label):
    print(f"\n  运行：{label} ...")
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
    m = results.compute_metrics()
    print(f"  完成：{time.time()-t0:.0f}s  |  交易数={len(results.trade_log):,}  |  CAGR={m['cagr']*100:.2f}%")
    return results


def capital_util_series(trade_log, nav):
    """Compute daily capital utilisation (cost basis / NAV) from trade_log."""
    df = trade_log.copy()
    if df.empty:
        return pd.Series(0.0, index=nav.index)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"]  = pd.to_datetime(df["exit_date"])
    # Exclude SHY (cash proxy)
    df = df[df["ticker"] != BASE_PARAMS.cash_proxy]
    df["entry_value"] = df["shares"] * df["entry_price"]
    dates = pd.to_datetime(nav.index)
    entry_vals = df.groupby("entry_date")["entry_value"].sum().reindex(dates, fill_value=0.0)
    exit_vals  = df.groupby("exit_date")["entry_value"].sum().reindex(dates, fill_value=0.0)
    daily_invested = (entry_vals - exit_vals).cumsum().clip(lower=0.0)
    util = (daily_invested / nav.values).clip(lower=0.0, upper=1.0)
    util.index = dates
    return util


def bear_market_dates(panel):
    """Return pd.DatetimeIndex of bear market days (SPY < 200-day SMA)."""
    spy_df = panel.get("SPY")
    if spy_df is None:
        return pd.DatetimeIndex([])
    adj = spy_df["adj_close"] if "adj_close" in spy_df.columns else spy_df["close"]
    sma = adj.rolling(200, min_periods=200).mean()
    bear = adj.index[(sma.notna()) & (adj <= sma)]
    return pd.DatetimeIndex(bear)


def print_comparison(base_res, exp_res, panel):
    bm = base_res.compute_metrics()
    em = exp_res.compute_metrics()

    bear_dates = bear_market_dates(panel)
    total_days = len(base_res.daily_nav)
    bear_pct   = len(bear_dates) / total_days * 100 if total_days else 0

    # Capital utilisation series
    base_util = capital_util_series(base_res.trade_log, base_res.daily_nav)
    exp_util  = capital_util_series(exp_res.trade_log,  exp_res.daily_nav)

    # Bear-period utilisation
    base_bear = base_util[base_util.index.isin(bear_dates)].mean()
    exp_bear  = exp_util[exp_util.index.isin(bear_dates)].mean()

    # Exempt-ticker trades during bear markets
    exp_tl = exp_res.trade_log.copy()
    exp_tl["entry_date"] = pd.to_datetime(exp_tl["entry_date"])
    bear_exempt_trades = exp_tl[
        exp_tl["ticker"].isin(BEAR_EXEMPT) &
        exp_tl["entry_date"].isin(bear_dates)
    ]

    print(f"\n{'='*68}")
    print(f"  对比结果：基准策略 vs 熊市豁免 TLT+GLD+UUP")
    print(f"{'='*68}")
    print(f"  回测期间：{START} → {END}")
    print(f"  熊市天数：{len(bear_dates):,} 天（占全程 {bear_pct:.1f}%）\n")

    rows = [
        ("CAGR",        bm['cagr'],              em['cagr'],              True),
        ("Sharpe",      bm['sharpe'],             em['sharpe'],            False),
        ("最大回撤",     bm['max_drawdown'],       em['max_drawdown'],      True),
        ("Sortino",     bm.get('sortino', 0),     em.get('sortino', 0),    False),
        ("Calmar",      bm.get('calmar', 0),      em.get('calmar', 0),     False),
        ("Profit Factor", bm.get('profit_factor', 0), em.get('profit_factor', 0), False),
    ]

    print(f"  {'指标':<20} {'基准':>16} {'豁免TLT+GLD':>16} {'变化':>12}")
    print(f"  {'-'*66}")
    for name, bv, ev, is_pct in rows:
        diff = ev - bv
        sign = "+" if diff >= 0 else ""
        if is_pct:
            dstr = f"{sign}{diff*100:.2f}pp"
            bstr = f"{bv*100:.2f}%"
            estr = f"{ev*100:.2f}%"
        else:
            dstr = f"{sign}{diff:.3f}"
            bstr = f"{bv:.3f}"
            estr = f"{ev:.3f}"
        print(f"  {name:<20} {bstr:>16} {estr:>16} {dstr:>12}")

    print(f"\n  {'资金使用率（全程均值）':<20} {base_util.mean()*100:>15.1f}% {exp_util.mean()*100:>15.1f}%")
    print(f"  {'资金使用率（仅熊市）':<20} {base_bear*100:>15.1f}% {exp_bear*100:>15.1f}%")

    print(f"\n  {'总交易笔数':<20} {len(base_res.trade_log):>16,} {len(exp_res.trade_log):>16,}")

    if len(bear_exempt_trades):
        for tkr in sorted(BEAR_EXEMPT):
            n = (bear_exempt_trades["ticker"] == tkr).sum()
            print(f"  {'  熊市 ' + tkr + ' 交易':<20} {'0':>16} {n:>16}")
        if "net_pnl" in bear_exempt_trades.columns:
            pnl  = bear_exempt_trades["net_pnl"].sum()
            wins = (bear_exempt_trades["net_pnl"] > 0).mean()
            print(f"\n  TLT+GLD+UUP 熊市净盈亏：${pnl:,.0f}  |  胜率：{wins*100:.0f}%")
            if len(bear_exempt_trades) > 1:
                by_tkr = bear_exempt_trades.groupby("ticker")["net_pnl"].agg(["sum","count","mean"])
                for tkr, row in by_tkr.iterrows():
                    print(f"    {tkr}:  总盈亏=${row['sum']:,.0f}  笔数={int(row['count'])}  均值=${row['mean']:,.0f}")

    print(f"\n{'='*68}")

    # Save JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "start":       START,
        "end":         END,
        "baseline":    {k: round(float(v), 6) for k, v in bm.items()},
        "bear_exempt": {k: round(float(v), 6) for k, v in em.items()},
        "bear_exempt_tickers": sorted(BEAR_EXEMPT),
        "bear_market_pct":     round(bear_pct, 2),
        "capital_util_mean_baseline": round(float(base_util.mean()), 4),
        "capital_util_mean_exempt":   round(float(exp_util.mean()), 4),
        "capital_util_bear_baseline": round(float(base_bear), 4),
        "capital_util_bear_exempt":   round(float(exp_bear), 4),
        "n_trades_baseline": int(len(base_res.trade_log)),
        "n_trades_exempt":   int(len(exp_res.trade_log)),
        "n_bear_exempt_trades": int(len(bear_exempt_trades)),
    }
    out = OUTPUT_DIR / "comparison_summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"  结果已保存至：{out}")


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
    indicators = precompute_indicators({t: panel[t] for t in strategy_tickers}, BASE_PARAMS)
    print(f"  完成：{time.time()-t0:.1f}s")

    print(f"\n开始两组回测...(各约需 2-3 分钟)")

    base_res = run_backtest(
        replace(BASE_PARAMS, bear_exempt_tickers=frozenset()),
        panel, indicators, strategy_tickers,
        "基准策略（无豁免）",
    )

    exp_res = run_backtest(
        replace(BASE_PARAMS, bear_exempt_tickers=BEAR_EXEMPT),
        panel, indicators, strategy_tickers,
        "豁免 TLT+GLD+UUP",
    )

    print_comparison(base_res, exp_res, panel)


if __name__ == "__main__":
    main()
