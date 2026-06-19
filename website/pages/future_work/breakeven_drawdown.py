"""如何用平价保护改善最大回撤"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.io as _pio

_pio.templates.default = "plotly_white"

_results_path = _root / "results" / "v1_unbiased_60m_2000"
_BE_CSV = _results_path / "breakeven_scenarios.csv"

# ── Load data ─────────────────────────────────────────────────────────────────
from website.data_loader import load_strategy

_cache_key = "_be_drawdown_results"
if _cache_key not in st.session_state:
    st.session_state[_cache_key] = load_strategy("v1_unbiased_60m_2000")
_res = st.session_state[_cache_key]


@st.cache_data(ttl=86400)
def _load_be(mtime: int):
    if mtime == 0:
        return None
    return pd.read_csv(
        _BE_CSV,
        parse_dates=["entry_date", "orig_exit_date",
                     "be1r_exit_date", "be15r_exit_date", "be2r_exit_date"],
    )


_BE_MTIME = int(_BE_CSV.stat().st_mtime) if _BE_CSV.exists() else 0
_be = _load_be(_BE_MTIME)


def _build_nav(nav_orig, lbl):
    dc, pc, tc = f"{lbl}_exit_date", f"{lbl}_net_pnl", f"{lbl}_triggered"
    mask = _be[tc] & _be[dc].notna() & (_be[dc] < _be["orig_exit_date"])
    ch = _be[mask]
    d = pd.Series(0.0, index=nav_orig.index, dtype=float)
    for dt, v in ch.groupby("orig_exit_date")["orig_net_pnl"].sum().items():
        if dt in d.index:
            d[dt] -= v
    for dt, v in ch.groupby(dc)[pc].sum().items():
        if dt in d.index:
            d[dt] += v
    return nav_orig + d.cumsum()


def _cagr(nav):
    ny = (nav.index[-1] - nav.index[0]).days / 365.25
    return (nav.iloc[-1] / nav.iloc[0]) ** (1.0 / ny) - 1


def _maxdd(nav):
    return ((nav - nav.cummax()) / nav.cummax()).min()


def _winrate(lbl):
    if lbl == "orig":
        return (_be["orig_net_pnl"] > 0).mean()
    dc, pc, tc = f"{lbl}_exit_date", f"{lbl}_net_pnl", f"{lbl}_triggered"
    mask = _be[tc] & _be[dc].notna() & (_be[dc] < _be["orig_exit_date"])
    pnl = _be["orig_net_pnl"].copy()
    pnl[mask] = _be.loc[mask, pc]
    return (pnl > 0).mean()


def _max_consec(lbl):
    if lbl == "orig":
        arr = _be.sort_values("orig_exit_date")["orig_net_pnl"].values
    else:
        dc, pc, tc = f"{lbl}_exit_date", f"{lbl}_net_pnl", f"{lbl}_triggered"
        mask = _be[tc] & _be[dc].notna() & (_be[dc] < _be["orig_exit_date"])
        dates = _be["orig_exit_date"].copy()
        pnls = _be["orig_net_pnl"].copy()
        dates[mask] = _be.loc[mask, dc]
        pnls[mask] = _be.loc[mask, pc]
        arr = pnls.iloc[np.argsort(dates.values)].values
    mx = cur = 0
    for v in arr:
        if v <= 0:
            cur += 1
            mx = max(mx, cur)
        else:
            cur = 0
    return mx


# ── Page ──────────────────────────────────────────────────────────────────────
st.title("如何用平价保护改善最大回撤")
st.caption("分析平价保护（Breakeven Protection）对策略最大回撤的影响，并给出可落地的使用建议")

st.markdown("---")

if _be is None:
    st.warning("缺少平价保护模拟数据。请在本地运行 `python src/scripts/compute_breakeven_scenarios.py` 后重新部署。")
    st.stop()

_nav_orig = _res.nav
_nav_be1r = _build_nav(_nav_orig, "be1r")
_nav_be15r = _build_nav(_nav_orig, "be15r")
_nav_be2r = _build_nav(_nav_orig, "be2r")

# ── 一、结论先行 ───────────────────────────────────────────────────────────────
st.subheader("一、结论：平价保护 1R 可将最大回撤降低约 1.1 个百分点")

_total = len(_be)
_navs_all = {
    "原始策略":      _nav_orig,
    "平价保护 1R":   _nav_be1r,
    "平价保护 1.5R": _nav_be15r,
    "平价保护 2R":   _nav_be2r,
}
_orig_c = _cagr(_nav_orig)
_orig_d = _maxdd(_nav_orig)
_be1r_c_pp = (_cagr(_nav_be1r) - _orig_c) * 100
_be1r_wr_pp = (_winrate("be1r") - _winrate("orig")) * 100

_m_rows = []
for (_nm, _nav), _lbl_wr in zip(_navs_all.items(), ["orig", "be1r", "be15r", "be2r"]):
    _c = _cagr(_nav)
    _d = _maxdd(_nav)
    _w = _winrate(_lbl_wr)
    _mc = _max_consec(_lbl_wr)
    _row = {"方案": _nm, "年化收益 CAGR": f"{_c*100:.2f}%"}
    if _nm == "原始策略":
        _row["CAGR 变化"] = "—"
        _row["胜率"] = f"{_w*100:.1f}%"
        _row["最大回撤"] = f"{_d*100:.2f}%"
        _row["最大回撤变化"] = "—"
        _row["最长连续亏损次数"] = str(_mc)
    else:
        _dc2 = (_c - _orig_c) * 100
        _dd2 = (_d - _orig_d) * 100
        _row["CAGR 变化"] = f"{'+' if _dc2 >= 0 else ''}{_dc2:.2f} pp"
        _row["胜率"] = f"{_w*100:.1f}%"
        _row["最大回撤"] = f"{_d*100:.2f}%"
        _row["最大回撤变化"] = f"{'+' if _dd2 >= 0 else ''}{_dd2:.2f} pp"
        _row["最长连续亏损次数"] = str(_mc)
    _m_rows.append(_row)

st.dataframe(pd.DataFrame(_m_rows), use_container_width=True, hide_index=True)

st.markdown("""
**核心结论**：在 {total:,} 笔已执行交易中，平价保护 1R（浮盈达到 1R 时将止损移至略高于开仓价的位置，使出场净盈利 ≈ +$1）可使最大回撤
从 **{orig_dd:.2f}%** 降至 **{be1r_dd:.2f}%**，同时年化收益略有提升（+{cagr_pp:.2f} pp）、胜率略有提升（+{wr_pp:.2f} pp）。
1.5R 和 2R 的效果几乎为零（原因见下节）。
""".format(
    total=_total,
    orig_dd=_maxdd(_nav_orig) * 100,
    be1r_dd=_maxdd(_nav_be1r) * 100,
    cagr_pp=_be1r_c_pp,
    wr_pp=_be1r_wr_pp,
))

st.markdown("---")

# ── 二、数学原理 ───────────────────────────────────────────────────────────────
st.subheader("二、数学原理：为什么只有 1R 有效，1.5R 和 2R 几乎没用")

st.markdown("""
策略1.0 的参数设定为：**止损 = 2×ATR**（即 R = 2×ATR），**追踪止损倍数 = 3×ATR**。

