"""策略1.0模拟交易监控"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_results_path = _root / "results" / "v1_unbiased_60m_2000"

st.title("策略1.0 模拟交易监控")
st.caption("基于策略1.0回测参数的实盘前模拟验证——跟踪策略信号、持仓状态与绩效表现")

st.warning("""
⚠️ **开发中** — 本页面目前展示回测结束日（2026-06-15）的"继承持仓"作为模拟交易起点。
完整的模拟交易系统需要接入实时行情数据源（Tiingo 实时 EOD API）和每日信号生成管道，正在开发中。
""")

st.markdown("---")

# ── 加载数据 ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def _load():
    import json
    trades = pd.read_csv(_results_path / "trades.csv", parse_dates=["entry_date","exit_date"])
    trades["holding_days"] = (trades["exit_date"] - trades["entry_date"]).dt.days
    nav    = pd.read_csv(_results_path / "nav.csv", index_col=0, parse_dates=True)
    spy    = pd.read_csv(_results_path / "spy_nav.csv", index_col=0, parse_dates=True)
    with open(_results_path / "metrics.json") as f:
        metrics = json.load(f)
    return trades, nav, spy, metrics

trades, nav, spy_nav, metrics = _load()

BACKTEST_END   = "2026-06-15"
INITIAL_CAPITAL = 10_000_000
FINAL_NAV       = float(nav["nav"].iloc[-1])

# ── 一、策略状态概览 ──────────────────────────────────────────────────────────
st.subheader("一、策略状态概览")

_open = trades[trades["exit_reason"] == "end_of_backtest"].copy()
_open["unrealized_pnl"] = _open["net_pnl"]
_open["notional"]       = _open["entry_price"] * _open["shares"]
_total_unrealized       = float(_open["unrealized_pnl"].sum())
_n_open                 = len(_open)
_nav_latest             = FINAL_NAV
_cash_deployed_pct      = _open["notional"].sum() / _nav_latest * 100

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "模拟交易起始 NAV",
    f"${_nav_latest/1e6:.2f}M",
    help=f"回测结束日（{BACKTEST_END}）的策略净值，作为模拟交易起点"
)
c2.metric(
    "当前持仓数量",
    f"{_n_open} 只",
    help="回测截止时仍持有的标的，继承进入模拟交易阶段"
)
c3.metric(
    "继承持仓浮盈",
    f"${_total_unrealized/1e6:.2f}M",
    delta=f"+{_total_unrealized/_nav_latest*100:.1f}% NAV",
    help="这些持仓在回测结束时已有的浮动盈利"
)
c4.metric(
    "资金使用率（成本基础）",
    f"{_cash_deployed_pct:.1f}%",
    help="当前持仓入场成本之和 ÷ NAV"
)

# ── 策略 Regime 状态 ──────────────────────────────────────────────────────────
st.markdown("#### 市场环境（Regime Filter）状态")
_regime_col1, _regime_col2 = st.columns([1, 3])
with _regime_col1:
    st.markdown("""
<div style="background:#2ca02c;color:white;padding:18px 24px;border-radius:10px;text-align:center;font-size:20px;font-weight:bold;">
✅ 开启开仓
</div>
""", unsafe_allow_html=True)
with _regime_col2:
    st.markdown("""
**当前判断**（基于回测最终状态）：SPY 收盘价位于 200 日均线**上方** → Regime Filter 通过 → 允许新开仓信号。

