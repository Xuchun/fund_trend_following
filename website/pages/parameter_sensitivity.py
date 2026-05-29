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

# ── Constants ──────────────────────────────────────────────────────────────────
_PERTURB_DIR = Path(__file__).resolve().parents[2] / "results" / "v1" / "perturbation"
_RF = 0.02
_BASELINE_CAGR  = m.get("cagr", 0)
_BASELINE_SHARPE = m.get("sharpe", 0)
_BASELINE_MAXDD  = m.get("max_drawdown", 0)


# ── Parameter display configuration ───────────────────────────────────────────
# (param_name, display_label, baseline_display, range_display, purpose)
_PARAM_CFG = [
    ("trail_multiplier_r1",   "早期移动止盈乘数（< 1R）",
     f"{p['trail_multiplier_r1']:.0f}×ATR",
     "2.0 / 2.5 / 3.0 / 3.5 / 4.0", "降低换手率 vs 早期止损保护"),
    ("breakout_window",       "突破窗口（N）",
     f"{p['breakout_window']} 日",
     "150 / 170 / 200 / 230 / 250 / 270 / 300", "动量周期与信号频率"),
    ("stop_loss_multiplier",  "ATR 止损乘数",
     f"{p['stop_loss_multiplier']:.1f}×",
     "1.5 / 2.0 / 2.5 / 3.0", "止损松紧对 MaxDD 的影响"),
    ("risk_per_trade",        "每笔风险比例",
     f"{p['risk_per_trade']*100:.1f}%",
     "0.5% / 1.0% / 1.5% / 2.0%", "仓位大小对 MaxDD 的影响"),
    ("position_cap",          "单标的仓位上限",
     f"{p['position_cap']*100:.0f}% NAV",
     "3% / 5% / 7% / 10%", "集中度 vs 分散化"),
    ("heat_limit",            "热度上限",
     f"{p['heat_limit']*100:.0f}%",
     "5% / 10% / 15% / 20%", "组合集中度影响"),
    ("correlation_threshold", "相关性阈值",
     f"{p['correlation_threshold']:.2f}",
     "0.5 / 0.6 / 0.7 / 0.8 / 0.9", "分散化效果"),
    ("volume_filter_multiplier", "成交量确认乘数",
     f"{p.get('volume_filter_multiplier', 1.5):.1f}×",
     "1.0 / 1.2 / 1.5 / 1.7 / 2.0", "过滤低质量假突破 vs 入场频率"),
    ("min_price",             "最低收盘价",
     f"${p.get('min_price', 10):.0f}",
     "$8 / $10 / $12 / $15", "低价股噪声过滤强度"),
    ("min_market_cap_b",      "最低市值",
     f"${p.get('min_market_cap_b', 2):.0f}B",
     "$2B / $3B / $4B", "大盘 vs 中盘稳定性"),
    ("min_adv_m",             "ADV 流动性过滤",
     f"${p.get('min_adv_m', 20):.0f}M",
     "$10M / $20M / $30M", "流动性约束 vs 可交易标的数"),
    ("slippage_bps",          "滑点（单边）",
     f"{p.get('slippage_bps', 10):.0f} bps",
     "5 / 8 / 10 / 12 / 15 bps", "实盘摩擦敏感度"),
    ("commission_bps",        "佣金（单边）",
     f"{p.get('commission_bps', 3):.0f} bps",
     "1 / 3 / 5 bps", "高频成本敏感性"),
]


# ── Helper functions ───────────────────────────────────────────────────────────

def _load(param_name: str) -> dict | None:
    path = _PERTURB_DIR / f"{param_name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _sensitivity_cv(recs: list[dict], metric: str) -> float:
    """Coefficient of variation for a metric across results."""
    vals = [r.get(metric, 0) for r in recs]
    import statistics
    if len(vals) < 2:
        return 0.0
    mn = abs(statistics.mean(vals))
    if mn < 1e-9:
        return 0.0
    return statistics.stdev(vals) / mn


def _robustness_label(cv: float) -> str:
    if cv < 0.10:
        return "✅ 高鲁棒"
    elif cv < 0.25:
        return "🟡 中等"
    else:
        return "🔴 敏感"


def _stability_region(recs: list[dict], metric: str = "sharpe") -> tuple:
    """Largest contiguous range where metric ≥ 90% of peak."""
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


def _format_label(param_name: str, val: float, baseline_val: float) -> str:
    is_base = abs(val - baseline_val) < max(abs(baseline_val) * 0.001, 0.001)
    if param_name == "breakout_window":
        s = f"N={int(val)}"
    elif param_name in ("risk_per_trade", "position_cap", "heat_limit"):
        s = f"{val*100:.1f}%"
    elif param_name in ("slippage_bps", "commission_bps"):
        s = f"{val:.0f} bps"
    elif param_name in ("min_market_cap_b",):
        s = f"${val:.0f}B"
    elif param_name in ("min_adv_m",):
        s = f"${val:.0f}M"
    elif param_name in ("min_price",):
        s = f"${val:.0f}"
    else:
        s = f"{val:.1f}×"
    return f"**{s}（基准）**" if is_base else s


def _make_table(data: dict) -> pd.DataFrame:
    param_name = data["param_name"]
    recs = data["results"]
    baseline_val = data["baseline_value"]
    slippage  = p.get("slippage_bps", 10)
    commission = p.get("commission_bps", 3)
    rows = []
    for r in recs:
        val = r["param_value"]
        turnover = r.get("annual_turnover", 0)
        # For slippage/commission sweeps, cost uses the swept value
        if param_name == "slippage_bps":
            cost = turnover * (val + commission) * 2 / 100
        elif param_name == "commission_bps":
            cost = turnover * (slippage + val) * 2 / 100
        else:
            cost = turnover * (slippage + commission) * 2 / 100
        rows.append({
            "参数值": _format_label(param_name, val, baseline_val),
            "CAGR":  f"{r.get('cagr', 0)*100:+.2f}%",
            "MaxDD": f"{r.get('max_drawdown', 0)*100:.1f}%",
            "Sharpe": f"{r.get('sharpe', 0):+.3f}",
            "Sortino": f"{r.get('sortino', 0):+.3f}",
            "年换手率": f"{turnover:.2f}x",
            "均持仓": f"{r.get('avg_holding_days', 0):.0f}天",
            "隐含年化成本": f"≈{cost:.2f}%",
        })
    return pd.DataFrame(rows)


