"""有关持仓天数的建议"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

_results_path = _root / "results" / "v1_unbiased_60m_2000"

st.title("有关持仓天数的建议")
st.caption('分析"是否应该限制大持仓天数（如>365天）来提高资金使用率、CAGR，同时保持或降低最大回撤"')

st.markdown("---")

# ── 核心结论 ──────────────────────────────────────────────────────────────────
st.info("""
**结论先行：不应该限制持仓天数。**

数据显示，持仓超过 365 天的交易是策略中**年化资本效率最高**的一类。
强制平仓大持仓，会截断大赢家的利润，而释放出的资金几乎不能找到同等回报率的新机会。
真正的资金低效来自另一个方向——大量 0-30 天的快速止损交易。
""")

st.markdown("---")

# ── 数据加载 ──────────────────────────────────────────────────────────────────
trades = pd.read_csv(_results_path / "trades.csv", parse_dates=["entry_date", "exit_date"])
trades["holding_days"] = (trades["exit_date"] - trades["entry_date"]).dt.days
trades["notional"] = trades["entry_price"] * trades["shares"]
total_pnl = trades["net_pnl"].sum()
total_n = len(trades)

# ── 一、持仓天数分桶分析 ───────────────────────────────────────────────────────
st.subheader("一、持仓天数分桶：越长赚得越多")

buckets = [
    ("0-30天",    0,   30),
    ("31-90天",  31,   90),
    ("91-180天", 91,  180),
    ("181-365天",181, 365),
    ("1-2年",    366, 730),
    ("2年以上",  731, 9999),
]

rows = []
for label, lo, hi in buckets:
    sub = trades[(trades["holding_days"] >= lo) & (trades["holding_days"] <= hi)]
    n = len(sub)
    wins = sub[sub["net_pnl"] > 0]
    wr = len(wins) / n * 100 if n > 0 else 0
    avg_r = sub["pnl_r_multiple"].mean()
    pnl = sub["net_pnl"].sum()
    rows.append({
        "持仓区间": label,
        "笔数": f"{n}（{n/total_n*100:.1f}%）",
        "胜率": f"{wr:.1f}%",
        "平均 R": f"{avg_r:+.2f}R",
        "净盈亏": f"${pnl/1e6:.1f}M",
        "占总利润": f"{pnl/total_pnl*100:.1f}%",
    })

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.markdown("""
规律一目了然：**持仓越长，胜率越高、R 倍数越高、利润越大。**

最值得注意的对比：
- 0-30 天的 1,871 笔交易（占总笔数 56%），胜率仅 10.3%，净亏损高达 **-$140.6M**
- 181-365 天的 81 笔，胜率 **100%**，平均 7.7R，净盈利 $50.6M
- >365 天的 10 笔，胜率 **100%**，平均 14.7R，净盈利 $13.0M
""")

# 柱状图：各桶净盈亏
_labels = [r["持仓区间"] for r in rows]
_pnls   = []
for label, lo, hi in buckets:
    sub = trades[(trades["holding_days"] >= lo) & (trades["holding_days"] <= hi)]
    _pnls.append(sub["net_pnl"].sum() / 1e6)

fig_bar = go.Figure(go.Bar(
    x=_labels,
    y=_pnls,
    marker_color=["#d62728" if v < 0 else "#2ca02c" for v in _pnls],
    text=[f"${v:.1f}M" for v in _pnls],
    textposition="outside",
))
fig_bar.update_layout(
    title="各持仓天数区间净盈亏",
    yaxis_title="净盈亏（$M）",
    height=360,
    template="plotly_white",
    margin=dict(t=50, b=40),
)
st.plotly_chart(fig_bar, use_container_width=True)

st.markdown("---")

# ── 二、>365 天的 10 笔交易详情 ───────────────────────────────────────────────
st.subheader("二、持仓超过 365 天的 10 笔交易：全部是高质量大赢家")

long = trades[trades["holding_days"] > 365].sort_values("pnl_r_multiple", ascending=False).copy()
long["持仓年数"] = (long["holding_days"] / 365.25).map(lambda x: f"{x:.1f} 年")
long["退出方式"] = long["exit_reason"].map({
    "trailing_stop":   "追踪止损",
    "stop_loss":       "止损",
    "end_of_backtest": "回测截止",
    "delisted":        "退市/并购",
}).fillna(long["exit_reason"])
long["持仓天数"] = long["holding_days"]
long["R 倍数"] = long["pnl_r_multiple"].map(lambda v: f"{v:.1f}R")
long["净盈亏"] = long["net_pnl"].map(lambda v: f"${v/1e3:.0f}K")
long["入场日期"] = long["entry_date"].dt.strftime("%Y-%m-%d")
long["平仓日期"] = long["exit_date"].dt.strftime("%Y-%m-%d")

st.dataframe(long[["ticker","入场日期","平仓日期","持仓天数","持仓年数","R 倍数","净盈亏","退出方式"]].reset_index(drop=True),
             use_container_width=True, hide_index=True)

st.markdown("""
**三个关键观察：**

