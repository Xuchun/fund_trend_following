"""Baseline参数回测结果（回测开始：2000-01-01）"""
# redeploy trigger

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.data_loader import load_strategy
from website.components.strategy_badge import render_page_header

_etf_csv = Path(__file__).resolve().parents[2] / "data" / "ETFs.csv"
import pandas as _pd_etf
_ETF_SET = set(_pd_etf.read_csv(_etf_csv)["SYMBOL"].dropna().str.strip().tolist()) if _etf_csv.exists() else set()
from website.components.metric_cards import render_summary_cards, render_full_metrics_table
from website.components.charts import (
    nav_vs_spy, drawdown_chart, rolling_sharpe_chart,
    r_multiple_distribution, annual_returns_chart,
    trades_per_year_chart, holding_days_distribution,
    profit_by_type_chart, daily_position_count_chart,
    monthly_return_heatmap, capital_utilization_chart,
    daily_entries_vs_skipped_chart,
)

_TIINGO_RESULTS_ID = "v1_unbiased_60m_2000"
_results_path  = Path(__file__).resolve().parents[2] / "results" / _TIINGO_RESULTS_ID
_spy_nav_mtime = int((_results_path / "spy_nav.csv").stat().st_mtime) if (_results_path / "spy_nav.csv").exists() else 0
_cache_key = f"_results_{_TIINGO_RESULTS_ID}_{_spy_nav_mtime}"
# Evict stale cache entries from earlier deployments
for _stale in [k for k in st.session_state if k.startswith(f"_results_{_TIINGO_RESULTS_ID}_") and k != _cache_key]:
    del st.session_state[_stale]
if _cache_key not in st.session_state:
    with st.spinner("正在加载 Tiingo 无偏差回测数据（2000起）…"):
        st.session_state[_cache_key] = load_strategy(_TIINGO_RESULTS_ID)
res  = st.session_state[_cache_key]
meta = res.meta
m    = dict(res.metrics)  # mutable copy

# Compute max_consecutive_losses from trades if not already in metrics
if "max_consecutive_losses" not in m and len(res.trades) > 0:
    _sorted = res.trades.sort_values("exit_date") if "exit_date" in res.trades.columns else res.trades
    _pnl = _sorted["net_pnl"].values
    _max_cl = _cur_cl = 0
    for _v in _pnl:
        if _v <= 0:
            _cur_cl += 1
            _max_cl  = max(_max_cl, _cur_cl)
        else:
            _cur_cl = 0
    m["max_consecutive_losses"] = _max_cl

# ── Compute extended SPY metrics from spy_nav ─────────────────────────────────
import numpy as _np

_spy_metrics = dict(m)   # already has spy_cagr, spy_sharpe, spy_max_drawdown

if res.spy_nav is not None:
    _sn  = res.spy_nav
    _sr  = _sn.pct_change().fillna(0.0)
    _rf  = (1 + 0.02) ** (1 / 252) - 1

    # Total return
    _spy_metrics["spy_total_return"] = float(_sn.iloc[-1] / _sn.iloc[0] - 1)

    # Annual volatility
    _spy_metrics["spy_annual_vol"] = float(_sr.std() * _np.sqrt(252))

    # Sortino
    _exc       = _sr - _rf
    _down_std  = float(_exc[_exc < 0].std() * _np.sqrt(252))
    _spy_cagr  = m.get("spy_cagr", 0)
    _spy_metrics["spy_sortino"] = float((_spy_cagr - 0.02) / _down_std) if _down_std > 0 else 0.0

    # Calmar
    _spy_maxdd = m.get("spy_max_drawdown", 0)
    _spy_metrics["spy_calmar"] = float(_spy_cagr / abs(_spy_maxdd)) if _spy_maxdd != 0 else 0.0

    # Max drawdown duration (trading days)
    _roll_max  = _sn.cummax()
    _underwater = (_sn < _roll_max)
    _max_dur = _cur_dur = 0
    for _uw in _underwater:
        if _uw:
            _cur_dur += 1
            _max_dur  = max(_max_dur, _cur_dur)
        else:
            _cur_dur = 0
    _spy_metrics["spy_max_dd_duration_days"] = _max_dur


render_page_header("Baseline参数回测结果", meta)
st.markdown(f"<p style='color:black;font-weight:bold;font-size:16px;margin-top:-8px;'>回测期间：{meta.backtest_start} → {meta.backtest_end}</p>", unsafe_allow_html=True)
st.markdown("---")

# ── Summary cards ─────────────────────────────────────────────────────────────
render_summary_cards(m, meta.color, meta.backtest_start, meta.backtest_end, _spy_metrics)

st.markdown("---")

# ── Data source section ───────────────────────────────────────────────────────
st.subheader("回测的数据来源")
st.markdown(f"""
| 项目 | 详情 |
|------|------|
| **数据来源** | Tiingo EOD（End-of-Day）历史价格 API |
| **回测期间** | {meta.backtest_start} → {meta.backtest_end} |
| **标的覆盖** | NYSE / NASDAQ / AMEX 全量历史股票 + 88 只跨资产 ETF，含退市 / 被收购 / 破产标的 |
| **标的池总量** | {meta.universe_total:,} 个（{meta.universe_stocks:,} 只股票 + {meta.universe_etfs:,} 只 ETF） |
| **无幸存者偏差** | Tiingo 保留完整历史数据（含退市标的），避免仅使用当前成分股带来的偏差 |
""")
st.markdown("""
**三级过滤逻辑：**

| 过滤层级 | 条件 | 执行时机 |
|---------|------|---------|
| 静态预过滤 | 累计满足天数 ≥ 252 天（约 1 年） | CSV 构建时，一次性筛选 |
| 引擎每日动态 | 原始收盘价 > $10 | 每日收盘后信号生成前 |
| 引擎每日动态 | ADV₆₀ > $60M（60 日均日成交额，shift(1) 无前视偏差） | 每日收盘后信号生成前 |

完整标的池构建方法详见「数据与标的池」页面。
""")

st.markdown("---")

# ── Baseline parameter table ───────────────────────────────────────────────────
_p = meta.params_anchor
st.subheader("📋 Baseline 锚点参数")
st.caption("以下参数值与设计方案 §1.2.1.1、代码 StrategyParams 及回测脚本三处完全一致。")

_col_a, _col_b = st.columns(2)

with _col_a:
    st.markdown("**入场信号**")
    st.markdown(f"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 突破窗口 | `breakout_window` | **{_p['breakout_window']} 日** |
| ATR 周期 | `atr_period` | **{_p['atr_period']} 日**（Wilder 平滑）|
| 成交量确认乘数 | `volume_filter_multiplier` | **{_p['volume_filter_multiplier']:.1f}×** 60日均量 |
| 突破强度过滤 | `breakout_strength_min` | **无**（0.0，不过滤）|
| Gap 过滤 | `gap_filter` | **±{_p['gap_filter']*100:.1f}%**（跳空超限放弃入场）|
""")

    st.markdown("**标的过滤**")
    st.markdown(r"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 最低股价 | `min_price` | **\$10**（原始收盘价）|
| 最低市值 | `min_market_cap_b` | **\$2B**（注①）|
| ADV 流动性 | `min_adv_m` | **<span style="color:#e74c3c">\$60M</span>**（60日均量）|
""", unsafe_allow_html=True)
    st.caption("注①：Tiingo 不提供历史流通股数据，以 ADV>$60M 作为流动性门槛（≈ $12亿+市值），min_market_cap_b 未在引擎中启用。")

    st.markdown("**止损 / 最小止损距离**")
    st.markdown(f"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| ATR 止损乘数 | `stop_loss_multiplier` | **{_p['stop_loss_multiplier']:.1f}×ATR** |
| 最小止损距离 | `min_stop_distance_pct` | **{_p['min_stop_distance_pct']*100:.1f}%**（低于此值放弃）|
""")

    st.markdown("**移动止盈（分段）**")
    st.markdown(f"""
| 阶段 | 代码名 | Baseline 值 |
|---|---|---|
| 早期（< 1R） | `trail_multiplier_r1` | **{_p['trail_multiplier_r1']:.1f}×ATR** |
| 中期（1–3R） | `trail_multiplier_r3` | **{_p['trail_multiplier_r3']:.1f}×ATR** |
| 大赢（≥ 3R） | `trail_multiplier_r5` | **{_p['trail_multiplier_r5']:.1f}×ATR** |
""")

with _col_b:
    st.markdown("**仓位与风险**")
    st.markdown(f"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 每笔风险比例 | `risk_per_trade` | **{_p['risk_per_trade']*100:.1f}% NAV** |
| 单标的仓位上限 | `position_cap` | **{_p['position_cap']*100:.0f}% NAV** |
| 热度上限 | `heat_limit` | **{_p['heat_limit']*100:.0f}% NAV**（注②）|
""")
    st.caption("注②：由于 position_cap 架空效应，实际每笔风险约 0.24% NAV，heat_limit ≥ 10% 在回测中从未触发（见参数敏感性分析页）。")

    st.markdown("**相关性过滤**")
    st.markdown(f"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 相关性窗口 | `correlation_window` | **{_p['correlation_window']} 日** |
| 相关性阈值 | `correlation_threshold` | **{_p['correlation_threshold']:.2f}**（超出则减仓）|
| 减仓比例 | `correlation_reduction` | **{_p['correlation_reduction']*100:.0f}%**（仓位乘以 0.5）|
""")

    st.markdown("**市场环境过滤（Regime Filter）**")
    st.markdown(f"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 启用 | `regime_filter_enabled` | **{'是' if _p['regime_filter_enabled'] else '否'}** |
| 基准标的 | `regime_ticker` | **{_p['regime_ticker']}** |
| SMA 窗口 | `regime_sma_window` | **{_p['regime_sma_window']} 日** |
""")

    st.markdown("**交易成本**")
    st.markdown(f"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 滑点（单边） | `slippage_bps` | **{_p['slippage_bps']:.0f} bps** |
| 佣金（单边） | `commission_bps` | **{_p['commission_bps']:.0f} bps** |
""")

    st.markdown("**空仓 / 回测设置**")
    st.markdown(r"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 空仓资金代理 | `cash_proxy` | **SHY**（1–3年期国债 ETF）|
| 初始资金 | — | **\$10,000,000** |
| 回测开始 | — | **2000-01-03** |
""")

st.markdown("---")

# ── Combined NAV + Drawdown chart (st.slider range → re-baselined) ───────────
from plotly.subplots import make_subplots as _make_subplots_nd
import plotly.graph_objects as _go_nd
import datetime as _dt_nd

st.subheader("净值曲线 & 回撤曲线")
_show_spy = st.checkbox("显示 SPY 基准曲线", value=True, key="nav_show_spy")

_nav_min_dt = res.nav.index[0].to_pydatetime()
_nav_max_dt = res.nav.index[-1].to_pydatetime()

# ── Period quick-select buttons ───────────────────────────────────────────────
_periods_nd = [("1年", 1), ("3年", 3), ("5年", 5), ("10年", 10), ("全程", None)]
_p_cols = st.columns([1, 1, 1, 1, 1, 6])
for _ci, (_lbl, _yrs) in enumerate(_periods_nd):
    with _p_cols[_ci]:
        if st.button(_lbl, key=f"nd_btn_{_lbl}"):
            _ps = (_nav_min_dt if _yrs is None else
                   max(_nav_min_dt,
                       _nav_max_dt - _dt_nd.timedelta(days=round(365.25 * _yrs))))
            st.session_state["nd_slider"] = (_ps, _nav_max_dt)

# ── Dual-handle range slider ──────────────────────────────────────────────────
_sel_s, _sel_e = st.slider(
    "选择时间范围",
    min_value=_nav_min_dt,
    max_value=_nav_max_dt,
    value=(_nav_min_dt, _nav_max_dt),
    format="YYYY-MM-DD",
    key="nd_slider",
    label_visibility="collapsed",
)

# ── Re-baseline data for selected range ───────────────────────────────────────
_nav_sl = res.nav.loc[_sel_s:_sel_e]
if len(_nav_sl) < 2:
    _nav_sl = res.nav
_nav_norm = _nav_sl / float(_nav_sl.iloc[0])
_has_spy_nd = _show_spy and res.spy_nav is not None

if _has_spy_nd:
    _spy_sl = res.spy_nav.loc[_sel_s:_sel_e]
    if len(_spy_sl) < 2:
        _spy_sl = res.spy_nav
    _spy_norm = _spy_sl / float(_spy_sl.iloc[0])

# ── Build figure ──────────────────────────────────────────────────────────────
_fig_nd = _make_subplots_nd(
    rows=2, cols=1, shared_xaxes=True,
    row_heights=[0.65, 0.35], vertical_spacing=0.05,
    subplot_titles=["", ""],
)

_fig_nd.add_trace(_go_nd.Scatter(
    x=_nav_norm.index, y=_nav_norm.values,
    name="策略1.0", line=dict(color=meta.color, width=2),
    hovertemplate="%{x|%Y-%m-%d}<br>NAV: %{y:.2f}x<extra></extra>",
), row=1, col=1)

if _has_spy_nd:
    _fig_nd.add_trace(_go_nd.Scatter(
        x=_spy_norm.index, y=_spy_norm.values,
        name="SPY", line=dict(color="#888888", width=1.2, dash="dash"),
        hovertemplate="%{x|%Y-%m-%d}<br>SPY: %{y:.2f}x<extra></extra>",
    ), row=1, col=1)

_dd_sl = (_nav_sl - _nav_sl.cummax()) / _nav_sl.cummax() * 100
_fig_nd.add_trace(_go_nd.Scatter(
    x=_dd_sl.index, y=_dd_sl.values,
    fill="tozeroy", fillcolor="rgba(214,39,40,0.25)",
    line=dict(color="#d62728", width=1),
    hovertemplate="%{x|%Y-%m-%d}<br>回撤: %{y:.1f}%<extra></extra>",
    showlegend=False,
), row=2, col=1)

if _has_spy_nd:
    _spy_dd = (_spy_sl - _spy_sl.cummax()) / _spy_sl.cummax() * 100
    _fig_nd.add_trace(_go_nd.Scatter(
        x=_spy_dd.index, y=_spy_dd.values,
        line=dict(color="#888888", width=1.2, dash="dash"),
        hovertemplate="%{x|%Y-%m-%d}<br>SPY回撤: %{y:.1f}%<extra></extra>",
        showlegend=False,
    ), row=2, col=1)

_fig_nd.update_layout(
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=60, r=20, t=60, b=40),
    height=620,
)
_fig_nd.update_yaxes(ticksuffix="x", title_text="净值（倍）", row=1, col=1)
_fig_nd.update_yaxes(ticksuffix="%", title_text="回撤 %", row=2, col=1)
st.plotly_chart(_fig_nd, use_container_width=True)

# ── Drawdown recovery analysis table ─────────────────────────────────────────
import numpy as _np_ep
import pandas as _pd_ep

_nav_ep = res.nav.copy()
if not isinstance(_nav_ep.index, _pd_ep.DatetimeIndex):
    _nav_ep.index = _pd_ep.to_datetime(_nav_ep.index)

_DD_THRESH = -0.05   # track episodes with drawdown < -5%
_n_ep      = len(_nav_ep)
_dates_ep  = _nav_ep.index
_vals_ep   = _nav_ep.values.astype(float)

_peak_val  = _vals_ep[0]
_peak_i    = 0
_in_ep     = False
_ep_pi     = 0      # peak index of current episode
_ep_ti     = 0      # trough index of current episode
_ep_tv     = 0.0   # trough value
_ep_rows   = []

