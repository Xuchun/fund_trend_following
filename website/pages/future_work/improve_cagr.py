"""如何提高年化收益"""

import json
import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_results_path = _root / "results" / "v1_unbiased_60m_2000"
_perturb_path = _root / "results" / "v1_unbiased_60m_2000" / "perturbation"

st.title("如何提高年化收益（CAGR）")
st.caption("基于 Top 20 盈利交易分析，找到提升年化收益的核心杠杆点，同时保持甚至降低最大回撤")

st.markdown("---")

# ── 核心洞察 ──────────────────────────────────────────────────────────────────
st.subheader("一、核心发现：利润高度集中在少数大赢家")

st.markdown("""
**Top 20 盈利交易的关键数据：**

| 指标 | 数值 |
|------|------|
| 全部交易净盈亏 | $120.7M |
| Top 20 交易净盈亏 | $70.2M |
| **Top 20 占总利润比例** | **58.1%** |
| Top 20 平均 R 倍数 | 18.4R |
| Top 20 最大 R 倍数 | 38.3R（CIEN） |
| Top 20 平均持仓天数 | 239 天 |

**结论：策略的利润来自于"让趋势充分发展"**。绝大多数利润来自 261 笔 R > 3 的交易（占 3,337 笔总交易的 7.8%），
其中最顶端的 20 笔就贡献了超过一半的总利润。

提高 CAGR 的核心逻辑因此非常清晰：**让大赢家赢得更多、更久，而不是增加交易频次或调整止损。**
""")

# ── 大赢家规律图 ──────────────────────────────────────────────────────────────
st.subheader("二、大赢家的两个规律")

trades = pd.read_csv(_results_path / "trades.csv", parse_dates=["entry_date", "exit_date"])
trades["holding_days"] = (trades["exit_date"] - trades["entry_date"]).dt.days

# 散点图：持仓天数 vs R倍数（R > 2 的交易）
big = trades[trades["pnl_r_multiple"] > 2].copy()
big["year"] = big["entry_date"].dt.year

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=big["holding_days"],
    y=big["pnl_r_multiple"],
    mode="markers",
    marker=dict(
        color=big["year"],
        colorscale="Viridis",
        size=7,
        opacity=0.6,
        colorbar=dict(title="入场年份"),
    ),
    text=big["ticker"],
    hovertemplate="<b>%{text}</b><br>持仓: %{x} 天<br>R 倍数: %{y:.1f}R<extra></extra>",
))
fig.update_layout(
    title="R > 2 的盈利交易：持仓天数 vs R 倍数",
    xaxis_title="持仓天数",
    yaxis_title="R 倍数",
    height=420,
    template="plotly_white",
)
st.plotly_chart(fig, use_container_width=True)

st.markdown("""
**规律 1：持仓时间越长，R 倍数越高。**

持仓超过 200 天的 53 笔交易平均 R 达到 **10.8R**，合计贡献总利润的 **41%**。
移动止盈的设计使策略天然"让利润奔跑"——这是当前策略结构的核心优势。

**规律 2：大赢家分布在不同年份，与牛熊市无关。**

20 笔大赢家覆盖 2003、2004、2010、2012、2013、2016、2019、2020、2021、2023、2024、2025、2026 年，
说明策略在各种市场环境都能找到优质趋势，CAGR 不依赖于特定牛市周期。
""")

st.markdown("---")

# ── 建议 1：金字塔加仓 ────────────────────────────────────────────────────────
st.subheader("建议 1：金字塔加仓（最高优先级）")
st.markdown("""
**预期效果：年化收益从 10.36% 提升至约 15%，粗估额外利润 +$61.6M（+51%）；最大回撤预期中度增加（约 -22% 至 -25%，vs 当前 -20.74%）**

当前策略仅在入场时开一次仓（最大 5% NAV），此后不再追加。但 Top 20 大赢家的特征是：
突破后持续强势运行 6–18 个月，中途回调幅度有限。这意味着有大量"经过验证的趋势"机会
被当前的固定仓位机制浪费了。

**核心逻辑：**

在趋势已经被市场验证（仓位达到 3R 浮盈）之后，风险已大幅降低，此时加仓的期望值远高于新入场。
""")

