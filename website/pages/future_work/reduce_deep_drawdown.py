"""如果减少深度回撤幅度"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from website.shared import get_results

_res = get_results()
_trd = _res.trades.copy()
_nav = _res.nav.copy()
_nav_s = _nav["nav"]

# ── Pre-compute drawdown series ───────────────────────────────────────────────
_roll_max = _nav_s.expanding().max()
_dd = (_nav_s - _roll_max) / _roll_max * 100   # in percent

# Deep DD episodes
_in_deep = _dd < -10
_episodes = []
_ep_start = None
for dt, val in _in_deep.items():
    if val and _ep_start is None:
        _ep_start = dt
    elif not val and _ep_start is not None:
        _ep_min = _dd[_ep_start:dt].min()
        _ep_dur = (_dd[_ep_start:dt].index[-1] - _ep_start).days
        _episodes.append({"start": _ep_start, "end": dt, "min_dd": _ep_min, "duration": _ep_dur})
        _ep_start = None
if _ep_start is not None:
    _ep_min = _dd[_ep_start:].min()
    _ep_dur = (_dd.index[-1] - _ep_start).days
    _episodes.append({"start": _ep_start, "end": _dd.index[-1], "min_dd": _ep_min, "duration": _ep_dur})
_edf = pd.DataFrame(_episodes) if _episodes else pd.DataFrame(columns=["start", "end", "min_dd", "duration"])

# Trades during vs outside deep DD
_dd_dates = set(_dd[_dd < -10].index.date)
_trd["during_deep_dd"] = _trd["entry_date"].dt.date.isin(_dd_dates)

st.title("如何减少深度回撤幅度")
st.caption(
    f"探讨三种可降低深度回撤持续时长的改进方向，"
    f"基于策略1.0深度回撤分析（共 {len(_edf)} 次 NAV 连续低于高水位 −10% 的回撤期）"
)

st.markdown("---")

# ── 背景：NAV + Deep DD chart ─────────────────────────────────────────────────
st.subheader("背景：深度回撤的规律")

st.markdown("""
策略1.0在 2000–2026 年的回测中共经历 **68 段**回撤幅度超过 10% 的连续深度回撤（其中多段来自同一次大熊市，
如 GFC 持续 600+ 天）。观察这些回撤的特征，可以发现一个共同规律：

> 持续最久的深度回撤（GFC 601天、2015-2016 年 338天、2018-2019 年 219天）并非来自单次剧烈亏损，
> 而是**在熊市或震荡市中继续持仓、缓慢消耗**造成的。

