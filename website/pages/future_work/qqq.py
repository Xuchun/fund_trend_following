"""QQQ历史价格与回撤分析"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import date as _date

st.title("QQQ 历史分析")

# ─── 数据加载（Yahoo Finance，1999年起）──────────────────────────────
@st.cache_data(ttl=86400)
def _load_qqq() -> pd.Series:
    raw = yf.download(
        "QQQ", start="1999-01-01",
        end=_date.today().isoformat(),
        interval="1d", auto_adjust=True, progress=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    s = raw["Close"].dropna()
    s.index = pd.to_datetime(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_convert(None)
    else:
        s.index = s.index.tz_localize(None)
    return s.sort_index().rename("qqq")

@st.cache_data(ttl=86400)
def _load_spy(start: str, end: str) -> pd.Series:
    raw = yf.download(
        "SPY", start=start, end=end,
        interval="1d", auto_adjust=True, progress=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    s = raw["Close"].dropna()
    s.index = pd.to_datetime(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_convert(None)
    else:
        s.index = s.index.tz_localize(None)
    return s.sort_index().rename("spy")


def _calc_metrics(prices: pd.Series, dd: pd.Series) -> dict:
    """计算CAGR、最大回撤、最大水下时间、最低点→复原四项指标。"""
    n_cal = (prices.index[-1] - prices.index[0]).days
    cagr = (prices.iloc[-1] / prices.iloc[0]) ** (365.0 / n_cal) - 1
    max_dd = dd.min()

    underwater = dd < 0
    max_uw = 0
    uw_start = None
    uw_best_start = None
    uw_best_end = None
    for dt, is_uw in underwater.items():
        if is_uw:
            if uw_start is None:
                uw_start = dt
        else:
            if uw_start is not None:
                dur = (dt - uw_start).days
                if dur > max_uw:
                    max_uw = dur
                    uw_best_start = uw_start
                    uw_best_end = dt
                uw_start = None
    if uw_start is not None:
        dur = (prices.index[-1] - uw_start).days
        if dur > max_uw:
            max_uw = dur
            uw_best_start = uw_start
            uw_best_end = None
    uw_range = (
        f"{uw_best_start.strftime('%Y-%m')} 至今"
        if uw_best_end is None
        else f"{uw_best_start.strftime('%Y-%m')} 至 {uw_best_end.strftime('%Y-%m')}"
    ) if uw_best_start else "—"

    mdd_trough_dt = dd.idxmin()
    mdd_peak_dt = prices.loc[:mdd_trough_dt].idxmax()
    mdd_period = f"{mdd_peak_dt.strftime('%Y-%m-%d')} → {mdd_trough_dt.strftime('%Y-%m-%d')}"

    after_trough = dd.loc[mdd_trough_dt:]
    recovery_pts = after_trough[after_trough >= 0]
    if len(recovery_pts) > 0:
        ttr_recovery_dt = recovery_pts.index[0]
        ttr_days = (ttr_recovery_dt - mdd_trough_dt).days
        ttr_val = f"{ttr_days / 365:.1f} 年"
        ttr_sub = f"{mdd_trough_dt.strftime('%Y-%m')} → {ttr_recovery_dt.strftime('%Y-%m')}"
    else:
        ttr_val = "至今未恢复"
        ttr_sub = f"最低点 {mdd_trough_dt.strftime('%Y-%m')}"

    return dict(
        cagr=cagr, max_dd=max_dd, mdd_period=mdd_period,
        max_uw_days=max_uw, uw_range=uw_range,
        ttr_val=ttr_val, ttr_sub=ttr_sub,
        date_range=f"{prices.index[0].strftime('%Y-%m-%d')} 至 {prices.index[-1].strftime('%Y-%m-%d')}",
    )


with st.spinner("正在加载 QQQ / SPY 价格数据…"):
    _prices = _load_qqq()
    _spy_prices = _load_spy(
        _prices.index[0].strftime("%Y-%m-%d"),
        _date.today().isoformat(),
    )
    # 两者对齐到共同的交易日
    _common_idx = _prices.index.intersection(_spy_prices.index)
    _prices_aligned = _prices.loc[_common_idx]
    _spy_aligned = _spy_prices.loc[_common_idx]

st.markdown(
    f"数据来源：**Yahoo Finance — QQQ（纳斯达克100 ETF，1999 年上市至今）**  \n"
    f"数据范围：**{_prices.index[0].strftime('%Y-%m-%d')}** 至 **{_prices.index[-1].strftime('%Y-%m-%d')}**，"
    f"共 **{len(_prices):,}** 个交易日。"
)

# 全程 ATH 与回撤序列
_ath = _prices.expanding().max()
_dd  = (_prices - _ath) / _ath * 100   # 百分比，负值

# ─── 一、历史价格图 ─────────────────────────────────────────────────
st.subheader("一、QQQ 历史价格（日线，对数坐标）")

_fig1 = go.Figure()
_fig1.add_trace(go.Scatter(
    x=_prices.index, y=_prices.values,
    mode="lines", name="收盘价",
    line=dict(color="#1E88E5", width=1.2),
    hovertemplate="%{x|%Y-%m-%d}  $%{y:,.2f}<extra></extra>",
))
_fig1.add_trace(go.Scatter(
    x=_ath.index, y=_ath.values,
    mode="lines", name="历史高点（ATH）",
    line=dict(color="#0D47A1", width=1, dash="dot"),
    hovertemplate="%{x|%Y-%m-%d} ATH $%{y:,.2f}<extra></extra>",
))
_fig1.update_layout(
    xaxis_title="日期",
    yaxis_title="价格（USD）",
    yaxis_type="log",
    height=480,
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    margin=dict(t=40, b=40, l=70),
)
st.plotly_chart(_fig1, use_container_width=True)
st.markdown("纵轴使用**对数刻度**，使 $30 量级（1999年）与 $500+ 量级（2024年）均清晰可见。")

# 计算 QQQ 与 SPY 指标（对齐后的相同区间）
_spy_dd_aligned = (_spy_aligned - _spy_aligned.expanding().max()) / _spy_aligned.expanding().max() * 100
_m_qqq = _calc_metrics(_prices_aligned, (_prices_aligned - _prices_aligned.expanding().max()) / _prices_aligned.expanding().max() * 100)
_m_spy = _calc_metrics(_spy_aligned, _spy_dd_aligned)

# QQQ 指标行
st.markdown("**QQQ**")
_km1, _km2, _km3, _km4 = st.columns(4)
_km1.metric("年化收益（CAGR）", f"{_m_qqq['cagr']:+.2%}", _m_qqq["date_range"], delta_color="off")
_km2.metric("历史最大回撤", f"{_m_qqq['max_dd']:.1f}%", _m_qqq["mdd_period"], delta_color="off")
_km3.metric("最大水下时间", f"{_m_qqq['max_uw_days'] / 365:.1f} 年", _m_qqq["uw_range"], delta_color="off")
_km4.metric("最低点→复原", _m_qqq["ttr_val"], _m_qqq["ttr_sub"], delta_color="off")

# SPY 对比指标行
st.markdown("**SPY（同期对比）**")
_sm1, _sm2, _sm3, _sm4 = st.columns(4)
_sm1.metric("年化收益（CAGR）", f"{_m_spy['cagr']:+.2%}", _m_spy["date_range"], delta_color="off")
_sm2.metric("历史最大回撤", f"{_m_spy['max_dd']:.1f}%", _m_spy["mdd_period"], delta_color="off")
_sm3.metric("最大水下时间", f"{_m_spy['max_uw_days'] / 365:.1f} 年", _m_spy["uw_range"], delta_color="off")
_sm4.metric("最低点→复原", _m_spy["ttr_val"], _m_spy["ttr_sub"], delta_color="off")

# 供后续回撤图、详细分析使用的原始 QQQ 序列（非对齐版，保留完整历史）
_max_dd_val = _dd.min()

# ─── 二、回撤时序图 ─────────────────────────────────────────────────
st.subheader("二、QQQ 价格回撤时序图（相对历史高点）")

_fig2 = go.Figure()
_fig2.add_trace(go.Scatter(
    x=_dd.index, y=_dd.values,
    mode="lines", name="回撤幅度",
    line=dict(color="#EF5350", width=1),
    fill="tozeroy",
    fillcolor="rgba(239,83,80,0.12)",
    hovertemplate="%{x|%Y-%m-%d}  %{y:.1f}%<extra></extra>",
))
for _lvl, _col in [(-30, "#E65100"), (-50, "#B71C1C"), (-70, "#4A148C"), (-83, "#6A1B9A")]:
    _fig2.add_hline(
        y=_lvl,
        line_dash="dash",
        line_color=_col,
        annotation_text=f"{_lvl}%",
        annotation_position="left",
        annotation_font_color=_col,
        annotation_font_size=11,
    )
_fig2.update_layout(
    xaxis_title="日期",
    yaxis_title="回撤（%）",
    yaxis=dict(ticksuffix="%", range=[min(_dd.min() * 1.1, -90), 5]),
    height=380,
    hovermode="x unified",
    margin=dict(t=40, b=40, l=70),
)
st.plotly_chart(_fig2, use_container_width=True)

# ─── 三、月线价格走势与回撤 ────────────────────────────────────────
st.subheader("四、QQQ 月线价格走势与回撤（1999 年至今）")
st.markdown("数据来源：Yahoo Finance 日线数据，月末最后交易日收盘价。")

_mo_px  = _prices.resample("ME").last().dropna()
_mo_ath = _mo_px.expanding().max()
_mo_dd  = (_mo_px - _mo_ath) / _mo_ath * 100

# 月线关键指标
_mo_n_days = (_mo_px.index[-1] - _mo_px.index[0]).days
_mo_cagr = (_mo_px.iloc[-1] / _mo_px.iloc[0]) ** (365.0 / _mo_n_days) - 1
_mo_max_dd_val = _mo_dd.min()

_mo_underwater = _mo_dd < 0
_mo_max_uw_days = 0
_mo_uw_start = None
_mo_uw_best_start = None
_mo_uw_best_end = None
for _dt, _is_uw in _mo_underwater.items():
    if _is_uw:
        if _mo_uw_start is None:
            _mo_uw_start = _dt
    else:
        if _mo_uw_start is not None:
            _dur = (_dt - _mo_uw_start).days
            if _dur > _mo_max_uw_days:
                _mo_max_uw_days = _dur
                _mo_uw_best_start = _mo_uw_start
                _mo_uw_best_end = _dt
            _mo_uw_start = None
if _mo_uw_start is not None:
    _dur = (_mo_px.index[-1] - _mo_uw_start).days
    if _dur > _mo_max_uw_days:
        _mo_max_uw_days = _dur
        _mo_uw_best_start = _mo_uw_start
        _mo_uw_best_end = None
_mo_uw_range = (
    f"{_mo_uw_best_start.strftime('%Y-%m')} 至今"
    if _mo_uw_best_end is None
    else f"{_mo_uw_best_start.strftime('%Y-%m')} 至 {_mo_uw_best_end.strftime('%Y-%m')}"
)

_mo_mdd_trough_dt = _mo_dd.idxmin()
_mo_after_trough = _mo_dd.loc[_mo_mdd_trough_dt:]
_mo_recovery_after_trough = _mo_after_trough[_mo_after_trough >= 0]
if len(_mo_recovery_after_trough) > 0:
    _mo_ttr_recovery_dt = _mo_recovery_after_trough.index[0]
    _mo_ttr_days = (_mo_ttr_recovery_dt - _mo_mdd_trough_dt).days
    _mo_ttr_val = f"{_mo_ttr_days / 365:.1f} 年"
    _mo_ttr_sub = f"{_mo_mdd_trough_dt.strftime('%Y-%m')} → {_mo_ttr_recovery_dt.strftime('%Y-%m')}"
else:
    _mo_ttr_val = "至今未恢复"
    _mo_ttr_sub = f"最低点 {_mo_mdd_trough_dt.strftime('%Y-%m')}"

_mm1, _mm2, _mm3, _mm4 = st.columns(4)
_mm1.metric(
    "年化收益（CAGR）",
    f"{_mo_cagr:+.2%}",
    f"{_mo_px.index[0].strftime('%Y-%m')} 至 {_mo_px.index[-1].strftime('%Y-%m')}",
    delta_color="off",
)
_mm2.metric("历史最大回撤", f"{_mo_max_dd_val:.1f}%")
_mm3.metric(
    "最大水下时间",
    f"{_mo_max_uw_days / 365:.1f} 年",
    _mo_uw_range,
    delta_color="off",
)
_mm4.metric("最低点→复原", _mo_ttr_val, _mo_ttr_sub, delta_color="off")

st.markdown("**各次月末价格首次跌破 −30%（相对历史高点）时买入，后续收益：**")
_mo_fwd_in_event = False
_mo_fwd_rows = []
for _fdt, _fdv in _mo_dd.items():
    if not _mo_fwd_in_event and _fdv <= -30:
        _fep = float(_mo_px[_fdt])
        _frow = {
            "买入时间": _fdt.strftime("%Y-%m"),
            "买入价（$）": f"{_fep:,.2f}",
            "当时回撤": f"{_fdv:.1f}%",
        }
        for _fy in [1, 2, 3, 5, 10]:
            _ffd = _mo_px[_mo_px.index >= _fdt + pd.DateOffset(years=_fy)]
            _frow[f"{_fy}年后收益"] = f"{(_ffd.iloc[0] / _fep - 1):+.1%}" if len(_ffd) else "—"
        _mo_fwd_rows.append(_frow)
        _mo_fwd_in_event = True
    elif _mo_fwd_in_event and _fdv >= 0:
        _mo_fwd_in_event = False
if _mo_fwd_rows:
    st.dataframe(pd.DataFrame(_mo_fwd_rows), use_container_width=True, hide_index=True)
else:
    st.markdown("数据范围内无跌破 −30% 的时间点。")

st.markdown("**各次月末价格首次跌破 −50%（相对历史高点）时买入，后续收益：**")
_mo_fwd50_in_event = False
_mo_fwd50_rows = []
for _fdt, _fdv in _mo_dd.items():
    if not _mo_fwd50_in_event and _fdv <= -50:
        _fep = float(_mo_px[_fdt])
        _frow = {
            "买入时间": _fdt.strftime("%Y-%m"),
            "买入价（$）": f"{_fep:,.2f}",
            "当时回撤": f"{_fdv:.1f}%",
        }
        for _fy in [1, 2, 3, 5, 10]:
            _ffd = _mo_px[_mo_px.index >= _fdt + pd.DateOffset(years=_fy)]
            _frow[f"{_fy}年后收益"] = f"{(_ffd.iloc[0] / _fep - 1):+.1%}" if len(_ffd) else "—"
        _mo_fwd50_rows.append(_frow)
        _mo_fwd50_in_event = True
    elif _mo_fwd50_in_event and _fdv >= 0:
        _mo_fwd50_in_event = False
if _mo_fwd50_rows:
    st.dataframe(pd.DataFrame(_mo_fwd50_rows), use_container_width=True, hide_index=True)
else:
    st.markdown("数据范围内无跌破 −50% 的时间点。")

# 4a 月线价格走势（对数坐标）
_fig_mo1 = go.Figure()
_fig_mo1.add_trace(go.Scatter(
    x=_mo_px.index, y=_mo_px.values,
    mode="lines", name="月末价格",
    line=dict(color="#1E88E5", width=1.8),
    hovertemplate="%{x|%Y-%m}  $%{y:,.2f}<extra></extra>",
))
_fig_mo1.add_trace(go.Scatter(
    x=_mo_ath.index, y=_mo_ath.values,
    mode="lines", name="历史高点（ATH）",
    line=dict(color="#0D47A1", width=1, dash="dot"),
    hovertemplate="%{x|%Y-%m} ATH $%{y:,.2f}<extra></extra>",
))
_fig_mo1.update_layout(
    xaxis_title="日期", yaxis_title="价格（USD）",
    yaxis_type="log",
    height=420, hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    margin=dict(t=40, b=40, l=70),
)
st.plotly_chart(_fig_mo1, use_container_width=True)

# 4b 月线回撤走势
_fig_mo2 = go.Figure()
_fig_mo2.add_trace(go.Scatter(
    x=_mo_dd.index, y=_mo_dd.values,
    mode="lines", name="回撤幅度",
    line=dict(color="#EF5350", width=1.2),
    fill="tozeroy", fillcolor="rgba(239,83,80,0.12)",
    hovertemplate="%{x|%Y-%m}  %{y:.1f}%<extra></extra>",
))
for _lvl, _col in [(-30, "#E65100"), (-50, "#B71C1C"), (-70, "#4A148C")]:
    _fig_mo2.add_hline(
        y=_lvl, line_dash="dash", line_color=_col,
        annotation_text=f"{_lvl}%", annotation_position="left",
        annotation_font_color=_col, annotation_font_size=11,
    )
_fig_mo2.update_layout(
    xaxis_title="日期", yaxis_title="回撤（%）",
    yaxis=dict(ticksuffix="%", range=[min(_mo_dd.min() * 1.1, -90), 5]),
    height=350, hovermode="x unified",
    margin=dict(t=30, b=40, l=70),
)
st.plotly_chart(_fig_mo2, use_container_width=True)

# 月线回撤事件 >30%
_mo_dds = _find_drawdowns(_mo_px, 0.30)
if _mo_dds:
    st.markdown("**月线数据识别的超过 30% 回撤事件：**")
    _mo_rows = []
    for _i, _d in enumerate(_mo_dds, 1):
        _mo_rows.append({
            "#": _i,
            "峰值日期": _d["peak_dt"].strftime("%Y-%m"),
            "峰值价格": f"${_d['peak_px']:,.2f}",
            "低谷日期": _d["trough_dt"].strftime("%Y-%m"),
            "低谷价格": f"${_d['trough_px']:,.2f}",
            "最大回撤": f"{_d['mdd']:.1%}",
            "峰→谷（月）": round(_d["d_pt"] / 30),
            "谷→复原（月）": round(_d["d_tr"] / 30) if _d["d_tr"] else "—",
            "总持续（月）": round(_d["d_tot"] / 30),
            "复原日期": _d["recovery_dt"].strftime("%Y-%m") if _d["recovery_dt"] else "至今未恢复",
        })
    st.dataframe(pd.DataFrame(_mo_rows), use_container_width=True, hide_index=True)

# ─── 五、年度收益柱状图 ─────────────────────────────────────────────
st.subheader("五、QQQ 年度收益历史（1999 年至今）")
st.markdown("数据来源：Yahoo Finance 日线数据，以每年最后一个交易日收盘价计算当年收益。")

# 每年最后一个交易日收盘价，计算年度涨跌幅
_yr_px = _prices.resample("YE").last().dropna()
_yr_rets = _yr_px.pct_change().dropna()
_yr_pct = _yr_rets * 100

_ann_df = pd.DataFrame({
    "year": _yr_pct.index.year,
    "pct":  _yr_pct.values,
    "color": _yr_pct.apply(lambda x: "#2E7D32" if x >= 0 else "#C62828"),
})

_fig4 = go.Figure()
_fig4.add_trace(go.Bar(
    x=_ann_df["year"],
    y=_ann_df["pct"],
    marker_color=_ann_df["color"],
    text=_ann_df["pct"].apply(lambda v: f"{v:+.1f}%"),
    textposition="outside",
    textfont=dict(size=9),
    hovertemplate="%{x}年：%{y:+.2f}%<extra></extra>",
))
_fig4.add_hline(y=0, line_color="white", line_width=1)
_fig4.update_layout(
    xaxis_title="年份",
    yaxis_title="年度收益率（%）",
    yaxis=dict(ticksuffix="%", zeroline=True),
    height=480,
    bargap=0.25,
    margin=dict(t=40, b=40, l=60, r=20),
    hovermode="x unified",
)
st.plotly_chart(_fig4, use_container_width=True)

_pos = _ann_df[_ann_df["pct"] >= 0]
_neg = _ann_df[_ann_df["pct"] < 0]
_c1, _c2, _c3, _c4 = st.columns(4)
_c1.metric("上涨年数", f"{len(_pos)} 年", f"共 {len(_ann_df)} 年")
_c2.metric("下跌年数", f"{len(_neg)} 年")
_c3.metric("最大涨幅", f"{_ann_df['pct'].max():+.1f}%",
           f"{int(_ann_df.loc[_ann_df['pct'].idxmax(), 'year'])} 年")
_c4.metric("最大跌幅", f"{_ann_df['pct'].min():+.1f}%",
           f"{int(_ann_df.loc[_ann_df['pct'].idxmin(), 'year'])} 年")

# ─── 六、年线价格走势与回撤 ─────────────────────────────────────────
st.subheader("六、QQQ 年线价格走势与回撤（1999 年至今）")
st.markdown("以每年最后一个交易日收盘价为基础。")

_yr_ath = _yr_px.expanding().max()
_yr_dd  = (_yr_px - _yr_ath) / _yr_ath * 100

# 年线关键指标
_yr_n_days = (_yr_px.index[-1] - _yr_px.index[0]).days
_yr_cagr = (_yr_px.iloc[-1] / _yr_px.iloc[0]) ** (365.0 / _yr_n_days) - 1
_yr_max_dd_val = _yr_dd.min()

_yr_underwater = _yr_dd < 0
_yr_max_uw_days = 0
_yr_max_uw_start_dt = None
_yr_max_uw_end_dt = None
_yr_uw_start_cur = None
for _dt, _is_uw in _yr_underwater.items():
    if _is_uw:
        if _yr_uw_start_cur is None:
            _yr_uw_start_cur = _dt
    else:
        if _yr_uw_start_cur is not None:
            _dur = (_dt - _yr_uw_start_cur).days
            if _dur > _yr_max_uw_days:
                _yr_max_uw_days = _dur
                _yr_max_uw_start_dt = _yr_uw_start_cur
                _yr_max_uw_end_dt = _dt
            _yr_uw_start_cur = None
if _yr_uw_start_cur is not None:
    _dur = (_yr_px.index[-1] - _yr_uw_start_cur).days
    if _dur > _yr_max_uw_days:
        _yr_max_uw_days = _dur
        _yr_max_uw_start_dt = _yr_uw_start_cur
        _yr_max_uw_end_dt = None

_yr_uw_range = (
    f"{_yr_max_uw_start_dt.year} 至今"
    if _yr_max_uw_end_dt is None
    else f"{_yr_max_uw_start_dt.year} 至 {_yr_max_uw_end_dt.year}"
)

_yr_mdd_trough_dt = _yr_dd.idxmin()
_yr_after_trough = _yr_dd.loc[_yr_mdd_trough_dt:]
_yr_recovery_after_trough = _yr_after_trough[_yr_after_trough >= 0]
if len(_yr_recovery_after_trough) > 0:
    _yr_ttr_recovery_dt = _yr_recovery_after_trough.index[0]
    _yr_ttr_days = (_yr_ttr_recovery_dt - _yr_mdd_trough_dt).days
    _yr_ttr_val = f"{_yr_ttr_days / 365:.1f} 年"
    _yr_ttr_sub = f"{_yr_mdd_trough_dt.year} → {_yr_ttr_recovery_dt.year}"
else:
    _yr_ttr_val = "至今未恢复"
    _yr_ttr_sub = f"最低点 {_yr_mdd_trough_dt.year}"

_ym1, _ym2, _ym3, _ym4 = st.columns(4)
_ym1.metric(
    "年化收益（CAGR）",
    f"{_yr_cagr:+.2%}",
    f"{_yr_px.index[0].year} 至 {_yr_px.index[-1].year}",
    delta_color="off",
)
_ym2.metric("历史最大回撤", f"{_yr_max_dd_val:.1f}%")
_ym3.metric(
    "最大水下时间",
    f"{_yr_max_uw_days / 365:.1f} 年",
    _yr_uw_range,
    delta_color="off",
)
_ym4.metric("最低点→复原", _yr_ttr_val, _yr_ttr_sub, delta_color="off")

# 年线价格走势（对数坐标）
_fig_yr1 = go.Figure()
_fig_yr1.add_trace(go.Scatter(
    x=_yr_px.index, y=_yr_px.values,
    mode="lines+markers", name="年末收盘价",
    line=dict(color="#1E88E5", width=2),
    marker=dict(size=5, color="#1E88E5"),
    hovertemplate="%{x|%Y}  $%{y:,.2f}<extra></extra>",
))
_fig_yr1.add_trace(go.Scatter(
    x=_yr_ath.index, y=_yr_ath.values,
    mode="lines", name="历史高点（ATH）",
    line=dict(color="#0D47A1", width=1, dash="dot"),
    hovertemplate="%{x|%Y} ATH $%{y:,.2f}<extra></extra>",
))
_fig_yr1.update_layout(
    xaxis_title="年份", yaxis_title="年末收盘价（USD）",
    yaxis_type="log",
    height=420, hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    margin=dict(t=40, b=40, l=70),
)
st.plotly_chart(_fig_yr1, use_container_width=True)

# 年线回撤走势
_fig_yr2 = go.Figure()
_fig_yr2.add_trace(go.Scatter(
    x=_yr_dd.index, y=_yr_dd.values,
    mode="lines+markers", name="回撤幅度",
    line=dict(color="#EF5350", width=1.5),
    marker=dict(size=5, color="#EF5350"),
    fill="tozeroy", fillcolor="rgba(239,83,80,0.12)",
    hovertemplate="%{x|%Y}  %{y:.1f}%<extra></extra>",
))
for _lvl, _col in [(-30, "#E65100"), (-50, "#B71C1C"), (-70, "#4A148C")]:
    _fig_yr2.add_hline(
        y=_lvl, line_dash="dash", line_color=_col,
        annotation_text=f"{_lvl}%", annotation_position="left",
        annotation_font_color=_col, annotation_font_size=11,
    )
_fig_yr2.update_layout(
    xaxis_title="年份", yaxis_title="回撤（%）",
    yaxis=dict(ticksuffix="%", range=[min(_yr_dd.min() * 1.1, -90), 5]),
    height=350, hovermode="x unified",
    margin=dict(t=30, b=40, l=70),
)
st.plotly_chart(_fig_yr2, use_container_width=True)

# 年线回撤事件 >30%
_yr_dds = _find_drawdowns(_yr_px, 0.30)
if _yr_dds:
    st.markdown("**年线数据识别的超过 30% 回撤事件：**")
    _yr_rows = []
    for _i, _d in enumerate(_yr_dds, 1):
        _yr_rows.append({
            "#": _i,
            "峰值年份": _d["peak_dt"].year,
            "峰值年末价": f"${_d['peak_px']:,.2f}",
            "低谷年份": _d["trough_dt"].year,
            "低谷年末价": f"${_d['trough_px']:,.2f}",
            "最大回撤": f"{_d['mdd']:.1%}",
            "峰→谷（年）": round(_d["d_pt"] / 365),
            "谷→复原（年）": round(_d["d_tr"] / 365) if _d["d_tr"] else "—",
            "总持续（年）": round(_d["d_tot"] / 365),
            "复原年份": _d["recovery_dt"].year if _d["recovery_dt"] else "至今未恢复",
        })
    st.dataframe(pd.DataFrame(_yr_rows), use_container_width=True, hide_index=True)