for _i in range(1, _n_ep):
    _v = _vals_ep[_i]
    if _v >= _peak_val:
        if _in_ep:
            _ep_rows.append({
                "高点": _dates_ep[_ep_pi].strftime("%Y-%m"),
                "低点": _dates_ep[_ep_ti].strftime("%Y-%m"),
                "修复": _dates_ep[_i].strftime("%Y-%m"),
                "最大回撤": (_ep_tv - _vals_ep[_ep_pi]) / _vals_ep[_ep_pi],
                "至低谷（交易日）": _ep_ti - _ep_pi,
                "修复耗时（交易日）": _i - _ep_ti,
                "总水下时间（交易日）": _i - _ep_pi,
            })
            _in_ep = False
        _peak_val = _v
        _peak_i   = _i
    else:
        _dd_v = (_v - _peak_val) / _peak_val
        if _dd_v < _DD_THRESH:
            if not _in_ep:
                _in_ep = True
                _ep_pi = _peak_i
                _ep_ti = _i
                _ep_tv = _v
            elif _v < _ep_tv:
                _ep_ti = _i
                _ep_tv = _v

if _in_ep:   # ongoing episode (not yet recovered)
    _ep_rows.append({
        "高点": _dates_ep[_ep_pi].strftime("%Y-%m"),
        "低点": _dates_ep[_ep_ti].strftime("%Y-%m"),
        "修复": "进行中",
        "最大回撤": (_ep_tv - _vals_ep[_ep_pi]) / _vals_ep[_ep_pi],
        "至低谷（交易日）": _ep_ti - _ep_pi,
        "修复耗时（交易日）": _n_ep - 1 - _ep_ti,
        "总水下时间（交易日）": _n_ep - 1 - _ep_pi,
    })

_ep_df = _pd_ep.DataFrame(_ep_rows)

# ── Deep drawdown episode duration chart ─────────────────────────────────────
import plotly.graph_objects as _go_ddd

st.markdown("---")
st.subheader("深度回撤分析（回撤 > 10%）")

_deep_eps_ddd = _ep_df[_ep_df["最大回撤"] < -0.10].copy() if len(_ep_df) > 0 else _pd_ep.DataFrame()

if len(_deep_eps_ddd) == 0:
    st.info("回测期间未出现回撤超过 10% 的深度情节。")
else:
    _deep_eps_ddd = _deep_eps_ddd.sort_values("高点")

    # X 轴：起始年份；同一年出现两次情节则用 YYYY-MM 区分
    _x_labels_ddd: list[str] = []
    _seen_yr_ddd: dict[str, int] = {}
    for _, _row_ddd in _deep_eps_ddd.iterrows():
        _yr_ddd = _row_ddd["高点"][:4]
        if _yr_ddd not in _seen_yr_ddd:
            _seen_yr_ddd[_yr_ddd] = 1
            _x_labels_ddd.append(_yr_ddd)
        else:
            _seen_yr_ddd[_yr_ddd] += 1
            _x_labels_ddd.append(_row_ddd["高点"])

    _y_vals_ddd   = _deep_eps_ddd["总水下时间（交易日）"].tolist()
    _dd_pct_ddd   = [abs(v) * 100 for v in _deep_eps_ddd["最大回撤"].tolist()]
    _custom_ddd   = [
        [f"{abs(r['最大回撤'])*100:.1f}", r["高点"], r["低点"], r["修复"], int(r["总水下时间（交易日）"])]
        for _, r in _deep_eps_ddd.iterrows()
    ]

    _fig_ddd = _go_ddd.Figure(_go_ddd.Bar(
        x=_x_labels_ddd,
        y=_y_vals_ddd,
        marker=dict(
            color=_dd_pct_ddd,
            colorscale="Reds",
            colorbar=dict(title="最大回撤 (%)"),
            cmin=10,
            cmax=max(_dd_pct_ddd) if _dd_pct_ddd else 30,
        ),
        customdata=_custom_ddd,
        hovertemplate=(
            "<b>起始：%{customdata[1]}</b><br>"
            "低谷：%{customdata[2]}<br>"
            "修复：%{customdata[3]}<br>"
            "最大回撤：%{customdata[0]}%<br>"
            "总水下：%{y} 交易日"
            "<extra></extra>"
        ),
        text=[f"{v}天<br>回撤{p:.1f}%" for v, p in zip(_y_vals_ddd, _dd_pct_ddd)],
        textposition="outside",
    ))
    _fig_ddd.update_layout(
        title="",
        height=400,
        margin=dict(l=60, r=20, t=30, b=50),
        bargap=0.35,
        xaxis=dict(
            type="category",
            title_text="<b>深度回撤起始年份</b>",
            title_font=dict(color="black", size=13),
        ),
        yaxis=dict(
            title_text="<b>深度回撤日数</b>",
            title_font=dict(color="black", size=13),
        ),
    )
    st.plotly_chart(_fig_ddd, use_container_width=True)

    _avg_total_ddd   = float(_deep_eps_ddd["总水下时间（交易日）"].mean())
    _longest_idx_ddd = _deep_eps_ddd["总水下时间（交易日）"].idxmax()
    _longest_ddd     = _deep_eps_ddd.loc[_longest_idx_ddd]
    _recovered_ddd   = _deep_eps_ddd[_deep_eps_ddd["修复"] != "进行中"]
    _avg_rec_ddd     = float(_recovered_ddd["修复耗时（交易日）"].mean()) if len(_recovered_ddd) > 0 else 0.0
    st.markdown(
        f"**解读：** 每根柱子代表一次回撤超过 10% 的深度回撤，颜色越深表示回撤幅度越大，"
        f"柱子越高表示水下时间越长。"
        f"共 **{len(_deep_eps_ddd)}** 次，"
        f"最长回撤起于 **{_longest_ddd['高点']}**，"
        f"历时 **{int(_longest_ddd['总水下时间（交易日）'])} 交易日**"
        f"（约 {_longest_ddd['总水下时间（交易日）']/252:.1f} 年）。"
    )

st.markdown("---")

# ── Streak analysis ───────────────────────────────────────────────────────────
import json as _json_br
_DIAG_PATH_BR = Path(__file__).resolve().parents[2] / "results" / "v1_unbiased_60m_2000" / "diagnostics.json"

st.subheader("连续亏损序列分析")

if _DIAG_PATH_BR.exists():
    import plotly.graph_objects as _go_br

    _diag_br = _json_br.loads(_DIAG_PATH_BR.read_text(encoding="utf-8"))
    _sa_br   = _diag_br.get("streak_analysis", {})
    _streak_counts_br: dict = _sa_br.get("streak_counts", {})

    if _streak_counts_br:
        _x_labels_br: list[str] = []
        _y_counts_br: list[int] = []
        _bar_colors_br: list[str] = []

        for _length_br in range(1, 10):
            _x_labels_br.append(str(_length_br))
            _y_counts_br.append(_streak_counts_br.get(str(_length_br), 0))
            if _length_br <= 4:
                _bar_colors_br.append("#2ca02c")
            else:
                _bar_colors_br.append("#f57c00")

        # Compute per-length counts for streaks >= 10 from trades
        import pandas as _pd_streak
        _trades_streak = res.trades.sort_values("exit_date").reset_index(drop=True) \
            if "exit_date" in res.trades.columns else res.trades.reset_index(drop=True)
        _ge10_counts: dict[int, int] = {}
        _cur_s = 0
        for _v_s in _trades_streak["net_pnl"].values:
            if _v_s <= 0:
                _cur_s += 1
            else:
                if _cur_s >= 10:
                    _ge10_counts[_cur_s] = _ge10_counts.get(_cur_s, 0) + 1
                _cur_s = 0
        if _cur_s >= 10:
            _ge10_counts[_cur_s] = _ge10_counts.get(_cur_s, 0) + 1

        for _len_ge10 in sorted(_ge10_counts.keys()):
            _x_labels_br.append(str(_len_ge10))
            _y_counts_br.append(_ge10_counts[_len_ge10])
            _bar_colors_br.append("#d62728")

        _fig_streak = _go_br.Figure(
            data=[_go_br.Bar(
                x=_x_labels_br,
                y=_y_counts_br,
                marker_color=_bar_colors_br,
                text=_y_counts_br,
                textposition="outside",
            )]
        )
        _fig_streak.update_layout(
            title="历史连续亏损序列分布",
            xaxis_title="连续亏损笔数",
            yaxis_title="出现次数",
            showlegend=False,
            height=400,
            margin=dict(t=50, b=40, l=40, r=20),
            xaxis=dict(type="category"),
        )
        st.plotly_chart(_fig_streak, use_container_width=True)

    _sc1, _sc2, _sc3 = st.columns(3)
    _sc1.metric("最长连续亏损（笔）", _sa_br.get("max_consecutive_losses", 0))
    _sc2.metric("总亏损序列数",       _sa_br.get("total_streaks", 0))
    _sc3.metric("平均序列长度",       f"{_sa_br.get('avg_streak_length', 0.0):.2f}")

    _max_cl_br = _sa_br.get("max_consecutive_losses", 0)
    _wr_pct_br = m.get("win_rate", 0) * 100
    _expected_loss_gap = 1 / (1 - m.get("win_rate", 0.38)) if m.get("win_rate", 0.38) < 1 else 0
    st.markdown(
        f'<div class="info-box">'
        f'在 {_wr_pct_br:.1f}% 胜率下，随机期望每隔约 {_expected_loss_gap:.1f} 笔交易出现一次亏损连续段。'
        f'最长 <strong>{_max_cl_br} 笔</strong>连续亏损是心理上最难承受的时刻，'
        f'但从统计上看并不异常。'
        f'</div>',
        unsafe_allow_html=True,
    )
else:
    st.info("连续亏损数据尚未生成。运行：python src/scripts/04_run_diagnostics.py")

st.markdown("---")

# ── Top 20 亏损交易分析 ────────────────────────────────────────────────────────
import plotly.graph_objects as _go_l20
import numpy as _np_l20

st.subheader("Top 20亏损交易分析")
st.caption("已平仓交易中 R 倍数最差的 20 笔——寻找大亏家的共性规律")

_l20 = res.trades.nsmallest(20, "pnl_r_multiple").copy()
_l20["类别"]     = _l20["ticker"].apply(lambda t: "ETF" if t in _ETF_SET else "股票")
_l20["卖出原因"] = _l20["exit_reason"].map({
    "trailing_stop":   "追踪止损",
    "stop_loss":       "初始止损",
    "end_of_backtest": "回测截止",
    "delisted":        "退市/并购",
}).fillna(_l20["exit_reason"])
_l20["入场年份"] = _l20["entry_date"].dt.year

_l20_n_stoploss  = int((_l20["exit_reason"] == "stop_loss").sum())
_l20_n_delisted  = int((_l20["exit_reason"] == "delisted").sum())
_l20_n_stocks    = int((_l20["类别"] == "股票").sum())
_l20_avg_hold    = float(_l20["holding_days"].mean())
_l20_med_hold    = float(_l20["holding_days"].median())
_l20_min_hold    = int(_l20["holding_days"].min())
_l20_max_hold    = int(_l20["holding_days"].max())
_l20_all_loss_avg = float(res.trades[res.trades["net_pnl"] <= 0]["holding_days"].mean())
_l20_n_gap       = int((_l20["gap_adjusted_loss_multiple"] < -1.05).sum())

# ── R 倍数排名图（横向柱状图）────────────────────────────────────────────────
_l20_desc = _l20.sort_values("pnl_r_multiple", ascending=False)  # 最差的在 y 列表末尾 → 顶部
_fig_l20r = _go_l20.Figure(_go_l20.Bar(
    y=[f"{row['ticker']}  ({int(row['入场年份'])})" for _, row in _l20_desc.iterrows()],
    x=_l20_desc["pnl_r_multiple"].tolist(),
    orientation="h",
    marker_color="#d62728",
    text=[f"{r:.2f}R" for r in _l20_desc["pnl_r_multiple"].tolist()],
    textposition="outside",
))
_fig_l20r.update_layout(
    title="Top 20 大亏家 R 倍数（括号内为入场年份）",
    xaxis_title="R 倍数",
    height=560,
    margin=dict(l=140, r=80, t=50, b=40),
    showlegend=False,
)
st.plotly_chart(_fig_l20r, use_container_width=True)

# ── 指标行 ────────────────────────────────────────────────────────────────────
_lm1, _lm2, _lm3, _lm4 = st.columns(4)
with _lm1:
    st.metric("初始止损退出",
              f"{_l20_n_stoploss} / 20  ({_l20_n_stoploss / 20 * 100:.0f}%)",
              help="触发初始止损退出 = 风控正常运作（快速截断亏损）")
with _lm2:
    st.metric("平均持仓天数",
              f"{_l20_avg_hold:.0f} 天",
              delta=f"vs 全部亏损交易 {_l20_all_loss_avg:.0f} 天",
              delta_color="inverse",
              help="大亏家持仓时间是否更长？趋势跟踪应快速止损，持仓异常长说明止损被绕开")
with _lm3:
    st.metric("跳空穿透 / 退市",
              f"{_l20_n_gap} 笔跳空 / {_l20_n_delisted} 笔退市",
              help="gap_adjusted_loss_multiple < -1.05R：止损被跳空穿透，实际亏损超 1R")
with _lm4:
    st.metric("股票 / ETF",
              f"{_l20_n_stocks} : {len(_l20) - _l20_n_stocks}",
              help="大亏家的资产类别分布")

# ── 散点图 + 年份分布 ─────────────────────────────────────────────────────────
_lca, _lcb = st.columns(2)

with _lca:
    _l20_corr = float(_np_l20.corrcoef(_l20["holding_days"], _l20["pnl_r_multiple"])[0, 1])
    _fig_lsc = _go_l20.Figure(_go_l20.Scatter(
        x=_l20["holding_days"].tolist(),
        y=_l20["pnl_r_multiple"].tolist(),
        mode="markers+text",
        text=_l20["ticker"].tolist(),
        textposition="top center",
        marker=dict(size=10, color="#d62728"),
    ))
    _fig_lsc.add_annotation(
        text=f"相关系数 r = {_l20_corr:.2f}",
        xref="paper", yref="paper", x=0.98, y=0.95,
        showarrow=False, align="right",
        bgcolor="wheat", bordercolor="#ccc", borderwidth=1,
        font=dict(size=11),
    )
    _fig_lsc.update_layout(
        title="持仓天数 vs R 倍数（大亏家）",
        xaxis_title="持仓天数",
        yaxis_title="R 倍数",
        height=380,
        margin=dict(l=50, r=30, t=50, b=40),
    )
    st.plotly_chart(_fig_lsc, use_container_width=True)

with _lcb:
    _l20_yr = _l20["入场年份"].value_counts().sort_index()
    _fig_lyr = _go_l20.Figure(_go_l20.Bar(
        x=_l20_yr.index.tolist(),
        y=_l20_yr.values.tolist(),
        marker_color="#d62728",
        text=_l20_yr.values.tolist(),
        textposition="outside",
    ))
    _fig_lyr.update_layout(
        title="大亏家入场年份分布",
        xaxis_title="入场年份",
        yaxis_title="笔数",
        height=380,
        margin=dict(l=50, r=30, t=50, b=40),
    )
    st.plotly_chart(_fig_lyr, use_container_width=True)

# ── 行业分布（亏损）────────────────────────────────────────────────────────────
_SECTOR_CN_L20 = {
    "Technology":             "科技",
    "Healthcare":             "医疗健康",
    "Consumer Cyclical":      "消费（周期）",
    "Consumer Defensive":     "消费（防御）",
    "Financial Services":     "金融",
    "Basic Materials":        "基础材料",
    "Energy":                 "能源",
    "Industrials":            "工业",
    "Real Estate":            "房地产",
    "Communication Services": "通信服务",
    "Utilities":              "公用事业",
}
_etf_cat_l20 = {e["ticker"]: f"ETF-{e.get('category', '其他')}" for e in meta.etf_universe}

@st.cache_data(ttl=86400 * 7, show_spinner="正在查询行业分类…")
def _get_sector_map_l20(tickers: tuple) -> dict:
    import yfinance as _yfl
    result = {}
    for tk in tickers:
        try:
            raw = _yfl.Ticker(tk).info.get("sector") or ""
            result[tk] = _SECTOR_CN_L20.get(raw, raw or "未知")
        except Exception:
            result[tk] = "未知"
    return result

