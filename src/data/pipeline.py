"""
Data pipeline: load, clean, cache, and serve OHLCV price data.

Cache layout:
    data/cache/prices/{ticker}.parquet

Incremental update: if a Parquet file already exists, only the missing
tail dates are downloaded and appended before saving.
"""

import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd

from .adapters.base import DataSourceAdapter

logger = logging.getLogger(__name__)

# Default cache root relative to the project root
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "prices"

# Standard schema columns (in order)
OHLCV_COLS = ["open", "high", "low", "close", "volume", "adj_factor", "is_tradable"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cache_path(ticker: str, cache_dir: Path) -> Path:
    return cache_dir / f"{ticker.upper()}.parquet"


def _load_from_cache(ticker: str, cache_dir: Path) -> Optional[pd.DataFrame]:
    path = _cache_path(ticker, cache_dir)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        df.index = pd.DatetimeIndex(df.index)
        return df
    except Exception as e:
        logger.warning("Could not read cache for %s (%s), will re-download", ticker, e)
        return None


def _save_to_cache(df: pd.DataFrame, ticker: str, cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(ticker, cache_dir)
    df.to_parquet(path)
    logger.debug("Cached %s: %d rows → %s", ticker, len(df), path)


def _validate_schema(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """
    Ensure the DataFrame has exactly the required columns and correct dtypes.
    Missing columns are filled with NaN / False; extra columns are dropped.
    """
    for col in OHLCV_COLS:
        if col not in df.columns:
            df[col] = False if col == "is_tradable" else float("nan")
    df = df[OHLCV_COLS]
    df["is_tradable"] = df["is_tradable"].astype(bool)
    for col in OHLCV_COLS[:-1]:  # all except is_tradable
        df[col] = df[col].astype(float)
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_price_data(
    ticker: str,
    adapter: DataSourceAdapter,
    start: str,
    end: str,
    cache_dir: Optional[Path] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Load OHLCV data for one ticker, using the local Parquet cache when possible.

    Incremental update logic:
      1. Load cached file (if any).
      2. If cache covers [start, end], return it directly.
      3. Otherwise download only the missing date range and append.
      4. Save the merged result back to cache.

    Args:
        ticker:        Ticker symbol.
        adapter:       DataSourceAdapter instance to use for downloads.
        start:         Start date "YYYY-MM-DD".
        end:           End date "YYYY-MM-DD".
        cache_dir:     Override the default cache directory.
        force_refresh: If True, skip cache and re-download everything.

    Returns:
        Standardized DataFrame indexed by date, columns = OHLCV_COLS.
        Returns an empty DataFrame (with correct columns) on complete failure.
    """
    if cache_dir is None:
        cache_dir = _DEFAULT_CACHE_DIR

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    cached: Optional[pd.DataFrame] = None
    if not force_refresh:
        cached = _load_from_cache(ticker, cache_dir)

    if cached is not None and not cached.empty:
        cache_start = cached.index.min()
        cache_end = cached.index.max()

        download_start: Optional[pd.Timestamp] = None
        download_end: Optional[pd.Timestamp] = None

        if start_ts < cache_start:
            download_start = start_ts
            download_end = cache_start - pd.Timedelta(days=1)
        if end_ts > cache_end:
            tail_start = cache_end + pd.Timedelta(days=1)
            download_end = end_ts
            download_start = min(download_start or tail_start, tail_start)

        if download_start is None:
            # Cache fully covers the requested range
            mask = (cached.index >= start_ts) & (cached.index <= end_ts)
            return cached[mask]

        logger.info(
            "Incremental download for %s: %s → %s",
            ticker, download_start.date(), download_end.date(),
        )
        new_data = adapter.get_ohlcv(
            ticker,
            download_start.strftime("%Y-%m-%d"),
            download_end.strftime("%Y-%m-%d"),
        )

        if not new_data.empty:
            combined = pd.concat([cached, new_data])
            combined = combined[~combined.index.duplicated(keep="last")]
            combined = combined.sort_index()
        else:
            combined = cached

        combined = _validate_schema(combined, ticker)
        _save_to_cache(combined, ticker, cache_dir)
        mask = (combined.index >= start_ts) & (combined.index <= end_ts)
        return combined[mask]

    # No usable cache → full download
    logger.info("Full download for %s: %s → %s", ticker, start, end)
    df = adapter.get_ohlcv(ticker, start, end)

    if df.empty:
        logger.warning("Empty result for %s", ticker)
        return pd.DataFrame(columns=OHLCV_COLS)

    df = _validate_schema(df, ticker)
    _save_to_cache(df, ticker, cache_dir)
    return df


def load_price_panel(
    tickers: list[str],
    adapter: DataSourceAdapter,
    start: str,
    end: str,
    cache_dir: Optional[Path] = None,
    force_refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """
    Load OHLCV data for a list of tickers and return a dict of DataFrames.

    Tickers that fail to load are omitted from the result (logged as warnings).

    Returns:
        Dict mapping ticker → DataFrame (may be smaller than `tickers` list).
    """
    panel: dict[str, pd.DataFrame] = {}
    for i, ticker in enumerate(tickers):
        try:
            df = load_price_data(ticker, adapter, start, end, cache_dir, force_refresh)
            if not df.empty:
                panel[ticker] = df
            else:
                logger.warning("[%d/%d] %s: empty, skipped", i + 1, len(tickers), ticker)
        except Exception as e:
            logger.warning("[%d/%d] %s: download error: %s", i + 1, len(tickers), ticker, e)
    logger.info("Loaded %d / %d tickers", len(panel), len(tickers))
    return panel


def compute_adj_prices(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply adj_factor to raw OHLCV to produce adjusted prices.

    Returns a new DataFrame with additional columns:
        adj_open, adj_high, adj_low, adj_close
    The original unadjusted columns are preserved.
    """
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        out[f"adj_{col}"] = out[col] * out["adj_factor"]
    return out