当浮盈恰好为 1.5R 时，追踪止损位于：

> 追踪止损 = 最高价 − 3×ATR = (开仓价 + 1.5R) − 3×ATR = (开仓价 + 3×ATR) − 3×ATR = **开仓价**

即在浮盈达到 1.5R 时，**原始追踪止损已自然等于开仓价**，额外施加"平价保护 1.5R"完全没有保护作用。
同理，2R 阈值时追踪止损已高于开仓价格（= 开仓价 + ATR），平价保护 2R 同样无效。

| 浮盈阈值 | 此时原始追踪止损位置 | 平价保护效果 |
|---------|------------------|------------|
| 1R | 开仓价 − 1×ATR（低于开仓价） | **有效**：将止损上移 1×ATR |
| 1.5R | 开仓价（恰好等于开仓价） | 无效：止损位置不变 |
| 2R | 开仓价 + 1×ATR（高于开仓价） | 无效：止损位置不变 |

因此，**只有平价保护 1R 值得考虑**。
""")

st.markdown("---")

# ── 三、NAV 与最大回撤对比 ──────────────────────────────────────────────────────
st.subheader("三、NAV 与最大回撤对比（原始策略 vs 平价保护 1R）")

_dd_orig = (_nav_orig - _nav_orig.cummax()) / _nav_orig.cummax() * 100
_dd_be1r = (_nav_be1r - _nav_be1r.cummax()) / _nav_be1r.cummax() * 100

_max_dd_date = _dd_orig.idxmin()
_max_dd_orig = _dd_orig.min()
_max_dd_be1r = _dd_be1r[_max_dd_date]

# Combined figure: NAV top, Drawdown bottom
from plotly.subplots import make_subplots as _make_subplots

_fig = _make_subplots(
    rows=2, cols=1, shared_xaxes=True,
    row_heights=[0.55, 0.45],
    vertical_spacing=0.06,
    subplot_titles=["归一化 NAV", "最大回撤（%）"],
)

# NAV traces
for _nm, _nav, _cl, _ds, _wd in [
    ("原始策略",    _nav_orig, "#1f77b4", "solid", 2.5),
    ("平价保护 1R", _nav_be1r, "#2ca02c", "dash",  1.8),
]:
    _nr = _nav / _nav.iloc[0]
    _fig.add_trace(go.Scatter(
        x=_nr.index, y=_nr.values, name=_nm,
        line=dict(color=_cl, dash=_ds, width=_wd),
        showlegend=True,
    ), row=1, col=1)

# Drawdown traces
_fig.add_trace(go.Scatter(
    x=_dd_orig.index, y=_dd_orig.values, name="原始策略（回撤）",
    line=dict(color="#1f77b4", dash="solid", width=1.5),
    fill="tozeroy", fillcolor="rgba(31,119,180,0.12)",
    showlegend=False,
), row=2, col=1)
_fig.add_trace(go.Scatter(
    x=_dd_be1r.index, y=_dd_be1r.values, name="平价保护 1R（回撤）",
    line=dict(color="#2ca02c", dash="dash", width=1.5),
    showlegend=False,
), row=2, col=1)

# Annotation: max drawdown point
_fig.add_annotation(
    x=_max_dd_date, y=_max_dd_orig,
    text=f"原始最大回撤<br>{_max_dd_orig:.1f}%",
    showarrow=True, arrowhead=2, arrowcolor="#1f77b4",
    font=dict(size=11, color="#1f77b4"),
    ax=40, ay=-40, row=2, col=1,
)
_fig.add_annotation(
    x=_max_dd_date, y=_max_dd_be1r,
    text=f"BE1R 同期回撤<br>{_max_dd_be1r:.1f}%",
    showarrow=True, arrowhead=2, arrowcolor="#2ca02c",
    font=dict(size=11, color="#2ca02c"),
    ax=-60, ay=-25, row=2, col=1,
)

_fig.update_layout(
    height=560,
    margin=dict(l=60, r=30, t=60, b=40),
    legend=dict(x=0.01, y=0.99),
    hovermode="x unified",
)
_fig.update_yaxes(title_text="归一化 NAV", row=1, col=1)
_fig.update_yaxes(title_text="回撤（%）", row=2, col=1)

st.plotly_chart(_fig, use_container_width=True)

st.markdown(f"""
最大回撤出现在 **{_max_dd_date.strftime('%Y-%m-%d')}**，原始策略为 **{_max_dd_orig:.2f}%**，
平价保护 1R 在同一时点的回撤为 **{_max_dd_be1r:.2f}%**，改善约 **{_max_dd_be1r - _max_dd_orig:.2f} pp**。
从回撤曲线可以看出，两条线在大多数时段几乎重合，差异主要集中在波动较大的市场阶段。
""")

st.markdown("---")

# ── 四、作用机制：168 笔提前出场交易分析 ────────────────────────────────────────────
st.subheader("四、作用机制：平价保护 1R 改变了哪些交易？")

_mask_changed = (
    _be["be1r_triggered"]
    & _be["be1r_exit_date"].notna()
    & (_be["be1r_exit_date"] < _be["orig_exit_date"])
)
_ch = _be[_mask_changed].copy()
_ch["orig_pnl_r"] = _ch["orig_net_pnl"] / (_ch["R"] * _ch["shares"])
_ch["be_pnl_r"]   = _ch["be1r_net_pnl"] / (_ch["R"] * _ch["shares"])
_ch["pnl_r_delta"] = _ch["be_pnl_r"] - _ch["orig_pnl_r"]
_ch["helped"] = _ch["pnl_r_delta"] > 0

_n_helped = int(_ch["helped"].sum())
_n_hurt   = int((~_ch["helped"]).sum())
_n_orig_loss = int((_ch["orig_net_pnl"] <= 0).sum())
_n_orig_win  = int((_ch["orig_net_pnl"] > 0).sum())

st.markdown(f"""
共 **{len(_ch)} 笔**交易因平价保护 1R 提前出场（占全部 {_total:,} 笔的 {len(_ch)/_total*100:.1f}%）：

