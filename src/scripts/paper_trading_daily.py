#!/usr/bin/env python3
"""
Paper Trading Daily Update Script — Strategy 1.0
Usage:  python src/scripts/paper_trading_daily.py [--date YYYY-MM-DD] [--no-entries]

Run after market close each trading day. Mirrors the backtest engine loop exactly:

  ① Open  — execute yesterday's pending exits and entries at today's open price.
  ② Cash  — apply SGOV return to uninvested cash (mirrors backtest engine step ②).
  ③ Close — generate new exit/entry signals from today's close.
  ④ NAV   — record NAV after marking positions to close.

Signals generated on day T are executed on day T+1 (no look-ahead).

Requirements:  yfinance >= 1.0,  pandas,  src/ on PYTHONPATH
"""

import sys, os, json, argparse, logging, math, time
from pathlib import Path
from datetime import date, datetime, timezone, timedelta

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pandas as pd
import yfinance as yf

from src.strategy.params import StrategyParams
from src.indicators.atr import compute_atr
from src.indicators.breakout import compute_rolling_high, compute_breakout_signal, compute_breakout_strength
from src.indicators.correlation import compute_log_returns, compute_max_correlation

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


_REQUIRED_PENDING_FIELDS = {"ticker", "signal_price", "atr", "signal_date", "signal_strength"}

def validate_pending_entries(state: dict) -> None:
    """Raise ValueError if any pending_entry is missing required fields."""
    for entry in state.get("pending_entries", []):
        missing = _REQUIRED_PENDING_FIELDS - set(entry.keys())
        if missing:
            raise ValueError(
                f"pending_entry '{entry.get('ticker', '?')}' is missing required fields: {sorted(missing)}. "
                f"If this entry was manually added to positions.json, ensure all fields are present."
            )


# ── Yahoo Finance helpers ─────────────────────────────────────────────────────

def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a yfinance auto_adjust=False DataFrame.

    Returns a DataFrame where:
      Close     = dividend+split adjusted close  (for breakout/signal calculations)
      High/Low/Open = same adjustment factor applied  (for ATR, rolling_high, gap filter)
      Volume    = raw share volume (unchanged)
      Raw_Close = unadjusted close (for ADV and min_price filter, matching backtest)

    Matches the backtest's precompute.py / adv.py which uses:
      adj_close / adj_high for breakout_strength, but raw close for ADV dollar volume.
    """
    adj = df.get("Adj Close")
    if adj is None or adj.isna().all():
        df = df.copy()
        df["Raw_Close"] = df["Close"]
        return df

    raw_close = df["Close"].replace(0, float("nan"))
    factor    = adj / raw_close

    return pd.DataFrame({
        "Open":      df["Open"]  * factor,
        "High":      df["High"]  * factor,
        "Low":       df["Low"]   * factor,
        "Close":     adj,
        "Volume":    df["Volume"],
        "Raw_Close": df["Close"],
    }, index=df.index)


def _fetch_batch(tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
    """Download OHLCV for a batch and split into per-ticker DataFrames."""
    if not tickers:
        return {}
    try:
        raw = yf.download(tickers, period=period, auto_adjust=False, progress=False)
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
                    out[t] = _normalize_ohlcv(df)
    else:
        df = raw.dropna(subset=["Close"])
        if not df.empty and len(tickers) == 1:
            out[tickers[0]] = _normalize_ohlcv(df)
    return out


def fetch_price_data(tickers: list[str], period: str = "300d", batch_size: int = 200) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for many tickers in batches. Returns ticker → DataFrame.

    Missing tickers (silent rate-limit drops) are logged.  Callers that need
    retry behaviour should check the returned dict and schedule retries via
    pending_retry / --retry-mode rather than sleeping inline.
    """
    result: dict[str, pd.DataFrame] = {}
    total = len(tickers)
    for i in range(0, total, batch_size):
        batch = tickers[i : i + batch_size]
        n_batch = (total - 1) // batch_size + 1
        log.info(f"  Batch {i // batch_size + 1}/{n_batch}: {len(batch)} tickers")
        result.update(_fetch_batch(batch, period))
    n_loaded = len(result)
    log.info(f"  Data loaded: {n_loaded}/{total} tickers")
    if n_loaded < total:
        _missing = [t for t in tickers if t not in result]
        log.warning(f"  Missing ({len(_missing)}): {_missing}")
    return result


# ── Trailing stop ─────────────────────────────────────────────────────────────

def _trail_mult(r_multiple: float) -> float:
    """Select trail multiplier from R-multiple. Mirrors backtest exit.py."""
    if r_multiple >= 3.0:
        return PARAMS.trail_multiplier_r5
    if r_multiple >= 1.0:
        return PARAMS.trail_multiplier_r3
    return PARAMS.trail_multiplier_r1


def update_trail_stop(pos: dict, high: float, cur_atr: float) -> tuple[float, float]:
    """
    Update highest_high and trail_stop. Returns (new_trail_stop, new_highest_high).
    Exact mirror of backtest src/strategy/v1/exit.py update_trail_stop_v1.
    """
    highest_high = max(pos["highest_high"], high)

    R = pos["entry_price"] - pos["stop_loss"]   # slip-adjusted; R = 2×ATR at entry
    if R <= 0 or pd.isna(cur_atr) or cur_atr <= 0:
        return pos["trail_stop"], highest_high

    r_multiple = (highest_high - pos["entry_price"]) / R
    new_trail  = highest_high - _trail_mult(r_multiple) * cur_atr
    trail_stop = max(pos["trail_stop"], new_trail)

    return trail_stop, highest_high


# ── Phase ① OPEN: execute yesterday's pending exits ───────────────────────────

def execute_pending_exits(
    state: dict,
    data: dict[str, pd.DataFrame],
    today: date,
    regime: str = "UNKNOWN",
) -> tuple[list[dict], list[dict]]:
    """
    Execute pending exit signals at today's open price.

    Mirrors backtest engine.py step ① OPEN (_execute_exit):
      fill_price = adj_open × (1 − slippage_bps / 10_000)   [sell slippage]
      commission = fill_price × shares × commission_bps / 10_000
      cash recovered = fill_price × shares − commission

    If no open price is available, the exit is carried over to the next day
    (same retry logic as backtest: "no open price today; retry next day").

    Returns:
        (exits_executed, remaining_pending_exits)
    """
    exits_executed: list[dict] = []
    remaining:      list[dict] = []

    _pending = state.get("pending_exits", [])
    if not _pending:
        return [], []

    log.info(f"--- Executing {len(_pending)} pending exits at today's open ---")
    held_tickers = {p["ticker"] for p in state["positions"]}

    for sig in _pending:
        ticker = sig["ticker"]

        if ticker not in held_tickers:
            log.info(f"  SKIP EXIT {ticker}: no longer in positions")
            continue

        df = data.get(ticker)
        if df is None or df.empty:
            log.warning(f"  CARRY EXIT {ticker}: no data — retry next day")
            remaining.append(sig)
            continue

        today_rows = df[df.index.date == today]
        if today_rows.empty:
            log.warning(f"  CARRY EXIT {ticker}: no open for {today} — retry next day")
            remaining.append(sig)
            continue

        bar_date         = today_rows.index[0].date()
        open_px          = float(today_rows["Open"].iloc[0])
        fill_price       = open_px * (1.0 - PARAMS.slippage_bps / 10_000)    # sell slippage
        exit_commission  = fill_price * sig["shares"] * PARAMS.commission_bps / 10_000
        entry_commission = sig.get("entry_commission", 0.0)  # stored when position was opened

        # net_pnl: mirrors backtest TradeRecord.net_pnl = gross_pnl - entry_commission - exit_commission
        gross_pnl = (fill_price - sig["entry_price"]) * sig["shares"]
        net_pnl   = gross_pnl - entry_commission - exit_commission

        # pnl_r: mirrors backtest TradeRecord.pnl_r_multiple = (exit_price - entry_price) / R  (gross, no commissions)
        R     = sig["entry_price"] - sig["stop_loss"]
        pnl_r = (fill_price - sig["entry_price"]) / R if R > 0 else 0.0

        # Cash recovery: proceeds minus exit commission (mirrors backtest portfolio.close_position)
        state["cash"] = state.get("cash", 0.0) + fill_price * sig["shares"] - exit_commission

        # Remove from open positions
        state["positions"] = [p for p in state["positions"] if p["ticker"] != ticker]
        held_tickers.discard(ticker)

        closed_record = {
            "ticker":             ticker,
            "signal_date":        sig.get("signal_date", ""),
            "signal_price":       sig.get("signal_price", 0.0),
            "signal_strength":    sig.get("signal_strength", 0.0),  # breakout strength; needed for overfitting Section 七
            "entry_date":         sig.get("entry_date", ""),
            "exit_date":          str(bar_date),
            "open_price":         sig.get("open_price", sig["entry_price"]),
            "entry_price":        sig["entry_price"],
            "exit_open":          round(open_px, 4),            # raw T+1 open (reference)
            "exit_price":         round(fill_price, 4),         # fill after sell slippage
            "shares":             sig["shares"],
            "stop_loss":          sig["stop_loss"],
            "stop_used":          sig.get("stop_used", 0.0),
            "highest_high":       sig.get("highest_high", sig["entry_price"]),  # MFE proxy; needed for overfitting Section 八
            "lowest_low":         sig.get("lowest_low", sig["entry_price"]),    # MAE proxy
            "atr_at_entry":       sig.get("atr_at_entry", 0.0),
            "stop_distance_pct":  round(
                (sig["entry_price"] - sig["stop_loss"]) / sig["entry_price"], 6
            ) if sig["entry_price"] > 0 else 0.0,
            "trail_stop_at_exit": sig.get("trail_stop_at_exit", 0.0),
            "atr_at_exit":        sig.get("atr_at_exit", 0.0),
            "exit_commission":    round(exit_commission, 2),
            "entry_commission":   round(entry_commission, 2),
            "pnl_r":              round(pnl_r, 4),
            "net_pnl":            round(net_pnl, 2),
            "exit_reason":        sig["exit_reason"],
            "detected_date":      sig.get("detected_date", ""),
            "holding_days":       (bar_date - pd.to_datetime(sig.get("entry_date", str(bar_date))).date()).days,
            "entry_regime":       sig.get("entry_regime", ""),
            "exit_regime":        regime,
        }
        state["closed_trades"] = state.get("closed_trades", []) + [closed_record]
        exits_executed.append(closed_record)
        log.info(
            f"  EXIT EXECUTED {ticker} @ open=${open_px:.2f} fill=${fill_price:.2f} "
            f"R={pnl_r:+.2f} PnL=${net_pnl:+,.0f} exit_comm=${exit_commission:.2f} [{sig['exit_reason']}]"
        )

    return exits_executed, remaining


# ── Phase ① OPEN: execute yesterday's pending entries ────────────────────────