> 模拟交易正式上线后，此状态将每日收盘后自动更新。
""")

st.markdown("---")

# ── 二、当前持仓明细 ──────────────────────────────────────────────────────────
st.subheader("二、当前持仓明细（继承自回测）")
st.caption(f"以下 {_n_open} 只持仓均在 {BACKTEST_END} 回测截止时仍处于开仓状态，作为模拟交易初始持仓。")

_etf_csv = _root / "data" / "ETFs.csv"
_ETF_SET = set(pd.read_csv(_etf_csv)["SYMBOL"].dropna().str.strip()) if _etf_csv.exists() else set()

_open_show = _open.copy()
_open_show["类别"]    = _open_show["ticker"].apply(lambda t: "ETF" if t in _ETF_SET else "股票")
_open_show["持仓天数 (至回测结束)"] = _open_show["holding_days"]
_open_show["浮盈 R"]  = _open_show["pnl_r_multiple"].map(lambda v: f"{v:+.2f}R")
_open_show["浮盈 ($)"] = _open_show["unrealized_pnl"].map(lambda v: f"${v:+,.0f}")
_open_show["入场价"]  = _open_show["entry_price"].map(lambda v: f"${v:.2f}")
_open_show["回测截止价"] = _open_show["exit_price"].map(lambda v: f"${v:.2f}")
_open_show["股数"]    = _open_show["shares"].map(lambda v: f"{v:,.0f}")
_open_show["入场日期"] = _open_show["entry_date"].dt.strftime("%Y-%m-%d")
_open_show_sorted = _open_show.sort_values("pnl_r_multiple", ascending=False)

st.dataframe(
    _open_show_sorted[[
        "ticker", "类别", "入场日期", "持仓天数 (至回测结束)",
        "入场价", "回测截止价", "股数", "浮盈 R", "浮盈 ($)"
    ]].rename(columns={"ticker": "标的"}),
    use_container_width=True,
    hide_index=True,
)

# 持仓浮盈分布图
_fig_pos = go.Figure(go.Bar(
    y=_open_show_sorted["ticker"].tolist(),
    x=_open_show_sorted["pnl_r_multiple"].tolist(),
    orientation="h",
    marker_color=["#2ca02c" if v >= 0 else "#d62728"
                  for v in _open_show_sorted["pnl_r_multiple"].tolist()],
    text=[f"{v:+.2f}R" for v in _open_show_sorted["pnl_r_multiple"].tolist()],
    textposition="outside",
    hovertemplate="<b>%{y}</b><br>浮盈: %{x:+.2f}R<extra></extra>",
))
_fig_pos.update_layout(
    title="当前持仓浮盈分布（R 倍数）",
    xaxis_title="浮盈 R 倍数",
    height=520,
    margin=dict(l=70, r=80, t=50, b=40),
    template="plotly_white",
    showlegend=False,
)
st.plotly_chart(_fig_pos, use_container_width=True)

st.markdown("---")

# ── 三、回测历史绩效回顾 ──────────────────────────────────────────────────────
st.subheader("三、回测历史绩效（模拟交易基准）")
st.caption("以下为回测期间完整绩效，作为模拟交易阶段的历史对照基准。")

_cagr    = metrics.get("cagr", 0)
_maxdd   = metrics.get("max_drawdown", 0)
_sharpe  = metrics.get("sharpe", 0)
_sortino = metrics.get("sortino", 0)
_calmar  = metrics.get("calmar", 0)
_pf      = metrics.get("profit_factor", 0)
_wr      = metrics.get("win_rate", 0)
_n       = metrics.get("n_trades", 0)

mc1, mc2, mc3, mc4 = st.columns(4)
mc1.metric("回测 CAGR", f"{_cagr*100:.2f}%", help="2000-01-03 → 2026-06-15")
mc2.metric("最大回撤",  f"{_maxdd*100:.2f}%")
mc3.metric("Sharpe 比率", f"{_sharpe:.3f}")
mc4.metric("Calmar 比率", f"{_calmar:.3f}")

mc5, mc6, mc7, mc8 = st.columns(4)
mc5.metric("Sortino 比率",  f"{_sortino:.3f}")
mc6.metric("Profit Factor", f"{_pf:.3f}")
mc7.metric("胜率",          f"{_wr*100:.1f}%")
mc8.metric("总交易笔数",    f"{int(_n):,}")

# ── NAV 曲线（简化版） ────────────────────────────────────────────────────────
_nav_plot  = nav["nav"].copy()
_spy_plot  = spy_nav["spy_nav"].copy()
_nav_norm  = _nav_plot / float(_nav_plot.iloc[0])
_spy_norm  = _spy_plot / float(_spy_plot.iloc[0])

_fig_nav = make_subplots(rows=2, cols=1, shared_xaxes=True,
                          row_heights=[0.65, 0.35], vertical_spacing=0.05)

_fig_nav.add_trace(go.Scatter(
    x=_nav_norm.index, y=_nav_norm.values,
    name="策略1.0", line=dict(color="#1f77b4", width=2),
    hovertemplate="%{x|%Y-%m-%d}<br>NAV: %{y:.2f}x<extra></extra>",
), row=1, col=1)
_fig_nav.add_trace(go.Scatter(
    x=_spy_norm.index, y=_spy_norm.values,
    name="SPY", line=dict(color="#888888", width=1.2, dash="dash"),
    hovertemplate="%{x|%Y-%m-%d}<br>SPY: %{y:.2f}x<extra></extra>",
), row=1, col=1)

_dd = (_nav_plot - _nav_plot.cummax()) / _nav_plot.cummax() * 100
_fig_nav.add_trace(go.Scatter(
    x=_dd.index, y=_dd.values,
    fill="tozeroy", fillcolor="rgba(214,39,40,0.2)",
    line=dict(color="#d62728", width=1),
    hovertemplate="%{x|%Y-%m-%d}<br>回撤: %{y:.1f}%<extra></extra>",
    showlegend=False,
), row=2, col=1)

_fig_nav.update_layout(
    title="策略1.0 净值曲线（回测历史）",
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=500,
    margin=dict(l=60, r=20, t=60, b=40),
    template="plotly_white",
)
_fig_nav.update_yaxes(ticksuffix="x", title_text="净值（倍）", row=1, col=1)
_fig_nav.update_yaxes(ticksuffix="%", title_text="回撤 %", row=2, col=1)
st.plotly_chart(_fig_nav, use_container_width=True)

st.markdown("---")

# ── 四、模拟交易系统建设路线图 ────────────────────────────────────────────────
st.subheader("四、模拟交易系统建设路线图")

col_a, col_b = st.columns(2)

with col_a:
    st.markdown("""
