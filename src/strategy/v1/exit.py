"""
Strategy V1 exit logic: trailing stop update and exit signal generation.

Both functions operate on a single Position object and update its state
in-place (highest_high, trail_stop). This is intentional: the position's
trailing state must be maintained even on days when no exit is triggered.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from backtest.position import Position
    from strategy.params import StrategyParams


def update_trail_stop_v1(
    position: "Position",
    high: float,
    close: float,
    atr: float,
    params: "StrategyParams",
) -> None:
    """
    Update position.highest_high and position.trail_stop in-place.

    Trailing stop segmented formula (design spec Section D):
        R_multiple = (close − entry_price) / R

        if R_multiple < 1:   multiplier = trail_multiplier_r1  (default 3.0)
        if R_multiple < 3:   multiplier = trail_multiplier_r3  (default 3.0)
        else:                multiplier = trail_multiplier_r5  (default 5.0)

        new_trail  = highest_high − multiplier × ATR
        trail_stop = max(trail_stop, new_trail)   ← only moves up

    Skips update if ATR is NaN/zero or position.R ≤ 0 (degenerate).
    """
    # Step 1: update highest high with today's intraday high
    position.highest_high = max(position.highest_high, high)

    # Guard: need valid ATR and a positive initial risk
    if math.isnan(atr) or atr <= 0:
        return
    r = position.R
    if r <= 0 or math.isnan(r):
        return

    # Step 2: compute R_multiple from today's close
    r_multiple = (close - position.entry_price) / r

    # Step 3: select trailing multiplier
    if r_multiple < 1.0:
        multiplier = params.trail_multiplier_r1
    elif r_multiple < 3.0:
        multiplier = params.trail_multiplier_r3
    else:
        multiplier = params.trail_multiplier_r5

    # Step 4: new candidate trail stop and ratchet (only moves up)
    new_trail = position.highest_high - multiplier * atr
    position.trail_stop = max(position.trail_stop, new_trail)


def check_exit_signals_v1(
    date: pd.Timestamp,
    position: "Position",
    high: float,
    low: float,
    close: float,
    atr: float,
    params: "StrategyParams",
) -> dict | None:
    """
    Update position state and check exit conditions for a single position.

    Always updates highest_high and trail_stop (side effect), then checks
    exit triggers in priority order:

      1. Stop loss    — triggered if low[t] < position.stop_loss
                        (intraday breach; execution at t+1 open in engine)
      2. Trailing stop — triggered if close[t] < position.trail_stop
                        (end-of-day check; execution at t+1 open in engine)

    Returns:
        dict  {'ticker': str, 'reason': 'stop_loss'|'trailing_stop', 'exit_date': Timestamp}
        None  if no exit is triggered
    """
    # Always update state first, regardless of exit
    update_trail_stop_v1(position, high, close, atr, params)

    # Priority 1: hard stop loss (intraday low check)
    if low < position.stop_loss:
        return {
            "ticker": position.ticker,
            "reason": "stop_loss",
            "exit_date": date,
        }

    # Priority 2: trailing stop (close check)
    if close < position.trail_stop:
        return {
            "ticker": position.ticker,
            "reason": "trailing_stop",
            "exit_date": date,
        }

    return None
