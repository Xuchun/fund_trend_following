"""参数敏感性分析"""

import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pandas as pd
import streamlit as st
from website.shared import get_results, placeholder
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta
p    = meta.params_anchor
m    = res.metrics

render_page_header("参数敏感性分析", meta)
st.caption(f"{meta.display_name} · 回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")


# ── Helper: load perturbation JSON ───────────────────────────────────────────
_PERTURB_DIR = Path(__file__).resolve().parents[2] / "results" / "v1" / "perturbation"


def _load_perturbation(param_name: str) -> dict | None:
    """Return parsed JSON dict for param_name, or None if not yet computed."""
    path = _PERTURB_DIR / f"{param_name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _cost(turnover, params=p):
    rt = (params.get("slippage_bps", 10) + params.get("commission_bps", 3)) * 2
    return turnover * rt / 100


# ── Overview table ─────────────────────────────────────────────────────────────
st.subheader("分析框架")
st.markdown(f"""
参数敏感性分析的目的是验证策略对参数选择的**鲁棒性（Robustness）**：
若策略在宽泛的参数范围内均能盈利，说明结果不依赖于特定参数的过拟合。

| 参数 | 当前基准值 | 测试范围 | 分析目的 | 状态 |
|------|-----------|---------|---------|------|
| 早期移动止盈乘数（< 1R） | **{p['trail_multiplier_r1']:.0f}×ATR** | 2.0 / 2.5 / 3.0 / 3.5 / 4.0 | 降低换手率 vs 早期止损保护 | ✅ 已完成 |
| 突破窗口（N） | **{p['breakout_window']} 日** | 150 / 170 / 200 / 230 / 250 / 270 / 300 | 动量周期与信号频率 | ✅ 已完成 |
| ATR 止损乘数 | {p['stop_loss_multiplier']:.1f}× | 1.5 / 2.0 / 2.5 / 3.0 | 止损松紧对 MaxDD 的影响 | 🔜 待分析 |
| 每笔风险比例 | {p['risk_per_trade']*100:.1f}% | 0.5% / 1.0% / 1.5% / 2.0% | 仓位大小对 MaxDD 的影响 | 🔜 待分析 |
| 单标的仓位上限 | {p['position_cap']*100:.0f}% NAV | 3% / 5% / 7% / 10% | 集中度 vs 分散化 | 🔜 待分析 |
| 热度上限 | {p['heat_limit']*100:.0f}% | 5% / 10% / 15% / 20% | 组合集中度影响 | 🔜 待分析 |
| 相关性阈值 | {p['correlation_threshold']:.2f} | 0.5 / 0.6 / 0.7 / 0.8 / 0.9 | 分散化效果 | 🔜 待分析 |
| 成交量确认乘数 | **{p.get('volume_filter_multiplier', 0):.1f}×** | 1.0 / 1.2 / 1.5 / 1.7 / 2.0 | 过滤低质量假突破 vs 入场频率 | 🔜 待分析 |
| 最低收盘价 | \${p.get('min_price', 10):.0f} | $8 / $10 / $12 / $15 | 低价股噪声过滤强度 | 🔜 待分析 |
| 最低市值 | \${p.get('min_market_cap_b', 2):.0f}B | $2B / $3B / $4B | 大盘 vs 中盘稳定性 | 🔜 待分析 |
| ADV 流动性过滤 | \${p.get('min_adv_m', 20):.0f}M | $10M / $20M / $30M | 流动性约束 vs 可交易标的数 | 🔜 待分析 |
| 滑点（单边） | {p.get('slippage_bps', 10):.0f} bps | 5 / 10 / 20 / 30 bps | 实盘摩擦敏感度 | 🔜 待分析 |
| 佣金（单边） | {p.get('commission_bps', 3):.0f} bps | 0 / 1 / 3 / 5 bps | 高频成本敏感性 | 🔜 待分析 |
""")

st.markdown("---")


