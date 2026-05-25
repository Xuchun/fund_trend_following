"""市场环境分析"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results, placeholder
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta

render_page_header("市场环境分析  Regime Analysis", meta)
st.caption(f"{meta.display_name} · 回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

st.subheader("市场环境分类")
st.markdown(f"""
本章节将分析策略在**不同市场环境**下的表现差异，识别策略的适用条件：

**环境分类维度（待分析）：**

| 市场环境 | 定义 | 回测期间示例 |
|----------|------|------------|
| 强趋势牛市 | SPY 200日均线向上，VIX < 20 | 2013–2014, 2017, 2021 |
| 震荡横盘 | SPY 在200日均线附近波动，VIX 15–25 | 2011, 2015–2016 |
| 熊市下跌 | SPY 低于200日均线，VIX > 30 | 2008–2009, 2020.Q1 |
| 高波动性 | VIX > 30 | 2008, 2020, 2022 |

**关键问题：**
- 策略在哪种环境下盈利最显著？
- 2008 年熊市期间为何损失如此严重？（纯多头）
- 市场环境过滤器（200日均线 / VIX 阈值）能否改善风险收益？（Strategy 2.0 核心改进）
""")

placeholder("Phase 6", "市场环境分析")
