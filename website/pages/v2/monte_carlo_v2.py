"""策略2.0 — 蒙特卡洛模拟（待完成）"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import render_v2_page_header, placeholder_v2

render_v2_page_header("蒙特卡洛模拟")
st.caption("策略2.0 · 横盘收敛 + 箱体突破趋势跟踪")
st.markdown("---")

placeholder_v2(
    "蒙特卡洛模拟",
    "将对策略2.0的交易序列做1000条随机重排模拟，评估正期望的统计确定性和最大回撤分布。",
)

st.markdown("---")
st.markdown("""
**本页面将包含（回测完成后）：**

1. **1000 条净值路径分布**：p5 / p50 / p95 通道，与策略1.0结果对比
2. **CAGR 分布**：直方图，标注负收益概率
3. **最大回撤分布**：p50 / p95，评估尾部风险
4. **最长水下期分布**：考察流动性要求
5. **结论**：正期望的统计置信度是否优于策略1.0
""")
