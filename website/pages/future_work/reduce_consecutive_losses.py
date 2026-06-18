"""如何降低连续亏损次数"""

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

st.title("如何降低连续亏损次数")
st.caption("基于连续亏损序列分析，识别长序列的根本成因并提出可落地的改进建议")

st.markdown("---")

# ── 数学基础：先设定正确的心理预期 ──────────────────────────────────────────────
st.subheader("一、数学基础：38.7% 胜率下，连亏是不可避免的")

import math
WIN_RATE = 0.387
LOSS_RATE = 1 - WIN_RATE
N_TRADES = 3337
expected_max = math.log(N_TRADES * WIN_RATE) / math.log(1 / LOSS_RATE)

st.markdown(f"""
策略1.0胜率为 **38.7%**，意味着每笔交易有 **61.3%** 的概率亏损。
在 {N_TRADES:,} 笔交易的样本中，纯随机情况下期望最长连亏为：

$$E[\\text{{最长连亏}}] = \\frac{{\\ln(N \\cdot p)}}{{\\ln(1/q)}} = \\frac{{\\ln({N_TRADES} \\times {WIN_RATE})}}{{\\ln(1/{LOSS_RATE:.3f})}} \\approx {expected_max:.0f} \\text{{ 笔}}$$

实际最长连亏为 **34 笔**，高于理论期望 {expected_max:.0f} 笔——说明长序列并非纯粹随机，
而是由特定市场环境驱动（见下文分析）。

| 如果胜率能提升到… | 理论最长连亏 |
|-----------------|------------|
| 38.7%（当前） | {expected_max:.0f} 笔 |
| 45% | {math.log(N_TRADES*0.45)/math.log(1/0.55):.0f} 笔 |
| 50% | {math.log(N_TRADES*0.50)/math.log(1/0.50):.0f} 笔 |

> 即使胜率提升到 50%，理论最长连亏仍有约 **{math.log(N_TRADES*0.50)/math.log(1/0.50):.0f} 笔**。
> 单靠提升胜率并不能根本解决长序列问题——必须找到并干预导致超长序列的结构性原因。
""")

st.markdown("---")

# ── 关键发现：长序列有规律，不是随机运气 ─────────────────────────────────────────
st.subheader('二、关键发现：长序列是"市场环境事件"，不是随机坏运气')

st.markdown("""
对所有 **≥ 10 笔**的连亏序列（共 41 个）做特征分析，发现了明显的共性模式：

| 特征 | 数据 | 含义 |
|------|------|------|
| 平均持仓天数 | **10–20 天**（显著低于全局均值） | 进场后极快被止损打出 |
| 初始止损（stop_loss）比例 | **70%–95%** | 不是趋势反转后被追踪止损打出，而是"假突破"快速失败 |
| 序列时间集中度 | 单个序列往往在 **2–6 周内**完成 | 这是同期多个仓位集中出清，而非时序上一笔一笔的随机亏损 |
""")

# Load trades and compute streak info
@st.cache_data
def load_streak_data():
    trades = pd.read_csv(
        _results_path / "trades.csv",
        parse_dates=["entry_date", "exit_date"]
    ).sort_values("exit_date").reset_index(drop=True)
    return trades

trades = load_streak_data()
pnl = trades["net_pnl"].values

# Build streak list
streaks_detail = []
cur = 0
cur_start = 0
for i, v in enumerate(pnl):
    if v <= 0:
        if cur == 0:
            cur_start = i
        cur += 1
    else:
        if cur > 0:
            seg = trades.iloc[cur_start:cur_start+cur]
            streaks_detail.append({
                "length":     cur,
                "start_date": seg["exit_date"].min(),
                "end_date":   seg["exit_date"].max(),
                "avg_hold":   seg["holding_days"].mean(),
                "sl_pct":     (seg["exit_reason"] == "stop_loss").mean(),
                "span_days":  (seg["exit_date"].max() - seg["exit_date"].min()).days + 1,
                "net_pnl":    seg["net_pnl"].sum(),
            })
        cur = 0

if cur > 0:
    seg = trades.iloc[cur_start:cur_start+cur]
    streaks_detail.append({
        "length":     cur,
        "start_date": seg["exit_date"].min(),
        "end_date":   seg["exit_date"].max(),
        "avg_hold":   seg["holding_days"].mean(),
        "sl_pct":     (seg["exit_reason"] == "stop_loss").mean(),
        "span_days":  (seg["exit_date"].max() - seg["exit_date"].min()).days + 1,
        "net_pnl":    seg["net_pnl"].sum(),
    })

