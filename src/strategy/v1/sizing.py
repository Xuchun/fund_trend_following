"""
Strategy V1 position sizing.

Implements the 4-step sizing pipeline from design spec Section B:
  Step 1: Raw position  (risk budget / risk per share)
  Step 2: Single-name cap  (position_cap % of NAV)
  Step 3: Correlation adjustment  (reduce if highly correlated with existing)
  Step 4: Portfolio heat check  (abandon if total risk exceeds heat_limit)
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd

from indicators.correlation import compute_max_correlation

if TYPE_CHECKING:
    from strategy.params import StrategyParams


def compute_position_size(
    entry_price: float,
    stop_loss: float,
    nav: float,
    existing_risk: float,
    current_positions: list[str],
    log_returns: dict[str, pd.Series],
    new_ticker: str,
    as_of_date: pd.Timestamp,
    params: "StrategyParams",
) -> int | None:
    """
    Compute the number of shares to buy for a new position.

    Args:
        entry_price:       Actual entry price (t+1 open + slippage).
        stop_loss:         Hard stop price for this position.
        nav:               Current portfolio NAV before this trade.
        existing_risk:     Sum of risk_amount across all open positions.
        current_positions: List of currently held tickers.
        log_returns:       Dict ticker → log-return Series (up to as_of_date).
        new_ticker:        Ticker being considered.
        as_of_date:        Signal date (for correlation window end).
        params:            StrategyParams instance.

    Returns:
        Integer share count (≥ 1), or None if the position should be skipped.
    """
    risk_per_share = entry_price - stop_loss

    # Guard: stop must be strictly below entry
    if risk_per_share <= 0 or math.isnan(risk_per_share):
        return None

    # ── Step 1: Raw position ────────────────────────────────────────────────
    risk_amount = nav * params.risk_per_trade
    raw_shares = risk_amount / risk_per_share

    # ── Step 2: Single-name cap ─────────────────────────────────────────────
    capped_shares = (nav * params.position_cap) / entry_price
    preliminary_shares = min(raw_shares, capped_shares)

    # ── Step 3: Correlation adjustment ──────────────────────────────────────
    max_corr = compute_max_correlation(
        new_ticker=new_ticker,
        current_positions=current_positions,
        log_returns=log_returns,
        as_of_date=as_of_date,
        window=params.correlation_window,
        min_samples=40,
    )

    if max_corr > params.correlation_threshold:
        final_shares = preliminary_shares * params.correlation_reduction
    else:
        final_shares = preliminary_shares

    # ── Step 4: Portfolio heat check ────────────────────────────────────────
    int_shares = int(final_shares)
    if int_shares < 1:
        return None

    new_risk = int_shares * risk_per_share
    total_heat = (existing_risk + new_risk) / nav
    if total_heat > params.heat_limit:
        return None

    return int_shares
