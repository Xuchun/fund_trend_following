#!/usr/bin/env python3
"""
IB Paper Trading Daily Script — Strategy 1.0
Runs after market close each trading day. Computes signals via Yahoo Finance,
then connects to IB TWS/Gateway (Paper Trading) to place orders.

Usage:
    python src/scripts/ib_paper_trading_daily.py [options]

Options:
    --date  YYYY-MM-DD   Override today's date (default: today)
    --host  HOST         IB TWS host (default: 127.0.0.1)
    --port  PORT         IB TWS paper port (default: 7497 for TWS, 4002 for Gateway)
    --client-id ID       IB client ID (default: 10, avoids conflict with manual TWS session)
    --dry-run            Compute signals but do NOT place orders (safe for testing)
    --no-entries         Skip new entry scanning (only process exits)

Prerequisites:
    1. pip install ib_insync yfinance
    2. IB TWS or Gateway must be running in Paper Trading mode
       TWS:     Enable API at File → Global Config → API → Settings
                Check "Enable ActiveX and Socket Clients", Socket port: 7497
                Check "Allow connections from localhost only" for safety
    3. The IB paper trading account should be reset to start with $200K
       TWS Paper Trading: right-click account → Reset Paper Trading Account
       (This sets the IB account value to $1M by default; our script tracks
        its OWN $200K NAV independently of the IB account balance)

State file: results/paper_trading/ib_state.json
    - Positions, stops, NAV history are stored here
    - Commit + push after each run to update the Streamlit monitor page
"""

import sys, json, argparse, logging, math
from pathlib import Path
from datetime import date, datetime, timezone

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pandas as pd
import yfinance as yf

from src.strategy.params import StrategyParams
from src.indicators.atr import compute_atr
from src.indicators.breakout import (
    compute_rolling_high,
    compute_breakout_signal,
    compute_breakout_strength,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_PT_DIR   = _root / "results" / "paper_trading"
_IB_STATE = _PT_DIR / "ib_state.json"
_UNIVERSE = _root / "data" / "tiingo_eligible_universe.csv"

PARAMS = StrategyParams()
INITIAL_CAPITAL = 200_000.0


# ── Rounding: 四舍五入 (round half up, not banker's rounding) ──────────────────

def round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


# ── State I/O ────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if not _IB_STATE.exists():
        raise FileNotFoundError(f"IB state not found: {_IB_STATE}")
    return json.loads(_IB_STATE.read_text())


def save_state(state: dict) -> None:
    _PT_DIR.mkdir(parents=True, exist_ok=True)
    _IB_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str))
    log.info(f"State saved → {_IB_STATE}")


# ── Yahoo Finance helpers ─────────────────────────────────────────────────────

