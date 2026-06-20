"""策略2.0 — 参数敏感性分析（待完成）"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import render_v2_page_header, placeholder_v2

render_v2_page_header("参数敏感性分析")
st.caption("策略2.0 · 横盘收敛 + 箱体突破趋势跟踪")
st.markdown("---")

placeholder_v2(
    "参数敏感性分析",
    "将对5个核心参数逐一进行单参数扰动测试，验证策略2.0的鲁棒性。",
)

st.markdown("---")
st.markdown("""
**待测试的5个参数：**

| 参数 | Baseline 值 | 测试值 |
|------|------------|--------|
| 突破回望窗口 N | 100 | 80 / 100 / 120 |
| 横盘收敛回望窗口 | 80 日 | 60 / 80 / 100 日 |
| 横盘收敛宽度阈值 | 25% | 20% / 25% / 30% |
| 移动止盈回望窗口 | 20 日 | 20 / 30 / 50 日 |
| ATR 倍数 | 2× | 2× / 3× |

**本页面将包含（回测完成后）：**

1. 每个参数的扰动测试曲线（CAGR / Sharpe / MaxDD vs 参数值）
2. 参数鲁棒性评分（Sharpe 变异系数 CV）
3. 与策略1.0的参数稳定性对比
""")
