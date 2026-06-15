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
    # For each period, pre-compute slices normalised to 1.0 at period start so
    # clicking a period button re-baselines both curves (not just x-zoom).
    periods = [
        ("1年",  1),
        ("3年",  3),
        ("5年",  5),
        ("10年", 10),
        ("全程", None),
    ]
    default_idx = len(periods) - 1  # 全程 active by default
    has_spy = spy_nav is not None
    n_per = 2 if has_spy else 1  # traces per period

    fig = go.Figure()

    for i, (label, years) in enumerate(periods):
        end = nav.index[-1]
        start = (end - pd.DateOffset(years=years)) if years is not None else nav.index[0]
        nav_sl = nav.loc[start:]; nav_sl = nav if nav_sl.empty else nav_sl
        nav_norm = nav_sl / float(nav_sl.iloc[0])
        visible = (i == default_idx)

        fig.add_trace(go.Scatter(
            x=nav_norm.index, y=nav_norm.values,
            name=strategy_name, line=dict(color=color, width=2),
            hovertemplate="%{x|%Y-%m-%d}<br>NAV: %{y:.2f}x<extra></extra>",
            visible=visible, legendgroup="strategy", showlegend=(i == default_idx),
        ))
        if has_spy:
            spy_sl = spy_nav.loc[start:]; spy_sl = spy_nav if spy_sl.empty else spy_sl
            spy_norm = spy_sl / float(spy_sl.iloc[0])
            fig.add_trace(go.Scatter(
                x=spy_norm.index, y=spy_norm.values,
                name="SPY (benchmark)", line=dict(color=SPY_COLOR, width=1.2, dash="dash"),
                hovertemplate="%{x|%Y-%m-%d}<br>SPY: %{y:.2f}x<extra></extra>",
                visible=visible, legendgroup="spy", showlegend=(i == default_idx),
            ))

    total = len(periods) * n_per
    buttons = []
    for i, (label, _) in enumerate(periods):
        vis = [False] * total
        for j in range(n_per):
            vis[i * n_per + j] = True
        buttons.append(dict(label=label, method="update",
                            args=[{"visible": vis}]))

    fig.update_layout(
        title="归一化净值曲线 vs SPY",
        yaxis_title="资产净值（各期起点 = 1.0x）",
        yaxis_tickformat=".1f",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        margin=dict(l=60, r=20, t=80, b=40),
        height=480,
        updatemenus=[dict(
            type="buttons", direction="left",
            buttons=buttons,
            active=default_idx,
            x=0.0, xanchor="left", y=1.13, yanchor="top",
            bgcolor="#f0f2f6", bordercolor="#cccccc",
            font=dict(size=12),
        )],
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
                         window: int = 252, rf_annual: float = 0.02) -> go.Figure:
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
        text=[f"{v*100:+.1f}%" for v in strat_annual.values],
        textposition="outside",
        textfont=dict(size=9),
        cliponaxis=False,
    ))
    fig.add_hline(y=0, line_color="#333", line_width=0.8)
    fig.update_layout(
        barmode="group",
        title="逐年回报对比",
        yaxis_title="年回报率 %",
        yaxis_ticksuffix="%",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        margin=dict(l=60, r=20, t=60, b=60),
        height=380,
    )
    return fig


def trades_per_year_chart(trades: pd.DataFrame) -> go.Figure:
    """Bar chart: number of trades closed per year, stacked by exit reason."""
    df = trades.copy()
    df["year"] = df["exit_date"].dt.year

    reason_colors = {
        "trailing_stop": "#1f77b4",
        "stop_loss":      "#d62728",
        "end_of_backtest": "#aaaaaa",
    }
    reason_labels = {
        "trailing_stop": "移动止盈",
        "stop_loss":     "固定止损",
        "end_of_backtest": "回测结束",
    }

    fig = go.Figure()
    for reason, color in reason_colors.items():
        sub = df[df["exit_reason"] == reason].groupby("year").size().reset_index(name="count")
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            x=sub["year"], y=sub["count"],
            name=reason_labels.get(reason, reason),
            marker_color=color,
            hovertemplate="%{x}年<br>" + reason_labels.get(reason, reason) + ": %{y} 笔<extra></extra>",
        ))

    total_per_year = df.groupby("year").size()
    avg = total_per_year.mean()
    fig.add_hline(
        y=avg, line_dash="dot", line_color="#555", line_width=1,
        annotation_text=f"均值 {avg:.0f} 笔/年",
        annotation_position="top right",
    )
    fig.update_layout(
        barmode="stack",
        title="逐年交易笔数（按平仓原因分类）",
        xaxis_title="年份",
        yaxis_title="交易笔数",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=20, t=60, b=40),
        height=340,
    )
    return fig