def execute_pending_entries(
    state: dict,
    data: dict[str, pd.DataFrame],
    today: date,
    regime: str = "UNKNOWN",
) -> list[dict]:
    """
    Execute pending entry signals at today's open price.

    Mirrors backtest engine.py step ① OPEN (_execute_entry):
      - Gap filter
      - Fill price = open × (1 + slippage_bps / 10_000)            [buy slippage]
      - Stop/trail recomputed from actual fill price (not signal price)
      - Position sizing RECOMPUTED at execution time with actual fill price,
        previous-day close NAV, and live portfolio heat — matches backtest
        compute_position_size() call inside _execute_entry()
      - commission = fill_price × shares × commission_bps / 10_000
      - cash deducted = fill_price × shares + commission             [matches backtest]
      - entry_commission stored in position dict for correct net_pnl at exit

    Returns:
        entries_executed
    """
    entries_executed: list[dict] = []
    _pending = state.get("pending_entries", [])
    if not _pending:
        state["pending_entries"] = []
        return []

    log.info(f"--- Executing {len(_pending)} pending entries at today's open ---")
    _held = {p["ticker"] for p in state["positions"]}

    # NAV for sizing = previous day's close NAV (mirrors backtest: last_nav = T-1 close NAV)
    _nav_hist   = state.get("nav_history", [])
    _sizing_nav = float(_nav_hist[-1]["nav"]) if _nav_hist else float(state.get("initial_nav", 200_000))
    if _sizing_nav <= 0:
        _sizing_nav = float(state.get("initial_nav", 200_000))

    # Pre-compute log returns for currently held positions (Step 3 correlation check)
    _held_log_returns: dict[str, pd.Series] = {}
    for ht in list(_held):
        hdf = data.get(ht)
        if hdf is not None and not hdf.empty:
            _held_log_returns[ht] = compute_log_returns(hdf["Close"])

    for sig in _pending:
        ticker = sig["ticker"]
        if ticker in _held:
            log.info(f"  SKIP {ticker}: already held")
            continue
        df = data.get(ticker)
        if df is None or df.empty:
            log.warning(f"  SKIP {ticker}: no price data")
            continue
        _today_rows = df[df.index.date == today]
        if _today_rows.empty:
            log.warning(f"  SKIP {ticker}: no data for {today}")
            continue

        open_px = float(_today_rows["Open"].iloc[0])

        # Gap filter — mirrors backtest execution.apply_gap_filter()
        _gap_pct = abs(open_px - sig["signal_price"]) / sig["signal_price"]
        if _gap_pct > PARAMS.gap_filter:
            log.info(f"  SKIP {ticker}: gap {_gap_pct*100:.1f}% > {PARAMS.gap_filter*100:.1f}% filter")
            continue

        # Fill price: buy slippage — mirrors backtest compute_fill_price(open, 'buy', slip)
        entry_px_slip = open_px * (1.0 + PARAMS.slippage_bps / 10_000)

        # Recompute stop/trail from actual fill price — mirrors backtest _execute_entry()
        if sig.get("atr") is None:
            log.error(f"  SKIP {ticker}: pending_entry missing 'atr' field — was this entry manually added without all required fields?")
            continue
        _atr     = float(sig["atr"])
        stop_px  = round(entry_px_slip - PARAMS.stop_loss_multiplier * _atr, 4)
        trail_px = round(entry_px_slip - PARAMS.trail_multiplier_r1  * _atr, 4)

        # Guard: degenerate stop — mirrors backtest _execute_entry() guard
        if stop_px >= entry_px_slip:
            log.info(f"  SKIP {ticker}: stop >= entry (degenerate ATR={_atr})")
            continue
        stop_dist_pct = (entry_px_slip - stop_px) / entry_px_slip
        if stop_dist_pct < PARAMS.min_stop_distance_pct:
            log.info(f"  SKIP {ticker}: stop dist {stop_dist_pct*100:.2f}% < min")
            continue

        # Recompute position sizing at execution time with actual fill price.
        # Mirrors backtest compute_position_size() called inside _execute_entry().
        stop_dist = entry_px_slip - stop_px

        # Step 1: raw shares from risk budget
        raw_shares_f   = (_sizing_nav * PARAMS.risk_per_trade) / stop_dist
        # Step 2: single-name cap (uses fill price, not signal price)
        cap_shares_f   = (_sizing_nav * PARAMS.position_cap) / entry_px_slip
        final_shares_f = min(raw_shares_f, cap_shares_f)

        # Step 3: correlation adjustment — use live held positions (updated each iteration)
        # as_of_date = signal_date (T-1, day of signal generation) — mirrors backtest which
        # passes signal.get("signal_date", date) to compute_position_size. Using the execution
        # date (T) would include T's close return, which isn't known at T's open.
        _held_list = list(_held)
        if _held_list:
            _cand_lr = compute_log_returns(df["Close"])
            _all_lr  = {**_held_log_returns, ticker: _cand_lr}
            max_corr, _corr_ticker = compute_max_correlation(
                new_ticker=ticker,
                current_positions=_held_list,
                log_returns=_all_lr,
                as_of_date=pd.Timestamp(sig.get("signal_date", str(today))),
                window=PARAMS.correlation_window,
                min_samples=40,
                return_ticker=True,
            )
            if max_corr > PARAMS.correlation_threshold:
                final_shares_f *= PARAMS.correlation_reduction

        shares = math.floor(final_shares_f + 0.5)
        if shares <= 0:
            log.info(f"  SKIP {ticker}: 0 shares after sizing")
            continue

        # Step 4: heat check against live portfolio state (post-exits + prior entries today).
        # Mirrors backtest: existing_risk = portfolio.existing_risk (updated after each execution).
        _existing_risk = sum(
            (p["entry_price"] - p["stop_loss"]) * p["shares"]
            for p in state["positions"]
        )
        _trade_risk = shares * stop_dist
        if (_existing_risk + _trade_risk) / _sizing_nav > PARAMS.heat_limit:
            log.info(f"  SKIP {ticker}: heat limit exceeded")
            continue

        # Commission — mirrors backtest compute_commission(entry_price, shares, bps)
        commission = entry_px_slip * shares * PARAMS.commission_bps / 10_000

        # Cash check — mirrors backtest: total_cost = shares × entry_price + commission
        _cash_needed = entry_px_slip * shares + commission
        if state.get("cash", 0.0) < _cash_needed:
            log.info(f"  SKIP {ticker}: insufficient cash (need ${_cash_needed:,.0f})")
            continue

        _trade_risk_pct = _trade_risk / _sizing_nav

        new_pos = {
            "ticker":            ticker,
            "signal_date":       sig.get("signal_date", ""),
            "signal_price":      sig["signal_price"],
            "signal_strength":   sig.get("signal_strength", sig.get("strength", 0.0)),   # breakout strength; flows to closed_trades
            "entry_date":        str(today),
            "open_price":        round(open_px, 4),          # raw T+1 open (reference)
            "entry_price":       round(entry_px_slip, 4),    # slip-adjusted fill (matches backtest)
            "shares":            shares,                      # recomputed at execution time
            "stop_loss":         stop_px,
            "trail_stop":        trail_px,
            "highest_high":      round(entry_px_slip, 4),    # init to entry_price (backtest convention)
            "lowest_low":        round(entry_px_slip, 4),    # MAE proxy: init to entry_price, falls each day
            "atr_at_entry":      _atr,
            "R_at_backtest_end": 0.0,
            "last_known_price":  round(open_px, 4),
            "last_price_date":   str(today),
            "entry_commission":  round(commission, 2),        # stored for correct net_pnl at exit
            "entry_regime":      regime,
        }
        state["positions"].append(new_pos)
        _held.add(ticker)
        # Update held log returns so subsequent entries' correlation check reflects this new position
        _held_log_returns[ticker] = compute_log_returns(df["Close"])
        # Deduct cash: fill_price × shares + commission (mirrors backtest open_position cost)
        state["cash"] = state.get("cash", 0.0) - _cash_needed

        entries_executed.append({
            **sig,
            "open_price":  round(open_px, 4),
            "entry_price": round(entry_px_slip, 4),
            "stop_price":  stop_px,
            "atr":         _atr,
            "shares":      shares,
            "commission":  round(commission, 2),
            "trade_risk":  round(_trade_risk_pct, 4),
        })
        log.info(
            f"  ENTRY EXECUTED {ticker} @ open=${open_px:.2f} fill=${entry_px_slip:.2f} "
            f"stop=${stop_px:.2f} trail=${trail_px:.2f} shares={shares} comm=${commission:.2f}"
        )

    state["pending_entries"] = []
    return entries_executed


# ── Phase ③ CLOSE: update trail stops, detect exit signals ───────────────────

def detect_exit_signals(
    state: dict,
    data: dict[str, pd.DataFrame],
    today: date,
) -> tuple[list[dict], list[dict]]:
    """
    Update trailing stops for all open positions and detect exit conditions.

    Mirrors backtest engine.py step ③ CLOSE (generate_exit_signals):
      - Always updates highest_high and trail_stop (even without exit)
      - Priority 1: low[t] < stop_loss   → "stop_loss"
      - Priority 2: close[t] < trail_stop → "trailing_stop"

    Does NOT execute exits. Returns signals to be executed at next day's open.

    Returns:
        (updated_open_positions, exit_signals_pending)
        Both exiting AND non-exiting positions are included in updated_open_positions
        (positions are removed only when the exit is executed the following day).
    """
    updated:      list[dict] = []
    exit_signals: list[dict] = []

    # Tickers already scheduled for exit — skip re-detection to avoid double signals
    already_pending = {s["ticker"] for s in state.get("pending_exits", [])}

    for pos in state["positions"]:
        ticker = pos["ticker"]

        if ticker in already_pending:
            updated.append(pos)
            continue

        df = data.get(ticker)
        if df is None or df.empty:
            log.warning(f"  {ticker}: no data — keeping open")
            updated.append(pos)
            continue

        today_rows = df[df.index.date <= today].tail(1)
        if today_rows.empty:
            updated.append(pos)
            continue

        bar_date = today_rows.index[0].date()
        high_px  = float(today_rows["High"].iloc[0])
        low_px   = float(today_rows["Low"].iloc[0])
        close_px = float(today_rows["Close"].iloc[0])

        # MAE tracking: lowest intraday low since entry.
        # Initialized to entry_price when position is opened; falls every day a new low is set.
        _prev_low = pos.get("lowest_low")
        if _prev_low is None:
            _prev_low = pos.get("entry_price", float("inf"))
        lowest_low = min(float(_prev_low), low_px)

        atr_s   = compute_atr(df["High"], df["Low"], df["Close"], PARAMS.atr_period)
        cur_atr = float(atr_s.iloc[-1])
        # Do NOT fall back to atr_at_entry when ATR is NaN — mirrors backtest
        # update_trail_stop_v1 which does `if isnan(atr): return` (skips update entirely).
        # update_trail_stop's own guard (pd.isna(cur_atr) → return) handles this correctly.

        # Always update trail stop first — mirrors backtest update_trail_stop_v1
        trail_stop, highest_high = update_trail_stop(pos, high_px, cur_atr)

        # Detect exit conditions — mirrors backtest check_exit_signals_v1
        exit_reason: str | None = None
        stop_used:   float      = 0.0
        if low_px < pos["stop_loss"]:           # Priority 1: intraday low vs hard stop
            exit_reason = "stop_loss"
            stop_used   = pos["stop_loss"]
        elif close_px < trail_stop:             # Priority 2: close vs trailing stop
            exit_reason = "trailing_stop"
            stop_used   = trail_stop

        # Always update position with new trail stop, regardless of exit
        updated.append({
            **pos,
            "trail_stop":       round(trail_stop, 6),
            "highest_high":     round(highest_high, 4),
            "lowest_low":       round(lowest_low, 4),
            "last_known_price": round(close_px, 4),
            "last_price_date":  str(bar_date),
        })

        if exit_reason:
            exit_signals.append({
                "ticker":           ticker,
                "exit_reason":      exit_reason,
                "stop_used":        round(stop_used, 4),
                "shares":           pos["shares"],
                "open_price":       pos.get("open_price", pos["entry_price"]),
                "entry_price":      pos["entry_price"],
                "entry_date":       pos.get("entry_date", ""),
                "signal_date":      pos.get("signal_date", ""),
                "signal_price":     pos.get("signal_price", 0.0),
                "signal_strength":  pos.get("signal_strength", 0.0),  # breakout strength at entry
                "stop_loss":        pos["stop_loss"],
                "atr_at_entry":     pos.get("atr_at_entry", 0.0),
                "highest_high":     round(highest_high, 4),  # MFE proxy at detection
                "lowest_low":       round(lowest_low, 4),    # MAE proxy at detection
                "trail_stop_at_exit": round(trail_stop, 6),  # trail level that triggered (or latest)
                "atr_at_exit":      round(cur_atr, 4),
                "detected_date":    str(bar_date),
                "entry_commission": pos.get("entry_commission", 0.0),  # for net_pnl at exit
                "entry_regime":     pos.get("entry_regime", ""),
            })
            log.info(f"  EXIT SIGNAL {ticker}  [{exit_reason}]  stop_used=${stop_used:.2f}")

    return updated, exit_signals


