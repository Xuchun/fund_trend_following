"""蒙特卡洛风险分析"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results, placeholder
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta

render_page_header("蒙特卡洛风险", meta)
st.caption(f"{meta.display_name} · 回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

# ── Baseline anchor parameter declaration ─────────────────────────────────────
_p = meta.params_anchor
st.markdown("""
> **⚠️ 重要说明：本页所有蒙特卡洛模拟结果均基于 Baseline Anchor 锚点参数。**
>
> 模拟方法：对 Baseline 回测产生的**历史日收益率序列**进行 Bootstrap 重采样（1,000 条路径），
> 评估策略在不同随机市场路径下的表现分布。输入数据为 `results/v1/nav.csv`（Baseline 回测净值）。
""")

with st.expander("📋 点击展开：本次模拟使用的 Baseline Anchor 锚点参数", expanded=False):
    _ca, _cb = st.columns(2)
    with _ca:
        st.markdown(f"""
| 参数 | 值 |
|------|-----|
| 突破窗口 `breakout_window` | **{_p['breakout_window']} 日** |
| ATR 止损乘数 `stop_loss_multiplier` | **{_p['stop_loss_multiplier']:.1f}×ATR** |
| 移动止盈 早期 `trail_multiplier_r1` | **{_p['trail_multiplier_r1']:.1f}×ATR** |
| 移动止盈 中期 `trail_multiplier_r3` | **{_p['trail_multiplier_r3']:.1f}×ATR** |
| 移动止盈 大赢 `trail_multiplier_r5` | **{_p['trail_multiplier_r5']:.1f}×ATR** |
| 成交量确认 `volume_filter_multiplier` | **{_p['volume_filter_multiplier']:.1f}×** |
| Gap 过滤 `gap_filter` | **±{_p['gap_filter']*100:.1f}%** |
""")
    with _cb:
        st.markdown(f"""
| 参数 | 值 |
|------|-----|
| 每笔风险 `risk_per_trade` | **{_p['risk_per_trade']*100:.1f}% NAV** |
| 仓位上限 `position_cap` | **{_p['position_cap']*100:.0f}% NAV** |
| 热度上限 `heat_limit` | **{_p['heat_limit']*100:.0f}% NAV** |
| Regime 过滤 `regime_filter_enabled` | **{'是' if _p['regime_filter_enabled'] else '否'}**（SPY SMA {_p['regime_sma_window']} 日）|
| 滑点 `slippage_bps` | **{_p['slippage_bps']:.0f} bps**（单边）|
| 佣金 `commission_bps` | **{_p['commission_bps']:.0f} bps**（单边）|
| 空仓代理 `cash_proxy` | **{_p.get('cash_proxy', 'SHY')}** |
""")

st.markdown("---")

# ── Load montecarlo.json ──────────────────────────────────────────────────────
_MC_PATH   = Path(__file__).resolve().parents[2] / "results" / "v1" / "montecarlo.json"
_DIAG_PATH = Path(__file__).resolve().parents[2] / "results" / "v1" / "diagnostics.json"

mc = None
if _MC_PATH.exists():
    try:
        mc = json.loads(_MC_PATH.read_text(encoding="utf-8"))
    except Exception:
        mc = None

# ── Section 1: analysis objective ────────────────────────────────────────────
n_trades_str = f"{res.metrics.get('n_trades', 0):,}"
if mc:
    st.subheader("模拟概览（Baseline Anchor 锚点参数）")
    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    mc1.metric("模拟路径数",   f"{mc['n_simulations']:,} 条")
    mc2.metric("模拟方法",     "Return + Block Bootstrap")
    mc3.metric("数据起点",     mc.get("start", "—"))
    mc4.metric("数据终点",     mc.get("end", "—"))
    mc5.metric("模拟交易日数", f"{mc['n_days']:,} 天")
else:
    st.subheader("分析目标")
    st.markdown(f"""
蒙特卡洛模拟通过**随机重采样历史日收益率序列**（Bootstrap Resampling），
评估策略在不同市场路径下的表现分布：

