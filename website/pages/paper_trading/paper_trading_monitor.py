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

_results = _root / "results" / "v1_unbiased_60m_2000"
_pt_file = _root / "results" / "paper_trading" / "positions.json"

# ── Strategy constants ────────────────────────────────────────────────────────
_TRAIL_R1   = 3.0
_TRAIL_R3   = 3.0
_TRAIL_R5   = 5.0
_ATR_PERIOD = 20
_SMA_WINDOW = 200

# ── Page header ───────────────────────────────────────────────────────────────
st.title("策略1.0 模拟交易监控")
st.caption("数据来源：Yahoo Finance（每小时自动刷新）| 止损价格基于最新 ATR-20 实时计算")

# ── Load paper trading state (fallback: build from backtest data) ─────────────
@st.cache_data(ttl=86400)
def _load_pt_state():
    if _pt_file.exists():
        return json.loads(_pt_file.read_text()), False
    # Fallback: build initial state from backtest trades + nav
    trades = pd.read_csv(_results / "trades.csv", parse_dates=["entry_date", "exit_date"])
    nav_df = pd.read_csv(_results / "nav.csv", index_col=0, parse_dates=True)
    open_pos = trades[trades["exit_reason"] == "end_of_backtest"].copy()
    initial_nav = float(nav_df["nav"].iloc[-1])
    market_value = float((open_pos["exit_price"] * open_pos["shares"]).sum())
    cash = initial_nav - market_value
    positions = []
    for _, r in open_pos.iterrows():
        positions.append({
            "ticker":            r["ticker"],
            "entry_date":        str(r["entry_date"].date()),
            "entry_price":       float(r["entry_price"]),
            "shares":            int(r["shares"]),
            "initial_stop_loss": float(r["stop_loss"]),
            "current_stop_loss": float(r["stop_loss"]),
            "peak_price":        float(r["exit_price"]),
            "atr_at_entry":      float(r["atr_at_entry"]),
            "R_at_backtest_end": float(r["pnl_r_multiple"]),
            "last_known_price":  float(r["exit_price"]),
            "last_price_date":   "2026-06-15",
        })
    state = {
        "schema_version": 1, "initialized_from": "backtest_end",
        "backtest_end_date": "2026-06-15", "last_update_date": "2026-06-15",
        "initial_nav": round(initial_nav, 2), "cash": round(cash, 2),
        "positions": positions, "closed_trades": [],
        "nav_history": [{"date": "2026-06-15", "nav": round(initial_nav, 2)}],
    }
    return state, True   # True = fallback mode

_state, _fallback = _load_pt_state()
if _fallback:
    st.info("ℹ️ 使用回测继承数据（positions.json 未找到，正在从回测结果初始化）")

_positions     = [p for p in _state["positions"] if not p.get("closed")]
_closed_trades = _state.get("closed_trades", [])
_nav_history   = _state.get("nav_history", [])
_last_update   = _state.get("last_update_date", "N/A")
_initial_nav   = _state["initial_nav"]
_cash          = _state.get("cash", 0.0)

# ── Yahoo Finance data ────────────────────────────────────────────────────────
_pos_tickers = [p["ticker"] for p in _positions]
_all_tickers = tuple(sorted(set(_pos_tickers + ["SPY"])))

@st.cache_data(ttl=3600)
def _fetch_yf(tickers: tuple, period: str = "300d") -> pd.DataFrame:
    import yfinance as yf
    if not tickers:
        return pd.DataFrame()
    return yf.download(list(tickers), period=period, auto_adjust=True, progress=False)

with st.spinner("从 Yahoo Finance 加载最新行情…"):
    _yf_raw = _fetch_yf(_all_tickers, period="300d")


def _get_df(ticker: str) -> pd.DataFrame | None:
    if _yf_raw.empty:
        return None
    if isinstance(_yf_raw.columns, pd.MultiIndex):
        if ticker not in _yf_raw.columns.get_level_values(1):
            return None
        df = _yf_raw.xs(ticker, level=1, axis=1).dropna(subset=["Close"])
    else:
        df = _yf_raw.dropna(subset=["Close"])
    return df if not df.empty else None


