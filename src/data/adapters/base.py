"""
Abstract base class for all data source adapters.

To switch from Yahoo Finance to another data source, implement a new subclass
of DataSourceAdapter and change the adapter instantiation in pipeline.py.
"""

from abc import ABC, abstractmethod
import pandas as pd


class DataSourceAdapter(ABC):
    """
    Defines the interface all data adapters must implement.

    Returned DataFrames must conform to the standard schema:
      - Index: DatetimeIndex (UTC or tz-naive), business-day frequency
      - Columns: open, high, low, close, volume, adj_factor, is_tradable
        (all float64 except is_tradable which is bool)
    """

    @abstractmethod
    def get_ohlcv(
        self,
        ticker: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """
        Fetch daily OHLCV for a single ticker over [start, end].

        Args:
            ticker: Ticker symbol (e.g. "SPY", "AAPL").
            start:  Start date inclusive, "YYYY-MM-DD".
            end:    End date inclusive, "YYYY-MM-DD".

        Returns:
            DataFrame with DatetimeIndex and columns:
            open, high, low, close, volume, adj_factor, is_tradable.
            Adjusted OHLCV is NOT included here; compute it downstream
            by multiplying open/high/low/close by adj_factor.
        """
        ...

    @abstractmethod
    def get_universe(self, date: str) -> list[str]:
        """
        Return the list of investable tickers as of `date`.

        For adapters that lack point-in-time data (e.g. Yahoo Finance),
        return the current universe and document the survivorship-bias
        limitation in the subclass docstring.

        Args:
            date: Reference date "YYYY-MM-DD" (may be ignored for Yahoo).

        Returns:
            List of ticker strings.
        """
        ...

    @abstractmethod
    def get_market_cap(self, ticker: str, date: str) -> float | None:
        """
        Return market cap (USD) for `ticker` as of `date`, or None if unavailable.

        Point-in-time accuracy depends on the underlying data source.
        Yahoo Finance only provides the current market cap (non-point-in-time).
        """
        ...
