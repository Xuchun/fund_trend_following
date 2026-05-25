"""
Universe management: S&P 500 constituents + key ETFs, and date-filtered selection.

Limitations:
  - S&P 500 list is fetched from Wikipedia (current membership only).
  - No point-in-time index membership data (Yahoo Finance limitation).
  - Market cap filter uses current market cap, not historical.
"""

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Key sector/market ETFs always included in the universe
ETF_TICKERS: list[str] = [
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq 100
    "IWM",   # Russell 2000
    "DIA",   # Dow Jones
    "GLD",   # Gold
    "TLT",   # 20Y Treasury
    "SHY",   # 1-3Y Treasury
    "XLK",   # Technology
    "XLF",   # Financials
    "XLE",   # Energy
    "XLV",   # Health Care
    "XLI",   # Industrials
    "XLP",   # Consumer Staples
    "XLY",   # Consumer Discretionary
    "XLU",   # Utilities
    "XLRE",  # Real Estate
    "XLB",   # Materials
    "XLC",   # Communication Services
    "VNQ",   # Real Estate (broader)
    "EEM",   # Emerging Markets
    "EFA",   # Developed ex-US
]

_sp500_cache: Optional[list[str]] = None


def fetch_sp500_tickers() -> list[str]:
    """
    Fetch current S&P 500 constituents from Wikipedia.

    Uses requests with a browser User-Agent to avoid 403 blocks.
    Result is cached in-process for the lifetime of the interpreter.
    Returns an empty list on failure (caller should handle gracefully).
    """
    global _sp500_cache
    if _sp500_cache is not None:
        return _sp500_cache

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        import requests
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        tables = pd.read_html(resp.text)
        tickers = tables[0]["Symbol"].tolist()
        # Yahoo Finance uses "-" instead of "." for BRK.B, BF.B, etc.
        tickers = [t.replace(".", "-") for t in tickers]
        _sp500_cache = sorted(tickers)
        logger.info("Fetched %d S&P 500 tickers from Wikipedia", len(_sp500_cache))
        return _sp500_cache
    except Exception as e:
        logger.error("Failed to fetch S&P 500 from Wikipedia: %s", e)
        return []


def get_universe_at_date(
    price_panel: dict[str, pd.DataFrame],
    date: str,
    lookback_days: int = 60,
    min_price: float = 5.0,
    min_adv_m: float = 1.0,
) -> list[str]:
    """
    Return tickers that are investable on `date` given the loaded price panel.

    Filters applied:
      1. Row for `date` must exist and is_tradable must be True.
      2. Close price >= min_price on `date`.
      3. 60-day trailing average daily dollar volume (ADV_60) >= min_adv_m million.
         ADV_60 uses shift(1) to avoid look-ahead bias (yesterday's close × volume).

    Args:
        price_panel:   Dict mapping ticker → standardized OHLCV DataFrame.
        date:          Selection date "YYYY-MM-DD".
        lookback_days: Rolling window for ADV calculation (default 60).
        min_price:     Minimum close price in USD (default $5).
        min_adv_m:     Minimum average daily dollar volume in millions (default $1M).

    Returns:
        Sorted list of tickers passing all filters.
    """
    target = pd.Timestamp(date)
    qualifying: list[str] = []

    for ticker, df in price_panel.items():
        if target not in df.index:
            continue

        row = df.loc[target]
        if not row["is_tradable"]:
            continue
        if row["close"] < min_price:
            continue

        # ADV_60: rolling dollar volume using prior-day data to avoid look-ahead
        hist = df[df.index <= target].tail(lookback_days + 1)
        if len(hist) < lookback_days:
            continue

        dollar_vol = hist["close"].shift(1) * hist["volume"]
        adv_60 = dollar_vol.iloc[1:].mean()  # skip the first NaN from shift

        if adv_60 < min_adv_m * 1_000_000:
            continue

        qualifying.append(ticker)

    return sorted(qualifying)
