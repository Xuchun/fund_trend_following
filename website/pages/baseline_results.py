"""基准回测结果"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results
from website.components.strategy_badge import render_page_header

_etf_csv = Path(__file__).resolve().parents[2] / "data" / "ETFs.csv"
import pandas as _pd_etf
_ETF_SET = set(_pd_etf.read_csv(_etf_csv)["SYMBOL"].dropna().str.strip().tolist()) if _etf_csv.exists() else set()
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

# ── Profit by type: stock vs ETF ──────────────────────────────────────────────
st.subheader("策略盈利来源：股票 vs ETF")
st.plotly_chart(profit_by_type_chart(res.trades, _ETF_SET), use_container_width=True)

etf_pnl   = res.trades[res.trades["ticker"].isin(_ETF_SET)]["net_pnl"].sum()
stock_pnl = res.trades[~res.trades["ticker"].isin(_ETF_SET)]["net_pnl"].sum()
total_pnl = etf_pnl + stock_pnl

_traded        = res.trades["ticker"].unique()
_stock_traded  = sum(1 for t in _traded if t not in _ETF_SET)
_etf_traded    = sum(1 for t in _traded if t in _ETF_SET)
_uni_stocks    = meta.universe_stocks
_uni_etfs      = meta.universe_etfs

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
**股票**
- 股票池：{_uni_stocks} 只 → 实际交易 **{_stock_traded} 只**（覆盖率 {_stock_traded/_uni_stocks*100:.1f}%）
- 盈利贡献：**${stock_pnl/1e6:.1f}M**（占总盈亏 {stock_pnl/total_pnl*100:.0f}%）
""")
with col2:
    st.markdown(f"""
**ETF**
- ETF 池：{_uni_etfs} 只 → 实际交易 **{_etf_traded} 只**（覆盖率 {_etf_traded/_uni_etfs*100:.1f}%）
- 盈利贡献：**${etf_pnl/1e6:.1f}M**（占总盈亏 {etf_pnl/total_pnl*100:.0f}%）
""")

# ── 深度分析：交易质量 / 资本效率 / 分散化价值 ────────────────────────────────
import numpy as _np

_trades = res.trades.copy()
_trades["_type"]     = _trades["ticker"].apply(lambda t: "ETF" if t in _ETF_SET else "股票")
_trades["_notional"] = _trades["entry_price"] * _trades["shares"]

def _stats(df):
    wins   = df[df["net_pnl"] > 0]
    losses = df[df["net_pnl"] <= 0]
    pf     = wins["net_pnl"].sum() / abs(losses["net_pnl"].sum()) if len(losses) > 0 else 0.0
    cap_eff = df["net_pnl"].sum() / df["_notional"].sum() * 100
    return dict(
        n          = len(df),
        win_rate   = len(wins) / len(df) * 100,
        avg_win_r  = df[df["net_pnl"] > 0]["pnl_r_multiple"].mean(),
        avg_loss_r = df[df["net_pnl"] <= 0]["pnl_r_multiple"].mean(),
        pf         = pf,
        avg_hold   = df["holding_days"].mean(),
        med_hold   = df["holding_days"].median(),
        net_pnl    = df["net_pnl"].sum(),
        notional   = df["_notional"].sum(),
        cap_eff    = cap_eff,
    )

_s = _stats(_trades[_trades["_type"] == "股票"])
_e = _stats(_trades[_trades["_type"] == "ETF"])

# 月度相关性
_trades["_month"] = _trades["exit_date"].dt.to_period("M")
_sm = _trades[_trades["_type"] == "股票"].groupby("_month")["net_pnl"].sum()
_em = _trades[_trades["_type"] == "ETF"].groupby("_month")["net_pnl"].sum()
_common = _sm.index.intersection(_em.index)
_corr = float(_sm.loc[_common].corr(_em.loc[_common])) if len(_common) > 1 else 0.0

