"""如何过滤极低波动率的开仓信号"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pandas as pd
import numpy as np
import streamlit as st

# ── 加载回测交易数据 ──────────────────────────────────────────────────────────
_TRADES_PATH = _root / "results" / "v1_new_rounding_test" / "trades.csv"

@st.cache_data
def _load_trades() -> pd.DataFrame:
    df = pd.read_csv(_TRADES_PATH)
    df["stop_dist_pct"] = (df["entry_price"] - df["stop_loss"]) / df["entry_price"] * 100
    df["atr_pct"] = df["atr_at_entry"] / df["entry_price"] * 100
    df["win"] = df["pnl_r_multiple"] > 0
    return df

def _group_stats(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0:
        return {"n": 0, "wr": 0, "avg_r": 0, "pf": 0}
    wr = sub["win"].mean()
    avg_r = sub["pnl_r_multiple"].mean()
    gross_win = sub.loc[sub["win"], "pnl_r_multiple"].sum()
    gross_loss = -sub.loc[~sub["win"], "pnl_r_multiple"].sum()
    pf = gross_win / gross_loss if gross_loss > 0 else float("nan")
    return {"n": n, "wr": wr, "avg_r": avg_r, "pf": pf}


# ════════════════════════════════════════════════════════════════════════════════
st.title("如何过滤极低波动率的开仓信号")
st.markdown(
    "分析历史回测中所有 3,341 笔交易的止损距离（波动率代理指标）"
    "与胜率、平均 R、盈亏比的关系，并讨论改参数是否构成过度拟合。"
)
st.markdown("---")

if not _TRADES_PATH.exists():
    st.error(f"找不到交易数据文件：{_TRADES_PATH}")
    st.stop()

df = _load_trades()

# ════════════════════════════════════════════════════════════════════════════════
st.subheader("一、背景：为何关注极低波动率信号？")
st.markdown("""
策略使用 **2×ATR** 作为止损距离，ATR（平均真实波幅）是衡量标的近期波动率的核心指标。
当某标的波动率极低时，ATR 很小，止损距离也很小，例如：

- GTLS（2026年某日）：ATR ≈ $0.555，止损距离 ≈ $1.11（占价格 0.53%）
- 按 1% NAV 风险规则计算，应买 1,649 股
- 但 5% 仓位上限将持股压到 44 股，实际风险仅 **0.027% NAV**

这类信号引发了一个问题：**止损距离极小的标的，趋势信号的质量是否也更差？**
""")

st.markdown("---")

# ════════════════════════════════════════════════════════════════════════════════
st.subheader("二、止损距离的整体分布")

col1, col2, col3, col4 = st.columns(4)
col1.metric("最小止损距离", f"{df['stop_dist_pct'].min():.3f}%")
col2.metric("中位数", f"{df['stop_dist_pct'].median():.2f}%")
col3.metric("平均值", f"{df['stop_dist_pct'].mean():.2f}%")
col4.metric("最大止损距离", f"{df['stop_dist_pct'].max():.2f}%")

st.markdown(f"""
现有参数 `min_stop_distance_pct = 0.5%` 已过滤掉止损距离低于 0.5% 的信号。
3,341 笔交易中，止损距离范围为 **{df['stop_dist_pct'].min():.3f}% ～ {df['stop_dist_pct'].max():.2f}%**，
中位数约 **{df['stop_dist_pct'].median():.2f}%**。

目前 `min_stop_distance_pct = 0.5%`，即止损距离 < 0.5% 的信号会被丢弃，但 0.5%～1% 之间的信号仍会被执行。
""")

st.markdown("---")

# ════════════════════════════════════════════════════════════════════════════════
st.subheader("三、止损距离 < 1% 的信号：绩效是否系统性偏低？")

all_stats = _group_stats(df)
low_mask = df["stop_dist_pct"] < 1.0
high_mask = ~low_mask
low_stats = _group_stats(df[low_mask])
high_stats = _group_stats(df[high_mask])

c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("**整体（3,341笔）**")
    st.metric("胜率", f"{all_stats['wr']*100:.1f}%")
    st.metric("平均 R", f"{all_stats['avg_r']:.4f}")
    st.metric("盈亏比", f"{all_stats['pf']:.4f}")

with c2:
    st.markdown(f"**止损距离 < 1%（{low_stats['n']}笔，{low_stats['n']/len(df)*100:.1f}%）**")
    wr_delta = (low_stats['wr'] - all_stats['wr']) * 100
    r_delta = low_stats['avg_r'] - all_stats['avg_r']
    pf_delta = low_stats['pf'] - all_stats['pf']
    st.metric("胜率", f"{low_stats['wr']*100:.1f}%", f"{wr_delta:+.1f}pp vs 整体")
    st.metric("平均 R", f"{low_stats['avg_r']:.4f}", f"{r_delta:+.4f} vs 整体")
    st.metric("盈亏比", f"{low_stats['pf']:.4f}", f"{pf_delta:+.4f} vs 整体")

with c3:
    st.markdown(f"**止损距离 ≥ 1%（{high_stats['n']}笔，{high_stats['n']/len(df)*100:.1f}%）**")
    st.metric("胜率", f"{high_stats['wr']*100:.1f}%")
    st.metric("平均 R", f"{high_stats['avg_r']:.4f}")
    st.metric("盈亏比", f"{high_stats['pf']:.4f}")

# 找出<1%的标的
low_df = df[low_mask].copy()
top_tickers = low_df["ticker"].value_counts().head(10)

st.markdown(f"""
**关键发现：止损距离 < 1% 的 {low_stats['n']} 笔交易，绩效显著优于整体！**