| 原始结果 | 数量 | 说明 |
|---------|------|------|
| 原始亏损（pnl ≤ 0） | **{_n_orig_loss} 笔** | 原始策略会亏损，BE 使其在开仓价附近出场（减少亏损） |
| 原始盈利（pnl > 0） | **{_n_orig_win} 笔** | 原始策略有盈利，BE 止损触发导致提前出场、获利减少 |

**净效果**：{_n_helped} 笔（{_n_helped/len(_ch)*100:.0f}%）被 BE 改善，{_n_hurt} 笔（{_n_hurt/len(_ch)*100:.0f}%）被 BE 削减。
平均每笔 P&L 变化：{_ch["orig_pnl_r"].mean():.2f}R → {_ch["be_pnl_r"].mean():.2f}R
（净改善 +{_ch["be_pnl_r"].mean() - _ch["orig_pnl_r"].mean():.2f}R / 笔，共减少损失约 **${_ch["pnl_r_delta"].mul(_ch["R"]*_ch["shares"]).sum():,.0f}**）
""")

# Scatter plot: original pnl_r vs be pnl_r
_clr_pts = ["#2ca02c" if h else "#d62728" for h in _ch["helped"]]
_fig_sc = go.Figure()

_fig_sc.add_trace(go.Scatter(
    x=_ch["orig_pnl_r"], y=_ch["be_pnl_r"],
    mode="markers",
    marker=dict(color=_clr_pts, size=7, opacity=0.7,
                line=dict(color="white", width=0.5)),
    name="各笔交易",
    customdata=np.stack([
        _ch["orig_pnl_r"], _ch["be_pnl_r"], _ch["pnl_r_delta"],
        pd.to_datetime(_ch["entry_date"]).dt.strftime("%Y-%m-%d"),
        _ch["ticker"] if "ticker" in _ch.columns else [""] * len(_ch),
    ], axis=1),
    hovertemplate=(
        "<b>%{customdata[4]}</b> (%{customdata[3]})<br>"
        "原始 P&L: %{customdata[0]:.2f}R<br>"
        "BE 后 P&L: %{customdata[1]:.2f}R<br>"
        "变化: %{customdata[2]:.2f}R"
        "<extra></extra>"
    ),
))

# Diagonal y=x line
_rng = [
    min(_ch["orig_pnl_r"].min(), _ch["be_pnl_r"].min()) - 0.2,
    max(_ch["orig_pnl_r"].max(), _ch["be_pnl_r"].max()) + 0.2,
]
_fig_sc.add_trace(go.Scatter(
    x=_rng, y=_rng, mode="lines",
    line=dict(color="gray", dash="dot", width=1),
    showlegend=False, name="无变化线（y=x）",
))

# y=0 and x=0 reference lines
_fig_sc.add_hline(y=0, line_color="rgba(0,0,0,0.2)", line_dash="dash", line_width=1)
_fig_sc.add_vline(x=0, line_color="rgba(0,0,0,0.2)", line_dash="dash", line_width=1)

_fig_sc.add_annotation(
    x=_rng[0] + 0.5, y=_rng[1] - 0.3,
    text="绿色：BE 改善了交易结果<br>红色：BE 使交易结果变差",
    showarrow=False, font=dict(size=11, color="#555"),
    align="left",
)

_fig_sc.update_layout(
    title=dict(text="168 笔受影响交易：原始 P&L vs 平价保护后 P&L（单位：R）", font=dict(size=13)),
    xaxis_title="原始 P&L（R）",
    yaxis_title="平价保护后 P&L（R）",
    height=420,
    margin=dict(l=60, r=30, t=60, b=50),
)

st.plotly_chart(_fig_sc, use_container_width=True)

st.markdown(f"""
图中每个点代表一笔受影响的交易。**对角线上方（绿色）= BE 改善了结果**；**对角线下方（红色）= BE 使结果变差**。

