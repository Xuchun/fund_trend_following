"""策略1.0 过拟合分析（模拟交易数据）"""

import sys
import json
from pathlib import Path

_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
import pandas as pd
import scipy.stats as _stats
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from website.style import show_df, POSITIVE_COLOR, NEGATIVE_COLOR

# ── Paths ─────────────────────────────────────────────────────────────────────
_results = _root / "results" / "v1_unbiased_60m_2000"
_pt_file = _root / "results" / "paper_trading" / "positions.json"

# ── Page header ───────────────────────────────────────────────────────────────
st.title("策略1.0 过拟合分析（模拟交易数据）")
st.markdown(
    "从多个维度检验策略1.0在历史数据上是否过度拟合——"
    "通过对比模拟交易的样本外表现与回测的样本内表现，量化策略真实 Alpha 的可信度。"
)
st.markdown("---")

# ── Load data ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120)
def _load_pt():
    if not _pt_file.exists():
        return {}
    return json.loads(_pt_file.read_text())

@st.cache_data(ttl=86400)
def _load_bt():
    try:
        m      = json.loads((_results / "metrics.json").read_text())
        nav    = pd.read_csv(_results / "nav.csv",    index_col=0, parse_dates=True)
        trades = pd.read_csv(_results / "trades.csv", parse_dates=["entry_date", "exit_date"])
        return m, nav, trades
    except FileNotFoundError:
        return {}, pd.DataFrame(), pd.DataFrame()

_pt               = _load_pt()
_bt_m, _bt_nav, _bt_trades = _load_bt()

# ── Parse paper trading data ──────────────────────────────────────────────────
_ct_raw   = _pt.get("closed_trades", [])
_nav_h    = _pt.get("nav_history",   [])
_sig_h    = _pt.get("signals_history", [])
_init_nav = float(_pt.get("initial_nav", 200_000))

ct = pd.DataFrame(_ct_raw).copy() if _ct_raw else pd.DataFrame()
if not ct.empty:
    for _col in ["entry_date", "exit_date", "signal_date", "detected_date"]:
        if _col in ct.columns:
            ct[_col] = pd.to_datetime(ct[_col], errors="coerce")
    for _col in ["pnl_r", "holding_days", "signal_strength", "atr_at_entry",
                 "entry_price", "stop_loss", "highest_high", "lowest_low"]:
        if _col in ct.columns:
            ct[_col] = pd.to_numeric(ct[_col], errors="coerce")
    # 如果 stop_distance_pct 未存入（旧版本数据），在页面里动态计算
    if "stop_distance_pct" not in ct.columns and "entry_price" in ct.columns and "stop_loss" in ct.columns:
        _ep = ct["entry_price"].replace(0, np.nan)
        ct["stop_distance_pct"] = (ct["entry_price"] - ct["stop_loss"]) / _ep

nav_df = pd.DataFrame()
if _nav_h:
    nav_df = (pd.DataFrame(_nav_h)
              .assign(date=lambda d: pd.to_datetime(d["date"]))
              .sort_values("date")
              .set_index("date"))
    nav_df["nav"] = pd.to_numeric(nav_df["nav"], errors="coerce")

sig_df = pd.DataFrame()
if _sig_h:
    sig_df = (pd.DataFrame(_sig_h)
              .assign(date=lambda d: pd.to_datetime(d["date"]))
              .sort_values("date"))
    for _c in ["n_raw_breakouts","n_candidates","n_heat_blocked","n_cash_blocked","n_corr_reduced",
               "n_price_filtered","n_adv_filtered","n_breakout_filtered",
               "n_atr_filtered","n_stop_dist_filtered","n_volume_filtered",
               "spy_pct_above_sma200"]:
        if _c in sig_df.columns:
            sig_df[_c] = pd.to_numeric(sig_df[_c], errors="coerce")

# ── Backtest R series (pnl_r_multiple) ───────────────────────────────────────
_bt_r = pd.Series(dtype=float)
if not _bt_trades.empty and "pnl_r_multiple" in _bt_trades.columns:
    _bt_r = _bt_trades["pnl_r_multiple"].dropna()

n_closed = len(ct)
_MIN_CHART = 5   # minimum trades to show charts
_MIN_STATS = 20  # minimum trades to run statistical tests

# ── 一、数据状态与统计功效 ────────────────────────────────────────────────────
st.subheader("一、数据状态与统计功效")

if _pt_file.exists():
    _last_upd = _pt.get("last_update_date", "N/A")
    _n_open   = len([p for p in _pt.get("positions", []) if not p.get("closed")])
    st.markdown(f"上次更新：**{_last_upd}** ｜ 当前持仓：**{_n_open}** 只 ｜ 已平仓：**{n_closed}** 笔")
else:
    st.warning("⚠️ 模拟交易尚未启动（positions.json 不存在），所有分析区域暂以空状态展示。")

