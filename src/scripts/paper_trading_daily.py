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

import sys, json, argparse, logging, math, time
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
            "atr_at_entry":       sig.get("atr_at_entry", 0.0),
            "trail_stop_at_exit": sig.get("trail_stop_at_exit", 0.0),
            "atr_at_exit":        sig.get("atr_at_exit", 0.0),
            "exit_commission":    round(exit_commission, 2),
            "entry_commission":   round(entry_commission, 2),
            "pnl_r":              round(pnl_r, 4),
            "net_pnl":            round(net_pnl, 2),
            "exit_reason":        sig["exit_reason"],
            "detected_date":      sig.get("detected_date", ""),
            "holding_days":       (bar_date - pd.to_datetime(sig.get("entry_date", str(bar_date))).date()).days,
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
        _atr     = sig.get("atr", 0.0)
        stop_px  = round(entry_px_slip - PARAMS.stop_loss_multiplier * _atr, 4)
        trail_px = round(entry_px_slip - PARAMS.trail_multiplier_r1  * _atr, 4)

        # Guard: degenerate stop — mirrors backtest _execute_entry() guard
        if stop_px >= entry_px_slip:
            log.info(f"  SKIP {ticker}: stop >= entry (degenerate ATR)")
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
            "signal_strength":   sig.get("strength", 0.0),   # breakout strength; flows to closed_trades
            "entry_date":        str(today),
            "open_price":        round(open_px, 4),          # raw T+1 open (reference)
            "entry_price":       round(entry_px_slip, 4),    # slip-adjusted fill (matches backtest)
            "shares":            shares,                      # recomputed at execution time
            "stop_loss":         stop_px,
            "trail_stop":        trail_px,
            "highest_high":      round(entry_px_slip, 4),    # init to entry_price (backtest convention)
            "atr_at_entry":      _atr,
            "R_at_backtest_end": 0.0,
            "last_known_price":  round(open_px, 4),
            "last_price_date":   str(today),
            "entry_commission":  round(commission, 2),        # stored for correct net_pnl at exit
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
            "strength":    sig.get("strength", 0.0),
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
                "trail_stop_at_exit": round(trail_stop, 6),  # trail level that triggered (or latest)
                "atr_at_exit":      round(cur_atr, 4),
                "detected_date":    str(bar_date),
                "entry_commission": pos.get("entry_commission", 0.0),  # for net_pnl at exit
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
    heat_used    = sum(
        (p["entry_price"] - p["stop_loss"]) * p["shares"] / nav
        for p in state["positions"]
    )
    signals: list[dict] = []

    # Rejection counters — stored in today_signals for future overfitting analysis
    n_raw_breakouts = 0   # passed all per-stock filters; before portfolio constraints
    n_corr_reduced  = 0   # correlation triggered size reduction (signal still accepted)
    n_heat_blocked  = 0   # blocked by portfolio heat limit
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
            continue

        # ADV filter — Raw_Close (unadjusted) × volume, shift(1), no look-ahead bias.
        # Mirrors backtest: compute_adv_from_ohlcv(df["close"], volume) uses raw close.
        adv = (today_df["Raw_Close"] * volume).shift(1).rolling(60).mean().iloc[-1]
        if pd.isna(adv) or adv < PARAMS.min_adv_m * 1e6:
            continue

        # Breakout signal — mirrors backtest entry.py
        rolling_high = compute_rolling_high(high, PARAMS.breakout_window)
        if not compute_breakout_signal(close, rolling_high).iloc[-1]:
            continue

        # ATR
        atr_s   = compute_atr(high, low, close, PARAMS.atr_period)
        cur_atr = float(atr_s.iloc[-1])
        if pd.isna(cur_atr) or cur_atr <= 0:
            continue

        entry_px  = float(close.iloc[-1])
        stop_px   = entry_px - PARAMS.stop_loss_multiplier * cur_atr
        stop_dist = entry_px - stop_px

        if stop_dist / entry_px < PARAMS.min_stop_distance_pct:
            continue

        # Volume confirmation — shift(1) mirrors backtest indicators/adv.py compute_volume_ma:
        # volume_ma[t] = mean(volume[t-60:t-1]), excludes today
        if PARAMS.volume_filter_multiplier > 0:
            vol_ma = volume.shift(1).rolling(60).mean().iloc[-1]
            if not pd.isna(vol_ma) and float(volume.iloc[-1]) < PARAMS.volume_filter_multiplier * float(vol_ma):
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

        pre_candidates.append({
            "ticker":          ticker,
            "entry_px":        entry_px,
            "stop_px":         stop_px,
            "stop_dist":       stop_dist,
            "shares":          shares,
            "cur_atr":         cur_atr,
            "notional":        notional,
            "trade_risk":      trade_risk,
            "strength":        strength,
            "_corr_triggered": _corr_triggered,
            "_corr_with":      _corr_with_ticker,
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
                "ticker":       ticker,
                "signal_price": round(entry_px, 4),
                "stop_price":   round(stop_px, 4),
                "shares":       shares,
                "trade_risk":   round(trade_risk, 4),
                "strength":     round(strength, 4),
                "rejection":    "heat_limit",
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
            "ticker":       ticker,
            "signal_price": round(entry_px, 4),
            "stop_price":   round(stop_px, 4),
            "shares":       shares,
            "trade_risk":   round(trade_risk, 4),
            "strength":     round(strength, 4),
            "rejection":    "corr_reduced" if _corr_triggered else None,
            "corr_with":    _corr_with_ticker if _corr_triggered else None,
        })
        heat_used += trade_risk

    # signals is already in strength order (pre_candidates was sorted by strength)
    scan_stats = {
        "n_raw_breakouts":    n_raw_breakouts,
        "n_heat_blocked":     n_heat_blocked,
        "n_corr_reduced":     n_corr_reduced,
        "all_raw_candidates": all_raw_candidates,   # full funnel; displayed in 四
    }
    return signals, scan_stats


