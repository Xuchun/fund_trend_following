"""执行摘要 — 首页"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results
from website.components.metric_cards import render_summary_cards
from website.components.strategy_badge import render_page_header
from website.components.charts import nav_vs_spy

res  = get_results()
meta = res.meta

render_page_header("执行摘要  Executive Summary", meta)
st.caption(f"{meta.display_name} · {meta.subtitle} · 回测期间 {meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

render_summary_cards(res.metrics, meta.color, meta.backtest_start, meta.backtest_end)

st.markdown("<br>", unsafe_allow_html=True)

st.plotly_chart(
    nav_vs_spy(res.nav, res.spy_nav, meta.color, meta.display_name),
    use_container_width=True,
)

st.markdown("---")
st.subheader("核心发现")

m        = res.metrics
cagr     = m.get("cagr", 0)
max_dd   = m.get("max_drawdown", 0)
win_rate = m.get("win_rate", 0)
avg_win  = m.get("avg_win_r", 0)
avg_loss = m.get("avg_loss_r", 0)
pf       = m.get("profit_factor", 1)

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
**策略行为符合趋势跟踪特征：**
- 胜率仅 {win_rate*100:.1f}%，但平均盈利 {avg_win:+.2f}R > 平均亏损 {avg_loss:.2f}R
- 盈亏比（Profit Factor）= {pf:.4f}，期望值微正
- 平均持仓 {m.get('avg_holding_days',0):.0f} 天，约 {m.get('trades_per_year',0):.0f} 笔/年
""")

with col2:
    st.markdown(f"""
**主要风险与局限：**
- 最大回撤 {max_dd*100:.1f}%，发生于 2008 金融危机期间
- 纯多头策略，熊市缺乏对冲机制
- 标的池为当前 S&P 900 成分股（**含幸存者偏差**）
- 真实表现预计低于回测值 20%–50%
""")

st.markdown("""
<div class="warning-box">
<h4>⚠️ 重要风险声明：幸存者偏差</h4>
当前回测标的池仅包含 <strong>2024 年末仍在 S&P 900 中的公司</strong>，不含历史退市、破产或被摘牌的公司
（如 2008 年的雷曼兄弟、贝尔斯登等）。这是本回测最主要的偏差来源，
<strong>CAGR 可能虚高 20%–50%</strong>。详见「局限性声明」页面。
</div>
""", unsafe_allow_html=True)

st.markdown("---")
st.caption("使用左侧边栏导航至各章节详细内容 →")