_pwr_cols = st.columns(4)
_pwr_cols[0].metric("已平仓笔数",  n_closed,    help="统计检验需要 ≥ 20 笔才有初步意义")
_pwr_cols[1].metric("回测交易笔数", len(_bt_r) if len(_bt_r) else "—")

if n_closed >= _MIN_STATS and len(_bt_r) > 0:
    _pt_mean = ct["pnl_r"].mean() if "pnl_r" in ct.columns else np.nan
    _bt_mean = _bt_r.mean()
    _pwr_cols[2].metric("模拟均值R",  f"{_pt_mean:+.3f}" if not np.isnan(_pt_mean) else "—")
    _pwr_cols[3].metric("回测均值R",  f"{_bt_mean:+.3f}")
else:
    _pwr_cols[2].metric("模拟均值R", "—", help=f"需 ≥ {_MIN_STATS} 笔平仓")
    _pwr_cols[3].metric("回测均值R",
                        f"{_bt_r.mean():+.3f}" if len(_bt_r) else "—")

# Progress toward statistical significance
_target = 50
_progress = min(n_closed / _target, 1.0)
st.progress(_progress,
    text=f"统计功效进度：{n_closed}/{_target} 笔（目标 {_target} 笔后，t 检验具备约 80% 功效）")

if n_closed == 0:
    st.info("模拟交易尚无已平仓记录。以下各分析区域在积累足够交易数据后将自动填充。")

st.caption(
    "**读图指引**：若模拟交易各项指标与回测基准大幅偏离（尤其均值R下滑、胜率下降、分布右移消失），"
    "说明策略存在过拟合。若表现与回测基本一致（在统计误差范围内），说明策略具备样本外有效性。"
)
st.markdown("---")

# ── 二、核心指标对比 ──────────────────────────────────────────────────────────
st.subheader("二、核心指标对比（模拟 vs 回测）")
st.caption("回测为样本内全量数据基准；模拟为样本外结果（2026年起）。数字差距反映策略真实适应能力。")

def _pct(v): return f"{v*100:.1f}%" if v is not None and not np.isnan(v) else "—"
def _r(v):   return f"{v:+.3f}R"   if v is not None and not np.isnan(v) else "—"
def _d(v):   return f"{v:.0f} 天"  if v is not None and not np.isnan(v) else "—"
def _n(v):   return f"{v:.0f}"     if v is not None and not np.isnan(v) else "—"

# Paper trading metrics
_pt_cagr  = _pt_wr = _pt_avg_r = _pt_avg_w = _pt_avg_l = _pt_hdays = _pt_shr = None
if n_closed >= _MIN_STATS:
    _r_ser = ct["pnl_r"].dropna() if "pnl_r" in ct.columns else pd.Series(dtype=float)
    if len(_r_ser):
        _pt_wr    = (_r_ser > 0).mean()
        _pt_avg_r = _r_ser.mean()
        _pt_avg_w = _r_ser[_r_ser > 0].mean() if (_r_ser > 0).any() else np.nan
        _pt_avg_l = _r_ser[_r_ser <= 0].mean() if (_r_ser <= 0).any() else np.nan
    if "holding_days" in ct.columns:
        _pt_hdays = ct["holding_days"].dropna().mean()
    if len(nav_df) >= 20:
        _nav_ret   = nav_df["nav"].pct_change().dropna()
        _pt_shr    = _nav_ret.mean() / _nav_ret.std() * np.sqrt(252) if _nav_ret.std() > 0 else np.nan
        _n_years   = (nav_df.index[-1] - nav_df.index[0]).days / 365.25
        _pt_cagr   = (nav_df["nav"].iloc[-1] / _init_nav) ** (1 / _n_years) - 1 if _n_years > 0.1 else np.nan

_NA = "（需 ≥ 20 笔）"

def _cmp(pt_v, bt_v, fmt, good_dir=1):
    """Return (pt_str, bt_str, delta_str, delta_color)."""
    pt_s = fmt(pt_v) if pt_v is not None and (isinstance(pt_v, float) and not np.isnan(pt_v)) else _NA
    bt_s = fmt(bt_v) if bt_v is not None and (isinstance(bt_v, float) and not np.isnan(bt_v)) else "—"
    delta = "—"
    color = "normal"
    if pt_v is not None and bt_v is not None:
        try:
            d = pt_v - bt_v
            delta = f"{d:+.3f}"
            color = "normal" if d * good_dir >= 0 else "inverse"
        except Exception:
            pass
    return pt_s, bt_s, delta, color

_rows = [
    ("年化收益（CAGR）",   _pt_cagr,   _bt_m.get("cagr"),          _pct,  1),
    ("Sharpe 比率",        _pt_shr,    _bt_m.get("sharpe"),         _r,    1),
    ("胜率（Win Rate）",   _pt_wr,     _bt_m.get("win_rate"),       _pct,  1),
    ("均值 R（每笔）",     _pt_avg_r,  _bt_m.get("avg_win_r") and  # backtest avg_r per trade
                            (_bt_r.mean() if len(_bt_r) else None), _r,    1),
    ("盈利笔均值 R",       _pt_avg_w,  _bt_m.get("avg_win_r"),     _r,    1),
    ("亏损笔均值 R",       _pt_avg_l,  _bt_m.get("avg_loss_r"),    _r,   -1),
    ("平均持仓天数",       _pt_hdays,  _bt_m.get("avg_holding_days"), _d, -1),
]

