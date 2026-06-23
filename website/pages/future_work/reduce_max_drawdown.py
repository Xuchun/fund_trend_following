"""如何降低最大回撤"""

import sys, json
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.style import show_df
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

_results = _root / "results" / "v1_unbiased_60m_2000"

st.title("如何降低最大回撤")
st.markdown("基于参数敏感性回测数据（2000–2026）和交易行为深度分析，提出三种降低最大回撤的具体方法")

st.markdown("---")

# ── 数据加载 ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400)
def _load_perturb(param: str):
    p = _results / "perturbation" / f"{param}.json"
    return json.loads(p.read_text()) if p.exists() else None

@st.cache_data(ttl=86400)
def _load_trades():
    return pd.read_csv(_results / "trades.csv", parse_dates=["entry_date", "exit_date"])

_bw    = _load_perturb("breakout_window")
trades = _load_trades()

# ── 当前状态概览 ───────────────────────────────────────────────────────────────
st.subheader("策略1.0 当前最大回撤概况")

_c1, _c2, _c3, _c4 = st.columns(4)
_c1.metric("最大回撤",     "−20.74%", delta_color="inverse")
_c2.metric("回撤持续",     "602 交易日", delta_color="inverse")
_c3.metric("Sharpe 比率",  "0.6342")
_c4.metric("Calmar 比率",  "0.4995")

st.markdown("""
最大回撤发生于 2008–2010 年 GFC 期间，但其深度和持续时间不是单纯的运气问题，
而是由策略的三个结构性特征驱动：

| 问题 | 机制 | 对应改进方法 |
|------|------|------------|
| 突破窗口选择 | 200日高点不一定是噪声最小的信号门槛 | **方法一**：调整 breakout_window |
| 震荡市持续开仓 | Regime Filter 只识别熊市，不识别震荡牛市 | **方法二**：增加 Choppiness Filter |
| 假突破全额止损 | 快速失败的仓位等到 −1.0R 才出场 | **方法三**：假突破快速离场规则 |
""")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
st.subheader("方法一：将突破窗口调整为 breakout_window = 150")
st.markdown("唯一有完整26年回测数据直接验证的参数调整，效果最确定，实现难度最低")