def _fetch_batch(tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
    if not tickers:
        return {}
    try:
        raw = yf.download(tickers, period=period, auto_adjust=True, progress=False)
    except Exception as exc:
        log.warning(f"yfinance batch error: {exc}")
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
    elif len(tickers) == 1:
        df = raw.dropna(subset=["Close"])
        if not df.empty:
            out[tickers[0]] = df
    return out


def fetch_data(tickers: list[str], period: str = "300d", batch: int = 200) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    n = len(tickers)
    for i in range(0, n, batch):
        chunk = tickers[i : i + batch]
        log.info(f"  Fetching batch {i // batch + 1}/{math.ceil(n / batch)}: {len(chunk)} tickers")
        result.update(_fetch_batch(chunk, period))
    log.info(f"  Data ready: {len(result)}/{n}")
    return result


# ── ATR (Wilder) ──────────────────────────────────────────────────────────────

def wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    tr = pd.concat(
        [high - low,
         (high - close.shift(1)).abs(),
         (low  - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


# ── Trailing stop ─────────────────────────────────────────────────────────────

def _trail_mult(R: float) -> float:
    if R >= 3.0:
        return PARAMS.trail_multiplier_r5
    if R >= 1.0:
        return PARAMS.trail_multiplier_r3
    return PARAMS.trail_multiplier_r1


def compute_stop(pos: dict, df: pd.DataFrame) -> tuple[float, float, float]:
    """Returns (new_stop, peak_price, current_atr). Stop only ratchets up."""
    entry_dt = pd.to_datetime(pos["entry_date"])
    since    = df[df.index >= entry_dt]
    if since.empty:
        return pos["current_stop_loss"], pos["peak_price"], pos["atr_at_entry"]

    peak   = max(pos["peak_price"], float(since["High"].max()))
    atr_s  = wilder_atr(df["High"], df["Low"], df["Close"], PARAMS.atr_period)
    cur_atr = float(atr_s.iloc[-1])
    if pd.isna(cur_atr):
        cur_atr = pos["atr_at_entry"]

    cur_px = float(since["Close"].iloc[-1])
    risk   = pos["entry_price"] - pos["initial_stop_loss"]
    R      = (cur_px - pos["entry_price"]) / risk if risk > 0 else 0.0

    new_stop = peak - _trail_mult(R) * cur_atr
    stop     = max(pos["current_stop_loss"], new_stop)
    return stop, peak, cur_atr


# ── Regime ────────────────────────────────────────────────────────────────────

def is_bull(spy_df: pd.DataFrame) -> bool:
    if spy_df is None or len(spy_df) < PARAMS.regime_sma_window:
        return False
    sma = spy_df["Close"].rolling(PARAMS.regime_sma_window).mean().iloc[-1]
    return float(spy_df["Close"].iloc[-1]) > float(sma)


# ── Exit check ────────────────────────────────────────────────────────────────

def check_exits(
    state: dict,
    data: dict[str, pd.DataFrame],
    today: date,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Returns (updated_positions, new_closed_trades, exit_orders).
    A position exits if today's close ≤ trailing stop.
    Order type: MOO (Market-On-Open) for next trading day.
    """
    updated: list[dict] = []
    closed:  list[dict] = []
    orders:  list[dict] = []

    for pos in state["positions"]:
        ticker = pos["ticker"]
        df     = data.get(ticker)
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

        stop, peak, cur_atr = compute_stop(pos, df)

        # Check if stop breached (use low for intraday, close for confirmation)
        if low_px <= stop:
            # Exit — place MOO order for next open
            risk    = pos["entry_price"] - pos["initial_stop_loss"]
            R_est   = (close_px - pos["entry_price"]) / risk if risk > 0 else 0.0
            pnl_est = (close_px - pos["entry_price"]) * pos["shares"]

            orders.append({
                "ticker":     ticker,
                "action":     "SELL",
                "shares":     pos["shares"],
                "order_type": "MOO",
                "reason":     "trailing_stop",
                "stop_price": round(stop, 4),
                "signal_date": str(bar_date),
            })
            closed.append({
                "ticker":         ticker,
                "entry_date":     pos["entry_date"],
                "exit_date":      str(today),       # will be next open date
                "entry_price":    pos["entry_price"],
                "exit_price_est": round(close_px, 4),  # estimate; actual fill from IB
                "shares":         pos["shares"],
                "initial_stop":   pos["initial_stop_loss"],
                "exit_stop":      round(stop, 4),
                "pnl_r_est":      round(R_est, 4),
                "net_pnl_est":    round(pnl_est, 2),
                "exit_reason":    "trailing_stop",
                "holding_days":   (today - pd.to_datetime(pos["entry_date"]).date()).days,
            })
            state["cash"] = state.get("cash", 0.0) + pos["entry_price"] * pos["shares"] + pnl_est
            log.info(f"  EXIT  {ticker}  stop=${stop:.2f}  close=${close_px:.2f}  "
                     f"R≈{R_est:+.2f}  PnL≈${pnl_est:+,.0f}")
        else:
            updated.append({
                **pos,
                "current_stop_loss": round(stop, 6),
                "peak_price":        round(peak, 4),
                "last_known_price":  round(close_px, 4),
                "last_price_date":   str(bar_date),
            })

    return updated, closed, orders


# ── Entry scan ────────────────────────────────────────────────────────────────

def scan_entries(
    state: dict,
    universe_data: dict[str, pd.DataFrame],
    today: date,
    nav: float,
) -> tuple[list[dict], list[dict]]:
    """
    Returns (new_positions, entry_orders).
    Uses 四舍五入 (round half up) for share counts.
    """
    held      = {p["ticker"] for p in state["positions"]}
    heat_used = sum(
        (p["entry_price"] - p["initial_stop_loss"]) * p["shares"] / nav
        for p in state["positions"]
    )
    cash      = state.get("cash", 0.0)
    new_pos:  list[dict] = []
    orders:   list[dict] = []

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

        adv = (close * volume).rolling(60).mean().iloc[-1]
        if pd.isna(adv) or adv < PARAMS.min_adv_m * 1e6:
            continue

        rolling_high = compute_rolling_high(high, PARAMS.breakout_window)
        if not compute_breakout_signal(close, rolling_high).iloc[-1]:
            continue

        atr_s   = compute_atr(high, low, close, PARAMS.atr_period)
        cur_atr = float(atr_s.iloc[-1])
        if pd.isna(cur_atr) or cur_atr <= 0:
            continue

        entry_px  = float(close.iloc[-1])
        stop_px   = entry_px - PARAMS.stop_loss_multiplier * cur_atr
        stop_dist = entry_px - stop_px

        if stop_dist / entry_px < PARAMS.min_stop_distance_pct:
            continue

        if PARAMS.volume_filter_multiplier > 0:
            vol_ma = volume.rolling(60).mean().iloc[-1]
            if not pd.isna(vol_ma) and float(volume.iloc[-1]) < PARAMS.volume_filter_multiplier * float(vol_ma):
                continue

        # Position sizing: 四舍五入 (round half up)
        risk_dollars = nav * PARAMS.risk_per_trade
        raw_shares   = risk_dollars / stop_dist
        shares       = round_half_up(raw_shares)
        if shares <= 0:
            continue

        notional = entry_px * shares
        max_notional = nav * PARAMS.position_cap
        if notional > max_notional:
            shares   = round_half_up(max_notional / entry_px)
            notional = entry_px * shares

        trade_risk = stop_dist * shares / nav
        if heat_used + trade_risk > PARAMS.heat_limit:
            log.debug(f"  {ticker}: heat limit reached, skipping")
            continue
        if notional > cash:
            log.debug(f"  {ticker}: insufficient cash, skipping")
            continue

        strength = float(compute_breakout_strength(close, rolling_high).iloc[-1])

        new_pos.append({
            "ticker":            ticker,
            "entry_date":        str(today),         # intended entry (MOO = next open)
            "entry_price":       round(entry_px, 4),  # signal price; actual fill from IB
            "shares":            shares,
            "initial_stop_loss": round(stop_px, 6),
            "current_stop_loss": round(stop_px, 6),
            "peak_price":        round(entry_px, 4),
            "atr_at_entry":      round(cur_atr, 6),
            "R_at_entry":        0.0,
            "last_known_price":  round(entry_px, 4),
            "last_price_date":   str(today),
            "signal_strength":   round(strength, 4),
            "order_status":      "pending_moo",
        })
        orders.append({
            "ticker":     ticker,
            "action":     "BUY",
            "shares":     shares,
            "order_type": "MOO",
            "reason":     "breakout_signal",
            "signal_price": round(entry_px, 4),
            "stop_price":   round(stop_px, 4),
            "trade_risk":   round(trade_risk, 4),
            "signal_date":  str(today),
        })

        heat_used += trade_risk
        cash      -= notional
        log.info(f"  ENTRY {ticker}  signal=${entry_px:.2f}  stop=${stop_px:.2f}  "
                 f"shares={shares:,}  risk={trade_risk*100:.2f}%")

    # Sort by breakout strength
    combined = sorted(zip(new_pos, orders), key=lambda x: x[0]["signal_strength"], reverse=True)
    return [x[0] for x in combined], [x[1] for x in combined]


# ── IB order placement ────────────────────────────────────────────────────────

def place_orders_ib(
    orders: list[dict],
    host: str,
    port: int,
    client_id: int,
    dry_run: bool,
) -> list[dict]:
    """
    Connect to IB and place MOO orders. Returns list of order results.
    In dry_run mode, prints the orders but does NOT submit them.
    """
    if not orders:
        return []

    log.info(f"{'[DRY RUN] ' if dry_run else ''}Placing {len(orders)} orders via IB...")

    if dry_run:
        for o in orders:
            log.info(f"  [DRY RUN] {o['action']} {o['shares']} {o['ticker']} MOO  ({o['reason']})")
        return [{"dry_run": True, **o} for o in orders]

    try:
        from ib_insync import IB, Stock, Order, util
    except ImportError:
        log.error("ib_insync not installed. Run: pip install ib_insync")
        return []

    ib = IB()
    results: list[dict] = []
    try:
        log.info(f"  Connecting to IB at {host}:{port} (clientId={client_id})...")
        ib.connect(host, port, clientId=client_id, timeout=15)
        if not ib.isConnected():
            log.error("  IB connection failed.")
            return []
        log.info(f"  Connected. Account(s): {ib.managedAccounts()}")

        for o in orders:
            try:
                contract = Stock(o["ticker"], "SMART", "USD")
                ib.qualifyContracts(contract)

                # MOO = Market-On-Open, executes at next day's open
                ib_order = Order(
                    action=o["action"],
                    totalQuantity=o["shares"],
                    orderType="MOO",
                    tif="OPG",
                )
                trade = ib.placeOrder(contract, ib_order)
                ib.sleep(0.5)

                result = {
                    **o,
                    "order_id": trade.order.orderId,
                    "ib_status": trade.orderStatus.status,
                    "submitted_at": str(datetime.now()),
                }
                results.append(result)
                log.info(f"  ✅ {o['action']} {o['shares']} {o['ticker']} MOO "
                         f"→ orderId={trade.order.orderId}  status={trade.orderStatus.status}")
            except Exception as exc:
                log.error(f"  ❌ Failed to place order for {o['ticker']}: {exc}")
                results.append({**o, "error": str(exc), "submitted_at": str(datetime.now())})

    except Exception as exc:
        log.error(f"  IB error: {exc}")
    finally:
        if ib.isConnected():
            ib.disconnect()
            log.info("  Disconnected from IB.")

    return results


def get_ib_account_summary(host: str, port: int, client_id: int) -> dict:
    """Fetch account summary from IB. Returns dict of key metrics."""
    try:
        from ib_insync import IB
    except ImportError:
        return {}

    ib = IB()
    summary: dict = {}
    try:
        ib.connect(host, port, clientId=client_id + 1, timeout=10)
        if not ib.isConnected():
            return {}
        for s in ib.accountSummary():
            if s.tag in ("NetLiquidation", "AvailableFunds", "TotalCashValue",
                         "UnrealizedPnL", "RealizedPnL", "GrossPositionValue"):
                try:
                    summary[s.tag] = round(float(s.value), 2)
                except ValueError:
                    pass
    except Exception as exc:
        log.warning(f"  Could not fetch IB account summary: {exc}")
    finally:
        if ib.isConnected():
            ib.disconnect()
    return summary


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy 1.0 IB Paper Trading Daily Update")
    parser.add_argument("--date",         default=None, help="Trading date YYYY-MM-DD (default: today)")
    parser.add_argument("--host",         default="127.0.0.1", help="IB TWS host")
    parser.add_argument("--port",         default=7497, type=int, help="IB port (TWS=7497, Gateway=4002)")
    parser.add_argument("--client-id",    default=10, type=int, dest="client_id",
                        help="IB client ID (default: 10)")
    parser.add_argument("--dry-run",      action="store_true",
                        help="Compute signals but do NOT place orders")
    parser.add_argument("--no-entries",   action="store_true", help="Skip entry scanning")
    parser.add_argument("--univ-period",  default="310d", help="yfinance period for universe scan")
    args = parser.parse_args()

    today = date.fromisoformat(args.date) if args.date else date.today()
    mode  = "[DRY RUN] " if args.dry_run else ""
    log.info(f"=== {mode}Strategy 1.0 IB Paper Trading: {today} ===")

    # --- Load state ---
    state = load_state()
    log.info(f"  Open positions: {len(state['positions'])} | Cash: ${state.get('cash',0):,.0f} | NAV: ${state.get('nav',0):,.0f}")

    # --- Fetch Yahoo Finance data for positions ---
    pos_tickers = [p["ticker"] for p in state["positions"]]
    fetch_tickers = list(set(pos_tickers + ["SPY"]))
    log.info("--- Fetching position data (Yahoo Finance) ---")
    pos_data = fetch_data(fetch_tickers, period="300d")

    spy_df    = pos_data.get("SPY")
    regime_ok = is_bull(spy_df)
    spy_close = float(spy_df["Close"].iloc[-1]) if spy_df is not None and not spy_df.empty else None
    log.info(f"  Regime: {'BULL ✅' if regime_ok else 'BEAR 🚫'} | SPY: {f'${spy_close:.2f}' if spy_close else 'N/A'}")

    # --- Compute exits ---
    log.info("--- Computing exits ---")
    updated_positions, new_closed, exit_orders = check_exits(state, pos_data, today)
    state["positions"]    = updated_positions
    state["closed_trades"] = state.get("closed_trades", []) + new_closed
    log.info(f"  {len(new_closed)} exits | {len(updated_positions)} remaining")

    # --- Compute NAV estimate ---
    mkt_value   = sum(p.get("last_known_price", p["entry_price"]) * p["shares"]
                      for p in state["positions"])
    current_nav = mkt_value + state.get("cash", 0.0)
    state["nav"] = round(current_nav, 2)

    # --- Compute entries ---
    entry_orders: list[dict] = []
    new_positions: list[dict] = []

    if regime_ok and not args.no_entries:
        log.info("--- Scanning universe for entries (Yahoo Finance) ---")
        universe    = pd.read_csv(_UNIVERSE)
        active_tks  = universe[universe["is_active"] == True]["ticker"].tolist()
        univ_data   = fetch_data(active_tks, period=args.univ_period)
        new_positions, entry_orders = scan_entries(state, univ_data, today, current_nav)
        log.info(f"  {len(entry_orders)} entry signal(s)")
    elif not regime_ok:
        log.info("  BEAR regime — no new entries")

    # --- Place orders via IB ---
    all_orders = exit_orders + entry_orders
    order_results = place_orders_ib(all_orders, args.host, args.port, args.client_id, args.dry_run)

    # Update state with new positions
    if not args.dry_run:
        for pos in new_positions:
            if state.get("cash", 0.0) >= pos["entry_price"] * pos["shares"]:
                state["positions"].append(pos)
                state["cash"] = state.get("cash", 0.0) - pos["entry_price"] * pos["shares"]
    else:
        # In dry-run, still log what WOULD have been added
        for pos in new_positions:
            log.info(f"  [DRY RUN] Would open: {pos['ticker']} ×{pos['shares']} @ ${pos['entry_price']:.2f}")

    # --- Fetch IB account summary (optional, won't fail if IB is offline) ---
    if not args.dry_run:
        log.info("--- Fetching IB account summary ---")
        ib_summary = get_ib_account_summary(args.host, args.port, args.client_id)
        if ib_summary:
            state["account_summary"] = ib_summary
            log.info(f"  IB NetLiq: ${ib_summary.get('NetLiquidation', 0):,.0f}")

    # --- Update NAV history & metadata ---
    history = [h for h in state.get("nav_history", []) if h["date"] != str(today)]
    history.append({"date": str(today), "nav": round(current_nav, 2), "regime": "BULL" if regime_ok else "BEAR"})
    state["nav_history"]     = sorted(history, key=lambda x: x["date"])
    state["last_update_date"] = str(today)
    state["last_update_utc"]  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _today_sig = {
        "date":         str(today),
        "regime":       "BULL" if regime_ok else "BEAR",
        "spy_close":    spy_close,
        "n_candidates": len(entry_orders),
        "n_entries":    len(new_positions),
        "n_exits":      len(new_closed),
        "exits":        exit_orders,
        "entries":      entry_orders,
    }
    state["today_signals"] = _today_sig

    # Accumulate signals_history (never overwrites past days)
    _sig_hist = [s for s in state.get("signals_history", []) if s["date"] != str(today)]
    _sig_hist.append(_today_sig)
    state["signals_history"] = sorted(_sig_hist, key=lambda x: x["date"])

    # Append order results to history
    order_log = state.get("orders_history", [])
    order_log.extend(order_results)
    state["orders_history"] = order_log[-500:]  # keep last 500 orders

    save_state(state)

    # --- Final summary ---
    log.info("=== Summary ===")
    log.info(f"  Exits:       {len(new_closed)}")
    log.info(f"  Entries:     {len(new_positions)}")
    log.info(f"  Open:        {len(state['positions'])}")
    log.info(f"  Cash:        ${state.get('cash', 0):,.0f}")
    log.info(f"  NAV:         ${current_nav:,.0f}")
    log.info(f"  vs Initial:  {(current_nav / state['initial_capital'] - 1)*100:+.1f}%")

    if entry_orders:
        log.info("--- Entry signals (sorted by strength) ---")
        for o in entry_orders:
            log.info(f"  {o['ticker']:6s}  signal=${o['signal_price']:.2f}  stop=${o['stop_price']:.2f}  "
                     f"×{o['shares']}  risk={o['trade_risk']*100:.2f}%")


if __name__ == "__main__":
    main()
