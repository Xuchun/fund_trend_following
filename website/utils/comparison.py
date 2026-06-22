"""Utility: render a before/after comparison section after a data-update rerun."""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

_V1 = Path(__file__).resolve().parents[3] / "results" / "v1"


def _delta_html(new_val: float, old_val: float, pct_scale: bool = True,
                lower_better: bool = False) -> str:
    """Return colored HTML delta string (arrow + magnitude)."""
    if old_val is None:
        return "—"
    delta = new_val - old_val
    if abs(delta) < 5e-6:
        return '<span style="color:#888">持平</span>'
    scale = 100 if pct_scale else 1
    arrow = "▲" if delta > 0 else "▼"
    mag = abs(delta * scale)
    fmt = f"{mag:.2f}{'pp' if pct_scale else ''}"
    good = (delta > 0 and not lower_better) or (delta < 0 and lower_better)
    color = "#2e7d32" if good else "#c62828"
    return f'<span style="color:{color}">{arrow} {fmt}</span>'


def render_data_update_comparison(current_meta, current_metrics: dict):
    """
    Append a "数据更新对比" section comparing prev_run_snapshot vs current run.

    Parameters
    ----------
    current_meta : strategy_meta object (has .backtest_end)
    current_metrics : dict from metrics.json
    """
    prev_path = _V1 / "prev_run_snapshot.json"
    if not prev_path.exists():
        return

    try:
        prev = json.loads(prev_path.read_text())
    except Exception:
        return

    pm = prev.get("metrics.json", {})
    if not pm:
        return

    prev_end = prev.get("_run_end", "上次运行")
    curr_end = current_meta.backtest_end

    # Detect if rerun has completed: backtest_end must be strictly later than snapshot's end
    import datetime as _dt
    try:
        rerun_done = _dt.date.fromisoformat(curr_end) > _dt.date.fromisoformat(prev_end)
    except ValueError:
        rerun_done = curr_end != prev_end

    st.markdown("---")
    st.subheader("数据更新对比")

    if not rerun_done:
        st.info(
            f"数据重跑进行中（后台运行），本次对比数据尚未更新。"
            f"重跑完成后刷新页面即可查看最新对比。"
            f"\n\n上次运行终止日：**{prev_end}** → 本次目标终止日：**最新市场数据**"
        )
        return

    cm = current_metrics

    rows = [
        ("回测终止日",
         prev_end,
         curr_end,
         "—"),
        ("CAGR",
         f"{pm.get('cagr', 0)*100:.2f}%",
         f"{cm.get('cagr', 0)*100:.2f}%",
         _delta_html(cm.get('cagr', 0), pm.get('cagr', 0))),
        ("Sharpe",
         f"{pm.get('sharpe', 0):.4f}",
         f"{cm.get('sharpe', 0):.4f}",
         _delta_html(cm.get('sharpe', 0), pm.get('sharpe', 0), pct_scale=False)),
        ("Sortino",
         f"{pm.get('sortino', 0):.4f}",
         f"{cm.get('sortino', 0):.4f}",
         _delta_html(cm.get('sortino', 0), pm.get('sortino', 0), pct_scale=False)),
        ("最大回撤",
         f"{abs(pm.get('max_drawdown', 0))*100:.2f}%",
         f"{abs(cm.get('max_drawdown', 0))*100:.2f}%",
         _delta_html(abs(cm.get('max_drawdown', 0)), abs(pm.get('max_drawdown', 0)), lower_better=True)),
        ("年化波动率",
         f"{pm.get('annual_vol', 0)*100:.2f}%",
         f"{cm.get('annual_vol', 0)*100:.2f}%",
         _delta_html(cm.get('annual_vol', 0), pm.get('annual_vol', 0), lower_better=True)),
        ("胜率",
         f"{pm.get('win_rate', 0)*100:.2f}%",
         f"{cm.get('win_rate', 0)*100:.2f}%",
         _delta_html(cm.get('win_rate', 0), pm.get('win_rate', 0))),
        ("Profit Factor",
         f"{pm.get('profit_factor', 0):.4f}",
         f"{cm.get('profit_factor', 0):.4f}",
         _delta_html(cm.get('profit_factor', 0), pm.get('profit_factor', 0), pct_scale=False)),
        ("总交易笔数",
         f"{int(pm.get('n_trades', 0)):,}",
         f"{int(cm.get('n_trades', 0)):,}",
         _delta_html(cm.get('n_trades', 0), pm.get('n_trades', 0), pct_scale=False)),
        ("平均持仓天数",
         f"{pm.get('avg_holding_days', 0):.1f}",
         f"{cm.get('avg_holding_days', 0):.1f}",
         _delta_html(cm.get('avg_holding_days', 0), pm.get('avg_holding_days', 0), pct_scale=False)),
    ]

    col_prev = f"上次运行（≈{prev_end}）"
    col_curr = f"本次运行（{curr_end}）"

    html_rows = ""
    for metric, old_v, new_v, delta_h in rows:
        html_rows += f"<tr><td>{metric}</td><td>{old_v}</td><td>{new_v}</td><td>{delta_h}</td></tr>"

    st.markdown(f"""
<table style="width:100%;border-collapse:collapse;font-size:0.9rem;">
<thead>
<tr style="background:#1565c0;color:white;">
  <th style="padding:8px 12px;text-align:left;">指标</th>
  <th style="padding:8px 12px;text-align:left;">{col_prev}</th>
  <th style="padding:8px 12px;text-align:left;">{col_curr}</th>
  <th style="padding:8px 12px;text-align:left;">变化</th>
</tr>
</thead>
<tbody>
{html_rows}
</tbody>
</table>
""", unsafe_allow_html=True)

    # Summary note
    cagr_delta = cm.get('cagr', 0) - pm.get('cagr', 0)
    sharpe_delta = cm.get('sharpe', 0) - pm.get('sharpe', 0)
    if abs(cagr_delta) < 0.001 and abs(sharpe_delta) < 0.002:
        summary = "本次数据更新对核心指标影响极小，策略表现基本稳定。"
    elif cagr_delta > 0.002 or sharpe_delta > 0.005:
        summary = f"新增数据有所提升策略表现：CAGR {'▲' if cagr_delta > 0 else '▼'} {abs(cagr_delta)*100:.2f}pp，Sharpe {'▲' if sharpe_delta > 0 else '▼'} {abs(sharpe_delta):.4f}。"
    else:
        summary = f"新增数据对策略表现有轻微影响：CAGR {'▲' if cagr_delta > 0 else '▼'} {abs(cagr_delta)*100:.2f}pp，Sharpe {'▲' if sharpe_delta > 0 else '▼'} {abs(sharpe_delta):.4f}。"

    st.markdown(f"📊 小结：{summary}")


