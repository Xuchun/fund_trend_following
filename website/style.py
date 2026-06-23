"""Global style constants and display helpers."""

import pandas as _pd
import streamlit as _st


def show_df(df, use_container_width: bool = True, hide_index: bool = True, **kwargs) -> None:
    """Display a DataFrame as a centered HTML table."""
    if isinstance(df, _pd.io.formats.style.Styler):
        df = df.data
    if not isinstance(df, _pd.DataFrame):
        _st.dataframe(df, use_container_width=use_container_width, hide_index=hide_index, **kwargs)
        return
    html = df.to_html(index=not hide_index, border=0, escape=True)
    _st.markdown(
        f'<div style="overflow-x:auto"><table class="sdf">{html[html.index("<thead>"):]}</div>',
        unsafe_allow_html=True,
    )


SPY_COLOR      = "#aaaaaa"
POSITIVE_COLOR = "#2ca02c"
NEGATIVE_COLOR = "#d62728"

# Fallback color sequence for strategies (overridden by strategy_meta.json)
STRATEGY_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd", "#8c564b"]

GLOBAL_CSS = """
<style>
    /* Metric cards */
    .metric-card {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 16px 20px;
        border-left: 4px solid var(--card-color, #1f77b4);
        margin-bottom: 8px;
    }
    .metric-label {
        font-size: 0.78rem;
        color: #666;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 4px;
    }
    .metric-value {
        font-size: 1.7rem;
        font-weight: 700;
        color: #1a1a1a;
        line-height: 1.1;
    }
    .metric-sub {
        font-size: 0.78rem;
        color: #888;
        margin-top: 3px;
    }
    /* Strategy badge */
    .strategy-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.04em;
        margin-left: 8px;
        vertical-align: middle;
    }
    /* Warning box */
    .warning-box {
        background: #fff3cd;
        border: 1px solid #ffc107;
        border-left: 5px solid #e65100;
        border-radius: 6px;
        padding: 14px 18px;
        margin: 12px 0;
    }
    .warning-box h4 { color: #e65100; margin: 0 0 6px 0; }
    /* Info box */
    .info-box {
        background: #e8f4f8;
        border: 1px solid #90caf9;
        border-left: 5px solid #1565c0;
        border-radius: 6px;
        padding: 14px 18px;
        margin: 12px 0;
    }
    /* Section divider */
    .section-header {
        border-bottom: 2px solid #e0e0e0;
        padding-bottom: 6px;
        margin: 24px 0 16px 0;
        color: #1a1a1a;
    }
    /* Placeholder */
    .placeholder-box {
        background: #f5f5f5;
        border: 2px dashed #ccc;
        border-radius: 8px;
        padding: 40px;
        text-align: center;
        color: #999;
    }
    /* Page title area */
    .page-title-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 4px;
    }
</style>
"""