_cmp_rows = []
for _label, _pt_v, _bt_v, _fmt, _gdir in _rows:
    _pt_s = _fmt(_pt_v) if (_pt_v is not None and isinstance(_pt_v, float) and not np.isnan(_pt_v)) else _NA
    _bt_s = _fmt(_bt_v) if (_bt_v is not None and isinstance(_bt_v, float) and not np.isnan(_bt_v)) else "—"
    _delta = "—"
    if _pt_v is not None and _bt_v is not None:
        try:
            _d_v = _pt_v - _bt_v
            _arrow = "▲" if _d_v * _gdir > 0 else "▼"
            _delta = f"{_arrow} {abs(_d_v):.3f}"
        except Exception:
            pass
    _cmp_rows.append({"指标": _label, "模拟交易（样本外）": _pt_s, "回测基准（样本内）": _bt_s, "差异": _delta})

show_df(pd.DataFrame(_cmp_rows), width="stretch", hide_index=True)

# Exit reason split
_exit_cols = st.columns(2)
with _exit_cols[0]:
    st.markdown("**退出原因分布（模拟）**")
    if n_closed >= _MIN_CHART and "exit_reason" in ct.columns:
        _pt_er = ct["exit_reason"].value_counts()
        _fig_er_pt = go.Figure(go.Pie(
            labels=_pt_er.index.tolist(),
            values=_pt_er.values.tolist(),
            marker_colors=["#d62728","#ff7f0e","#2ca02c"],
            hole=0.4, textinfo="label+percent",
        ))
        _fig_er_pt.update_layout(height=240, margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
        st.plotly_chart(_fig_er_pt, width="stretch")
    else:
        st.info(f"需 ≥ {_MIN_CHART} 笔平仓")
with _exit_cols[1]:
    st.markdown("**退出原因分布（回测）**")
    if not _bt_trades.empty and "exit_reason" in _bt_trades.columns:
        _bt_er = _bt_trades["exit_reason"].value_counts()
        _fig_er_bt = go.Figure(go.Pie(
            labels=_bt_er.index.tolist(),
            values=_bt_er.values.tolist(),
            marker_colors=["#d62728","#ff7f0e","#2ca02c"],
            hole=0.4, textinfo="label+percent",
        ))
        _fig_er_bt.update_layout(height=240, margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
        st.plotly_chart(_fig_er_bt, width="stretch")
    else:
        st.info("回测数据不可用")

st.markdown("---")

# ── 三、R 倍数分布对比 ────────────────────────────────────────────────────────
st.subheader("三、R 倍数分布对比")
st.caption(
    "若模拟交易的 R 分布与回测分布形态一致（均值、离散度相近），说明样本外无明显退化。"
    "若模拟分布整体左移（均值更低、亏损尾更重），是过拟合信号。"
)

if n_closed >= _MIN_CHART and "pnl_r" in ct.columns:
    _pt_r_clean = ct["pnl_r"].dropna()

    _fig_dist = go.Figure()
    _fig_dist.add_trace(go.Histogram(
        x=_bt_r, name="回测（样本内）",
        nbinsx=60, histnorm="probability density",
        marker_color="rgba(31,119,180,0.45)", marker_line_color="rgba(31,119,180,0.8)",
        marker_line_width=0.5,
    ))
    _fig_dist.add_trace(go.Histogram(
        x=_pt_r_clean, name="模拟（样本外）",
        nbinsx=30, histnorm="probability density",
        marker_color="rgba(214,39,40,0.6)", marker_line_color="rgba(214,39,40,0.9)",
        marker_line_width=0.7,
    ))
    _fig_dist.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.6)
    if len(_bt_r):
        _fig_dist.add_vline(x=float(_bt_r.mean()), line_dash="dot",
                            line_color="rgba(31,119,180,0.9)", line_width=2,
                            annotation_text=f"回测均值 {_bt_r.mean():+.2f}R",
                            annotation_position="top right")
    if len(_pt_r_clean):
        _fig_dist.add_vline(x=float(_pt_r_clean.mean()), line_dash="dot",
                            line_color="rgba(214,39,40,0.9)", line_width=2,
                            annotation_text=f"模拟均值 {_pt_r_clean.mean():+.2f}R",
                            annotation_position="top left")
    _fig_dist.update_layout(
        barmode="overlay", height=380,
        xaxis_title="R 倍数（pnl_r）", yaxis_title="概率密度",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=20, t=50, b=50), template="plotly_white",
    )
    st.plotly_chart(_fig_dist, width="stretch")

    # Statistical tests (only when enough data)
    if n_closed >= _MIN_STATS and len(_bt_r) > 0:
        _t_stat, _t_p  = _stats.ttest_1samp(_pt_r_clean, 0)
        _ks_stat, _ks_p = _stats.ks_2samp(_pt_r_clean, _bt_r)
        _test_cols = st.columns(3)
        _sig_t = "✅ 显著 > 0" if _t_p < 0.05 and _t_stat > 0 else ("❌ 不显著" if _t_p >= 0.05 else "⚠️ 显著 < 0")
        _sig_ks = "✅ 同分布（p≥0.05）" if _ks_p >= 0.05 else "⚠️ 分布差异显著（p<0.05）"
        _test_cols[0].metric("t 检验（均值R > 0？）",
                             f"t = {_t_stat:.2f}, p = {_t_p:.3f}", delta=_sig_t,
                             help="p < 0.05 且 t > 0：模拟均值R显著大于零，策略样本外有效")
        _test_cols[1].metric("KS 检验（分布一致性）",
                             f"D = {_ks_stat:.3f}, p = {_ks_p:.3f}", delta=_sig_ks,
                             help="p ≥ 0.05：分布未发生显著漂移；p < 0.05：过拟合信号")
        _bt_pf = (_bt_r[_bt_r > 0].sum() / abs(_bt_r[_bt_r <= 0].sum())) if (_bt_r <= 0).any() else np.inf
        _pt_pf = (_pt_r_clean[_pt_r_clean > 0].sum() / abs(_pt_r_clean[_pt_r_clean <= 0].sum())) if (_pt_r_clean <= 0).any() else np.inf
        _test_cols[2].metric("盈利因子（Profit Factor）",
                             f"模拟 {_pt_pf:.2f}  vs  回测 {_bt_pf:.2f}",
                             delta=f"{_pt_pf - _bt_pf:+.2f}",
                             delta_color="normal" if _pt_pf >= _bt_pf else "inverse",
                             help="模拟 PF ≥ 回测 PF：样本外盈利能力未退化")
    else:
        st.info(f"统计检验需 ≥ {_MIN_STATS} 笔平仓，当前 {n_closed} 笔。")