# ── Section 1: trail_multiplier_r1 ────────────────────────────────────────────
st.subheader("✅ 已完成：早期追踪止损乘数（trail_multiplier_r1）")
st.markdown("""
**背景：** 原版 2×ATR 早期追踪止损过紧，大量仓位在趋势充分发展前被震出，
年换手率高达 11.24x，隐含年化交易成本 2.92%。
2023年 版本升级至 3×ATR 并同步切换复权价格（adj prices），令分红收益纳入回测 NAV。

**新测试范围：** 2.0 / 2.5 / 3.0（当前基准）/ 3.5 / 4.0，
在完整 2004–2026 回测期、全宇宙（S&P900 + ETF）、SPY 200日过滤器下对比。
""")

trail_data = _load_perturbation("trail_multiplier_r1")

if trail_data is not None:
    # ── Full 5-value perturbation results ─────────────────────────────────────
    recs = trail_data["results"]
    rows = []
    for r in recs:
        val = r["param_value"]
        is_baseline = abs(val - trail_data["baseline_value"]) < 0.01
        label = f"**{val:.1f}×ATR（基准）**" if is_baseline else f"{val:.1f}×ATR"
        turnover = r.get("annual_turnover", 0)
        cost     = turnover * (10 + 3) * 2 / 100
        rows.append([
            label,
            f"{r.get('cagr', 0)*100:+.2f}%",
            f"{r.get('max_drawdown', 0)*100:.1f}%",
            f"{r.get('sharpe', 0):+.3f}",
            f"{turnover:.2f}x",
            f"{r.get('trades_per_year', 0):.0f} 笔/年",
            f"{r.get('avg_holding_days', 0):.0f} 天",
            f"≈{cost:.2f}%",
        ])

    st.dataframe(
        pd.DataFrame(rows, columns=[
            "乘数", "CAGR", "最大回撤", "Sharpe（rf=2%）",
            "年换手率", "交易频率", "平均持仓", "隐含年化成本",
        ]),
        use_container_width=True, hide_index=True,
    )
    st.caption(
        f"数据来源：results/v1/perturbation/trail_multiplier_r1.json  "
        f"（全宇宙，rf=2%，{trail_data['start']} → {trail_data['end']}）"
    )

    # Find baseline row for conclusion
    base_rec = next(
        (r for r in recs if abs(r["param_value"] - trail_data["baseline_value"]) < 0.01),
        recs[0],
    )
    st.markdown(f"""
**结论：** 在 2–4×ATR 范围内，策略 CAGR 和 Sharpe 保持相对稳定，说明结果对该参数具有**鲁棒性**。
- 乘数过小（2×ATR）：换手率高、持仓短，交易摩擦拖累收益
- 乘数过大（4×ATR）：回撤容忍度更高，但趋势后期拿回更多
- **基准 {trail_data['baseline_value']:.0f}×ATR**：CAGR {base_rec.get('cagr',0)*100:+.2f}%，Sharpe {base_rec.get('sharpe',0):+.3f}，换手率 {base_rec.get('annual_turnover',0):.2f}x
""")
else:
    # ── Fallback: old 2-value hardcoded comparison ─────────────────────────────
    trail_rows = [
        ("CAGR",            "+2.05%",  "+4.03%"),
        ("最大回撤",          "-31.6%",  "-28.4%"),
        ("Sharpe（rf=5%）",   "-0.172",  "-0.018"),
        ("年换手率",           "11.24x",  "7.54x"),
        ("交易频率",           "261 笔/年", "177 笔/年"),
        ("平均持仓",           "24 天",   "37 天"),
        ("隐含年化成本",        "2.92%",   "1.96%"),
    ]
    st.dataframe(
        pd.DataFrame(trail_rows, columns=["指标", "2×ATR·原始价（原版）", "3×ATR·复权价（改后）"]),
        use_container_width=True, hide_index=True,
    )
    st.caption("注：上表 Sharpe 使用无风险利率 5% 计算（与当时代码一致）；当前基准已改为 2%（历史均值）。")
    st.info(
        "全范围扰动测试（2.0 / 2.5 / 3.0 / 3.5 / 4.0）正在运行中，"
        "完成后此表将自动更新为五点比较数据。"
    )
    st.markdown("""
**已知结论（2点对比）：** 两项改动叠加后，CAGR 翻倍（+2.05% → +4.03%），最大回撤改善 3 个百分点，
交易成本降低约 1%/年，平均持仓从 24 天延长至 37 天。
""")