- 胜率 **{low_stats['wr']*100:.1f}%** vs 整体 {all_stats['wr']*100:.1f}%（高 {low_stats['wr']*100 - all_stats['wr']*100:.1f}pp）
- 平均 R **{low_stats['avg_r']:.4f}** vs 整体 {all_stats['avg_r']:.4f}（高 {low_stats['avg_r'] - all_stats['avg_r']:.4f}）
- 盈亏比 **{low_stats['pf']:.4f}** vs 整体 {all_stats['pf']:.4f}（高 {low_stats['pf'] - all_stats['pf']:.4f}）

**原因：** 这 {low_stats['n']} 笔交易主要来自债券 ETF（IEF、BND、AGG、TIP、LQD 等）。
债券 ETF 波动率天然极低，但其价格趋势往往平稳且持续时间长，正好适合趋势跟踪策略。
如果以"止损距离 < 1%"为由过滤这些信号，反而会剔除掉质量更好的交易。
""")

# 展示<1%的详细数据
with st.expander(f"查看全部 {low_stats['n']} 笔止损距离 < 1% 的交易"):
    show_df = low_df[["ticker", "entry_date", "stop_dist_pct", "atr_pct", "pnl_r_multiple", "win"]].copy()
    show_df.columns = ["标的", "入场日期", "止损距离%", "ATR%", "R倍数", "是否盈利"]
    show_df = show_df.sort_values("止损距离%")
    show_df["止损距离%"] = show_df["止损距离%"].map("{:.3f}%".format)
    show_df["ATR%"] = show_df["ATR%"].map("{:.3f}%".format)
    show_df["R倍数"] = show_df["R倍数"].map("{:.3f}".format)
    show_df["是否盈利"] = show_df["是否盈利"].map({True: "✅ 盈利", False: "❌ 亏损"})
    st.dataframe(show_df, use_container_width=True, hide_index=True)

st.markdown("---")

# ════════════════════════════════════════════════════════════════════════════════
st.subheader("四、止损距离四分位分析：是否存在单调规律？")

q_vals = df["stop_dist_pct"].quantile([0.0, 0.25, 0.5, 0.75, 1.0]).values
q_labels = ["Q1（止损最小）", "Q2", "Q3", "Q4（止损最大）"]
q_data = []
for i in range(4):
    if i == 0:
        mask = (df["stop_dist_pct"] >= q_vals[i]) & (df["stop_dist_pct"] < q_vals[i + 1])
    else:
        mask = (df["stop_dist_pct"] > q_vals[i]) & (df["stop_dist_pct"] <= q_vals[i + 1])
    sub = df[mask]
    stats = _group_stats(sub)
    q_data.append({
        "分组": q_labels[i],
        "止损距离范围": f"{q_vals[i]:.2f}% ～ {q_vals[i+1]:.2f}%",
        "笔数": stats["n"],
        "胜率": f"{stats['wr']*100:.1f}%",
        "平均R": f"{stats['avg_r']:.4f}",
        "盈亏比": f"{stats['pf']:.4f}",
    })

q_df = pd.DataFrame(q_data)
st.dataframe(q_df, use_container_width=True, hide_index=True)

st.markdown("""
**四分位分析结论：止损距离与绩效之间不存在单调规律。**