df_streaks = pd.DataFrame(streaks_detail)
major = df_streaks[df_streaks["length"] >= 10].copy()

# Scatter: length vs avg_hold
fig_sc = go.Figure(go.Scatter(
    x=major["avg_hold"],
    y=major["length"],
    mode="markers+text",
    text=major["start_date"].dt.strftime("%Y-%m"),
    textposition="top center",
    textfont=dict(size=9),
    marker=dict(
        size=major["sl_pct"] * 20 + 6,
        color=major["sl_pct"],
        colorscale="Reds",
        colorbar=dict(title="初始止损%"),
        cmin=0.4, cmax=1.0,
        showscale=True,
    ),
    customdata=np.column_stack([
        major["sl_pct"]*100,
        major["net_pnl"]/1e4,
        major["span_days"],
    ]),
    hovertemplate=(
        "<b>%{text}</b><br>"
        "序列长度：%{y} 笔<br>"
        "平均持仓：%{x:.1f} 天<br>"
        "初始止损占比：%{customdata[0]:.0f}%<br>"
        "净亏损：$%{customdata[1]:.0f}万<br>"
        "序列跨度：%{customdata[2]} 天<extra></extra>"
    ),
))
fig_sc.update_layout(
    title="≥10 笔连亏序列：平均持仓天数 vs 序列长度（气泡大小 = 初始止损占比）",
    xaxis_title="平均持仓天数（越短 = 越快被打出）",
    yaxis_title="连亏笔数",
    height=420,
    margin=dict(l=60, r=20, t=60, b=50),
)
st.plotly_chart(fig_sc, use_container_width=True)

st.markdown("""
**图表解读：** 持仓天数越短（横轴越靠左）、气泡颜色越深（初始止损占比越高），
说明该序列是典型的"假突破密集失败"场景——市场在反复发出突破信号，但每次突破都迅速失败并触发初始止损。

**这一规律有重要的战略含义：**
长连亏序列不是策略1.0在某段时间一直做了错误决策，
而是市场进入了一种"震荡假突破"的环境，策略的趋势跟踪逻辑与此类市场状态天然不兼容。
""")

with st.expander("📋 全部 ≥10 笔连亏序列明细", expanded=False):
    show = major[["length","start_date","end_date","avg_hold","sl_pct","span_days","net_pnl"]].copy()
    show.columns = ["长度(笔)","起始日期","结束日期","均持仓(天)","初始止损%","跨度(天)","净亏损($)"]
    show["起始日期"] = show["起始日期"].dt.strftime("%Y-%m-%d")
    show["结束日期"] = show["结束日期"].dt.strftime("%Y-%m-%d")
    show["初始止损%"] = show["初始止损%"].map(lambda v: f"{v*100:.0f}%")
    show["净亏损($)"] = show["净亏损($)"].map(lambda v: f"${v:,.0f}")
    show = show.sort_values("长度(笔)", ascending=False).reset_index(drop=True)
    st.dataframe(show, use_container_width=True, hide_index=True)

st.markdown("---")

# ── 建议 ──────────────────────────────────────────────────────────────────────
st.subheader("三、具体改进建议")

# 建议 1
st.markdown("### 建议 1：震荡市检测器（Choppiness Filter）—— 最高优先级")
st.markdown("""
**直接攻击长连亏的根本原因。**

假突破密集期的市场特征是：价格反复突破然后回撤，没有持续方向。
可以通过以下指标识别这类"震荡市"并暂停或减少新开仓：

**方案 A：Choppiness Index（震荡指数）**
""")
st.code("""
# Choppiness Index：越接近 100 = 越震荡；越接近 0 = 越趋势
def choppiness_index(high, low, close, period=14):
    atr = pd.Series(high - low)  # 简化版，实际用 ATR
    total_range = high.rolling(period).max() - low.rolling(period).min()
    ci = 100 * np.log10(atr.rolling(period).sum() / total_range) / np.log10(period)
    return ci

# 入场条件中加入过滤
if choppiness_index(spy_high, spy_low, spy_close).iloc[-1] > 61.8:
    skip_entry(ticker, reason="choppy_market")
""", language="python")