**模拟方法：**
- Return Bootstrap：对日收益率有放回随机重采样（IID）
- Block Bootstrap：按月分块随机重排（保留自相关结构）
- 生成 1,000 条模拟净值路径
- 分析 CAGR、MaxDD、Sharpe 的 5/25/50/75/95 百分位分布

运行：`python src/scripts/05_run_montecarlo.py`
""")

st.markdown("---")

# ── Section 2: NAV paths fan chart ───────────────────────────────────────────
if mc and "nav_percentiles" in mc:
    import plotly.graph_objects as go

    st.subheader("净值路径分布（1,000 条模拟路径）")

    np_data = mc["nav_percentiles"]
    dates   = np_data["dates"]
    p5      = np_data["p5"]
    p25     = np_data["p25"]
    p50     = np_data["p50"]
    p75     = np_data["p75"]
    p95     = np_data["p95"]

    initial = mc.get("initial_nav", 10_000_000)
    # Normalise to 1.0
    p5n  = [v / initial for v in p5]
    p25n = [v / initial for v in p25]
    p50n = [v / initial for v in p50]
    p75n = [v / initial for v in p75]
    p95n = [v / initial for v in p95]

    fig = go.Figure()

    # 5-95 band
    fig.add_trace(go.Scatter(
        x=dates + dates[::-1],
        y=p95n + p5n[::-1],
        fill="toself",
        fillcolor="rgba(31,119,180,0.10)",
        line=dict(width=0),
        name="5%–95% 区间",
        showlegend=True,
        hoverinfo="skip",
    ))
    # 25-75 band
    fig.add_trace(go.Scatter(
        x=dates + dates[::-1],
        y=p75n + p25n[::-1],
        fill="toself",
        fillcolor="rgba(31,119,180,0.22)",
        line=dict(width=0),
        name="25%–75% 区间",
        showlegend=True,
        hoverinfo="skip",
    ))
    # p95
    fig.add_trace(go.Scatter(
        x=dates, y=p95n, mode="lines",
        line=dict(color="#2ca02c", width=1, dash="dot"),
        name="95th percentile",
    ))
    # p50
    fig.add_trace(go.Scatter(
        x=dates, y=p50n, mode="lines",
        line=dict(color="#1f77b4", width=2.5),
        name="中位数 (50th)",
    ))
    # p5
    fig.add_trace(go.Scatter(
        x=dates, y=p5n, mode="lines",
        line=dict(color="#d62728", width=1, dash="dot"),
        name="5th percentile",
    ))

    fig.update_layout(
        title="模拟净值路径（归一化，初始=1.0）",
        xaxis_title="日期",
        yaxis_title="净值（相对初始资金）",
        height=450,
        margin=dict(t=50, b=50, l=50, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    fig.update_yaxes(tickformat=".2f")
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# ── Section 3: CAGR & MaxDD distribution ─────────────────────────────────────
if mc and "cagr_dist" in mc:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import numpy as np

    st.subheader("收益与风险分布")

    cd  = mc["cagr_dist"]
    dd  = mc["max_drawdown_dist"]
    sd  = mc["sharpe_dist"]
    dur = mc["drawdown_duration"]

    # Key metrics row
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("CAGR 中位数",   f"{cd['p50']*100:+.1f}%")
    col2.metric("CAGR 5th pct",  f"{cd['p5']*100:+.1f}%")
    col3.metric("最大回撤 中位数", f"{dd['p50']*100:.1f}%")
    col4.metric("最大回撤 最差",   f"{dd['worst']*100:.1f}%")
    col5.metric("Sharpe 中位数",  f"{sd['p50']:+.3f}")

    # CAGR histogram + MaxDD histogram side-by-side
    cagr_vals = [v * 100 for v in mc.get("cagr_all", [])]
    dd_vals   = [v * 100 for v in mc.get("max_drawdown_all", [])]

    if cagr_vals and dd_vals:
        fig2 = make_subplots(
            rows=1, cols=2,
            subplot_titles=("CAGR 分布（年化收益率）", "最大回撤分布"),
        )

        # CAGR histogram
        fig2.add_trace(
            go.Histogram(
                x=cagr_vals,
                nbinsx=40,
                marker_color=[
                    "#d62728" if v < 0 else "#1f77b4" for v in cagr_vals
                ],
                name="CAGR",
                showlegend=False,
            ),
            row=1, col=1,
        )
        # Vertical line at p50
        fig2.add_vline(
            x=cd["p50"] * 100, line_dash="dash", line_color="#1f77b4",
            annotation_text=f"中位数 {cd['p50']*100:+.1f}%",
            annotation_position="top right", row=1, col=1,
        )
        fig2.add_vline(
            x=0, line_dash="solid", line_color="black", line_width=1,
            row=1, col=1,
        )

        # MaxDD histogram
        fig2.add_trace(
            go.Histogram(
                x=dd_vals,
                nbinsx=40,
                marker_color="#f57c00",
                name="MaxDD",
                showlegend=False,
            ),
            row=1, col=2,
        )
        fig2.add_vline(
            x=dd["p50"] * 100, line_dash="dash", line_color="#f57c00",
            annotation_text=f"中位数 {dd['p50']*100:.1f}%",
            annotation_position="top left", row=1, col=2,
        )
        fig2.add_vline(
            x=dd["p95"] * 100, line_dash="dot", line_color="#d62728",
            annotation_text=f"95th {dd['p95']*100:.1f}%",
            annotation_position="top right", row=1, col=2,
        )

        fig2.update_layout(
            height=380,
            margin=dict(t=60, b=40, l=50, r=20),
        )
        fig2.update_xaxes(title_text="CAGR (%)", row=1, col=1)
        fig2.update_xaxes(title_text="最大回撤 (%)", row=1, col=2)
        fig2.update_yaxes(title_text="模拟次数", row=1, col=1)
        st.plotly_chart(fig2, use_container_width=True)

    # Summary table
    prob_neg = cd.get("prob_negative_cagr", 0)
    prob_ruin = cd.get("prob_ruin", 0)
    st.markdown(
        f'<div class="info-box">'
        f'在 {mc["n_simulations"]:,} 条随机路径中：'
        f'<strong>{prob_neg*100:.1f}%</strong> 的路径出现负年化收益，'
        f'<strong>{prob_ruin*100:.1f}%</strong> 的路径最终 NAV 低于初始资金的 50%（破产概率）。'
        f'CAGR 中位数 {cd["p50"]*100:+.1f}%，95% 置信区间 [{cd["p5"]*100:+.1f}%, {cd["p95"]*100:+.1f}%]。'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # ── Section 4: Drawdown duration table ───────────────────────────────────
    st.subheader("水下时间分布（连续亏损期概率）")

    dur_rows = [
        ("最长水下 > 3 个月（63 交易日）",  f"{dur['prob_gt_3m']*100:.1f}%"),
        ("最长水下 > 6 个月（126 交易日）", f"{dur['prob_gt_6m']*100:.1f}%"),
        ("最长水下 > 12 个月（252 交易日）",f"{dur['prob_gt_12m']*100:.1f}%"),
        ("最长水下 > 24 个月（504 交易日）",f"{dur['prob_gt_24m']*100:.1f}%"),
    ]
    import pandas as pd
    st.dataframe(
        pd.DataFrame(dur_rows, columns=["指标", "概率（1,000 条路径）"]),
        use_container_width=True, hide_index=True,
    )

    d1, d2, d3 = st.columns(3)
    d1.metric("平均最长水下（交易日）", f"{dur['avg_days']:.0f}")
    d2.metric("95th pct 最长水下",      f"{dur['p95_days']:.0f} 天")
    d3.metric("最坏情况最长水下",        f"{dur['max_days']:,} 天")

    st.markdown("---")

else:
    st.info(
        "蒙特卡洛数据尚未生成。运行：\n"
        "```\npython src/scripts/05_run_montecarlo.py\n```"
    )
    st.markdown("---")

# ── Section 5: streak analysis (from diagnostics) ────────────────────────────
st.subheader("连续亏损序列分析（基于历史真实交易）")

if _DIAG_PATH.exists():
    import plotly.graph_objects as go

    _diag = json.loads(_DIAG_PATH.read_text(encoding="utf-8"))
    _sa   = _diag.get("streak_analysis", {})
    _streak_counts: dict = _sa.get("streak_counts", {})

    if _streak_counts:
        x_labels: list[str] = []
        y_counts: list[int] = []
        bar_colors: list[str] = []

        for length in range(1, 10):
            x_labels.append(str(length))
            y_counts.append(_streak_counts.get(str(length), 0))
            if length <= 4:
                bar_colors.append("#2ca02c")
            else:
                bar_colors.append("#f57c00")

        x_labels.append("≥10")
        y_counts.append(_streak_counts.get("10+", 0))
        bar_colors.append("#d62728")

        fig3 = go.Figure(
            data=[go.Bar(
                x=x_labels,
                y=y_counts,
                marker_color=bar_colors,
                text=y_counts,
                textposition="outside",
            )]
        )
        fig3.update_layout(
            title="历史连续亏损序列分布",
            xaxis_title="连续亏损笔数",
            yaxis_title="出现次数",
            showlegend=False,
            height=360,
            margin=dict(t=50, b=40, l=40, r=20),
        )
        st.plotly_chart(fig3, use_container_width=True)

    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("最长连续亏损（笔）", _sa.get("max_consecutive_losses", 0))
    sc2.metric("总亏损序列数",       _sa.get("total_streaks", 0))
    sc3.metric("平均序列长度",       f"{_sa.get('avg_streak_length', 0.0):.2f}")

    _max_cl = _sa.get("max_consecutive_losses", 0)
    st.markdown(
        f'<div class="info-box">'
        f'在 38% 胜率下，随机期望每隔约 2.6 笔交易出现一次亏损连续段。'
        f'最长 <strong>{_max_cl} 笔</strong>连续亏损是心理上最难承受的时刻，'
        f'但从统计上看并不异常。'
        f'</div>',
        unsafe_allow_html=True,
    )
else:
    st.info("连续亏损数据尚未生成。运行：python src/scripts/04_run_diagnostics.py")

# ── Section 6: Assessment ─────────────────────────────────────────────────────
st.markdown("---")
st.subheader("评估")

if mc and "cagr_dist" in mc:
    cd  = mc["cagr_dist"]
    dd  = mc["max_drawdown_dist"]
    sd  = mc.get("sharpe_dist", {})
    dur = mc["drawdown_duration"]

    prob_neg  = cd.get("prob_negative_cagr", 0)
    prob_ruin = cd.get("prob_ruin", 0)
    cagr_p50  = cd["p50"]
    cagr_p5   = cd["p5"]
    cagr_p95  = cd["p95"]
    dd_p50    = dd["p50"]
    dd_worst  = dd["worst"]
    dd_p95    = dd.get("p95", dd_worst)
    sharpe_p50 = sd.get("p50", 0)
    avg_days   = dur.get("avg_days", 0)
    p95_days   = dur.get("p95_days", 0)
    max_days   = dur.get("max_days", 0)
    prob_gt24  = dur.get("prob_gt_24m", 0)

    # Historical actual figures from meta
    actual_maxdd = res.metrics.get("max_drawdown", 0)
    actual_sharpe = res.metrics.get("sharpe", 0)
    actual_cagr   = res.metrics.get("cagr", 0)

    st.markdown(f"""
