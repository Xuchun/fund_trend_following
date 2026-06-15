"""数据与标的池 (Tiingo) — 无幸存者偏差动态标的池"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

_project = Path(__file__).resolve().parents[2]

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── 数据路径 ──────────────────────────────────────────────────────────────────
_EU_CSV = _project / "data" / "tiingo_eligible_universe.csv"

st.title("数据与标的池 (Tiingo)")
st.caption("基于 Tiingo EOD 数据构建的无幸存者偏差动态标的池")
st.markdown("---")


@st.cache_data(show_spinner=False)
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

# ≥252 天（1年）过滤后的推荐标的池
MIN_ELIGIBLE_DAYS = 252
eu_rec     = eu[eu["eligible_days"] >= MIN_ELIGIBLE_DAYS]
rec_active = eu_rec[eu_rec["is_active"]]
rec_del    = eu_rec[~eu_rec["is_active"]]

# ── 一、过滤方法与理由 ─────────────────────────────────────────────────────────
st.subheader("一、过滤方法与理由")
st.markdown("""
策略 1.0 的原始标的池基于 **2024 年末在指数中的 S&P 900 成分股**，存在严重的**幸存者偏差**——
历史上破产、退市、被踢出指数的公司被完全排除在外，导致回测 CAGR 可能虚高 20%–50%。

为修正这一偏差，我们从 Tiingo 下载了 **NYSE / NASDAQ / AMEX 全量历史股票 + 85 只 ETF** 的日度价格数据
（2004–2026，含已退市标的），并使用以下**纯点对点（Point-in-Time）过滤条件**构建动态标的池：
""")

col_a, col_b = st.columns(2)
with col_a:
    st.markdown("""
**过滤条件 1：原始收盘价 > $10**
- 使用**未复权**收盘价，与每天实际下单价格一致
- 排除低价股（Penny Stocks）：流动性差、点差大、容易被操纵
- 不使用复权价，避免历史分拆造成过滤结果偏差
""")
with col_b:
    st.markdown("""
