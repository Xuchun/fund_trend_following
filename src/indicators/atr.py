"""
ATR (Average True Range) using Wilder's smoothing method.

Wilder's ATR differs from a simple rolling average:
  - Seed value  = simple mean of the first `period` TR values
  - Subsequent  = (ATR_prev × (period - 1) + TR_curr) / period

This is a recursive formula, so the full history is consumed to produce
each value — unlike a rolling window that forgets older data.
"""

import numpy as np
import pandas as pd


def compute_true_range(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> pd.Series:
    """
    Compute daily True Range.

    TR[i] = max(
        high[i] - low[i],
        |high[i] - close[i-1]|,
        |low[i]  - close[i-1]|,
    )

    The first row has no prior close, so TR[0] = high[0] - low[0].

    Returns a Series with the same index as the inputs.
    """
    hl = high - low
    hc = (high - close.shift(1)).abs()
    lc = (low  - close.shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr


def compute_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 20,
) -> pd.Series:
    """
    Compute ATR using Wilder's smoothing.

    TR[i] = max(
        high[i] - low[i],
        |high[i] - close[i-1]|,
        |low[i]  - close[i-1]|,
    )

    ATR seed  = simple mean of TR[1 : period+1]  (TR[0] is valid but skipped for consistency)
    ATR[i]    = (ATR[i-1] × (period - 1) + TR[i]) / period

    Returns a Series aligned with the input index.
    Rows before the seed window is filled are NaN.

    Args:
        high:   Daily high prices.
        low:    Daily low prices.
        close:  Daily close prices (used for prior-close in TR).
        period: Smoothing period (default 20, matching common strategy usage).
    """
    if len(close) < period + 1:
        return pd.Series(np.nan, index=close.index)

    tr = compute_true_range(high, low, close)
    tr_values = tr.values.astype(float)

    atr_values = np.full(len(tr_values), np.nan)

    # Seed: simple average of TR[1:period+1].
    # TR[0] = high[0]-low[0] is valid (not NaN), but skipped to align the
    # seed window with the first full period of gap-adjusted TR values.
    seed_start = 1
    seed_end = seed_start + period  # exclusive
    if seed_end > len(tr_values):
        return pd.Series(np.nan, index=close.index)

    atr_values[seed_end - 1] = np.mean(tr_values[seed_start:seed_end])

    # Wilder's recursive smoothing
    for i in range(seed_end, len(tr_values)):
        atr_values[i] = (atr_values[i - 1] * (period - 1) + tr_values[i]) / period

    return pd.Series(atr_values, index=close.index)