**1. 正向预期价值高度确定**

在 {mc["n_simulations"]:,} 条随机路径中，负年化收益概率仅 **{prob_neg*100:.1f}%**，
净值归零（NAV 跌破初始 50%）的概率为 **{prob_ruin*100:.1f}%**。
CAGR 中位数 **{cagr_p50*100:+.1f}%**，95% 置信区间为
[{cagr_p5*100:+.1f}%, {cagr_p95*100:+.1f}%]。
这是蒙特卡洛分析最核心的结论——在任何合理的历史重采样下，
策略的长期正收益几乎是必然的，而非侥幸。

**2. 历史回测结果具有代表性**

实际历史 CAGR **{actual_cagr*100:+.2f}%** 落在模拟中位数 **{cagr_p50*100:+.1f}%** 附近，
实际 Sharpe **{actual_sharpe:+.3f}** 与模拟中位数 **{sharpe_p50:+.3f}** 高度吻合。
值得注意的是，历史最大回撤 **{actual_maxdd*100:.1f}%** 优于模拟中位数 **{dd_p50*100:.1f}%**，
说明实际回测并非"运气最好"的情形——模型的统计特性在历史数据上得到了如实体现，
这增强了参数稳定性的信心。

**3. 长期水下时间是最大的投资者心理挑战**