else:
    st.info(f"R 倍数分布图需 ≥ {_MIN_CHART} 笔平仓，当前 {n_closed} 笔。")

st.markdown("---")

# ── 四、累计 R 走势 ───────────────────────────────────────────────────────────
st.subheader("四、累计 R 走势（每笔顺序）")
st.caption(
    "横轴为第 N 笔交易，纵轴为累计 R。蓝色为回测（所有交易按时序），红色为模拟。"
    "若两曲线斜率相近，说明每笔交易的平均质量一致；模拟斜率明显低于回测是过拟合信号。"
)

_fig_cumr = go.Figure()
if len(_bt_r):
    _bt_r_sorted = _bt_trades.sort_values("entry_date")["pnl_r_multiple"].dropna() if "pnl_r_multiple" in _bt_trades.columns else _bt_r
    _fig_cumr.add_trace(go.Scatter(
        x=list(range(1, len(_bt_r_sorted) + 1)),
        y=_bt_r_sorted.cumsum().values,
        name="回测（样本内，全量）",
        line=dict(color="rgba(31,119,180,0.4)", width=1.2),
        hovertemplate="第 %{x} 笔<br>累计 R: %{y:.2f}<extra>回测</extra>",
    ))
    # Expected line: slope = mean R per trade
    _slope = float(_bt_r_sorted.mean())
    _n_expected = max(len(_bt_r_sorted), max(n_closed, 10))
    _fig_cumr.add_trace(go.Scatter(
        x=[0, _n_expected],
        y=[0, _slope * _n_expected],
        name=f"回测期望斜率（{_slope:+.3f}R/笔）",
        line=dict(color="rgba(31,119,180,0.9)", width=2, dash="dash"),
        hoverinfo="skip",
    ))

if n_closed >= _MIN_CHART and "pnl_r" in ct.columns:
    _ct_sorted = ct.sort_values("entry_date")["pnl_r"].dropna()
    _fig_cumr.add_trace(go.Scatter(
        x=list(range(1, len(_ct_sorted) + 1)),
        y=_ct_sorted.cumsum().values,
        name="模拟（样本外）",
        line=dict(color="#d62728", width=2.5),
        mode="lines+markers",
        marker_size=5,
        hovertemplate="第 %{x} 笔<br>累计 R: %{y:.2f}<extra>模拟</extra>",
    ))

_fig_cumr.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.4)
_fig_cumr.update_layout(
    xaxis_title="交易笔序号", yaxis_title="累计 R",
    height=380, template="plotly_white",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=50, r=20, t=50, b=50),
)
st.plotly_chart(_fig_cumr, width="stretch")
st.markdown("---")

# ── 五、NAV 走势 ──────────────────────────────────────────────────────────────
st.subheader("五、NAV 走势（标准化）")
st.caption("均从起始 1.0 标准化。回测由于数据跨度长，此图仅供趋势形态参考。")

