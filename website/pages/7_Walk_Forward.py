import streamlit as st
st.set_page_config(page_title="Walk-Forward", page_icon="🔄", layout="wide")
from website.shared import setup_sidebar, placeholder
from website.components.strategy_badge import render_page_header

res = setup_sidebar()
render_page_header("Walk-Forward 验证  Out-of-Sample Validation", res.meta)
st.caption("样本内训练 → 样本外验证，检验策略泛化能力")
st.markdown("---")

st.markdown("""
**本章节将分析以下内容（4个扩展窗口，IS 均从 2004 年开始）：**

| 窗口 | IS 区间 | OOS 区间 |
|---|---|---|
| Window 1 | 2004–2021 | 2022 |
| Window 2 | 2004–2022 | 2023 |
| Window 3 | 2004–2023 | 2024 |
| Window 4 | 2004–2024 | 2025（未来） |

**核心问题**：IS 和 OOS 的 CAGR / Sharpe / MaxDD 是否存在显著衰减？衰减程度是否在可接受范围内？
""")

placeholder("Phase 6 · Walk-Forward 分析", "Walk-Forward Out-of-Sample 验证")
