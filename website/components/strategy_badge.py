"""Strategy version badge — appears on every page's top-right."""

from __future__ import annotations
import streamlit as st
import streamlit.components.v1 as _cv1
from website.data_loader import StrategyMeta

_PRINT_CSS = """
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


def render_page_header(title: str, meta: StrategyMeta) -> None:
    """Render page title with PDF download button and strategy badge."""
    st.markdown(_PRINT_CSS, unsafe_allow_html=True)
    col1, col2 = st.columns([4, 2])
    with col1:
        st.title(title)
    with col2:
        _cv1.html(
            f'<div style="display:flex;justify-content:flex-end;align-items:center;'
            f'gap:10px;padding-top:20px;">'
            f'<button onclick="window.parent.print()"'
            f' title="打开打印对话框后选择「存储为 PDF」即可下载"'
            f' style="background:#1565c0;color:#fff;border:none;padding:7px 16px;'
            f'border-radius:5px;cursor:pointer;font-size:13px;'
            f'font-family:sans-serif;white-space:nowrap;">📄 下载 PDF</button>'
            f'</div>',
            height=60,
        )
