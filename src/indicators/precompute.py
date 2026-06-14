"""
Batch pre-computation of all indicators for the full price panel.

Run once before the backtest loop. The returned nested dict allows O(1)
per-day lookups inside the hot loop, avoiding repeated rolling calculations.
"""

import logging
from typing import TYPE_CHECKING

import pandas as pd

from .atr import compute_atr
from .adv import compute_adv_from_ohlcv, compute_volume_ma
from .breakout import compute_rolling_high, compute_breakout_signal, compute_breakout_strength
from .consolidation import compute_consolidation_signal
from .correlation import compute_log_returns

if TYPE_CHECKING:
    from strategy.params import StrategyParams

logger = logging.getLogger(__name__)


def precompute_indicators(
    price_panel: dict[str, pd.DataFrame],
    params: "StrategyParams",
) -> dict[str, dict]:
    """
    Pre-compute all indicators for every ticker in `price_panel`.

    Returns a nested dict:
    {
        ticker: {
            'atr':               pd.Series,   # Wilder's ATR
            'rolling_high':      pd.Series,   # max(high[t-N:t-1])
            'breakout_signal':   pd.Series,   # bool: close > rolling_high
            'breakout_strength': pd.Series,   # close / rolling_high
            'adv':               pd.Series,   # ADV_60 dollar volume (includes today, no shift)
            'volume_ma':         pd.Series,   # 60-day avg share volume (shift=1)
            'log_returns':       pd.Series,   # ln(close[t]/close[t-1])
        }
    }

    Parameter sensitivity:
      - Changing `atr_period`       → only 'atr' needs recomputation.
      - Changing `breakout_window`  → only 'rolling_high', 'breakout_signal',
                                      'breakout_strength' need recomputation.
      - 'adv', 'volume_ma', 'log_returns' are parameter-independent.

    Args:
        price_panel: Dict of ticker → standardized OHLCV DataFrame
                     (output of pipeline.load_price_panel).
        params:      StrategyParams instance supplying atr_period and
                     breakout_window.

    Returns:
        Nested indicator dict as described above.
    """
    result: dict[str, dict] = {}

    for ticker, df in price_panel.items():
        try:
            close  = df["adj_close"]
            high   = df["adj_high"]
            low    = df["adj_low"]
            volume = df["volume"]

            atr = compute_atr(high, low, close, period=params.atr_period)
            rolling_high = compute_rolling_high(high, window=params.breakout_window)
            breakout_signal = compute_breakout_signal(close, rolling_high)
            breakout_strength = compute_breakout_strength(close, rolling_high)
            adv = compute_adv_from_ohlcv(df["close"], volume, window=60)
            volume_ma = compute_volume_ma(volume, window=60)
            log_returns = compute_log_returns(close)
            consolidation_signal = compute_consolidation_signal(
                high, low,
                window=params.consolidation_window,
                threshold=params.consolidation_threshold,
            )

            result[ticker] = {
                "atr":                  atr,
                "rolling_high":         rolling_high,
                "breakout_signal":      breakout_signal,
                "breakout_strength":    breakout_strength,
                "adv":                  adv,
                "volume_ma":            volume_ma,
                "log_returns":          log_returns,
                "consolidation_signal": consolidation_signal,
            }
        except Exception as e:
            logger.warning("Failed to compute indicators for %s: %s", ticker, e)

    logger.info(
        "Precomputed indicators for %d / %d tickers",
        len(result), len(price_panel),
    )
    return result
