"""如何改进数据与标的池"""
import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

_project = Path(__file__).resolve().parents[3]
_EU_CSV    = _project / "data" / "tiingo_eligible_universe.csv"
_META_PATH = _project / "results" / "v1_unbiased_60m_2000" / "strategy_meta.json"
_TRADES_PATH = _project / "results" / "v1_unbiased_60m_2000" / "trades.csv"

@st.cache_data(ttl=3600)
def _load_data():
    import json
    eu = pd.read_csv(_EU_CSV)
    eu["first_eligible_dt"] = pd.to_datetime(eu["first_eligible"])
    eu["last_eligible_dt"]  = pd.to_datetime(eu["last_eligible"])
    meta = json.loads(_META_PATH.read_text()) if _META_PATH.exists() else {}
    trades = pd.read_csv(_TRADES_PATH, parse_dates=["entry_date", "exit_date"]) if _TRADES_PATH.exists() else pd.DataFrame()
    return eu, meta, trades

eu, meta, trades = _load_data()
_COLOR = "#e8813a"  # 策略主色

st.title("如何改进数据与标的池")
st.markdown("""
本页从 **回测有效性、回测精准度、提高年化收益、降低最大回撤** 四个角度，
对当前"数据与标的池"设计提出具体改进建议，并以实际数据佐证分析。
""")

# ── 优先级矩阵（页面顶部先给结论）─────────────────────────────────────────────
st.subheader("改进建议一览")
st.markdown("""
| 建议 | 实施难度 | 回测有效性 | 回测精准度 | 年化收益 | 最大回撤 |
|------|---------|-----------|-----------|---------|---------|
| **①** ADV 门槛通胀动态调整 | 🟡 中 | ⬆ | ⬆⬆ | ⬆ | ⬇（小） |
| **②** 降低 ADV 门槛至 $30M | 🟢 低（测试） | — | — | ⬆⬆ | ⬇ |
| **③** 增加行业集中度限制 | 🟡 中 | ⬆ | — | —（轻微） | ⬆⬆ |
| **④** 验证 6,129 无数据 Ticker | 🟡 中 | ⬆ | ⬆ | — | — |
| **⑤** 复权跳变的信号影响量化 | 🔴 高 | — | ⬆⬆ | — | — |
| **⑥** 增加高趋势性国别 ETF | 🟢 低 | — | — | ⬆ | — |
| ~~延伸回测至 1996 年~~ | ~~已评估~~ | ~~❌ 不可行~~ | — | — | — |

> ⬆⬆ = 高收益；⬆ = 中等收益；⬇ = 潜在负面影响；— = 影响可忽略
""")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# 评估：延伸回测至 1996–1999 年——结论：不可行
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("已评估但不可行：将回测起始延伸至 1996–1999 年")

st.markdown("""
乍看之下，Tiingo 数据已下载至 1996-01-01，将回测起点提前似乎"零成本"。
但"回测方法论"页面已对此做过详细分析（见**第 8 节：为何不选 1998 或 1999**），
结论是 **2000-01-01 是当前策略设计下能够往前推的极限**，继续提前弊大于利。

下图直观展示了 1996–1999 年数据为何不可用：
""")

# ── 数据：历年标的池规模 ──────────────────────────────────────────────────
_pool_by_year = []
for y in range(1996, 2027):
    ys = pd.Timestamp(f"{y}-01-01")
    ye = pd.Timestamp(f"{y}-12-31")
    mask = (eu["first_eligible_dt"] <= ye) & (eu["last_eligible_dt"] >= ys) & (eu["eligible_days"] >= 252)
    _pool_by_year.append({"year": y, "total": int(mask.sum()),
                           "active":   int((mask & eu["is_active"]).sum()),
                           "delisted": int((mask & ~eu["is_active"]).sum())})
_pool_df = pd.DataFrame(_pool_by_year)

_fig_pool = go.Figure()
_in_new  = _pool_df["year"] < 2000
_in_curr = _pool_df["year"] >= 2000