def holding_days_distribution(trades: pd.DataFrame) -> go.Figure:
    """Histogram of holding days for all trades."""
    hd = trades["holding_days"].dropna()
    median_d = hd.median()
    mean_d   = hd.mean()

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=hd.values,
        nbinsx=60,
        marker_color="#1f77b4",
        opacity=0.8,
        name="持仓天数",
        hovertemplate="持仓 %{x} 天：%{y} 笔<extra></extra>",
    ))
    for val, dash, label, color in [
        (median_d, "solid", f"中位数 {median_d:.0f} 天", "#e65100"),
        (mean_d,   "dash",  f"均值 {mean_d:.0f} 天",    "#2ca02c"),
    ]:
        fig.add_vline(
            x=val, line_dash=dash, line_color=color, line_width=1.5,
            annotation_text=label,
            annotation_position="top right" if val == mean_d else "top left",
            annotation_font_color=color,
        )
    fig.update_layout(
        title="持仓天数分布（所有交易）",
        xaxis_title="持仓天数",
        yaxis_title="交易笔数",
        margin=dict(l=60, r=20, t=60, b=40),
        height=320,
    )
    return fig


def profit_by_type_chart(trades: pd.DataFrame, etf_tickers: set[str]) -> go.Figure:
    """Stacked bar: annual net P&L split by stock vs ETF."""
    df = trades.copy()
    df["year"] = df["exit_date"].dt.year
    df["type"] = df["ticker"].apply(lambda t: "ETF" if t in etf_tickers else "股票")

    pnl_col  = "net_pnl" if "net_pnl" in df.columns else "gross_pnl"
    grouped  = df.groupby(["year", "type"])[pnl_col].sum()

    all_years = sorted(df["year"].unique())

    etf_vals   = [grouped.get(("ETF",   y), grouped.get((y, "ETF"),   0)) / 1e6 for y in all_years]
    stock_vals = [grouped.get(("股票",   y), grouped.get((y, "股票"),  0)) / 1e6 for y in all_years]

    # reindex properly
    etf_series   = grouped.xs("ETF",   level="type") / 1e6 if "ETF"   in grouped.index.get_level_values("type") else pd.Series(dtype=float)
    stock_series = grouped.xs("股票",  level="type") / 1e6 if "股票"  in grouped.index.get_level_values("type") else pd.Series(dtype=float)
    etf_vals   = [float(etf_series.get(y,   0)) for y in all_years]
    stock_vals = [float(stock_series.get(y,  0)) for y in all_years]
    totals     = [e + s for e, s in zip(etf_vals, stock_vals)]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=all_years, y=etf_vals,
        name="ETF",
        marker_color="#ff7f0e",
        hovertemplate="%{x}年<br>ETF: $%{y:.2f}M<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=all_years, y=stock_vals,
        name="股票",
        marker_color="#1f77b4",
        hovertemplate="%{x}年<br>股票: $%{y:.2f}M<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=all_years, y=totals,
        name="合计",
        mode="lines+markers",
        line=dict(color="#333333", width=1.5, dash="dot"),
        marker=dict(size=5),
        hovertemplate="%{x}年<br>合计: $%{y:.2f}M<extra></extra>",
    ))
    fig.add_hline(y=0, line_color="#555", line_width=0.8)
    fig.update_layout(
        barmode="relative",
        title="策略1.0盈利来源：股票 vs ETF（按年，已平仓交易净盈亏）",
        xaxis_title="年份",
        yaxis_title="净盈亏（百万美元）",
        yaxis_tickprefix="$",
        yaxis_ticksuffix="M",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        margin=dict(l=60, r=20, t=60, b=40),
        height=360,
    )
    return fig