if _bw:
    _bw_df = pd.DataFrame(_bw["results"])
    _bw_df["maxdd_pct"] = _bw_df["max_drawdown"] * 100
    _bw_df["calmar"]    = _bw_df["cagr"] / _bw_df["max_drawdown"].abs()

    _baseline_mdd = _bw_df.loc[_bw_df["param_value"] == 200, "max_drawdown"].values[0]

    _bar_colors = []
    for _, row in _bw_df.iterrows():
        if row["param_value"] == 200:
            _bar_colors.append("#888888")       # 灰色 = baseline
        elif row["max_drawdown"] > _baseline_mdd:  # 更接近0 = 更好
            _bar_colors.append("#2ca02c")       # 绿色 = 优于baseline
        else:
            _bar_colors.append("#d62728")       # 红色 = 差于baseline

    _fig_bw = make_subplots(specs=[[{"secondary_y": True}]])
    _fig_bw.add_trace(go.Bar(
        x=_bw_df["param_value"].astype(str),
        y=_bw_df["maxdd_pct"],
        name="最大回撤 (%)",
        marker_color=_bar_colors,
        text=[f"{v:.2f}%" for v in _bw_df["maxdd_pct"]],
        textposition="outside",
        textfont=dict(size=11),
    ), secondary_y=False)
    _fig_bw.add_trace(go.Scatter(
        x=_bw_df["param_value"].astype(str),
        y=_bw_df["sharpe"],
        name="Sharpe",
        mode="lines+markers",
        marker=dict(size=9, color="#1f77b4", symbol="circle"),
        line=dict(width=2.5, color="#1f77b4"),
    ), secondary_y=True)

    # 标记 baseline 和推荐值
    _fig_bw.add_annotation(
        x="200", y=_baseline_mdd * 100 - 0.5,
        text="← Baseline (200)", showarrow=False,
        font=dict(color="#666", size=10), xanchor="left",
    )
    _fig_bw.add_annotation(
        x="150", y=_bw_df.loc[_bw_df["param_value"]==150,"maxdd_pct"].values[0] - 0.5,
        text="← 推荐 (150)", showarrow=False,
        font=dict(color="#2ca02c", size=10), xanchor="left",
    )

    _fig_bw.update_layout(
        title="突破窗口参数敏感性：最大回撤（柱）vs Sharpe（线）",
        height=420, template="plotly_white",
        legend=dict(orientation="h", y=1.1),
        margin=dict(t=60, b=50), bargap=0.28,
    )
    _fig_bw.update_yaxes(title_text="最大回撤 (%)，越接近 0 越好", secondary_y=False)
    _fig_bw.update_yaxes(title_text="Sharpe 比率", secondary_y=True, showgrid=False)
    _fig_bw.update_xaxes(title_text="突破窗口（天），其余参数保持 baseline 不变")
    st.plotly_chart(_fig_bw, use_container_width=True)

    st.markdown("绿色 = MaxDD 优于 baseline（200日），灰色 = baseline，红色 = MaxDD 差于 baseline")

    # 完整数据表
    _tbl_bw = _bw_df[["param_value","max_drawdown","sharpe","cagr","calmar",
                        "max_dd_duration_days","n_trades"]].copy()
    _tbl_bw.columns = ["突破窗口(天)","最大回撤","Sharpe","CAGR","Calmar","最长回撤(天)","交易笔数"]
    _tbl_bw["最大回撤"] = _tbl_bw["最大回撤"].map(lambda v: f"{v*100:.2f}%")
    _tbl_bw["CAGR"]    = _tbl_bw["CAGR"].map(lambda v: f"{v*100:+.2f}%")
    _tbl_bw["Sharpe"]  = _tbl_bw["Sharpe"].map(lambda v: f"{v:.4f}")
    _tbl_bw["Calmar"]  = _tbl_bw["Calmar"].map(lambda v: f"{v:.4f}")
    _tbl_bw["最长回撤(天)"] = _tbl_bw["最长回撤(天)"].map(int)
    _tbl_bw["交易笔数"] = _tbl_bw["交易笔数"].map(int)
    show_df(_tbl_bw, use_container_width=True, hide_index=True)

    _r150 = _bw_df[_bw_df["param_value"] == 150].iloc[0]
    _r200 = _bw_df[_bw_df["param_value"] == 200].iloc[0]
    _dd_impr = (_r200["max_drawdown"] - _r150["max_drawdown"]) / abs(_r200["max_drawdown"]) * 100
    _calmar_impr = (_r150["calmar"] - _r200["calmar"]) / _r200["calmar"] * 100

    st.success(f"""
**breakout_window = 150 对比 baseline（200）：**

| 指标 | baseline (200) | 推荐 (150) | 变化 |
|------|--------------|-----------|------|
| 最大回撤 | {_r200["max_drawdown"]*100:.2f}% | **{_r150["max_drawdown"]*100:.2f}%** | ↓ 改善 {_dd_impr:.1f}% |
| Calmar 比率 | {_r200["calmar"]:.4f} | **{_r150["calmar"]:.4f}** | ↑ 提升 {_calmar_impr:.1f}% |
| Sharpe 比率 | {_r200["sharpe"]:.4f} | {_r150["sharpe"]:.4f} | ↓ 小幅下降 {(_r200["sharpe"]-_r150["sharpe"])/_r200["sharpe"]*100:.1f}% |
| CAGR | {_r200["cagr"]*100:+.2f}% | {_r150["cagr"]*100:+.2f}% | 基本持平 |

这是所有已验证的单参数调整中，**MaxDD 改善幅度最大、Calmar 提升最显著**的选项。
""")

    st.markdown("""
**为什么更短的窗口反而降低了最大回撤？**

150日高点比200日高点"门槛更低"，乍看应该让更多假突破信号进来才对。
但数据揭示了相反的逻辑：

- **200日高点**是一个惯性很大的门槛。当价格终于突破200日高点时，
  往往已有大量持仓者等待在这个价位出货（前高套牢盘）。
  策略在趋势的**中后期**才入场，此后回撤风险更大。

- **150日高点**更早捕捉趋势（从趋势起点附近入场），
  此时套牢盘阻力小，价格更容易继续上行而不是回头。
  入场较早 → 浮盈更多 → ATR 移动止损收紧更快 → 即使回头，损失也更小。
""")
else:
    st.info("⏳ breakout_window 参数敏感性数据加载中，请稍后刷新页面。")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
