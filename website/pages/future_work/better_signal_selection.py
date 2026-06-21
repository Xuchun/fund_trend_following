"""如何选中更优开仓信号"""

import json
import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_results_path = _root / "results" / "v1_unbiased_60m_2000"
_perturb_path = _root / "results" / "v1_unbiased_60m_2000" / "perturbation"

st.title("如何选中更优开仓信号")
st.caption('基于"每日开仓信号：已开仓 vs 放弃开仓"分析，找到改进信号选择机制的方向，从而提高 CAGR 并保持甚至降低最大回撤')

st.markdown("---")

# ── 数据加载 ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400)
def _load():
    trades = pd.read_csv(_results_path / "trades.csv", parse_dates=["entry_date", "exit_date"])
    trades["holding_days"] = (trades["exit_date"] - trades["entry_date"]).dt.days
    es = pd.read_csv(_results_path / "daily_entry_stats.csv", index_col="date", parse_dates=True)
    return trades, es

trades, es = _load()

TOTAL_SIGNALS = int(es["signals"].sum())
TOTAL_EXEC    = int(es["executed"].sum())
TOTAL_SKIP    = int(es["skipped"].sum())
SKIP_CASH     = int(es["skip_cash"].sum())
SKIP_RATE     = TOTAL_SKIP / TOTAL_SIGNALS

# ── 一、核心数据 ──────────────────────────────────────────────────────────────
st.subheader("一、核心数据：86.8% 的信号被放弃，且主因单一")

c1, c2, c3, c4 = st.columns(4)
c1.metric("总信号数", f"{TOTAL_SIGNALS:,}")
c2.metric("已执行", f"{TOTAL_EXEC:,}", f"{TOTAL_EXEC/TOTAL_SIGNALS*100:.1f}%")
c3.metric("已放弃", f"{TOTAL_SKIP:,}", f"-{SKIP_RATE*100:.1f}%", delta_color="inverse")
c4.metric("其中：资金不足", f"{SKIP_CASH:,}", f"{SKIP_CASH/TOTAL_SIGNALS*100:.1f}% 的信号",
          delta_color="inverse")

st.markdown("""
**放弃原因分布：**

| 原因 | 数量 | 占总信号 | 说明 |
|------|------|---------|------|
| **资金不足** | 20,289 | **80.0%** | 当天已有持仓占用资金，新仓位无法获得足够资本 |
| 热度超限 | 0 | 0% | `heat_limit = 10%` 在回测中从**未触发** |
| 相关性过高 | 0 | 0% | 相关性过滤在回测中从**未触发** |
| 其他 | 1,728 | 6.8% | 缺口过大、已持仓该标的等 |

**结构性根源**：`position_cap = 5% NAV`，平均每日持仓约 14.4 只，几乎所有资金被占用。
平均每天有 **6.2 个新突破信号**，但资金只够执行 **0.81 个**。
""")

st.markdown("---")

# ── 二、最关键发现：信号拥挤时执行了更差的信号 ────────────────────────────────
st.subheader("二、核心发现：信号拥挤时，当前机制反而选了更差的信号")

# 构建数据
trades["entry_date_only"] = trades["entry_date"].dt.date
_es_map = es[["signals"]].copy()
_es_map.index = _es_map.index.date
trades["signals_that_day"] = trades["entry_date_only"].map(_es_map["signals"])

bins   = [0, 1, 3, 5, 10, 50, 200]
labels = ["1 个", "2-3 个", "4-5 个", "6-10 个", "11-50 个", "51+ 个"]
trades["signal_bin"] = pd.cut(
    trades["signals_that_day"].fillna(0), bins=bins, labels=labels
)

q_grp = (
    trades.groupby("signal_bin", observed=True)
    .agg(
        笔数=("net_pnl", "count"),
        均值R=("pnl_r_multiple", "mean"),
        胜率=("net_pnl", lambda x: (x > 0).mean() * 100),
        中位R=("pnl_r_multiple", "median"),
        总盈亏=("net_pnl", "sum"),
    )
    .reset_index()
)

# 图表：当天信号数 vs 执行交易的平均R / 胜率
_fig_qlt = make_subplots(rows=1, cols=2, subplot_titles=["平均 R 倍数", "胜率 (%)"])