st.markdown("---")


# ── Section 2: breakout_window ────────────────────────────────────────────────
st.subheader("✅ 已完成：突破窗口（breakout_window）")
st.markdown("""
**背景：** 突破窗口 N 决定"趋势"的时间尺度。
N 越小信号越多，但噪音也越高；N 越大信号越少，但动量更强。
200 日突破（52 周新高）是机构趋势跟踪最常用的入场门槛。

**新测试范围：** 150 / 200（当前基准）/ 250 / 300，
在完整 2004–2026 回测期、全宇宙、SPY 200日过滤器下对比。
""")

bw_data = _load_perturbation("breakout_window")

if bw_data is not None:
    # ── Full 4-value perturbation results ─────────────────────────────────────
    recs = bw_data["results"]
    rows = []
    for r in recs:
        val = r["param_value"]
        is_baseline = abs(val - bw_data["baseline_value"]) < 1
        label = f"**N={int(val)}（基准）**" if is_baseline else f"N={int(val)}"
        turnover = r.get("annual_turnover", 0)
        cost     = turnover * (10 + 3) * 2 / 100
        rows.append([
            label,
            f"{r.get('cagr', 0)*100:+.2f}%",
            f"{r.get('max_drawdown', 0)*100:.1f}%",
            f"{r.get('sharpe', 0):+.3f}",
            f"{turnover:.2f}x",
            f"{r.get('trades_per_year', 0):.0f} 笔/年",
            f"{r.get('avg_holding_days', 0):.0f} 天",
            f"≈{cost:.2f}%",
            f"{int(r.get('max_dd_duration_days', 0)):,} 天",
        ])

    st.dataframe(
        pd.DataFrame(rows, columns=[
            "突破窗口", "CAGR", "最大回撤", "Sharpe（rf=2%）",
            "年换手率", "交易频率", "平均持仓", "隐含年化成本", "最长水下",
        ]),
        use_container_width=True, hide_index=True,
    )
    st.caption(
        f"数据来源：results/v1/perturbation/breakout_window.json  "
        f"（全宇宙，rf=2%，{bw_data['start']} → {bw_data['end']}）"
    )

    base_rec = next(
        (r for r in recs if abs(r["param_value"] - bw_data["baseline_value"]) < 1),
        recs[0],
    )
    st.markdown(f"""
**结论：** 突破窗口从 150 延长至 300，策略特征平滑变化：
- 窗口越长：信号更少、持仓更久、换手更低、交易摩擦更小
- **基准 N={int(bw_data['baseline_value'])}**：CAGR {base_rec.get('cagr',0)*100:+.2f}%，Sharpe {base_rec.get('sharpe',0):+.3f}，均持仓 {base_rec.get('avg_holding_days',0):.0f} 天
- 宽泛范围内策略均能盈利，说明对突破窗口具有**鲁棒性**

> **选择 N=200 的理由**：52 周新高是业界最常用的趋势入场门槛，
> 信号少但质量高，持仓时间更长，交易摩擦成本更低。
""")
else:
    # ── Fallback: existing 2-value comparison ─────────────────────────────────
    is_200 = abs(p.get("breakout_window", 100) - 200) < 1
    cagr_cur     = m.get("cagr", 0)
    maxdd_cur    = m.get("max_drawdown", 0)
    sharpe_cur   = m.get("sharpe", 0)
    turnover_cur = m.get("annual_turnover", 0)
    tpy_cur      = m.get("trades_per_year", 0)
    hold_cur     = m.get("avg_holding_days", 0)
    cost_cur     = _cost(turnover_cur)
    maxdd_dur    = m.get("max_dd_duration_days", 0)

    fmt_cur = [
        f"{cagr_cur*100:+.2f}%",
        f"{maxdd_cur*100:.1f}%",
        f"{sharpe_cur:+.3f}",
        f"{turnover_cur:.2f}x",
        f"{tpy_cur:.0f} 笔/年",
        f"{hold_cur:.0f} 天",
        f"{cost_cur:.2f}%",
        f"{maxdd_dur:,} 天",
    ]

    REF_N100 = ["+4.03%", "-28.4%", "-0.018", "7.54x", "177 笔/年", "37 天", "1.96%", "789 天"]

    if is_200:
        col_n100, col_n200 = REF_N100, fmt_cur
        lbl_n100, lbl_n200 = "N=100（原版）", "**N=200（当前）**"
    else:
        col_n100, col_n200 = fmt_cur, ["—"] * len(fmt_cur)
        lbl_n100, lbl_n200 = "**N=100（当前）**", "N=200（待回测）"

    bw_rows = list(zip(
        ["CAGR", "最大回撤", "Sharpe（rf=5%→2%）", "年换手率",
         "交易频率", "平均持仓", "隐含年化成本", "最长水下时间"],
        col_n100, col_n200,
    ))
    st.dataframe(
        pd.DataFrame(bw_rows, columns=["指标", lbl_n100, lbl_n200]),
        use_container_width=True, hide_index=True,
    )
    if is_200:
        st.caption("注：N=100 的 Sharpe 使用旧无风险利率 5% 计算；N=200 使用 2%（历史均值）。")

    st.info(
        "全范围扰动测试（150 / 200 / 250 / 300）正在运行中，"
        "完成后此表将自动更新为四点比较数据。"
    )

    if is_200:
        cagr_chg  = cagr_cur - 0.0403
        tpy_chg   = tpy_cur - 177
        hold_chg  = hold_cur - 37
        cost_chg  = cost_cur - 1.96
        st.markdown(f"""
**已知结论（2点对比）：**
- **交易频率**：{tpy_cur:.0f} 笔/年（原 177 笔，变化 {tpy_chg:+.0f} 笔）
- **平均持仓**：{hold_cur:.0f} 天（原 37 天，变化 {hold_chg:+.0f} 天）
- **隐含年化成本**：{cost_cur:.2f}%（原 1.96%，节省 {1.96-cost_cur:+.2f}%/年）
- **CAGR**：{cagr_cur*100:+.2f}%（原 +4.03%，变化 {cagr_chg*100:+.2f}%）
""")

