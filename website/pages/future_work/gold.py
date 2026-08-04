"""黄金历史价格与回撤分析"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io

st.title("黄金价格历史分析")

# ─── 数据加载（优先 FRED 1968年起，降级到 yfinance 2000年起）──────
@st.cache_data(ttl=86400)
def _load_gold() -> tuple:
    """Returns (pd.Series, source_label)"""
    # 1) 尝试 FRED：LBMA 黄金下午定盘价，1968年起
    try:
        url = (
            "https://fred.stlouisfed.org/graph/fredgraph.csv"
            "?id=GOLDAMGBD228NLBM"
        )
        r = requests.get(
            url, timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (compatible; gold-analysis/1.0)"},
        )
        if r.status_code == 200 and "Date" in r.text[:200]:
            df = pd.read_csv(
                io.StringIO(r.text), index_col=0,
                parse_dates=True, na_values=".",
            )
            s = df.iloc[:, 0].dropna().astype(float).sort_index()
            s.index = pd.to_datetime(s.index)
            if s.index.tz is not None:
                s.index = s.index.tz_convert(None)
            if len(s) > 5000:   # 合理性校验
                return s.rename("gold"), "FRED — LBMA 伦敦黄金下午定盘价（1968 年起）"
    except Exception:
        pass

    # 2) 降级到 yfinance GC=F（COMEX 黄金期货连续合约，2000年起）
    import yfinance as yf
    from datetime import date as _date
    raw = yf.download(
        "GC=F", start="2000-01-01",
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
    return s.sort_index().rename("gold"), "Yahoo Finance — GC=F 黄金期货连续合约（2000 年起）"

with st.spinner("正在加载黄金价格数据…"):
    _prices, _src_label = _load_gold()

st.markdown(
    f"数据来源：**{_src_label}**  \n"
    f"数据范围：**{_prices.index[0].strftime('%Y-%m-%d')}** 至 **{_prices.index[-1].strftime('%Y-%m-%d')}**，"
    f"共 **{len(_prices):,}** 个交易日。"
)

# 全程 ATH 与回撤序列
_ath = _prices.expanding().max()
_dd  = (_prices - _ath) / _ath * 100   # 百分比，负值

# ─── 一、历史价格图 ─────────────────────────────────────────────────
st.subheader("一、黄金历史价格（日线，对数坐标）")

_fig1 = go.Figure()
_fig1.add_trace(go.Scatter(
    x=_prices.index, y=_prices.values,
    mode="lines", name="收盘价",
    line=dict(color="#FFD700", width=1.2),
    hovertemplate="%{x|%Y-%m-%d}  $%{y:,.1f}<extra></extra>",
))
_fig1.add_trace(go.Scatter(
    x=_ath.index, y=_ath.values,
    mode="lines", name="历史高点（ATH）",
    line=dict(color="#B8860B", width=1, dash="dot"),
    hovertemplate="%{x|%Y-%m-%d} ATH $%{y:,.1f}<extra></extra>",
))
_fig1.update_layout(
    xaxis_title="日期",
    yaxis_title="价格（USD/oz）",
    yaxis_type="log",
    height=480,
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    margin=dict(t=40, b=40, l=70),
)
st.plotly_chart(_fig1, use_container_width=True)
st.markdown("纵轴使用**对数刻度**，使 $100 量级（1970s）与 $3,000+ 量级（2020s）均清晰可见。")

# 日线数据三项关键指标
_n_cal_days = (_prices.index[-1] - _prices.index[0]).days
_cagr = (_prices.iloc[-1] / _prices.iloc[0]) ** (365.0 / _n_cal_days) - 1
_max_dd_val = _dd.min()

# 最大水下时间：连续处于历史高点以下的最长日历天数
_underwater = _dd < 0
_max_uw_days = 0
_uw_start = None
_uw_best_start = None
_uw_best_end = None
for _dt, _is_uw in _underwater.items():
    if _is_uw:
        if _uw_start is None:
            _uw_start = _dt
    else:
        if _uw_start is not None:
            _dur = (_dt - _uw_start).days
            if _dur > _max_uw_days:
                _max_uw_days = _dur
                _uw_best_start = _uw_start
                _uw_best_end = _dt
            _uw_start = None
if _uw_start is not None:
    _dur = (_prices.index[-1] - _uw_start).days
    if _dur > _max_uw_days:
        _max_uw_days = _dur
        _uw_best_start = _uw_start
        _uw_best_end = None
_uw_range = (
    f"{_uw_best_start.strftime('%Y-%m')} 至今"
    if _uw_best_end is None
    else f"{_uw_best_start.strftime('%Y-%m')} 至 {_uw_best_end.strftime('%Y-%m')}"
)

_mdd_trough_dt = _dd.idxmin()
_after_trough = _dd.loc[_mdd_trough_dt:]
_recovery_after_trough = _after_trough[_after_trough >= 0]
if len(_recovery_after_trough) > 0:
    _ttr_recovery_dt = _recovery_after_trough.index[0]
    _ttr_days = (_ttr_recovery_dt - _mdd_trough_dt).days
    _ttr_val = f"{_ttr_days / 365:.1f} 年"
    _ttr_sub = f"{_mdd_trough_dt.strftime('%Y-%m')} → {_ttr_recovery_dt.strftime('%Y-%m')}"
else:
    _ttr_val = "至今未恢复"
    _ttr_sub = f"最低点 {_mdd_trough_dt.strftime('%Y-%m')}"

_km1, _km2, _km3, _km4 = st.columns(4)
_km1.metric(
    "年化收益（CAGR）",
    f"{_cagr:+.2%}",
    f"{_prices.index[0].strftime('%Y-%m-%d')} 至 {_prices.index[-1].strftime('%Y-%m-%d')}",
    delta_color="off",
)
_km2.metric("历史最大回撤", f"{_max_dd_val:.1f}%")
_km3.metric(
    "最大水下时间",
    f"{_max_uw_days / 365:.1f} 年",
    _uw_range,
    delta_color="off",
)
_km4.metric("最低点→复原", _ttr_val, _ttr_sub, delta_color="off")

# ─── 二、回撤时序图 ─────────────────────────────────────────────────
st.subheader("二、黄金价格回撤时序图（相对历史高点）")

_fig2 = go.Figure()
_fig2.add_trace(go.Scatter(
    x=_dd.index, y=_dd.values,
    mode="lines", name="回撤幅度",
    line=dict(color="#EF5350", width=1),
    fill="tozeroy",
    fillcolor="rgba(239,83,80,0.12)",
    hovertemplate="%{x|%Y-%m-%d}  %{y:.1f}%<extra></extra>",
))
for _lvl, _col in [(-30, "#E65100"), (-50, "#B71C1C"), (-70, "#4A148C")]:
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
    yaxis=dict(ticksuffix="%", range=[min(_dd.min() * 1.1, -78), 5]),
    height=380,
    hovermode="x unified",
    margin=dict(t=40, b=40, l=70),
)
st.plotly_chart(_fig2, use_container_width=True)

# ─── 三、回撤 >30% 详细分析 ────────────────────────────────────────
st.subheader("三、超过 30% 的历史回撤详细分析")


def _find_drawdowns(s: pd.Series, thresh: float = 0.30) -> list:
    """
    状态机：遍历价格序列，找出所有从 ATH 下跌超过 thresh 的回撤区间。
    每个区间记录：峰值、低谷、复原日期及各阶段天数。
    """
    periods     = []
    in_dd       = False
    running_max = float(s.iloc[0])
    peak_dt     = s.index[0];  peak_px   = running_max
    trough_dt   = s.index[0];  trough_px = running_max

    for dt, px in s.items():
        px = float(px)
        if px >= running_max:
            if in_dd:
                mdd = (trough_px - peak_px) / peak_px
                if mdd <= -thresh:
                    periods.append(dict(
                        peak_dt=peak_dt,     peak_px=peak_px,
                        trough_dt=trough_dt, trough_px=trough_px,
                        recovery_dt=dt,      mdd=mdd,
                        d_pt=(trough_dt - peak_dt).days,
                        d_tr=(dt - trough_dt).days,
                        d_tot=(dt - peak_dt).days,
                    ))
                in_dd = False
            running_max = px
            peak_dt   = dt; peak_px   = px
            trough_dt = dt; trough_px = px
        else:
            if not in_dd:
                in_dd     = True
                trough_dt = dt; trough_px = px
            elif px < trough_px:
                trough_dt = dt; trough_px = px

    # 当前仍处于回撤中
    if in_dd:
        mdd = (trough_px - peak_px) / peak_px
        if mdd <= -thresh:
            periods.append(dict(
                peak_dt=peak_dt,     peak_px=peak_px,
                trough_dt=trough_dt, trough_px=trough_px,
                recovery_dt=None,    mdd=mdd,
                d_pt=(trough_dt - peak_dt).days,
                d_tr=None,
                d_tot=(s.index[-1] - peak_dt).days,
            ))
    return periods


_dds = _find_drawdowns(_prices, 0.30)

if not _dds:
    st.info("数据范围内未发现超过 30% 的回撤。")
else:
    # 汇总表
    _sum_rows = []
    for _i, _d in enumerate(_dds, 1):
        _sum_rows.append({
            "#":            _i,
            "峰值日期":     _d["peak_dt"].strftime("%Y-%m"),
            "峰值价格":     f"${_d['peak_px']:,.0f}",
            "低谷日期":     _d["trough_dt"].strftime("%Y-%m"),
            "低谷价格":     f"${_d['trough_px']:,.0f}",
            "最大回撤":     f"{_d['mdd']:.1%}",
            "峰→谷（天）":  _d["d_pt"],
            "谷→复原（天）": _d["d_tr"] if _d["d_tr"] is not None else "—",
            "总持续（天）": _d["d_tot"],
            "复原日期":     _d["recovery_dt"].strftime("%Y-%m") if _d["recovery_dt"] else "至今未恢复",
        })
    st.dataframe(pd.DataFrame(_sum_rows), use_container_width=True, hide_index=True)

    st.markdown("---")

    # 逐事件详细图表
    for _i, _d in enumerate(_dds, 1):
        _ongoing = _d["recovery_dt"] is None
        _hdr = (
            f"#{_i}  峰值 {_d['peak_dt'].strftime('%Y-%m')} (${_d['peak_px']:,.0f})"
            f" → 最大回撤 {_d['mdd']:.1%}"
            + ("（至今未恢复）" if _ongoing
               else f" → 复原 {_d['recovery_dt'].strftime('%Y-%m')}")
        )
        with st.expander(_hdr, expanded=True):
            # 前后各留 6 个月的展示窗口
            _pad = pd.Timedelta(days=180)
            _s0  = max(_prices.index[0], _d["peak_dt"] - _pad)
            _s1  = min(
                _prices.index[-1],
                (_d["recovery_dt"] + _pad) if _d["recovery_dt"] else _prices.index[-1],
            )
            _seg = _prices[_s0:_s1]

            _fig = go.Figure()
            _fig.add_trace(go.Scatter(
                x=_seg.index, y=_seg.values,
                mode="lines", name="黄金价格",
                line=dict(color="#FFD700", width=1.5),
                hovertemplate="%{x|%Y-%m-%d}  $%{y:,.1f}<extra></extra>",
            ))
            # 回撤区间阴影
            _fig.add_vrect(
                x0=_d["peak_dt"].strftime("%Y-%m-%d"),
                x1=(_d["recovery_dt"].strftime("%Y-%m-%d") if _d["recovery_dt"]
                    else _prices.index[-1].strftime("%Y-%m-%d")),
                fillcolor="rgba(239,83,80,0.10)",
                line_width=0,
            )
            # 峰值
            _fig.add_vline(
                x=_d["peak_dt"].strftime("%Y-%m-%d"),
                line_dash="dash", line_color="#2E7D32",
                annotation_text=f"峰值 ${_d['peak_px']:,.0f}",
                annotation_position="top right",
                annotation_font_color="#2E7D32",
            )
            # 低谷
            _fig.add_vline(
                x=_d["trough_dt"].strftime("%Y-%m-%d"),
                line_dash="dash", line_color="#C62828",
                annotation_text=f"低谷 ${_d['trough_px']:,.0f}（{_d['mdd']:.1%}）",
                annotation_position="top left",
                annotation_font_color="#C62828",
            )
            # 复原
            if _d["recovery_dt"]:
                _fig.add_vline(
                    x=_d["recovery_dt"].strftime("%Y-%m-%d"),
                    line_dash="dash", line_color="#1565C0",
                    annotation_text="复原",
                    annotation_position="top right",
                    annotation_font_color="#1565C0",
                )
            _fig.update_layout(
                height=320,
                showlegend=False,
                xaxis_title="日期",
                yaxis_title="USD/oz",
                hovermode="x unified",
                margin=dict(t=30, b=40, l=70, r=20),
            )
            st.plotly_chart(_fig, use_container_width=True)

            # 关键指标
            _c1, _c2, _c3, _c4 = st.columns(4)
            _c1.metric("最大回撤", f"{_d['mdd']:.1%}")
            _c2.metric(
                "峰到谷",
                f"{_d['d_pt']:,} 天",
                f"约 {_d['d_pt'] / 365:.1f} 年",
                delta_color="off",
            )
            _c3.metric(
                "谷到复原",
                f"{_d['d_tr']:,} 天" if _d["d_tr"] is not None else "至今未恢复",
                f"约 {_d['d_tr'] / 365:.1f} 年" if _d["d_tr"] is not None else None,
                delta_color="off",
            )
            _c4.metric(
                "总持续时间",
                f"{_d['d_tot']:,} 天",
                f"约 {_d['d_tot'] / 365:.1f} 年",
                delta_color="off",
            )

# ─── 四、月线价格走势与回撤 ────────────────────────────────────────
st.subheader("四、黄金月线价格走势与回撤（1985 年至今）")
st.markdown("数据来源：Macrotrends，月末收盘价，美元/盎司。")

_mo_csv = _root / "data" / "gold" / "gold_monthly_prices.csv"
_mo = pd.read_csv(_mo_csv, parse_dates=["date"], index_col="date").sort_index()
_mo_px  = _mo["price_usd"]
_mo_ath = _mo_px.expanding().max()
_mo_dd  = (_mo_px - _mo_ath) / _mo_ath * 100

# 月线三项关键指标
_mo_n_days = (_mo_px.index[-1] - _mo_px.index[0]).days
_mo_cagr = (_mo_px.iloc[-1] / _mo_px.iloc[0]) ** (365.0 / _mo_n_days) - 1
_mo_max_dd_val = _mo_dd.min()

_mo_underwater = _mo_dd < 0
_mo_max_uw_days = 0
_mo_uw_start = None
for _dt, _is_uw in _mo_underwater.items():
    if _is_uw:
        if _mo_uw_start is None:
            _mo_uw_start = _dt
    else:
        if _mo_uw_start is not None:
            _dur = (_dt - _mo_uw_start).days
            _mo_max_uw_days = max(_mo_max_uw_days, _dur)
            _mo_uw_start = None
if _mo_uw_start is not None:
    _mo_max_uw_days = max(_mo_max_uw_days, (_mo_px.index[-1] - _mo_uw_start).days)

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
    f"约 {round(_mo_max_uw_days / 30)} 个月",
    delta_color="off",
)
_mm4.metric("最低点→复原", _mo_ttr_val, _mo_ttr_sub, delta_color="off")

# 4a 价格走势（对数坐标）
_fig_mo1 = go.Figure()
_fig_mo1.add_trace(go.Scatter(
    x=_mo_px.index, y=_mo_px.values,
    mode="lines", name="月末价格",
    line=dict(color="#FFD700", width=1.8),
    hovertemplate="%{x|%Y-%m}  $%{y:,.1f}<extra></extra>",
))
_fig_mo1.add_trace(go.Scatter(
    x=_mo_ath.index, y=_mo_ath.values,
    mode="lines", name="历史高点（ATH）",
    line=dict(color="#B8860B", width=1, dash="dot"),
    hovertemplate="%{x|%Y-%m} ATH $%{y:,.1f}<extra></extra>",
))
_fig_mo1.update_layout(
    xaxis_title="日期", yaxis_title="价格（USD/oz）",
    yaxis_type="log",
    height=420, hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    margin=dict(t=40, b=40, l=70),
)
st.plotly_chart(_fig_mo1, use_container_width=True)

# 4b 回撤走势
_fig_mo2 = go.Figure()
_fig_mo2.add_trace(go.Scatter(
    x=_mo_dd.index, y=_mo_dd.values,
    mode="lines", name="回撤幅度",
    line=dict(color="#EF5350", width=1.2),
    fill="tozeroy", fillcolor="rgba(239,83,80,0.12)",
    hovertemplate="%{x|%Y-%m}  %{y:.1f}%<extra></extra>",
))
for _lvl, _col in [(-30, "#E65100"), (-50, "#B71C1C")]:
    _fig_mo2.add_hline(
        y=_lvl, line_dash="dash", line_color=_col,
        annotation_text=f"{_lvl}%", annotation_position="left",
        annotation_font_color=_col, annotation_font_size=11,
    )
_fig_mo2.update_layout(
    xaxis_title="日期", yaxis_title="回撤（%）",
    yaxis=dict(ticksuffix="%", range=[min(_mo_dd.min() * 1.1, -55), 5]),
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
            "峰值价格": f"${_d['peak_px']:,.0f}",
            "低谷日期": _d["trough_dt"].strftime("%Y-%m"),
            "低谷价格": f"${_d['trough_px']:,.0f}",
            "最大回撤": f"{_d['mdd']:.1%}",
            "峰→谷（月）": round(_d["d_pt"] / 30),
            "谷→复原（月）": round(_d["d_tr"] / 30) if _d["d_tr"] else "—",
            "总持续（月）": round(_d["d_tot"] / 30),
            "复原日期": _d["recovery_dt"].strftime("%Y-%m") if _d["recovery_dt"] else "至今未恢复",
        })
    st.dataframe(pd.DataFrame(_mo_rows), use_container_width=True, hide_index=True)

# ─── 五、年均价格走势与回撤 ────────────────────────────────────────
st.subheader("五、黄金年均价格走势与回撤（1967–2026）")
st.markdown("数据来源：Macrotrends，年度平均价格，美元/盎司。覆盖最完整的长期历史（近 60 年）。")

_yr_csv = _root / "data" / "gold" / "gold_annual_avg_price.csv"
_yr     = pd.read_csv(_yr_csv)
_yr["date"] = pd.to_datetime(_yr["year"].astype(str) + "-12-31")
_yr = _yr.set_index("date").sort_index()
_yr_px  = _yr["price_usd"]
_yr_ath = _yr_px.expanding().max()
_yr_dd  = (_yr_px - _yr_ath) / _yr_ath * 100

# 年均三项关键指标
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

# 5a 年均价格走势（对数坐标）
_fig_yr1 = go.Figure()
_fig_yr1.add_trace(go.Scatter(
    x=_yr_px.index, y=_yr_px.values,
    mode="lines+markers", name="年均价格",
    line=dict(color="#FFD700", width=2),
    marker=dict(size=5, color="#FFD700"),
    hovertemplate="%{x|%Y}  $%{y:,.2f}<extra></extra>",
))
_fig_yr1.add_trace(go.Scatter(
    x=_yr_ath.index, y=_yr_ath.values,
    mode="lines", name="历史高点（ATH）",
    line=dict(color="#B8860B", width=1, dash="dot"),
    hovertemplate="%{x|%Y} ATH $%{y:,.2f}<extra></extra>",
))
_fig_yr1.update_layout(
    xaxis_title="年份", yaxis_title="年均价格（USD/oz）",
    yaxis_type="log",
    height=420, hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    margin=dict(t=40, b=40, l=70),
)
st.plotly_chart(_fig_yr1, use_container_width=True)

# 5b 年均价格回撤走势
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
    yaxis=dict(ticksuffix="%", range=[min(_yr_dd.min() * 1.1, -75), 5]),
    height=350, hovermode="x unified",
    margin=dict(t=30, b=40, l=70),
)
st.plotly_chart(_fig_yr2, use_container_width=True)

# 年均价格回撤事件 >30%
_yr_dds = _find_drawdowns(_yr_px, 0.30)
if _yr_dds:
    st.markdown("**年均价格识别的超过 30% 回撤事件：**")
    _yr_rows = []
    for _i, _d in enumerate(_yr_dds, 1):
        _yr_rows.append({
            "#": _i,
            "峰值年份": _d["peak_dt"].year,
            "峰值年均价": f"${_d['peak_px']:,.2f}",
            "低谷年份": _d["trough_dt"].year,
            "低谷年均价": f"${_d['trough_px']:,.2f}",
            "最大回撤": f"{_d['mdd']:.1%}",
            "峰→谷（年）": round(_d["d_pt"] / 365),
            "谷→复原（年）": round(_d["d_tr"] / 365) if _d["d_tr"] else "—",
            "总持续（年）": round(_d["d_tot"] / 365),
            "复原年份": _d["recovery_dt"].year if _d["recovery_dt"] else "至今未恢复",
        })
    st.dataframe(pd.DataFrame(_yr_rows), use_container_width=True, hide_index=True)

# ─── 六、年度收益柱状图 ─────────────────────────────────────────────
st.subheader("六、黄金年度收益历史（1969–2026）")
st.markdown("数据来源：Macrotrends，名义价格年度收益率。")

_ann_csv = _root / "data" / "gold" / "gold_annual_returns.csv"
_ann = pd.read_csv(_ann_csv)
_ann = _ann.sort_values("year").reset_index(drop=True)
_ann["pct"] = _ann["annual_return"] * 100
_ann["color"] = _ann["annual_return"].apply(
    lambda x: "#2E7D32" if x >= 0 else "#C62828"
)

_fig4 = go.Figure()
_fig4.add_trace(go.Bar(
    x=_ann["year"],
    y=_ann["pct"],
    marker_color=_ann["color"],
    text=_ann["pct"].apply(lambda v: f"{v:+.1f}%"),
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

# 统计摘要
_pos = _ann[_ann["annual_return"] >= 0]
_neg = _ann[_ann["annual_return"] < 0]
_c1, _c2, _c3, _c4 = st.columns(4)
_c1.metric("上涨年数", f"{len(_pos)} 年", f"共 {len(_ann)} 年")
_c2.metric("下跌年数", f"{len(_neg)} 年")
_c3.metric("最大涨幅", f"{_ann['pct'].max():+.1f}%",
           f"{int(_ann.loc[_ann['pct'].idxmax(), 'year'])} 年")
_c4.metric("最大跌幅", f"{_ann['pct'].min():+.1f}%",
           f"{int(_ann.loc[_ann['pct'].idxmin(), 'year'])} 年")
