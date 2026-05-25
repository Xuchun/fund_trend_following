"""Strategy version badge — appears on every page's top-right."""

from __future__ import annotations
import streamlit as st
from website.data_loader import StrategyMeta


def render_page_header(title: str, meta: StrategyMeta) -> None:
    """Render page title with strategy badge on the right."""
    col1, col2 = st.columns([5, 1])
    with col1:
        st.title(title)
    with col2:
        st.markdown(
            f'<div style="text-align:right; padding-top:28px;">'
            f'<span style="background:{meta.color}; color:white; '
            f'padding:4px 12px; border-radius:14px; font-size:0.8rem; '
            f'font-weight:700; letter-spacing:0.05em;">'
            f'{meta.badge_text}</span></div>',
            unsafe_allow_html=True,
        )