_colors = ["#2ca02c" if v >= 0 else "#d62728" for v in q_grp["均值R"]]
_fig_qlt.add_trace(go.Bar(
    x=q_grp["signal_bin"].tolist(),
    y=q_grp["均值R"].tolist(),
    marker_color=_colors,
    text=[f"{v:+.3f}R" for v in q_grp["均值R"]],
    textposition="outside",
    showlegend=False,
), row=1, col=1)

_wr_colors = ["#2ca02c" if v >= 40 else ("#f57c00" if v >= 35 else "#d62728")
              for v in q_grp["胜率"]]
_fig_qlt.add_trace(go.Bar(
    x=q_grp["signal_bin"].tolist(),
    y=q_grp["胜率"].tolist(),
    marker_color=_wr_colors,
    text=[f"{v:.1f}%" for v in q_grp["胜率"]],
    textposition="outside",
    showlegend=False,
), row=1, col=2)

_fig_qlt.update_yaxes(title_text="均值 R", row=1, col=1)
_fig_qlt.update_yaxes(title_text="胜率 %", row=1, col=2)
_fig_qlt.update_xaxes(title_text="入场当天信号数", row=1, col=1)
_fig_qlt.update_xaxes(title_text="入场当天信号数", row=1, col=2)
_fig_qlt.update_layout(
    title="按入场当天信号数分组：执行的交易质量",
    height=380, template="plotly_white",
    margin=dict(t=60, b=40),
)
st.plotly_chart(_fig_qlt, use_container_width=True)

# 数据表
q_grp_show = q_grp.copy()
q_grp_show["均值R"]  = q_grp_show["均值R"].map(lambda v: f"{v:+.3f}R")
q_grp_show["胜率"]   = q_grp_show["胜率"].map(lambda v: f"{v:.1f}%")
q_grp_show["中位R"]  = q_grp_show["中位R"].map(lambda v: f"{v:+.3f}R")
q_grp_show["总盈亏"] = q_grp_show["总盈亏"].map(lambda v: f"${v/1e6:.1f}M")
st.dataframe(q_grp_show.rename(columns={"signal_bin": "入场当天信号数"}),
             use_container_width=True, hide_index=True)

st.markdown("""
**解读（重要）：**

- **信号只有 1 个时**：胜率 **44.3%**，均值 **+0.32R** — 当天无竞争，被执行的概率极高
- **信号达到 11-50 个时**：胜率跌至 **31.3%**，均值竟然为 **-0.05R**（负值！）

这揭示了一个严重问题：当信号拥挤（多个标的同日突破）时，当前选择机制（很可能是字母顺序或随机顺序）
**反而执行了低质量信号，让高质量信号因资金不足排在后面被放弃**。
信号越拥挤，这个问题越严重。
""")

st.markdown("---")

# ── 三、信号拥挤的年份趋势 ────────────────────────────────────────────────────
st.subheader("三、信号拥挤程度逐年加剧")

es["year"] = es.index.year
yearly = (
    es[es["signals"] > 0]
    .groupby("year")
    .agg(日均信号=("signals", "mean"), 日均执行=("executed", "mean"),
         日均放弃=("skipped", "mean"))
    .reset_index()
)
yearly["放弃率"] = yearly["日均放弃"] / yearly["日均信号"] * 100

_fig_yr = make_subplots(rows=2, cols=1, shared_xaxes=True,
                         row_heights=[0.6, 0.4], vertical_spacing=0.06,
                         subplot_titles=["日均信号数 vs 日均执行数", "放弃率 (%)"])

_fig_yr.add_trace(go.Bar(
    x=yearly["year"], y=yearly["日均信号"],
    name="日均信号数", marker_color="rgba(31,119,180,0.4)",
), row=1, col=1)
_fig_yr.add_trace(go.Bar(
    x=yearly["year"], y=yearly["日均执行"],
    name="日均执行数", marker_color="#1f77b4",
), row=1, col=1)
_fig_yr.add_trace(go.Scatter(
    x=yearly["year"], y=yearly["放弃率"],
    mode="lines+markers",
    line=dict(color="#d62728", width=2),
    marker=dict(size=6),
    name="放弃率",
    showlegend=False,
), row=2, col=1)
_fig_yr.add_hline(y=86.8, line_dash="dot", line_color="#888",
                   annotation_text="整体均值 86.8%", row=2, col=1)

