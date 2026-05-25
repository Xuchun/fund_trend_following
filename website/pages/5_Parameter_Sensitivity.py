import streamlit as st
st.set_page_config(page_title="参数敏感性", page_icon="🎛️", layout="wide")
from website.shared import setup_sidebar, placeholder
from website.components.strategy_badge import render_page_header

res = setup_sidebar()
render_page_header("参数敏感性分析  Parameter Sensitivity", res.meta)
st.caption("分析各参数变动对策略表现的影响")
st.markdown("---")

st.markdown("""
**本章节将分析以下内容：**
- 15 个参数的 1D 扰动测试（每次只改变一个参数，其余保持不变）
- 每个参数对 CAGR / Sharpe / Max Drawdown 的影响曲线
- 关键参数对的 2D 热力图（如 `breakout_window × stop_loss_multiplier`）
- 结论：哪些参数最关键？策略对其敏感程度如何？
""")

placeholder("Phase 6 · 参数扰动分析", "参数敏感性分析")
