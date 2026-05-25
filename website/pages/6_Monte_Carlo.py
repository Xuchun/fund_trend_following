import streamlit as st
st.set_page_config(page_title="蒙特卡洛", page_icon="🎲", layout="wide")
from website.shared import setup_sidebar, placeholder
from website.components.strategy_badge import render_page_header

res = setup_sidebar()
render_page_header("蒙特卡洛与风险分析  Monte Carlo & Risk", res.meta)
st.caption("1000条路径模拟，评估策略结果的统计显著性")
st.markdown("---")

st.markdown("""
**本章节将分析以下内容：**
- 1000 条路径的 NAV 分布（Return Bootstrap + Block Bootstrap）
- 5th / 50th / 95th percentile 置信区间带
- 不同置信度下的潜在最大回撤分布
- 连续亏损序列（Drawdown Streak）的概率分布
""")

placeholder("Phase 6 · 蒙特卡洛分析", "蒙特卡洛与风险分析")