st.code("""
# 金字塔加仓规则（伪代码）
PYRAMID_TRIGGER_R  = 3.0    # 浮盈达到 3R 时触发加仓
PYRAMID_ADD_SIZE   = 0.5    # 加仓规模 = 原始仓位的 50%（或原始 risk 的 50%）
PYRAMID_MAX_ADDS   = 2      # 最多加仓 2 次

for position in open_positions:
    r_current = position.unrealized_r
    if r_current >= PYRAMID_TRIGGER_R * (position.add_count + 1):
        if position.add_count < PYRAMID_MAX_ADDS:
            new_shares = position.original_shares * PYRAMID_ADD_SIZE
            add_to_position(position, shares=new_shares, reason="pyramid")
            position.add_count += 1
            # 新加仓的止损 = 当前移动止损线（而非原始止损价）
            position.stop_price = current_trailing_stop
""", language="python")

# 量化估算
st.info("""
**粗估计算逻辑：**

全部 261 笔 R > 3 的交易，假设在 3R 时追加原始仓位的 50%，
这笔额外仓位能获得的收益约为：`初始风险 × (最终R - 3) × 0.5`

用历史数据计算：额外利润约 **$61.6M**，相当于当前总利润的 **51%**。

若 CAGR 的增速与利润增速大致同步，粗估 CAGR 从 10.36% 提升至 **约 14-16%**。

（实际效果需完整回测验证；加仓也会增加单笔持仓规模，回撤可能同步扩大）
""")

st.markdown("""
**风险控制关键点：**
- 加仓后总仓位上限不超过初始 position_cap 的 2 倍（即不超过 NAV 的 10%）
- 加仓止损设在当前移动止损线，而非原始入场止损，避免大幅回吐浮盈
- 每笔交易最多加仓 2 次，防止持仓过度集中

> 详见单独页面：**加仓机制（金字塔）**（Future Work 分组）
""")

# Chart: Pyramid gain by R bucket
_big = trades[trades["pnl_r_multiple"] >= 3.0].copy()
_big["initial_risk"] = _big["net_pnl"] / _big["pnl_r_multiple"]
_big["pyramid_gain"] = (_big["pnl_r_multiple"] - 3.0) * 0.5 * _big["initial_risk"]

_r_buckets = [(3, 5), (5, 10), (10, 15), (15, 20), (20, 30), (30, 99)]
_r_labels  = ["3-5R", "5-10R", "10-15R", "15-20R", "20-30R", "30R+"]
_r_current, _r_pyramid = [], []
for lo, hi in _r_buckets:
    sub = _big[(_big["pnl_r_multiple"] >= lo) & (_big["pnl_r_multiple"] < hi)]
    _r_current.append(sub["net_pnl"].sum() / 1e6)
    _r_pyramid.append(sub["pyramid_gain"].sum() / 1e6)

_fig_pyra = go.Figure()
_fig_pyra.add_trace(go.Bar(x=_r_labels, y=_r_current, name="当前利润（$M）", marker_color="#22c55e"))
_fig_pyra.add_trace(go.Bar(x=_r_labels, y=_r_pyramid, name="金字塔加仓额外利润（$M）", marker_color="#86efac"))
_fig_pyra.update_layout(
    barmode="stack",
    title=f"金字塔加仓潜在额外利润（R>3 的 {len(_big)} 笔交易，在 3R 时追加 50%）",
    xaxis_title="R 倍数区间",
    yaxis_title="利润（$M）",
    height=380,
    legend=dict(x=0.55, y=0.95),
    margin=dict(t=50, b=40),
)
st.plotly_chart(_fig_pyra, use_container_width=True)
st.caption(
    f"R>3 的 {len(_big)} 笔交易当前利润共 ${_big['net_pnl'].sum()/1e6:.1f}M；"
    f"若在 3R 时追加 50% 仓位，额外利润约 ${_big['pyramid_gain'].sum()/1e6:.1f}M（+{_big['pyramid_gain'].sum()/_big['net_pnl'].sum()*100:.0f}%）。"
    "高 R 区间（>10R）是金字塔加仓的主要受益来源，因为剩余利润空间最大。"
)

