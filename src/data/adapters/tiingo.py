"""
Tiingo data source adapter.

Data quality advantages over Yahoo Finance:
  - More accurate dividend and split adjustments.
  - Includes delisted tickers (call get_ohlcv with a known delisted symbol).
  - Stable, well-documented API with predictable rate limits.

Limitations:
  - No point-in-time index constituents (survivorship bias still present
    unless caller supplies historical membership lists).
  - Market cap: current value only, not point-in-time.

API docs: https://api.tiingo.com/documentation/end-of-day
"""

import logging
import os
import time
from typing import Optional

import pandas as pd
import requests

from .base import DataSourceAdapter

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.tiingo.com/tiingo/daily"
_REQUIRED_COLS = ["open", "high", "low", "close", "volume", "adj_factor", "is_tradable"]
_ADJ_FACTOR_JUMP_THRESH = 0.50


def _normalize_ticker(ticker: str) -> str:
    """Convert Yahoo-style BRK-B → Tiingo-style BRK-B (Tiingo also uses hyphen)."""
    return ticker.upper()


def _parse_response(data: list[dict], ticker: str) -> pd.DataFrame:
    """Convert Tiingo JSON list → standardised OHLCV DataFrame."""
    if not data:
        return pd.DataFrame(columns=_REQUIRED_COLS)

    df = pd.DataFrame(data)

    # Parse dates; Tiingo returns ISO-8601 with timezone offset
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None)
    df = df.set_index("date").sort_index()

    # Raw OHLCV
    raw_close = df["close"].astype(float)
    adj_close = df["adjClose"].astype(float)

    # adj_factor = adjClose / close; clip to guard against data errors
    adj_factor = (adj_close / raw_close.replace(0, float("nan"))).clip(1e-6, 10.0)

    # is_tradable: flag bad rows
    vol = df["volume"].astype(float)
    raw_open = df["open"].astype(float)
    raw_high = df["high"].astype(float)
    raw_low = df["low"].astype(float)

    bad_volume = vol == 0
    bad_ohlc = (raw_open > raw_high + 1e-6) | (raw_low > raw_close + 1e-6)
    bad_adj = adj_factor.pct_change().abs() > _ADJ_FACTOR_JUMP_THRESH

    is_tradable = ~(bad_volume | bad_ohlc | bad_adj)

    result = pd.DataFrame(
        {
            "open":        raw_open,
            "high":        raw_high,
            "low":         raw_low,
            "close":       raw_close,
            "volume":      vol,
            "adj_factor":  adj_factor,
            "is_tradable": is_tradable,
        },
        index=df.index,
    )
    result.index.name = "date"
    return result


class TiingoAdapter(DataSourceAdapter):
    """
    DataSourceAdapter backed by the Tiingo End-of-Day API.

    Usage:
        adapter = TiingoAdapter()                          # reads TIINGO_API_TOKEN env var
        adapter = TiingoAdapter(api_token="<your_token>") # explicit token
        df = adapter.get_ohlcv("AAPL", "2004-01-01", "2026-06-13")

    Rate limits (Power plan): 10,000 req/hr, 100,000 req/day.
    The default request_delay of 0.4 s keeps throughput ≈ 2.5 req/s (well within limits).
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        request_delay: float = 0.4,
        max_retries: int = 3,
    ):
        token = api_token or os.environ.get("TIINGO_API_TOKEN", "")
        if not token:
            raise ValueError(
                "Tiingo API token required. Pass api_token= or set TIINGO_API_TOKEN env var."
            )
        self._token = token
        self._delay = request_delay
        self._max_retries = max_retries

        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Token {token}",
        })

    def get_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """
        Fetch daily OHLCV for a single ticker from the Tiingo API.

        Retries up to max_retries times on transient errors (429, 5xx, timeout).
        Returns an empty DataFrame (correct schema) if the ticker is not found.
        """
        sym = _normalize_ticker(ticker)
        url = f"{_BASE_URL}/{sym}/prices"
        params = {
            "startDate": start,
            "endDate":   end,
            "resampleFreq": "daily",
            "token": self._token,
        }

        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=30)

                if resp.status_code == 404:
                    logger.warning("Tiingo: ticker %s not found (404)", sym)
                    return pd.DataFrame(columns=_REQUIRED_COLS)

                if resp.status_code == 429:
                    wait = 60 * attempt
                    logger.warning("Tiingo rate-limited; waiting %ds (attempt %d)", wait, attempt)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if self._delay > 0:
                    time.sleep(self._delay)

                return _parse_response(data, sym)

            except requests.exceptions.Timeout:
                logger.warning("Tiingo timeout for %s (attempt %d/%d)", sym, attempt, self._max_retries)
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)
            except requests.exceptions.RequestException as e:
                logger.error("Tiingo request error for %s: %s", sym, e)
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)
                else:
                    raise

        return pd.DataFrame(columns=_REQUIRED_COLS)

    def get_universe(self, date: str) -> list[str]:
        """
        Return current S&P 900 + ETF universe (same as Yahoo adapter).

        NOTE: Not point-in-time. Survivorship bias limitation applies.
        """
        from ..universe import fetch_sp900_tickers, ETF_TICKERS
        sp900 = fetch_sp900_tickers()
        return sorted(set(sp900) | set(ETF_TICKERS))

    def get_market_cap(self, ticker: str, date: str) -> Optional[float]:
        """
        Return current market cap from Tiingo fundamentals (NOT point-in-time).
        Returns None if unavailable or fundamentals not subscribed.
        """
        sym = _normalize_ticker(ticker)
        url = f"https://api.tiingo.com/tiingo/fundamentals/{sym}/statements"
        try:
            resp = self._session.get(url, params={"token": self._token}, timeout=15)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data and isinstance(data, list):
                latest = data[-1]
                mktcap = latest.get("marketCap")
                return float(mktcap) if mktcap else None
        except Exception as e:
            logger.warning("Could not get market cap for %s: %s", sym, e)
        return None