def daily_position_count_chart(trades: pd.DataFrame, nav_index, color: str = "#1f77b4") -> go.Figure:
    """Bar chart: number of open positions on each trading day."""
    if len(trades) == 0:
        return go.Figure()

    df = trades.copy()
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"]  = pd.to_datetime(df["exit_date"])

    dates = pd.to_datetime(nav_index)

    # Event-based cumsum: +1 on entry day, -1 on exit day
    entry_counts = df.groupby("entry_date").size().reindex(dates, fill_value=0)
    exit_counts  = df.groupby("exit_date").size().reindex(dates, fill_value=0)
    daily_count  = (entry_counts - exit_counts).cumsum().clip(lower=0)

    mean_val = float(daily_count.mean())
    max_val  = int(daily_count.max())
    zero_pct = float((daily_count == 0).mean()) * 100

    # 30-day rolling mean for trend line
    rolling_mean = daily_count.rolling(30, min_periods=1).mean()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=daily_count.index,
        y=daily_count.values,
        marker_color=color,
        marker_line_width=0,
        opacity=0.7,
        name="持仓标的数",
        hovertemplate="%{x|%Y-%m-%d}：%{y} 只<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=rolling_mean.index,
        y=rolling_mean.values,
        mode="lines",
        line=dict(color="#e65100", width=1.5),
        name=f"30日均值",
        hovertemplate="%{x|%Y-%m-%d}：均值 %{y:.1f} 只<extra></extra>",
    ))
    fig.add_hline(
        y=mean_val,
        line_dash="dot",
        line_color="black",
        line_width=1,
        annotation_text=f"全程均值 {mean_val:.1f} 只",
        annotation_position="top left",
        annotation_font_size=11,
    )
    fig.update_layout(
        title=f"每日持仓标的数目（最多 {max_val} 只，全程均值 {mean_val:.1f} 只，空仓天数占比 {zero_pct:.1f}%）",
        xaxis_title="日期",
        yaxis_title="持仓标的数量（只）",
        bargap=0,
        height=360,
        margin=dict(l=60, r=20, t=60, b=40),
        legend=dict(orientation="h", x=1, xanchor="right", y=1.12),
        hovermode="x unified",
    )
    return fig


def monthly_return_heatmap(nav: pd.Series) -> go.Figure:
    """Heatmap of monthly returns: years (rows) × months (columns)."""
    monthly = nav.resample("ME").last().pct_change().dropna()
    df = pd.DataFrame({
        "year":  monthly.index.year,
        "month": monthly.index.month,
        "ret":   monthly.values * 100,
    })
    month_names = {1:"1月",2:"2月",3:"3月",4:"4月",5:"5月",6:"6月",
                   7:"7月",8:"8月",9:"9月",10:"10月",11:"11月",12:"12月"}
    pivot = df.pivot(index="year", columns="month", values="ret")
    for m in range(1, 13):
        if m not in pivot.columns:
            pivot[m] = np.nan
    pivot = pivot[[m for m in range(1, 13)]]
    pivot.columns = [month_names[m] for m in range(1, 13)]
    pivot = pivot.sort_index(ascending=False)  # most recent year at top

    z = pivot.values
    x = list(pivot.columns)
    y = [str(yr) for yr in pivot.index]
    text_z = [[f"{v:+.1f}%" if not np.isnan(v) else "" for v in row] for row in z]

    flat = z[~np.isnan(z)]
    abs_max = float(np.percentile(np.abs(flat), 95)) if len(flat) > 0 else 15.0
    abs_max = max(abs_max, 5.0)

    pos_m = int(np.nansum(z > 0))
    tot_m = int(np.sum(~np.isnan(z)))

    fig = go.Figure(go.Heatmap(
        z=z, x=x, y=y,
        text=text_z, texttemplate="%{text}",
        textfont=dict(size=9),
        colorscale=[[0.0,"#d62728"],[0.5,"#ffffff"],[1.0,"#2ca02c"]],
        zmid=0, zmin=-abs_max, zmax=abs_max,
        hovertemplate="%{y}年 %{x}: %{z:.2f}%<extra></extra>",
        showscale=True,
        colorbar=dict(title=dict(text="%", side="right"), ticksuffix="%"),
    ))
    fig.update_layout(
        title=f"月度收益热力图（正收益月份 {pos_m}/{tot_m}，占比 {pos_m/tot_m*100:.0f}%）",
        xaxis=dict(side="top", tickfont=dict(size=11)),
        height=max(420, len(pivot) * 26 + 160),
        margin=dict(l=60, r=80, t=80, b=20),
    )
    return fig


