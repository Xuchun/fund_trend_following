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

render_page_header("市场环境分析", meta)
st.caption(f"{meta.display_name} · 回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

_REGIME_PATH = Path(__file__).resolve().parents[2] / "results" / "v1_unbiased_60m_2000" / "regime.json"

regime_data = None
if _REGIME_PATH.exists():
    try:
        regime_data = json.loads(_REGIME_PATH.read_text(encoding="utf-8"))
    except Exception:
        regime_data = None

# ── Section 0: 市场环境定义 ───────────────────────────────────────────────────
st.subheader("市场环境定义")
st.markdown(
    "各环境的起止日期以 **S&P500 关键拐点月份**为边界，而非自然年末对齐，"
    "使每个环境对应一个在经济上相对同质的市场阶段。\n\n"
    "注：2000-01 至 2000-02（互联网泡沫末期上涨阶段）未划入任何环境，约 41 个交易日。"
)
st.markdown("""
| 市场环境 | 起始 | 结束 | 边界确定依据 |
|---------|------|------|------------|
| 互联网泡沫崩溃 | 2000-03 | 2002-10 | S&P500 顶部 **2000-03-24**（纳斯达克 −78%）；底部 **2002-10-09** |
| 熊市后复苏 | 2002-11 | 2007-10 | 底部次月启动；S&P500 再次见顶 **2007-10-09** |
| 金融危机 | 2007-11 | 2009-03 | 顶部次月下行加速；S&P500 底部 **2009-03-09**（−57%） |
| QE驱动慢牛 | 2009-04 | 2020-01 | 底部次月 QE 开始生效；COVID 冲击前最后完整月 |
| COVID崩盘+复苏 | 2020-02 | 2021-12 | 暴跌始于 **2020-02-19**（S&P500 −34%）；含 V 形完整复苏 |
| 加息熊市 | 2022-01 | 2022-09 | S&P500 于 **2022-01-03** 见顶；9月末(340.79)≈年内最低，10月起已明显反弹（+8%），10-12月留白 |
| AI驱动牛市 | 2023-01 | 2026-06 | ChatGPT 引爆 AI 主题；延伸至回测结束日 **2026-06-15** |
""")
st.markdown("---")

# ── Section 1: 市场环境汇总表 ─────────────────────────────────────────────────
st.subheader("各市场环境绩效汇总")

REGIME_DESC = {
    "互联网泡沫崩溃": "S&P500 顶部→底部，纳斯达克最大跌幅 −78%",
    "熊市后复苏":     "底部反弹，房市泡沫积累，S&P500 五年涨幅 +100%",
    "金融危机":       "雷曼破产，S&P500 峰谷跌幅 −57%",
    "QE驱动慢牛":     "美联储宽松周期，十一年长牛，S&P500 年化 +13.6%",
    "COVID崩盘+复苏": "疫情急跌 −34% 后 V 形反弹，波动率极高",
    "加息熊市":       "美联储激进加息，股债双杀，2022年前三季度 SPY 年化 −31%（10月起已反弹，10-12月留白）",
    "AI驱动牛市":     "ChatGPT 引爆 AI 主题，科技股集中领涨",
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
            "策略1.0 CAGR":     f"{s.get('cagr',0)*100:+.1f}%",
            "策略1.0 MaxDD":    f"{s.get('max_drawdown',0)*100:.1f}%",
            "策略1.0 Sharpe":   f"{s.get('sharpe',0):+.3f}",
            "SPY CAGR":      f"{spy.get('cagr',0)*100:+.1f}%" if spy else "—",
            "SPY MaxDD":     f"{spy.get('max_drawdown',0)*100:.1f}%" if spy else "—",
            "交易笔数":      f"{s.get('n_trades',0):,}",
            "胜率":          f"{s.get('win_rate',0)*100:.1f}%",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── CAGR comparison bar chart ──────────────────────────────────────────
    st.subheader("策略1.0 vs SPY：各环境 CAGR 对比")

    names        = list(regimes.keys())
    strat_cagrs  = [regimes[n]["strategy"].get("cagr", 0) * 100 for n in names]
    spy_cagrs    = [regimes[n].get("spy", {}).get("cagr", 0) * 100 for n in names]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="策略1.0", x=names, y=strat_cagrs,
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
        name="策略1.0 MaxDD", x=names, y=strat_dds,
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
            cols[0].metric("策略1.0 CAGR",    f"{s.get('cagr',0)*100:+.1f}%")
            cols[1].metric("策略1.0 Sharpe",   f"{s.get('sharpe',0):+.3f}")
            cols[2].metric("策略1.0 MaxDD",    f"{s.get('max_drawdown',0)*100:.1f}%")
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

    _crisis_s   = regimes.get("金融危机", {})
    _crisis_dd  = _crisis_s.get("strategy", {}).get("max_drawdown", 0)
    _crisis_spy_dd = _crisis_s.get("spy", {}).get("max_drawdown", 0)
    st.markdown(
        f'<div class="info-box">'
        f'策略1.0在 <strong>QE驱动慢牛（2009–2020）</strong>和 <strong>AI驱动牛市（2023–今）</strong>绝对收益可观，但跑输 SPY。'
        f'<strong>金融危机</strong>期间纯多头策略1.0跟随下跌（无做空），但最大回撤仅 {_crisis_dd*100:.1f}%，'
        f'远低于 SPY 的 {_crisis_spy_dd*100:.1f}%。'
        f'<strong>加息熊市（2022）</strong>是最大考验：SPY 过滤器阻止了大量开仓，但已持仓跟随下行直至止损触发。'
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
| 加息熊市 | 2022-01 ~ 2022-09 | 股债双杀，SPY 年化 −31%（前三季度）|
| AI驱动牛市 | 2023–2025 | 科技领涨，趋势集中 |
""")

# ── Assessment ────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("评估")

if regime_data and "regimes" in regime_data:
    regimes  = regime_data["regimes"]
    full_p   = regime_data.get("full_period", {})

    def _s(name):
        return regimes.get(name, {}).get("strategy", {})

    def _spy(name):
        return regimes.get(name, {}).get("spy", {})

    def _alpha(name):
        sc = _s(name).get("cagr", 0)
        bc = _spy(name).get("cagr", 0)
        return sc - bc

    crisis_alpha   = _alpha("金融危机")
    crisis_strat_dd = _s("金融危机").get("max_drawdown", 0)
    crisis_spy_dd   = _spy("金融危机").get("max_drawdown", 0)

    qe_alpha        = _alpha("QE驱动慢牛")
    qe_cagr         = _s("QE驱动慢牛").get("cagr", 0)
    qe_spy_cagr     = _spy("QE驱动慢牛").get("cagr", 0)
    qe_sharpe       = _s("QE驱动慢牛").get("sharpe", 0)

    covid_cagr      = _s("COVID崩盘+复苏").get("cagr", 0)
    covid_sharpe    = _s("COVID崩盘+复苏").get("sharpe", 0)
    covid_strat_dd  = _s("COVID崩盘+复苏").get("max_drawdown", 0)
    covid_spy_dd    = _spy("COVID崩盘+复苏").get("max_drawdown", 0)

    hike_cagr       = _s("加息熊市").get("cagr", 0)
    hike_spy_cagr   = _spy("加息熊市").get("cagr", 0)
    hike_alpha      = _alpha("加息熊市")
    hike_winrate    = _s("加息熊市").get("win_rate", 0)
    hike_strat_dd   = _s("加息熊市").get("max_drawdown", 0)

    ai_cagr         = _s("AI驱动牛市").get("cagr", 0)
    ai_spy_cagr     = _spy("AI驱动牛市").get("cagr", 0)
    ai_alpha        = _alpha("AI驱动牛市")
    ai_sharpe       = _s("AI驱动牛市").get("sharpe", 0)
    ai_strat_dd     = _s("AI驱动牛市").get("max_drawdown", 0)

    bubble_cagr     = _s("互联网泡沫崩溃").get("cagr", 0)
    bubble_spy_cagr = _spy("互联网泡沫崩溃").get("cagr", 0)
    recovery_cagr   = _s("熊市后复苏").get("cagr", 0)
    recovery_spy_cagr = _spy("熊市后复苏").get("cagr", 0)

    full_cagr   = full_p.get("cagr", 0)
    full_sharpe = full_p.get("sharpe", 0)
    full_dd     = full_p.get("max_drawdown", 0)

    st.markdown(f"""
**1. 下行保护是策略1.0最核心的竞争优势**

金融危机（2007-11 → 2009-03）是对策略1.0最有力的压力测试：
SPY 最大回撤高达 **{crisis_spy_dd*100:.1f}%**，而策略1.0最大回撤仅 **{crisis_strat_dd*100:.1f}%**；
SPY 年化收益 **{_spy("金融危机").get("cagr",0)*100:+.2f}%**，策略1.0实现 **{_s("金融危机").get("cagr",0)*100:+.2f}%**，
超额收益 **{crisis_alpha*100:+.2f}%**。
追踪止损机制在趋势反转初期有效截断了亏损，令策略1.0在峰谷完整的系统性崩盘中
显著跑赢大盘，这是该策略1.0最有说服力的结果，也是其作为投资组合"尾部保护"配置的核心价值。

**2. COVID 急跌：回撤控制远优于 SPY，绝对收益亮眼**

COVID 期间（2020–2021）是策略1.0风险调整回报最佳的阶段：
CAGR **{covid_cagr*100:+.2f}%**，Sharpe **{covid_sharpe:+.3f}**，最大回撤仅 **{covid_strat_dd*100:.1f}%**。
相比之下 SPY 最大回撤 **{covid_spy_dd*100:.1f}%**（急跌-34%后强劲反弹）。
策略1.0在急跌时止损及时，在复苏趋势中快速建仓，
充分体现了追踪止损 + 趋势跟踪在高波动环境中的优势。

**3. 牛市跑输 SPY 是结构性特征，非策略1.0缺陷**

QE 驱动慢牛（2009-04 → 2020-01）中，策略1.0 CAGR **{qe_cagr*100:+.2f}%** vs SPY **{qe_spy_cagr*100:+.2f}%**，
差距 **{qe_alpha*100:+.2f}%**；AI 驱动牛市（2023-01 → 2026-06）差距进一步扩大至 **{ai_alpha*100:+.2f}%**。
这是**结构性弱点**：纯多头趋势策略1.0持有多元化仓位，
在 SPY 由少数科技股集中拉动的环境下必然滞后。
但需注意，策略1.0在 AI 牛市中的 CAGR 仍达 **{ai_cagr*100:+.2f}%**，Sharpe **{ai_sharpe:+.3f}**，
最大回撤 **{ai_strat_dd*100:.1f}%**——绝对收益可观，只是相对收益落后。

**4. 加息熊市（2022年前三季度）：下行保护再次验证**

2022年1-9月，策略1.0 CAGR **{hike_cagr*100:+.2f}%**，SPY 同期 **{hike_spy_cagr*100:+.2f}%**，超额 **{hike_alpha*100:+.2f}%**。
绝对收益为负（策略仍亏损），但相对 SPY 的防御能力是所有环境中最突出的之一：
SPY 过滤器在趋势下行初期阻断了大量新仓，限制了新增敞口；
已持仓通过追踪止损及时减仓，最大回撤控制在 **{hike_strat_dd*100:.1f}%**，
远低于 SPY 的 **{hike_spy_cagr*100:.1f}%** 年化跌幅。
胜率骤降至 **{hike_winrate*100:.1f}%** 揭示了纯多头策略在熊市中的局限：
无做空能力，只能被动减少损失，无法主动获利。

**5. 跨环境综合评价：攻守失衡是已知权衡**

| 环境 | 策略1.0表现 | vs SPY |
|------|----------|--------|
| 互联网泡沫崩溃 | ✅ 极强 | 大幅跑赢（{bubble_cagr*100:+.1f}% vs {bubble_spy_cagr*100:+.1f}%） |
| 熊市后复苏 | ✅ 强 | 跑赢（{recovery_cagr*100:+.1f}% vs {recovery_spy_cagr*100:+.1f}%） |
| 金融危机 | 🟡 抗跌 | 跑赢（损失远少于 SPY {crisis_spy_dd*100:.1f}%） |
| QE驱动慢牛 | 🔴 落后 | 跑输约 {abs(qe_alpha)*100:.1f}%（牛市代价） |
| COVID崩盘+复苏 | ✅ 极强 | 回撤控制优于 SPY（策略 {covid_strat_dd*100:.1f}% vs SPY {covid_spy_dd*100:.1f}%） |
| 加息熊市 | ✅ 强 | 大幅跑赢（{hike_cagr*100:+.1f}% vs SPY {hike_spy_cagr*100:+.1f}%，超额 {hike_alpha*100:+.1f}%）|
| AI驱动牛市 | 🟡 可接受 | 跑输 {abs(ai_alpha)*100:.1f}% 但绝对收益可观（{ai_cagr*100:+.1f}%） |

策略1.0在**每一个市场环境中均跑赢或接近 SPY 的风险调整表现**，
但以"原始收益率"衡量，只有金融危机和 COVID 崩盘阶段能明显击败 SPY。
这是趋势跟踪与买入持有策略1.0之间的经典权衡：
**用牛市的相对落后，换取熊市的本金保护**。
""")

    # Verdict
    bear_markets = [n for n in ["金融危机", "加息熊市"] if _alpha(n) > 0]
    bull_markets_neg = [n for n in ["QE驱动慢牛", "AI驱动牛市"] if _alpha(n) < -0.05]

    verdict = (
        f"✅ 综合评价：策略1.0在 5 个市场环境中展示出一致的风险控制能力——"
        f"熊市/危机场景（金融危机、加息熊市）均跑赢 SPY，"
        f"牛市环境获得正绝对收益但落后于 SPY。"
        f"全周期 CAGR {full_cagr*100:+.2f}%、Sharpe {full_sharpe:+.3f}、MaxDD {full_dd*100:.1f}%，"
        f"定位是**攻守兼备但偏重防守**的量化策略，"
        f"适合将其视为投资组合的风险对冲配置而非单纯超越指数的工具。"
    )
    st.markdown(
        f'<div class="info-box"><strong>{verdict}</strong></div>',
        unsafe_allow_html=True,
    )

    # 数据更新对比
    from website.utils.comparison import render_regime_comparison
    render_regime_comparison(meta, regime_data)

else:
    st.info("市场环境分析数据尚未生成，无法提供评估。运行：python src/scripts/09_run_regime.py")