_stock_tkrs_l20 = tuple(
    row["ticker"] for _, row in _l20.iterrows() if row["类别"] != "ETF"
)
_sec_map_l20 = _get_sector_map_l20(_stock_tkrs_l20)

_l20["行业"] = _l20.apply(
    lambda row: (
        _etf_cat_l20.get(row["ticker"], "ETF")
        if row["类别"] == "ETF"
        else _sec_map_l20.get(row["ticker"], "未知")
    ),
    axis=1,
)

_sec_grp_l20 = (
    _l20.groupby("行业", sort=False)
    .agg(
        笔数  = ("ticker", "count"),
        合计R = ("pnl_r_multiple", "sum"),
        标的  = ("ticker", lambda x: "、".join(x.tolist())),
    )
    .reset_index()
    .sort_values("笔数", ascending=False)
)

st.markdown("#### 行业分布")
_sec_colors_l20 = [
    "#d62728","#e15759","#f28e2b","#ff9da7","#b07aa1",
    "#4e79a7","#76b7b2","#59a14f","#edc948","#bab0ac",
]
_col_pie_l, _col_bar_l = st.columns(2)

with _col_pie_l:
    _fig_sec_l_pie = _go_l20.Figure(_go_l20.Pie(
        labels=_sec_grp_l20["行业"].tolist(),
        values=_sec_grp_l20["笔数"].tolist(),
        hole=0.38,
        marker_colors=_sec_colors_l20[:len(_sec_grp_l20)],
        customdata=[[r, s] for r, s in zip(_sec_grp_l20["合计R"].tolist(), _sec_grp_l20["标的"].tolist())],
        hovertemplate=(
            "<b>%{label}</b><br>笔数：%{value}<br>"
            "合计 R：%{customdata[0]:.1f}R<br>标的：%{customdata[1]}<extra></extra>"
        ),
        textinfo="label+value",
        textfont_size=12,
    ))
    _fig_sec_l_pie.update_layout(
        title="行业分布（交易笔数）",
        height=400,
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=False,
    )
    st.plotly_chart(_fig_sec_l_pie, use_container_width=True)

with _col_bar_l:
    _sec_grp_ls = _sec_grp_l20.sort_values("合计R", ascending=False)
    _fig_sec_l_bar = _go_l20.Figure(_go_l20.Bar(
        y=_sec_grp_ls["行业"].tolist(),
        x=_sec_grp_ls["合计R"].tolist(),
        orientation="h",
        marker_color="#d62728",
        text=[f"{v:.1f}R" for v in _sec_grp_ls["合计R"].tolist()],
        textposition="outside",
        customdata=_sec_grp_ls["标的"].tolist(),
        hovertemplate="<b>%{y}</b><br>合计 R：%{x:.1f}R<br>标的：%{customdata}<extra></extra>",
    ))
    _fig_sec_l_bar.update_layout(
        title="各行业合计 R 倍数（亏损）",
        xaxis_title="合计 R",
        height=400,
        margin=dict(l=120, r=70, t=50, b=40),
        showlegend=False,
    )
    st.plotly_chart(_fig_sec_l_bar, use_container_width=True)

_sec_grp_l_show = _sec_grp_l20.copy()
_sec_grp_l_show.columns = ["行业 / 类别", "笔数", "合计 R", "包含标的"]
_sec_grp_l_show["合计 R"] = _sec_grp_l_show["合计 R"].map(lambda v: f"{v:.1f}R")
st.dataframe(_sec_grp_l_show, use_container_width=True, hide_index=True)

# ── 买入股价分布（还原拆股后的真实市场价）────────────────────────────────────────────
st.markdown("#### 买入股价分布（入场当日真实市场价，已还原拆股）")
st.caption(
    "价格直接来自 Tiingo 原始历史数据（`close` 字段 = 当日真实收盘价，未做任何拆股或股息调整）。"
    "例如 BB 2003-09-29 真实价格 **$38.50**；AAPL 2004-08-27 真实价格 **$34.35**。"
    "与策略 `min_price=$10` 过滤器使用同一列数据，口径完全一致。"
)

import json as _json_l20
_raw_price_json_l20 = _results_path / "top20_raw_entry_prices.json"
_raw_map_l20: dict = {}
if _raw_price_json_l20.exists():
    with open(_raw_price_json_l20) as _f_l20:
        _raw_map_l20 = _json_l20.load(_f_l20)

_l20["入场价"] = _l20.apply(
    lambda row: _raw_map_l20.get(
        f"{row['ticker']}|{row['entry_date'].strftime('%Y-%m-%d')}"
    ),
    axis=1,
)

_PRICE_TIERS_L20 = [
    ("低价股 (<$20)",      lambda p: p < 20,          "#59a14f"),
    ("中价股 ($20–$100)",  lambda p: 20 <= p < 100,   "#4e79a7"),
    ("高价股 ($100–$500)", lambda p: 100 <= p < 500,  "#f28e2b"),
    ("超高价股 (>$500)",   lambda p: p >= 500,        "#e15759"),
]

def _price_tier_l20(p):
    for label, cond, _ in _PRICE_TIERS_L20:
        if cond(p):
            return label
    return "未知"

def _price_color_l20(p):
    for _, cond, color in _PRICE_TIERS_L20:
        if cond(p):
            return color
    return "#aaaaaa"

_l20_wp = _l20[_l20["入场价"].notna()].copy()
_l20_wp["价格区间"] = _l20_wp["入场价"].apply(_price_tier_l20)
_l20_wp_s = _l20_wp.sort_values("入场价")

_fig_price_l = _go_l20.Figure(_go_l20.Bar(
    y=_l20_wp_s["ticker"].tolist(),
    x=_l20_wp_s["入场价"].tolist(),
    orientation="h",
    marker_color=[_price_color_l20(p) for p in _l20_wp_s["入场价"].tolist()],
    text=[f"${p:.0f}" for p in _l20_wp_s["入场价"].tolist()],
    textposition="outside",
    customdata=[
        [row["entry_date"].strftime("%Y-%m-%d"), f"{row['pnl_r_multiple']:.2f}R", row["价格区间"]]
        for _, row in _l20_wp_s.iterrows()
    ],
    hovertemplate=(
        "<b>%{y}</b><br>真实买入价：$%{x:.2f}<br>"
        "入场日期：%{customdata[0]}<br>R 倍数：%{customdata[1]}<br>"
        "价格区间：%{customdata[2]}<extra></extra>"
    ),
))
_fig_price_l.update_layout(
    title="Top 20 大亏家入场当日真实市场价（已还原拆股）",
    xaxis_title="真实买入价（$）",
    height=540,
    margin=dict(l=80, r=90, t=50, b=40),
    showlegend=False,
)
st.plotly_chart(_fig_price_l, use_container_width=True)

_tier_cnt_l = _l20_wp["价格区间"].value_counts() if not _l20_wp.empty else {}
_pt_cols_l = st.columns(4)
for _ptc_l, (label, _, _c) in zip(_pt_cols_l, _PRICE_TIERS_L20):
    _ptc_l.metric(label, f"{_tier_cnt_l.get(label, 0)} 笔")

if not _l20_wp.empty:
    _med_pl = float(_l20_wp["入场价"].median())
    _max_pl = float(_l20_wp["入场价"].max())
    _min_pl = float(_l20_wp["入场价"].min())
    st.markdown(
        f"中位数 **${_med_pl:.0f}**，区间 **${_min_pl:.0f} – ${_max_pl:.0f}**（真实市场价，已还原拆股）。"
    )
else:
    st.info("股价数据获取失败，请检查网络连接。")

# ── 明细表 ────────────────────────────────────────────────────────────────────
_l20_show = _l20.sort_values("pnl_r_multiple")[[
    "ticker", "行业", "类别", "entry_date", "exit_date", "holding_days",
    "pnl_r_multiple", "net_pnl", "入场价", "gap_adjusted_loss_multiple", "卖出原因", "入场年份",
]].copy().reset_index(drop=True)
_l20_show.columns = ["标的", "行业", "类别", "买入日期", "卖出日期", "持仓天数",
                     "R 倍数", "净亏损($)", "真实买入价($)", "实际R(含跳空)", "卖出原因", "入场年份"]
_l20_show["买入日期"]      = _l20_show["买入日期"].dt.strftime("%Y-%m-%d")
_l20_show["卖出日期"]      = _l20_show["卖出日期"].dt.strftime("%Y-%m-%d")
_l20_show["净亏损($)"]     = _l20_show["净亏损($)"].map(lambda v: f"${v:+,.0f}")
_l20_show["R 倍数"]        = _l20_show["R 倍数"].map(lambda v: f"{v:.2f}R")
_l20_show["真实买入价($)"] = _l20_show["真实买入价($)"].map(
    lambda v: f"${v:.2f}" if v is not None and v == v else "—"
)
_l20_show["实际R(含跳空)"] = _l20_show["实际R(含跳空)"].map(
    lambda v: f"{v:.2f}R" if v == v else "—"
)

with st.expander("📋 Top 20 大亏家明细", expanded=True):
    st.dataframe(_l20_show, use_container_width=True, hide_index=True)

# ── 共性总结 ──────────────────────────────────────────────────────────────────
_l20_yr_top3 = _l20["入场年份"].value_counts().nlargest(3)
_lyr_str  = "、".join([f"{int(yr)}年({int(cnt)}笔)" for yr, cnt in _l20_yr_top3.items()])
_exit_dist = _l20["卖出原因"].value_counts()
_exit_str  = "、".join([f"{reason}({cnt}笔)" for reason, cnt in _exit_dist.items()])
_hold_note = (
    f"大亏家持仓更长（{_l20_avg_hold:.0f} vs {_l20_all_loss_avg:.0f} 天），某些交易在慢慢亏损后才止损"
    if _l20_avg_hold > _l20_all_loss_avg + 5
    else f"大亏家与普通亏损持仓相近（{_l20_avg_hold:.0f} vs {_l20_all_loss_avg:.0f} 天），止损执行及时"
)
_cat_note = (
    "个股风险更大，大亏家以股票为主" if _l20_n_stocks >= 15
    else f"股票 {_l20_n_stocks} 笔 / ETF {len(_l20) - _l20_n_stocks} 笔，ETF 也存在较大回撤"
)

st.markdown(f"""
**共性总结：**

| 维度 | 数据 | 解读 |
|------|------|------|
| 退出方式 | {_exit_str} | {"大亏家主要由初始止损退出，风控在正常运作，截断亏损逻辑有效" if _l20_n_stoploss >= 12 else f"退市/并购导致 {_l20_n_delisted} 笔异常亏损，为不可控风险（公司事件）"} |
| 持仓时长 | 平均 {_l20_avg_hold:.0f} 天（中位 {_l20_med_hold:.0f} 天），区间 [{_l20_min_hold}–{_l20_max_hold}] 天 | {_hold_note} |
| 跳空风险 | {_l20_n_gap} 笔止损被跳空穿透（实际 > 1R 亏损）/ {_l20_n_delisted} 笔退市 | {"跳空和退市是超额亏损的主因，属于单笔风险中的尾部事件" if (_l20_n_gap + _l20_n_delisted) > 3 else "跳空穿透较少，止损执行质量良好"} |
| 资产类别 | {_l20_n_stocks} 只股票 / {len(_l20) - _l20_n_stocks} 只 ETF | {_cat_note} |
| 年份集中度 | 集中于 {_lyr_str} | 大亏家往往出现在特定市场环境（熊市或黑天鹅事件），与整体市场条件相关 |
""")

st.markdown("---")

st.subheader("逐年回报对比 & 逐年交易笔数")

# ── Annual returns + Trades per year (shared x-axis) ─────────────────────────
from plotly.subplots import make_subplots as _msp_ay
import plotly.graph_objects as _go_ay
import pandas as _pd_ar

_nav_ar = res.nav.copy()
if not isinstance(_nav_ar.index, _pd_ar.DatetimeIndex):
    _nav_ar.index = _pd_ar.to_datetime(_nav_ar.index)
_strat_ann = _nav_ar.resample("YE").last().pct_change().dropna()
_strat_ann.index = _strat_ann.index.year
_cur_yr_ar  = _nav_ar.index[-1].year
_strat_ann  = _strat_ann[_strat_ann.index < _cur_yr_ar]
_pos_yr_ar  = int((_strat_ann > 0).sum())
_n_yr_ar    = len(_strat_ann)
_trades_per_yr = m.get("trades_per_year", 0)

_has_spy_ay = res.spy_nav is not None
if _has_spy_ay:
    _spy_ann    = res.spy_nav.resample("YE").last().pct_change().dropna()
    _spy_ann.index = _spy_ann.index.year
    _common_yrs = _strat_ann.index.intersection(_spy_ann.index)

_tr_df_ay = res.trades.copy()
_tr_df_ay["year"] = _tr_df_ay["exit_date"].dt.year

_fig_ay = _msp_ay(
    rows=2, cols=1, shared_xaxes=True,
    row_heights=[0.55, 0.45], vertical_spacing=0.06,
    subplot_titles=["逐年回报对比", "逐年交易笔数"],
)

# Row 1 — annual returns
if _has_spy_ay:
    _fig_ay.add_trace(_go_ay.Bar(
        x=list(_common_yrs), y=(_spy_ann.loc[_common_yrs] * 100).tolist(),
        name="SPY", marker_color="#888888", opacity=0.7, offsetgroup="spy",
        hovertemplate="%{x}年<br>SPY: %{y:+.1f}%<extra></extra>",
    ), row=1, col=1)

_fig_ay.add_trace(_go_ay.Bar(
    x=list(_strat_ann.index), y=(_strat_ann.values * 100).tolist(),
    name="策略1.0",
    marker_color=["#2ca02c" if v >= 0 else "#d62728" for v in _strat_ann.values],
    opacity=0.85, offsetgroup="strat",
    text=[f"{v*100:+.1f}%" for v in _strat_ann.values],
    textposition="outside", textfont=dict(size=9), cliponaxis=False,
    hovertemplate="%{x}年<br>策略1.0: %{y:+.1f}%<extra></extra>",
), row=1, col=1)
_fig_ay.add_hline(y=0, line_color="#333", line_width=0.8, row=1, col=1)

# Row 2 — trades per year (manually stacked via base)
_reason_cfg_ay = [
    ("trailing_stop",   "#1f77b4", "移动止盈"),
    ("stop_loss",       "#d62728", "固定止损"),
    ("end_of_backtest", "#aaaaaa", "回测结束"),
]
_all_yrs_ay = sorted(_tr_df_ay["year"].unique())
_base_ay = {yr: 0 for yr in _all_yrs_ay}
for _rsn_ay, _rclr_ay, _rlbl_ay in _reason_cfg_ay:
    _sub_ay = _tr_df_ay[_tr_df_ay["exit_reason"] == _rsn_ay].groupby("year").size()
    _y_ay   = [int(_sub_ay.get(yr, 0)) for yr in _all_yrs_ay]
    _b_ay   = [_base_ay[yr] for yr in _all_yrs_ay]
    if sum(_y_ay) == 0:
        continue
    _fig_ay.add_trace(_go_ay.Bar(
        x=_all_yrs_ay, y=_y_ay, base=_b_ay,
        name=_rlbl_ay, marker_color=_rclr_ay, offsetgroup="trades",
        hovertemplate=f"%{{x}}年<br>{_rlbl_ay}: %{{y}} 笔<extra></extra>",
    ), row=2, col=1)
    for _j_ay, _yr_ay in enumerate(_all_yrs_ay):
        _base_ay[_yr_ay] += _y_ay[_j_ay]

_avg_tr_ay = float(_tr_df_ay.groupby("year").size().mean())
_fig_ay.add_hline(
    y=_avg_tr_ay, line_dash="dot", line_color="#555", line_width=1,
    annotation_text=f"均值 {_avg_tr_ay:.0f} 笔/年",
    annotation_position="top right",
    row=2, col=1,
)