- Q2（止损距离中等偏小，3.55%～4.66%）盈亏比最低（1.04），反而是"止损最大"的 Q4（>6.19%）盈亏比最高（2.01）。
- 但 Q1 的盈亏比（1.67）高于 Q2 和 Q3，说明极低止损距离（债券 ETF）具有独立的盈利来源。
- 整体看，**不存在"止损距离越小、信号越差"的系统性规律**，无法用于构建有效过滤器。
""")

st.markdown("---")

# ════════════════════════════════════════════════════════════════════════════════
st.subheader("五、ATR%（入场日波动率）与绩效的关系")

atr_low_mask = df["atr_pct"] < 0.5
atr_mid_mask = (df["atr_pct"] >= 0.5) & (df["atr_pct"] < 2.0)
atr_high_mask = df["atr_pct"] >= 2.0

atr_data = []
for label, mask in [("<0.5%", atr_low_mask), ("0.5%～2.0%", atr_mid_mask), ("≥2.0%", atr_high_mask)]:
    stats = _group_stats(df[mask])
    atr_data.append({
        "ATR%分组": label,
        "笔数": stats["n"],
        "占比": f"{stats['n']/len(df)*100:.1f}%",
        "胜率": f"{stats['wr']*100:.1f}%",
        "平均R": f"{stats['avg_r']:.4f}",
        "盈亏比": f"{stats['pf']:.4f}",
    })

atr_df = pd.DataFrame(atr_data)
st.dataframe(atr_df, use_container_width=True, hide_index=True)

st.markdown(f"""
ATR%（入场当日 ATR ÷ 收盘价）范围为 **{df['atr_pct'].min():.3f}% ～ {df['atr_pct'].max():.2f}%**，均值 **{df['atr_pct'].mean():.2f}%**。
低 ATR%（< 0.5%，对应止损距离约 < 1%）的交易占比极小，且绩效不差，与止损距离分析结论一致。
""")

st.markdown("---")

# ════════════════════════════════════════════════════════════════════════════════
st.subheader("六、这样做是否算过度拟合？")

st.markdown("""
**核心问题：** 如果我们"看到 GTLS 风险只有 0.03% NAV，然后决定把 `min_stop_distance_pct` 从 0.5% 提高到 1.0%"，
这是否构成过度拟合（Overfitting / Data Snooping）？

---

### 6.1 什么是过度拟合？

过度拟合发生在以下情况：
- 你**用同一批数据**既训练（发现规律）又决策（改参数）
- 参数改动并非基于先验逻辑，而是基于**后验观察到的具体结果**
- 改动可能只是在拟合历史噪音，而非真实的市场规律

---

### 6.2 用回测来决定参数 = Data Snooping

如果我们的决策过程是：
1. 运行回测 → 得到 3,341 笔交易
2. 发现止损距离 < 1% 的 27 笔交易
3. 分析这 27 笔的胜率 → 决定是否修改 `min_stop_distance_pct`

这就是 **Data Snooping（数据偷窥）**：参数是根据**已经见过的数据**调整的，
等于模型"记住"了训练集，而非发现了普遍规律。

即便这 27 笔绩效确实偏差，用同一批数据验证然后改参数，
也不能证明改后的策略在未来（样本外）会更好。

---

### 6.3 什么做法不算过度拟合？

**方法一：先验逻辑驱动（不看回测结果）**

在制定策略规则时，基于**市场微结构或交易成本逻辑**设定过滤阈值：
> "止损距离 < 0.5% 的信号，买卖价差和滑点就可能吃掉大部分利润，故过滤掉。"

这是先验（Prior）决策，不依赖回测结果，不算 Data Snooping。

**方法二：独立样本验证**

将数据分为训练集（如 2000–2015）和测试集（2016–2026），只用训练集发现规律，
用测试集验证，参数不再回调。两套数据得出相同结论才可信。

**方法三：模拟交易（Paper Trading）**

在当前策略规则不变的情况下，从 2026-08-01 开始纸上交易，收集真实的样本外数据。
这是最干净的样本外测试，完全未被历史回测"污染"。

---

### 6.4 本案的结论

本次分析发现，止损距离 < 1% 的 27 笔交易，绩效实际上**优于**整体：
- 胜率 51.9% vs 39.5%（高 12.4pp）
- 盈亏比 3.40 vs 1.56（高 1.84）

这说明：即便我们"想用回测来给自己找理由提高阈值"，数据本身也不支持这个改动。
**没有理由提高 `min_stop_distance_pct`**，当前 0.5% 的阈值是合理的。
""")

st.markdown("---")

# ════════════════════════════════════════════════════════════════════════════════
st.subheader("七、结论与建议")

st.success("""
**结论：不建议提高 `min_stop_distance_pct`，当前 0.5% 阈值是合理的。**

1. 历史回测中止损距离 < 1% 的 27 笔交易，胜率（51.9%）和盈亏比（3.40）均**显著高于**整体水平。
   这些信号主要来自债券 ETF（IEF、BND、AGG、TIP 等），低波动率但趋势平稳，正是策略擅长的类型。

2. 止损距离与绩效之间**不存在单调关系**：Q2 盈亏比最低，Q1 和 Q4 均高于 Q2，无法用止损距离构建有效过滤器。

3. GTLS 案例（0.03% NAV 风险）是 **5% 仓位上限 + 极小 ATR 的叠加效果**，风险计算本身是正确的。
   这是策略设计的合理结果，而非需要修复的 bug。

4. 如需继续研究，**正确的方法是等待模拟交易的样本外数据**，而非在已见过的回测数据上反复调参。
   模拟交易从 2026-08-01 正式启动，将提供真正干净的样本外验证。
""")

st.info("""
**如果未来真的想调整 `min_stop_distance_pct`，应该这样做：**
1. 先写下先验逻辑（为什么该阈值在经济学/交易成本上有意义），而非看回测结果再决定
2. 在修改之前锁定当前参数版本，用新参数重新跑独立时段的回测
3. 最终以模拟交易的实际表现为准，而非回测优化结果
""")