st.markdown("""
**方案 B：近期信号成功率（更直接，但有前视风险需谨慎）**
""")
st.code("""
# 维护一个滑动窗口：最近 20 笔已完结交易的胜率
recent_win_rate = rolling_win_rate(window=20)

# 若近期胜率低于正常水平的一半，暂停新开仓 N 天
PAUSE_THRESHOLD = 0.20   # 低于 20% 即暂停
PAUSE_DAYS = 5

if recent_win_rate < PAUSE_THRESHOLD:
    pause_new_entries(days=PAUSE_DAYS)
""", language="python")

st.markdown("""
> **注意：** 方案 B 存在轻微的"用已知结果指导决策"的风险，需在 Walk-Forward 中严格验证，
> 不可在回测中使用当天出场结果来指导当天入场。

**预期效果：** 以 2010 年 34 笔连亏为例，若当时检测到震荡市并暂停入场，
那 34 笔中大多数（在震荡期内快速止损的）根本不会开仓，序列可能从 34 压缩到 5 以内。
""")

st.markdown("---")

# 建议 2
st.markdown("### 建议 2：提高入场信号质量（Breakout Strength Filter）")
st.markdown("""
**策略1.0 当前 `breakout_strength_min = 0`，即不要求突破强度。**

弱突破（收盘价仅刚好超过 200 日高点，无量无力）在震荡市中失败率极高。
加入突破强度过滤可以筛掉大量"假突破"，直接提升胜率。

**规则设计：**
""")
st.code("""
# 现有逻辑（breakout_strength_min = 0，任何超过均算突破）
is_breakout = close > rolling_high_200

# 加强后：要求收盘价超过 200 日高点至少 X%
BREAKOUT_STRENGTH_MIN = 0.01   # 需超过高点 1%（当前默认 0）

is_strong_breakout = close > rolling_high_200 * (1 + BREAKOUT_STRENGTH_MIN)
""", language="python")

st.markdown("""
**参数敏感性参考（来自参数敏感性分析页）：** `breakout_strength_min` 从 0 提升到 0.01–0.02，
预期效果：
- 交易笔数减少 10–20%（过滤掉弱信号）
- 胜率提升约 2–4 个百分点
- 连亏序列中的"快速假突破失败"笔数显著减少

**代价：** 会错过少量真实突破（入场信号发出时强度不足，但后续确实上涨的标的）。
""")

st.markdown("---")

# 建议 3
st.markdown("### 建议 3：限制单日 / 单周最大开仓数（Entry Clustering Limit）")
st.markdown("""
**针对"同批次开仓全部快速失败"的集中亏损场景。**

分析显示，多笔长连亏序列对应的是一批在同一时间窗口内密集开仓的标的，随后集中出场。
限制"窗口期内新开仓数"可以避免在单一市场环境下押注过多相关标的。
""")
st.code("""
MAX_NEW_ENTRIES_PER_DAY  = 5    # 单日最多开 5 个新仓
MAX_NEW_ENTRIES_PER_WEEK = 10   # 单周最多开 10 个新仓

# 已有信号按优先级排序（如突破强度、ATR 质量），只执行前 N 个
signals_today = generate_signals(date)
signals_today = signals_today.sort_values("breakout_strength", ascending=False)
execute_signals = signals_today.head(MAX_NEW_ENTRIES_PER_DAY)
""", language="python")

st.markdown("""
**直觉解释：** 如果某天市场同时出现 30 个突破信号，这本身就是一个警告——
在正常趋势市中，信号分布应该相对分散。密集信号往往意味着近期上涨过快、
突破可信度偏低，此时少开仓比多开仓更安全。
""")

st.markdown("---")

# 建议 4
st.markdown("### 建议 4：连亏后仓位动态缩减（Anti-Streak Sizing）")
st.markdown("""
**这条建议不会减少连亏"笔数"，但能降低心理和财务冲击，让人更容易坚持执行策略。**

在连续亏损期间，每笔的实际亏损金额如果能小一些，心理压力会显著减轻，
也不容易在最坏的时机放弃策略。
""")
st.code("""
BASE_RISK_PCT = 0.01   # 正常情况每笔风险 1% NAV

# 连亏计数器
def get_position_scale(consecutive_losses: int) -> float:
    if consecutive_losses >= 10:
        return 0.50    # 连亏 10+ 笔：仓位缩至 50%
    elif consecutive_losses >= 7:
        return 0.65    # 连亏 7–9 笔：仓位缩至 65%
    elif consecutive_losses >= 5:
        return 0.80    # 连亏 5–6 笔：仓位缩至 80%
    else:
        return 1.00    # 正常

# 入场时应用
scale = get_position_scale(current_streak)
risk_pct = BASE_RISK_PCT * scale
""", language="python")

