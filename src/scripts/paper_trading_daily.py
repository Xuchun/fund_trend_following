#!/usr/bin/env python3
"""
Paper Trading Daily Update Script — Strategy 1.0
Usage:  python src/scripts/paper_trading_daily.py [--date YYYY-MM-DD] [--no-entries]

Run after market close each trading day to:
  1. Update trailing stops for all open positions
  2. Check for exits (stop breached)
  3. Scan universe for new entry signals (if regime is bullish)
  4. Save updated state → results/paper_trading/positions.json
  5. Append today's NAV to nav_history

Requirements:  yfinance >= 1.0,  pandas,  src/ on PYTHONPATH
"""

import sys, json, argparse, logging
from pathlib import Path
from datetime import date, datetime, timezone

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pandas as pd
import yfinance as yf

from src.strategy.params import StrategyParams
from src.indicators.atr import compute_atr
from src.indicators.breakout import compute_rolling_high, compute_breakout_signal, compute_breakout_strength

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_PT_DIR    = _root / "results" / "paper_trading"
_PT_STATE  = _PT_DIR / "positions.json"
_UNIVERSE  = _root / "data" / "tiingo_eligible_universe.csv"

PARAMS = StrategyParams()


# ── I/O ──────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if not _PT_STATE.exists():
        raise FileNotFoundError(f"State file not found: {_PT_STATE}\nRun initialization first.")
    return json.loads(_PT_STATE.read_text())


def save_state(state: dict) -> None:
    _PT_DIR.mkdir(parents=True, exist_ok=True)
    _PT_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str))
    log.info(f"State saved → {_PT_STATE}")


# ── Yahoo Finance helpers ─────────────────────────────────────────────────────

