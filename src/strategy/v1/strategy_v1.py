"""
Strategy V1: assembles entry, exit, and sizing modules into the BaseStrategy interface.

The backtest engine only interacts with this class through the two abstract
methods. Swapping to V2 requires only changing the strategy instantiation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from strategy.base import BaseStrategy
from strategy.v1.entry import generate_entry_signals_v1
from strategy.v1.exit import check_exit_signals_v1

if TYPE_CHECKING:
    from backtest.portfolio import Portfolio
    from strategy.params import StrategyParams


class StrategyV1(BaseStrategy):
    """
    Trend-following Strategy 1.0.

    Entry:  N-day channel breakout (close > rolling_high_N).
    Stop:   Fixed hard stop at entry − M × ATR.
    Trail:  Segmented trailing stop keyed on R_multiple.
    Size:   Risk-parity raw → cap → correlation → heat.
    """

    def generate_entry_signals(
        self,
        date: pd.Timestamp,
        universe: list[str],
        price_panel: dict[str, pd.DataFrame],
        indicators: dict[str, dict],
        portfolio: "Portfolio",
    ) -> list[dict]:
        currently_held = set(portfolio.positions.keys())
        return generate_entry_signals_v1(
            date=date,
            universe=universe,
            price_panel=price_panel,
            indicators=indicators,
            currently_held=currently_held,
            params=self.params,
        )

    def generate_exit_signals(
        self,
        date: pd.Timestamp,
        portfolio: "Portfolio",
        price_panel: dict[str, pd.DataFrame],
        indicators: dict[str, dict],
    ) -> list[dict]:
        exit_signals: list[dict] = []

        for ticker, position in portfolio.positions.items():
            if ticker not in price_panel or ticker not in indicators:
                continue

            df = price_panel[ticker]
            if date not in df.index:
                continue

            row = df.loc[date]
            atr_series = indicators[ticker]["atr"]
            atr = float(atr_series[date]) if date in atr_series.index else float("nan")

            signal = check_exit_signals_v1(
                date=date,
                position=position,
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                atr=atr,
                params=self.params,
            )
            if signal is not None:
                exit_signals.append(signal)

        return exit_signals