st.markdown("""
**注意：** 这条规则需要验证不会引入"低谷减仓、高峰满仓"的负向择时效应。
回测时应检查：是否在正确的时机减仓（连亏期）而非在市场即将反转前反而减了仓？

**替代方案（更简单）：** 不根据连亏次数，而是根据当前净值离历史高点的回撤幅度来调整仓位，
这样更客观，也不依赖"连亏序列"这个噪声较大的计数器。
""")

st.markdown("---")

# 建议 5（最长远）
st.markdown("### 建议 5（长期）：引入非相关收益来源打破序列")
st.markdown("""
**这是从根本上解决问题的方向，也是最复杂的。**

长连亏序列的本质是：**所有持仓都在同一市场环境下输**。
如果组合中有一部分策略在"趋势跟踪失效"的震荡市中仍能盈利，
这些盈利就会自然地"插入"损失序列，把长序列打断成若干短序列。

**可能的非相关收益来源：**

| 方向 | 思路 | 与趋势跟踪的相关性 |
|------|------|----------------|
| **震荡市均值回归策略** | 在 Choppiness Index 高时，做 RSI 超买超卖反转 | 负相关（震荡市趋势跟踪亏损，均值回归盈利） |
| **做空 / 反向 ETF** | Regime = 熊市时，买入 SH（S&P 500 反向 ETF） | 负相关 |
| **波动率策略** | 在高 VIX 期间买入 VXX 或做保护性期权 | 负相关 |
| **多市场扩展** | 加入商品、外汇的趋势跟踪 | 低相关（不同资产的趋势不同步） |

**最低成本的起点**：在 Regime Filter 判断为熊市期间，
将部分资金投入 SH（S&P500 反向 ETF）而非 SHY（国债）。
这样熊市中部分亏损被对冲，连亏序列被自然打断。
""")

st.markdown("---")

# ── 汇总建议 ──────────────────────────────────────────────────────────────────
st.subheader("四、建议优先级汇总")

st.markdown("""
| 建议 | 减少连亏次数效果 | 减少心理冲击效果 | 对 CAGR 影响 | 实现难度 | 优先级 |
|------|---------------|---------------|------------|---------|--------|
| 建议 2：Breakout Strength Filter | ★★★ | ★★★ | 低偏正 | ★ 低 | 🔴 最高 |
| 建议 1：震荡市检测器 | ★★★★ | ★★★★ | 中（需验证） | ★★ 中 | 🔴 最高 |
| 建议 3：开仓集中度限制 | ★★★ | ★★★ | 低 | ★ 低 | 🟡 高 |
| 建议 4：连亏后动态缩仓 | ★（不减少笔数） | ★★★★ | 低偏负 | ★ 低 | 🟡 高（心理价值大） |
| 建议 5：引入非相关收益 | ★★★★★ | ★★★★★ | 高（正向） | ★★★ 高 | 🟢 长期 |

**推荐实施路径：**

1. **立即可做**：将 `breakout_strength_min` 从 0 调整为 0.01，在参数敏感性分析中观察胜率和连亏序列的变化
2. **下一步**：设计并回测震荡市检测器（Choppiness Index 版本），比较加入前后的最长连亏和整体夏普比率
3. **心理缓冲**：实盘时配置连亏动态缩仓规则，即使回测中效果有限，对执行纪律的保护价值极大
4. **长期目标**：逐步引入非相关收益来源，从根本上打断长序列结构
""")

st.markdown("---")

st.info(
    "**最重要的心理认知**：连续亏损不是"策略出错"的信号，而是趋势跟踪策略在震荡市中的正常表现。"
    "历史数据中，每一次最长连亏序列之后，策略都恢复并创下了新高。"
    "提前理解这一点，比任何算法改进都更能帮助实盘中保持执行纪律。"
)
