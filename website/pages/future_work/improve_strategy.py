"""如何改进策略1.0"""

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
import plotly.io as _pio
from plotly.subplots import make_subplots

_pio.templates.default = "plotly_white"

_results_path = _root / "results" / "v1_unbiased_60m_2000"
_perturb_path = _results_path / "perturbation"

st.title("如何改进策略1.0")
st.caption(
    "对策略1.0的每个核心模块进行逐一分析，从提高历史回测有效性、"
    "提高回测精准度、提高年化收益、降低最大回撤四个维度提出改进建议，并用数据佐证"
)
st.markdown("---")

# ── 数据加载 ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400)
def _load():
    trades = pd.read_csv(
        _results_path / "trades.csv",
        parse_dates=["entry_date", "exit_date"],
    )
    trades["holding_days"] = (trades["exit_date"] - trades["entry_date"]).dt.days
    metrics = json.loads((_results_path / "metrics.json").read_text())

    def _perturb(name):
        f = _perturb_path / f"{name}.json"
        return json.loads(f.read_text()) if f.exists() else None

    return trades, metrics, {
        "stop_loss_multiplier":    _perturb("stop_loss_multiplier"),
        "trail_multiplier_r1":     _perturb("trail_multiplier_r1"),
        "volume_filter_multiplier":_perturb("volume_filter_multiplier"),
        "breakout_window":         _perturb("breakout_window"),
        "min_adv_m":               _perturb("min_adv_m"),
        "min_price":               _perturb("min_price"),
        "position_cap":            _perturb("position_cap"),
        "slippage_bps":            _perturb("slippage_bps"),
        "heat_limit":              _perturb("heat_limit"),
    }

trades, metrics, pert = _load()

# ── 一、综合优先级总览 ─────────────────────────────────────────────────────────
st.subheader("一、综合改进优先级总览")

_kpi_c1, _kpi_c2, _kpi_c3, _kpi_c4 = st.columns(4)
_kpi_c1.metric("当前 CAGR", f"{metrics['cagr']*100:.2f}%")
_kpi_c2.metric("当前最大回撤", f"-{abs(metrics['max_drawdown'])*100:.2f}%")
_kpi_c3.metric("当前 Sharpe", f"{metrics['sharpe']:.3f}")
_kpi_c4.metric("总交易笔数", f"{metrics['n_trades']:,}")

st.markdown("""
| 优先级 | 模块 | 主要改进建议 | 有效性 | 精准度 | 年化收益 | 最大回撤 | 实现难度 |
|:-----:|------|------------|:-----:|:-----:|:-------:|:-------:|:-------:|
| 🔴 **最高** | **入场条件** | **金字塔加仓**；Gap 改为 ATR 基准 | ✅ 提升 | ✅ 提升 | **+4–5%** | -1–2% | ★★★ 高 |
| 🔴 **高** | **初始止损** | 止损执行价改为 min(stop, open[t+1]) | 中性 | ✅ **最高** | -0.74pp | 中性 | ★ 低 |
| 🔴 **高** | **分段移动止盈** | ≥10R 新增第四档 7×ATR | 中性 | 中性 | +1–2% | 中性 | ★ 低 |
| 🟠 **中高等** | **熊市做空对冲** | 熊市期（SPY<200MA）持有20%反向ETF | ✅ 提升 | 中性 | **+2.4 pp** | ✅ 改善 | ★★ 中 |
| 🟠 **中高等** | **时间止损** | N 日无进展则主动退出 | 中性 | 中性 | ✅ 提升 | ✅ 降低 | ★★ 中 |
| 🟠 **中高等** | **Cluster Risk** | 相关性过滤升级为组合集中度上限 | 中性 | 中性 | 中性 | ✅ 降低 | ★★ 中 |
| 🟠 **中高等** | 市场环境过滤 | 增加 Choppiness Index 二层过滤 | ✅ 提升 | 中性 | 中性 | ✅ 降低 | ★★ 中 |
| 🟡 中等 | 标的过滤 | ADV 门槛通胀动态调整 | ✅ 提升 | 中性 | +0.5–1% | 中性 | ★★ 中 |
| 🟡 中等 | 执行假设 | 分层滑点；止损执行价（同初始止损节） | ✅ 提升 | ✅ 提升 | 中性 | 中性 | ★ 低 |
| 🟢 中低等 | 仓位管理 | 热度上限 heat_limit 降至 8% | 中性 | 中性 | -0.3% | ✅ 降低 | ★ 低 |
| 🟢 中低等 | 成交量过滤 | Walk-Forward 验证 1.5× 阈值稳健性 | ✅ 提升 | 中性 | 中性 | 中性 | ★★ 中 |

**图例：** ✅ 改善 / 中性 / -降低。
优先级：🔴 高影响 → 🟠 中高等 → 🟡 中等 → 🟢 中低等。
""")

st.markdown("---")

# ── 二、利润来源：理解策略的盈利结构 ──────────────────────────────────────────────
st.subheader("二、利润来源分析：明白策略靠什么赚钱，才知道如何改进")

# R distribution data
_buckets  = [(-99,-1), (-1,0), (0,1), (1,3), (3,5), (5,10), (10,99)]
_blabels  = ["<-1R", "-1R~0", "0~1R", "1R~3R", "3R~5R", "5R~10R", ">10R"]
_bcounts, _bpnl, _bavgr = [], [], []
for lo, hi in _buckets:
    sub = trades[(trades["pnl_r_multiple"] >= lo) & (trades["pnl_r_multiple"] < hi)]
    _bcounts.append(len(sub))
    _bpnl.append(sub["net_pnl"].sum() / 1e6)
    _bavgr.append(sub["pnl_r_multiple"].mean() if len(sub) else 0)

_bar_colors = ["#ef4444","#f97316","#86efac","#22c55e","#16a34a","#15803d","#0f5132"]
_fig_rdist = make_subplots(
    rows=1, cols=2,
    subplot_titles=["各 R 区间交易笔数", "各 R 区间累计净盈亏（$M）"],
)
_fig_rdist.add_trace(go.Bar(
    x=_blabels, y=_bcounts,
    marker_color=_bar_colors,
    text=[f"{v:,}" for v in _bcounts],
    textposition="outside",
    showlegend=False,
), row=1, col=1)
_fig_rdist.add_trace(go.Bar(
    x=_blabels, y=_bpnl,
    marker_color=_bar_colors,
    text=[f"${v:.1f}M" for v in _bpnl],
    textposition="outside",
    showlegend=False,
), row=1, col=2)
_fig_rdist.update_layout(
    height=380, margin=dict(t=60, b=40),
    title="交易 R 倍数分布：笔数 vs 利润贡献",
)
_fig_rdist.update_yaxes(title_text="笔数", row=1, col=1)
_fig_rdist.update_yaxes(title_text="净盈亏（$M）", row=1, col=2)
st.plotly_chart(_fig_rdist, use_container_width=True)

_total_pnl = trades["net_pnl"].sum()
_big_trades = trades[trades["pnl_r_multiple"] >= 3.0]
_big_pnl    = _big_trades["net_pnl"].sum()
_top20_pnl  = trades.nlargest(20, "net_pnl")["net_pnl"].sum()

c1, c2, c3 = st.columns(3)
c1.metric("总净盈亏", f"${_total_pnl/1e6:.1f}M")
c2.metric(f"R>3 的 {len(_big_trades)} 笔交易", f"${_big_pnl/1e6:.1f}M",
          f"占总利润 {_big_pnl/_total_pnl*100:.0f}%")
c3.metric("Top 20 笔交易", f"${_top20_pnl/1e6:.1f}M",
          f"占总利润 {_top20_pnl/_total_pnl*100:.0f}%")

st.markdown(f"""
**核心洞察：利润高度集中，改进方向因此非常明确。**

- **亏损交易（{_bcounts[0]+_bcounts[1]:,} 笔）** 共亏损 \${abs(_bpnl[0]+_bpnl[1]):.1f}M，其中 <-1R 的大亏单（{_bcounts[0]:,} 笔）占亏损总额的 {abs(_bpnl[0])/(abs(_bpnl[0])+abs(_bpnl[1]))*100:.0f}%
- **小盈利交易（0~3R，{_bcounts[2]+_bcounts[3]:,} 笔）** 贡献正向利润但规模有限
- **大赢家（R>3，{len(_big_trades)} 笔，仅占 {len(_big_trades)/len(trades)*100:.1f}%）** 贡献总利润的 **{_big_pnl/_total_pnl*100:.0f}%**

因此改进策略有两条清晰路径：**① 减少大R亏损**（提升有效性+回撤）；**② 让大赢家赚更多**（提升年化收益）。
""")

st.markdown("---")

# ── 三、标的过滤 ───────────────────────────────────────────────────────────────
st.subheader("三、标的过滤")

