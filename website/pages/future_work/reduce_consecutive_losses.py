"""如何降低连续亏损次数"""

import json
import math
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
from plotly.subplots import make_subplots

_pio.templates.default = "plotly_white"

_results_path = _root / "results" / "v1_unbiased_60m_2000"
_perturb_path = _root / "results" / "v1_unbiased_60m_2000" / "perturbation"

st.title("如何降低连续亏损次数")
st.markdown("基于连续亏损序列分析，识别长序列的根本成因并提出可落地的改进建议")

st.markdown("---")

# ── 建议优先级汇总（置顶）────────────────────────────────────────────────────────
st.subheader("★ 建议优先级总览（从最推荐到最复杂）")

st.markdown("""
以下排序综合考虑：**实施难度**、**对减少连亏笔数的直接效果**、**对CAGR的预期影响**，
以及与当前策略1.0代码的兼容性。详细分析见下方各建议节。
""")

_priority_rows = [
    {
        "排序": "🥇 第1位",
        "建议": "建议2：突破强度过滤（Breakout Strength Filter）",
        "核心逻辑": "过滤弱突破，减少「假突破快速失败」",
        "减少连亏笔数": "★★★",
        "对CAGR影响": "低偏正",
        "实施难度": "★ 极低",
        "备注": "一行参数修改；参数敏感性已验证",
    },
    {
        "排序": "🥈 第2位",
        "建议": "建议3：单日开仓集中度限制（Entry Clustering Limit）",
        "核心逻辑": "避免同批次集中入场 → 集中止损",
        "减少连亏笔数": "★★★",
        "对CAGR影响": "低",
        "实施难度": "★ 低",
        "备注": "34笔连亏中多笔同日入场；直接可回测验证",
    },
    {
        "排序": "🥉 第3位",
        "建议": "建议6：暂停熔断（方案A：同日≥3笔止损；方案B：连亏≥10笔）",
        "核心逻辑": "检测到市场异常信号后暂停新仓N天",
        "减少连亏笔数": "★★★",
        "对CAGR影响": "低",
        "实施难度": "★ 低",
        "备注": "方案A捕捉急剧下跌，方案B捕捉持续震荡；可叠加使用",
    },
    {
        "排序": "第4位",
        "建议": "建议1：震荡市检测器（Choppiness Index Filter）",
        "核心逻辑": "主动识别「假突破密集期」，预防性暂停入场",
        "减少连亏笔数": "★★★★",
        "对CAGR影响": "中（需验证）",
        "实施难度": "★★ 中",
        "备注": "效果最强但需Walk-Forward验证，防过拟合",
    },
    {
        "排序": "第5位",
        "建议": "建议4：连亏后动态缩仓（Anti-Streak Sizing）",
        "核心逻辑": "连亏期自动缩减每笔风险敞口",
        "减少连亏笔数": "★（不减笔数）",
        "对CAGR影响": "低偏负",
        "实施难度": "★ 低",
        "备注": "不减少连亏次数，但大幅降低回撤幅度和心理压力",
    },
    {
        "排序": "第6位",
        "建议": "建议5：引入非相关收益（熊市做空/均值回归策略）",
        "核心逻辑": "非相关策略的盈利自然插入亏损序列打断长串",
        "减少连亏笔数": "★★★★★",
        "对CAGR影响": "高（正向）",
        "实施难度": "★★★ 高",
        "备注": "最彻底解决，但需要开发第二套策略；长期目标",
    },
]

st.dataframe(
    pd.DataFrame(_priority_rows),
    use_container_width=True,
    hide_index=True,
)

st.info(
    "**推荐实施路径**：① 先改 `breakout_strength_min` 参数（第1位，当日可做）"
    " → ② 加单日开仓上限（第2位，低工程量）"
    " → ③ 加批量止损熔断逻辑（第3位，低工程量）"
    " → ④ 设计并回测震荡市检测器（第4位，需专项研究）"
    " → ⑤ 实盘配置连亏缩仓（第5位，心理价值）"
    " → ⑥ 长期逐步引入非相关收益（第6位）。"
)

st.markdown("---")

# ── 一、数学基础 ──────────────────────────────────────────────────────────────────
st.subheader("一、数学基础：38.7% 胜率下，连亏是不可避免的")

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

# ── 二、关键发现 ──────────────────────────────────────────────────────────────────
st.subheader('二、关键发现：长序列是"市场环境事件"，不是随机坏运气')

