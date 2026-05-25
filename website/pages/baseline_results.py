"""基准回测结果"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results
from website.components.strategy_badge import render_page_header
from website.components.metric_cards import render_summary_cards, render_full_metrics_table
from website.components.charts import (
    nav_vs_spy, drawdown_chart, rolling_sharpe_chart,
    r_multiple_distribution, annual_returns_chart,
    trades_per_year_chart, holding_days_distribution,
)

res  = get_results()
meta = res.meta
m    = res.metrics

render_page_header("基准回测结果  Baseline Results", meta)
st.caption(f"回测期间：{meta.backtest_start} → {meta.backtest_end}  ·  初始资金：$10,000,000")
st.markdown("---")

# ── Summary cards ─────────────────────────────────────────────────────────────
render_summary_cards(m, meta.color, meta.backtest_start, meta.backtest_end)

st.markdown("<br>", unsafe_allow_html=True)

# ── Context note for poor CAGR ────────────────────────────────────────────────
cagr = m.get("cagr", 0)
if cagr < 0.05:
    st.markdown("""
<div class="warning-box">
<h4>⚠️ 关于低 CAGR 的说明</h4>
Strategy 1.0 在 2004–2024 全期的 CAGR 仅为 0.3%，主因是 2008 年金融危机期间
<strong>纯多头策略遭受 -54% 的最大回撤</strong>，导致长达 12 年的资金恢复期。
2010–2024 子区间 CAGR 约 6%，说明策略本身在无极端熊市时仍有效。
<strong>Strategy 2.0 将引入市场环境过滤器（Market Regime Filter）以应对此问题。</strong>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── NAV chart ─────────────────────────────────────────────────────────────────
st.subheader("净值曲线 vs SPY")
st.plotly_chart(nav_vs_spy(res.nav, res.spy_nav, meta.color, meta.display_name),
                use_container_width=True)

# ── Drawdown chart ────────────────────────────────────────────────────────────
st.subheader("回撤曲线")
st.plotly_chart(drawdown_chart(res.nav, meta.color), use_container_width=True)

st.markdown("---")

# ── Annual returns + Rolling Sharpe side by side ──────────────────────────────
col1, col2 = st.columns(2)
with col1:
    st.subheader("逐年回报对比")
    st.plotly_chart(annual_returns_chart(res.nav, res.spy_nav, meta.color, meta.display_name),
                    use_container_width=True)
with col2:
    st.subheader("滚动 Sharpe 比率")
    st.plotly_chart(rolling_sharpe_chart(res.returns, res.spy_nav, meta.color, meta.display_name),
                    use_container_width=True)

st.markdown("---")

# ── R-multiple distribution ───────────────────────────────────────────────────
st.subheader("交易盈亏分布（R 倍数）")
st.plotly_chart(r_multiple_distribution(res.trades), use_container_width=True)

win_rate = m.get("win_rate", 0)
avg_win  = m.get("avg_win_r", 0)
avg_loss = m.get("avg_loss_r", 0)
pf       = m.get("profit_factor", 1)
st.markdown(f"""
**解读：** 胜率 {win_rate*100:.1f}% 看似低，但这是趋势跟踪策略的**正常特征**。
关键在于平均盈利（{avg_win:+.2f}R）远大于平均亏损（{avg_loss:.2f}R），
盈亏比 {pf:.4f} > 1，期望值为正。右侧长尾（大盈利交易）是策略盈利的核心来源。
""")

st.markdown("---")

# ── Full metrics table ────────────────────────────────────────────────────────
st.subheader("完整指标对比表")
render_full_metrics_table(m, m)

st.markdown("---")

# ── Trade summary ─────────────────────────────────────────────────────────────
st.subheader("交易样本")
n_show = st.slider("显示交易笔数", 10, 100, 20, 10)
trades_display = res.trades.sort_values("exit_date", ascending=False).head(n_show).copy()
if "pnl_r_multiple" in trades_display.columns:
    trades_display = trades_display[[
        "ticker", "entry_date", "exit_date", "entry_price", "exit_price",
        "shares", "pnl_r_multiple",
    ]].rename(columns={
        "ticker": "标的",
        "entry_date": "入场日",
        "exit_date": "出场日",
        "entry_price": "入场价",
        "exit_price": "出场价",
        "shares": "股数",
        "pnl_r_multiple": "R 倍数",
    })
st.dataframe(trades_display, use_container_width=True, hide_index=True)
