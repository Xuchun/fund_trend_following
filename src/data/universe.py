"""
Universe management: S&P 500 constituents + key ETFs, and date-filtered selection.

Limitations:
  - S&P 500 list is fetched from Wikipedia (current membership only).
  - No point-in-time index membership data (Yahoo Finance limitation).
  - Market cap filter uses current market cap, not historical.
"""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── Volatility / inverse ETF exclusion list ──────────────────────────────────
# These products have structural negative drift (VIX futures roll cost, daily
# leverage reset decay) and are inappropriate for a long-only trend-following
# strategy.  Applied to BOTH the Yahoo Finance and Tiingo universe.
EXCLUDED_VOL_ETFS: frozenset[str] = frozenset([
    # Category 1: VIX / volatility / leveraged / inverse (structural negative drift)
    "VXX", "UVXY", "SVXY", "VIXY", "TVIX",
    "SQQQ", "TQQQ", "UPRO", "SPXU", "SPXL", "SPXS",
    "SDS", "SSO", "SH",
    "TZA", "TNA", "FAS", "FAZ",
    "SDOW", "UDOW",
    "LABU", "LABD",
    "NUGT", "DUST", "JNUG", "JDST",
    # Category 2: structurally unsuitable for long-only trend-following
    "GDX",   # gold miners: company-specific risk on top of gold price; GLD/SLV suffice
    "FXI",   # China large-cap: government intervention breaks trend signals
    "ASHR",  # China A-shares: same; tighter capital-flow controls
    "KWEB",  # China internet: policy risk acute (−50%+ in 2021 on regulation)
    "EMB",   # EM bonds: credit + rate + EM risk combined; crisis-correlated with equities
    # Category 3: misclassified leveraged products (removed from ETF universe 2026-06)
    "ETH",   # GraniteShares 2x Long Ethereum Daily ETF — daily-reset 2x leverage, same structural decay as TQQQ/VXX
])

# ── ETF universe: loaded from data/ETFs.csv ────────────────────────────────
# Fallback used only when the CSV cannot be read (e.g., missing file).
_FALLBACK_ETF_TICKERS: list[str] = [
    "SPY", "QQQ", "IWM", "DIA", "GLD", "TLT", "SHY",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLC",
    "VNQ", "EEM", "EFA",
]


def _load_etf_tickers() -> list[str]:
    """Load ETF tickers from data/ETFs.csv in the project root."""
    csv_path = Path(__file__).resolve().parents[2] / "data" / "ETFs.csv"
    try:
        tickers = pd.read_csv(csv_path)["SYMBOL"].dropna().str.strip().tolist()
        tickers = sorted(set(tickers))
        logger.info("Loaded %d ETF tickers from %s", len(tickers), csv_path.name)
        return tickers
    except Exception as e:
        logger.warning("Cannot read ETFs.csv (%s) — using built-in fallback list", e)
        return _FALLBACK_ETF_TICKERS


ETF_TICKERS: list[str] = _load_etf_tickers()

_sp500_cache: Optional[list[str]] = None
_sp400_cache: Optional[list[str]] = None

_WIKI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _fetch_tickers_from_wikipedia(url: str, symbol_col: str = "Symbol") -> list[str]:
    """Fetch a ticker list from a Wikipedia table. Returns [] on failure."""
    try:
        import requests
        from io import StringIO
        resp = requests.get(url, headers=_WIKI_HEADERS, timeout=30)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        tickers = tables[0][symbol_col].tolist()
        return sorted(t.replace(".", "-") for t in tickers)
    except Exception as e:
        logger.error("Failed to fetch from %s: %s", url, e)
        return []


def fetch_sp500_tickers() -> list[str]:
    """
    Fetch current S&P 500 constituents (~500 large-caps, market cap > ~$14B).

    Uses requests with a browser User-Agent to avoid 403 blocks.
    Result is cached in-process for the lifetime of the interpreter.
    Returns an empty list on failure.
    """
    global _sp500_cache
    if _sp500_cache is None:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        _sp500_cache = _fetch_tickers_from_wikipedia(url)
        if _sp500_cache:
            logger.info("Fetched %d S&P 500 tickers from Wikipedia", len(_sp500_cache))
    return _sp500_cache or []


def fetch_sp400_tickers() -> list[str]:
    """
    Fetch current S&P MidCap 400 constituents (~400 mid-caps, market cap $2B–$14B).

    Combined with S&P 500, these ~900 tickers cover the strategy's target universe
    (market cap > $20亿 = $2B) far better than S&P 500 alone.
    Result is cached in-process. Returns an empty list on failure.
    """
    global _sp400_cache
    if _sp400_cache is None:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
        _sp400_cache = _fetch_tickers_from_wikipedia(url)
        if _sp400_cache:
            logger.info("Fetched %d S&P MidCap 400 tickers from Wikipedia", len(_sp400_cache))
    return _sp400_cache or []


def fetch_sp900_tickers() -> list[str]:
    """
    Fetch S&P 500 + MidCap 400 = ~900 tickers.

    This is the recommended candidate universe for the strategy:
      - Covers market cap roughly $2B and above (matching the $20亿 requirement)
      - Mid-caps ($2B–$14B) are where trend-following strategies find the best signals
      - Dynamic price/ADV filters in the engine further narrow the list each day
    """
    sp500 = fetch_sp500_tickers()
    sp400 = fetch_sp400_tickers()
    combined = sorted(set(sp500) | set(sp400))
    logger.info(
        "S&P 900 universe: %d tickers (SP500=%d, MidCap400=%d, overlap excluded)",
        len(combined), len(sp500), len(sp400),
    )
    return combined


def get_universe_at_date(
    price_panel: dict[str, pd.DataFrame],
    date: str,
    lookback_days: int = 60,
    min_price: float = 10.0,
    min_adv_m: float = 60.0,
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

        # ADV_60: rolling dollar volume using prior-day data to avoid look-ahead.
        # Compute (close × volume) first, then shift(1) so that at time t the
        # value reflects mean(dv[t-1], dv[t-2], …, dv[t-60]) — same convention
        # as adv.py and 08_eligible_universe.py.
        hist = df[df.index <= target].tail(lookback_days + 1)
        if len(hist) < lookback_days:
            continue

        dollar_vol = (hist["close"] * hist["volume"]).shift(1)
        adv_60 = dollar_vol.iloc[1:].mean()  # skip the first NaN from shift

        if adv_60 < min_adv_m * 1_000_000:
            continue

        qualifying.append(ticker)

    return sorted(qualifying)
