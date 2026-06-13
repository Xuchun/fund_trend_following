"""策略2.0 — Walk-Forward 验证（待完成）"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import render_v2_page_header, placeholder_v2

render_v2_page_header("Walk-Forward 验证")
st.caption("策略2.0 · 横盘收敛 + 箱体突破趋势跟踪")
st.markdown("---")

placeholder_v2(
    "Walk-Forward 验证",
    "将通过滚动窗口的样本外验证，检验策略2.0是否存在过拟合，评估 IS→OOS 的 Sharpe 衰减。",
)

st.markdown("---")
st.markdown("""
**本页面将包含（回测完成后）：**

1. **Walk-Forward 窗口设计**：IS/OOS 窗口划分，5 个 OOS 窗口
2. **OOS 拼接净值曲线**：将 5 个 OOS 期间的真实表现拼接成完整曲线
3. **逐窗口指标**：每个 OOS 窗口的 CAGR / Sharpe / MaxDD
4. **IS vs OOS 衰减**：Sharpe 衰减幅度与策略1.0对比
5. **结论**：策略2.0是否具备真实的样本外预测能力
""")
