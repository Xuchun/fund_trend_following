"""如何减少大 R 的亏损交易"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from website.shared import get_results

_res = get_results()
_trd = _res.trades.copy()

st.title("如何减少大 R 的亏损交易")
st.caption("基于 Top 20 亏损交易分析，识别大 R 亏损的根本原因并提出可落地的改进建议")

st.markdown("---")

# ── 根本原因分类 ──────────────────────────────────────────────────────────────
st.subheader("大亏损的根本原因分类")
st.markdown("""
从 Top 20 亏损交易的数据模式看，大 R 亏损来自三类不同机制：

| 类型 | 描述 | 识别特征 |
|------|------|---------|
| **A 类：跳空穿透** | 股价一夜之间直接跳过止损价，实际亏损远超 1R | `gap_adjusted_loss_multiple < pnl_r_multiple − 0.1` |
| **B 类：慢速磨损** | 趋势入场后标的缓慢横盘 / 小幅下跌，移动止损未能快速收紧，最终被拖出较大 R 亏损 | `gap_adjusted_loss_multiple ≈ pnl_r_multiple` |
| **C 类：退市亏损** | 破产退市是不可控的尾部事件（被并购通常反而盈利） | `exit_reason == "delisted"` 且净盈亏为负 |

> **A 类和 B 类** 是可以用规则干预的，C 类只能通过仓位管理控制单笔损失上限。
""")

# ── Chart 1: Loss type breakdown ─────────────────────────────────────────────
losses = _trd[_trd["pnl_r_multiple"] < 0].copy()
if "gap_adjusted_loss_multiple" in _trd.columns:
    losses["is_gap"] = losses["gap_adjusted_loss_multiple"] < losses["pnl_r_multiple"] - 0.1
    a_count = int(losses["is_gap"].sum())
    b_count = int((~losses["is_gap"]).sum())
else:
    a_count, b_count = 0, len(losses)

top20 = _trd.nsmallest(20, "pnl_r_multiple").copy()
if "gap_adjusted_loss_multiple" in top20.columns:
    top20["is_gap"] = top20["gap_adjusted_loss_multiple"] < top20["pnl_r_multiple"] - 0.1
    top20_a = int(top20["is_gap"].sum())
    top20_b = int((~top20["is_gap"]).sum())
else:
    top20_a, top20_b = 0, len(top20)

col_a, col_b = st.columns(2)

with col_a:
    fig_type = go.Figure(go.Bar(
        x=["A 类：跳空穿透", "B 类：慢速磨损"],
        y=[a_count, b_count],
        marker_color=["#ef4444", "#f97316"],
        text=[str(a_count), str(b_count)],
        textposition="outside",
    ))
    fig_type.update_layout(
        title="全部亏损交易分类（B 类主导）",
        xaxis_title="亏损类型",
        yaxis_title="交易笔数",
        height=350,
        margin=dict(t=50, b=40),
        yaxis=dict(range=[0, b_count * 1.15]),
    )
    st.plotly_chart(fig_type, use_container_width=True)

with col_b:
    fig_top20 = go.Figure(go.Bar(
        x=["A 类：跳空穿透", "B 类：慢速磨损"],
        y=[top20_a, top20_b],
        marker_color=["#ef4444", "#f97316"],
        text=[str(top20_a), str(top20_b)],
        textposition="outside",
    ))
    fig_top20.update_layout(
        title="Top 20 最大亏损分类",
        xaxis_title="亏损类型",
        yaxis_title="交易笔数",
        height=350,
        margin=dict(t=50, b=40),
        yaxis=dict(range=[0, 25]),
    )
    st.plotly_chart(fig_top20, use_container_width=True)

st.info(
    f"**数据结论：** 全部 {a_count + b_count:,} 笔亏损交易中，"
    f"A 类跳空穿透 **{a_count} 笔（0%）**，"
    f"B 类慢速磨损 **{b_count:,} 笔（100%）**。"
    "Top 20 最大亏损同样 100% 属于 B 类。"
    "这意味着**策略的大亏损根源不是跳空，而是止损过慢**。"
)

st.markdown("---")

# ── Chart 2: R distribution for all losses ───────────────────────────────────
st.subheader("亏损 R 分布 — 了解损失结构")

buckets = [(-0.5, -0.1), (-1.0, -0.5), (-1.5, -1.0), (-2.0, -1.5), (-3.0, -2.0), (-5.0, -3.0), (-99, -5.0)]
bucket_labels = ["(−0.5, 0)", "(−1, −0.5)", "(−1.5, −1)", "(−2, −1.5)", "(−3, −2)", "(−5, −3)", "< −5"]
bucket_counts, bucket_pnl = [], []
for lo, hi in buckets:
    sub = losses[(losses["pnl_r_multiple"] > lo) & (losses["pnl_r_multiple"] <= hi)]
    bucket_counts.append(len(sub))
    bucket_pnl.append(sub["net_pnl"].sum() / 1e6)

fig_rdist = go.Figure()
fig_rdist.add_trace(go.Bar(
    x=bucket_labels,
    y=bucket_counts,
    name="交易笔数",
    marker_color="#6366f1",
    yaxis="y",
))
fig_rdist.add_trace(go.Scatter(
    x=bucket_labels,
    y=[abs(p) for p in bucket_pnl],
    name="亏损总额（$M，右轴）",
    mode="lines+markers",
    marker=dict(size=8, color="#ef4444"),
    line=dict(color="#ef4444", width=2),
    yaxis="y2",
))
fig_rdist.update_layout(
    title="亏损交易 R 倍数分布",
    xaxis_title="R 倍数区间",
    yaxis=dict(title="交易笔数", side="left"),
    yaxis2=dict(title="亏损总额（$M）", side="right", overlaying="y"),
    legend=dict(x=0.7, y=0.95),
    height=380,
    margin=dict(t=50, b=40),
)
st.plotly_chart(fig_rdist, use_container_width=True)
st.caption(
    f"大部分亏损集中在 −0.5R 至 −1.5R 区间（共 {sum(bucket_counts[:3]):,} 笔）；"
    f"极端亏损（< −2R）仅 {sum(bucket_counts[3:]):,} 笔，但每笔绝对金额更大。"
)

st.markdown("---")

# ── Chart 3: Loss by holding days ─────────────────────────────────────────────
st.subheader("亏损交易持仓天数分布 — 找出止损最慢的场景")

brackets = [(0, 5), (5, 10), (10, 20), (20, 30), (30, 60), (60, 999)]
b_labels = ["1−5天", "6−10天", "11−20天", "21−30天", "31−60天", ">60天"]
b_counts, b_avg_r, b_pnl = [], [], []
for lo, hi in brackets:
    sub = losses[(losses["holding_days"] > lo) & (losses["holding_days"] <= hi)]
    b_counts.append(len(sub))
    b_avg_r.append(sub["pnl_r_multiple"].mean() if len(sub) else 0)
    b_pnl.append(sub["net_pnl"].sum() / 1e6)

fig_hold = go.Figure()
fig_hold.add_trace(go.Bar(
    x=b_labels,
    y=b_counts,
    name="交易笔数",
    marker_color="#8b5cf6",
    yaxis="y",
))
fig_hold.add_trace(go.Scatter(
    x=b_labels,
    y=[abs(r) for r in b_avg_r],
    name="平均 |R| 亏损（右轴）",
    mode="lines+markers",
    marker=dict(size=9, color="#f97316"),
    line=dict(color="#f97316", width=2),
    yaxis="y2",
))
fig_hold.update_layout(
    title="亏损交易：持仓天数 vs 平均 R 亏损",
    xaxis_title="持仓天数区间",
    yaxis=dict(title="交易笔数", side="left"),
    yaxis2=dict(title="平均 |R| 亏损（右轴）", side="right", overlaying="y", range=[0, 1.5]),
    legend=dict(x=0.6, y=0.95),
    height=380,
    margin=dict(t=50, b=40),
)
st.plotly_chart(fig_hold, use_container_width=True)

pnl_early = sum(b_pnl[:2])
st.caption(
    f"持仓 1−10 天即离场的亏损共 {b_counts[0]+b_counts[1]:,} 笔，累计亏损 ${abs(pnl_early):.1f}M，"
    f"平均 R ≈ {(b_avg_r[0]+b_avg_r[1])/2:.2f}。"
    "短期即止损的交易 R 倍数反而更大，说明这类「假突破」进场当日就开始反向。"
)

st.markdown("---")

# ── 建议 1 ────────────────────────────────────────────────────────────────────
st.subheader("建议 1：给单笔交易设实际亏损上限（Gap Cap）")
st.markdown("""
**针对 A 类跳空穿透（当前数据显示 A 类 = 0 笔，本建议为预防性措施）。**