_fig_ay.update_layout(
    barmode="group",
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=60, r=20, t=80, b=40),
    height=640,
)
_fig_ay.update_yaxes(ticksuffix="%", title_text="年回报率 %", row=1, col=1)
_fig_ay.update_yaxes(title_text="交易笔数", row=2, col=1)
st.plotly_chart(_fig_ay, use_container_width=True)

st.markdown(
    f"**解读（上）：** {_n_yr_ar} 个完整年度中 **{_pos_yr_ar}** 年正收益（{_pos_yr_ar/_n_yr_ar*100:.0f}%）。"
    "策略1.0在强牛市年份因持仓不满往往落后 SPY，但下行年份（如 2008、2022）损失明显小于 SPY，"
    "体现了**截断亏损**的核心优势。"
)
st.markdown(
    f"**解读（下）：** 平均每年约 **{_trades_per_yr:.0f}** 笔交易。"
    "熊市年份（市场环境过滤器关闭大多数标的新开仓，TLT / GLD / UUP 豁免）交易笔数明显减少，"
    "牛市年份信号密集、笔数较多。"
)

st.markdown("---")

# ── R-multiple distribution ───────────────────────────────────────────────────
st.subheader("交易盈亏分布（R 倍数）")
st.plotly_chart(r_multiple_distribution(res.trades), use_container_width=True)

win_rate = m.get("win_rate", 0)
avg_win  = m.get("avg_win_r", 0)
avg_loss = m.get("avg_loss_r", 0)
pf       = m.get("profit_factor", 1)
st.markdown(f"""
**解读：** 胜率 {win_rate*100:.1f}% 看似低，但这是趋势跟踪策略1.0的**正常特征**。
关键在于平均盈利（{avg_win:+.2f}R）远大于平均亏损（{avg_loss:.2f}R），
盈亏比 {pf:.4f} > 1，期望值为正。右侧长尾（大盈利交易）是策略1.0盈利的核心来源。
""")

# ── Big-R trades table (R > 3) ────────────────────────────────────────────────
_etf_set = set(meta.etf_universe[i]["ticker"] for i in range(len(meta.etf_universe)))
_exit_reason_cn = {
    "trailing_stop":    "追踪止损",
    "stop_loss":        "初始止损",
    "end_of_backtest":  "回测截止",
    "delisted":         "退市/并购",
}
_big_r = res.trades[res.trades["pnl_r_multiple"] > 3].copy()
_big_r["类别"]     = _big_r["ticker"].apply(lambda t: "ETF" if t in _etf_set else "股票")
_big_r["卖出原因"] = _big_r["exit_reason"].map(_exit_reason_cn).fillna(_big_r["exit_reason"])
_big_r_show = _big_r[[
    "ticker", "类别", "entry_date", "exit_date", "holding_days", "pnl_r_multiple", "卖出原因"
]].copy()
_big_r_show.columns = ["标的", "类别", "买入日期", "卖出日期", "持仓天数", "R 倍数", "卖出原因"]
_big_r_show["买入日期"] = _big_r_show["买入日期"].dt.strftime("%Y-%m-%d")
_big_r_show["卖出日期"] = _big_r_show["卖出日期"].dt.strftime("%Y-%m-%d")
_big_r_show["R 倍数"]  = _big_r_show["R 倍数"].map(lambda x: f"{x:.2f}R")
_big_r_show = _big_r_show.sort_values("R 倍数", ascending=False).reset_index(drop=True)

with st.expander(f"📋 R > 3 的大盈利交易明细（共 {len(_big_r_show)} 笔）", expanded=False):
    st.dataframe(_big_r_show, use_container_width=True, hide_index=True, height=500)

st.markdown("---")

# ── Top 20 盈利交易分析 ────────────────────────────────────────────────────────
import plotly.graph_objects as _go_t20
import numpy as _np_t20

st.subheader("Top 20盈利交易分析")
st.caption("已平仓交易中 R 倍数最高的 20 笔——寻找大赢家的共性规律")

_t20 = res.trades.nlargest(20, "pnl_r_multiple").copy()
_t20["类别"]     = _t20["ticker"].apply(lambda t: "ETF" if t in _ETF_SET else "股票")
_t20["卖出原因"] = _t20["exit_reason"].map({
    "trailing_stop":   "追踪止损",
    "stop_loss":       "初始止损",
    "end_of_backtest": "回测截止",
    "delisted":        "退市/并购",
}).fillna(_t20["exit_reason"])
_t20["入场年份"] = _t20["entry_date"].dt.year

_t20_n_trailing  = int((_t20["exit_reason"] == "trailing_stop").sum())
_t20_n_stocks    = int((_t20["类别"] == "股票").sum())
_t20_avg_hold    = float(_t20["holding_days"].mean())
_t20_med_hold    = float(_t20["holding_days"].median())
_t20_min_hold    = int(_t20["holding_days"].min())
_t20_max_hold    = int(_t20["holding_days"].max())
_t20_all_win_avg = float(res.trades[res.trades["net_pnl"] > 0]["holding_days"].mean())
_t20_corr        = float(_np_t20.corrcoef(_t20["holding_days"], _t20["pnl_r_multiple"])[0, 1])

# ── R 倍数排名图（横向柱状图）────────────────────────────────────────────────
_t20_asc = _t20.sort_values("pnl_r_multiple")
_fig_t20r = _go_t20.Figure(_go_t20.Bar(
    y=[f"{row['ticker']}  ({int(row['入场年份'])})" for _, row in _t20_asc.iterrows()],
    x=_t20_asc["pnl_r_multiple"].tolist(),
    orientation="h",
    marker_color="#2ca02c",
    text=[f"{r:.1f}R" for r in _t20_asc["pnl_r_multiple"].tolist()],
    textposition="outside",
))
_fig_t20r.update_layout(
    title="Top 20 大赢家 R 倍数（括号内为入场年份）",
    xaxis_title="R 倍数",
    height=560,
    margin=dict(l=140, r=80, t=50, b=40),
    showlegend=False,
)
st.plotly_chart(_fig_t20r, use_container_width=True)

# ── 指标行 ────────────────────────────────────────────────────────────────────
_tm1, _tm2, _tm3, _tm4 = st.columns(4)
with _tm1:
    st.metric("追踪止损退出",
              f"{_t20_n_trailing} / 20  ({_t20_n_trailing / 20 * 100:.0f}%)",
              help="大赢家通过追踪止损离场 = 让利润奔跑到趋势结束")
with _tm2:
    st.metric("平均持仓天数",
              f"{_t20_avg_hold:.0f} 天",
              delta=f"vs 全部盈利交易 {_t20_all_win_avg:.0f} 天",
              help="大赢家是否比普通盈利交易持仓更久？")
with _tm3:
    st.metric("持仓区间",
              f"{_t20_min_hold} – {_t20_max_hold} 天",
              help="最短与最长持仓天数")
with _tm4:
    st.metric("股票 / ETF",
              f"{_t20_n_stocks} : {len(_t20) - _t20_n_stocks}",
              help="大赢家的资产类别分布")

# ── 持仓天数 vs R 倍数 散点图 + 年份分布 ──────────────────────────────────────
_tca, _tcb = st.columns(2)

with _tca:
    _fig_scatter = _go_t20.Figure(_go_t20.Scatter(
        x=_t20["holding_days"].tolist(),
        y=_t20["pnl_r_multiple"].tolist(),
        mode="markers+text",
        text=_t20["ticker"].tolist(),
        textposition="top center",
        marker=dict(size=10, color="#2ca02c"),
    ))
    _fig_scatter.add_annotation(
        text=f"相关系数 r = {_t20_corr:.2f}",
        xref="paper", yref="paper", x=0.98, y=0.05,
        showarrow=False, align="right",
        bgcolor="wheat", bordercolor="#ccc", borderwidth=1,
        font=dict(size=11),
    )
    _fig_scatter.update_layout(
        title="持仓天数 vs R 倍数（大赢家）",
        xaxis_title="持仓天数",
        yaxis_title="R 倍数",
        height=380,
        margin=dict(l=50, r=30, t=50, b=40),
    )
    st.plotly_chart(_fig_scatter, use_container_width=True)

with _tcb:
    _t20_yr = _t20["入场年份"].value_counts().sort_index()
    _fig_yr = _go_t20.Figure(_go_t20.Bar(
        x=_t20_yr.index.tolist(),
        y=_t20_yr.values.tolist(),
        marker_color="#f28e2b",
        text=_t20_yr.values.tolist(),
        textposition="outside",
    ))
    _fig_yr.update_layout(
        title="大赢家入场年份分布",
        xaxis_title="入场年份",
        yaxis_title="笔数",
        height=380,
        margin=dict(l=50, r=30, t=50, b=40),
    )
    st.plotly_chart(_fig_yr, use_container_width=True)

# ── 行业分布 ──────────────────────────────────────────────────────────────────
_SECTOR_CN_T20 = {
    "Technology":             "科技",
    "Healthcare":             "医疗健康",
    "Consumer Cyclical":      "消费（周期）",
    "Consumer Defensive":     "消费（防御）",
    "Financial Services":     "金融",
    "Basic Materials":        "基础材料",
    "Energy":                 "能源",
    "Industrials":            "工业",
    "Real Estate":            "房地产",
    "Communication Services": "通信服务",
    "Utilities":              "公用事业",
}
_etf_cat_t20 = {e["ticker"]: f"ETF-{e.get('category', '其他')}" for e in meta.etf_universe}

@st.cache_data(ttl=86400 * 7, show_spinner="正在查询行业分类…")
def _get_sector_map_t20(tickers: tuple) -> dict:
    import yfinance as _yf
    result = {}
    for tk in tickers:
        try:
            raw = _yf.Ticker(tk).info.get("sector") or ""
            result[tk] = _SECTOR_CN_T20.get(raw, raw or "未知")
        except Exception:
            result[tk] = "未知"
    return result

_stock_tkrs_t20 = tuple(
    row["ticker"] for _, row in _t20.iterrows() if row["类别"] != "ETF"
)
_sec_map_t20 = _get_sector_map_t20(_stock_tkrs_t20)

_t20["行业"] = _t20.apply(
    lambda row: (
        _etf_cat_t20.get(row["ticker"], "ETF")
        if row["类别"] == "ETF"
        else _sec_map_t20.get(row["ticker"], "未知")
    ),
    axis=1,
)

_sec_grp = (
    _t20.groupby("行业", sort=False)
    .agg(
        笔数  = ("ticker", "count"),
        合计R = ("pnl_r_multiple", "sum"),
        标的  = ("ticker", lambda x: "、".join(x.tolist())),
    )
    .reset_index()
    .sort_values("笔数", ascending=False)
)

st.markdown("#### 行业分布")
_sec_colors = [
    "#4e79a7","#f28e2b","#e15759","#76b7b2","#59a14f",
    "#edc948","#b07aa1","#ff9da7","#9c755f","#bab0ac",
]
_col_pie, _col_bar = st.columns(2)

with _col_pie:
    _fig_sec_pie = _go_t20.Figure(_go_t20.Pie(
        labels=_sec_grp["行业"].tolist(),
        values=_sec_grp["笔数"].tolist(),
        hole=0.38,
        marker_colors=_sec_colors[:len(_sec_grp)],
        customdata=[[r, s] for r, s in zip(_sec_grp["合计R"].tolist(), _sec_grp["标的"].tolist())],
        hovertemplate=(
            "<b>%{label}</b><br>笔数：%{value}<br>"
            "合计 R：%{customdata[0]:.1f}R<br>标的：%{customdata[1]}<extra></extra>"
        ),
        textinfo="label+value",
        textfont_size=12,
    ))
    _fig_sec_pie.update_layout(
        title="行业分布（交易笔数）",
        height=400,
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=False,
    )
    st.plotly_chart(_fig_sec_pie, use_container_width=True)

with _col_bar:
    _sec_grp_s = _sec_grp.sort_values("合计R")
    _fig_sec_bar = _go_t20.Figure(_go_t20.Bar(
        y=_sec_grp_s["行业"].tolist(),
        x=_sec_grp_s["合计R"].tolist(),
        orientation="h",
        marker_color="#2ca02c",
        text=[f"{v:.1f}R" for v in _sec_grp_s["合计R"].tolist()],
        textposition="outside",
        customdata=_sec_grp_s["标的"].tolist(),
        hovertemplate="<b>%{y}</b><br>合计 R：%{x:.1f}R<br>标的：%{customdata}<extra></extra>",
    ))
    _fig_sec_bar.update_layout(
        title="各行业合计 R 倍数",
        xaxis_title="合计 R",
        height=400,
        margin=dict(l=120, r=70, t=50, b=40),
        showlegend=False,
    )
    st.plotly_chart(_fig_sec_bar, use_container_width=True)

_sec_grp_show = _sec_grp.copy()
_sec_grp_show.columns = ["行业 / 类别", "笔数", "合计 R", "包含标的"]
_sec_grp_show["合计 R"] = _sec_grp_show["合计 R"].map(lambda v: f"{v:.1f}R")
st.dataframe(_sec_grp_show, use_container_width=True, hide_index=True)

# ── 买入股价分布（还原拆股后的真实市场价）────────────────────────────────────────────
st.markdown("#### 买入股价分布（入场当日真实市场价，已还原拆股）")
st.caption(
    "价格直接来自 Tiingo 原始历史数据（`close` 字段 = 当日真实收盘价，未做任何拆股或股息调整）。"
    "例如 AAPL 2004-08-27 真实价格 **$34.35**；BB 2003-09-29 真实价格 **$38.50**。"
    "与策略 `min_price=$10` 过滤器使用同一列数据，口径完全一致。"
)

import json as _json_t20
_raw_price_json_t20 = _results_path / "top20_raw_entry_prices.json"
_raw_map_t20: dict = {}
if _raw_price_json_t20.exists():
    with open(_raw_price_json_t20) as _f_t20:
        _raw_map_t20 = _json_t20.load(_f_t20)

_t20["入场价"] = _t20.apply(
    lambda row: _raw_map_t20.get(
        f"{row['ticker']}|{row['entry_date'].strftime('%Y-%m-%d')}"
    ),
    axis=1,
)

_PRICE_TIERS = [
    ("低价股 (<$20)",       lambda p: p < 20,           "#59a14f"),
    ("中价股 ($20–$100)",   lambda p: 20 <= p < 100,    "#4e79a7"),
    ("高价股 ($100–$500)",  lambda p: 100 <= p < 500,   "#f28e2b"),
    ("超高价股 (>$500)",    lambda p: p >= 500,         "#e15759"),
]

def _price_tier(p):
    for label, cond, _ in _PRICE_TIERS:
        if cond(p):
            return label
    return "未知"

def _price_color(p):
    for _, cond, color in _PRICE_TIERS:
        if cond(p):
            return color
    return "#aaaaaa"

_t20_wp = _t20[_t20["入场价"].notna()].copy()
_t20_wp["价格区间"] = _t20_wp["入场价"].apply(_price_tier)
_t20_wp_s = _t20_wp.sort_values("入场价")

_fig_price = _go_t20.Figure(_go_t20.Bar(
    y=_t20_wp_s["ticker"].tolist(),
    x=_t20_wp_s["入场价"].tolist(),
    orientation="h",
    marker_color=[_price_color(p) for p in _t20_wp_s["入场价"].tolist()],
    text=[f"${p:.0f}" for p in _t20_wp_s["入场价"].tolist()],
    textposition="outside",
    customdata=[
        [row["entry_date"].strftime("%Y-%m-%d"), f"{row['pnl_r_multiple']:.2f}R", row["价格区间"]]
        for _, row in _t20_wp_s.iterrows()
    ],
    hovertemplate=(
        "<b>%{y}</b><br>"
        "真实买入价：$%{x:.2f}<br>"
        "入场日期：%{customdata[0]}<br>"
        "R 倍数：%{customdata[1]}<br>"
        "价格区间：%{customdata[2]}<extra></extra>"
    ),
))
_fig_price.update_layout(
    title="Top 20 大赢家入场当日真实市场价（已还原拆股）",
    xaxis_title="真实买入价（$）",
    height=540,
    margin=dict(l=80, r=90, t=50, b=40),
    showlegend=False,
)
st.plotly_chart(_fig_price, use_container_width=True)

