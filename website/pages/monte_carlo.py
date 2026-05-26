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

render_page_header("蒙特卡洛风险  Monte Carlo Risk", meta)
st.caption(f"{meta.display_name} · 回测期间：{meta.backtest_start} → {meta.backtest_end}")
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
    st.subheader("模拟概览")
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("模拟路径数",    f"{mc['n_simulations']:,} 条")
    mc2.metric("模拟方法",      mc.get("method", "—").replace("_", " "))
    mc3.metric("模拟区间",      f"{mc['start']} → {mc['end']}")
    mc4.metric("模拟交易日数",  f"{mc['n_days']:,} 天")
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