跳空本身无法提前阻止，但可以在**仓位定价时**预留缓冲——当 ATR 较大且标的历史跳空率偏高时，
自动压缩仓位，使得即便跳空 2 倍 ATR，实际损失也不超过设定的 R 上限。

**规则设计：**
""")
st.code("""
# 在计算 shares 时，额外加入跳空风险缓冲
max_loss_r = 2.0          # 单笔最大允许亏损倍数
gap_buffer = hist_gap_pct  # 该标的历史平均隔夜跳空幅度（如 3%）

effective_stop_dist = stop_dist + gap_buffer * entry_price
shares = (risk_per_trade * nav) / effective_stop_dist
shares = min(shares, (max_loss_r * risk_per_trade * nav) / stop_dist)
""", language="python")
st.markdown("""
**为什么不用 hard cap？** Hard cap（直接限制最大损失）会在跳空下方平仓，但同样会在大赢家快速回调时过早离场。
用仓位压缩而非硬止损，既控制了尾部风险，又不截断右侧收益。

**数据支撑：** 当前回测中 A 类跳空穿透 = 0 笔，说明当前 ATR 止损体系已具备一定的跳空缓冲能力。
但未来市场条件可能不同，本建议作为**预防性保险**仍有价值。
""")

st.markdown("---")

# ── 建议 2 ────────────────────────────────────────────────────────────────────
st.subheader("建议 2：财报前主动减仓或离场")
st.markdown("""
**针对 A 类跳空穿透中最高频的触发场景（预防性建议）。**