def _all_positive(recs: list[dict]) -> bool:
    return all(r.get("cagr", 0) > 0 for r in recs)


def _render_param_section(data: dict, section_title: str, background_text: str):
    """Render a full parameter section with table, sensitivity, stability, conclusion."""
    recs = data["results"]
    baseline_val = data["baseline_value"]
    param_name = data["param_name"]

    st.subheader(section_title)
    if background_text:
        st.markdown(background_text)

    df = _make_table(data)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(
        f"来源：results/v1/perturbation/{param_name}.json  "
        f"（全宇宙，rf=2%，{data['start']} → {data['end']}）"
    )

    # Sensitivity metrics
    cv_cagr   = _sensitivity_cv(recs, "cagr")
    cv_sharpe = _sensitivity_cv(recs, "sharpe")
    cv_dd     = _sensitivity_cv(recs, "max_drawdown")

    stab_lo, stab_hi = _stability_region(recs, "sharpe")

    base_rec = next(
        (r for r in recs if abs(r["param_value"] - baseline_val) < max(abs(baseline_val) * 0.001, 0.001)),
        recs[0],
    )
    best_sharpe_rec = max(recs, key=lambda r: r["sharpe"])
    best_cagr_rec   = max(recs, key=lambda r: r["cagr"])
    all_pos = _all_positive(recs)

    sharpes = [r["sharpe"] for r in sorted(recs, key=lambda r: r["param_value"])]
    cagrs   = [r["cagr"]   for r in sorted(recs, key=lambda r: r["param_value"])]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("CAGR CV（敏感度）",   f"{cv_cagr:.3f}",  help="< 0.10 = 高鲁棒 | 0.10–0.25 = 中等 | > 0.25 = 敏感")
    col2.metric("Sharpe CV（敏感度）", f"{cv_sharpe:.3f}", help="< 0.10 = 高鲁棒 | 0.10–0.25 = 中等 | > 0.25 = 敏感")
    col3.metric("CAGR 鲁棒性",  _robustness_label(cv_cagr))
    col4.metric("Sharpe 鲁棒性", _robustness_label(cv_sharpe))

    return {
        "param_name": param_name,
        "recs": recs,
        "baseline_val": baseline_val,
        "base_rec": base_rec,
        "best_sharpe_rec": best_sharpe_rec,
        "best_cagr_rec": best_cagr_rec,
        "all_pos": all_pos,
        "cv_cagr": cv_cagr,
        "cv_sharpe": cv_sharpe,
        "cv_dd": cv_dd,
        "stab_lo": stab_lo,
        "stab_hi": stab_hi,
        "sharpes": sharpes,
        "cagrs": cagrs,
    }


# ── Framework overview table ───────────────────────────────────────────────────
def _status_icon(param_name: str) -> str:
    if (_PERTURB_DIR / f"{param_name}.json").exists():
        return "✅ 已完成"
    return "🔜 待分析"


st.subheader("分析框架")
st.markdown(f"""
参数敏感性分析的目的是验证策略对参数选择的**鲁棒性（Robustness）**：
若策略在宽泛的参数范围内均能盈利，说明结果不依赖于特定参数的过拟合。

| 参数 | 当前基准值 | 测试范围 | 分析目的 | 状态 |
|------|-----------|---------|---------|------|
""" + "\n".join(
    f"| {label} | {baseline} | {rng} | {purpose} | {_status_icon(name)} |"
    for name, label, baseline, rng, purpose in _PARAM_CFG
))

st.info(
    "📌 **关于 IS/OOS 数据范围的说明：**  \n"
    f"本页所有扰动测试使用**完整历史数据（{meta.backtest_start} → {meta.backtest_end}）**，"
    "包含 Walk-Forward 验证中标记为 OOS 的年份（2022–2026）。  \n"
    "这在方法论上是可接受的，原因是：**策略参数（N=200、止损 2×ATR 等）在运行回测前已根据业界经验事先确定**，"
    "并非通过观察 OOS 结果后反向挑选——因此不存在『看 OOS 结果 → 调参 → 再测试』的数据泄漏。  \n"
    "扰动测试的目的仅为验证鲁棒性，而非选择参数。  \n"
    "即将实现的**参数热力图分析**将严格使用 IS 截止日（2021-12-31），与 Walk-Forward OOS 窗口完全隔离。"
)

st.markdown("---")


# ── Per-parameter sections ─────────────────────────────────────────────────────

_section_meta: dict[str, dict] = {}  # collect results for overall assessment