# ── ATR (Wilder) ─────────────────────────────────────────────────────────────
def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    tr = pd.concat(
        [high - low,
         (high - close.shift(1)).abs(),
         (low  - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


# ── Live position enrichment ──────────────────────────────────────────────────
def _enrich(pos: dict) -> dict:
    df = _get_df(pos["ticker"])
    if df is None:
        return {**pos, "_ok": False}

    entry_dt    = pd.to_datetime(pos["entry_date"])
    since_entry = df[df.index >= entry_dt]
    if since_entry.empty:
        return {**pos, "_ok": False}

    cur_price  = float(since_entry["Close"].iloc[-1])
    cur_date   = str(since_entry.index[-1].date())
    peak_price = max(pos["peak_price"], float(since_entry["High"].max()))

    atr_s   = _wilder_atr(df["High"], df["Low"], df["Close"], _ATR_PERIOD)
    cur_atr = float(atr_s.iloc[-1])
    if pd.isna(cur_atr):
        cur_atr = pos["atr_at_entry"]

    risk = pos["entry_price"] - pos["initial_stop_loss"]
    R    = (cur_price - pos["entry_price"]) / risk if risk > 0 else 0.0

    trail_mult = _TRAIL_R5 if R >= 3.0 else (_TRAIL_R3 if R >= 1.0 else _TRAIL_R1)
    new_stop   = peak_price - trail_mult * cur_atr
    cur_stop   = max(pos["current_stop_loss"], new_stop)

    mkt_value      = cur_price * pos["shares"]
    unreal_pnl     = (cur_price - pos["entry_price"]) * pos["shares"]
    stop_buffer_pct = (cur_price - cur_stop) / cur_price * 100
    is_stopped     = cur_price <= cur_stop

    return {
        **pos,
        "_ok":            True,
        "current_price":  cur_price,
        "current_date":   cur_date,
        "peak_price":     peak_price,
        "current_atr":    cur_atr,
        "current_stop":   cur_stop,
        "trail_mult":     trail_mult,
        "R":              R,
        "mkt_value":      mkt_value,
        "unreal_pnl":     unreal_pnl,
        "stop_buffer_pct": stop_buffer_pct,
        "is_stopped":     is_stopped,
    }


_live = [_enrich(p) for p in _positions]
_ok   = [p for p in _live if p["_ok"]]
_active  = [p for p in _ok if not p["is_stopped"]]
_stopped = [p for p in _ok if p["is_stopped"]]

# ── SPY regime ────────────────────────────────────────────────────────────────
_spy_df    = _get_df("SPY")
_spy_close = None
_spy_sma   = None
_bull      = False
if _spy_df is not None and len(_spy_df) >= _SMA_WINDOW:
    _spy_close = float(_spy_df["Close"].iloc[-1])
    _spy_sma   = float(_spy_df["Close"].rolling(_SMA_WINDOW).mean().iloc[-1])
    _bull      = _spy_close > _spy_sma

# ── NAV estimate ──────────────────────────────────────────────────────────────
_total_mkt    = sum(p["mkt_value"] for p in _ok)
_total_unreal = sum(p["unreal_pnl"] for p in _ok)
_est_nav      = _total_mkt + _cash
_data_date    = max((p.get("current_date", "") for p in _ok), default="N/A")

# ═══════════════════════════════════════════════════════════════════════════════
# Section 1 — Overview
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("一、策略状态概览")
st.caption(f"行情日期：{_data_date} ｜ 上次日常更新：{_last_update} ｜ Yahoo Finance（1小时缓存）")

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "模拟交易 NAV（估算）",
    f"${_est_nav / 1e6:.2f}M",
    delta=f"{(_est_nav / _initial_nav - 1) * 100:+.2f}% vs 起始",
    help=f"持仓市值 ${_total_mkt/1e6:.2f}M + 现金 ${_cash/1e6:.2f}M",
)
c2.metric(
    "当前持仓",
    f"{len(_active)} 只",
    delta=f"触及止损 {len(_stopped)} 只" if _stopped else None,
    delta_color="inverse" if _stopped else "normal",
)
c3.metric(
    "持仓浮盈",
    f"${_total_unreal / 1e6:+.2f}M",
    delta=f"{_total_unreal / _est_nav * 100:+.1f}% NAV" if _est_nav else None,
    help="持仓当前市值 − 入场成本（未扣除佣金）",
)
c4.metric(
    "现金",
    f"${_cash / 1e6:.2f}M",
    help="可用于新开仓的现金（每次止损出场后增加）",
)

# ── Regime status ─────────────────────────────────────────────────────────────
st.markdown("#### 市场环境（Regime Filter）")
_rc1, _rc2 = st.columns([1, 3])
with _rc1:
    if _bull:
        st.markdown(
            '<div style="background:#2ca02c;color:white;padding:18px 24px;border-radius:10px;'
            'text-align:center;font-size:18px;font-weight:bold;">✅ 允许开仓</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="background:#d62728;color:white;padding:18px 24px;border-radius:10px;'
            'text-align:center;font-size:18px;font-weight:bold;">🚫 暂停开仓</div>',
            unsafe_allow_html=True,
        )
with _rc2:
    if _spy_close and _spy_sma:
        _gap = (_spy_close / _spy_sma - 1) * 100
        if _bull:
            st.success(f"SPY ${_spy_close:.2f} ＞ SMA200 ${_spy_sma:.2f}（高出 {_gap:+.1f}%）→ Regime 通过，允许新开仓")
        else:
            st.error(f"SPY ${_spy_close:.2f} ＜ SMA200 ${_spy_sma:.2f}（低 {abs(_gap):.1f}%）→ Regime 拦截，暂停新开仓")
    else:
        st.warning("无法获取 SPY 数据，Regime 状态未知")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# Section 2 — Live Positions
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("二、当前持仓实时状态（Yahoo Finance）")

if _stopped:
    st.warning(f"⚠️ **{len(_stopped)} 只持仓已触及移动止损** — 当前价 ≤ 当前止损价，建议执行止损出场。")

if _ok:
    _rows = []
    for p in sorted(_ok, key=lambda x: x.get("R", 0), reverse=True):
        _rows.append({
            "标的":      p["ticker"],
            "状态":      "🔴 触及止损" if p["is_stopped"] else "🟢 持有",
            "入场日":    p["entry_date"],
            "入场价":    f"${p['entry_price']:.2f}",
            "当前价":    f"${p['current_price']:.2f}",
            "移动止损":  f"${p['current_stop']:.2f}",
            "止损缓冲":  f"{p['stop_buffer_pct']:.1f}%",
            "浮盈 R":    f"{p['R']:+.2f}R",
            "浮盈 $":    f"${p['unreal_pnl']:+,.0f}",
            "市值":      f"${p['mkt_value']/1e3:.0f}K",
            "股数":      f"{p['shares']:,}",
        })
    st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)

    # R-multiple bar chart
    _sorted = sorted(_ok, key=lambda x: x.get("R", 0), reverse=True)
    _tks    = [p["ticker"] for p in _sorted]
    _Rs     = [p["R"] for p in _sorted]
    _cols   = ["#d62728" if p["is_stopped"] else ("#2ca02c" if r >= 0 else "#ff7f0e")
                for p, r in zip(_sorted, _Rs)]
    _fig_r  = go.Figure(go.Bar(
        y=_tks, x=_Rs, orientation="h", marker_color=_cols,
        text=[f"{v:+.2f}R" for v in _Rs], textposition="outside",
        hovertemplate="<b>%{y}</b><br>R = %{x:+.2f}<extra></extra>",
    ))
    _fig_r.update_layout(
        title="持仓实时浮盈（R 倍数）— 红色 = 已触及止损",
        xaxis_title="R 倍数",
        height=max(400, len(_tks) * 28),
        margin=dict(l=70, r=100, t=50, b=40),
        template="plotly_white",
        showlegend=False,
    )
    st.plotly_chart(_fig_r, use_container_width=True)
else:
    st.info("当前无持仓数据（Yahoo Finance 未能返回行情）。")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 — Trailing Stop Detail
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("三、移动止损明细")
st.caption("止损价 = max(继承止损, 历史最高价 − 止损乘数 × ATR20)，只能向上棘轮，不能下调")

if _ok:
    _stop_rows = sorted(_ok, key=lambda x: x.get("stop_buffer_pct", 999))
    _sd = pd.DataFrame([{
        "标的":         p["ticker"],
        "状态":         "🔴 触及" if p["is_stopped"] else "✅",
        "入场价":       f"${p['entry_price']:.2f}",
        "当前价":       f"${p['current_price']:.2f}",
        "历史最高":     f"${p['peak_price']:.2f}",
        "ATR(20)":      f"${p['current_atr']:.2f}",
        "止损乘数":     f"{p['trail_mult']:.1f}×",
        "当前止损价":   f"${p['current_stop']:.2f}",
        "价格距止损":   f"{p['stop_buffer_pct']:.1f}%",
    } for p in _stop_rows])
    st.dataframe(_sd, use_container_width=True, hide_index=True)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# Section 4 — NAV History
# ═══════════════════════════════════════════════════════════════════════════════
if _nav_history:
    st.subheader("四、模拟交易 NAV 走势")
    _nh = pd.DataFrame(_nav_history)
    _nh["date"] = pd.to_datetime(_nh["date"])
    _nh = _nh.sort_values("date")

    # Append today's live estimate if not already present
    if _data_date != "N/A":
        _today_dt = pd.to_datetime(_data_date)
        if not (_nh["date"] == _today_dt).any():
            _nh = pd.concat(
                [_nh, pd.DataFrame([{"date": _today_dt, "nav": _est_nav}])],
                ignore_index=True,
            )

    _norm = _nh["nav"] / _initial_nav
    _fig_nav = go.Figure(go.Scatter(
        x=_nh["date"], y=_norm,
        mode="lines+markers",
        line=dict(color="#1f77b4", width=2.5),
        hovertemplate="%{x|%Y-%m-%d}<br>NAV: %{y:.3f}x<extra></extra>",
    ))
    _fig_nav.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5,
                        annotation_text="起始 NAV", annotation_position="right")
    _fig_nav.update_layout(
        title="模拟交易净值（相对起始 NAV）",
        yaxis_title="NAV 倍数",
        height=300,
        margin=dict(l=60, r=20, t=50, b=40),
        template="plotly_white",
    )
    st.plotly_chart(_fig_nav, use_container_width=True)
    st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# Section 5 — Closed Paper Trades