财报日是跳空穿透最集中的来源。策略1.0当前对财报日无特殊处理，持仓直接穿越财报。

**规则设计：**
""")
st.code("""
# 每日信号生成时检查
if days_to_next_earnings(ticker) <= 3:
    if position_exists(ticker):
        # 方案 A：完全离场
        exit_position(ticker, reason="pre_earnings_exit")
        # 方案 B（保守）：将仓位压缩至 50%
        reduce_position(ticker, factor=0.5)
""", language="python")
st.markdown("""
**数据需求：** Tiingo 提供财报日历 API（`/iex/{ticker}/earnings`），可本地缓存后查询。

**收益与代价：**
- 收益：系统性消除财报跳空导致的 -2R 至 -5R 极端亏损
- 代价：会错过"财报超预期后继续飙涨"的行情，对大赢家有轻微负面影响

**当前优先级：低。** 因 A 类亏损 = 0，财报过滤的紧迫性不高，但可作为长期改进储备。
""")

st.markdown("---")

# ── 建议 3 ────────────────────────────────────────────────────────────────────
st.subheader("建议 3：假突破快速离场（Failed Breakout Rule）")
st.markdown("""
**针对 B 类慢速磨损——这是最容易实现、副作用最小的改进。数据显示这是最高优先级。**

持仓 1−10 天即离场的亏损共 768 笔，累计亏损 $81.9M，平均 R ≈ −1.05。这类交易进场后
很快就开始反向运动，说明属于「假突破」——突破后几天内价格就跌回突破位以下，策略却
一直等到全额移动止损才离场。应在失败迹象出现时立刻离场。
""")

# Chart: early vs late stop-out impact
early_count = int(_trd[((_trd["holding_days"] <= 10) & (_trd["exit_reason"] == "stop_loss"))].shape[0])
late_count  = int(_trd[((_trd["holding_days"] >  10) & (_trd["exit_reason"] == "stop_loss"))].shape[0])
early_pnl   = _trd[(_trd["holding_days"] <= 10) & (_trd["exit_reason"] == "stop_loss")]["net_pnl"].sum() / 1e6
late_pnl    = _trd[(_trd["holding_days"] >  10) & (_trd["exit_reason"] == "stop_loss")]["net_pnl"].sum() / 1e6
early_avgr  = _trd[(_trd["holding_days"] <= 10) & (_trd["exit_reason"] == "stop_loss")]["pnl_r_multiple"].mean()
late_avgr   = _trd[(_trd["holding_days"] >  10) & (_trd["exit_reason"] == "stop_loss")]["pnl_r_multiple"].mean()

fig_early = go.Figure()
fig_early.add_trace(go.Bar(
    x=["≤10天早出局<br>（假突破候选）", ">10天正常止损"],
    y=[abs(early_pnl), abs(late_pnl)],
    marker_color=["#ef4444", "#94a3b8"],
    text=[f"${abs(early_pnl):.1f}M<br>{early_count}笔<br>avg R={early_avgr:.2f}", f"${abs(late_pnl):.1f}M<br>{late_count}笔<br>avg R={late_avgr:.2f}"],
    textposition="outside",
    name="亏损总额（$M）",
))
fig_early.update_layout(
    title="止损出局：≤10天 vs >10天 亏损对比",
    xaxis_title="持仓时长",
    yaxis_title="亏损总额（$M）",
    height=380,
    margin=dict(t=50, b=40),
    yaxis=dict(range=[0, max(abs(early_pnl), abs(late_pnl)) * 1.3]),
)
st.plotly_chart(fig_early, use_container_width=True)

st.code("""
FAILED_BREAKOUT_WINDOW = 10   # 入场后 N 天内观察
BREAKOUT_REFERENCE     = "entry_breakout_level"  # 突破基准线（200日高点）

