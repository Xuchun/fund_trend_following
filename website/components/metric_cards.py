"""Metric card HTML helpers."""

from __future__ import annotations
import streamlit as st


def _card_html(label: str, value: str, sub: str, color: str) -> str:
    return f"""
<div class="metric-card" style="--card-color:{color}">
  <div class="metric-label">{label}</div>
  <div class="metric-value">{value}</div>
  <div class="metric-sub">{sub}</div>
</div>"""


def render_summary_cards(metrics: dict, color: str,
                          start: str, end: str) -> None:
    """Render the 8 headline metric cards."""
    cagr         = metrics.get("cagr", 0)
    total_ret    = metrics.get("total_return", 0)
    max_dd       = metrics.get("max_drawdown", 0)
    sharpe       = metrics.get("sharpe", 0)
    win_rate     = metrics.get("win_rate", 0)
    n_trades     = metrics.get("n_trades", 0)
    max_dd_days  = metrics.get("max_dd_duration_days", 0)
    avg_deep_days = metrics.get("avg_deep_dd_duration_days", 0)
    n_episodes   = metrics.get("n_deep_dd_episodes", 0)

    def fmt_pct(v):
        sign = "+" if v >= 0 else ""
        return f"{sign}{v*100:.1f}%"

    def signed_color(v):
        return "#2ca02c" if v >= 0 else "#d62728"

    cols = st.columns(3)
    with cols[0]:
        st.markdown(_card_html(
            "CAGR（年化复合回报）",
            f'<span style="color:{signed_color(cagr)}">{fmt_pct(cagr)}</span>',
            f"回测期 {start[:4]}–{end[:4]}",
            color,
        ), unsafe_allow_html=True)

    with cols[1]:
        st.markdown(_card_html(
            "最大回撤",
            f'<span style="color:#d62728">{fmt_pct(max_dd)}</span>',
            "从高点到低点的最大亏损",
            color,
        ), unsafe_allow_html=True)

    with cols[2]:
        sharpe_color = "#2ca02c" if sharpe > 0.5 else ("#d62728" if sharpe < 0 else "#f57c00")
        st.markdown(_card_html(
            "Sharpe 比率",
            f'<span style="color:{sharpe_color}">{sharpe:+.3f}</span>',
            "无风险利率 5%（日度计算）",
            color,
        ), unsafe_allow_html=True)

    cols2 = st.columns(3)
    with cols2[0]:
        st.markdown(_card_html(
            "总回报率",
            f'<span style="color:{signed_color(total_ret)}">{fmt_pct(total_ret)}</span>',
            f"$10M → ${10_000_000*(1+total_ret):,.0f}",
            color,
        ), unsafe_allow_html=True)

    with cols2[1]:
        st.markdown(_card_html(
            "交易胜率",
            f"{win_rate*100:.1f}%",
            "胜率低但期望值为正（趋势跟踪特征）",
            color,
        ), unsafe_allow_html=True)

    with cols2[2]:
        st.markdown(_card_html(
            "总交易笔数",
            f"{int(n_trades):,}",
            f"约 {metrics.get('trades_per_year',0):.0f} 笔/年",
            color,
        ), unsafe_allow_html=True)

    cols3 = st.columns(3)
    with cols3[0]:
        yrs = f"{max_dd_days/252:.1f} 年" if max_dd_days else "—"
        st.markdown(_card_html(
            "最长水下时间",
            f'<span style="color:#d62728">{max_dd_days:,} 交易日</span>',
            f"≈ {yrs}（交易日计），NAV 持续低于前高点的最长连续周期",
            color,
        ), unsafe_allow_html=True)

    with cols3[1]:
        yrs2 = f"{avg_deep_days/252:.1f} 年" if avg_deep_days else "—"
        st.markdown(_card_html(
            "平均深度水下时间（回撤 > 10%）",
            f'<span style="color:#d62728">{avg_deep_days:.0f} 交易日</span>',
            f"≈ {yrs2}（交易日计），共 {n_episodes} 次回撤超过 10% 的情节",
            color,
        ), unsafe_allow_html=True)

    with cols3[2]:
        turnover     = metrics.get("annual_turnover", 0)
        rt_bps       = (metrics.get("slippage_bps", 10) + metrics.get("commission_bps", 3)) * 2
        implied_cost = turnover * rt_bps / 100 if turnover else 0
        st.markdown(_card_html(
            "隐含年化交易成本",
            f'<span style="color:#d62728">≈ {implied_cost:.2f}%</span>',
            f"换手率 {turnover:.1f}x × 往返 {rt_bps:.0f} bps，已含于回测净值",
            color,
        ), unsafe_allow_html=True)


def render_full_metrics_table(metrics: dict, spy_metrics: dict | None = None) -> None:
    """Render the full comparison metrics table."""
    import pandas as pd

    def pct(v, decimals=2):
        if v is None: return "—"
        return f"{v*100:+.{decimals}f}%"

    def num(v, decimals=3):
        if v is None: return "—"
        return f"{v:+.{decimals}f}"

    def days(v):
        if v is None: return "—"
        return f"{int(v):,} 天"

    def cnt(v):
        if v is None: return "—"
        return f"{int(v):,}"

    turnover     = metrics.get("annual_turnover")
    slippage_bps = 10.0
    commission_bps = 3.0
    rt_cost_bps  = (slippage_bps + commission_bps) * 2   # round-trip
    implied_cost = (turnover * rt_cost_bps / 10_000) if turnover else None

    rows = [
        ("**收益**", "", ""),
        ("CAGR", pct(metrics.get("cagr")), pct(spy_metrics.get("spy_cagr") if spy_metrics else None)),
        ("总回报率", pct(metrics.get("total_return")), "—"),
        ("**风险**", "", ""),
        ("年化波动率", pct(metrics.get("annual_vol")), "—"),
        ("最大回撤", pct(metrics.get("max_drawdown")), pct(spy_metrics.get("spy_max_drawdown") if spy_metrics else None)),
        ("最长回撤（天）", days(metrics.get("max_dd_duration_days")), "—"),
        ("**风险收益**", "", ""),
        ("Sharpe 比率（rf=5%）", num(metrics.get("sharpe")), num(spy_metrics.get("spy_sharpe") if spy_metrics else None)),
        ("Sortino 比率", num(metrics.get("sortino")), "—"),
        ("Calmar 比率", num(metrics.get("calmar"), 3), "—"),
        ("**交易统计**", "", ""),
        ("总交易笔数", cnt(metrics.get("n_trades")), "—"),
        ("胜率", pct(metrics.get("win_rate"), 1), "—"),
        ("平均盈利（R 倍数）", num(metrics.get("avg_win_r"), 2), "—"),
        ("平均亏损（R 倍数）", num(metrics.get("avg_loss_r"), 2), "—"),
        ("盈亏比（Profit Factor）", f"{metrics.get('profit_factor',0):.2f}" if metrics.get("profit_factor") else "—", "—"),
        ("平均持仓天数", f"{metrics.get('avg_holding_days',0):.0f} 天", "—"),
        ("交易频率", f"{metrics.get('trades_per_year',0):.0f} 笔/年", "—"),
        ("**换手率（Turnover）**", "", ""),
        ("年换手率",
         f"{turnover:.1f}x  ({turnover*100:.0f}%/年)" if turnover else "—",
         "—"),
        ("隐含年化交易成本",
         f"≈ {implied_cost*100:.2f}%/年（已含于回测）" if implied_cost else "—",
         "—"),
    ]

    df = pd.DataFrame(rows, columns=["指标", "策略 1.0", "SPY 基准"])
    st.dataframe(df, use_container_width=True, hide_index=True)
