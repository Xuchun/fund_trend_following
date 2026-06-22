"""如何买到错失的大赢家"""
from __future__ import annotations
import json
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from website.style import GLOBAL_CSS

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

_dir = _root / "results" / "v1_unbiased_60m_2000"

# ── 数据加载 ──────────────────────────────────────────────────────────────────
@st.cache_data
def _load():
    sig = pd.read_csv(
        _dir / "all_signals_simulated.csv",
        parse_dates=["signal_date", "entry_date", "exit_date"],
    )
    daily = pd.read_csv(
        _dir / "daily_entry_stats.csv",
        parse_dates=["date"], index_col="date",
    )
    trd = pd.read_csv(
        _dir / "trades.csv",
        parse_dates=["entry_date", "exit_date"],
    )
    with open(_dir / "metrics.json") as f:
        met = json.load(f)
    return sig, daily, trd, met

sig, daily, trd, met = _load()

N_ALL    = len(sig)
N_EXEC   = int(sig["executed"].sum())
N_MISS   = N_ALL - N_EXEC
TOP_N    = 50

# 保留原始 index 以便后续在 sig 中精确排除自身
top50        = sig.nlargest(TOP_N, "pnl_r")
top50_missed = top50[~top50["executed"]].copy()
top50_caught = top50[top50["executed"]].copy()
n_miss50     = len(top50_missed)
n_exec50     = len(top50_caught)

exec_r   = sig.loc[sig["executed"],  "pnl_r"]
missed_r = sig.loc[~sig["executed"], "pnl_r"]

# ── 标题与概览 ────────────────────────────────────────────────────────────────
st.title("🏆 如何买到错失的大赢家")
st.caption("从全量候选信号中找出被错失的高收益交易，深度解析原因，寻找改善年化收益的路径")

c1, c2, c3, c4 = st.columns(4)
c1.metric("候选信号总数", f"{N_ALL:,}")
c2.metric("实际开仓", f"{N_EXEC:,}", f"{N_EXEC/N_ALL:.1%}")
c3.metric("未开仓（模拟）", f"{N_MISS:,}", f"{N_MISS/N_ALL:.1%}")
c4.metric(f"Top {TOP_N} 中错失", f"{n_miss50} 个", f"{n_miss50/TOP_N:.0%}")

st.info(
    "**分析方法**：`all_signals_simulated.csv` 对全部 18,124 个候选信号各自独立模拟「若单独开仓」的结果，"
    "采用与策略 1.0 完全相同的止损（2×ATR）、移动止损和退出规则，**但不受资金或仓位数量约束**。"
    "`pnl_r` 表示该信号若单独开仓时的盈亏倍数（R）。"
    "Baseline 页面所引用的 25,334 个信号来自日度汇总（含少量回测预热期前的极早期信号），"
    "与此处 18,124 个有效模拟信号略有差异。"
)

# ══════════════════════════════════════════════════════════════════════════════
# 一、全量信号收益分布
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("📊 一、全量信号收益分布")
st.markdown(
    "橙色为实际开仓，灰色为未开仓（模拟结果）。注意右侧极端高收益区域——"
    "那里隐藏着最值得研究的「大赢家」。"
)

CLIP_HI = 20
n_exec_tail   = int((exec_r   > CLIP_HI).sum())
n_missed_tail = int((missed_r > CLIP_HI).sum())

fig_hist = go.Figure()
fig_hist.add_trace(go.Histogram(
    x=exec_r.clip(-5, CLIP_HI), nbinsx=100,
    name=f"已开仓 ({N_EXEC:,})",
    marker_color="#e67e22", opacity=0.75,
))
fig_hist.add_trace(go.Histogram(
    x=missed_r.clip(-5, CLIP_HI), nbinsx=100,
    name=f"未开仓 ({N_MISS:,})",
    marker_color="#95a5a6", opacity=0.6,
))
fig_hist.update_layout(
    barmode="overlay",
    title=f"全量信号 pnl_r 分布（截断至 {CLIP_HI}R；超出部分：已开仓 {n_exec_tail} 个，未开仓 {n_missed_tail} 个）",
    xaxis_title="pnl_r（R 倍数）",
    yaxis_title="信号数量",
    height=380,
    legend=dict(x=0.68, y=0.95),
)
fig_hist.add_vline(x=0, line_dash="dash", line_color="#e74c3c", opacity=0.5,
                   annotation_text="盈亏平衡", annotation_position="top right")
st.plotly_chart(fig_hist, use_container_width=True)

sc1, sc2 = st.columns(2)
for col, label, series in [
    (sc1, "已开仓信号", exec_r),
    (sc2, "未开仓信号（模拟）", missed_r),
]:
    with col:
        st.markdown(f"**{label}**")
        d = series.describe().round(3).to_frame("R 值")
        d.index = ["数量", "均值", "标准差", "最小", "25%", "中位数", "75%", "最大"]
        st.dataframe(d, use_container_width=True)