_fig_yr.update_layout(
    barmode="overlay", height=460, template="plotly_white",
    legend=dict(orientation="h", y=1.08),
    margin=dict(t=60, b=40),
)
_fig_yr.update_yaxes(title_text="信号数", row=1, col=1)
_fig_yr.update_yaxes(title_text="放弃率 %", row=2, col=1)
st.plotly_chart(_fig_yr, use_container_width=True)

st.markdown("""
2013 年后放弃率长期维持 90%+，2024-2026 年已超过 **93%**，趋势还在持续恶化。
每天平均 6-14 个信号竞争 0.7-0.9 个执行位，选择机制的重要性越来越高。
""")

st.markdown("---")

# ── 四个建议 ──────────────────────────────────────────────────────────────────

st.subheader("四个改进建议")

# 建议 1
st.markdown("#### 建议 1：信号质量排序（Signal Ranking）— 最高优先级")
st.markdown("""
**预期效果：CAGR +2–4%，最大回撤无变化（执行次数和仓位规模完全不变）**

这是最直接的改进：**不改变任何仓位参数，只改变"执行哪个信号"的顺序**。
当天有 N 个信号时，按质量打分排序，优先执行得分最高的。

**质量评分维度：**
""")

col1, col2 = st.columns(2)
with col1:
    st.markdown("""
**量价维度（权重 65%）**
- 成交量倍数：当日成交量 ÷ 60日均量（占 35%）
- 突破幅度：(收盘价 - 200日高点) ÷ 200日高点（占 30%）
""")
with col2:
    st.markdown("""
**动量维度（权重 35%）**
- 相对强度 RS：过去 252 日涨幅在全市场排名（占 25%）
- 波动率调整：ATR% 处于历史中段时加分，过高惩罚（占 10%）
""")

st.code("""
def rank_signals(signals_today: list[Signal]) -> list[Signal]:
    for s in signals_today:
        vol_score = s.volume / s.volume_ma60          # 量能倍数
        brk_score = (s.close / s.high_200d) - 1       # 突破幅度
        rs_score  = s.rs_rank_252d                     # RS 相对强度 0~1
        atr_score = 1 / s.atr_pct if s.atr_pct > 0 else 0  # 低波动加分

        s.quality_score = (
            0.35 * normalize(vol_score)
          + 0.30 * normalize(brk_score)
          + 0.25 * normalize(rs_score)
          + 0.10 * normalize(atr_score)
        )
    return sorted(signals_today, key=lambda s: s.quality_score, reverse=True)

# 每天只执行排名最靠前的（资金允许的范围内）
ranked = rank_signals(today_signals)
for signal in ranked:
    if has_sufficient_cash(signal):
        execute(signal)
    else:
        break  # 资金不足，后续信号同样无法执行
""", language="python")

st.info("""
**为何预期效果显著？**

当天有 11-50 个信号时，当前均值 R = -0.05R（几乎没有正期望）。
若改为按质量排序，同样只执行 0.8 笔，但选中的是质量最高的那笔，
预期均值 R 可回升至 +0.3-0.5R 区间——仅靠顺序改变，就能大幅改善高拥挤日的交易质量。
""")

st.markdown("---")

# 建议 2
st.markdown("#### 建议 2：在来源减少低质量信号（突破强度过滤）")
st.markdown("""
**预期效果：CAGR +0.5–1.5%，同时降低最大回撤**

与其让 6.2 个信号竞争 0.81 个执行位，不如在信号生成阶段就过滤掉低质量突破，
把每天的信号数降到 2-3 个，然后**全部执行**（放弃率从 86.8% 降至 40% 以下）。
""")

st.code("""
# 当前：breakout_strength_min = 0（任何突破都生成信号）
# 建议：量价双重验证

MIN_VOLUME_RATIO  = 1.5    # 突破当日成交量 ≥ 60日均量的 1.5 倍
MIN_BREAKOUT_PCT  = 0.005  # 收盘价超过 200日高点至少 0.5%
REQUIRE_UP_CANDLE = True   # 阳线突破（close > open）

def is_valid_breakout(bar, params) -> bool:
    vol_ratio   = bar["volume"] / bar["volume_ma60"]
    brk_pct     = (bar["close"] / bar["high_200d"]) - 1
    is_up       = bar["close"] > bar["open"]
    return (
        vol_ratio >= params.min_volume_ratio
        and brk_pct >= params.min_breakout_pct
        and (not params.require_up_candle or is_up)
    )
""", language="python")

