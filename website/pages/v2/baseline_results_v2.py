"""策略2.0 — Baseline参数回测结果（待完成）"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import render_v2_page_header, placeholder_v2

render_v2_page_header("Baseline 参数回测结果")
st.caption("策略2.0 · 横盘收敛 + 箱体突破趋势跟踪")
st.markdown("---")

placeholder_v2(
    "Baseline参数回测结果",
    "将展示策略2.0 Baseline参数下的核心绩效指标、净值曲线、年度收益、交易统计等。"
    "Baseline 参数：突破窗口 N=100，横盘回望 80 日，收敛阈值 25%，移动止盈 20 日 2×ATR。",
)

st.markdown("---")
st.markdown("""
**本页面将包含（回测完成后）：**

1. **核心绩效指标**：CAGR、Sharpe、Max DD、Calmar、Win Rate、Avg Win/Loss、Profit Factor
2. **净值曲线**：策略2.0 vs SPY vs 策略1.0（三者对比）
3. **逐年收益分析**：柱状图，标注牛熊市背景
4. **交易统计**：笔数、平均持仓天数、换手率、市场暴露率
5. **PnL 分布**：收益分布直方图，关注右尾长度
6. **策略2.0 vs 策略1.0**：各核心指标的直接对比
""")
