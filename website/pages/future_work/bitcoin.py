"""比特币 vs 比特币ETF 历史价格分析"""

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

st.title("比特币 vs 比特币ETF 历史分析")

# ─── 数据加载 ────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def _load(ticker: str, start: str) -> pd.Series:
    raw = yf.download(
        ticker, start=start,
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
    return s.sort_index()


with st.spinner("正在加载数据…"):
    _btc   = _load("BTC-USD", "2014-09-17")   # Yahoo BTC 最早可靠数据
    _ibit  = _load("IBIT",    "2024-01-11")   # iShares Bitcoin Trust ETF（BlackRock）
    _fbtc  = _load("FBTC",    "2024-01-11")   # Fidelity Wise Origin Bitcoin Fund
    _gbtc  = _load("GBTC",    "2015-05-01")   # Grayscale Bitcoin Trust（2024年转为ETF）

st.markdown(
    "数据来源：**Yahoo Finance**（`auto_adjust=True`，价格含分红复权，比特币无分红）  \n"
    "- **BTC-USD**：比特币现货价格（USD），2014年至今  \n"
    "- **IBIT**：iShares Bitcoin Trust ETF（BlackRock），2024-01-11 上市  \n"
    "- **FBTC**：Fidelity Wise Origin Bitcoin Fund，2024-01-11 上市  \n"
    "- **GBTC**：Grayscale Bitcoin Trust（2024年1月转为ETF），2015年起场外交易"
)

# 计算BTC回撤序列（全量）
_btc_ath = _btc.expanding().max()
_btc_dd  = (_btc - _btc_ath) / _btc_ath * 100


# ─── 通用工具函数 ────────────────────────────────────────────────────
def _calc_metrics(prices: pd.Series, dd: pd.Series) -> dict:
    n_cal = (prices.index[-1] - prices.index[0]).days
    cagr = (prices.iloc[-1] / prices.iloc[0]) ** (365.0 / n_cal) - 1
    max_dd = dd.min()

    mdd_trough_dt = dd.idxmin()
    mdd_peak_dt   = prices.loc[:mdd_trough_dt].idxmax()
    mdd_period    = f"{mdd_peak_dt.strftime('%Y-%m-%d')} → {mdd_trough_dt.strftime('%Y-%m-%d')}"

    underwater = dd < 0
    max_uw = 0; uw_start = None; uw_best_start = None; uw_best_end = None
    for dt, is_uw in underwater.items():
        if is_uw:
            if uw_start is None:
                uw_start = dt
        else:
            if uw_start is not None:
                dur = (dt - uw_start).days
                if dur > max_uw:
                    max_uw = dur; uw_best_start = uw_start; uw_best_end = dt
                uw_start = None
    if uw_start is not None:
        dur = (prices.index[-1] - uw_start).days
        if dur > max_uw:
            max_uw = dur; uw_best_start = uw_start; uw_best_end = None
    uw_range = (
        f"{uw_best_start.strftime('%Y-%m')} 至今" if uw_best_end is None
        else f"{uw_best_start.strftime('%Y-%m')} 至 {uw_best_end.strftime('%Y-%m')}"
    ) if uw_best_start else "—"

    after_trough  = dd.loc[mdd_trough_dt:]
    recovery_pts  = after_trough[after_trough >= 0]
    if len(recovery_pts) > 0:
        ttr_dt  = recovery_pts.index[0]
        ttr_val = f"{(ttr_dt - mdd_trough_dt).days / 365:.1f} 年"
        ttr_sub = f"{mdd_trough_dt.strftime('%Y-%m')} → {ttr_dt.strftime('%Y-%m')}"
    else:
        ttr_val = "至今未恢复"
        ttr_sub = f"最低点 {mdd_trough_dt.strftime('%Y-%m')}"

    return dict(
        cagr=cagr, max_dd=max_dd, mdd_period=mdd_period,
        max_uw_days=max_uw, uw_range=uw_range,
        ttr_val=ttr_val, ttr_sub=ttr_sub,
        date_range=f"{prices.index[0].strftime('%Y-%m-%d')} 至 {prices.index[-1].strftime('%Y-%m-%d')}",
    )


# ─── 一、BTC 历史价格 ────────────────────────────────────────────────
st.subheader("一、比特币历史价格（BTC-USD，对数坐标）")

_fig1 = go.Figure()
_fig1.add_trace(go.Scatter(
    x=_btc.index, y=_btc.values,
    mode="lines", name="BTC-USD",
    line=dict(color="#F7931A", width=1.2),
    hovertemplate="%{x|%Y-%m-%d}  $%{y:,.0f}<extra></extra>",
))
_fig1.add_trace(go.Scatter(
    x=_btc_ath.index, y=_btc_ath.values,
    mode="lines", name="历史高点（ATH）",
    line=dict(color="#B36200", width=1, dash="dot"),
    hovertemplate="%{x|%Y-%m-%d} ATH $%{y:,.0f}<extra></extra>",
))
_fig1.update_layout(
    xaxis_title="日期", yaxis_title="价格（USD）",
    yaxis_type="log",
    height=480, hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    margin=dict(t=40, b=40, l=70),
)
st.plotly_chart(_fig1, use_container_width=True)
st.markdown("纵轴使用**对数刻度**。年化收益（CAGR）基于 Yahoo Finance 复权价格，**不含分红**（比特币无分红）。")

_m_btc = _calc_metrics(_btc, _btc_dd)
_b1, _b2, _b3, _b4 = st.columns(4)
_b1.metric("年化收益（CAGR）", f"{_m_btc['cagr']:+.2%}", _m_btc["date_range"], delta_color="off")
_b2.metric("历史最大回撤", f"{_m_btc['max_dd']:.1f}%", _m_btc["mdd_period"], delta_color="off")
_b3.metric("最大水下时间", f"{_m_btc['max_uw_days'] / 365:.1f} 年", _m_btc["uw_range"], delta_color="off")
_b4.metric("最低点→复原", _m_btc["ttr_val"], _m_btc["ttr_sub"], delta_color="off")

# ─── 二、BTC 回撤时序图 ──────────────────────────────────────────────
st.subheader("二、比特币回撤时序图（相对历史高点）")

_fig2 = go.Figure()
_fig2.add_trace(go.Scatter(
    x=_btc_dd.index, y=_btc_dd.values,
    mode="lines", name="回撤幅度",
    line=dict(color="#EF5350", width=1),
    fill="tozeroy", fillcolor="rgba(239,83,80,0.12)",
    hovertemplate="%{x|%Y-%m-%d}  %{y:.1f}%<extra></extra>",
))
for _lvl, _col in [(-50, "#E65100"), (-70, "#B71C1C"), (-83, "#4A148C")]:
    _fig2.add_hline(
        y=_lvl, line_dash="dash", line_color=_col,
        annotation_text=f"{_lvl}%", annotation_position="left",
        annotation_font_color=_col, annotation_font_size=11,
    )
_fig2.update_layout(
    xaxis_title="日期", yaxis_title="回撤（%）",
    yaxis=dict(ticksuffix="%", range=[min(_btc_dd.min() * 1.1, -90), 5]),
    height=380, hovermode="x unified",
    margin=dict(t=40, b=40, l=70),
)
st.plotly_chart(_fig2, use_container_width=True)

# 超过 50% 的回撤汇总表
def _find_drawdowns(s: pd.Series, thresh: float) -> list:
    periods = []
    in_dd = False
    running_max = float(s.iloc[0])
    peak_dt = s.index[0]; peak_px = running_max
    trough_dt = s.index[0]; trough_px = running_max
    for dt, px in s.items():
        px = float(px)
        if px >= running_max:
            if in_dd:
                mdd = (trough_px - peak_px) / peak_px
                if mdd <= -thresh:
                    periods.append(dict(
                        peak_dt=peak_dt, peak_px=peak_px,
                        trough_dt=trough_dt, trough_px=trough_px,
                        recovery_dt=dt, mdd=mdd,
                        d_pt=(trough_dt - peak_dt).days,
                        d_tr=(dt - trough_dt).days,
                        d_tot=(dt - peak_dt).days,
                    ))
                in_dd = False
            running_max = px; peak_dt = dt; peak_px = px
            trough_dt = dt; trough_px = px
        else:
            if not in_dd:
                in_dd = True; trough_dt = dt; trough_px = px
            elif px < trough_px:
                trough_dt = dt; trough_px = px
    if in_dd:
        mdd = (trough_px - peak_px) / peak_px
        if mdd <= -thresh:
            periods.append(dict(
                peak_dt=peak_dt, peak_px=peak_px,
                trough_dt=trough_dt, trough_px=trough_px,
                recovery_dt=None, mdd=mdd,
                d_pt=(trough_dt - peak_dt).days,
                d_tr=None,
                d_tot=(s.index[-1] - peak_dt).days,
            ))
    return periods

_dds = _find_drawdowns(_btc, 0.50)
if _dds:
    st.markdown("**超过 50% 的历史回撤汇总：**")
    _rows = []
    for _i, _d in enumerate(_dds, 1):
        _rows.append({
            "#": _i,
            "峰值日期": _d["peak_dt"].strftime("%Y-%m"),
            "峰值价格": f"${_d['peak_px']:,.0f}",
            "低谷日期": _d["trough_dt"].strftime("%Y-%m"),
            "低谷价格": f"${_d['trough_px']:,.0f}",
            "最大回撤": f"{_d['mdd']:.1%}",
            "峰→谷（天）": _d["d_pt"],
            "谷→复原（天）": _d["d_tr"] if _d["d_tr"] is not None else "—",
            "总持续（天）": _d["d_tot"],
            "复原日期": _d["recovery_dt"].strftime("%Y-%m") if _d["recovery_dt"] else "至今未恢复",
        })
    st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True)

