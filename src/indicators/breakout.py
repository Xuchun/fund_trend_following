"""
Breakout signal indicators.

All functions use shift(1) so that the value on day t reflects only
information available before the open on day t (no look-ahead bias).
"""

import pandas as pd


def compute_rolling_high(
    high: pd.Series,
    window: int = 100,
) -> pd.Series:
    """
    Rolling N-day high, excluding the current day.

    rolling_high[t] = max(high[t-N : t-1])

    Implementation: high.shift(1).rolling(window).max()

    The result is NaN for the first `window` rows because there are not yet
    enough prior bars to fill the window.

    Args:
        high:   Daily high prices.
        window: Look-back period N (default 100).

    Returns:
        Series with same index as `high`.
    """
    return high.shift(1).rolling(window=window, min_periods=window).max()


def compute_breakout_signal(
    close: pd.Series,
    rolling_high: pd.Series,
) -> pd.Series:
    """
    True on days when close exceeds the prior N-day high.

    breakout_signal[t] = close[t] > rolling_high[t]

    NaN in rolling_high produces False (no signal) rather than NaN,
    so callers can safely use this as a boolean mask.

    Args:
        close:        Daily close prices.
        rolling_high: Output of compute_rolling_high().

    Returns:
        Boolean Series with same index as `close`.
    """
    signal = close > rolling_high
    signal = signal.fillna(False)
    return signal


def compute_breakout_strength(
    close: pd.Series,
    rolling_high: pd.Series,
) -> pd.Series:
    """
    Ratio of close to the rolling high, used to rank simultaneous breakouts.

    breakout_strength[t] = close[t] / rolling_high[t]

    Values > 1 indicate a breakout. When multiple signals fire on the same
    day, positions are opened in descending order of breakout_strength.

    NaN where rolling_high is NaN or zero.

    Args:
        close:        Daily close prices.
        rolling_high: Output of compute_rolling_high().

    Returns:
        Float Series with same index as `close`.
    """
    ratio = close / rolling_high
    # Replace inf/-inf (division by zero) with NaN
    ratio = ratio.replace([float("inf"), float("-inf")], float("nan"))
    strength = ratio.where(rolling_high > 0)
    return strength