_fig_nav = go.Figure()
if not _bt_nav.empty:
    _bt_nav_norm = _bt_nav.iloc[:, 0] / float(_bt_nav.iloc[0, 0])
    _fig_nav.add_trace(go.Scatter(
        x=_bt_nav_norm.index, y=_bt_nav_norm.values,
        name="回测（样本内，2000–今）",
        line=dict(color="rgba(31,119,180,0.35)", width=1.2),
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}x<extra>回测</extra>",
    ))

if not nav_df.empty and len(nav_df) >= 2:
    _pt_nav_norm = nav_df["nav"] / float(nav_df["nav"].iloc[0])
    _fig_nav.add_trace(go.Scatter(
        x=_pt_nav_norm.index, y=_pt_nav_norm.values,
        name="模拟（样本外）",
        line=dict(color="#d62728", width=2.5),
        mode="lines+markers", marker_size=4,
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}x<extra>模拟</extra>",
    ))
else:
    _fig_nav.add_annotation(
        text="模拟 NAV 数据不足（运行后自动填充）",
        xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
        font=dict(size=14, color="gray"),
    )

_fig_nav.add_hline(y=1.0, line_dash="dot", line_color="gray", opacity=0.5)
_fig_nav.update_layout(
    yaxis_title="净值（倍）", height=360, template="plotly_white",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=50, r=20, t=50, b=50),
)
st.plotly_chart(_fig_nav, width="stretch")
st.markdown("---")

# ── 六、信号漏斗分析 ──────────────────────────────────────────────────────────
st.subheader("六、信号漏斗分析")
st.caption(
    "每天有多少原始突破信号存在，多少因组合热度/现金不足被拦截，多少最终被执行。"
    "漏斗拦截率持续偏高说明组合热度饱和，策略实际捕获的 Alpha 少于回测假设。"
)

_funnel_cols = ["n_raw_breakouts", "n_heat_blocked", "n_cash_blocked", "n_corr_reduced", "n_candidates"]
_has_funnel  = not sig_df.empty and any(c in sig_df.columns for c in _funnel_cols)

if _has_funnel and len(sig_df) >= 3:
    _sg = sig_df.copy()
    for _c in _funnel_cols:
        if _c not in _sg.columns:
            _sg[_c] = 0

    # Rolling 20-day averages to smooth noise
    _rolling = 20
    _fig_funnel = go.Figure()
    _fig_funnel.add_trace(go.Bar(
        x=_sg["date"], y=_sg["n_raw_breakouts"].fillna(0),
        name="原始突破数", marker_color="rgba(31,119,180,0.5)",
    ))
    _fig_funnel.add_trace(go.Bar(
        x=_sg["date"], y=_sg["n_heat_blocked"].fillna(0),
        name="热度拦截", marker_color="rgba(214,39,40,0.7)",
    ))
    _fig_funnel.add_trace(go.Bar(
        x=_sg["date"], y=_sg["n_cash_blocked"].fillna(0),
        name="现金拦截", marker_color="rgba(255,127,14,0.7)",
    ))
    _fig_funnel.add_trace(go.Scatter(
        x=_sg["date"], y=_sg["n_candidates"].fillna(0),
        name="最终候选信号数", mode="lines",
        line=dict(color="#2ca02c", width=2),
    ))
    _fig_funnel.update_layout(
        barmode="stack", height=360,
        xaxis_title="日期", yaxis_title="信号数量",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template="plotly_white", margin=dict(l=50, r=20, t=50, b=50),
    )
    st.plotly_chart(_fig_funnel, width="stretch")

    # Utilization stats
    _total_raw  = _sg["n_raw_breakouts"].sum()
    _total_heat = _sg["n_heat_blocked"].sum()
    _total_cash = _sg["n_cash_blocked"].sum()
    _total_acc  = _sg["n_candidates"].sum()
    if _total_raw > 0:
        _util_cols = st.columns(4)
        _util_cols[0].metric("总原始突破数", _n(_total_raw))
        _util_cols[1].metric("热度拦截率",   f"{_total_heat/_total_raw*100:.1f}%",
                             help="高拦截率说明资金量相对策略信号频率偏小，或参数组合热度上限过低")
        _util_cols[2].metric("现金拦截率",   f"{_total_cash/_total_raw*100:.1f}%")
        _util_cols[3].metric("信号利用率",   f"{_total_acc/_total_raw*100:.1f}%",
                             help="模拟 vs 回测的差异：回测通常假设资金充足，实盘受资金约束而错过部分信号")
else:
    st.info("信号漏斗数据在 GitHub Actions 首次运行后自动填充（来自 signals_history 字段）。")

st.markdown("---")

# ── 七、突破强度 vs 后续表现 ─────────────────────────────────────────────────
st.subheader("七、突破强度 vs 后续表现")
st.caption(
    "突破强度 = adj_close / 200日最高价（越大说明突破越显著）。"
    "若强突破在样本外仍带来更高R，说明该选股维度有真实 Alpha。"
    "若关系消失，是策略对该特征过拟合的证据。"
)

