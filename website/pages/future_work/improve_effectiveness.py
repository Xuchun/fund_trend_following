"""如何改进策略有效性"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.style import show_df
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.io as _pio
from plotly.subplots import make_subplots

_pio.templates.default = "plotly_white"

_results_path = _root / "results" / "v1_unbiased_60m_2000"

st.title("如何改进策略有效性")
st.markdown(
    '基于26年回测的「策略有效性分析」，深入研究Alpha压缩的根本原因，并从数据出发提出两条可落地的改进路径'
)

st.markdown("---")

# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data
def _load_data():
    trades = pd.read_csv(
        _results_path / "trades.csv", parse_dates=["entry_date", "exit_date"]
    )
    spy = pd.read_csv(
        _results_path / "spy_nav.csv", parse_dates=["date"], index_col="date"
    )["spy_nav"]
    nav_df = pd.read_csv(
        _results_path / "nav.csv", parse_dates=["date"], index_col="date"
    )
    nav = nav_df.iloc[:, 0]
    return trades, spy, nav

trades, spy, nav = _load_data()

spy_ret_daily = spy.pct_change().dropna()
spy_200ma     = spy.rolling(200, min_periods=150).mean()
spy_vol_20    = spy_ret_daily.rolling(20).std() * np.sqrt(252)

# Aligned series (strategy vs SPY)
_idx = nav.index.intersection(spy.index)
_s   = nav[_idx] / float(nav[_idx[0]])
_b   = spy[_idx] / float(spy[_idx[0]])
_ny  = len(_idx) / 252

# Annual stats: vol, returns, alpha, trade quality
_ann_rows = []
for yr in range(_idx[0].year, _idx[-1].year + 1):
    yr_t = trades[trades["entry_date"].dt.year == yr]
    if len(yr_t) < 10:
        continue
    spy_yr   = spy_ret_daily[spy_ret_daily.index.year == yr]
    spy_vol  = float(spy_yr.std() * np.sqrt(252) * 100) if len(spy_yr) > 10 else float("nan")
    nav_yr   = _s[_s.index.year == yr]
    b_yr     = _b[_b.index.year == yr]
    s_ret = float(nav_yr.iloc[-1] / nav_yr.iloc[0] - 1) * 100 if len(nav_yr) >= 20 else float("nan")
    b_ret = float(b_yr.iloc[-1] / b_yr.iloc[0] - 1) * 100 if len(b_yr) >= 20 else float("nan")
    wr    = float((yr_t["net_pnl"] > 0).mean() * 100)
    avg_r = float(yr_t["pnl_r_multiple"].mean())
    pct3r = float((yr_t["pnl_r_multiple"] >= 3).mean() * 100)
    _ann_rows.append({
        "year": yr, "spy_vol": spy_vol, "s_ret": s_ret, "b_ret": b_ret,
        "alpha": s_ret - b_ret, "wr": wr, "avg_r": avg_r, "pct3r": pct3r,
    })
ann = pd.DataFrame(_ann_rows).dropna()

# Vol regime tagging for trades
entry_dates = pd.DatetimeIndex(trades["entry_date"])
trades = trades.copy()
trades["spy_vol_entry"] = spy_vol_20.reindex(entry_dates, method="ffill").values
trades["spy_ma_ratio"]  = (spy.reindex(entry_dates, method="ffill").values /
                            spy_200ma.reindex(entry_dates, method="ffill").values - 1)

# ── Section 1: 核心发现 ────────────────────────────────────────────────────────
st.subheader("一、核心发现：策略 Alpha 与市场波动率正相关")

# Correlation
_corr = float(ann["spy_vol"].corr(ann["alpha"]))
_hv   = ann[ann["spy_vol"] > 20]
_lv   = ann[ann["spy_vol"] <= 20]
_hv_alpha_avg = float(_hv["alpha"].mean())
_lv_alpha_avg = float(_lv["alpha"].mean())
_hv_beat = int((_hv["alpha"] > 0).sum())
_lv_beat = int((_lv["alpha"] > 0).sum())

col1, col2, col3 = st.columns(3)
col1.metric("波动率与Alpha相关系数", f"{_corr:.2f}")
col2.metric(f"高波动年（>20%）平均Alpha", f"{_hv_alpha_avg:+.1f} pp")
col3.metric(f"低波动年（≤20%）平均Alpha", f"{_lv_alpha_avg:+.1f} pp")

# Chart 1a: Scatter SPY vol vs Alpha
fig_scatter = go.Figure()
_colors_s = ["#2ca02c" if a > 0 else "#d62728" for a in ann["alpha"]]
fig_scatter.add_trace(go.Scatter(
    x=ann["spy_vol"], y=ann["alpha"],
    mode="markers+text",
    text=ann["year"].astype(str),
    textposition="top center",
    textfont=dict(size=10),
    marker=dict(color=_colors_s, size=10, opacity=0.85),
    hovertemplate="<b>%{text}</b><br>SPY波动率: %{x:.1f}%<br>Alpha: %{y:+.1f} pp<extra></extra>",
))
# Trend line
_z = np.polyfit(ann["spy_vol"], ann["alpha"], 1)
_xline = np.linspace(ann["spy_vol"].min(), ann["spy_vol"].max(), 50)
fig_scatter.add_trace(go.Scatter(
    x=_xline, y=np.polyval(_z, _xline),
    mode="lines", name="趋势线",
    line=dict(color="gray", dash="dash", width=1.5),
    showlegend=False,
))
fig_scatter.add_hline(y=0, line_color="rgba(0,0,0,0.4)", line_width=1)
fig_scatter.add_vline(x=20, line_color="rgba(255,140,0,0.4)", line_width=1.5,
                      annotation_text="20% 分界", annotation_position="top right")
fig_scatter.update_layout(
    title=f"年度超额收益（Alpha）vs SPY 年化波动率（相关系数 r = {_corr:.2f}）",
    xaxis_title="SPY 年化波动率（%）",
    yaxis_title="策略 Alpha（pp）",
    height=400,
    margin=dict(l=60, r=30, t=55, b=50),
)
st.plotly_chart(fig_scatter, width="stretch")

# Chart 1b: Dual-axis time series: SPY vol (bars) + Alpha (line)
fig_ts = make_subplots(specs=[[{"secondary_y": True}]])
_ylabs = [str(y) + ("*" if y == int(ann["year"].iloc[-1]) else "") for y in ann["year"]]
fig_ts.add_trace(go.Bar(
    name="SPY 年化波动率",
    x=_ylabs, y=ann["spy_vol"].round(1),
    marker_color="rgba(31,119,180,0.5)",
    hovertemplate="<b>%{x}</b><br>SPY波动率: %{y:.1f}%<extra></extra>",
), secondary_y=False)
_alpha_colors = ["#2ca02c" if a > 0 else "#d62728" for a in ann["alpha"]]
fig_ts.add_trace(go.Scatter(
    name="策略 Alpha",
    x=_ylabs, y=ann["alpha"].round(1),
    mode="lines+markers",
    marker=dict(color=_alpha_colors, size=8),
    line=dict(color="rgba(100,100,100,0.7)", width=1.5),
    hovertemplate="<b>%{x}</b><br>Alpha: %{y:+.1f} pp<extra></extra>",
), secondary_y=True)
fig_ts.add_hline(y=0, secondary_y=True, line_color="black", line_width=1)
fig_ts.update_layout(
    title="逐年 SPY 波动率（蓝色柱）与策略超额收益 Alpha（折线）",
    height=380,
    margin=dict(l=60, r=60, t=55, b=50),
    legend=dict(orientation="h", x=0, y=1.08),
)
fig_ts.update_yaxes(title_text="SPY 年化波动率（%）", secondary_y=False)
fig_ts.update_yaxes(title_text="Alpha（pp）", secondary_y=True)
st.plotly_chart(fig_ts, width="stretch")

st.markdown(
    f'<div style="background:#f0f4ff;border-left:4px solid #1f77b4;padding:12px 16px;border-radius:4px;margin:8px 0">'
    f'<strong>关键结论：</strong> 过去26年中，<strong>高波动年份（>20%）策略平均跑赢SPY {_hv_alpha_avg:+.1f} pp</strong>，'
    f'{len(_hv)}个高波动年中有 {_hv_beat} 年超越SPY；而<strong>低波动年份（≤20%）平均仅 {_lv_alpha_avg:+.1f} pp</strong>，'
    f'{len(_lv)}个低波动年中仅 {_lv_beat} 年超越SPY。'
    f'Alpha与SPY年化波动率的Pearson相关系数为 <strong>{_corr:.2f}</strong>，两者正相关关系明显。'
    f'</div>',
    unsafe_allow_html=True,
)

st.markdown("---")

# ── Section 2: 根本原因 ────────────────────────────────────────────────────────
st.subheader("二、根本原因：牛市中 SPY 的复利增速超过策略的捕获能力")

st.markdown(
    "Alpha压缩的根源不在于策略「变差」，而在于**低波动牛市中大盘指数的复利速度超过了趋势跟踪策略所能匹配的上限**。"
    "以下从两个维度拆解这一现象："
)

# 2a: Regime trade quality table
_reg_rows = []
for label, lo, hi in [
    ("低波动 SPY vol < 12%",   0.00, 0.12),
    ("中波动 12% ≤ vol < 20%", 0.12, 0.20),
    ("高波动 vol ≥ 20%",       0.20, 1.00),
]:
    m = (trades["spy_vol_entry"] >= lo) & (trades["spy_vol_entry"] < hi)
    g = trades[m]
    _reg_rows.append({
        "入场时市场波动率": label,
        "交易笔数": len(g),
        "占总交易%": f"{len(g)/len(trades)*100:.0f}%",
        "胜率": f"{(g['net_pnl']>0).mean()*100:.1f}%",
        "平均R倍数": round(float(g["pnl_r_multiple"].mean()), 3),
        "3R+占比": f"{(g['pnl_r_multiple']>=3).mean()*100:.0f}%",
        "5R+占比": f"{(g['pnl_r_multiple']>=5).mean()*100:.0f}%",
    })
reg_df = pd.DataFrame(_reg_rows)
show_df(reg_df, width="stretch", hide_index=True)

# Bar chart: win rate by regime
fig_reg = go.Figure()
_reg_labels = ["低波动\n(<12%)", "中波动\n(12-20%)", "高波动\n(≥20%)"]
_reg_wr  = [float(r["胜率"].replace("%","")) for r in _reg_rows]
_reg_avgr = [float(r["平均R倍数"]) for r in _reg_rows]
fig_reg.add_trace(go.Bar(
    name="胜率",
    x=_reg_labels, y=_reg_wr,
    marker_color=["#1f77b4","#2ca02c","#ff7f0e"],
    text=[f"{v:.1f}%" for v in _reg_wr],
    textposition="outside",
    yaxis="y",
))
fig_reg.add_trace(go.Scatter(
    name="平均R倍数",
    x=_reg_labels, y=_reg_avgr,
    mode="markers+lines",
    marker=dict(size=12, color=["#1f77b4","#2ca02c","#ff7f0e"],
                line=dict(color="black", width=1.5)),
    line=dict(color="gray", dash="dash", width=1.5),
    yaxis="y2",
))
fig_reg.update_layout(
    title="不同市场波动率环境下的交易质量",
    yaxis=dict(title="胜率（%）", range=[25, 50]),
    yaxis2=dict(title="平均R倍数", overlaying="y", side="right", range=[-0.1, 0.6]),
    height=360,
    margin=dict(l=60, r=60, t=55, b=60),
    legend=dict(orientation="h", x=0, y=1.08),
)
st.plotly_chart(fig_reg, width="stretch")

st.markdown(
    "**核心洞察：**\n\n"
    "- 中波动区间（12-20%）是策略最优秀的交易环境：胜率最高（42.2%），平均R最大（0.401）。\n"
    "- 高波动环境（>20%）下单笔交易胜率最低（32.5%），但正是在这些年份策略最能跑赢SPY——"
    "因为SPY本身也大跌，策略的回撤保护机制发挥了作用。\n"
    "- 低波动环境（<12%）下交易质量下滑（37.7%胜率），同时SPY在低波动中往往单边大涨，"
    "造成策略跑输大盘的体感最强。"
)

# 2b: "Sluggish bull" analysis - SPY >15% years where strategy lagged
st.markdown("#### 策略在「高速牛市」中的追赶极限")
_bull_drag = ann[(ann["b_ret"] > 15) & (ann["alpha"] < 0)].sort_values("alpha")
_bull_drag_show = _bull_drag[["year","b_ret","s_ret","alpha","spy_vol"]].copy()
_bull_drag_show.columns = ["年份","SPY年度收益%","策略年度收益%","Alpha pp","SPY波动率%"]
_bull_drag_show = _bull_drag_show.round(1)
st.markdown(
    f"以下 **{len(_bull_drag)} 年**中，SPY 年度涨幅 > 15% 且策略跑输，"
    "平均Alpha = "
    f"**{_bull_drag['alpha'].mean():+.1f} pp**："
)
show_df(_bull_drag_show, width="stretch", hide_index=True)
st.markdown(
    "在这些年份，SPY 以 15-31% 的年化速度复利增长，而趋势跟踪策略受制于 ~39% 的胜率，"
    "累计收益被大幅拉开差距。**提高胜率或让盈利单跑得更远**是应对的两条核心路径。"
)

st.markdown("---")

# ── Section 3 (new): 改进路径一 ──────────────────────────────────────────────
st.subheader("三、改进路径一：熊市中加入 SPY 反向敞口（做空对冲）")

st.markdown(
    "策略在熊市中依靠移动止盈保护资本，但未能主动**从下跌中获利**。"
    "当 SPY 处于确认熊市（低于200日均线）时，叠加 20% 的指数反向敞口（如购买 SH 等反向 ETF），"
    "可在熊市年份显著提升收益。"
)

# Simulate overlay: 80% strategy + 20% (-SPY) when SPY < 200MA
_s_ret_d  = _s.pct_change().fillna(0)
_b_ret_d  = _b.pct_change().fillna(0)
_in_bear  = (spy[_idx] < spy_200ma[_idx]).fillna(False)

_blend_ret = _s_ret_d.copy()
_blend_ret[_in_bear] = 0.80 * _s_ret_d[_in_bear] + 0.20 * (-_b_ret_d[_in_bear])
_blend_nav = (1 + _blend_ret).cumprod()

# Stats
_s_cagr   = (float(_s.iloc[-1]) ** (1 / _ny) - 1) * 100
_b_cagr   = (float(_b.iloc[-1]) ** (1 / _ny) - 1) * 100
_bl_cagr  = (float(_blend_nav.iloc[-1]) ** (1 / _ny) - 1) * 100
_s_dd     = float(((_s - _s.cummax()) / _s.cummax()).min()) * 100
_bl_dd    = float(((_blend_nav - _blend_nav.cummax()) / _blend_nav.cummax()).min()) * 100
_s_sh     = float(_s_ret_d.mean() / _s_ret_d.std() * np.sqrt(252))
_bl_sh    = float(_blend_ret.mean() / _blend_ret.std() * np.sqrt(252))
_n_bear_d = int(_in_bear.sum())
_n_total_d = len(_in_bear)

_stat_rows = [
    {"指标": "年化收益 CAGR", "当前策略": f"{_s_cagr:.2f}%", "加入熊市对冲后": f"{_bl_cagr:.2f}%"},
    {"指标": "最大回撤", "当前策略": f"{_s_dd:.2f}%", "加入熊市对冲后": f"{_bl_dd:.2f}%"},
    {"指标": "Sharpe 比率", "当前策略": f"{_s_sh:.2f}", "加入熊市对冲后": f"{_bl_sh:.2f}"},
    {"指标": "vs SPY Alpha", "当前策略": f"{_s_cagr - _b_cagr:+.2f} pp", "加入熊市对冲后": f"{_bl_cagr - _b_cagr:+.2f} pp"},
]
show_df(pd.DataFrame(_stat_rows), width="stretch", hide_index=True)

# Annual year-by-year for key bear years
_yr_rows = []
for yr in ann["year"]:
    s_yr = _s[_s.index.year == yr]
    b_yr = _b[_b.index.year == yr]
    bl_yr = _blend_nav[_blend_nav.index.year == yr]
    if len(s_yr) < 20:
        continue
    sr = float(s_yr.iloc[-1] / s_yr.iloc[0] - 1) * 100
    br = float(b_yr.iloc[-1] / b_yr.iloc[0] - 1) * 100
    blr = float(bl_yr.iloc[-1] / bl_yr.iloc[0] - 1) * 100
    _yr_rows.append({"year": yr, "s": sr, "b": br, "bl": blr,
                     "alpha_base": sr - br, "alpha_blend": blr - br})
yr_df = pd.DataFrame(_yr_rows)

# Chart: nav curves
fig_nav = go.Figure()
fig_nav.add_trace(go.Scatter(
    name="策略1.0（当前）",
    x=_s.index, y=_s.values,
    mode="lines", line=dict(color="#2ca02c", width=2),
))
fig_nav.add_trace(go.Scatter(
    name="策略1.0 + 熊市对冲（20% 反向SPY）",
    x=_blend_nav.index, y=_blend_nav.values,
    mode="lines", line=dict(color="#ff7f0e", width=2, dash="dot"),
))
fig_nav.add_trace(go.Scatter(
    name="SPY（基准）",
    x=_b.index, y=_b.values,
    mode="lines", line=dict(color="#1f77b4", width=1.5, dash="dash"),
    opacity=0.6,
))
fig_nav.update_layout(
    title="净值曲线对比：当前策略 vs 加入熊市对冲后",
    yaxis_title="净值（初始 = 1.0）",
    height=400,
    margin=dict(l=60, r=30, t=55, b=50),
    legend=dict(orientation="h", x=0, y=1.10),
)
st.plotly_chart(fig_nav, width="stretch")

# Bar: annual return comparison for key years
_key_years = yr_df[(yr_df["b"] < -10) | (yr_df["alpha_blend"] - yr_df["alpha_base"] > 3)].sort_values("year")
fig_annual = go.Figure()
fig_annual.add_trace(go.Bar(
    name="当前策略 Alpha",
    x=_key_years["year"].astype(str),
    y=_key_years["alpha_base"].round(1),
    marker_color="#2ca02c",
    offsetgroup=0,
))
fig_annual.add_trace(go.Bar(
    name="加入熊市对冲后 Alpha",
    x=_key_years["year"].astype(str),
    y=_key_years["alpha_blend"].round(1),
    marker_color="#ff7f0e",
    offsetgroup=1,
))
fig_annual.add_hline(y=0, line_color="black", line_width=1)
fig_annual.update_layout(
    title="主要熊市 / 震荡年份：加入对冲前后 Alpha 对比",
    xaxis_title="年份",
    yaxis_title="Alpha（pp）",
    barmode="group",
    height=360,
    margin=dict(l=60, r=30, t=55, b=50),
    legend=dict(orientation="h", x=0, y=1.08),
)
st.plotly_chart(fig_annual, width="stretch")

st.markdown(
    f'<div style="background:#f0f4ff;border-left:4px solid #ff7f0e;padding:12px 16px;border-radius:4px;margin:8px 0">'
    f'<strong>模拟结果：</strong>历史上 SPY 有 {_n_bear_d} 个交易日（占 {_n_bear_d/_n_total_d*100:.0f}%）处于200日均线以下。'
    f'在这些日期叠加 20% 反向 SPY 敞口后，策略 CAGR 从 {_s_cagr:.1f}% 提升至 {_bl_cagr:.1f}%，'
    f'Sharpe 比率从 {_s_sh:.2f} 提升至 {_bl_sh:.2f}，最大回撤从 {_s_dd:.1f}% 改善至 {_bl_dd:.1f}%。'
    f'</div>',
    unsafe_allow_html=True,
)

st.markdown(
    "**实施建议：**\n\n"
    "- **触发条件**：SPY 低于200日均线且持续 10 个交易日以上（避免假信号），将 20% 仓位配置至反向 ETF（如 SH）。\n"
    "- **退出条件**：SPY 重回200日均线以上时，平仓反向 ETF，恢复全仓趋势跟踪策略。\n"
    "- **风险提示**：如果 SPY 出现快速 V 形反转（如 2020年3月）,持有反向 ETF 可能放大短期亏损。"
    " 建议同时设置反向 ETF 仓位的止损线（如跌幅超过 10% 平仓）。\n"
    "- **本质**：这不改变策略的信号逻辑，只是在已知熊市环境中增加一个对冲层，"
    "是策略进化的轻量化路径。"
)

st.markdown("---")

# ── Section 5: 改进路径三 ─────────────────────────────────────────────────────
st.subheader("四、改进路径二：让大赢家持仓更久（减少过早退出）")

st.markdown(
    "策略的 Alpha 在很大程度上依赖于少数**高 R 倍数的大赢家**。"
    "如果在低波动牛市中能让这些胜利者持仓更长时间，将能更好地捕捉长期趋势。"
)

# Winner holding days by era + R tier
_era_defs = [("2000−2007", 2000, 2007), ("2008−2015", 2008, 2015), ("2016−2025", 2016, 2025)]
_hold_rows = []
for ename, y1, y2 in _era_defs:
    m = (trades["entry_date"].dt.year >= y1) & (trades["entry_date"].dt.year <= y2)
    t = trades[m]
    wins = t[t["net_pnl"] > 0]
    all_w = wins["holding_days"].mean() if len(wins) > 0 else float("nan")
    w_3r  = wins[wins["pnl_r_multiple"] >= 3]["holding_days"].mean() if len(wins[wins["pnl_r_multiple"] >= 3]) > 0 else float("nan")
    w_5r  = wins[wins["pnl_r_multiple"] >= 5]["holding_days"].mean() if len(wins[wins["pnl_r_multiple"] >= 5]) > 0 else float("nan")
    n_3r  = len(wins[wins["pnl_r_multiple"] >= 3])
    pct_3r = float((t["pnl_r_multiple"] >= 3).mean() * 100)
    _hold_rows.append({
        "阶段": ename,
        "3R+占比": f"{pct_3r:.0f}%",
        "3R+笔数": n_3r,
        "所有盈利单平均持仓（天）": round(all_w, 1),
        "3R+盈利单平均持仓（天）": round(w_3r, 1),
        "5R+盈利单平均持仓（天）": round(w_5r, 1) if not np.isnan(w_5r) else "—",
    })
show_df(pd.DataFrame(_hold_rows), width="stretch", hide_index=True)

# Scatter: pnl_r_multiple vs holding_days for winning trades
_wins_plot = trades[trades["net_pnl"] > 0].copy()
_wins_plot["era"] = pd.cut(
    _wins_plot["entry_date"].dt.year,
    bins=[1999, 2007, 2015, 2026],
    labels=["2000−2007", "2008−2015", "2016−2025"],
)
_era_colors = {"2000−2007": "#1f77b4", "2008−2015": "#ff7f0e", "2016−2025": "#2ca02c"}
fig_hold = go.Figure()
for era, color in _era_colors.items():
    g = _wins_plot[_wins_plot["era"] == era]
    fig_hold.add_trace(go.Scatter(
        name=era,
        x=g["holding_days"],
        y=g["pnl_r_multiple"],
        mode="markers",
        marker=dict(color=color, size=5, opacity=0.5),
        hovertemplate="%{text}<br>持仓: %{x}天<br>盈亏: %{y:.1f}R<extra></extra>",
        text=g["ticker"],
    ))
fig_hold.update_layout(
    title="盈利交易：持仓天数 vs 盈亏R倍数（按时代分色）",
    xaxis_title="持仓天数",
    yaxis_title="盈亏（R倍数）",
    height=400,
    margin=dict(l=60, r=30, t=55, b=50),
    legend=dict(orientation="h", x=0, y=1.08),
)
fig_hold.update_xaxes(range=[0, 400])
fig_hold.update_yaxes(range=[0, 20])
st.plotly_chart(fig_hold, width="stretch")

# Distribution of 3R+ winners by era
fig_hold_bar = go.Figure()
_eras_names = [r["阶段"] for r in _hold_rows]
_3r_counts  = [r["3R+笔数"] for r in _hold_rows]
_3r_pcts    = [float(r["3R+占比"].replace("%","")) for r in _hold_rows]
fig_hold_bar.add_trace(go.Bar(
    name="3R+交易笔数",
    x=_eras_names, y=_3r_counts,
    marker_color=["#1f77b4","#ff7f0e","#2ca02c"],
    text=_3r_counts, textposition="outside",
    yaxis="y",
))
fig_hold_bar.add_trace(go.Scatter(
    name="3R+占该阶段全部交易%",
    x=_eras_names, y=_3r_pcts,
    mode="markers+lines",
    marker=dict(size=12, color=["#1f77b4","#ff7f0e","#2ca02c"],
                line=dict(color="black", width=1.5)),
    line=dict(color="gray", dash="dash", width=1.5),
    yaxis="y2",
))
fig_hold_bar.update_layout(
    title="各阶段 3R+ 大赢家数量与占比",
    yaxis=dict(title="3R+ 笔数"),
    yaxis2=dict(title="3R+ 占比（%）", overlaying="y", side="right"),
    height=340,
    margin=dict(l=60, r=60, t=55, b=50),
    legend=dict(orientation="h", x=0, y=1.08),
)
st.plotly_chart(fig_hold_bar, width="stretch")

st.markdown(
    "**关键发现：**\n\n"
    "- 3R+ 大赢家平均持仓 **155–170 天**，是所有盈利单（~80天）的两倍以上——说明大赢家需要足够的时间让趋势充分发展。\n"
    "- 2016-2025 年的 3R+ 大赢家有所增加（128笔），但占比与前两个时代相当（约 8%）。\n"
    "- 问题不在于大赢家「变少」，而在于近期**低波动牛市中 SPY 的年化涨幅（20-30%）**远超策略能通过个股趋势跟踪匹配的速度。\n\n"
    "**实施建议：**\n\n"
    "- **第3/5级以上盈利单延迟调整移动止盈**：当盈利达到 3R 以上时，将移动止盈收紧速度放缓，"
    "给大赢家更多空间发展（如从 5×ATR 调整到 7×ATR）。\n"
    "- **识别「趋势延续」信号**：当持仓中已有 3R+ 盈利且成交量/动量仍然健康时，可适当扩仓（加仓金字塔），"
    "主动放大大赢家的收益贡献。\n"
    "- **避免在牛市初期信号出现时过早止盈**：设置最低持仓天数门槛（如 20 天）防止过快出场。"
)

st.markdown("---")

# ── Section 5 (new): 改进路径总结 ──────────────────────────────────────────
st.subheader("五、两条路径的综合对比与实施优先级")

_summary_rows = [
    {
        "改进路径": "① 熊市期加入反向ETF对冲",
        "实施难度": "中",
        "预期CAGR影响": f"+{_bl_cagr - _s_cagr:.1f} pp（模拟值）",
        "预期Sharpe影响": f"{_s_sh:.2f} → {_bl_sh:.2f}（模拟值）",
        "主要风险": "V形反转时反向ETF快速亏损，需设置止损",
        "数据支持": f"历史模拟：CAGR {_s_cagr:.1f}% → {_bl_cagr:.1f}%，Sharpe {_s_sh:.2f} → {_bl_sh:.2f}",
    },
    {
        "改进路径": "② 大赢家延迟收紧移动止盈",
        "实施难度": "中",
        "预期CAGR影响": "需重新回测量化",
        "预期Sharpe影响": "可能小幅改善",
        "主要风险": "3R+盈利可能回吐更多（回撤加大）",
        "数据支持": "3R+盈利单平均持仓155-170天，与持仓天数/R倍数正相关",
    },
]
show_df(pd.DataFrame(_summary_rows), width="stretch", hide_index=True)

st.markdown(
    "**实施优先建议：**\n\n"
    "1. **优先落地 ①（熊市反向对冲）**：模拟显示 CAGR 提升最大（+2.4pp），Sharpe 也显著改善。"
    " 需要独立的 ETF 配置和风控规则，建议先在模拟账户验证后再实盘。"
    " 该路径是将策略从「纯多头趋势跟踪」升级为「多空双向策略」的关键一步，也是 **策略2.0** 的重要组成方向。\n"
    "2. **结合信号选择 ②（大赢家管理）**：与「如何选中更优开仓信号」和加仓金字塔机制联合设计，"
    "避免单独调整移动止盈参数导致整体策略失衡。"
)

st.markdown("---")

st.info(
    "**相关页面**\n\n"
    "- 「如何选中更优开仓信号」：通过过滤低质量信号提升胜率，从源头减少低R多交易对Alpha的稀释。\n"
    "- 「加仓机制（金字塔）」：对已有 3R+ 盈利的持仓进行加仓，放大大赢家的收益贡献。\n"
    "- 「策略描述（策略2.0）」：策略2.0 规划了多空双向信号、行业轮动等更系统化的有效性改进方案。"
)
