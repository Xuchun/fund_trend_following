"""
Abstract base class for all strategy versions.

V1 and V2 both inherit from BaseStrategy and implement the two abstract
methods. The backtest engine only calls these two methods, so swapping
strategy versions requires changing a single line in engine.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from backtest.portfolio import Portfolio
    from strategy.params import StrategyParams


class BaseStrategy(ABC):
    def __init__(self, params: "StrategyParams") -> None:
        self.params = params

    @abstractmethod
    def generate_entry_signals(
        self,
        date: pd.Timestamp,
        universe: list[str],
        price_panel: dict[str, pd.DataFrame],
        indicators: dict[str, dict],
        portfolio: "Portfolio",
    ) -> list[dict]:
        """
        Generate candidate entry signals as of the close of `date`.

        Returns a list of signal dicts sorted by breakout_strength descending.
        Each dict must contain at minimum:
            ticker, signal_close, atr, breakout_strength,
            preliminary_stop_loss, stop_distance_pct.

        Note: actual entry_price and final stop_loss are determined at t+1
        open by the engine (after gap filter and slippage).
        """
        ...

    @abstractmethod
    def generate_exit_signals(
        self,
        date: pd.Timestamp,
        portfolio: "Portfolio",
        price_panel: dict[str, pd.DataFrame],
        indicators: dict[str, dict],
    ) -> list[dict]:
        """
        Check all open positions for exit conditions as of the close of `date`.

        Also updates position.highest_high and position.trail_stop in-place
        for every open position (regardless of whether exit is triggered).

        Returns a list of exit signal dicts with keys:
            ticker, reason ('stop_loss' | 'trailing_stop'), exit_date.
        """
        ...