_tier_cnt = _t20_wp["价格区间"].value_counts() if not _t20_wp.empty else {}
_pt_cols = st.columns(4)
for _ptc, (label, _, color) in zip(_pt_cols, _PRICE_TIERS):
    _ptc.metric(label, f"{_tier_cnt.get(label, 0)} 笔")

if not _t20_wp.empty:
    _median_p = float(_t20_wp["入场价"].median())
    _max_p    = float(_t20_wp["入场价"].max())
    _min_p    = float(_t20_wp["入场价"].min())
    st.markdown(
        f"中位数 **${_median_p:.0f}**，区间 **${_min_p:.0f} – ${_max_p:.0f}**（真实市场价，已还原拆股）。"
    )
else:
    st.info("股价数据获取失败，请检查网络连接。")

# ── 明细表 ────────────────────────────────────────────────────────────────────
_t20_show = _t20.sort_values("pnl_r_multiple", ascending=False)[[
    "ticker", "行业", "类别", "entry_date", "exit_date", "holding_days",
    "pnl_r_multiple", "net_pnl", "入场价", "卖出原因", "入场年份",
]].copy().reset_index(drop=True)
_t20_show.columns = ["标的", "行业", "类别", "买入日期", "卖出日期", "持仓天数",
                     "R 倍数", "净盈亏($)", "真实买入价($)", "卖出原因", "入场年份"]
_t20_show["买入日期"]    = _t20_show["买入日期"].dt.strftime("%Y-%m-%d")
_t20_show["卖出日期"]    = _t20_show["卖出日期"].dt.strftime("%Y-%m-%d")
_t20_show["净盈亏($)"]   = _t20_show["净盈亏($)"].map(lambda v: f"${v:,.0f}")
_t20_show["R 倍数"]      = _t20_show["R 倍数"].map(lambda v: f"{v:.2f}R")
_t20_show["真实买入价($)"] = _t20_show["真实买入价($)"].map(
    lambda v: f"${v:.2f}" if v is not None and v == v else "—"
)

with st.expander("📋 Top 20 大赢家明细", expanded=True):
    st.dataframe(_t20_show, use_container_width=True, hide_index=True)

# ── 共性总结 ──────────────────────────────────────────────────────────────────
_t20_yr_top3 = _t20["入场年份"].value_counts().nlargest(3)
_yr_str = "、".join([f"{int(yr)}年({int(cnt)}笔)" for yr, cnt in _t20_yr_top3.items()])
_etf_note = (
    "股票贡献了绝大多数大赢家，个股爆发力远超 ETF"
    if _t20_n_stocks > len(_t20) - _t20_n_stocks
    else f"股票与 ETF 均有贡献（{_t20_n_stocks} vs {len(_t20) - _t20_n_stocks}）"
)
st.markdown(f"""
**共性总结：**

| 维度 | 数据 | 解读 |
|------|------|------|
| 退出方式 | {_t20_n_trailing}/20 笔（{_t20_n_trailing / 20 * 100:.0f}%）为追踪止损 | 大赢家几乎全靠"让利润奔跑"，极少被初始止损打出 |
| 持仓时长 | 平均 {_t20_avg_hold:.0f} 天（中位 {_t20_med_hold:.0f} 天），区间 [{_t20_min_hold}–{_t20_max_hold}] 天 | 比全部盈利交易均值（{_t20_all_win_avg:.0f} 天）长出 {_t20_avg_hold - _t20_all_win_avg:.0f} 天；**持仓时间越长 R 越大**（r={_t20_corr:.2f}） |
| 资产类别 | {_t20_n_stocks} 只股票 / {len(_t20) - _t20_n_stocks} 只 ETF | {_etf_note} |
| 年份集中度 | 集中于 {_yr_str} | 大赢家往往出现在特定行情年份，验证了顺势交易的核心逻辑 |
""")

st.markdown("---")

# ── Profit by type: stock vs ETF ──────────────────────────────────────────────
st.subheader("盈利来源：股票 vs ETF")
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

# ── 盈利集中度 ──────────────────────────────────────────────────────────────────
import plotly.graph_objects as _go_c2

_tk_c2 = res.trades.groupby("ticker").agg(
    交易次数=("net_pnl", "count"),
    总盈亏  =("net_pnl", "sum"),
    胜率    =("net_pnl", lambda x: (x > 0).mean()),
    平均R   =("pnl_r_multiple", "mean"),
    最大R   =("pnl_r_multiple", "max"),
).reset_index()
_tk_c2["类别"] = _tk_c2["ticker"].apply(lambda t: "ETF" if t in _ETF_SET else "股票")

_n_ta_c2     = res.trades["ticker"].nunique()
_pos_pnl_c2  = float(_tk_c2[_tk_c2["总盈亏"] > 0]["总盈亏"].sum())
_n_profit_c2 = int((_tk_c2["总盈亏"] > 0).sum())
_n_loss_c2   = int((_tk_c2["总盈亏"] <= 0).sum())

st.markdown("#### 盈利集中度")
_top20_c2 = _tk_c2.nlargest(20, "总盈亏")
_fig_top20_c2 = _go_c2.Figure(_go_c2.Bar(
    y=_top20_c2["ticker"].tolist()[::-1],
    x=(_top20_c2["总盈亏"] / 1e6).tolist()[::-1],
    orientation="h",
    marker_color=["#2ca02c" if v > 0 else "#d62728"
                  for v in _top20_c2["总盈亏"].tolist()[::-1]],
    text=[f"${v:.1f}M" for v in (_top20_c2["总盈亏"] / 1e6).tolist()[::-1]],
    textposition="outside",
))
_fig_top20_c2.update_layout(
    title="累计净盈亏 TOP 20 标的",
    xaxis_title="净盈亏（$M）",
    height=520,
    margin=dict(l=70, r=80, t=50, b=40),
    showlegend=False,
)
st.plotly_chart(_fig_top20_c2, use_container_width=True)

_top5_c2   = float(_tk_c2.nlargest(5,  "总盈亏")["总盈亏"].sum())
_top10_c2  = float(_tk_c2.nlargest(10, "总盈亏")["总盈亏"].sum())
_top20_c2v = float(_tk_c2.nlargest(20, "总盈亏")["总盈亏"].sum())
st.markdown(f"""
实际交易的 {_n_ta_c2:,} 个标的中，**{_n_profit_c2:,} 个**（{_n_profit_c2/_n_ta_c2*100:.0f}%）净盈利，**{_n_loss_c2:,} 个**净亏损。

| 维度 | 金额 | 占全部净盈利比例 |
|------|------|----------------|
| TOP 5 标的 | ${_top5_c2/1e6:.1f}M | {_top5_c2/_pos_pnl_c2*100:.0f}% |
| TOP 10 标的 | ${_top10_c2/1e6:.1f}M | {_top10_c2/_pos_pnl_c2*100:.0f}% |
| TOP 20 标的 | ${_top20_c2v/1e6:.1f}M | {_top20_c2v/_pos_pnl_c2*100:.0f}% |

这是趋势跟踪的核心统计特征：**少数大赢标的贡献绝大多数利润**，整体正期望来自右尾效应。
""")

with st.expander("📋 亏损最大的 10 个标的", expanded=False):
    _bot10_c2 = _tk_c2.nsmallest(10, "总盈亏")[
        ["ticker", "类别", "交易次数", "总盈亏", "胜率", "平均R"]
    ].copy()
    _bot10_c2["总盈亏"] = _bot10_c2["总盈亏"].map(lambda v: f"${v:+,.0f}")
    _bot10_c2["胜率"]   = _bot10_c2["胜率"].map(lambda v: f"{v*100:.0f}%")
    _bot10_c2["平均R"]  = _bot10_c2["平均R"].map(lambda v: f"{v:.2f}R")
    st.dataframe(_bot10_c2, use_container_width=True, hide_index=True)

st.markdown("---")

# ── 平价保护分析 ──────────────────────────────────────────────────────────────
import numpy as _np_be
import pandas as _pd_be

_BE_CSV = _results_path / "breakeven_scenarios.csv"

def _be_csv_key() -> str:
    if not _BE_CSV.exists():
        return "missing"
    import hashlib as _hl
    with open(_BE_CSV, "rb") as _f:
        return _hl.md5(_f.read()).hexdigest()

_BE_KEY = _be_csv_key()


@st.cache_data(ttl=86400)
def _load_be_scenarios(_key: str):
    if _key == "missing":
        return None
    return _pd_be.read_csv(
        _BE_CSV,
        parse_dates=["entry_date", "orig_exit_date",
                     "be1r_exit_date", "be15r_exit_date", "be2r_exit_date"],
    )


def _render_breakeven():
    st.subheader("平价保护分析")
    st.markdown("""
**平价保护**（Breakeven Protection）：开仓后，一旦浮盈达到设定阈值，将追踪止损上移至略高于开仓价格的位置，使出场时净盈利 ≈ +$1（扣除滑点和佣金后）。其他策略设置（过滤条件、仓位管理、执行与成本假设）均保持不变。

本分析对所有已执行信号分别模拟三种平价保护规则：

| 规则 | 触发条件 | 止损调整 |
|------|----------|----------|
| 平价保护 1R | 浮盈（以最高价计）≥ 1×R | 追踪止损上移至略高于开仓价格的位置（净盈利 ≈ +$1） |
| 平价保护 1.5R | 浮盈（以最高价计）≥ 1.5×R | 追踪止损上移至略高于开仓价格的位置（净盈利 ≈ +$1） |
| 平价保护 2R | 浮盈（以最高价计）≥ 2×R | 追踪止损上移至略高于开仓价格的位置（净盈利 ≈ +$1） |

**策略参数提示**：本策略止损为 2×ATR，追踪止损倍数为 3×ATR。当浮盈恰好为 1.5R 时，追踪止损 = 最高价 − 3×ATR = (开仓价 + 1.5R) − 3×ATR = (开仓价 + 3×ATR) − 3×ATR = 开仓价。即原始追踪止损在浮盈达到 1.5R 时自然等于开仓价，因此平价保护 1.5R 和 2R 的实际效果极为有限。
""")

    _be = _load_be_scenarios(_BE_KEY)
    if _be is None:
        st.info("平价保护分析数据不在当前运行环境中。请在本地运行 `python src/scripts/compute_breakeven_scenarios.py` 后重新部署。")
        return

    _nav_orig = res.nav  # pd.Series, DatetimeIndex

    def _build_nav(_lbl: str):
        _dc = f"{_lbl}_exit_date"
        _pc = f"{_lbl}_net_pnl"
        _tc = f"{_lbl}_triggered"
        _mask = _be[_tc] & _be[_dc].notna() & (_be[_dc] < _be["orig_exit_date"])
        _ch   = _be[_mask]
        _d    = _pd_be.Series(0.0, index=_nav_orig.index, dtype=float)
        for _dt, _v in _ch.groupby("orig_exit_date")["orig_net_pnl"].sum().items():
            if _dt in _d.index:
                _d[_dt] -= _v
        for _dt, _v in _ch.groupby(_dc)[_pc].sum().items():
            if _dt in _d.index:
                _d[_dt] += _v
        return _nav_orig + _d.cumsum()

    _navs = {
        "原始策略":      _nav_orig,
        "平价保护 1R":   _build_nav("be1r"),
        "平价保护 1.5R": _build_nav("be15r"),
        "平价保护 2R":   _build_nav("be2r"),
    }

    # ── Metrics + win rate ────────────────────────────────────────────────────
    def _cagr(_nav):
        _ny = (_nav.index[-1] - _nav.index[0]).days / 365.25
        return (_nav.iloc[-1] / _nav.iloc[0]) ** (1.0 / _ny) - 1

    def _maxdd(_nav):
        return ((_nav - _nav.cummax()) / _nav.cummax()).min()

    def _winrate(_lbl: str):
        if _lbl == "orig":
            return (_be["orig_net_pnl"] > 0).mean()
        _dc = f"{_lbl}_exit_date"
        _pc = f"{_lbl}_net_pnl"
        _tc = f"{_lbl}_triggered"
        _mask = _be[_tc] & _be[_dc].notna() & (_be[_dc] < _be["orig_exit_date"])
        _pnl  = _be["orig_net_pnl"].copy()
        _pnl[_mask] = _be.loc[_mask, _pc]
        return (_pnl > 0).mean()

    def _max_consec(_lbl: str) -> int:
        if _lbl == "orig":
            _pnl_arr = _be.sort_values("orig_exit_date")["orig_net_pnl"].values
        else:
            _dc = f"{_lbl}_exit_date"
            _pc = f"{_lbl}_net_pnl"
            _tc = f"{_lbl}_triggered"
            _mask = _be[_tc] & _be[_dc].notna() & (_be[_dc] < _be["orig_exit_date"])
            _dates = _be["orig_exit_date"].copy()
            _pnls  = _be["orig_net_pnl"].copy()
            _dates[_mask] = _be.loc[_mask, _dc]
            _pnls[_mask]  = _be.loc[_mask, _pc]
            _pnl_arr = _pnls.iloc[_np_be.argsort(_dates.values)].values
        _mx = _cur = 0
        for _v in _pnl_arr:
            if _v <= 0:
                _cur += 1
                _mx = max(_mx, _cur)
            else:
                _cur = 0
        return _mx

    _orig_c = _cagr(_nav_orig)
    _orig_d = _maxdd(_nav_orig)

    _m_rows = []
    for (_nm, _nav), _lbl_wr in zip(_navs.items(), ["orig", "be1r", "be15r", "be2r"]):
        _c  = _cagr(_nav)
        _d  = _maxdd(_nav)
        _w  = _winrate(_lbl_wr)
        _mc = _max_consec(_lbl_wr)
        _row = {"方案": _nm, "年化收益 CAGR": f"{_c*100:.2f}%"}
        if _nm == "原始策略":
            _row["CAGR 变化"]          = "—"
            _row["胜率"]               = f"{_w*100:.1f}%"
            _row["最大回撤"]           = f"{_d*100:.2f}%"
            _row["最大回撤变化"]       = "—"
            _row["最长连续亏损次数"]   = str(_mc)
        else:
            _dc2 = (_c - _orig_c) * 100
            _dd2 = (_d - _orig_d) * 100
            _row["CAGR 变化"]          = f"{'+' if _dc2 >= 0 else ''}{_dc2:.2f} pp"
            _row["胜率"]               = f"{_w*100:.1f}%"
            _row["最大回撤"]           = f"{_d*100:.2f}%"
            _row["最大回撤变化"]       = f"{'+' if _dd2 >= 0 else ''}{_dd2:.2f} pp"
            _row["最长连续亏损次数"]   = str(_mc)
        _m_rows.append(_row)

    st.markdown("**各方案指标对比**")
    st.dataframe(_pd_be.DataFrame(_m_rows), use_container_width=True, hide_index=True)

    # ── Trade impact breakdown ────────────────────────────────────────────────
    _total = len(_be)
    st.markdown(f"**平价保护触发情况（共 {_total:,} 笔已执行交易）**")
    _imp = []
    for _lbl2, _name in [("be1r", "1R"), ("be15r", "1.5R"), ("be2r", "2R")]:
        _dc3 = f"{_lbl2}_exit_date"
        _tc3 = f"{_lbl2}_triggered"
        _n_trig  = int(_be[_tc3].sum())
        _n_early = int((_be[_tc3] & _be[_dc3].notna() & (_be[_dc3] < _be["orig_exit_date"])).sum())
        _imp.append({
            "阈值": _name,
            "曾触发": f"{_n_trig} 笔 ({_n_trig/_total*100:.0f}%)",
            "实际提前出场": f"{_n_early} 笔 ({_n_early/_total*100:.1f}%)",
        })
    st.dataframe(_pd_be.DataFrame(_imp), use_container_width=True, hide_index=True)

    st.markdown(
        "注：「曾触发」= 该交易浮盈曾达到阈值（止损已上移至略高于开仓价格的位置）。"
        "「实际提前出场」= 平价保护使退出日期早于原始策略。"
        "触发但未提前出场 = 浮盈达到阈值后价格继续上涨，原始追踪止损已高于平价保护止损价，平价保护无额外保护作用。"
    )


