"""
Position dataclass: single-trade state machine.

Created here (rather than in strategy/) so that both strategy/v1/exit.py
and the Phase-4 backtest engine can import from a single authoritative source.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Position:
    """
    Complete state for one open position.

    Fields set at entry (never change after open):
        ticker, entry_date, entry_price, shares, stop_loss, atr_at_entry

    Fields updated daily by exit.py:
        highest_high  — tracks the maximum high reached since entry
        trail_stop    — trailing stop price (monotonically increases)
    """

    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: int
    stop_loss: float       # fixed hard stop (never moves down or up)
    trail_stop: float      # trailing stop (only moves up)
    highest_high: float    # max(high) since entry; initialised to entry_price
    atr_at_entry: float    # ATR on entry day; used to compute R

    # ── Derived properties ─────────────────────────────────────────────────

    @property
    def R(self) -> float:
        """Initial risk per share = entry_price − stop_loss."""
        return self.entry_price - self.stop_loss

    @property
    def risk_amount(self) -> float:
        """Total risk committed by this position (used for heat calculation)."""
        return self.shares * self.R

    def market_value(self, current_price: float) -> float:
        """Mark-to-market value at `current_price`."""
        return self.shares * current_price

    def r_multiple(self, current_price: float) -> float:
        """
        Current unrealised gain expressed in units of initial risk R.

        r_multiple = (current_price − entry_price) / R
        Negative means the position is underwater.
        """
        r = self.R
        if r <= 0 or math.isnan(r):
            return 0.0
        return (current_price - self.entry_price) / r
