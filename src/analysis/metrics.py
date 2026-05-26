"""
Core performance metrics — Phase 6, Week 1.

Standalone module: accepts only pd.Series / pd.DataFrame, returns plain dict.
No imports from backtest/, strategy/, or data/.

Design-spec reference: Section 1.2.1.2 and Section 3.5.1.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


# ── Public API ─────────────────────────────────────────────────────────────


def compute_metrics(
    daily_nav: pd.Series,
    daily_returns: pd.Series,
    trade_log: pd.DataFrame,
    initial_capital: float,
    risk_free_rate: float = 0.02,
) -> dict:
    """
    Compute all core performance indicators defined in design-spec 1.2.1.2.

    Parameters
    ----------
    daily_nav : pd.Series
        Absolute NAV values indexed by date.
    daily_returns : pd.Series
        Daily fractional returns (pct-change of NAV) indexed by date.
    trade_log : pd.DataFrame
        One row per completed trade.  Expected columns (subset):
        entry_date, exit_date, holding_days, net_pnl, pnl_r_multiple,
        entry_price, shares, R, exit_reason.
    initial_capital : float
        Starting NAV in dollars (used for turnover denominator).
    risk_free_rate : float
        Annual risk-free rate (default 2 % — historical US T-bill average).

    Returns
    -------
    dict with keys grouped by category:

    Returns:
        cagr, total_return

    Risk:
        annual_vol, max_drawdown, max_dd_duration_days,
        avg_deep_dd_duration_days, n_deep_dd_episodes

    Risk-adjusted:
        sharpe, sortino, calmar

    Trade statistics:
        n_trades, win_rate, avg_win_r, avg_loss_r, profit_factor,
        avg_holding_days, trades_per_year

    Portfolio:
        annual_turnover, market_exposure
    """
    metrics: dict = {}

    # ── Return metrics ──────────────────────────────────────────────────────
    n_days   = len(daily_nav)
    final_nav = float(daily_nav.iloc[-1]) if n_days > 0 else initial_capital

    metrics["total_return"] = (final_nav / initial_capital) - 1.0
    metrics["cagr"] = (
        (final_nav / initial_capital) ** (252.0 / n_days) - 1.0
        if n_days > 1 else 0.0
    )

    # ── Risk metrics ────────────────────────────────────────────────────────
    ret = daily_returns
    metrics["annual_vol"] = float(ret.std() * math.sqrt(252)) if len(ret) > 1 else 0.0

    cum_max = daily_nav.cummax()
    dd      = (daily_nav - cum_max) / cum_max
    metrics["max_drawdown"] = float(dd.min())

    # Max drawdown duration: longest consecutive run below peak (trading days)
    in_dd    = (dd < 0).values
    max_dur  = 0
    cur_dur  = 0
    for v in in_dd:
        if v:
            cur_dur += 1
            max_dur  = max(max_dur, cur_dur)
        else:
            cur_dur  = 0
    metrics["max_dd_duration_days"] = max_dur

    # Deep-drawdown episodes: continuous periods with drawdown < -10%
    DEEP_THRESHOLD = -0.10
    in_deep    = (dd < DEEP_THRESHOLD).values
    deep_segs: list[int] = []
    seg_start: int | None = None
    for i, v in enumerate(in_deep):
        if v and seg_start is None:
            seg_start = i
        elif not v and seg_start is not None:
            deep_segs.append(i - seg_start)
            seg_start = None
    if seg_start is not None:
        deep_segs.append(len(in_deep) - seg_start)

    metrics["avg_deep_dd_duration_days"] = (
        float(sum(deep_segs) / len(deep_segs)) if deep_segs else 0.0
    )
    metrics["n_deep_dd_episodes"] = len(deep_segs)

    # ── Risk-adjusted metrics ───────────────────────────────────────────────
    mean_ret  = float(ret.mean()) if len(ret) > 0 else 0.0
    annual_vol = metrics["annual_vol"]
    rf_daily   = risk_free_rate / 252

    metrics["sharpe"] = (
        (mean_ret * 252 - risk_free_rate) / annual_vol
        if annual_vol > 0 else 0.0
    )

    downside = ret[ret < rf_daily]
    down_vol = float(downside.std() * math.sqrt(252)) if len(downside) > 1 else 0.0
    metrics["sortino"] = (
        (mean_ret * 252 - risk_free_rate) / down_vol
        if down_vol > 0 else 0.0
    )

    max_dd_abs = abs(metrics["max_drawdown"])
    metrics["calmar"] = metrics["cagr"] / max_dd_abs if max_dd_abs > 1e-9 else 0.0

    # ── Trade statistics ────────────────────────────────────────────────────
    tl      = trade_log
    n_trades = len(tl)
    metrics["n_trades"] = n_trades

    if n_trades > 0:
        pnl_col = "net_pnl" if "net_pnl" in tl.columns else "gross_pnl"
        r_col   = "pnl_r_multiple" if "pnl_r_multiple" in tl.columns else None

        wins   = tl[tl[pnl_col] > 0]
        losses = tl[tl[pnl_col] <= 0]

        metrics["win_rate"] = len(wins) / n_trades

        if r_col:
            metrics["avg_win_r"]  = (
                float(tl.loc[tl[pnl_col] > 0,  r_col].mean()) if len(wins)   > 0 else 0.0
            )
            metrics["avg_loss_r"] = (
                float(tl.loc[tl[pnl_col] <= 0, r_col].mean()) if len(losses) > 0 else 0.0
            )
        else:
            metrics["avg_win_r"]  = 0.0
            metrics["avg_loss_r"] = 0.0

        total_wins   = float(wins[pnl_col].sum())           if len(wins)   > 0 else 0.0
        total_losses = float(losses[pnl_col].abs().sum())   if len(losses) > 0 else 1e-9
        metrics["profit_factor"] = total_wins / total_losses if total_losses > 0 else 0.0

        if "holding_days" in tl.columns:
            metrics["avg_holding_days"] = float(tl["holding_days"].mean())
        else:
            metrics["avg_holding_days"] = 0.0

        n_years = n_days / 252
        metrics["trades_per_year"] = n_trades / n_years if n_years > 0 else 0.0

        # Max consecutive losing trades
        max_cl = cur_cl = 0
        for win in (tl[pnl_col].values > 0):
            if not win:
                cur_cl += 1
                max_cl  = max(max_cl, cur_cl)
            else:
                cur_cl = 0
        metrics["max_consecutive_losses"] = max_cl
    else:
        metrics.update({
            "win_rate": 0.0, "avg_win_r": 0.0, "avg_loss_r": 0.0,
            "profit_factor": 0.0, "avg_holding_days": 0.0, "trades_per_year": 0.0,
            "max_consecutive_losses": 0,
        })

    # ── Portfolio metrics ───────────────────────────────────────────────────
    metrics["annual_turnover"] = _compute_turnover(tl, daily_nav, n_days)
    metrics["market_exposure"] = _compute_exposure(tl, daily_nav)

    return metrics


# ── Helpers ─────────────────────────────────────────────────────────────────


def _compute_turnover(
    trade_log: pd.DataFrame,
    daily_nav: pd.Series,
    n_days: int,
) -> float:
    """
    Annual Turnover = total buy notional / (avg NAV × years).

    Measures how many times the full portfolio is bought each year.
    Example: 7.5 means $75M bought/year on a $10M portfolio.
    """
    if (
        len(trade_log) == 0
        or n_days == 0
        or "entry_price" not in trade_log.columns
        or "shares" not in trade_log.columns
    ):
        return 0.0

    total_buy = float((trade_log["entry_price"] * trade_log["shares"]).sum())
    avg_nav   = float(daily_nav.mean())
    n_years   = n_days / 252

    if avg_nav > 0 and n_years > 0:
        return total_buy / (avg_nav * n_years)
    return 0.0


def _compute_exposure(
    trade_log: pd.DataFrame,
    daily_nav: pd.Series,
) -> float:
    """
    Market Exposure = fraction of trading days with ≥1 open position.

    Uses trade_log entry/exit dates to reconstruct which days had positions.
    Returns a value in [0.0, 1.0].
    """
    if (
        len(trade_log) == 0
        or "entry_date" not in trade_log.columns
        or "exit_date" not in trade_log.columns
    ):
        return 0.0

    all_dates  = daily_nav.index
    n_total    = len(all_dates)
    if n_total == 0:
        return 0.0

    # Build a daily position-count series efficiently using event markers.
    # +1 at entry_date, -1 at exit_date + 1 business day.
    events: dict = {}
    for _, row in trade_log.iterrows():
        entry = pd.Timestamp(row["entry_date"])
        exit_ = pd.Timestamp(row["exit_date"])

        events[entry] = events.get(entry, 0) + 1

        # Day after exit: position is closed before open
        after_exit = _next_trading_day(exit_, all_dates)
        if after_exit is not None:
            events[after_exit] = events.get(after_exit, 0) - 1

    # Walk through all trading days and maintain running count
    position_count = 0
    days_exposed   = 0
    for date in all_dates:
        position_count += events.get(date, 0)
        if position_count > 0:
            days_exposed += 1

    return days_exposed / n_total


def _next_trading_day(
    date: pd.Timestamp,
    all_dates: pd.DatetimeIndex,
) -> pd.Timestamp | None:
    """Return the first trading date strictly after `date`, or None."""
    later = all_dates[all_dates > date]
    return later[0] if len(later) > 0 else None


# ── Drawdown helpers (used by analysis modules in later phases) ─────────────


def drawdown_series(daily_nav: pd.Series) -> pd.Series:
    """Return drawdown from peak as a fraction (negative values)."""
    cum_max = daily_nav.cummax()
    return (daily_nav - cum_max) / cum_max


def rolling_sharpe(
    daily_returns: pd.Series,
    window: int = 252,
    risk_free_rate: float = 0.02,
) -> pd.Series:
    """
    Rolling annualised Sharpe ratio.

    Parameters
    ----------
    daily_returns : pd.Series
    window : int
        Rolling window in trading days.
    risk_free_rate : float
        Annual risk-free rate.
    """
    rf_daily = risk_free_rate / 252
    excess   = daily_returns - rf_daily
    return excess.rolling(window).apply(
        lambda x: (x.mean() * 252) / (x.std() * math.sqrt(252))
        if x.std() > 0 else float("nan"),
        raw=True,
    )


def annual_returns(daily_nav: pd.Series) -> pd.Series:
    """
    Per-calendar-year return as a fraction.

    Returns a Series indexed by year (int).
    """
    yr = daily_nav.resample("YE").last().pct_change().dropna()
    yr.index = yr.index.year
    return yr