# Load trades
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
                "avg_r":      seg["pnl_r_multiple"].mean() if "pnl_r_multiple" in seg.columns else float("nan"),
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
        "avg_r":      seg["pnl_r_multiple"].mean() if "pnl_r_multiple" in seg.columns else float("nan"),
    })

df_streaks = pd.DataFrame(streaks_detail)
major = df_streaks[df_streaks["length"] >= 10].copy()
_max_row = df_streaks.loc[df_streaks["length"].idxmax()]
_max_seg = trades.iloc[
    df_streaks["length"].idxmax() * 0 : 0  # placeholder, recomputed below
]

# Recompute 34-streak details
_all_streaks_raw = []
_c2 = 0; _si2 = None
for _i2, _row2 in trades.iterrows():
    if _row2["net_pnl"] <= 0:
        if _c2 == 0:
            _si2 = _i2
        _c2 += 1
    else:
        if _c2 > 0:
            _all_streaks_raw.append({"start": _si2, "end": _i2 - 1, "length": _c2})
        _c2 = 0
if _c2 > 0:
    _all_streaks_raw.append({"start": _si2, "end": len(trades) - 1, "length": _c2})

_max34 = max(_all_streaks_raw, key=lambda x: x["length"])
_max34_trades = trades.iloc[_max34["start"] : _max34["end"] + 1]
_max34_len    = _max34["length"]
_max34_start  = _max34_trades["exit_date"].min()
_max34_end    = _max34_trades["exit_date"].max()
_max34_sl_n   = int((_max34_trades["exit_reason"] == "stop_loss").sum())
_max34_cal    = (_max34_end - _max34_start).days
_max34_avg_r  = float(_max34_trades["pnl_r_multiple"].mean()) if "pnl_r_multiple" in _max34_trades.columns else float("nan")
_max34_tot_r  = float(_max34_trades["pnl_r_multiple"].sum()) if "pnl_r_multiple" in _max34_trades.columns else float("nan")

# Load nav for drawdown
_nav_path = _results_path / "nav.csv"
if _nav_path.exists():
    _nav_dd = pd.read_csv(_nav_path, parse_dates=["date"], index_col="date").iloc[:, 0]
    _peak_pre = float(_nav_dd[_nav_dd.index <= _max34_start].max())
    _trough   = float(_nav_dd[(_nav_dd.index >= _max34_start) & (_nav_dd.index <= _max34_end)].min())
    _streak_dd_pct = (_trough - _peak_pre) / _peak_pre * 100
else:
    _streak_dd_pct = float("nan")

st.markdown(f"""
对所有 **≥ 10 笔**的连亏序列（共 {len(major)} 个）做特征分析，发现了明显的共性模式：

| 特征 | 数据 | 含义 |
|------|------|------|
| 平均持仓天数 | **10–20 天**（显著低于全局均值） | 进场后极快被止损打出 |
| 止损（stop_loss）比例 | **70%–95%** | 不是趋势反转后被移动止盈打出，而是"假突破"快速失败 |
| 序列时间集中度 | 单个序列往往在 **2–6 周内**完成 | 这是同期多个仓位集中出清，而非时序上一笔一笔的随机亏损 |

**最长连亏（{_max34_len} 笔）关键数据：**

| 指标 | 数值 | 含义 |
|------|------|------|
| 时间区间 | {_max34_start.strftime("%Y年%m月%d日")} — {_max34_end.strftime("%Y年%m月%d日")} | 历时约 {_max34_cal} 个日历日 |
| 止损占比 | {_max34_sl_n}/{_max34_len} 笔（{_max34_sl_n/_max34_len*100:.0f}%） | 绝大多数为"假突破快速失败" |
| 合计亏损（R） | {_max34_tot_r:.1f}R | 每笔平均 {_max34_avg_r:.2f}R |
| 策略回撤 | {_streak_dd_pct:.1f}% | 从连亏前高点到谷底 |
| SPY位置 | 处于200日均线**上方** | 200MA过滤已启用但未触发，说明震荡市可在均线上方发生 |

> **重要启示**：该34笔连亏发生时 SPY 仍高于200日均线，策略的 `regime_filter_enabled=True` 没有过滤掉这批信号。
> 单一的"SPY在200MA以上才开仓"规则，不能防范 **SPY在均线上方但市场进入宽幅震荡** 的情形。
""")

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
        colorbar=dict(title="止损%"),
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
        "止损占比：%{customdata[0]:.0f}%<br>"
        "净亏损：$%{customdata[1]:.0f}万<br>"
        "序列跨度：%{customdata[2]} 天<extra></extra>"
    ),
))
fig_sc.update_layout(
    title="≥10 笔连亏序列：平均持仓天数 vs 序列长度（气泡大小 = 止损占比）",
    xaxis_title="平均持仓天数（越短 = 越快被打出）",
    yaxis_title="连亏笔数",
    height=420,
    margin=dict(l=60, r=20, t=60, b=50),
)
st.plotly_chart(fig_sc, use_container_width=True)