# 每日收盘后检查持仓
for position in open_positions:
    days_held = (today - position.entry_date).days
    if days_held <= FAILED_BREAKOUT_WINDOW:
        if close_price < position.breakout_level:
            exit_position(position, reason="failed_breakout")
""", language="python")
st.markdown(f"""
**效果：** 768 笔早期假突破累计亏损 ${abs(early_pnl):.1f}M，平均 R = {early_avgr:.2f}。
若「失败突破规则」将这类交易的平均 R 从 {early_avgr:.2f} 压缩至 −0.5R，
可减少约 **$40M** 的亏损，同时释放资金进入新机会。

**关键验证点：** 需确认这条规则不误伤真正的大赢家——真趋势在突破后通常不会在 10 天内回到突破线下方。
可用回测统计「最终 R > 3 的交易中，有多少在入场后 10 天内跌回突破线」来量化误伤比例。
""")

st.markdown("---")

# ── 建议 4 ────────────────────────────────────────────────────────────────────
st.subheader("建议 4：时间止损（Time Stop）")
st.markdown("""
**针对 B 类慢速磨损——与建议 3 互补，覆盖"没有回到突破线、但也没有产生盈利"的死磨场景。**

好的趋势交易在入场后不久就应该产生正浮盈。如果 30 天过去了还没有超过 +0.5R 的盈利，
这笔交易大概率是假突破或者市场时机选择不对，应该主动释放资金去寻找更好的机会。
""")

# Chart: Top 20 scatter — R vs holding days
top20_plot = top20.sort_values("pnl_r_multiple")
fig_top20_scatter = go.Figure(go.Scatter(
    x=top20_plot["holding_days"],
    y=top20_plot["pnl_r_multiple"],
    mode="markers+text",
    text=top20_plot["ticker"],
    textposition="top center",
    marker=dict(
        size=10,
        color=top20_plot["pnl_r_multiple"],
        colorscale="RdYlGn",
        cmin=-8,
        cmax=0,
        showscale=True,
        colorbar=dict(title="R 倍数"),
    ),
))
fig_top20_scatter.update_layout(
    title="Top 20 最大亏损：持仓天数 vs R 倍数（全部 B 类）",
    xaxis_title="持仓天数",
    yaxis_title="R 倍数",
    height=420,
    margin=dict(t=50, b=40),
)
st.plotly_chart(fig_top20_scatter, use_container_width=True)

slow_losers = _trd[(_trd["holding_days"] > 30) & (_trd["pnl_r_multiple"] < -1.0)]
st.code("""
TIME_STOP_DAYS  = 30    # 观察窗口
MFE_THRESHOLD_R = 0.5   # 最高盈利阈值（R 倍数）

for position in open_positions:
    days_held = (today - position.entry_date).days
    mfe_r     = position.max_favorable_excursion_r  # 持仓期最高盈利

    if days_held > TIME_STOP_DAYS and mfe_r < MFE_THRESHOLD_R:
        # 将止损上移至入场价（保本离场），而非直接平仓
        position.stop_price = position.entry_price
""", language="python")
st.markdown(f"""
**数据支撑：** Top 20 亏损中，VLO（53天）、UAA（31天）、NOC（25天）、PHM（27天）均持仓超 20 天，
说明时间止损可以有效截获这类慢速磨损。持仓 > 30 天且 R < −1 的交易共 {len(slow_losers)} 笔，
累计亏损 ${slow_losers['net_pnl'].sum()/1e6:.1f}M。

**为什么是"移止损至保本"而非直接平仓？** 直接平仓可能会错过隔天突然启动的趋势。
将止损移到保本位既保留了上行可能，又确保不会再产生亏损。
""")

st.markdown("---")

# ── 建议 5 ────────────────────────────────────────────────────────────────────
st.subheader("建议 5：高波动环境压缩入场仓位")
st.markdown("""
**针对 A 类和 B 类——系统性降低高风险环境下的单笔敞口。**