def capital_utilization_chart(
    trades: pd.DataFrame,
    nav: pd.Series,
    color: str = "#1f77b4",
    cash_proxy: str = "SHY",
) -> go.Figure:
    """
    Area chart: % of NAV invested in equity/ETF positions (excluding cash proxy) each day.

    Invested capital is measured at cost (shares × entry_price), which slightly
    understates true market-value utilization for winning positions but requires
    no daily price data — it is computed purely from trades.csv and nav.csv.
    """
    if len(trades) == 0 or len(nav) == 0:
        return go.Figure()

    df = trades.copy()
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["exit_date"]  = pd.to_datetime(df["exit_date"])

    # Exclude cash-proxy ticker if it ever appears
    if "ticker" in df.columns:
        df = df[df["ticker"] != cash_proxy]

    df["entry_value"] = df["shares"] * df["entry_price"]

    dates = pd.to_datetime(nav.index)

    # Event-based cumsum: +value on entry day, −value on exit day
    entry_vals = df.groupby("entry_date")["entry_value"].sum().reindex(dates, fill_value=0.0)
    exit_vals  = df.groupby("exit_date")["entry_value"].sum().reindex(dates, fill_value=0.0)
    daily_invested = (entry_vals - exit_vals).cumsum().clip(lower=0.0)

    # Utilization = invested_at_cost / NAV (%)
    util_pct = (daily_invested / nav.values * 100).clip(lower=0.0, upper=100.0)

    rolling_30 = util_pct.rolling(30, min_periods=1).mean()
    mean_util  = float(util_pct.mean())
    max_util   = float(util_pct.max())

    fig = go.Figure()

    # Shaded area
    fig.add_trace(go.Scatter(
        x=util_pct.index,
        y=util_pct.values,
        fill="tozeroy",
        fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.18)",
        line=dict(color=color, width=1),
        name="每日资金使用率",
        hovertemplate="%{x|%Y-%m-%d}：%{y:.1f}%<extra></extra>",
    ))

    # 30-day rolling mean
    fig.add_trace(go.Scatter(
        x=rolling_30.index,
        y=rolling_30.values,
        mode="lines",
        line=dict(color="#e65100", width=1.8),
        name="30日均值",
        hovertemplate="%{x|%Y-%m-%d}：30日均 %{y:.1f}%<extra></extra>",
    ))

    # Mean reference line
    fig.add_hline(
        y=mean_util,
        line_dash="dot",
        line_color="black",
        line_width=1,
        annotation_text=f"全程均值 {mean_util:.1f}%",
        annotation_position="top left",
        annotation_font_size=11,
    )

    fig.update_layout(
        title=f"资金使用率（成本基础，均值 {mean_util:.1f}%，峰值 {max_util:.1f}%）",
        xaxis_title="日期",
        yaxis_title="资金使用率（%）",
        yaxis=dict(range=[0, min(max_util * 1.15, 100)], ticksuffix="%"),
        height=360,
        margin=dict(l=60, r=20, t=60, b=40),
        legend=dict(orientation="h", x=1, xanchor="right", y=1.12),
        hovermode="x unified",
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
        title="策略1.0净值对比（归一化到初始 1.0）",
        yaxis_title="资产净值", yaxis_ticksuffix="x",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        margin=dict(l=60, r=20, t=60, b=40),
        height=450,
    )
    return fig