_has_strength = (not ct.empty and "signal_strength" in ct.columns
                 and ct["signal_strength"].notna().any()
                 and (ct["signal_strength"] > 0).any())

if _has_strength and n_closed >= _MIN_CHART:
    _str_df = ct[["signal_strength", "pnl_r", "exit_reason"]].dropna(subset=["signal_strength","pnl_r"])
    _str_df = _str_df[_str_df["signal_strength"] > 0]

    if len(_str_df) >= _MIN_CHART:
        _colors_map = {"stop_loss": "#d62728", "trailing_stop": "#ff7f0e"}
        _colors = [_colors_map.get(r, "#2ca02c") for r in _str_df["exit_reason"]]

        _fig_str = go.Figure()
        _fig_str.add_trace(go.Scatter(
            x=_str_df["signal_strength"], y=_str_df["pnl_r"],
            mode="markers",
            marker=dict(color=_colors, size=8, opacity=0.7,
                        line=dict(color="white", width=0.5)),
            hovertemplate=(
                "突破强度: %{x:.4f}<br>R: %{y:+.3f}<extra></extra>"
            ),
            showlegend=False,
        ))
        # Trend line
        if len(_str_df) >= 5:
            _slope_s, _int_s, _rv_s, _pv_s, _ = _stats.linregress(
                _str_df["signal_strength"], _str_df["pnl_r"])
            _xs = np.linspace(_str_df["signal_strength"].min(), _str_df["signal_strength"].max(), 50)
            _fig_str.add_trace(go.Scatter(
                x=_xs, y=_slope_s * _xs + _int_s,
                mode="lines", name=f"趋势线（r={_rv_s:.2f}, p={_pv_s:.3f}）",
                line=dict(color="#1f77b4", width=2, dash="dash"),
            ))

        _fig_str.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
        _fig_str.update_layout(
            xaxis_title="突破强度（adj_close / 200日高点）",
            yaxis_title="最终 R 倍数",
            height=380, template="plotly_white",
            margin=dict(l=50, r=20, t=40, b=50),
        )
        st.plotly_chart(_fig_str, width="stretch")

        # Quartile analysis
        if len(_str_df) >= 8:
            _str_df["quartile"] = pd.qcut(_str_df["signal_strength"], q=4,
                                          labels=["Q1低", "Q2", "Q3", "Q4高"], duplicates="drop")
            _q_stats = (_str_df.groupby("quartile", observed=True)["pnl_r"]
                        .agg(笔数="count", 均值R="mean", 胜率=lambda x: (x > 0).mean())
                        .reset_index().rename(columns={"quartile": "突破强度分组"}))
            _q_stats["均值R"]  = _q_stats["均值R"].round(3)
            _q_stats["胜率"]   = (_q_stats["胜率"] * 100).round(1).astype(str) + "%"
            show_df(_q_stats, width="stretch", hide_index=True)
    else:
        st.info(f"突破强度分析需要至少 {_MIN_CHART} 笔有效数据，当前 {len(_str_df)} 笔。")
elif not _has_strength and n_closed > 0:
    st.info(
        "已平仓记录中暂无 `signal_strength` 字段（该字段在最新版本的日脚本中已写入，"
        "历史已平仓记录没有此字段，新的平仓记录将自动包含）。"
    )
else:
    st.info(f"需 ≥ {_MIN_CHART} 笔平仓记录，当前 {n_closed} 笔。")

st.markdown("---")

# ── 八、MFE 分析（最大有利偏移） ─────────────────────────────────────────────
_colors_map = {"stop_loss": "#d62728", "trailing_stop": "#ff7f0e"}
st.subheader("八、MFE 分析（最大有利偏移 vs 最终出场 R）")
st.caption(
    "MFE = 持仓期间历史最高价带来的最大浮盈（以 R 表示）。"
    "若多数交易的出场 R 远低于 MFE，说明止盈偏早；若出场 R 接近 MFE，说明较好捕获了趋势。"
    "**捕获率 = 出场R / MFE_R**，越高越好（趋势跟踪策略正常范围约 40%–70%）。"
)

_has_mfe = (not ct.empty
            and all(c in ct.columns for c in ["highest_high", "entry_price", "stop_loss", "exit_price", "pnl_r"]))