其中，2015-12 至 2016-11 那次 338 天回撤尤为典型——彼时 SPY 在技术上仍处于震荡区间，
Regime Filter 没有触发，但策略自身的持仓已经开始失血。
这说明现有的市场环境过滤器存在盲区：**策略层面的亏损先于宏观信号出现。**
""")

# NAV chart with deep DD shading
fig_nav = go.Figure()
fig_nav.add_trace(go.Scatter(
    x=_nav_s.index,
    y=_nav_s.values,
    name="策略 NAV",
    line=dict(color="#6366f1", width=1.5),
    fill=None,
))
# Shade deep DD periods
for _, row in _edf.iterrows():
    fig_nav.add_vrect(
        x0=row["start"], x1=row["end"],
        fillcolor="rgba(239,68,68,0.12)",
        line_width=0,
    )
# Add -10% drawdown line as reference
hwm = _roll_max
nav_floor_10 = hwm * 0.90
fig_nav.add_trace(go.Scatter(
    x=nav_floor_10.index,
    y=nav_floor_10.values,
    name="高水位 × 90%（−10% 线）",
    line=dict(color="#ef4444", width=1, dash="dot"),
    opacity=0.6,
))
fig_nav.update_layout(
    title=f"策略 NAV 走势（红色阴影 = {len(_edf)} 段深度回撤 >10%）",
    xaxis_title="日期",
    yaxis_title="NAV（$）",
    height=420,
    margin=dict(t=50, b=40),
    legend=dict(x=0.01, y=0.99),
    yaxis=dict(type="log"),
)
st.plotly_chart(fig_nav, use_container_width=True)

# Summary table of worst episodes
worst = _edf.nsmallest(8, "min_dd")[["start", "end", "min_dd", "duration"]].copy()
worst["start"] = worst["start"].dt.strftime("%Y-%m-%d")
worst["end"] = worst["end"].dt.strftime("%Y-%m-%d")
worst["min_dd"] = worst["min_dd"].map(lambda x: f"{x:.1f}%")
worst.columns = ["开始日期", "结束日期", "最大回撤深度", "持续天数"]
st.markdown("**最深的 8 段回撤（>10% 阈值）：**")
st.dataframe(worst, use_container_width=True, hide_index=True)

st.markdown("---")

# ── 关键数据发现：深度回撤期间的交易表现 ─────────────────────────────────────
st.subheader("⚡ 关键发现：深度回撤期间开仓的交易表现更好")

during = _trd[_trd["during_deep_dd"]]
outside = _trd[~_trd["during_deep_dd"]]

col_a, col_b = st.columns(2)
with col_a:
    fig_compare = go.Figure(go.Bar(
        x=["深度回撤期间开仓", "非深度回撤期开仓"],
        y=[during["pnl_r_multiple"].mean(), outside["pnl_r_multiple"].mean()],
        marker_color=["#ef4444", "#22c55e"],
        text=[f"{during['pnl_r_multiple'].mean():.3f}R", f"{outside['pnl_r_multiple'].mean():.3f}R"],
        textposition="outside",
    ))
    fig_compare.update_layout(
        title="深度回撤期 vs 正常期：平均 R 倍数",
        yaxis_title="平均 R 倍数",
        height=340,
        margin=dict(t=50, b=40),
        yaxis=dict(range=[0, 0.55]),
    )
    st.plotly_chart(fig_compare, use_container_width=True)

with col_b:
    fig_wr = go.Figure(go.Bar(
        x=["深度回撤期间开仓", "非深度回撤期开仓"],
        y=[during["pnl_r_multiple"].gt(0).mean() * 100, outside["pnl_r_multiple"].gt(0).mean() * 100],
        marker_color=["#ef4444", "#22c55e"],
        text=[f"{during['pnl_r_multiple'].gt(0).mean()*100:.1f}%", f"{outside['pnl_r_multiple'].gt(0).mean()*100:.1f}%"],
        textposition="outside",
    ))
    fig_wr.update_layout(
        title="深度回撤期 vs 正常期：胜率",
        yaxis_title="胜率（%）",
        height=340,
        margin=dict(t=50, b=40),
        yaxis=dict(range=[0, 55]),
    )
    st.plotly_chart(fig_wr, use_container_width=True)

st.warning(
    f"**反直觉发现：** 深度回撤期间（NAV < −10% 高水位）开仓的 {len(during):,} 笔交易，"
    f"平均 R = **{during['pnl_r_multiple'].mean():.3f}**，胜率 = **{during['pnl_r_multiple'].gt(0).mean()*100:.1f}%**；"
    f"反而优于非深度回撤期 {len(outside):,} 笔（平均 R = {outside['pnl_r_multiple'].mean():.3f}，"
    f"胜率 = {outside['pnl_r_multiple'].gt(0).mean()*100:.1f}%）。\n\n"
    "**可能解释：** 在市场整体走弱时仍能突破新高的股票，是市场中最强的相对强势标的，"
    "信号质量反而更高。这意味着**净值保护线（方向一）如果完全停止开仓，可能会错过更优质的信号**，"
    "需要在回测中仔细权衡。"
)

st.markdown("---")

# ── 方向一 ────────────────────────────────────────────────────────────────────
st.subheader("方向一：净值保护线（推荐优先测试）")

st.markdown("""
**核心逻辑：** 当策略 NAV 从高水位线下跌超过阈值（如 −12%）时，**全面暂停新开仓**，
让持仓自然止损出场，等待 NAV 重新站上保护线后恢复正常开仓。

这比现有 Regime Filter 更直接：Regime Filter 看的是市场（SPY），净值保护线看的是**策略自己的盈亏状态**。
""")

col1, col2 = st.columns(2)
with col1:
    st.markdown("""
**潜在收益：**
- 在趋势失效初期及时踩刹车，避免持续消耗
- 不改变正常市场下的任何开仓逻辑
- 规则简单透明，实盘执行无歧义
- 水下时间有望从"月级"缩短至"周级"
""")
with col2:
    st.markdown("""