_render_breakeven()
st.markdown("---")

# ── 开仓K线强度分析 ─────────────────────────────────────────────────────────────
import numpy as _np_ks
import pandas as _pd_ks

_SIM_CSV = _results_path / "all_signals_simulated.csv"
_SIM_MTIME = int(_SIM_CSV.stat().st_mtime) if _SIM_CSV.exists() else 0

@st.cache_data(ttl=86400)
def _load_sim_signals(_mtime: int):
    if _mtime == 0:
        return None
    _df = _pd_ks.read_csv(_SIM_CSV, parse_dates=["signal_date", "entry_date", "exit_date"])
    return _df[~_df["gap_filtered"]].reset_index(drop=True)

def _render_kstrength():
    import plotly.graph_objects as _go_ks_i
    from scipy.stats import pearsonr as _pearsonr, spearmanr as _spearmanr

    _sim = _load_sim_signals(_SIM_MTIME)
    _ks_total = len(res.trades)

    st.subheader("开仓K线强度分析")
    st.markdown("""
**开仓K线强度** 定义为开仓信号产生当天的日涨幅（使用复权收盘价）：

开仓K线强度 = （信号日收盘价 − 前一日收盘价）÷ 前一日收盘价

其中**信号日** = entry_date 的前一个交易日（策略在收盘后生成信号，次日开盘执行）。
""")

    if _sim is None:
        st.info("全信号模拟数据不在当前运行环境中。请在本地运行 `src/scripts/simulate_all_signals.py` 生成数据后重新查看。")
        return

    _ex  = _sim[_sim["executed"]]
    _nex = _sim[~_sim["executed"]]

    st.markdown(f"""
本分析基于 **全量信号模拟**（`simulate_all_signals.py`），包含已执行与未执行开仓信号：
通过技术过滤器的信号共 **{len(_sim):,}** 个
（已执行 **{len(_ex):,}** 个 / 未执行 **{len(_nex):,}** 个）。
Gap > 2.5% 被过滤的信号另外 {_pd_ks.read_csv(_SIM_CSV)['gap_filtered'].sum():,} 个，未计入分析。
""")

    # ── Distribution chart ────────────────────────────────────────────────────
    _fig_dist = _go_ks_i.Figure()
    for _label, _sub, _col in [
        ("未执行", _nex, "#aec7e8"),
        ("已执行·亏损", _ex[_ex["pnl_r"] <= 0], "#d62728"),
        ("已执行·盈利", _ex[_ex["pnl_r"] > 0],  "#2ca02c"),
    ]:
        _fig_dist.add_trace(_go_ks_i.Histogram(
            x=_sub["k_strength"].clip(-2, 25),
            name=_label, marker_color=_col,
            opacity=0.7, bingroup=1, xbins=dict(size=0.5),
        ))
    _fig_dist.update_layout(
        barmode="overlay",
        title="开仓K线强度分布（已执行 vs 未执行）",
        xaxis_title="K线强度（%）", yaxis_title="信号数",
        height=360, margin=dict(l=60, r=30, t=50, b=50),
        legend=dict(orientation="h", x=0.4, y=1.14),
    )
    st.plotly_chart(_fig_dist, use_container_width=True)

    # ── Bucket analysis charts ────────────────────────────────────────────────
    def _bkt_chart(df, title, ks_mean, color_bar, color_line):
        _d = df.copy()
        _d["bucket"] = _pd_ks.cut(
            _d["k_strength"],
            bins=[-_np_ks.inf, 1, 2, 3, 5, _np_ks.inf],
            labels=["0–1%", "1–2%", "2–3%", "3–5%", "> 5%"],
        )
        _b = _d.groupby("bucket", observed=True).agg(
            n=("pnl_r", "count"),
            win_pct=("pnl_r", lambda x: (x > 0).mean() * 100),
            avg_r=("pnl_r", "mean"),
        ).reset_index()
        _lbs = _b["bucket"].astype(str).tolist()
        _fig = _go_ks_i.Figure()
        _fig.add_trace(_go_ks_i.Bar(
            x=_lbs, y=_b["win_pct"].tolist(), name="胜率（%）",
            marker_color=color_bar, yaxis="y1",
            text=[f"{v:.0f}%" for v in _b["win_pct"].tolist()],
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(color="white", size=13),
        ))
        _fig.add_trace(_go_ks_i.Scatter(
            x=_lbs, y=_b["avg_r"].tolist(), name="平均R",
            mode="lines+markers", yaxis="y2",
            marker=dict(size=8, color=color_line), line=dict(color=color_line, width=2),
        ))
        _fig.update_layout(
            title=dict(
                text=f"{title}   <span style='font-size:13px;color:#666'>（K线强度均值 {ks_mean:.2f}%，共 {len(df):,} 个信号）</span>",
                font=dict(size=14),
            ),
            xaxis_title="K线强度",
            yaxis=dict(title="胜率（%）", range=[0, 70], ticksuffix="%"),
            yaxis2=dict(title="平均R", overlaying="y", side="right", range=[-0.3, 0.8]),
            height=380, margin=dict(l=60, r=70, t=80, b=50),
            legend=dict(orientation="h", x=0.5, y=1.12),
        )
        for _lb, _nv, _wv in zip(_lbs, _b["n"].tolist(), _b["win_pct"].tolist()):
            _fig.add_annotation(
                x=_lb, y=_wv + 5, text=f"n={int(_nv)}",
                showarrow=False, font=dict(size=11, color="#444"), yref="y",
            )
        return _fig

    _c1, _c2 = st.columns(2)
    with _c1:
        st.plotly_chart(
            _bkt_chart(_sim, "全量信号（已执行 + 未执行）",
                       _sim["k_strength"].mean(), "#1f77b4", "#ff7f0e"),
            use_container_width=True,
        )
    with _c2:
        st.plotly_chart(
            _bkt_chart(_ex, "仅已执行信号",
                       _ex["k_strength"].mean(), "#2ca02c", "#d62728"),
            use_container_width=True,
        )

    # ── Correlation stats ─────────────────────────────────────────────────────
    _r_p_all, _p_p_all = _pearsonr(_sim["k_strength"], _sim["pnl_r"])
    _r_s_all, _p_s_all = _spearmanr(_sim["k_strength"], _sim["pnl_r"])
    _r_p_ex,  _       = _pearsonr(_ex["k_strength"],  _ex["pnl_r"])
    _r_s_ex,  _       = _spearmanr(_ex["k_strength"], _ex["pnl_r"])

    _cc1, _cc2, _cc3, _cc4 = st.columns(4)
    with _cc1:
        st.metric("Pearson r（全量）", f"{_r_p_all:.4f}")
    with _cc2:
        st.metric("Spearman r（全量）", f"{_r_s_all:.4f}")
    with _cc3:
        st.metric("Pearson r（已执行）", f"{_r_p_ex:.4f}")
    with _cc4:
        st.metric("Spearman r（已执行）", f"{_r_s_ex:.4f}")

    st.markdown(f"""
全量信号（n={len(_sim):,}）：Pearson r = {_r_p_all:.4f}（p = {_p_p_all:.3f}），Spearman r = {_r_s_all:.4f}（p = {_p_s_all:.3f}）。
样本量大，相关性达到统计显著，但**绝对值仅约 0.02**，说明 k_strength 只解释了约 0.05% 的收益方差——**实际预测力可忽略不计**。

各分组胜率在 33%–36% 之间，平均R也无单调趋势。
值得注意的是，**已执行信号的 k_strength 均值（{_ex['k_strength'].mean():.1f}%）高于未执行（{_nex['k_strength'].mean():.1f}%）**，
但这来自策略按**突破强度（breakout_strength = close/rolling_high）排序**优先入场，而非 k_strength 本身的筛选。

**结论：开仓K线强度与后续收益之间不存在有预测意义的关系，不建议将其用作开仓过滤条件。**
""")

_render_kstrength()

st.markdown("---")

import plotly.graph_objects as _go

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

> 趋势跟踪策略的换手率通常在每年 500%–2,000%，本策略 {turnover*100:.0f}% 处于正常范围。
""")

st.markdown("---")

# ── Holding days distribution ─────────────────────────────────────────────────
st.subheader("持仓天数分布")
st.plotly_chart(holding_days_distribution(res.trades), use_container_width=True)

_avg_hold      = m.get("avg_holding_days", 0)
_med_hold      = float(res.trades["holding_days"].median()) if "holding_days" in res.trades.columns else 0
_long_hold     = int((res.trades["holding_days"] > 60).sum()) if "holding_days" in res.trades.columns else 0
_long_hold_pct = _long_hold / len(res.trades) * 100 if len(res.trades) > 0 else 0

st.markdown(
    f"**解读：** 持仓中位数 **{_med_hold:.0f} 天**，均值 **{_avg_hold:.0f} 天**，"
    f"均值显著大于中位数，说明分布右偏——大多数交易快速止损出场（短持仓），"
    f"少数大赢家被持有较长时间（持仓 > 60 天的交易占 {_long_hold_pct:.0f}%）。"
    "这种「多次小亏、少次大赚」的持仓结构是趋势跟踪策略的典型特征。"
)

# ── Trades with holding days > 200 ────────────────────────────────────────────
_lh200 = res.trades[res.trades["holding_days"] > 200].copy()
if len(_lh200) > 0:
    _lh200["类别"] = _lh200["ticker"].apply(lambda t: "ETF" if t in _ETF_SET else "股票")
    _lh200["卖出原因"] = _lh200["exit_reason"].map({
        "trailing_stop":   "追踪止损",
        "stop_loss":       "初始止损",
        "end_of_backtest": "回测截止",
        "delisted":        "退市/并购",
    }).fillna(_lh200["exit_reason"])
    _lh200_show = _lh200[[
        "ticker", "类别", "entry_date", "exit_date", "holding_days",
        "pnl_r_multiple", "net_pnl", "卖出原因",
    ]].copy()
    _lh200_show.columns = ["标的", "类别", "开仓日期", "平仓日期", "持仓天数", "R 倍数", "净盈亏($)", "卖出原因"]
    _lh200_show["开仓日期"] = _lh200_show["开仓日期"].dt.strftime("%Y-%m-%d")
    _lh200_show["平仓日期"] = _lh200_show["平仓日期"].dt.strftime("%Y-%m-%d")
    _lh200_show["净盈亏($)"] = _lh200_show["净盈亏($)"].map(lambda v: f"${v:+,.0f}")
    _lh200_show["R 倍数"]    = _lh200_show["R 倍数"].map(lambda v: f"{v:.2f}R")
    _lh200_show = _lh200_show.sort_values("持仓天数", ascending=False).reset_index(drop=True)
    with st.expander(f"📋 持仓天数 > 200 天的交易（共 {len(_lh200_show)} 笔）", expanded=True):
        st.dataframe(_lh200_show, use_container_width=True, hide_index=True)

# ── Capital utilization ───────────────────────────────────────────────────────
st.subheader("资金使用率")

st.plotly_chart(
    capital_utilization_chart(res.trades, res.nav, meta.color),
    use_container_width=True,
)

_cash_proxy_name = meta.params_anchor.get("cash_proxy", "SHY")
st.markdown(f"""
**解读：** 纵轴为当日所有持仓标的的**入场成本之和 ÷ NAV**（百分比）。
持有 {_cash_proxy_name}（空仓代理）不计入使用率，仅持有股票或 ETF 标的时才计为"资金已投入"。

此处使用"成本基础"而非"市值"计算，对于盈利标的会小幅低估实际使用率，
但无需访问每日价格数据、可从交易记录直接推导，结果仍能准确反映资金部署节奏。

