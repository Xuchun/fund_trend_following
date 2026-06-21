"""策略1.0模拟交易监控"""

import sys, json
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_results  = _root / "results" / "v1_unbiased_60m_2000"
_pt_dir   = _root / "results" / "paper_trading"
_m1_file  = _pt_dir / "positions.json"
_m2_file  = _pt_dir / "ib_state.json"

_TRAIL_R1   = 3.0
_TRAIL_R3   = 3.0
_TRAIL_R5   = 5.0
_ATR_PERIOD = 20
_SMA_WINDOW = 200

# ─────────────────────────────────────────────────────────────────────────────
st.title("策略1.0 模拟交易监控")
st.caption("同时运行两种模拟交易方法，互相验证信号与执行质量")

tab1, tab2 = st.tabs(["📊 方法一：手动跟踪（Yahoo Finance）", "🤖 方法二：IB 自动交易（Interactive Brokers）"])

# ═══════════════════════════════════════════════════════════════════════════════
# ── Shared helpers ─────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600)
def _fetch_yf(tickers: tuple, period: str = "300d") -> pd.DataFrame:
    import yfinance as yf
    if not tickers:
        return pd.DataFrame()
    return yf.download(list(tickers), period=period, auto_adjust=True, progress=False)


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


def _wilder_atr(high, low, close, period=20):
    tr = pd.concat(
        [high - low,
         (high - close.shift(1)).abs(),
         (low  - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _enrich_position(pos: dict, raw_yf: pd.DataFrame) -> dict:
    """Add live price + computed trailing stop to a position dict."""
    df = _get_df(raw_yf, pos["ticker"])

    # Fallback to last_known_price when YF fetch fails
    if df is None:
        fallback = pos.get("last_known_price")
        if not fallback:
            return {**pos, "_ok": False}
        risk = pos["entry_price"] - pos["initial_stop_loss"]
        R    = (fallback - pos["entry_price"]) / risk if risk > 0 else 0.0
        return {
            **pos,
            "_ok":            True,
            "_stale":         True,
            "current_price":  fallback,
            "current_date":   pos.get("last_price_date", "N/A"),
            "peak_price":     pos["peak_price"],
            "current_atr":    pos["atr_at_entry"],
            "current_stop":   pos["current_stop_loss"],
            "trail_mult":     _TRAIL_R5 if R >= 3.0 else (_TRAIL_R3 if R >= 1.0 else _TRAIL_R1),
            "R":              R,
            "mkt_value":      fallback * pos["shares"],
            "unreal_pnl":     (fallback - pos["entry_price"]) * pos["shares"],
            "stop_buffer_pct": (fallback - pos["current_stop_loss"]) / fallback * 100,
            "is_stopped":     fallback <= pos["current_stop_loss"],
        }

    # Compare dates only to avoid timezone mismatch between yfinance (tz-aware) and entry_date (tz-naive)
    entry_d     = pd.to_datetime(pos["entry_date"]).date()
    since_entry = df[pd.to_datetime(df.index).date >= entry_d] if not df.empty else df
    if since_entry.empty:
        fallback = pos.get("last_known_price")
        if not fallback:
            return {**pos, "_ok": False}
        risk = pos["entry_price"] - pos["initial_stop_loss"]
        R    = (fallback - pos["entry_price"]) / risk if risk > 0 else 0.0
        return {
            **pos,
            "_ok":            True,
            "_stale":         True,
            "current_price":  fallback,
            "current_date":   pos.get("last_price_date", "N/A"),
            "peak_price":     pos["peak_price"],
            "current_atr":    pos["atr_at_entry"],
            "current_stop":   pos["current_stop_loss"],
            "trail_mult":     _TRAIL_R5 if R >= 3.0 else (_TRAIL_R3 if R >= 1.0 else _TRAIL_R1),
            "R":              R,
            "mkt_value":      fallback * pos["shares"],
            "unreal_pnl":     (fallback - pos["entry_price"]) * pos["shares"],
            "stop_buffer_pct": (fallback - pos["current_stop_loss"]) / fallback * 100,
            "is_stopped":     fallback <= pos["current_stop_loss"],
        }

    cur_price  = float(since_entry["Close"].iloc[-1])
    cur_date   = str(since_entry.index[-1].date())
    peak_price = max(pos["peak_price"], float(since_entry["High"].max()))

    atr_s   = _wilder_atr(df["High"], df["Low"], df["Close"], _ATR_PERIOD)
    cur_atr = float(atr_s.iloc[-1])
    if pd.isna(cur_atr):
        cur_atr = pos["atr_at_entry"]

    risk = pos["entry_price"] - pos["initial_stop_loss"]
    R    = (cur_price - pos["entry_price"]) / risk if risk > 0 else 0.0
    tm   = _TRAIL_R5 if R >= 3.0 else (_TRAIL_R3 if R >= 1.0 else _TRAIL_R1)
    stop = max(pos["current_stop_loss"], peak_price - tm * cur_atr)

    mkt_val    = cur_price * pos["shares"]
    unreal     = (cur_price - pos["entry_price"]) * pos["shares"]
    buf_pct    = (cur_price - stop) / cur_price * 100
    is_stopped = cur_price <= stop

    return {
        **pos,
        "_ok":            True,
        "current_price":  cur_price,
        "current_date":   cur_date,
        "peak_price":     peak_price,
        "current_atr":    cur_atr,
        "current_stop":   stop,
        "trail_mult":     tm,
        "R":              R,
        "mkt_value":      mkt_val,
        "unreal_pnl":     unreal,
        "stop_buffer_pct": buf_pct,
        "is_stopped":     is_stopped,
    }


@st.cache_data(ttl=86400)
def _load_bt():
    with open(_results / "metrics.json") as f:
        m = json.load(f)
    nav = pd.read_csv(_results / "nav.csv", index_col=0, parse_dates=True)
    spy = pd.read_csv(_results / "spy_nav.csv", index_col=0, parse_dates=True)
    trades = pd.read_csv(_results / "trades.csv", parse_dates=["entry_date", "exit_date"])
    return m, nav, spy, trades


_bm, _bt_nav, _bt_spy, _bt_trades = _load_bt()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — 方法一：手动跟踪（Yahoo Finance）
# ═══════════════════════════════════════════════════════════════════════════════

with tab1:
    st.markdown("""
    **运行方式：** 由 **GitHub Actions 自动运行**，每个交易日美东时间 4:30 PM 收盘后自动触发，
    无需任何手动操作。运行结果自动推送到 GitHub，本页面随即刷新。

    **初始资金：** $200,000 USD（全新独立账户，调试期 2026-06-19 起，正式启动 2026-07-01）
    """)

    # ── Load Method 1 state ──────────────────────────────────────────────────
    @st.cache_data(ttl=3600)
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
    _m1_last_upd   = _m1.get("last_update_date", "N/A")
    _m1_today_sig  = _m1.get("today_signals")

    # ── Fetch live prices ────────────────────────────────────────────────────
    _m1_tickers = tuple(sorted(set([p["ticker"] for p in _m1_positions] + ["SPY"])))
    with st.spinner("从 Yahoo Finance 加载行情…"):
        _m1_raw = _fetch_yf(_m1_tickers, "300d")

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
    _m1_nav   = _m1_mkt + _m1_cash
    _m1_date  = max((p.get("current_date", "") for p in _m1_ok), default="N/A")
    _m1_stale = any(p.get("_stale") for p in _m1_ok)

    # ── Overview ─────────────────────────────────────────────────────────────
    st.subheader("一、策略状态概览")
    st.caption(f"行情日期：{_m1_date} ｜ 上次更新：{_m1_last_upd} ｜ Yahoo Finance（1小时缓存）")
    if _m1_stale:
        st.caption(f"⚠️ 以上数值基于 {_m1_date} 开仓参考价（当日美股休市，Yahoo Finance 无收盘数据）；持仓浮盈 $0 属正常，下一交易日更新后将显示实际盈亏。")
    else:
        st.caption(f"以上数值基于 {_m1_date} 收盘价估算。")

    c1, c2, c3, c4, c5 = st.columns(5)
    _nav_label = "模拟 NAV（上次价估算）" if _m1_stale else "模拟 NAV（估算）"
    c1.metric(_nav_label, f"${_m1_nav/1e6:.2f}M",
              delta=f"{(_m1_nav/_m1_init_nav-1)*100:+.2f}% vs 起始")
    c2.metric("持仓数量", f"{len(_m1_act)} 只",
              delta=f"触止损 {len(_m1_stop)} 只" if _m1_stop else None,
              delta_color="inverse" if _m1_stop else "normal")
    c3.metric("持仓浮盈", f"${_m1_unrl/1e6:+.2f}M",
              delta=f"{_m1_unrl/_m1_nav*100:+.1f}% NAV" if _m1_nav else None)
    c4.metric("持仓市值", f"${_m1_mkt/1e6:.2f}M",
              delta=f"占 NAV {_m1_mkt/_m1_nav*100:.1f}%" if _m1_nav else None)
    c5.metric("现金", f"${_m1_cash/1e6:.2f}M")

    st.markdown("---")

    # ── Today's trades (combined) ─────────────────────────────────────────────
    st.subheader("二、今日完成的交易")
    _trade_rows = []
    if _m1_today_sig:
        _ts_trade_date = _m1_today_sig.get("date", "N/A")
        for e in _m1_today_sig.get("exits", []):
            _trade_rows.append({
                "交易日期": _ts_trade_date,
                "方向": "🔴 卖出",
                "标的": e["ticker"],
                "股数": e.get("shares", ""),
                "成交价": f"${e['stop_price']:.2f}" if e.get("stop_price") else "—",
                "止损价": "—",
                "风险%": "—",
            })
        for e in _m1_today_sig.get("entries", []):
            _trade_rows.append({
                "交易日期": _ts_trade_date,
                "方向": "🟢 买入",
                "标的": e["ticker"],
                "股数": e.get("shares", ""),
                "成交价": f"${e['signal_price']:.2f}" if e.get("signal_price") else "—",
                "止损价": f"${e['stop_price']:.2f}" if e.get("stop_price") else "—",
                "风险%": f"{e['trade_risk']*100:.2f}%" if e.get("trade_risk") else "—",
            })
    if _trade_rows:
        st.dataframe(pd.DataFrame(_trade_rows), use_container_width=True, hide_index=True)
    else:
        st.info("今日无交易")

    st.markdown("---")

    # ── Tomorrow's orders ────────────────────────────────────────────────────
    st.subheader("三、明日要执行的交易")
    # Compute next trading day (skip weekends)
    import datetime as _dt
    _today = _dt.date.today()
    _next_td = _today + _dt.timedelta(days=1)
    while _next_td.weekday() >= 5:  # 5=Sat, 6=Sun
        _next_td += _dt.timedelta(days=1)
    st.caption(f"下一交易日预计：{_next_td}（不含美股假日）｜ 以下订单在开盘后按市价执行")

    if _m1_today_sig:
        _sig_exits   = _m1_today_sig.get("exits", [])
        _sig_entries = _m1_today_sig.get("entries", [])
        _order_rows  = []
        for e in _sig_exits:
            _order_rows.append({
                "操作": "🔴 平仓卖出",
                "标的": e["ticker"],
                "股数": e.get("shares", ""),
                "参考价": f"${e['stop_price']:.2f}" if e.get("stop_price") else "—",
                "订单类型": "市价单（开盘执行）",
                "备注": "止损触发",
            })
        for e in _sig_entries:
            _order_rows.append({
                "操作": "🟢 开仓买入",
                "标的": e["ticker"],
                "股数": e.get("shares", ""),
                "参考价": f"${e['signal_price']:.2f}" if e.get("signal_price") else "—",
                "订单类型": "市价单（开盘执行）",
                "备注": f"止损设于 ${e['stop_price']:.2f}，风险 {e['trade_risk']*100:.2f}% NAV" if e.get("stop_price") else "—",
            })
        if _order_rows:
            st.dataframe(pd.DataFrame(_order_rows), use_container_width=True, hide_index=True)
            n_sell = len(_sig_exits)
            n_buy  = len(_sig_entries)
            st.caption(f"共 {n_sell} 笔平仓、{n_buy} 笔开仓，合计 {n_sell+n_buy} 笔订单")
        else:
            st.info("明日无需执行任何交易")
    else:
        st.info("尚无今日信号，明日交易计划待脚本运行后更新")

    st.markdown("---")

    # ── Today's signals ───────────────────────────────────────────────────────
    st.subheader("四、今日开平仓信号")
    if _m1_today_sig:
        _ts_date    = _m1_today_sig.get("date", "N/A")
        _ts_regime  = _m1_today_sig.get("regime", "N/A")
        _ts_spy     = _m1_today_sig.get("spy_close")
        _ts_exits   = _m1_today_sig.get("exits", [])
        _ts_entries = _m1_today_sig.get("entries", [])
        _ts_regime_str = "🟢 BULL" if _ts_regime == "BULL" else "🔴 BEAR"
        if _spy_close and _spy_sma:
            _ts_gap = (_spy_close / _spy_sma - 1) * 100
            _ts_op  = "＞" if _spy_close > _spy_sma else "＜"
            _ts_regime_str += f"，SPY {_spy_close:.2f} {_ts_op} SMA200 {_spy_sma:.2f}（{_ts_gap:+.1f}%）"
        st.caption(f"信号日期：{_ts_date} ｜ Regime：{_ts_regime_str}")

        _tab_exit, _tab_entry = st.tabs([f"退出信号（{len(_ts_exits)} 笔）", f"入场信号（{len(_ts_entries)} 笔）"])
        with _tab_exit:
            if _ts_exits:
                st.dataframe(pd.DataFrame([{
                    "标的": e["ticker"], "操作": "SELL",
                    "股数": e.get("shares", ""),
                    "止损价": f"${e['stop_price']:.2f}" if e.get("stop_price") else "",
                    "订单类型": e.get("order_type", ""),
                } for e in _ts_exits]), use_container_width=True, hide_index=True)
            else:
                st.info("无退出信号")

        with _tab_entry:
            if _ts_entries:
                st.dataframe(pd.DataFrame([{
                    "标的": e["ticker"], "操作": "BUY",
                    "股数": e.get("shares", ""),
                    "信号价": f"${e['signal_price']:.2f}" if e.get("signal_price") else "",
                    "止损价": f"${e['stop_price']:.2f}" if e.get("stop_price") else "",
                    "风险%": f"{e['trade_risk']*100:.2f}%" if e.get("trade_risk") else "",
                } for e in _ts_entries]), use_container_width=True, hide_index=True)
            else:
                st.info("无入场信号")
    else:
        _ts_regime_cap = "🟢 BULL" if _bull else "🔴 BEAR"
        st.caption(f"信号日期：N/A ｜ Regime：{_ts_regime_cap}")
        _tab_exit, _tab_entry = st.tabs(["退出信号（0 笔）", "入场信号（0 笔）"])
        with _tab_exit:
            st.info("无退出信号")
        with _tab_entry:
            st.info("无入场信号")

    st.markdown("---")

    # ── Live positions ───────────────────────────────────────────────────────
    st.subheader("五、当前持仓实时状态")
    if _m1_stop:
        st.warning(f"⚠️ **{len(_m1_stop)} 只已触及止损** — 建议执行止损出场")

    if _m1_ok:
        _rows = [{
            "标的": p["ticker"],
            "状态": "🔴 触止损" if p["is_stopped"] else "🟢 持有",
            "入场日": p["entry_date"],
            "入场价": f"${p['entry_price']:.2f}",
            "当前价": f"${p['current_price']:.2f}",
            "移动止损": f"${p['current_stop']:.2f}",
            "缓冲": f"{p['stop_buffer_pct']:.1f}%",
            "R": f"{p['R']:+.2f}R",
            "浮盈 $": f"${p['unreal_pnl']:+,.0f}",
            "市值": f"${p['mkt_value']/1e3:.0f}K",
        } for p in sorted(_m1_ok, key=lambda x: x.get("R", 0), reverse=True)]
        st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)

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
    st.subheader("六、移动止损明细")
    if _m1_ok:
        _sd = pd.DataFrame([{
            "标的": p["ticker"], "状态": "🔴" if p["is_stopped"] else "✅",
            "当前价": f"${p['current_price']:.2f}", "历史最高": f"${p['peak_price']:.2f}",
            "ATR(20)": f"${p['current_atr']:.2f}", "乘数": f"{p['trail_mult']:.1f}×",
            "止损价": f"${p['current_stop']:.2f}", "价格距止损": f"{p['stop_buffer_pct']:.1f}%",
        } for p in sorted(_m1_ok, key=lambda x: x.get("stop_buffer_pct", 999))])
        st.dataframe(_sd, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Trade history (open + closed) ────────────────────────────────────────
    st.subheader("七、交易历史")
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
        st.dataframe(pd.DataFrame(_all_trades), use_container_width=True, hide_index=True)
    else:
        st.info("暂无交易记录")

    st.markdown("---")

    # ── NAV history ──────────────────────────────────────────────────────────
    if _m1_history:
        st.subheader("八、NAV 走势")
        _nh = pd.DataFrame(_m1_history)
        _nh["date"] = pd.to_datetime(_nh["date"])
        _nh = _nh.sort_values("date")
        if _m1_date != "N/A" and not (_nh["date"] == pd.to_datetime(_m1_date)).any():
            _nh = pd.concat([_nh, pd.DataFrame([{"date": pd.to_datetime(_m1_date), "nav": _m1_nav}])], ignore_index=True)
        _fig_nav = go.Figure(go.Scatter(
            x=_nh["date"], y=_nh["nav"] / _m1_init_nav,
            mode="lines+markers", line=dict(color="#1f77b4", width=2.5),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.3f}x<extra></extra>",
        ))
        _fig_nav.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5)
        _fig_nav.update_layout(
            title="方法一 NAV（相对起始）", yaxis_title="倍数",
            height=280, margin=dict(l=60, r=20, t=45, b=40), template="plotly_white",
        )
        st.plotly_chart(_fig_nav, use_container_width=True)

    st.markdown("---")

    # ── Closed trades ─────────────────────────────────────────────────────────
    if _m1_closed:
        st.subheader(f"九、平仓记录（{len(_m1_closed)} 笔）")
        _ct = pd.DataFrame(_m1_closed).sort_values("exit_date", ascending=False)
        _ct["R"] = _ct["pnl_r"].map(lambda v: f"{v:+.2f}R")
        _ct["净盈亏"] = _ct["net_pnl"].map(lambda v: f"${v:+,.0f}")
        st.dataframe(_ct[["ticker","entry_date","exit_date","holding_days","R","净盈亏","exit_reason"]].rename(
            columns={"ticker":"标的","entry_date":"入场日","exit_date":"出场日","holding_days":"天数","exit_reason":"原因"}
        ), use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Automation info ───────────────────────────────────────────────────────
    with st.expander("⚙️ 自动化配置说明"):
        st.markdown("""
**GitHub Actions 自动运行**（无需任何手动操作）

- 工作流文件：`.github/workflows/paper_trading_m1.yml`
- 触发时间：每个交易日 **美东 4:30 PM**（21:30 UTC）自动运行
- 运行内容：下载 Yahoo Finance 数据 → 计算信号 → 更新 positions.json → 自动推送到 GitHub
- 也可在 GitHub → Actions → "Paper Trading M1" 页面手动触发

如需临时手动运行（调试用）：
```bash
python src/scripts/paper_trading_daily.py --date YYYY-MM-DD
```
""")

    # ── Backtest reference ────────────────────────────────────────────────────
    with st.expander("📊 回测基准（2000–2026）"):
        bm1, bm2, bm3, bm4 = st.columns(4)
        bm1.metric("CAGR",    f"{_bm.get('cagr',0)*100:.2f}%")
        bm2.metric("最大回撤", f"{_bm.get('max_drawdown',0)*100:.2f}%")
        bm3.metric("Sharpe",   f"{_bm.get('sharpe',0):.3f}")
        bm4.metric("Calmar",   f"{_bm.get('calmar',0):.3f}")
        _nn = _bt_nav["nav"]; _ss = _bt_spy["spy_nav"]
        _fig_ref = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35], vertical_spacing=0.05)
        _fig_ref.add_trace(go.Scatter(x=_nn.index, y=_nn/_nn.iloc[0], name="策略1.0", line=dict(color="#1f77b4", width=2)), row=1, col=1)
        _fig_ref.add_trace(go.Scatter(x=_ss.index, y=_ss/_ss.iloc[0], name="SPY", line=dict(color="#888", width=1.2, dash="dash")), row=1, col=1)
        _dd = (_nn - _nn.cummax()) / _nn.cummax() * 100
        _fig_ref.add_trace(go.Scatter(x=_dd.index, y=_dd.values, fill="tozeroy", fillcolor="rgba(214,39,40,0.2)", line=dict(color="#d62728", width=1), showlegend=False), row=2, col=1)
        _fig_ref.update_layout(height=440, template="plotly_white", hovermode="x unified",
                               legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                               margin=dict(l=60, r=20, t=40, b=40))
        _fig_ref.update_yaxes(ticksuffix="x", row=1, col=1)
        _fig_ref.update_yaxes(ticksuffix="%", row=2, col=1)
        st.plotly_chart(_fig_ref, use_container_width=True)


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
    @st.cache_data(ttl=86400)
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
    st.caption(f"上次脚本运行：{_m2_last_upd} ｜ 初始资金：${_m2_init_cap:,.0f}")

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
        st.caption(f"信号日期：{sig_date} ｜ Regime：{'🟢 BULL' if sig_regime == 'BULL' else '🔴 BEAR'}" +
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
                st.dataframe(_ex_df, use_container_width=True, hide_index=True)
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
                st.dataframe(_en_df, use_container_width=True, hide_index=True)
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
            _m2_raw = _fetch_yf(_m2_tickers, "300d")

        _m2_live = [_enrich_position(p, _m2_raw) for p in _m2_positions]
        _m2_ok   = [p for p in _m2_live if p.get("_ok")]
        _m2_stp  = [p for p in _m2_ok if p["is_stopped"]]

        if _m2_stp:
            st.warning(f"⚠️ **{len(_m2_stp)} 只已触及止损** — IB 脚本运行后将自动生成退出订单")

        _m2_rows = [{
            "标的": p["ticker"],
            "状态": "🔴 触止损" if p["is_stopped"] else "🟢 持有",
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
            st.dataframe(pd.DataFrame(_m2_rows), use_container_width=True, hide_index=True)
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
        if "pnl_r_est" in _m2_ct.columns:
            _m2_ct["R"] = _m2_ct["pnl_r_est"].map(lambda v: f"{v:+.2f}R")
        if "net_pnl_est" in _m2_ct.columns:
            _m2_ct["净盈亏(估)"] = _m2_ct["net_pnl_est"].map(lambda v: f"${v:+,.0f}")
        cols = [c for c in ["ticker","entry_date","exit_date","holding_days","R","净盈亏(估)","exit_reason"] if c in _m2_ct.columns]
        st.dataframe(_m2_ct[cols].rename(columns={"ticker":"标的","entry_date":"入场日","exit_date":"出场日","holding_days":"天数","exit_reason":"原因"}),
                     use_container_width=True, hide_index=True)
        st.markdown("---")

    # ── Order history ─────────────────────────────────────────────────────────
    if _m2_orders_hist:
        with st.expander(f"📋 订单历史（最近 {min(50, len(_m2_orders_hist))} 条）"):
            _ord_df = pd.DataFrame(_m2_orders_hist[-50:][::-1])
            _show_cols = [c for c in ["ticker","action","shares","order_type","reason","signal_price","stop_price","ib_status","submitted_at","dry_run"] if c in _ord_df.columns]
            st.dataframe(_ord_df[_show_cols], use_container_width=True, hide_index=True)

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