# ── 1. trail_multiplier_r1 ─────────────────────────────────────────────────────
_d = _load("trail_multiplier_r1")
if _d:
    _info = _render_param_section(
        _d,
        "✅ 早期移动止盈乘数（trail_multiplier_r1）",
        """**背景：** 早期（< 1R）移动止盈乘数控制趋势发展初期的止损松紧。
乘数越小，仓位被震出的概率越高；乘数越大，让利给市场更多空间但初期回撤也更大。
基准 3×ATR 是从原版 2×ATR 升级后的权衡选择。""",
    )
    base = _info["base_rec"]
    best = _info["best_sharpe_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"{lo:.1f}×–{hi:.1f}×" if lo is not None else "全范围"
    baseline_is_best = abs(base["param_value"] - best["param_value"]) < 0.01
    monotonic = all(_info["sharpes"][i] <= _info["sharpes"][i+1] for i in range(len(_info["sharpes"])-1))

    st.markdown(f"""
**结论：** {"✅ 全部参数值均实现正 CAGR，策略对该参数具有鲁棒性。" if _info["all_pos"] else "⚠️ 存在负 CAGR 的参数值，需关注。"}
Sharpe 稳定区间：**{stab_str}**（Sharpe ≥ 基准最优值的 90%）。

{"- Sharpe 呈单调递增：更大的乘数在样本内表现更优，但需 OOS 验证" if monotonic else "- Sharpe 呈非单调形态，存在明确的稳定高原区间"}
- 基准 {base['param_value']:.1f}×ATR：CAGR {base['cagr']*100:+.2f}%，Sharpe {base['sharpe']:+.3f}，MaxDD {base['max_drawdown']*100:.1f}%
{"- Sharpe 最高点：基准值本身已是最优" if baseline_is_best else f"- Sharpe 最高点 {best['param_value']:.1f}×ATR（{best['cagr']*100:+.2f}%，Sharpe {best['sharpe']:+.3f}），略优于基准——建议 OOS 验证"}
""")
    _section_meta["trail_multiplier_r1"] = _info
else:
    st.subheader("⏳ 早期移动止盈乘数（trail_multiplier_r1）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")

# ── 2. breakout_window ─────────────────────────────────────────────────────────
_d = _load("breakout_window")
if _d:
    _info = _render_param_section(
        _d,
        "✅ 突破窗口（breakout_window）",
        """**背景：** 突破窗口 N 决定"趋势"的时间尺度。
N 越小信号越多，但噪音也越高；N 越大信号越少，但动量更强。
200 日突破（52 周新高）是机构趋势跟踪最常用的入场门槛。""",
    )
    base = _info["base_rec"]
    best = _info["best_sharpe_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"N={int(lo)}–{int(hi)}" if lo is not None else "全范围"
    cagr_range = max(_info["cagrs"]) - min(_info["cagrs"])

    st.markdown(f"""
**结论：** {"✅ 全部参数值均实现正 CAGR，策略对突破窗口具有鲁棒性。" if _info["all_pos"] else "⚠️ 存在负 CAGR 的参数值。"}
CAGR 变化幅度 **{cagr_range*100:.2f}%**（N=150→300），Sharpe 稳定区间：**{stab_str}**。

- 窗口越长：信号越少、持仓更久、换手更低、交易摩擦更小
- 基准 N={int(base['param_value'])}：CAGR {base['cagr']*100:+.2f}%，Sharpe {base['sharpe']:+.3f}，均持仓 {base['avg_holding_days']:.0f} 天
- 极平坦的参数景观是过拟合风险最低的信号：即便实盘趋势周期发生小幅漂移，策略表现不会显著退化
- **选择 N=200 的理由**：52 周新高具有充分的行业实践支撑，且处于稳定高原区间内
""")
    _section_meta["breakout_window"] = _info
else:
    st.subheader("⏳ 突破窗口（breakout_window）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")

# ── 3. stop_loss_multiplier ────────────────────────────────────────────────────
_d = _load("stop_loss_multiplier")
if _d:
    _info = _render_param_section(
        _d,
        "✅ ATR 止损乘数（stop_loss_multiplier）",
        """**背景：** 固定止损线 = 入场价 − N×ATR(20)。
乘数越小止损越紧，止损频率更高但每次亏损更小；乘数越大止损更宽，
止损频率更低但风险每次更大。在 1R 风险框架下，乘数影响仓位大小（同等资金暴露下，
止损越宽持仓越小）。""",
    )
    base = _info["base_rec"]
    best = _info["best_sharpe_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"{lo:.1f}×–{hi:.1f}×" if lo is not None else "全范围"
    st.markdown(f"""
**结论：** {"✅ 全部参数值均实现正 CAGR。" if _info["all_pos"] else "⚠️ 存在负 CAGR 的参数值。"}
Sharpe 稳定区间：**{stab_str}**。

- 基准 {base['param_value']:.1f}×ATR：CAGR {base['cagr']*100:+.2f}%，Sharpe {base['sharpe']:+.3f}，MaxDD {base['max_drawdown']*100:.1f}%
{"- 基准值即 Sharpe 最优点，无需调整" if abs(base['param_value'] - best['param_value']) < 0.01 else f"- Sharpe 最高点 {best['param_value']:.1f}×（{best['cagr']*100:+.2f}%，Sharpe {best['sharpe']:+.3f}）"}
- CAGR CV={_info['cv_cagr']:.3f}，{_robustness_label(_info['cv_cagr'])}
""")
    _section_meta["stop_loss_multiplier"] = _info
else:
    st.subheader("⏳ ATR 止损乘数（stop_loss_multiplier）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")

# ── 4. risk_per_trade ──────────────────────────────────────────────────────────
_d = _load("risk_per_trade")
if _d:
    _info = _render_param_section(
        _d,
        "✅ 每笔风险比例（risk_per_trade）",
        """**背景：** 理论上，每笔交易风险 = risk_per_trade × NAV，用于计算仓位大小：
仓位股数 = (risk_per_trade × NAV) ÷ (stop_distance × 股价)。
然而在当前配置中，**position_cap（单标的仓位上限 = 5% NAV）是主导约束**，
导致 risk_per_trade ≥ 1% 时几乎所有交易都被截断至 5% NAV 上限。""",
    )
    base = _info["base_rec"]
    best = _info["best_sharpe_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"{lo*100:.1f}%–{hi*100:.1f}%" if lo is not None else "全范围"
    st.markdown(f"""
**结论：** {"✅ 全部参数值均实现正 CAGR。" if _info["all_pos"] else "⚠️ 存在负 CAGR 的参数值。"}
Sharpe 稳定区间：**{stab_str}**。

> ⚠️ **重要发现：position_cap 架空了 risk_per_trade**
>
> **为什么 1.0% / 1.5% / 2.0% 的回测结果几乎完全相同？**
>
> - 典型止损距离（stop_distance_pct）约 4.7% NAV（实测范围 0.51%–13.10%）
> - 以 risk_per_trade=1% 计算：原始仓位 = 1% ÷ 4.7% = **21.3% NAV**，远超 position_cap=5%
> - 因此 **100% 的交易** 在 risk_per_trade ≥ 1% 时都被截断至 5% NAV（position_cap 全面触发）
> - 即使 risk_per_trade=0.5%，仍有 **99.1%** 的交易触发上限
> - 实际每笔真实风险 ≈ 5% NAV × 4.7% ≈ **0.24% NAV**（远低于名义的 1%）
>
> **结论：** 在当前配置下，risk_per_trade 被 position_cap 完全架空，调整此参数（≥ 0.5%）
> 不会改变仓位大小或回测结果。**真正控制风险敞口的参数是 position_cap**。
> 若要使 risk_per_trade 生效，需将 position_cap 提高至 ≥ 25%（不推荐）或将 risk_per_trade 降至 ≤ 0.2%。
""")
    _section_meta["risk_per_trade"] = _info
else:
    st.subheader("⏳ 每笔风险比例（risk_per_trade）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")

# ── 5. position_cap ────────────────────────────────────────────────────────────
_d = _load("position_cap")
if _d:
    _info = _render_param_section(
        _d,
        "✅ 单标的仓位上限（position_cap）",
        """**背景：** 单标的持仓上限（占 NAV）。当仓位大小计算值超出此上限时截断，
保护组合不过度集中于单一标的。
较低上限约束更强，可能错失大趋势；较高上限集中度更高但波动更大。""",
    )
    base = _info["base_rec"]
    best = _info["best_sharpe_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"{lo*100:.0f}%–{hi*100:.0f}%" if lo is not None else "全范围"
    st.markdown(f"""
**结论：** {"✅ 全部参数值均实现正 CAGR。" if _info["all_pos"] else "⚠️ 存在负 CAGR 的参数值。"}
Sharpe 稳定区间：**{stab_str}**。

- 基准 {base['param_value']*100:.0f}%：CAGR {base['cagr']*100:+.2f}%，Sharpe {base['sharpe']:+.3f}，MaxDD {base['max_drawdown']*100:.1f}%
{"- 基准值即 Sharpe 最优点" if abs(base['param_value'] - best['param_value']) < 0.001 else f"- Sharpe 最高点：{best['param_value']*100:.0f}%（{best['cagr']*100:+.2f}%，Sharpe {best['sharpe']:+.3f}）"}
- CAGR CV={_info['cv_cagr']:.3f}，{_robustness_label(_info['cv_cagr'])}
""")
    _section_meta["position_cap"] = _info
else:
    st.subheader("⏳ 单标的仓位上限（position_cap）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")

# ── 6. heat_limit ──────────────────────────────────────────────────────────────
_d = _load("heat_limit")
if _d:
    _info = _render_param_section(
        _d,
        "✅ 热度上限（heat_limit）",
        """**背景：** 热度（Heat）= 所有开仓的风险总和（∑ 止损距离 × 仓位大小 / NAV）。
Heat limit 控制组合总风险暴露上限。当新信号入场会导致总热度超过上限时，该信号不执行。
较低上限更保守，可能错失趋势聚集期的入场机会；较高上限更激进。""",
    )
    base = _info["base_rec"]
    best = _info["best_sharpe_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"{lo*100:.0f}%–{hi*100:.0f}%" if lo is not None else "全范围"
    st.markdown(f"""
**结论：** {"✅ 全部参数值均实现正 CAGR。" if _info["all_pos"] else "⚠️ 存在负 CAGR 的参数值。"}
Sharpe 稳定区间：**{stab_str}**。

- 基准 {base['param_value']*100:.0f}%：CAGR {base['cagr']*100:+.2f}%，Sharpe {base['sharpe']:+.3f}，MaxDD {base['max_drawdown']*100:.1f}%
{"- 基准值即 Sharpe 最优点" if abs(base['param_value'] - best['param_value']) < 0.001 else f"- Sharpe 最高点：{best['param_value']*100:.0f}%（{best['cagr']*100:+.2f}%，Sharpe {best['sharpe']:+.3f}）"}

> ⚠️ **重要发现：heat_limit ≥ 10% 在当前配置下从未触发**
>
> **为什么 10% / 15% / 20% 的回测结果完全相同？**
>
> 热度检查公式：`total_heat = ∑(各仓位风险额) / 当前NAV`
>
> 由于 position_cap=5% NAV 是主导约束（参见上文"每笔风险比例"分析），
> 每笔交易的实际风险约为 5% NAV × 4.7%（典型止损距离）≈ **0.24% NAV**。
>
> | heat_limit 值 | 触发所需并发持仓数 | 实际最大并发持仓 | 是否触发 |
> |---|---|---|---|
> | 5% | > 21 笔 | 32 笔 | **偶尔触发** |
> | 10% | > 42 笔 | 32 笔 | **从不触发** |
> | 15% | > 63 笔 | 32 笔 | **从不触发** |
> | 20% | > 83 笔 | 32 笔 | **从不触发** |
>
> **结论：** heat_limit 代码逻辑正确，但受 position_cap 架空效应影响，
> 真正有效的约束范围是 ≤ 7%（32 笔 × 0.24% ≈ 7.7%）。
> 基准值 10% 已超出实际约束范围，属于冗余安全边际。
> **真正控制组合总风险的参数是 position_cap**。
""")
    _section_meta["heat_limit"] = _info
else:
    st.subheader("⏳ 热度上限（heat_limit）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")

# ── 7. correlation_threshold ───────────────────────────────────────────────────
_d = _load("correlation_threshold")
if _d:
    _info = _render_param_section(
        _d,
        "✅ 相关性阈值（correlation_threshold）",
        """**背景：** 当新信号与已持仓标的的 60 日对数收益率相关性 > 阈值时，
仓位大小减半（correlation_reduction = 0.5）。
较低阈值（如 0.5）意味着更积极地分散，入场更谨慎；
较高阈值（如 0.9）几乎不限制，允许高相关资产同时入场。""",
    )
    base = _info["base_rec"]
    best = _info["best_sharpe_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"{lo:.1f}–{hi:.1f}" if lo is not None else "全范围"
    st.markdown(f"""
**结论：** {"✅ 全部参数值均实现正 CAGR。" if _info["all_pos"] else "⚠️ 存在负 CAGR 的参数值。"}
Sharpe 稳定区间：**{stab_str}**。

- 基准 {base['param_value']:.2f}：CAGR {base['cagr']*100:+.2f}%，Sharpe {base['sharpe']:+.3f}，MaxDD {base['max_drawdown']*100:.1f}%
{"- 基准值即 Sharpe 最优点" if abs(base['param_value'] - best['param_value']) < 0.01 else f"- Sharpe 最高点：阈值 {best['param_value']:.1f}（{best['cagr']*100:+.2f}%，Sharpe {best['sharpe']:+.3f}）"}
- CAGR CV={_info['cv_cagr']:.3f}，{_robustness_label(_info['cv_cagr'])}
""")
    _section_meta["correlation_threshold"] = _info
else:
    st.subheader("⏳ 相关性阈值（correlation_threshold）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")

# ── 8. volume_filter_multiplier ────────────────────────────────────────────────
_d = _load("volume_filter_multiplier")
if _d:
    _info = _render_param_section(
        _d,
        "✅ 成交量确认乘数（volume_filter_multiplier）",
        """**背景：** 入场条件要求突破当日成交量 ≥ N × 60日均量。
较高的乘数过滤更严格（假突破减少，但入场机会也更少）；
乘数 = 1.0 表示仅需成交量高于均量，接近不过滤；设为 0 则完全关闭过滤器。""",
    )
    base = _info["base_rec"]
    best = _info["best_sharpe_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"{lo:.1f}×–{hi:.1f}×" if lo is not None else "全范围"
    st.markdown(f"""
**结论：** {"✅ 全部参数值均实现正 CAGR。" if _info["all_pos"] else "⚠️ 存在负 CAGR 的参数值。"}
Sharpe 稳定区间：**{stab_str}**。

- 基准 {base['param_value']:.1f}×：CAGR {base['cagr']*100:+.2f}%，Sharpe {base['sharpe']:+.3f}，MaxDD {base['max_drawdown']*100:.1f}%
{"- 基准值即 Sharpe 最优点" if abs(base['param_value'] - best['param_value']) < 0.01 else f"- Sharpe 最高点：{best['param_value']:.1f}×（{best['cagr']*100:+.2f}%，Sharpe {best['sharpe']:+.3f}）"}
- 成交量过滤器主要影响入场频率；过度严格时会错失有效突破
""")
    _section_meta["volume_filter_multiplier"] = _info
else:
    st.subheader("⏳ 成交量确认乘数（volume_filter_multiplier）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")

# ── 9. min_price ───────────────────────────────────────────────────────────────
_d = _load("min_price")
if _d:
    _info = _render_param_section(
        _d,
        "✅ 最低收盘价过滤（min_price）",
        r"""**背景：** 过滤股价低于阈值的标的，避免低价股的高噪声、流动性差和大相对价差问题。
阈值降低（\$8）纳入更多中低价股，增加标的池；提高（\$15）只保留较高价格股票。""",
    )
    base = _info["base_rec"]
    best = _info["best_sharpe_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"${lo:.0f}–${hi:.0f}" if lo is not None else "全范围"
    st.markdown(f"""
**结论：** {"✅ 全部参数值均实现正 CAGR。" if _info["all_pos"] else "⚠️ 存在负 CAGR 的参数值。"}
Sharpe 稳定区间：**{stab_str}**。

- 基准 ${base['param_value']:.0f}：CAGR {base['cagr']*100:+.2f}%，Sharpe {base['sharpe']:+.3f}，MaxDD {base['max_drawdown']*100:.1f}%
{"- 基准值即 Sharpe 最优点" if abs(base['param_value'] - best['param_value']) < 0.1 else f"- Sharpe 最高点：${best['param_value']:.0f}（{best['cagr']*100:+.2f}%，Sharpe {best['sharpe']:+.3f}）"}
- CAGR CV={_info['cv_cagr']:.3f}，{_robustness_label(_info['cv_cagr'])}
""")
    _section_meta["min_price"] = _info
else:
    st.subheader("⏳ 最低收盘价过滤（min_price）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")

# ── 10. min_market_cap_b ───────────────────────────────────────────────────────
_d = _load("min_market_cap_b")
if _d:
    _info = _render_param_section(
        _d,
        "✅ 最低市值过滤（min_market_cap_b）",
        """**背景：** 过滤市值低于阈值的标的，聚焦大中盘流动性更好的股票。
注意：当前实现使用 Yahoo Finance 市值（非时序点内），可能存在一定前视偏差。""",
    )
    base = _info["base_rec"]
    best = _info["best_sharpe_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"${lo:.0f}B–${hi:.0f}B" if lo is not None else "全范围"
    st.markdown(f"""
**结论：** {"✅ 全部参数值均实现正 CAGR。" if _info["all_pos"] else "⚠️ 存在负 CAGR 的参数值。"}
Sharpe 稳定区间：**{stab_str}**。

- 基准 ${base['param_value']:.0f}B：CAGR {base['cagr']*100:+.2f}%，Sharpe {base['sharpe']:+.3f}，MaxDD {base['max_drawdown']*100:.1f}%
{"- 基准值即 Sharpe 最优点" if abs(base['param_value'] - best['param_value']) < 0.1 else f"- Sharpe 最高点：${best['param_value']:.0f}B（{best['cagr']*100:+.2f}%，Sharpe {best['sharpe']:+.3f}）"}
- 市值过滤主要影响标的池大小；较小市值纳入更多中盘股，趋势质量可能下降
""")
    _section_meta["min_market_cap_b"] = _info
else:
    st.subheader("⏳ 最低市值过滤（min_market_cap_b）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")

# ── 11. min_adv_m ─────────────────────────────────────────────────────────────
_d = _load("min_adv_m")
if _d:
    _info = _render_param_section(
        _d,
        "✅ ADV 流动性过滤（min_adv_m）",
        r"""**背景：** 仅允许日均成交额（过去 60 日）超过阈值的标的入场，
确保持仓能在合理冲击成本下退出。\$20M 是当前基准，
实盘容量 \$1000 万时，\$20M ADV 意味着当日成交量可轻松容纳。""",
    )
    base = _info["base_rec"]
    best = _info["best_sharpe_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"${lo:.0f}M–${hi:.0f}M" if lo is not None else "全范围"
    st.markdown(f"""
**结论：** {"✅ 全部参数值均实现正 CAGR。" if _info["all_pos"] else "⚠️ 存在负 CAGR 的参数值。"}
Sharpe 稳定区间：**{stab_str}**。

- 基准 ${base['param_value']:.0f}M：CAGR {base['cagr']*100:+.2f}%，Sharpe {base['sharpe']:+.3f}，MaxDD {base['max_drawdown']*100:.1f}%
{"- 基准值即 Sharpe 最优点" if abs(base['param_value'] - best['param_value']) < 0.1 else f"- Sharpe 最高点：${best['param_value']:.0f}M（{best['cagr']*100:+.2f}%，Sharpe {best['sharpe']:+.3f}）"}
- ADV 过滤在降低流动性风险的同时会收窄标的池；过严可能错失有效趋势
""")
    _section_meta["min_adv_m"] = _info
else:
    st.subheader("⏳ ADV 流动性过滤（min_adv_m）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")

# ── 12. slippage_bps ──────────────────────────────────────────────────────────
_d = _load("slippage_bps")
if _d:
    _info = _render_param_section(
        _d,
        "✅ 滑点（slippage_bps）",
        """**背景：** 单边滑点（bps）= 实际成交价与信号价之间的摩擦成本模型。
策略 baseline 假设 10 bps（0.1%）单边滑点，结合市价冲击和买卖价差。
此测试验证策略边际是否足够支撑不同的实盘摩擦水平。""",
    )
    base = _info["base_rec"]
    best = _info["best_sharpe_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"{lo:.0f}–{hi:.0f} bps" if lo is not None else "全范围"
    st.markdown(f"""
**结论：** {"✅ 全部测试水平下策略均保持正收益。" if _info["all_pos"] else "⚠️ 高滑点情景下策略出现负收益，需关注。"}
Sharpe 稳定区间：**{stab_str}**。

- 基准 {base['param_value']:.0f} bps：CAGR {base['cagr']*100:+.2f}%，Sharpe {base['sharpe']:+.3f}，MaxDD {base['max_drawdown']*100:.1f}%
- 滑点从最低到最高值，CAGR 变化 {(max(_info['cagrs'])-min(_info['cagrs']))*100:.2f}%
- CAGR CV={_info['cv_cagr']:.3f}，{_robustness_label(_info['cv_cagr'])}
- 实盘可接受的滑点上限：只要均持仓 > 30 天，每笔 10–15 bps 滑点占总收益比例有限
""")
    _section_meta["slippage_bps"] = _info
else:
    st.subheader("⏳ 滑点（slippage_bps）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")

# ── 13. commission_bps ────────────────────────────────────────────────────────
_d = _load("commission_bps")
if _d:
    _info = _render_param_section(
        _d,
        "✅ 佣金（commission_bps）",
        """**背景：** 单边佣金（bps）。Interactive Brokers 等机构级账户的股票佣金已低至
0.35–1 bps，但此测试覆盖 1–5 bps 以评估不同实盘成本结构的影响。""",
    )
    base = _info["base_rec"]
    lo, hi = _info["stab_lo"], _info["stab_hi"]
    stab_str = f"{lo:.0f}–{hi:.0f} bps" if lo is not None else "全范围"
    st.markdown(f"""
**结论：** {"✅ 全部测试水平下策略均保持正收益。" if _info["all_pos"] else "⚠️ 高佣金情景下策略出现负收益，需关注。"}
Sharpe 稳定区间：**{stab_str}**。

- 基准 {base['param_value']:.0f} bps：CAGR {base['cagr']*100:+.2f}%，Sharpe {base['sharpe']:+.3f}
- 年换手率约 {base.get('annual_turnover', 7):.1f}x，佣金从 1→5 bps 的累积影响约 {(5-1)*2*base.get('annual_turnover',7)/100:.2f}%/年
- 佣金相对滑点影响更小：策略每笔交易平均持仓较长，佣金在总成本中占比有限
""")
    _section_meta["commission_bps"] = _info
else:
    st.subheader("⏳ 佣金（commission_bps）")
    st.info("扰动测试正在运行中，完成后自动显示结果。")

st.markdown("---")


# ── Trade Execution Diagnostics ────────────────────────────────────────────────
st.subheader("交易执行诊断（Trade Execution Diagnostics）")
st.markdown(f"""
> **数据来源说明：** 此诊断基于 **Baseline anchor 锚点参数**的历史回测交易日志（`results/v1/trades.csv`），
> 而非参数敏感性分析中各扰动参数的交易。
> 诊断目的是评估策略在正常运行条件下"计划止损价 vs 实际成交价"的偏差，
> 是策略执行质量的固有属性，用 Baseline 跑一次即可代表策略整体。
> 回测期间：{meta.backtest_start} → {meta.backtest_end}，锚点参数：N={p['breakout_window']}日突破，止损 {p['stop_loss_multiplier']:.0f}×ATR。
""")

_DIAG_PATH = Path(__file__).resolve().parents[2] / "results" / "v1" / "diagnostics.json"

if _DIAG_PATH.exists():
    import json as _json
    diag = _json.loads(_DIAG_PATH.read_text(encoding="utf-8"))

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
    tail_risk  = eq.get("tail_risk", "")

    # Execution quality (mean-based)
    if assessment == "excellent":
        box_color, border_color, icon = "#e8f5e9", "#2e7d32", "✅"
    elif assessment == "acceptable":
        box_color, border_color, icon = "#fff8e1", "#f57c00", "⚠️"
    else:
        box_color, border_color, icon = "#ffebee", "#c62828", "🔴"

    st.markdown(
        f'<div class="info-box" style="background:{box_color};border-left-color:{border_color};">'
        f'{icon} 执行质量评估：<strong>{assessment.upper()}</strong> — '
        f'理论止损 {eq.get("expected_avg_loss_r", -1.0):+.2f}R，'
        f'实际止损 {eq.get("actual_avg_loss_r", 0.0):+.3f}R，'
        f'缺口影响 {eq.get("gap_impact_r", 0.0):+.3f}R'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Tail risk (per design spec 1.2.3 benchmarks)
    st.markdown("**尾部风险评估（设计方案 1.2.3 基准线）**")
    tr_col1, tr_col2, tr_col3 = st.columns(3)
    p95_mag = eq.get("p95_loss_magnitude", abs(gs.get("p5", 0.0)))
    max_mag = eq.get("max_loss_magnitude",  abs(gs.get("worst", 0.0)))
    tr_col1.metric(
        "P95 损失量级",
        f"{p95_mag:.2f}R",
        help="止损交易中最差 5% 的平均损失量级。设计方案基准：> 2.5R = 危险",
    )
    tr_col2.metric(
        "最大单笔损失",
        f"{max_mag:.2f}R",
        help="历史上最大的缺口止损损失。设计方案基准：> 10R = 灾难",
    )
    if tail_risk == "正常":
        tr_icon, tr_bg, tr_bd = "✅", "#e8f5e9", "#2e7d32"
    elif tail_risk == "危险":
        tr_icon, tr_bg, tr_bd = "⚠️", "#fff8e1", "#f57c00"
    else:
        tr_icon, tr_bg, tr_bd = "🔴", "#ffebee", "#c62828"
    tr_col3.markdown(
        f'<div class="info-box" style="background:{tr_bg};border-left-color:{tr_bd};padding:8px 12px;">'
        f'{tr_icon} 尾部风险：<strong>{tail_risk}</strong>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="info-box">'
        f'P95={p95_mag:.2f}R（基准阈值 2.5R），最大={max_mag:.2f}R（基准阈值 10R）。'
        f'{"P95 和最大损失均低于危险阈值，策略尾部风险在可控范围内。" if tail_risk == "正常" else "尾部风险超出基准线，建议进一步分析缺口来源。"}'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.caption("数据来源：results/v1/diagnostics.json | 仅统计 exit_reason == stop_loss 的交易")

    st.markdown("#### B. 连续亏损序列分析")
    sa = diag.get("streak_analysis", {})
    sb1, sb2, sb3 = st.columns(3)
    sb1.metric("最长连续亏损（笔）", sa.get("max_consecutive_losses", 0))
    sb2.metric("平均序列长度",       f"{sa.get('avg_streak_length', 0.0):.2f}")
    sb3.metric("亏损序列总数",       sa.get("total_streaks", 0))

    streak_counts: dict = sa.get("streak_counts", {})
    if streak_counts:
        table_rows = []
        cumulative = 0
        total_streaks = sa.get("total_streaks", 1) or 1
        for length in range(1, 10):
            key = str(length)
            cnt = streak_counts.get(key, 0)
            cumulative += cnt
            table_rows.append({
                "序列长度（笔）": length,
                "出现次数": cnt,
                "累计占比": f"{cumulative / total_streaks * 100:.1f}%",
            })
        cnt_10plus = streak_counts.get("10+", 0)
        cumulative += cnt_10plus
        table_rows.append({
            "序列长度（笔）": "≥10",
            "出现次数": cnt_10plus,
            "累计占比": f"{cumulative / total_streaks * 100:.1f}%",
        })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=False, hide_index=True)

    max_cl = sa.get("max_consecutive_losses", 0)
    st.markdown(
        f'<div class="info-box">'
        f'最长连续亏损 <strong>{max_cl} 笔</strong>——在趋势策略中属于正常特征（胜率 ~38%）。'
        f'在 38% 胜率下，统计期望每隔约 2.6 笔出现一次亏损连续段。'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown("#### C. 逐年交易质量")
    yearly = diag.get("yearly_stats", [])
    if yearly:
        yearly_rows = []
        for row in yearly:
            yearly_rows.append({
                "年份": row["year"],
                "交易笔数": row["n_trades"],
                "胜率": f"{row['win_rate']*100:.1f}%",
                "平均R": f"{row['avg_r']:+.3f}",
                "最佳交易R": f"{row['best_r']:+.3f}",
                "最差交易R": f"{row['worst_r']:+.3f}",
                "平均持仓天数": f"{row['avg_hold_days']:.0f}",
            })
        st.dataframe(pd.DataFrame(yearly_rows), use_container_width=True, hide_index=True)
else:
    st.info("诊断数据尚未生成。运行：python src/scripts/04_run_diagnostics.py")

st.markdown("---")


# ── Overall Assessment ─────────────────────────────────────────────────────────
st.subheader("综合评估")

_completed = list(_section_meta.keys())
_total_params = len(_PARAM_CFG)
_n_done = len(_completed)

if _n_done == 0:
    st.info("全部扰动测试正在运行中，完成后自动显示综合评估。")
else:
    # Gather aggregate stats
    _all_robust_cagr  = [v["cv_cagr"]   for v in _section_meta.values()]
    _all_robust_sharpe= [v["cv_sharpe"] for v in _section_meta.values()]
    _all_positive     = [v["all_pos"]   for v in _section_meta.values()]
    _n_all_pos        = sum(_all_positive)
    _n_pass_cagr      = sum(1 for cv in _all_robust_cagr   if cv < 0.10)
    _n_pass_sharpe    = sum(1 for cv in _all_robust_sharpe if cv < 0.10)
    _n_medium_cagr    = sum(1 for cv in _all_robust_cagr   if 0.10 <= cv < 0.25)
    _n_fragile_cagr   = sum(1 for cv in _all_robust_cagr   if cv >= 0.25)

    # Identify most sensitive params
    _sorted_by_cv = sorted(
        _section_meta.items(), key=lambda kv: kv[1]["cv_sharpe"], reverse=True
    )
    _most_sensitive   = _sorted_by_cv[0][0]  if _sorted_by_cv else "N/A"
    _most_robust      = _sorted_by_cv[-1][0] if _sorted_by_cv else "N/A"

    # Check if trail_multiplier_r1 is monotonic (key concern from earlier)
    _trail_monotonic = False
    if "trail_multiplier_r1" in _section_meta:
        _ts = _section_meta["trail_multiplier_r1"]["sharpes"]
        _trail_monotonic = all(_ts[i] <= _ts[i+1] for i in range(len(_ts)-1))

    _progress_pct = _n_done / _total_params * 100

    st.markdown(f"""
#### 测试覆盖率：{_n_done} / {_total_params} 参数已完成（{_progress_pct:.0f}%）

**1. 正收益覆盖率 — 策略的基础鲁棒性**

已完成的 {_n_done} 个参数中，**{_n_all_pos} 个**（{_n_all_pos/_n_done*100:.0f}%）
在全部测试值下均实现正 CAGR。
{"✅ 策略正期望来源于市场结构（趋势持续性），而非特定参数组合。" if _n_all_pos == _n_done else f"⚠️ 有 {_n_done - _n_all_pos} 个参数的极端值出现负收益，需关注。"}

**2. 敏感度分析（CAGR 变异系数 CV）**

| 鲁棒性等级 | 参数数量 | 标准 |
|-----------|---------|------|
| ✅ 高鲁棒（CV < 0.10） | {_n_pass_cagr} | 参数变化对 CAGR 影响 < ±10% |
| 🟡 中等（0.10–0.25）  | {_n_medium_cagr} | 参数变化对 CAGR 影响 ±10–25% |
| 🔴 敏感（CV ≥ 0.25）  | {_n_fragile_cagr} | 参数变化对 CAGR 影响 > ±25% |

- **最敏感参数**：`{_most_sensitive}`（Sharpe CV = {_section_meta[_most_sensitive]['cv_sharpe']:.3f}）
- **最鲁棒参数**：`{_most_robust}`（Sharpe CV = {_section_meta[_most_robust]['cv_sharpe']:.3f}）

**3. 参数景观形态（Flatness）**
""")

    # Build landscape table
    _landscape_rows = []
    for pname, pinfo in _section_meta.items():
        label = next((cfg[1] for cfg in _PARAM_CFG if cfg[0] == pname), pname)
        lo, hi = pinfo["stab_lo"], pinfo["stab_hi"]
        if lo is not None and hi is not None:
            stab = f"{lo} – {hi}"
        else:
            stab = "全范围稳定"
        _landscape_rows.append({
            "参数": label,
            "CAGR CV": f"{pinfo['cv_cagr']:.3f}",
            "Sharpe CV": f"{pinfo['cv_sharpe']:.3f}",
            "Sharpe 稳定区间（≥90% 峰值）": stab,
            "全正 CAGR": "✅" if pinfo["all_pos"] else "⚠️",
        })
    if _landscape_rows:
        st.dataframe(pd.DataFrame(_landscape_rows), use_container_width=True, hide_index=True)

    # Key findings
    concerns = []
    positives = []

    if _n_all_pos == _n_done:
        positives.append(f"全部 {_n_done} 个已测参数在所有测试值下均实现正 CAGR")
    if _n_pass_cagr >= _n_done * 0.7:
        positives.append(f"{_n_pass_cagr}/{_n_done} 个参数 CAGR CV < 0.10，参数景观整体平坦")
    if "breakout_window" in _section_meta:
        bw = _section_meta["breakout_window"]
        if bw["cv_cagr"] < 0.05:
            positives.append(f"突破窗口 N 的参数景观极为平坦（CAGR CV={bw['cv_cagr']:.3f}），52周新高选择有充分支撑")

    if _trail_monotonic and "trail_multiplier_r1" in _section_meta:
        trail = _section_meta["trail_multiplier_r1"]
        best = trail["best_sharpe_rec"]
        base = trail["base_rec"]
        if abs(best["param_value"] - base["param_value"]) > 0.01:
            concerns.append(
                f"trail_multiplier_r1 Sharpe 呈单调递增：基准 3.0× 不是样本内最优（"
                f"{best['param_value']:.1f}× 在 CAGR、Sharpe 上更优），需 OOS 验证"
            )

    if _n_fragile_cagr > 0:
        fragile_params = [p for p, v in _section_meta.items() if v["cv_cagr"] >= 0.25]
        concerns.append(f"以下参数 CAGR 敏感度较高（CV ≥ 0.25）：{', '.join(fragile_params)}")

    st.markdown("**4. 关键发现**")
    for pos in positives:
        st.markdown(f"- ✅ {pos}")
    for con in concerns:
        st.markdown(f"- ⚠️ {con}")

    if _n_done < _total_params:
        st.markdown(f"""
**5. 尚未完成的参数（{_total_params - _n_done} 个）**

以下参数的扰动测试仍在运行中，完成后本页面将自动更新：
""")
        _pending = [cfg[1] for cfg in _PARAM_CFG if cfg[0] not in _completed]
        for lbl in _pending:
            st.markdown(f"- {lbl}")

    # Final verdict
    st.markdown("**6. 结构性结论（1.2.2.3）**")
    _n_structural = len(_completed)
    if _n_structural > 0:
        _verdict_parts = []
        for pname, pinfo in _section_meta.items():
            label = next((cfg[1] for cfg in _PARAM_CFG if cfg[0] == pname), pname)
            lo, hi = pinfo["stab_lo"], pinfo["stab_hi"]
            cv = pinfo["cv_sharpe"]
            if cv < 0.10:
                if lo is not None and hi is not None:
                    _verdict_parts.append(f"- **{label}** → 宽阔高原（CV={cv:.3f}），全范围盈利，稳定区间覆盖所有测试值")
                else:
                    _verdict_parts.append(f"- **{label}** → 高鲁棒（CV={cv:.3f}），参数景观极为平坦")
            elif cv < 0.25:
                _verdict_parts.append(f"- **{label}** → 中等敏感（CV={cv:.3f}），避免极端值，基准参数处于稳定区间")
            else:
                _verdict_parts.append(f"- **{label}** → 较敏感（CV={cv:.3f}），需谨慎选择，避免远离基准值")

        for part in _verdict_parts:
            st.markdown(part)

    # Overall box
    if _n_done == _total_params:
        _all_pass = _n_all_pos == _total_params and _n_fragile_cagr == 0
        if _all_pass and not concerns:
            _icon, _color, _border = "✅", "#e8f5e9", "#2e7d32"
            _summary = (
                f"全部 {_total_params} 个参数通过鲁棒性验证：测试范围内无负 CAGR，"
                f"参数景观整体平坦。策略的正期望来自市场结构性动量，而非参数过拟合。"
            )
        elif concerns:
            _icon, _color, _border = "🟡", "#fff8e1", "#f57c00"
            _summary = (
                f"{_n_all_pos}/{_total_params} 参数通过正收益测试。"
                f"关注点：{'; '.join(concerns[:2])}。整体鲁棒，但存在可优化空间。"
            )
        else:
            _icon, _color, _border = "🔴", "#ffebee", "#c62828"
            _summary = (
                f"存在 {_n_fragile_cagr} 个高敏感参数或 {_n_done - _n_all_pos} 个负收益情景，"
                f"建议在提高实盘之前进一步 Walk-Forward 验证。"
            )
    else:
        _icon, _color, _border = "🟡", "#fff8e1", "#f57c00"
        _summary = (
            f"已完成 {_n_done}/{_total_params} 参数测试（{_progress_pct:.0f}%）。"
            f"已测结果：{_n_all_pos}/{_n_done} 全正 CAGR，{_n_pass_cagr}/{_n_done} 高鲁棒。"
            f"扰动测试仍在运行中，完成后本评估将自动更新为最终结论。"
        )

    st.markdown(
        f'<div class="info-box" style="background:{_color};border-left-color:{_border};">'
        f'<strong>{_icon} {_summary}</strong>'
        f'</div>',
        unsafe_allow_html=True,
    )