st.subheader("方法二：增加震荡市检测器（Choppiness Filter）")
st.markdown("解决现有 Regime Filter 的核心盲区：能识别熊市，但无法识别震荡牛市")

# ── 连亏序列分析 ──────────────────────────────────────────────────────────────
_st = trades.sort_values("exit_date").reset_index(drop=True)
_pnl = _st["net_pnl"].values

_streaks = []
_cur, _s0 = 0, 0
for i, v in enumerate(_pnl):
    if v <= 0:
        if _cur == 0:
            _s0 = i
        _cur += 1
    else:
        if _cur > 0:
            seg = _st.iloc[_s0:_s0 + _cur]
            _streaks.append({
                "length":   _cur,
                "start_dt": seg["exit_date"].min(),
                "avg_hold": seg["holding_days"].mean(),
                "sl_pct":   (seg["exit_reason"] == "stop_loss").mean(),
                "pnl_m":    seg["net_pnl"].sum() / 1e6,
            })
        _cur = 0
if _cur > 0:
    seg = _st.iloc[_s0:_s0 + _cur]
    _streaks.append({
        "length":   _cur,
        "start_dt": seg["exit_date"].min(),
        "avg_hold": seg["holding_days"].mean(),
        "sl_pct":   (seg["exit_reason"] == "stop_loss").mean(),
        "pnl_m":    seg["net_pnl"].sum() / 1e6,
    })

_df_sk = pd.DataFrame(_streaks)
_major_sk = _df_sk[_df_sk["length"] >= 7].copy()

# 散点图：时间线上的连亏序列
_fig_sk = go.Figure()
_fig_sk.add_trace(go.Scatter(
    x=_major_sk["start_dt"],
    y=_major_sk["length"],
    mode="markers+text",
    text=_major_sk["start_dt"].dt.strftime("%Y-%m"),
    textposition="top center",
    textfont=dict(size=9),
    marker=dict(
        size=_major_sk["length"] * 1.3 + 5,
        color=_major_sk["sl_pct"],
        colorscale="Reds",
        cmin=0.4, cmax=1.0,
        colorbar=dict(title="止损<br>触发率", thickness=14),
        showscale=True,
        line=dict(width=1, color="white"),
    ),
    customdata=np.column_stack([_major_sk["avg_hold"], _major_sk["pnl_m"].abs()]),
    hovertemplate=(
        "<b>%{text}</b><br>"
        "连亏笔数：%{y}<br>"
        "平均持仓：%{customdata[0]:.1f} 天<br>"
        "合计亏损：$%{customdata[1]:.1f}M<extra></extra>"
    ),
))


_fig_sk.update_layout(
    title="≥7 笔连亏序列时间分布（气泡越大 = 连亏越长，颜色越深 = 止损触发率越高）",
    xaxis_title="序列起始日期",
    yaxis_title="连亏笔数",
    height=400,
    template="plotly_white",
    margin=dict(t=60, b=50, r=80),
)
st.plotly_chart(_fig_sk, use_container_width=True)

# 统计数字
_n_major   = len(_major_sk)
_total_loss = _major_sk["pnl_m"].sum()
_n_sl_dom  = int((_major_sk["sl_pct"] > 0.7).sum())
_m1, _m2, _m3 = st.columns(3)
_m1.metric("≥7笔连亏序列", f"{_n_major} 个")
_m2.metric("合计净亏损",    f"${abs(_total_loss):.1f}M")
_m3.metric("止损主导(>70%)的序列", f"{_n_sl_dom} / {_n_major}")