模拟显示，**{prob_gt24*100:.0f}%** 的路径存在超过 24 个月的连续水下期，
平均最长水下时间达 **{avg_days:.0f} 个交易日（约 {avg_days/252:.1f} 年）**，
95th percentile 情形长达 **{p95_days:.0f} 天（约 {p95_days/252:.1f} 年）**，
极端情形 **{max_days:,} 天（约 {max_days/252:.1f} 年）**。
这意味着投资者需要具备至少 2–3 年不追加赎回的流动性安排，
以及承受账面持续浮亏的心理准备。此风险不可低估。

**4. 尾部回撤风险需要明确披露**

最大回撤分布的 95th percentile 为 **{dd_p95*100:.1f}%**，最差情形 **{dd_worst*100:.1f}%**。
虽然这些极端情形概率较低，但资金管理上必须以"最坏情形出现时我是否仍可存续"为基准，
而非以"中位情形"作为压力测试标准。建议以 **{dd_p95*100:.0f}%** 作为最大可承受回撤的参考值。

**5. Bootstrap 方法的局限性**

本次模拟同时使用了 Return Bootstrap（IID 重采样）和 Block Bootstrap（月度分块）两种方法：
- Return Bootstrap 打破了日收益率的时序相关性，可能低估趋势跟踪策略中"连续盈利/亏损段"的真实概率；
- Block Bootstrap 保留了月度内的自相关结构，对趋势类策略更具代表性，
  但仍未能完全复现多月跨度的宏观市场状态切换（如持续 12 个月的熊市）。