# ── Regime filter ─────────────────────────────────────────────────────────────

def is_bull_regime(spy_df: pd.DataFrame | None) -> bool:
    if not PARAMS.regime_filter_enabled:
        return True  # Regime filter disabled → always treat as bull (mirrors backtest engine)
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
    pos_data: dict[str, pd.DataFrame] | None = None,
) -> tuple[list[dict], dict]:
    """Scan universe for new breakout signals.

    Returns:
        (signals, scan_stats) where scan_stats contains rejection counters for
        overfitting analysis: how many raw breakouts existed vs. how many were
        blocked by portfolio-level constraints (heat, cash) or had size reduced
        by the correlation filter.
    """
    held         = {p["ticker"] for p in state["positions"]}
    held_tickers = [p["ticker"] for p in state["positions"]]
    # Exclude pending_exits from heat_used — mirrors backtest where exits execute
    # BEFORE entries at T+1 open, so their heat is already freed by the time the
    # entry heat-check runs. Including them would over-count heat and block signals
    # that the backtest would accept.
    _pending_exit_tks = {e["ticker"] for e in state.get("pending_exits", [])}
    heat_used    = sum(
        (p["entry_price"] - p["stop_loss"]) * p["shares"] / nav
        for p in state["positions"]
        if p["ticker"] not in _pending_exit_tks
    )
    signals: list[dict] = []

    # Rejection counters — stored in today_signals for future overfitting analysis
    n_raw_breakouts      = 0   # passed all per-stock filters; before portfolio constraints
    n_corr_reduced       = 0   # correlation triggered size reduction (signal still accepted)
    n_heat_blocked       = 0   # blocked by portfolio heat limit
    n_price_filtered     = 0   # filtered by min_price
    n_adv_filtered       = 0   # filtered by ADV₆₀
    n_breakout_filtered  = 0   # no 200-day breakout signal
    n_atr_filtered       = 0   # ATR invalid or zero
    n_stop_dist_filtered = 0   # stop distance too small (< min_stop_distance_pct)
    n_volume_filtered    = 0   # volume below 1.5× 60-day average
    # Note: no cash pre-filtering at signal time (mirrors backtest). Cash is checked
    # at T+1 execution so gap-filter failures free cash for the next signal in line.

    # Full candidate list (all raw breakouts with per-candidate rejection reason)
    # "四、今日开平仓信号" displays this so the user sees the full funnel, not just approved ones.
    all_raw_candidates: list[dict] = []

    # Pre-compute log returns for held positions (for Step 3 correlation check)
    held_log_returns: dict[str, pd.Series] = {}
    if pos_data and held_tickers:
        for ht in held_tickers:
            hdf = pos_data.get(ht)
            if hdf is not None and not hdf.empty:
                held_log_returns[ht] = compute_log_returns(hdf["Close"])

    # ── Phase 1: apply all per-stock filters, collect pre-candidates ─────────
    # Heat check is deferred to Phase 2 so candidates are sorted by strength first.
    # This ensures the heat budget is allocated to the strongest breakouts, not
    # whichever ticker happens to appear first in the universe dict.
    pre_candidates: list[dict] = []

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

        # Min-price filter uses Raw_Close (unadjusted) — mirrors backtest entry.py row["close"]
        if float(today_df["Raw_Close"].iloc[-1]) < PARAMS.min_price:
            n_price_filtered += 1
            continue

        # ADV filter — Raw_Close (unadjusted) × volume, shift(1), no look-ahead bias.
        # Mirrors backtest: compute_adv_from_ohlcv(df["close"], volume) uses raw close.
        adv = (today_df["Raw_Close"] * volume).shift(1).rolling(60).mean().iloc[-1]
        if pd.isna(adv) or adv < PARAMS.min_adv_m * 1e6:
            n_adv_filtered += 1
            continue

        # Breakout signal — mirrors backtest entry.py
        rolling_high = compute_rolling_high(high, PARAMS.breakout_window)
        if not compute_breakout_signal(close, rolling_high).iloc[-1]:
            n_breakout_filtered += 1
            continue

        # ATR
        atr_s   = compute_atr(high, low, close, PARAMS.atr_period)
        cur_atr = float(atr_s.iloc[-1])
        if pd.isna(cur_atr) or cur_atr <= 0:
            n_atr_filtered += 1
            continue

        entry_px  = float(close.iloc[-1])
        stop_px   = entry_px - PARAMS.stop_loss_multiplier * cur_atr
        stop_dist = entry_px - stop_px

        if stop_dist / entry_px < PARAMS.min_stop_distance_pct:
            n_stop_dist_filtered += 1
            continue

        # Volume confirmation — shift(1) mirrors backtest indicators/adv.py compute_volume_ma:
        # volume_ma[t] = mean(volume[t-60:t-1]), excludes today
        # Always compute _vol_ma so vol_ratio is available for overfitting analysis.
        _vol_ma = volume.shift(1).rolling(60).mean().iloc[-1]
        if PARAMS.volume_filter_multiplier > 0:
            if not pd.isna(_vol_ma) and float(volume.iloc[-1]) < PARAMS.volume_filter_multiplier * float(_vol_ma):
                n_volume_filtered += 1
                continue

        # ── All per-stock filters passed — count as a raw breakout candidate ──
        n_raw_breakouts += 1

        # Position sizing — mirrors backtest sizing.py compute_position_size():

        # Step 1: raw shares from risk budget (keep float until final rounding)
        raw_shares_f = (nav * PARAMS.risk_per_trade) / stop_dist

        # Step 2: single-name cap
        cap_shares_f   = (nav * PARAMS.position_cap) / entry_px
        final_shares_f = min(raw_shares_f, cap_shares_f)

        # Step 3: correlation adjustment
        _corr_triggered = False
        _corr_with_ticker = None
        if held_log_returns:
            _cand_lr = compute_log_returns(close)
            _all_lr  = {**held_log_returns, ticker: _cand_lr}
            max_corr, _corr_with_ticker = compute_max_correlation(
                new_ticker=ticker,
                current_positions=held_tickers,
                log_returns=_all_lr,
                as_of_date=pd.Timestamp(today),
                window=PARAMS.correlation_window,
                min_samples=40,
                return_ticker=True,
            )
            if max_corr > PARAMS.correlation_threshold:
                final_shares_f *= PARAMS.correlation_reduction
                _corr_triggered = True

        # Round once with round-half-up — mirrors math.floor(final_shares + 0.5) in backtest
        shares = math.floor(final_shares_f + 0.5)
        if shares <= 0:
            continue

        notional  = entry_px * shares
        trade_risk = stop_dist * shares / nav
        strength   = float(compute_breakout_strength(close, rolling_high).iloc[-1])

        _vol_ratio = (
            float(volume.iloc[-1]) / float(_vol_ma)
            if not pd.isna(_vol_ma) and float(_vol_ma) > 0 else None
        )
        pre_candidates.append({
            "ticker":              ticker,
            "entry_px":            entry_px,
            "stop_px":             stop_px,
            "stop_dist":           stop_dist,
            "shares":              shares,
            "cur_atr":             cur_atr,
            "notional":            notional,
            "trade_risk":          trade_risk,
            "strength":            strength,
            "_corr_triggered":     _corr_triggered,
            "_corr_with":          _corr_with_ticker,
            "stop_distance_pct":   stop_dist / entry_px,
            "atr_pct":             cur_atr / entry_px,
            "adv60_m":             adv / 1e6,
            "vol_ratio":           _vol_ratio,
        })

    # ── Phase 2: sort by breakout strength, then apply heat check ─────────────
    pre_candidates.sort(key=lambda x: x["strength"], reverse=True)

    for cand in pre_candidates:
        ticker            = cand["ticker"]
        entry_px          = cand["entry_px"]
        stop_px           = cand["stop_px"]
        shares            = cand["shares"]
        cur_atr           = cand["cur_atr"]
        notional          = cand["notional"]
        trade_risk        = cand["trade_risk"]
        strength          = cand["strength"]
        _corr_triggered   = cand["_corr_triggered"]
        _corr_with_ticker = cand["_corr_with"]

        # Step 4: portfolio heat check (applied in strength order)
        if heat_used + trade_risk > PARAMS.heat_limit:
            n_heat_blocked += 1
            all_raw_candidates.append({
                "ticker":            ticker,
                "signal_price":      round(entry_px, 4),
                "stop_price":        round(stop_px, 4),
                "shares":            shares,
                "trade_risk":        round(trade_risk, 4),
                "strength":          round(strength, 4),
                "rejection":         "heat_limit",
                "stop_distance_pct": round(cand.get("stop_distance_pct", 0), 6),
                "atr_pct":           round(cand.get("atr_pct", 0), 6),
                "adv60_m":           round(cand.get("adv60_m", 0), 3),
                "vol_ratio":         round(cand["vol_ratio"], 4) if cand.get("vol_ratio") is not None else None,
            })
            continue

        if _corr_triggered:
            n_corr_reduced += 1

        signals.append({
            "ticker":       ticker,
            "signal_price": round(entry_px, 4),
            "stop_loss":    round(stop_px, 4),
            "shares":       shares,
            "atr":          round(cur_atr, 4),
            "strength":     round(strength, 4),
            "trade_risk":   round(trade_risk, 4),
            "notional":     round(notional, 2),
        })
        all_raw_candidates.append({
            "ticker":            ticker,
            "signal_price":      round(entry_px, 4),
            "stop_price":        round(stop_px, 4),
            "shares":            shares,
            "trade_risk":        round(trade_risk, 4),
            "strength":          round(strength, 4),
            "rejection":         "corr_reduced" if _corr_triggered else None,
            "corr_with":         _corr_with_ticker if _corr_triggered else None,
            "stop_distance_pct": round(cand.get("stop_distance_pct", 0), 6),
            "atr_pct":           round(cand.get("atr_pct", 0), 6),
            "adv60_m":           round(cand.get("adv60_m", 0), 3),
            "vol_ratio":         round(cand["vol_ratio"], 4) if cand.get("vol_ratio") is not None else None,
        })
        heat_used += trade_risk

    # signals is already in strength order (pre_candidates was sorted by strength)
    scan_stats = {
        "n_raw_breakouts":     n_raw_breakouts,
        "n_heat_blocked":      n_heat_blocked,
        "n_corr_reduced":      n_corr_reduced,
        "n_price_filtered":    n_price_filtered,
        "n_adv_filtered":      n_adv_filtered,
        "n_breakout_filtered": n_breakout_filtered,
        "n_atr_filtered":      n_atr_filtered,
        "n_stop_dist_filtered": n_stop_dist_filtered,
        "n_volume_filtered":   n_volume_filtered,
        "all_raw_candidates":  all_raw_candidates,   # full funnel; displayed in 四
    }
    return signals, scan_stats


# ── Daily summary generation ─────────────────────────────────────────────────

# Sector → representative ETF (for broader sector news context)
_SECTOR_ETF = {
    "Technology":             "SMH",   # semiconductors dominate our tech holdings
    "Industrials":            "XLI",
    "Healthcare":             "XLV",
    "Financial Services":     "XLF",
    "Consumer Cyclical":      "XLY",
    "Communication Services": "XLC",
    "Energy":                 "XLE",
    "Utilities":              "XLU",
    "Basic Materials":        "XLB",
    "Real Estate":            "XLRE",
}


def _check_url(url: str, timeout: int = 6) -> bool:
    """返回 True 表示 URL 可正常访问（HTTP 2xx/3xx）。"""
    if not url or not url.startswith("http"):
        return False
    try:
        import urllib.request
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status < 400
    except Exception:
        return False