st.markdown("""
**图表解读（关键洞察）：**

- **气泡越大且颜色越深**：该连亏序列以"快速止损"为主——
  入场后平均 10–20 天内就被打出（全局均值 42 天），说明市场在密集发出假突破信号
- **这类序列集中在 2–6 周内完成**：不是时间序列上一笔一笔的随机亏损，
  而是同批仓位集中失败、集中出清
- **这就是 MaxDD 的微观积累机制**：每笔 −1.0R 的止损，
  在组合层面叠加成 NAV 的持续下滑

**现有 Regime Filter 的盲区：**

当前的 SPY SMA200 过滤器在牛市中完全开放策略开仓，但 **震荡牛市**（SPY 高于 SMA200，
但方向混乱）同样会引发大量假突破。典型案例：2021年11月那次 431天深度回撤，
彼时 SPY 持续高于 SMA200，但策略持仓已在大量失血。

**Choppiness Index**（CI）是一个专门衡量"市场是震荡还是趋势"的指标：
""")

st.code("""
import numpy as np

def choppiness_index(high: pd.Series, low: pd.Series, period: int = 14) -> pd.Series:
    \"\"\"
    CI > 61.8：市场处于震荡状态，趋势信号可信度低
    CI < 38.2：市场处于强趋势状态，趋势信号高可信度
    \"\"\"
    sum_atr   = (high - low).rolling(period).sum()
    total_rng = high.rolling(period).max() - low.rolling(period).min()
    ci = 100 * np.log10(sum_atr / total_rng) / np.log10(period)
    return ci

# 在策略入场逻辑中加入过滤：
ci_today = choppiness_index(spy_high, spy_low, period=14).iloc[-1]
if ci_today > 61.8:
    skip_all_new_entries(reason="choppy_market")   # 今日不开任何新仓
""", language="python")

st.info("""
**预期效果：**

在震荡市检测到后暂停新开仓，组合处于"收缩模式"——
旧仓位按正常止损/止盈出场，但不再新增亏损仓位。
NAV 不再主动下滑，而是等待市场恢复趋势性后再重新开仓。

这直接截断了最大回撤的积累过程，而非等到已经亏了大量资金才被动应对。
""")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
st.subheader("方法三：假突破快速离场（Failed Breakout Rule）")
st.markdown("针对开仓后快速失败的交易：这批交易贡献了最大的绝对亏损，却对利润几乎没有贡献")

# ── 持仓天数分桶分析 ──────────────────────────────────────────────────────────
_total_pnl = trades["net_pnl"].sum()
_total_n   = len(trades)

_bkt_defs = [
    ("0–30天",    0,   30),
    ("31–90天",  31,   90),
    ("91–180天", 91,  180),
    ("181–365天",181, 365),
    ("1–2年",    366, 730),
    ("2年以上",  731, 9999),
]
_bkt_rows = []
for label, lo, hi in _bkt_defs:
    sub = trades[(trades["holding_days"] >= lo) & (trades["holding_days"] <= hi)]
    n   = len(sub)
    wr  = (sub["net_pnl"] > 0).mean() * 100 if n > 0 else 0
    avg_r = sub["pnl_r_multiple"].mean() if n > 0 else 0
    pnl = sub["net_pnl"].sum()
    _bkt_rows.append({
        "持仓区间": label,
        "笔数": n,
        "笔数占比": n / _total_n * 100,
        "胜率": wr,
        "平均R": avg_r,
        "净盈亏M": pnl / 1e6,
        "占总利润": pnl / _total_pnl * 100,
    })
_df_bkt = pd.DataFrame(_bkt_rows)