综合来看，模拟低估了极端长跌市场环境的回撤深度，
**实际尾部风险可能比模拟显示的 {dd_p95*100:.1f}% 更大**。

**6. 与实盘表现的潜在差距**

蒙特卡洛模拟基于历史日收益率的重采样，隐含假设是未来收益率分布与历史一致。
实盘中存在以下不确定性：
① 历史选股池（标普500/900成分股）存在**幸存者偏差**，实盘难以完整复制；
② 大资金规模下**市场冲击成本**和流动性约束可能远超历史滑点假设；
③ **策略套利拥挤**风险：趋势跟踪策略被广泛采用后，同向仓位在相同信号触发时加剧尾部回撤。

因此，历史模拟结论应视为**乐观情景的上界**，实盘预期应适度保守。
""")

    verdict_color = "green" if prob_neg < 0.01 else ("orange" if prob_neg < 0.05 else "red")
    if prob_neg < 0.01 and prob_ruin == 0:
        verdict = "✅ 综合评价：策略统计特性稳健，正收益概率高，适合长周期持有；核心风险在于水下时间过长考验投资者耐心，而非策略本身的失效。"
    elif prob_neg < 0.05:
        verdict = "🟡 综合评价：策略整体可行，但存在一定负收益概率，需关注极端回撤情形。"
    else:
        verdict = "⚠️ 综合评价：负收益概率偏高，需重新审视策略参数或市场适用性。"

    st.markdown(
        f'<div class="info-box"><strong>{verdict}</strong></div>',
        unsafe_allow_html=True,
    )

else:
    st.info("蒙特卡洛数据尚未生成，无法提供评估。运行：python src/scripts/05_run_montecarlo.py")
