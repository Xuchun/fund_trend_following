"""蒙特卡洛模拟"""

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

render_page_header("蒙特卡洛模拟", meta)
st.markdown(f"**回测期间：{meta.backtest_start} → {meta.backtest_end}**")

# ── Baseline anchor parameter declaration ─────────────────────────────────────
_p = meta.params_anchor
st.warning(
    "⚠️ **重要说明：本页所有蒙特卡洛模拟结果均基于 Baseline Anchor 锚点参数。**\n\n"
    "模拟方法：对 Baseline 回测产生的**历史日收益率序列**进行 **Block Bootstrap 重采样**（月度分块随机重排，1,000 条路径），"
    "保留趋势跟踪策略收益率序列的自相关结构，评估策略1.0在不同随机市场路径下的表现分布。"
    "输入数据为 `results/v1_unbiased_60m_2000/nav.csv`（Baseline 回测净值）。"
)

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

# ── Load montecarlo.json ──────────────────────────────────────────────────────
_MC_PATH   = Path(__file__).resolve().parents[2] / "results" / "v1_unbiased_60m_2000" / "montecarlo.json"
_DIAG_PATH = Path(__file__).resolve().parents[2] / "results" / "v1_unbiased_60m_2000" / "diagnostics.json"

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
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("模拟路径数",   f"{mc['n_simulations']:,} 条")
    mc2.metric("数据起点",     mc.get("start", "—"))
    mc3.metric("数据终点",     mc.get("end", "—"))
    mc4.metric("模拟交易日数", f"{mc['n_days']:,} 天")
    st.markdown("""
**模拟方法：Block Bootstrap（月度分块随机重排）**

将历史日收益率序列按月（≈21 交易日）分块，随机重排各月块后拼接成模拟路径。
与 IID 有放回重采样（Return Bootstrap）相比，Block Bootstrap 保留了月度内的收益率自相关结构，
对趋势跟踪策略更具代表性——趋势信号依赖收益率的序列延续性，IID 假设会破坏这一特性，低估连亏段和深度回撤的真实概率。
所有指标（CAGR、MaxDD、Sharpe、NAV 路径、水下时间）均使用同一组 1,000 条路径计算，方法统一。
""")
else:
    st.subheader("分析目标")
    st.markdown("""
蒙特卡洛模拟通过 **Block Bootstrap 重采样历史日收益率序列**（月度分块随机重排），
评估策略1.0在 1,000 条随机市场路径下的表现分布。

**为什么用 Block Bootstrap 而非 IID Return Bootstrap？**
趋势跟踪策略的日收益率天然不是 IID——牛熊市切换造成收益率聚集，信号依赖序列延续性。
IID 重采样打断了这个结构，会系统性低估连亏段和深度回撤的真实概率。
Block Bootstrap 按月分块保留了月度内的自相关，对趋势策略更具代表性。

**所有指标均使用同一组路径：** CAGR、MaxDD、Sharpe、NAV 扇形图、水下时间。

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

    # Actual historical NAV overlay
    import pandas as _pd_mc
    _nav_csv = Path(__file__).resolve().parents[2] / "results" / "v1_unbiased_60m_2000" / "nav.csv"
    if _nav_csv.exists():
        _nav_mc = _pd_mc.read_csv(_nav_csv, parse_dates=["date"]).set_index("date")["nav"]
        _nav_mc_norm = (_nav_mc / _nav_mc.iloc[0]).tolist()
        _nav_mc_dates = [d.strftime("%Y-%m-%d") for d in _nav_mc.index]
        fig.add_trace(go.Scatter(
            x=_nav_mc_dates, y=_nav_mc_norm, mode="lines",
            line=dict(color="black", width=2),
            name="实际历史路径",
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

else:
    st.info(
        "蒙特卡洛数据尚未生成。运行：\n"
        "```\npython src/scripts/05_run_montecarlo.py\n```"
    )

# ── Section 5: Assessment ─────────────────────────────────────────────────────
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
策略1.0的长期正收益几乎是必然的，而非侥幸。

**2. 历史回测结果具有代表性**

baseline历史回测 CAGR **{actual_cagr*100:+.2f}%** 落在模拟中位数 **{cagr_p50*100:+.1f}%** 附近，
baseline历史回测 Sharpe **{actual_sharpe:+.3f}** 与模拟中位数 **{sharpe_p50:+.3f}** 高度吻合。
值得注意的是，baseline历史回测最大回撤 **{actual_maxdd*100:.1f}%** 优于模拟中位数 **{dd_p50*100:.1f}%**，
说明baseline历史回测并非"运气最好"的情形——模型的统计特性在历史数据上得到了如实体现，
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
""")

    st.markdown(f"""
**5. Block Bootstrap 方法的局限性**

本次模拟采用 Block Bootstrap（月度分块，≈21 交易日/块），保留了月度内的自相关结构，
对趋势跟踪策略比 IID 重采样更具代表性。但仍存在以下局限：
- 月度块无法复现**多月跨度的宏观状态持续**（如 2008 年连续 12 个月的熊市），
  因为每个月块是独立随机重排的；
- 因此，极端长跌市场环境下的回撤深度可能被低估。

**实际尾部风险可能比模拟显示的 {dd_p95*100:.1f}% 更大**。

**6. 与实盘表现的潜在差距**

蒙特卡洛模拟基于历史日收益率的重采样，隐含假设是未来收益率分布与历史一致。
实盘中存在以下不确定性：
① 历史标的池已通过 Tiingo 全量数据（含退市标的）消除幸存者偏差，但 **$60M ADV 过滤条件**基于历史均值，实盘中标的当日流动性可能低于门槛而被动排除；
② 大资金规模下**市场冲击成本**和流动性约束可能远超历史滑点假设；
③ **策略1.0套利拥挤**风险：趋势跟踪策略1.0被广泛采用后，同向仓位在相同信号触发时加剧尾部回撤。

因此，历史模拟结论应视为**乐观情景的上界**，实盘预期应适度保守。
""")

    verdict_color = "green" if prob_neg < 0.01 else ("orange" if prob_neg < 0.05 else "red")
    if prob_neg < 0.01 and prob_ruin == 0:
        verdict = "✅ 综合评价：策略1.0统计特性稳健，正收益概率高，适合长周期持有；核心风险在于水下时间过长考验投资者耐心，而非策略1.0本身的失效。"
    elif prob_neg < 0.05:
        verdict = "🟡 综合评价：策略1.0整体可行，但存在一定负收益概率，需关注极端回撤情形。"
    else:
        verdict = "⚠️ 综合评价：负收益概率偏高，需重新审视策略1.0参数或市场适用性。"

    st.markdown(
        f'<div class="info-box"><strong>{verdict}</strong></div>',
        unsafe_allow_html=True,
    )

    st.page_link("pages/limitations.py", label="→ 局限性声明（完整风险披露）", icon="⚠️")

    # 数据更新对比
    from website.utils.comparison import render_mc_comparison
    render_mc_comparison(meta, mc)

else:
    st.info("蒙特卡洛数据尚未生成，无法提供评估。运行：python src/scripts/05_run_montecarlo.py")