def render_mc_comparison(current_meta, mc_data: dict):
    """Render Monte Carlo specific comparison."""
    prev_path = _V1 / "prev_run_snapshot.json"
    if not prev_path.exists():
        return
    try:
        prev = json.loads(prev_path.read_text())
    except Exception:
        return

    prev_mc = prev.get("montecarlo.json", {})
    if not prev_mc:
        return

    prev_end = prev.get("_run_end", "上次运行")
    curr_end = current_meta.backtest_end
    import datetime as _dt
    try:
        rerun_done = _dt.date.fromisoformat(curr_end) > _dt.date.fromisoformat(prev_end)
    except ValueError:
        rerun_done = curr_end != prev_end

    st.markdown("---")
    st.subheader("数据更新对比（蒙特卡洛）")

    if not rerun_done:
        st.info("数据重跑进行中，刷新页面即可查看最新对比。")
        return

    def _g(d, *keys):
        for k in keys:
            d = d.get(k, {}) if isinstance(d, dict) else {}
        return d if not isinstance(d, dict) else 0

    rows = [
        ("CAGR 中位数（p50）",
         f"{_g(prev_mc, 'cagr_dist', 'p50')*100:.2f}%",
         f"{_g(mc_data, 'cagr_dist', 'p50')*100:.2f}%",
         _delta_html(_g(mc_data, 'cagr_dist', 'p50'), _g(prev_mc, 'cagr_dist', 'p50'))),
        ("CAGR 5th pct",
         f"{_g(prev_mc, 'cagr_dist', 'p5')*100:.2f}%",
         f"{_g(mc_data, 'cagr_dist', 'p5')*100:.2f}%",
         _delta_html(_g(mc_data, 'cagr_dist', 'p5'), _g(prev_mc, 'cagr_dist', 'p5'))),
        ("负收益概率",
         f"{_g(prev_mc, 'cagr_dist', 'prob_negative_cagr')*100:.2f}%",
         f"{_g(mc_data, 'cagr_dist', 'prob_negative_cagr')*100:.2f}%",
         _delta_html(_g(mc_data, 'cagr_dist', 'prob_negative_cagr'),
                     _g(prev_mc, 'cagr_dist', 'prob_negative_cagr'), lower_better=True)),
        ("最大回撤中位数",
         f"{abs(_g(prev_mc, 'max_drawdown_dist', 'p50'))*100:.2f}%",
         f"{abs(_g(mc_data, 'max_drawdown_dist', 'p50'))*100:.2f}%",
         _delta_html(abs(_g(mc_data, 'max_drawdown_dist', 'p50')),
                     abs(_g(prev_mc, 'max_drawdown_dist', 'p50')), lower_better=True)),
        ("最大回撤 95th pct",
         f"{abs(_g(prev_mc, 'max_drawdown_dist', 'p95'))*100:.2f}%",
         f"{abs(_g(mc_data, 'max_drawdown_dist', 'p95'))*100:.2f}%",
         _delta_html(abs(_g(mc_data, 'max_drawdown_dist', 'p95')),
                     abs(_g(prev_mc, 'max_drawdown_dist', 'p95')), lower_better=True)),
    ]

    _render_comparison_table(rows, prev_end, curr_end)


