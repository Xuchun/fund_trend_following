"""
Pairwise correlation between log-return series.

Used at open-position time to check whether a new candidate is too
correlated with existing holdings, and to apply position-size reduction
when correlation exceeds the configured threshold.
"""

import numpy as np
import pandas as pd


def compute_log_returns(close: pd.Series) -> pd.Series:
    """
    Daily log returns: ln(close[t] / close[t-1]).

    The first row is NaN.

    Args:
        close: Daily close prices (adjusted or unadjusted, must be consistent).

    Returns:
        Series with same index as `close`.
    """
    return np.log(close / close.shift(1))


def compute_pairwise_correlation(
    returns_new: pd.Series,
    returns_existing: pd.Series,
    window: int = 60,
    min_samples: int = 40,
) -> float | None:
    """
    Pearson correlation between two log-return series over the trailing window.

    Steps (per design spec):
      1. Inner-join the two series on their date index.
      2. Take the most recent `window` observations.
      3. Return None if fewer than `min_samples` valid rows remain.
      4. Return None if either series has zero standard deviation.
      5. Return the Pearson correlation coefficient.

    Args:
        returns_new:      Log returns of the candidate ticker.
        returns_existing: Log returns of one existing position.
        window:           Rolling look-back in trading days (default 60).
        min_samples:      Minimum valid observations required (default 40).

    Returns:
        Pearson correlation in [-1, 1], or None if computation is not possible.
    """
    # Align on common dates, drop any NaN rows
    aligned = pd.concat(
        [returns_new.rename("new"), returns_existing.rename("existing")],
        axis=1,
        join="inner",
    ).dropna()

    tail = aligned.tail(window)
    if len(tail) < min_samples:
        return None

    std_new = tail["new"].std()
    std_ex  = tail["existing"].std()
    if std_new == 0 or std_ex == 0:
        return None

    corr = tail["new"].corr(tail["existing"])
    if np.isnan(corr):
        return None
    return float(corr)


def compute_max_correlation(
    new_ticker: str,
    current_positions: list[str],
    log_returns: dict[str, pd.Series],
    as_of_date: pd.Timestamp,
    window: int = 60,
    min_samples: int = 40,
) -> float:
    """
    Maximum positive Pearson correlation between a candidate and all open positions.

    Only positive correlation triggers position reduction — negative correlation
    indicates diversification benefit in a long-only portfolio and is treated as 0.

    Only uses log-return data up to and including `as_of_date` so there is no
    look-ahead bias.

    Args:
        new_ticker:        Ticker being considered for entry.
        current_positions: List of tickers currently held.
        log_returns:       Dict mapping ticker → full log-return Series.
        as_of_date:        Signal date; only data on or before this date is used.
        window:            Rolling look-back (default 60).
        min_samples:       Minimum valid observations (default 40).

    Returns:
        max(corr, 0) across all current positions.
        Returns 0.0 if no valid correlation can be computed (treat as uncorrelated).
    """
    if not current_positions or new_ticker not in log_returns:
        return 0.0

    returns_new = log_returns[new_ticker]
    returns_new = returns_new[returns_new.index <= as_of_date]

    max_pos_corr = 0.0
    for pos_ticker in current_positions:
        if pos_ticker not in log_returns or pos_ticker == new_ticker:
            continue
        returns_pos = log_returns[pos_ticker]
        returns_pos = returns_pos[returns_pos.index <= as_of_date]

        corr = compute_pairwise_correlation(
            returns_new, returns_pos, window=window, min_samples=min_samples
        )
        if corr is not None:
            max_pos_corr = max(max_pos_corr, corr)

    return max_pos_corr