st.markdown("---")

# ── 建议 2：放宽大赢家的移动止盈 ───────────────────────────────────────────────
st.subheader("建议 2：对大赢家放宽移动止盈倍数")
st.markdown("""
**预期效果：CAGR 约 +1–2%，最大回撤影响中性**

当前策略的移动止盈倍数分档：

| 持仓阶段 | 移动止盈倍数 |
|---------|------------|
| 初始入场 | 2× ATR |
| 达到 1R 浮盈 | 3× ATR |
| 达到 3R 浮盈 | 5× ATR（`trail_multiplier_r5`） |

问题：一旦仓位达到 10R、20R 乃至 38R 的极高盈利水平，5× ATR 的止损在绝对金额上已非常大，
但在波动率高的行情中（如 CIEN 2025、APP 2024），这个倍数可能仍然过紧，导致过早离场。

**改进方案：增加第四档，给 >10R 的大赢家更多呼吸空间：**
""")

st.code("""
# 在现有三档基础上增加第四档
TRAIL_MULTIPLIER_R1  = 3.0   # 达到 1R 时：止损放宽至 3× ATR
TRAIL_MULTIPLIER_R3  = 5.0   # 达到 3R 时：止损放宽至 5× ATR
TRAIL_MULTIPLIER_R10 = 7.0   # 达到 10R 时：止损放宽至 7× ATR  ← 新增

def get_trail_multiplier(unrealized_r):
    if unrealized_r >= 10:
        return TRAIL_MULTIPLIER_R10
    elif unrealized_r >= 3:
        return TRAIL_MULTIPLIER_R3
    elif unrealized_r >= 1:
        return TRAIL_MULTIPLIER_R1
    else:
        return TRAIL_INITIAL  # 初始 2× ATR
""", language="python")

st.markdown("""
**为什么不会增加大回撤：**

第四档只对已有 10R+ 浮盈的仓位生效。即便止损从 5× ATR 放宽到 7× ATR，
在浮盈如此大的情况下，整体最大回撤也不会受到明显影响——因为这些仓位本身已经
距入场价极远，止损线远高于成本。

**CIEN 案例验证：** CIEN 持仓 278 天，最终达到 38.3R。
若移动止盈更宽松，理论上可以在 2025 年 CIEN 的中途震荡中保住仓位更长时间，
潜在额外盈利可观。
""")

# Chart: Trail multiplier sensitivity
_trail_f = _perturb_path / "trail_multiplier_r1.json"
if _trail_f.exists():
    _td = json.loads(_trail_f.read_text())
    _tv  = _td["param_values"]
    _tc  = [r["cagr"] * 100 for r in _td["results"]]
    _tm  = [abs(r["max_drawdown"]) * 100 for r in _td["results"]]
    _fig_trail = go.Figure()
    _fig_trail.add_trace(go.Bar(
        x=[str(v) for v in _tv], y=_tc, name="CAGR (%)", marker_color="#6366f1", yaxis="y",
    ))
    _fig_trail.add_trace(go.Scatter(
        x=[str(v) for v in _tv], y=_tm, name="最大回撤（%，右轴）",
        mode="lines+markers", marker=dict(size=9, color="#ef4444"),
        line=dict(color="#ef4444", width=2), yaxis="y2",
    ))
    _fig_trail.update_layout(
        title="移动止盈乘数（trail_multiplier_r1）敏感性：CAGR vs MaxDD",
        xaxis_title="trail_multiplier（× ATR，1R→3R 阶段）",
        yaxis=dict(title="CAGR (%)", side="left", range=[8.5, 11.5]),
        yaxis2=dict(title="最大回撤（%）", side="right", overlaying="y", range=[18, 23]),
        legend=dict(x=0.6, y=0.05), height=360, margin=dict(t=50, b=40),
    )
    st.plotly_chart(_fig_trail, use_container_width=True)
    st.caption(
        "当前 trail_multiplier_r1 = 3.0（1R→3R 阶段）已是 CAGR 最优点（10.36%）。"
        "建议 2 针对的是 >10R 阶段新增第四档（trail_multiplier_r10 = 7.0×），"
        "现有敏感性分析未覆盖此参数，需单独回测验证。"
    )