# ── Retry mode ───────────────────────────────────────────────────────────────

def run_retry() -> None:
    """Retry downloading and re-evaluating tickers listed in state['pending_retry'].

    Called by `--retry-mode`.  A dedicated GitHub Actions workflow runs this every
    hour so failed tickers are automatically re-evaluated without waiting for the
    next full daily run.
    """
    state   = load_state()
    pending = state.get("pending_retry", {})
    retry_tickers = pending.get("tickers", [])

    if not retry_tickers:
        log.info("=== Retry mode: no pending_retry — nothing to do ===")
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

    # ── Download only the missing tickers ────────────────────────────────────
    retry_data    = fetch_price_data(retry_tickers, period="310d")
    still_missing = [t for t in retry_tickers if t not in retry_data]
    recovered     = [t for t in retry_tickers if t in retry_data]

    # ── Re-evaluate entry signals for recovered tickers ──────────────────────
    if recovered:
        log.info(f"  Recovered: {recovered}")
        last_nav = (
            state["nav_history"][-1]["nav"]
            if state.get("nav_history") else state.get("initial_nav", 200_000.0)
        )
        retry_candidates, _ = scan_entries(state, retry_data, scan_date, last_nav, pos_data={})
        existing_tickers    = {e["ticker"] for e in state.get("pending_entries", [])}
        for sig in retry_candidates:
            if sig["ticker"] not in existing_tickers:
                state.setdefault("pending_entries", []).append({
                    "ticker":       sig["ticker"],
                    "signal_date":  str(scan_date),
                    "signal_price": sig["signal_price"],
                    "stop_price":   sig["stop_loss"],
                    "shares":       sig["shares"],
                    "atr":          round(sig["atr"], 4),
                    "strength":     round(sig["strength"], 4),
                    "trade_risk":   round(sig["trade_risk"], 4),
                    "notional":     round(sig["notional"], 2),
                })
                log.info(
                    f"  RETRY ENTRY added: {sig['ticker']} @ ${sig['signal_price']:.2f} "
                    f"strength={sig['strength']:.4f}"
                )
    else:
        log.warning("  No tickers recovered on this attempt")

    # ── Update or clear pending_retry ─────────────────────────────────────────
    if still_missing:
        log.warning(f"  Still missing: {still_missing}")
        _next      = datetime.now(timezone.utc) + timedelta(hours=1)
        _sgt_off   = timedelta(hours=8)
        state["pending_retry"] = {
            "tickers":        still_missing,
            "scan_date":      str(scan_date),
            "attempt":        attempt + 1,
            "next_retry_utc": _next.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "next_retry_sgt": (_next + _sgt_off).strftime("%Y-%m-%d %H:%M SGT"),
            "created_utc":    pending.get("created_utc", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        }
        log.info(f"  Next retry scheduled: {state['pending_retry']['next_retry_sgt']}")
    else:
        log.info("  All tickers recovered — clearing pending_retry")
        state.pop("pending_retry", None)

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

    today = date.fromisoformat(args.date) if args.date else date.today()
    log.info(f"=== Strategy 1.0 Paper Trading: {today} ===")

    state = load_state()
    log.info(f"  Open positions: {len(state['positions'])} | Cash: ${state.get('cash',0)/1e6:.2f}M")

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
    log.info(f"  Regime: {'BULL ✅' if regime_ok else 'BEAR 🚫'}  SPY close: {f'${spy_close:.2f}' if spy_close else 'N/A'}")

    # Guard: if today has no market data (pre-market, weekend, holiday), abort without
    # touching state so the website continues to show the last completed trading day.
    _spy_today = (
        spy_df[spy_df.index.normalize() == pd.Timestamp(today)]
        if spy_df is not None and not spy_df.empty else pd.DataFrame()
    )
    if _spy_today.empty:
        log.warning(
            f"  No market data for {today} — pre-market, weekend, or holiday. "
            "State unchanged; website keeps showing last completed trading day."
        )
        log.info("=== Done (no-op — market not yet open) ===")
        return

    # ── Step 2: ① OPEN — execute yesterday's pending exits ───────────────────
    exits_executed, remaining_exits = execute_pending_exits(state, pos_data, today)
    # Carry over any exits that couldn't execute (no data)
    # New exit signals will be appended later; don't overwrite remaining yet

    # ── Step 3: ① OPEN — execute yesterday's pending entries ─────────────────
    entries_executed = execute_pending_entries(state, pos_data, today)

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
        universe_df = pd.read_csv(_UNIVERSE)
        active_set  = set(universe_df[universe_df["is_active"] == True]["ticker"].tolist())

        if regime_ok:
            scan_tickers = list(active_set)
            log.info("--- Scanning full universe for new entry signals (BULL) ---")
        elif _bear_exempt:
            # Bear market: only scan exempt tickers that are active in the universe
            # (mirrors backtest: [t for t in universe if t in bear_exempt])
            scan_tickers = [t for t in _bear_exempt if t in active_set]
            log.info(f"--- BEAR regime — scanning exempt tickers only: {scan_tickers} ---")
        else:
            scan_tickers = []
            log.info("  BEAR regime — no new entry signals (no bear-exempt tickers configured)")

        if scan_tickers:
            univ_data = fetch_price_data(scan_tickers, period=args.universe_period)

            # Track any tickers whose data was silently dropped (rate-limit) and
            # schedule them for an automatic retry 1 hour later via pending_retry.
            _missing_tickers = [t for t in scan_tickers if t not in univ_data]
            if _missing_tickers:
                _retry_at   = datetime.now(timezone.utc) + timedelta(hours=1)
                _sgt_offset = timedelta(hours=8)
                state["pending_retry"] = {
                    "tickers":        _missing_tickers,
                    "scan_date":      str(today),
                    "attempt":        1,
                    "next_retry_utc": _retry_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "next_retry_sgt": (_retry_at + _sgt_offset).strftime("%Y-%m-%d %H:%M SGT"),
                    "created_utc":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                log.warning(
                    f"  {len(_missing_tickers)} tickers missing → pending_retry "
                    f"at {state['pending_retry']['next_retry_sgt']}: {_missing_tickers}"
                )
            elif state.get("pending_retry"):
                state.pop("pending_retry")
                log.info("  All tickers downloaded — cleared previous pending_retry")

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
                    "ticker":       sig["ticker"],
                    "signal_date":  str(today),
                    "signal_price": sig["signal_price"],
                    "stop_price":   sig["stop_loss"],
                    "shares":       sig["shares"],
                    "atr":          sig["atr"],
                    "strength":     sig["strength"],
                    "trade_risk":   sig["trade_risk"],
                    "notional":     sig["notional"],
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

    # ── Step 8: build today_signals for website display ───────────────────────
    _today_sig = {
        "date":    str(today),
        "regime":  "BULL" if regime_ok else "BEAR",
        "spy_close": round(spy_close, 2) if spy_close else None,
        "n_candidates":    len(candidates),
        "n_entries":       len(new_pending),           # entry signals pending for tomorrow
        "n_executed":      len(entries_executed),      # entries executed today at open
        "n_exits":         len(new_exit_signals),      # exit signals pending for tomorrow
        "n_raw_breakouts": scan_stats["n_raw_breakouts"],  # breakouts before portfolio constraints
        "n_heat_blocked":  scan_stats["n_heat_blocked"],   # blocked by heat limit
        "n_cash_blocked":  scan_stats.get("n_cash_blocked", 0),  # blocked by cash (legacy field)
        "n_corr_reduced":  scan_stats["n_corr_reduced"],   # size reduced by correlation filter

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
            "strength":     p.get("strength"),
        } for p in new_pending],
    }
    state["today_signals"] = _today_sig

    _sig_hist = [s for s in state.get("signals_history", []) if s["date"] != str(today)]
    _sig_hist.append(_today_sig)
    state["signals_history"] = sorted(_sig_hist, key=lambda x: x["date"])

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
