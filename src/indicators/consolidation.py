"""Consolidation filter: price range over lookback window must be narrow."""

import pandas as pd


def compute_consolidation_signal(
    high: pd.Series,
    low: pd.Series,
    window: int = 80,
    threshold: float = 0.25,
) -> pd.Series:
    """
    Returns True where the price range over the past `window` days is < threshold.

    range_ratio = (max(high[t-window:t-1]) - min(low[t-window:t-1])) / min(low[t-window:t-1])
    signal = range_ratio < threshold

    shift(1) excludes today's bar — no look-ahead bias.
    NaN where fewer than `window` bars exist.
    """
    high_max = high.rolling(window=window, min_periods=window).max().shift(1)
    low_min  = low.rolling(window=window, min_periods=window).min().shift(1)
    range_ratio = (high_max - low_min) / low_min
    return (range_ratio < threshold).fillna(False)