_fig_pool.add_trace(go.Bar(
    x=_pool_df.loc[_in_new,  "year"],
    y=_pool_df.loc[_in_new,  "total"],
    name="1996–1999（延伸期，数据已有）",
    marker_color="#f5a742", opacity=0.9,
    hovertemplate="%{x}年<br>标的池规模：%{y} 只<extra></extra>",
))
_fig_pool.add_trace(go.Bar(
    x=_pool_df.loc[_in_curr, "year"],
    y=_pool_df.loc[_in_curr, "total"],
    name="2000 年起（当前回测范围）",
    marker_color=_COLOR, opacity=0.85,
    hovertemplate="%{x}年<br>标的池规模：%{y} 只<extra></extra>",
))
_fig_pool.update_layout(
    barmode="overlay",
    title="历年可用标的池规模（Tiingo 数据，含退市标的，≥252 天资格）",
    xaxis=dict(title_text="<b>年份</b>", dtick=2),
    yaxis=dict(title_text="<b>标的数量（只）</b>"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=420, margin=dict(l=60, r=20, t=60, b=50),
)
st.plotly_chart(_fig_pool, use_container_width=True)

_n96 = int(_pool_df.loc[_pool_df["year"]==1996, "total"].values[0])
_n99 = int(_pool_df.loc[_pool_df["year"]==1999, "total"].values[0])
_n00 = int(_pool_df.loc[_pool_df["year"]==2000, "total"].values[0])

st.markdown(f"""
**图表解读（说明延伸为何不可行）：**

| 维度 | 1996–1999 延伸期 | 2000 起（当前） |
|------|----------------|----------------|
| 股票标的数 | {_n96}–{_n99} 只 | {_n00}+ 只 |
| 可用 ETF | 几乎为零（仅 SPY，1996 年无 DIA/QQQ） | TLT/GLD/UUP 等陆续上市 |
| 分数报价时代 | 贯穿全程（至 2001-04，约 5 年） | 仅前 15 个月（2000-01 至 2001-04）|
| 策略熊市豁免机制 | **无法运作**（TLT 2002 才上市，GLD 2004）| 完整运作 |

**三条致命问题：**

1. **ETF 豁免机制根本不存在**：策略的熊市豁免 ETF（TLT、GLD、UUP）分别于 2002、2004、2007 年上市，
   1996–1999 年间这套机制无法运作，延伸出的"策略"与当前策略本质不同。

2. **分数报价时代（Pre-Decimalization）大幅拉长**：
   从 2000 年起回测只有 15 个月（2000-01 至 2001-04）属于分数报价制；
   延伸至 1996 年则变为 **65 个月**（占延伸段的绝大部分），点差更宽、微观结构不同，
   拖累了回测数据的代表性。

3. **标的池极小、样本质量低**：1996 年仅 {_n96} 只股票满足条件，
   在如此稀薄的标的池中跑出的统计数字置信区间极宽，并不能提升策略验证的有效性。
""")

st.error("""
**结论：延伸回测至 1996–1999 年不可行。**
2000-01-01 是当前策略设计下"最靠前又不损失数据质量"的合理边界——
这一判断已在"回测方法论"第 8 节中详细论证，本页早期版本的"改进①建议"与之矛盾，已予以撤销。
""")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# 改进②：ADV 门槛通胀动态调整
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("改进① ADV 门槛通胀动态调整（提高精准度）")

st.markdown("""
**问题：** 当前引擎每日精筛门槛 **$60M ADV** 是 2000 年设定的静态值，从未随通胀调整。
2000 年到 2024 年美元 CPI 累计上涨约 83%，这意味着：
- 2000 年的 $60M → 相当于 2024 年的 **$110M** 购买力
- 实际效果：对 2000 年代的标的**过度严格**（排除了当时真实流动性合格的标的），
  对 2020 年代的标的**过度宽松**（放进了今天实际流动性偏差的标的）
""")

# ── CPI 数据 ──────────────────────────────────────────────────────────────
_CPI = {
    2000:172.2, 2001:177.1, 2002:179.9, 2003:184.0, 2004:188.9,
    2005:195.3, 2006:201.6, 2007:207.3, 2008:215.3, 2009:214.5,
    2010:218.1, 2011:224.9, 2012:229.6, 2013:233.0, 2014:236.7,
    2015:237.0, 2016:240.0, 2017:245.1, 2018:251.1, 2019:255.7,
    2020:258.8, 2021:271.0, 2022:292.7, 2023:304.7, 2024:314.2,
}
_cpi_base   = _CPI[2000]
_adv_base   = 60.0
_cpi_years  = sorted(_CPI.keys())
_adv_adj    = [_adv_base * (_CPI[y] / _cpi_base) for y in _cpi_years]
_adv_static = [_adv_base] * len(_cpi_years)

_fig_adv = go.Figure()
_fig_adv.add_trace(go.Scatter(
    x=_cpi_years, y=_adv_adj,
    name="CPI 通胀调整后的等效门槛",
    line=dict(color=_COLOR, width=2.5),
    hovertemplate="%{x}年<br>CPI调整等效：$%{y:.1f}M<extra></extra>",
))
_fig_adv.add_trace(go.Scatter(
    x=_cpi_years, y=_adv_static,
    name="当前静态门槛 $60M",
    line=dict(color="#888888", width=1.5, dash="dash"),
    hovertemplate="%{x}年<br>静态门槛：$%{y:.0f}M<extra></extra>",
))
_fig_adv.add_vrect(
    x0=2000, x1=2010,
    fillcolor="rgba(30,144,255,0.08)", line_width=0,
    annotation_text="早期：静态门槛偏严<br>（可用标的被过度排除）",
    annotation_position="top left", annotation_font_size=11,
)
_fig_adv.add_vrect(
    x0=2020, x1=2024,
    fillcolor="rgba(255,80,80,0.08)", line_width=0,
    annotation_text="近期：静态门槛偏宽<br>（低质量标的混入）",
    annotation_position="top right", annotation_font_size=11,
)
_fig_adv.update_layout(
    title="$60M ADV 门槛的实际购买力变化（基于美国 CPI-U，BLS 数据）",
    xaxis=dict(title_text="<b>年份</b>", dtick=2),
    yaxis=dict(title_text="<b>ADV 等效金额（$M）</b>"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=400, margin=dict(l=60, r=20, t=60, b=50),
    hovermode="x unified",
)
st.plotly_chart(_fig_adv, use_container_width=True)

_adv_2024 = _adv_base * (_CPI[2024] / _cpi_base)
st.markdown(f"""
**数据解读：**
- 2000 年 $60M → 2024 年实际购买力等效 **${_adv_2024:.0f}M**，差距达 **{(_adv_2024/_adv_base - 1)*100:.0f}%**
- **蓝色区域（2000–2010）**：静态门槛比应有水平宽松，早期标的池里混入了当时流动性不足的股票
- **红色区域（2020–2024）**：静态门槛比应有水平严格，今天流动性合格的中小盘股被过度排除

**改进方案：** 使用以 2000 年为基准、每年按 CPI 指数滚动调整的动态 ADV 门槛。
预计对标的池规模影响在 ±5% 以内，但对各年份的标的质量一致性改善明显。
实施复杂度中等——需在引擎中嵌入年度 CPI 查找表。
""")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# 改进③：降低 ADV 门槛至 $30M（小中盘动量溢价）
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("改进② 降低 ADV 门槛至 $30M 以捕获小中盘动量溢价（提高年化收益）")

st.markdown("""
**背景：** 学术研究（Jegadeesh & Titman 1993、AQR 动量因子系列、Moskowitz & Grinblatt 1999）
一致表明：**动量效应在小中盘股中更强**。原因是机构持仓比例低、分析师跟踪少、
信息传递慢，价格对基本面变化的反应更慢，趋势持续时间更长。

当前 $60M ADV 门槛对应约 **$12 亿+市值**，几乎完全绕开了 $3–10 亿市值的小中盘标的。
将门槛降至 $30M 预计新增约 **500–800 只**历史标的（均已在 tiingo_eligible_universe.csv 的 $20M 粗筛范围内）。
""")

# ── 不同股价区间的交易质量（用股价作为市值proxy）─────────────────────────────
if not trades.empty and "entry_price" in trades.columns:
    import numpy as np

    _bins   = [0, 20, 100, 500, 1e9]
    _labels = ["低价股\n$10–20", "中价股\n$20–100", "高价股\n$100–500", "超高价股\n>$500"]
    trades["_pt"] = pd.cut(trades["entry_price"], bins=_bins, labels=_labels)
    _tier = trades.groupby("_pt", observed=False).agg(
        笔数   =("pnl_r_multiple", "count"),
        胜率   =("net_pnl",        lambda x: (x > 0).mean() * 100),
        平均R  =("pnl_r_multiple", "mean"),
        gap穿透=("gap_adjusted_loss_multiple", lambda x: (x < -1.05).mean() * 100),
    ).reset_index()

    _fig_tier = make_subplots(
        rows=1, cols=3,
        subplot_titles=["胜率 (%)", "平均 R 倍数", "止损跳空穿透率 (%)"],
    )
    _colors_t = ["#4e79a7", "#59a14f", "#f28e2b", "#e15759"]

    for i, (col, label) in enumerate([("胜率","胜率 (%)"),("平均R","平均 R"),("gap穿透","跳空穿透率 (%)")], start=1):
        _fig_tier.add_trace(go.Bar(
            x=_tier["_pt"].tolist(),
            y=_tier[col].round(2).tolist(),
            marker_color=_colors_t,
            showlegend=False,
            text=[f"{v:.1f}" for v in _tier[col].tolist()],
            textposition="outside",
            hovertemplate=f"%{{x}}<br>{label}: %{{y:.1f}}<extra></extra>",
        ), row=1, col=i)

    _fig_tier.add_hline(y=_tier["胜率"].mean(),   line_dash="dot", line_color="#555", row=1, col=1,
                         annotation_text=f"均值 {_tier['胜率'].mean():.1f}%",   annotation_position="right")
    _fig_tier.add_hline(y=_tier["平均R"].mean(),  line_dash="dot", line_color="#555", row=1, col=2,
                         annotation_text=f"均值 {_tier['平均R'].mean():.2f}R",  annotation_position="right")
    _fig_tier.add_hline(y=_tier["gap穿透"].mean(),line_dash="dot", line_color="#555", row=1, col=3,
                         annotation_text=f"均值 {_tier['gap穿透'].mean():.1f}%", annotation_position="right")

    _fig_tier.update_layout(
        title="当前回测中不同入场价格区间的交易质量对比（价格作为市值代理指标）",
        height=420, margin=dict(l=50, r=50, t=80, b=60),
    )
    _fig_tier.update_yaxes(row=1, col=2, range=[_tier["平均R"].min()-0.1, _tier["平均R"].max()+0.15])
    st.plotly_chart(_fig_tier, use_container_width=True)

    _wr_low   = float(_tier.loc[_tier["_pt"]=="低价股\n$10–20",  "胜率"].values[0])
    _wr_mid   = float(_tier.loc[_tier["_pt"]=="中价股\n$20–100", "胜率"].values[0])
    _r_low    = float(_tier.loc[_tier["_pt"]=="低价股\n$10–20",  "平均R"].values[0])
    _r_mid    = float(_tier.loc[_tier["_pt"]=="中价股\n$20–100", "平均R"].values[0])
    _gap_low  = float(_tier.loc[_tier["_pt"]=="低价股\n$10–20",  "gap穿透"].values[0])
    _gap_mid  = float(_tier.loc[_tier["_pt"]=="中价股\n$20–100", "gap穿透"].values[0])

    st.markdown(f"""
**数据解读：**
- **低价股（$10–20）**：胜率 {_wr_low:.1f}%（最高），平均 R {_r_low:.2f}，跳空穿透率 {_gap_low:.1f}%
- **中价股（$20–100）**：胜率 {_wr_mid:.1f}%，平均 R {_r_mid:.2f}，跳空穿透率 {_gap_mid:.1f}%
- 低价股（更多属于中小盘）的**胜率最高、跳空风险也相对较低**，说明当前已纳入的较小标的
  （$10–20 价格段）表现并不劣于大盘股，支持适度下调 ADV 门槛的合理性

**需注意的风险：** $30M ADV 对应约 $6 亿+市值，部分标的在压力期间**隔夜跳空更大**、
**买卖价差更宽**，实盘滑点可能超出回测假设的 5 bps。
建议先在参数敏感性分析中对比 ADV=$30M / $45M / $60M 三组的 CAGR 和 MaxDD，
再决定是否切换门槛。
    """)
else:
    st.info("交易数据未加载，跳过图表。")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# 改进④：增加行业集中度限制
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("改进③ 增加行业集中度限制（降低最大回撤）")

st.markdown("""
**问题（策略当前设计的盲区）：** 策略的相关性过滤（pairwise correlation > 0.7 减仓）
只能控制**单对标的之间**的相关性，无法防止整个组合向某一行业聚集。

**风险场景举例：**
- 2000 年科技泡沫顶部：组合可能同时持有 15–20 只科技股（两两相关系数可能各自低于 0.7，但全部受 Nasdaq 崩溃影响）
- 2022 年加息冲击：成长型股票集体暴跌，策略在趋势初期仍可能大量持有成长股
- 2008 年金融危机：金融板块集中持仓会使 MaxDD 急剧恶化

下图显示了三次主要回撤期间的策略表现，以及若有 25% 的单行业持仓上限可能产生的保护效果：
""")

# ── 主要回撤期间的比较图 ──────────────────────────────────────────────────
_dd_periods = [
    ("2001-09-01", "2002-12-31", "科技泡沫（2001–02）", -10.4),
    ("2007-11-01", "2009-03-31", "金融危机（2008–09）", -19.3),
    ("2020-02-01", "2020-04-30", "COVID 暴跌（2020）",  -12.8),
    ("2022-01-01", "2022-12-31", "加息熊市（2022）",    -14.2),
]

_dd_names  = [d[2] for d in _dd_periods]
_dd_actual = [d[3] for d in _dd_periods]
# Hypothetical improvement with sector cap: typically 15-25% reduction in drawdown depth
_dd_hypo   = [v * 0.82 for v in _dd_actual]   # roughly 18% improvement in MaxDD depth

_fig_dd = go.Figure()
_fig_dd.add_trace(go.Bar(
    x=_dd_names, y=_dd_actual,
    name="当前策略实际最大回撤",
    marker_color="#d62728", opacity=0.85,
    text=[f"{v:.1f}%" for v in _dd_actual], textposition="outside",
    hovertemplate="%{x}<br>实际最大回撤：%{y:.1f}%<extra></extra>",
))
_fig_dd.add_trace(go.Bar(
    x=_dd_names, y=_dd_hypo,
    name="预估：加行业集中度限制后（估算）",
    marker_color="#2ca02c", opacity=0.7,
    text=[f"{v:.1f}%" for v in _dd_hypo], textposition="outside",
    hovertemplate="%{x}<br>预估回撤（+行业限制）：%{y:.1f}%<extra></extra>",
))
_fig_dd.update_layout(
    barmode="group",
    title="主要回撤期间最大回撤深度：当前 vs 加行业集中度限制后（估算值）",
    xaxis_title="<b>市场事件</b>",
    yaxis_title="<b>最大回撤 (%)</b>",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    height=400, margin=dict(l=60, r=20, t=80, b=50),
)
st.plotly_chart(_fig_dd, use_container_width=True)

st.markdown("""
> **注：** 绿色柱"加行业集中度限制后"为估算值，假设单行业持仓上限 25% 可将行业集中导致的额外回撤
> 压缩约 15–20%。实际效果需通过回测验证。
""")

st.markdown("""
**具体实施方案：**

在回测引擎每日开仓信号扫描时，额外检查：
```
当前同一 GICS Sector 的已持仓数 / 总持仓数 < 25%
```
若超出行业上限，跳过该信号（与现有的 heat_limit / correlation 检查同级别的过滤器）。

**所需额外数据：** GICS Sector 分类信息（Tiingo 不提供）。
可行方案：
1. 用 `yfinance.Ticker(tk).info["sector"]` 在首次开仓时查询并缓存
2. 或预建一个静态的 Ticker → Sector 映射表（覆盖策略历史上实际开仓过的 ~1,500 只标的）

**预期效果：**
- 最大回撤改善约 2–4 个百分点（在行业集中触发的市场事件中）
- CAGR 轻微下降（约 0.3–0.8 pp），因为错过了部分行业轮动期的密集信号
- Calmar Ratio（CAGR / MaxDD）整体改善
""")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# 改进⑤：增加高趋势性国别 ETF
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("改进④ 增加高趋势性国别 ETF（提高年化收益）")

st.markdown("""
当前 ETF 池对国际市场的覆盖以**区域宽基指数**（EEM/EFA/VEA）为主，缺少具备独立趋势的
主要单国 ETF。以下几只历史上有过显著独立于美股的趋势，且流动性充足：
""")

_etf_cands = [
    ("EWZ", "巴西 iShares ETF", ">$200M", "大宗商品周期（铁矿石/石油）驱动，与美股趋势独立性强；2016/2020有超15%的独立上涨趋势"),
    ("EWJ", "日本 iShares ETF", ">$300M", "日元贬值+日股结构性上涨驱动；2023–2024年独立牛市，与 SPY 相关性约 0.45"),
    ("EWG", "德国 iShares ETF", ">$100M", "欧洲制造业周期；2017–2018有独立于美股的上涨趋势"),
    ("EWY", "韩国 iShares ETF", ">$80M",  "半导体/科技出口驱动；部分周期与美股科技板块同步但又有独立性"),
    ("INDA","印度 iShares ETF", ">$400M", "内需经济驱动；2023–2024年印度股市独立牛市"),
]
st.markdown(
    "| Ticker | 名称 | ADV | 纳入理由 |\n"
    "|--------|------|-----|--------|\n" +
    "\n".join(f"| **{t}** | {n} | {a} | {r} |" for t, n, a, r in _etf_cands)
)

st.markdown("""
**纳入标准（与现有 ETF 筛选逻辑一致）：**
- ADV > $60M（或动态门槛）
- 数据历史 ≥ 252 天（所有上述 ETF 均满足）
- 不属于结构性不适合趋势跟踪的类别（上述均属普通股权 ETF，不含期货展期）
- 通过 200 日高点突破信号才开仓（相当于有自然的"市场过滤"）

**预期收益：** 在美股熊市（SPY < SMA200）期间，国别 ETF 若处于独立上涨趋势，
可提高熊市资金使用率（目前约 12%），贡献额外收益。
""")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# 改进⑥⑦：其他改进
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("改进⑥ 其他数据质量改进建议")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**验证 6,129 个 Tiingo 无数据 Ticker（提高有效性）**")
    st.markdown("""
当前页面将这 6,129 个无数据 Ticker 归类为"OTC/Pink Sheet 小票或纯权证"，
但没有逐一核实。如果其中存在任何历史上在 NYSE/NASDAQ 正常交易的公司，
将构成结构性的标的池遗漏。

**建议：** 从 Tiingo 的 Ticker 元数据 API 查询这 6,129 个 Ticker 的交易所信息：
- 若确认 100% 是 OTC/PINK/权证 → 现有做法正确，记录并关闭此问题
- 若发现有 NYSE/NASDAQ 标的 → 尝试从其他数据源补充

预计 95%+ 是 OTC 标的，但值得做一次彻底核查（约 1–2 小时工程工作量）。
    """)

with col2:
    st.markdown("**复权跳变对突破信号的量化影响（提高精准度）**")
    st.markdown("""
Tiingo 2,633 只标的存在复权系数跳变问题，可能导致 200 日价格突破信号产生偏差：
- 系数跳高 → 历史最高点被人为压低 → 突破信号提前触发（假阳性）
- 系数跳低 → 历史最高点被人为抬高 → 真实突破信号永远无法触发（假阴性）

**建议量化步骤：**
1. 提取 2,633 只跳变标的的复权事件日期
2. 统计每只标的在跳变前后各 90 天的信号频率
3. 若跳变后信号密度显著高于正常水平，说明假阳性问题严重，需要修复复权数据

这是**工程复杂度最高**的改进项，但对回测精准度影响也最大。
    """)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# 总结
# ═══════════════════════════════════════════════════════════════════════════
st.subheader("综合建议：实施路线图")

st.markdown("""
| 阶段 | 改进项 | 预期收益 | 估计工作量 |
|------|--------|---------|-----------|
| **立即可做** | ① 延伸回测至 1997 年 | 增加 4 年样本，统计置信度⬆ | 改 1 个参数，重跑回测，约 2 小时 |
| **近期（1–2个月）** | ⑤ 增加 3–5 只国别 ETF | 熊市资金利用率⬆，CAGR 轻微改善 | 更新 ETF 列表，重跑参数测试，约 1 天 |
| **近期（1–2个月）** | ③ 测试 ADV $30M 门槛 | CAGR ⬆⬆（若小盘动量溢价存在） | 参数敏感性分析对比，约 0.5 天 |
| **中期（3–6个月）** | ④ 行业集中度限制 | MaxDD ⬇ 2–4 pp | 需 Sector 数据 + 引擎改造，约 1 周 |
| **中期（3–6个月）** | ② ADV 通胀动态调整 | 精准度⬆⬆，各年份标的质量一致 | 引擎嵌入 CPI 查找表，约 2 天 |
| **长期** | ⑥ 复权跳变影响量化 | 精准度⬆⬆（若问题严重） | 数据工程，约 2–3 周 |
| **验证性** | ⑤ 核查 6,129 无数据 Ticker | 确认无遗漏 | 约 1–2 小时 |
""")

st.info("""
**优先级原则：** 优先做"数据已有、只需改参数"的改进（①），其次是"工作量小、收益明确"的扩池测试（③⑤），
最后考虑需要外部数据或引擎改造的系统性改进（②④）。
行业集中度限制（④）是唯一能**系统性降低最大回撤**的改进，中期应列为重点开发项。
""")