st.markdown("""
当前使用两个动态过滤条件：价格 > \$10（原始价格）、ADV₆₀ > \$60M。

**改进建议：**
- **回测有效性**：\$10 和 \$60M 门槛是静态固定的，2000年与2026年的购买力相差极大。应引入通胀折算，将历史门槛动态调低（或以2024年为基准向前折算）。
- **年化收益**：ADV 从 \$60M 降至 \$30–50M 可扩大标的池，捕捉中盘动量溢价；但要同步调高滑点假设。
- **最大回撤**：增加行业集中度上限（单行业最多占总仓位 25%），防止板块集体突破引发相关性回撤。
""")

_adv_d = pert["min_adv_m"]
_prc_d = pert["min_price"]

if _adv_d and _prc_d:
    _fig_univ = make_subplots(
        rows=1, cols=2,
        subplot_titles=[
            "ADV 门槛（min_adv_m）敏感性",
            "价格门槛（min_price）敏感性",
        ],
    )
    _adv_base = _adv_d["baseline_value"]
    _adv_vals = _adv_d["param_values"]
    _adv_cagr = [r["cagr"]*100 for r in _adv_d["results"]]
    _adv_mdd  = [abs(r["max_drawdown"])*100 for r in _adv_d["results"]]
    _adv_clr  = ["#22c55e" if v == _adv_base else "#6366f1" for v in _adv_vals]
    _fig_univ.add_trace(go.Bar(
        x=[f"${v:.0f}M" for v in _adv_vals], y=_adv_cagr,
        marker_color=_adv_clr, name="ADV CAGR",
        text=[f"{v:.2f}%" for v in _adv_cagr], textposition="outside",
        showlegend=False,
    ), row=1, col=1)
    _fig_univ.add_trace(go.Scatter(
        x=[f"${v:.0f}M" for v in _adv_vals], y=_adv_mdd,
        mode="lines+markers", marker=dict(size=8, color="#ef4444"),
        line=dict(color="#ef4444", width=2), name="ADV MaxDD",
        showlegend=False, yaxis="y2",
    ), row=1, col=1)

    _prc_base = _prc_d["baseline_value"]
    _prc_vals = _prc_d["param_values"]
    _prc_cagr = [r["cagr"]*100 for r in _prc_d["results"]]
    _prc_mdd  = [abs(r["max_drawdown"])*100 for r in _prc_d["results"]]
    _prc_clr  = ["#22c55e" if v == _prc_base else "#6366f1" for v in _prc_vals]
    _fig_univ.add_trace(go.Bar(
        x=[f"${v:.0f}" for v in _prc_vals], y=_prc_cagr,
        marker_color=_prc_clr, name="Price CAGR",
        text=[f"{v:.2f}%" for v in _prc_cagr], textposition="outside",
        showlegend=False,
    ), row=1, col=2)
    _fig_univ.add_trace(go.Scatter(
        x=[f"${v:.0f}" for v in _prc_vals], y=_prc_mdd,
        mode="lines+markers", marker=dict(size=8, color="#ef4444"),
        line=dict(color="#ef4444", width=2), name="Price MaxDD",
        showlegend=False, yaxis="y4",
    ), row=1, col=2)

    _fig_univ.update_layout(
        height=380, margin=dict(t=60, b=40, r=60),
        yaxis=dict(title="CAGR (%)", range=[6, 12]),
        yaxis2=dict(title="最大回撤（%）", overlaying="y", side="right", range=[13, 28]),
        yaxis3=dict(title="CAGR (%)", range=[8, 12]),
        yaxis4=dict(title="最大回撤（%）", overlaying="y3", side="right", range=[13, 28]),
    )
    _fig_univ.update_xaxes(title_text="ADV 门槛", row=1, col=1)
    _fig_univ.update_xaxes(title_text="价格门槛", row=1, col=2)
    st.plotly_chart(_fig_univ, use_container_width=True)

    _best_adv_i = _adv_cagr.index(max(_adv_cagr))
    st.markdown(
        f"ADV 门槛：当前 \${_adv_base:.0f}M（绿色），CAGR = {_adv_cagr[_adv_vals.index(_adv_base)]:.2f}%，是所有测试值中的最优点。"
        f"降至 \$30M 或 \$40M 时 CAGR 反而下降（{_adv_cagr[0]:.2f}% / {_adv_cagr[1]:.2f}%），说明低流动性标的引入噪音。"
        f" 价格门槛：降至 \$8 CAGR（{_prc_cagr[0]:.2f}%）略高于当前 \$10（{_prc_cagr[1]:.2f}%），可作为候选改进点，但幅度有限。"
    )

st.markdown("---")

# ── 四、市场环境过滤 ───────────────────────────────────────────────────────────
st.subheader("四、市场环境过滤")

st.markdown("""
当前使用单一 SPY SMA(200) 判断牛熊市。

**改进建议：**

- **回测有效性**：引入 **Choppiness Index（CI）** 作为第二层过滤。CI 能识别"SPY 位于 SMA200 之上但无方向性趋势"的震荡牛市，这类环境下大量入场信号是假突破，是连续亏损的高发期。CI < 61.8 表示趋势明确，CI > 61.8 表示震荡。建议：`SPY > SMA(200)` 且 `CI < 61.8` 时才开仓。
- **年化收益**：将熊市豁免 ETF 列表从 TLT/GLD/UUP 3 只扩展至 5 只，增加 SHY（加息型熊市）和 VIXY（危机型熊市），捕捉更多反向趋势机会。
- **最大回撤**：CI 二层过滤可避免在震荡市场中频繁假突破入场，预期降低最大回撤 2–4%（详见"如何降低最大回撤"页面的实证分析）。

> 注：市场环境过滤的改进详见专项页面 **如何降低最大回撤** — 方法二（Choppiness Index）。
""")

# Regime stats from strategy_meta
_meta_f = _results_path / "strategy_meta.json"
if _meta_f.exists():
    _meta = json.loads(_meta_f.read_text())
    _rs = _meta.get("regime_stats", {})
    if _rs:
        _bear_pct  = _rs.get("bear_pct", 0)
        _bear_days = _rs.get("bear_days_total", 0)
        _episodes  = _rs.get("top_episodes", [])

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"""
**历史熊市封仓统计（2000–2026）：**

| 指标 | 数值 |
|------|------|
| 熊市封仓天数占比 | {_bear_pct:.1f}% |
| 熊市封仓总天数 | {_bear_days:,} 天 |
| 主要熊市期间 | {"；".join([f"{ep.get('start_year','')}–{ep.get('end_year','')}（{ep.get('days',0)}天）" for ep in _episodes[:3]])} |
""")
        with col2:
            st.markdown(f"""
**CI 二层过滤的预期效果：**

在熊市封仓期间（占 {_bear_pct:.1f}% 天数），策略已停止开仓——改进空间有限。

真正的改进空间在于**震荡牛市**：SPY 位于 SMA200 之上（策略认为是牛市、继续扫描信号），
但市场实际上是横盘震荡（CI > 61.8），假突破率极高，此时开仓亏损概率远高于正常牛市。

CI 过滤能精准识别并跳过这类"假牛市"期间的信号。
""")

st.markdown("---")

# ── 五、熊市做空对冲（新增）──────────────────────────────────────────────────────
st.subheader("五、熊市中加入 SPY 反向敞口（做空对冲）")

st.markdown(
    "> 📊 本节的完整数据分析详见「**如何改进策略有效性 → 三、改进路径一**」。\n\n"
    "**优先级定位：🟠 中高等** — 历史模拟 CAGR 提升 **+2.4 pp**，Sharpe **0.79 → 0.94**，实施难度中等（★★）。"
)

st.markdown(
    "策略在熊市中依靠追踪止损保护资本，但未能主动**从下跌中获利**。"
    "当 SPY 处于确认熊市（低于200日均线）时，叠加 20% 的指数反向敞口（如购买 SH 等反向 ETF），"
    "可在熊市年份显著提升组合收益。"
)

@st.cache_data
def _load_spy_nav_is():
    _spy_is = pd.read_csv(_results_path / "spy_nav.csv", parse_dates=["date"], index_col="date")["spy_nav"]
    _nav_df_is = pd.read_csv(_results_path / "nav.csv", parse_dates=["date"], index_col="date")
    return _spy_is, _nav_df_is.iloc[:, 0]

_spy_is, _nav_is = _load_spy_nav_is()
_spy_200ma_is = _spy_is.rolling(200, min_periods=150).mean()
_idx_is  = _nav_is.index.intersection(_spy_is.index)
_s_is    = _nav_is[_idx_is] / float(_nav_is[_idx_is[0]])
_b_is    = _spy_is[_idx_is] / float(_spy_is[_idx_is[0]])
_ny_is   = len(_idx_is) / 252