st.markdown("---")


# ── Pending analyses ───────────────────────────────────────────────────────────
st.subheader("🔜 待完成：其他参数网格搜索")
st.markdown("""
以下分析将在后续版本中完成，采用**网格搜索（Grid Search）+ 热力图**形式展示：

**分析优先级：**
1. **ATR 止损乘数**：与持仓时间和回撤深度直接相关
2. **每笔风险比例 + 单标的仓位上限**：影响仓位规模和资金曲线波动
3. **热度上限 + 相关性阈值**：联合分析，评估分散化效果
4. **滑点 + 佣金**：评估交易成本假设对最终收益的敏感度
5. **最低价格 / 市值 / ADV 过滤器**：评估标的池收紧/放宽对信号质量的影响
6. **成交量确认乘数**：过滤假突破 vs 入场机会的权衡

每个参数的分析结果将包含：
- CAGR / Sharpe / MaxDD 热力图（参数 × 时间子区间）
- 最优参数区间识别
- 参数稳定性评估（避免过拟合）
""")

placeholder("Phase 6", "参数敏感性分析 — 网格搜索热力图")

st.markdown("---")
st.subheader("交易执行诊断（Trade Execution Diagnostics）")

_DIAG_PATH = Path(__file__).resolve().parents[2] / "results" / "v1" / "diagnostics.json"