观察规律：
- 原始亏损较深的交易（x < -0.5R）几乎都在对角线上方 ── BE 把大亏变成了小亏或平局
- 原始盈利的交易（x > 0）基本都在对角线下方 ── BE 截短了部分盈利
- 净效应为正：{_n_helped} 笔改善，{_n_hurt} 笔变差，改善幅度通常大于损失幅度
""")

st.markdown("---")

# ── 五、年度分布 ───────────────────────────────────────────────────────────────
st.subheader("五、平价保护 1R 的年度效果分布")

_ch["year"] = pd.to_datetime(_ch["entry_date"]).dt.year
_yearly = _ch.groupby("year").agg(
    笔数=("orig_pnl_r", "count"),
    改善笔数=("helped", "sum"),
    均变化R=("pnl_r_delta", "mean"),
).reset_index()
_yearly["改善率"] = _yearly["改善笔数"] / _yearly["笔数"]

_fig_yr = go.Figure()
_bar_clr = ["#2ca02c" if v >= 0 else "#d62728" for v in _yearly["均变化R"]]
_fig_yr.add_trace(go.Bar(
    x=_yearly["year"].astype(str), y=_yearly["均变化R"],
    marker_color=_bar_clr,
    text=[f"{v:.2f}R" for v in _yearly["均变化R"]],
    textposition="outside",
    name="年均 P&L 变化（R）",
    customdata=np.stack([_yearly["笔数"], _yearly["改善笔数"]], axis=1),
    hovertemplate="<b>%{x}</b><br>笔数: %{customdata[0]}<br>改善笔数: %{customdata[1]}<br>均变化: %{y:.2f}R<extra></extra>",
))
_fig_yr.update_layout(
    title=dict(text="各年受影响交易的平均 P&L 变化（正 = 平价保护改善了结果）", font=dict(size=13)),
    xaxis_title="年份",
    yaxis_title="平均 P&L 变化（R）",
    height=340,
    margin=dict(l=60, r=30, t=60, b=50),
    showlegend=False,
)
_fig_yr.add_hline(y=0, line_color="gray", line_width=1)

st.plotly_chart(_fig_yr, use_container_width=True)

st.markdown("---")

# ── 六、实施建议 ───────────────────────────────────────────────────────────────
st.subheader("六、实施建议")

st.markdown(f"""
**建议：在策略1.0中加入平价保护 1R。**

