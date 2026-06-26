"""策略1.0模拟交易监控"""

import sys, json
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.style import show_df
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from src.strategy.params import StrategyParams as _StrategyParams
from src.indicators.atr import compute_atr as _compute_atr

_results  = _root / "results" / "v1_unbiased_60m_2000"
_pt_dir   = _root / "results" / "paper_trading"
_m1_file  = _pt_dir / "positions.json"
_m2_file  = _pt_dir / "ib_state.json"

_meta_path = _results / "strategy_meta.json"
_ETF_SET: set = set()
if _meta_path.exists():
    _ETF_SET = {e["ticker"] for e in json.loads(_meta_path.read_text()).get("etf_universe", [])}

def _asset_type(ticker: str) -> str:
    return "ETF" if ticker in _ETF_SET else "股票"

# Read all display-critical parameters from StrategyParams — the single source of truth
# used by both the backtest engine and the paper trading daily script.
_V1_PARAMS  = _StrategyParams()
_TRAIL_R1   = _V1_PARAMS.trail_multiplier_r1   # 3.0
_TRAIL_R3   = _V1_PARAMS.trail_multiplier_r3   # 3.0
_TRAIL_R5   = _V1_PARAMS.trail_multiplier_r5   # 5.0
_ATR_PERIOD = _V1_PARAMS.atr_period            # 20
_SMA_WINDOW = _V1_PARAMS.regime_sma_window     # 200

# ─────────────────────────────────────────────────────────────────────────────
st.title("策略1.0 模拟交易监控")
st.markdown("同时运行两种模拟交易方法，互相验证信号与执行质量")

tab1, tab2 = st.tabs(["📊 方法一：手动跟踪（Yahoo Finance）", "🤖 方法二：IB 自动交易（Interactive Brokers）"])

# ═══════════════════════════════════════════════════════════════════════════════
# ── Shared helpers ─────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _build_method_zip(data: dict, method: str) -> bytes:
    import zipfile, io, csv
    from datetime import date as _d

    def _rows_to_csv(rows: list, fieldnames: list) -> bytes:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue().encode("utf-8-sig")

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{method}_raw.json",
                    json.dumps(data, ensure_ascii=False, indent=2))

        nav_h = data.get("nav_history", [])
        if nav_h:
            zf.writestr(f"{method}_nav_history.csv",
                _rows_to_csv(nav_h, ["date", "nav", "regime", "spy_close"]))

        sh = data.get("signals_history", [])
        if sh:
            zf.writestr(f"{method}_signals_history.csv",
                _rows_to_csv(sh, [
                    "date", "regime", "spy_close",
                    "n_raw_breakouts",              # raw breakouts before portfolio constraints
                    "n_candidates",                 # passed all portfolio constraints (approved)
                    "n_heat_blocked", "n_cash_blocked", "n_corr_reduced",
                    "n_entries", "n_executed", "n_exits",
                ]))

        # Today's full breakout candidate list: all tickers that passed per-stock filters,
        # with per-ticker rejection reason (None = approved, heat_limit, cash_limit, corr_reduced).
        # This is the detailed view of the most recent day's signal funnel.
        _ts = data.get("today_signals", {})
        _cands = _ts.get("candidate_signals", [])
        if _cands:
            zf.writestr(f"{method}_today_candidate_signals.csv",
                _rows_to_csv(_cands, [
                    "ticker", "signal_price", "stop_price", "shares", "trade_risk", "rejection",
                ]))

        ct = data.get("closed_trades", [])
        if ct:
            zf.writestr(f"{method}_closed_trades.csv",
                _rows_to_csv(ct, list(ct[0].keys())))

        op = [p for p in data.get("positions", []) if not p.get("closed")]
        if op:
            zf.writestr(f"{method}_open_positions.csv",
                _rows_to_csv(op, list(op[0].keys())))

        # 开仓历史：持仓中 + 已平仓的开仓数据合并（closed trades now carry signal_price & atr_at_entry）
        _entry_hist = sorted([
            {"ticker": p["ticker"],
             "signal_date": p.get("signal_date", ""), "signal_price": p.get("signal_price", ""),
             "entry_date": p["entry_date"], "open_price": p.get("open_price", ""), "entry_price": p["entry_price"],
             "shares": p["shares"], "stop_loss": p.get("stop_loss", ""),
             "atr_at_entry": p.get("atr_at_entry", ""), "status": "open"}
            for p in op
        ] + [
            {"ticker": c["ticker"],
             "signal_date": c.get("signal_date", ""), "signal_price": c.get("signal_price", ""),
             "entry_date": c.get("entry_date", ""), "entry_price": c.get("entry_price", ""),
             "shares": c.get("shares", ""), "stop_loss": c.get("stop_loss", c.get("initial_stop", "")),
             "open_price": c.get("open_price", ""), "atr_at_entry": c.get("atr_at_entry", ""),
             "status": "closed"}
            for c in ct
        ], key=lambda x: x["entry_date"], reverse=True)
        if _entry_hist:
            zf.writestr(f"{method}_entry_history.csv",
                _rows_to_csv(_entry_hist,
                    ["ticker","signal_date","signal_price","entry_date","open_price","entry_price",
                     "shares","stop_loss","atr_at_entry","status"]))

        # ── 回测参考数据（用于过拟合分析：以回测分布为基准，比较模拟交易表现）──────────
        for _bt_fname in ("metrics.json", "trades.csv", "nav.csv"):
            _bt_path = _results / _bt_fname
            if _bt_path.exists():
                zf.writestr(f"backtest_reference_{_bt_fname}", _bt_path.read_bytes())

    return zbuf.getvalue()

_YF_FETCH_FILE = Path(__file__).resolve().parents[3] / "results" / "paper_trading" / "last_yf_fetch.json"

@st.cache_data(ttl=3600)
def _fetch_yf(tickers: tuple, period: str = "300d"):
    """Returns (DataFrame, fetch_time_sgt_str). Both are cached together for 1 hour.
    Also persists the fetch timestamp to last_yf_fetch.json so it survives page reloads."""
    from datetime import datetime, timezone, timedelta
    import yfinance as yf
    _sgt = timezone(timedelta(hours=8))
    _fetch_time = datetime.now(_sgt).strftime("%Y-%m-%d %H:%M 新加坡时间（SGT，UTC+8）")
    if not tickers:
        return pd.DataFrame(), _fetch_time
    _df = yf.download(list(tickers), period=period, auto_adjust=True, progress=False)
    # Persist timestamp — this block only runs on a real download (cache miss), not on cache hits
    try:
        _YF_FETCH_FILE.parent.mkdir(parents=True, exist_ok=True)
        _YF_FETCH_FILE.write_text(
            json.dumps({"last_fetch_sgt": _fetch_time}, ensure_ascii=False)
        )
    except Exception:
        pass
    return _df, _fetch_time


def _us_open_to_sgt(date_str: str) -> str:
    """把交易日（美股开盘 9:30 AM 美东时间）转换为新加坡时间字符串，自动处理夏/冬令时。"""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    try:
        _et  = ZoneInfo("America/New_York")
        _sgt = ZoneInfo("Asia/Singapore")
        _dt_sgt = datetime.strptime(date_str, "%Y-%m-%d") \
                           .replace(hour=9, minute=30, tzinfo=_et) \
                           .astimezone(_sgt)
        return _dt_sgt.strftime("%Y-%m-%d %H:%M SGT")
    except Exception:
        return date_str  # 无法转换时退回纯日期


def _us_close_to_sgt(date_str: str) -> str:
    """把信号日（美股收盘 4:00 PM 美东时间）转换为新加坡时间字符串，自动处理夏/冬令时。
    夏令时：4:00 PM EDT = 次日 04:00 SGT；冬令时：4:00 PM EST = 次日 05:00 SGT。"""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    try:
        _et  = ZoneInfo("America/New_York")
        _sgt = ZoneInfo("Asia/Singapore")
        _dt_sgt = datetime.strptime(date_str, "%Y-%m-%d") \
                           .replace(hour=16, minute=0, tzinfo=_et) \
                           .astimezone(_sgt)
        return _dt_sgt.strftime("%Y-%m-%d %H:%M SGT")
    except Exception:
        return date_str


def _get_df(raw: pd.DataFrame, ticker: str):
    if raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        if ticker not in raw.columns.get_level_values(1):
            return None
        df = raw.xs(ticker, level=1, axis=1).dropna(subset=["Close"])
    else:
        df = raw.dropna(subset=["Close"])
    return df if not df.empty else None