if _has_mfe and n_closed >= _MIN_CHART:
    _mfe = ct[["highest_high","entry_price","stop_loss","exit_price","pnl_r","exit_reason"]].dropna()
    _R_base = _mfe["entry_price"] - _mfe["stop_loss"]
    _valid  = _R_base > 0
    _mfe = _mfe[_valid].copy()
    _R_base = _R_base[_valid]

    if len(_mfe) >= _MIN_CHART:
        _mfe["mfe_r"]     = (_mfe["highest_high"] - _mfe["entry_price"]) / _R_base
        _mfe["capture"]   = np.where(_mfe["mfe_r"] > 0,
                                     _mfe["pnl_r"] / _mfe["mfe_r"], np.nan)
        _mfe_clean = _mfe.dropna(subset=["mfe_r","capture"])

        _mfe_cols = st.columns(3)
        _mfe_cols[0].metric("平均 MFE (R)",    f"{_mfe_clean['mfe_r'].mean():+.2f}R")
        _mfe_cols[1].metric("平均出场 R",       f"{_mfe_clean['pnl_r'].mean():+.2f}R")
        _mfe_cols[2].metric("平均捕获率",
                            f"{_mfe_clean['capture'].median()*100:.0f}%（中位数）")

        _colors_map = {"stop_loss": "#d62728", "trailing_stop": "#ff7f0e"}
        _fig_mfe = go.Figure()
        _er_colors = [_colors_map.get(r, "#2ca02c") for r in _mfe_clean["exit_reason"]]
        _fig_mfe.add_trace(go.Scatter(
            x=_mfe_clean["mfe_r"], y=_mfe_clean["pnl_r"],
            mode="markers",
            marker=dict(color=_er_colors, size=8, opacity=0.75,
                        line=dict(color="white", width=0.5)),
            hovertemplate="MFE: %{x:+.2f}R<br>出场: %{y:+.2f}R<extra></extra>",
            showlegend=False,
        ))
        # 45-degree "perfect capture" line
        _max_r = max(_mfe_clean["mfe_r"].max(), 1.0)
        _fig_mfe.add_trace(go.Scatter(
            x=[0, _max_r], y=[0, _max_r],
            mode="lines", name="完美捕获线（100%）",
            line=dict(color="gray", width=1.5, dash="dot"),
        ))
        _fig_mfe.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.4)
        _fig_mfe.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.4)
        _fig_mfe.update_layout(
            xaxis_title="MFE（持仓最高浮盈，R）", yaxis_title="最终出场 R",
            height=380, template="plotly_white",
            margin=dict(l=50, r=20, t=40, b=50),
        )
        st.plotly_chart(_fig_mfe, width="stretch")

        # Capture ratio distribution
        _fig_cap = go.Figure(go.Histogram(
            x=_mfe_clean["capture"].clip(-0.5, 2.0),
            nbinsx=30, marker_color="rgba(148,103,189,0.7)",
            name="捕获率分布",
        ))
        _fig_cap.add_vline(x=_mfe_clean["capture"].median(), line_dash="dash",
                           line_color="#9467bd", line_width=2,
                           annotation_text=f"中位数 {_mfe_clean['capture'].median()*100:.0f}%",
                           annotation_position="top right")
        _fig_cap.update_layout(
            xaxis_title="捕获率（出场R / MFE_R）", yaxis_title="笔数",
            height=260, template="plotly_white",
            margin=dict(l=50, r=20, t=30, b=50),
        )
        st.plotly_chart(_fig_cap, width="stretch")
    else:
        st.info(f"有效 MFE 数据 {len(_mfe)} 笔，需 ≥ {_MIN_CHART} 笔。")
else:
    st.info(
        f"MFE 分析需 ≥ {_MIN_CHART} 笔平仓且包含 highest_high 字段。"
        "该字段在最新版本日脚本中已写入，历史平仓记录可能缺失。"
    )

st.markdown("---")

# ── 九、统计显著性进度 ────────────────────────────────────────────────────────
st.subheader("九、统计显著性进度")
st.caption(
    "t 统计量 = 均值R × √N / 标准差R。"
    "需要 t > 1.96（p < 0.05）才能以 95% 置信度说明策略样本外 Alpha 显著大于零。"
)