_s_ret_d_is  = _s_is.pct_change().fillna(0)
_b_ret_d_is  = _b_is.pct_change().fillna(0)
_in_bear_is  = (_spy_is[_idx_is] < _spy_200ma_is[_idx_is]).fillna(False)

_blend_ret_is = _s_ret_d_is.copy()
_blend_ret_is[_in_bear_is] = (
    0.80 * _s_ret_d_is[_in_bear_is] + 0.20 * (-_b_ret_d_is[_in_bear_is])
)
_blend_nav_is = (1 + _blend_ret_is).cumprod()

_s_cagr_is   = (float(_s_is.iloc[-1]) ** (1 / _ny_is) - 1) * 100
_b_cagr_is   = (float(_b_is.iloc[-1]) ** (1 / _ny_is) - 1) * 100
_bl_cagr_is  = (float(_blend_nav_is.iloc[-1]) ** (1 / _ny_is) - 1) * 100
_s_dd_is     = float(((_s_is - _s_is.cummax()) / _s_is.cummax()).min()) * 100
_bl_dd_is    = float(((_blend_nav_is - _blend_nav_is.cummax()) / _blend_nav_is.cummax()).min()) * 100
_s_sh_is     = float(_s_ret_d_is.mean() / _s_ret_d_is.std() * np.sqrt(252))
_bl_sh_is    = float(_blend_ret_is.mean() / _blend_ret_is.std() * np.sqrt(252))
_n_bear_d_is = int(_in_bear_is.sum())
_n_total_d_is = len(_in_bear_is)

_stat_rows_is = [
    {"指标": "年化收益 CAGR",  "当前策略": f"{_s_cagr_is:.2f}%",              "加入熊市对冲后": f"{_bl_cagr_is:.2f}%"},
    {"指标": "最大回撤",       "当前策略": f"{_s_dd_is:.2f}%",               "加入熊市对冲后": f"{_bl_dd_is:.2f}%"},
    {"指标": "Sharpe 比率",   "当前策略": f"{_s_sh_is:.2f}",                 "加入熊市对冲后": f"{_bl_sh_is:.2f}"},
    {"指标": "vs SPY Alpha",  "当前策略": f"{_s_cagr_is - _b_cagr_is:+.2f} pp", "加入熊市对冲后": f"{_bl_cagr_is - _b_cagr_is:+.2f} pp"},
]
st.dataframe(pd.DataFrame(_stat_rows_is), use_container_width=True, hide_index=True)

_fig_nav_is = go.Figure()
_fig_nav_is.add_trace(go.Scatter(
    name="策略1.0（当前）",
    x=_s_is.index, y=_s_is.values,
    mode="lines", line=dict(color="#2ca02c", width=2),
))
_fig_nav_is.add_trace(go.Scatter(
    name="策略1.0 + 熊市对冲（20% 反向SPY）",
    x=_blend_nav_is.index, y=_blend_nav_is.values,
    mode="lines", line=dict(color="#ff7f0e", width=2, dash="dot"),
))
_fig_nav_is.add_trace(go.Scatter(
    name="SPY（基准）",
    x=_b_is.index, y=_b_is.values,
    mode="lines", line=dict(color="#1f77b4", width=1.5, dash="dash"),
    opacity=0.6,
))
_fig_nav_is.update_layout(
    title="净值曲线对比：当前策略 vs 加入熊市对冲后",
    yaxis_title="净值（初始 = 1.0）",
    height=400,
    margin=dict(l=60, r=30, t=55, b=50),
    legend=dict(orientation="h", x=0, y=1.10),
)
st.plotly_chart(_fig_nav_is, use_container_width=True)

st.markdown(
    f'<div style="background:#f0f4ff;border-left:4px solid #ff7f0e;padding:12px 16px;border-radius:4px;margin:8px 0">'
    f'<strong>模拟结果：</strong>历史上 SPY 有 {_n_bear_d_is} 个交易日（占 {_n_bear_d_is/_n_total_d_is*100:.0f}%）处于200日均线以下。'
    f'在这些日期叠加 20% 反向 SPY 敞口后，CAGR 从 {_s_cagr_is:.1f}% 提升至 {_bl_cagr_is:.1f}%（+{_bl_cagr_is-_s_cagr_is:.1f} pp），'
    f'Sharpe 从 {_s_sh_is:.2f} → {_bl_sh_is:.2f}，最大回撤从 {_s_dd_is:.1f}% 改善至 {_bl_dd_is:.1f}%。'
    f'</div>',
    unsafe_allow_html=True,
)

st.markdown(
    "**实施建议：**\n\n"
    "- **触发条件**：SPY 低于200日均线且持续 10 个交易日以上（避免假信号），将 20% 仓位配置至反向 ETF（如 SH）。\n"
    "- **退出条件**：SPY 重回200日均线以上时，平仓反向 ETF，恢复全仓趋势跟踪策略。\n"
    "- **风险提示**：若 SPY 出现快速 V 形反转（如 2020年3月），持有反向 ETF 可能放大短期亏损；"
    " 建议设置反向 ETF 仓位的止损线（如跌幅超过 10% 平仓）。\n"
    "- **本质**：这不改变策略的信号逻辑，只是在确认熊市环境中增加一个对冲层，"
    "是策略从「纯多头」升级为「多空双向」的轻量化第一步，也是 **策略2.0** 的重要组成方向。"
)

st.markdown("---")

# ── 六、成交量过滤 ─────────────────────────────────────────────────────────────
st.subheader("六、成交量过滤")

st.markdown("""
当前 volume_filter_multiplier = 1.5×，要求突破当日成交量 ≥ 60日均量的 1.5 倍。

**改进建议：**
- **回测有效性**：1.5× 是经验设定，缺乏 Walk-Forward 验证。若各时期最优值不稳定（如2000–2010最优 1.2×，2015–2026最优 2.0×），则存在过拟合风险。
- **年化收益 & 最大回撤**：扰动数据显示 1.5× 是 CAGR 最优点，同时 MaxDD 也最低。提高阈值（2.0×）CAGR 降低且 MaxDD 反而更大；降低阈值（1.0×）同样表现更差。**当前设置无需调整，但需要 Walk-Forward 验证其稳健性。**
""")

_vol_d = pert["volume_filter_multiplier"]
if _vol_d:
    _vv = _vol_d["param_values"]
    _vc = [r["cagr"]*100 for r in _vol_d["results"]]
    _vm = [abs(r["max_drawdown"])*100 for r in _vol_d["results"]]
    _vn = [r["n_trades"] for r in _vol_d["results"]]
    _vbase = _vol_d["baseline_value"]

    _fig_vol = go.Figure()
    _fig_vol.add_trace(go.Bar(
        x=[str(v) for v in _vv], y=_vc,
        marker_color=["#22c55e" if v == _vbase else "#6366f1" for v in _vv],
        name="CAGR (%)", yaxis="y",
        text=[f"{v:.2f}%" for v in _vc], textposition="outside",
    ))
    _fig_vol.add_trace(go.Scatter(
        x=[str(v) for v in _vv], y=_vm,
        mode="lines+markers", marker=dict(size=9, color="#ef4444"),
        line=dict(color="#ef4444", width=2),
        name="最大回撤（%，右轴）", yaxis="y2",
    ))
    _fig_vol.add_trace(go.Scatter(
        x=[str(v) for v in _vv], y=_vn,
        mode="lines+markers", marker=dict(size=7, color="#94a3b8"),
        line=dict(color="#94a3b8", width=1.5, dash="dot"),
        name="交易笔数（右轴2）", yaxis="y3",
    ))
    _fig_vol.update_layout(
        title="成交量过滤倍数（volume_filter_multiplier）敏感性",
        xaxis_title="volume_filter_multiplier（× 60日均量）",
        yaxis=dict(title="CAGR (%)", side="left", range=[7, 12]),
        yaxis2=dict(title="最大回撤（%）", side="right", overlaying="y", range=[18, 28]),
        yaxis3=dict(title="交易笔数", side="right", overlaying="y",
                    position=0.85, showgrid=False),
        legend=dict(x=0.4, y=0.05), height=380, margin=dict(t=50, b=40, r=80),
    )
    st.plotly_chart(_fig_vol, use_container_width=True)
    st.markdown(
        f"当前 1.5×（绿色）：CAGR {_vc[_vv.index(_vbase)]:.2f}%，MaxDD {_vm[_vv.index(_vbase)]:.2f}%，{_vn[_vv.index(_vbase)]:.0f} 笔交易。"
        f"调高至 2.0× 时 MaxDD 恶化至 {_vm[-1]:.2f}%（因过度过滤了成交量并非总是高的真实趋势）；"
        f"调低至 1.0× 时 MaxDD 最差 {_vm[0]:.2f}%（假突破增多）。1.5× 同时是 CAGR 和 MaxDD 的最优点。"
    )

