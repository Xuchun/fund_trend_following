"""参数敏感性分析"""

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

render_page_header("参数敏感性分析  Parameter Sensitivity", meta)
st.caption(f"{meta.display_name} · 回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

st.subheader("待分析参数")
st.markdown("""
本章节将对以下关键参数进行网格搜索（Grid Search）敏感性分析，
评估策略对参数选择的鲁棒性：

| 参数 | 基准值 | 测试范围 | 分析目的 |
|------|--------|----------|---------|
| 突破窗口（N） | 100 日 | 50 / 75 / 100 / 150 / 200 | 动量周期敏感性 |
| ATR 乘数（止损） | 2.0× | 1.5 / 2.0 / 2.5 / 3.0 | 止损松紧对 Sharpe 的影响 |
| 每笔风险比例 | 1.0% | 0.5% / 1.0% / 1.5% / 2.0% | 仓位大小对 MaxDD 的影响 |
| 热度上限 | 10% | 5% / 10% / 15% / 20% | 组合集中度影响 |
| 相关性阈值 | 0.70 | 0.50 / 0.60 / 0.70 / 0.80 | 分散化效果 |

分析结果将以热力图（Heatmap）形式展示参数对 CAGR / Sharpe / MaxDD 的影响。
""")

placeholder("Phase 6", "参数敏感性分析")