def _enrich_position(pos: dict, raw_yf: pd.DataFrame) -> dict:
    """Add live price + computed trailing/hard stop to a position dict.

    Mirrors backtest dual-stop logic exactly:
      - stop_loss:  fixed hard stop (intraday low trigger)
      - trail_stop: trailing stop that ratchets up (close trigger)
      - R-multiple for trail_mult selection uses highest_high (peak), not current close
      - entry_price is slip-adjusted so R = entry_price - stop_loss = 2×ATR exactly
    """
    df = _get_df(raw_yf, pos["ticker"])

    # Backward-compatibility: migrate old schema fields on the fly
    if "stop_loss" not in pos:
        pos = {**pos, "stop_loss": pos.get("initial_stop_loss", 0.0)}
    if "trail_stop" not in pos:
        pos = {**pos, "trail_stop": pos.get("current_stop_loss", pos["stop_loss"])}
    if "highest_high" not in pos:
        pos = {**pos, "highest_high": pos.get("peak_price", pos["entry_price"])}

    R_base = pos["entry_price"] - pos["stop_loss"]   # = 2×ATR; both slip-adjusted

    def _compute_stop(peak: float, atr: float, stored_trail: float) -> tuple[float, float, float]:
        """Returns (effective_stop, trail_stop_live, trail_mult)."""
        r_mult_peak = (peak - pos["entry_price"]) / R_base if R_base > 0 else 0.0
        tm = _TRAIL_R5 if r_mult_peak >= 3.0 else (_TRAIL_R3 if r_mult_peak >= 1.0 else _TRAIL_R1)
        trail_live = max(stored_trail, peak - tm * atr)
        effective  = max(pos["stop_loss"], trail_live)   # hard stop may be binding early on
        return effective, trail_live, tm

    # Fallback when YF fetch fails — only close price available, no intraday low
    # Hard stop approximated with close (same as trailing stop check); mark stale
    if df is None:
        fallback = pos.get("last_known_price")
        if not fallback:
            return {**pos, "_ok": False}
        peak_hh = pos["highest_high"]
        eff_stop, trail_live, tm = _compute_stop(peak_hh, pos["atr_at_entry"], pos["trail_stop"])
        R = (fallback - pos["entry_price"]) / R_base if R_base > 0 else 0.0
        # Without intraday low, approximate: triggered if close < stop_loss OR close < trail_stop
        if fallback < pos["stop_loss"]:
            stop_reason = "stop_loss"
        elif fallback < trail_live:
            stop_reason = "trailing_stop"
        else:
            stop_reason = None
        return {
            **pos,
            "_ok":             True,
            "_stale":          True,
            "current_price":   fallback,
            "current_date":    pos.get("last_price_date", "N/A"),
            "highest_high":    peak_hh,
            "current_atr":     pos["atr_at_entry"],
            "current_stop":    eff_stop,
            "trail_stop_live": trail_live,
            "trail_mult":      tm,
            "R":               R,
            "mkt_value":       fallback * pos["shares"],
            "unreal_pnl":      (fallback - pos["entry_price"]) * pos["shares"],
            "stop_buffer_pct": (fallback - eff_stop) / fallback * 100,
            "is_stopped":      stop_reason is not None,
            "stop_reason":     stop_reason,
        }

    # Compare dates only to avoid timezone mismatch between yfinance (tz-aware) and entry_date (tz-naive)
    entry_d     = pd.to_datetime(pos["entry_date"]).date()
    since_entry = df[pd.to_datetime(df.index).date >= entry_d] if not df.empty else df
    if since_entry.empty:
        fallback = pos.get("last_known_price")
        if not fallback:
            return {**pos, "_ok": False}
        peak_hh = pos["highest_high"]
        eff_stop, trail_live, tm = _compute_stop(peak_hh, pos["atr_at_entry"], pos["trail_stop"])
        R = (fallback - pos["entry_price"]) / R_base if R_base > 0 else 0.0
        if fallback < pos["stop_loss"]:
            stop_reason = "stop_loss"
        elif fallback < trail_live:
            stop_reason = "trailing_stop"
        else:
            stop_reason = None
        return {
            **pos,
            "_ok":             True,
            "_stale":          True,
            "current_price":   fallback,
            "current_date":    pos.get("last_price_date", "N/A"),
            "highest_high":    peak_hh,
            "current_atr":     pos["atr_at_entry"],
            "current_stop":    eff_stop,
            "trail_stop_live": trail_live,
            "trail_mult":      tm,
            "R":               R,
            "mkt_value":       fallback * pos["shares"],
            "unreal_pnl":      (fallback - pos["entry_price"]) * pos["shares"],
            "stop_buffer_pct": (fallback - eff_stop) / fallback * 100,
            "is_stopped":      stop_reason is not None,
            "stop_reason":     stop_reason,
        }

    cur_price    = float(since_entry["Close"].iloc[-1])
    low_today    = float(since_entry["Low"].iloc[-1])
    cur_date     = str(since_entry.index[-1].date())
    highest_high = max(pos["highest_high"], float(since_entry["High"].max()))

    atr_s   = _compute_atr(df["High"], df["Low"], df["Close"], _ATR_PERIOD)
    cur_atr = float(atr_s.iloc[-1])
    if pd.isna(cur_atr):
        cur_atr = pos["atr_at_entry"]

    eff_stop, trail_live, tm = _compute_stop(highest_high, cur_atr, pos["trail_stop"])

    # Dual-trigger — matches strategy description and backtest exit.py exactly:
    #   Priority 1: hard stop  — intraday low[t] < stop_loss
    #   Priority 2: trail stop — close[t]         < trail_stop
    if low_today < pos["stop_loss"]:
        stop_reason = "stop_loss"
    elif cur_price < trail_live:
        stop_reason = "trailing_stop"
    else:
        stop_reason = None
    is_stopped = stop_reason is not None

    # Display R: unrealized gain in units of initial risk (uses current close, not peak)
    R = (cur_price - pos["entry_price"]) / R_base if R_base > 0 else 0.0

    return {
        **pos,
        "_ok":             True,
        "current_price":   cur_price,
        "current_date":    cur_date,
        "highest_high":    highest_high,
        "current_atr":     cur_atr,
        "current_stop":    eff_stop,
        "trail_stop_live": trail_live,
        "trail_mult":      tm,
        "R":               R,
        "mkt_value":       cur_price * pos["shares"],
        "unreal_pnl":      (cur_price - pos["entry_price"]) * pos["shares"],
        "stop_buffer_pct": (cur_price - eff_stop) / cur_price * 100,
        "is_stopped":      is_stopped,
        "stop_reason":     stop_reason,
    }


@st.cache_data(ttl=86400)
def _load_bt():
    with open(_results / "metrics.json") as f:
        m = json.load(f)
    nav = pd.read_csv(_results / "nav.csv", index_col=0, parse_dates=True)
    spy = pd.read_csv(_results / "spy_nav.csv", index_col=0, parse_dates=True)
    trades = pd.read_csv(_results / "trades.csv", parse_dates=["entry_date", "exit_date"])
    return m, nav, spy, trades


try:
    _bm, _bt_nav, _bt_spy, _bt_trades = _load_bt()
except FileNotFoundError:
    st.error("⚠️ 回测结果文件缺失，无法加载基准数据。请确认 `results/v1_unbiased_60m_2000/` 目录已同步到 GitHub。")
    st.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — 方法一：手动跟踪（Yahoo Finance）
# ═══════════════════════════════════════════════════════════════════════════════