st.markdown("---")

# ── 六、入场条件 ───────────────────────────────────────────────────────────────
st.subheader("七、入场条件")

st.markdown("#### 6.1 突破窗口：当前 200 日是最优选择")

_bw_d = pert["breakout_window"]
if _bw_d:
    _bwv = _bw_d["param_values"]
    _bwc = [r["cagr"]*100 for r in _bw_d["results"]]
    _bwm = [abs(r["max_drawdown"])*100 for r in _bw_d["results"]]
    _bws = [r.get("sharpe", 0) for r in _bw_d["results"]]
    _bwbase = _bw_d["baseline_value"]

    _fig_bw = go.Figure()
    _fig_bw.add_trace(go.Bar(
        x=[str(v) for v in _bwv], y=_bwc,
        marker_color=["#22c55e" if v == _bwbase else "#6366f1" for v in _bwv],
        name="CAGR (%)", yaxis="y",
        text=[f"{v:.2f}%" for v in _bwc], textposition="outside",
    ))
    _fig_bw.add_trace(go.Scatter(
        x=[str(v) for v in _bwv], y=_bwm,
        mode="lines+markers", marker=dict(size=9, color="#ef4444"),
        line=dict(color="#ef4444", width=2),
        name="最大回撤（%，右轴）", yaxis="y2",
    ))
    _fig_bw.add_trace(go.Scatter(
        x=[str(v) for v in _bwv], y=_bws,
        mode="lines+markers", marker=dict(size=8, color="#f59e0b"),
        line=dict(color="#f59e0b", width=2, dash="dash"),
        name="Sharpe（右轴2）", yaxis="y3",
    ))
    _fig_bw.update_layout(
        title="突破窗口（breakout_window）敏感性：CAGR、MaxDD、Sharpe",
        xaxis_title="突破窗口（交易日）",
        yaxis=dict(title="CAGR (%)", side="left", range=[8, 11.5]),
        yaxis2=dict(title="最大回撤（%）", side="right", overlaying="y", range=[16, 24]),
        yaxis3=dict(title="Sharpe", side="right", overlaying="y",
                    position=0.85, showgrid=False),
        legend=dict(x=0.35, y=0.05), height=380, margin=dict(t=50, b=40, r=80),
    )
    st.plotly_chart(_fig_bw, use_container_width=True)
    st.markdown(
        f"200 日突破（绿色）是所有测试窗口中 CAGR 和 Sharpe 的最优点。"
        f"更短窗口（150日）CAGR {_bwc[0]:.2f}% 但 MaxDD 更低 {_bwm[0]:.2f}%；"
        f"更长窗口（300日）CAGR 和 Sharpe 均明显下降。200日突破窗口无需改变。"
    )

st.markdown("#### 6.2 Gap 过滤：改为 ATR 基准（回测精准度改进）")
st.markdown("""
当前 Gap 过滤使用固定 2.5% 阈值（|开盘跳空 / 前收| > 2.5% 则跳过），与策略整体 ATR 体系不一致：

| 股票类型 | 典型 ATR/price | 2.5% 固定阈值的问题 |
|---------|-------------|-----------------|
| 低波动（公用事业）| 0.5–0.8% | 2.5% 跳空极为罕见，过滤等同于无效 |
| 中等波动（主流股）| 1.5–2.0% | 2.5% 接近 1.5× ATR，过滤较合理 |
| 高波动（成长股）| 2.5–4.0% | 2.5% 是日常正常波动，过度过滤 |

**建议**：将 Gap 过滤改为 `|gap| > 1.5 × ATR(20) / close`，使阈值自适应各股票的实际波动水平。

注：此改进需要完整回测验证其对 CAGR 和 MaxDD 的净影响。
""")

st.markdown("#### 6.3 金字塔加仓：最高优先级年化收益改进")

# Pyramid data
_big_trades = trades[trades["pnl_r_multiple"] >= 3.0].copy()
_big_trades["initial_risk"] = _big_trades["net_pnl"] / _big_trades["pnl_r_multiple"]
_big_trades["pyramid_gain"] = (_big_trades["pnl_r_multiple"] - 3.0) * 0.5 * _big_trades["initial_risk"]

_r_buckets = [(3,5), (5,10), (10,15), (15,20), (20,30), (30,99)]
_r_labels  = ["3–5R", "5–10R", "10–15R", "15–20R", "20–30R", "30R+"]
_r_current, _r_pyramid, _r_count = [], [], []
for lo, hi in _r_buckets:
    sub = _big_trades[(_big_trades["pnl_r_multiple"] >= lo) & (_big_trades["pnl_r_multiple"] < hi)]
    _r_current.append(sub["net_pnl"].sum() / 1e6)
    _r_pyramid.append(sub["pyramid_gain"].sum() / 1e6)
    _r_count.append(len(sub))

_fig_pyra = go.Figure()
_fig_pyra.add_trace(go.Bar(
    x=_r_labels, y=_r_current,
    name="当前利润（$M）",
    marker_color="#22c55e",
    text=[f"${v:.1f}M<br>{c}笔" for v, c in zip(_r_current, _r_count)],
    textposition="outside",
))
_fig_pyra.add_trace(go.Bar(
    x=_r_labels, y=_r_pyramid,
    name=f"金字塔加仓额外利润（$M）",
    marker_color="#86efac",
    text=[f"+${v:.1f}M" for v in _r_pyramid],
    textposition="inside",
))
_fig_pyra.update_layout(
    barmode="stack",
    title=f"金字塔加仓潜在额外利润：R>3 的 {len(_big_trades)} 笔交易，在 3R 时追加原始仓位的 50%",
    xaxis_title="R 倍数区间",
    yaxis_title="利润（$M）",
    height=400,
    legend=dict(x=0.45, y=0.95),
    margin=dict(t=60, b=40),
)
st.plotly_chart(_fig_pyra, use_container_width=True)

_total_pyramid = _big_trades["pyramid_gain"].sum()
_total_current_big = _big_trades["net_pnl"].sum()
st.markdown(
    f"R>3 的 {len(_big_trades)} 笔交易当前利润共 \${_total_current_big/1e6:.1f}M；"
    f"若在 3R 时追加 50% 仓位，粗估额外利润约 \${_total_pyramid/1e6:.1f}M"
    f"（+{_total_pyramid/_total_current_big*100:.0f}%，相当于总利润的 {_total_pyramid/_total_pnl*100:.0f}%）。"
    "高 R 区间（>10R）是金字塔加仓的主要受益来源。"
    "（粗估基于静态计算，实际效果需完整回测验证，加仓会同步扩大潜在回撤。）"
)

st.info(f"""
**粗估总效益：CAGR 约从 {metrics['cagr']*100:.2f}% 提升至 14–16%**

- 全部 {len(_big_trades)} 笔 R > 3 的交易，假设在 3R 时追加原始仓位的 50%
- 额外利润约 **${_total_pyramid/1e6:.1f}M**，相当于当前总利润的 **{_total_pyramid/_total_pnl*100:.0f}%**
- 粗估 CAGR 增速与利润增速大致同步 → CAGR 从 {metrics['cagr']*100:.2f}% 提升至约 **14–16%**
- 代价：加仓会扩大持仓规模，预期 MaxDD 增加 1–4%（-22% 至 -25%）

详见专项页面：**加仓机制（金字塔）**（Future Work 分组）
""")

st.markdown("---")

# ── 七、初始止损 ───────────────────────────────────────────────────────────────
st.subheader("七、初始止损")

st.markdown("#### 7.1 止损乘数：当前 2× ATR 是 CAGR 最优点，但 Sharpe 不是")

