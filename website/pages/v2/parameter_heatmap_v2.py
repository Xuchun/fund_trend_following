"""策略2.0 — 参数热力图分析（待完成）"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import render_v2_page_header, placeholder_v2

render_v2_page_header("参数热力图分析")
st.markdown("策略2.0 · 横盘收敛 + 箱体突破趋势跟踪")
st.markdown("---")

placeholder_v2(
    "参数热力图分析",
    "将展示参数两两组合的Sharpe/CAGR/MaxDD热力图，识别最优参数区间与过拟合风险区。",
)

st.markdown("---")
st.markdown("""
**本页面将包含（回测完成后）：**

1. **突破窗口 N × 横盘收敛阈值** 二维热力图（Sharpe）
2. **横盘收敛阈值 × 移动止盈窗口** 二维热力图（Sharpe）
3. **移动止盈窗口 × ATR 倍数** 二维热力图（MaxDD）
4. 最优参数区间的稳定性分析
5. 与 Baseline 参数的相对表现
""")