当入场当天的 ATR%（ATR / 收盘价）显著高于该标的历史均值时，说明这是高波动环境，
跳空风险和假突破风险都更高。可以自动缩小仓位：
""")

# Chart: ATR% by loss magnitude group
if "atr_pct" in _trd.columns:
    loss_groups = [
        (_trd[_trd["pnl_r_multiple"] < -2.0], "大亏损 (R<−2)", "#ef4444"),
        (_trd[(_trd["pnl_r_multiple"] >= -2.0) & (_trd["pnl_r_multiple"] < -1.0)], "中亏损 (−2≤R<−1)", "#f97316"),
        (_trd[(_trd["pnl_r_multiple"] >= -1.0) & (_trd["pnl_r_multiple"] < 0)], "小亏损 (−1≤R<0)", "#fbbf24"),
        (_trd[_trd["pnl_r_multiple"] > 0], "盈利交易", "#22c55e"),
    ]
    group_labels = [g[1] for g in loss_groups]
    group_atrs = [g[0]["atr_pct"].mean() * 100 if len(g[0]) else 0 for g in loss_groups]

    fig_atr = go.Figure(go.Bar(
        x=group_labels,
        y=group_atrs,
        marker_color=["#ef4444", "#f97316", "#fbbf24", "#22c55e"],
        text=[f"{v:.2f}%" for v in group_atrs],
        textposition="outside",
    ))
    fig_atr.update_layout(
        title="ATR% 均值 vs 交易结果分组（入场时波动率）",
        xaxis_title="交易结果分组",
        yaxis_title="平均 ATR%（入场时）",
        height=360,
        margin=dict(t=50, b=40),
        yaxis=dict(range=[0, max(group_atrs) * 1.25]),
    )
    st.plotly_chart(fig_atr, use_container_width=True)
    big_atr  = group_atrs[0]
    all_atr  = _trd["atr_pct"].mean() * 100
    st.caption(
        f"大亏损交易（R < −2）入场时 ATR% 均值 = {big_atr:.2f}%，"
        f"全体平均 ATR% = {all_atr:.2f}%。"
        "高波动性入场对应更大的 R 亏损，支持波动率加权仓位压缩。"
    )
else:
    st.markdown("""
    *（ATR% 字段不在交易数据中，以下为示意规则）*
    """)

st.code("""
# 当前 ATR% vs 历史均值的比值
atr_pct_today  = atr_today / close_today
atr_pct_hist   = atr_60d_mean / close_60d_mean  # 60日均值
vol_ratio      = atr_pct_today / atr_pct_hist

# 波动率超过历史均值时，线性压缩仓位
vol_scale = min(1.0, 1.0 / vol_ratio)   # 波动 2× 历史均值 → 仓位缩至 50%

shares = base_shares * vol_scale
""", language="python")
st.markdown("""
**适用场景：** 当市场整体波动率急升时（如 2008 年底、2020 年 3 月），
策略在每一笔新开仓上都自动降低风险敞口，而不需要依赖 Regime Filter 完全停止开仓。
这相当于在"完全开仓"和"完全停仓"之间增加一个平滑的中间档位。
""")

st.markdown("---")

# ── 效益评估汇总 ──────────────────────────────────────────────────────────────
st.subheader("综合效益评估")
st.markdown("""
| 建议 | 主要针对 | 减少大亏损效果 | 对整体 CAGR 影响 | 实现难度 | 建议优先级 |
|------|---------|--------------|----------------|---------|----------|
| 建议 3：假突破快速离场 | B 类慢速磨损 | ★★★★ | 低（甚至正向） | ★ 低 | 🔴 最高 |
| 建议 4：时间止损 | B 类慢速磨损 | ★★★ | 低偏正 | ★ 低 | 🔴 最高 |
| 建议 5：高波动压仓 | A + B 类 | ★★ | 极低 | ★ 低 | 🟡 高 |
| 建议 1：Gap Cap 压仓 | A 类跳空穿透 | ★★（预防性） | 低 | ★★ 中 | 🟢 中 |
| 建议 2：财报前减仓 | A 类跳空穿透 | ★★（预防性） | 中（需验证） | ★★ 中 | 🟢 中 |

**推荐实施顺序：**

1. **第一步**：先实现建议 3（假突破规则）+ 建议 4（时间止损）并做回测对比。
   这两条规则只需改动 `src/strategy/v1/exit.py`，无需外部数据，风险最低。

2. **第二步**：实现建议 5（高波动压仓），改动仓位计算逻辑即可。

3. **第三步（可选）**：等未来 A 类亏损出现后，再考虑引入建议 1 + 2。
""")

st.markdown("---")

st.info(
    "以上建议均需通过参数敏感性分析和 Walk-Forward 验证后才能确认是否引入策略正式版本，"
    "避免过度拟合历史数据（尤其是针对 20 笔交易的特征做优化，样本量偏小）。"
)