**过滤条件 2：ADV₆₀ > $2,000 万（$20M）**
- ADV₆₀ = 60 日滚动平均日成交额 = close × volume（60 日均值）
- 使用 shift(1)：今天的 ADV₆₀ 用截至昨天的历史数据，**严格无前视偏差**
- 替代市值过滤（Tiingo 无历史流通股数据）：$20M ADV 对应约 $5–10 亿市值以上
""")

st.markdown("""
两个条件同时满足的标的，在满足条件的**每一天**均进入该日的候选标的池。
引擎在每个交易日根据当日是否满足两个条件，动态决定标的是否在当日参与信号扫描。
这保证了整个回测过程中**不存在任何前视偏差或选择偏差**。
""")

st.markdown("---")

# ── 二、潜在缺陷 ──────────────────────────────────────────────────────────────
st.subheader("二、潜在缺陷与局限性")
st.markdown("""
| # | 缺陷 | 影响方向 | 说明 |
|---|------|---------|------|
| 1 | **无历史市值过滤** | 偏乐观 | Tiingo 无历史流通股数据，ADV > $20M 代替市值 > $5 亿，可能纳入部分实盘难以大量持仓的小票 |
| 2 | **ETF 分类混用** | 轻微 | ETF 和股票同一标准过滤，部分低价 / 低流动性 ETF 可能在上市初期短暂进入标的池 |
| 3 | **Tiingo 数据质量** | 中性 | 部分标的存在复权系数跳变（2,633 个）、价格尖峰（5,305 个），引擎的 `is_tradable` 标记已排除异常行 |
| 4 | **ADV 门槛静态** | 轻微 | $20M 门槛 2004 年偏宽（美股流动性较低），2024 年偏紧；动态门槛可更精确但实现复杂 |
| 5 | **SPAC / 壳公司短暂入池** | 偏悲观 | 部分标的仅满足条件 < 3 个月即退市，不可能产生 200 日突破信号，属无效噪声但对回测结果影响极小 |
""")

st.info(
    "**综合评估**：上述缺陷均为次要影响。相比 S&P 900 的幸存者偏差（系统性高估收益），"
    "本标的池通过纳入 1,206 个已退市标的，大幅降低了回测结果的乐观偏差，"
    "使回测更接近真实历史表现。"
)

st.markdown("---")

# ── 三、推荐回测标的池（满足条件 ≥ 1 年）─────────────────────────────────────
st.subheader("三、推荐回测标的池（满足条件 ≥ 1 年）")

st.info(
    f"**策略 1.0 入场信号基于 200 日价格突破**，因此满足过滤条件不足 1 年（252 天）的标的"
    f"几乎永远不会触发有效信号。过滤掉这 {len(eu) - len(eu_rec):,} 个短命标的后，"
    f"推荐回测使用以下 **{len(eu_rec):,} 个**标的。"
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("推荐标的总数", f"{len(eu_rec):,}",
          delta=f"vs 全量 {len(eu):,}", delta_color="off")
c2.metric("现役", f"{len(rec_active):,}", help="data_end ≥ 2026-01-01")
c3.metric("已退市", f"{len(rec_del):,}", help="幸存者偏差防御的核心")
c4.metric("平均满足天数", f"{eu_rec['eligible_days'].mean():.0f} 天")

st.markdown("<br>", unsafe_allow_html=True)

# Pie for recommended pool
_pie = go.Figure(go.Pie(
    labels=["现役（Active）", "已退市（Delisted）"],
    values=[len(rec_active), len(rec_del)],
    hole=0.52,
    marker_colors=["#1565c0", "#e57373"],
    textinfo="label+percent+value",
    textfont_size=13,
))
_pie.update_layout(
    title=f"推荐标的池（≥1年）构成：{len(rec_active):,} 现役 + {len(rec_del):,} 已退市",
    height=320,
    margin=dict(t=50, b=20, l=20, r=20),
    showlegend=False,
)
st.plotly_chart(_pie, use_container_width=True)

# 3-way comparison table
_cmp_data = {
    "方案":       ["S&P 900（原始）", "Tiingo 全量（ADV > $20M）", "**Tiingo ≥ 1年（推荐）**"],
    "标的总数":   ["903",             f"{len(eu):,}",             f"**{len(eu_rec):,}**"],
    "含退市标的": ["❌ 无",           f"✅ {len(delisted):,} 个", f"**✅ {len(rec_del):,} 个**"],
    "幸存者偏差": ["⚠️ 严重",        "✅ 最小",                  "**✅ 大幅降低**"],
    "无效标的噪声": ["低",            "高（1,460 个无效标的）",   "**低（已过滤）**"],
    "8 GB 内存":  ["✅ 轻松",        "⚠️ 勉强（~6 GB）",         "**✅ 舒适（~3 GB）**"],
}
st.dataframe(pd.DataFrame(_cmp_data), use_container_width=True, hide_index=True)

st.markdown("---")

# ── 四、进阶方案：提高 ADV 门槛可进一步过滤小票 ──────────────────────────────
st.subheader("四、进阶方案：提高 ADV 门槛可进一步过滤小票")

st.markdown("""
当前 ADV₆₀ > $20M 门槛可能纳入部分实盘难以大量持仓的小票
（Tiingo 无历史市值数据，ADV 是唯一代理指标）。
提高门槛是让回测**更保守、更接近实盘**的最简单方法。

下表同时应用了**满足条件 ≥ 1 年（252 天）**的过滤——
注意：ADV 门槛越高，满足条件的天数越少，因此能通过 ≥1年门槛的标的数量会比单纯
看"曾经满足过 $50M"少得多。
""")

_adv_rows = {
    "过滤条件":               ["ADV₆₀ > $20M（当前）",
                               "ADV₆₀ > $50M",
                               "ADV₆₀ > $100M"],
    "曾满足条件（任意一天）": ["4,402", "3,036", "2,060"],
    "满足条件 ≥ 1 年（推荐）": [f"**2,943**", "**1,891**", "**1,237**"],
    "较当前（≥1年）减少":     ["—（基准）",
                               f"▼ {2943-1891:,} 个（-{(2943-1891)/2943*100:.0f}%）",
                               f"▼ {2943-1237:,} 个（-{(2943-1237)/2943*100:.0f}%）"],
    "等效市值下限":            ["约 $5 亿+", "约 $15 亿+", "约 $30 亿+（接近 S&P 500）"],
    "保守程度":                ["⚠️ 宽松（当前）", "✅ 适中", "✅✅ 保守"],
}
st.dataframe(pd.DataFrame(_adv_rows), use_container_width=True, hide_index=True)

st.markdown(f"""
**关键数字：**
- 当前方案（ADV > $20M + ≥1年）→ **{2943:,} 个**（本页推荐，已过滤短命标的）
- 提高到 ADV > $50M + ≥1年 → **1,891 个**（减少 {2943-1891} 个，-{(2943-1891)/2943*100:.0f}%）
- 提高到 ADV > $100M + ≥1年 → **1,237 个**（接近 S&P 500 规模）

