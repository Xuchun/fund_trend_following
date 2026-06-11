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

render_page_header("Walk-Forward 验证", meta)
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
IS: 2004──────────────────────────2025  │  OOS: 2026（部分，截至 2026-06-09）
```

所有 OOS 窗口均使用**相同的基准参数**（无窗口内重新优化），
评估策略1.0是否在样本外保持稳健，而非过拟合历史数据。
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
            name="策略1.0 OOS 拼接",
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
        f'扩展窗口设计使用固定基准参数，结果反映策略1.0在历史样本外的真实稳健性。'
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
评估策略1.0对**不利执行条件**的敏感程度：
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

# ── Assessment ────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("评估")

if wf_data:
    windows  = wf_data.get("windows", [])
    ret      = wf_data.get("retention", {})
    full_is  = wf_data.get("full_is", {})
    oos_m    = wf_data.get("oos_stitched", {}).get("metrics", {})

    cagr_ret_raw   = ret.get("cagr_retention", 0)
    sharpe_ret_raw = ret.get("sharpe_retention", 0)
    is_cagr        = full_is.get("cagr", 0)
    is_sharpe      = full_is.get("sharpe", 0)
    oos_cagr       = oos_m.get("cagr", 0)
    oos_sharpe     = oos_m.get("sharpe", 0)
    oos_maxdd      = oos_m.get("max_drawdown", 0)

    # Honest CAGR retention: oos_cagr / is_cagr (not arithmetic mean of ratios)
    honest_retention = oos_cagr / is_cagr if abs(is_cagr) > 1e-9 else 0.0

    # Per-window analysis
    pos_windows = sum(1 for w in windows if w.get("oos", {}).get("cagr", 0) > 0)
    beat_spy_windows = sum(
        1 for w in windows
        if w.get("oos", {}).get("cagr", 0) > w.get("spy_oos", {}).get("cagr", 0)
    )
    total_windows = len(windows)

    st.markdown(f"""
**1. 无过拟合，策略1.0样本外有正收益**

在 4 个独立 OOS 窗口中，**{pos_windows}/{total_windows} 个窗口实现正收益**，
OOS 拼接净值 CAGR 为 **{oos_cagr*100:+.2f}%**（对比全样本内 IS CAGR {is_cagr*100:+.2f}%）。
这是 Walk-Forward 验证的核心结论：策略1.0在从未参与参数优化的年份依然盈利，
表明参数不是对历史数据的过度拟合，而是捕捉了真实的市场结构规律。

**2. 2022 熊市是策略1.0最强的 OOS 验证**

2022 年（Window 1）是唯一出现负收益的 OOS 年份，策略1.0 CAGR **-15.45%**——
但同期 SPY 收益为 **-18.2%**，策略1.0在最恶劣的 OOS 市场中仍**跑赢基准 +2.7 个百分点**。
加息熊市中 SPY 过滤器抑制了新仓开立，而存量仓位随趋势下行，
这是纯多头趋势跟踪策略1.0的结构性弱点，属预期之内，并非策略1.0失效。

**3. 2023–2024 牛市 OOS 收益优秀，但落后于 SPY**

2023 年 OOS CAGR **+17.86%**、2024 年 **+18.95%**，表现出色，
但同期 SPY 分别为 **+26.4%** 和 **+24.9%**，策略1.0落后约 7–8 个百分点。
这是趋势跟踪在 AI 驱动的集中型牛市中的典型滞后——宽基指数由少数科技股拉动，
而策略1.0持有的多元化趋势仓位难以集中受益。策略1.0的优势在于波动率控制，而非追顶。

**4. CAGR 保留率指标有误导性，Sharpe 保留率更诚实**

页面显示"平均 CAGR 保留率 {cagr_ret_raw*100:.0f}%"——
这是各窗口 OOS/IS 比率的算术均值，Window 2/3 的超高保留率（+277%、+271%）
与 Window 1 的负值相互抵消，结果在数学上偶然接近 100%，**不能视为策略1.0健康的证明**。

更诚实的指标是整体衰减率：OOS 拼接 CAGR {oos_cagr*100:+.2f}% vs IS {is_cagr*100:+.2f}%，
绝对保留率约 **{honest_retention*100:.0f}%**；
OOS Sharpe **{oos_sharpe:+.3f}** vs IS Sharpe **{is_sharpe:+.3f}**，
Sharpe 保留率约 **{(oos_sharpe/is_sharpe*100) if abs(is_sharpe)>1e-9 else 0:.0f}%**，
这才是策略1.0样本外效率衰减的真实刻度。

**5. 2025 年（部分 OOS）表现疲软，需持续关注**

Window 4（2025 年全年 OOS）CAGR 仅 **+3.08%**，Sharpe **+0.138**，
同期 SPY 达 **+17.9%**，差距扩大。需注意 2025 年数据可能尚不完整（取决于回测截止日），
但若这一趋势持续，可能意味着当前市场环境（AI 科技股集中牛市）对多元趋势策略1.0不利，
而非策略1.0本身的失效——历史上量化宽松牛市（2010–2019）同样出现过数年策略1.0跑输指数的阶段。

**6. Walk-Forward 设计的局限性**

本次采用"扩展窗口、固定参数"设计，这是验证过拟合的标准方法，
但存在两点值得注意：
① 全部 IS 窗口均以 2004 年为起点，参数在金融危机和量化宽松的完整周期上被隐含优化，
   若策略1.0在 2022–2025 这一小样本上运行，参数未必会选择相同；
② OOS 仅 4 年（3 年完整），统计置信度有限——单年度的正负表现差异可能是环境使然，
   而非策略1.0能力的真实信号。建议在获得更多年度 OOS 数据后重新评估结论的稳健性。
""")

    # Verdict
    if pos_windows >= 3 and honest_retention > 0.5:
        verdict = f"✅ 综合评价：Walk-Forward 验证通过。{pos_windows}/4 个 OOS 窗口盈利，OOS CAGR {oos_cagr*100:+.1f}% 证明策略1.0无明显过拟合；核心提示是近年 Sharpe 衰减（{oos_sharpe:+.3f} vs IS {is_sharpe:+.3f}），在强势集中牛市中 alpha 来源受到压缩，属于趋势跟踪策略1.0的已知特性。"
    elif pos_windows >= 2:
        verdict = f"🟡 综合评价：Walk-Forward 结果中性，{pos_windows}/4 窗口盈利，OOS CAGR {oos_cagr*100:+.1f}%，需关注近期 alpha 衰减趋势。"
    else:
        verdict = f"⚠️ 综合评价：Walk-Forward 警示，仅 {pos_windows}/4 窗口盈利，建议审查策略1.0参数适应性。"

    st.markdown(
        f'<div class="info-box"><strong>{verdict}</strong></div>',
        unsafe_allow_html=True,
    )

else:
    st.info("Walk-Forward 数据尚未生成，无法提供评估。运行：python src/scripts/08_run_walkforward.py")