def render_wf_comparison(current_meta, wf_data: dict):
    """Render Walk-Forward specific comparison."""
    prev_path = _V1 / "prev_run_snapshot.json"
    if not prev_path.exists():
        return
    try:
        prev = json.loads(prev_path.read_text())
    except Exception:
        return

    prev_wf = prev.get("walkforward.json", {})
    if not prev_wf:
        return

    prev_end = prev.get("_run_end", "上次运行")
    curr_end = current_meta.backtest_end
    import datetime as _dt
    try:
        rerun_done = _dt.date.fromisoformat(curr_end) > _dt.date.fromisoformat(prev_end)
    except ValueError:
        rerun_done = curr_end != prev_end

    st.markdown("---")
    st.subheader("数据更新对比（Walk-Forward）")

    if not rerun_done:
        st.info("数据重跑进行中，刷新页面即可查看最新对比。")
        return

    def _oos(d):
        return d.get("oos_stitched", {}).get("metrics", {})

    p_oos = _oos(prev_wf)
    c_oos = _oos(wf_data)

    rows = [
        ("OOS 拼接 CAGR",
         f"{p_oos.get('cagr', 0)*100:.2f}%",
         f"{c_oos.get('cagr', 0)*100:.2f}%",
         _delta_html(c_oos.get('cagr', 0), p_oos.get('cagr', 0))),
        ("OOS 拼接 Sharpe",
         f"{p_oos.get('sharpe', 0):.4f}",
         f"{c_oos.get('sharpe', 0):.4f}",
         _delta_html(c_oos.get('sharpe', 0), p_oos.get('sharpe', 0), pct_scale=False)),
        ("OOS 拼接最大回撤",
         f"{abs(p_oos.get('max_drawdown', 0))*100:.2f}%",
         f"{abs(c_oos.get('max_drawdown', 0))*100:.2f}%",
         _delta_html(abs(c_oos.get('max_drawdown', 0)), abs(p_oos.get('max_drawdown', 0)), lower_better=True)),
    ]

    _render_comparison_table(rows, prev_end, curr_end)


def render_regime_comparison(current_meta, regime_data: dict):
    """Render Regime Analysis specific comparison."""
    prev_path = _V1 / "prev_run_snapshot.json"
    if not prev_path.exists():
        return
    try:
        prev = json.loads(prev_path.read_text())
    except Exception:
        return

    prev_reg = prev.get("regime.json", {})
    if not prev_reg:
        return

    prev_end = prev.get("_run_end", "上次运行")
    curr_end = current_meta.backtest_end
    import datetime as _dt
    try:
        rerun_done = _dt.date.fromisoformat(curr_end) > _dt.date.fromisoformat(prev_end)
    except ValueError:
        rerun_done = curr_end != prev_end

    st.markdown("---")
    st.subheader("数据更新对比（市场环境）")

    if not rerun_done:
        st.info("数据重跑进行中，刷新页面即可查看最新对比。")
        return

    def _full(d):
        return d.get("full_period", {})

    pf = _full(prev_reg)
    cf = _full(regime_data)

    rows = [
        ("全周期 CAGR",
         f"{pf.get('strategy_cagr', 0)*100:.2f}%",
         f"{cf.get('strategy_cagr', 0)*100:.2f}%",
         _delta_html(cf.get('strategy_cagr', 0), pf.get('strategy_cagr', 0))),
        ("全周期 Sharpe",
         f"{pf.get('strategy_sharpe', 0):.4f}",
         f"{cf.get('strategy_sharpe', 0):.4f}",
         _delta_html(cf.get('strategy_sharpe', 0), pf.get('strategy_sharpe', 0), pct_scale=False)),
        ("全周期最大回撤",
         f"{abs(pf.get('strategy_max_drawdown', 0))*100:.2f}%",
         f"{abs(cf.get('strategy_max_drawdown', 0))*100:.2f}%",
         _delta_html(abs(cf.get('strategy_max_drawdown', 0)), abs(pf.get('strategy_max_drawdown', 0)), lower_better=True)),
    ]

    _render_comparison_table(rows, prev_end, curr_end)


def _render_comparison_table(rows, prev_end: str, curr_end: str):
    col_prev = f"上次运行（≈{prev_end}）"
    col_curr = f"本次运行（{curr_end}）"

    html_rows = ""
    for metric, old_v, new_v, delta_h in rows:
        html_rows += f"<tr><td style='padding:6px 12px'>{metric}</td><td style='padding:6px 12px'>{old_v}</td><td style='padding:6px 12px'>{new_v}</td><td style='padding:6px 12px'>{delta_h}</td></tr>"

    st.markdown(f"""
<table style="width:100%;border-collapse:collapse;font-size:0.9rem;">
<thead>
<tr style="background:#1565c0;color:white;">
  <th style="padding:8px 12px;text-align:left;">指标</th>
  <th style="padding:8px 12px;text-align:left;">{col_prev}</th>
  <th style="padding:8px 12px;text-align:left;">{col_curr}</th>
  <th style="padding:8px 12px;text-align:left;">变化</th>
</tr>
</thead>
<tbody>
{html_rows}
</tbody>
</table>
""", unsafe_allow_html=True)
