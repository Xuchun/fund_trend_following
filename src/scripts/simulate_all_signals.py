"""
simulate_all_signals.py — Strategy V1 full signal simulation

Generates ALL entry signals that pass the v1 technical filters for every
trading day, ignoring portfolio constraints (position cap, heat limit,
correlation, cash). Simulates isolated P&L for each signal using the v1
exit logic (trailing stop / stop loss).

Output:
    results/v1_unbiased_60m_2000/all_signals_simulated.csv

Columns:
    ticker, signal_date, k_strength, gap_filtered,
    entry_date, entry_price, stop_loss, R,
    exit_date, exit_price, pnl_r, exit_reason, executed

Usage:
    python src/scripts/simulate_all_signals.py

Runtime: ~3-8 minutes depending on hardware.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
_root    = Path(__file__).resolve().parents[2]
_RESULTS = _root / "results" / "v1_unbiased_60m_2000"
_PRICES  = _root / "data" / "cache" / "prices"
_UNI     = _root / "data" / "tiingo_eligible_universe.csv"
_OUT     = _RESULTS / "all_signals_simulated.csv"

# ── Load strategy parameters ──────────────────────────────────────────────────
with open(_RESULTS / "strategy_meta.json") as _f:
    _meta = json.load(_f)
_P = _meta.get("params_anchor", _meta)

MIN_PRICE        = float(_P["min_price"])               # 10.0
MIN_ADV_M        = float(_P["min_adv_m"]) * 1e6        # 60e6
BREAKOUT_WINDOW  = int(_P["breakout_window"])           # 200
ATR_PERIOD       = int(_P["atr_period"])                # 20
STOP_MULT        = float(_P["stop_loss_multiplier"])    # 2.0
MIN_STOP_DIST    = float(_P["min_stop_distance_pct"])  # 0.005
TRAIL_R1         = float(_P["trail_multiplier_r1"])    # 3.0
TRAIL_R3         = float(_P["trail_multiplier_r3"])    # 3.0
TRAIL_R5         = float(_P["trail_multiplier_r5"])    # 5.0
VOL_MULT         = float(_P["volume_filter_multiplier"]) # 1.5
BS_MIN           = float(_P["breakout_strength_min"])  # 0.0
GAP_FILTER       = float(_P["gap_filter"])             # 0.025
SLIPPAGE_BPS     = float(_P["slippage_bps"])           # 10.0
REGIME_SMA_WIN   = int(_P["regime_sma_window"])        # 200
BEAR_EXEMPT      = set(_P.get("bear_exempt_tickers", ["GLD", "TLT", "UUP"]))

BACKTEST_END = pd.Timestamp("2026-06-15")


# ── Wilder ATR (vectorized) ───────────────────────────────────────────────────
def _wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20) -> np.ndarray:
    n = len(close)
    hl = high - low
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    hc = np.abs(high - prev_close)
    lc = np.abs(low  - prev_close)
    tr = np.maximum(np.maximum(hl, hc), lc)

    atr = np.full(n, np.nan)
    seed_end = 1 + period
    if seed_end > n:
        return atr
    atr[seed_end - 1] = np.mean(tr[1:seed_end])
    for i in range(seed_end, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


# ── Load one ticker: returns dict of numpy arrays keyed by column ─────────────
def _load_ticker(ticker: str) -> dict | None:
    f = _PRICES / f"{ticker}.parquet"
    if not f.exists():
        return None
    try:
        df = pd.read_parquet(f).sort_index()
    except Exception:
        return None

    af  = df["adj_factor"].values.astype(float)
    raw_o = df["open"].values.astype(float)
    raw_h = df["high"].values.astype(float)
    raw_l = df["low"].values.astype(float)
    raw_c = df["close"].values.astype(float)
    vol   = df["volume"].values.astype(float)
    is_tr = df["is_tradable"].values.astype(bool)

    ao = raw_o * af
    ah = raw_h * af
    al = raw_l * af
    ac = raw_c * af

    atr = _wilder_atr(ah, al, ac, ATR_PERIOD)

    # Rolling max of adj_high (BREAKOUT_WINDOW, shifted 1 to avoid look-ahead)
    s = pd.Series(ah, index=df.index)
    rolling_high = s.shift(1).rolling(BREAKOUT_WINDOW, min_periods=BREAKOUT_WINDOW).max().values

    # Breakout signal: adj_close > rolling_high
    breakout_sig = ac > rolling_high

    # Breakout strength
    with np.errstate(divide="ignore", invalid="ignore"):
        bs = np.where(rolling_high > 0, ac / rolling_high, np.nan)

    # ADV (60d average of close × volume, shifted)
    dv  = raw_c * vol
    adv = pd.Series(dv, index=df.index).shift(1).rolling(60, min_periods=60).mean().values

    # Volume MA (60d, shifted)
    vol_ma = pd.Series(vol, index=df.index).shift(1).rolling(60, min_periods=60).mean().values

    return {
        "index":         np.array(df.index),   # datetime64[ns]
        "adj_open":      ao,
        "adj_high":      ah,
        "adj_low":       al,
        "adj_close":     ac,
        "raw_close":     raw_c,
        "volume":        vol,
        "is_tradable":   is_tr,
        "atr":           atr,
        "rolling_high":  rolling_high,
        "breakout_sig":  breakout_sig,
        "bs":            bs,
        "adv":           adv,
        "vol_ma":        vol_ma,
    }


# ── Simulate a single trade (isolated, no portfolio) ─────────────────────────
def _simulate_trade(
    d: dict,
    sig_idx: int,       # index into d["index"] arrays for the signal day
) -> dict:
    """
    Simulate entry and exit for one signal.

    Returns a dict with: gap_filtered, entry_date, entry_price, stop_loss, R,
                         exit_date, exit_price, pnl_r, exit_reason.
    """
    idx_arr = d["index"]
    n       = len(idx_arr)

    # Entry = next trading day (sig_idx + 1)
    if sig_idx + 1 >= n:
        return {"gap_filtered": True, "exit_reason": "no_next_day"}

    entry_i     = sig_idx + 1
    signal_ac   = float(d["adj_close"][sig_idx])
    open_price  = float(d["adj_open"][entry_i])

    # Gap filter
    if signal_ac <= 0:
        return {"gap_filtered": True, "exit_reason": "gap_filtered"}
    gap_pct = abs(open_price - signal_ac) / signal_ac
    if gap_pct > GAP_FILTER:
        return {"gap_filtered": True, "exit_reason": "gap_filtered"}

    atr_sig     = float(d["atr"][sig_idx])
    entry_price = open_price * (1.0 + SLIPPAGE_BPS / 10_000)
    stop_loss   = entry_price - STOP_MULT * atr_sig
    if stop_loss >= entry_price:
        return {"gap_filtered": True, "exit_reason": "degenerate_stop"}
    R           = entry_price - stop_loss

    trail_stop   = entry_price - TRAIL_R1 * atr_sig
    highest_high = entry_price

    exit_date   = None
    exit_price  = None
    exit_reason = "end_of_backtest"

    for j in range(entry_i, n):
        day_ts = idx_arr[j]
        if day_ts > BACKTEST_END:
            break

        ah_j  = float(d["adj_high"][j])
        al_j  = float(d["adj_low"][j])
        ac_j  = float(d["adj_close"][j])
        atr_j = float(d["atr"][j])

        # Update trailing stop
        highest_high = max(highest_high, ah_j)
        if not np.isnan(atr_j) and atr_j > 0:
            r_mult = (highest_high - entry_price) / R
            mult   = TRAIL_R5 if r_mult >= 3.0 else (TRAIL_R3 if r_mult >= 1.0 else TRAIL_R1)
            new_trail  = highest_high - mult * atr_j
            trail_stop = max(trail_stop, new_trail)

        # Check exit triggers
        triggered = None
        if al_j < stop_loss:
            triggered = "stop_loss"
        elif ac_j < trail_stop:
            triggered = "trailing_stop"

        if triggered:
            # Execute at next day's open
            if j + 1 < n:
                next_o     = float(d["adj_open"][j + 1])
                exit_price = next_o * (1.0 - SLIPPAGE_BPS / 10_000)
                exit_date  = idx_arr[j + 1]
            else:
                exit_price = ac_j * (1.0 - SLIPPAGE_BPS / 10_000)
                exit_date  = day_ts
            exit_reason = triggered
            break

    if exit_date is None:
        # End of data / backtest
        last_j     = min(n - 1, n - 1)
        exit_price = float(d["adj_close"][last_j]) * (1.0 - SLIPPAGE_BPS / 10_000)
        exit_date  = idx_arr[last_j]
        exit_reason = "end_of_backtest"

    pnl_r = (exit_price - entry_price) / R

    return {
        "gap_filtered": False,
        "entry_date":   idx_arr[entry_i],
        "entry_price":  entry_price,
        "stop_loss":    stop_loss,
        "R":            R,
        "exit_date":    exit_date,
        "exit_price":   exit_price,
        "pnl_r":        pnl_r,
        "exit_reason":  exit_reason,
    }


# ── Build regime series from spy_nav.csv ──────────────────────────────────────
def _build_regime() -> pd.Series:
    spy_nav = pd.read_csv(_RESULTS / "spy_nav.csv", parse_dates=["date"], index_col="date")["spy_nav"]
    sma     = spy_nav.rolling(REGIME_SMA_WIN, min_periods=REGIME_SMA_WIN).mean()
    # Warmup period (sma NaN) → True (matches engine behavior: other=True)
    return (spy_nav > sma).where(sma.notna(), other=True)


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    # Load universe
    uni     = pd.read_csv(_UNI)
    tickers = uni["ticker"].tolist()
    # Add bear_exempt tickers that may not be in the universe
    for _t in BEAR_EXEMPT:
        if _t not in tickers:
            tickers.append(_t)

    # Load executed trades for marking
    trades    = pd.read_csv(_RESULTS / "trades.csv", parse_dates=["entry_date"])
    executed  = set(zip(trades["ticker"], trades["entry_date"].dt.normalize()))

    # Regime series
    regime = _build_regime()

    log.info("Loaded universe: %d tickers. Loading price data + computing indicators …", len(tickers))

    results = []
    missing = 0
    n_signals_total = 0

    for i, ticker in enumerate(tickers):
        if i % 200 == 0:
            log.info("  %d / %d tickers processed, %d signals so far",
                     i, len(tickers), n_signals_total)

        d = _load_ticker(ticker)
        if d is None:
            missing += 1
            continue

        idx_arr = d["index"]
        n = len(idx_arr)

        # Vectorised signal mask
        sig_mask = (
            d["breakout_sig"]
            & d["is_tradable"]
            & (d["raw_close"] >= MIN_PRICE)
            & ~np.isnan(d["adv"])   & (d["adv"] >= MIN_ADV_M)
            & ~np.isnan(d["atr"])   & (d["atr"] > 0)
        )
        # Stop distance
        prelim_stop = d["adj_close"] - STOP_MULT * d["atr"]
        with np.errstate(divide="ignore", invalid="ignore"):
            stop_dist = np.where(
                d["adj_close"] > 0,
                (d["adj_close"] - prelim_stop) / d["adj_close"],
                0.0,
            )
        sig_mask &= (stop_dist >= MIN_STOP_DIST)

        # Volume filter
        if VOL_MULT > 0:
            sig_mask &= (
                ~np.isnan(d["vol_ma"])
                & (d["vol_ma"] > 0)
                & (d["volume"] >= VOL_MULT * d["vol_ma"])
            )

        # Breakout strength filter (usually 0.0 so no-op)
        if BS_MIN > 0:
            sig_mask &= ~np.isnan(d["bs"]) & (d["bs"] >= 1.0 + BS_MIN)

        # Regime filter (align to ticker dates)
        if ticker not in BEAR_EXEMPT:
            regime_aligned = regime.reindex(
                pd.DatetimeIndex(idx_arr), method="ffill"
            ).fillna(True).values
            sig_mask &= regime_aligned

        signal_indices = np.where(sig_mask)[0]
        n_signals_total += len(signal_indices)

        for si in signal_indices:
            ts = idx_arr[si]
            ts_pd = pd.Timestamp(ts).normalize()

            # k_strength: (adj_close[t] - adj_close[t-1]) / adj_close[t-1]
            if si == 0:
                continue
            prev_ac = float(d["adj_close"][si - 1])
            curr_ac = float(d["adj_close"][si])
            if prev_ac == 0:
                continue
            k_strength = (curr_ac - prev_ac) / prev_ac * 100.0

            trade_info = _simulate_trade(d, si)

            # Match to executed trades using entry_date (t+1), not signal_date (t)
            sim_entry_date = None
            if not trade_info.get("gap_filtered", True) and "entry_date" in trade_info:
                sim_entry_date = pd.Timestamp(trade_info["entry_date"]).normalize()
            is_executed = (ticker, sim_entry_date) in executed if sim_entry_date else False

            row = {
                "ticker":       ticker,
                "signal_date":  ts_pd,
                "k_strength":   k_strength,
                "executed":     is_executed,
                "gap_filtered": trade_info.get("gap_filtered", False),
                "exit_reason":  trade_info.get("exit_reason", ""),
            }
            if not trade_info.get("gap_filtered", True):
                row.update({
                    "entry_date":  sim_entry_date,
                    "entry_price": trade_info["entry_price"],
                    "stop_loss":   trade_info["stop_loss"],
                    "R":           trade_info["R"],
                    "exit_date":   pd.Timestamp(trade_info["exit_date"]).normalize(),
                    "exit_price":  trade_info["exit_price"],
                    "pnl_r":       trade_info["pnl_r"],
                })
            results.append(row)

    log.info("Done. %d signals found across %d tickers (%d tickers missing price data).",
             n_signals_total, len(tickers) - missing, missing)

    out_df = pd.DataFrame(results)
    out_df.to_csv(_OUT, index=False)
    log.info("Saved → %s  (%d rows)", _OUT, len(out_df))

    # Quick summary
    tradeable = out_df[~out_df["gap_filtered"]]
    exec_df   = tradeable[tradeable["executed"]]
    non_exec  = tradeable[~tradeable["executed"]]
    log.info(
        "Tradeable (passed gap filter): %d total | %d executed | %d non-executed",
        len(tradeable), len(exec_df), len(non_exec),
    )
    if len(tradeable) > 0:
        from scipy.stats import pearsonr, spearmanr
        r_p, p_p = pearsonr(tradeable["k_strength"], tradeable["pnl_r"])
        r_s, p_s = spearmanr(tradeable["k_strength"], tradeable["pnl_r"])
        log.info("All signals  — Pearson r=%.4f (p=%.3f)  Spearman r=%.4f (p=%.3f)",
                 r_p, p_p, r_s, p_s)
    if len(exec_df) > 0:
        from scipy.stats import pearsonr, spearmanr
        r_p2, _ = pearsonr(exec_df["k_strength"], exec_df["pnl_r"])
        r_s2, _ = spearmanr(exec_df["k_strength"], exec_df["pnl_r"])
        log.info("Executed only — Pearson r=%.4f  Spearman r=%.4f", r_p2, r_s2)


if __name__ == "__main__":
    main()