> 💡 **建议**：先用当前方案（2,943 个）跑完无偏差基线回测，
> 再用 ADV > $50M（1,891 个）做一次灵敏度对比，
> 看小票暴露对 CAGR / MaxDD 的实际影响。若差异 < 1%，则无需调整。
""")

st.markdown("---")

# ── 五、标的池分布图 ──────────────────────────────────────────────────────────
st.subheader("五、全量标的池分布图（参考：4,402 个）")

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 满足条件时长分布",
    "📅 每年新进入标的",
    "📉 每年退市标的",
    "📈 历年标的池规模",
])

# ── Tab1: Duration distribution ────────────────────────────────────────────
with tab1:
    st.markdown("每个标的累计满足两个过滤条件（close > $10 & ADV₆₀ > $20M）的天数分布。")
    bins   = [0, 63, 126, 252, 756, 1260, 2520, 99999]
    labels = ["<3 个月", "3–6 个月", "6mo–1 年", "1–3 年", "3–5 年", "5–10 年", ">10 年"]
    eu["duration_bin"] = pd.cut(eu["eligible_days"], bins=bins, labels=labels, right=True)

    dur_active   = active.copy()
    dur_delisted = delisted.copy()
    dur_active["duration_bin"]   = pd.cut(dur_active["eligible_days"],   bins=bins, labels=labels, right=True)
    dur_delisted["duration_bin"] = pd.cut(dur_delisted["eligible_days"], bins=bins, labels=labels, right=True)

    g_act = dur_active["duration_bin"].value_counts().reindex(labels, fill_value=0)
    g_del = dur_delisted["duration_bin"].value_counts().reindex(labels, fill_value=0)

    _fig_dur = go.Figure()
    _fig_dur.add_bar(x=labels, y=g_act.values, name="现役", marker_color="#1565c0")
    _fig_dur.add_bar(x=labels, y=g_del.values, name="已退市", marker_color="#e57373")
    _fig_dur.update_layout(
        barmode="stack",
        title="满足过滤条件的累计天数分布",
        xaxis_title="累计满足天数",
        yaxis_title="标的数量",
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(_fig_dur, use_container_width=True)

    st.markdown(f"""
**关键发现：**
- **<3 个月（{g_act['<3 个月']+g_del['<3 个月']} 个）**：绝大多数是 SPAC、短暂上市即退市、或数据异常标的。
  由于策略需要 200 天数据计算突破信号，这些标的**永远不会产生有效入场信号**，对回测无实质影响。
- **>10 年（{g_act['>10 年']+g_del['>10 年']:,} 个）**：长期稳定的大中型股，是趋势跟踪策略的核心猎场。
- **推荐回测使用 ≥ 252 天（约 1 年）的标的**，过滤后保留 {len(eu[eu['eligible_days']>=252]):,} 个，
  既大幅降低噪声，又完整保留有价值的历史。
""")

# ── Tab2: New entries per year ────────────────────────────────────────────
with tab2:
    st.markdown("每年新进入标的池的标的数量（按 `first_eligible` 年份统计）。")
    entry_year = eu["first_eligible"].dt.year.value_counts().sort_index().reset_index()
    entry_year.columns = ["year", "count"]
    entry_active   = active["first_eligible"].dt.year.value_counts().sort_index()
    entry_delisted = delisted["first_eligible"].dt.year.value_counts().sort_index()
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
    st.plotly_chart(_fig_entry, use_container_width=True)

    top_years = entry_year.nlargest(3, "count")
    st.markdown(f"""
**峰值年份**：{int(top_years.iloc[0]['year'])} 年（{int(top_years.iloc[0]['count'])} 个新标的），
{int(top_years.iloc[1]['year'])} 年（{int(top_years.iloc[1]['count'])} 个），
{int(top_years.iloc[2]['year'])} 年（{int(top_years.iloc[2]['count'])} 个）。
2004 年数量最多（{int(entry_year[entry_year['year']==2004]['count'].values[0])} 个），
因为所有在 2004 年 1 月 1 日之前就已满足条件的标的，`first_eligible` 均落在 2004 年初（数据起点）。
""")

# ── Tab3: Exits per year (delisted) ───────────────────────────────────────
with tab3:
    st.markdown("已退市标的的退市年份分布（按 `last_eligible` 年份统计，仅统计已退市标的）。")
    exit_year = delisted["last_eligible"].dt.year.value_counts().sort_index().reset_index()
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
    st.plotly_chart(_fig_exit, use_container_width=True)

    peak_exit = exit_year.nlargest(1, "count").iloc[0]
    st.markdown(f"""
