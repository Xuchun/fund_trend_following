"""
Shared sidebar setup — called at the top of every page.
Returns the currently selected StrategyResults so each page can render its content.
"""

from __future__ import annotations
import sys
from pathlib import Path

# Make project root importable when running from any working directory
_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
# Also ensure `website` package is importable
_website = _root / "website"
if str(_website.parent) not in sys.path:
    sys.path.insert(0, str(_website.parent))

import streamlit as st
from website.data_loader import list_strategies, load_strategy, StrategyResults
from website.style import GLOBAL_CSS


def setup_sidebar() -> StrategyResults:
    """
    Render strategy selector in sidebar and return loaded results for the
    currently selected strategy. Call this at the top of every page.
    """
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

    strategies = list_strategies()
    if not strategies:
        st.error("⚠️ 未找到回测结果。请先运行回测脚本生成 results/v1/ 目录。")
        st.stop()

    strategy_ids   = [m.id for m in strategies]
    strategy_labels = [f"{m.display_name} — {m.subtitle}" for m in strategies]

    with st.sidebar:
        st.markdown("### 📊 趋势跟踪策略1.0回测")
        st.markdown("---")

        if len(strategies) == 1:
            selected_idx = 0
            st.markdown(
                f'<div style="background:{strategies[0].color};color:white;'
                f'padding:8px 12px;border-radius:6px;font-weight:600;font-size:0.85rem;">'
                f'📌 {strategies[0].display_name}</div>',
                unsafe_allow_html=True,
            )
            st.caption(strategies[0].subtitle)
        else:
            selected_label = st.selectbox(
                "选择策略版本",
                strategy_labels,
                key="strategy_selector",
            )
            selected_idx = strategy_labels.index(selected_label)

        st.markdown("---")
        st.caption(
            f"回测期间：{strategies[selected_idx].backtest_start[:4]}–"
            f"{strategies[selected_idx].backtest_end[:4]}\n\n"
            f"标的：{strategies[selected_idx].universe_stocks} 只股票 + "
            f"{strategies[selected_idx].universe_etfs} 只 ETF"
        )

    selected_id = strategy_ids[selected_idx]

    # Cache per strategy to avoid re-loading on every interaction
    cache_key = f"_results_{selected_id}"
    if cache_key not in st.session_state:
        with st.spinner(f"正在加载 {strategies[selected_idx].display_name} 数据…"):
            st.session_state[cache_key] = load_strategy(selected_id)

    return st.session_state[cache_key]


def get_results() -> "StrategyResults":
    """Return current results from session state. Call at the top of every page."""
    res = st.session_state.get("current_results")
    if res is None:
        st.warning("⚠️ 请从主页进入此页面以加载策略1.0数据。")
        st.stop()
    return res


def placeholder(phase: str, section: str) -> None:
    """Standard placeholder for sections pending Phase 6 analysis."""
    st.markdown(
        f'<div class="placeholder-box">'
        f'<h3 style="color:#bbb;margin:0">⏳ 待填充</h3>'
        f'<p style="color:#aaa;margin:8px 0 0 0">'
        f'本章节（{section}）将在 <strong>{phase}</strong> 完成后自动填充分析数据。</p>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ── Strategy 2.0 helpers ───────────────────────────────────────────────────────

_V2_BADGE_COLOR = "#ff7f0e"

_V2_PRINT_CSS = """
<style>
@media print {
    [data-testid="stSidebar"],
    [data-testid="stSidebarNav"],
    [data-testid="stHeader"],
    [data-testid="stDecoration"],
    [data-testid="stToolbar"],
    [data-testid="stStatusWidget"],
    header, footer,
    .stApp > header { display: none !important; }
    iframe { display: none !important; }
    .main .block-container,
    [data-testid="stMainBlockContainer"] {
        padding-top: 0.5cm !important;
        padding-left: 1cm !important;
        padding-right: 1cm !important;
        max-width: 100% !important;
    }
    @page { margin: 1.5cm; }
    .stPlotlyChart,
    [data-testid="stDataFrame"],
    [data-testid="stAlert"] { page-break-inside: avoid; }
    h2, h3 { page-break-after: avoid; }
}
</style>
"""


def render_v2_page_header(title: str) -> None:
    """Page header for Strategy 2.0 pages (no strategy meta needed yet)."""
    import streamlit.components.v1 as _cv1
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
    st.markdown(_V2_PRINT_CSS, unsafe_allow_html=True)
    col1, col2 = st.columns([4, 2])
    with col1:
        st.title(title)
    with col2:
        _cv1.html(
            '<div style="display:flex;justify-content:flex-end;align-items:center;'
            f'gap:10px;padding-top:20px;">'
            '<button onclick="window.parent.print()" '
            'title="打开打印对话框后选择「存储为 PDF」即可下载" '
            'style="background:#1565c0;color:#fff;border:none;padding:7px 16px;'
            'border-radius:5px;cursor:pointer;font-size:13px;'
            'font-family:sans-serif;white-space:nowrap;">📄 下载 PDF</button>'
            f'<span style="background:{_V2_BADGE_COLOR};color:white;padding:4px 12px;'
            'border-radius:14px;font-size:0.8rem;font-weight:700;'
            'letter-spacing:0.05em;">策略2.0 开发中</span>'
            '</div>',
            height=60,
        )


def placeholder_v2(section: str, description: str = "") -> None:
    """Standard placeholder for v2 sections pending backtesting."""
    desc_html = f"<br><small style='color:#bbb'>{description}</small>" if description else ""
    st.markdown(
        f'<div class="placeholder-box">'
        f'<h3 style="color:#bbb;margin:0">⏳ 策略2.0回测尚未完成</h3>'
        f'<p style="color:#aaa;margin:8px 0 0 0">'
        f'本章节（{section}）将在策略2.0回测完成后填充分析数据。'
        f'{desc_html}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )
