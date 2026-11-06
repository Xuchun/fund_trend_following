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

st.markdown("年化收益（CAGR）基于 Yahoo Finance 复权价格（`auto_adjust=True`）计算，**已包含历史分红再投资**，为总回报年化收益（Total Return CAGR）。")

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

# ─── 三、年度收益柱状图 ─────────────────────────────────────────────
st.subheader("三、QQQ 年度收益历史（1999 年至今）")
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