# ─── 三、年度收益柱状图 ──────────────────────────────────────────────
st.subheader("三、比特币年度收益历史（2014 年至今）")

_yr_px   = _btc.resample("YE").last().dropna()
_yr_rets = _yr_px.pct_change().dropna()
_yr_pct  = _yr_rets * 100
_ann_df  = pd.DataFrame({
    "year":  _yr_pct.index.year,
    "pct":   _yr_pct.values,
    "color": _yr_pct.apply(lambda x: "#2E7D32" if x >= 0 else "#C62828"),
})

_fig3 = go.Figure()
_fig3.add_trace(go.Bar(
    x=_ann_df["year"], y=_ann_df["pct"],
    marker_color=_ann_df["color"],
    text=_ann_df["pct"].apply(lambda v: f"{v:+.0f}%"),
    textposition="outside", textfont=dict(size=9),
    hovertemplate="%{x}年：%{y:+.1f}%<extra></extra>",
))
_fig3.add_hline(y=0, line_color="white", line_width=1)
_fig3.update_layout(
    xaxis_title="年份", yaxis_title="年度收益率（%）",
    yaxis=dict(ticksuffix="%"),
    height=480, bargap=0.25,
    margin=dict(t=40, b=40, l=60, r=20),
    hovermode="x unified",
)
st.plotly_chart(_fig3, use_container_width=True)

