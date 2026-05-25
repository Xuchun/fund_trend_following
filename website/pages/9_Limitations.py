import streamlit as st
st.set_page_config(page_title="局限性声明", page_icon="⚠️", layout="wide")
from website.shared import setup_sidebar
from website.components.strategy_badge import render_page_header

res  = setup_sidebar()
meta = res.meta

render_page_header("局限性与风险声明  Limitations & Disclosures", meta)
st.caption("专业投资者必读：回测结果的已知偏差与局限性")
st.markdown("---")

st.markdown("""
<div class="warning-box">
<h4>⚠️ 重要声明</h4>
回测结果基于历史数据，<strong>不代表未来表现</strong>。以下偏差均会导致回测结果系统性高于真实可获得的收益，
请在评估策略可行性时充分考虑以下所有偏差的综合影响。
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Bias 1: Survivorship (most important) ───────────────────────────────────
st.subheader("偏差 1：幸存者偏差（最重要，影响最大）")
col1, col2 = st.columns([2, 1])
with col1:
    st.markdown("""
**问题**：本回测的标的池（S&P 900）仅包含截至 2024 年底仍在成分股中的公司，
不含 2004–2024 年间因破产、退市或被并购而消失的公司。

**典型案例（2008年金融危机相关）**：
- 雷曼兄弟（Lehman Brothers）— 破产
- 贝尔斯登（Bear Stearns）— 被收购
- 华盛顿互惠（Washington Mutual）— 被接管
- 电路城（Circuit City）— 破产

这些公司在其存续期内产生大量亏损，但在本回测中完全缺席，导致策略「天然回避」了最坏的结局。

**量化影响**：根据学术研究，幸存者偏差通常导致 CAGR **虚高 20%–50%**（具体取决于标的池和回测期）。
""")
with col2:
    m = res.metrics
    cagr = m.get("cagr", 0)
    st.markdown(f"""
<div style="border:2px solid #e65100;border-radius:8px;padding:16px;background:#fff3e0;">
<div style="font-size:0.85rem;color:#e65100;font-weight:700">回测 CAGR</div>
<div style="font-size:2rem;font-weight:700;color:#e65100">{cagr*100:+.2f}%</div>
<div style="font-size:0.8rem;color:#888;margin-top:8px">保守预期（下调 30%–50%）</div>
<div style="font-size:1.5rem;font-weight:700;color:#d62728">{cagr*100*0.5:+.2f}% ~ {cagr*100*0.7:+.2f}%</div>
<div style="font-size:0.75rem;color:#999;margin-top:6px">这才是更接近真实的区间</div>
</div>
""", unsafe_allow_html=True)

st.markdown("**解决方案**：切换至含历史退市股数据的商业数据源（如 Polygon.io / Refinitiv CRSP），此偏差将自动消除。")

st.markdown("---")

# ── Bias 2: Market cap not point-in-time ────────────────────────────────────
st.subheader("偏差 2：市值非 Point-in-Time")
st.markdown("""
**问题**：使用当前（2024年）的 S&P 900 成分股作为整个回测期（2004–2024）的候选池。
历史上，这些公司中有一部分在 2004 年时市值远低于 $20 亿（策略的筛选门槛），属于「事后知道它们长大了」的选股偏差。

**影响**：策略在历史上无意间选到了一批后来成为大公司的「明日之星」，低估了实际的信号质量。
""")

st.markdown("---")

# ── Bias 3: ETF inception dates ─────────────────────────────────────────────
st.subheader("偏差 3：ETF 成立日期")
st.markdown("""
**问题**：部分 ETF（如 XLRE 于 2015 年成立、XLC 于 2018 年成立）在回测早期尚不存在，
但已被纳入 2004 年起的候选池。

**影响**：相对有限，因为 ETF 占总标的池比例较小（约 2%），且主要 ETF（SPY、QQQ 等）成立时间远早于 2004 年。
""")

st.markdown("---")

# ── Bias 4: Execution cost simplification ───────────────────────────────────
st.subheader("偏差 4：执行成本低估")
st.markdown("""
**问题**：当前模型使用固定滑点（10 bps）和固定佣金（3 bps），未建模「市场冲击成本」（Market Impact）。

对于管理规模较大的实盘账户（如 $1000 万以上），大单交易会推动市场价格不利于自己，
实际执行成本可能显著高于模型中的 13 bps。

**建议**：实盘初期用较小规模（$100–300 万）验证策略，逐步扩大规模后重新评估滑点模型。
""")

st.markdown("---")

# ── Bear market limitation ───────────────────────────────────────────────────
st.subheader("偏差 5：纯多头策略在熊市的系统性局限")
st.markdown(f"""
**问题**：Strategy 1.0 为纯多头策略（Long Only），在熊市中仅能通过止损出局，无法做空获益。

本次回测包含 2008 年金融危机（标准普尔 500 指数跌幅约 -55%），
策略的最大回撤为 **{res.metrics.get('max_drawdown',0)*100:.1f}%**，
恢复期约 **{res.metrics.get('max_dd_duration_days',0):.0f} 天**（约 12 年）。

这是策略设计层面的已知缺陷，**不是代码错误**。

**解决方向**（Strategy 2.0 规划中）：
- 加入市场环境过滤器（SPY 低于 200 日均线时禁止开多仓）
- 或引入做空信号（N 日低点突破做空）
""")

st.markdown("---")

# ── Recommended haircut summary ──────────────────────────────────────────────
st.subheader("综合建议：实盘预期的合理 Haircut")
st.markdown("""
<div class="warning-box">
<h4>⚠️ 给 Portfolio Manager 的建议</h4>
综合以上所有偏差，建议对回测指标进行如下折扣后作为实盘预期：
</div>
""", unsafe_allow_html=True)

import pandas as pd
m = res.metrics
haircut_df = pd.DataFrame([
    ("CAGR", f"{m.get('cagr',0)*100:+.2f}%", "×50%–70%",
     f"{m.get('cagr',0)*100*0.5:+.2f}% ~ {m.get('cagr',0)*100*0.7:+.2f}%"),
    ("Sharpe 比率", f"{m.get('sharpe',0):+.3f}", "×50%–70%",
     f"{m.get('sharpe',0)*0.5:+.3f} ~ {m.get('sharpe',0)*0.7:+.3f}"),
    ("最大回撤", f"{m.get('max_drawdown',0)*100:.1f}%", "×130%–150%（更深）",
     f"{m.get('max_drawdown',0)*100*1.3:.1f}% ~ {m.get('max_drawdown',0)*100*1.5:.1f}%"),
], columns=["指标", "回测值", "建议调整", "保守预期区间"])

st.dataframe(haircut_df, use_container_width=True, hide_index=True)