**观察**：退市高峰在 {int(peak_exit['year'])} 年（{int(peak_exit['count'])} 个），
与市场环境（并购潮、金融危机后重组、行业洗牌）密切相关。
这 {len(delisted):,} 个已退市标的正是避免幸存者偏差的关键——
若回测中只使用 S&P 900 现役成分股，这些历史上大幅亏损或破产的标的将被系统性忽略。
""")

# ── Tab4: Pool size per year ───────────────────────────────────────────────
with tab4:
    st.markdown("每个自然年内，有多少个标的至少在该年度内的某一天满足过滤条件。")

    years = list(range(2004, 2027))
    pool_counts = []
    for y in years:
        yr_start = pd.Timestamp(f"{y}-01-01")
        yr_end   = pd.Timestamp(f"{y}-12-31")
        mask = (eu["first_eligible"] <= yr_end) & (eu["last_eligible"] >= yr_start)
        act_mask = mask & eu["is_active"]
        del_mask = mask & ~eu["is_active"]
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
        title="各年度标的池规模（满足 close > $10 & ADV₆₀ > $20M 的标的数）",
        xaxis_title="年份",
        yaxis_title="标的数量",
        height=440,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(_fig_pool, use_container_width=True)

    peak_row = pool_df.loc[pool_df["total"].idxmax()]
    min_row  = pool_df.loc[pool_df["total"].idxmin()]
    st.markdown(f"""
**观察**：
- 标的池规模随时间显著增长，从 2004 年约 **{pool_df[pool_df['year']==2004]['total'].values[0]:,} 个**
  增长至峰值年份 {int(peak_row['year'])} 年的 **{int(peak_row['total']):,} 个**。
- 增长主要来自：①美股上市公司总量增加（IPO、新兴行业 ETF）；②整体股价随牛市上行，
  更多标的满足 $10 价格门槛；③市场整体流动性提升，更多标的满足 $20M ADV 门槛。
- 每年同时存在约 **{delisted['last_eligible'].dt.year.value_counts().mean():.0f} 个**退市标的，
  保证了历史数据的完整性。