- **使用率骤降**通常对应市场进入熊市（SPY 低于 200 日均线），策略停止开仓；
- **使用率上升**对应牛市信号密集、持仓数量增多；
- 使用率长期远低于 100% 反映了趋势跟踪策略的"轻仓等待"特性——大多数资金以 {_cash_proxy_name} 形式持有，等待高质量突破信号。
""")

st.markdown("---")

# ── Daily position count ──────────────────────────────────────────────────────
st.subheader("每日持仓标的数目")
st.plotly_chart(
    daily_position_count_chart(res.trades, res.nav.index, meta.color),
    use_container_width=True,
)
_dc = res.trades.copy()
_dc["entry_date"] = _pd_ar.to_datetime(_dc["entry_date"])
_dc["exit_date"]  = _pd_ar.to_datetime(_dc["exit_date"])
_nav_idx = _pd_ar.to_datetime(res.nav.index)
_entry_c = _dc.groupby("entry_date").size().reindex(_nav_idx, fill_value=0)
_exit_c  = _dc.groupby("exit_date").size().reindex(_nav_idx, fill_value=0)
_daily_n = (_entry_c - _exit_c).cumsum().clip(lower=0)
_mean_n  = float(_daily_n.mean())
_max_n   = int(_daily_n.max())
_zero_pct= float((_daily_n == 0).mean()) * 100
st.markdown(
    f"**解读：** 回测期间每日持仓标的数量的实际分布。"
    f"全程均值约 **{_mean_n:.1f} 只**，历史峰值 **{_max_n} 只**。"
    f"空仓天数（0 只持仓）占全程约 **{_zero_pct:.1f}%**，"
    f"主要集中于熊市阶段（SPY 跌破 200 日均线时，Regime Filter 停止大多数标的新开仓（TLT / GLD / UUP 豁免）并等待旧仓止损出清）。"
    f"持仓数目随市场环境的起伏变化，体现了策略1.0在不同市场条件下的动态参与度。"
)

# ── 每日开仓 vs 放弃开仓 ──────────────────────────────────────────────────────
import pandas as _pd_es
_es_path = res.meta.results_dir / "daily_entry_stats.csv"
if _es_path.exists():
    _entry_stats = _pd_es.read_csv(_es_path, index_col="date", parse_dates=True)
    st.subheader("每日开仓信号：已开仓 vs 放弃开仓")
    st.plotly_chart(
        daily_entries_vs_skipped_chart(_entry_stats, meta.color),
        use_container_width=True,
    )
    _tot_sig = int(_entry_stats["signals"].sum())
    _tot_exe = int(_entry_stats["executed"].sum())
    _tot_skp = int(_entry_stats["skipped"].sum())
    _skip_rt = _tot_skp / _tot_sig * 100 if _tot_sig > 0 else 0
    _has_detail = all(c in _entry_stats.columns for c in ["skip_heat", "skip_corr", "skip_cash"])
    if _has_detail:
        _n_heat = int(_entry_stats["skip_heat"].sum())
        _n_corr = int(_entry_stats["skip_corr"].sum())
        _n_cash = int(_entry_stats["skip_cash"].sum())
        _n_other = _tot_skp - _n_heat - _n_corr - _n_cash
        _reason_lines = []
        if _n_cash > 0:
            _reason_lines.append(f"- **资金不足**（{_n_cash:,} 次）：已持仓耗尽可用现金，无法覆盖新仓成本；")
        if _n_heat > 0:
            _reason_lines.append(f"- **组合热度超限**（{_n_heat:,} 次）：已持仓总风险敞口接近 NAV 的 10%；")
        if _n_corr > 0:
            _reason_lines.append(f"- **相关性过高**（{_n_corr:,} 次）：候选标的与已持仓相关性 > 0.70，仓位压缩至 0；")
        if _n_other > 0:
            _reason_lines.append(f"- **其他过滤**（{_n_other:,} 次）：缺口过大、已持仓、非可交易日等；")
        _insight = ""
        if _n_heat == 0 and _n_corr == 0:
            _insight = (
                "\n\n**策略洞察：** 本配置下放弃开仓几乎完全由**资金不足**驱动，"
                "热度超限和相关性过滤均未触发。原因在于策略每笔仓位上限为 NAV 的 5%，"
                "约持满 20 笔后现金耗尽；而 10% 热度上限理论上需 ~10 笔高风险仓位才能触发，"
                "实际上现金先于热度耗尽。这说明当前参数下策略受**资金约束**而非**风险约束**限制。"
            )
        _reason_text = "\n".join(_reason_lines)
        st.markdown(
            f"**解读：** 每个月柱中，下方为被拒绝的开仓信号，上方（策略主色）为成功开仓。"
            f"全程共产生 **{_tot_sig:,}** 个开仓信号，其中 **{_tot_exe:,}** 次成功开仓，"
            f"**{_tot_skp:,}** 次（占 **{_skip_rt:.1f}%**）被放弃，细分原因如下：\n\n"
            + _reason_text
            + _insight
            + "\n\n放弃开仓率反映风控过滤器的「严格程度」——过高意味着牛市中错过较多机会，过低则风控执行不够充分。"
        )
    else:
        st.markdown(
            f"**解读：** 全程共产生 **{_tot_sig:,}** 个开仓信号，其中 **{_tot_exe:,}** 次成功开仓，"
            f"**{_tot_skp:,}** 次（占 **{_skip_rt:.1f}%**）被放弃。"
        )

st.markdown("---")

# ── Traded ticker analysis ────────────────────────────────────────────────────
import pandas as _pd_ta

_ta = res.trades.copy()
_ta["_is_etf"] = _ta["ticker"].isin(_ETF_SET)

# Per-ticker aggregated stats
_tk = _ta.groupby("ticker").agg(
    交易次数=("net_pnl", "count"),
    总盈亏  =("net_pnl", "sum"),
    胜率    =("net_pnl", lambda x: (x > 0).mean()),
    平均R   =("pnl_r_multiple", "mean"),
    最大R   =("pnl_r_multiple", "max"),
).reset_index()
_tk["类别"] = _tk["ticker"].apply(lambda t: "ETF" if t in _ETF_SET else "股票")

_ta_traded_all  = set(_ta["ticker"].unique())
_ta_traded_etf  = {t for t in _ta_traded_all if t in _ETF_SET}
_ta_traded_stk  = _ta_traded_all - _ETF_SET
_n_ta  = len(_ta_traded_all)
_n_ts  = len(_ta_traded_stk)
_n_te  = len(_ta_traded_etf)
_n_pt  = meta.universe_total
_n_ps  = meta.universe_stocks
_n_pe  = meta.universe_etfs
_pct_all = _n_ta / _n_pt * 100 if _n_pt else 0
_pct_s   = _n_ts / _n_ps * 100 if _n_ps else 0
_pct_e   = _n_te / _n_pe * 100 if _n_pe else 0

# ── 一、标的覆盖率 ────────────────────────────────────────────────────────────
st.markdown("#### 实际开仓标的覆盖率")
_tc1, _tc2, _tc3 = st.columns(3)
_tc1.metric("实际开仓标的总数", f"{_n_ta:,}",
            help=f"标的池共 {_n_pt:,} 个，覆盖率 {_pct_all:.1f}%")
_tc2.metric("其中：股票", f"{_n_ts:,}",
            help=f"股票池 {_n_ps:,} 个，覆盖率 {_pct_s:.1f}%")
_tc3.metric("其中：ETF", f"{_n_te:,}",
            help=f"ETF 池 {_n_pe:,} 个，覆盖率 {_pct_e:.1f}%")

st.dataframe(_pd_ta.DataFrame([
    {"类别": "股票", "标的池": _n_ps, "实际开仓": _n_ts,
     "覆盖率": f"{_pct_s:.1f}%", "未触发": _n_ps - _n_ts},
    {"类别": "ETF",  "标的池": _n_pe, "实际开仓": _n_te,
     "覆盖率": f"{_pct_e:.1f}%", "未触发": _n_pe - _n_te},
    {"类别": "合计", "标的池": _n_pt, "实际开仓": _n_ta,
     "覆盖率": f"{_pct_all:.1f}%", "未触发": _n_pt - _n_ta},
]), use_container_width=True, hide_index=True)
st.caption(
    f"未触发开仓的 {_n_pt - _n_ta:,} 个标的：要么在可交易期内始终未发出 200 日高点突破信号，"
    "要么突破发生时恰逢熊市阶段（Regime Filter 关闭大多数标的新开仓，TLT / GLD / UUP 豁免）。"
)

# ── Delisted / acquired trades ────────────────────────────────────────────────
_dl = res.trades[res.trades["exit_reason"] == "delisted"].copy() if "exit_reason" in res.trades.columns else res.trades.iloc[0:0].copy()
_n_total   = len(res.trades)
_n_dl      = len(_dl)
_dl_pct    = _n_dl / _n_total * 100 if _n_total else 0

st.subheader("退市 / 被收购标的的交易")

if _n_dl == 0:
    st.info("本次回测中未检测到退市 / 被收购平仓。")
else:
    _dl_wins     = int((_dl["net_pnl"] > 0).sum())
    _dl_win_rate = _dl_wins / _n_dl * 100
    _dl_avg_r    = float(_dl["pnl_r_multiple"].mean()) if "pnl_r_multiple" in _dl.columns else float("nan")
    _dl_net_pnl  = float(_dl["net_pnl"].sum()) if "net_pnl" in _dl.columns else float("nan")

    _c1, _c2, _c3, _c4 = st.columns(4)
    _c1.metric("退市平仓笔数",  f"{_n_dl}",         help=f"占全部 {_n_total} 笔的 {_dl_pct:.1f}%")
    _c2.metric("胜率",          f"{_dl_win_rate:.0f}%", help="net_pnl > 0 的比例")
    _c3.metric("平均 R 倍数",   f"{_dl_avg_r:.2f}R",    help="含并购溢价捕获的 R 倍数均值")
    _c4.metric("累计净盈亏",    f"${_dl_net_pnl:,.0f}", help="退市 / 并购事件带来的总净利润")

    # Bar chart: count by year of exit
    _dl["exit_year"] = _pd_etf.to_datetime(_dl["exit_date"]).dt.year
    _yr_cnt = _dl.groupby("exit_year").size().reset_index(name="count")
    _fig_dl = _go.Figure(_go.Bar(
        x=_yr_cnt["exit_year"].astype(str),
        y=_yr_cnt["count"],
        marker_color="#e67e22",
        text=_yr_cnt["count"],
        textposition="outside",
        hovertemplate="退市年份 %{x}：%{y} 笔<extra></extra>",
    ))
    _fig_dl.update_layout(
        title="各年度退市 / 被收购平仓笔数",
        xaxis_title="退市年份", yaxis_title="笔数",
        height=280, margin=dict(l=50, r=20, t=50, b=40),
        bargap=0.3,
    )
    st.plotly_chart(_fig_dl, use_container_width=True)

    # Detail table
    with st.expander(f"查看全部 {_n_dl} 笔退市平仓明细", expanded=False):
        _dl_show = _dl[["ticker", "entry_date", "exit_date", "holding_days",
                         "pnl_r_multiple", "net_pnl"]].copy()
        _dl_show = _dl_show.sort_values("exit_date")
        _dl_show.columns = ["代码", "入场日", "退市平仓日", "持仓天数", "R 倍数", "净盈亏 ($)"]
        _dl_show["R 倍数"]    = _dl_show["R 倍数"].map(lambda x: f"{x:.2f}R")
        _dl_show["净盈亏 ($)"] = _dl_show["净盈亏 ($)"].map(lambda x: f"${x:,.0f}")
        st.dataframe(_dl_show, use_container_width=True, hide_index=True)

    st.markdown(f"""
