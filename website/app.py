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
    page_title="趋势跟踪策略1.0回测",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

from website.style import GLOBAL_CSS
from website.data_loader import list_strategies, load_strategy

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ── Load available strategies ─────────────────────────────────────────────────
strategies = list_strategies()
if not strategies:
    st.error("⚠️ 未找到回测结果。请先运行回测脚本生成 results/v1/ 目录。")
    st.stop()

strategy_ids    = [m.id for m in strategies]
strategy_labels = [f"{m.display_name} — {m.subtitle}" for m in strategies]

# ── Sidebar: strategy selector ────────────────────────────────────────────────
if len(strategies) == 1:
    selected_idx = 0
else:
    with st.sidebar:
        selected_label = st.selectbox("选择策略版本", strategy_labels, key="strategy_selector")
        selected_idx   = strategy_labels.index(selected_label)

sel_meta = strategies[selected_idx]

# ── Cache strategy data in session state ──────────────────────────────────────
selected_id = strategy_ids[selected_idx]
cache_key   = f"_results_{selected_id}"
if cache_key not in st.session_state:
    with st.spinner(f"正在加载 {sel_meta.display_name} 数据…"):
        st.session_state[cache_key] = load_strategy(selected_id)
st.session_state["current_results"] = st.session_state[cache_key]

# ── Navigation ────────────────────────────────────────────────────────────────
_pages = Path(__file__).parent / "pages"

pg = st.navigation(
    {
        "": [
            st.Page(_pages / "home.py",          title="总结",           icon="📋"),
        ],
        "策略信息": [
            st.Page(_pages / "strategy_logic.py", title="策略逻辑",       icon="📐"),
            st.Page(_pages / "universe.py",        title="数据与标的池",   icon="🌐"),
            st.Page(_pages / "methodology.py",     title="回测方法论",     icon="⚙️"),
        ],
        "回测结果": [
            st.Page(_pages / "baseline_results.py",      title="Baseline参数回测结果", icon="📊"),
            st.Page(_pages / "parameter_sensitivity.py", title="参数敏感性分析", icon="🎛️"),
            st.Page(_pages / "parameter_heatmap.py",    title="参数热力图分析", icon="🗺️"),
            st.Page(_pages / "monte_carlo.py",           title="蒙特卡洛模拟",   icon="🎲"),
            st.Page(_pages / "walk_forward.py",          title="Walk-Forward 验证", icon="🔄"),
            st.Page(_pages / "regime_analysis.py",       title="市场环境分析",   icon="🌦️"),
        ],
        "评估与建议": [
            st.Page(_pages / "limitations.py",     title="局限性声明",     icon="⚠️"),
        ],
    },
    position="sidebar",
)
pg.run()