st.markdown("---")

# ── 建议 3：大赢家不受相关性减仓影响 ─────────────────────────────────────────────
st.subheader("建议 3：已盈利仓位不做相关性减仓")
st.markdown("""
**预期效果：CAGR 约 +0.5–1%，回撤影响中性偏正**

当前策略：在开新仓时，若新标的与已有持仓相关性 > 0.7，则将新仓位压缩至 50%。
这是为了防止持仓过度集中于同一板块或因子。

**问题：** 相关性过滤的逻辑不应逆向作用于已有的盈利仓位。当前逻辑可能在以下场景造成损失：

> 持仓 A 已达 5R，此时信号触发开仓 B（与 A 高度相关）。
> 策略将 B 的仓位压缩至 50%——**这是对的**，B 是新仓位，风险敞口应该小一些。
> 但若同时存在"持仓 A 也被反向压缩规模"的逻辑，则会错误减少已验证的大赢家仓位。

**建议：明确保护已盈利仓位，不让其因新信号的相关性而被减仓：**
""")

st.code("""
# 相关性过滤只对新开仓生效，已有仓位不受影响
for new_signal in today_signals:
    correlation_with_portfolio = compute_correlation(new_signal.ticker, open_positions)
    if correlation_with_portfolio > CORR_THRESHOLD:
        new_signal.shares *= 0.5  # 压缩新仓位
    # ✅ 已有 open_positions 的规模不做任何调整
    # （原来如果存在相关性惩罚对已持仓也生效，需要去除）
""", language="python")

# Chart: Correlation threshold sensitivity
_corr_f = _perturb_path / "correlation_threshold.json"
if _corr_f.exists():
    _cd = json.loads(_corr_f.read_text())
    _cv  = _cd["param_values"]
    _cc  = [r["cagr"] * 100 for r in _cd["results"]]
    _cm  = [abs(r["max_drawdown"]) * 100 for r in _cd["results"]]
    _cn  = [r["n_trades"] for r in _cd["results"]]
    _baseline_corr = _cd["baseline_value"]
    _fig_corr = go.Figure()
    _fig_corr.add_trace(go.Bar(
        x=[str(v) for v in _cv], y=_cc, name="CAGR (%)",
        marker_color=["#22c55e" if v == _baseline_corr else "#6366f1" for v in _cv],
        yaxis="y",
    ))
    _fig_corr.add_trace(go.Scatter(
        x=[str(v) for v in _cv], y=_cm, name="最大回撤（%，右轴）",
        mode="lines+markers", marker=dict(size=9, color="#ef4444"),
        line=dict(color="#ef4444", width=2), yaxis="y2",
    ))
    _fig_corr.update_layout(
        title="相关性阈值（correlation_threshold）敏感性：CAGR vs MaxDD",
        xaxis_title="相关性阈值",
        yaxis=dict(title="CAGR (%)", side="left", range=[7, 11.5]),
        yaxis2=dict(title="最大回撤（%）", side="right", overlaying="y", range=[15, 26]),
        legend=dict(x=0.5, y=0.05), height=360, margin=dict(t=50, b=40),
    )
    st.plotly_chart(_fig_corr, use_container_width=True)
    st.caption(
        f"当前 correlation_threshold = {_baseline_corr}（绿色）。"
        f"更严格的阈值（0.5）大幅增加交易笔数（{_cn[0]:.0f}），MaxDD 升至 {_cm[0]:.1f}%，CAGR 反而降至 {_cc[0]:.2f}%。"
        "说明过度扩展信号数量会摊薄质量；维持当前阈值是合理的，但需保护好已有盈利仓位的规模。"
    )

st.markdown("---")