1. **全部 10 笔均为追踪止损退出**——趋势自然结束后才离场，没有一笔是僵尸仓被动等待
2. **9/10 笔集中在 366-433 天**（刚过 1 年），只有 SPLK 达到 955 天（2.6 年），超长持仓是极少数情况
3. **R 倍数全部 ≥ 6.4R**，是策略最有价值的交易之一（LNG 21R、TTWO 20R、META 17.4R）
""")

st.markdown("---")

# ── 三、年化资本效率对比 ──────────────────────────────────────────────────────
st.subheader("三、年化资本效率：大持仓不拖累资金，反而是最高效的")

st.markdown("""
衡量资本效率的正确方法：**年化资本回报率 = 净盈亏 ÷ 仓位规模 ÷ 持仓年数**
（即每投入 1 元、持有 1 年的实际回报）
""")

eff_rows = []
for label, lo, hi in buckets:
    sub = trades[(trades["holding_days"] >= lo) & (trades["holding_days"] <= hi)].copy()
    sub["ann_cap_return"] = (sub["net_pnl"] / sub["notional"]) / (sub["holding_days"] / 252)
    sub_win = sub[sub["net_pnl"] > 0]
    mean_ann = sub_win["ann_cap_return"].mean() * 100 if len(sub_win) > 0 else 0
    all_mean = sub["ann_cap_return"].mean() * 100 if len(sub) > 0 else 0
    eff_rows.append({
        "持仓区间": label,
        "盈利交易年化资本效率": f"{mean_ann:.1f}%",
        "全部交易年化资本效率（含亏损）": f"{all_mean:.1f}%",
    })

st.dataframe(pd.DataFrame(eff_rows), use_container_width=True, hide_index=True)

st.markdown("""
**结论：**