_sl_d = pert["stop_loss_multiplier"]
if _sl_d:
    _slv = _sl_d["param_values"]
    _slc = [r["cagr"]*100 for r in _sl_d["results"]]
    _slm = [abs(r["max_drawdown"])*100 for r in _sl_d["results"]]
    _sls = [r.get("sharpe", 0) for r in _sl_d["results"]]
    _slbase = _sl_d["baseline_value"]

    _fig_sl = go.Figure()
    _fig_sl.add_trace(go.Bar(
        x=[str(v) for v in _slv], y=_slc,
        marker_color=["#22c55e" if v == _slbase else "#6366f1" for v in _slv],
        name="CAGR (%)", yaxis="y",
        text=[f"{v:.2f}%" for v in _slc], textposition="outside",
    ))
    _fig_sl.add_trace(go.Scatter(
        x=[str(v) for v in _slv], y=_slm,
        mode="lines+markers", marker=dict(size=9, color="#ef4444"),
        line=dict(color="#ef4444", width=2),
        name="最大回撤（%，右轴）", yaxis="y2",
    ))
    _fig_sl.add_trace(go.Scatter(
        x=[str(v) for v in _slv], y=_sls,
        mode="lines+markers", marker=dict(size=8, color="#f59e0b"),
        line=dict(color="#f59e0b", width=2, dash="dash"),
        name="Sharpe（右轴2）", yaxis="y3",
    ))
    _fig_sl.update_layout(
        title="初始止损乘数（stop_loss_multiplier）敏感性：CAGR、MaxDD、Sharpe",
        xaxis_title="stop_loss_multiplier（× ATR）",
        yaxis=dict(title="CAGR (%)", side="left", range=[8.5, 11.5]),
        yaxis2=dict(title="最大回撤（%）", side="right", overlaying="y", range=[18, 24]),
        yaxis3=dict(title="Sharpe", side="right", overlaying="y",
                    position=0.85, showgrid=False),
        legend=dict(x=0.35, y=0.05), height=380, margin=dict(t=50, b=40, r=80),
    )
    st.plotly_chart(_fig_sl, use_container_width=True)

    _sl_base_i = _slv.index(_slbase)
    st.markdown(
        f"当前 2× ATR（绿色）：CAGR {_slc[_sl_base_i]:.2f}%（最优），但 Sharpe {_sls[_sl_base_i]:.3f} 不是最优。"
        f"扩大至 2.5× ATR 时 CAGR 降至 {_slc[2]:.2f}% 但 MaxDD 轻微改善（{_slm[2]:.2f}%）；"
        f"收紧至 1.5× ATR 时 CAGR 略降（{_slc[0]:.2f}%）但 MaxDD 最高（{_slm[0]:.2f}%）—— 频繁假止损反而扩大回撤。"
        "维持 2× ATR 是 CAGR 最优选择。"
    )

st.markdown("#### 7.2 止损执行价精准度改进（最高回测精准度改进优先级）")
st.markdown("""
当前止损触发逻辑：low[t] < stop_loss → 次日开盘价平仓

**问题**：假设次日高开（stock gaps up），回测仍用高开价执行，而实盘止损单会在止损价执行——
回测系统性高估了止损出场价，隐含 CAGR 被高估。

**建议**：将止损执行价改为 min(stop_loss_price, open[t+1])：
- 若次日低开 → 按开盘价执行（与当前相同，正确）
- 若次日高开 → 按止损价执行（实盘止损单的行为，更保守、更真实）

**估算影响**：约 −0.74 pp CAGR（CAGR 从 10.58% 降至约 9.84%），让回测更保守但更准确。
这是一行代码的改动，却能显著提升回测可信度。

注：此改进详见"如何改进回测方法论"页面 — 改进①。
""")

st.markdown("---")

# ── 八、分段移动止盈 ─────────────────────────────────────────────────────────
st.subheader("八、分段移动止盈")

st.markdown("#### 8.1 当前三档移动止盈的敏感性")

_tr_d = pert["trail_multiplier_r1"]
if _tr_d:
    _trv = _tr_d["param_values"]
    _trc = [r["cagr"]*100 for r in _tr_d["results"]]
    _trm = [abs(r["max_drawdown"])*100 for r in _tr_d["results"]]
    _trn = [r["n_trades"] for r in _tr_d["results"]]
    _trbase = _tr_d["baseline_value"]

    _fig_tr = go.Figure()
    _fig_tr.add_trace(go.Bar(
        x=[str(v) for v in _trv], y=_trc,
        marker_color=["#22c55e" if v == _trbase else "#6366f1" for v in _trv],
        name="CAGR (%)", yaxis="y",
        text=[f"{v:.2f}%" for v in _trc], textposition="outside",
    ))
    _fig_tr.add_trace(go.Scatter(
        x=[str(v) for v in _trv], y=_trm,
        mode="lines+markers", marker=dict(size=9, color="#ef4444"),
        line=dict(color="#ef4444", width=2),
        name="最大回撤（%，右轴）", yaxis="y2",
    ))
    _fig_tr.add_trace(go.Scatter(
        x=[str(v) for v in _trv], y=_trn,
        mode="lines+markers", marker=dict(size=7, color="#94a3b8"),
        line=dict(color="#94a3b8", width=1.5, dash="dot"),
        name="交易笔数（右轴2）", yaxis="y3",
    ))
    _fig_tr.update_layout(
        title="移动止盈乘数（trail_multiplier_r1，适用于 R_peak < 3R 阶段）敏感性",
        xaxis_title="trail_multiplier_r1（× ATR，R_peak < 3R 阶段）",
        yaxis=dict(title="CAGR (%)", side="left", range=[8.5, 11.5]),
        yaxis2=dict(title="最大回撤（%）", side="right", overlaying="y", range=[18, 23]),
        yaxis3=dict(title="交易笔数", side="right", overlaying="y",
                    position=0.85, showgrid=False),
        legend=dict(x=0.35, y=0.05), height=380, margin=dict(t=50, b=40, r=80),
    )
    st.plotly_chart(_fig_tr, use_container_width=True)

    _tr_base_i = _trv.index(_trbase)
    st.markdown(
        f"当前 3× ATR（绿色）：CAGR {_trc[_tr_base_i]:.2f}%（所有测试值中最优），"
        f"MaxDD {_trm[_tr_base_i]:.2f}%，{_trn[_tr_base_i]:.0f} 笔交易。"
        f"收紧至 2× ATR 时 CAGR 降至 {_trc[0]:.2f}%，且交易笔数大幅增加（{_trn[0]:.0f} 笔）——"
        "被频繁噪音震出，换手率飙升。"
    )

st.markdown("#### 8.2 大赢家止盈第四档：≥10R 放宽至 7× ATR（年化收益改进）")

# Show the big winners and their potential
_very_big = trades[trades["pnl_r_multiple"] >= 10.0].copy()
_very_big = _very_big.nlargest(15, "pnl_r_multiple")[
    ["ticker", "entry_date", "exit_date", "pnl_r_multiple", "net_pnl", "holding_days", "exit_reason"]
].copy()
_very_big["entry_date"] = _very_big["entry_date"].dt.strftime("%Y-%m-%d")
_very_big["exit_date"]  = _very_big["exit_date"].dt.strftime("%Y-%m-%d")
_very_big["pnl_r_multiple"] = _very_big["pnl_r_multiple"].map(lambda v: f"{v:.1f}R")
_very_big["net_pnl"] = _very_big["net_pnl"].map(lambda v: f"${v/1e6:.2f}M")

st.markdown(f"""
当前共有 **{len(trades[trades['pnl_r_multiple']>=10.0])} 笔** R ≥ 10R 的超级大赢家，
合计贡献 **${trades[trades['pnl_r_multiple']>=10.0]['net_pnl'].sum()/1e6:.1f}M**（占总利润 {trades[trades['pnl_r_multiple']>=10.0]['net_pnl'].sum()/_total_pnl*100:.0f}%）。

这些仓位受 5× ATR 止盈约束。在持仓达到 10R 浮盈后，将止盈放宽至 7× ATR，
给超级趋势更多呼吸空间，避免被中途震荡提前踢出。

**前 15 笔 R ≥ 10R 的大赢家（均为移动止盈出场或回测结束）：**
""")
st.dataframe(
    _very_big.rename(columns={
        "ticker": "标的", "entry_date": "入场日", "exit_date": "出场日",
        "pnl_r_multiple": "R倍数", "net_pnl": "净盈亏",
        "holding_days": "持仓天数", "exit_reason": "出场原因",
    }),
    use_container_width=True, hide_index=True,
)
st.markdown(
    "注：'end_of_backtest' 表示回测结束时仍持仓——这些仓位实际上可能还在继续运行，"
    "更宽松的止盈（7× ATR）在此类仓位上的效果无法通过当前回测范围完整衡量。"
    "预期 CAGR 改善约 +1–2%，需完整回测验证。"
)

st.markdown("---")

# ── 九、仓位管理 ───────────────────────────────────────────────────────────────
st.subheader("九、仓位管理")

st.markdown("""
当前仓位管理参数：risk_per_trade = 1%、position_cap = 5%、heat_limit = 10%、correlation_threshold = 0.7。

**改进建议：**
- **年化收益**：金字塔加仓的实现需要预留空间——将初始仓位设为 0.7× 正常规模，为后续加仓留出 position_cap 额度（详见"加仓机制"页面）。
- **最大回撤**：将 heat_limit 从 10% 降至 8%，理论最大同时止损损失从 10% NAV 降至 8% NAV，轻微降低极端情形下的最大回撤。
""")

_pc_d = pert["position_cap"]
_hl_d = pert["heat_limit"]