**理由：**
1. **最大回撤改善明显**：最大回撤从 {_maxdd(_nav_orig)*100:.2f}% 降至 {_maxdd(_nav_be1r)*100:.2f}%（−{abs(_maxdd(_nav_be1r)-_maxdd(_nav_orig))*100:.2f} pp），
   在不显著牺牲年化收益的前提下，降低了策略的尾部风险。

2. **预期价值为正**：168 笔受影响交易中，{_n_helped} 笔改善（{_n_helped/len(_ch)*100:.0f}%），{_n_hurt} 笔变差（{_n_hurt/len(_ch)*100:.0f}%）。
   主要机制是将"追涨到顶后回撤至止损"的交易转化为"保本出场"。

3. **与现有追踪止损天然兼容**：平价保护 1R 仅在追踪止损原本低于开仓价时起作用（约浮盈 < 1.5R 阶段），
   不干扰后期趋势延续阶段（浮盈 ≥ 1.5R 后追踪止损已高于开仓价，两者等效）。

4. **实现简单**：在出场循环中，追踪止损更新后加一行判断即可：
   ```
   if peak_profit >= 1 × R:
       trail_stop = max(trail_stop, entry_price)
   ```

**注意事项：**
- 约有 {_n_orig_win} 笔原本盈利的交易会因平价保护提前出场而减少获利，这是不可避免的代价。
- 平价保护不能替代趋势跟踪的核心逻辑，只是在浮盈归零之前的一道"底线保护"。
- 对最长连续亏损次数无明显改善（仍为 {_max_consec("be1r")} 次），连亏问题需通过其他方式解决（见"如何降低连续亏损次数"页面）。
""")

_trig_1r = int(_be["be1r_triggered"].sum())
st.markdown(f"""
**触发概率**：历史上约 **{_trig_1r/_total*100:.0f}%** 的交易（{_trig_1r} / {_total:,} 笔）浮盈达到过 1R，
其中约 **{len(_ch)/_trig_1r*100:.0f}%** 最终因平价保护提前出场（其余交易在触发保护后继续上涨，追踪止损自然高于开仓价，保护无需额外介入）。
""")
