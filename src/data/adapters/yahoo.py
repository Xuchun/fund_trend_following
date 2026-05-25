"""
Yahoo Finance data source adapter.

Limitations (accepted for prototype):
  - Survivorship bias: no delisted tickers, results biased ~20-50% high.
  - Market cap: current value only, not point-in-time.
  - Universe: static list, not historical index membership.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from .base import DataSourceAdapter

logger = logging.getLogger(__name__)

# Columns required in the final DataFrame
_REQUIRED_COLS = ["open", "high", "low", "close", "volume", "adj_factor", "is_tradable"]

# Threshold for flagging a daily adj_factor jump as suspicious (e.g. 50% move)
_ADJ_FACTOR_JUMP_THRESH = 0.50


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten yfinance 1.x MultiIndex columns to simple lowercase names."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    return df


def _compute_adj_factor(raw: pd.DataFrame) -> pd.Series:
    """
    Compute daily adjustment factor from raw (auto_adjust=False) data.

    adj_factor = adj_close / close
    Values are clipped to (0, 10] to guard against data errors.
    """
    adj = raw["adj close"] / raw["close"]
    adj = adj.clip(lower=1e-6, upper=10.0)
    return adj


def _mark_is_tradable(
    df: pd.DataFrame,
    adj_factor: pd.Series,
) -> pd.Series:
    """
    Return a boolean Series: True where the row is usable for trading.

    A row is non-tradable if ANY of the following hold:
      1. volume == 0 (market closed / no data)
      2. open > high or low > close (dirty OHLC)
      3. |adj_factor change| > threshold (likely bad corporate-action data)
    """
    bad_volume = df["volume"] == 0
    bad_ohlc = (df["open"] > df["high"] + 1e-6) | (df["low"] > df["close"] + 1e-6)
    adj_pct_change = adj_factor.pct_change().abs()
    bad_adj = adj_pct_change > _ADJ_FACTOR_JUMP_THRESH

    is_tradable = ~(bad_volume | bad_ohlc | bad_adj)
    return is_tradable


class YahooFinanceAdapter(DataSourceAdapter):
    """
    Concrete DataSourceAdapter backed by yfinance.

    Usage:
        adapter = YahooFinanceAdapter()
        df = adapter.get_ohlcv("SPY", "2020-01-01", "2023-12-31")
    """

    def get_ohlcv(
        self,
        ticker: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """
        Download raw (unadjusted) OHLCV from Yahoo Finance and return a
        standardized DataFrame with adj_factor and is_tradable columns.

        The caller is responsible for applying adj_factor when needed:
            adj_close = close * adj_factor
            adj_open  = open  * adj_factor
        """
        logger.debug("Downloading %s from %s to %s", ticker, start, end)

        try:
            raw = yf.download(
                ticker,
                start=start,
                end=end,
                auto_adjust=False,
                progress=False,
                actions=False,
            )
        except Exception as e:
            logger.error("yfinance download failed for %s: %s", ticker, e)
            raise

        if raw.empty:
            logger.warning("No data returned for %s (%s → %s)", ticker, start, end)
            return pd.DataFrame(columns=_REQUIRED_COLS)

        raw = _flatten_columns(raw)

        # Ensure required raw columns exist
        needed = {"open", "high", "low", "close", "volume", "adj close"}
        missing = needed - set(raw.columns)
        if missing:
            raise ValueError(f"Yahoo data for {ticker} missing columns: {missing}")

        adj_factor = _compute_adj_factor(raw)
        is_tradable = _mark_is_tradable(raw, adj_factor)

        result = pd.DataFrame(
            {
                "open":        raw["open"].astype(float),
                "high":        raw["high"].astype(float),
                "low":         raw["low"].astype(float),
                "close":       raw["close"].astype(float),
                "volume":      raw["volume"].astype(float),
                "adj_factor":  adj_factor,
                "is_tradable": is_tradable,
            },
            index=raw.index,
        )

        result.index.name = "date"
        result = result.sort_index()
        return result

    def get_universe(self, date: str) -> list[str]:
        """
        Return a static combined universe of S&P 500 constituents + key ETFs.

        NOTE: This is NOT point-in-time. It reflects the *current* S&P 500
        membership. Historical entries/exits are ignored.
        """
        from ..universe import fetch_sp500_tickers, ETF_TICKERS
        sp500 = fetch_sp500_tickers()
        return sorted(set(sp500) | set(ETF_TICKERS))

    def get_market_cap(self, ticker: str, date: str) -> Optional[float]:
        """
        Return current market cap from Yahoo Finance (NOT point-in-time).

        Returns None on any error.
        """
        try:
            info = yf.Ticker(ticker).info
            return float(info.get("marketCap") or 0) or None
        except Exception as e:
            logger.warning("Could not get market cap for %s: %s", ticker, e)
            return None
