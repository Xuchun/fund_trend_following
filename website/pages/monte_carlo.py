"""蒙特卡洛风险分析"""

from __future__ import annotations

import json
import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
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

st.subheader("分析目标")
st.markdown(f"""
蒙特卡洛模拟将通过**随机重采样历史交易序列**（Bootstrap Resampling），
评估策略在不同市场路径下的表现分布：

**模拟方法：**
- 对 {res.metrics.get('n_trades', 0):,} 笔历史交易进行有放回抽样
- 生成 1,000 条模拟净值路径
- 分析 CAGR、MaxDD、Sharpe 的 5th/25th/50th/75th/95th 百分位分布

**关键输出（待生成）：**
1. 净值路径扇形图（1,000 条路径 + 置信区间）
2. CAGR 分布直方图（最差 5% 情境）
3. 最大回撤分布（99% VAR）
4. 破产概率（NAV < 50% 初始资金的概率）
""")

st.markdown("---")
st.subheader("连续亏损序列分析（基于历史真实交易）")

_DIAG_PATH = Path(__file__).resolve().parents[2] / "results" / "v1" / "diagnostics.json"

if _DIAG_PATH.exists():
    import plotly.graph_objects as go

    _diag = json.loads(_DIAG_PATH.read_text(encoding="utf-8"))
    _sa   = _diag.get("streak_analysis", {})
    _streak_counts: dict = _sa.get("streak_counts", {})

    if _streak_counts:
        # Build bar data: x = 1..9 individually, then "≥10"
        x_labels: list[str] = []
        y_counts: list[int] = []
        bar_colors: list[str] = []

        for length in range(1, 10):
            x_labels.append(str(length))
            y_counts.append(_streak_counts.get(str(length), 0))
            if length <= 4:
                bar_colors.append("#2ca02c")   # green — normal
            else:
                bar_colors.append("#f57c00")   # orange — tough

        # >= 10 group
        x_labels.append("≥10")
        y_counts.append(_streak_counts.get("10+", 0))
        bar_colors.append("#d62728")           # red — extreme

        fig = go.Figure(
            data=[
                go.Bar(
                    x=x_labels,
                    y=y_counts,
                    marker_color=bar_colors,
                    text=y_counts,
                    textposition="outside",
                )
            ]
        )
        fig.update_layout(
            title="历史连续亏损序列分布",
            xaxis_title="连续亏损笔数",
            yaxis_title="出现次数",
            showlegend=False,
            height=380,
            margin=dict(t=50, b=40, l=40, r=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Metrics row
    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("最长连续亏损（笔）", _sa.get("max_consecutive_losses", 0))
    mc2.metric("总亏损序列数",       _sa.get("total_streaks", 0))
    mc3.metric("平均序列长度",       f"{_sa.get('avg_streak_length', 0.0):.2f}")

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

placeholder("Phase 6", "蒙特卡洛风险分析")
