"""
Parameter heatmap analysis — Phase 6, Week 3.

Extends perturbation.py with:
  • IS-period restriction (--is-end prevents OOS data contamination)
  • 2-D cross-scan (nested loop over two parameters)
  • Stability-region detection

Design-spec reference: Section 3.5.5.

Public API
----------
run_1d_heatmap(...)  -> pd.DataFrame
run_2d_heatmap(...)  -> pd.DataFrame
find_parameter_stability_region(heatmap_df, cv_threshold) -> dict
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from strategy.params import StrategyParams

logger = logging.getLogger(__name__)


# ── 1-D heatmap ───────────────────────────────────────────────────────────────


def run_1d_heatmap(
    param_name: str,
    param_values: list,
    baseline_params: "StrategyParams",
    price_panel: dict,
    baseline_indicators: dict,
    start: str,
    is_end: str,
    initial_capital: float = 10_000_000.0,
    risk_free_rate: float = 0.02,
    strategy_tickers: list[str] | None = None,
    metrics: list[str] | None = None,
) -> pd.DataFrame:
    """
    1-D parameter heatmap (IS data only).

    Identical to run_perturbation_test() in perturbation.py, but the backtest
    end date is hard-capped at ``is_end`` to prevent look-ahead / OOS leakage.

    Parameters
    ----------
    param_name : str
        StrategyParams field to sweep.
    param_values : list
        Values to test.
    baseline_params : StrategyParams
        All other parameters remain at these values.
    price_panel : dict
        {ticker: OHLCV DataFrame}.
    baseline_indicators : dict
        Pre-computed indicators for baseline_params.
    start, is_end : str
        In-sample date range (YYYY-MM-DD).  ``is_end`` is strictly enforced.
    initial_capital : float
    risk_free_rate : float
    strategy_tickers : list[str] | None
    metrics : list[str] | None
        Subset of metric keys to include in output.  None → all metrics.

    Returns
    -------
    pd.DataFrame
        Index = param_values; columns = metric names (or requested subset).
    """
    from analysis.perturbation import run_perturbation_test

    logger.info(
        "1-D heatmap: %s over %s  |  IS period: %s → %s",
        param_name, param_values, start, is_end,
    )

    df = run_perturbation_test(
        param_name=param_name,
        param_values=param_values,
        baseline_params=baseline_params,
        price_panel=price_panel,
        baseline_indicators=baseline_indicators,
        start=start,
        end=is_end,
        initial_capital=initial_capital,
        risk_free_rate=risk_free_rate,
        strategy_tickers=strategy_tickers,
    )

    if metrics is not None:
        available = [m for m in metrics if m in df.columns]
        df = df[available]

    return df


# ── 2-D heatmap ───────────────────────────────────────────────────────────────


def run_2d_heatmap(
    param1_name: str,
    param1_values: list,
    param2_name: str,
    param2_values: list,
    baseline_params: "StrategyParams",
    price_panel: dict,
    baseline_indicators: dict,
    start: str,
    is_end: str,
    metric: str = "sharpe",
    initial_capital: float = 10_000_000.0,
    risk_free_rate: float = 0.02,
    strategy_tickers: list[str] | None = None,
) -> pd.DataFrame:
    """
    2-D cross-parameter heatmap (IS data only).

    Runs a full backtest for every (param1, param2) combination.  Total
    backtests = len(param1_values) × len(param2_values).

    ⚠️  Expensive: 4×4 = 16 full backtests ≈ several hours on full universe.
    Consider using a reduced universe (--mode etf) for quick iteration.

    Parameters
    ----------
    param1_name, param2_name : str
        StrategyParams fields to cross-scan.
    param1_values, param2_values : list
        Values for each dimension.
    baseline_params : StrategyParams
        All other parameters remain at these values.
    price_panel : dict
    baseline_indicators : dict
    start, is_end : str
        In-sample date range.  is_end strictly enforced.
    metric : str
        The performance metric to display in the heatmap grid (e.g. 'sharpe').
    initial_capital : float
    risk_free_rate : float
    strategy_tickers : list[str] | None

    Returns
    -------
    pd.DataFrame
        Shape = (len(param1_values), len(param2_values)).
        Index  = param1_values (named param1_name).
        Columns = param2_values (named param2_name).
        Values  = requested metric for each combination.
    """
    from analysis.perturbation import _build_indicators
    from backtest.engine import BacktestEngine
    from strategy.v1.strategy_v1 import StrategyV1

    auxiliary = {baseline_params.cash_proxy, "SPY"}
    if strategy_tickers is None:
        strategy_tickers = [t for t in price_panel if t not in auxiliary]

    n_total = len(param1_values) * len(param2_values)
    logger.info(
        "2-D heatmap: %s × %s  |  %d combinations  |  IS: %s → %s  |  metric=%s",
        param1_name, param2_name, n_total, start, is_end, metric,
    )

    grid: dict[tuple, float] = {}
    run_idx = 0

    for v1 in param1_values:
        # Build indicators for param1 first
        ind1 = _build_indicators(param1_name, v1, baseline_indicators, price_panel)
        params1 = replace(baseline_params, **{param1_name: v1})

        for v2 in param2_values:
            run_idx += 1
            logger.info(
                "[%d/%d]  %s=%s  %s=%s …",
                run_idx, n_total, param1_name, v1, param2_name, v2,
            )
            params2 = replace(params1, **{param2_name: v2})
            ind2 = _build_indicators(param2_name, v2, ind1, price_panel)

            engine = BacktestEngine(
                strategy=StrategyV1(params2),
                price_panel=price_panel,
                indicators=ind2,
                params=params2,
                initial_capital=initial_capital,
            )
            results = engine.run(start, is_end, strategy_tickers)
            m = results.compute_metrics(risk_free_rate=risk_free_rate)
            grid[(v1, v2)] = m.get(metric, float("nan"))

            logger.info(
                "  → %s=%.4f  CAGR=%+.2f%%  MaxDD=%.1f%%",
                metric, grid[(v1, v2)], m.get("cagr", 0) * 100, m.get("max_drawdown", 0) * 100,
            )

    # Assemble into DataFrame
    df = pd.DataFrame(
        [[grid[(v1, v2)] for v2 in param2_values] for v1 in param1_values],
        index=pd.Index(param1_values, name=param1_name),
        columns=pd.Index(param2_values, name=param2_name),
    )
    return df


# ── Stability-region analysis ─────────────────────────────────────────────────


def find_parameter_stability_region(
    heatmap_df: pd.DataFrame,
    cv_threshold: float = 0.10,
    flatness_threshold: float = 0.90,
) -> dict:
    """
    Detect the stable region of a 1-D heatmap.

    Criteria (design-spec 1.2.5):
      1. Flatness: no sharp peak — adjacent values change < (1 - flatness_threshold)
      2. Low CV: std/|mean| < cv_threshold across all values
      3. Contiguous: the stable region must be a single continuous range

    Parameters
    ----------
    heatmap_df : pd.DataFrame
        Output of run_1d_heatmap() (index = param values, columns = metrics).
    cv_threshold : float
        CV < cv_threshold → robust.
    flatness_threshold : float
        A point is "flat" if its value ≥ max × flatness_threshold.

    Returns
    -------
    dict  {metric_name: {"cv": float, "stable_region": (min, max) | None,
                          "is_robust": bool}}
    """
    results: dict = {}
    param_values = list(heatmap_df.index)

    for col in heatmap_df.columns:
        series = heatmap_df[col].dropna()
        if series.empty:
            continue

        vals = series.values.astype(float)
        mean_abs = abs(float(series.mean()))
        cv = float(series.std() / mean_abs) if mean_abs > 1e-9 else float("nan")

        # Contiguous stable region: values ≥ max × flatness_threshold
        peak = float(np.nanmax(vals))
        threshold = peak * flatness_threshold
        stable_idx = [i for i, v in enumerate(vals) if v >= threshold]

        if stable_idx:
            # Find the longest contiguous run
            best_start = best_end = stable_idx[0]
            cur_start  = stable_idx[0]
            for i in range(1, len(stable_idx)):
                if stable_idx[i] == stable_idx[i - 1] + 1:
                    best_end = stable_idx[i]
                else:
                    cur_start = stable_idx[i]
            stable_region = (param_values[best_start], param_values[best_end])
        else:
            stable_region = None

        results[col] = {
            "cv":            cv,
            "is_robust":     (cv < cv_threshold) if not np.isnan(cv) else False,
            "stable_region": stable_region,
            "peak_value":    peak,
        }

    return results