- **>365 天**的交易，盈利交易年化资本效率 **43%**，高于 91-365 天组的 36%
- 0-30 天组的资本效率极低（含亏损全部计入后深度负值），这才是真正拖累资金使用率的来源
- **大持仓不是问题，恰恰是策略最优质的资产**
""")

st.markdown("---")

# ── 四、"限制持仓天数"的代价估算 ────────────────────────────────────────────
st.subheader("四、如果在第 365 天强制平仓，代价有多大？")

# 大持仓超出365天的额外资金日
long_copy = trades[trades["holding_days"] > 365].copy()
long_copy["extra_days"] = long_copy["holding_days"] - 365
total_extra_cap_days = (long_copy["extra_days"] * long_copy["notional"]).sum()
avg_notional = trades["notional"].mean()
avg_hold = trades["holding_days"].mean()
potential_new_trades = total_extra_cap_days / (avg_notional * avg_hold)

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("损失的潜在利润（保守估）", "~$6.5M–$13M",
              help="大持仓在第365天之后继续产生的盈利；保守假设在第365天时仅处于最终R的50%，后半段全部损失")
with col2:
    st.metric("释放出的资金能多做", f"约 {potential_new_trades:.0f} 笔交易",
              help="26年间额外可做的新交易数（极少，且受牛熊市信号数量限制）")
with col3:
    st.metric("替代交易的期望回报", "远低于被截断的大赢家",
              help="策略整体均值R约+0.5R，而被截断的持仓平均R=14.7R")

st.markdown("""
**这笔交换在数学上不合算：**
- 截断 10 笔均值 14.7R 的大赢家，损失 $6.5M–$13M
- 换来约 30 笔新交易机会（26 年均摊），期望回报仅 +0.5R 量级
- 且这 30 笔新机会受 Regime Filter 约束，不一定真实存在（熊市期间无新开仓）
""")

st.markdown("---")

# ── 五、真正的资金使用率问题 ────────────────────────────────────────────────
st.subheader("五、真正的资金低效来自哪里？")

st.markdown("**0-30 天的快速止损交易才是资金使用率的主要拖累：**")

# Chart: 0-30 days vs all others — direct comparison
_fast = trades[(trades["holding_days"] <= 30)].copy()
_fast_loss = _fast[_fast["net_pnl"] < 0]
_slow = trades[(trades["holding_days"] > 30)].copy()
_slow_loss = _slow[_slow["net_pnl"] < 0]
_rest_gain = trades[(trades["holding_days"] > 90)].copy()

_fig_split = go.Figure()
_fig_split.add_trace(go.Bar(
    x=["0-30天<br>快速止损（1,871笔）", ">30天<br>其余交易（1,466笔）"],
    y=[_fast["net_pnl"].sum() / 1e6, _slow["net_pnl"].sum() / 1e6],
    marker_color=["#ef4444", "#22c55e"],
    text=[
        f"${_fast['net_pnl'].sum()/1e6:.1f}M<br>胜率={(_fast['net_pnl']>0).mean()*100:.1f}%",
        f"${_slow['net_pnl'].sum()/1e6:.1f}M<br>胜率={(_slow['net_pnl']>0).mean()*100:.1f}%",
    ],
    textposition="outside",
))
_fig_split.update_layout(
    title="0-30天快速止损 vs 其余交易的净盈亏对比",
    yaxis_title="净盈亏（$M）",
    height=320,
    margin=dict(t=50, b=40),
    yaxis=dict(range=[_fast["net_pnl"].sum() / 1e6 * 1.15, _slow["net_pnl"].sum() / 1e6 * 1.2]),
)
st.plotly_chart(_fig_split, use_container_width=True)

st.markdown(f"""
| 问题 | 数据 | 说明 |
|------|------|------|
| 0-30 天快速止损 | {len(_fast):,} 笔，净亏损 ${abs(_fast['net_pnl'].sum()/1e6):.1f}M | 占总交易 {len(_fast)/total_n*100:.0f}%，胜率仅 {(_fast['net_pnl']>0).mean()*100:.1f}% |
| 其中第 1-10 天就止损 | 占 0-30 天组 {len(_fast[_fast['holding_days']<=10])/len(_fast)*100:.0f}% | 说明入场质量是核心问题 |
| >30 天（趋势充分发展） | {len(_slow):,} 笔，净盈利 ${_slow['net_pnl'].sum()/1e6:.1f}M | 胜率 {(_slow['net_pnl']>0).mean()*100:.0f}%，策略真正的利润来源 |

这些快速亏损是**趋势跟踪策略必须支付的"保费"**——策略通过截断这些亏损，换来了少数大赢家的右尾收益。
但如果能**提高入场质量**，减少假突破比例，则可以：
1. 降低亏损交易密度（减少 0-30 天快速止损的数量）
2. 释放更多资金用于真正的趋势机会
3. 同时提升 CAGR 和降低最大回撤
""")

st.markdown("---")

# ── 六、建议 ────────────────────────────────────────────────────────────────
st.subheader("六、建议：保护大持仓，优化入场质量")

st.markdown("""
| 方向 | 具体措施 | 预期效果 |
|------|---------|---------|
| ✅ 保护大持仓 | 对 >10R 仓位放宽追踪止损至 7× ATR（见《如何提高年化收益》建议2） | CAGR +1-2%，回撤中性 |
| ✅ 放大大持仓收益 | 金字塔加仓：在 3R 时追加 50% 仓位（见《如何提高年化收益》建议1） | CAGR 估算 +4-5% |
| 🔧 减少假突破入场 | 突破强度过滤（成交量确认 ≥ 1.5× 均量，阳线突破等） | 减少 0-30 天止损，CAGR +0.5-1.5% |
| 🔧 淘汰僵尸仓 | 时间止损：30 天内最高盈利 < 0.5R，止损移至保本 | 释放资金，轻微提升 CAGR |
| ❌ 不推荐 | 强制在第 365 天平仓大持仓 | CAGR 下降 $6.5M-$13M 利润损失 |
""")

st.warning("""
**核心认知：持仓时间不是问题，入场质量才是问题。**

持仓超过 365 天的 10 笔交易，是 26 年回测中**年化资本效率最高**的交易之一（43% 年化回报率）。
它们的长持仓是因为趋势持续强劲，追踪止损一直没有触发——这正是策略设计的理想状态。

真正需要优化的是：
1. 减少那些"突破后马上被打回去"的假入场（减少 0-30 天止损）
2. 通过金字塔加仓放大已经验证的大趋势

这两个方向同时提升 CAGR 和改善风险特性，而限制持仓天数则只会两头受损。
""")