def _fetch_market_news(
    tickers: list[str],
    sector: str,
    trade_date: date,
    max_items: int = 3,
) -> list[dict]:
    """抓取 Yahoo Finance 新闻，仅返回 trade_date 当天（含次日）且 URL 可访问的条目。
    兼容 yfinance 新 API（字段在 item['content'] 中）和旧 API（字段在 item 顶层）。
    """
    date_lo = trade_date
    date_hi = trade_date + timedelta(days=1)

    def _parse_item(item: dict) -> tuple[str, str, str, date | None]:
        """返回 (title, url, summary, pub_date)。"""
        content = item.get("content") or item
        title   = (content.get("title") or "").strip()
        summary = (content.get("summary") or content.get("description") or "").strip()
        url = (
            content.get("previewUrl")
            or (content.get("canonicalUrl") or {}).get("url")
            or content.get("link")
            or ""
        )
        pub_date = None
        pub_raw = content.get("pubDate") or content.get("displayTime")
        if pub_raw:
            try:
                pub_date = datetime.fromisoformat(pub_raw.replace("Z", "+00:00")).date()
            except Exception:
                pass
        else:
            ts = item.get("providerPublishTime")
            if ts:
                try:
                    pub_date = datetime.fromtimestamp(int(ts)).date()
                except Exception:
                    pass
        return title, url, summary, pub_date

    etf = _SECTOR_ETF.get(sector)
    search_tickers = ([etf] if etf else []) + list(tickers)[:3]

    seen: set[str] = set()
    results: list[dict] = []
    for t in search_tickers:
        if len(results) >= max_items:
            break
        try:
            for item in (yf.Ticker(t).news or [])[:10]:
                title, url, summary, pub_date = _parse_item(item)
                if not title or title in seen:
                    continue
                if pub_date and date_lo <= pub_date <= date_hi:
                    if not _check_url(url):
                        log.info(f"    Skipping inaccessible URL: {url[:60]}")
                        continue
                    seen.add(title)
                    results.append({
                        "title":    title,
                        "url":      url,
                        "summary":  summary,
                        "pub_date": str(pub_date),
                    })
                    if len(results) >= max_items:
                        break
        except Exception:
            continue
    return results