# ── 建议 4：突破强度过滤 ──────────────────────────────────────────────────────────
st.subheader("建议 4：引入突破强度过滤，提升大赢家比例")
st.markdown("""
**预期效果：CAGR 约 +0.5–1.5%，同时降低最大回撤**

当前参数：`breakout_strength_min = 0`（不过滤突破强度，任何突破都参与）

**问题：** 低质量突破（价格刚好触及 200 日高点，但成交量不足、ATR 过低）更容易形成假突破，
成为连续亏损的来源。过滤这类交易，可以：

1. 提高整体胜率（38.7% → 42-45%）
2. 减少入场交易总数，降低资金摩擦
3. 资金集中到真正高质量的突破机会，从而提高 Top 20 贡献占比

**突破强度的衡量维度：**
""")

col1, col2 = st.columns(2)
with col1:
    st.markdown("""
**量价维度**
- 突破当日成交量 ≥ 20 日均量的 1.5 倍
- 突破幅度（收盘价 / 200 日高点 - 1）≥ 0.5%
- 突破当日实体（close - open）> 0（阳线突破）
""")
with col2:
    st.markdown("""
**动量维度**
- 突破前 20 日内已有 ≥ 3 天超量上涨
- 过去 60 日 RS（相对强度）排名在全市场前 30%
- ATR 处于历史 30-70% 分位（避免过高波动的假突破）
""")

st.code("""
# 突破强度过滤器（示例：量价双重验证）
MIN_VOLUME_RATIO  = 1.5   # 突破当日成交量 / 20日均量
MIN_BREAKOUT_PCT  = 0.005 # 收盘价超过 200日高点至少 0.5%

def is_valid_breakout(bar):
    vol_ratio = bar["volume"] / bar["volume_ma20"]
    breakout_pct = (bar["close"] / bar["high_200d"]) - 1
    is_up_candle = bar["close"] > bar["open"]
    return (
        vol_ratio >= MIN_VOLUME_RATIO
        and breakout_pct >= MIN_BREAKOUT_PCT
        and is_up_candle
    )
""", language="python")

st.markdown("""
**与连续亏损的关系：** 突破质量过滤同时也是减少连续亏损的核心建议之一。
提高入场质量，既能提升 CAGR，又能降低亏损交易密度，一举两得。

> 详见页面：**如何降低连续亏损次数** — 建议 2（突破强度过滤）
""")

# Chart: Volume filter multiplier as proxy for breakout strength
_volf = _perturb_path / "volume_filter_multiplier.json"
if _volf.exists():
    _vd = json.loads(_volf.read_text())
    _vv  = _vd["param_values"]
    _vc  = [r["cagr"] * 100 for r in _vd["results"]]
    _vm  = [abs(r["max_drawdown"]) * 100 for r in _vd["results"]]
    _vn  = [r["n_trades"] for r in _vd["results"]]
    _baseline_v = _vd["baseline_value"]
    _fig_vol = go.Figure()
    _fig_vol.add_trace(go.Bar(
        x=[str(v) for v in _vv], y=_vc, name="CAGR (%)",
        marker_color=["#22c55e" if v == _baseline_v else "#6366f1" for v in _vv],
        yaxis="y",
    ))
    _fig_vol.add_trace(go.Scatter(
        x=[str(v) for v in _vv], y=_vn, name="交易笔数（右轴）",
        mode="lines+markers", marker=dict(size=9, color="#94a3b8"),
        line=dict(color="#94a3b8", width=2), yaxis="y2",
    ))
    _fig_vol.update_layout(
        title="成交量过滤倍数（volume_filter_multiplier）敏感性：CAGR vs 交易笔数",
        xaxis_title="volume_filter_multiplier（× 均量）",
        yaxis=dict(title="CAGR (%)", side="left", range=[7, 11.5]),
        yaxis2=dict(title="交易笔数", side="right", overlaying="y"),
        legend=dict(x=0.6, y=0.05), height=360, margin=dict(t=50, b=40),
    )
    st.plotly_chart(_fig_vol, use_container_width=True)
    best_vidx = _vc.index(max(_vc))
    st.caption(
        f"当前 volume_filter_multiplier = {_baseline_v}（绿色），CAGR = {_vc[_vv.index(_baseline_v)]:.2f}%。"
        f"成交量要求过高（2.0×）使交易笔数从 3,337 降至 {_vn[-1]:.0f}，CAGR 反降至 {_vc[-1]:.2f}%。"
        "说明成交量过滤存在最优点，过度过滤会遗漏真实突破。"
    )