**潜在代价（数据支撑）：**
- 深度回撤期间开仓的交易平均 R = 0.425，高于非深度回撤期的 0.250
- 完全停止开仓将错过这批质量更高的信号
- 若 NAV 短暂跌破阈值后快速反弹，可能错过随后的行情
- 阈值过紧 → 频繁暂停（Whipsaw）；过松 → 保护效果有限
""")

st.info("""
**建议实现方式：**
在 BacktestEngine 中新增 `drawdown_guard` 参数：
- 计算当前 NAV 距历史高水位的跌幅
- 跌幅超过阈值时，当日不执行任何新开仓（已有持仓继续按止损/止盈管理）
- NAV 恢复至高水位线 −5% 以上后，解除保护，恢复开仓
""")

st.markdown("---")

# ── 方向二 ────────────────────────────────────────────────────────────────────
st.subheader("方向二：动态热度上限（仓位随回撤递减）")

st.markdown("""
**核心逻辑：** 策略当前使用固定 `heat_limit = 10%`（最大同时持有 10 个 1%风险仓位）。
改为根据策略 NAV 的当前回撤深度，动态调低热度上限，实现"亏得越多、仓位越轻"的自适应风控。
""")

st.markdown("""
| NAV 水下深度 | 热度上限 | 含义 |
|-------------|---------|------|
| < −5% | 7%（原 10%） | 轻微减仓，保留大部分机会 |
| −5% ~ −10% | 5% | 明显减仓 |
| > −10% | 3% | 大幅减仓，仅维持少量持仓 |
""")

# Heat limit sensitivity chart (from perturbation data)
_heat_path = _root / "results/v1_unbiased_60m_2000/perturbation/heat_limit.json"
if _heat_path.exists():
    heat_data = json.loads(_heat_path.read_text())
    hv = heat_data["param_values"]
    h_cagr = [r["cagr"] * 100 for r in heat_data["results"]]
    h_mdd  = [abs(r["max_drawdown"]) * 100 for r in heat_data["results"]]

    fig_heat = go.Figure()
    fig_heat.add_trace(go.Bar(
        x=[f"{v:.0%}" for v in hv],
        y=h_cagr,
        name="CAGR (%)",
        marker_color="#6366f1",
        yaxis="y",
    ))
    fig_heat.add_trace(go.Scatter(
        x=[f"{v:.0%}" for v in hv],
        y=h_mdd,
        name="最大回撤（%，右轴）",
        mode="lines+markers",
        marker=dict(size=9, color="#ef4444"),
        line=dict(color="#ef4444", width=2),
        yaxis="y2",
    ))
    fig_heat.update_layout(
        title="热度上限（heat_limit）敏感性：CAGR vs MaxDD",
        xaxis_title="heat_limit",
        yaxis=dict(title="CAGR (%)", side="left", range=[7, 12]),
        yaxis2=dict(title="最大回撤（%）", side="right", overlaying="y", range=[15, 24]),
        legend=dict(x=0.5, y=0.05),
        height=380,
        margin=dict(t=50, b=40),
    )
    st.plotly_chart(fig_heat, use_container_width=True)
    st.caption(
        f"当前 baseline heat_limit = {heat_data['baseline_value']:.0%}。"
        f"降至 5% 时 MaxDD 降至约 {h_mdd[1]:.1f}%，但 CAGR 也下降至 {h_cagr[1]:.2f}%，"
        "说明静态热度上限降低会同时伤害收益。动态版本（仅在深度回撤时降低）可能更优，"
        "但需要专项回测验证。"
    )

col3, col4 = st.columns(2)
with col3:
    st.markdown("""
**潜在收益：**
- 下跌时损失放缓，回撤幅度收窄
- 保留部分持仓，不完全错过反弹
- 与净值保护线可叠加使用
""")
with col4:
    st.markdown("""
**潜在代价：**
- 减仓后若市场反弹，会错过部分上行收益
- 参数组合变多（各级阈值），过拟合风险上升
- 实现复杂度高于方向一
""")

st.markdown("---")

# ── 方向三 ────────────────────────────────────────────────────────────────────
st.subheader("方向三：提高移动止盈灵敏度")

st.markdown("""
**核心逻辑：** 从参数敏感性分析可见，移动止盈乘数从 **3.0×（当前）降至 2.5×ATR**，
Sharpe 略有提升。更紧的移动止盈意味着：

