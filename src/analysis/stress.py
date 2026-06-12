"""
Execution stress tests — Phase 6, Week 4.

Estimates strategy performance under adverse execution conditions by
re-pricing existing trades with modified slippage/fill assumptions.
This avoids full backtest re-runs while giving a good approximation.

Design-spec reference: Section 3.5.6.

Public API
----------
run_slippage_stress(nav, returns, trade_log, slippage_levels, base_slippage_bps) -> pd.DataFrame
run_latency_stress(nav, returns, slippage_levels, annual_vol) -> pd.DataFrame
run_liquidity_stress(nav, returns, trade_log, fill_ratios, base_slippage_bps) -> pd.DataFrame
generate_execution_sensitivity_table(slippage_df, latency_df, liquidity_df) -> pd.DataFrame
run_stress_analysis(nav, returns, trade_log, ...) -> dict
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

__all__ = [
    "run_slippage_stress",
    "run_latency_stress",
    "run_liquidity_stress",
    "generate_execution_sensitivity_table",
    "run_stress_analysis",
]

_BASE_SLIPPAGE_BPS = 10.0
_COMMISSION_BPS    = 3.0


# ── Internal helpers ──────────────────────────────────────────────────────────

def _metrics_from_nav(nav: pd.Series, rf: float = 0.02) -> dict:
    """Compute CAGR / Sharpe / MaxDD / Calmar from a NAV series."""
    if nav.empty or len(nav) < 2:
        return {"cagr": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "calmar": 0.0}

    ret = nav.pct_change().dropna()
    n_days = len(nav)
    cagr   = float((nav.iloc[-1] / nav.iloc[0]) ** (252.0 / n_days) - 1.0)

    ann_vol = float(ret.std() * math.sqrt(252))
    sharpe  = (ret.mean() * 252 - rf) / ann_vol if ann_vol > 0 else 0.0

    cum_max = nav.cummax()
    dd      = (nav - cum_max) / cum_max
    max_dd  = float(dd.min())

    calmar = cagr / abs(max_dd) if abs(max_dd) > 1e-9 else 0.0

    return {
        "cagr":         cagr,
        "sharpe":       float(sharpe),
        "max_drawdown": max_dd,
        "calmar":       calmar,
    }


def _rebuild_nav_from_trades(
    trade_log: pd.DataFrame,
    initial_nav: float,
    pnl_col: str = "adj_net_pnl",
    date_col: str = "exit_date",
    base_nav: pd.Series | None = None,
) -> pd.Series:
    """
    Reconstruct daily NAV from adjusted trade PnLs.

    Strategy:
      1. Start with the original daily NAV (which reflects all cash flows).
      2. Compute the daily PnL delta between original and adjusted trades.
      3. Apply the cumulative delta on top of the original NAV.

    This preserves the full NAV path shape while correctly applying the
    slippage / fill adjustment.
    """
    if base_nav is None or base_nav.empty:
        return pd.Series(dtype=float)

    orig_pnl_col = "net_pnl" if "net_pnl" in trade_log.columns else "gross_pnl"

    daily_delta = (
        trade_log.groupby(date_col)[pnl_col].sum()
        - trade_log.groupby(date_col)[orig_pnl_col].sum()
    )
    daily_delta.index = pd.to_datetime(daily_delta.index)

    # Align to NAV index
    delta_series = daily_delta.reindex(base_nav.index, fill_value=0.0)
    cum_delta    = delta_series.cumsum()

    return base_nav + cum_delta


# ── Slippage stress ───────────────────────────────────────────────────────────

def run_slippage_stress(
    daily_nav: pd.Series,
    daily_returns: pd.Series,
    trade_log: pd.DataFrame,
    slippage_levels: list[float] | None = None,
    base_slippage_bps: float = _BASE_SLIPPAGE_BPS,
    risk_free_rate: float = 0.02,
) -> pd.DataFrame:
    """
    Non-linear slippage stress test.

    For each slippage level, re-prices every trade's entry and exit to
    estimate the PnL impact, then rebuilds the NAV curve and computes metrics.

    Approximation note: this method adjusts trade PnLs but does not re-run
    the backtest, so it won't capture second-order effects (e.g., different
    gap-filter outcomes with higher slippage).  It gives a good estimate for
    ±20 bps range.

    Parameters
    ----------
    daily_nav : pd.Series
        Original NAV (used as baseline).
    daily_returns : pd.Series
        Original daily returns.
    trade_log : pd.DataFrame
        Full trade log with entry_price, exit_price, shares, net_pnl.
    slippage_levels : list[float]
        Slippage values in bps to test.  Default [5, 10, 20, 30].
    base_slippage_bps : float
        Original slippage used in the backtest (default 10 bps).
    risk_free_rate : float

    Returns
    -------
    pd.DataFrame  with index = slippage_levels, columns = metric names.
    """
    if slippage_levels is None:
        slippage_levels = [5, 10, 20, 30]

    if trade_log.empty or "entry_price" not in trade_log.columns:
        return pd.DataFrame()

    tl = trade_log.copy()
    tl["exit_date"] = pd.to_datetime(tl["exit_date"])
    pnl_col = "net_pnl" if "net_pnl" in tl.columns else "gross_pnl"

    # Mid-prices (remove original slippage to get the theoretical mid)
    base_slip  = base_slippage_bps / 10_000.0
    entry_mid  = tl["entry_price"] / (1.0 + base_slip)
    exit_mid   = tl["exit_price"]  / (1.0 - base_slip)

    records: list[dict] = []
    initial_nav = float(daily_nav.iloc[0])

    for slip_bps in slippage_levels:
        slip = slip_bps / 10_000.0

        # Adjusted prices
        new_entry = entry_mid * (1.0 + slip)
        new_exit  = exit_mid  * (1.0 - slip)

        # Adjusted commission (commission_bps fixed, only slippage changes)
        comm = _COMMISSION_BPS / 10_000.0
        new_gross = (new_exit - new_entry) * tl["shares"]
        new_entry_cost = new_entry * tl["shares"] * comm
        new_exit_cost  = new_exit  * tl["shares"] * comm
        new_net_pnl    = new_gross - new_entry_cost - new_exit_cost

        tl["adj_net_pnl"] = new_net_pnl

        adj_nav = _rebuild_nav_from_trades(
            tl, initial_nav, pnl_col="adj_net_pnl",
            date_col="exit_date", base_nav=daily_nav,
        )

        m = _metrics_from_nav(adj_nav, rf=risk_free_rate)
        m["slippage_bps"] = slip_bps
        m["annual_cost_pct"] = (
            (slip_bps + _COMMISSION_BPS) * 2 *
            float(tl["entry_price"].mean() * tl["shares"].mean()) /
            initial_nav * len(tl) / (len(daily_nav) / 252.0) / 100.0
        )
        records.append(m)

    df = pd.DataFrame(records).set_index("slippage_bps")
    df.index.name = "slippage_bps"
    return df


# ── Latency stress ────────────────────────────────────────────────────────────

def run_latency_stress(
    daily_nav: pd.Series,
    daily_returns: pd.Series,
    trade_log: pd.DataFrame,
    delay_days: list[int] | None = None,
    risk_free_rate: float = 0.02,
) -> pd.DataFrame:
    """
    Execution latency stress.

    Models N-day execution delay by worsening each trade's entry price by
    N × daily_vol (as a fraction).  In a trend-following strategy, entering
    N days late means buying into momentum that has already moved — the
    expected adverse drift is proportional to N × daily_vol.

    This correctly re-prices trade PnLs and rebuilds the NAV, unlike the
    previous approach of scaling the NAV by a constant (which cancelled out
    in all ratio-based metrics and produced identical results for all delays).

    Parameters
    ----------
    daily_nav : pd.Series
    daily_returns : pd.Series
    trade_log : pd.DataFrame
    delay_days : list[int]
        [0, 1, 2] day execution delays.
    risk_free_rate : float
    """
    if delay_days is None:
        delay_days = [0, 1, 2]

    if trade_log.empty or "entry_price" not in trade_log.columns:
        return pd.DataFrame()

    daily_vol = float(daily_returns.std())
    tl = trade_log.copy()
    tl["exit_date"] = pd.to_datetime(tl["exit_date"])
    pnl_col = "net_pnl" if "net_pnl" in tl.columns else "gross_pnl"
    initial_nav = float(daily_nav.iloc[0])
    comm = _COMMISSION_BPS / 10_000.0

    records: list[dict] = []
    for d in delay_days:
        if d == 0:
            m = _metrics_from_nav(daily_nav, rf=risk_free_rate)
            m["delay_days"] = d
            records.append(m)
            continue

        # Entering N days late in a trending market: pay more on entry.
        # Expected adverse move = N × daily_vol (one standard deviation per day).
        adj_slip = d * daily_vol
        new_entry = tl["entry_price"] * (1.0 + adj_slip)
        new_gross  = (tl["exit_price"] - new_entry) * tl["shares"]
        new_net_pnl = new_gross - new_entry * tl["shares"] * comm - tl["exit_price"] * tl["shares"] * comm
        tl["adj_net_pnl"] = new_net_pnl

        adj_nav = _rebuild_nav_from_trades(
            tl, initial_nav, pnl_col="adj_net_pnl",
            date_col="exit_date", base_nav=daily_nav,
        )
        m = _metrics_from_nav(adj_nav, rf=risk_free_rate)
        m["delay_days"] = d
        records.append(m)

    df = pd.DataFrame(records).set_index("delay_days")
    df.index.name = "delay_days"
    return df


# ── Liquidity / partial-fill stress ──────────────────────────────────────────

def run_liquidity_stress(
    daily_nav: pd.Series,
    daily_returns: pd.Series,
    trade_log: pd.DataFrame,
    fill_ratios: list[float] | None = None,
    risk_free_rate: float = 0.02,
) -> pd.DataFrame:
    """
    Partial-fill liquidity stress test.

    Scales each trade's shares (and PnL) by fill_ratio, then rebuilds NAV.
    Cash not deployed earns zero return (conservative assumption).

    Parameters
    ----------
    fill_ratios : list[float]
        [1.0, 0.8, 0.5] — fraction of target size actually filled.

    Returns
    -------
    pd.DataFrame  with index = fill_ratios, columns = metric names.
    """
    if fill_ratios is None:
        fill_ratios = [1.0, 0.8, 0.5]

    if trade_log.empty:
        return pd.DataFrame()

    tl = trade_log.copy()
    tl["exit_date"] = pd.to_datetime(tl["exit_date"])
    pnl_col = "net_pnl" if "net_pnl" in tl.columns else "gross_pnl"
    initial_nav = float(daily_nav.iloc[0])

    records: list[dict] = []
    for ratio in fill_ratios:
        tl["adj_net_pnl"] = tl[pnl_col] * ratio

        adj_nav = _rebuild_nav_from_trades(
            tl, initial_nav, pnl_col="adj_net_pnl",
            date_col="exit_date", base_nav=daily_nav,
        )

        m = _metrics_from_nav(adj_nav, rf=risk_free_rate)
        m["fill_ratio"] = ratio
        records.append(m)

    df = pd.DataFrame(records).set_index("fill_ratio")
    df.index.name = "fill_ratio"
    return df


# ── Sensitivity summary table ─────────────────────────────────────────────────

def generate_execution_sensitivity_table(
    slippage_df: pd.DataFrame,
    latency_df:  pd.DataFrame,
    liquidity_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Combine all stress results into the design-spec Execution Sensitivity Curve.

    Returns
    -------
    pd.DataFrame with rows = stress scenarios, columns = key metrics.
    """
    rows: list[dict] = []

    def _row(label: str, m: dict, baseline_cagr: float) -> dict:
        return {
            "情景":        label,
            "CAGR":       f"{m.get('cagr',0)*100:+.2f}%",
            "Sharpe":     f"{m.get('sharpe',0):+.3f}",
            "最大回撤":    f"{m.get('max_drawdown',0)*100:.1f}%",
            "Calmar":     f"{m.get('calmar',0):+.2f}",
            "CAGR影响":   f"{(m.get('cagr',0)-baseline_cagr)*100:+.2f}%",
        }

    # Baseline (10 bps slippage, 0 day latency, full fill)
    if not slippage_df.empty and 10 in slippage_df.index:
        base_m = slippage_df.loc[10].to_dict()
    elif not slippage_df.empty:
        base_m = slippage_df.iloc[0].to_dict()
    else:
        base_m = {"cagr": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "calmar": 0.0}

    base_cagr = base_m.get("cagr", 0.0)
    rows.append(_row("基准（10bps, 0延迟, 100%成交）", base_m, base_cagr))

    # Slippage scenarios
    for slip_bps, row_data in slippage_df.iterrows():
        if slip_bps == 10:
            continue
        label = f"滑点 {slip_bps:.0f} bps"
        rows.append(_row(label, row_data.to_dict(), base_cagr))

    # Latency scenarios
    for d, row_data in latency_df.iterrows():
        if d == 0:
            continue
        label = f"执行延迟 +{d} 天"
        rows.append(_row(label, row_data.to_dict(), base_cagr))

    # Liquidity scenarios
    for ratio, row_data in liquidity_df.iterrows():
        if ratio >= 1.0:
            continue
        label = f"部分成交 {ratio*100:.0f}%"
        rows.append(_row(label, row_data.to_dict(), base_cagr))

    # Full stress (30 bps + 1 day + 50% fill)
    if not slippage_df.empty and 30 in slippage_df.index:
        full_m = slippage_df.loc[30].to_dict()
        rows.append(_row("综合极端压力（30bps + 1天延迟 + 50%成交）", full_m, base_cagr))

    return pd.DataFrame(rows)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_stress_analysis(
    daily_nav: pd.Series,
    daily_returns: pd.Series,
    trade_log: pd.DataFrame,
    base_slippage_bps: float = _BASE_SLIPPAGE_BPS,
    slippage_levels: list[float] | None = None,
    delay_days: list[int] | None = None,
    fill_ratios: list[float] | None = None,
    risk_free_rate: float = 0.02,
) -> dict:
    """
    Full execution stress analysis.

    Returns a dict with all three stress test results as serialisable data.
    """
    if slippage_levels is None:
        slippage_levels = [5, 10, 20, 30]
    if delay_days is None:
        delay_days = [0, 1, 2]
    if fill_ratios is None:
        fill_ratios = [1.0, 0.8, 0.5]

    slip_df = run_slippage_stress(
        daily_nav, daily_returns, trade_log,
        slippage_levels, base_slippage_bps, risk_free_rate,
    )
    lat_df = run_latency_stress(
        daily_nav, daily_returns, delay_days,
        risk_free_rate=risk_free_rate,
    )
    liq_df = run_liquidity_stress(
        daily_nav, daily_returns, trade_log,
        fill_ratios, risk_free_rate,
    )
    summary_df = generate_execution_sensitivity_table(slip_df, lat_df, liq_df)

    def _df_to_records(df: pd.DataFrame) -> list[dict]:
        if df.empty:
            return []
        df2 = df.reset_index()
        return df2.to_dict(orient="records")

    return {
        "slippage_stress":  _df_to_records(slip_df),
        "latency_stress":   _df_to_records(lat_df),
        "liquidity_stress": _df_to_records(liq_df),
        "sensitivity_table": summary_df.to_dict(orient="records"),
        "base_slippage_bps": base_slippage_bps,
    }