def _fetch_batch(tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
    """Download OHLCV for a batch and split into per-ticker DataFrames."""
    if not tickers:
        return {}
    try:
        raw = yf.download(tickers, period=period, auto_adjust=True, progress=False)
    except Exception as exc:
        log.warning(f"  yfinance download failed: {exc}")
        return {}
    if raw.empty:
        return {}

    out: dict[str, pd.DataFrame] = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for t in tickers:
            if t in raw.columns.get_level_values(1):
                df = raw.xs(t, level=1, axis=1).dropna(subset=["Close"])
                if not df.empty:
                    out[t] = df
    else:
        # Single-ticker download
        df = raw.dropna(subset=["Close"])
        if not df.empty and len(tickers) == 1:
            out[tickers[0]] = df
    return out


def fetch_price_data(tickers: list[str], period: str = "300d", batch_size: int = 200) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for many tickers in batches. Returns ticker → DataFrame."""
    result: dict[str, pd.DataFrame] = {}
    total = len(tickers)
    for i in range(0, total, batch_size):
        batch = tickers[i : i + batch_size]
        n_batch = (total - 1) // batch_size + 1
        log.info(f"  Batch {i // batch_size + 1}/{n_batch}: {len(batch)} tickers")
        result.update(_fetch_batch(batch, period))
    log.info(f"  Data loaded: {len(result)}/{total} tickers")
    return result


# ── Trailing stop ─────────────────────────────────────────────────────────────

def _trail_mult(R: float) -> float:
    if R >= 3.0:
        return PARAMS.trail_multiplier_r5
    if R >= 1.0:
        return PARAMS.trail_multiplier_r3
    return PARAMS.trail_multiplier_r1


def update_trailing_stop(pos: dict, df: pd.DataFrame) -> tuple[float, float, float]:
    """
    Returns (new_current_stop, new_peak_price, current_atr).
    Stop can only ratchet up, never down.
    """
    entry_date = pd.to_datetime(pos["entry_date"])
    since_entry = df[df.index >= entry_date]

    if since_entry.empty:
        return pos["current_stop_loss"], pos["peak_price"], pos["atr_at_entry"]

    peak_price = max(pos["peak_price"], float(since_entry["High"].max()))

    atr_s = compute_atr(df["High"], df["Low"], df["Close"], PARAMS.atr_period)
    cur_atr = float(atr_s.iloc[-1])
    if pd.isna(cur_atr):
        cur_atr = pos["atr_at_entry"]

    cur_price = float(since_entry["Close"].iloc[-1])
    risk = pos["entry_price"] - pos["initial_stop_loss"]
    R = (cur_price - pos["entry_price"]) / risk if risk > 0 else 0.0

    new_stop = peak_price - _trail_mult(R) * cur_atr
    current_stop = max(pos["current_stop_loss"], new_stop)

    return current_stop, peak_price, cur_atr


# ── Exit check ────────────────────────────────────────────────────────────────

def check_exits(
    state: dict,
    data: dict[str, pd.DataFrame],
    today: date,
) -> tuple[list[dict], list[dict]]:
    """
    Returns (updated_open_positions, new_closed_trades).
    A position exits if today's low <= current trailing stop.
    Exit price = max(stop, close) to handle gap-downs.
    """
    updated: list[dict] = []
    closed:  list[dict] = []

    for pos in state["positions"]:
        ticker = pos["ticker"]
        df = data.get(ticker)
        if df is None or df.empty:
            log.warning(f"  {ticker}: no data — keeping open")
            updated.append(pos)
            continue

        today_rows = df[df.index.date <= today].tail(1)
        if today_rows.empty:
            updated.append(pos)
            continue

        bar_date  = today_rows.index[0].date()
        close_px  = float(today_rows["Close"].iloc[0])
        low_px    = float(today_rows["Low"].iloc[0])

        current_stop, peak_price, cur_atr = update_trailing_stop(pos, df)

        if low_px <= current_stop:
            # Stop breached — exit at stop or close (gap-down protection)
            exit_px     = max(current_stop, close_px)
            risk        = pos["entry_price"] - pos["initial_stop_loss"]
            R           = (exit_px - pos["entry_price"]) / risk if risk > 0 else 0.0
            net_pnl     = (exit_px - pos["entry_price"]) * pos["shares"]

            closed.append({
                "ticker":        ticker,
                "entry_date":    pos["entry_date"],
                "exit_date":     str(bar_date),
                "entry_price":   pos["entry_price"],
                "exit_price":    round(exit_px, 4),
                "shares":        pos["shares"],
                "initial_stop":  pos["initial_stop_loss"],
                "final_stop":    round(current_stop, 4),
                "pnl_r":         round(R, 4),
                "net_pnl":       round(net_pnl, 2),
                "exit_reason":   "trailing_stop",
                "holding_days":  (bar_date - pd.to_datetime(pos["entry_date"]).date()).days,
            })
            state["cash"] = state.get("cash", 0.0) + pos["entry_price"] * pos["shares"] + net_pnl
            log.info(f"  EXIT  {ticker} @ ${exit_px:.2f}  R={R:+.2f}  PnL=${net_pnl:+,.0f}")
        else:
            updated.append({
                **pos,
                "current_stop_loss": round(current_stop, 6),
                "peak_price":        round(peak_price, 4),
                "last_known_price":  round(close_px, 4),
                "last_price_date":   str(bar_date),
            })

    return updated, closed


# ── Regime filter ─────────────────────────────────────────────────────────────

def is_bull_regime(spy_df: pd.DataFrame | None) -> bool:
    if spy_df is None or len(spy_df) < PARAMS.regime_sma_window:
        return False
    sma = spy_df["Close"].rolling(PARAMS.regime_sma_window).mean().iloc[-1]
    return float(spy_df["Close"].iloc[-1]) > float(sma)


# ── Entry scan ────────────────────────────────────────────────────────────────

def scan_entries(
    state: dict,
    universe_data: dict[str, pd.DataFrame],
    today: date,
    nav: float,
) -> list[dict]:
    """Scan universe for new breakout signals. Returns list of candidate signals."""
    held = {p["ticker"] for p in state["positions"]}
    heat_used = sum(
        (p["entry_price"] - p["initial_stop_loss"]) * p["shares"] / nav
        for p in state["positions"]
    )
    cash = state.get("cash", 0.0)
    signals: list[dict] = []

    for ticker, df in universe_data.items():
        if ticker in held:
            continue
        if len(df) < PARAMS.breakout_window + 5:
            continue

        today_df = df[df.index.date <= today]
        if today_df.empty:
            continue

        close  = today_df["Close"]
        high   = today_df["High"]
        low    = today_df["Low"]
        volume = today_df["Volume"]

        if float(close.iloc[-1]) < PARAMS.min_price:
            continue

        # ADV filter (60-day average dollar volume)
        adv = (close * volume).rolling(60).mean().iloc[-1]
        if pd.isna(adv) or adv < PARAMS.min_adv_m * 1e6:
            continue

        # Breakout signal
        rolling_high = compute_rolling_high(high, PARAMS.breakout_window)
        if not compute_breakout_signal(close, rolling_high).iloc[-1]:
            continue

        # ATR
        atr_s  = compute_atr(high, low, close, PARAMS.atr_period)
        cur_atr = float(atr_s.iloc[-1])
        if pd.isna(cur_atr) or cur_atr <= 0:
            continue

        entry_px  = float(close.iloc[-1])
        stop_px   = entry_px - PARAMS.stop_loss_multiplier * cur_atr
        stop_dist = entry_px - stop_px

        if stop_dist / entry_px < PARAMS.min_stop_distance_pct:
            continue

        # Volume confirmation
        if PARAMS.volume_filter_multiplier > 0:
            vol_ma = volume.rolling(60).mean().iloc[-1]
            if not pd.isna(vol_ma) and float(volume.iloc[-1]) < PARAMS.volume_filter_multiplier * float(vol_ma):
                continue

        # Position sizing
        risk_dollars = nav * PARAMS.risk_per_trade
        shares = int(risk_dollars / stop_dist)
        if shares <= 0:
            continue

        notional = entry_px * shares
        if notional / nav > PARAMS.position_cap:
            shares   = int(nav * PARAMS.position_cap / entry_px)
            notional = entry_px * shares

        trade_risk = stop_dist * shares / nav
        if heat_used + trade_risk > PARAMS.heat_limit:
            continue
        if notional > cash:
            continue

        strength = float(compute_breakout_strength(close, rolling_high).iloc[-1])
        signals.append({
            "ticker":     ticker,
            "entry_price": round(entry_px, 4),
            "stop_loss":   round(stop_px, 4),
            "shares":      shares,
            "atr":         round(cur_atr, 4),
            "strength":    round(strength, 4),
            "trade_risk":  round(trade_risk, 4),
            "notional":    round(notional, 2),
        })
        heat_used += trade_risk

    signals.sort(key=lambda x: x["strength"], reverse=True)
    return signals


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy 1.0 Paper Trading Daily Update")
    parser.add_argument("--date",             default=None,   help="Trading date YYYY-MM-DD (default: today)")
    parser.add_argument("--no-entries",       action="store_true", help="Skip new entry scanning")
    parser.add_argument("--universe-period",  default="310d", help="yfinance period string for universe download")
    args = parser.parse_args()

    today = date.fromisoformat(args.date) if args.date else date.today()
    log.info(f"=== Strategy 1.0 Paper Trading: {today} ===")

    state = load_state()
    log.info(f"  Open positions: {len(state['positions'])} | Cash: ${state.get('cash',0)/1e6:.2f}M")

    # --- Step 1: fetch data for open positions + SPY ---
    pos_tickers = [p["ticker"] for p in state["positions"]]
    log.info("--- Fetching position + SPY data ---")
    pos_data = fetch_price_data(list(set(pos_tickers + ["SPY"])), period="300d")

    spy_df     = pos_data.get("SPY")
    regime_ok  = is_bull_regime(spy_df)
    spy_close  = float(spy_df["Close"].iloc[-1]) if spy_df is not None and not spy_df.empty else None
    log.info(f"  Regime: {'BULL ✅' if regime_ok else 'BEAR 🚫'}  SPY close: {f'${spy_close:.2f}' if spy_close else 'N/A'}")

    # --- Step 2: exits & stop updates ---
    log.info("--- Checking exits ---")
    updated_positions, new_closed = check_exits(state, pos_data, today)
    state["positions"]    = updated_positions
    state["closed_trades"] = state.get("closed_trades", []) + new_closed
    log.info(f"  {len(new_closed)} exits | {len(updated_positions)} still open")

    # --- Step 3: NAV estimate after exits ---
    mkt_value = sum(
        p.get("last_known_price", p["entry_price"]) * p["shares"]
        for p in state["positions"]
    )
    current_nav = mkt_value + state.get("cash", 0.0)

    # --- Step 4: new entries ---
    candidates: list[dict] = []
    entries_executed: list[dict] = []
    if regime_ok and not args.no_entries:
        log.info("--- Scanning universe for new entries ---")
        universe   = pd.read_csv(_UNIVERSE)
        active     = universe[universe["is_active"] == True]["ticker"].tolist()
        univ_data  = fetch_price_data(active, period=args.universe_period)
        candidates = scan_entries(state, univ_data, today, current_nav)
        log.info(f"  Signals found: {len(candidates)}")

        for sig in candidates:
            if state.get("cash", 0.0) < sig["notional"]:
                log.info(f"  Skip {sig['ticker']}: insufficient cash")
                continue
            new_pos = {
                "ticker":            sig["ticker"],
                "entry_date":        str(today),
                "entry_price":       sig["entry_price"],
                "shares":            sig["shares"],
                "initial_stop_loss": sig["stop_loss"],
                "current_stop_loss": sig["stop_loss"],
                "peak_price":        sig["entry_price"],
                "atr_at_entry":      sig["atr"],
                "R_at_backtest_end": 0.0,
                "last_known_price":  sig["entry_price"],
                "last_price_date":   str(today),
            }
            state["positions"].append(new_pos)
            state["cash"] = state.get("cash", 0.0) - sig["notional"]
            entries_executed.append(sig)
            log.info(f"  ENTRY {sig['ticker']} @ ${sig['entry_price']:.2f}  "
                     f"stop=${sig['stop_loss']:.2f}  shares={sig['shares']:,}  "
                     f"risk={sig['trade_risk']*100:.2f}%")
    elif not regime_ok:
        log.info("  BEAR regime — no new entries")

    # --- Step 5: update metadata & NAV history ---
    history = [h for h in state.get("nav_history", []) if h["date"] != str(today)]
    history.append({"date": str(today), "nav": round(current_nav, 2), "regime": "BULL" if regime_ok else "BEAR"})
    state["nav_history"]     = sorted(history, key=lambda x: x["date"])
    state["last_update_date"] = str(today)
    state["last_update_utc"]  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- Step 6: save today's signals for website display ---
    _today_sig = {
        "date":         str(today),
        "regime":       "BULL" if regime_ok else "BEAR",
        "spy_close":    round(spy_close, 2) if spy_close else None,
        "n_candidates": len(candidates),
        "n_entries":    len(entries_executed),
        "n_exits":      len(new_closed),
        "exits": [{
            "ticker":     c["ticker"],
            "shares":     c["shares"],
            "stop_price": c["exit_price"],
            "order_type": "MARKET",
        } for c in new_closed],
        "entries": [{
            "ticker":       e["ticker"],
            "shares":       e["shares"],
            "signal_price": e["entry_price"],
            "stop_price":   e["stop_loss"],
            "trade_risk":   e["trade_risk"],
            "order_type":   "MARKET",
        } for e in entries_executed],
    }
    state["today_signals"] = _today_sig

    # --- Step 6b: accumulate signals_history (never overwrites past days) ---
    _sig_hist = [s for s in state.get("signals_history", []) if s["date"] != str(today)]
    _sig_hist.append(_today_sig)
    state["signals_history"] = sorted(_sig_hist, key=lambda x: x["date"])

    save_state(state)

    # --- Summary ---
    log.info("=== Done ===")
    log.info(f"  Exits:      {len(new_closed)}")
    log.info(f"  Entries:    {len(entries_executed)}")
    log.info(f"  Open:       {len(state['positions'])}")
    log.info(f"  Cash:       ${state.get('cash',0)/1e6:.2f}M")
    log.info(f"  NAV:        ${current_nav/1e6:.2f}M")
    log.info(f"  vs Initial: {(current_nav / state['initial_nav'] - 1)*100:+.1f}%")

    if entries_executed:
        log.info("--- New entries ---")
        for sig in entries_executed:
            log.info(f"  {sig['ticker']:6s}  entry=${sig['entry_price']:.2f}  stop=${sig['stop_loss']:.2f}  "
                     f"shares={sig['shares']:,}  notional=${sig['notional']/1e3:.0f}K")


if __name__ == "__main__":
    main()