# ═══════════════════════════════════════════════════════════════════════════════
if _closed_trades:
    st.subheader(f"五、模拟交易平仓记录（共 {len(_closed_trades)} 笔）")
    _ct = pd.DataFrame(_closed_trades).sort_values("exit_date", ascending=False)
    _ct["R 倍数"] = _ct["pnl_r"].map(lambda v: f"{v:+.2f}R")
    _ct["净盈亏"] = _ct["net_pnl"].map(lambda v: f"${v:+,.0f}")
    _ct["退出方式"] = _ct["exit_reason"].map({"trailing_stop": "追踪止损", "stop_loss": "初始止损"}).fillna(_ct["exit_reason"])
    st.dataframe(
        _ct[["ticker", "entry_date", "exit_date", "holding_days", "entry_price", "exit_price", "R 倍数", "净盈亏", "退出方式"]].rename(
            columns={"ticker": "标的", "entry_date": "入场日", "exit_date": "出场日",
                     "holding_days": "持仓天数", "entry_price": "入场价", "exit_price": "出场价"}
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# Section 6 — How to run daily updates (instructions)
# ═══════════════════════════════════════════════════════════════════════════════
with st.expander("📋 如何运行每日更新脚本", expanded=False):
    st.markdown(f"""
每个交易日收盘后（美东时间 4PM 之后），在项目根目录运行：

```bash
# 自动使用今天日期
python src/scripts/paper_trading_daily.py

# 指定日期（用于补跑）
python src/scripts/paper_trading_daily.py --date 2026-06-20

# 跳过新开仓扫描（只更新止损 / 检查出场）
python src/scripts/paper_trading_daily.py --no-entries
```

运行后将更新 `results/paper_trading/positions.json`，**提交并推送到 GitHub** 后，本页面自动更新：

```bash
git add results/paper_trading/positions.json
git commit -m "paper trading: update YYYY-MM-DD"
git push
```

**状态文件位置：** `results/paper_trading/positions.json`
**起始 NAV：** ${_initial_nav/1e6:.2f}M（回测结束日 {_state.get('backtest_end_date', '2026-06-15')}）
**继承持仓：** {len(_state['positions'])} 只（从回测 end_of_backtest 持仓继承）
""")

# ═══════════════════════════════════════════════════════════════════════════════
# Section 7 — Backtest reference (collapsed)
# ═══════════════════════════════════════════════════════════════════════════════
with st.expander("📊 回测基准参考（策略1.0历史绩效 2000–2026）", expanded=False):
    @st.cache_data(ttl=86400)
    def _load_bt() -> tuple:
        with open(_results / "metrics.json") as f:
            m = json.load(f)
        nav = pd.read_csv(_results / "nav.csv", index_col=0, parse_dates=True)
        spy = pd.read_csv(_results / "spy_nav.csv", index_col=0, parse_dates=True)
        return m, nav, spy

    _bm, _bt_nav, _bt_spy = _load_bt()
    bm1, bm2, bm3, bm4 = st.columns(4)
    bm1.metric("CAGR",    f"{_bm.get('cagr', 0)*100:.2f}%", help="2000-01-03 → 2026-06-15")
    bm2.metric("最大回撤", f"{_bm.get('max_drawdown', 0)*100:.2f}%")
    bm3.metric("Sharpe",   f"{_bm.get('sharpe', 0):.3f}")
    bm4.metric("Calmar",   f"{_bm.get('calmar', 0):.3f}")

    _nn = _bt_nav["nav"]
    _ss = _bt_spy["spy_nav"]
    _fig_ref = make_subplots(rows=2, cols=1, shared_xaxes=True,
                              row_heights=[0.65, 0.35], vertical_spacing=0.05)
    _fig_ref.add_trace(go.Scatter(x=_nn.index, y=_nn / _nn.iloc[0], name="策略1.0",
                                   line=dict(color="#1f77b4", width=2)), row=1, col=1)
    _fig_ref.add_trace(go.Scatter(x=_ss.index, y=_ss / _ss.iloc[0], name="SPY",
                                   line=dict(color="#888", width=1.2, dash="dash")), row=1, col=1)
    _dd = (_nn - _nn.cummax()) / _nn.cummax() * 100
    _fig_ref.add_trace(go.Scatter(x=_dd.index, y=_dd.values, fill="tozeroy",
                                   fillcolor="rgba(214,39,40,0.2)",
                                   line=dict(color="#d62728", width=1),
                                   showlegend=False), row=2, col=1)
    _fig_ref.update_layout(
        height=450, template="plotly_white", hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=20, t=40, b=40),
    )
    _fig_ref.update_yaxes(ticksuffix="x", title_text="净值（倍）", row=1, col=1)
    _fig_ref.update_yaxes(ticksuffix="%", title_text="回撤", row=2, col=1)
    st.plotly_chart(_fig_ref, use_container_width=True)