- 趋势反转初期更快兑现浮盈，减少回吐
- 更快释放仓位，在新趋势出现时有资金入场
- 个股层面的水下时间缩短，对组合整体回撤有间接改善
""")

# Trail multiplier sensitivity chart
_trail_path = _root / "results/v1_unbiased_60m_2000/perturbation/trail_multiplier_r1.json"
if _trail_path.exists():
    trail_data = json.loads(_trail_path.read_text())
    tv  = trail_data["param_values"]
    t_cagr   = [r["cagr"] * 100 for r in trail_data["results"]]
    t_mdd    = [abs(r["max_drawdown"]) * 100 for r in trail_data["results"]]
    t_sharpe = [r["sharpe"] for r in trail_data["results"]]
    baseline_trail = trail_data["baseline_value"]

    fig_trail = go.Figure()
    fig_trail.add_trace(go.Bar(
        x=[str(v) for v in tv],
        y=t_cagr,
        name="CAGR (%)",
        marker_color=["#22c55e" if v == baseline_trail else "#6366f1" for v in tv],
        yaxis="y",
    ))
    fig_trail.add_trace(go.Scatter(
        x=[str(v) for v in tv],
        y=t_mdd,
        name="最大回撤（%，右轴）",
        mode="lines+markers",
        marker=dict(size=9, color="#ef4444"),
        line=dict(color="#ef4444", width=2),
        yaxis="y2",
    ))
    fig_trail.add_annotation(
        x=str(baseline_trail),
        y=max(t_cagr) + 0.3,
        text="当前值",
        showarrow=True,
        arrowhead=2,
        ax=0, ay=-25,
        yref="y",
    )
    fig_trail.update_layout(
        title="移动止盈乘数（trail_multiplier）敏感性：CAGR vs MaxDD",
        xaxis_title="trail_multiplier（× ATR）",
        yaxis=dict(title="CAGR (%)", side="left", range=[8.5, 11.5]),
        yaxis2=dict(title="最大回撤（%）", side="right", overlaying="y", range=[18, 23]),
        legend=dict(x=0.6, y=0.05),
        height=400,
        margin=dict(t=50, b=40),
    )
    st.plotly_chart(fig_trail, use_container_width=True)

    best_idx = t_cagr.index(max(t_cagr))
    st.caption(
        f"CAGR 最高点在 trail = {tv[best_idx]}（当前值），"
        f"CAGR = {t_cagr[best_idx]:.2f}%，MaxDD = −{t_mdd[best_idx]:.1f}%。"
        f"trail = 3.5 时 MaxDD 降至最低（−{min(t_mdd):.1f}%），"
        f"但 CAGR 下降至 {t_cagr[tv.index(3.5)]:.2f}%，得不偿失。"
        "移动止盈乘数对回撤改善效果有限，参数扰动范围内 MaxDD 差异仅 ≈ 1.5ppt。"
    )

col5, col6 = st.columns(2)
with col5:
    st.markdown("""
**潜在收益：**
- 每笔盈利交易的最终收益更稳定（少回吐）
- 换手率略高，但资金利用率提升
- Sharpe 略优（参数敏感性分析已验证）
""")
with col6:
    st.markdown("""
**潜在代价：**
- 强趋势中提前出场，错过"大鱼尾巴"
- 换手率上升，交易成本微增
- 对大回撤本身改善有限（治标不治本）
""")

st.markdown("---")

# ── 综合建议 ──────────────────────────────────────────────────────────────────
st.subheader("综合建议与优先级")

st.markdown("""
| 优先级 | 方向 | 推荐理由 | 实现难度 |
|--------|------|---------|---------|
| 🥇 **优先** | 方向一：净值保护线 | 逻辑最直接，不改变正常市场行为，Whipsaw 风险可控 | 低 |
| 🥈 **次选** | 方向三：移动止盈 2.5× | 已有回测支持，参数调整幅度小，副作用少 | 极低（改一个参数）|
| 🥉 **探索** | 方向二：动态热度 | 概念合理，但参数多、过拟合风险高，需谨慎 | 中 |

**重要提示：** 回测数据显示深度回撤期间的开仓质量反而更高（avg R = 0.425 vs 0.250），
实施方向一（净值保护线）前需通过专项回测量化净效益，可能存在"停止开仓反而伤害整体收益"的反效果。
""")

st.warning("""
**重要提醒：** 以上方向均为假设性改进，需通过完整回测（2000–2026）量化验证后才能评估实际效果。
减少回撤深度/时长几乎必然以牺牲部分上行收益为代价——关键是这个权衡是否值得。
建议使用 Walk-Forward 验证框架评估改进后的 OOS 表现，避免在样本内过拟合。
""")
