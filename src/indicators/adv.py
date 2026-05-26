"""
Average Daily (Dollar) Volume indicator.

Uses shift(1) so ADV on day t is computed from days [t-window, t-1],
avoiding any look-ahead bias from today's volume.
"""

import pandas as pd


def compute_dollar_volume(
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """
    Daily dollar volume = close × volume.

    Uses the unadjusted close and volume as reported by the data source.
    Callers may substitute adj_close if preferred, but for universe
    filtering the unadjusted value is typically sufficient.

    Args:
        close:  Daily close prices.
        volume: Daily share volume.

    Returns:
        Series with same index as inputs.
    """
    return close * volume


def compute_adv(
    dollar_vol: pd.Series,
    window: int = 60,
) -> pd.Series:
    """
    Rolling average daily dollar volume, excluding the current day.

    ADV[t] = mean(dollar_vol[t-window : t-1])

    Implementation: dollar_vol.shift(1).rolling(window).mean()

    NaN for the first `window` rows.

    Args:
        dollar_vol: Daily dollar volume (e.g. output of compute_dollar_volume).
        window:     Look-back period in trading days (default 60).

    Returns:
        Series with same index as `dollar_vol`.
    """
    return dollar_vol.shift(1).rolling(window=window, min_periods=window).mean()


def compute_adv_from_ohlcv(
    close: pd.Series,
    volume: pd.Series,
    window: int = 60,
) -> pd.Series:
    """
    Convenience wrapper: compute dollar volume then ADV in one call.

    Args:
        close:  Daily close prices.
        volume: Daily share volume.
        window: Look-back period in trading days (default 60).

    Returns:
        ADV Series with same index as inputs.
    """
    dollar_vol = compute_dollar_volume(close, volume)
    return compute_adv(dollar_vol, window)


def compute_volume_ma(
    volume: pd.Series,
    window: int = 60,
) -> pd.Series:
    """
    Rolling average of raw share volume, excluding the current day.

    volume_ma[t] = mean(volume[t-window : t-1])

    Used for breakout volume confirmation:
        volume[t] > multiplier × volume_ma[t]

    Shares the same shift(1) convention as all other indicators,
    so there is no look-ahead bias.

    Args:
        volume: Daily share volume.
        window: Look-back period in trading days (default 60).

    Returns:
        Series with same index as `volume`.
    """
    return volume.shift(1).rolling(window=window, min_periods=window).mean()