st.markdown(
    f"**关键发现**：未开仓信号均值（**{missed_r.mean():.3f}R**）与已开仓（**{exec_r.mean():.3f}R**）非常接近，"
    f"说明两组信号质量无系统性差异——错失的并非「更差」的信号，而是随机被资金约束淘汰的候选信号。"
    f"但未开仓信号的右尾有 **{n_missed_tail} 个**超过 {CLIP_HI}R，这些就是被完全错失的大赢家。"
)

# ══════════════════════════════════════════════════════════════════════════════
# 二、Top 50 大赢家：实际开仓了多少？
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader(f"🥇 二、Top {TOP_N} 大赢家：实际开仓了多少？")
st.markdown(
    f"按 pnl_r 排序，全量 {N_ALL:,} 个信号中收益最高的 {TOP_N} 个——"
    f"**{n_exec50} 个实际开仓**（已被捕获），**{n_miss50} 个未开仓**（完全错失）。"
)

pie_col, tbl_col = st.columns([1, 2])

with pie_col:
    fig_pie = go.Figure(go.Pie(
        labels=["已捕获", "错失"],
        values=[n_exec50, n_miss50],
        marker_colors=["#e67e22", "#e74c3c"],
        hole=0.42,
        textinfo="label+value+percent",
        textfont_size=13,
    ))
    fig_pie.update_layout(title=f"Top {TOP_N} 大赢家构成", height=300, showlegend=False)
    st.plotly_chart(fig_pie, use_container_width=True)

with tbl_col:
    tbl = top50.copy()
    tbl["状态"] = tbl["executed"].map({True: "✅ 已捕获", False: "❌ 错失"})
    tbl["信号日"] = tbl["signal_date"].dt.strftime("%Y-%m-%d")
    tbl["pnl_r"]  = tbl["pnl_r"].round(1)
    tbl["k 强度"] = tbl["k_strength"].round(2)
    tbl["持仓天数"] = (tbl["exit_date"] - tbl["entry_date"]).dt.days.fillna(0).astype(int)
    st.markdown(f"**Top {TOP_N} 大赢家完整列表**")
    st.dataframe(
        tbl[["ticker", "信号日", "pnl_r", "k 强度", "持仓天数", "exit_reason", "状态"]].rename(
            columns={"ticker": "标的", "exit_reason": "退出原因"}
        ).reset_index(drop=True),
        use_container_width=True,
        height=360,
    )

# 已捕获 vs 错失基本特征对比
st.markdown("#### Top 50 中已捕获 vs 错失信号特征对比")

def _safe_days(df):
    d = (df["exit_date"] - df["entry_date"]).dt.days
    return f"{d.mean():.0f} 天" if len(d) > 0 else "—"

