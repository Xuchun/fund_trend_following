"""
Market regime analysis — Phase 6, Week 4.

Slices existing backtest results (nav.csv + trades.csv) into historical
market regimes and computes per-regime performance metrics.
No new backtests are required — all analysis runs on pre-computed results.

Design-spec reference: Section 3.5.8.

Public API
----------
REGIMES : dict
run_regime_analysis(daily_nav, daily_returns, trade_log, spy_returns, regimes) -> dict
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

__all__ = ["REGIMES", "run_regime_analysis"]

# ── Regime definitions ────────────────────────────────────────────────────────

REGIMES: dict[str, tuple[str, str]] = {
    "互联网泡沫崩溃": ("2000-03-01", "2002-10-31"),  # S&P500 顶部 2000-03，底部 2002-10-09
    "熊市后复苏":     ("2002-11-01", "2007-10-31"),  # 底部次月 → S&P500 再次见顶 2007-10-09
    "金融危机":       ("2007-11-01", "2009-03-31"),  # 顶部次月 → S&P500 底部 2009-03-09
    "QE驱动慢牛":     ("2009-04-01", "2020-01-31"),  # 底部次月 → COVID 冲击前最后完整月
    "COVID崩盘+复苏": ("2020-02-01", "2021-12-31"),  # 暴跌始于 2020-02-19
    "加息熊市":       ("2022-01-01", "2022-12-31"),  # 全年
    "AI驱动牛市":     ("2023-01-01", "2026-06-30"),  # 延伸至回测结束日 2026-06-15
}


# ── Internal metric helpers ───────────────────────────────────────────────────

def _cagr(nav: pd.Series) -> float:
    if len(nav) < 2:
        return 0.0
    n_days = len(nav)
    return float((nav.iloc[-1] / nav.iloc[0]) ** (252.0 / n_days) - 1.0)


def _sharpe(returns: pd.Series, rf: float = 0.02) -> float:
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    return float((returns.mean() * 252 - rf) / (returns.std() * math.sqrt(252)))


def _max_drawdown(nav: pd.Series) -> float:
    if nav.empty:
        return 0.0
    cum_max = nav.cummax()
    dd = (nav - cum_max) / cum_max
    return float(dd.min())


def _annual_vol(returns: pd.Series) -> float:
    if len(returns) < 2:
        return 0.0
    return float(returns.std() * math.sqrt(252))


def _slice_metrics(
    nav: pd.Series,
    returns: pd.Series,
    trade_log: pd.DataFrame,
    start: str,
    end: str,
    rf: float = 0.02,
) -> dict:
    """Compute metrics for a date-sliced window."""
    nav_sl = nav.loc[start:end]
    ret_sl = returns.loc[start:end]

    if nav_sl.empty:
        return {}

    tl_sl = pd.DataFrame()
    if trade_log is not None and not trade_log.empty and "exit_date" in trade_log.columns:
        tl_sl = trade_log[
            (trade_log["exit_date"] >= start) & (trade_log["exit_date"] <= end)
        ]

    n_trades = len(tl_sl)
    win_rate = 0.0
    profit_factor = 0.0
    if n_trades > 0:
        pnl_col = "net_pnl" if "net_pnl" in tl_sl.columns else "gross_pnl"
        wins   = tl_sl[tl_sl[pnl_col] > 0]
        losses = tl_sl[tl_sl[pnl_col] <= 0]
        win_rate = len(wins) / n_trades
        total_win  = float(wins[pnl_col].sum()) if len(wins) > 0 else 0.0
        total_loss = float(losses[pnl_col].abs().sum()) if len(losses) > 0 else 1e-9
        profit_factor = total_win / total_loss if total_loss > 0 else 0.0

    return {
        "cagr":          _cagr(nav_sl),
        "max_drawdown":  _max_drawdown(nav_sl),
        "sharpe":        _sharpe(ret_sl, rf),
        "annual_vol":    _annual_vol(ret_sl),
        "n_trading_days": len(nav_sl),
        "n_trades":      n_trades,
        "win_rate":      win_rate,
        "profit_factor": profit_factor,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def run_regime_analysis(
    daily_nav: pd.Series,
    daily_returns: pd.Series,
    trade_log: pd.DataFrame,
    spy_returns: pd.Series | None = None,
    regimes: dict[str, tuple[str, str]] | None = None,
    risk_free_rate: float = 0.02,
) -> dict:
    """
    Compute per-regime performance metrics from existing backtest results.

    No new backtests are run.  All metrics are computed by slicing daily_nav,
    daily_returns, and trade_log into each regime's date range.

    Parameters
    ----------
    daily_nav : pd.Series
        Full-period NAV indexed by date.
    daily_returns : pd.Series
        Full-period daily returns indexed by date.
    trade_log : pd.DataFrame
        Full-period trade log (exit_date used for trade allocation).
    spy_returns : pd.Series | None
        SPY daily returns (optional, for benchmark comparison).
    regimes : dict | None
        {name: (start, end)} mapping.  Defaults to REGIMES.
    risk_free_rate : float
        Annual risk-free rate for Sharpe (default 2%).

    Returns
    -------
    dict with keys:
        "regimes": {name: {"start", "end", "strategy": {...}, "spy": {...}}}
        "full_period": {...}  — baseline IS metrics for comparison
    """
    if regimes is None:
        regimes = REGIMES

    # Ensure DatetimeIndex
    for s in (daily_nav, daily_returns):
        if not isinstance(s.index, pd.DatetimeIndex):
            s.index = pd.to_datetime(s.index)

    if spy_returns is not None and not isinstance(spy_returns.index, pd.DatetimeIndex):
        spy_returns.index = pd.to_datetime(spy_returns.index)

    # Ensure trade_log dates are timestamps
    if trade_log is not None and not trade_log.empty:
        if "exit_date" in trade_log.columns:
            trade_log = trade_log.copy()
            trade_log["exit_date"] = pd.to_datetime(trade_log["exit_date"])

    result: dict = {}

    # Full-period baseline
    result["full_period"] = _slice_metrics(
        daily_nav, daily_returns, trade_log,
        str(daily_nav.index[0].date()), str(daily_nav.index[-1].date()),
        risk_free_rate,
    )

    # Per-regime
    regime_results: dict = {}
    for name, (start, end) in regimes.items():
        strategy_m = _slice_metrics(
            daily_nav, daily_returns, trade_log, start, end, risk_free_rate,
        )
        if not strategy_m:
            continue

        spy_m: dict = {}
        if spy_returns is not None:
            spy_sl = spy_returns.loc[start:end]
            if not spy_sl.empty:
                spy_nav = (1 + spy_sl).cumprod()
                spy_nav = spy_nav / spy_nav.iloc[0]
                spy_m = {
                    "cagr":         _cagr(spy_nav),
                    "max_drawdown": _max_drawdown(spy_nav),
                    "sharpe":       _sharpe(spy_sl, risk_free_rate),
                    "annual_vol":   _annual_vol(spy_sl),
                }

        regime_results[name] = {
            "start":    start,
            "end":      end,
            "strategy": strategy_m,
            "spy":      spy_m,
        }

    result["regimes"] = regime_results
    return result
