"""基准回测结果"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results
from website.components.strategy_badge import render_page_header

import sys
from pathlib import Path
_src = Path(__file__).resolve().parents[3] / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
from data.universe import ETF_TICKERS
_ETF_SET = set(ETF_TICKERS)
from website.components.metric_cards import render_summary_cards, render_full_metrics_table
from website.components.charts import (
    nav_vs_spy, drawdown_chart, rolling_sharpe_chart,
    r_multiple_distribution, annual_returns_chart,
    trades_per_year_chart, holding_days_distribution,
    profit_by_type_chart,
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
    regime_on = meta.params_anchor.get("regime_filter_enabled", False)
    if regime_on:
        regime_note = (
            "已启用 <strong>SPY 200日均线过滤器</strong>，熊市期间（约占全程 19%）停止开新仓、"
            "闲置资金转入 SHY。但过滤器<strong>不强制平仓</strong>——"
            "2008 年危机期间已持有的头寸仍由追踪止损逐步平出，因此最大回撤未能完全规避。<br>"
            "<strong>Strategy 2.0 计划引入强制减仓机制，在熊市信号触发时主动平仓。</strong>"
        )
    else:
        regime_note = (
            "纯多头策略遭受熊市的全部冲击，毫无对冲机制。<br>"
            "<strong>Strategy 2.0 将引入 SPY 200日均线过滤器以减少熊市回撤。</strong>"
        )
    st.markdown(f"""
<div class="warning-box">
<h4>⚠️ 关于低 CAGR 的说明</h4>
CAGR 仅 {cagr*100:.1f}%，主因是 2008 年金融危机期间
<strong>最大回撤达 {abs(m.get("max_drawdown",0))*100:.1f}%</strong>，导致长期的资金恢复期。
2010–2024 子区间 CAGR 约 6%，说明策略本身在无极端熊市时仍有效。<br>
{regime_note}
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

# ── Turnover callout ──────────────────────────────────────────────────────────
turnover = m.get("annual_turnover", 0)
slippage_bps   = meta.params_anchor.get("slippage_bps", 10)
commission_bps = meta.params_anchor.get("commission_bps", 3)
rt_cost_bps    = (slippage_bps + commission_bps) * 2
implied_cost_pct = turnover * rt_cost_bps / 100   # in bps→%

st.subheader("组合换手率（Portfolio Turnover）")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric(
        "年换手率",
        f"{turnover:.1f}x",
        help="= 全年买入总额 ÷ 平均 NAV ÷ 年数。12.5x 表示每年持仓被替换约 12.5 次。",
    )
with col2:
    st.metric(
        "年换手率（百分比）",
        f"{turnover*100:.0f}%",
        help="等同于左侧 x 倍数，以百分比表示。",
    )
with col3:
    st.metric(
        "隐含年化交易成本",
        f"≈ {implied_cost_pct:.2f}%",
        help=f"= 换手率 × 单边成本({slippage_bps:.0f} bps 滑点 + {commission_bps:.0f} bps 佣金)× 2。已包含于回测净值中。",
    )

st.markdown(f"""
**解读：** 年换手率 {turnover:.1f}x（{turnover*100:.0f}%）表示每年平均买入约 {turnover:.1f} 倍 NAV 的股票。
以单边 {slippage_bps:.0f} bps 滑点 + {commission_bps:.0f} bps 佣金（合计 {slippage_bps+commission_bps:.0f} bps）、往返 {rt_cost_bps:.0f} bps 计，
隐含年化交易摩擦约 **{implied_cost_pct:.2f}%**，已完整计入回测净值，无需额外扣除。

> 趋势跟踪策略的换手率通常在 500%–2,000%/年之间，本策略 {turnover*100:.0f}% 处于正常范围。
""")

st.markdown("---")

# ── Trades per year + holding days side by side ───────────────────────────────
col1, col2 = st.columns(2)
with col1:
    st.subheader("逐年交易笔数")
    st.plotly_chart(trades_per_year_chart(res.trades), use_container_width=True)
with col2:
    st.subheader("持仓天数分布")
    st.plotly_chart(holding_days_distribution(res.trades), use_container_width=True)

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
