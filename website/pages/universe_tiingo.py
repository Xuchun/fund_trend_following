"""数据与标的池 — 无幸存者偏差动态标的池"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

_project = Path(__file__).resolve().parents[2]

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from website.style import show_df
# ── 数据路径 ──────────────────────────────────────────────────────────────────
_EU_CSV = _project / "data" / "tiingo_eligible_universe.csv"


st.markdown("""
<style>
@media print {
    [data-testid="stSidebar"],
    [data-testid="stSidebarNav"],
    [data-testid="stHeader"],
    [data-testid="stDecoration"],
    [data-testid="stToolbar"],
    [data-testid="stStatusWidget"],
    header, footer,
    .stApp > header { display: none !important; }
    iframe { display: none !important; }
    .main .block-container,
    [data-testid="stMainBlockContainer"] {
        padding-top: 0.5cm !important;
        padding-left: 1cm !important;
        padding-right: 1cm !important;
        max-width: 100% !important;
    }
    @page { margin: 1.5cm; }
    .stPlotlyChart,
    [data-testid="stDataFrame"],
    [data-testid="stAlert"] { page-break-inside: avoid; }
    h2, h3 { page-break-after: avoid; }
}
</style>
""", unsafe_allow_html=True)

import streamlit.components.v1 as _components_v1

_col_u_title, _col_u_right = st.columns([4, 2])
with _col_u_title:
    st.title("数据与标的池")
with _col_u_right:
    _components_v1.html("""
    <div style="display:flex;justify-content:flex-end;align-items:center;height:46px;">
        <button onclick="window.top.print()"
            title="打开打印对话框后选择「存储为 PDF」即可下载"
            style="background:#1565c0;color:#fff;border:none;padding:7px 16px;
                   border-radius:5px;cursor:pointer;font-size:13px;
                   font-family:sans-serif;white-space:nowrap;">📄 下载 PDF</button>
    </div>
    """, height=50)
st.markdown("---")


@st.cache_data(show_spinner=False, ttl=3600)
def _load_universe() -> pd.DataFrame:
    df = pd.read_csv(_EU_CSV)
    df["first_eligible"] = pd.to_datetime(df["first_eligible"])
    df["last_eligible"]  = pd.to_datetime(df["last_eligible"])
    df["data_start"]     = pd.to_datetime(df["data_start"])
    df["data_end"]       = pd.to_datetime(df["data_end"])
    return df


if not _EU_CSV.exists():
    st.error(f"标的池文件未找到：{_EU_CSV}\n请先运行 `python src/scripts/08_eligible_universe.py`")
    st.stop()

eu = _load_universe()
active   = eu[eu["is_active"]]
delisted = eu[~eu["is_active"]]

# ── 结构性排除名单（与回测引擎排除逻辑一致） ──────────────────────────────────
# 1. 结构性不适合趋势跟踪的 vol/inverse ETF
_EXCL_ETFS = {"FXI", "GDX", "KWEB", "VXX", "EMB", "ASHR", "ETH"}
# 2. 辅助标的（引擎用作市场环境指标和现金代理，不参与交易）
_EXCL_AUX  = {"SPY", "SHY"}
_EXCL_ALL  = _EXCL_ETFS | _EXCL_AUX

# ≥252 天（1年）过滤 + 排除所有非交易标的 → 与回测实际策略池完全一致（2,976 个）
MIN_ELIGIBLE_DAYS = 252
eu_rec     = eu[(eu["eligible_days"] >= MIN_ELIGIBLE_DAYS) & (~eu["ticker"].isin(_EXCL_ALL))]
rec_active = eu_rec[eu_rec["is_active"]]
rec_del    = eu_rec[~eu_rec["is_active"]]

# ── ETF 集合（来自 strategy_meta） ────────────────────────────────────────────
import json as _json_mod
_META_PATH = _project / "results" / "v1_unbiased_60m_2000" / "strategy_meta.json"
_meta: dict = {}
_ETF_SET: set[str] = set()
if _META_PATH.exists():
    _meta = _json_mod.loads(_META_PATH.read_text())
    _ETF_SET = {e["ticker"] for e in _meta.get("etf_universe", [])}

# ETFs that pass the ≥252-day pool filter (used in descriptions before _etf is defined)
_pool_etf_count = int(eu[(eu["eligible_days"] >= MIN_ELIGIBLE_DAYS) & (~eu["ticker"].isin(_EXCL_ALL))]["ticker"].isin(_ETF_SET).sum()) if _ETF_SET else 0

# ── 动态日期变量（随数据更新自动刷新） ────────────────────────────────────────
_TIINGO_DOWNLOAD_START = "1996-01-01"                                # 下载脚本起始参数（静态）
_data_latest    = eu["data_end"].max().strftime("%Y-%m-%d")          # Tiingo 最新数据日（动态）
_backtest_start = _meta.get("backtest_start", "2000-01-03")          # 回测开始日（来自 strategy_meta）
_backtest_end   = _meta.get("backtest_end",   _data_latest)          # 回测结束日（来自 strategy_meta）
_download_yrs   = round((pd.Timestamp(_data_latest) - pd.Timestamp(_TIINGO_DOWNLOAD_START)).days / 365)
_backtest_yrs   = round((pd.Timestamp(_backtest_end) - pd.Timestamp(_backtest_start)).days / 365)
_start_year     = pd.Timestamp(_backtest_start).year
_end_year       = pd.Timestamp(_backtest_end).year

st.subheader("Tiingo 数据说明")
st.markdown(f"""
| 项目 | 详情 |
|------|------|
| **数据来源** | [Tiingo](https://www.tiingo.com/) EOD（End-of-Day）历史价格 API |
| **原始下载范围** | {_TIINGO_DOWNLOAD_START} → {_data_latest}（约 {_download_yrs} 年） |
| **回测使用范围** | {_backtest_start} → {_backtest_end}（约 {_backtest_yrs} 年） |
| **覆盖标的** | NYSE / NASDAQ / AMEX 全量历史股票 + {len(_ETF_SET)} 只跨资产 ETF |
| **下载 Ticker 总数** | 21,384（含 14,805 活跃 + 7,402 已退市/被收购）；成功下载 15,255 个，6,129 个因 Tiingo 无数据跳过 |
| **字段** | 开/高/低/收、复权收盘价、成交量（日度） |
| **含退市标的** | 是 — Tiingo 保留已退市、被收购、破产公司的完整历史数据 |
""", unsafe_allow_html=True)

_col_a, _col_b = st.columns(2)
with _col_a:
    st.markdown(f"""
**优势**
- 含退市/被收购标的 → 彻底消除幸存偏差
- 原始数据从 {_TIINGO_DOWNLOAD_START[:4]} 年起，具备 {_download_yrs} 年完整历史储备
- 当前回测使用 {_start_year} 年起数据，跨越多次完整牛熊周期
- 日度复权价格，精确处理拆股/分红
- {_pool_etf_count} 只 ETF 覆盖跨资产（股票指数、债券、大宗商品、REITs、加密、国防、建筑）
""")
with _col_b:
    st.markdown(f"""
**局限**
- 无日内数据（仅 EOD），无法做高频回测
- 无历史市值快照 → 策略改用 ADV（日均成交额）作流动性代理
- 量价数据可能被 Tiingo 事后修正（对历史回测有轻微影响）
- {_TIINGO_DOWNLOAD_START[:4]}–{_start_year - 1} 年数据已下载备用，暂未参与回测
- 不覆盖港股、A 股等非美交易所标的
""")

st.markdown("---")

# ── 标的池概览 ─────────────────────────────────────────────────────────────────
st.subheader(f"标的池概览（历史回测 {_backtest_start} → {_backtest_end}，标的过滤方法如下）")

_eu252 = eu_rec.copy()
_eu252["_is_etf"] = _eu252["ticker"].isin(_ETF_SET)
_stk = _eu252[~_eu252["_is_etf"]]
_etf = _eu252[_eu252["_is_etf"]]

_universe_total  = int(_meta.get("universe_total",  len(_eu252)))
_universe_stocks = int(_meta.get("universe_stocks", len(_stk)))
_universe_etfs   = int(_meta.get("universe_etfs",   len(_etf)))

_c1, _c2, _c3, _c4, _c5, _c6 = st.columns(6)
_c1.metric("股票数量", f"{_universe_stocks:,}",
           help="回测策略池中的股票数量（含退市/被收购历史标的）")
_c2.metric("股票仍在交易", f"{len(_stk[_stk['is_active']]):,}", help="目前仍在正常挂牌交易")
_c3.metric("股票已退市/收购", f"{len(_stk[~_stk['is_active']]):,}", help="历史上退市、破产或被收购，是消除幸存偏差的关键")
_c4.metric("ETF 数量", f"{_universe_etfs:,}",
           help="候选池共 88 只 ETF；排除 7 只结构性不适合 ETF + SPY（市场环境过滤）+ SHY（现金代理）= 84 只参与策略信号")
_c5.metric("ETF 仍在交易", f"{len(_etf[_etf['is_active']]):,}", help="目前仍在正常交易的 ETF")
_c6.metric("合计标的数", f"{_universe_total:,}",
           help=f"回测实际策略池总量 = {_universe_stocks:,} 只股票 + {_universe_etfs} 只 ETF；引擎每日动态按 ADV 阈值再过滤（默认 $60M）")

st.markdown("---")

# ── 一、过滤方法与理由 ─────────────────────────────────────────────────────────
st.subheader("标的池过滤方法")
st.markdown("""
策略 1.0 的原始标的池基于 **2024 年末在指数中的 S&P 900 成分股**，存在严重的**幸存者偏差**——
历史上破产、退市、被踢出指数的公司被完全排除在外。

为修正这一偏差，我们从 Tiingo 下载了 **NYSE / NASDAQ / AMEX 全量历史股票 + 88 只 ETF** 的日度价格数据
（含已退市标的），并使用以下**纯点对点（Point-in-Time）过滤条件**构建动态标的池：
""")

col_a, col_b = st.columns(2)
with col_a:
    st.markdown("""
**过滤条件 1：原始收盘价 > \$10**
- 使用**未复权**收盘价，与每天实际下单价格一致
- 排除低价股（Penny Stocks）：流动性差、点差大、容易被操纵
- 不使用复权价，避免历史分拆造成过滤结果偏差
""")
with col_b:
    st.markdown("""
**过滤条件 2：ADV₆₀ > \$20M（CSV 粗筛）／ > \$60M（引擎精筛）**
- ADV₆₀ = 60 日滚动平均日成交额 = close × volume（shift(1) 无前视偏差，不含当日）
- **标的池 CSV 构建时使用 \$20M 粗筛**：保证 ticker 有足够历史数据计算技术指标（ATR、突破信号等）
- **引擎每日执行时使用 \$60M 精筛**（Baseline 参数）：作为实际流动性门槛，对应约 \$12 亿+市值，防止实盘无法成交
- 两阶段设计：粗筛是超集，精筛是真正执行门槛，不引入选择偏差
""")

st.markdown("""
**过滤条件 3：数据长度 ≥ 1 年（252 个交易日）**
- 策略 1.0 的入场信号基于 **200 日价格突破**，上市不足 1 年的标的历史数据不足 200 日，永远无法触发有效突破信号
- 将极短命标的（如 SPAC、快速退市公司）提前排除，避免引擎空扫无效标的浪费计算资源
- 具体实现：仅纳入在价格 > \$10 且 ADV₆₀ > \$20M（粗筛口径）条件下，累计满足天数 ≥ 252 天的标的
""")

st.markdown("""
**过滤条件 1（price > \$10）和条件 2（ADV₆₀ > \$20M，粗筛）** 在标的池 CSV 构建时逐日计算，满足两个条件的每一天计入 eligible_days；**过滤条件 3（≥252 天）** 是静态预过滤，决定哪些 ticker 纳入标的池——保证每个 ticker 都有足够的历史数据计算指标。
引擎在每个回测交易日再次检查当日是否满足价格 > \$10 且 ADV₆₀ > \$60M（策略实际执行门槛），动态决定标的是否参与当日信号扫描。
这保证了整个回测过程中**不存在任何前视偏差或选择偏差**。

**额外排除：结构性不适合趋势跟踪的 ETF（两类）**

**第一类：波动率 / 反向 / 杠杆产品**（结构性负漂移）

| 代表产品 | 排除原因 |
|---------|---------|
| VXX、UVXY、VIXY | VIX 期货展期成本（Contango 损耗），长期必然亏损 |
| TQQQ、UPRO、SPXL、SQQQ | 每日复杠波动率拖拽，长期侵蚀本金 |
| SSO、SDS、SH | 反向产品与纯多头趋势跟踪逻辑矛盾 |
| LABU/LABD、NUGT/DUST | 日内重置，震荡市系统性损耗 |

**第二类：结构性不适合趋势跟踪的市场 / 资产类别**（经回测验证，有结构性依据）

| 代码 | 产品 | 排除原因 |
|------|------|---------|
| GDX | 黄金矿业 ETF | 矿业股有公司特有风险（罢工/矿区政治），趋势性远差于实物金；策略池已有 GLD/SLV，GDX 是噪声更大的重复暴露（回测：3笔 0% 胜率，亏损 \$105k） |
| FXI | 中国大盘股 ETF | 政府政策干预（2015 熔断、2021 科技整改、2023 房地产危机），200 日突破无法预判政策性大跌（回测：2笔 0% 胜率，亏损 \$44k） |
| ASHR | 中国 A 股 ETF | 同 FXI，A 股受资金流管控更直接（回测：1笔 0% 胜率，亏损 \$20k） |
| EMB | 新兴市场债券 ETF | 同时承受信用 + 利率 + 新兴市场三重风险；危机时与股票正相关，利率上行时又受久期拖累（回测：3笔 33% 胜率，亏损 \$70k，含 −4.9R 跳空） |
| KWEB | 中国互联网 ETF | 政策干预风险尤为突出（2021 年单年跌逾 50%） |

> **注**：排除决策基于结构性论据，方向上与回测亏损一致属于佐证，并非事后拟合。
""")

# ── 二、潜在缺陷 ──────────────────────────────────────────────────────────────
st.markdown("**标的池过滤方法潜在缺陷**")
st.markdown("""
| # | 缺陷 | 影响方向 | 说明 |
|---|------|---------|------|
| 1 | **无历史市值过滤** | 偏乐观 | Tiingo 无历史流通股数据，ADV > \$60M 代替市值 > \$12 亿，可能排除部分流动性刚达标的中盘标的 |
| 2 | **Tiingo 数据质量** | 中性 | 部分标的存在复权系数跳变（2,633 个）、价格尖峰（5,305 个），引擎的 is_tradable 标记已排除异常行 |
| 3 | **ADV 门槛静态** | 轻微 | \$60M 门槛 2000 年偏紧（美股流动性较低），2024 年偏宽；动态门槛可更精确但实现复杂 |
""")

st.info(
    "**综合评估**：上述缺陷均为次要影响。相比 S&P 900 的幸存者偏差（系统性高估收益），"
    "本标的池通过纳入已退市标的，大幅降低了回测结果的偏差，"
    "使回测更接近真实历史表现。"
)

st.markdown("---")

# ── 标的池分布图 ──────────────────────────────────────────────────────────────
st.subheader("标的池分布图")

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 满足条件时长分布",
    "📅 每年新进入标的",
    "📉 每年退市标的",
    "📈 历年标的池规模",
])

# ── Tab1: Duration distribution ────────────────────────────────────────────
with tab1:

    bins   = [252, 756, 1260, 2520, 99999]
    labels = ["1–3 年", "3–5 年", "5–10 年", ">10 年"]

    dur_active   = rec_active.copy()
    dur_delisted = rec_del.copy()
    dur_active["duration_bin"]   = pd.cut(dur_active["eligible_days"],   bins=bins, labels=labels, right=True)
    dur_delisted["duration_bin"] = pd.cut(dur_delisted["eligible_days"], bins=bins, labels=labels, right=True)

    g_act = dur_active["duration_bin"].value_counts().reindex(labels, fill_value=0)
    g_del = dur_delisted["duration_bin"].value_counts().reindex(labels, fill_value=0)

    _fig_dur = go.Figure()
    _fig_dur.add_bar(x=labels, y=g_act.values, name="现役", marker_color="#1565c0")
    _fig_dur.add_bar(x=labels, y=g_del.values, name="已退市", marker_color="#e57373")
    _fig_dur.update_layout(
        barmode="stack",
        xaxis_title="累计满足条件天数",
        yaxis_title="标的数量",
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.markdown(f"**基于标的池全部 {len(eu_rec):,} 个标的（现役 {len(rec_active):,} + 已退市 {len(rec_del):,}）**")
    st.plotly_chart(_fig_dur, width="stretch")

    st.markdown(f"""
**关键发现：**
- **>10 年（{g_act['>10 年']+g_del['>10 年']:,} 个）**：长期稳定的大中型股，是趋势跟踪策略的核心猎场，
  占最终标的池的 {(g_act['>10 年']+g_del['>10 年'])/len(eu_rec)*100:.0f}%。
- **1–3 年（{g_act['1–3 年']+g_del['1–3 年']:,} 个）**：满足最低门槛的短期标的，
  包含部分历史上短暂流动性足够随后退市的公司——正是消除幸存者偏差的关键贡献者。
""")

# ── Tab2: New entries per year ────────────────────────────────────────────
with tab2:
    st.markdown("最终回测标的池中，每年新进入的标的数量（按 `first_eligible` 年份统计）。")
    entry_year = eu_rec["first_eligible"].dt.year.value_counts().sort_index().reset_index()
    entry_year.columns = ["year", "count"]
    entry_active   = rec_active["first_eligible"].dt.year.value_counts().sort_index()
    entry_delisted = rec_del["first_eligible"].dt.year.value_counts().sort_index()
    entry_year["active"]   = entry_year["year"].map(entry_active).fillna(0).astype(int)
    entry_year["delisted"] = entry_year["year"].map(entry_delisted).fillna(0).astype(int)

    _fig_entry = go.Figure()
    _fig_entry.add_bar(x=entry_year["year"], y=entry_year["active"],
                       name="现役", marker_color="#1565c0")
    _fig_entry.add_bar(x=entry_year["year"], y=entry_year["delisted"],
                       name="已退市", marker_color="#e57373")
    _fig_entry.update_layout(
        barmode="stack",
        title="每年新满足条件进入标的池的标的数",
        xaxis_title="年份",
        yaxis_title="新进入标的数量",
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(_fig_entry, width="stretch")

    top_years = entry_year.nlargest(3, "count")
    _start_yr_count = entry_year[entry_year['year'] == _start_year]
    _start_yr_str = f"{_start_year} 年数量最多（{int(_start_yr_count['count'].values[0])} 个），因为所有在 {_start_year} 年 1 月 1 日之前就已满足条件的标的，`first_eligible` 均落在 {_start_year} 年初（数据起点）。" if len(_start_yr_count) > 0 else ""
    st.markdown(f"""
**峰值年份**：{int(top_years.iloc[0]['year'])} 年（{int(top_years.iloc[0]['count'])} 个新标的），
{int(top_years.iloc[1]['year'])} 年（{int(top_years.iloc[1]['count'])} 个），
{int(top_years.iloc[2]['year'])} 年（{int(top_years.iloc[2]['count'])} 个）。
{_start_yr_str}
""")

# ── Tab3: Exits per year (delisted) ───────────────────────────────────────
with tab3:
    st.markdown("最终回测标的池中已退市标的的退市年份分布（按 `last_eligible` 年份统计）。")
    exit_year = rec_del["last_eligible"].dt.year.value_counts().sort_index().reset_index()
    exit_year.columns = ["year", "count"]

    _fig_exit = go.Figure()
    _fig_exit.add_bar(x=exit_year["year"], y=exit_year["count"],
                      name="退市标的", marker_color="#e57373")
    _fig_exit.update_layout(
        title="每年退出标的池的已退市标的数",
        xaxis_title="年份",
        yaxis_title="退市标的数量",
        height=420,
        showlegend=False,
    )
    st.plotly_chart(_fig_exit, width="stretch")

    peak_exit = exit_year.nlargest(1, "count").iloc[0]
    st.markdown(f"""
**观察**：退市高峰在 {int(peak_exit['year'])} 年（{int(peak_exit['count'])} 个），
与市场环境（并购潮、金融危机后重组、行业洗牌）密切相关。
最终回测标的池中共 {len(rec_del):,} 个已退市标的——
若回测中只使用 S&P 900 现役成分股，这些历史上大幅亏损或破产的标的将被系统性忽略，
导致回测结果产生严重幸存者偏差。
""")

# ── Tab4: Pool size per year ───────────────────────────────────────────────
with tab4:
    st.markdown("最终回测标的池中，每个自然年内有多少标的处于活跃（满足过滤条件）状态。")

    years = list(range(_start_year, _end_year + 1))
    pool_counts = []
    for y in years:
        yr_start = pd.Timestamp(f"{y}-01-01")
        yr_end   = pd.Timestamp(f"{y}-12-31")
        mask = (eu_rec["first_eligible"] <= yr_end) & (eu_rec["last_eligible"] >= yr_start)
        act_mask = mask & eu_rec["is_active"]
        del_mask = mask & ~eu_rec["is_active"]
        pool_counts.append({
            "year":    y,
            "active":  int(act_mask.sum()),
            "delisted": int(del_mask.sum()),
            "total":   int(mask.sum()),
        })
    pool_df = pd.DataFrame(pool_counts)

    _fig_pool = go.Figure()
    _fig_pool.add_bar(x=pool_df["year"], y=pool_df["active"],
                      name="现役标的", marker_color="#1565c0")
    _fig_pool.add_bar(x=pool_df["year"], y=pool_df["delisted"],
                      name="退市标的", marker_color="#e57373")
    _fig_pool.update_layout(
        barmode="stack",
        title=f"各年度最终回测标的池规模（{len(eu_rec):,} 个，满足条件 ≥ 1 年）",
        xaxis_title="年份",
        yaxis_title="标的数量",
        height=440,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(_fig_pool, width="stretch")

    peak_row = pool_df.loc[pool_df["total"].idxmax()]
    st.markdown(f"""
**观察**：
- 最终回测标的池规模随时间增长，从 {_start_year} 年约 **{pool_df[pool_df['year']==_start_year]['total'].values[0]:,} 个**
  增长至峰值年份 {int(peak_row['year'])} 年的 **{int(peak_row['total']):,} 个**。
- 增长主要来自：①美股上市公司总量增加；②整体股价随牛市上行，更多标的满足 \$10 价格门槛；
  ③市场整体流动性提升，更多标的满足 \$60M ADV 门槛。
- 每年的退市标的柱（红色）显示了在该年还在活跃交易、但最终于某时点退市的历史标的数量，
  这是无偏差回测的核心贡献——这些标的若在当年被纳入，就会被纳入；不会因为"后来退市了"而被排除。
""")

st.markdown("---")

# ── 六、标的详细列表（≥ 1 年过滤后）──────────────────────────────────────────
st.subheader("标的详细列表（标的池）")

_display_cols = {
    "ticker":          "Ticker",
    "first_eligible":  "首次满足条件",
    "last_eligible":   "最近满足条件",
    "eligible_days":   "累计满足天数",
    "data_start":      "数据起始日",
    "data_end":        "数据截止日",
}

def _fmt_df(df, sort_col):
    out = (
        df[list(_display_cols.keys())]
        .rename(columns=_display_cols)
        .sort_values(sort_col, ascending=False)
        .reset_index(drop=True)
    )
    out.insert(1, "类型", df["ticker"].map(lambda t: "ETF" if t in _ETF_SET else "股票").values)
    for col in ["首次满足条件", "最近满足条件", "数据起始日", "数据截止日"]:
        out[col] = pd.to_datetime(out[col]).dt.strftime("%Y-%m-%d")
    return out

# 预先构建合并列表
_ticker_status = eu_rec.set_index("ticker")["is_active"].map({True: "现役", False: "已退市"})
_df_all_combined = _fmt_df(eu_rec, "累计满足天数")
_df_all_combined["状态"] = _df_all_combined["Ticker"].map(_ticker_status).values
_all_csv = _df_all_combined.to_csv(index=False).encode("utf-8")

# 下载按钮放在 tabs 上方，永远可见
_dl_col1, _dl_col2, _dl_col3 = st.columns([1.4, 1.7, 4])
with _dl_col1:
    _df_act_dl = _fmt_df(rec_active, "累计满足天数")
    st.download_button("⬇ 下载现役标的列表",
                       data=_df_act_dl.to_csv(index=False).encode("utf-8"),
                       file_name="tiingo_rec_active.csv", mime="text/csv")
with _dl_col2:
    st.download_button("⬇ 下载现役+已退市标的列表",
                       data=_all_csv,
                       file_name="tiingo_recommended_universe.csv", mime="text/csv")

tab_act, tab_del, tab_all = st.tabs([
    f"✅ 现役（{len(rec_active):,} 个）",
    f"📋 已退市（{len(rec_del):,} 个）",
    f"🔍 现役+已退市（{len(eu_rec):,} 个）",
])

with tab_act:
    _df = _fmt_df(rec_active, "累计满足天数")
    show_df(_df, width="stretch", hide_index=True,
                 column_config={"累计满足天数": st.column_config.NumberColumn(format="%d 天")})

with tab_del:
    _df = _fmt_df(rec_del, "最近满足条件")
    show_df(_df, width="stretch", hide_index=True,
                 column_config={"累计满足天数": st.column_config.NumberColumn(format="%d 天")})

with tab_all:
    st.markdown(f"现役 {len(rec_active):,} + 已退市 {len(rec_del):,}，满足 ≥252 交易日条件")
    show_df(_df_all_combined, width="stretch", hide_index=True,
                 column_config={"累计满足天数": st.column_config.NumberColumn(format="%d 天")})

st.markdown("---")

# ── ETF 标的池明细 ─────────────────────────────────────────────────────────────
if _META_PATH.exists():
    # 只显示满足 ≥252 天条件、实际进入回测标的池的 ETF
    _pool_etf_tickers = set(_etf["ticker"] for _, _etf in eu_rec[eu_rec["ticker"].isin(_ETF_SET)].iterrows())
    _etf_df = pd.DataFrame([e for e in _meta.get("etf_universe", []) if e["ticker"] in _pool_etf_tickers])
    _cat_order = [
        "美股指数", "美股风格", "板块 SPDR", "美股行业",
        "国际股票", "美国国债", "债券", "大宗商品", "房地产",
        "波动率", "加密货币",
    ]
    _etf_df["_cat_order"] = _etf_df["category"].apply(
        lambda c: _cat_order.index(c) if c in _cat_order else 99
    )
    _etf_df = _etf_df.sort_values(["_cat_order", "ticker"]).drop(columns="_cat_order")

    st.subheader(f"ETF 标的池明细（{len(_etf_df)} 只）")
    _etf_dl = _etf_df[["ticker", "name", "category"]].rename(
        columns={"ticker": "Ticker", "name": "名称 / Full Name", "category": "类别"}
    )
    st.download_button(
        "⬇ 下载 ETF 标的池列表",
        data=_etf_dl.to_csv(index=False).encode("utf-8"),
        file_name="etf_universe.csv",
        mime="text/csv",
    )
    _etf_tab_labels = [c for c in _cat_order if c in _etf_df["category"].values]
    _etf_tabs = st.tabs(_etf_tab_labels)
    for _etf_tab, _etf_cat in zip(_etf_tabs, _etf_tab_labels):
        with _etf_tab:
            _grp = _etf_df[_etf_df["category"] == _etf_cat][["ticker", "name"]]
            _grp = _grp.rename(columns={"ticker": "Ticker", "name": "名称 / Full Name"})
            show_df(_grp, width="stretch", hide_index=True)

    st.markdown(f"**合计：{len(_etf_df)} 只 ETF**（候选池共 {len(_ETF_SET)} 只；排除原因：7 只结构性不适合 ETF 已排除；JGLO 仅 206 交易日数据不足 252 天；CPER 流动性不足 ADV 最高 \$53M 未达 \$60M 门槛；SPY 为市场环境过滤标的、SHY 为现金代理，均不参与趋势跟踪信号）")
else:
    st.info("ETF 列表未加载。请检查 results/v1_unbiased_60m_2000/strategy_meta.json 中的 etf_universe 字段。")

st.markdown("---")

# ── 标的池充分性分析 ────────────────────────────────────────────────────────────
st.subheader("为什么当前标的池不需要再扩充？")

_adv_analysis_col1, _adv_analysis_col2 = st.columns(2)

with _adv_analysis_col1:
    st.markdown("#### 股票池")

    _eu_all        = eu[~eu["ticker"].isin(_ETF_SET)]
    _eu_under252   = _eu_all[_eu_all["eligible_days"] < MIN_ELIGIBLE_DAYS]
    _eu_over252    = _eu_all[_eu_all["eligible_days"] >= MIN_ELIGIBLE_DAYS]
    _no_data_cnt   = 21_384 - 15_255   # Tiingo 无数据（已知固定值）
    # 被结构性排除的 ETF（不在 ETF_SET 中，因此通过了"非 ETF"过滤，出现在候选池里，但被 EXCL_ALL 从策略池排除）
    _excl_in_cands     = sorted(_eu_over252[_eu_over252["ticker"].isin(_EXCL_ALL)]["ticker"].tolist())
    _n_excl_in_cands   = len(_excl_in_cands)
    _excl_in_cands_str = "、".join(_excl_in_cands)

    st.markdown(f"""
**下载范围：NYSE / NASDAQ / AMEX 全量历史股票**

下载对象不是某个指数成分股，而是美国三大交易所**有史以来所有上市公司**，包含已退市、破产、被收购的标的，从根本上消除幸存者偏差。

| 阶段 | 数量 | 说明 |
|------|-----:|------|
| Tiingo 下载尝试 | 21,384 | 全量历史 Ticker |
| 成功下载（有价格数据）| 15,255 | |
| Tiingo 无数据跳过 | {_no_data_cnt:,} | 极度冷门票、权证、OTC 壳公司 |
| 有数据但从未满足流动性条件 | {15_255 - len(_eu_all):,} | 价格或 ADV 从未同时达标（\$10 / \$20M），未进入候选池 |
| eligible_days < 252（不足 1 年）| {len(_eu_under252):,} | SPAC、超短命公司、刚上市新股 |
| 满足条件标的（≥252 天，含误入的非策略ETF） | {len(_eu_over252):,} | 活跃 {_eu_over252["is_active"].sum():,} + 退市 {(~_eu_over252["is_active"]).sum():,}；注：其中 {_n_excl_in_cands} 只为结构性排除的 ETF（{_excl_in_cands_str}），因其不在策略ETF清单中，被"非ETF过滤"误放入此候选范围 |
| 减去：结构性排除的 ETF | -{_n_excl_in_cands} | {_excl_in_cands_str}——属于 ETF，由 EXCL\_ALL 过滤器从策略池移除 |
| **最终股票策略池（≥252 天）** | **{_universe_stocks:,}** | 回测引擎实际使用的纯股票标的池 |

**为什么不需要再加？**
- 下载源头已覆盖全量美股，没有系统性遗漏
- 6,129 个 Tiingo 无数据的 Ticker 基本是场外（OTC/Pink Sheet）小票或纯权证，流动性极差，不适合趋势跟踪
- 1,463 个不足 252 天的标的生命周期太短，无法形成完整趋势，合理排除
- OTC / 粉单市场标的有意不纳入：流动性差、点差大、数据质量低
""")

with _adv_analysis_col2:
    st.markdown("#### ETF 池")

    _cat_counts = {}
    if _ETF_SET:
        _etf_meta_list = _meta.get("etf_universe", [])
        for _e in _etf_meta_list:
            _cat = _e.get("category", "其他")
            _cat_counts[_cat] = _cat_counts.get(_cat, 0) + 1

    _coverage_rows = [
        ("美股指数",   "✅ 充分", "SPY/QQQ/IWM/DIA/RSP + 中小盘"),
        ("美股板块",   "✅ 充分", "SPDR 11 个板块全覆盖（XLK/XLF/XLE…）"),
        ("美股行业",   "✅ 充分", "半导体/生物科技/国防/建筑/银行/零售…"),
        ("美股风格",   "✅ 充分", "成长/价值/动量/股息/大中小盘"),
        ("国际股票",   "✅ 充分", "发达市场 + 新兴市场 + 主要国家 ETF"),
        ("美国国债",   "✅ 充分", "短中长期国债全期限覆盖"),
        ("信用债",     "✅ 充分", "投资级/高收益/TIPS/市政债"),
        ("大宗商品",   "✅ 充分", "黄金/白银/铜/天然气/综合商品 DBC"),
        ("房地产",     "✅ 充分", "VNQ/SCHH/XLRE 三只互为补充"),
        ("加密货币",   "✅ 够用", "IBIT（比特币现货 ETF）"),
    ]

    st.markdown(f"""
**候选池：{len(_ETF_SET)} 只 ETF（实际参与回测 {_universe_etfs} 只），覆盖所有主要资产类别**

| 类别 | 覆盖评估 | 代表标的 |
|------|---------|---------|
""" + "\n".join(f"| {r} | {s} | {d} |" for r, s, d in _coverage_rows))

    st.markdown("""
**刻意不加的 ETF 及理由：**

| Ticker | 排除原因 |
|--------|---------|
| USO / UCO（原油） | 期货展期成本高（contango 持续侵蚀），历史回测 ≠ 真实收益 |
| CORN / WEAT / SOYB | 农产品期货流动性低，展期损耗严重 |
| PDBC | DBC 已在池中，两者高度重叠，冗余 |
| GDX（黄金矿股） | 已有 GDXJ（小型矿商），两者相关性 > 0.90 |
| TQQQ / UPRO 等杠杆 | 杠杆产品每日复利会造成长期路径损耗，不适合趋势跟踪 |
| 国际债券（BNDX、IAGG、IGOV 等） | ① 与美国债券高度相关（r > 0.7），TLT/AGG 等已有完整覆盖，边际贡献极小；② 低波动率（年化 3–6%）导致 ATR 极小、仓位微薄，即使趋势成立对 NAV 影响可忽略；③ 对冲版本对冲成本约 1.5–2%/年侵蚀收益，非对冲版本汇率噪声掩盖债券本身趋势 |
| 新兴主题 ETF（< 3 年） | 历史数据不足，无法完成有效回测 |
""")

    st.info(
        f"**结论：** 当前 {len(_ETF_SET)} 只 ETF 候选池中，**{_universe_etfs} 只**实际参与趋势跟踪信号"
        f"（7 只结构性排除 + SPY 用于市场环境过滤 + SHY 用于现金代理，共排除 {len(_ETF_SET) - _universe_etfs} 只）。"
        "已达到边际收益递减点。再添加高度相关的 ETF 只会引入数据冗余，不会提升策略的跨资产多样性。"
        "后续如需扩充，优先考虑新增**国别 ETF**（如 EWY-韩国已加入）或"
        "**新兴资产类别**，而非在现有类别中继续叠加。"
    )