_pos = _ann_df[_ann_df["pct"] >= 0]
_neg = _ann_df[_ann_df["pct"] < 0]
_c1, _c2, _c3, _c4 = st.columns(4)
_c1.metric("上涨年数", f"{len(_pos)} 年", f"共 {len(_ann_df)} 年")
_c2.metric("下跌年数", f"{len(_neg)} 年")
_c3.metric("最大涨幅", f"{_ann_df['pct'].max():+.0f}%",
           f"{int(_ann_df.loc[_ann_df['pct'].idxmax(), 'year'])} 年")
_c4.metric("最大跌幅", f"{_ann_df['pct'].min():+.0f}%",
           f"{int(_ann_df.loc[_ann_df['pct'].idxmin(), 'year'])} 年")

# ─── 四、比特币ETF上市以来价格走势对比 ─────────────────────────────
st.subheader("四、比特币 ETF 上市以来价格走势对比（2024-01-11 至今）")
st.markdown(
    "2024年1月11日，美国SEC批准首批现货比特币ETF上市。以下将 BTC-USD、IBIT、FBTC、GBTC "
    "的价格**归一化至100**，比较各标的自ETF上市以来的相对表现。"
)

# 对齐到ETF上市后的共同交易日
_etf_start = pd.Timestamp("2024-01-11")
_btc_etf  = _btc[_btc.index >= _etf_start]
_gbtc_etf = _gbtc[_gbtc.index >= _etf_start]

