"""
Walk-Forward OOS validation — Phase 6, Week 4.

Uses the EXISTING full-period backtest (nav.csv + trades.csv) to extract
OOS performance for each expanding window.  No new backtests are required:
slicing the already-computed equity curve into IS / OOS periods is both
correct and fast.

Design-spec reference: Section 3.5.7.

Walk-Forward Windows (expanding IS, 1-year OOS each):
  Window 1 : IS 2000–2021  OOS 2022
  Window 2 : IS 2000–2022  OOS 2023
  Window 3 : IS 2000–2023  OOS 2024
  Window 4 : IS 2000–2024  OOS 2025
  Window 5 : IS 2000–2025  OOS 2026 (partial, ends 2026-06-15)

Public API
----------
WALK_FORWARD_WINDOWS : list[dict]
run_walk_forward(daily_nav, daily_returns, trade_log, spy_returns) -> dict
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

__all__ = ["WALK_FORWARD_WINDOWS", "run_walk_forward"]

# ── Window definitions ────────────────────────────────────────────────────────

WALK_FORWARD_WINDOWS: list[dict] = [
    {"label": "Window 1", "is_start": "2004-01-01", "is_end": "2021-12-31",
     "oos_start": "2022-01-01", "oos_end": "2022-12-31"},
    {"label": "Window 2", "is_start": "2004-01-01", "is_end": "2022-12-31",
     "oos_start": "2023-01-01", "oos_end": "2023-12-31"},
    {"label": "Window 3", "is_start": "2004-01-01", "is_end": "2023-12-31",
     "oos_start": "2024-01-01", "oos_end": "2024-12-31"},
    {"label": "Window 4", "is_start": "2004-01-01", "is_end": "2024-12-31",
     "oos_start": "2025-01-01", "oos_end": "2025-12-31"},
    {"label": "Window 5", "is_start": "2004-01-01", "is_end": "2025-12-31",
     "oos_start": "2026-01-01", "oos_end": "2026-12-31"},
]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _slice_metrics(
    nav: pd.Series,
    returns: pd.Series,
    trade_log: pd.DataFrame,
    start: str,
    end: str,
    rf: float = 0.02,
) -> dict:
    nav_sl = nav.loc[start:end]
    ret_sl = returns.loc[start:end]

    if nav_sl.empty:
        return {}

    n_days = len(nav_sl)
    cagr = float((nav_sl.iloc[-1] / nav_sl.iloc[0]) ** (252.0 / n_days) - 1.0)

    ann_vol = float(ret_sl.std() * math.sqrt(252)) if len(ret_sl) > 1 else 0.0
    sharpe  = (ret_sl.mean() * 252 - rf) / ann_vol if ann_vol > 0 else 0.0

    cum_max = nav_sl.cummax()
    dd      = (nav_sl - cum_max) / cum_max
    max_dd  = float(dd.min())

    calmar = cagr / abs(max_dd) if abs(max_dd) > 1e-9 else 0.0

    tl_sl = pd.DataFrame()
    if trade_log is not None and not trade_log.empty and "exit_date" in trade_log.columns:
        tl_sl = trade_log[
            (trade_log["exit_date"] >= start) & (trade_log["exit_date"] <= end)
        ]

    n_trades = len(tl_sl)
    win_rate = 0.0
    if n_trades > 0:
        pnl_col = "net_pnl" if "net_pnl" in tl_sl.columns else "gross_pnl"
        win_rate = float((tl_sl[pnl_col] > 0).mean())

    return {
        "cagr":         cagr,
        "sharpe":       float(sharpe),
        "max_drawdown": max_dd,
        "calmar":       calmar,
        "annual_vol":   ann_vol,
        "n_trading_days": n_days,
        "n_trades":     n_trades,
        "win_rate":     win_rate,
    }


def _spy_metrics(
    spy_returns: pd.Series,
    start: str,
    end: str,
    rf: float = 0.02,
) -> dict:
    if spy_returns is None:
        return {}
    sl = spy_returns.loc[start:end]
    if sl.empty:
        return {}
    nav = (1 + sl).cumprod()
    n = len(nav)
    cagr = float((nav.iloc[-1]) ** (252.0 / n) - 1.0)
    ann_vol = float(sl.std() * math.sqrt(252)) if len(sl) > 1 else 0.0
    sharpe  = (sl.mean() * 252 - rf) / ann_vol if ann_vol > 0 else 0.0
    cum_max = nav.cummax()
    max_dd  = float(((nav - cum_max) / cum_max).min())
    return {"cagr": cagr, "sharpe": float(sharpe), "max_drawdown": max_dd}


# ── Public API ────────────────────────────────────────────────────────────────

def run_walk_forward(
    daily_nav: pd.Series,
    daily_returns: pd.Series,
    trade_log: pd.DataFrame,
    spy_returns: pd.Series | None = None,
    windows: list[dict] | None = None,
    risk_free_rate: float = 0.02,
) -> dict:
    """
    Expanding-window Walk-Forward OOS validation.

    For each window, slices the full-period backtest results into IS and OOS
    portions and computes metrics for each.  Also stitches all OOS periods
    into a single equity curve.

    Parameters
    ----------
    daily_nav : pd.Series
        Full-period NAV (DatetimeIndex).
    daily_returns : pd.Series
        Full-period daily returns.
    trade_log : pd.DataFrame
        Full-period trade log.
    spy_returns : pd.Series | None
        SPY daily returns for benchmark comparison.
    windows : list[dict] | None
        Walk-forward window specs.  Defaults to WALK_FORWARD_WINDOWS.
    risk_free_rate : float

    Returns
    -------
    dict with keys:
        "windows"          : per-window IS + OOS metrics
        "oos_stitched"     : combined OOS equity curve (dates + nav normalised to 1.0)
        "oos_stitched_spy" : SPY benchmark for same OOS period
        "retention"        : CAGR / Sharpe / MaxDD retention ratios (OOS / IS)
        "full_is"          : full IS metrics (entire backtest period)
    """
    if windows is None:
        windows = WALK_FORWARD_WINDOWS

    # Ensure DatetimeIndex
    if not isinstance(daily_nav.index, pd.DatetimeIndex):
        daily_nav.index = pd.to_datetime(daily_nav.index)
    if not isinstance(daily_returns.index, pd.DatetimeIndex):
        daily_returns.index = pd.to_datetime(daily_returns.index)
    if trade_log is not None and not trade_log.empty and "exit_date" in trade_log.columns:
        trade_log = trade_log.copy()
        trade_log["exit_date"] = pd.to_datetime(trade_log["exit_date"])
    if spy_returns is not None and not isinstance(spy_returns.index, pd.DatetimeIndex):
        spy_returns.index = pd.to_datetime(spy_returns.index)

    actual_end = str(daily_nav.index[-1].date())

    # Full IS metrics
    full_start = str(daily_nav.index[0].date())
    full_is = _slice_metrics(
        daily_nav, daily_returns, trade_log, full_start, actual_end, risk_free_rate,
    )

    window_results: list[dict] = []
    oos_nav_pieces: list[pd.Series] = []
    oos_spy_pieces: list[pd.Series] = []

    for w in windows:
        oos_end_actual = min(w["oos_end"], actual_end)
        if w["oos_start"] > actual_end:
            continue  # OOS period hasn't been reached yet

        is_m  = _slice_metrics(daily_nav, daily_returns, trade_log,
                               w["is_start"], w["is_end"], risk_free_rate)
        oos_m = _slice_metrics(daily_nav, daily_returns, trade_log,
                               w["oos_start"], oos_end_actual, risk_free_rate)

        spy_oos = _spy_metrics(spy_returns, w["oos_start"], oos_end_actual, risk_free_rate)

        window_results.append({
            "label":     w["label"],
            "is_start":  w["is_start"],
            "is_end":    w["is_end"],
            "oos_start": w["oos_start"],
            "oos_end":   oos_end_actual,
            "is":        is_m,
            "oos":       oos_m,
            "spy_oos":   spy_oos,
        })

        # Collect OOS NAV slice (normalised to start at 1.0)
        oos_nav = daily_nav.loc[w["oos_start"]:oos_end_actual]
        if not oos_nav.empty:
            oos_nav_pieces.append(oos_nav / oos_nav.iloc[0])

        if spy_returns is not None:
            spy_oos_ret = spy_returns.loc[w["oos_start"]:oos_end_actual]
            if not spy_oos_ret.empty:
                spy_oos_nav = (1 + spy_oos_ret).cumprod()
                oos_spy_pieces.append(spy_oos_nav)

    # Stitch OOS equity curve (each window normalised to 1.0 at its start,
    # then chain-linked: window[i] starts at window[i-1]'s final value)
    stitched_dates: list[str] = []
    stitched_nav:   list[float] = []
    running_level = 1.0

    for piece in oos_nav_pieces:
        nav_linked = piece * running_level
        stitched_dates.extend([str(d.date()) for d in nav_linked.index])
        stitched_nav.extend(nav_linked.tolist())
        running_level = nav_linked.iloc[-1]

    stitched_spy_dates: list[str] = []
    stitched_spy_nav:   list[float] = []
    running_spy = 1.0
    for piece in oos_spy_pieces:
        spy_linked = piece * running_spy
        stitched_spy_dates.extend([str(d.date()) for d in spy_linked.index])
        stitched_spy_nav.extend(spy_linked.tolist())
        running_spy = spy_linked.iloc[-1]

    # Retention metrics (average OOS/IS ratio across windows)
    def _retention(key: str) -> float:
        ratios = []
        for wr in window_results:
            is_val  = wr["is"].get(key, 0.0)
            oos_val = wr["oos"].get(key, 0.0)
            if abs(is_val) > 1e-9:
                ratios.append(oos_val / is_val)
        return float(np.mean(ratios)) if ratios else 0.0

    retention = {
        "cagr_retention":   _retention("cagr"),
        "sharpe_retention": _retention("sharpe"),
    }

    # OOS stitched metrics
    oos_stitched_metrics: dict = {}
    if stitched_nav and len(stitched_nav) > 1:
        oos_nav_s = pd.Series(stitched_nav)
        oos_ret_s = oos_nav_s.pct_change().dropna()
        n = len(oos_nav_s)
        cagr = float((oos_nav_s.iloc[-1]) ** (252.0 / n) - 1.0)
        ann_vol = float(oos_ret_s.std() * math.sqrt(252))
        sharpe  = (oos_ret_s.mean() * 252 - risk_free_rate) / ann_vol if ann_vol > 0 else 0.0
        cum_max = oos_nav_s.cummax()
        max_dd  = float(((oos_nav_s - cum_max) / cum_max).min())
        oos_stitched_metrics = {
            "cagr": cagr, "sharpe": float(sharpe),
            "max_drawdown": max_dd, "annual_vol": ann_vol,
        }

    return {
        "windows":           window_results,
        "full_is":           full_is,
        "retention":         retention,
        "oos_stitched": {
            "dates": stitched_dates,
            "nav":   stitched_nav,
            "metrics": oos_stitched_metrics,
        },
        "oos_stitched_spy": {
            "dates": stitched_spy_dates,
            "nav":   stitched_spy_nav,
        },
    }