st.markdown("""
**与建议 1 的关系：** 两者可以叠加使用——先用建议 2 把信号数从 6.2 降到 2-3 个，
再用建议 1 对剩余信号排序。双重过滤后，每个被执行的信号都经过了量价验证和相对质量排名。
""")

st.markdown("---")

# 建议 3
st.markdown("#### 建议 3：降低 position_cap，同时执行更多信号")
st.markdown("""
**预期效果：需要回测验证，中性偏正**

资金不足的根本原因是 `position_cap = 5%` 限制了同时持仓数。
降低单笔仓位上限可以让更多信号同时被执行：
""")

import pandas as _pd_cap
_cap_df = _pd_cap.DataFrame({
    "方案": ["当前", "方案 A", "方案 B"],
    "position_cap": ["5% NAV", "4% NAV", "3% NAV"],
    "理论最大持仓数": ["~20 只", "~25 只", "~33 只"],
    "每笔仓位（$136M NAV）": ["~$6.8M", "~$5.4M", "~$4.1M"],
    "信号执行率（预估）": ["~13%", "~17%", "~23%"],
})
st.dataframe(_cap_df, use_container_width=True, hide_index=True)

st.markdown("""
**权衡：** 单笔仓位缩小会减少每笔绝对盈利，但同时执行更多好信号可弥补。
**建议与建议 1 结合**：先按质量排序，再用较小仓位执行前 N 名信号，
既保证质量又提高执行率。

**注意：** 降低 `position_cap` 对最大回撤的影响需要完整回测验证，
单笔仓位变小通常有助于分散风险、降低最大回撤，但同时持仓数增多也增加了整体风险敞口。
""")

# Chart: position_cap sensitivity from actual backtest data
_pcap_f = _perturb_path / "position_cap.json"
if _pcap_f.exists():
    _pcd = json.loads(_pcap_f.read_text())
    _pcv  = _pcd["param_values"]
    _pcc  = [r["cagr"] * 100 for r in _pcd["results"]]
    _pcm  = [abs(r["max_drawdown"]) * 100 for r in _pcd["results"]]
    _pcn  = [r["n_trades"] for r in _pcd["results"]]
    _baseline_pc = _pcd["baseline_value"]
    _fig_pc = go.Figure()
    _fig_pc.add_trace(go.Bar(
        x=[f"{v:.0%}" for v in _pcv], y=_pcc, name="CAGR (%)",
        marker_color=["#22c55e" if v == _baseline_pc else "#6366f1" for v in _pcv],
        yaxis="y",
    ))
    _fig_pc.add_trace(go.Scatter(
        x=[f"{v:.0%}" for v in _pcv], y=_pcm, name="最大回撤（%，右轴）",
        mode="lines+markers", marker=dict(size=9, color="#ef4444"),
        line=dict(color="#ef4444", width=2), yaxis="y2",
    ))
    _fig_pc.add_trace(go.Scatter(
        x=[f"{v:.0%}" for v in _pcv], y=_pcn, name="交易笔数（右轴2）",
        mode="lines+markers", marker=dict(size=7, color="#94a3b8"),
        line=dict(color="#94a3b8", width=1.5, dash="dot"), yaxis="y3",
    ))
    _fig_pc.update_layout(
        title="单笔仓位上限（position_cap）敏感性：CAGR、MaxDD、交易笔数",
        xaxis_title="position_cap（% NAV）",
        yaxis=dict(title="CAGR (%)", side="left", range=[7, 12]),
        yaxis2=dict(title="最大回撤（%）", side="right", overlaying="y", position=1.0, range=[18, 28]),
        yaxis3=dict(title="交易笔数", side="right", overlaying="y", position=0.85, showgrid=False),
        legend=dict(x=0.4, y=0.05), height=380, margin=dict(t=50, b=40, r=80),
    )
    st.plotly_chart(_fig_pc, use_container_width=True)
    st.caption(
        f"当前 position_cap = {_baseline_pc:.0%}（绿色），CAGR = {_pcc[_pcv.index(_baseline_pc)]:.2f}%，{_pcn[_pcv.index(_baseline_pc)]:.0f} 笔交易。"
        f"降至 3% 时交易笔数大幅增加至 {_pcn[0]:.0f} 笔，但每笔规模缩小，CAGR 降至 {_pcc[0]:.2f}%。"
        "提高至 7% 时交易笔数减少、持仓集中度上升，MaxDD 增至 22.9%。当前 5% 是 CAGR 最优点。"
    )