st.markdown("---")

# ── 效益评估汇总 ──────────────────────────────────────────────────────────────
st.subheader("综合效益评估")

st.markdown("""
| 建议 | 预期 CAGR 提升 | 对最大回撤的影响 | 实现难度 | 建议优先级 |
|------|--------------|---------------|---------|----------|
| **建议 1：金字塔加仓** | 约 +4–5%（历史估算） | 中度增加（仓位增大） | ★★★ 高 | 🔴 最高 |
| **建议 2：放宽大赢家移动止盈** | 约 +1–2% | 中性（只影响 >10R 仓位） | ★ 低 | 🔴 高 |
| **建议 4：突破质量过滤** | 约 +0.5–1.5% | 降低（减少假突破亏损） | ★★ 中 | 🟡 高 |
| **建议 3：大赢家不做相关性减仓** | 约 +0.5–1% | 中性 | ★ 低 | 🟡 中 |

**粗估组合效果（保守）：**
""")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("当前 CAGR", "10.36%")
with col2:
    st.metric("仅建议 1+2", "~13–15%", "+3–5%")
with col3:
    st.metric("全部建议组合", "~14–16%", "+4–6%")

col1b, col2b, col3b = st.columns(3)
with col1b:
    st.metric("当前最大回撤", "-20.74%")
with col2b:
    st.metric("仅建议 1+2", "~-22% 至 -25%", "-1% 至 -4%",
              delta_color="inverse",
              help="建议1（金字塔加仓）使持仓规模扩大，趋势反转时回撤幅度中度增加；建议2（宽松移动止盈）对>10R仓位影响中性")
with col3b:
    st.metric("全部建议组合", "~-20% 至 -23%", "0% 至 -2%",
              delta_color="inverse",
              help="建议4（突破质量过滤）减少假突破亏损，部分抵消金字塔加仓对回撤的负面影响；净效果：最大回撤与当前大体相当或略有增加")

st.caption("最大回撤预估说明：金字塔加仓在趋势反转时会使亏损规模同步扩大（加仓止损设在移动止盈线，但绝对金额更大）。突破质量过滤（建议4）能减少假突破引发的连续小亏损，部分抵消回撤扩大效果。以上均为粗估，需完整回测验证。")

st.markdown("---")

st.subheader("推荐实施路径")
st.markdown("""
**第一步（立即可做，低风险）：**
- 实现建议 2（trail_multiplier_r10 = 7× ATR）并在历史数据上重新回测
- 代码改动量极小，仅修改 `src/strategy/v1/exit.py` 中的移动止盈档位
- 预期可提升 CAGR 1–2%，回撤影响中性

**第二步（中期，需要完整回测）：**
- 实现建议 4（突破强度过滤），先从量价双重验证开始
- 做参数敏感性分析：`min_volume_ratio` 从 1.2 到 2.0 扫描
- 预期同时提升 CAGR 和降低回撤

**第三步（高影响，需要谨慎验证）：**
- 实现建议 1（金字塔加仓）
- 这是影响最大的改进，但也最复杂：需要处理仓位上限、相关性约束、资金分配逻辑
- 建议先在小参数范围回测，逐步放开

**重要提醒：**
""")

st.warning("""
以上所有建议都是基于 **20 笔交易** 的模式归纳，存在过度拟合历史的风险。

正确的验证流程：
1. 先修改参数，在 **2000-01-01 → 2015-12-31** 的数据上训练/优化
2. 在 **2016-01-01 → 2026-06-15** 的 Walk-Forward 数据上验证
3. 只有在 OOS 数据上同样表现更优，才能确认该改进真实有效
""")