_common = _btc_etf.index \
    .intersection(_ibit.index) \
    .intersection(_fbtc.index) \
    .intersection(_gbtc_etf.index)

_base = {
    "BTC-USD": _btc_etf.loc[_common],
    "IBIT":    _ibit.loc[_common],
    "FBTC":    _fbtc.loc[_common],
    "GBTC":    _gbtc_etf.loc[_common],
}

_colors = {
    "BTC-USD": "#F7931A",
    "IBIT":    "#1E88E5",
    "FBTC":    "#2E7D32",
    "GBTC":    "#7B1FA2",
}

_fig4 = go.Figure()
for _name, _ser in _base.items():
    _norm = _ser / _ser.iloc[0] * 100
    _fig4.add_trace(go.Scatter(
        x=_norm.index, y=_norm.values,
        mode="lines", name=_name,
        line=dict(color=_colors[_name], width=1.8),
        hovertemplate=f"{_name}  %{{x|%Y-%m-%d}}  %{{y:.1f}}<extra></extra>",
    ))
_fig4.update_layout(
    xaxis_title="日期", yaxis_title="归一化价格（起点=100）",
    height=420, hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    margin=dict(t=40, b=40, l=70),
)
st.plotly_chart(_fig4, use_container_width=True)

# ETF上市以来各标的关键指标对比
st.markdown("**各标的自 2024-01-11 以来关键指标对比：**")
_etf_rows = []
for _name, _ser in _base.items():
    _ser_dd = (_ser - _ser.expanding().max()) / _ser.expanding().max() * 100
    _n = ((_ser.index[-1] - _ser.index[0]).days)
    _total_ret = _ser.iloc[-1] / _ser.iloc[0] - 1
    _etf_rows.append({
        "标的":        _name,
        "起始价":      f"${_ser.iloc[0]:,.2f}",
        "最新价":      f"${_ser.iloc[-1]:,.2f}",
        "区间总收益":  f"{_total_ret:+.1%}",
        "最大回撤":    f"{_ser_dd.min():.1f}%",
        "数据天数":    f"{_n} 天",
    })
st.dataframe(pd.DataFrame(_etf_rows), use_container_width=True, hide_index=True)

# ── 跟踪误差分析 ──────────────────────────────────────────────────────
st.markdown("**各比特币ETF对BTC-USD的价格跟踪误差：**")
st.markdown(
    "以 BTC-USD 为基准，计算各ETF的跟踪质量。"
    "跟踪差异（Tracking Difference）= ETF区间总收益 − BTC同期总收益；"
    "年化跟踪误差（Tracking Error）= 日收益差的标准差 × √252。"
)

# 计算每日对数收益率，再求差
_btc_ret  = _base["BTC-USD"].pct_change().dropna()
_te_rows  = []
_etf_names = [n for n in _base if n != "BTC-USD"]

for _name in _etf_names:
    _etf_ret = _base[_name].pct_change().dropna()
    _common_idx = _btc_ret.index.intersection(_etf_ret.index)
    _diff = _etf_ret.loc[_common_idx] - _btc_ret.loc[_common_idx]
    _td   = ((_base[_name].iloc[-1] / _base[_name].iloc[0]) -
             (_base["BTC-USD"].iloc[-1] / _base["BTC-USD"].iloc[0]))   # 绝对差（百分点）
    _btc_total = _base["BTC-USD"].iloc[-1] / _base["BTC-USD"].iloc[0] - 1
    _etf_total = _base[_name].iloc[-1] / _base[_name].iloc[0] - 1
    _te_rows.append({
        "ETF":              _name,
        "跟踪差异（区间）":  f"{(_etf_total - _btc_total):+.2%}",
        "平均日偏差":        f"{_diff.mean() * 100:+.4f}%",
        "年化跟踪误差（TE）": f"{_diff.std() * (252 ** 0.5) * 100:.3f}%",
        "最大单日正偏差":    f"{_diff.max() * 100:+.2f}%",
        "最大单日负偏差":    f"{_diff.min() * 100:+.2f}%",
        "样本交易日数":      len(_common_idx),
    })