**解读：** 回测期间共有 **{_n_dl}** 笔交易（占总交易的 {_dl_pct:.1f}%）因标的退市或被收购而平仓。
由于策略1.0基于价格突破入场，被并购标的往往在宣布前已产生较强趋势，
并购溢价会使最后一个交易日的收盘价出现跳升，平均 R 倍数达 {_dl_avg_r:.2f}R
（高于策略整体的 {m.get("avg_win_r", float("nan")):.2f}R 胜率组均值）。
这表明 Tiingo 动态标的池中的历史退市 / 并购事件对策略贡献了**正收益**，并非噪声。
""")

st.markdown("---")

# ── 每年开仓信号数量柱状图 ────────────────────────────────────────────────────
st.subheader("每年开仓信号数量柱状图")

if _es_path.exists():
    import plotly.graph_objects as _go_esy

    _esy_raw  = _pd_es.read_csv(_es_path, index_col="date", parse_dates=True)
    _esy_ann  = _esy_raw.resample("YE").sum()
    _esy_ann.index = _esy_ann.index.year

    _years_esy    = _esy_ann.index.tolist()
    _all_sigs_esy = (_esy_ann["signals"].tolist()  if "signals"  in _esy_ann.columns else [0] * len(_years_esy))
    _exe_sigs_esy = (_esy_ann["executed"].tolist() if "executed" in _esy_ann.columns else [0] * len(_years_esy))

    _fig_esy = _go_esy.Figure()
    _fig_esy.add_trace(_go_esy.Bar(
        x=_years_esy,
        y=_all_sigs_esy,
        name="所有开仓信号（含未执行）",
        marker_color="#aaaaaa",
        opacity=0.85,
        offsetgroup="A",
        hovertemplate="%{x}年<br>所有信号（含未执行）：%{y:,} 个<extra></extra>",
    ))
    _fig_esy.add_trace(_go_esy.Bar(
        x=_years_esy,
        y=_exe_sigs_esy,
        name="实际执行的开仓信号",
        marker_color=meta.color,
        offsetgroup="B",
        hovertemplate="%{x}年<br>实际执行：%{y:,} 个<extra></extra>",
    ))
    _fig_esy.update_layout(
        barmode="group",
        hovermode="x unified",
        height=440,
        margin=dict(l=60, r=20, t=30, b=50),
        bargap=0.2,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(title_text="<b>年份</b>", title_font=dict(size=13), dtick=1),
        yaxis=dict(title_text="<b>信号数量（个）</b>", title_font=dict(size=13)),
    )
    st.plotly_chart(_fig_esy, use_container_width=True)

    _tot_all_esy = int(sum(_all_sigs_esy))
    _tot_exe_esy = int(sum(_exe_sigs_esy))
    _exe_rt_esy  = _tot_exe_esy / _tot_all_esy * 100 if _tot_all_esy > 0 else 0
    _avg_all_esy = _tot_all_esy / len(_years_esy) if _years_esy else 0
    _avg_exe_esy = _tot_exe_esy / len(_years_esy) if _years_esy else 0

    _ec1, _ec2, _ec3 = st.columns(3)
    _ec1.metric("全程总候选信号",   f"{_tot_all_esy:,} 个")
    _ec2.metric("全程实际执行",     f"{_tot_exe_esy:,} 个",   delta=f"执行率 {_exe_rt_esy:.1f}%")
    _ec3.metric("平均每年执行信号", f"{_avg_exe_esy:.0f} 个", help=f"所有候选信号均值 {_avg_all_esy:.0f} 个/年")

    st.markdown(
        f"**解读：** 灰色柱表示每年策略**产生的所有开仓候选信号**（满足 200 日高点突破、成交量确认、"
        f"最低股价与流动性过滤条件），彩色柱为其中**实际完成建仓的信号**。"
        f"两根柱子之差即被风控系统放弃的信号（资金不足 / 热度超限 / 相关性过高）。"
        f"牛市年份候选信号密集；熊市年份（2002、2008、2022）因 Regime Filter 关闭大部分标的新开仓，"
        f"两根柱子同时骤降，体现了策略1.0的**动态风险管理**能力。"
    )
else:
    st.info("开仓信号数据尚未生成。运行：python src/scripts/04_run_diagnostics.py")

st.markdown("---")

# ── 每标的交易次数分布 ─────────────────────────────────────────────────────────
st.subheader("每标的交易次数分布")

_freq_ta     = _ta.groupby("ticker").size()
_once_ta     = int((_freq_ta == 1).sum())
_multi_ta    = int((_freq_ta > 1).sum())
_max_freq_ta = int(_freq_ta.max())
_top_tk_ta   = _freq_ta.idxmax()

_fdist_x, _fdist_y = [], []
for _k in range(1, 10):
    _fdist_x.append(str(_k))
    _fdist_y.append(int((_freq_ta == _k).sum()))
_ge10_ta = int((_freq_ta >= 10).sum())
_fdist_x.append("≥10")
_fdist_y.append(_ge10_ta)

_fig_freq_ta = _go.Figure(_go.Bar(
    x=_fdist_x, y=_fdist_y,
    marker_color=meta.color,
    text=_fdist_y, textposition="outside",
))
_fig_freq_ta.update_layout(
    title="每标的历史交易次数分布",
    xaxis_title="交易次数（该标的整个回测期内合计）",
    yaxis_title="标的数量",
    height=320, margin=dict(l=50, r=20, t=50, b=40),
)
st.plotly_chart(_fig_freq_ta, use_container_width=True)
st.markdown(
    f"**{_once_ta:,} 个**标的（{_once_ta/_n_ta*100:.0f}%）仅交易过 1 次；"
    f"**{_multi_ta:,} 个**（{_multi_ta/_n_ta*100:.0f}%）被多次买卖，"
    f"交易最多的是 **{_top_tk_ta}**（{_max_freq_ta} 次）。"
    "一次性交易占主导，说明策略追求的是独立的、非重复性趋势机会；"
    "多次交易的标的往往是趋势明显的 ETF 或大盘龙头。"
)

with st.expander("📋 交易次数最多的 TOP 10 标的", expanded=False):
    _topfreq_df = _freq_ta.sort_values(ascending=False).head(10).reset_index()
    _topfreq_df.columns = ["标的", "交易次数"]
    _topfreq_df["类别"] = _topfreq_df["标的"].apply(
        lambda t: "ETF" if t in _ETF_SET else "股票"
    )
    _tk_pnl_map = _tk.set_index("ticker")["总盈亏"].to_dict()
    _topfreq_df["总净盈亏($)"] = _topfreq_df["标的"].map(_tk_pnl_map).map(
        lambda v: f"${v:+,.0f}"
    )
    st.dataframe(_topfreq_df, use_container_width=True, hide_index=True)

st.markdown("---")

# ── Monthly return heatmap ────────────────────────────────────────────────────
st.subheader("月度收益热力图")
st.plotly_chart(monthly_return_heatmap(res.nav), use_container_width=True)

_nav_mh = res.nav.copy()
if not isinstance(_nav_mh.index, _pd_ar.DatetimeIndex):
    _nav_mh.index = _pd_ar.to_datetime(_nav_mh.index)
_monthly_mh  = _nav_mh.resample("ME").last().pct_change().dropna() * 100
_pos_m_cnt   = int((_monthly_mh > 0).sum())
_neg_m_cnt   = int((_monthly_mh <= 0).sum())
_best_m_val  = float(_monthly_mh.max())
_worst_m_val = float(_monthly_mh.min())
_best_m_dt   = _monthly_mh.idxmax()
_worst_m_dt  = _monthly_mh.idxmin()
st.markdown(
    f"**解读：** {_pos_m_cnt + _neg_m_cnt} 个月中 **{_pos_m_cnt}** 个月正收益（{_pos_m_cnt/(_pos_m_cnt+_neg_m_cnt)*100:.0f}%）。"
    f"最好月份 **{_best_m_dt.strftime('%Y年%m月')}（{_best_m_val:+.1f}%）**，"
    f"最差月份 **{_worst_m_dt.strftime('%Y年%m月')}（{_worst_m_val:+.1f}%）**。"
    "热力图可直观识别季节性规律：红色集中区域（如某季度持续亏损）是策略1.0改进的潜在方向。"
)

st.markdown("---")

# ── Full metrics table ────────────────────────────────────────────────────────
st.subheader("完整指标对比表")
render_full_metrics_table(m, _spy_metrics)

st.markdown("---")

# ── Trade summary ─────────────────────────────────────────────────────────────
_trade_hdr_col, _trade_btn_col = st.columns([5, 1])
with _trade_hdr_col:
    st.subheader("交易样本")
with _trade_btn_col:
    _dl_cols = ["ticker", "entry_date", "exit_date", "holding_days",
                "entry_price", "exit_price", "shares", "net_pnl",
                "pnl_r_multiple", "exit_reason"]
    _dl_cols = [c for c in _dl_cols if c in res.trades.columns]
    _all_trades_dl = (
        res.trades.sort_values("exit_date", ascending=False)[_dl_cols]
        .rename(columns={
            "ticker":         "标的",
            "entry_date":     "入场日",
            "exit_date":      "出场日",
            "holding_days":   "持仓天",
            "entry_price":    "入场价",
            "exit_price":     "出场价",
            "shares":         "股数",
            "net_pnl":        "净盈亏($)",
            "pnl_r_multiple": "R倍数",
            "exit_reason":    "出场原因",
        })
    )
    st.download_button(
        label="⬇ 下载全部交易",
        data=_all_trades_dl.to_csv(index=False).encode("utf-8"),
        file_name="all_trades.csv",
        mime="text/csv",
    )
n_show = st.slider("显示交易笔数", 10, 100, 20, 10)
trades_display = res.trades.sort_values("exit_date", ascending=False).head(n_show).copy()
_td_cols = ["ticker", "entry_date", "exit_date", "holding_days",
            "entry_price", "exit_price", "shares", "net_pnl",
            "pnl_r_multiple", "exit_reason"]
_td_cols = [c for c in _td_cols if c in trades_display.columns]
trades_display = trades_display[_td_cols].rename(columns={
    "ticker":         "标的",
    "entry_date":     "入场日",
    "exit_date":      "出场日",
    "holding_days":   "持仓天",
    "entry_price":    "入场价",
    "exit_price":     "出场价",
    "shares":         "股数",
    "net_pnl":        "净盈亏($)",
    "pnl_r_multiple": "R 倍数",
    "exit_reason":    "出场原因",
})
if "净盈亏($)" in trades_display.columns:
    trades_display["净盈亏($)"] = trades_display["净盈亏($)"].apply(
        lambda v: f"${v:+,.0f}"
    )
st.dataframe(trades_display, use_container_width=True, hide_index=True)

# ── Assessment ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("评估")

import numpy as _np2
import pandas as _pd3

# ── Compute additional stats ──────────────────────────────────────────────────
_nav_s = res.nav.copy()
if not isinstance(_nav_s.index, _pd3.DatetimeIndex):
    _nav_s.index = _pd3.to_datetime(_nav_s.index)

# Annual returns (exclude current partial year)
_annual_all = _nav_s.resample("YE").last().pct_change().dropna()
_current_year = _nav_s.index[-1].year
_annual = _annual_all[_annual_all.index.year < _current_year]
_n_years      = len(_annual)
_bt_years     = (_nav_s.index[-1] - _nav_s.index[0]).days / 365.25  # actual backtest duration
_pos_years    = int((_annual > 0).sum())
_neg_years    = int((_annual < 0).sum())
_worst_yr     = int(_annual.idxmin().year)
_worst_ret    = float(_annual.min())
_best_yr      = int(_annual.idxmax().year)
_best_ret     = float(_annual.max())

_cagr         = m.get("cagr", 0)
_sharpe       = m.get("sharpe", 0)
_sortino      = m.get("sortino", 0)
_calmar       = m.get("calmar", 0)
_maxdd        = m.get("max_drawdown", 0)
_maxdd_dur    = m.get("max_dd_duration_days", 0)
_pf           = m.get("profit_factor", 0)
_wr           = m.get("win_rate", 0)
_avg_win_r    = m.get("avg_win_r", 0)
_avg_loss_r   = m.get("avg_loss_r", 0)
_turnover     = m.get("annual_turnover", 0)
_exposure     = m.get("market_exposure", 0)
_spy_cagr     = m.get("spy_cagr", 0)
_spy_sharpe   = m.get("spy_sharpe", 0)
_spy_maxdd    = m.get("spy_max_drawdown", 0)
_cagr_gap     = _cagr - _spy_cagr
_maxdd_ratio  = abs(_maxdd / _spy_maxdd) if _spy_maxdd != 0 else 0
_n_trades     = m.get("n_trades", 0)
_max_cl       = m.get("max_consecutive_losses", 0)
_total_ret    = m.get("total_return", 0)

_tr_copy = res.trades.copy()
_big5r = int((_tr_copy["pnl_r_multiple"] > 5).sum())
_big5r_pct = _big5r / len(_tr_copy) * 100 if len(_tr_copy) > 0 else 0
_max_r = float(_tr_copy["pnl_r_multiple"].max())

_implied_cost = _turnover * (
    meta.params_anchor.get("slippage_bps", 10) + meta.params_anchor.get("commission_bps", 3)
) * 2 / 100

# ── Dynamic negative-year description ────────────────────────────────────────
_spy_ann_dict: dict = {}
if res.spy_nav is not None:
    _spy_nav_tmp = res.spy_nav.copy()
    if not isinstance(_spy_nav_tmp.index, _pd3.DatetimeIndex):
        _spy_nav_tmp.index = _pd3.to_datetime(_spy_nav_tmp.index)
    for _idx, _ret in _spy_nav_tmp.resample("YE").last().pct_change().dropna().items():
        if _idx.year < _current_year:
            _spy_ann_dict[int(_idx.year)] = float(_ret)

_neg_details = sorted(
    [(int(_idx.year), float(_ret)) for _idx, _ret in _annual[_annual < 0].items()],
    key=lambda x: x[1],
)
if _neg_details:
    _small_loss = [(y, r) for y, r in _neg_details if r > -0.10]
    _big_loss   = [(y, r) for y, r in _neg_details if r <= -0.10]
    _nd_parts: list[str] = []
    if _small_loss:
        _nd_parts.append(
            f"{len(_small_loss)} 年亏损较轻（> -10%）："
            + "、".join(f"{y}年（{r*100:.1f}%）" for y, r in sorted(_small_loss))
        )
    if _big_loss:
        _big_strs = []
        for _y, _r in sorted(_big_loss):
            _spy_r = _spy_ann_dict.get(_y)
            _spy_suffix = f"，同期 SPY {_spy_r*100:.1f}%" if _spy_r is not None else ""
            _big_strs.append(f"{_y}年（策略1.0 {_r*100:.1f}%{_spy_suffix}）")
        _nd_parts.append(
            f"{len(_big_loss)} 年出现较大亏损（≤ -10%）：" + "、".join(_big_strs)
        )
    _neg_yr_desc = "；".join(_nd_parts) + "。"
else:
    _neg_yr_desc = "历史回测中无负收益年份。"

_beats_spy = _cagr_gap > 0
_sec1_header = (
    f"**1. 绝对收益超越 SPY {abs(_cagr_gap)*100:.1f} 个百分点**"
    if _beats_spy else
    f"**1. 绝对收益可观，但跑输 SPY 约 {abs(_cagr_gap)*100:.1f} 个百分点**"
)
_sec1_body = (
    f"在 {meta.backtest_start[:4]}–{meta.backtest_end[:4]} 约 {_bt_years:.0f} 年的回测期内，"
    f"策略1.0 CAGR **{_cagr*100:+.2f}%**，同期 SPY 为 **{_spy_cagr*100:+.2f}%**，领先 **{_cagr_gap*100:+.2f}%**。"
    f"以 $10M 初始资金计算，净值增长 **{_total_ret:.2f} 倍**（期末约 ${_total_ret*10:.0f}M）。"
    f"包含 2000–2002 科网泡沫破裂、2008–2009 金融危机的完整市场周期，在此期间 SPY 最大回撤高达 **{abs(_spy_maxdd)*100:.1f}%**；"
    f"策略1.0通过市场环境过滤器规避了大部分熊市损失，最大回撤仅 **{abs(_maxdd)*100:.1f}%**，"
    f"同时在 26 年间 CAGR 仍领先 SPY——这是趋势跟踪策略在完整周期中展现的全部优势。"
    if _beats_spy else
    f"在 {meta.backtest_start[:4]}–{meta.backtest_end[:4]} 约 {_bt_years:.0f} 年的回测期内，"
    f"策略1.0 CAGR **{_cagr*100:+.2f}%**，同期 SPY 为 **{_spy_cagr*100:+.2f}%**，差距 **{_cagr_gap*100:+.2f}%**。"
    f"以 $10M 初始资金计算，净值增长 **{_total_ret:.2f} 倍**（期末约 ${_total_ret*10:.0f}M）。"
    f"跑输 SPY 是这份结果最直接的弱点，也是向任何潜在投资者解释时需要正面回答的第一个问题。"
    f"对此的核心回答是：**SPY 在相同时间内最大回撤 {abs(_spy_maxdd)*100:.1f}%，而策略1.0最大回撤仅 {abs(_maxdd)*100:.1f}%**——"
    f"收益更低，但承受的风险断崖式下降。"
)

st.markdown(f"""
{_sec1_header}

{_sec1_body}

**2. Sharpe 轻微领先 SPY，风险调整后有竞争力**

策略1.0 Sharpe **{_sharpe:+.3f}** vs SPY **{_spy_sharpe:+.3f}**，差距微小但方向有利。
Sortino **{_sortino:+.3f}**（对下行波动的惩罚更严格），Calmar **{_calmar:+.3f}**（CAGR / MaxDD）。
这三个指标共同说明：在单位风险维度上，策略1.0与 SPY 大体相当，
并非用大幅更低的风险调整收益换来了更低的绝对回撤——而是在**基本等效的风险效率下**，
大幅压缩了最大回撤的绝对深度。

**3. 最大回撤 {abs(_maxdd)*100:.1f}% 是策略1.0最突出的实际优势**

SPY 在回测期内最大回撤高达 **{abs(_spy_maxdd)*100:.1f}%**（2008–2009 金融危机），
策略1.0同期最大回撤仅 **{abs(_maxdd)*100:.1f}%**，下行深度约为 SPY 的 **{_maxdd_ratio*100:.0f}%**。
最长水下时间 **{_maxdd_dur} 个交易日**（约 {_maxdd_dur/252:.1f} 年）。
对于以保全本金为前提的机构资金而言，这一差距具有实质意义：
**{abs(_spy_maxdd)*100:.0f}%** 的跌幅需要涨 **{(1/(1-min(abs(_spy_maxdd),0.99))-1)*100:.0f}%** 才能回本，而策略1.0 **{abs(_maxdd)*100:.0f}%** 仅需涨 **{(1/(1-min(abs(_maxdd),0.99))-1)*100:.0f}%**。

**4. 胜率低而盈亏比高，符合趋势跟踪的数学结构**

胜率 **{_wr*100:.1f}%** 在表观上偏低，但这是趋势策略的内在特征，而非缺陷。
盈利交易平均 **{_avg_win_r:+.2f}R**，亏损交易平均 **{abs(_avg_loss_r):.2f}R**，
Profit Factor **{_pf:.3f}**——每亏 1 元预期赚回 {_pf:.2f} 元。
在 {_n_trades:,} 笔交易中，超过 5R 的大赢家 {_big5r} 笔（占比 {_big5r_pct:.1f}%），
最大单笔 **{_max_r:+.2f}R**。
**大赢家的右尾贡献是策略1.0盈利的核心来源**——不能因为胜率偏低就轻易判断策略1.0无效。

**5. 年度表现稳定，{_n_years} 年中 {_pos_years} 年正收益（{_pos_years/_n_years*100:.0f}%）**

{_n_years} 个完整年度中，{_pos_years} 年正收益，{_neg_years} 年负收益。
最差年份 **{_worst_yr} 年（{_worst_ret*100:+.1f}%）**，最好年份 **{_best_yr} 年（{_best_ret*100:+.1f}%）**。
{_neg_yr_desc}
这种"负收益年份损失可控、正收益年份收益可观"的结构，
是趋势策略长期正复利的基础。

**6. 交易成本与换手率处于合理区间**

年换手率 **{_turnover:.2f}x**，隐含年化交易摩擦约 **{_implied_cost:.2f}%**，
已完整计入回测净值。市场暴露率 **{_exposure*100:.1f}%**（约 {100-_exposure*100:.1f}% 时间现金转入 SHY），
说明策略1.0全年大部分时间有仓位，并非依赖少数几笔交易的偶然发挥。

**7. 策略1.0定位的准确理解**
""")

# Positioning assessment table
st.markdown(f"""
| 维度 | 结论 |
|------|------|
| 绝对收益 | ✅ CAGR {_cagr*100:+.2f}%，{_n_years}年累计 {(_total_ret-1)*100:.0f}%，正期望明确 |
| 相对收益 | {"✅ 领先 SPY " + f"{abs(_cagr_gap)*100:.1f}%/年，在完整市场周期中具备超额收益" if _beats_spy else "⚠️ 落后 SPY " + f"{abs(_cagr_gap)*100:.1f}%/年，在长牛市中是结构性弱点"} |
| 回撤控制 | ✅ MaxDD {abs(_maxdd)*100:.1f}% vs SPY {abs(_spy_maxdd)*100:.1f}%，下行保护能力突出 |
| 风险效率 | ✅ Sharpe {_sharpe:.3f} vs SPY {_spy_sharpe:.3f}，单位风险回报大体相当 |
| 交易成本 | ✅ {_implied_cost:.2f}%/年，已计入净值，不影响结论可信度 |
| 适用场景 | 适合作为投资组合中的**防御性趋势配置**，而非替代 SPY 的进攻性资产 |
""")

# Verdict
if _cagr > 0.06 and _sharpe > _spy_sharpe and abs(_maxdd) < abs(_spy_maxdd) * 0.5:
    verdict_icon = "✅"
    if _beats_spy:
        verdict_body = (
            f"综合评价：基准回测结果超越预期目标。"
            f"CAGR {_cagr*100:+.2f}%（领先 SPY {abs(_cagr_gap)*100:.1f}%），Sharpe {_sharpe:.3f}（vs SPY {_spy_sharpe:.3f}），"
            f"MaxDD {abs(_maxdd)*100:.1f}%（仅为 SPY {abs(_spy_maxdd)*100:.1f}% 的 {_maxdd_ratio*100:.0f}%）。"
            f"在涵盖两次重大熊市的 26 年完整周期中，策略1.0同时实现了**超额绝对收益**与**大幅降低最大回撤**，"
            f"是趋势跟踪策略的最佳实证场景。"
        )
    else:
        verdict_body = (
            f"综合评价：基准回测结果达到预期目标。"
            f"CAGR {_cagr*100:+.2f}%，Sharpe {_sharpe:.3f}（微超 SPY {_spy_sharpe:.3f}），"
            f"MaxDD {abs(_maxdd)*100:.1f}%（仅为 SPY {abs(_spy_maxdd)*100:.1f}% 的 {_maxdd_ratio*100:.0f}%）。"
            f"策略1.0的核心价值在于**用约 {abs(_cagr_gap)*100:.1f}% 的年化收益损失，换取约 {(abs(_spy_maxdd)-abs(_maxdd))*100:.1f}% 的最大回撤保护**，"
            f"是风险厌恶型投资者在权益资产中最值得考虑的量化选项之一。"
        )
elif _cagr > 0.05:
    verdict_icon = "🟡"
    verdict_body = (
        f"综合评价：结果整体可接受，CAGR {_cagr*100:+.2f}%，但 Sharpe 或回撤控制仍有提升空间。"
    )
else:
    verdict_icon = "⚠️"
    verdict_body = f"综合评价：CAGR {_cagr*100:+.2f}% 偏低，需审查策略1.0参数或回测设置。"

st.markdown(
    f'<div class="info-box"><strong>{verdict_icon} {verdict_body}</strong></div>',
    unsafe_allow_html=True,
)