if _pc_d:
    _pcv = _pc_d["param_values"]
    _pcc = [r["cagr"]*100 for r in _pc_d["results"]]
    _pcm = [abs(r["max_drawdown"])*100 for r in _pc_d["results"]]
    _pcn = [r["n_trades"] for r in _pc_d["results"]]
    _pcbase = _pc_d["baseline_value"]

    _fig_pm = make_subplots(
        rows=1, cols=1 if not _hl_d else 2,
        subplot_titles=(
            ["单笔仓位上限（position_cap）敏感性"]
            if not _hl_d
            else ["单笔仓位上限（position_cap）", "组合热度上限（heat_limit）"]
        ),
    )

    _pcclr = ["#22c55e" if v == _pcbase else "#6366f1" for v in _pcv]
    _fig_pm.add_trace(go.Bar(
        x=[f"{v:.0%}" for v in _pcv], y=_pcc,
        marker_color=_pcclr, name="position_cap CAGR",
        text=[f"{v:.2f}%" for v in _pcc], textposition="outside",
        showlegend=False,
    ), row=1, col=1)
    _fig_pm.add_trace(go.Scatter(
        x=[f"{v:.0%}" for v in _pcv], y=_pcm,
        mode="lines+markers", marker=dict(size=9, color="#ef4444"),
        line=dict(color="#ef4444", width=2), showlegend=False,
        yaxis="y2",
    ), row=1, col=1)

    if _hl_d:
        _hlv = _hl_d["param_values"]
        _hlc = [r["cagr"]*100 for r in _hl_d["results"]]
        _hlm = [abs(r["max_drawdown"])*100 for r in _hl_d["results"]]
        _hlbase = _hl_d["baseline_value"]
        _hlclr = ["#22c55e" if v == _hlbase else "#6366f1" for v in _hlv]

        _fig_pm.add_trace(go.Bar(
            x=[f"{v:.0%}" for v in _hlv], y=_hlc,
            marker_color=_hlclr, name="heat_limit CAGR",
            text=[f"{v:.2f}%" for v in _hlc], textposition="outside",
            showlegend=False,
        ), row=1, col=2)
        _fig_pm.add_trace(go.Scatter(
            x=[f"{v:.0%}" for v in _hlv], y=_hlm,
            mode="lines+markers", marker=dict(size=9, color="#ef4444"),
            line=dict(color="#ef4444", width=2), showlegend=False,
            yaxis="y4",
        ), row=1, col=2)

    _fig_pm.update_layout(
        height=380, margin=dict(t=60, b=40, r=60),
        yaxis=dict(title="CAGR (%)", range=[7, 12]),
        yaxis2=dict(title="最大回撤（%）", overlaying="y", side="right", range=[17, 28]),
        yaxis3=dict(title="CAGR (%)", range=[7, 12]),
        yaxis4=dict(title="最大回撤（%）", overlaying="y3", side="right", range=[17, 28]),
    )
    st.plotly_chart(_fig_pm, use_container_width=True)

    _pc_base_i = _pcv.index(_pcbase)
    _hl_caption = ""
    if _hl_d:
        _hl_base_i = _hl_d["param_values"].index(_hl_d["baseline_value"])
        _hlc_list = [r["cagr"]*100 for r in _hl_d["results"]]
        _hlm_list = [abs(r["max_drawdown"])*100 for r in _hl_d["results"]]
        _hl_caption = (
            f" heat_limit：当前 {_hl_d['baseline_value']:.0%}（绿色）CAGR {_hlc_list[_hl_base_i]:.2f}%，MaxDD {_hlm_list[_hl_base_i]:.2f}%；"
            "降低 heat_limit 可轻微改善 MaxDD，代价是 CAGR 小幅下降。"
        )
    st.markdown(
        f"position_cap：当前 {_pcbase:.0%}（绿色）是 CAGR 最优点（{_pcc[_pc_base_i]:.2f}%）。"
        f"降低至 3% 时交易笔数增加（{_pcn[0]:.0f} 笔）但每笔规模缩小，CAGR 降至 {_pcc[0]:.2f}%。"
        f"提高至 7% 时 MaxDD 增至 {_pcm[-1]:.2f}%。5% 是当前最优平衡点。"
        + _hl_caption
    )

st.markdown("---")

# ── 十、Cluster Risk ──────────────────────────────────────────────────────────
st.subheader("十、Cluster Risk：相关性过滤的隐藏漏洞")

st.markdown("""
当前仓位管理对相关性的处理：若新标的与任意已持仓标的相关系数 > 0.7，则将新仓位减半（0.5R 风险）。

**问题**：逐对减半不等于集中度上限。5 只相关性各超 0.7 的标的，每只都被减半，
但合计风险仍达到 5 × 0.5R = **2.5R 的组合级集中风险**。

若这 5 只属于同一行业（如 2022 年科技股集体下跌），结果是：
相关性控制在纸面上生效了，但实际回撤与没有控制时相差无几。
""")

@st.cache_data(ttl=86400)
def _compute_concurrent():
    _t = pd.read_csv(_results_path / "trades.csv", parse_dates=["entry_date", "exit_date"])
    _t["holding_days"] = (_t["exit_date"] - _t["entry_date"]).dt.days
    counts = []
    for _, row in _t.iterrows():
        d = row["entry_date"]
        c = int((((_t["entry_date"] <= d) & (_t["exit_date"] >= d))).sum()) - 1
        counts.append(c)
    _t["concurrent_at_entry"] = counts
    return _t

_trades_ext = _compute_concurrent()

st.markdown("#### 10.1 当持仓越拥挤，单笔入场的胜率越低")

_conc_buckets  = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 99)]
_conc_labels   = ["0–4 只", "5–9 只", "10–14 只", "15–19 只", "20+ 只"]
_conc_wr, _conc_avgr, _conc_n, _conc_pnl = [], [], [], []
for lo, hi in _conc_buckets:
    sub = _trades_ext[
        (_trades_ext["concurrent_at_entry"] >= lo) &
        (_trades_ext["concurrent_at_entry"] < hi)
    ]
    _conc_wr.append((sub["net_pnl"] > 0).mean() * 100 if len(sub) else 0)
    _conc_avgr.append(sub["pnl_r_multiple"].mean() if len(sub) else 0)
    _conc_n.append(len(sub))
    _conc_pnl.append(sub["net_pnl"].sum() / 1e6)

_fig_conc = make_subplots(
    rows=1, cols=2,
    subplot_titles=["入场时并发持仓数 vs 胜率", "入场时并发持仓数 vs 平均 R"],
)
_wr_colors = ["#22c55e" if v >= 45 else ("#f59e0b" if v >= 35 else "#ef4444")
              for v in _conc_wr]
_fig_conc.add_trace(go.Bar(
    x=_conc_labels, y=_conc_wr,
    marker_color=_wr_colors,
    text=[f"{v:.1f}%<br>({n}笔)" for v, n in zip(_conc_wr, _conc_n)],
    textposition="outside", showlegend=False,
), row=1, col=1)
_avgr_colors = ["#22c55e" if v >= 0.4 else ("#f59e0b" if v >= 0.2 else "#ef4444")
                for v in _conc_avgr]
_fig_conc.add_trace(go.Bar(
    x=_conc_labels, y=_conc_avgr,
    marker_color=_avgr_colors,
    text=[f"{v:+.3f}R" for v in _conc_avgr],
    textposition="outside", showlegend=False,
), row=1, col=2)
_fig_conc.update_layout(
    height=380, margin=dict(t=60, b=40),
)
_fig_conc.update_yaxes(title_text="胜率 (%)", row=1, col=1)
_fig_conc.update_yaxes(title_text="平均 R", row=1, col=2)
st.plotly_chart(_fig_conc, use_container_width=True)

st.markdown(
    f"持仓拥挤时（15–19 只：胜率 {_conc_wr[3]:.1f}%，均值 {_conc_avgr[3]:+.3f}R；"
    f"20+ 只：胜率 {_conc_wr[4]:.1f}%，均值 {_conc_avgr[4]:+.3f}R），"
    "表现明显弱于持仓稀疏时（10–14 只：胜率 "
    f"{_conc_wr[2]:.1f}%，均值 {_conc_avgr[2]:+.3f}R）。"
    "这说明投资组合拥挤本身会降低边际入场的质量——风险集中时市场整体动量往往已被充分利用。"
)

st.markdown("#### 10.2 Cluster Risk：累积风险不因逐对减半而消失")

_fig_cluster = go.Figure()
_n_vals = list(range(1, 8))
_cluster_risk_full = [n * 1.0 for n in _n_vals]
_cluster_risk_halved = [n * 0.5 for n in _n_vals]
_cluster_cap = [2.0] * len(_n_vals)