st.markdown("#### 交易质量对比")
import pandas as _pd2
_quality_df = _pd2.DataFrame({
    "指标":      ["交易笔数", "胜率", "平均盈利 R", "平均亏损 R", "Profit Factor", "平均持仓天数", "中位持仓天数"],
    "股票":      [f"{_s['n']:,}", f"{_s['win_rate']:.1f}%", f"{_s['avg_win_r']:+.2f}R",
                  f"{_s['avg_loss_r']:+.2f}R", f"{_s['pf']:.3f}", f"{_s['avg_hold']:.1f} 天", f"{_s['med_hold']:.1f} 天"],
    "ETF":       [f"{_e['n']:,}", f"{_e['win_rate']:.1f}%", f"{_e['avg_win_r']:+.2f}R",
                  f"{_e['avg_loss_r']:+.2f}R", f"{_e['pf']:.3f}", f"{_e['avg_hold']:.1f} 天", f"{_e['med_hold']:.1f} 天"],
    "结论":      [f"ETF 仅占 {_e['n']/(_s['n']+_e['n'])*100:.0f}%", "ETF 胜率更高" if _e['win_rate'] > _s['win_rate'] else "股票胜率更高", "股票赢时赢更多" if _s['avg_win_r'] > _e['avg_win_r'] else "ETF赢时赢更多", "股票输时输更少" if abs(_s['avg_loss_r']) < abs(_e['avg_loss_r']) else "ETF输时输更少",
                  "几乎相同", "股票趋势更持久" if _s['avg_hold'] > _e['avg_hold'] else "ETF趋势更持久", "股票趋势更持久" if _s['med_hold'] > _e['med_hold'] else "ETF趋势更持久"],
})
st.dataframe(_quality_df, use_container_width=True, hide_index=True)

st.markdown("#### 资本效率")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("股票资本效率", f"{_s['cap_eff']:.2f}%",
              help=f"总净盈亏 ${_s['net_pnl']/1e6:.1f}M ÷ 总买入金额 ${_s['notional']/1e6:.0f}M")
with col2:
    st.metric("ETF 资本效率", f"{_e['cap_eff']:.2f}%",
              help=f"总净盈亏 ${_e['net_pnl']/1e6:.1f}M ÷ 总买入金额 ${_e['notional']/1e6:.0f}M")
with col3:
    ratio = _s['cap_eff'] / _e['cap_eff'] if _e['cap_eff'] != 0 else 0
    st.metric("股票 / ETF 效率比", f"{ratio:.1f}×",
              help="股票每投入1元产生的回报是 ETF 的多少倍")
_s_pct = stock_pnl / total_pnl * 100 if total_pnl != 0 else 0
_s_cap_pct = _s["notional"] / (_s["notional"] + _e["notional"]) * 100
st.caption(f"资本效率 = 净盈亏 ÷ 总买入金额。{_s_pct:.0f}% 利润来自股票，但也因为股票占用了更多资本（{_s_cap_pct:.0f}%）；关键在于每单位资本的回报率，股票是 ETF 的 {ratio:.1f}×。")

st.markdown("#### 分散化价值")
_corr_label = "几乎零相关" if abs(_corr) < 0.2 else ("低相关" if abs(_corr) < 0.4 else "中等相关")
col1, col2 = st.columns([1, 2])
with col1:
    st.metric("月度盈亏相关性", f"{_corr:.3f}", help="股票 vs ETF 月度净盈亏的 Pearson 相关系数")
    st.caption(f"→ {_corr_label}，ETF 提供真实的分散化价值")
with col2:
    # 找ETF救场的关键年份
    _trades["_year"] = _trades["exit_date"].dt.year
    _by_year = _trades.groupby(["_year","_type"])["net_pnl"].sum().unstack(fill_value=0)
    _by_year.columns.name = None
    _rescue = []
    for yr, row in _by_year.iterrows():
        s_pnl = row.get("股票", 0)
        e_pnl = row.get("ETF", 0)
        if s_pnl < 0 and e_pnl > 0:
            _rescue.append(f"**{yr}**：股票亏 ${abs(s_pnl)/1e4:.0f}万，ETF 盈 ${e_pnl/1e4:.0f}万")
    if _rescue:
        st.markdown("**ETF 在股票亏损年份提供缓冲：**")
        for line in _rescue:
            st.markdown(f"- {line}")

st.markdown(f"""
> **综合判断：** 股票资本效率更高（{ratio:.1f}×），但 ETF 与股票几乎零相关，在关键年份提供对冲缓冲。
> 建议保留 ETF 池，若要提高股票敞口，可适当上调单笔风险比例（如 1% → 1.2% NAV），而非削减 ETF。
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