with tab1:
    st.markdown("""
    **运行方式：** 由 **GitHub Actions 自动运行**，每个交易日美东时间收盘后自动触发（夏令时 7:00 PM / 冬令时 6:00 PM，即新加坡时间次日早上 **7:00 AM**），
    无需任何手动操作。运行结果自动推送到 GitHub，本页面随即刷新。

    **初始资金：** $200,000 USD（全新独立账户，调试期 2026-06-19 起，正式启动 2026-07-01）
    """)

    with st.expander("⚙️ 自动化配置说明"):
        st.markdown("""
**GitHub Actions 自动运行**（无需任何手动操作）

- 工作流文件：`.github/workflows/paper_trading_m1.yml`
- 触发时间：每个交易日 **夏令时 7:00 PM / 冬令时 6:00 PM**（23:00 UTC）自动运行，确保 Yahoo Finance 收盘数据已就绪
- 运行内容：下载 Yahoo Finance 数据 → 计算信号 → 更新 positions.json → 自动推送到 GitHub
- 也可在 GitHub → Actions → "Paper Trading M1" 页面手动触发

如需临时手动运行（调试用）：
```bash
python src/scripts/paper_trading_daily.py --date YYYY-MM-DD
```
""")

    # ── Load Method 1 state ──────────────────────────────────────────────────
    @st.cache_data(ttl=120)
    def _load_m1():
        if _m1_file.exists():
            return json.loads(_m1_file.read_text()), False
        # Fallback: empty $200K fresh state
        return {
            "initial_nav": 200000.0, "cash": 200000.0,
            "positions": [], "closed_trades": [],
            "nav_history": [{"date": "2026-06-19", "nav": 200000.0}],
            "last_update_date": "尚未运行",
        }, True

    _m1, _m1_fallback = _load_m1()
    if _m1_fallback:
        st.info("ℹ️ positions.json 尚未生成，等待 GitHub Actions 首次运行后自动创建。")

    _m1_positions  = [p for p in _m1["positions"] if not p.get("closed")]
    _m1_closed     = _m1.get("closed_trades", [])
    _m1_history    = _m1.get("nav_history", [])
    _m1_cash       = _m1.get("cash", 0.0)
    _m1_init_nav   = _m1["initial_nav"]
    _m1_last_upd_raw = _m1.get("last_update_utc") or ""   # guard against JSON null
    if _m1_last_upd_raw:
        from datetime import datetime, timezone, timedelta
        _sgt = timezone(timedelta(hours=8))
        _m1_last_upd = (datetime.strptime(_m1_last_upd_raw, "%Y-%m-%dT%H:%M:%SZ")
                        .replace(tzinfo=timezone.utc)
                        .astimezone(_sgt)
                        .strftime("%Y-%m-%d %H:%M 新加坡时间（SGT，UTC+8）"))
    else:
        # last_update_utc not yet written by this run; fall back to date-only field
        _m1_last_upd = _m1.get("last_update_date", "N/A") + "（仅限日期，时间不详）"
    _m1_today_sig  = _m1.get("today_signals")

    # ── Fetch live prices ────────────────────────────────────────────────────
    _m1_tickers = tuple(sorted(set([p["ticker"] for p in _m1_positions] + ["SPY"])))
    with st.spinner("从 Yahoo Finance 加载行情…"):
        _m1_raw, _m1_fetch_time = _fetch_yf(_m1_tickers, "300d")

    _m1_live = [_enrich_position(p, _m1_raw) for p in _m1_positions]
    _m1_ok   = [p for p in _m1_live if p.get("_ok")]
    _m1_act  = [p for p in _m1_ok if not p["is_stopped"]]
    _m1_stop = [p for p in _m1_ok if p["is_stopped"]]

    # SPY regime
    _spy_df    = _get_df(_m1_raw, "SPY")
    _spy_close = None; _spy_sma = None; _bull = False
    if _spy_df is not None and len(_spy_df) >= _SMA_WINDOW:
        _spy_close = float(_spy_df["Close"].iloc[-1])
        _spy_sma   = float(_spy_df["Close"].rolling(_SMA_WINDOW).mean().iloc[-1])
        _bull      = _spy_close > _spy_sma

    _m1_mkt   = sum(p["mkt_value"] for p in _m1_ok)
    _m1_unrl  = sum(p["unreal_pnl"] for p in _m1_ok)
    _m1_cost  = sum(p["entry_price"] * p["shares"] for p in _m1_ok)
    _m1_nav   = _m1_mkt + _m1_cash
    _m1_date  = max((p.get("current_date", "") for p in _m1_ok), default="N/A")
    _m1_stale = any(p.get("_stale") for p in _m1_ok)

    # 优先从持久化文件读取上次下载时间；文件不存在时回退到本次会话的缓存时间戳
    try:
        _last_fetch_sgt = json.loads(_YF_FETCH_FILE.read_text())["last_fetch_sgt"]
    except Exception:
        _last_fetch_sgt = _m1_fetch_time

    st.subheader("一、策略状态概览")
    st.markdown(f"上次更新：{_last_fetch_sgt} ｜ Yahoo Finance")

    # Current drawdown from all-time peak (nav_history + live nav)
    _all_nav_vals = [float(h["nav"]) for h in _m1_history] + [_m1_nav]
    _peak_nav     = max(_all_nav_vals) if _all_nav_vals else _m1_nav
    _cur_dd       = (_m1_nav / _peak_nav - 1) * 100 if _peak_nav > 0 else 0.0

    # Portfolio heat = total dollar risk across positions / nav
    _heat_used_abs  = sum((p["entry_price"] - p["stop_loss"]) * p["shares"] for p in _m1_ok)
    _heat_pct       = _heat_used_abs / _m1_nav * 100 if _m1_nav > 0 else 0.0
    _heat_limit_pct = _V1_PARAMS.heat_limit * 100        # e.g. 10%
    _heat_rem_pct   = _heat_limit_pct - _heat_pct
    _risk_per_trade_pct = _V1_PARAMS.risk_per_trade * 100  # e.g. 1%
    _slots_left     = int(_heat_rem_pct / _risk_per_trade_pct) if _risk_per_trade_pct > 0 else 0

    _nav_pnl_pct = (_m1_nav / _m1_init_nav - 1) * 100
    _nav_pnl_usd = _m1_nav - _m1_init_nav
    _nav_label = f"净值（{_m1_date} 最后记录价格）" if _m1_stale else "净值"

    # 每日净值变化：当前净值 vs nav_history 最新一条（上一个交易日收盘净值）
    _prev_nav = float(_m1_history[-1]["nav"]) if _m1_history else _m1_init_nav
    _daily_chg_pct = (_m1_nav / _prev_nav - 1) * 100 if _prev_nav > 0 else 0.0
    _prev_date = _m1_history[-1]["date"] if _m1_history else "—"

    c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
    c1.metric("每日净值变化（%）", f"{_daily_chg_pct:+.2f}%",
              delta=f"vs {_prev_date} 收盘")
    c2.metric(_nav_label, f"${_m1_nav/1e6:.2f}M")
    c3.metric("净值浮盈（%）", f"{_nav_pnl_pct:+.2f}%", delta="vs 起始资金")
    c4.metric("净值浮盈（$）", f"${_nav_pnl_usd:+,.0f}")
    c5.metric("距历史峰值", f"{_cur_dd:.2f}%",
              delta="当前在历史高点" if _cur_dd >= -0.01 else f"峰值 ${_peak_nav/1e6:.3f}M")
    c6.metric("持仓数量", f"{len(_m1_ok)} 只",
              delta=f"其中 {len(_m1_stop)} 只触止损" if _m1_stop else None,
              delta_color="inverse" if _m1_stop else "normal")
    c7.metric("持仓市值", f"${_m1_mkt/1e6:.2f}M",
              delta=f"占 NAV {_m1_mkt/_m1_nav*100:.1f}%" if _m1_nav else None)
    c8.metric("现金", f"${_m1_cash/1e6:.2f}M")

    # Portfolio heat progress bar
    _hfill   = min(_heat_pct / _heat_limit_pct, 1.0) * 100
    _hcolor  = "#d62728" if _heat_pct > _heat_limit_pct * 0.85 else ("#ff7f0e" if _heat_pct > _heat_limit_pct * 0.6 else "#2ca02c")
    st.markdown(
        f"<div style='margin:10px 0 4px'>"
        f"<span style='color:#111;font-size:0.88em'><b>组合热度（风险预算）</b>："
        f"已用 <b>{_heat_pct:.1f}%</b> / 上限 {_heat_limit_pct:.0f}%，"
        f"剩余 <b>{_heat_rem_pct:.1f}%</b>（约可新开 <b>{_slots_left}</b> 笔）</span>"
        f"<div style='background:#e0e0e0;border-radius:4px;height:8px;margin-top:5px'>"
        f"<div style='background:{_hcolor};width:{_hfill:.0f}%;height:8px;border-radius:4px'></div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # ── Today's trades (executions at today's open) ───────────────────────────
    st.subheader("二、今日完成的交易")
    _trade_rows = []
    if _m1_today_sig:
        _ts_trade_date     = _m1_today_sig.get("date", "N/A")
        _ts_trade_datetime = _us_open_to_sgt(_ts_trade_date)
        # New schema: exits_executed / entries_executed (executed at T+1 open with slippage+commission)
        # Old schema fallback: exits (same-day, no slip/comm) / entries (executed at open)
        _exits_exec   = _m1_today_sig.get("exits_executed") or []
        _entries_exec = _m1_today_sig.get("entries_executed") or _m1_today_sig.get("entries", [])
        for e in _exits_exec:
            _open_px  = e.get("exit_open")
            _fill_px  = e.get("exit_price")
            _reason   = e.get("exit_reason", "")
            _reason_label = {"stop_loss": "🔴 触止损", "trailing_stop": "🔴 触移动止盈"}.get(_reason, _reason)
            _pnl_r    = e.get("pnl_r")
            _net_pnl  = e.get("net_pnl")
            _trade_rows.append({
                "交易日期/时间": _ts_trade_datetime,
                "方向": "🔴 卖出",
                "标的": e["ticker"],
                "类型": _asset_type(e["ticker"]),
                "成交量": e.get("shares", ""),
                "开盘价（无滑点）": f"${_open_px:.2f}" if _open_px else "—",
                "成交价（有滑点）": f"${_fill_px:.2f}" if _fill_px else "—",
                "原因": _reason_label,
                "盈亏（R）": f"{_pnl_r:+.2f}R" if _pnl_r is not None else "—",
                "净盈亏（$）": f"${_net_pnl:+,.0f}" if _net_pnl is not None else "—",
            })
        for e in _entries_exec:
            _open_px  = e.get("open_price")
            _entry_px = e.get("entry_price")
            _stop     = e.get("stop_price")
            _sig_px   = e.get("signal_price")
            _shares   = e.get("shares", 0)
            _risk_pct = e.get("trade_risk")
            # "原因" reflects the actual entry trigger per strategy description Section 4:
            # adj_close[t] > max(adj_high[t-200:t-1]) → 突破200日高点
            if _sig_px and _stop:
                _entry_reason = f"突破200日高点（信号收盘 ${_sig_px:.2f}，止损 ${_stop:.2f}）"
            elif _stop:
                _entry_reason = f"突破200日高点（止损 ${_stop:.2f}）"
            else:
                _entry_reason = "突破200日高点"
            _trade_rows.append({
                "交易日期/时间": _ts_trade_datetime,
                "方向": "🟢 买入",
                "标的": e["ticker"],
                "类型": _asset_type(e["ticker"]),
                "成交量": _shares,
                "开盘价（无滑点）": f"${_open_px:.2f}" if _open_px else "—",
                "成交价（有滑点）": f"${_entry_px:.2f}" if _entry_px else "—",
                "原因": _entry_reason,
                "盈亏（R）": "—",
                "净盈亏（$）": f"风险 {_risk_pct*100:.2f}% NAV" if _risk_pct else "—",
            })
    if _trade_rows:
        show_df(pd.DataFrame(sorted(_trade_rows, key=lambda x: (0 if "卖出" in x["方向"] else 1, x["标的"]))), use_container_width=True, hide_index=True)
    else:
        st.info("今日无交易（今日开盘时无来自昨日的挂单）")

    st.markdown("---")

    # ── Tomorrow's orders ────────────────────────────────────────────────────
    st.subheader("三、明日要执行的交易")
    import datetime as _dt

    # New schema: pending_exits + pending_entries (both from today's close detections)
    _pend_exits   = _m1.get("pending_exits", [])
    _pend_entries = _m1.get("pending_entries", [])

    # 执行日 = signal_date 后的下一个交易日（不是 date.today()+1）
    # 优先从 pending 订单的 signal_date 推算，确保跨天查看时日期正确
    _sig_date_str = None
    if _pend_entries:
        _sig_date_str = _pend_entries[0].get("signal_date")
    elif _pend_exits:
        _sig_date_str = _pend_exits[0].get("detected_date") or _pend_exits[0].get("signal_date")
    if _sig_date_str:
        _sig_d = _dt.date.fromisoformat(_sig_date_str)
        _next_td = _sig_d + _dt.timedelta(days=1)
        while _next_td.weekday() >= 5:
            _next_td += _dt.timedelta(days=1)
    else:
        _today_dt = _dt.date.today()
        _next_td  = _today_dt + _dt.timedelta(days=1)
        while _next_td.weekday() >= 5:
            _next_td += _dt.timedelta(days=1)

    _next_td_sgt = _us_open_to_sgt(str(_next_td))
    st.markdown(f"<span style='color:#111111'>执行日/时间：{_next_td_sgt} 开盘 ｜ 以下订单在开盘后按市价执行</span>", unsafe_allow_html=True)
    _order_rows   = []

    # ① 平仓优先（策略描述：T+1 开盘先执行平仓，再执行开仓）
    for s in sorted(_pend_exits, key=lambda x: x["ticker"]):
        _reason = s.get("exit_reason", "")
        _reason_label = {"stop_loss": "止损触发", "trailing_stop": "移动止盈触发"}.get(_reason, _reason)
        _order_rows.append({
            "操作": "🔴 平仓卖出",
            "标的": s["ticker"],
            "股数": s.get("shares", ""),
            "参考价": f"${s['stop_used']:.2f}" if s.get("stop_used") else "—",
            "总金额": f"${s.get('shares', 0) * s.get('stop_used', 0):,.0f}" if s.get("stop_used") else "—",
            "订单类型": "市价单（开盘执行）",
            "备注": _reason_label,
        })

    # ② 开仓按突破强度（strength = 信号收盘 ÷ 200日最高价）从高到低排序，模拟现金流逐笔判断
    # 预计T+1可用现金 = 当前现金 + 所有平仓回款（以止损价估算），只显示现金够用的开仓
    _exit_proceeds_proj = sum(s.get("shares", 0) * s.get("stop_used", 0) for s in _pend_exits)
    _proj_cash = _m1_cash + _exit_proceeds_proj
    _blocked_entries = []
    # 从 candidate_signals 建立 ticker → {rejection, corr_with} 映射，用于备注说明
    _cand_meta = {
        c["ticker"]: {"rejection": c.get("rejection"), "corr_with": c.get("corr_with")}
        for c in (_m1_today_sig or {}).get("candidate_signals", [])
    }
    for e in sorted(_pend_entries, key=lambda x: x.get("strength", 0), reverse=True):
        _strength    = e.get("strength", 0)
        _strength_str = f"突破强度 {_strength:.4f}，" if _strength else ""
        _cost        = e.get("shares", 0) * e.get("signal_price", 0)
        _meta        = _cand_meta.get(e["ticker"], {})
        if _meta.get("rejection") == "corr_reduced":
            _corr_with = _meta.get("corr_with")
            _corr_note = f"⚠️ 相关性减仓（×0.5，与 {_corr_with} 相关），" if _corr_with else "⚠️ 相关性减仓（×0.5），"
        else:
            _corr_note = ""
        if _proj_cash >= _cost:
            _proj_cash -= _cost
            _order_rows.append({
                "操作":     "🟢 开仓买入",
                "标的":     e["ticker"],
                "股数":     e.get("shares", ""),
                "参考价":   f"${e['signal_price']:.2f}" if e.get("signal_price") else "—",
                "总金额":   f"${_cost:,.0f}",
                "订单类型": "市价单（开盘执行）",
                "备注":     (f"{_corr_note}{_strength_str}止损 ${e['stop_price']:.2f}，风险 {e['trade_risk']*100:.2f}% NAV"
                             if e.get("stop_price") else "—"),
            })
        else:
            _blocked_entries.append(e["ticker"])

    # 加入执行顺序列（第一列）
    for _i, _row in enumerate(_order_rows):
        _row["执行顺序"] = _i + 1

    if _order_rows:
        _ord_cols = ["执行顺序", "操作", "标的", "股数", "参考价", "总金额", "订单类型", "备注"]
        show_df(pd.DataFrame(_order_rows)[_ord_cols], use_container_width=True, hide_index=True)

        n_sell      = len(_pend_exits)
        n_buy       = len(_pend_entries) - len(_blocked_entries)
        n_blocked   = len(_blocked_entries)
        _total_sell = sum(s.get("shares", 0) * s.get("stop_used", 0) for s in _pend_exits)
        _exec_entries = [e for e in _pend_entries if e["ticker"] not in _blocked_entries]
        _total_buy  = sum(e.get("shares", 0) * e.get("signal_price", 0) for e in _exec_entries)
        _net        = _total_buy - _total_sell
        _cash_after = _m1_cash + _total_sell - _total_buy
        st.markdown(
            f"共 {n_sell} 笔平仓、{n_buy} 笔开仓，合计 {n_sell+n_buy} 笔订单　｜　"
            f"预计卖出回款 \\${_total_sell:,.0f}，买入支出 \\${_total_buy:,.0f}，"
            f"净资金变动 {'−' if _net > 0 else '+'}\\${abs(_net):,.0f}，"
            f"执行后剩余现金 \\${_cash_after:,.0f}"
        )
        if _blocked_entries:
            # 热度拦截数：从今日信号的 candidate_signals 里统计
            _cands_for_heat = (_m1_today_sig or {}).get("candidate_signals", [])
            _n_heat_blocked = sum(1 for c in _cands_for_heat if c.get("rejection") == "heat_limit")
            _heat_tickers   = [c["ticker"] for c in _cands_for_heat if c.get("rejection") == "heat_limit"]
            _n_total_skipped = _n_heat_blocked + n_blocked
            _heat_line = (f"其中 **{_n_heat_blocked} 笔**因组合热度上限已由每日脚本拒绝"
                          f"（{', '.join(_heat_tickers)}）；" if _n_heat_blocked else "")
            st.warning(
                f"⚠️ 共 **{_n_total_skipped} 笔**开仓不执行：{_heat_line}"
                f"**{n_blocked} 笔**因现金不足从本表格移除（{', '.join(_blocked_entries)}）。\n\n"
                f"预计T+1可用现金（当前现金 \\${_m1_cash:,.0f} + 平仓回款 \\${_exit_proceeds_proj:,.0f}"
                f" = \\${_m1_cash + _exit_proceeds_proj:,.0f}）不够支付全部开仓，"
                f"已按突破强度由高到低优先执行前 {n_buy} 笔。"
            )
    else:
        st.info("明日无需执行任何交易")

    st.markdown("---")

    # ── Today's signals (detected at close, pending for tomorrow) ────────────
    st.subheader("四、今日开平仓信号")
    if _m1_today_sig:
        _ts_date   = _m1_today_sig.get("date", "N/A")
        _ts_regime = _m1_today_sig.get("regime", "N/A")
        # exit_signals / candidate_signals / entry_signals: new schema (detected at close, pending tomorrow)
        # Always fall back to pending_exits/pending_entries as canonical source.
        _ts_exit_sigs    = _m1_today_sig.get("exit_signals")      or _m1.get("pending_exits",   [])
        _ts_all_cands    = _m1_today_sig.get("candidate_signals",  [])   # ALL raw breakouts w/ rejection
        _ts_entry_sigs   = _m1_today_sig.get("entry_signals")     or _m1.get("pending_entries", [])

        # Build the approved-ticker set for marking selected candidates
        # Exclude entries blocked by cash constraint (computed in Section 三)
        _approved_tickers = {e["ticker"] for e in _ts_entry_sigs} - set(_blocked_entries)
        if not _approved_tickers:
            _approved_tickers = {p["ticker"] for p in _m1.get("pending_entries", [])} - set(_blocked_entries)

        _ts_regime_str = "🟢 BULL" if _ts_regime == "BULL" else "🔴 BEAR"
        if _spy_close and _spy_sma:
            _ts_gap = (_spy_close / _spy_sma - 1) * 100
            _ts_op  = "＞" if _spy_close > _spy_sma else "＜"
            _ts_regime_str += f"，SPY {_spy_close:.2f} {_ts_op} SMA200 {_spy_sma:.2f}（{_ts_gap:+.1f}%）"
        _ts_datetime_sgt = _us_close_to_sgt(_ts_date) if _ts_date != "N/A" else "N/A"
        st.markdown(f"信号日期/时间：{_ts_datetime_sgt} 盘后 ｜ Regime：{_ts_regime_str}")

        # Tab title: show all-candidate count if available, else approved count
        _entry_tab_label = (
            f"开仓信号（{len(_ts_all_cands)} 笔突破，{len(_approved_tickers)} 笔已选）"
            if _ts_all_cands else
            f"开仓信号（{len(_ts_entry_sigs)} 笔）"
        )
        _tab_exit, _tab_entry = st.tabs([f"平仓信号（{len(_ts_exit_sigs)} 笔）", _entry_tab_label])
        with _tab_exit:
            if _ts_exit_sigs:
                _exit_reason_map = {"stop_loss": "🔴 触止损", "trailing_stop": "🔴 触移动止盈"}
                show_df(pd.DataFrame([{
                    "标的":    s["ticker"],
                    "触发类型": _exit_reason_map.get(s.get("exit_reason", ""), s.get("exit_reason", "")),
                    "参考价":  f"${s['stop_used']:.2f}" if s.get("stop_used") else (
                               f"${s.get('stop_price', 0):.2f}" if s.get("stop_price") else ""),
                    "股数":    s.get("shares", ""),
                    "执行方式": "市价单（次日开盘）",
                } for s in sorted(_ts_exit_sigs, key=lambda x: x["ticker"])]), use_container_width=True, hide_index=True)
            else:
                st.info("今日无退出信号")

        with _tab_entry:
            _rejection_label = {
                None:           "✅ 已选入（次日执行）",
                "corr_reduced": "⚠️ 已选入（相关性减仓）",
                "heat_limit":   "🔴 未选（热度上限）",
                "cash_limit":   "🔴 未选（现金不足）",
            }
            if _ts_all_cands:
                # Full funnel view: all raw breakout candidates with rejection reason
                st.caption(
                    f"共 **{len(_ts_all_cands)}** 只个股触发突破信号（通过全部个股筛选），"
                    f"其中 **{len(_approved_tickers)}** 只通过全部约束被选入（含现金约束），"
                    f"剩余因热度上限或现金不足被跳过。"
                )
                _status_order = {
                    "✅ 已选入（次日执行）":    0,
                    "⚠️ 已选入（相关性减仓）": 1,
                    "🔴 未选（现金不足）":      2,
                    "🔴 未选（热度上限）":      3,
                }
                def _get_status(c):
                    if c["ticker"] in _blocked_entries:
                        return "🔴 未选（现金不足）"
                    return _rejection_label.get(c.get("rejection"), c.get("rejection", "✅ 已选入"))
                _cand_rows = [{
                    "标的":         c["ticker"],
                    "信号价（今收）": f"${c.get('signal_price', 0):.2f}" if c.get("signal_price") else "",
                    "参考止损":      f"${c.get('stop_price', 0):.2f}"   if c.get("stop_price")   else "",
                    "股数":          c.get("shares", ""),
                    "风险% NAV":     f"{c['trade_risk']*100:.2f}%" if c.get("trade_risk") else "",
                    "状态":          _get_status(c),
                    "执行方式":      "市价单（次日开盘）" if c["ticker"] in _approved_tickers else "—",
                } for c in _ts_all_cands]
                _cand_rows.sort(key=lambda r: (_status_order.get(r["状态"], 9), r["标的"]))
                show_df(pd.DataFrame(_cand_rows), use_container_width=True, hide_index=True)
            elif _ts_entry_sigs:
                # Fallback: only approved signals available (old schema or first run)
                st.caption("仅显示已选入信号（候选汇总数据将在下次日脚本运行后更新）")
                show_df(pd.DataFrame([{
                    "标的":    e["ticker"],
                    "信号价（今收）": f"${e.get('signal_price', 0):.2f}" if e.get("signal_price") else "",
                    "参考止损":      f"${e.get('stop_price', 0):.2f}"   if e.get("stop_price")   else "",
                    "股数":          e.get("shares", ""),
                    "风险% NAV":     f"{e['trade_risk']*100:.2f}%" if e.get("trade_risk") else "",
                    "状态":          ("🔴 未选（现金不足）" if e["ticker"] in _blocked_entries
                                      else "✅ 已选入（次日执行）"),
                    "执行方式":      "—" if e["ticker"] in _blocked_entries else "市价单（次日开盘）",
                } for e in sorted(_ts_entry_sigs, key=lambda x: x["ticker"])]), use_container_width=True, hide_index=True)
            else:
                st.info("今日无入场信号")
    else:
        _ts_regime_cap = "🟢 BULL" if _bull else "🔴 BEAR"
        st.markdown(f"信号日期：N/A ｜ Regime：{_ts_regime_cap}")
        _tab_exit, _tab_entry = st.tabs(["平仓信号（0 笔）", "开仓信号（0 笔）"])
        with _tab_exit:
            st.info("无退出信号")
        with _tab_entry:
            st.info("无入场信号")

    st.markdown("---")

    # ── Live positions ───────────────────────────────────────────────────────
    st.subheader("五、当前持仓实时状态")
    if _m1_date and _m1_date != "N/A":
        st.markdown(f"上次更新：{_last_fetch_sgt} ｜ Yahoo Finance（数据截至 {_m1_date} 收盘）")
    if _m1_stop:
        st.warning(f"⚠️ **{len(_m1_stop)} 只已触及止损** — 建议执行止损出场")

    if _m1_ok:
        def _status_label(p: dict) -> str:
            sr = p.get("stop_reason")
            if sr == "stop_loss":      return "🔴 触止损"
            if sr == "trailing_stop":  return "🔴 触移动止盈"
            return "🟢 持有"

        # Default sort: 触止损/触移动止盈 first, then 缓冲 ascending within each group
        import datetime as _dt_pos
        _today_pos = _dt_pos.date.today()
        def _status_sort_key(p):
            sr = p.get("stop_reason")
            if sr == "stop_loss":     return (0, p["stop_buffer_pct"])
            if sr == "trailing_stop": return (1, p["stop_buffer_pct"])
            return (2, p["stop_buffer_pct"])
        _pos_sorted = sorted(_m1_ok, key=_status_sort_key)
        _pos_df = pd.DataFrame([{
            "标的":      p["ticker"],
            "状态":      _status_label(p),
            "当前价":    p["current_price"],
            "止损":      p["stop_loss"],
            "移动止盈":  p["trail_stop_live"],
            "缓冲":      p["stop_buffer_pct"],
            "浮盈(R)":   p["R"],
            "浮盈($)":   p["unreal_pnl"],
            "风险%NAV":  round((p["entry_price"] - p["stop_loss"]) * p["shares"] / _m1_nav * 100, 3) if _m1_nav else 0,
            "持仓天数":  (_today_pos - _dt_pos.date.fromisoformat(p["entry_date"])).days,
            "当前市值":  p["mkt_value"] / 1000,
            "入场日":    p["entry_date"],
            "入场价":    p["entry_price"],
        } for p in _pos_sorted])

        def _style_pos(df):
            s = pd.DataFrame('', index=df.index, columns=df.columns)
            for i, p in enumerate(_pos_sorted):
                s.at[i, "止损" if p["stop_loss"] >= p["trail_stop_live"] else "移动止盈"] = "font-weight: bold"
                if p["stop_buffer_pct"] <= 3.0:
                    s.at[i, "缓冲"] = "color: #d62728; font-weight: bold"
            return s

        show_df(
            _pos_df.style.apply(_style_pos, axis=None),
            column_config={
                "当前价":   st.column_config.NumberColumn(format="$%.2f"),
                "止损":     st.column_config.NumberColumn(format="$%.2f"),
                "移动止盈": st.column_config.NumberColumn(format="$%.2f"),
                "缓冲":     st.column_config.NumberColumn(format="%.1f%%"),
                "浮盈(R)":  st.column_config.NumberColumn(label="浮盈（R）", format="%+.2fR"),
                "浮盈($)":  st.column_config.NumberColumn(label="浮盈（$）", format="$%+.0f"),
                "风险%NAV": st.column_config.NumberColumn(label="风险% NAV", format="%.3f%%"),
                "持仓天数": st.column_config.NumberColumn(format="%d 天"),
                "当前市值": st.column_config.NumberColumn(format="$%.0fK"),
                "入场价":   st.column_config.NumberColumn(format="$%.2f"),
            },
        )
        st.markdown(
            "<span style='color:#111111'>**缓冲** = (当前价 − 有效止损) / 当前价 × 100%，其中有效止损 = max(止损, 移动止盈)（即粗体显示的那个）</span><br>"
            "<span style='color:#111111'>**浮盈（R）** = (当前价 − 入场价) / (入场价 − 止损价)，其中分母 = 2 × ATR = 初始每股风险</span>",
            unsafe_allow_html=True,
        )

        _sorted = sorted(_m1_ok, key=lambda x: x.get("R", 0), reverse=True)
        _fig = go.Figure(go.Bar(
            y=[p["ticker"] for p in _sorted],
            x=[p["R"] for p in _sorted],
            orientation="h",
            marker_color=["#d62728" if p["is_stopped"] else ("#2ca02c" if p["R"] >= 0 else "#ff7f0e")
                          for p in _sorted],
            text=[f"{p['R']:+.2f}R" for p in _sorted],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>R = %{x:+.2f}<extra></extra>",
        ))
        _fig.update_layout(
            title="持仓浮盈（R 倍数，红色 = 触及止损）",
            xaxis_title="R 倍数", height=max(380, len(_sorted) * 26),
            margin=dict(l=70, r=100, t=50, b=40),
            template="plotly_white", showlegend=False,
        )
        st.plotly_chart(_fig, use_container_width=True)

    st.markdown("---")

    # ── Stop detail ──────────────────────────────────────────────────────────
    st.subheader("六、止损/移动止盈明细")
    if _m1_ok:
        _sd_df = pd.DataFrame([{
            "标的":          p["ticker"],
            "状态":          ("🔴 触止损（待次日清仓）" if p.get("stop_reason") == "stop_loss"
                             else ("🔴 触移动止盈（待次日清仓）" if p.get("stop_reason") == "trailing_stop" else "✅ 持仓中")),
            "当前价":        p["current_price"],
            "历史最高":      p["highest_high"],
            "ATR(20)":      p["current_atr"],
            "乘数":          p["trail_mult"],
            "止损":          p["stop_loss"],
            "移动止盈":      p["trail_stop_live"],
            "有效止损/止盈": p["current_stop"],
            "距止损/止盈":   p["stop_buffer_pct"],
        } for p in sorted(_m1_ok, key=lambda x: (
            0 if x.get("stop_reason") == "stop_loss" else
            1 if x.get("stop_reason") == "trailing_stop" else 2,
            x["ticker"]
        ))])
        show_df(_sd_df,
            column_config={
                "当前价":        st.column_config.NumberColumn(format="$%.2f"),
                "历史最高":      st.column_config.NumberColumn(format="$%.2f"),
                "ATR(20)":      st.column_config.NumberColumn(format="$%.2f"),
                "乘数":          st.column_config.NumberColumn(format="%.1fx"),
                "止损":          st.column_config.NumberColumn(format="$%.2f"),
                "移动止盈":      st.column_config.NumberColumn(format="$%.2f"),
                "有效止损/止盈": st.column_config.NumberColumn(format="$%.2f"),
                "距止损/止盈":   st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

    st.markdown("---")

    # ── NAV history ──────────────────────────────────────────────────────────
    if _m1_history:
        st.subheader("七、NAV 走势")
        _nh = pd.DataFrame(_m1_history)
        _nh["date"] = pd.to_datetime(_nh["date"])
        _nh = _nh.sort_values("date").reset_index(drop=True)
        if _m1_date != "N/A" and not (_nh["date"] == pd.to_datetime(_m1_date)).any():
            _nh = pd.concat([_nh, pd.DataFrame([{"date": pd.to_datetime(_m1_date), "nav": _m1_nav}])], ignore_index=True)
        _nh_s = _nh.set_index("date")["nav"]

        _show_spy_m1 = st.checkbox("显示 SPY 基准曲线", value=True, key="m1_nav_show_spy")

        _nav_min_dt_m1 = _nh_s.index[0].to_pydatetime()
        _nav_max_dt_m1 = _nh_s.index[-1].to_pydatetime()
        _has_range_m1  = _nav_min_dt_m1 != _nav_max_dt_m1

        import datetime as _dt_m1nav
        _periods_m1 = [("1年", 1), ("3年", 3), ("5年", 5), ("10年", 10), ("全程", None)]
        _pc_m1 = st.columns([1, 1, 1, 1, 1, 6])
        for _ci_m1, (_lbl_m1, _yrs_m1) in enumerate(_periods_m1):
            with _pc_m1[_ci_m1]:
                if st.button(_lbl_m1, key=f"m1_nav_btn_{_lbl_m1}") and _has_range_m1:
                    _ps_m1 = (_nav_min_dt_m1 if _yrs_m1 is None else
                              max(_nav_min_dt_m1, _nav_max_dt_m1 - _dt_m1nav.timedelta(days=round(365.25 * _yrs_m1))))
                    st.session_state["m1_nav_slider"] = (_ps_m1, _nav_max_dt_m1)

        if _has_range_m1:
            _sel_s_m1, _sel_e_m1 = st.slider(
                "选择时间范围",
                min_value=_nav_min_dt_m1, max_value=_nav_max_dt_m1,
                value=(_nav_min_dt_m1, _nav_max_dt_m1),
                format="YYYY-MM-DD", key="m1_nav_slider",
                label_visibility="collapsed",
            )
            _nav_sl_m1 = _nh_s.loc[_sel_s_m1:_sel_e_m1]
            if len(_nav_sl_m1) < 2:
                _nav_sl_m1 = _nh_s
        else:
            _nav_sl_m1 = _nh_s

        # SPY for comparison (strip timezone from YF index)
        _has_spy_m1 = _show_spy_m1 and _spy_df is not None
        if _has_spy_m1:
            _spy_cmp = _spy_df["Close"].copy()
            _spy_cmp.index = pd.to_datetime(_spy_cmp.index).tz_localize(None) if pd.to_datetime(_spy_cmp.index).tz is not None else pd.to_datetime(_spy_cmp.index)
            if _has_range_m1:
                _spy_sl_m1 = _spy_cmp.loc[_sel_s_m1:_sel_e_m1]
                if len(_spy_sl_m1) < 2:
                    _spy_sl_m1 = _spy_cmp
            else:
                _spy_sl_m1 = _spy_cmp
            if not _spy_sl_m1.empty:
                # 找到策略和 SPY 共同的最早日期，确保两条曲线从同一日期归一化到 1
                _common_start = max(_nav_sl_m1.index[0], _spy_sl_m1.index[0])
                _nav_sl_m1    = _nav_sl_m1[_nav_sl_m1.index >= _common_start]
                _spy_sl_m1    = _spy_sl_m1[_spy_sl_m1.index >= _common_start]
                _spy_norm_m1  = _spy_sl_m1 / float(_spy_sl_m1.iloc[0])
                _spy_dd_m1    = (_spy_sl_m1 - _spy_sl_m1.cummax()) / _spy_sl_m1.cummax() * 100
            else:
                _has_spy_m1 = False

        _nav_norm_m1 = _nav_sl_m1 / float(_nav_sl_m1.iloc[0])
        _dd_m1 = (_nav_sl_m1 - _nav_sl_m1.cummax()) / _nav_sl_m1.cummax() * 100

        _fig_nav = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.65, 0.35], vertical_spacing=0.05,
            subplot_titles=["", ""],
        )
        _fig_nav.add_trace(go.Scatter(
            x=_nav_norm_m1.index, y=_nav_norm_m1.values,
            name="策略1.0（模拟）", mode="lines+markers",
            line=dict(color="#1f77b4", width=2),
            hovertemplate="%{x|%Y-%m-%d}<br>NAV: %{y:.2f}x<extra></extra>",
        ), row=1, col=1)
        if _has_spy_m1:
            _fig_nav.add_trace(go.Scatter(
                x=_spy_norm_m1.index, y=_spy_norm_m1.values,
                name="SPY", line=dict(color="#888888", width=1.2, dash="dash"),
                hovertemplate="%{x|%Y-%m-%d}<br>SPY: %{y:.2f}x<extra></extra>",
            ), row=1, col=1)
        _fig_nav.add_trace(go.Scatter(
            x=_dd_m1.index, y=_dd_m1.values,
            fill="tozeroy", fillcolor="rgba(214,39,40,0.25)",
            line=dict(color="#d62728", width=1),
            hovertemplate="%{x|%Y-%m-%d}<br>回撤: %{y:.1f}%<extra></extra>",
            showlegend=False,
        ), row=2, col=1)
        if _has_spy_m1:
            _fig_nav.add_trace(go.Scatter(
                x=_spy_dd_m1.index, y=_spy_dd_m1.values,
                line=dict(color="#888888", width=1.2, dash="dash"),
                hovertemplate="%{x|%Y-%m-%d}<br>SPY回撤: %{y:.1f}%<extra></extra>",
                showlegend=False,
            ), row=2, col=1)
        _fig_nav.update_layout(
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=60, r=20, t=60, b=40),
            height=620,
        )
        _fig_nav.update_yaxes(ticksuffix="x", title_text="净值（倍）", row=1, col=1)
        _fig_nav.update_yaxes(ticksuffix="%", title_text="回撤 %", row=2, col=1)
        st.plotly_chart(_fig_nav, use_container_width=True)

    st.markdown("---")

    # ── Signal funnel history chart ───────────────────────────────────────────
    _sig_hist = _m1.get("signals_history", [])
    if _sig_hist:
        st.subheader("八、信号漏斗历史趋势")
        _sh_df = pd.DataFrame(_sig_hist)
        _sh_df["date"] = pd.to_datetime(_sh_df["date"])
        _sh_df = _sh_df.sort_values("date").reset_index(drop=True)

        # 对最新一条记录做现金约束修正：旧脚本 n_cash_blocked=0，实际被现金拦截的笔数由 _blocked_entries 提供
        _sh_df = _sh_df.copy()
        if _blocked_entries and len(_sh_df) > 0:
            _last = _sh_df.index[-1]
            _n_cash_fix = len(_blocked_entries)
            _sh_df.at[_last, "n_candidates"]  = max(0, _sh_df.at[_last, "n_candidates"] - _n_cash_fix)
            _sh_df.at[_last, "n_cash_blocked"] = _sh_df.at[_last, "n_cash_blocked"] + _n_cash_fix \
                                                   if "n_cash_blocked" in _sh_df.columns else _n_cash_fix

        _fig_sh = go.Figure()
        _fig_sh.add_trace(go.Bar(
            x=_sh_df["date"],
            y=_sh_df.get("n_candidates", _sh_df.get("n_entries", 0)),
            name="已选入（通过全部约束）",
            marker_color="#2ca02c",
        ))
        _blocked = _sh_df.get("n_heat_blocked", pd.Series([0]*len(_sh_df))) + \
                   _sh_df.get("n_cash_blocked",  pd.Series([0]*len(_sh_df)))
        _fig_sh.add_trace(go.Bar(
            x=_sh_df["date"],
            y=_blocked,
            name="被拦截（热度/现金）",
            marker_color="#d62728",
        ))
        _fig_sh.add_trace(go.Scatter(
            x=_sh_df["date"],
            y=_sh_df.get("n_raw_breakouts", _sh_df.get("n_candidates", pd.Series([0]*len(_sh_df)))),
            name="原始突破数（通过个股筛选）",
            mode="lines+markers",
            line=dict(color="#1f77b4", width=2),
            yaxis="y",
        ))
        _fig_sh.update_layout(
            barmode="stack",
            title="每日信号漏斗（原始突破 = 已选入 + 被拦截）",
            xaxis_title="日期",
            yaxis_title="信号数量",
            xaxis=dict(
                tickformat="%Y-%m-%d",
                dtick="D1",
                tickangle=-30,
            ),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=60, r=20, t=60, b=60),
            height=350,
            template="plotly_white",
        )
        st.plotly_chart(_fig_sh, use_container_width=True)
        st.markdown(
            "<span style='color:#111111'>蓝线 = 每日通过个股筛选的突破总数；绿色 = 被组合约束选入；红色 = 被热度/现金上限拦截。</span>",
            unsafe_allow_html=True,
        )
        st.markdown("---")

    # ── Trade history (open + closed) ────────────────────────────────────────
    st.subheader("九、交易历史")
    _all_trades = []
    for p in sorted(_m1_positions, key=lambda x: x["entry_date"]):
        _all_trades.append({
            "状态": "🟢 持仓中",
            "标的": p["ticker"],
            "入场日": p["entry_date"],
            "出场日": "—",
            "入场价": f"${p['entry_price']:.2f}",
            "出场价": "—",
            "股数": p["shares"],
            "持仓天数": "—",
            "R": "—",
            "净盈亏": "—",
        })
    for c in sorted(_m1_closed, key=lambda x: x.get("exit_date",""), reverse=True):
        _all_trades.insert(0, {
            "状态": "🔴 已平仓",
            "标的": c["ticker"],
            "入场日": c.get("entry_date", ""),
            "出场日": c.get("exit_date", ""),
            "入场价": f"${c.get('entry_price',0):.2f}",
            "出场价": f"${c.get('exit_price',0):.2f}",
            "股数": c.get("shares", ""),
            "持仓天数": c.get("holding_days", ""),
            "R": f"{c['pnl_r']:+.2f}R" if c.get("pnl_r") is not None else "—",
            "净盈亏": f"${c['net_pnl']:+,.0f}" if c.get("net_pnl") is not None else "—",
        })
    if _all_trades:
        _all_trades_df = pd.DataFrame(_all_trades)
        show_df(_all_trades_df, use_container_width=True, hide_index=True)
        _csv_trades = _all_trades_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "⬇️ 下载交易历史 CSV",
            data=_csv_trades,
            file_name="trade_history.csv",
            mime="text/csv",
        )
    else:
        st.info("暂无交易记录")

    st.markdown("---")

    # ── Closed trades ─────────────────────────────────────────────────────────
    st.subheader(f"十、平仓记录（{len(_m1_closed)} 笔）")
    if _m1_closed:
        _ct = pd.DataFrame(_m1_closed)
        _n_cl     = len(_ct)
        _wins     = _ct[_ct["pnl_r"] > 0] if "pnl_r" in _ct else pd.DataFrame()
        _win_rate = len(_wins) / _n_cl * 100 if _n_cl > 0 else 0.0
        _avg_r    = float(_ct["pnl_r"].mean()) if "pnl_r" in _ct.columns else 0.0
        _tot_pnl  = float(_ct["net_pnl"].sum()) if "net_pnl" in _ct.columns else 0.0
        _avg_days = float(_ct["holding_days"].mean()) if "holding_days" in _ct.columns else 0.0
        _avg_win_r = float(_wins["pnl_r"].mean()) if len(_wins) > 0 else 0.0
        _losses   = _ct[_ct["pnl_r"] <= 0] if "pnl_r" in _ct else pd.DataFrame()
        _avg_loss_r = float(_losses["pnl_r"].mean()) if len(_losses) > 0 else 0.0

        sc1, sc2, sc3, sc4, sc5, sc6 = st.columns(6)
        sc1.metric("已平仓笔数", f"{_n_cl} 笔")
        sc2.metric("胜率", f"{_win_rate:.1f}%")
        sc3.metric("平均持仓", f"{_avg_days:.0f} 天")
        sc4.metric("平均R", f"{_avg_r:+.2f}R")
        sc5.metric("盈亏比", f"{abs(_avg_win_r/(_avg_loss_r or 1)):.2f}x",
                   delta=f"赢 {_avg_win_r:+.2f}R / 亏 {_avg_loss_r:+.2f}R")
        sc6.metric("总净盈亏", f"${_tot_pnl:+,.0f}")

        st.markdown("---")
        _ct_sorted = _ct.sort_values("exit_date", ascending=False)
        show_df(
            _ct_sorted[["ticker","entry_date","exit_date","holding_days","pnl_r","net_pnl","exit_reason"]].rename(
                columns={"ticker":"标的","entry_date":"入场日","exit_date":"出场日",
                         "holding_days":"天数","pnl_r":"R","net_pnl":"净盈亏","exit_reason":"原因"}
            ),
            column_config={
                "R":    st.column_config.NumberColumn(format="%+.2fR"),
                "净盈亏": st.column_config.NumberColumn(format="$%+.0f"),
            },
        )
    else:
        st.info("暂无平仓记录")

    st.markdown("---")

    # ── 数据下载（方法一）────────────────────────────────────────────────────
    st.subheader("数据下载（用于未来策略1.0的过拟合分析）")
    st.markdown(
        "包含所有模拟交易数据：NAV 历史、开仓记录、平仓记录、"
        "信号历史（每日漏斗计数）、**今日突破候选明细**（含拒绝原因）、当前持仓、回测参考数据。"
    )

    _dl1_nav   = _m1.get("nav_history", [])
    _dl1_sig   = _m1.get("signals_history", [])
    _dl1_ct    = _m1.get("closed_trades", [])
    _dl1_op    = [p for p in _m1.get("positions", []) if not p.get("closed")]
    _dl1_ts    = _m1.get("today_signals", {})
    _dl1_cands = _dl1_ts.get("candidate_signals", [])   # full funnel for most recent run

    # 开仓历史 = 所有已开仓交易（持仓中 + 已平仓），按开仓日期排序
    _dl1_entries = sorted([
        {"ticker": p["ticker"],
         "signal_date": p.get("signal_date", ""), "signal_price": p.get("signal_price", ""),
         "entry_date": p["entry_date"], "open_price": p.get("open_price", ""), "entry_price": p["entry_price"],
         "shares": p["shares"], "stop_loss": p.get("stop_loss", ""),
         "atr_at_entry": p.get("atr_at_entry", ""), "状态": "持仓中"}
        for p in _dl1_op
    ] + [
        {"ticker": c["ticker"],
         "signal_date": c.get("signal_date", ""), "signal_price": c.get("signal_price", ""),
         "entry_date": c.get("entry_date", ""), "open_price": c.get("open_price", ""),
         "entry_price": c.get("entry_price", ""),
         "shares": c.get("shares", ""), "stop_loss": c.get("stop_loss", ""),
         "atr_at_entry": "", "状态": "已平仓"}
        for c in _dl1_ct
    ], key=lambda x: x["entry_date"], reverse=True)

    _dl1_rejection_label = {
        None:           "✅ 已选入",
        "corr_reduced": "⚠️ 已选入（相关性减仓）",
        "heat_limit":   "🔴 未选（热度上限）",
        "cash_limit":   "🔴 未选（现金不足）",
    }

    with st.expander(f"NAV 历史（{len(_dl1_nav)} 条）"):
        if _dl1_nav:
            show_df(
                pd.DataFrame(_dl1_nav).sort_values("date", ascending=False),
                use_container_width=True, hide_index=True)
        else:
            st.info("暂无数据")

    with st.expander(f"开仓记录（{len(_dl1_entries)} 笔，含持仓中 + 已平仓）"):
        if _dl1_entries:
            show_df(pd.DataFrame(_dl1_entries), use_container_width=True, hide_index=True)
        else:
            st.info("暂无开仓记录")

    with st.expander(f"平仓记录（{len(_dl1_ct)} 笔）"):
        if _dl1_ct:
            show_df(
                pd.DataFrame(_dl1_ct).sort_values("exit_date", ascending=False),
                use_container_width=True, hide_index=True)
        else:
            st.info("暂无平仓记录")

    with st.expander(f"信号历史（{len(_dl1_sig)} 条，每日漏斗计数）"):
        st.caption(
            "每行代表一个交易日的信号漏斗统计。"
            "原始突破数 → 热度/现金拦截 → 通过约束数（候选）→ 实际执行数。"
            "用于分析组合约束对策略执行率的影响。"
        )
        if _dl1_sig:
            show_df(pd.DataFrame([{
                "日期":           s["date"],
                "Regime":         s.get("regime", ""),
                "SPY收盘":        s.get("spy_close", ""),
                "原始突破数":     s.get("n_raw_breakouts", ""),  # 通过个股过滤器的总突破数
                "热度拦截":       s.get("n_heat_blocked",  ""),  # 被组合热度限制拦截
                "现金拦截":       s.get("n_cash_blocked",  ""),  # 被现金不足拦截
                "相关性减仓":     s.get("n_corr_reduced",  ""),  # 触发相关性减半（仍执行）
                "候选信号数":     s.get("n_candidates",    ""),  # 通过全部约束的信号数
                "当日开仓信号":   s.get("n_entries",       ""),  # 保存为 pending
                "当日已执行":     s.get("n_executed",      ""),  # T+1 开盘实际成交
                "平仓数":         s.get("n_exits",         ""),
            } for s in reversed(_dl1_sig)]), use_container_width=True, hide_index=True)
        else:
            st.info("暂无数据")

    _dl1_cands_approved = sum(1 for c in _dl1_cands if c.get("rejection") in (None, "corr_reduced"))
    _dl1_cands_rejected = len(_dl1_cands) - _dl1_cands_approved
    with st.expander(
        f"今日突破候选明细（{len(_dl1_cands)} 只突破，{_dl1_cands_approved} 只已选，{_dl1_cands_rejected} 只被拦截）"
        + f"  ·  信号日期：{_dl1_ts.get('date', 'N/A')}"
    ):
        st.caption(
            "所有通过**个股筛选**（价格、ADV、突破、ATR、成交量）的标的，"
            "含被组合约束（热度上限/现金不足）拦截的个股及原因。"
            "注：此处仅显示最近一次日脚本运行的候选明细；历史每日明细见『信号历史』表（汇总计数）。"
        )
        if _dl1_cands:
            show_df(pd.DataFrame([{
                "标的":         c["ticker"],
                "信号价（今收）": f"${c.get('signal_price', 0):.2f}" if c.get("signal_price") else "",
                "参考止损":      f"${c.get('stop_price', 0):.2f}"   if c.get("stop_price")   else "",
                "股数":          c.get("shares", ""),
                "风险% NAV":     f"{c['trade_risk']*100:.2f}%" if c.get("trade_risk") else "",
                "状态":          _dl1_rejection_label.get(c.get("rejection"), c.get("rejection", "✅ 已选入")),
            } for c in sorted(_dl1_cands, key=lambda x: x["ticker"])]),
            use_container_width=True, hide_index=True)
        else:
            st.info(
                "候选明细将在下次日脚本运行后自动填充（需运行更新后的 paper_trading_daily.py）。"
            )

    with st.expander(f"当前持仓（{len(_dl1_op)} 只）"):
        if _dl1_op:
            show_df(pd.DataFrame(_dl1_op), use_container_width=True, hide_index=True)
        else:
            st.info("当前无持仓")

    from datetime import date as _date_cls
    st.download_button(
        label="⬇️ 下载方法一全部数据（ZIP）",
        data=_build_method_zip(_m1, "m1"),
        file_name=f"m1_paper_trading_{_date_cls.today().isoformat()}.zip",
        mime="application/zip",
        help=(
            "包含（CSV + 完整JSON）：\n"
            "• m1_nav_history.csv — 每日 NAV\n"
            "• m1_entry_history.csv — 所有开仓记录（持仓中 + 已平仓）\n"
            "• m1_closed_trades.csv — 已平仓记录（含 pnl_r、signal_strength 等）\n"
            "• m1_signals_history.csv — 每日信号漏斗计数\n"
            "• m1_today_candidate_signals.csv — 最近一次运行的突破候选明细（含拒绝原因）\n"
            "• m1_open_positions.csv — 当前持仓\n"
            "• backtest_reference_metrics.json / trades.csv / nav.csv — 回测基准数据"
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — 方法二：IB 自动交易
# ═══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.markdown("""
    **运行方式：** 每个交易日收盘后在本地运行 `python src/scripts/ib_paper_trading_daily.py`，
    脚本自动连接 IB TWS（Paper Trading 模式）下单，并将结果推送到 GitHub。

    **初始资金：** $200,000 USD（独立账户，不依赖回测历史）
    """)

    # ── Load Method 2 state ──────────────────────────────────────────────────
    @st.cache_data(ttl=120)
    def _load_m2():
        if _m2_file.exists():
            return json.loads(_m2_file.read_text())
        return None

    _m2 = _load_m2()

    if _m2 is None:
        # Fallback: show empty $200K initial state
        st.info("ℹ️ ib_state.json 尚未生成，显示初始状态（$200K，0 持仓）。")
        _m2 = {
            "schema_version": 1, "method": "ib_paper_trading",
            "debug_start_date": "2026-06-19", "live_start_date": "2026-07-01",
            "initial_capital": 200000.0, "currency": "USD",
            "last_update_date": None, "nav": 200000.0, "cash": 200000.0,
            "account_summary": {}, "positions": [], "closed_trades": [],
            "nav_history": [], "orders_history": [], "today_signals": {},
        }

    _m2_positions  = [p for p in _m2.get("positions", []) if not p.get("closed")]
    _m2_closed     = _m2.get("closed_trades", [])
    _m2_history    = _m2.get("nav_history", [])
    _m2_last_upd   = _m2.get("last_update_date") or "尚未运行"
    _m2_init_cap   = _m2.get("initial_capital", 200_000.0)
    _m2_nav        = _m2.get("nav", _m2_init_cap)
    _m2_cash       = _m2.get("cash", _m2_init_cap)
    _m2_orders_hist = _m2.get("orders_history", [])
    _m2_today_sig  = _m2.get("today_signals", {})
    _m2_live_start = _m2.get("live_start_date", "2026-07-01")
    _m2_debug_start = _m2.get("debug_start_date", "2026-06-19")
    _m2_ib_summary = _m2.get("account_summary", {})

    # Phase banner
    import datetime as _dt
    _today_dt = _dt.date.today()
    _live_start_dt = _dt.date.fromisoformat(_m2_live_start)
    if _today_dt < _live_start_dt:
        days_left = (_live_start_dt - _today_dt).days
        st.warning(f"🔧 **调试阶段** — 正式启动日期：{_m2_live_start}（还有 {days_left} 天）。建议使用 `--dry-run` 参数先验证信号。")
    else:
        st.success(f"🚀 **已正式启动** — 自 {_m2_live_start} 起实盘模拟交易运行中")

    st.markdown("---")

    # ── Overview metrics ─────────────────────────────────────────────────────
    st.subheader("一、账户状态概览")
    st.markdown(f"上次脚本运行：{_m2_last_upd} ｜ 初始资金：${_m2_init_cap:,.0f}")

    _m2_pnl = _m2_nav - _m2_init_cap
    _m2_pnl_pct = (_m2_nav / _m2_init_cap - 1) * 100

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("账户 NAV", f"${_m2_nav:,.0f}",
              delta=f"{_m2_pnl_pct:+.2f}%  (${_m2_pnl:+,.0f})",
              delta_color="normal" if _m2_pnl >= 0 else "inverse")
    a2.metric("当前持仓", f"{len(_m2_positions)} 只")
    a3.metric("现金", f"${_m2_cash:,.0f}",
              delta=f"{_m2_cash/_m2_nav*100:.1f}% of NAV" if _m2_nav else None)
    a4.metric("已平仓笔数", f"{len(_m2_closed)} 笔")

    # IB Account Summary (if available)
    if _m2_ib_summary:
        st.markdown("#### IB 账户实时数据（最近一次连接）")
        ib1, ib2, ib3, ib4 = st.columns(4)
        ib1.metric("IB NetLiquidation", f"${_m2_ib_summary.get('NetLiquidation', 0):,.0f}")
        ib2.metric("IB AvailableFunds", f"${_m2_ib_summary.get('AvailableFunds', 0):,.0f}")
        ib3.metric("IB UnrealizedPnL",  f"${_m2_ib_summary.get('UnrealizedPnL', 0):+,.0f}")
        ib4.metric("IB RealizedPnL",    f"${_m2_ib_summary.get('RealizedPnL', 0):+,.0f}")

    st.markdown("---")

    # ── Today's signals ───────────────────────────────────────────────────────
    st.subheader("二、今日信号")
    if _m2_today_sig:
        sig_date    = _m2_today_sig.get("date", "N/A")
        sig_regime  = _m2_today_sig.get("regime", "N/A")
        sig_spy     = _m2_today_sig.get("spy_close")
        sig_exits   = _m2_today_sig.get("exits", [])
        sig_entries = _m2_today_sig.get("entries", [])
        st.markdown(f"信号日期：{sig_date} 盘后 ｜ Regime：{'🟢 BULL' if sig_regime == 'BULL' else '🔴 BEAR'}" +
                   (f" ｜ SPY：${sig_spy:.2f}" if sig_spy else ""))

        _sc1, _sc2 = st.columns(2)
        with _sc1:
            st.markdown(f"**退出信号（{len(sig_exits)} 笔）**")
            if sig_exits:
                _ex_df = pd.DataFrame([{
                    "标的": e["ticker"],
                    "操作": "SELL",
                    "股数": e["shares"],
                    "止损价": f"${e['stop_price']:.2f}",
                    "订单类型": e["order_type"],
                } for e in sig_exits])
                show_df(_ex_df, use_container_width=True, hide_index=True)
            else:
                st.info("无退出信号")

        with _sc2:
            st.markdown(f"**入场信号（{len(sig_entries)} 笔）**")
            if sig_entries:
                _en_df = pd.DataFrame([{
                    "标的": e["ticker"],
                    "操作": "BUY",
                    "股数": e["shares"],
                    "信号价": f"${e['signal_price']:.2f}",
                    "止损价": f"${e['stop_price']:.2f}",
                    "风险%": f"{e['trade_risk']*100:.2f}%",
                    "订单类型": e["order_type"],
                } for e in sig_entries])
                show_df(_en_df, use_container_width=True, hide_index=True)
            else:
                st.info("无入场信号")
    else:
        st.info(f"尚无今日信号。请运行 `python src/scripts/ib_paper_trading_daily.py`")

    st.markdown("---")

    # ── Live positions (fetch prices from Yahoo Finance) ──────────────────────
    st.subheader("三、当前持仓状态")
    if _m2_positions:
        _m2_tickers = tuple(sorted(set([p["ticker"] for p in _m2_positions] + ["SPY"])))
        with st.spinner("从 Yahoo Finance 加载持仓行情…"):
            _m2_raw, _ = _fetch_yf(_m2_tickers, "300d")

        _m2_live = [_enrich_position(p, _m2_raw) for p in _m2_positions]
        _m2_ok   = [p for p in _m2_live if p.get("_ok")]
        _m2_stp  = [p for p in _m2_ok if p["is_stopped"]]

        if _m2_stp:
            st.warning(f"⚠️ **{len(_m2_stp)} 只已触及止损** — IB 脚本运行后将自动生成退出订单")

        def _m2_status(p: dict) -> str:
            sr = p.get("stop_reason")
            if sr == "stop_loss":      return "🔴 触止损"
            if sr == "trailing_stop":  return "🔴 触移动止盈"
            return "🟢 持有"

        _m2_rows = [{
            "标的": p["ticker"],
            "状态": _m2_status(p),
            "入场日": p["entry_date"],
            "入场价": f"${p['entry_price']:.2f}",
            "当前价": f"${p['current_price']:.2f}",
            "移动止损": f"${p['current_stop']:.2f}",
            "缓冲": f"{p['stop_buffer_pct']:.1f}%",
            "R": f"{p['R']:+.2f}R",
            "浮盈 $": f"${p['unreal_pnl']:+,.0f}",
            "股数": p["shares"],
        } for p in sorted(_m2_ok, key=lambda x: x.get("R", 0), reverse=True)]

        if _m2_rows:
            show_df(pd.DataFrame(_m2_rows), use_container_width=True, hide_index=True)
    else:
        st.info("当前无持仓。Regime 允许时，下次运行脚本将扫描开仓信号。")

    st.markdown("---")

    # ── NAV History ───────────────────────────────────────────────────────────
    if _m2_history:
        st.subheader("四、NAV 走势")
        _m2_nh = pd.DataFrame(_m2_history)
        _m2_nh["date"] = pd.to_datetime(_m2_nh["date"])
        _m2_nh = _m2_nh.sort_values("date")
        _fig_m2nav = go.Figure(go.Scatter(
            x=_m2_nh["date"], y=_m2_nh["nav"] / _m2_init_cap,
            mode="lines+markers", line=dict(color="#ff7f0e", width=2.5),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.3f}x<extra></extra>",
        ))
        _fig_m2nav.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5)
        _fig_m2nav.update_layout(
            title="方法二 NAV（相对起始 $200K）", yaxis_title="倍数",
            height=280, margin=dict(l=60, r=20, t=45, b=40), template="plotly_white",
        )
        st.plotly_chart(_fig_m2nav, use_container_width=True)
        st.markdown("---")

    # ── Closed trades ─────────────────────────────────────────────────────────
    if _m2_closed:
        st.subheader(f"五、已平仓记录（{len(_m2_closed)} 笔）")
        _m2_ct = pd.DataFrame(_m2_closed).sort_values("exit_date", ascending=False)
        _m2_rename = {"ticker":"标的","entry_date":"入场日","exit_date":"出场日","holding_days":"天数","exit_reason":"原因"}
        _m2_cfg: dict = {}
        if "pnl_r_est" in _m2_ct.columns:
            _m2_rename["pnl_r_est"] = "R"
            _m2_cfg["R"] = st.column_config.NumberColumn(format="%+.2fR")
        if "net_pnl_est" in _m2_ct.columns:
            _m2_rename["net_pnl_est"] = "净盈亏(估)"
            _m2_cfg["净盈亏(估)"] = st.column_config.NumberColumn(format="$%+.0f")
        _m2_cols = [c for c in ["ticker","entry_date","exit_date","holding_days","pnl_r_est","net_pnl_est","exit_reason"] if c in _m2_ct.columns]
        show_df(_m2_ct[_m2_cols].rename(columns=_m2_rename), column_config=_m2_cfg or None)
        st.markdown("---")

    # ── Order history ─────────────────────────────────────────────────────────
    if _m2_orders_hist:
        with st.expander(f"📋 订单历史（最近 {min(50, len(_m2_orders_hist))} 条）"):
            _ord_df = pd.DataFrame(_m2_orders_hist[-50:][::-1])
            _show_cols = [c for c in ["ticker","action","shares","order_type","reason","signal_price","stop_price","ib_status","submitted_at","dry_run"] if c in _ord_df.columns]
            show_df(_ord_df[_show_cols], use_container_width=True, hide_index=True)

    # ── Setup guide ───────────────────────────────────────────────────────────
    with st.expander("⚙️ IB Paper Trading 配置与使用指南"):
        st.markdown(f"""
### IB TWS 配置

1. 登录 **IB Paper Trading 账户**（TWS 或 IB Gateway）
2. **启用 API 连接**：
   - TWS：File → Global Configuration → API → Settings
   - 勾选 "Enable ActiveX and Socket Clients"
   - Socket port：**7497**（TWS Paper Trading）
   - 勾选 "Allow connections from localhost only"（安全）
3. 推荐**重置 Paper Trading 账户**初始资金：
   - 右键账户 → Reset Paper Trading Account
   - 脚本使用自己的 $200K NAV 计算，但 IB 账户余额一致更易对账

### 每日运行

```bash
# 调试阶段（不实际下单，只看信号）
python src/scripts/ib_paper_trading_daily.py --dry-run

# 正式模式（实际通过 IB API 下单）
python src/scripts/ib_paper_trading_daily.py

# 可选参数
python src/scripts/ib_paper_trading_daily.py \\
    --port 4002 \\          # IB Gateway 端口（默认 7497 为 TWS）
    --client-id 10 \\       # IB 客户端 ID（避免与 TWS 手动操作冲突）
    --no-entries            # 只检查止损，不扫描开仓

# 完成后推送到 GitHub
git add results/paper_trading/ib_state.json
git commit -m "IB paper trading: YYYY-MM-DD"
git push
```

### 关键参数

| 参数 | 值 |
|------|-----|
| 初始资金 | $200,000 |
| 每笔风险 | 1% NAV ($2,000 at start) |
| 最大热度 | 10% NAV |
| 单仓上限 | 5% NAV ($10,000 at start) |
| 开仓信号 | 200日突破 + ATR止损 |
| 止损方式 | 移动止盈（ATR×3/5，每日更新） |
| 订单类型 | MOO（次日开盘价执行） |
| 股数取整 | **四舍五入**（小数≥0.5进一） |
| 正式启动 | **{_m2_live_start}** |
""")

    st.markdown("---")

    # ── 数据下载（方法二）────────────────────────────────────────────────────
    st.subheader("数据下载（用于未来策略1.0的过拟合分析）")
    st.markdown(
        "包含所有模拟交易数据：NAV 历史、开仓记录、平仓记录、"
        "信号历史（每日漏斗计数）、**今日突破候选明细**（含拒绝原因）、当前持仓、回测参考数据。"
    )

    _dl2_nav   = _m2.get("nav_history", [])
    _dl2_sig   = _m2.get("signals_history", [])
    _dl2_ct    = _m2.get("closed_trades", [])
    _dl2_op    = [p for p in _m2.get("positions", []) if not p.get("closed")]
    _dl2_ts    = _m2.get("today_signals", {})
    _dl2_cands = _dl2_ts.get("candidate_signals", [])

    _dl2_entries = sorted([
        {"ticker": p["ticker"], "entry_date": p["entry_date"],
         "entry_price": p["entry_price"], "shares": p["shares"],
         "stop_loss": p.get("stop_loss", p.get("initial_stop_loss", "")), "atr_at_entry": p.get("atr_at_entry", ""),
         "状态": "持仓中"}
        for p in _dl2_op
    ] + [
        {"ticker": c["ticker"], "entry_date": c.get("entry_date", ""),
         "entry_price": c.get("entry_price", ""), "shares": c.get("shares", ""),
         "stop_loss": c.get("stop_loss", c.get("initial_stop", "")), "atr_at_entry": "",
         "状态": "已平仓"}
        for c in _dl2_ct
    ], key=lambda x: x["entry_date"], reverse=True)

    _dl2_rejection_label = {
        None:           "✅ 已选入",
        "corr_reduced": "⚠️ 已选入（相关性减仓）",
        "heat_limit":   "🔴 未选（热度上限）",
        "cash_limit":   "🔴 未选（现金不足）",
    }

    with st.expander(f"NAV 历史（{len(_dl2_nav)} 条）"):
        if _dl2_nav:
            show_df(
                pd.DataFrame(_dl2_nav).sort_values("date", ascending=False),
                use_container_width=True, hide_index=True)
        else:
            st.info("暂无数据")

    with st.expander(f"开仓记录（{len(_dl2_entries)} 笔，含持仓中 + 已平仓）"):
        if _dl2_entries:
            show_df(pd.DataFrame(_dl2_entries), use_container_width=True, hide_index=True)
        else:
            st.info("暂无开仓记录")

    with st.expander(f"平仓记录（{len(_dl2_ct)} 笔）"):
        if _dl2_ct:
            show_df(
                pd.DataFrame(_dl2_ct).sort_values("exit_date", ascending=False),
                use_container_width=True, hide_index=True)
        else:
            st.info("暂无平仓记录")

    with st.expander(f"信号历史（{len(_dl2_sig)} 条，每日漏斗计数）"):
        st.caption(
            "每行代表一个交易日的信号漏斗统计。"
            "原始突破数 → 热度/现金拦截 → 通过约束数（候选）→ 实际执行数。"
        )
        if _dl2_sig:
            show_df(pd.DataFrame([{
                "日期":           s["date"],
                "Regime":         s.get("regime", ""),
                "SPY收盘":        s.get("spy_close", ""),
                "原始突破数":     s.get("n_raw_breakouts", ""),
                "热度拦截":       s.get("n_heat_blocked",  ""),
                "现金拦截":       s.get("n_cash_blocked",  ""),
                "相关性减仓":     s.get("n_corr_reduced",  ""),
                "候选信号数":     s.get("n_candidates",    ""),
                "当日开仓信号":   s.get("n_entries",       ""),
                "当日已执行":     s.get("n_executed",      ""),
                "平仓数":         s.get("n_exits",         ""),
            } for s in reversed(_dl2_sig)]), use_container_width=True, hide_index=True)
        else:
            st.info("暂无数据")

    _dl2_cands_approved = sum(1 for c in _dl2_cands if c.get("rejection") in (None, "corr_reduced"))
    _dl2_cands_rejected = len(_dl2_cands) - _dl2_cands_approved
    with st.expander(
        f"今日突破候选明细（{len(_dl2_cands)} 只突破，{_dl2_cands_approved} 只已选，{_dl2_cands_rejected} 只被拦截）"
        + f"  ·  信号日期：{_dl2_ts.get('date', 'N/A')}"
    ):
        st.caption(
            "所有通过**个股筛选**的标的（含被组合约束拦截的个股及原因）。"
            "注：仅显示最近一次日脚本运行的候选明细；历史每日明细见『信号历史』表（汇总计数）。"
        )
        if _dl2_cands:
            show_df(pd.DataFrame([{
                "标的":         c["ticker"],
                "信号价（今收）": f"${c.get('signal_price', 0):.2f}" if c.get("signal_price") else "",
                "参考止损":      f"${c.get('stop_price', 0):.2f}"   if c.get("stop_price")   else "",
                "股数":          c.get("shares", ""),
                "风险% NAV":     f"{c['trade_risk']*100:.2f}%" if c.get("trade_risk") else "",
                "状态":          _dl2_rejection_label.get(c.get("rejection"), c.get("rejection", "✅ 已选入")),
            } for c in sorted(_dl2_cands, key=lambda x: x["ticker"])]),
            use_container_width=True, hide_index=True)
        else:
            st.info("候选明细将在方法二日脚本运行后自动填充。")

    with st.expander(f"当前持仓（{len(_dl2_op)} 只）"):
        if _dl2_op:
            show_df(pd.DataFrame(_dl2_op), use_container_width=True, hide_index=True)
        else:
            st.info("当前无持仓")

    from datetime import date as _date_cls
    st.download_button(
        label="⬇️ 下载方法二全部数据（ZIP）",
        data=_build_method_zip(_m2, "m2"),
        file_name=f"m2_paper_trading_{_date_cls.today().isoformat()}.zip",
        mime="application/zip",
        help=(
            "包含（CSV + 完整JSON）：\n"
            "• m2_nav_history.csv — 每日 NAV\n"
            "• m2_entry_history.csv — 所有开仓记录（持仓中 + 已平仓）\n"
            "• m2_closed_trades.csv — 已平仓记录\n"
            "• m2_signals_history.csv — 每日信号漏斗计数\n"
            "• m2_today_candidate_signals.csv — 最近一次运行的突破候选明细（含拒绝原因）\n"
            "• m2_open_positions.csv — 当前持仓\n"
            "• backtest_reference_metrics.json / trades.csv / nav.csv — 回测基准数据"
        ),
    )