def _summarize_news_with_claude(
    news_items: list[dict],
    sector: str,
    direction: str,
    nav_chg_pct: float,
    spy_chg_pct: float,
    movers: "list[tuple[str, float, float, str]] | None" = None,
) -> list[str]:
    """调用 Claude Haiku 把当日新闻综合为解释净值vs SPY分歧的 bullet points。
    返回 bullet 字符串列表（不含前缀符号），失败时返回空列表。
    若 ANTHROPIC_API_KEY 未配置或调用失败，返回空列表。
    """
    try:
        import anthropic
        client = anthropic.Anthropic()

        news_text = "\n\n".join(
            f"[{i+1}] 标题：{n['title']}\n    摘要：{n['summary'] or '（无摘要）'}"
            for i, n in enumerate(news_items[:5])
        )

        # 构建持仓涨跌明细（按美元影响排序，最多10个）
        vs_spy = nav_chg_pct - spy_chg_pct
        movers_text = ""
        if movers:
            _sorted_movers = sorted(movers, key=lambda x: x[2])  # 按美元涨跌升序（跌幅最大在前）
            _top = _sorted_movers[:5] + _sorted_movers[-3:]       # 跌幅最大5个 + 涨幅最大3个
            _seen = set()
            _lines = []
            for tk, pct, dol, sec in _top:
                if tk in _seen:
                    continue
                _seen.add(tk)
                _lines.append(f"  - {tk}（{sec}）：{pct:+.1f}%，对净值影响 ${dol:+,.0f}")
            movers_text = "今日持仓涨跌明细（对净值影响最大的标的）：\n" + "\n".join(_lines) + "\n\n"

        _diverge_note = ""
        if abs(vs_spy) >= 1.5:
            _diverge_note = (
                f"【重要】净值与 SPY 偏差达 {vs_spy:+.2f}%，属于显著分歧。"
                f"分析中必须明确点名造成偏差的具体持仓标的（写出 ticker 代码），"
                f"并说明它们今日的涨跌幅（上方明细中有数据），不得只泛泛说'某板块'。\n"
            )

        prompt = (
            f"以下是 Yahoo Finance 今日（交易日当天）关于 {sector} 板块的新闻（已编号）：\n\n"
            f"{news_text}\n\n"
            f"背景：今日策略净值变化 {nav_chg_pct:+.2f}%，SPY 变化 {spy_chg_pct:+.2f}%，"
            f"策略净值 vs SPY 偏差 {vs_spy:+.2f}%。\n"
            f"策略重仓 {sector} 板块，因此净值与 SPY 出现了分歧。\n\n"
            f"{movers_text}"
            f"{_diverge_note}\n"
            f"任务：基于以上新闻内容，写 3-4 条简体中文分析，解释：\n"
            f"① {sector} 板块今日为何{direction}（背后的驱动逻辑，不是事件描述）\n"
            f"② 为什么这导致策略净值与 SPY 出现分歧\n\n"
            f"要求：\n"
            f"- 分析因果逻辑（为什么），不要只复述标题说了什么\n"
            f"- 如净值与大盘偏差显著（|偏差| ≥ 1.5%），必须在分析中具体指出是哪些持仓标的（ticker代码）拉开了差距，以及它们各自的涨跌幅\n"
            f"- 每条一句话，句末用 [来源N] 标注所依据的新闻编号，如 [来源1] 或 [来源1,2]\n"
            f"- 直接输出文字，不要以 - 或 * 或数字开头\n"
            f"- 用换行分隔各条，只输出中文分析内容，不要任何其他文字"
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        bullets = [line.strip().lstrip("-•*· 0123456789.）)") for line in raw.split("\n") if line.strip()]
        bullets = [b for b in bullets if b]

        # 把 [来源N] 替换为实际 markdown 链接
        import re as _re
        def _replace_citations(bullet):
            def _sub(m):
                parts = [int(x.strip()) - 1 for x in m.group(1).split(",")]
                links = []
                for idx in parts:
                    if 0 <= idx < len(news_items):
                        n = news_items[idx]
                        title = (n["title"][:28] + "…") if len(n["title"]) > 28 else n["title"]
                        links.append(f"[{title}]({n['url']})" if n.get("url") else f"《{title}》")
                return "（" + "、".join(links) + "）" if links else ""
            return _re.sub(r"\[来源([\d,\s]+)\]", _sub, bullet)

        return [_replace_citations(b) for b in bullets]
    except Exception as e:
        log.warning(f"  Claude news summarize failed: {e}")
        return []


def _gen_daily_summary(
    today: date,
    current_nav: float,
    prev_nav: float | None,
    spy_close: float | None,
    prev_spy: float | None,
    positions: list[dict],
    prev_prices: dict[str, float],
    exits_executed: list[dict],
    entries_executed: list[dict],
    new_exit_signals: list[dict],
) -> dict:
    """生成每日交易日小结（分析性解释，非统计数字罗列），存入 positions.json 供网页展示。"""
    nav_chg_pct = (current_nav / prev_nav - 1) * 100 if prev_nav else 0.0
    spy_chg_pct = (spy_close / prev_spy - 1) * 100 if (spy_close and prev_spy) else 0.0
    vs_spy      = nav_chg_pct - spy_chg_pct

    # 持仓逐个当日涨跌
    movers: list[tuple[str, float, float, str]] = []   # (ticker, pct, dollar, sector)
    sector_pnl:  dict[str, float] = {}
    sector_nav:  dict[str, float] = {}   # sector → 市值（用于计算权重）
    for p in positions:
        t        = p["ticker"]
        curr_px  = p.get("last_known_price", p["entry_price"])
        prev_px  = prev_prices.get(t)
        mkt_val  = curr_px * p["shares"]
        sec      = p.get("sector", "N/A")
        sector_nav[sec] = sector_nav.get(sec, 0.0) + mkt_val
        if prev_px is None or prev_px <= 0:
            continue
        dollar_chg = (curr_px - prev_px) * p["shares"]
        pct_chg    = (curr_px / prev_px - 1) * 100
        movers.append((t, pct_chg, dollar_chg, sec))
        sector_pnl[sec] = sector_pnl.get(sec, 0.0) + dollar_chg

    movers.sort(key=lambda x: x[2])   # 按美元涨跌排序
    total_mkt = sum(sector_nav.values()) or 1.0

    bullets: list[str] = []

    # ── 确定关注板块（影响最大的板块） ──────────────────────────────────────────
    focus_sec: str | None = None
    focus_tickers: list[str] = []
    _direction = "下跌"
    if sector_pnl:
        if vs_spy < 0:
            focus_sec     = min(sector_pnl, key=sector_pnl.get)
            focus_tickers = [t for t, _, _, s in movers if s == focus_sec][:3]
            _direction    = "下跌"
        else:
            focus_sec     = max(sector_pnl, key=sector_pnl.get)
            focus_tickers = [t for t, _, _, s in movers[::-1] if s == focus_sec][:3]
            _direction    = "上涨"

    # ── 抓取当日新闻并用 Claude 生成所有 bullet points ───────────────────────
    news_items: list[dict] = []
    if focus_sec:
        log.info(f"  Fetching today's news for sector={focus_sec}, tickers={focus_tickers}")
        news_items = _fetch_market_news(focus_tickers, focus_sec, today, max_items=5)

    if news_items:
        log.info(f"  Found {len(news_items)} news items, calling Claude for bullet points …")
        _claude_bullets = _summarize_news_with_claude(
            news_items, focus_sec or "", _direction, nav_chg_pct, spy_chg_pct,
            movers=movers,
        )
        if _claude_bullets:
            bullets.extend(_claude_bullets)
        else:
            # Claude 调用失败时退回显示新闻标题
            for _ni in news_items:
                _link = f"[{_ni['title']}]({_ni['url']})" if _ni.get("url") else f"《{_ni['title']}》"
                bullets.append(f"📰 {_link}（Yahoo Finance，{_ni['pub_date']}）")
    else:
        log.info(f"  No news found for {today} — summary will be empty")

    now_sgt = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M SGT")
    return {
        "date":            str(today),
        "updated_sgt":     now_sgt,
        "nav_change_pct":  round(nav_chg_pct, 2),
        "spy_change_pct":  round(spy_chg_pct, 2),
        "vs_spy_pct":      round(vs_spy, 2),
        "bullets":         bullets,
        "news":            [{"title": n["title"], "url": n.get("url", "")} for n in news_items],
    }


# ── Download log helpers ─────────────────────────────────────────────────────

_NYSE_CALENDAR_URL = "https://www.nyse.com/markets/hours-calendars"


def _sgt_str(utc_dt: "datetime") -> str:
    return (utc_dt + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M SGT")


def _next_retry_at(from_utc: "datetime") -> "datetime":
    """Return the next :30-past-the-hour UTC time at or after from_utc.

    The retry workflow cron is '30 * * * 1-5', so it fires at :30 every hour.
    We add a 2-minute buffer so the workflow has time to start before the
    timing check inside run_retry() passes.
    """
    # Round up to the next :30
    if from_utc.minute < 30:
        candidate = from_utc.replace(minute=30, second=0, microsecond=0)
    else:
        candidate = (from_utc + timedelta(hours=1)).replace(minute=30, second=0, microsecond=0)
    # If we're already past the candidate (e.g. we ARE at :30 exactly), add an hour
    if candidate <= from_utc:
        candidate += timedelta(hours=1)
    return candidate


def _check_market_holiday(check_date: date) -> "tuple[bool | None, str, str]":
    """Return (is_holiday, holiday_name, source_url).
    True  = confirmed holiday or weekend.
    False = confirmed trading day.
    None  = cannot determine (library unavailable).
    """
    try:
        import pandas as _pd
        import pandas_market_calendars as mcal
        nyse     = mcal.get_calendar("NYSE")
        _cd      = str(check_date)
        schedule = nyse.schedule(start_date=_cd, end_date=_cd)
        if not schedule.empty:
            return False, "", ""
        # Market closed — determine the reason
        if check_date.weekday() >= 5:
            return True, "周末（Weekend）", _NYSE_CALENDAR_URL
        # Build name map from regular_holidays rules
        _yr      = check_date.year
        _yr_s    = f"{_yr}-01-01"
        _yr_e    = f"{_yr}-12-31"
        _named   = {}
        for _r in nyse.regular_holidays.rules:
            try:
                _dates = _r.dates(start_date=_yr_s, end_date=_yr_e, return_name=True)
                for _ts, _rn in _dates.items():
                    _named[_ts.date()] = str(_rn)
            except Exception:
                pass
        _name = _named.get(check_date, "NYSE 假日")
        return True, _name, _NYSE_CALENDAR_URL
    except Exception:
        return None, "无法确认（pandas_market_calendars 不可用）", _NYSE_CALENDAR_URL


def _get_et_date() -> date:
    """Return the current calendar date in US Eastern Time."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:
        return date.today()


def _get_target_date() -> date:
    """Return the NYSE trading date whose closing data should be available now.

    The main script is scheduled at 23:00 UTC (19:00 ET), but GitHub Actions
    queue delays can push it past midnight UTC (e.g., 00:10 UTC = 20:10 ET).
    Using date.today() in UTC would then return the wrong date.

    We use US Eastern Time instead: data is considered available 30 minutes
    after the 16:00 ET close (i.e., >= 16:30 ET = today's data; < 16:30 ET =
    yesterday's data). We then walk back to the most recent NYSE trading day.
    """
    try:
        from zoneinfo import ZoneInfo
        import pandas_market_calendars as mcal
        _et      = ZoneInfo("America/New_York")
        _now_et  = datetime.now(_et)
        _cutoff  = _now_et.replace(hour=16, minute=30, second=0, microsecond=0)
        _cand    = _now_et.date() if _now_et >= _cutoff else _now_et.date() - timedelta(days=1)
        nyse     = mcal.get_calendar("NYSE")
        for _ in range(10):
            if not nyse.schedule(start_date=str(_cand), end_date=str(_cand)).empty:
                return _cand
            _cand -= timedelta(days=1)
    except Exception:
        pass
    # Fallback: use ET-based date to avoid UTC-midnight issues on GitHub Actions
    try:
        from zoneinfo import ZoneInfo
        _now_et = datetime.now(ZoneInfo("America/New_York"))
        _cutoff = _now_et.replace(hour=16, minute=30, second=0, microsecond=0)
        return _now_et.date() if _now_et >= _cutoff else (_now_et.date() - timedelta(days=1))
    except Exception:
        return date.today()


def _get_dl_log(state: dict, today: date) -> dict:
    """Return today's download_log, resetting if date changed."""
    log_obj = state.get("download_log", {})
    if log_obj.get("date") != str(today):
        log_obj = {"date": str(today), "attempts": [], "holiday": None}
    return log_obj


def _append_attempt(log_obj: dict, record: dict) -> None:
    record.setdefault("seq", len(log_obj["attempts"]) + 1)
    log_obj["attempts"].append(record)


def _update_daily_summary(state: dict, today: date) -> bool:
    """Download current prices and regenerate today's daily summary.

    Called by run_retry() when market data becomes available after the main
    script's no-data early exit.  Returns True on success.
    """
    try:
        pos_tickers   = [p["ticker"] for p in state.get("positions", [])]
        pend_exits    = [s["ticker"] for s in state.get("pending_exits", [])]
        pend_entries  = [s["ticker"] for s in state.get("pending_entries", [])]
        needed        = list(set(pos_tickers + pend_exits + pend_entries + ["SPY", "SHY"]))
        price_data    = fetch_price_data(needed, period="300d")

        spy_df    = price_data.get("SPY")
        spy_close = float(spy_df["Close"].iloc[-1]) if spy_df is not None and not spy_df.empty else None

        cash      = state.get("cash", 0.0)
        pos_value = 0.0
        prev_prices: dict = {}
        for pos in state.get("positions", []):
            _t  = pos["ticker"]
            _df = price_data.get(_t)
            prev_prices[_t] = pos.get("last_known_price", pos["entry_price"])
            if _df is not None and not _df.empty:
                _px = float(_df["Close"].iloc[-1])
                pos_value += _px * pos.get("shares", 0)
                pos["last_known_price"] = _px
        current_nav = cash + pos_value

        prev_nav = state["nav_history"][-1]["nav"] if state.get("nav_history") else None
        prev_spy = state["nav_history"][-1].get("spy_close") if state.get("nav_history") else None

        state["daily_summary"] = _gen_daily_summary(
            today            = today,
            current_nav      = current_nav,
            prev_nav         = prev_nav,
            spy_close        = spy_close,
            prev_spy         = prev_spy,
            positions        = state.get("positions", []),
            prev_prices      = prev_prices,
            exits_executed   = [],
            entries_executed = [],
            new_exit_signals = [],
        )
        state["daily_summary"].pop("data_pending", None)
        log.info(f"  Daily summary updated for {today} via retry")
        return True
    except Exception as _e:
        log.warning(f"  _update_daily_summary failed: {_e}")
        return False


# ── Retry mode ───────────────────────────────────────────────────────────────

def run_retry() -> None:
    """Retry downloading and re-evaluating tickers listed in state['pending_retry'].

    Also handles `no_data_probe`: if the main run found no YF data for today (no-op),
    this function retries the SPY probe hourly and performs a holiday check after 3
    consecutive no-data attempts.

    Called by `--retry-mode`.  A dedicated GitHub Actions workflow runs this every
    hour so failed tickers are automatically re-evaluated without waiting for the
    next full daily run.
    """
    state   = load_state()

    # ── no_data_probe: main run found no YF data for today ────────────────────
    # Note: we do NOT return early here — always fall through to pending_retry
    # so that previously-failed tickers are retried even while waiting for today's market.
    _ndp = state.get("no_data_probe", {})
    _today = _get_et_date()   # 使用 ET 日期，与主函数写入 no_data_probe 的日期保持一致
    _probe_handled = False   # True when SPY probe actually ran this invocation
    if _ndp and _ndp.get("date") == str(_today):
        _next_utc_str = _ndp.get("next_retry_utc", "")
        _now_utc = datetime.now(timezone.utc)
        if _next_utc_str:
            _next_dt = datetime.fromisoformat(_next_utc_str.replace("Z", "+00:00"))
            if _now_utc < _next_dt:
                _rem = int((_next_dt - _now_utc).total_seconds() / 60)
                log.info(f"=== Retry mode: {_rem}min until no_data_probe retry — skipping probe, checking pending_retry ===")
                # Fall through to pending_retry below
            else:
                log.info(f"=== Retry mode: no_data_probe attempt {_ndp.get('attempt', 2)} ===")
                _dl_log = _get_dl_log(state, _today)
                _attempt_n = _ndp.get("attempt", 2)

                # Probe SPY
                _spy_probe = fetch_price_data(["SPY"], period="5d")
                _spy_df_p  = _spy_probe.get("SPY")
                _spy_has_today = (
                    not (_spy_df_p is None or _spy_df_p.empty) and
                    not _spy_df_p[_spy_df_p.index.date == _today].empty
                )

                if _spy_has_today:
                    # Data is now available — generate real summary, clear probe
                    log.info("  SPY data now available — generating daily summary")
                    _update_daily_summary(state, _today)
                    _append_attempt(_dl_log, {
                        "time_sgt": _sgt_str(_now_utc),
                        "type": "retry_probe",
                        "status": "data_available",
                        "success": 1, "failed": 0,
                        "note": "市场有数据，已生成今日小结",
                    })
                    state.pop("no_data_probe", None)
                else:
                    # Still no data
                    _no_data_total = _attempt_n  # this is the Nth no-data attempt

                    if _no_data_total >= 3:
                        # Holiday check
                        log.info(f"  {_no_data_total} consecutive no-data — checking holiday")
                        _is_hol, _hol_name, _hol_url = _check_market_holiday(_today)
                        _append_attempt(_dl_log, {
                            "time_sgt": _sgt_str(_now_utc),
                            "type": "retry_probe",
                            "status": "no_data",
                            "success": 0, "failed": 0,
                        })
                        if _is_hol is True:
                            _dl_log["holiday"] = {
                                "is_holiday": True,
                                "name": _hol_name,
                                "source": _hol_url,
                            }
                            log.info(f"  Holiday confirmed: {_hol_name}")
                            state.pop("no_data_probe", None)
                        elif _is_hol is False:
                            # Unexpectedly confirmed open — keep probing
                            _next = _next_retry_at(_now_utc)
                            _dl_log["holiday"] = None
                            _ndp["attempt"] = _no_data_total + 1
                            _ndp["next_retry_utc"] = _next.strftime("%Y-%m-%dT%H:%M:%SZ")
                            _ndp["next_retry_sgt"] = _sgt_str(_next)
                            state["no_data_probe"] = _ndp
                        else:
                            # Cannot confirm — keep probing with holiday=unknown
                            _next = _next_retry_at(_now_utc)
                            _dl_log["holiday"] = {
                                "is_holiday": None,
                                "name": "未能确认，持续重试中",
                                "source": _hol_url,
                            }
                            _ndp["attempt"] = _no_data_total + 1
                            _ndp["next_retry_utc"] = _next.strftime("%Y-%m-%dT%H:%M:%SZ")
                            _ndp["next_retry_sgt"] = _sgt_str(_next)
                            state["no_data_probe"] = _ndp
                    else:
                        # Schedule next probe
                        _next = _next_retry_at(_now_utc)
                        _append_attempt(_dl_log, {
                            "time_sgt": _sgt_str(_now_utc),
                            "type": "retry_probe",
                            "status": "no_data",
                            "success": 0, "failed": 0,
                            "next_retry_sgt": _sgt_str(_next),
                        })
                        _ndp["attempt"] = _no_data_total + 1
                        _ndp["next_retry_utc"] = _next.strftime("%Y-%m-%dT%H:%M:%SZ")
                        _ndp["next_retry_sgt"] = _sgt_str(_next)
                        state["no_data_probe"] = _ndp

                state["download_log"] = _dl_log
                state["last_no_op_utc"] = _now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                _probe_handled = True
                log.info("  no_data_probe handled — checking pending_retry next")
                # Fall through to pending_retry below (no return here)

    pending = state.get("pending_retry", {})
    retry_tickers = pending.get("tickers", [])

    if not retry_tickers:
        if _probe_handled:
            save_state(state)
            log.info("=== Retry done (probe only, no pending_retry) ===")
        else:
            log.info("=== Retry mode: nothing to do ===")
        return

    # ── Timing check ─────────────────────────────────────────────────────────
    next_utc_str = pending.get("next_retry_utc", "")
    if next_utc_str:
        next_retry_dt = datetime.fromisoformat(next_utc_str.replace("Z", "+00:00"))
        now_utc       = datetime.now(timezone.utc)
        if now_utc < next_retry_dt:
            remaining = int((next_retry_dt - now_utc).total_seconds() / 60)
            log.info(
                f"=== Retry mode: {remaining}min until next retry "
                f"({pending.get('next_retry_sgt', '')}) — exiting ==="
            )
            return

    scan_date = date.fromisoformat(pending.get("scan_date", str(date.today())))
    attempt   = pending.get("attempt", 1)
    log.info(f"=== Retry mode: attempt {attempt} for {scan_date}: {retry_tickers} ===")

    # Hard cap: after 8 hourly retries, the tickers are genuinely unavailable on YF.
    # Flag them as persistent so the main daily run skips them; stop wasting CI minutes.
    _MAX_RETRY_ATTEMPTS = 8
    if attempt > _MAX_RETRY_ATTEMPTS:
        _yf_persist = set(state.get("yf_persistent_unavailable", []))
        _newly = set(retry_tickers) - _yf_persist
        if _newly:
            _yf_persist |= _newly
            state["yf_persistent_unavailable"] = sorted(_yf_persist)
            log.warning(
                f"  Exceeded {_MAX_RETRY_ATTEMPTS} retry attempts — "
                f"flagging {len(_newly)} tickers as YF-persistent-unavailable: {sorted(_newly)}"
            )
        state.pop("pending_retry", None)
        save_state(state)
        log.info("=== Retry abandoned: tickers flagged as permanently unavailable ===")
        return

    # ── Download only the missing tickers ────────────────────────────────────
    retry_data    = fetch_price_data(retry_tickers, period="310d")
    still_missing = [t for t in retry_tickers if t not in retry_data]
    recovered     = [t for t in retry_tickers if t in retry_data]

    # Auto-clean data_error_log: drop tickers recovered this retry
    if recovered and state.get("data_error_log"):
        _resolved = set(recovered)
        _new_log = []
        for _entry in state["data_error_log"]:
            _still = [t for t in _entry.get("tickers_missed", []) if t not in _resolved]
            if _still:
                _new_log.append({**_entry, "tickers_missed": _still})
            else:
                log.info(f"  data_error_log resolved (retry): {_entry.get('tickers_missed', [])} now downloaded")
        state["data_error_log"] = _new_log

    # ── Re-evaluate entry signals for recovered tickers ──────────────────────
    if recovered:
        log.info(f"  Recovered: {recovered}")
        # Remove from yf_persistent_unavailable any tickers that recovered in retry
        _yf_persist_r = set(state.get("yf_persistent_unavailable", []))
        _recovered_from_persist_r = set(recovered) & _yf_persist_r
        if _recovered_from_persist_r:
            _yf_persist_r -= _recovered_from_persist_r
            state["yf_persistent_unavailable"] = sorted(_yf_persist_r)
            log.info(f"  Removed from yf_persistent_unavailable (recovered in retry): {sorted(_recovered_from_persist_r)}")
        last_nav = (
            state["nav_history"][-1]["nav"]
            if state.get("nav_history") else state.get("initial_nav", 200_000.0)
        )
        retry_candidates, _ = scan_entries(state, retry_data, scan_date, last_nav, pos_data={})
        existing_tickers    = {e["ticker"] for e in state.get("pending_entries", [])}
        for sig in retry_candidates:
            if sig["ticker"] not in existing_tickers:
                state.setdefault("pending_entries", []).append({
                    "ticker":          sig["ticker"],
                    "signal_date":     str(scan_date),
                    "signal_price":    sig["signal_price"],
                    "stop_price":      sig["stop_loss"],
                    "shares":          sig["shares"],
                    "atr":             round(sig["atr"], 4),
                    "signal_strength": round(sig["strength"], 4),
                    "trade_risk":      round(sig["trade_risk"], 4),
                    "notional":        round(sig["notional"], 2),
                })
                log.info(
                    f"  RETRY ENTRY added: {sig['ticker']} @ ${sig['signal_price']:.2f} "
                    f"strength={sig['strength']:.4f}"
                )
    else:
        log.warning("  No tickers recovered on this attempt")

    # ── Update or clear pending_retry ─────────────────────────────────────────
    _now_retry_utc   = datetime.now(timezone.utc)
    _orig_total      = pending.get("original_total_scanned", len(retry_tickers))
    # tickers successfully downloaded BEFORE this retry = orig_total - len(retry_tickers)
    _prev_success    = _orig_total - len(retry_tickers)
    _cum_success     = _prev_success + len(recovered)   # cumulative after this retry

    if still_missing:
        log.warning(f"  Still missing: {still_missing}")
        _next = _next_retry_at(_now_retry_utc)
        state["pending_retry"] = {
            "tickers":                still_missing,
            "scan_date":              str(scan_date),
            "attempt":                attempt + 1,
            "downloaded_count":       len(retry_data),
            "total_scanned":          len(retry_tickers),
            "original_total_scanned": _orig_total,   # carry through
            "next_retry_utc":         _next.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "next_retry_sgt":         _sgt_str(_next),
            "created_utc":            pending.get("created_utc", _now_retry_utc.strftime("%Y-%m-%dT%H:%M:%SZ")),
            "last_attempt_utc":       _now_retry_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        log.info(f"  Next retry scheduled: {state['pending_retry']['next_retry_sgt']}")
        _retry_dl_status = "partial"
        _next_sgt_val    = state["pending_retry"]["next_retry_sgt"]
    else:
        log.info("  All tickers recovered — clearing pending_retry")
        state.pop("pending_retry", None)
        state["last_download_stats"] = {
            "downloaded_count": _cum_success,
            "total_scanned":    _orig_total,
            "updated_utc":      _now_retry_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        _retry_dl_status = "success"
        _next_sgt_val    = None

    # Record to download_log
    _dl_log_retry = _get_dl_log(state, scan_date)
    _append_attempt(_dl_log_retry, {
        "time_sgt":           _sgt_str(_now_retry_utc),
        "type":               "retry_download",
        "status":             _retry_dl_status,
        "total":              _orig_total,
        "success":            len(recovered),
        "cumulative_success": _cum_success,
        "failed":             len(still_missing),
        "next_retry_sgt":     _next_sgt_val,
    })
    state["download_log"] = _dl_log_retry

    save_state(state)
    log.info("=== Retry done ===")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy 1.0 Paper Trading Daily Update")
    parser.add_argument("--date",            default=None,   help="Trading date YYYY-MM-DD (default: today)")
    parser.add_argument("--no-entries",      action="store_true", help="Skip new entry scanning")
    parser.add_argument("--universe-period", default="310d", help="yfinance period string for universe download")
    parser.add_argument("--retry-mode",      action="store_true", help="Retry downloading pending_retry tickers")
    args = parser.parse_args()

    if args.retry_mode:
        run_retry()
        return

    today = date.fromisoformat(args.date) if args.date else _get_target_date()
    log.info(f"=== Strategy 1.0 Paper Trading: {today} ===")

    state = load_state()

    # ── Duplicate-run guard ───────────────────────────────────────────────────
    # Prevent re-downloading the full universe when the same target date was
    # already fully processed. Only applies to auto-detected dates so that
    # manual --date backfills are never blocked.
    if not args.date:
        _last_upd = state.get("last_update_date", "2000-01-01")
        if today <= date.fromisoformat(_last_upd):
            _now_utc_dup = datetime.now(timezone.utc)
            state["last_no_op_utc"] = _now_utc_dup.strftime("%Y-%m-%dT%H:%M:%SZ")
            save_state(state)
            log.info(
                f"=== Done (already processed {today}, "
                f"last_update_date={_last_upd} — no-op) ==="
            )
            return

    # ── Non-trading day early exit ────────────────────────────────────────────
    # Exit early only when NYSE is genuinely closed today (holiday/weekend).
    # NOTE: Do NOT use "_et_today != today" — that comparison fires every time
    # the script runs after midnight ET (e.g., 02:00 AM), causing a false
    # "market closed" exit even when today is a normal trading day.
    if not args.date:
        _et_today = _get_et_date()
        _is_hol, _hol_name, _ = _check_market_holiday(_et_today)
        if _is_hol is True:
            _closed_reason = _hol_name or "假日"
            _now_utc_cl = datetime.now(timezone.utc)
            state["daily_summary"] = {
                "date":           str(_et_today),
                "updated_sgt":    _sgt_str(_now_utc_cl),
                "nav_change_pct": None,
                "spy_change_pct": None,
                "vs_spy_pct":     None,
                "bullets":        [
                    f"📅 今日（{_et_today}）美股市场不开盘（{_closed_reason}）。",
                    f"最近交易日：{today}。",
                ],
                "news":           [],
                "market_closed":  True,
            }
            state["last_no_op_utc"] = _now_utc_cl.strftime("%Y-%m-%dT%H:%M:%SZ")
            save_state(state)
            log.info(f"=== Done (market closed today: {_closed_reason}) ===")
            return
    validate_pending_entries(state)
    log.info(f"  Open positions: {len(state['positions'])} | Cash: ${state.get('cash',0)/1e6:.2f}M")

    # Snapshot yesterday's close prices before any updates (used for daily summary later)
    _prev_prices: dict[str, float] = {
        p["ticker"]: p.get("last_known_price", p["entry_price"])
        for p in state.get("positions", [])
    }
    _prev_nav = state["nav_history"][-1]["nav"] if state.get("nav_history") else None
    _prev_spy = state["nav_history"][-1].get("spy_close") if state.get("nav_history") else None

    # ── Step 1: fetch data for all tickers needed today ───────────────────────
    pos_tickers          = [p["ticker"] for p in state["positions"]]
    pending_exit_tickers = [s["ticker"] for s in state.get("pending_exits", [])]
    pending_entr_tickers = [s["ticker"] for s in state.get("pending_entries", [])]
    all_needed = list(set(pos_tickers + pending_exit_tickers + pending_entr_tickers + ["SPY", "SHY"]))
    log.info("--- Fetching position + pending + SPY + SHY data ---")
    pos_data = fetch_price_data(all_needed, period="300d")

    spy_df    = pos_data.get("SPY")
    regime_ok = is_bull_regime(spy_df)
    spy_close = float(spy_df["Close"].iloc[-1]) if spy_df is not None and not spy_df.empty else None
    _spy_sma200 = (
        float(spy_df["Close"].rolling(PARAMS.regime_sma_window).mean().iloc[-1])
        if spy_df is not None and len(spy_df) >= PARAMS.regime_sma_window else None
    )
    spy_pct_above_sma200 = (
        round((spy_close / _spy_sma200 - 1) * 100, 4)
        if (spy_close and _spy_sma200) else None
    )
    log.info(f"  Regime: {'BULL ✅' if regime_ok else 'BEAR 🚫'}  SPY close: {f'${spy_close:.2f}' if spy_close else 'N/A'}")

    # Guard: if today has no market data (pre-market, weekend, holiday), abort without
    # touching state so the website continues to show the last completed trading day.
    _spy_today = (
        spy_df[spy_df.index.date == today]
        if spy_df is not None and not spy_df.empty else pd.DataFrame()
    )
    if _spy_today.empty:
        log.warning(
            f"  No market data for {today} — pre-market, weekend, or holiday. "
            "State unchanged; website keeps showing last completed trading day."
        )
        _now_utc = datetime.now(timezone.utc)
        _dl_log  = _get_dl_log(state, today)

        # Count previous no-data attempts today
        _prev_no_data = sum(
            1 for a in _dl_log.get("attempts", [])
            if a.get("type") == "main_probe" and a.get("status") == "no_data"
        )
        _attempt_n = _prev_no_data + 1

        _next_retry_utc = _next_retry_at(_now_utc)
        _append_attempt(_dl_log, {
            "time_sgt":       _sgt_str(_now_utc),
            "type":           "main_probe",
            "status":         "no_data",
            "success":        0,
            "failed":         0,
            "attempt":        _attempt_n,
            "next_retry_sgt": _sgt_str(_next_retry_utc),
        })

        if _attempt_n >= 3 and _dl_log.get("holiday") is None:
            _is_hol, _hol_name, _hol_url = _check_market_holiday(today)
            if _is_hol is True:
                _dl_log["holiday"] = {"is_holiday": True, "name": _hol_name, "source": _hol_url}
                log.info(f"  Holiday confirmed: {_hol_name}")
            elif _is_hol is False:
                _dl_log["holiday"] = {"is_holiday": False, "name": "", "source": ""}
            else:
                _dl_log["holiday"] = {"is_holiday": None, "name": "未能确认", "source": _hol_url}

        state["download_log"] = _dl_log
        state["no_data_probe"] = {
            "date":            str(today),
            "attempt":         _attempt_n + 1,
            "next_retry_utc":  _next_retry_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "next_retry_sgt":  _sgt_str(_next_retry_utc),
        }
        state["last_no_op_utc"] = _now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Write a placeholder summary so the monitor page shows today's date
        # even while we wait for Yahoo Finance data.  Will be overwritten with
        # real data as soon as run_retry() confirms data is available.
        if state.get("daily_summary", {}).get("date") != str(today):
            state["daily_summary"] = {
                "date":           str(today),
                "updated_sgt":    _sgt_str(_now_utc),
                "nav_change_pct": None,
                "spy_change_pct": None,
                "vs_spy_pct":     None,
                "bullets":        [f"📊 {today} 收盘数据尚未获取到，正在持续重试，获取成功后将自动更新。"],
                "news":           [],
                "data_pending":   True,
            }

        save_state(state)
        log.info("=== Done (no-op — market not yet open) ===")
        return

    # ── Step 1b: check suspended positions (YF + Tiingo) ─────────────────────
    _suspended = [p for p in state.get("positions", []) if p.get("suspended")]
    if _suspended:
        _tiingo_token = os.environ.get("TIINGO_API_TOKEN", "")
        for _sp in _suspended:
            _st = _sp["ticker"]
            _resumed = False
            # Check YF
            _yf_check = fetch_price_data([_st], period="5d")
            if _yf_check.get(_st) is not None and not _yf_check[_st].empty:
                _sp["suspended"] = False
                _sp.pop("suspend_reason", None)
                _sp.pop("suspend_date", None)
                _sp.pop("last_data_date", None)
                log.info(f"  {_st}: resumed trading (YF data found) — suspension cleared")
                _resumed = True
            # Check Tiingo if YF still empty
            if not _resumed and _tiingo_token:
                try:
                    import requests as _req
                    _url = (f"https://api.tiingo.com/tiingo/daily/{_st}/prices"
                            f"?startDate={today}&endDate={today}")
                    _r = _req.get(_url, headers={"Authorization": f"Token {_tiingo_token}"},
                                  timeout=10)
                    if _r.status_code == 200 and _r.json():
                        _sp["suspended"] = False
                        _sp.pop("suspend_reason", None)
                        _sp.pop("suspend_date", None)
                        _sp.pop("last_data_date", None)
                        log.info(f"  {_st}: resumed trading (Tiingo data found) — suspension cleared")
                        _resumed = True
                except Exception as _e:
                    log.warning(f"  {_st}: Tiingo check failed: {_e}")
            if not _resumed:
                log.info(f"  {_st}: still suspended — no data from YF or Tiingo for {today}")

    # ── Step 2: ① OPEN — execute yesterday's pending exits ───────────────────
    _regime_str = "BULL" if regime_ok else "BEAR"
    exits_executed, remaining_exits = execute_pending_exits(state, pos_data, today, regime=_regime_str)
    # Carry over any exits that couldn't execute (no data)
    # New exit signals will be appended later; don't overwrite remaining yet

    # ── Step 3: ① OPEN — execute yesterday's pending entries ─────────────────
    entries_executed = execute_pending_entries(state, pos_data, today, regime=_regime_str)

    # ── Step 3.5: ② CASH — apply SGOV return to uninvested cash ─────────────
    # Mirrors backtest engine step ②: portfolio.cash *= (1 + sgov_ret)
    # Applied AFTER open executions (cash reflects today's buys/sells) and
    # BEFORE NAV snapshot, so NAV correctly captures interest earned today.
    shy_df   = pos_data.get("SHY")
    shy_ret  = 0.0
    if shy_df is not None and not shy_df.empty and len(shy_df) >= 2:
        today_ts = pd.Timestamp(today)
        close_s  = shy_df["Close"]
        if today_ts in close_s.index:
            idx = close_s.index.get_loc(today_ts)
            if idx > 0:
                shy_ret = float(close_s.iloc[idx] / close_s.iloc[idx - 1] - 1)
    _cash_before = state.get("cash", 0.0)
    state["cash"] = _cash_before * (1.0 + shy_ret)
    if shy_ret != 0.0:
        log.info(f"  SHY return: {shy_ret*100:+.4f}%  "
                 f"cash ${_cash_before:,.0f} → ${state['cash']:,.0f}")
    else:
        log.warning("  SHY data unavailable for today — cash earns 0%")

    # ── Step 4: ③ CLOSE — update trail stops, detect new exit signals ─────────
    log.info("--- Updating trail stops and detecting exit signals ---")
    updated_positions, new_exit_signals = detect_exit_signals(state, pos_data, today)
    state["positions"] = updated_positions
    log.info(f"  {len(new_exit_signals)} new exit signal(s) | {len(updated_positions)} positions open")

    # Pending exits = carried-over (no data yesterday) + newly detected today
    state["pending_exits"] = remaining_exits + new_exit_signals

    # ── Step 5: ④ NAV — mark to close ────────────────────────────────────────
    mkt_value   = sum(p.get("last_known_price", p["entry_price"]) * p["shares"] for p in state["positions"])
    current_nav = mkt_value + state.get("cash", 0.0)

    # ── Step 6: ③ CLOSE — scan entry signals ─────────────────────────────────
    # Mirrors backtest engine.py regime logic exactly:
    #   Bull  → scan full universe
    #   Bear  → scan only bear_exempt_tickers (e.g. GLD, TLT, UUP); empty list → no scan
    candidates:  list[dict] = []
    new_pending: list[dict] = []
    scan_stats:  dict       = {"n_raw_breakouts": 0, "n_heat_blocked": 0, "n_corr_reduced": 0}
    _bear_exempt = list(PARAMS.bear_exempt_tickers)  # e.g. ['GLD', 'TLT', 'UUP']

    if not args.no_entries:
        universe_df  = pd.read_csv(_UNIVERSE)
        _EXCL_TICKERS = {"FXI", "GDX", "KWEB", "VXX", "EMB", "ASHR", "ETH", "SPY", "SHY"}

        # ── Dynamic YF-unavailable list ────────────────────────────────────────
        # If yesterday's pending_retry is still open when today's main run starts,
        # those tickers are permanently unavailable on YF. Two criteria to flag:
        #   (a) ≤10 tickers:  safe to flag even on a single overnight failure —
        #       unlikely to be transient YF rate-limiting at such a small scale.
        #   (b) attempt ≥ 5:  5+ consecutive hourly retries all failed → genuinely
        #       unavailable regardless of count (rate-limits resolve within hours,
        #       not across multiple days of retries).
        _stale_retry = state.get("pending_retry", {})
        if _stale_retry and _stale_retry.get("scan_date", str(today)) != str(today):
            _stale_tickers = _stale_retry.get("tickers", [])
            _stale_attempts = _stale_retry.get("attempt", 1)
            if 0 < len(_stale_tickers) and (len(_stale_tickers) <= 10 or _stale_attempts >= 5):
                _yf_persist = set(state.get("yf_persistent_unavailable", []))
                _newly_flagged = set(_stale_tickers) - _yf_persist
                if _newly_flagged:
                    _yf_persist |= _newly_flagged
                    state["yf_persistent_unavailable"] = sorted(_yf_persist)
                    log.warning(
                        f"  Auto-flagged as YF-persistent-unavailable "
                        f"({len(_stale_tickers)} tickers, attempt={_stale_attempts}): "
                        f"{sorted(_newly_flagged)}"
                    )

        _YF_UNAVAILABLE = set(state.get("yf_persistent_unavailable", []))

        active_set = set(
            universe_df[
                (universe_df["is_active"] == True) &
                (universe_df["eligible_days"] >= 252) &
                (~universe_df["ticker"].isin(_EXCL_TICKERS | _YF_UNAVAILABLE))
            ]["ticker"].tolist()
        )
        _tiingo_eligible = universe_df[
            (universe_df["is_active"] == True) &
            (universe_df["eligible_days"] >= 252) &
            (~universe_df["ticker"].isin(_EXCL_TICKERS))
        ]
        state["universe_stats"] = {
            "tiingo_eligible":        len(_tiingo_eligible),
            "yf_downloadable":        len(active_set),
            "yf_unavailable_in_pool": len(_tiingo_eligible) - len(active_set),
            "total_active":           int((universe_df["is_active"] == True).sum()),
            "total_delisted":         int((universe_df["is_active"] == False).sum()),
            "updated_utc":            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        log.info(
            f"  Universe: Tiingo-eligible={len(_tiingo_eligible)}, "
            f"YF-downloadable={len(active_set)}, "
            f"YF-unavailable-in-pool={len(_tiingo_eligible) - len(active_set)}"
        )

        # ── Weekly recovery check (Monday): try known-unavailable tickers ──────
        # If any succeed, they'll be removed from yf_persistent_unavailable below.
        _tiingo_pool_tickers = set(_tiingo_eligible["ticker"].tolist())
        _persist_in_pool = _YF_UNAVAILABLE & _tiingo_pool_tickers

        if regime_ok:
            scan_tickers = list(active_set)
            if today.weekday() == 0 and _persist_in_pool:
                scan_tickers += sorted(_persist_in_pool)
                log.info(f"  Monday recovery check: also scanning {sorted(_persist_in_pool)}")
            log.info("--- Scanning full universe for new entry signals (BULL) ---")
        elif _bear_exempt:
            scan_tickers = [t for t in _bear_exempt if t in active_set]
            log.info(f"--- BEAR regime — scanning exempt tickers only: {scan_tickers} ---")
        else:
            scan_tickers = []
            log.info("  BEAR regime — no new entry signals (no bear-exempt tickers configured)")

        _univ_data: dict = {}
        if scan_tickers:
            try:
                _univ_data = fetch_price_data(scan_tickers, period=args.universe_period)
            except Exception as _univ_dl_exc:
                log.error(
                    f"  Universe download failed "
                    f"({type(_univ_dl_exc).__name__}: {_univ_dl_exc}). "
                    "Skipping signal scan — exits and pending entries already complete."
                )
                scan_tickers = []  # prevent the scan block below from running

        if scan_tickers:
            univ_data = _univ_data

            # Remove from yf_persistent_unavailable any tickers that just succeeded
            # (auto-recovery: previously flagged but now downloadable again).
            _yf_persist_now = set(state.get("yf_persistent_unavailable", []))
            _recovered_persist = set(univ_data.keys()) & _yf_persist_now
            if _recovered_persist:
                _yf_persist_now -= _recovered_persist
                state["yf_persistent_unavailable"] = sorted(_yf_persist_now)
                log.info(f"  Recovered from yf_persistent_unavailable: {sorted(_recovered_persist)}")

            # Auto-flag tickers with insufficient data density (< 50 rows in the
            # download window).  These are effectively non-tradeable on YF even
            # though the download technically succeeds (e.g. ZVZZT / ZXZZT with
            # only 1 row per year).
            _MIN_ROWS = 50
            _sparse = [t for t, df in univ_data.items() if len(df) < _MIN_ROWS]
            if _sparse:
                _yf_persist_now = set(state.get("yf_persistent_unavailable", []))
                _newly_sparse = set(_sparse) - _yf_persist_now
                if _newly_sparse:
                    _yf_persist_now |= _newly_sparse
                    state["yf_persistent_unavailable"] = sorted(_yf_persist_now)
                    log.warning(f"  Auto-flagged sparse tickers (<{_MIN_ROWS} rows): {sorted(_newly_sparse)}")

            # Track any tickers whose data was silently dropped (rate-limit) and
            # schedule them for an automatic retry 1 hour later via pending_retry.
            _missing_tickers = [t for t in scan_tickers if t not in univ_data]
            _yf_unavail_now  = set(state.get("yf_persistent_unavailable", []))
            _retry_tickers   = [t for t in _missing_tickers if t not in _yf_unavail_now]
            if _retry_tickers:
                _retry_at   = _next_retry_at(datetime.now(timezone.utc))
                _now_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                state["pending_retry"] = {
                    "tickers":                _retry_tickers,
                    "scan_date":              str(today),
                    "attempt":                1,
                    "downloaded_count":       len(univ_data),
                    "total_scanned":          len(scan_tickers),
                    "original_total_scanned": len(scan_tickers),  # carried through all retries
                    "next_retry_utc":         _retry_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "next_retry_sgt":         _sgt_str(_retry_at),
                    "created_utc":            _now_utc_str,
                    "last_attempt_utc":       _now_utc_str,
                }
                _skipped_persist = len(_missing_tickers) - len(_retry_tickers)
                log.warning(
                    f"  {len(_missing_tickers)} tickers missing "
                    f"({_skipped_persist} skipped — already in yf_persistent_unavailable) "
                    f"→ {len(_retry_tickers)} queued for retry "
                    f"at {state['pending_retry']['next_retry_sgt']}: {_retry_tickers}"
                )
            elif state.get("pending_retry"):
                state.pop("pending_retry")
                log.info("  All tickers downloaded — cleared previous pending_retry")

            # Always persist download stats for the monitor page
            _now_dl_utc = datetime.now(timezone.utc)
            state["last_download_stats"] = {
                "downloaded_count": len(univ_data),
                "total_scanned":    len(scan_tickers),
                "updated_utc":      _now_dl_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

            # Record to download_log
            _dl_log_main = _get_dl_log(state, today)
            _dl_status   = "success" if not _retry_tickers else "partial"
            _append_attempt(_dl_log_main, {
                "time_sgt":          _sgt_str(_now_dl_utc),
                "type":              "main_download",
                "status":            _dl_status,
                "total":             len(scan_tickers),
                "success":           len(univ_data),
                "cumulative_success": len(univ_data),
                "failed":            len(_retry_tickers),
                "next_retry_sgt": (
                    state["pending_retry"]["next_retry_sgt"] if _retry_tickers else None
                ),
            })
            state["download_log"] = _dl_log_main
            # Clear no_data_probe since we have data now
            state.pop("no_data_probe", None)

            # Auto-clean data_error_log: drop tickers that succeeded this run
            if state.get("data_error_log"):
                _resolved = set(univ_data.keys())
                _new_log = []
                for _entry in state["data_error_log"]:
                    _still = [t for t in _entry.get("tickers_missed", []) if t not in _resolved]
                    if _still:
                        _new_log.append({**_entry, "tickers_missed": _still})
                    else:
                        log.info(f"  data_error_log resolved: {_entry.get('tickers_missed', [])} now downloaded")
                state["data_error_log"] = _new_log

            candidates, scan_stats = scan_entries(state, univ_data, today, current_nav, pos_data=pos_data)
            log.info(
                f"  Raw breakouts: {scan_stats['n_raw_breakouts']} | "
                f"Heat-blocked: {scan_stats['n_heat_blocked']} | "
                f"Corr-reduced: {scan_stats['n_corr_reduced']} | "
                f"Accepted: {len(candidates)}"
            )
            # All heat-passing candidates go to pending_entries — mirrors backtest.
            # Cash check is deferred to T+1 execution, so gap-filter failures free
            # cash for the next signal in line without needing a separate backup list.
            for sig in candidates:
                new_pending.append({
                    "ticker":          sig["ticker"],
                    "signal_date":     str(today),
                    "signal_price":    sig["signal_price"],
                    "stop_price":      sig["stop_loss"],
                    "shares":          sig["shares"],
                    "atr":             sig["atr"],
                    "signal_strength": sig["strength"],
                    "trade_risk":      sig["trade_risk"],
                    "notional":        sig["notional"],
                })
                log.info(f"  PENDING {sig['ticker']} @ signal ${sig['signal_price']:.2f}  "
                         f"stop=${sig['stop_loss']:.2f}  shares={sig['shares']:,}  "
                         f"risk={sig['trade_risk']*100:.2f}%")
    else:
        log.info("  --no-entries flag set — skipping entry scan")

    state["pending_entries"] = new_pending

    # ── Step 7: update metadata & NAV history ────────────────────────────────
    history = [h for h in state.get("nav_history", []) if h["date"] != str(today)]
    history.append({
        "date":      str(today),
        "nav":       round(current_nav, 2),
        "regime":    "BULL" if regime_ok else "BEAR",
        "spy_close": round(spy_close, 2) if spy_close else None,
    })
    state["nav_history"]      = sorted(history, key=lambda x: x["date"])
    state["last_update_date"] = str(today)
    state["last_update_utc"]  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Step 7b: generate daily summary for monitor page ─────────────────────
    state["daily_summary"] = _gen_daily_summary(
        today            = today,
        current_nav      = current_nav,
        prev_nav         = _prev_nav,
        spy_close        = spy_close,
        prev_spy         = _prev_spy,
        positions        = state["positions"],
        prev_prices      = _prev_prices,
        exits_executed   = exits_executed,
        entries_executed = entries_executed,
        new_exit_signals = new_exit_signals,
    )
    log.info(f"  Daily summary generated for {today}")

    # ── Step 8: build today_signals for website display ───────────────────────
    _today_sig = {
        "date":    str(today),
        "regime":  "BULL" if regime_ok else "BEAR",
        "spy_close": round(spy_close, 2) if spy_close else None,
        "n_candidates":    len(candidates),
        "n_entries":       len(new_pending),           # entry signals pending for tomorrow
        "n_executed":      len(entries_executed),      # entries executed today at open
        "n_exits":         len(new_exit_signals),      # exit signals pending for tomorrow
        "n_raw_breakouts":     scan_stats["n_raw_breakouts"],  # breakouts before portfolio constraints
        "n_heat_blocked":      scan_stats["n_heat_blocked"],   # blocked by heat limit
        "n_cash_blocked":      scan_stats.get("n_cash_blocked", 0),  # blocked by cash (legacy field)
        "n_corr_reduced":      scan_stats["n_corr_reduced"],   # size reduced by correlation filter
        "n_price_filtered":    scan_stats.get("n_price_filtered", 0),
        "n_adv_filtered":      scan_stats.get("n_adv_filtered", 0),
        "n_breakout_filtered": scan_stats.get("n_breakout_filtered", 0),
        "n_atr_filtered":      scan_stats.get("n_atr_filtered", 0),
        "n_stop_dist_filtered": scan_stats.get("n_stop_dist_filtered", 0),
        "n_volume_filtered":   scan_stats.get("n_volume_filtered", 0),
        "spy_pct_above_sma200": spy_pct_above_sma200,

        # ① OPEN executions (from yesterday's pending signals)
        "exits_executed": [{
            "ticker":      c["ticker"],
            "shares":      c["shares"],
            "exit_open":   c.get("exit_open", c["exit_price"]),   # raw open (no slip)
            "exit_price":  c["exit_price"],                        # fill after sell slippage
            "net_pnl":     c["net_pnl"],
            "pnl_r":       c["pnl_r"],
            "exit_reason": c["exit_reason"],
        } for c in exits_executed],
        "entries_executed": [{
            "ticker":       e["ticker"],
            "signal_date":  e.get("signal_date", ""),
            "signal_price": e["signal_price"],
            "open_price":   e["open_price"],
            "entry_price":  e["entry_price"],
            "shares":       e["shares"],
            "stop_price":   e["stop_price"],
            "trade_risk":   e["trade_risk"],
        } for e in entries_executed],

        # ③ CLOSE signals (detected today, pending for tomorrow's execution)
        "exit_signals": [{
            "ticker":      s["ticker"],
            "exit_reason": s["exit_reason"],
            "stop_used":   s["stop_used"],
            "shares":      s["shares"],
        } for s in new_exit_signals],
        # All raw breakout candidates (passed per-stock filters) with rejection reason.
        # Superset of entry_signals — displayed in 四 so the user sees the full funnel.
        "candidate_signals": scan_stats.get("all_raw_candidates", []),
        # Approved subset (passed portfolio heat/cash constraints): same as pending_entries.
        "entry_signals": [{
            "ticker":       p["ticker"],
            "signal_price": p["signal_price"],
            "stop_price":   p["stop_price"],
            "shares":       p["shares"],
            "trade_risk":   p["trade_risk"],
            "strength":     p.get("signal_strength", p.get("strength")),
        } for p in new_pending],
    }
    state["today_signals"] = _today_sig

    _sig_hist = [s for s in state.get("signals_history", []) if s["date"] != str(today)]
    _sig_hist.append(_today_sig)
    state["signals_history"] = sorted(_sig_hist, key=lambda x: x["date"])

    # ── Step 9: refresh sector labels for open positions ─────────────────────
    # Done here (GitHub Actions, no rate-limit) so the monitor page can read
    # sector directly from positions.json instead of calling yfinance live.
    _need_sector = [p for p in state["positions"] if not p.get("sector")]
    if _need_sector:
        log.info(f"  Fetching sector for {len(_need_sector)} positions …")
        for _p in _need_sector:
            try:
                _info = yf.Ticker(_p["ticker"]).info
                _p["sector"] = _info.get("sector") or _info.get("quoteType") or "N/A"
            except Exception:
                _p["sector"] = "N/A"
        log.info("  Sector labels updated")

    # ── Step 10: 用最终 yf_persistent_unavailable 重新计算 universe_stats ────
    # 保证网页指标卡与 Debug 标的数一致（稀疏过滤可能在 Step 6 后新增黑名单条目）
    try:
        _final_yf_unavail = set(state.get("yf_persistent_unavailable", []))
        _final_active_set = set(
            universe_df[
                (universe_df["is_active"] == True) &
                (universe_df["eligible_days"] >= 252) &
                (~universe_df["ticker"].isin(_EXCL_TICKERS | _final_yf_unavail))
            ]["ticker"].tolist()
        )
        _final_tiingo = universe_df[
            (universe_df["is_active"] == True) &
            (universe_df["eligible_days"] >= 252) &
            (~universe_df["ticker"].isin(_EXCL_TICKERS))
        ]
        state["universe_stats"] = {
            "tiingo_eligible":        len(_final_tiingo),
            "yf_downloadable":        len(_final_active_set),
            "yf_unavailable_in_pool": len(_final_tiingo) - len(_final_active_set),
            "total_active":           int((universe_df["is_active"] == True).sum()),
            "total_delisted":         int((universe_df["is_active"] == False).sum()),
            "updated_utc":            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        log.info(
            f"  Universe stats (final): yf_downloadable={len(_final_active_set)}, "
            f"yf_unavailable_in_pool={len(_final_tiingo) - len(_final_active_set)}"
        )
    except Exception as _e:
        log.warning(f"  Failed to update final universe_stats: {_e}")

    save_state(state)

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("=== Done ===")
    log.info(f"  Exits executed:     {len(exits_executed)}  (from yesterday's pending, at today's open)")
    log.info(f"  Entries executed:   {len(entries_executed)}  (from yesterday's pending, at today's open)")
    log.info(f"  New exit signals:   {len(new_exit_signals)}  (pending for tomorrow's open)")
    log.info(f"  New entry signals:  {len(new_pending)}  (pending for tomorrow's open)")
    log.info(f"  Open positions:     {len(state['positions'])}")
    log.info(f"  Cash:               ${state.get('cash',0)/1e6:.2f}M")
    log.info(f"  NAV:                ${current_nav/1e6:.2f}M")
    log.info(f"  vs Initial:         {(current_nav / state['initial_nav'] - 1)*100:+.1f}%")

    if exits_executed:
        log.info("--- Exits executed at T+1 open ---")
        for c in exits_executed:
            log.info(f"  {c['ticker']:6s}  fill=${c['exit_price']:.2f}  R={c['pnl_r']:+.2f}  [{c['exit_reason']}]")

    if entries_executed:
        log.info("--- Entries executed at T+1 open ---")
        for e in entries_executed:
            log.info(f"  {e['ticker']:6s}  fill=${e['entry_price']:.2f}  signal=${e['signal_price']:.2f}  shares={e['shares']:,}")

    if new_exit_signals:
        log.info("--- New exit signals (execute tomorrow at open) ---")
        for s in new_exit_signals:
            log.info(f"  {s['ticker']:6s}  [{s['exit_reason']}]  stop_used=${s['stop_used']:.2f}")

    if new_pending:
        log.info("--- New entry signals (execute tomorrow at open) ---")
        for p in new_pending:
            log.info(f"  {p['ticker']:6s}  signal=${p['signal_price']:.2f}  stop=${p['stop_price']:.2f}  "
                     f"shares={p['shares']:,}  notional=${p['notional']/1e3:.0f}K")


if __name__ == "__main__":
    main()
