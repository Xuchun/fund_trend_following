"""
Trend-Following Strategy Backtest Website — entry point.
Run: streamlit run website/app.py
"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st

st.set_page_config(
    page_title="趋势跟踪策略回测",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

from website.style import GLOBAL_CSS
from website.data_loader import list_strategies, load_strategy

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ── Navigation (defined first so pg.run() always executes) ───────────────────
_pages = Path(__file__).parent / "pages"
_v2    = _pages / "v2"
_fw    = _pages / "future_work"
_pt    = _pages / "paper_trading"

pg = st.navigation(
    {
        "数据与方法论": [
            st.Page(_pages / "universe_tiingo.py", title="数据与标的池", icon="🗄️"),
            st.Page(_pages / "methodology.py",     title="回测方法论",            icon="⚙️"),
        ],
        "策略1.0": [
            st.Page(_pages / "strategy_logic.py",             title="策略描述",             icon="📐"),
            st.Page(_pages / "baseline_results_tiingo_2000.py", title="Baseline参数回测结果", icon="📊"),
            st.Page(_pages / "parameter_sensitivity_tiingo.py", title="参数敏感性分析",     icon="🎛️"),
            st.Page(_pages / "parameter_heatmap.py",          title="参数热力图分析",       icon="🗺️"),
            st.Page(_pages / "monte_carlo.py",                title="蒙特卡洛模拟",         icon="🎲"),
            st.Page(_pages / "walk_forward.py",               title="Walk-Forward 验证",    icon="🔄"),
            st.Page(_pages / "regime_analysis.py",            title="市场环境分析",         icon="🌦️"),
            st.Page(_pages / "limitations.py",                title="局限性声明",           icon="⚠️"),
            st.Page(_pages / "home.py",                       title="总结",     icon="📋"),
        ],
        "策略1.0模拟交易（开发中）": [
            st.Page(_pt / "paper_trading_monitor.py", title="策略1.0模拟交易监控", icon="📡"),
        ],
        "策略1.0改进方案（开发中）": [
            st.Page(_fw / "improve_strategy.py",          title="如何改进策略1.0",         icon="🔧"),
            st.Page(_fw / "improve_effectiveness.py",     title="如何改进策略有效性",      icon="📈"),
            st.Page(_fw / "better_signal_selection.py",   title="如何选中更优开仓信号",    icon="🎯"),
            st.Page(_fw / "improve_cagr.py",              title="如何提高年化收益",        icon="🚀"),
            st.Page(_fw / "reduce_large_losses.py",       title="如何减少大R的亏损交易",  icon="🛡️"),
            st.Page(_fw / "reduce_consecutive_losses.py", title="如何降低连续亏损次数",    icon="📉"),
            st.Page(_fw / "breakeven_drawdown.py",        title="如何用平价保护改善最大回撤", icon="🛡️"),
            st.Page(_fw / "reduce_max_drawdown.py",       title="如何降低最大回撤",        icon="📉"),
            st.Page(_fw / "improve_universe.py",          title="如何改进数据与标的池",    icon="🔬"),
            st.Page(_fw / "improve_methodology.py",      title="如何改进回测方法论",       icon="🧪"),
            st.Page(_fw / "holding_days_advice.py",       title="有关持仓天数的建议",      icon="📅"),
            st.Page(_fw / "reduce_deep_drawdown.py",      title="如何减少深度回撤幅度",    icon="🔻"),
            st.Page(_fw / "improve_capital_utilization.py", title="如何提高熊市资金使用率", icon="📈"),
            st.Page(_fw / "second_data_source.py",         title="是否购买第二家数据源",   icon="🗄️"),
        ],
        "策略2.0（开发中）": [
            st.Page(_v2 / "strategy_logic_v2.py",        title="策略描述",       icon="📐"),
            st.Page(_v2 / "baseline_results_v2.py",      title="Baseline参数回测结果", icon="📊"),
            st.Page(_v2 / "parameter_sensitivity_v2.py", title="参数敏感性分析", icon="🎛️"),
            st.Page(_v2 / "parameter_heatmap_v2.py",    title="参数热力图分析", icon="🗺️"),
            st.Page(_v2 / "monte_carlo_v2.py",           title="蒙特卡洛模拟",   icon="🎲"),
            st.Page(_v2 / "walk_forward_v2.py",          title="Walk-Forward 验证", icon="🔄"),
            st.Page(_v2 / "regime_analysis_v2.py",       title="市场环境分析",   icon="🌦️"),
            st.Page(_v2 / "limitations_v2.py",           title="局限性声明",     icon="⚠️"),
            st.Page(_pages / "strategy_comparison.py",    title="策略对比（1.0 vs 2.0）", icon="⚖️"),
        ],
        "Future Work": [
            st.Page(_fw / "multi_strategy_plan.py",              title="多策略开发 Plan",  icon="🚀"),
            st.Page(_fw / "pyramiding.py",                        title="加仓机制（金字塔）", icon="📐"),
        ],
    },
    position="sidebar",
)
pg.run()
