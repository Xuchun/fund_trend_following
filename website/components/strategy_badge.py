"""Strategy version badge — appears on every page's top-right."""

from __future__ import annotations
import streamlit as st
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
        st.html("""
        <div style="display:flex;justify-content:flex-end;align-items:center;
                    gap:10px;padding-top:10px;">
            <button id="badge-pdf-btn"
                title="打开打印对话框后选择「存储为 PDF」即可下载"
                style="background:#1565c0;color:#fff;border:none;padding:7px 16px;
                       border-radius:5px;cursor:pointer;font-size:13px;
                       font-family:sans-serif;white-space:nowrap;">
                📄 下载 PDF
            </button>
        </div>
        <script>
        (function() {
            var btn = document.getElementById('badge-pdf-btn');
            if (btn) btn.onclick = function() { window.print(); };
        })();
        </script>
        """, unsafe_allow_javascript=True)