**已完成 ✅**
- 回测引擎（2000-01-03 → 2026-06-15）
- 策略参数固化（Baseline 参数集）
- 回测结果分析（本网站全部页面）
- 继承持仓确认（20 只标的）
""")

with col_b:
    st.markdown("""
**开发中 🔧**
- 每日 EOD 数据拉取管道（Tiingo API 自动化）
- 信号生成脚本（每日收盘后运行）
- 持仓跟踪数据库（SQLite / CSV 日志）
- 本页面实时数据接入
- 模拟盈亏 vs 回测对比图表
""")

st.markdown("""
#### 模拟交易 vs 回测的预期差异

| 来源 | 说明 |
|------|------|
| **数据时差** | 回测使用历史 EOD，模拟交易使用 T+0 EOD（同日数据） |
| **滑点差异** | 回测按固定 10 bps 估算，实际成交滑点因流动性而异 |
| **信号延迟** | 信号在收盘后生成，次日开盘按开盘价或指定价格执行 |
| **分红 / 拆股** | Tiingo 数据已还原，实盘需同步调整持仓成本 |
| **市场环境变化** | 2026 年后市场结构可能与回测历史存在差异 |
""")

st.markdown("---")

# ── 五、近期交易记录（回测最后30笔） ─────────────────────────────────────────
st.subheader("五、近期平仓记录（回测最后 30 笔，供参考）")

_recent = trades[trades["exit_reason"] != "end_of_backtest"].sort_values("exit_date", ascending=False).head(30).copy()
_recent["类别"]    = _recent["ticker"].apply(lambda t: "ETF" if t in _ETF_SET else "股票")
_recent["退出方式"] = _recent["exit_reason"].map({
    "trailing_stop": "追踪止损",
    "stop_loss":     "初始止损",
    "delisted":      "退市/并购",
}).fillna(_recent["exit_reason"])
_recent["R 倍数"] = _recent["pnl_r_multiple"].map(lambda v: f"{v:+.2f}R")
_recent["净盈亏"] = _recent["net_pnl"].map(lambda v: f"${v:+,.0f}")
_recent["入场日"] = _recent["entry_date"].dt.strftime("%Y-%m-%d")
_recent["出场日"] = _recent["exit_date"].dt.strftime("%Y-%m-%d")

st.dataframe(
    _recent[["ticker", "类别", "入场日", "出场日", "holding_days",
             "R 倍数", "净盈亏", "退出方式"]].rename(columns={
        "ticker": "标的", "holding_days": "持仓天数"
    }),
    use_container_width=True,
    hide_index=True,
)