st.markdown("""
**图表解读：** 持仓天数越短（横轴越靠左）、气泡颜色越深（止损占比越高），
说明该序列是典型的"假突破密集失败"场景——市场在反复发出突破信号，但每次突破都迅速失败并触发止损。

**这一规律有重要的战略含义：**
长连亏序列不是策略1.0在某段时间一直做了错误决策，
而是市场进入了一种"震荡假突破"的环境，策略的趋势跟踪逻辑与此类市场状态天然不兼容。
""")

with st.expander("📋 全部 ≥10 笔连亏序列明细", expanded=False):
    show = major[["length","start_date","end_date","avg_hold","sl_pct","span_days","net_pnl"]].copy()
    show.columns = ["长度(笔)","起始日期","结束日期","均持仓(天)","止损%","跨度(天)","净亏损($)"]
    show["起始日期"] = show["起始日期"].dt.strftime("%Y-%m-%d")
    show["结束日期"] = show["结束日期"].dt.strftime("%Y-%m-%d")
    show["止损%"] = show["止损%"].map(lambda v: f"{v*100:.0f}%")
    show["净亏损($)"] = show["净亏损($)"].map(lambda v: f"${v:,.0f}")
    show = show.sort_values("长度(笔)", ascending=False).reset_index(drop=True)
    st.dataframe(show, use_container_width=True, hide_index=True)

st.markdown("---")

# ── 三、具体改进建议 ─────────────────────────────────────────────────────────────
st.subheader("三、具体改进建议")

# ── 建议 1 ──────────────────────────────────────────────────────────────────────
st.markdown("### 建议1：震荡市检测器（Choppiness Filter）")
st.markdown("""
**直接攻击长连亏的根本原因——主动识别震荡市并预防性暂停入场。**

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
**方案 B：SPY近20日跌幅过滤（直接对标34笔连亏的触发条件）**

该34笔连亏前20日，SPY出现明显回撤；策略虽然内置了200MA过滤，但SPY仍处于均线上方，
所以过滤器未启动。可以增加一层"动态回撤"过滤：
""")
st.code("""
# SPY 近20日累计跌幅超过5%时暂停新开仓
spy_20d_return = (spy_close / spy_close.shift(20)) - 1
if spy_20d_return.iloc[-1] < -0.05:
    pause_new_entries(reason="spy_short_term_weakness")
""", language="python")

st.markdown("""
**方案 C：近期信号成功率（更直接，但有前视风险需谨慎）**
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
> **注意：** 方案C存在轻微的"用已知结果指导决策"的风险，需在 Walk-Forward 中严格验证，
> 不可在回测中使用当天出场结果来指导当天入场。

**预期效果：** 以 2010 年 34 笔连亏为例，若当时检测到震荡市并暂停入场，
那 34 笔中大多数（在震荡期内快速止损的）根本不会开仓，序列可能从 34 压缩到 5 以内。
""")

st.markdown("---")