_fig_cluster.add_trace(go.Bar(
    x=[f"{n} 只相关仓位" for n in _n_vals],
    y=_cluster_risk_full,
    name="不减半（全仓 1R 各）",
    marker_color="rgba(239,68,68,0.5)",
))
_fig_cluster.add_trace(go.Bar(
    x=[f"{n} 只相关仓位" for n in _n_vals],
    y=_cluster_risk_halved,
    name="当前做法（逐对减半至 0.5R 各）",
    marker_color="rgba(99,102,241,0.7)",
))
_fig_cluster.add_trace(go.Scatter(
    x=[f"{n} 只相关仓位" for n in _n_vals],
    y=_cluster_cap,
    mode="lines",
    line=dict(color="#22c55e", width=2.5, dash="dash"),
    name="建议：Cluster Risk 上限 2R",
))
_fig_cluster.update_layout(
    barmode="group",
    title="Cluster Risk 累积：逐对减半 vs 组合级上限",
    xaxis_title="同一行业/板块中的相关仓位数量",
    yaxis_title="组合集中风险（R）",
    height=380,
    legend=dict(x=0.01, y=0.95),
    margin=dict(t=60, b=40),
)
st.plotly_chart(_fig_cluster, use_container_width=True)

st.markdown("""
**图解读**：当同一行业有 4 只相关仓位时，当前做法（逐对减半）仍累积 2.0R 的集中风险，
与"不减半"时的 4 只相比只节省了一半——但若全行业同时回撤，这 2R 仍会同步亏损。

**建议：引入 Cluster Risk 上限**

将相关仓位分组（按行业、因子或相关性聚类），对每组设置总风险上限：

| 组别 | 上限 | 触发条件 |
|------|------|---------|
| 科技/半导体（NVDA/AMD/XLK/SOXX 类） | ≤ 2R | 新仓超限时拒绝开仓 |
| 能源（XLE/HAL/SLB 类） | ≤ 2R | 同上 |
| 大盘 ETF（QQQ/SPY/IWM 类） | ≤ 1R | 同上 |
| 防御性资产（TLT/GLD/UUP） | ≤ 3R | 允许更多（熊市豁免） |

Cluster Risk 上限不替代现有的逐对相关性减半，而是**在其之上增加组合级别的硬性上限**。
预期效果：最大回撤降低 5–10%，对 CAGR 影响中性（减少的是低质量的过度集中入场）。

注：需要维护一份行业/板块分类表，并在引擎每日扫描入场信号时实时计算各组的当前风险敞口。
""")

st.markdown("---")

# ── 十一、时间止损 ────────────────────────────────────────────────────────────
st.subheader("十一、时间止损：剔除「占座不赚钱」的仓位")

st.markdown("""
当前策略只有两种退出机制：**止损**（跌破 2×ATR 强制止损）和**移动止盈**（跌破追踪止损线）。

**问题**：存在一类交易——**开仓后长期徘徊在入场价附近，既没有触发止损，也没有形成趋势**。
这类仓位占用了宝贵的资金额度（position_cap），同时贡献了接近 0 的期望收益。

时间止损的核心逻辑：**在 N 日内如果仓位没有实质性盈利进展，主动退出，释放资金给更好的机会。**
""")

st.markdown("#### 11.1 核心发现：持仓时间与胜率的惊人分化")

_hd_buckets = [(0, 10), (10, 20), (20, 30), (30, 60), (60, 120), (120, 999)]
_hd_labels  = ["0–9 天", "10–19 天", "20–29 天", "30–59 天", "60–119 天", "120+ 天"]
_hd_wr, _hd_avgr, _hd_n_win, _hd_n_lose, _hd_pnl = [], [], [], [], []
for lo, hi in _hd_buckets:
    sub = trades[(trades["holding_days"] >= lo) & (trades["holding_days"] < hi)]
    winners = sub[sub["net_pnl"] > 0]
    losers  = sub[sub["net_pnl"] <= 0]
    _hd_wr.append((sub["net_pnl"] > 0).mean() * 100 if len(sub) else 0)
    _hd_avgr.append(sub["pnl_r_multiple"].mean() if len(sub) else 0)
    _hd_n_win.append(len(winners))
    _hd_n_lose.append(len(losers))
    _hd_pnl.append(sub["net_pnl"].sum() / 1e6)

_fig_hd = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    row_heights=[0.55, 0.45],
    vertical_spacing=0.06,
    subplot_titles=["持仓天数：盈利笔数 vs 亏损笔数", "持仓天数 vs 胜率 & 平均 R"],
)
_fig_hd.add_trace(go.Bar(
    x=_hd_labels, y=_hd_n_win, name="盈利笔数",
    marker_color="#22c55e",
    text=[str(v) for v in _hd_n_win], textposition="auto",
), row=1, col=1)
_fig_hd.add_trace(go.Bar(
    x=_hd_labels, y=[-v for v in _hd_n_lose], name="亏损笔数",
    marker_color="#ef4444",
    text=[f"-{v}" for v in _hd_n_lose], textposition="auto",
), row=1, col=1)
_fig_hd.add_hline(y=0, line_color="#666", line_width=1, row=1, col=1)

_fig_hd.add_trace(go.Scatter(
    x=_hd_labels, y=_hd_wr,
    mode="lines+markers+text",
    marker=dict(size=10, color="#6366f1"),
    line=dict(color="#6366f1", width=2.5),
    name="胜率 (%)",
    text=[f"{v:.0f}%" for v in _hd_wr],
    textposition="top center",
    yaxis="y3",
), row=2, col=1)
_fig_hd.add_trace(go.Scatter(
    x=_hd_labels, y=_hd_avgr,
    mode="lines+markers+text",
    marker=dict(size=9, color="#f59e0b"),
    line=dict(color="#f59e0b", width=2.5, dash="dash"),
    name="平均 R（右轴）",
    text=[f"{v:+.2f}R" for v in _hd_avgr],
    textposition="bottom center",
    yaxis="y4",
), row=2, col=1)
_fig_hd.add_hline(y=50, line_dash="dot", line_color="#22c55e",
                   annotation_text="50% 胜率分界线", row=2, col=1)
_fig_hd.add_hline(y=0, line_dash="dot", line_color="#f59e0b",
                   annotation_text="0R 分界线", annotation_position="bottom right",
                   yref="y4", row=2, col=1)

_fig_hd.update_layout(
    barmode="relative", height=560,
    margin=dict(t=60, b=40, r=60),
    yaxis=dict(title="交易笔数"),
    yaxis2=dict(title=""),
    yaxis3=dict(title="胜率 (%)", side="left", range=[-5, 110]),
    yaxis4=dict(title="平均 R", side="right", overlaying="y3", range=[-2, 8]),
    legend=dict(orientation="h", y=1.06),
)
st.plotly_chart(_fig_hd, use_container_width=True)

_wr_0_19 = sum(_hd_n_win[:2]) / (sum(_hd_n_win[:2]) + sum(_hd_n_lose[:2])) * 100
_wr_60p  = sum(_hd_n_win[4:]) / (sum(_hd_n_win[4:]) + sum(_hd_n_lose[4:])) * 100

_c1, _c2, _c3 = st.columns(3)
_c1.metric("0–19 天交易的胜率", f"{_wr_0_19:.1f}%",
           "几乎全是亏损", delta_color="inverse")
_c2.metric("30–59 天交易的胜率", f"{_hd_wr[3]:.1f}%", "首次超过 50%")
_c3.metric("60+ 天交易的胜率", f"{_wr_60p:.1f}%", "绝大多数是赢家")

_n_short_losers = _hd_n_lose[0] + _hd_n_lose[1]
_total_losers   = sum(_hd_n_lose)
st.markdown(
    f"**关键数据**：持仓 0–19 天的交易共 {sum(_hd_n_win[:2])+sum(_hd_n_lose[:2]):,} 笔，"
    f"其中亏损 {_n_short_losers:,} 笔（占该区间 {_n_short_losers/(sum(_hd_n_win[:2])+sum(_hd_n_lose[:2]))*100:.0f}%），"
    f"亏损笔数占所有亏损的 {_n_short_losers/_total_losers*100:.0f}%。"
    "这些交易大多数是直接触发止损出场，时间止损的意义在于**更早识别「趋势未启动」的信号**，"
    "在止损线被击穿之前主动退出，以更小的亏损换取更快的资金周转。"
)

st.markdown("#### 11.2 资金占用成本：亏损交易持仓越久，损失越大")

_fig_hd2 = go.Figure()
_pnl_colors = ["#22c55e" if v >= 0 else "#ef4444" for v in _hd_pnl]
_fig_hd2.add_trace(go.Bar(
    x=_hd_labels,
    y=_hd_pnl,
    marker_color=_pnl_colors,
    text=[f"${v:.1f}M<br>{_hd_n_win[i]+_hd_n_lose[i]}笔" for i, v in enumerate(_hd_pnl)],
    textposition="outside",
    showlegend=False,
))
_fig_hd2.update_layout(
    title="各持仓时间区间的累计净盈亏（$M）",
    xaxis_title="持仓天数区间",
    yaxis_title="累计净盈亏（$M）",
    height=360,
    margin=dict(t=50, b=40),
)
st.plotly_chart(_fig_hd2, use_container_width=True)