""")

st.markdown("---")

# ── 六、各时长档位明细 ────────────────────────────────────────────────────────
st.subheader("六、各时长档位明细（为什么过滤 < 1 年？）")

_n_lt3m   = int((eu["eligible_days"] < 63).sum())
_n_3m_1y  = int(((eu["eligible_days"] >= 63) & (eu["eligible_days"] < 252)).sum())
_n_1y_3y  = int(((eu["eligible_days"] >= 252) & (eu["eligible_days"] < 756)).sum())
_n_3y_5y  = int(((eu["eligible_days"] >= 756) & (eu["eligible_days"] < 1260)).sum())
_n_5y_10y = int(((eu["eligible_days"] >= 1260) & (eu["eligible_days"] < 2520)).sum())
_n_gt10y  = int((eu["eligible_days"] >= 2520).sum())

def _split(mask):
    a = int((eu[mask]["is_active"]).sum())
    d = int((~eu[mask]["is_active"]).sum())
    return a, d

rows_detail = [
    ("< 3 个月",    _n_lt3m,   *_split(eu["eligible_days"] < 63),                                               "❌ 几乎无用"),
    ("3 个月–1 年", _n_3m_1y,  *_split((eu["eligible_days"] >= 63) & (eu["eligible_days"] < 252)),              "⚠️ 价值很低"),
    ("1–3 年",      _n_1y_3y,  *_split((eu["eligible_days"] >= 252) & (eu["eligible_days"] < 756)),             "✅ 有价值"),
    ("3–5 年",      _n_3y_5y,  *_split((eu["eligible_days"] >= 756) & (eu["eligible_days"] < 1260)),            "✅ 有价值"),
    ("5–10 年",     _n_5y_10y, *_split((eu["eligible_days"] >= 1260) & (eu["eligible_days"] < 2520)),           "✅ 核心标的"),
    ("> 10 年",     _n_gt10y,  *_split(eu["eligible_days"] >= 2520),                                            "✅ 核心标的"),
]
st.dataframe(
    pd.DataFrame(rows_detail, columns=["满足条件时长", "标的总数", "现役", "已退市", "策略实用性"]),
    use_container_width=True, hide_index=True,
)
st.markdown(f"""
策略 1.0 入场信号基于 **200 日价格突破**——满足条件不足 252 天的标的，
在整个满足条件期间几乎**无法产生任何有效信号**，属于纯噪声。
< 3 个月的 **{_n_lt3m:,} 个**主要是 SPAC、事件驱动爆量股、数据异常标的；
3 个月–1 年的 **{_n_3m_1y:,} 个**偶尔可产生信号但占比极低。
过滤掉这两档（**共 {_n_lt3m+_n_3m_1y:,} 个**），保留有价值的 **{len(eu_rec):,} 个**。
""")

st.markdown("---")

# ── 七、标的详细列表（≥ 1 年过滤后）──────────────────────────────────────────
st.subheader(f"七、标的详细列表（推荐池：{len(eu_rec):,} 个）")

_display_cols = {
    "ticker":          "Ticker",
    "first_eligible":  "首次满足条件",
    "last_eligible":   "最近满足条件",
    "eligible_days":   "累计满足天数",
    "data_start":      "数据起始日",
    "data_end":        "数据截止日",
}

tab_act, tab_del, tab_all = st.tabs([
    f"✅ 现役（推荐池，{len(rec_active):,} 个）",
    f"📋 已退市（推荐池，{len(rec_del):,} 个）",
    f"🔍 全量参考（{len(eu):,} 个）",
])

def _fmt_df(df, sort_col):
    out = (
        df[list(_display_cols.keys())]
        .rename(columns=_display_cols)
        .sort_values(sort_col, ascending=False)
        .reset_index(drop=True)
    )
    for col in ["首次满足条件", "最近满足条件", "数据起始日", "数据截止日"]:
        out[col] = pd.to_datetime(out[col]).dt.strftime("%Y-%m-%d")
    return out

with tab_act:
    _df = _fmt_df(rec_active, "累计满足天数")
    st.dataframe(_df, use_container_width=True, hide_index=True,
                 column_config={"累计满足天数": st.column_config.NumberColumn(format="%d 天")})
    st.download_button("⬇ 下载现役标的列表（推荐池）",
                       data=_df.to_csv(index=False).encode("utf-8"),
                       file_name="tiingo_rec_active.csv", mime="text/csv")

with tab_del:
    _df = _fmt_df(rec_del, "最近满足条件")
    st.dataframe(_df, use_container_width=True, hide_index=True,
                 column_config={"累计满足天数": st.column_config.NumberColumn(format="%d 天")})
    st.download_button("⬇ 下载已退市标的列表（推荐池）",
                       data=_df.to_csv(index=False).encode("utf-8"),
                       file_name="tiingo_rec_delisted.csv", mime="text/csv")

with tab_all:
    st.caption(f"全量 {len(eu):,} 个（含 {_n_lt3m+_n_3m_1y:,} 个短命标的，供参考）")
    _df = _fmt_df(eu, "累计满足天数")
    st.dataframe(_df, use_container_width=True, hide_index=True,
                 column_config={"累计满足天数": st.column_config.NumberColumn(format="%d 天")})
    st.download_button("⬇ 下载全量标的列表",
                       data=_df.to_csv(index=False).encode("utf-8"),
                       file_name="tiingo_full_universe.csv", mime="text/csv")

st.markdown("---")

# ── 八、数据来源说明 ──────────────────────────────────────────────────────────
st.subheader("八、数据来源说明")
st.markdown("""
**数据来源：** Tiingo End-of-Day API（2026 年 6 月，Power 计划）

| 项目 | 详情 |
|------|------|
| 下载范围 | NYSE / NASDAQ / AMEX 全量美股 + 85 只 ETF，共约 21,381 个 ticker |
| 成功下载 | 15,255 个（含历史退市标的） |
| 下载失败 | 6,126 个（经验证均为 warrant、unit 等无价格数据的空壳代码） |
| 历史深度 | 2004-01-01 → 2026-06-13 |
| 数据格式 | 原始 OHLCV + 复权系数（adj_factor = adjClose / close），每标的一个 parquet 文件 |
| 数据质量 | 运行 `06_check_tiingo_quality.py` 后：2,633 个复权跳变异常、5,305 个价格尖峰、8,328 个零成交量行，均通过 `is_tradable=False` 标记 |
| 幸存者偏差防御 | ✅ 通过下载 Tiingo 官方 `supported_tickers.csv`（含历史上市/退市日期）实现全量覆盖，非基于当前成分股 |

> ⚠️ **注意**：Tiingo Power 计划为按月付费（$30/月）。本数据集于 2026 年 6 月一次性下载完成并压缩备份，
> 订阅已于 2026-07-14 前取消。后续回测直接使用本地 parquet 缓存，无需再次订阅。
""")
