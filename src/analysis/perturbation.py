"""
One-at-a-time perturbation (sensitivity) tests — Phase 6, Week 2.

Orchestrates sensitivity sweeps: loads data once, varies a single parameter,
re-uses indicators when possible, runs BacktestEngine for each value.

Design-spec reference: Section 3.5.2.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from strategy.params import StrategyParams

logger = logging.getLogger(__name__)

# Which StrategyParams fields invalidate each indicator group
_BREAKOUT_SENSITIVE: frozenset[str] = frozenset({"breakout_window"})
_ATR_SENSITIVE: frozenset[str] = frozenset({"atr_period"})


# ── Public API ───────────────────────────────────────────────────────────────


def run_perturbation_test(
    param_name: str,
    param_values: list,
    baseline_params: "StrategyParams",
    price_panel: dict,
    baseline_indicators: dict,
    start: str,
    end: str,
    initial_capital: float = 10_000_000.0,
    risk_free_rate: float = 0.02,
    strategy_tickers: list[str] | None = None,
) -> pd.DataFrame:
    """
    One-at-a-time perturbation: vary param_name, fix all others at baseline.

    Indicator re-use logic:
      - trail_multiplier_r1 / r3 / r5, position sizing params, etc.
        → baseline_indicators reused as-is (no indicator dependency)
      - breakout_window → rolling_high/breakout_signal/breakout_strength rebuilt
      - atr_period      → atr rebuilt

    Parameters
    ----------
    param_name : str
        StrategyParams field to vary.
    param_values : list
        Values to sweep (e.g. [2.0, 2.5, 3.0, 3.5, 4.0]).
    baseline_params : StrategyParams
        Reference config; all fields except param_name stay fixed.
    price_panel : dict
        Pre-loaded {ticker: OHLCV DataFrame}.
    baseline_indicators : dict
        Pre-computed indicators for baseline_params.
    start, end : str
        Backtest date range (YYYY-MM-DD).
    initial_capital : float
        Starting NAV in USD.
    risk_free_rate : float
        Annual risk-free rate for Sharpe/Sortino (default 2%).
    strategy_tickers : list[str] | None
        Tickers to trade. None → all panel tickers except cash proxy and SPY.

    Returns
    -------
    pd.DataFrame
        Index = param_values (named after param_name); columns = metric names.
    """
    from backtest.engine import BacktestEngine
    from strategy.v1.strategy_v1 import StrategyV1

    auxiliary = {baseline_params.cash_proxy, "SPY"}
    if strategy_tickers is None:
        strategy_tickers = [t for t in price_panel if t not in auxiliary]

    records: list[dict] = []
    n = len(param_values)

    for idx, val in enumerate(param_values, 1):
        logger.info(
            "[%d/%d] %s = %s …", idx, n, param_name, val
        )
        params = replace(baseline_params, **{param_name: val})
        indicators = _build_indicators(
            param_name, val, baseline_indicators, price_panel
        )

        engine = BacktestEngine(
            strategy=StrategyV1(params),
            price_panel=price_panel,
            indicators=indicators,
            params=params,
            initial_capital=initial_capital,
        )
        results = engine.run(start, end, strategy_tickers)
        m = results.compute_metrics(risk_free_rate=risk_free_rate)
        m["param_value"] = val
        records.append(m)

        logger.info(
            "  → CAGR=%+.2f%%  Sharpe=%.3f  MaxDD=%.1f%%  "
            "Trades=%d  Turnover=%.2fx  AvgHold=%.0f d",
            m["cagr"] * 100, m["sharpe"], m["max_drawdown"] * 100,
            m["n_trades"], m["annual_turnover"], m["avg_holding_days"],
        )

    df = pd.DataFrame(records).set_index("param_value")
    df.index.name = param_name
    return df


def compute_sensitivity_cv(results_df: pd.DataFrame) -> pd.Series:
    """
    Coefficient of Variation (CV = std / |mean|) per metric.

    Interpretation:
      CV < 0.10  → robust  (< ±10% variation across tested range)
      CV > 0.30  → fragile (> ±30% variation)

    Parameters
    ----------
    results_df : pd.DataFrame
        Output of run_perturbation_test().

    Returns
    -------
    pd.Series indexed by metric name.
    """
    numeric = results_df.select_dtypes(include="number")
    means = numeric.mean().abs().replace(0, float("nan"))
    stds = numeric.std()
    return stds / means


def find_stability_region(
    param_values: list,
    metric_values: pd.Series,
    threshold_pct: float = 0.90,
    baseline_value: float | None = None,
) -> tuple[float | None, float | None]:
    """
    Largest contiguous range of param_values where metric stays ≥ threshold.

    Parameters
    ----------
    param_values : list
        Ordered parameter values tested.
    metric_values : pd.Series
        Metric (e.g. Sharpe) for each value (same order as param_values).
    threshold_pct : float
        Fraction of baseline_value required (default 90%).
    baseline_value : float | None
        Reference metric. If None, uses max(metric_values).

    Returns
    -------
    (min_stable, max_stable), or (None, None) if no stable region found.
    """
    if baseline_value is None:
        baseline_value = float(metric_values.max())

    threshold = baseline_value * threshold_pct
    vals = list(param_values)
    metrics = list(metric_values)

    best_start: float | None = None
    best_end: float | None = None
    best_len = 0
    seg_start: int | None = None

    for i, (v, m) in enumerate(zip(vals, metrics)):
        if m >= threshold:
            if seg_start is None:
                seg_start = i
        else:
            if seg_start is not None:
                seg_len = i - seg_start
                if seg_len > best_len:
                    best_len, best_start, best_end = seg_len, vals[seg_start], vals[i - 1]
                seg_start = None

    if seg_start is not None:
        seg_len = len(vals) - seg_start
        if seg_len > best_len:
            best_start, best_end = vals[seg_start], vals[-1]

    return (best_start, best_end)


# ── Internal helpers ─────────────────────────────────────────────────────────


def _build_indicators(
    param_name: str,
    new_val,
    baseline_indicators: dict,
    price_panel: dict,
) -> dict:
    """Return indicator dict for new_val, rebuilding only what changed."""
    if param_name in _BREAKOUT_SENSITIVE:
        return _rebuild_breakout_indicators(int(new_val), baseline_indicators, price_panel)
    if param_name in _ATR_SENSITIVE:
        return _rebuild_atr_indicators(int(new_val), baseline_indicators, price_panel)
    return baseline_indicators


def _rebuild_breakout_indicators(
    new_window: int,
    baseline_indicators: dict,
    price_panel: dict,
) -> dict:
    """Rebuild rolling_high / breakout_signal / breakout_strength only."""
    from indicators.breakout import (
        compute_breakout_signal,
        compute_breakout_strength,
        compute_rolling_high,
    )

    new_indicators: dict = {}
    for ticker, ind in baseline_indicators.items():
        df = price_panel.get(ticker)
        if df is None:
            continue
        high  = df["adj_high"]
        close = df["adj_close"]

        rolling_high      = compute_rolling_high(high, window=new_window)
        breakout_signal   = compute_breakout_signal(close, rolling_high)
        breakout_strength = compute_breakout_strength(close, rolling_high)

        ticker_ind = dict(ind)
        ticker_ind["rolling_high"]      = rolling_high
        ticker_ind["breakout_signal"]   = breakout_signal
        ticker_ind["breakout_strength"] = breakout_strength
        new_indicators[ticker] = ticker_ind

    return new_indicators


def _rebuild_atr_indicators(
    new_period: int,
    baseline_indicators: dict,
    price_panel: dict,
) -> dict:
    """Rebuild ATR only."""
    from indicators.atr import compute_atr

    new_indicators: dict = {}
    for ticker, ind in baseline_indicators.items():
        df = price_panel.get(ticker)
        if df is None:
            continue
        atr = compute_atr(
            df["adj_high"], df["adj_low"], df["adj_close"], period=new_period
        )
        ticker_ind = dict(ind)
        ticker_ind["atr"] = atr
        new_indicators[ticker] = ticker_ind

    return new_indicators
