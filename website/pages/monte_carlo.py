"""蒙特卡洛风险分析"""

from __future__ import annotations

import json
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

render_page_header("蒙特卡洛风险  Monte Carlo Risk", meta)
st.caption(f"{meta.display_name} · 回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

st.subheader("分析目标")
st.markdown(f"""
蒙特卡洛模拟将通过**随机重采样历史交易序列**（Bootstrap Resampling），
评估策略在不同市场路径下的表现分布：

**模拟方法：**
- 对 {res.metrics.get('n_trades', 0):,} 笔历史交易进行有放回抽样
- 生成 1,000 条模拟净值路径
- 分析 CAGR、MaxDD、Sharpe 的 5th/25th/50th/75th/95th 百分位分布

**关键输出（待生成）：**
1. 净值路径扇形图（1,000 条路径 + 置信区间）
2. CAGR 分布直方图（最差 5% 情境）
3. 最大回撤分布（99% VAR）
4. 破产概率（NAV < 50% 初始资金的概率）
""")

placeholder("Phase 6", "蒙特卡洛风险分析")