if n_closed >= 3 and "pnl_r" in ct.columns:
    _r_ser = ct["pnl_r"].dropna()
    _n_n   = len(_r_ser)
    _mu    = _r_ser.mean()
    _sigma = _r_ser.std(ddof=1)

    _t_curr = (_mu / (_sigma / np.sqrt(_n_n))) if (_sigma > 0 and _n_n > 0) else 0
    _t_targ = 1.96
    _p_curr = _stats.t.sf(abs(_t_curr), df=_n_n - 1) * 2 if _n_n > 1 else 1.0

    # Trades needed to reach t = 1.96 at current mean and std
    _n_needed = int(np.ceil((_t_targ * _sigma / max(_mu, 0.001)) ** 2)) if _mu > 0 else 9999

    _sig_cols = st.columns(4)
    _sig_cols[0].metric("当前 t 统计量", f"{_t_curr:.2f}", delta="临界值 ±1.96")
    _sig_cols[1].metric("当前 p 值",
                        f"{_p_curr:.3f}",
                        delta="✅ 显著" if _p_curr < 0.05 and _t_curr > 0 else "❌ 尚不显著",
                        delta_color="normal" if _p_curr < 0.05 and _t_curr > 0 else "off")
    _sig_cols[2].metric("均值R（当前）", f"{_mu:+.3f}R")
    _sig_cols[3].metric("还需约 N 笔",
                        f"{max(_n_needed - _n_n, 0)} 笔" if _mu > 0 else "均值R≤0",
                        help="在均值R和方差不变的假设下，达到 t=1.96 还需的交易笔数（理论估算）")

    # t-stat trajectory chart
    _ns  = list(range(3, max(n_closed + 50, 100)))
    _ts  = [_mu / (_sigma / np.sqrt(n_i)) for n_i in _ns]
    _fig_t = go.Figure()
    _fig_t.add_trace(go.Scatter(
        x=_ns, y=_ts, name="t 统计量（在当前均值R和σ下）",
        line=dict(color="#1f77b4", width=2),
        hovertemplate="N=%{x} 笔<br>t=%{y:.2f}<extra></extra>",
    ))
    _fig_t.add_hline(y=1.96, line_dash="dash", line_color="green",
                     annotation_text="临界值 t=1.96（p=0.05）",
                     annotation_position="right")
    _fig_t.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.4)
    _fig_t.add_vline(x=n_closed, line_dash="dot", line_color="#d62728",
                     annotation_text=f"当前 N={n_closed}",
                     annotation_position="top right")
    _fig_t.update_layout(
        xaxis_title="累计平仓笔数", yaxis_title="t 统计量",
        height=320, template="plotly_white",
        margin=dict(l=50, r=60, t=40, b=50),
        showlegend=False,
    )
    st.plotly_chart(_fig_t, width="stretch")
    st.caption(
        f"⚠️ 以上预测假设均值R（{_mu:+.3f}）和标准差R（{_sigma:.3f}）保持不变，仅供参考。"
        f"若未来交易质量下滑（均值R降低），达到显著性所需的笔数将大幅增加。"
    )
else:
    st.info(f"需 ≥ 3 笔平仓记录，当前 {n_closed} 笔。")

st.markdown("---")

# ── 十、过拟合风险评分（综合）────────────────────────────────────────────────
st.subheader("十、综合评估")

_flags = []
_goods = []

if n_closed >= _MIN_STATS:
    _r_ser = ct["pnl_r"].dropna()
    _mu    = _r_ser.mean()
    _wr    = (_r_ser > 0).mean()
    _bt_wr = _bt_m.get("win_rate", np.nan)
    _bt_avg_r = float(_bt_r.mean()) if len(_bt_r) else np.nan

    if _mu > 0:      _goods.append("✅ 模拟均值R > 0，策略样本外有正期望")
    else:            _flags.append("❌ 模拟均值R ≤ 0，样本外期望值为负，存在过拟合风险")

    if not np.isnan(_bt_avg_r) and _mu > 0.5 * _bt_avg_r:
        _goods.append(f"✅ 模拟均值R（{_mu:+.3f}）超过回测均值R（{_bt_avg_r:+.3f}）50% 以上")
    elif not np.isnan(_bt_avg_r):
        _flags.append(f"⚠️ 模拟均值R（{_mu:+.3f}）低于回测均值R（{_bt_avg_r:+.3f}）50% 以上")

    if not np.isnan(_bt_wr) and _wr >= _bt_wr * 0.85:
        _goods.append(f"✅ 模拟胜率（{_wr*100:.0f}%）≥ 回测胜率（{_bt_wr*100:.0f}%）× 85%")
    elif not np.isnan(_bt_wr):
        _flags.append(f"⚠️ 模拟胜率（{_wr*100:.0f}%）低于回测胜率（{_bt_wr*100:.0f}%）× 85%")

    # KS test
    if len(_r_ser) >= 10 and len(_bt_r) > 0:
        _, _ks_p = _stats.ks_2samp(_r_ser, _bt_r)
        if _ks_p >= 0.05:
            _goods.append(f"✅ KS 检验 p={_ks_p:.3f} ≥ 0.05：R 分布与回测无显著差异")
        else:
            _flags.append(f"⚠️ KS 检验 p={_ks_p:.3f} < 0.05：R 分布已发生显著漂移")

if n_closed < _MIN_STATS:
    st.info(f"综合评估需 ≥ {_MIN_STATS} 笔平仓，当前 {n_closed} 笔。以下为框架预览：")
    _goods = ["（尚无足够数据判断）"]
    _flags = []

_eval_cols = st.columns(2)
with _eval_cols[0]:
    st.markdown("**正面信号（样本外有效）**")
    for _g in (_goods or ["暂无正面信号"]):
        st.markdown(_g)
with _eval_cols[1]:
    st.markdown("**警示信号（可能过拟合）**")
    for _f in (_flags or ["暂无警示信号"]):
        st.markdown(_f)

_score_caption = (
    f"当前 {n_closed} 笔平仓记录，统计功效有限。"
    "建议积累至 50 笔以上后再做最终判断。"
    if n_closed < 50 else
    f"已积累 {n_closed} 笔平仓，统计功效较强，以上评估可作为过拟合判断的主要依据。"
)
st.caption(_score_caption)