# 双轴图：净盈亏（柱）+ 胜率（线）
_fig_hld = make_subplots(specs=[[{"secondary_y": True}]])
_bkt_colors = ["#d62728" if v < 0 else "#2ca02c" for v in _df_bkt["净盈亏M"]]
_fig_hld.add_trace(go.Bar(
    x=_df_bkt["持仓区间"],
    y=_df_bkt["净盈亏M"],
    name="净盈亏（$M）",
    marker_color=_bkt_colors,
    text=[f"${v:+.1f}M" for v in _df_bkt["净盈亏M"]],
    textposition="outside",
    textfont=dict(size=11),
), secondary_y=False)
_fig_hld.add_trace(go.Scatter(
    x=_df_bkt["持仓区间"],
    y=_df_bkt["胜率"],
    name="胜率 (%)",
    mode="lines+markers",
    marker=dict(size=9, color="#1f77b4"),
    line=dict(width=2.5, color="#1f77b4"),
), secondary_y=True)
_fig_hld.update_layout(
    title="持仓天数分桶：净盈亏（柱）& 胜率（线）",
    height=420, template="plotly_white",
    legend=dict(orientation="h", y=1.1),
    margin=dict(t=60, b=50), bargap=0.3,
)
_fig_hld.update_yaxes(title_text="净盈亏（$M）", secondary_y=False)
_fig_hld.update_yaxes(title_text="胜率 (%)", secondary_y=True, showgrid=False)
_fig_hld.update_xaxes(title_text="持仓天数区间")
st.plotly_chart(_fig_hld, use_container_width=True)

# 数据表
_tbl_bkt = _df_bkt.copy()
_tbl_bkt["笔数（占比）"] = _tbl_bkt.apply(lambda r: f"{int(r['笔数'])}（{r['笔数占比']:.1f}%）", axis=1)
_tbl_bkt["胜率"]  = _tbl_bkt["胜率"].map(lambda v: f"{v:.1f}%")
_tbl_bkt["平均R"] = _tbl_bkt["平均R"].map(lambda v: f"{v:+.2f}R")
_tbl_bkt["净盈亏"] = _tbl_bkt["净盈亏M"].map(lambda v: f"${v:+.1f}M")
_tbl_bkt["占总利润"] = _tbl_bkt["占总利润"].map(lambda v: f"{v:+.1f}%")
show_df(
    _tbl_bkt[["持仓区间","笔数（占比）","胜率","平均R","净盈亏","占总利润"]],
    use_container_width=True, hide_index=True,
)

# 关键数字
_r030 = _df_bkt[_df_bkt["持仓区间"] == "0–30天"].iloc[0]
_n030     = int(_r030["笔数"])
_wr030    = _r030["胜率"]
_pnl030   = _r030["净盈亏M"]

st.error(f"""
**核心数据：0–30天的 {_n030:,} 笔交易（占总数 {_r030["笔数占比"]:.1f}%），
胜率仅 {_wr030:.1f}%，合计净亏损 ${abs(_pnl030):.1f}M。**

这批交易几乎都是"假突破"——开仓后股价迅速回头，触发止损，每笔亏损约 −1.0R。
它们是最大回撤的核心来源：在深度回撤期，每一笔 −1R 不断叠加，
形成组合 NAV 的持续下行，把最大回撤一步步拉深。
""")

# 假突破细化分析
_fb_proxy = trades[(trades["holding_days"] <= 30) & (trades["exit_reason"] == "stop_loss")]
_n_fb  = len(_fb_proxy)
_pnl_fb = _fb_proxy["net_pnl"].sum() / 1e6
_avg_r_fb = _fb_proxy["pnl_r_multiple"].mean()

# R 倍数分布（0–30天 止损出场的交易）
_fig_rdist = go.Figure()
_fig_rdist.add_trace(go.Histogram(
    x=_fb_proxy["pnl_r_multiple"],
    nbinsx=40,
    marker_color="#d62728",
    opacity=0.8,
    name="0–30天止损交易",
))
_fig_rdist.add_vline(x=_avg_r_fb, line_dash="dash", line_color="#333",
                     annotation_text=f"均值 {_avg_r_fb:.2f}R",
                     annotation_position="top right")
