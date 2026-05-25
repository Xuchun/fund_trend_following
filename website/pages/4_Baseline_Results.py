import streamlit as st
st.set_page_config(page_title="基准回测结果", page_icon="📊", layout="wide")

from website.shared import setup_sidebar
from website.components.strategy_badge import render_page_header
from website.components.metric_cards import render_full_metrics_table
from website.components.charts import (
    nav_vs_spy, drawdown_chart, rolling_sharpe_chart,
    r_multiple_distribution, annual_returns_chart,
)

res  = setup_sidebar()
meta = res.meta
m    = res.metrics

render_page_header("基准回测结果  Baseline Results", meta)
st.caption(f"{meta.display_name} · {meta.backtest_start} → {meta.backtest_end} · 初始资本 ${meta.initial_capital:,.0f}")
st.markdown("---")

# ── 1. NAV vs SPY ────────────────────────────────────────────────────────────
st.plotly_chart(
    nav_vs_spy(res.nav, res.spy_nav, meta.color, meta.display_name),
    use_container_width=True,
)

# ── 2. Drawdown + Rolling Sharpe side by side ───────────────────────────────
col1, col2 = st.columns([1, 1])
with col1:
    st.plotly_chart(
        drawdown_chart(res.nav, meta.color),
        use_container_width=True,
    )
with col2:
    st.plotly_chart(
        rolling_sharpe_chart(res.returns, res.spy_nav, meta.color, meta.display_name),
        use_container_width=True,
    )

# ── 3. Annual returns + R-multiple distribution ──────────────────────────────
col3, col4 = st.columns([1, 1])
with col3:
    st.plotly_chart(
        annual_returns_chart(res.nav, res.spy_nav, meta.color, meta.display_name),
        use_container_width=True,
    )
with col4:
    st.plotly_chart(
        r_multiple_distribution(res.trades),
        use_container_width=True,
    )

st.markdown("---")

# ── 4. Full metrics table ────────────────────────────────────────────────────
st.subheader("完整指标汇总")
render_full_metrics_table(m, m)   # pass m twice; spy fields extracted inside

# ── 5. Trade exit breakdown ──────────────────────────────────────────────────
st.markdown("---")
st.subheader("平仓原因分布")
if "exit_reason" in res.trades.columns:
    exit_counts = res.trades["exit_reason"].value_counts()
    total = len(res.trades)
    col1, col2, col3 = st.columns(3)
    labels = {
        "trailing_stop":    ("追踪止损", col1, "#ff7f0e"),
        "stop_loss":        ("固定止损", col2, "#d62728"),
        "end_of_backtest":  ("回测结束", col3, "#aaaaaa"),
    }
    for reason, (label, col, c) in labels.items():
        n = exit_counts.get(reason, 0)
        with col:
            st.markdown(f"""
<div style="text-align:center;border:2px solid {c};border-radius:8px;padding:14px;">
<div style="font-size:1.8rem;font-weight:700;color:{c}">{n:,}</div>
<div style="font-size:0.85rem;font-weight:600">{label}</div>
<div style="font-size:0.8rem;color:#888">{n/total*100:.1f}%</div>
</div>""", unsafe_allow_html=True)

# ── 6. Sanity check note ─────────────────────────────────────────────────────
sanity_path = meta.results_dir / "sanity.txt"
if sanity_path.exists():
    sanity = sanity_path.read_text().strip()
    st.markdown("---")
    st.subheader("运行时 Sanity Check")
    if sanity.startswith("✓"):
        st.success(sanity)
    else:
        st.warning(sanity)
