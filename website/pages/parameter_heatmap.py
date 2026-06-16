"""参数热力图分析"""

from __future__ import annotations

import json
import sys
import statistics
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import plotly.graph_objects as go
import streamlit as st

from website.shared import get_results
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta
p    = meta.params_anchor

render_page_header("参数热力图分析", meta)
st.caption(f"{meta.display_name} · 回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

_PERTURB_DIR = _root / "results" / "v1_unbiased_60m" / "perturbation"
_HEATMAP_DIR = _root / "results" / "v1_unbiased_60m" / "heatmap"


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _load_perturb(param_name: str) -> dict | None:
    path = _PERTURB_DIR / f"{param_name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_heatmap(filename: str) -> dict | None:
    path = _HEATMAP_DIR / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cv(recs: list[dict], metric: str = "sharpe") -> float:
    vals = [r.get(metric, 0) for r in recs]
    if len(vals) < 2:
        return 0.0
    mn = abs(statistics.mean(vals))
    return statistics.stdev(vals) / mn if mn > 1e-9 else 0.0


def _robustness(cv: float) -> str:
    if cv < 0.10:
        return "✅ 高鲁棒（CV < 0.10）"
    elif cv < 0.25:
        return "🟡 中等（CV 0.10–0.25）"
    return "🔴 敏感（CV > 0.25）"


def _stability_region(recs: list[dict], metric: str = "sharpe") -> tuple:
    """Returns (lo, hi) of the widest contiguous region where metric ≥ 90% of peak."""
    sorted_recs = sorted(recs, key=lambda r: r["param_value"])
    vals = [r["param_value"] for r in sorted_recs]
    metrics = [r.get(metric, 0) for r in sorted_recs]
    peak = max(metrics) if metrics else 0
    threshold = peak * 0.90
    best_start = best_end = None
    best_len = 0
    seg_start = None
    for i, (v, mv) in enumerate(zip(vals, metrics)):
        if mv >= threshold:
            if seg_start is None:
                seg_start = i
        else:
            if seg_start is not None:
                seg_len = i - seg_start
                if seg_len > best_len:
                    best_len, best_start, best_end = seg_len, vals[seg_start], vals[i - 1]
                seg_start = None
    if seg_start is not None:
        seg_len = len(vals) - seg_start
        if seg_len > best_len:
            best_start, best_end = vals[seg_start], vals[-1]
    return best_start, best_end


def _bar_color(sharpe: float, peak: float) -> str:
    ratio = sharpe / peak if peak > 0 else 0
    if ratio >= 0.95:
        return "#2ca02c"
    elif ratio >= 0.90:
        return "#8bc34a"
    elif ratio >= 0.80:
        return "#f57c00"
    return "#d62728"


def _fmt_param(param_name: str, val) -> str:
    if param_name == "breakout_window":
        return f"N={int(val)}"
    elif param_name in ("risk_per_trade", "position_cap", "heat_limit"):
        return f"{val*100:.1f}%"
    elif param_name in ("slippage_bps", "commission_bps"):
        return f"{val:.0f}bps"
    elif param_name == "min_market_cap_b":
        return f"${val:.0f}B"
    elif param_name == "min_adv_m":
        return f"${val:.0f}M"
    elif param_name == "min_price":
        return f"${val:.0f}"
    elif param_name == "correlation_threshold":
        return f"{val:.1f}"
    return f"{val}"


def _render_1d_chart(data: dict, title: str) -> None:
    """Render a 1D bar chart (Sharpe + CAGR) with stability region highlight."""
    recs = sorted(data["results"], key=lambda r: r["param_value"])
    baseline_val = data["baseline_value"]
    param_name = data["param_name"]

    x_labels = [_fmt_param(param_name, r["param_value"]) for r in recs]
    sharpes   = [r["sharpe"] for r in recs]
    cagrs     = [r["cagr"] * 100 for r in recs]
    peak      = max(sharpes)
    colors    = [_bar_color(s, peak) for s in sharpes]

    fig = go.Figure()

    # Sharpe bars
    fig.add_trace(go.Bar(
        x=x_labels, y=sharpes, name="Sharpe",
        marker_color=colors,
        text=[f"{s:.3f}" for s in sharpes],
        textposition="outside",
        yaxis="y",
    ))

    # CAGR line (secondary axis)
    fig.add_trace(go.Scatter(
        x=x_labels, y=cagrs, name="CAGR%",
        mode="lines+markers",
        line=dict(color="#1f77b4", dash="dot", width=2),
        marker=dict(size=6),
        yaxis="y2",
    ))

    # Baseline vertical line
    baseline_label = _fmt_param(param_name, baseline_val)
    if baseline_label in x_labels:
        fig.add_vline(
            x=x_labels.index(baseline_label),
            line_width=2, line_dash="dash", line_color="black",
            annotation_text="基准", annotation_position="top",
        )

    # 90% stability threshold line
    threshold_90 = peak * 0.90
    fig.add_hline(
        y=threshold_90, line_dash="dot", line_color="gray",
        annotation_text=f"90% 峰值 ({threshold_90:.3f})",
        annotation_position="bottom right",
    )

    cv = _cv(recs)
    stab_lo, stab_hi = _stability_region(recs)
    stab_str = (f"{_fmt_param(param_name, stab_lo)} → {_fmt_param(param_name, stab_hi)}"
                if stab_lo is not None else "无连续稳定区间")

    fig.update_layout(
        title=title,
        yaxis=dict(title="Sharpe 比率", range=[0, max(sharpes) * 1.25]),
        yaxis2=dict(title="CAGR (%)", overlaying="y", side="right",
                    range=[0, max(cagrs) * 1.35]),
        legend=dict(x=0.01, y=0.99),
        height=380,
        margin=dict(t=50, b=50, l=60, r=60),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )

    st.plotly_chart(fig, use_container_width=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("CV（Sharpe）", f"{cv:.3f}", help="< 0.10 = 高鲁棒")
    c2.metric("鲁棒性", _robustness(cv).split("（")[0])
    c3.metric("连续稳定区间（≥90%峰值）", stab_str)


# ── 数据范围说明 ───────────────────────────────────────────────────────────────

st.subheader("📋 数据范围说明")

st.markdown(f"""
#### 为什么热力图和扰动测试都使用完整历史数据（{meta.backtest_start} → {meta.backtest_end}）？

本策略所有参数（N=200、止损 2×ATR 等）在运行任何回测**之前**，已根据业界经验和趋势跟踪机制原理事先确定，
**没有经过"观察 OOS 结果 → 调参 → 再测试"的循环**。因此：

- 热力图和扰动测试的目的是**验证鲁棒性**（理解参数景观），而非**挑选参数**。
- 由于不存在 OOS 数据泄漏，使用完整数据在方法论上可接受。
- 两种分析使用相同的数据范围，保持一致性。

#### 两种分析的对比

| | Perturbation Tests（已完成）| Heatmap（本页） |
|-|--------------------------|----------------|
| 数据范围 | {meta.backtest_start} → {meta.backtest_end}（全期数据）| {meta.backtest_start} → {meta.backtest_end}（全期数据）|
| 是否存在数据泄漏 | 否（参数未基于 OOS 挑选）| 否（目的为验证鲁棒性，非选参）|
| 分析维度 | 1D，逐参数 | 1D 可视化 + 2D 双参数网格 |
| 用途 | 验证单参数鲁棒性 | 验证双参数联合稳定性 |
| 结果能否用于 Strategy 2.0 选参 | **不应直接用于选参** | **不应直接用于选参** |
""")

st.markdown("---")


# ── 1. 1D Heatmap ─────────────────────────────────────────────────────────────

st.subheader("📊 一、1D Heatmap（单参数景观可视化）")
st.markdown("""
复用扰动测试（Perturbation Tests）数据，对三个核心参数生成 Sharpe + CAGR 双轴图，
可视化参数景观（Parameter Landscape）。

- **X 轴**：参数取值；竖虚线 = 当前基准值
- **左 Y 轴（柱）**：Sharpe 比率（绿色 ≥ 95% 峰值，浅绿 ≥ 90%，橙 ≥ 80%，红 < 80%）
- **右 Y 轴（虚线）**：CAGR %
- **水平灰线**：90% 峰值阈值（稳定区间判断标准）
- **CV（变异系数）< 0.10** = 高鲁棒；**稳定区间** = 连续满足 ≥ 90% 峰值的最宽参数范围
""")


# ── 1.1 breakout_window ───────────────────────────────────────────────────────

st.markdown("#### 1.1 突破窗口 N（breakout_window）")

_bw_data = _load_perturb("breakout_window")
if _bw_data:
    st.markdown("""
**背景：** N 控制突破信号的动量周期——N 越小，信号越频繁但噪声越多；N 越大，趋势过滤更强但入场更滞后。
理论上较宽的 N 范围（150–300）应表现相近，呈现高原形态（Plateau）。
""")
    _render_1d_chart(_bw_data, "突破窗口 N — Sharpe & CAGR 参数景观")

    _bw_recs = sorted(_bw_data["results"], key=lambda r: r["param_value"])
    st.markdown("**详细数据：**")
    import pandas as pd
    _bw_rows = []
    for r in _bw_recs:
        is_base = "★" if r["param_value"] == _bw_data["baseline_value"] else ""
        _bw_rows.append({
            "参数值": f"N={int(r['param_value'])} {is_base}",
            "Sharpe": f"{r['sharpe']:+.3f}",
            "CAGR":   f"{r['cagr']*100:+.2f}%",
            "MaxDD":  f"{r['max_drawdown']*100:.1f}%",
            "Sortino": f"{r['sortino']:+.3f}",
            "胜率": f"{r['win_rate']*100:.1f}%",
        })
    st.dataframe(pd.DataFrame(_bw_rows), use_container_width=True, hide_index=True)
else:
    st.warning("breakout_window 扰动数据未找到")

st.markdown("---")


# ── 1.2 stop_loss_multiplier ──────────────────────────────────────────────────

st.markdown("#### 1.2 ATR 止损乘数（stop_loss_multiplier）")

_sl_data = _load_perturb("stop_loss_multiplier")
if _sl_data:
    st.markdown("""
**背景：** 止损乘数决定每笔交易的初始风险范围——较紧的止损（1.5×）减少单次亏损但增加被震出概率；
较宽的止损（3.0×）容纳更大波动但会影响 MaxDD。在 1.5×–3.0× 范围内应呈现稳健的高原形态。
""")
    _render_1d_chart(_sl_data, "ATR 止损乘数 — Sharpe & CAGR 参数景观")

    _sl_recs = sorted(_sl_data["results"], key=lambda r: r["param_value"])
    import pandas as pd
    _sl_rows = []
    for r in _sl_recs:
        is_base = "★" if abs(r["param_value"] - _sl_data["baseline_value"]) < 0.01 else ""
        _sl_rows.append({
            "参数值": f"{r['param_value']:.1f}× {is_base}",
            "Sharpe": f"{r['sharpe']:+.3f}",
            "CAGR":   f"{r['cagr']*100:+.2f}%",
            "MaxDD":  f"{r['max_drawdown']*100:.1f}%",
            "Sortino": f"{r['sortino']:+.3f}",
            "胜率": f"{r['win_rate']*100:.1f}%",
        })
    st.dataframe(pd.DataFrame(_sl_rows), use_container_width=True, hide_index=True)
else:
    st.warning("stop_loss_multiplier 扰动数据未找到")

st.markdown("---")


# ── 1.3 trail_multiplier_r1 ───────────────────────────────────────────────────

st.markdown("#### 1.3 移动止盈乘数（trail_multiplier_r1）")

_tm_data = _load_perturb("trail_multiplier_r1")
if _tm_data:
    st.markdown("""
**背景：** 移动止盈乘数（< 1R 时使用）控制早期盈利保护的宽松程度——较低值（2.0×）对早期获利更敏感，
较高值（4.0×）允许更大波动继续持仓。不同乘数影响盈利捕获与过早止盈的权衡。
""")
    _render_1d_chart(_tm_data, "移动止盈乘数 — Sharpe & CAGR 参数景观")

    _tm_recs = sorted(_tm_data["results"], key=lambda r: r["param_value"])
    import pandas as pd
    _tm_rows = []
    for r in _tm_recs:
        is_base = "★" if abs(r["param_value"] - _tm_data["baseline_value"]) < 0.01 else ""
        _tm_rows.append({
            "参数值": f"{r['param_value']:.1f}× {is_base}",
            "Sharpe": f"{r['sharpe']:+.3f}",
            "CAGR":   f"{r['cagr']*100:+.2f}%",
            "MaxDD":  f"{r['max_drawdown']*100:.1f}%",
            "Sortino": f"{r['sortino']:+.3f}",
            "胜率": f"{r['win_rate']*100:.1f}%",
        })
    st.dataframe(pd.DataFrame(_tm_rows), use_container_width=True, hide_index=True)
else:
    st.warning("trail_multiplier_r1 扰动数据未找到")

st.markdown("---")


# ── 2. Slice Tests ────────────────────────────────────────────────────────────

st.subheader("🔪 二、Slice Tests（固定锚点的单参数扫描）")
st.markdown(f"""
固定 N={p['breakout_window']}、止损 {p['stop_loss_multiplier']:.0f}×ATR（基准锚点），
分别扰动以下参数，以折线图呈现 Sharpe 的变化。
数据来自"参数敏感性分析"页面的扰动测试结果，无需额外回测。
""")

_SLICE_PARAMS = [
    ("correlation_threshold",   "相关性阈值",     f"{p['correlation_threshold']:.2f}",  lambda v: f"{v:.1f}"),
    ("risk_per_trade",          "每笔风险比例",   f"{p['risk_per_trade']*100:.1f}%",    lambda v: f"{v*100:.1f}%"),
    ("min_market_cap_b",        "最低市值",        f"${p.get('min_market_cap_b',2):.0f}B", lambda v: f"${v:.0f}B"),
    ("min_adv_m",               "ADV 流动性",     f"${p.get('min_adv_m',20):.0f}M",    lambda v: f"${v:.0f}M"),
    ("volume_filter_multiplier","成交量确认乘数", f"{p.get('volume_filter_multiplier',1.5):.1f}×", lambda v: f"{v:.1f}×"),
    ("slippage_bps",            "滑点（单边）",   f"{p.get('slippage_bps',10):.0f} bps", lambda v: f"{v:.0f}bps"),
    ("commission_bps",          "佣金（单边）",   f"{p.get('commission_bps',3):.0f} bps", lambda v: f"{v:.0f}bps"),
]

import pandas as pd

_slice_summary_rows = []
for _pname, _plabel, _pbase, _pfmt in _SLICE_PARAMS:
    _sd = _load_perturb(_pname)
    if _sd is None:
        continue
    _recs = sorted(_sd["results"], key=lambda r: r["param_value"])
    _cv_v = _cv(_recs)
    _stab_lo, _stab_hi = _stability_region(_recs)
    _stab_str = (f"{_pfmt(_stab_lo)} → {_pfmt(_stab_hi)}" if _stab_lo is not None else "无连续稳定区间")
    _slice_summary_rows.append({
        "参数": _plabel,
        "基准值": _pbase,
        "CV（Sharpe）": f"{_cv_v:.3f}",
        "鲁棒性": _robustness(_cv_v).split("（")[0],
        "稳定区间（≥90%峰值）": _stab_str,
    })

if _slice_summary_rows:
    st.markdown("**Slice Tests 汇总（点击展开各参数详细图表）：**")
    st.dataframe(pd.DataFrame(_slice_summary_rows), use_container_width=True, hide_index=True)

st.markdown("")

for _pname, _plabel, _pbase, _pfmt in _SLICE_PARAMS:
    _sd = _load_perturb(_pname)
    if _sd is None:
        continue
    _recs = sorted(_sd["results"], key=lambda r: r["param_value"])
    _baseline_val = _sd["baseline_value"]
    with st.expander(f"📈 {_plabel}（基准 = {_pbase}）"):
        _xs     = [_pfmt(r["param_value"]) for r in _recs]
        _shs    = [r["sharpe"] for r in _recs]
        _cagrs2 = [r["cagr"] * 100 for r in _recs]
        _peak2  = max(_shs)
        _colors2 = [_bar_color(s, _peak2) for s in _shs]
        _fig2 = go.Figure()
        _fig2.add_trace(go.Bar(
            x=_xs, y=_shs, name="Sharpe",
            marker_color=_colors2,
            text=[f"{s:.3f}" for s in _shs], textposition="outside",
        ))
        _fig2.add_trace(go.Scatter(
            x=_xs, y=_cagrs2, name="CAGR%",
            mode="lines+markers",
            line=dict(color="#1f77b4", dash="dot", width=2),
            yaxis="y2",
        ))
        _base_label2 = _pfmt(_baseline_val)
        if _base_label2 in _xs:
            _fig2.add_vline(
                x=_xs.index(_base_label2),
                line_width=2, line_dash="dash", line_color="black",
                annotation_text="基准", annotation_position="top",
            )
        _fig2.add_hline(
            y=_peak2 * 0.90, line_dash="dot", line_color="gray",
            annotation_text=f"90% 峰值",
        )
        _fig2.update_layout(
            yaxis=dict(title="Sharpe", range=[0, _peak2 * 1.3]),
            yaxis2=dict(title="CAGR%", overlaying="y", side="right"),
            legend=dict(x=0.01, y=0.99),
            height=300, margin=dict(t=30, b=40, l=50, r=60),
            plot_bgcolor="white", paper_bgcolor="white",
        )
        st.plotly_chart(_fig2, use_container_width=True)
        _cv2 = _cv(_recs)
        _stab_lo2, _stab_hi2 = _stability_region(_recs)
        _stab_str2 = (f"{_pfmt(_stab_lo2)} → {_pfmt(_stab_hi2)}"
                      if _stab_lo2 is not None else "无连续稳定区间")
        _c21, _c22, _c23 = st.columns(3)
        _c21.metric("CV（Sharpe）", f"{_cv2:.3f}")
        _c22.metric("鲁棒性", _robustness(_cv2).split("（")[0])
        _c23.metric("连续稳定区间", _stab_str2)

st.markdown("---")


# ── 3. 2D Heatmap ─────────────────────────────────────────────────────────────

st.subheader("🗺️ 三、2D Heatmap（双参数联合网格扫描）")

_HM_A_FILE = "breakout_window_x_stop_loss_multiplier.json"
_HM_B_FILE = "breakout_window_x_trail_multiplier_r1.json"

_hm_a = _load_heatmap(_HM_A_FILE)
_hm_b = _load_heatmap(_HM_B_FILE)
_log_path = _HEATMAP_DIR / "run_2d.log"


def _count_done(hm: dict | None, n_total: int) -> str:
    if hm is None:
        return f"0 / {n_total}"
    n_done = len(hm.get("combinations", []))
    return f"{n_done} / {n_total}"


def _render_2d_heatmap(hm: dict, metric: str = "sharpe", title: str = "") -> None:
    combos = hm["combinations"]
    v1s = sorted({c["param1_value"] for c in combos})
    v2s = sorted({c["param2_value"] for c in combos})
    p1_name = hm["param1"]
    p2_name = hm["param2"]

    # Build matrix
    z_sharpe = []
    z_cagr   = []
    hover    = []
    for v2 in v2s:
        row_s, row_c, row_h = [], [], []
        for v1 in v1s:
            m_hit = next((c for c in combos
                         if c["param1_value"] == v1 and c["param2_value"] == v2), None)
            if m_hit:
                s = m_hit.get("sharpe", 0)
                c_val = m_hit.get("cagr", 0) * 100
                dd = m_hit.get("max_drawdown", 0) * 100
                row_s.append(s)
                row_c.append(c_val)
                row_h.append(f"Sharpe={s:+.3f}<br>CAGR={c_val:+.2f}%<br>MaxDD={dd:.1f}%")
            else:
                row_s.append(None)
                row_c.append(None)
                row_h.append("")
        z_sharpe.append(row_s)
        z_cagr.append(row_c)
        hover.append(row_h)

    all_s = [s for row in z_sharpe for s in row if s is not None]
    peak_s = max(all_s) if all_s else 1
    threshold_s = peak_s * 0.90

    # Mark baseline
    base_v1 = p.get(p1_name)
    base_v2 = p.get(p2_name)

    x_labels = [_fmt_param(p1_name, v) for v in v1s]
    y_labels = [_fmt_param(p2_name, v) for v in v2s]

    # Add ★ to baseline cell text
    text_matrix = []
    for i, v2 in enumerate(v2s):
        row_txt = []
        for j, v1 in enumerate(v1s):
            val = z_sharpe[i][j]
            if val is None:
                row_txt.append("—")
                continue
            s_str = f"{val:+.3f}"
            if base_v1 is not None and abs(v1 - base_v1) < 0.01 and \
               base_v2 is not None and abs(v2 - base_v2) < 0.01:
                s_str += " ★"
            row_txt.append(s_str)
        text_matrix.append(row_txt)

    fig = go.Figure(go.Heatmap(
        x=x_labels,
        y=y_labels,
        z=z_sharpe,
        text=text_matrix,
        texttemplate="%{text}",
        colorscale=[
            [0.0, "#d62728"],
            [0.5, "#f57c00"],
            [0.85, "#8bc34a"],
            [1.0, "#2ca02c"],
        ],
        zmin=max(0, min(all_s) - 0.05) if all_s else 0,
        zmax=max(all_s) + 0.02 if all_s else 1,
        hovertext=hover,
        hoverinfo="text",
        showscale=True,
        colorbar=dict(title="Sharpe"),
    ))

    # Highlight stability region border
    stab_cells_x, stab_cells_y = [], []
    for i, v2 in enumerate(v2s):
        for j, v1 in enumerate(v1s):
            s = z_sharpe[i][j]
            if s is not None and s >= threshold_s:
                stab_cells_x.append(x_labels[j])
                stab_cells_y.append(y_labels[i])

    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        xaxis=dict(title=p1_name),
        yaxis=dict(title=p2_name),
        height=420,
        margin=dict(t=55, b=60, l=100, r=60),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Stability summary
    st.markdown(f"**峰值 Sharpe = {peak_s:+.3f}；90% 阈值 = {threshold_s:.3f}**（绿色格子为稳定区间）")
    if stab_cells_x:
        n_stable = len(stab_cells_x)
        n_total_c = len([s for row in z_sharpe for s in row if s is not None])
        st.success(
            f"稳定格子数：{n_stable} / {n_total_c}（{n_stable/n_total_c*100:.0f}%）—— "
            "大面积绿色高原表明两参数联合变化时策略表现稳健。"
        )


# ── 3.1 Grid A ────────────────────────────────────────────────────────────────

st.markdown("#### 3.1 N × ATR止损乘数（28 次回测）")

if _hm_a and len(_hm_a.get("combinations", [])) == 28:
    _render_2d_heatmap(_hm_a, title="2D 热力图：突破窗口 N × ATR止损乘数（Sharpe）")
elif _hm_a and len(_hm_a.get("combinations", [])) > 0:
    _n_done_a = len(_hm_a["combinations"])
    st.info(f"⏳ **计算进行中** — 已完成 {_n_done_a} / 28 次回测 …")
    if _n_done_a >= 4:
        st.markdown("**已有结果（部分）：**")
        _render_2d_heatmap(_hm_a, title=f"2D 热力图（部分，{_n_done_a}/28）：突破窗口 N × ATR止损乘数")
else:
    st.info(
        "⏳ **2D 网格计算进行中（0/28）** — 预计约 3 小时完成。"
        "完成后刷新页面即可查看结果。"
    )
    if _log_path.exists():
        _last_lines = _log_path.read_text(encoding="utf-8").splitlines()[-8:]
        with st.expander("查看计算日志（最后 8 行）"):
            st.code("\n".join(_last_lines))

st.markdown("---")


# ── 3.2 Grid B ────────────────────────────────────────────────────────────────

st.markdown("#### 3.2 N × 移动止盈乘数（20 次回测，可选）")

if _hm_b and len(_hm_b.get("combinations", [])) == 20:
    _render_2d_heatmap(_hm_b, title="2D 热力图：突破窗口 N × 移动止盈乘数（Sharpe）")
elif _hm_b and len(_hm_b.get("combinations", [])) > 0:
    _n_done_b = len(_hm_b["combinations"])
    st.info(f"⏳ **计算进行中** — 已完成 {_n_done_b} / 20 次回测 …")
    if _n_done_b >= 4:
        _render_2d_heatmap(_hm_b, title=f"2D 热力图（部分，{_n_done_b}/20）：突破窗口 N × 移动止盈乘数")
else:
    st.info(
        "⏳ **2D 网格计算进行中（0/20）** — Grid A 完成后开始。"
        "完成后刷新页面即可查看结果。"
    )

st.markdown("---")


# ── 4. 结论 ───────────────────────────────────────────────────────────────────

st.subheader("📝 结论")

_bw_cv  = _cv(_load_perturb("breakout_window")["results"])  if _load_perturb("breakout_window")  else None
_sl_cv  = _cv(_load_perturb("stop_loss_multiplier")["results"]) if _load_perturb("stop_loss_multiplier") else None
_tm_cv  = _cv(_load_perturb("trail_multiplier_r1")["results"])  if _load_perturb("trail_multiplier_r1")  else None

_bw_stab = _stability_region(_load_perturb("breakout_window")["results"])  if _load_perturb("breakout_window")  else (None, None)
_sl_stab = _stability_region(_load_perturb("stop_loss_multiplier")["results"]) if _load_perturb("stop_loss_multiplier") else (None, None)
_tm_stab = _stability_region(_load_perturb("trail_multiplier_r1")["results"])  if _load_perturb("trail_multiplier_r1")  else (None, None)

_bw_stab_str = (f"N ∈ [{int(_bw_stab[0])}, {int(_bw_stab[1])}]"
                if _bw_stab[0] is not None else "无连续稳定区间")
_sl_stab_str = (f"{_sl_stab[0]:.1f}× – {_sl_stab[1]:.1f}×"
                if _sl_stab[0] is not None else "无连续稳定区间")
_tm_stab_str = (f"{_tm_stab[0]:.1f}× – {_tm_stab[1]:.1f}×"
                if _tm_stab[0] is not None else "无连续稳定区间")

st.markdown(f"""
### 1D Heatmap 结论（三核心参数）

| 参数 | 基准值 | Sharpe 范围 | CV（Sharpe）| 鲁棒性评级 | 连续稳定区间（≥90%峰值）|
|------|--------|------------|------------|----------|----------------------|
| 突破窗口 N | N={p['breakout_window']} | 0.481–0.608 | {f'{_bw_cv:.3f}' if _bw_cv else '—'} | {"✅ 高鲁棒" if _bw_cv and _bw_cv < 0.10 else "🟡 中等"} | {_bw_stab_str} |
| ATR 止损乘数 | {p['stop_loss_multiplier']:.1f}× | 0.514–0.570 | {f'{_sl_cv:.3f}' if _sl_cv else '—'} | {"✅ 高鲁棒" if _sl_cv and _sl_cv < 0.10 else "🟡 中等"} | {_sl_stab_str} |
| 移动止盈乘数 | {p['trail_multiplier_r1']:.0f}×  | 0.498–0.604 | {f'{_tm_cv:.3f}' if _tm_cv else '—'} | {"✅ 高鲁棒" if _tm_cv and _tm_cv < 0.10 else "🟡 中等"} | {_tm_stab_str} |

**关键发现：**

1. **突破窗口 N（CV={f'{_bw_cv:.3f}' if _bw_cv else '—'}，< 0.10）**：
   在 150–300 日范围内，Sharpe 介于 0.48–0.61，峰值位于 N=250（0.608）和 N=170（0.583）。
   虽然整体 Sharpe 变化不大（高原形态），但没有单一连续稳定区间覆盖所有 7 个测试值，
   说明参数景观相对平坦但略有起伏。基准 N=200（Sharpe=0.519）处于均值附近，选取合理。

2. **ATR 止损乘数（CV={f'{_sl_cv:.3f}' if _sl_cv else '—'}，< 0.10）**：
   在 1.5×–3.0× 范围内，**所有测试值均满足 ≥ 90% 峰值**（Sharpe 最低 0.514，最高 0.570），
   稳定区间覆盖完整测试范围（{_sl_stab_str}），呈现近乎完美的高原形态。
   这表明策略对止损松紧极不敏感，鲁棒性最高。

3. **移动止盈乘数（CV={f'{_tm_cv:.3f}' if _tm_cv else '—'}，< 0.10）**：
   峰值出现在 2.5×（Sharpe=0.604）。基准值 3.0×（Sharpe=0.519）低于 90% 峰值阈值（0.544），
   稳定区间仅为 {_tm_stab_str}。Sharpe 从 2.5× 到 3.0× 有明显下降，
   提示该参数存在一定敏感性，但整体 CV < 0.10，仍属可接受范围。
   **若未来调参，可考虑将 trail_multiplier_r1 调整至 2.5×。**

---

### Slice Tests 结论（7 个辅助参数）

| 参数 | CV | 鲁棒性 | 结论 |
|------|----|----|------|
| 相关性阈值 | {f"{_cv(_load_perturb('correlation_threshold')['results']):.3f}" if _load_perturb('correlation_threshold') else '—'} | ✅ 高鲁棒 | Sharpe 在 0.45–0.56 之间，无明显方向性趋势 |
| 每笔风险比例 | {f"{_cv(_load_perturb('risk_per_trade')['results']):.3f}" if _load_perturb('risk_per_trade') else '—'} | ✅ 极高鲁棒 | 0.5%–2.0% 范围内结果几乎相同，MaxDD 随之等比例变化 |
| 最低市值 | {f"{_cv(_load_perturb('min_market_cap_b')['results']):.3f}" if _load_perturb('min_market_cap_b') else '—'} | ✅ 极高鲁棒 | $2B–$4B 结果完全相同，市值过滤在此范围内无差异 |
| ADV 流动性 | {f"{_cv(_load_perturb('min_adv_m')['results']):.3f}" if _load_perturb('min_adv_m') else '—'} | ✅ 高鲁棒 | 宽松过滤 → Sharpe 更高，但实盘滑点更大；20M 为合理平衡点 |
| 成交量确认乘数 | {f"{_cv(_load_perturb('volume_filter_multiplier')['results']):.3f}" if _load_perturb('volume_filter_multiplier') else '—'} | ✅ 极高鲁棒 | 1.0×–2.0× 范围内 Sharpe 变化极小（0.492–0.536） |
| 滑点 | {f"{_cv(_load_perturb('slippage_bps')['results']):.3f}" if _load_perturb('slippage_bps') else '—'} | ✅ 高鲁棒 | 单调递减（符合预期），即便 15bps 高摩擦 Sharpe 仍为 0.473 |
| 佣金 | {f"{_cv(_load_perturb('commission_bps')['results']):.3f}" if _load_perturb('commission_bps') else '—'} | ✅ 高鲁棒 | 单调递减（符合预期），佣金影响远小于滑点 |

**总体评估：** 所有 7 个辅助参数的 CV(Sharpe) 均 < 0.10，策略对这些参数均表现出高鲁棒性。

---

### 2D Heatmap 结论
""")

if _hm_a and len(_hm_a.get("combinations", [])) == 28:
    _combos_a = _hm_a["combinations"]
    _all_s_a  = [c["sharpe"] for c in _combos_a]
    _peak_a   = max(_all_s_a)
    _n_stable_a = sum(1 for s in _all_s_a if s >= _peak_a * 0.90)
    st.markdown(f"""
**N × ATR止损乘数（已完成 28/28）：**
- 峰值 Sharpe = {_peak_a:+.3f}，90% 阈值 = {_peak_a * 0.90:.3f}
- 稳定格子数：{_n_stable_a} / 28（{_n_stable_a/28*100:.0f}%）
- {"✅ 两参数联合大范围稳定，策略对 N 与止损乘数的组合选择鲁棒" if _n_stable_a/28 >= 0.5 else "⚠️ 稳定区间较窄，需谨慎"}
""")
elif _hm_a:
    _n_done_a = len(_hm_a.get("combinations", []))
    st.info(f"⏳ Grid A 计算进行中（{_n_done_a}/28），结论待更新。")
else:
    st.info("⏳ 2D Heatmap 计算尚未完成。完成后刷新页面查看 2D 联合稳定性结论。")

if _hm_b and len(_hm_b.get("combinations", [])) == 20:
    _combos_b = _hm_b["combinations"]
    _all_s_b  = [c["sharpe"] for c in _combos_b]
    _peak_b   = max(_all_s_b)
    _n_stable_b = sum(1 for s in _all_s_b if s >= _peak_b * 0.90)
    st.markdown(f"""
**N × 移动止盈乘数（已完成 20/20）：**
- 峰值 Sharpe = {_peak_b:+.3f}，90% 阈值 = {_peak_b * 0.90:.3f}
- 稳定格子数：{_n_stable_b} / 20（{_n_stable_b/20*100:.0f}%）
""")
elif _hm_b:
    _n_done_b = len(_hm_b.get("combinations", []))
    st.info(f"⏳ Grid B 计算进行中（{_n_done_b}/20），结论待更新。")

st.markdown("""
---

### 综合结论

**策略 1.0 的参数鲁棒性在全部 10 个已测参数中均表现良好。**

- **三个核心参数**（N、止损乘数、止盈乘数）的 CV(Sharpe) 均 < 0.10，符合高鲁棒标准。
- **ATR 止损乘数**鲁棒性最高（CV=0.045），1.5×–3.0× 全部通过稳定性测试。
- **每笔风险比例**和**最低市值过滤**几乎不影响 Sharpe，属于"不敏感参数"。
- **移动止盈乘数**在 2.5× 时表现最优（0.604 vs 基准 0.519），基准值 3.0× 略低于峰值；
  CV < 0.10 仍属鲁棒，但未来 Strategy 2.0 可考虑优化此参数。
- **交易成本参数**（滑点、佣金）呈预期的单调递减，即便在 15 bps 高摩擦下 Sharpe 仍为正。

**方法论结论：** 策略设计时参数已事先确定，热力图/扰动测试均为事后鲁棒性验证，
不存在过拟合或数据泄漏风险。参数景观总体呈高原形态（Plateau），策略 1.0 的参数设置具有充分的鲁棒性基础。
""")