_fig_rdist.update_layout(
    title=f"0–30天止损交易的 R 倍数分布（共 {_n_fb:,} 笔）",
    xaxis_title="R 倍数（负值 = 亏损）",
    yaxis_title="交易笔数",
    height=340,
    template="plotly_white",
    margin=dict(t=60, b=50),
)
st.plotly_chart(_fig_rdist, use_container_width=True)

st.markdown(f"""
**数据摘要：**

- 0–30天内被止损打出的交易：**{_n_fb:,} 笔**
- 平均 R 倍数：**{_avg_r_fb:.3f}R**（几乎等于完整的 −1.0R）
- 合计亏损：**${abs(_pnl_fb):.1f}M**

分布图显示绝大多数集中在 −1.0R 附近，说明这批交易几乎没有任何进入浮盈阶段——
开仓后直接从入场价跌到止损价出场。这正是假突破的典型模式。
""")

st.markdown("""
**改进规则：假突破快速离场**

若入场后 **N 天内**（建议 N = 10），收盘价跌回突破基准线（入场时的 N日高点）以下，立刻离场。
此时损失约为 −0.3R（价格从入场价跌回突破线的距离），远小于等到全额止损的 −1.0R。
""")

st.code("""
FAILED_BREAKOUT_WINDOW = 10  # 入场后观察窗口

for position in open_positions:
    days_held = (today - position.entry_date).days
    if days_held <= FAILED_BREAKOUT_WINDOW:
        if close_price < position.breakout_level:
            # 价格跌回突破线：约 -0.3R 出场，远优于等到 ATR 止损的 -1.0R
            exit_position(position, reason="failed_breakout")
""", language="python")

# 效果估算
_est_n_applicable = int(_n_fb * 0.5)
_saving_per_trade_r = 0.70
_saving_total_m = _est_n_applicable * _saving_per_trade_r * 0.01 * 10

st.info(f"""
**潜在效果估算（保守假设）：**

- 0–30天止损交易共 {_n_fb:,} 笔
- 假设 50% 适用假突破规则（~{_est_n_applicable:,}笔），每笔节省 0.7R（从 −1.0R 压至 −0.3R）
- 以 $1,000万初始资金、1% 单笔风险计算，每笔节省约 $7,000
- 累计节省：约 **${_est_n_applicable * 0.007:.1f}M**（直接压缩 MaxDD 深度）

⚠️ **关键验证**：需统计"最终 R > 3 的大赢家"中，有多少在入场后 10 天内跌回突破线——
若误伤率低于 5%，此规则的净收益非常明确。
""")

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
st.subheader("综合建议与优先级")

st.markdown("""
| 优先级 | 方法 | MaxDD 改善预期 | 数据支持 | 实现难度 | Sharpe 影响 |
|--------|------|-------------|---------|---------|-----------|
| 🥇 **优先** | 方法一：breakout_window = 150 | **−2.5个百分点（已有回测验证）** | ✅ 完整26年回测 | 极低（改1个参数） | 轻微下降 −4% |
| 🥈 **次选** | 方法三：假突破快速离场 | −2–4个百分点（理论估算） | 📊 交易数据支持 | 低（改 exit 逻辑） | 轻微正向 |
| 🥉 **探索** | 方法二：震荡市检测器 | −2–3个百分点（理论估算） | 📊 连亏数据支持 | 中（新增指标+验证） | 中性偏正 |
""")

st.warning("""
**重要提醒：**

- 方法二和方法三目前尚未经过完整回测验证，效果估算基于交易行为机制分析
- 实际改善幅度必须通过全量回测（2000–2026）+ Walk-Forward OOS 验证后才能确认
- 降低 MaxDD 几乎必然在某些市场环境下以牺牲部分 CAGR 或 Sharpe 为代价，需权衡

**推荐实施路径：**

1. **立即可做**：将 `breakout_window` 改为 150，跑完整回测，直接对比 MaxDD 和 Calmar
2. **下一步**：叠加假突破规则（代码改动集中在 `exit.py`），再跑对比回测
3. **更大工程**：设计 Choppiness Filter，需 CI 阈值扫描 + Walk-Forward 验证，避免过拟合
""")