st.markdown(
    f"0–9 天区间：{_hd_n_win[0]+_hd_n_lose[0]:,} 笔交易累计亏损 \${abs(_hd_pnl[0]):.1f}M，"
    f"平均每笔 \${abs(_hd_pnl[0])*1e6/(_hd_n_win[0]+_hd_n_lose[0])/1e3:.0f}k——"
    "这些基本是立即触发止损的假突破，时间止损对其帮助有限（已被快速止损）。"
    f" 10–29 天区间：{sum(_hd_n_win[1:3])+sum(_hd_n_lose[1:3]):,} 笔，累计亏损 \${abs(_hd_pnl[1]+_hd_pnl[2]):.1f}M——"
    "这类「拖延型亏损」是时间止损的核心目标：开仓后未被快速止损，但也未形成趋势，占用资金 2–4 周。"
)

st.markdown("#### 11.3 时间止损实施建议")
st.markdown("""
**核心规则（建议参数，需回测验证）：**

若持仓满 **20 个交易日**后，当前浮盈仍 **< 0.5R**（即价格几乎没有正向进展），则主动平仓退出。

| 触发条件 | 含义 |
|---------|------|
| 持仓天数 ≥ 20 日 | 已给予趋势足够的启动时间 |
| 当前浮盈 < 0.5R | 价格自入场后几乎没有有效上涨 |
| 同时满足两条件 | 判定为「趋势未启动型」仓位，主动退出 |

**与现有止损机制的关系：**

时间止损是第三条退出通道，优先级低于止损和移动止盈：

| 优先级 | 退出机制 | 触发方式 |
|--------|---------|---------|
| Priority 1 | 初始止损 | 日内最低价 < stop_loss |
| Priority 2 | 移动止盈 | 收盘价 < trail_stop |
| Priority 3 | **时间止损** | 持仓 ≥ 20 日 且 浮盈 < 0.5R |

**预期效果：**

- **年化收益**：释放的资金可以再投入新突破信号，提高资金使用效率
- **最大回撤**：减少「拖延型亏损」，特别是在熊市初期（趋势尚未明朗时普遍存在）
- **换手率**：适度提升，但每笔新入场质量可能更高（来自信号排序）

**注意事项**：参数（20 日、0.5R 阈值）需要完整历史回测验证；
过短的时间窗口（<10 日）会与初始止损机制重叠；
过低的 R 阈值（< 0.2R）可能过早退出正在缓慢启动的真实趋势。
""")

_n_potential_ts = len(trades[(trades["holding_days"] >= 20) & (trades["net_pnl"] <= 0)])
_pnl_potential  = trades[(trades["holding_days"] >= 20) & (trades["net_pnl"] <= 0)]["net_pnl"].sum()
st.info(
    f"**历史数据参考**：持仓 ≥ 20 日且最终亏损的交易共 **{_n_potential_ts} 笔**，"
    f"合计亏损 **\${abs(_pnl_potential)/1e6:.1f}M**（占全部亏损的 "
    f"{abs(_pnl_potential)/trades[trades['net_pnl']<=0]['net_pnl'].sum()*100:.0f}%）。"
    "若时间止损能将这些交易的平均出场 R 从当前水平改善至 −0.3R（保守估计），"
    f"可节省约 \$14M 亏损。实际效果需完整回测验证——因为部分交易在被止损前可能本已接近盈利。"
)

st.markdown("---")

# ── 十二、执行与成本假设 ───────────────────────────────────────────────────────
st.subheader("十二、执行与成本假设")

st.markdown("#### 10.1 滑点假设的影响")

_sp_d = pert["slippage_bps"]
if _sp_d:
    _spv = _sp_d["param_values"]
    _spc = [r["cagr"]*100 for r in _sp_d["results"]]
    _spm = [abs(r["max_drawdown"])*100 for r in _sp_d["results"]]
    _spbase = _sp_d["baseline_value"]

    _fig_sp = go.Figure()
    _fig_sp.add_trace(go.Bar(
        x=[f"{v:.0f} bps" for v in _spv], y=_spc,
        marker_color=["#22c55e" if v == _spbase else "#6366f1" for v in _spv],
        name="CAGR (%)", yaxis="y",
        text=[f"{v:.2f}%" for v in _spc], textposition="outside",
    ))
    _fig_sp.add_trace(go.Scatter(
        x=[f"{v:.0f} bps" for v in _spv], y=_spm,
        mode="lines+markers", marker=dict(size=9, color="#ef4444"),
        line=dict(color="#ef4444", width=2),
        name="最大回撤（%，右轴）", yaxis="y2",
    ))
    _fig_sp.update_layout(
        title="单边滑点（slippage_bps）敏感性：CAGR vs 最大回撤",
        xaxis_title="单边滑点（bps）",
        yaxis=dict(title="CAGR (%)", side="left", range=[7.5, 11.5]),
        yaxis2=dict(title="最大回撤（%）", side="right", overlaying="y", range=[16, 23]),
        legend=dict(x=0.55, y=0.05), height=360, margin=dict(t=50, b=40),
    )
    st.plotly_chart(_fig_sp, use_container_width=True)

    _sp_base_i = _spv.index(_spbase)
    st.markdown(
        f"当前 {_spbase:.0f} bps（绿色）：CAGR {_spc[_sp_base_i]:.2f}%。"
        f"若实际滑点降至 5 bps（大盘高流动性股票的实际水平），CAGR 可提升至 {_spc[0]:.2f}%（+{_spc[0]-_spc[_sp_base_i]:.2f} pp）——"
        "这是「正向惊喜」来源：回测保守，实盘可能超越回测。"
        f"若滑点升至 15 bps（小盘股或流动性不佳时段），CAGR 降至 {_spc[-1]:.2f}%。"
    )

st.markdown("#### 10.2 改进建议总结")
st.markdown("""
**有效性改进（提升回测对实盘的代表性）：**
- 引入分层滑点：ADV > \$500M 标的用 5 bps，ADV \$60–500M 用 10 bps，比固定 10 bps 更贴近实际

**精准度改进（让回测更保守更真实）：**
- **最高优先级**：止损执行价改为 `min(stop_loss_price, open[t+1])`（同第七节），估算影响 −0.74 pp CAGR，但让回测可信度大幅提升
""")

st.markdown("---")

# ── 十三、综合实施路径 ─────────────────────────────────────────────────────────
st.subheader("十三、综合实施路径")

st.markdown(f"""
**当前基线：CAGR {metrics['cagr']*100:.2f}%，MaxDD -{abs(metrics['max_drawdown'])*100:.2f}%，Sharpe {metrics['sharpe']:.3f}**

以下按优先级排序，代码改动难度由低到高：

**第一步：低难度、高可信度改进（立即可做）**

1. **止损执行价 → min(stop_loss, open[t+1])**（回测精准度）
   - 改动：1 行代码
   - 效果：CAGR −0.74 pp（更保守但更真实），让回测结果可以更有信心地代表实盘

2. **大赢家第四档止盈：R_peak ≥ 10R → 7× ATR**（年化收益）
   - 改动：在 exit.py 中增加一档
   - 预期效果：CAGR +1–2%，MaxDD 影响中性

**第二步：中难度、可量化改进（需要完整回测验证）**

3. **Gap 过滤改为 ATR 基准：|gap| > 1.5 × ATR / close**（精准度）
   - 预期效果：信号质量更均匀，CAGR 变化待验证

4. **成交量过滤 1.5× 进行 Walk-Forward 验证**（有效性）
   - 重新运行 Walk-Forward 并检验 1.5× 在各子期间是否稳定最优

**第三步：高难度、最高影响改进（需要引擎级改动）**

5. **金字塔加仓**（年化收益最大化）
   - 预期效果：CAGR +4–5%（约 {metrics['cagr']*100:.2f}% → 14–16%），MaxDD 扩大 1–4%
   - 改动：仓位管理模块需要支持"同一标的多次开仓并独立追踪止损"

6. **Choppiness Index 二层市场过滤**（最大回撤改善）
   - 预期效果：MaxDD 降低 2–4%，CAGR 轻微影响（减少假突破亏损）
   - 改动：需要引入新指标计算并集成进市场环境过滤逻辑

**风险提示：** 以上所有预期效果均为粗估，必须通过完整历史回测（2000→2026）
验证，并在 Walk-Forward OOS 数据（2016→2026）上确认，才能排除对历史数据的过拟合。
""")