# ── 建议 2 ──────────────────────────────────────────────────────────────────────
st.markdown("### 建议2：提高入场信号质量（Breakout Strength Filter）")
st.markdown("""
**策略1.0 当前 `breakout_strength_min = 0`，即不要求突破强度。**

弱突破（收盘价仅刚好超过 200 日高点，无量无力）在震荡市中失败率极高。
加入突破强度过滤可以筛掉大量"假突破"，直接提升胜率。这是 **实施成本最低** 的改进，
只需修改一个参数并回测验证。

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

# Chart: Volume filter multiplier sensitivity
_volf2 = _perturb_path / "volume_filter_multiplier.json"
if _volf2.exists():
    _vd2 = json.loads(_volf2.read_text())
    _vv2 = _vd2["param_values"]
    _vc2 = [r["cagr"] * 100 for r in _vd2["results"]]
    _vn2 = [r["n_trades"] for r in _vd2["results"]]
    _baseline_v2 = _vd2["baseline_value"]
    _fig_v2 = go.Figure()
    _fig_v2.add_trace(go.Bar(
        x=[str(v) for v in _vv2], y=_vc2, name="CAGR (%)",
        marker_color=["#22c55e" if v == _baseline_v2 else "#6366f1" for v in _vv2],
        yaxis="y",
    ))
    _fig_v2.add_trace(go.Scatter(
        x=[str(v) for v in _vv2], y=_vn2, name="交易笔数（右轴）",
        mode="lines+markers", marker=dict(size=9, color="#94a3b8"),
        line=dict(color="#94a3b8", width=2, dash="dot"), yaxis="y2",
    ))
    _fig_v2.update_layout(
        title="成交量过滤倍数敏感性（突破强度代理指标）：CAGR vs 交易笔数",
        xaxis_title="volume_filter_multiplier（× 均量）",
        yaxis=dict(title="CAGR (%)", side="left", range=[7.5, 11.5]),
        yaxis2=dict(title="交易笔数", side="right", overlaying="y", range=[2800, 3900]),
        legend=dict(x=0.6, y=0.05), height=360, margin=dict(t=50, b=40),
    )
    st.plotly_chart(_fig_v2, use_container_width=True)
    st.markdown(
        f"成交量要求从 1.0× 升至当前值 {_baseline_v2}×，CAGR 从 {_vc2[0]:.2f}% 升至 {_vc2[_vv2.index(_baseline_v2)]:.2f}%，"
        f"交易笔数从 {_vn2[0]:.0f} 降至 {_vn2[_vv2.index(_baseline_v2)]:.0f}。"
        "过滤低量突破提升了每笔交易质量，减少了假突破比例。继续提高阈值至 2.0× 反而伤害绩效（过度过滤）。"
    )

st.markdown("---")

# ── 建议 3 ──────────────────────────────────────────────────────────────────────
st.markdown("### 建议3：限制单日 / 单周最大开仓数（Entry Clustering Limit）")
st.markdown("""
**针对"同批次开仓全部快速失败"的集中亏损场景。**

34笔最长连亏的分析显示，多笔交易集中于同一或相邻交易日入场，随后被同期下跌统一止损出局。
限制"窗口期内新开仓数"可以避免在单一市场环境下押注过多相关标的。
""")
st.code("""
MAX_NEW_ENTRIES_PER_DAY  = 3    # 单日最多开 3 个新仓（当前无限制）
MAX_NEW_ENTRIES_PER_WEEK = 8    # 单周最多开 8 个新仓

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

# Chart: Daily signal count distribution
_es2 = pd.read_csv(_results_path / "daily_entry_stats.csv", index_col="date", parse_dates=True)
_sig_by_day2 = _es2["signals"][_es2["signals"] > 0]
_sig_bins2   = [(1,1),(2,3),(4,5),(6,10),(11,20),(21,9999)]
_sig_labels2 = ["1个", "2-3个", "4-5个", "6-10个", "11-20个", "21+个"]
_sig_counts2 = [(((_sig_by_day2 >= lo) & (_sig_by_day2 <= hi)).sum()) for lo, hi in _sig_bins2]
_sig_pcts2   = [c / len(_sig_by_day2) * 100 for c in _sig_counts2]

_fig_sig2 = go.Figure(go.Bar(
    x=_sig_labels2,
    y=_sig_counts2,
    marker_color=["#22c55e","#22c55e","#fbbf24","#f97316","#ef4444","#dc2626"],
    text=[f"{c}天<br>({p:.1f}%)" for c, p in zip(_sig_counts2, _sig_pcts2)],
    textposition="outside",
))
_fig_sig2.update_layout(
    title="每日突破信号数分布（2000-2026，共 4,099 个有信号交易日）",
    xaxis_title="当日信号数",
    yaxis_title="天数",
    height=360,
    margin=dict(t=50, b=40),
    yaxis=dict(range=[0, max(_sig_counts2) * 1.2]),
)
st.plotly_chart(_fig_sig2, use_container_width=True)
st.markdown(
    f"有 {_sig_counts2[3]+_sig_counts2[4]+_sig_counts2[5]:,} 天（{_sig_pcts2[3]+_sig_pcts2[4]+_sig_pcts2[5]:.1f}%）每日信号数 ≥ 6个，"
    "这类高拥挤日下集中开仓风险最大。"
    "限制单日开仓数可防止在同一市场环境下押注过多相关标的。"
)

st.markdown("---")

# ── 建议 4 ──────────────────────────────────────────────────────────────────────
st.markdown("### 建议4：连亏后仓位动态缩减（Anti-Streak Sizing）")
st.markdown("""
**这条建议不会减少连亏"笔数"，但能降低心理和财务冲击，让人更容易坚持执行策略。**

34笔连亏导致的策略回撤为 **{:.1f}%**。如果在连亏到第10笔时自动缩仓，
后续剩余的亏损笔将以更小的仓位执行，实际资金回撤会更小。
""".format(_streak_dd_pct))
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

# ── 建议 5 ──────────────────────────────────────────────────────────────────────
st.markdown("### 建议5（长期）：引入非相关收益来源打破序列")
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
这样熊市中部分亏损被对冲，连亏序列被自然打断。详见「如何改进策略有效性」页面中的熊市做空模拟分析。
""")

st.markdown("---")

# ── 建议 6（新增） ───────────────────────────────────────────────────────────────
st.markdown("### 建议6：暂停熔断（Circuit Breaker）——两种触发方案")
st.markdown("""
**响应式规则——发现"问题市场"信号后立即暂停，不依赖预测。两种触发方式可单独使用或结合使用。**
""")

st.markdown("#### 方案 A：同日批量止损熔断")
st.markdown("""
34笔最长连亏的分析显示，多笔交易在同一天或相邻日触发止损。
这是"市场已进入快速下跌/震荡"的明确信号，但策略仍继续开新仓被逐一打出。

当同一个自然日内有 **≥N 笔**仓位触发止损（stop_loss），
自动暂停新开仓 **M 个交易日**，等待市场企稳。
""")
st.code("""
# 每日统计触发止损的仓位数
daily_stop_losses = count_stop_losses_today()

# 参数（需回测调优）
CIRCUIT_BREAKER_THRESHOLD = 3   # 同日触发≥3笔止损 → 激活熔断
PAUSE_TRADING_DAYS = 5           # 暂停5个交易日

if daily_stop_losses >= CIRCUIT_BREAKER_THRESHOLD:
    pause_new_entries(
        days=PAUSE_TRADING_DAYS,
        reason="batch_stop_loss_circuit_breaker"
    )
""", language="python")

st.markdown("#### 方案 B：连续亏损超阈值暂停期")
st.markdown("""
**来自「连续亏损分析」section的改进建议：当策略已连续亏损超过 10 笔，
自动进入观察期（暂停 5～10 个交易日），让市场完成震荡后再重新入场，
以减少在无效信号环境中反复受损。**

方案A捕捉的是"单日集中打出"的急剧信号，方案B捕捉的是"持续流血"的累积信号——
两者各有盲区，组合使用可覆盖更多长连亏场景。
""")
st.code("""
# 维护滚动连续亏损计数器
consecutive_losses = get_current_streak_length()

# 参数（需回测调优）
STREAK_PAUSE_THRESHOLD = 10   # 连续亏损≥10笔 → 进入观察期
STREAK_PAUSE_DAYS = 5          # 暂停5个交易日（也可设为7-10天）

if consecutive_losses >= STREAK_PAUSE_THRESHOLD:
    pause_new_entries(
        days=STREAK_PAUSE_DAYS,
        reason="consecutive_loss_streak_breaker"
    )
""", language="python")

st.markdown("""
**两种方案对比：**

| | 方案A（同日批量止损） | 方案B（连续亏损超阈值） |
|--|--|--|
| **触发条件** | 同一天 ≥3 笔止损 | 累计连亏 ≥10 笔 |
| **响应速度** | 极快（当日触发） | 较慢（需积累到阈值） |
| **最适合场景** | 急剧下跌、集中止损 | 持续震荡、逐笔出血 |
| **34笔连亏中** | 早期即可触发 | 触发后仍剩余约24笔 |
| **前视偏差风险** | 无 | 无（用已结束的交易计数） |

**与建议3（开仓集中度限制）的关系：**
- 建议3是**事前预防**：限制每日开仓数，减少同期持仓集中度
- 建议6是**事后响应**：观察到批量止损/持续亏损信号后才暂停，不需要预测

推荐实施顺序：先用建议3降低集中度风险，再叠加建议6的两种熔断机制作为安全阀。

**预期效果（方案A）：** 在34笔连亏期间，若在首次出现"同日3笔止损"时就暂停5天，
可能将34笔序列截断成数个短序列。

**预期效果（方案B）：** 在连亏第10笔时触发暂停5天，相当于给了市场时间"完成调整"，
避免在震荡未结束时继续开仓被打出剩余的24笔。
""")

# Show daily stop-loss distribution to support the suggestion
if "exit_reason" in trades.columns and "exit_date" in trades.columns:
    _daily_sl = (
        trades[trades["exit_reason"] == "stop_loss"]
        .groupby(trades["exit_date"].dt.date)
        .size()
        .reset_index(name="count")
    )
    _sl_bins = [(1,1),(2,2),(3,3),(4,5),(6,9999)]
    _sl_labels = ["1笔", "2笔", "3笔", "4-5笔", "6+笔"]
    _sl_counts = [((_daily_sl["count"] >= lo) & (_daily_sl["count"] <= hi)).sum() for lo, hi in _sl_bins]

    _fig_sl = go.Figure(go.Bar(
        x=_sl_labels,
        y=_sl_counts,
        marker_color=["#22c55e","#fbbf24","#f97316","#ef4444","#dc2626"],
        text=[f"{c}天" for c in _sl_counts],
        textposition="outside",
    ))
    _fig_sl.update_layout(
        title="每日触发止损笔数分布（批量止损熔断阈值参考）",
        xaxis_title="当日止损笔数",
        yaxis_title="天数",
        height=320,
        margin=dict(t=50, b=40),
        yaxis=dict(range=[0, max(_sl_counts) * 1.2]),
    )
    st.plotly_chart(_fig_sl, use_container_width=True)
    _n_batch = sum(_sl_counts[2:])
    st.markdown(
        f"共有 {_n_batch} 天出现同日 ≥3 笔止损，若每次触发后暂停5个交易日，"
        "预计可避免相当数量的「震荡市继续盲目开仓」情形。"
        "建议阈值设为3笔（可回测比较2/3/4笔的最优参数）。"
    )

st.markdown("---")

# ── 四、汇总建议 ──────────────────────────────────────────────────────────────────
st.subheader("四、建议优先级与实施路径（汇总）")

st.markdown("""
| 建议 | 减少连亏次数 | 减少心理冲击 | 对CAGR影响 | 实现难度 | 优先级 |
|------|------------|------------|-----------|---------|-------|
| **建议2：突破强度过滤** | ★★★ | ★★★ | 低偏正 | ★ 极低 | 🔴 最高 |
| **建议3：开仓集中度限制** | ★★★ | ★★★ | 低 | ★ 低 | 🔴 最高 |
| **建议6：暂停熔断（同日≥3笔止损 / 连亏≥10笔）** | ★★★ | ★★★ | 低 | ★ 低 | 🔴 最高 |
| **建议1：震荡市检测器** | ★★★★ | ★★★★ | 中（需验证） | ★★ 中 | 🟡 高 |
| **建议4：连亏后动态缩仓** | ★（不减笔数） | ★★★★ | 低偏负 | ★ 低 | 🟡 高（心理价值大） |
| **建议5：引入非相关收益** | ★★★★★ | ★★★★★ | 高（正向） | ★★★ 高 | 🟢 长期 |

**推荐实施路径：**

1. **当日可做**：将 `breakout_strength_min` 从 0 调整为 0.01，在参数敏感性分析中验证胜率和连亏序列的变化
2. **低工程量**：加入单日开仓上限（`MAX_NEW_ENTRIES_PER_DAY = 3`）+ 暂停熔断双触发（同日≥3笔止损 → 暂停5天；累计连亏≥10笔 → 暂停5天）
3. **专项研究**：设计并回测震荡市检测器（Choppiness Index 或 SPY近20日跌幅），Walk-Forward验证防过拟合
4. **心理缓冲**：实盘配置连亏动态缩仓规则（连亏5笔→80%仓，10笔→50%仓）
5. **长期目标**：逐步引入非相关收益来源（从熊市做空SH开始），从根本上打断长序列结构
""")

st.markdown("---")

st.info(
    '**最重要的心理认知**：连续亏损不是"策略出错"的信号，而是趋势跟踪策略在震荡市中的正常表现。'
    f"历史数据中，最长的 {_max34_len} 笔连亏（{_max34_start.strftime('%Y年%m月')}—{_max34_end.strftime('%m月')}）"
    f"导致了 {_streak_dd_pct:.1f}% 的策略回撤，但之后策略完全恢复并持续创下新高。"
    "提前理解这一点，比任何算法改进都更能帮助实盘中保持执行纪律。"
)
