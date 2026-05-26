"""Walk-Forward 验证"""

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

render_page_header("Walk-Forward 验证  Out-of-Sample Analysis", meta)
st.caption(f"{meta.display_name} · 回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

_WF_PATH     = Path(__file__).resolve().parents[2] / "results" / "v1" / "walkforward.json"
_STRESS_PATH = Path(__file__).resolve().parents[2] / "results" / "v1" / "stress.json"

wf_data     = None
stress_data = None

if _WF_PATH.exists():
    try:
        wf_data = json.loads(_WF_PATH.read_text(encoding="utf-8"))
    except Exception:
        wf_data = None

if _STRESS_PATH.exists():
    try:
        stress_data = json.loads(_STRESS_PATH.read_text(encoding="utf-8"))
    except Exception:
        stress_data = None

# ── Section 1: Walk-Forward ───────────────────────────────────────────────────
st.subheader("Walk-Forward OOS 验证方法")
st.markdown("""
采用**扩展窗口（Expanding Window）**设计：IS 起始固定在 2004 年，OOS 为逐年滚动向前的单年度：

```
IS: 2004──────────────2021  │  OOS: 2022
IS: 2004─────────────────2022  │  OOS: 2023
IS: 2004────────────────────2023  │  OOS: 2024
IS: 2004───────────────────────2024  │  OOS: 2025
```

所有 OOS 窗口均使用**相同的基准参数**（无窗口内重新优化），
评估策略是否在样本外保持稳健，而非过拟合历史数据。
""")

if wf_data:
    import plotly.graph_objects as go

    windows = wf_data.get("windows", [])
    ret     = wf_data.get("retention", {})
    full_is = wf_data.get("full_is", {})
    oos_st  = wf_data.get("oos_stitched", {})
    oos_spy = wf_data.get("oos_stitched_spy", {})

    # ── OOS stitched equity curve ─────────────────────────────────────────
    st.subheader("OOS 拼接净值曲线 vs SPY")

    oos_dates = oos_st.get("dates", [])
    oos_nav   = oos_st.get("nav", [])

    if oos_dates and oos_nav:
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=oos_dates, y=oos_nav,
            mode="lines",
            line=dict(color="#1f77b4", width=2.5),
            name="策略 OOS 拼接",
        ))

        spy_dates = oos_spy.get("dates", [])
        spy_nav   = oos_spy.get("nav", [])
        if spy_dates and spy_nav:
            fig.add_trace(go.Scatter(
                x=spy_dates, y=spy_nav,
                mode="lines",
                line=dict(color="#aaaaaa", width=1.5, dash="dash"),
                name="SPY（同期）",
            ))

        # Add OOS window separators
        for w in windows:
            fig.add_shape(
                type="line",
                x0=w["oos_start"], x1=w["oos_start"],
                y0=0, y1=1, yref="paper",
                line=dict(dash="dot", color="#888", width=1),
            )
            fig.add_annotation(
                x=w["oos_start"], y=1.04, yref="paper",
                text=w["label"], showarrow=False,
                font=dict(size=10, color="#888"),
            )

        oos_m = oos_st.get("metrics", {})
        fig.update_layout(
            title=(
                f"OOS 拼接净值（4年汇总）  "
                f"CAGR {oos_m.get('cagr',0)*100:+.1f}%  "
                f"Sharpe {oos_m.get('sharpe',0):+.3f}  "
                f"MaxDD {oos_m.get('max_drawdown',0)*100:.1f}%"
            ),
            xaxis_title="日期",
            yaxis_title="净值（归一化，各OOS期独立起点=1.0）",
            height=440,
            margin=dict(t=60, b=50, l=50, r=20),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── IS vs OOS summary table ───────────────────────────────────────────
    st.subheader("IS vs OOS 指标对比")

    rows = []
    for w in windows:
        is_m  = w.get("is",  {})
        oos_m = w.get("oos", {})
        spy_oos = w.get("spy_oos", {})
        is_cagr  = is_m.get("cagr", 0)
        oos_cagr = oos_m.get("cagr", 0)
        retention = oos_cagr / is_cagr if abs(is_cagr) > 1e-9 else 0.0
        rows.append({
            "窗口":         w["label"],
            "OOS 区间":     f"{w['oos_start'][:7]} → {w['oos_end'][:7]}",
            "IS CAGR":      f"{is_cagr*100:+.1f}%",
            "OOS CAGR":     f"{oos_cagr*100:+.1f}%",
            "CAGR保留率":   f"{retention*100:.0f}%",
            "OOS Sharpe":   f"{oos_m.get('sharpe',0):+.3f}",
            "OOS MaxDD":    f"{oos_m.get('max_drawdown',0)*100:.1f}%",
            "SPY OOS CAGR": f"{spy_oos.get('cagr',0)*100:+.1f}%" if spy_oos else "—",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Retention metrics highlight
    cagr_ret   = ret.get("cagr_retention",   0)
    sharpe_ret = ret.get("sharpe_retention", 0)
    oos_m = oos_st.get("metrics", {})

    rc1, rc2, rc3, rc4 = st.columns(4)
    rc1.metric("平均 CAGR 保留率",   f"{cagr_ret*100:.0f}%",
               help="OOS CAGR / IS CAGR，理想值 > 70%")
    rc2.metric("平均 Sharpe 保留率", f"{sharpe_ret*100:.0f}%",
               help="OOS Sharpe / IS Sharpe，理想值 > 60%")
    rc3.metric("OOS 拼接 CAGR",      f"{oos_m.get('cagr',0)*100:+.1f}%")
    rc4.metric("OOS 拼接 MaxDD",     f"{oos_m.get('max_drawdown',0)*100:.1f}%")

    # Interpretation
    overfit_flag = cagr_ret < 0.5
    color = "red" if overfit_flag else ("orange" if cagr_ret < 0.7 else "green")
    verdict = "⚠️ 存在过拟合风险" if overfit_flag else ("🟡 中等保留率" if cagr_ret < 0.7 else "✅ 鲁棒性良好")
    st.markdown(
        f'<div class="info-box">'
        f'<strong>判断：{verdict}</strong>　'
        f'CAGR 保留率 {cagr_ret*100:.0f}%（理想 > 70%），'
        f'Sharpe 保留率 {sharpe_ret*100:.0f}%（理想 > 60%）。'
        f'扩展窗口设计使用固定基准参数，结果反映策略在历史样本外的真实稳健性。'
        f'</div>',
        unsafe_allow_html=True,
    )

else:
    st.info(
        "Walk-Forward 数据尚未生成。运行：\n"
        "```\npython src/scripts/08_run_walkforward.py\n```"
    )

st.markdown("---")

# ── Section 2: Execution Stress ───────────────────────────────────────────────
st.subheader("执行压力测试（Execution Stress）")
st.markdown("""
评估策略对**不利执行条件**的敏感程度：
- **滑点压力**：将单边滑点从 5 bps 增加至 30 bps（当前基准 10 bps）
- **延迟执行**：模拟 1–2 天执行延迟的 NAV 影响
- **部分成交**：目标仓位仅 50%–80% 成交
""")

if stress_data:
    import plotly.graph_objects as go

    # Slippage stress chart
    slip_records = stress_data.get("slippage_stress", [])
    if slip_records:
        slip_df = pd.DataFrame(slip_records)
        st.subheader("滑点压力（CAGR & Sharpe）")

        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(
            x=slip_df["slippage_bps"],
            y=slip_df["cagr"] * 100,
            mode="lines+markers",
            name="CAGR (%)",
            line=dict(color="#1f77b4", width=2),
            marker=dict(size=8),
            yaxis="y1",
        ))
        fig3.add_trace(go.Scatter(
            x=slip_df["slippage_bps"],
            y=slip_df["sharpe"],
            mode="lines+markers",
            name="Sharpe",
            line=dict(color="#ff7f0e", width=2, dash="dot"),
            marker=dict(size=8),
            yaxis="y2",
        ))
        fig3.update_layout(
            xaxis_title="单边滑点（bps）",
            yaxis=dict(title="CAGR (%)", side="left"),
            yaxis2=dict(title="Sharpe", side="right", overlaying="y"),
            height=360,
            margin=dict(t=20, b=50, l=60, r=60),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        # Mark baseline
        fig3.add_vline(x=10, line_dash="dash", line_color="#888",
                       annotation_text="基准 10bps", annotation_position="top right")
        st.plotly_chart(fig3, use_container_width=True)

    # Sensitivity summary table
    sens_rows = stress_data.get("sensitivity_table", [])
    if sens_rows:
        st.subheader("执行敏感性汇总表")
        st.dataframe(pd.DataFrame(sens_rows), use_container_width=True, hide_index=True)

else:
    st.info(
        "压力测试数据尚未生成。运行：\n"
        "```\npython src/scripts/07_run_stress.py\n```"
    )
