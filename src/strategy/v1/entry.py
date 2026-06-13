"""
Strategy V1 entry signal generation.

Scans the universe at the close of day t and returns candidate signals
sorted by breakout_strength (best breakout first).

Entry price and final stop_loss are NOT determined here — they depend on
t+1 opening price (gap filter + slippage), which is applied in engine.py.
"""

from __future__ import annotations

import pandas as pd

# ETF set for volume-filter bypass (loaded once at module import)
try:
    from data.universe import ETF_TICKERS as _ETF_TICKERS
    _ETF_SET: frozenset[str] = frozenset(_ETF_TICKERS)
except ImportError:
    _ETF_SET = frozenset()


def generate_entry_signals_v1(
    date: pd.Timestamp,
    universe: list[str],
    price_panel: dict[str, pd.DataFrame],
    indicators: dict[str, dict],
    currently_held: set[str],
    params: "StrategyParams",  # noqa: F821  (TYPE_CHECKING avoided for simplicity)
) -> list[dict]:
    """
    Generate candidate entry signals as of the close of `date`.

    Filters applied (in order):
      a. Ticker is not already held.
      b. Row exists for `date` and is_tradable is True.
      c. close[t] >= params.min_price.
      d. ADV_60[t] >= params.min_adv_m × 1e6  (includes today t, no shift; no look-ahead since signal is generated after close).
      e. breakout_signal[t] is True  (close[t] > rolling_high_N[t]).
      f. ATR[t] is not NaN.
      g. Preliminary stop distance >= params.min_stop_distance_pct.
         stop_distance = (close − preliminary_stop) / close
         where preliminary_stop = close − stop_loss_multiplier × ATR.
      h. Volume confirmation (if params.volume_filter_multiplier > 0):
         volume[t] >= params.volume_filter_multiplier × volume_ma_60[t].
         Rejects low-conviction breakouts not accompanied by elevated volume.
      i. Breakout strength (if params.breakout_strength_min > 0):
         close[t] / rolling_high_N[t] >= 1 + params.breakout_strength_min.
         Rejects marginal new highs; requires a decisive breakout above the lookback high.

    Note on market_cap filter: Yahoo Finance does not provide point-in-time
    market cap. The filter is skipped here; callers using a commercial data
    adapter should pass a pre-filtered universe.

    Args:
        date:           Signal date (t).
        universe:       List of ticker symbols to scan.
        price_panel:    Dict ticker → OHLCV DataFrame (output of pipeline).
        indicators:     Dict ticker → precomputed indicator dict (Phase 2).
        currently_held: Set of tickers with open positions.
        params:         StrategyParams instance.

    Returns:
        List of signal dicts sorted by breakout_strength descending.
        Each dict contains:
            ticker, signal_close, atr, breakout_strength,
            preliminary_stop_loss, stop_distance_pct.
    """
    signals: list[dict] = []

    for ticker in universe:
        # ── (a) Not already in portfolio ───────────────────────────────────
        if ticker in currently_held:
            continue

        if ticker not in price_panel or ticker not in indicators:
            continue

        df = price_panel[ticker]
        ind = indicators[ticker]

        # ── (b) Row exists and is tradable ─────────────────────────────────
        if date not in df.index:
            continue
        row = df.loc[date]
        if not row["is_tradable"]:
            continue

        # Min-price filter uses raw close (actual tradable price at that time).
        # All other calculations use adj_close (total-return consistent).
        if float(row["close"]) < params.min_price:
            continue
        close = float(row["adj_close"])

        # ── (d) ADV filter ──────────────────────────────────────────────────
        adv_series = ind["adv"]
        if date not in adv_series.index:
            continue
        adv = adv_series[date]
        if pd.isna(adv) or adv < params.min_adv_m * 1_000_000:
            continue

        # ── (e) Breakout signal ─────────────────────────────────────────────
        sig_series = ind["breakout_signal"]
        if date not in sig_series.index or not sig_series[date]:
            continue

        # ── (f) Valid ATR ───────────────────────────────────────────────────
        atr_series = ind["atr"]
        if date not in atr_series.index:
            continue
        atr = float(atr_series[date])
        if pd.isna(atr) or atr <= 0:
            continue

        # ── (g) Minimum stop distance ───────────────────────────────────────
        preliminary_stop = close - params.stop_loss_multiplier * atr
        if preliminary_stop >= close:
            continue  # degenerate: stop above entry
        stop_distance_pct = (close - preliminary_stop) / close
        if stop_distance_pct < params.min_stop_distance_pct:
            continue

        # ── (h) Volume confirmation ─────────────────────────────────────────
        if params.volume_filter_multiplier > 0:
            vol_ma_series = ind.get("volume_ma")
            if vol_ma_series is not None and date in vol_ma_series.index:
                vol_ma = vol_ma_series[date]
                if not pd.isna(vol_ma) and vol_ma > 0:
                    today_vol = float(row["volume"])
                    if today_vol < params.volume_filter_multiplier * vol_ma:
                        continue

        # ── Breakout strength ────────────────────────────────────────────────
        str_series = ind["breakout_strength"]
        bs = float(str_series[date]) if (date in str_series.index and not pd.isna(str_series[date])) else 1.0

        # ── (i) Breakout strength filter ────────────────────────────────────
        if params.breakout_strength_min > 0 and bs < 1.0 + params.breakout_strength_min:
            continue

        signals.append(
            {
                "ticker":              ticker,
                "signal_date":         date,
                "signal_close":        close,
                "atr":                 atr,
                "breakout_strength":   bs,
                "preliminary_stop_loss": preliminary_stop,
                "stop_distance_pct":   stop_distance_pct,
            }
        )

    # Best breakout first
    signals.sort(key=lambda s: s["breakout_strength"], reverse=True)
    return signals