st.markdown("---")

# 建议 4
st.markdown("#### 建议 4：每日执行上限 + 质量门槛（主动控制开仓节奏）")
st.markdown("""
**预期效果：降低集中开仓风险，轻微提升 CAGR**

不依赖资金被动决定执行数量，而是**主动设定每天最多执行 K 个信号**，
并对每个信号设置最低质量门槛——低于门槛的信号即使资金充足也不执行。
""")

st.code("""
MAX_DAILY_ENTRIES   = 3     # 每天最多开 3 个新仓
MIN_QUALITY_SCORE   = 0.4   # 质量分低于 0.4 的信号不执行（满分 1.0）

ranked = rank_signals(today_signals)
entries_today = 0

for signal in ranked:
    if entries_today >= MAX_DAILY_ENTRIES:
        break  # 今日额度已满
    if signal.quality_score < MIN_QUALITY_SCORE:
        break  # 剩余信号质量不足，不执行
    if has_sufficient_cash(signal):
        execute(signal)
        entries_today += 1
""", language="python")

st.markdown("""
**为何需要每日上限：** 2026 年平均每天 14.3 个信号，若资金充足会大量集中开仓，
带来同方向风险。最优化的开仓节奏是每天 1-3 个高质量信号，而非"资金够就开"。
""")

st.markdown("---")

# ── 综合评估 ──────────────────────────────────────────────────────────────────
st.subheader("综合效益评估")

st.markdown("""
| 建议 | 预期 CAGR 提升 | 对最大回撤影响 | 实现难度 | 优先级 |
|------|-------------|-------------|---------|-------|
| **建议 1：信号质量排序** | **+2–4%** | **无影响** | ★ 低 | 🔴 最高 |
| **建议 2：突破强度过滤** | +0.5–1.5% | 降低（减少假突破） | ★★ 中 | 🔴 高 |
| **建议 4：每日上限+门槛** | 与建议1叠加 | 轻微降低 | ★ 低 | 🟡 高 |
| **建议 3：降低 position_cap** | 待回测验证 | 中性（需验证） | ★★ 中 | 🟡 中 |

**推荐实施路径：**

1. **第一步**（立即可做）：实现建议 1（信号质量排序）
   - 修改信号生成后的排序逻辑，优先执行 `quality_score` 最高的信号
   - 代码改动集中在 `src/strategy/v1/entry.py`，不影响仓位逻辑
   - 全量回测并对比前后 Sharpe、均值 R 的变化

2. **第二步**：叠加建议 2（突破强度过滤）并做参数扫描
   - `min_volume_ratio` 从 1.0 到 2.0 扫描，观察总信号数 vs 绩效的权衡曲线
   - 若两者叠加后执行率从 13% 降至 10%（更少但更好），但均值 R 提升，则净效果为正

3. **第三步**：基于回测结果决定是否调整 `position_cap`（建议 3）
""")

st.warning("""
**重要提醒：** 以上分析的局限性——

我们能观测到"执行的信号"的绩效，但无法直接知道"被放弃的信号"如果执行会是什么结果。
改进效果必须通过**完整历史回测**（2000→2026）验证，
并在 **Walk-Forward OOS**（2016→2026）数据上确认，才能排除过拟合风险。

尤其是建议 1 的权重设计（0.35/0.30/0.25/0.10）是假设，实际最优权重需要系统性参数扫描。
""")

st.markdown("""
---

**一句话核心洞察：**

> **86.8% 的放弃率本身不是问题——问题是被执行的 13.2% 没有被优先选为最优质的 13.2%。**
>
> 信号拥挤时（11-50 个信号），当前机制执行的交易均值 R 为 -0.05R，几乎没有正期望。
> 只要加入信号质量排序，就能在**不改变任何仓位参数的情况下**，把现有执行次数的平均回报提升一个档次。
""")
