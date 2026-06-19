"""
compute_breakeven_scenarios.py — Breakeven protection scenario analysis

For each executed trade in the v1 backtest, re-simulates the exit under three
breakeven protection rules:
  - 1R:   if peak unrealized profit ≥ 1.0 × R, move trailing stop to be_stop_price
  - 1.5R: if peak unrealized profit ≥ 1.5 × R, move trailing stop to be_stop_price
  - 2R:   if peak unrealized profit ≥ 2.0 × R, move trailing stop to be_stop_price

where be_stop_price is set slightly above entry_price so that the net_pnl ≈ +$1 after
all costs (slippage + commissions), rather than exactly at entry_price which would yield
a small loss due to those costs.

All other strategy settings are unchanged.

Output: results/v1_unbiased_60m_2000/breakeven_scenarios.csv

Usage:
    python src/scripts/compute_breakeven_scenarios.py
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

_root    = Path(__file__).resolve().parents[2]
_RESULTS = _root / "results" / "v1_unbiased_60m_2000"
_PRICES  = _root / "data" / "cache" / "prices"
_OUT     = _RESULTS / "breakeven_scenarios.csv"

with open(_RESULTS / "strategy_meta.json") as _f:
    _meta = json.load(_f)
_P = _meta.get("params_anchor", _meta)

ATR_PERIOD     = int(_P["atr_period"])                    # 20
STOP_MULT      = float(_P["stop_loss_multiplier"])        # 2.0
TRAIL_R1       = float(_P["trail_multiplier_r1"])         # 3.0
TRAIL_R3       = float(_P["trail_multiplier_r3"])         # 3.0
TRAIL_R5       = float(_P["trail_multiplier_r5"])         # 5.0
SLIPPAGE_BPS   = float(_P["slippage_bps"])                # 10.0
COMMISSION_BPS = float(_P["commission_bps"])              # 3.0

BACKTEST_END       = pd.Timestamp("2026-06-15")
THRESHOLDS         = [1.0, 1.5, 2.0]
BE_LABELS          = ["be1r", "be15r", "be2r"]
TARGET_NET_PROFIT  = 1.0   # dollars; BE stop set so net_pnl ≈ +$1 after all costs
_ADJ               = 1.0 - SLIPPAGE_BPS / 10_000 - COMMISSION_BPS / 10_000


# ── Wilder ATR (vectorized) ───────────────────────────────────────────────────
def _wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20) -> np.ndarray:
    n = len(close)
    hl = high - low
    prev_c = np.roll(close, 1); prev_c[0] = close[0]
    hc = np.abs(high - prev_c)
    lc = np.abs(low  - prev_c)
    tr = np.maximum(np.maximum(hl, hc), lc)
    atr = np.full(n, np.nan)
    seed = 1 + period
    if seed > n:
        return atr
    atr[seed - 1] = np.mean(tr[1:seed])
    for i in range(seed, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


# ── Load adjusted price + ATR for one ticker ─────────────────────────────────
def _load_ticker(ticker: str) -> dict | None:
    f = _PRICES / f"{ticker}.parquet"
    if not f.exists():
        return None
    try:
        df = pd.read_parquet(f).sort_index()
    except Exception:
        return None
    af = df["adj_factor"].values.astype(float)
    ah = df["high"].values.astype(float)  * af
    al = df["low"].values.astype(float)   * af
    ac = df["close"].values.astype(float) * af
    ao = df["open"].values.astype(float)  * af
    return {
        "index":     np.array(df.index),
        "adj_open":  ao,
        "adj_high":  ah,
        "adj_low":   al,
        "adj_close": ac,
        "atr":       _wilder_atr(ah, al, ac, ATR_PERIOD),
    }


# ── Simulate one trade under one breakeven threshold ─────────────────────────
def _simulate_be(
    d: dict,
    entry_date: pd.Timestamp,
    entry_price: float,
    stop_loss: float,
    R: float,
    atr_at_entry: float,
    orig_exit_date: pd.Timestamp,
    orig_exit_reason: str,
    threshold: float,
) -> dict | None:
    """
    Returns dict:
        be_triggered  – True if the unrealized profit ever reached threshold × R
        exit_date     – None  if outcome is identical to original
        exit_price    – None  if outcome is identical to original
        exit_reason   – None  if outcome is identical to original
    Returns None if entry date not found in price data.
    """
    idx_arr = d["index"]
    n       = len(idx_arr)

    # Locate entry bar (exact match)
    entry_np = np.datetime64(entry_date, "ns")
    matches  = np.searchsorted(idx_arr, entry_np)
    if matches >= n or idx_arr[matches] != entry_np:
        return None
    entry_i = int(matches)

    # Determine loop upper bound (inclusive signal-day index)
    is_eob = (orig_exit_reason == "end_of_backtest")
    if is_eob:
        loop_end_i = n - 1
    else:
        orig_np = np.datetime64(orig_exit_date, "ns")
        exec_i  = int(np.searchsorted(idx_arr, orig_np))
        # signal day = the bar whose trigger caused execution at exec_i
        # exec_i is the execution open; the trigger fired on exec_i - 1
        loop_end_i = exec_i - 1
        if loop_end_i < entry_i:
            return None

    # Initial trail stop mirrors the backtest engine
    atr_eff = atr_at_entry if (not np.isnan(atr_at_entry) and atr_at_entry > 0) else R / STOP_MULT
    trail_stop   = entry_price - TRAIL_R1 * atr_eff
    highest_high = entry_price
    be_triggered = False

    for j in range(entry_i, loop_end_i + 1):
        # Cutoff at backtest end (relevant for EOB trades)
        day_ts = pd.Timestamp(idx_arr[j]).normalize()
        if day_ts > BACKTEST_END:
            break

        ah_j  = float(d["adj_high"][j])
        al_j  = float(d["adj_low"][j])
        ac_j  = float(d["adj_close"][j])
        atr_j = float(d["atr"][j])

        # Update highest_high first
        highest_high = max(highest_high, ah_j)

        # Update trailing stop (standard V1 ratchet)
        if not np.isnan(atr_j) and atr_j > 0:
            r_mult = (highest_high - entry_price) / R
            mult   = TRAIL_R5 if r_mult >= 3.0 else (TRAIL_R3 if r_mult >= 1.0 else TRAIL_R1)
            trail_stop = max(trail_stop, highest_high - mult * atr_j)

        # Check breakeven trigger
        if not be_triggered and (highest_high - entry_price) >= threshold * R:
            be_triggered = True

        # Apply breakeven floor to trail stop
        if be_triggered:
            trail_stop = max(trail_stop, entry_price)

        # Check exit conditions
        if al_j < stop_loss:
            next_i = j + 1
            if next_i < n:
                ep = float(d["adj_open"][next_i]) * (1.0 - SLIPPAGE_BPS / 10_000)
                ed = pd.Timestamp(idx_arr[next_i]).normalize()
            else:
                ep = ac_j * (1.0 - SLIPPAGE_BPS / 10_000)
                ed = day_ts
            return {"be_triggered": be_triggered, "exit_date": ed, "exit_price": ep, "exit_reason": "stop_loss"}

        elif ac_j < trail_stop:
            next_i = j + 1
            if next_i < n:
                ep = float(d["adj_open"][next_i]) * (1.0 - SLIPPAGE_BPS / 10_000)
                ed = pd.Timestamp(idx_arr[next_i]).normalize()
            else:
                ep = ac_j * (1.0 - SLIPPAGE_BPS / 10_000)
                ed = day_ts
            return {"be_triggered": be_triggered, "exit_date": ed, "exit_price": ep, "exit_reason": "trailing_stop"}

    # No early exit — same as original
    return {"be_triggered": be_triggered, "exit_date": None, "exit_price": None, "exit_reason": None}


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    trades = pd.read_csv(_RESULTS / "trades.csv",
                         parse_dates=["entry_date", "exit_date"])
    log.info("Loaded %d executed trades", len(trades))

    rows = []
    missing_data = 0
    tickers = trades["ticker"].unique()

    for i, ticker in enumerate(tickers):
        if i % 50 == 0:
            log.info("  %d / %d tickers processed", i, len(tickers))

        d = _load_ticker(ticker)
        ticker_trades = trades[trades["ticker"] == ticker]

        for _, tr in ticker_trades.iterrows():
            base = {
                "ticker":            ticker,
                "entry_date":        tr["entry_date"],
                "orig_exit_date":    tr["exit_date"],
                "orig_net_pnl":      tr["net_pnl"],
                "orig_exit_reason":  tr["exit_reason"],
                "shares":            tr["shares"],
                "entry_commission":  tr["entry_commission"],
                "entry_price":       tr["entry_price"],
                "stop_loss":         tr["stop_loss"],
                "R":                 tr["R"],
            }

            if d is None:
                missing_data += 1
                for lbl in BE_LABELS:
                    base[f"{lbl}_triggered"]  = False
                    base[f"{lbl}_exit_date"]  = pd.NaT
                    base[f"{lbl}_exit_price"] = np.nan
                    base[f"{lbl}_net_pnl"]    = np.nan
                    base[f"{lbl}_exit_reason"] = ""
                rows.append(base)
                continue

            for threshold, lbl in zip(THRESHOLDS, BE_LABELS):
                res = _simulate_be(
                    d,
                    tr["entry_date"].normalize(),
                    float(tr["entry_price"]),
                    float(tr["stop_loss"]),
                    float(tr["R"]),
                    float(tr["atr_at_entry"]),
                    tr["exit_date"].normalize(),
                    str(tr["exit_reason"]),
                    threshold,
                )

                if res is None or res["exit_date"] is None:
                    base[f"{lbl}_triggered"]   = res["be_triggered"] if res else False
                    base[f"{lbl}_exit_date"]   = pd.NaT
                    base[f"{lbl}_exit_price"]  = np.nan
                    base[f"{lbl}_net_pnl"]     = np.nan
                    base[f"{lbl}_exit_reason"] = ""
                else:
                    ep  = res["exit_price"]
                    qty = float(tr["shares"])
                    ec_exit = ep * qty * COMMISSION_BPS / 10_000
                    pnl_be  = (ep - float(tr["entry_price"])) * qty - float(tr["entry_commission"]) - ec_exit
                    base[f"{lbl}_triggered"]   = res["be_triggered"]
                    base[f"{lbl}_exit_date"]   = res["exit_date"]
                    base[f"{lbl}_exit_price"]  = ep
                    base[f"{lbl}_net_pnl"]     = pnl_be
                    base[f"{lbl}_exit_reason"] = res["exit_reason"]

            rows.append(base)

    out = pd.DataFrame(rows)
    out.to_csv(_OUT, index=False)
    log.info("Saved → %s  (%d rows, %d missing price data)", _OUT, len(out), missing_data)

    # Quick summary
    for threshold, lbl in zip(THRESHOLDS, BE_LABELS):
        n_trig   = int(out[f"{lbl}_triggered"].sum())
        n_change = int(out[f"{lbl}_exit_date"].notna().sum())
        log.info("  %s — triggered: %d  |  changed exit: %d", lbl, n_trig, n_change)


if __name__ == "__main__":
    main()
