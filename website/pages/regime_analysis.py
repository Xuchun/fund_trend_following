"""市场环境分析"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pandas as pd
import streamlit as st
from website.shared import get_results
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta

render_page_header("市场环境分析  Regime Analysis", meta)
st.caption(f"{meta.display_name} · 回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

_REGIME_PATH = Path(__file__).resolve().parents[2] / "results" / "v1" / "regime.json"

regime_data = None
if _REGIME_PATH.exists():
    try:
        regime_data = json.loads(_REGIME_PATH.read_text(encoding="utf-8"))
    except Exception:
        regime_data = None

# ── Section 1: 市场环境汇总表 ─────────────────────────────────────────────────
st.subheader("各市场环境绩效汇总")

REGIME_DESC = {
    "金融危机":       "2008–2009 年金融海啸，美股最大跌幅 -55%",
    "量化宽松牛市":   "2010–2019 年美联储宽松周期，十年牛市",
    "COVID崩盘+复苏": "2020–2021 疫情急跌急反，波动率极高",
    "加息熊市":       "2022 年美联储激进加息，股债双杀",
    "AI驱动牛市":     "2023–2025 AI 主题驱动，科技股领涨",
}

if regime_data and "regimes" in regime_data:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    regimes = regime_data["regimes"]
    full_p  = regime_data.get("full_period", {})

    # ── Summary metrics table ──────────────────────────────────────────────
    rows = []
    for name, data in regimes.items():
        s   = data.get("strategy", {})
        spy = data.get("spy", {})
        period = f"{data['start'][:7]} → {data['end'][:7]}"
        rows.append({
            "市场环境":      name,
            "区间":          period,
            "策略 CAGR":     f"{s.get('cagr',0)*100:+.1f}%",
            "策略 MaxDD":    f"{s.get('max_drawdown',0)*100:.1f}%",
            "策略 Sharpe":   f"{s.get('sharpe',0):+.3f}",
            "SPY CAGR":      f"{spy.get('cagr',0)*100:+.1f}%" if spy else "—",
            "SPY MaxDD":     f"{spy.get('max_drawdown',0)*100:.1f}%" if spy else "—",
            "交易笔数":      f"{s.get('n_trades',0):,}",
            "胜率":          f"{s.get('win_rate',0)*100:.1f}%",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── CAGR comparison bar chart ──────────────────────────────────────────
    st.subheader("策略 vs SPY：各环境 CAGR 对比")

    names        = list(regimes.keys())
    strat_cagrs  = [regimes[n]["strategy"].get("cagr", 0) * 100 for n in names]
    spy_cagrs    = [regimes[n].get("spy", {}).get("cagr", 0) * 100 for n in names]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="策略", x=names, y=strat_cagrs,
        marker_color=[
            "#2ca02c" if v >= 0 else "#d62728" for v in strat_cagrs
        ],
        text=[f"{v:+.1f}%" for v in strat_cagrs],
        textposition="outside",
    ))
    if any(v != 0 for v in spy_cagrs):
        fig.add_trace(go.Bar(
            name="SPY", x=names, y=spy_cagrs,
            marker_color="#aaaaaa",
            text=[f"{v:+.1f}%" for v in spy_cagrs],
            textposition="outside",
            opacity=0.7,
        ))

    fig.update_layout(
        barmode="group",
        title="各市场环境年化收益率（CAGR）",
        yaxis_title="CAGR (%)",
        height=420,
        margin=dict(t=50, b=80, l=50, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        hovermode="x unified",
    )
    fig.add_hline(y=0, line_dash="solid", line_color="black", line_width=1)
    st.plotly_chart(fig, use_container_width=True)

    # ── MaxDD comparison chart ─────────────────────────────────────────────
    st.subheader("各环境最大回撤对比")

    strat_dds = [regimes[n]["strategy"].get("max_drawdown", 0) * 100 for n in names]
    spy_dds   = [regimes[n].get("spy", {}).get("max_drawdown", 0) * 100 for n in names]

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        name="策略 MaxDD", x=names, y=strat_dds,
        marker_color="#f57c00",
        text=[f"{v:.1f}%" for v in strat_dds],
        textposition="outside",
    ))
    if any(v != 0 for v in spy_dds):
        fig2.add_trace(go.Bar(
            name="SPY MaxDD", x=names, y=spy_dds,
            marker_color="#d62728", opacity=0.55,
            text=[f"{v:.1f}%" for v in spy_dds],
            textposition="outside",
        ))

    fig2.update_layout(
        barmode="group",
        title="各市场环境最大回撤",
        yaxis_title="最大回撤 (%)",
        height=380,
        margin=dict(t=50, b=80, l=50, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig2, use_container_width=True)

    # ── Per-regime detail cards ────────────────────────────────────────────
    st.subheader("逐环境详情")
    for name, data in regimes.items():
        s   = data.get("strategy", {})
        spy = data.get("spy", {})
        with st.expander(f"{name}  ({data['start'][:7]} → {data['end'][:7]})"):
            st.caption(REGIME_DESC.get(name, ""))
            cols = st.columns(5)
            cols[0].metric("策略 CAGR",    f"{s.get('cagr',0)*100:+.1f}%")
            cols[1].metric("策略 Sharpe",   f"{s.get('sharpe',0):+.3f}")
            cols[2].metric("策略 MaxDD",    f"{s.get('max_drawdown',0)*100:.1f}%")
            cols[3].metric("SPY CAGR",      f"{spy.get('cagr',0)*100:+.1f}%" if spy else "—")
            cols[4].metric("SPY MaxDD",     f"{spy.get('max_drawdown',0)*100:.1f}%" if spy else "—")

            sc1, sc2 = st.columns(2)
            sc1.metric("交易笔数", f"{s.get('n_trades',0):,}")
            sc2.metric("胜率",     f"{s.get('win_rate',0)*100:.1f}%")

    # ── Full period baseline ───────────────────────────────────────────────
    st.markdown("---")
    st.subheader("全回测期基准")
    bc1, bc2, bc3, bc4 = st.columns(4)
    bc1.metric("CAGR",       f"{full_p.get('cagr',0)*100:+.2f}%")
    bc2.metric("Sharpe",     f"{full_p.get('sharpe',0):+.3f}")
    bc3.metric("MaxDD",      f"{full_p.get('max_drawdown',0)*100:.1f}%")
    bc4.metric("总交易笔数",  f"{full_p.get('n_trades',0):,}")

    st.markdown(
        f'<div class="info-box">'
        f'策略在 <strong>量化宽松牛市（2010–2019）</strong>表现最强，长趋势环境与追踪止损模型完美契合。'
        f'<strong>金融危机</strong>期间纯多头策略跟随下跌（无做空），但最大回撤显著低于 SPY（-55%）。'
        f'<strong>加息熊市（2022）</strong>是最大的考验：SPY 过滤器阻止了大量开仓但已持仓无法规避。'
        f'</div>',
        unsafe_allow_html=True,
    )

else:
    st.info(
        "市场环境分析数据尚未生成。运行：\n"
        "```\npython src/scripts/09_run_regime.py\n```"
    )

    st.subheader("环境分类说明")
    st.markdown("""
| 市场环境 | 区间 | 特征 |
|----------|------|------|
| 金融危机 | 2008–2009 | 极端下行，VIX 峰值 > 80 |
| 量化宽松牛市 | 2010–2019 | 十年长牛，低波动，强趋势 |
| COVID崩盘+复苏 | 2020–2021 | 急跌（-34%）后V形反弹 |
| 加息熊市 | 2022 | 股债双杀，SPY -19% |
| AI驱动牛市 | 2023–2025 | 科技领涨，趋势集中 |
""")