compare = pd.DataFrame({
    "指标": ["平均 pnl_r", "最大 pnl_r", "平均 k 强度", "平均持仓天数", "Gap 过滤比例"],
    "已捕获": [
        f"{top50_caught.pnl_r.mean():.1f}R",
        f"{top50_caught.pnl_r.max():.1f}R",
        f"{top50_caught.k_strength.mean():.2f}",
        _safe_days(top50_caught),
        f"{top50_caught.gap_filtered.mean():.0%}",
    ],
    "错失": [
        f"{top50_missed.pnl_r.mean():.1f}R",
        f"{top50_missed.pnl_r.max():.1f}R",
        f"{top50_missed.k_strength.mean():.2f}",
        _safe_days(top50_missed),
        f"{top50_missed.gap_filtered.mean():.0%}",
    ],
})
st.dataframe(compare, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# 三、多角度分析：为何错失这些大赢家？
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("🔍 三、多角度分析：为何错失这些大赢家？")

# ── 角度一：时间分布 ──────────────────────────────────────────────────────────
st.markdown("#### 角度一：大赢家的年度时间分布")
st.markdown("错失的大赢家是否集中在特定年份或市场环境中？")

top50_copy = top50.copy()
top50_copy["year"]   = top50_copy["signal_date"].dt.year
top50_copy["状态"]   = top50_copy["executed"].map({True: "已捕获", False: "错失"})
yr_grp = top50_copy.groupby(["year", "状态"]).size().unstack(fill_value=0)
for col in ["已捕获", "错失"]:
    if col not in yr_grp.columns:
        yr_grp[col] = 0

fig_time = go.Figure()
fig_time.add_trace(go.Bar(x=yr_grp.index, y=yr_grp["已捕获"],
                          name="已捕获", marker_color="#e67e22"))
fig_time.add_trace(go.Bar(x=yr_grp.index, y=yr_grp["错失"],
                          name="错失",   marker_color="#e74c3c"))
fig_time.update_layout(
    barmode="stack", title=f"Top {TOP_N} 大赢家年度分布",
    xaxis_title="年份", yaxis_title="信号数量", height=340,
    legend=dict(x=0.8, y=0.95),
)
st.plotly_chart(fig_time, use_container_width=True)

# ── 角度二：资金占用（并发仓位）────────────────────────────────────────────────
st.markdown("#### 角度二：错失当天的资金占用情况")
st.markdown(
    "当一个大赢家信号到来时，若已有大量仓位占据资金，策略只能放弃。"
    "下面统计每个错失信号的**入场日**当天，已有多少仓位开仓（资金占用量）。"
)

def _open_pos_on(date):
    if pd.isna(date):
        return 0
    return int(((trd["entry_date"] <= date) & (trd["exit_date"] >= date)).sum())

top50_missed = top50_missed.copy()
top50_missed["并发仓位数"] = top50_missed["entry_date"].apply(_open_pos_on)

def _daily_info(date):
    if date in daily.index:
        r = daily.loc[date]
        return int(r.get("skip_cash", 0)), int(r.get("signals", 0)), int(r.get("executed", 0))
    return 0, 0, 0

_di = top50_missed["signal_date"].apply(
    lambda d: pd.Series(_daily_info(d), index=["skip_cash_day", "n_sig_day", "n_exec_day"])
)
top50_missed = pd.concat([top50_missed.reset_index(drop=True), _di.reset_index(drop=True)], axis=1)

avg_open = top50_missed["并发仓位数"].mean()
max_open = top50_missed["并发仓位数"].max()
pct_cash = (top50_missed["skip_cash_day"] > 0).mean()

ca, cb = st.columns(2)
with ca:
    fig_pos = go.Figure()
    fig_pos.add_trace(go.Histogram(
        x=top50_missed["并发仓位数"], nbinsx=15,
        marker_color="#3498db", name="并发仓位数",
    ))
    fig_pos.add_vline(x=avg_open, line_dash="dash", line_color="red",
                      annotation_text=f"均值 {avg_open:.0f}", annotation_position="top right")
    fig_pos.update_layout(
        title="错失信号入场日的并发仓位数分布",
        xaxis_title="当天已开仓数量",
        yaxis_title="错失信号数",
        height=320,
    )
    st.plotly_chart(fig_pos, use_container_width=True)

with cb:
    fig_scat = go.Figure()
    fig_scat.add_trace(go.Scatter(
        x=top50_missed["并发仓位数"],
        y=top50_missed["pnl_r"].round(1),
        mode="markers+text",
        text=top50_missed["ticker"],
        textposition="top center",
        marker=dict(
            size=11,
            color=top50_missed["pnl_r"],
            colorscale="Reds", showscale=True,
            colorbar=dict(title="pnl_r"),
        ),
        hovertemplate="<b>%{text}</b><br>并发仓位: %{x}<br>pnl_r: %{y}R",
    ))
    fig_scat.update_layout(
        title="错失信号：当天并发仓位 vs 潜在收益",
        xaxis_title="当天已有开仓数量",
        yaxis_title="pnl_r（R）",
        height=320,
    )
    st.plotly_chart(fig_scat, use_container_width=True)

st.markdown(
    f"错失大赢家当天，平均已有 **{avg_open:.0f} 个**仓位开仓，最多达 **{max_open} 个**。"
    f"其中 **{pct_cash:.0%}** 的错失信号当天，日度统计中存在因「资金不足」而跳过的记录。"
    f"这确认了**资金容量**是核心约束，而非信号质量。"
)

# ── 角度三：信号强度（k 值）对比 ──────────────────────────────────────────────
st.markdown("#### 角度三：信号强度（k 值）对比——现有排序是否已有效过滤弱信号？")
st.markdown(
    "策略 1.0 **已在回测引擎中实现**按突破强度降序排列同天候选信号"
    "（`src/strategy/v1/entry.py` 第 154 行：`signals.sort(key=lambda s: s[\"breakout_strength\"], reverse=True)`），"
    "并非随机顺序。这里验证：现有排序是否已将较弱信号淘汰在外？"
    "若错失信号的 k 值**低于**当天已执行信号均值，说明排序机制已有效发挥作用，"
    "资金容量才是根本瓶颈；若 k 值**高于**执行均值，则说明排序仍有改善空间。"
)
st.info(
    "**两种突破强度指标对比**\n\n"
    "| 指标 | 公式 | 含义 | 当前状态 |\n"
    "|------|------|------|----------|\n"
    "| `breakout_strength`（已实现）| close / 200日最高价 | 比率，如 1.05 = 超出 5% | ✅ 引擎已用于降序排列 |\n"
    "| `k_strength`（本页分析用）| (close − 200日最高价) / ATR₂₀ | ATR 标准化，如 2.5 = 超出 2.5 个 ATR | 📊 仅用于数据分析 |\n\n"
    "两者衡量同一件事（突破幅度），高度相关，排序结果相近。"
    "ATR 标准化的优点：跨标的可比性更好——高波动股 5% 突破的「含金量」低于低波动股 5% 突破。"
)

def _k_gap(orig_idx, row):
    date = row["signal_date"]
    same_day = sig[sig["signal_date"] == date]
    exec_ks = same_day.loc[same_day["executed"] & (same_day.index != orig_idx), "k_strength"]
    k_rank  = int((same_day["k_strength"] >= row["k_strength"]).sum())
    n_total = len(same_day)
    if len(exec_ks) > 0:
        mean_exec_k = exec_ks.mean()
        gap = row["k_strength"] - mean_exec_k
    else:
        mean_exec_k, gap = np.nan, np.nan
    return pd.Series({
        "k_rank_day":  k_rank,
        "n_total_day": n_total,
        "n_exec_day2": len(exec_ks),
        "mean_exec_k": round(mean_exec_k, 2) if not np.isnan(mean_exec_k) else None,
        "k_gap":       round(gap, 2) if not np.isnan(gap) else None,
    })

k_info = pd.DataFrame(
    [_k_gap(idx, row) for idx, row in top50_missed.iterrows()]
)
top50_missed = pd.concat([top50_missed.reset_index(drop=True), k_info.reset_index(drop=True)], axis=1)

valid_gap = top50_missed["k_gap"].dropna()
n_pos_gap = int((valid_gap > 0).sum())
n_neg_gap = int((valid_gap < 0).sum())

kc1, kc2 = st.columns(2)
with kc1:
    fig_box = go.Figure()
    fig_box.add_trace(go.Box(
        y=top50_caught["k_strength"], name="已捕获",
        marker_color="#e67e22", boxmean=True,
    ))
    fig_box.add_trace(go.Box(
        y=top50_missed["k_strength"], name="错失",
        marker_color="#e74c3c", boxmean=True,
    ))
    fig_box.update_layout(
        title=f"Top {TOP_N} 中 k 强度分布对比",
        yaxis_title="k 强度",
        height=340,
    )
    st.plotly_chart(fig_box, use_container_width=True)

with kc2:
    fig_gap = go.Figure()
    fig_gap.add_trace(go.Histogram(
        x=valid_gap, nbinsx=12,
        marker_color="#3498db", name="k_gap",
    ))
    fig_gap.add_vline(x=0, line_dash="dash", line_color="#e74c3c",
                      annotation_text="k_gap=0", annotation_position="top left")
    fig_gap.update_layout(
        title="错失信号的 k 差（自身 k − 当天执行均值 k）",
        xaxis_title="k_gap（正值=错失信号比执行信号更强）",
        yaxis_title="信号数",
        height=340,
    )
    st.plotly_chart(fig_gap, use_container_width=True)

if n_pos_gap <= n_neg_gap:
    st.success(
        f"**排序机制验证通过**：在 {n_miss50} 个错失的 Top {TOP_N} 信号中，"
        f"**{n_neg_gap} 个（{n_neg_gap/max(n_miss50,1):.0%}）的 k 值低于当天已执行信号均值**——"
        f"现有 `breakout_strength` 排序已将较弱信号排在后面，起到了过滤作用。"
        f"仅 **{n_pos_gap} 个（{n_pos_gap/max(n_miss50,1):.0%}）**的 k 值高于执行均值（即排序若切换为 k_strength 可能改善的部分）。"
        f"**结论：资金容量是错失大赢家的主因，排序问题极小。**"
    )
else:
    st.warning(
        f"**排序仍有改善空间**：在 {n_miss50} 个错失的 Top {TOP_N} 信号中，"
        f"**{n_pos_gap} 个（{n_pos_gap/max(n_miss50,1):.0%}）的 k 值高于当天已执行信号均值**——"
        f"说明现有 `breakout_strength` 排序未能完全识别最强信号，"
        f"切换至 ATR 标准化的 k_strength 可能带来改善。"
        f"（{n_neg_gap} 个 k 值弱于执行均值，占 {n_neg_gap/max(n_miss50,1):.0%}。）"
    )

# ── 角度四：竞争信号——当天执行的是什么？ ────────────────────────────────────
st.markdown("#### 角度四：当天被执行的「竞争信号」事后表现如何？")
st.markdown(
    "对于每个错失的大赢家，找出同一信号日被实际执行的其他信号，"
    "对比其事后收益，量化机会成本。"
)

comp_rows = []
for orig_idx, row in top50_missed.iterrows():
    date = row["signal_date"]
    comps = sig.loc[
        (sig["signal_date"] == date) & sig["executed"] & (sig.index != orig_idx),
        ["ticker", "pnl_r", "k_strength"],
    ]
    if len(comps) == 0:
        continue
    comp_rows.append({
        "missed_ticker":   row["ticker"],
        "missed_pnl_r":    row["pnl_r"],
        "n_competitors":   len(comps),
        "comp_mean_pnl_r": comps["pnl_r"].mean(),
        "comp_max_pnl_r":  comps["pnl_r"].max(),
        "comp_mean_k":     comps["k_strength"].mean(),
    })

if comp_rows:
    comp_df = pd.DataFrame(comp_rows)
    comp_df["机会成本 (R)"] = comp_df["missed_pnl_r"] - comp_df["comp_mean_pnl_r"]

    fig_comp = go.Figure()
    x_labels = comp_df["missed_ticker"].tolist()
    fig_comp.add_trace(go.Bar(
        x=x_labels, y=comp_df["missed_pnl_r"].round(1),
        name="错失大赢家 pnl_r", marker_color="#e74c3c",
    ))
    fig_comp.add_trace(go.Bar(
        x=x_labels, y=comp_df["comp_mean_pnl_r"].round(2),
        name="当天执行信号平均 pnl_r", marker_color="#95a5a6",
    ))
    fig_comp.update_layout(
        barmode="group",
        title="错失大赢家 vs 当天实际执行信号的平均收益（R）",
        xaxis_title="错失大赢家标的",
        yaxis_title="pnl_r (R)",
        height=420,
        xaxis_tickangle=-45,
        legend=dict(x=0.6, y=0.98),
    )
    st.plotly_chart(fig_comp, use_container_width=True)

    total_occ = comp_df["机会成本 (R)"].sum()
    avg_occ   = comp_df["机会成本 (R)"].mean()
    st.markdown(
        f"每个错失大赢家与当天执行信号均值的收益差（机会成本）：平均 **{avg_occ:.1f}R/次**，"
        f"合计 **{total_occ:.0f}R** 的额外潜在收益被遗漏。"
    )

# ── 角度五：k 值与 pnl_r 的相关性 ────────────────────────────────────────────
st.markdown("#### 角度五：k 强度与收益的相关性——高 k 值是否预示着大赢家？")
st.markdown(
    "如果 k 值与 pnl_r 存在正相关，则优先执行高 k 值信号具有统计依据。"
)

top_vis = sig.nlargest(800, "pnl_r").copy()
top_vis["颜色"] = top_vis["executed"].map({True: "#e67e22", False: "#95a5a6"})

fig_kr = go.Figure()
for executed, label, color in [(True, "已开仓", "#e67e22"), (False, "未开仓", "#adb5bd")]:
    sub = top_vis[top_vis["executed"] == executed]
    fig_kr.add_trace(go.Scatter(
        x=sub["k_strength"].clip(0, 25),
        y=sub["pnl_r"].clip(0, 100),
        mode="markers",
        name=label,
        marker=dict(color=color, size=6, opacity=0.6),
        text=sub["ticker"],
        hovertemplate="<b>%{text}</b><br>k 强度: %{x:.2f}<br>pnl_r: %{y:.1f}R",
    ))

# 趋势线
valid = top_vis.dropna(subset=["k_strength", "pnl_r"])
xv = valid["k_strength"].clip(0, 25).values
yv = valid["pnl_r"].clip(0, 100).values
if len(xv) > 2:
    m, b = np.polyfit(xv, yv, 1)
    xl = np.linspace(0, 25, 200)
    fig_kr.add_trace(go.Scatter(
        x=xl, y=m * xl + b,
        mode="lines", name="趋势线",
        line=dict(color="#2c3e50", dash="dash", width=2),
    ))

fig_kr.update_layout(
    title="Top 800 信号：k 强度 vs pnl_r（截断至 25R / 100R）",
    xaxis_title="k 强度（截断至 25）",
    yaxis_title="pnl_r（R，截断至 100）",
    height=400,
    legend=dict(x=0.7, y=0.98),
)
st.plotly_chart(fig_kr, use_container_width=True)

corr_all = sig["k_strength"].corr(sig["pnl_r"])
corr_top = top50["k_strength"].corr(top50["pnl_r"])

# 不同 k 档位的平均 pnl_r
sig_copy = sig.copy()
sig_copy["k_bucket"] = pd.cut(
    sig_copy["k_strength"].clip(0, 20),
    bins=[0, 1, 2, 3, 5, 10, 20],
    labels=["0–1", "1–2", "2–3", "3–5", "5–10", "10–20"],
)
k_perf = sig_copy.groupby("k_bucket", observed=True)["pnl_r"].agg(
    均值="mean", 中位数="median", 数量="count", 胜率=lambda x: (x > 0).mean()
).round(3)

st.markdown(f"k_strength 与 pnl_r 的 Pearson 相关系数：全量 **{corr_all:.3f}**，Top {TOP_N} 中 **{corr_top:.3f}**")
st.markdown("**不同 k 档位的平均收益（全量信号）**")
st.dataframe(k_perf, use_container_width=True)

st.markdown(
    "高 k 值信号在均值和胜率上均优于低 k 值信号，与现有 `breakout_strength` 降序排列的方向一致。"
    "此处数据支持考虑将排序键从百分比比率（`breakout_strength`）切换为 ATR 标准化（`k_strength`），"
    "在跨标的可比性上更优，但预期效果为边际改善，并非颠覆性变化（见建议一）。"
)

# ══════════════════════════════════════════════════════════════════════════════
# 四、改善建议
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("💡 四、改善建议：如何捕获更多大赢家？")
st.markdown(
    "**根本矛盾**：策略每笔仓位最大占用 5% NAV，导致满仓约 20 个仓位时资金耗尽，"
    "新信号再强也无法入场。解决路径有三条，难度与效果各不相同。"
)

st.markdown("---")
# ── 建议一 ───────────────────────────────────────────────────────────────────
st.markdown("#### ⚙️ 建议一：将信号排序键从 breakout_strength 改为 ATR 标准化的 k_strength（改动极小）")
st.markdown(
    f"""
**已实现的基础**：策略 1.0 回测引擎（`src/strategy/v1/entry.py` 第 154 行）已按
`breakout_strength = close / 200日最高价` 降序排列同天候选信号——这是正确方向。

**数据验证**：角度三显示，{n_miss50} 个错失 Top {TOP_N} 信号中，
**{n_neg_gap} 个（{n_neg_gap/max(n_miss50,1):.0%}）的 k 值低于当天已执行信号均值**，
说明现有 `breakout_strength` 排序已在起作用，绝大多数错失信号的突破强度本就弱于被执行的信号。
**排序问题是次要因素，资金容量不足才是根本原因。**

**潜在改进**：`breakout_strength`（比率）与 `k_strength`（ATR 标准化）高度相关，
但 k_strength 在跨标的比较中更公平——高波动股 5% 突破的「含金量」低于低波动股 5% 突破。
将排序键改为 `k_strength`，代码改动仅一行，不改变任何参数和风险结构，
可在边际上优化混合高低波动标的时的选择质量。

**实施方式**：在 `entry.py` 第 154 行将
`signals.sort(key=lambda s: s["breakout_strength"], reverse=True)`
改为 `signals.sort(key=lambda s: s["k_strength"], reverse=True)`，
并确认 `k_strength` 字段已在 `_compute()` 中输出。
"""
)

# ── 建议一：实证回测结果 ──────────────────────────────────────────────────────
st.markdown("##### 🧪 实证回测验证：切换排序键的实际效果")
st.markdown(
    "理论分析之外，我们实际运行了一次完整回测（2000–2026，monkey-patch 方式，"
    "不修改任何源文件），将排序键从 `breakout_strength` 改为 `k_strength`，"
    "其余所有参数保持与 Baseline 完全相同，结果如下："
)

_bt_data = {
    "指标": ["CAGR", "Sharpe", "最大回撤", "Calmar", "胜率", "盈亏比", "交易笔数"],
    "breakout_strength（当前）": ["10.58%", "0.644", "−19.29%", "0.548", "39.07%", "1.739", "3,335"],
    "k_strength（实验）":        [ "9.39%", "0.591", "−16.26%", "0.577", "38.45%", "1.575", "3,363"],
    "变化":                      ["−1.19 pp ❌", "−0.053 ❌", "+3.03 pp ✅", "+0.029 ✅", "−0.62 pp", "−0.164 ❌", "+28"],
}
st.dataframe(
    pd.DataFrame(_bt_data),
    use_container_width=True, hide_index=True,
)

_c_bt1, _c_bt2 = st.columns(2)
with _c_bt1:
    _fig_bt = go.Figure()
    _metrics_bt = ["CAGR (%)", "Sharpe×10", "Profit Factor"]
    _bs_vals     = [10.58, 0.644 * 10, 1.739]
    _ks_vals     = [ 9.39, 0.591 * 10, 1.575]
    _fig_bt.add_trace(go.Bar(
        name="breakout_strength（当前）",
        x=_metrics_bt, y=_bs_vals,
        marker_color="#e67e22",
        text=[f"{v:.2f}" for v in _bs_vals], textposition="outside",
    ))
    _fig_bt.add_trace(go.Bar(
        name="k_strength（实验）",
        x=_metrics_bt, y=_ks_vals,
        marker_color="#3498db",
        text=[f"{v:.2f}" for v in _ks_vals], textposition="outside",
    ))
    _fig_bt.update_layout(
        barmode="group",
        title="CAGR / Sharpe / 盈亏比 对比",
        height=320, margin=dict(t=50, b=40),
        legend=dict(x=0.3, y=1.1, orientation="h"),
    )
    st.plotly_chart(_fig_bt, use_container_width=True)

with _c_bt2:
    _fig_bt2 = go.Figure()
    _fig_bt2.add_trace(go.Bar(
        name="breakout_strength（当前）",
        x=["最大回撤（绝对值 %）"],
        y=[19.29],
        marker_color="#e67e22",
        text=["19.29%"], textposition="outside",
    ))
    _fig_bt2.add_trace(go.Bar(
        name="k_strength（实验）",
        x=["最大回撤（绝对值 %）"],
        y=[16.26],
        marker_color="#3498db",
        text=["16.26%"], textposition="outside",
    ))
    _fig_bt2.update_layout(
        barmode="group",
        title="最大回撤对比（越低越好）",
        yaxis=dict(range=[0, 25]),
        height=320, margin=dict(t=50, b=40),
        legend=dict(x=0.1, y=1.1, orientation="h"),
    )
    st.plotly_chart(_fig_bt2, use_container_width=True)

st.warning(
    "**实证结论：不推荐切换到 k_strength 排序。**\n\n"
    "切换后 **CAGR 下降 1.19pp、Sharpe 下降 0.053、盈亏比下降 0.164**，"
    "虽然最大回撤改善了 3.03pp，但代价过高。\n\n"
    "**原因分析**：ATR 标准化会压低高波动股的 k 值排名。"
    "趋势跟踪的超额收益主要来自高波动爆发型股票（小盘成长股、突破型个股），"
    "这类股票在 breakout_strength 排序下靠前，在 k_strength 排序下被相对压低，"
    "结果是更多低波动稳健型标的被优先执行——MaxDD 因此改善，"
    "但少了那些爆发型大赢家，CAGR 和盈亏比显著下降。\n\n"
    "**维持现有 `breakout_strength` 排序**，无需任何修改。"
)

# ── 建议二 ───────────────────────────────────────────────────────────────────
st.markdown("#### ✅ 建议二：降低单笔仓位上限，扩大并发容量（中等改动，需回测验证）")

avg_hold    = float(met.get("avg_holding_days", 42))
daily_exec  = float(daily["executed"].mean())
rough_conc  = avg_hold * daily_exec
cagr_now    = float(met.get("cagr", 0)) * 100 if met.get("cagr", 0) < 1 else float(met.get("cagr", 0))
max_dd_now  = abs(float(met.get("max_drawdown", 0))) * 100 if abs(float(met.get("max_drawdown", 0))) < 1 else abs(float(met.get("max_drawdown", 0)))

# 当前和降仓后并发仓位数估算
current_cap_pct  = 5.0   # %
proposed_cap_pct = 3.0   # %
scale = current_cap_pct / proposed_cap_pct
rough_new_conc   = rough_conc * scale

fig_cap = go.Figure()
fig_cap.add_trace(go.Bar(
    x=["当前（5% 上限）", "建议（3% 上限）"],
    y=[rough_conc, rough_new_conc],
    marker_color=["#e67e22", "#27ae60"],
    text=[f"~{rough_conc:.0f} 个", f"~{rough_new_conc:.0f} 个"],
    textposition="outside",
    width=0.4,
))
fig_cap.update_layout(
    title="单笔仓位上限调整对并发持仓数量的影响（估算）",
    yaxis_title="平均并发仓位数（估算）",
    height=320,
    yaxis=dict(range=[0, rough_new_conc * 1.3]),
)
st.plotly_chart(fig_cap, use_container_width=True)

# 若 position_cap 从 5% → 3%，估算可多捕获多少 missed top50
frac_additional = 1 - (current_cap_pct / proposed_cap_pct) ** -1  # ≈0.4
est_more_catch  = int(n_miss50 * frac_additional)

st.markdown(
    f"""
**数据支撑**：
- 策略平均持仓天数 **{avg_hold:.0f} 天**，平均每天新开仓 **{daily_exec:.2f} 个**
- 推算当前平均并发仓位 ≈ **{rough_conc:.0f} 个**

将单笔仓位上限从 **5% NAV** 降至 **3% NAV**，
并发容量提升约 **{(scale - 1):.0%}**（~{rough_conc:.0f} → ~{rough_new_conc:.0f} 个），
理论上可多捕获错失 Top {TOP_N} 信号的约 **{est_more_catch} 个**。

**代价**：每笔仓位盈亏金额同比缩小（R 倍数不变，但每 R 的美元价值降低），
净年化收益需回测验证。

**最大回撤影响**：持仓更分散，单笔大幅亏损对组合的冲击更小，
理论上最大回撤应**持平或降低**，而非上升。
"""
)

# ── 建议三 ───────────────────────────────────────────────────────────────────
st.markdown("#### ✅ 建议三：高 k 强度信号给予更高初始仓位权重（需谨慎验证）")

# Show k_strength → avg pnl_r curve for executed signals only
exec_sig = sig[sig["executed"]].copy()
exec_sig["k_bucket"] = pd.cut(
    exec_sig["k_strength"].clip(0, 15),
    bins=[0, 1, 2, 3, 5, 15],
    labels=["0–1", "1–2", "2–3", "3–5", "5+"],
)
k_exec_perf = exec_sig.groupby("k_bucket", observed=True)["pnl_r_multiple" if "pnl_r_multiple" in exec_sig.columns else "pnl_r"].agg(
    均值="mean", 数量="count"
).round(3)

col_k3a, col_k3b = st.columns([1, 2])
with col_k3a:
    st.markdown("**已开仓信号：k 档位 vs 平均 pnl_r**")
    st.dataframe(k_exec_perf, use_container_width=True)
with col_k3b:
    if len(k_exec_perf) > 0:
        fig_k3 = go.Figure()
        fig_k3.add_trace(go.Bar(
            x=k_exec_perf.index.astype(str),
            y=k_exec_perf["均值"],
            marker_color="#e67e22",
            text=k_exec_perf["均值"].round(2),
            textposition="outside",
        ))
        fig_k3.update_layout(
            title="k 强度档位与平均实际收益（已执行信号）",
            xaxis_title="k 强度区间",
            yaxis_title="平均 pnl_r (R)",
            height=280,
        )
        st.plotly_chart(fig_k3, use_container_width=True)

st.markdown(
    """
**建议**：对 k 值极高（如 k > 5）的信号，在建议二（扩大并发容量）的基础上，
可适度增大初始仓位（如仓位上限提升至 1.5×）。这样高质量突破在盈利时贡献更大，
同时通过止损保护下行风险。

**注意**：加仓逻辑会引入"择时"成分，需严格 Walk-Forward 验证，防止过拟合。
建议仅在建议一、二经回测确认有效后再引入此项。
"""
)

# ══════════════════════════════════════════════════════════════════════════════
# 五、量化影响估算
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("📈 五、量化影响估算")

avg_missed_r  = float(top50_missed["pnl_r"].mean()) if n_miss50 > 0 else 0
total_years   = 26.5
risk_per_trade = 0.01  # 1% NAV 目标风险
extra_r_yr    = (n_miss50 / total_years) * avg_missed_r
cagr_lift_pct = risk_per_trade * extra_r_yr * 100

st.markdown(
    f"""
**假设：成功捕获全部 {n_miss50} 个错失 Top {TOP_N} 信号（理想上限估算）**

| 指标 | 数值 |
|------|------|
| 错失 Top {TOP_N} 的平均 pnl_r | **{avg_missed_r:.1f}R** |
| 回测期每年约错失此类信号 | **{n_miss50/total_years:.1f} 个** |
| 每年额外盈亏贡献（1% NAV 风险/笔） | **≈ +{cagr_lift_pct:.2f}% 年化** |
| 现有 CAGR | **{cagr_now:.2f}%** |
| 理论改善后 CAGR 上限 | **约 {cagr_now + cagr_lift_pct:.1f}%** |

> ⚠️ 此为理想上限：实际中无法 100% 捕获所有错失大赢家；
> 改变仓位结构也会影响其余交易。
> **正确做法是修改 `position_cap` 参数后跑完整回测和 Walk-Forward 验证。**
"""
)

# ══════════════════════════════════════════════════════════════════════════════
# 六、建议优先级总结
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("✅ 六、建议优先级总结")

summary = pd.DataFrame({
    "优先级": ["⭐⭐⭐ 最高", "⭐⭐ 高", "⭐ 中"],
    "建议": [
        "将 position_cap 从 5% 降至 3%（扩大并发容量）",
        "排序键从 breakout_strength 改为 k_strength（ATR 标准化）",
        "对高 k 值信号给予更高初始仓位权重",
    ],
    "实施难度": ["中（需完整回测验证）", "低（改一行排序逻辑）", "高（需新逻辑 + 严格验证）"],
    "预期效果": ["并发容量 +65%，捕获更多信号", "边际改善跨标的排序公平性", "精准提升高质量突破暴露"],
    "最大回撤影响": ["应持平或降低", "中性", "需谨慎控制"],
    "当前状态": ["⏳ 待回测验证", "🔧 排序已实现，仅需改键名", "🔬 需严格 Walk-Forward 后引入"],
})
st.dataframe(summary, use_container_width=True, hide_index=True)

st.success(
    "**推荐行动**：最高优先级是将 `position_cap` 从 0.05 改为 0.03，"
    "跑完整回测 + Walk-Forward，观察年化收益、最大回撤、交易次数的变化。"
    "同时可将排序键从 `breakout_strength` 改为 `k_strength`（一行代码，低风险）。"
    "两者经验证有效后，再考虑引入高 k 加仓逻辑。"
)
