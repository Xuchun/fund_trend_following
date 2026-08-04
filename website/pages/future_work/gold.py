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
    _prices = _load_gold()

st.markdown(
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