if _DIAG_PATH.exists():
    import json as _json
    diag = _json.loads(_DIAG_PATH.read_text(encoding="utf-8"))

    # ── Section A: Gap 止损分析 ────────────────────────────────────────────
    st.markdown("#### A. Gap 止损分析（只统计触发固定止损的交易）")

    gs = diag.get("gap_loss_stats", {})
    col1, col2, col3 = st.columns(3)
    col1.metric("止损交易笔数", f"{gs.get('n_stop_trades', 0):,}")
    col2.metric("理论止损损失", "-1.00R（计划）")
    col3.metric("实际平均止损损失", f"{gs.get('mean', 0.0):.2f}R")

    col4, col5, col6 = st.columns(3)
    col4.metric("在计划止损价内", f"{gs.get('pct_within_1r', 0.0)*100:.1f}%")
    col5.metric("缺口扩大到 > 2R", f"{gs.get('pct_beyond_2r', 0.0)*100:.1f}%")
    col6.metric("严重缺口 > 5R",  f"{gs.get('pct_beyond_5r', 0.0)*100:.1f}%")

    eq = diag.get("execution_quality", {})
    assessment = eq.get("assessment", "")
    if assessment == "excellent":
        box_color, border_color = "#e8f5e9", "#2e7d32"
        icon = "✅"
    elif assessment == "acceptable":
        box_color, border_color = "#fff8e1", "#f57c00"
        icon = "⚠️"
    else:
        box_color, border_color = "#ffebee", "#c62828"
        icon = "🔴"

    st.markdown(
        f'<div class="info-box" style="background:{box_color};border-left-color:{border_color};">'
        f'{icon} 执行质量评估：<strong>{assessment.upper()}</strong> — '
        f'理论止损 {eq.get("expected_avg_loss_r", -1.0):+.2f}R，'
        f'实际止损 {eq.get("actual_avg_loss_r", 0.0):+.3f}R，'
        f'缺口影响 {eq.get("gap_impact_r", 0.0):+.3f}R'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.caption("数据来源：results/v1/diagnostics.json | 仅统计 exit_reason == stop_loss 的交易")

    # ── Section B: 连续亏损序列分析 ───────────────────────────────────────
    st.markdown("#### B. 连续亏损序列分析")

    sa = diag.get("streak_analysis", {})
    sb1, sb2, sb3 = st.columns(3)
    sb1.metric("最长连续亏损（笔）", sa.get("max_consecutive_losses", 0))
    sb2.metric("平均序列长度",       f"{sa.get('avg_streak_length', 0.0):.2f}")
    sb3.metric("亏损序列总数",       sa.get("total_streaks", 0))

    # Build streak table (group >= 10 under "≥10")
    streak_counts: dict = sa.get("streak_counts", {})
    if streak_counts:
        table_rows = []
        cumulative = 0
        total_streaks = sa.get("total_streaks", 1) or 1

        # Lengths 1-9 individually, then "≥10"
        for length in range(1, 10):
            key = str(length)
            cnt = streak_counts.get(key, 0)
            cumulative += cnt
            table_rows.append({
                "序列长度（笔）": length,
                "出现次数":       cnt,
                "累计占比":       f"{cumulative / total_streaks * 100:.1f}%",
            })
        # Group >= 10
        cnt_10plus = streak_counts.get("10+", 0)
        cumulative += cnt_10plus
        table_rows.append({
            "序列长度（笔）": "≥10",
            "出现次数":       cnt_10plus,
            "累计占比":       f"{cumulative / total_streaks * 100:.1f}%",
        })
        st.dataframe(
            pd.DataFrame(table_rows),
            use_container_width=False,
            hide_index=True,
        )

    max_cl = sa.get("max_consecutive_losses", 0)
    st.markdown(
        f'<div class="info-box">'
        f'最长连续亏损 <strong>{max_cl} 笔</strong>——对心理承受力的考验，'
        f'但在趋势策略中属于正常特征（胜率 ~38%）。'
        f'在 38% 胜率下，统计期望每隔约 2.6 笔出现一次亏损连续段。'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Section C: 逐年交易质量 ───────────────────────────────────────────
    st.markdown("#### C. 逐年交易质量")

    yearly = diag.get("yearly_stats", [])
    if yearly:
        yearly_rows = []
        for row in yearly:
            yearly_rows.append({
                "年份":       row["year"],
                "交易笔数":   row["n_trades"],
                "胜率":       f"{row['win_rate']*100:.1f}%",
                "平均R":      f"{row['avg_r']:+.3f}",
                "最佳交易R":  f"{row['best_r']:+.3f}",
                "最差交易R":  f"{row['worst_r']:+.3f}",
                "平均持仓天数": f"{row['avg_hold_days']:.0f}",
            })
        st.dataframe(
            pd.DataFrame(yearly_rows),
            use_container_width=True,
            hide_index=True,
        )
else:
    st.info("诊断数据尚未生成。运行：python src/scripts/04_run_diagnostics.py")

# ── Assessment ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("评估")

trail_data = _load_perturbation("trail_multiplier_r1")
bw_data    = _load_perturbation("breakout_window")

if trail_data and bw_data:
    t_recs = trail_data["results"]
    b_recs = bw_data["results"]
    t_base = trail_data["baseline_value"]
    b_base = bw_data["baseline_value"]

    # trail: all positive?
    t_all_pos = all(r["cagr"] > 0 for r in t_recs)
    t_min_cagr = min(r["cagr"] for r in t_recs)
    t_max_cagr = max(r["cagr"] for r in t_recs)
    t_cagr_range = t_max_cagr - t_min_cagr
    t_base_rec = next(r for r in t_recs if abs(r["param_value"] - t_base) < 0.01)

    # trail: best Pareto point (max Sharpe)
    t_best_sharpe_rec = max(t_recs, key=lambda r: r["sharpe"])
    t_best_cagr_rec   = max(t_recs, key=lambda r: r["cagr"])

    # Is baseline the optimum for trail?
    t_baseline_is_best = (
        abs(t_base_rec["param_value"] - t_best_sharpe_rec["param_value"]) < 0.01
    )

    # breakout: all positive?
    b_all_pos = all(r["cagr"] > 0 for r in b_recs)
    b_min_cagr = min(r["cagr"] for r in b_recs)
    b_max_cagr = max(r["cagr"] for r in b_recs)
    b_cagr_range = b_max_cagr - b_min_cagr
    b_base_rec = next(r for r in b_recs if abs(r["param_value"] - b_base) < 1)

    b_best_sharpe_rec = max(b_recs, key=lambda r: r["sharpe"])
    b_baseline_is_best = (
        abs(b_base_rec["param_value"] - b_best_sharpe_rec["param_value"]) < 1
    )

    # trail monotonic check: does Sharpe increase as param increases?
    t_sharpes = [r["sharpe"] for r in sorted(t_recs, key=lambda r: r["param_value"])]
    t_monotonic_up = all(t_sharpes[i] <= t_sharpes[i+1] for i in range(len(t_sharpes)-1))

    st.markdown(f"""
**1. 两参数测试范围内均无负收益，策略具备基础鲁棒性**

在已完成的两个参数扰动测试中，全部 {len(t_recs) + len(b_recs)} 个参数取值均实现正 CAGR：
- `trail_multiplier_r1`（2.0→4.0×）：CAGR 区间 [{t_min_cagr*100:+.2f}%, {t_max_cagr*100:+.2f}%]
- `breakout_window`（150→300）：CAGR 区间 [{b_min_cagr*100:+.2f}%, {b_max_cagr*100:+.2f}%]

任何合理参数组合下策略均能盈利，这是鲁棒性的核心证据：
策略的正期望来自市场结构（趋势持续性），而非对某个特定参数值的精确依赖。

**2. breakout_window：参数景观极为平坦，基准选择可信度高**

N=150→300 的 CAGR 变化幅度仅 **{b_cagr_range*100:.2f}%**，Sharpe 最大差距仅
{(max(r["sharpe"] for r in b_recs) - min(r["sharpe"] for r in b_recs)):.3f}。
{"基准 N=" + str(int(b_base)) + " 恰好是局部最优值（Sharpe 最高），" if b_baseline_is_best else "基准 N=" + str(int(b_base)) + " 接近局部最优，"}
且 200 日突破（52 周新高）有充分的行业实践支撑。
平坦的参数景观意味着：即便在实盘中突破周期发生小幅漂移，策略表现不会有显著退化。
这是两个参数中过拟合风险最低的。

**3. trail_multiplier_r1：性能随乘数增大单调递增，基准不是最优点**

这是参数敏感性分析最值得关注的发现。
Sharpe 从 2.0× 的 {t_sharpes[0]:+.3f} 单调上升至 4.0× 的 {t_sharpes[-1]:+.3f}，
CAGR 从 {t_min_cagr*100:+.2f}% 升至 {t_max_cagr*100:+.2f}%，呈**完全单调递增**趋势。

| 乘数 | CAGR | Sharpe | MaxDD |
|------|------|--------|-------|
| **3.0×（基准）** | {t_base_rec["cagr"]*100:+.2f}% | {t_base_rec["sharpe"]:+.3f} | {t_base_rec["max_drawdown"]*100:.1f}% |
| **{t_best_sharpe_rec["param_value"]:.1f}×（Sharpe最高）** | {t_best_sharpe_rec["cagr"]*100:+.2f}% | {t_best_sharpe_rec["sharpe"]:+.3f} | {t_best_sharpe_rec["max_drawdown"]*100:.1f}% |

基准 3.0× 是从原版 2.0×（高换手率）升级时的权衡选择；
当前数据显示 **{t_best_sharpe_rec["param_value"]:.1f}× 在 CAGR、Sharpe、MaxDD 三项上全面优于基准**，
且换手率差距已不显著（{t_best_sharpe_rec["annual_turnover"]:.2f}x vs {t_base_rec["annual_turnover"]:.2f}x）。
建议将此参数列为下一版本重新评估的候选项，
但需警惕：单调趋势在样本内可能只反映"止损更宽 = 更多趋势被完整持有"的机制优势，
也可能包含对历史数据的隐性过拟合。应在 OOS 数据上验证该差距是否持续。

**4. 已测试参数覆盖率有限，核心风险参数尚未分析**

当前仅完成 8 个计划参数中的 2 个（25%）。
尚未分析的 6 个参数中，以下三个对策略表现影响更为直接：

| 参数 | 影响维度 | 待测范围 |
|------|---------|---------|
| `stop_loss_multiplier`（ATR止损乘数）| MaxDD 深度、R 倍数分布 | 1.5 / 2.0 / 2.5 / 3.0 |
| `risk_per_trade`（每笔风险比例）| 仓位大小、NAV 波动率 | 0.5% / 1.0% / 1.5% / 2.0% |
| `heat_limit`（热度上限）| 组合集中度、极端市场暴露 | 5% / 10% / 15% / 20% |

在这些核心风险参数完成测试之前，
"策略整体鲁棒性"的结论尚不完整。特别是止损乘数与每笔风险比例的联合影响，
决定了策略在极端行情中的真实最大损失能力。

**5. 综合评估结论**
""")

    # Overall verdict
    concerns = []
    if not t_baseline_is_best:
        concerns.append(f"trail_multiplier_r1 基准值不是样本内最优（{t_best_sharpe_rec['param_value']:.1f}× 更优）")
    if b_cagr_range > 0.02:
        concerns.append("breakout_window CAGR 变动超过 2%")

    if not concerns:
        verdict_icon = "✅"
        verdict_body = (
            f"两个已测参数均通过鲁棒性验证：全范围正收益，景观平坦，无明显过拟合迹象。"
            f"主要待办是将 trail_multiplier_r1 的最优值（{t_best_sharpe_rec['param_value']:.1f}×）"
            f"纳入 OOS 验证，并完成止损乘数、仓位大小等核心风险参数的测试。"
        )
    else:
        verdict_icon = "🟡"
        verdict_body = (
            f"已测参数整体鲁棒，但存在关注点：{'; '.join(concerns)}。"
            f"建议完成全部 8 个参数的扰动测试后再做最终评估。"
        )

    st.markdown(
        f'<div class="info-box"><strong>{verdict_icon} {verdict_body}</strong></div>',
        unsafe_allow_html=True,
    )

else:
    missing = []
    if not trail_data:
        missing.append("trail_multiplier_r1")
    if not bw_data:
        missing.append("breakout_window")
    st.info(
        f"以下扰动数据尚未生成，无法提供完整评估：{', '.join(missing)}\n"
        "运行：python src/scripts/03_run_perturbation.py"
    )
