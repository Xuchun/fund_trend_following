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

# ── Load Strategy 1.0 results (shared across all v1 pages) ────────────────────
strategies = list_strategies()
if not strategies:
    st.error("⚠️ 未找到回测结果。请先运行回测脚本生成 results/v1/ 目录。")
    st.stop()

strategy_ids = [m.id for m in strategies]
selected_idx = 0
sel_meta     = strategies[selected_idx]

selected_id = strategy_ids[selected_idx]
cache_key   = f"_results_{selected_id}"
if cache_key not in st.session_state:
    with st.spinner(f"正在加载 {sel_meta.display_name} 数据…"):
        st.session_state[cache_key] = load_strategy(selected_id)
st.session_state["current_results"] = st.session_state[cache_key]

# ── Navigation ────────────────────────────────────────────────────────────────
_pages = Path(__file__).parent / "pages"
_v2    = _pages / "v2"
_fw    = _pages / "future_work"

pg = st.navigation(
    {
        "": [
            st.Page(_pages / "strategy_comparison.py", title="策略对比", icon="⚖️"),
        ],
        "数据与方法论": [
            st.Page(_pages / "universe.py",    title="数据与标的池", icon="🌐"),
            st.Page(_pages / "methodology.py", title="回测方法论",   icon="⚙️"),
        ],
        "策略1.0": [
            st.Page(_pages / "home.py",                title="总结",           icon="📋"),
            st.Page(_pages / "strategy_logic.py",      title="策略描述",       icon="📐"),
            st.Page(_pages / "baseline_results.py",     title="Baseline参数回测结果", icon="📊"),
            st.Page(_pages / "parameter_sensitivity.py", title="参数敏感性分析", icon="🎛️"),
            st.Page(_pages / "parameter_heatmap.py",   title="参数热力图分析", icon="🗺️"),
            st.Page(_pages / "monte_carlo.py",          title="蒙特卡洛模拟",   icon="🎲"),
            st.Page(_pages / "walk_forward.py",         title="Walk-Forward 验证", icon="🔄"),
            st.Page(_pages / "regime_analysis.py",      title="市场环境分析",   icon="🌦️"),
            st.Page(_pages / "limitations.py",          title="局限性声明",     icon="⚠️"),
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
        ],
    },
    position="sidebar",
)
pg.run()
