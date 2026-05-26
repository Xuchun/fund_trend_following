"""
Monte Carlo risk analysis — Phase 6, Week 3.

Bootstrap-resampling of historical daily returns to estimate the distribution
of strategy outcomes across 1,000 simulated market paths.

Design-spec reference: Section 3.5.4.

Two methods:
  - Return Bootstrap  : IID resample of daily returns (breaks autocorrelation)
  - Block Bootstrap   : monthly-block resample (preserves short-term structure)

Public API
----------
run_return_bootstrap(daily_returns, n_simulations, seed) -> np.ndarray
run_block_bootstrap(daily_returns, block_size, n_simulations, seed) -> np.ndarray
compute_nav_paths(return_paths, initial_nav) -> np.ndarray
compute_max_drawdowns(nav_paths) -> np.ndarray
compute_drawdown_durations(nav_paths) -> dict
run_montecarlo(daily_returns, n_simulations, initial_nav) -> dict
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd

__all__ = [
    "run_return_bootstrap",
    "run_block_bootstrap",
    "compute_nav_paths",
    "compute_max_drawdowns",
    "compute_drawdown_durations",
    "run_montecarlo",
]


# ── Bootstrap samplers ────────────────────────────────────────────────────────


def run_return_bootstrap(
    daily_returns: pd.Series,
    n_simulations: int = 1_000,
    seed: int = 42,
) -> np.ndarray:
    """
    IID return bootstrap: resample daily returns with replacement.

    Each simulation preserves the same number of trading days as the original
    but draws randomly from the empirical return distribution.  This breaks
    serial autocorrelation — use block bootstrap if you want to preserve it.

    Parameters
    ----------
    daily_returns : pd.Series
        Fractional daily returns (e.g. 0.003 for +0.3%).
    n_simulations : int
        Number of paths to generate.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    np.ndarray, shape (n_days, n_simulations)
        Each column is one simulated return path.
    """
    rng = np.random.default_rng(seed)
    returns = daily_returns.dropna().to_numpy()
    n = len(returns)
    idx = rng.integers(0, n, size=(n, n_simulations))
    return returns[idx]


def run_block_bootstrap(
    daily_returns: pd.Series,
    block_size: str = "monthly",
    n_simulations: int = 1_000,
    seed: int = 43,
) -> np.ndarray:
    """
    Block bootstrap: resample monthly (or quarterly) return blocks.

    Preserves within-block autocorrelation structure better than IID bootstrap,
    which matters for drawdown duration estimation.

    Parameters
    ----------
    daily_returns : pd.Series
        Fractional daily returns with DatetimeIndex.
    block_size : str
        'monthly' or 'quarterly'.
    n_simulations : int
        Number of paths to generate.
    seed : int
        Random seed.

    Returns
    -------
    np.ndarray, shape (n_days_approx, n_simulations)
        Each column is one simulated return path (length may differ slightly
        from original due to block boundaries).
    """
    rng = np.random.default_rng(seed)

    if not isinstance(daily_returns.index, pd.DatetimeIndex):
        daily_returns = daily_returns.copy()
        daily_returns.index = pd.to_datetime(daily_returns.index)

    freq = "ME" if block_size == "monthly" else "QE"
    groups = daily_returns.groupby(pd.Grouper(freq=freq))
    blocks = [grp.to_numpy() for _, grp in groups if len(grp) > 0]
    n_blocks = len(blocks)
    n_target = len(daily_returns)

    paths: list[np.ndarray] = []
    for _ in range(n_simulations):
        sampled: list[np.ndarray] = []
        total = 0
        while total < n_target:
            b = blocks[rng.integers(0, n_blocks)]
            sampled.append(b)
            total += len(b)
        path = np.concatenate(sampled)[:n_target]
        paths.append(path)

    return np.column_stack(paths)


# ── NAV path computation ──────────────────────────────────────────────────────


def compute_nav_paths(
    return_paths: np.ndarray,
    initial_nav: float = 1.0,
) -> np.ndarray:
    """
    Compute cumulative NAV from return paths.

    Parameters
    ----------
    return_paths : np.ndarray, shape (n_days, n_simulations)
    initial_nav : float

    Returns
    -------
    np.ndarray, shape (n_days + 1, n_simulations)
        Row 0 is initial_nav; each subsequent row is cumulative NAV.
    """
    growth = np.cumprod(1.0 + return_paths, axis=0) * initial_nav
    start_row = np.full((1, return_paths.shape[1]), initial_nav)
    return np.vstack([start_row, growth])


def compute_max_drawdowns(nav_paths: np.ndarray) -> np.ndarray:
    """
    Maximum drawdown per simulation path.

    Parameters
    ----------
    nav_paths : np.ndarray, shape (n_days+1, n_simulations)

    Returns
    -------
    np.ndarray, shape (n_simulations,)
        Values are negative fractions (e.g. -0.25 means -25%).
    """
    running_max = np.maximum.accumulate(nav_paths, axis=0)
    dd = (nav_paths - running_max) / running_max
    return dd.min(axis=0)


def compute_drawdown_durations(nav_paths: np.ndarray) -> dict:
    """
    Analyse drawdown duration across all simulation paths.

    Computes the maximum consecutive number of trading days each path spends
    below its historical peak, then aggregates across simulations.

    Parameters
    ----------
    nav_paths : np.ndarray, shape (n_days+1, n_simulations)

    Returns
    -------
    dict with keys:
        prob_gt_3m  : fraction of paths with max underwater > 63 trading days
        prob_gt_6m  : fraction of paths with max underwater > 126 trading days
        prob_gt_12m : fraction of paths with max underwater > 252 trading days
        prob_gt_24m : fraction of paths with max underwater > 504 trading days
        avg_days    : mean max drawdown duration (trading days)
        p95_days    : 95th-percentile max drawdown duration
        max_days    : worst-case max drawdown duration
    """
    running_max = np.maximum.accumulate(nav_paths, axis=0)
    in_dd = nav_paths < running_max  # bool (n_days+1, n_sims)

    n_sims = nav_paths.shape[1]
    max_dur = np.zeros(n_sims, dtype=int)

    cur_dur = np.zeros(n_sims, dtype=int)
    for row in in_dd:
        cur_dur = np.where(row, cur_dur + 1, 0)
        max_dur = np.maximum(max_dur, cur_dur)

    TRADING_DAYS = {3: 63, 6: 126, 12: 252, 24: 504}
    return {
        "prob_gt_3m":  float((max_dur > TRADING_DAYS[3]).mean()),
        "prob_gt_6m":  float((max_dur > TRADING_DAYS[6]).mean()),
        "prob_gt_12m": float((max_dur > TRADING_DAYS[12]).mean()),
        "prob_gt_24m": float((max_dur > TRADING_DAYS[24]).mean()),
        "avg_days":    float(max_dur.mean()),
        "p95_days":    float(np.percentile(max_dur, 95)),
        "max_days":    int(max_dur.max()),
    }


# ── Main entry point ──────────────────────────────────────────────────────────


def run_montecarlo(
    daily_returns: pd.Series,
    n_simulations: int = 1_000,
    initial_nav: float = 10_000_000.0,
    risk_free_rate: float = 0.02,
    method: str = "return_bootstrap",
) -> dict:
    """
    Full Monte Carlo analysis.

    Parameters
    ----------
    daily_returns : pd.Series
        Fractional daily returns with DatetimeIndex.
    n_simulations : int
        Number of bootstrap paths (default 1,000).
    initial_nav : float
        Starting portfolio value in dollars.
    risk_free_rate : float
        Annual risk-free rate for Sharpe calculation.
    method : str
        'return_bootstrap', 'block_bootstrap', or 'both'.
        When 'both', return_bootstrap is used for NAV paths;
        block_bootstrap is used for drawdown duration analysis.

    Returns
    -------
    dict with all deliverables required by design-spec 1.2.4.2.
    """
    returns = daily_returns.dropna()
    n_days  = len(returns)
    rf_daily = risk_free_rate / 252.0

    # ── Step 1: generate return paths ────────────────────────────────────────
    return_paths = run_return_bootstrap(returns, n_simulations=n_simulations, seed=42)

    if method == "block_bootstrap":
        return_paths = run_block_bootstrap(returns, n_simulations=n_simulations, seed=43)
    elif method == "both":
        block_paths = run_block_bootstrap(returns, n_simulations=n_simulations, seed=43)

    # ── Step 2: NAV paths ────────────────────────────────────────────────────
    nav_paths = compute_nav_paths(return_paths, initial_nav=initial_nav)  # (n+1, sims)

    # ── Step 3: CAGR distribution ────────────────────────────────────────────
    final_navs  = nav_paths[-1]
    years       = n_days / 252.0
    cagr_all    = (final_navs / initial_nav) ** (1.0 / years) - 1.0

    cagr_dist = {
        "p5":  float(np.percentile(cagr_all, 5)),
        "p25": float(np.percentile(cagr_all, 25)),
        "p50": float(np.percentile(cagr_all, 50)),
        "p75": float(np.percentile(cagr_all, 75)),
        "p95": float(np.percentile(cagr_all, 95)),
        "mean": float(cagr_all.mean()),
        "std":  float(cagr_all.std()),
        "prob_negative_cagr": float((cagr_all < 0).mean()),
        "prob_ruin": float((final_navs < 0.5 * initial_nav).mean()),
    }

    # ── Step 4: Max drawdown distribution ────────────────────────────────────
    max_dds = compute_max_drawdowns(nav_paths)

    max_dd_dist = {
        "p5":   float(np.percentile(max_dds, 5)),
        "p25":  float(np.percentile(max_dds, 25)),
        "p50":  float(np.percentile(max_dds, 50)),
        "p75":  float(np.percentile(max_dds, 75)),
        "p95":  float(np.percentile(max_dds, 95)),
        "worst": float(max_dds.min()),
    }

    # ── Step 5: Sharpe distribution ──────────────────────────────────────────
    mean_ret  = return_paths.mean(axis=0)
    std_ret   = return_paths.std(axis=0, ddof=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sharpe_all = np.where(
            std_ret > 0,
            (mean_ret * 252 - risk_free_rate) / (std_ret * math.sqrt(252)),
            0.0,
        )

    from scipy.stats import skew as scipy_skew
    sharpe_dist = {
        "p5":   float(np.percentile(sharpe_all, 5)),
        "p25":  float(np.percentile(sharpe_all, 25)),
        "p50":  float(np.percentile(sharpe_all, 50)),
        "p75":  float(np.percentile(sharpe_all, 75)),
        "p95":  float(np.percentile(sharpe_all, 95)),
        "mean": float(sharpe_all.mean()),
        "std":  float(sharpe_all.std()),
        "skew": float(scipy_skew(sharpe_all)),
    }

    # ── Step 6: Drawdown duration ─────────────────────────────────────────────
    if method == "both":
        block_nav = compute_nav_paths(block_paths, initial_nav=initial_nav)
        dd_duration = compute_drawdown_durations(block_nav)
    else:
        dd_duration = compute_drawdown_durations(nav_paths)

    # ── Step 7: NAV percentile paths (monthly, for charting) ─────────────────
    percentiles = [5, 25, 50, 75, 95]
    # Sample at monthly intervals for JSON size
    if isinstance(returns.index, pd.DatetimeIndex):
        date_index = returns.index
        # Build monthly sample indices
        monthly_idx  = []
        monthly_dates = []
        prev_month = None
        for i, d in enumerate(date_index):
            m = (d.year, d.month)
            if m != prev_month:
                monthly_idx.append(i + 1)   # +1 because nav_paths row 0 = initial
                monthly_dates.append(str(d.date()))
                prev_month = m
        # Always include the last point
        if monthly_idx[-1] != n_days:
            monthly_idx.append(n_days)
            monthly_dates.append(str(date_index[-1].date()))

        sampled_nav = nav_paths[monthly_idx, :]  # (n_months, n_sims)
    else:
        # Fallback: every 20 days
        step_idx = list(range(0, n_days + 1, 20))
        if step_idx[-1] != n_days:
            step_idx.append(n_days)
        sampled_nav = nav_paths[step_idx, :]
        monthly_dates = [str(i) for i in step_idx]

    nav_percentiles: dict = {"dates": monthly_dates}
    for p in percentiles:
        nav_percentiles[f"p{p}"] = np.percentile(sampled_nav, p, axis=1).tolist()

    # ── Assemble result ───────────────────────────────────────────────────────
    start_date = str(returns.index[0].date()) if isinstance(returns.index, pd.DatetimeIndex) else "N/A"
    end_date   = str(returns.index[-1].date()) if isinstance(returns.index, pd.DatetimeIndex) else "N/A"

    return {
        "method":       method,
        "n_simulations": n_simulations,
        "n_days":        n_days,
        "initial_nav":   initial_nav,
        "risk_free_rate": risk_free_rate,
        "start":         start_date,
        "end":           end_date,
        "cagr_all":          cagr_all.tolist(),
        "max_drawdown_all":  max_dds.tolist(),
        "cagr_dist":         cagr_dist,
        "max_drawdown_dist": max_dd_dist,
        "sharpe_dist":       sharpe_dist,
        "drawdown_duration": dd_duration,
        "nav_percentiles":   nav_percentiles,
    }