st.dataframe(pd.DataFrame(_te_rows), use_container_width=True, hide_index=True)

# 累计跟踪差异走势图（ETF相对BTC的超额/落后累计）
st.markdown("**各ETF相对BTC-USD的累计跟踪差异走势（百分点，起点=0）：**")
_fig_te = go.Figure()
for _name in _etf_names:
    _etf_ret = _base[_name].pct_change().dropna()
    _common_idx = _btc_ret.index.intersection(_etf_ret.index)
    _cum_diff = (_etf_ret.loc[_common_idx] - _btc_ret.loc[_common_idx]).cumsum() * 100
    _fig_te.add_trace(go.Scatter(
        x=_cum_diff.index, y=_cum_diff.values,
        mode="lines", name=_name,
        line=dict(color=_colors[_name], width=1.5),
        hovertemplate=f"{_name}  %{{x|%Y-%m-%d}}  累计偏差 %{{y:+.2f}}ppt<extra></extra>",
    ))
_fig_te.add_hline(y=0, line_color="white", line_width=1, line_dash="dot")
_fig_te.update_layout(
    xaxis_title="日期",
    yaxis_title="ETF − BTC 累计日收益差（百分点）",
    yaxis=dict(ticksuffix=" ppt"),
    height=360, hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    margin=dict(t=40, b=40, l=80),
)
st.plotly_chart(_fig_te, use_container_width=True)
st.markdown(
    "曲线在0轴以上：ETF累计收益**优于**BTC（含管理费抵消后仍有正偏差，通常为复权/分红处理差异）；"
    "曲线在0轴以下：ETF累计收益**落后**于BTC（主要来源：管理费、买卖价差、溢折价）。"
)

# ── 长期持有费用损耗测算 ──────────────────────────────────────────────
st.markdown("**持有不同年限，各ETF相对比特币的理论价格损耗（基于年化管理费）：**")
st.markdown(
    "损耗 = 1 − (1 − 年管理费率)ᴺ，仅含年度管理费，不含买卖价差和溢折价。  \n"
    "数据来源：各ETF官方公布年管理费率（IBIT 0.25%，FBTC 0.25%，GBTC 1.50%）。"
)

_fees = {"IBIT": 0.0025, "FBTC": 0.0025, "GBTC": 0.0150}
_hold_years = [1, 3, 5, 10, 20]

_drag_rows = []
for _etf, _fee in _fees.items():
    _row = {"ETF": _etf, "年管理费率": f"{_fee:.2%}"}
    for _yr in _hold_years:
        _drag = (1 - (1 - _fee) ** _yr) * 100
        _row[f"持有{_yr}年损耗"] = f"{_drag:.2f}%"
    _drag_rows.append(_row)
st.dataframe(pd.DataFrame(_drag_rows), use_container_width=True, hide_index=True)

# 损耗对比柱状图
_fig_drag = go.Figure()
_x = [f"{y}年" for y in _hold_years]
for _etf, _fee in _fees.items():
    _y = [(1 - (1 - _fee) ** y) * 100 for y in _hold_years]
    _fig_drag.add_trace(go.Bar(
        name=_etf, x=_x, y=_y,
        marker_color=_colors[_etf],
        text=[f"{v:.1f}%" for v in _y],
        textposition="outside",
        textfont=dict(size=10),
        hovertemplate=f"{_etf}  持有%{{x}}  损耗 %{{y:.2f}}%<extra></extra>",
    ))
_fig_drag.update_layout(
    barmode="group",
    xaxis_title="持有年限",
    yaxis_title="相对BTC的损耗（%）",
    yaxis=dict(ticksuffix="%"),
    height=400,
    bargap=0.2, bargroupgap=0.05,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    margin=dict(t=40, b=40, l=70, r=20),
)
st.plotly_chart(_fig_drag, use_container_width=True)
st.markdown(
    "**结论**：IBIT 和 FBTC 管理费均为 0.25%/年，长期持有损耗可控（持有20年约损耗 4.9%）；"
    "GBTC 管理费高达 1.50%/年，持有10年损耗约 14%，持有20年损耗约 26%，长期持有成本显著更高。"
)
