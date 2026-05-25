"""Reusable Plotly chart functions. All accept `color` param — never hardcoded."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

SPY_COLOR = "#aaaaaa"
POS_COLOR = "#2ca02c"
NEG_COLOR = "#d62728"


def nav_vs_spy(nav: pd.Series, spy_nav: pd.Series | None,
               color: str, strategy_name: str) -> go.Figure:
    norm = nav / float(nav.iloc[0])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=norm.index, y=norm.values,
        name=strategy_name, line=dict(color=color, width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>NAV: %{y:.2f}x<extra></extra>",
    ))
    if spy_nav is not None:
        spy = spy_nav / float(spy_nav.iloc[0])
        fig.add_trace(go.Scatter(
            x=spy.index, y=spy.values,
            name="SPY (benchmark)", line=dict(color=SPY_COLOR, width=1.2, dash="dash"),
            hovertemplate="%{x|%Y-%m-%d}<br>SPY: %{y:.2f}x<extra></extra>",
        ))
    fig.update_layout(
        title="归一化净值曲线 vs SPY",
        yaxis_title="资产净值（1 = 初始资金）",
        yaxis_tickformat=".1f",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        margin=dict(l=60, r=20, t=60, b=40),
        height=420,
    )
    fig.update_yaxes(ticksuffix="x")
    return fig


def drawdown_chart(nav: pd.Series, color: str) -> go.Figure:
    peak = nav.cummax()
    dd   = (nav - peak) / peak * 100

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dd.index, y=dd.values,
        fill="tozeroy", fillcolor=f"rgba(214,39,40,0.25)",
        line=dict(color=NEG_COLOR, width=1),
        name="回撤",
        hovertemplate="%{x|%Y-%m-%d}<br>回撤: %{y:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        title="最大回撤（从高点的百分比）",
        yaxis_title="回撤 %",
        yaxis_ticksuffix="%",
        hovermode="x unified",
        margin=dict(l=60, r=20, t=60, b=40),
        height=280,
    )
    return fig


def rolling_sharpe_chart(returns: pd.Series, spy_nav: pd.Series | None,
                         color: str, strategy_name: str,
                         window: int = 252, rf_annual: float = 0.05) -> go.Figure:
    rf_daily = (1 + rf_annual) ** (1 / 252) - 1
    excess   = returns - rf_daily
    rs = excess.rolling(window).apply(
        lambda x: (x.mean() * 252) / (x.std() * np.sqrt(252)) if x.std() > 0 else np.nan,
        raw=True,
    )

    fig = go.Figure()
    fig.add_hline(y=0, line_color="#333", line_width=0.8)
    fig.add_hline(y=1, line_color=POS_COLOR, line_width=0.6, line_dash="dash",
                  annotation_text="Sharpe=1", annotation_position="right")

    if spy_nav is not None:
        spy_ret = spy_nav.pct_change().fillna(0)
        spy_exc = spy_ret - rf_daily
        spy_rs  = spy_exc.rolling(window).apply(
            lambda x: (x.mean() * 252) / (x.std() * np.sqrt(252)) if x.std() > 0 else np.nan,
            raw=True,
        )
        fig.add_trace(go.Scatter(
            x=spy_rs.index, y=spy_rs.values,
            name="SPY", line=dict(color=SPY_COLOR, width=1, dash="dash"),
            hovertemplate="%{x|%Y-%m-%d}<br>SPY Sharpe: %{y:.2f}<extra></extra>",
        ))

    fig.add_trace(go.Scatter(
        x=rs.index, y=rs.values,
        name=strategy_name, line=dict(color=color, width=1.5),
        hovertemplate="%{x|%Y-%m-%d}<br>Sharpe: %{y:.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=f"滚动 {window} 日 Sharpe 比率（无风险利率 {rf_annual*100:.0f}%）",
        yaxis_title="Sharpe",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        margin=dict(l=60, r=20, t=60, b=40),
        height=320,
    )
    return fig


def r_multiple_distribution(trades: pd.DataFrame) -> go.Figure:
    r = trades["pnl_r_multiple"].dropna()
    wins   = r[r > 0]
    losses = r[r <= 0]

    bins = np.linspace(max(r.min() - 0.5, -7), min(r.max() + 0.5, 10), 55)

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=losses.values, xbins=dict(start=bins[0], end=bins[-1], size=bins[1]-bins[0]),
        name=f"亏损 ({len(losses)}笔)", marker_color=NEG_COLOR, opacity=0.75,
    ))
    fig.add_trace(go.Histogram(
        x=wins.values, xbins=dict(start=bins[0], end=bins[-1], size=bins[1]-bins[0]),
        name=f"盈利 ({len(wins)}笔)", marker_color=POS_COLOR, opacity=0.75,
    ))
    for x, dash, label in [(-1, "dash", "-1R"), (0, "solid", "0"), (2, "dot", "+2R")]:
        fig.add_vline(x=x, line_dash=dash, line_color="#555", line_width=1,
                      annotation_text=label, annotation_position="top")

    win_rate = len(wins) / len(r) if len(r) > 0 else 0
    fig.add_annotation(
        text=(f"n={len(r)} | 中位数={r.median():.2f}R | "
              f"均值={r.mean():.2f}R | 胜率={win_rate:.1%}"),
        xref="paper", yref="paper", x=0.98, y=0.97,
        showarrow=False, align="right",
        bgcolor="wheat", bordercolor="#ccc", borderwidth=1,
        font=dict(size=11),
    )
    fig.update_layout(
        barmode="overlay",
        title="交易盈亏分布（R 倍数）",
        xaxis_title="R 倍数（1R = 入场风险）",
        yaxis_title="交易笔数",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=20, t=60, b=40),
        height=340,
    )
    return fig


def annual_returns_chart(nav: pd.Series, spy_nav: pd.Series | None,
                         color: str, strategy_name: str) -> go.Figure:
    strat_annual = nav.resample("YE").last().pct_change().dropna()
    strat_annual.index = strat_annual.index.year

    fig = go.Figure()
    if spy_nav is not None:
        spy_annual = spy_nav.resample("YE").last().pct_change().dropna()
        spy_annual.index = spy_annual.index.year
        common = strat_annual.index.intersection(spy_annual.index)
        fig.add_trace(go.Bar(
            x=common, y=spy_annual.loc[common].values * 100,
            name="SPY", marker_color=SPY_COLOR, opacity=0.7,
        ))

    bar_colors = [POS_COLOR if v >= 0 else NEG_COLOR for v in strat_annual.values]
    fig.add_trace(go.Bar(
        x=strat_annual.index, y=strat_annual.values * 100,
        name=strategy_name, marker_color=bar_colors, opacity=0.85,
    ))
    fig.add_hline(y=0, line_color="#333", line_width=0.8)
    fig.update_layout(
        barmode="group",
        title="逐年回报对比",
        yaxis_title="年回报率 %",
        yaxis_ticksuffix="%",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        margin=dict(l=60, r=20, t=60, b=40),
        height=340,
    )
    return fig


def multi_strategy_nav(results_list: list, spy_nav: pd.Series | None) -> go.Figure:
    """Overlay NAV curves for multiple strategies (used in comparison page)."""
    fig = go.Figure()
    for res in results_list:
        norm = res.nav / float(res.nav.iloc[0])
        fig.add_trace(go.Scatter(
            x=norm.index, y=norm.values,
            name=res.meta.display_name,
            line=dict(color=res.meta.color, width=2),
            hovertemplate=f"{res.meta.display_name}<br>%{{x|%Y-%m-%d}}<br>%{{y:.2f}}x<extra></extra>",
        ))
    if spy_nav is not None:
        spy = spy_nav / float(spy_nav.iloc[0])
        fig.add_trace(go.Scatter(
            x=spy.index, y=spy.values,
            name="SPY", line=dict(color=SPY_COLOR, width=1.2, dash="dash"),
            hovertemplate="SPY<br>%{x|%Y-%m-%d}<br>%{y:.2f}x<extra></extra>",
        ))
    fig.update_layout(
        title="策略净值对比（归一化到初始 1.0）",
        yaxis_title="资产净值", yaxis_ticksuffix="x",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        margin=dict(l=60, r=20, t=60, b=40),
        height=450,
    )
    return fig
