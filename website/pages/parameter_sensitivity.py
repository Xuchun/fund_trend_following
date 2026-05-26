"""参数敏感性分析"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pandas as pd
import streamlit as st
from website.shared import get_results, placeholder
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta
p    = meta.params_anchor
m    = res.metrics

render_page_header("参数敏感性分析  Parameter Sensitivity", meta)
st.caption(f"{meta.display_name} · 回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

# ── Overview table ─────────────────────────────────────────────────────────────
st.subheader("分析框架")
st.markdown(f"""
参数敏感性分析的目的是验证策略对参数选择的**鲁棒性（Robustness）**：
若策略在宽泛的参数范围内均能盈利，说明结果不依赖于特定参数的过拟合。

| 参数 | 当前基准值 | 测试范围 | 分析目的 | 状态 |
|------|-----------|---------|---------|------|
| 早期追踪止损乘数（< 1R） | **{p['trail_multiplier_r1']:.0f}×ATR** | 2.0 / 3.0 | 降低换手率 vs 早期止损保护 | ✅ 已完成 |
| 突破窗口（N） | **{p['breakout_window']} 日** | 100 / 200 | 动量周期与信号频率 | ✅ 已完成 |
| ATR 止损乘数 | {p['stop_loss_multiplier']:.1f}× | 1.5 / 2.0 / 2.5 / 3.0 | 止损松紧对 MaxDD 的影响 | 🔜 待分析 |
| 每笔风险比例 | {p['risk_per_trade']*100:.1f}% | 0.5% / 1.0% / 1.5% / 2.0% | 仓位大小对 MaxDD 的影响 | 🔜 待分析 |
| 热度上限 | {p['heat_limit']*100:.0f}% | 5% / 10% / 15% / 20% | 组合集中度影响 | 🔜 待分析 |
| 相关性阈值 | {p['correlation_threshold']:.2f} | 0.50 / 0.60 / 0.70 / 0.80 | 分散化效果 | 🔜 待分析 |
""")

st.markdown("---")

# ── Helper ─────────────────────────────────────────────────────────────────────
def _cost(turnover, params=p):
    rt = (params.get("slippage_bps", 10) + params.get("commission_bps", 3)) * 2
    return turnover * rt / 100


# ── Section 1: trail_multiplier_r1 ────────────────────────────────────────────
st.subheader("✅ 已完成：早期追踪止损乘数（trail_multiplier_r1）")
st.markdown("""
**背景：** 原版 2×ATR 早期追踪止损过紧，大量仓位在趋势充分发展前被震出，
年换手率高达 11.24x，隐含年化交易成本 2.92%。

**同批次变更：** 同步切换至复权价格（adj prices），令分红收益纳入回测 NAV。
因此下表比较的是两个版本之间的**综合差异**（追踪止损 + 价格体系同步变化）。
""")

trail_rows = [
    ("CAGR",       "+2.05%",  "+4.03%"),
    ("最大回撤",    "-31.6%",  "-28.4%"),
    ("Sharpe（rf=5%）", "-0.172",  "-0.018"),
    ("年换手率",    "11.24x",  "7.54x"),
    ("交易频率",    "261 笔/年","177 笔/年"),
    ("平均持仓",    "24 天",   "37 天"),
    ("隐含年化成本","2.92%",   "1.96%"),
]
st.dataframe(
    pd.DataFrame(trail_rows, columns=["指标", "2×ATR·原始价（原版）", "3×ATR·复权价（改后）"]),
    use_container_width=True, hide_index=True,
)
st.caption("注：上表 Sharpe 使用无风险利率 5% 计算（与当时代码一致）；当前基准已改为 2%（历史均值）。")
st.markdown("""
**结论：** 两项改动叠加后，CAGR 翻倍（+2.05% → +4.03%），最大回撤改善 3 个百分点，
交易成本降低约 1%/年，平均持仓从 24 天延长至 37 天。
""")

st.markdown("---")

# ── Section 2: breakout_window ────────────────────────────────────────────────
st.subheader("✅ 已完成：突破窗口（breakout_window）")
st.markdown("""
**背景：** 100 日突破每年产生约 177 笔交易，平均持仓 37 天，仍偏短。
200 日突破（即 52 周新高）是机构趋势跟踪中最经典的入场门槛，
信号更少但质量更高，预期可将平均持仓延长至 60–90 天。

**测试方法：** 保持其余所有参数不变（3×ATR 早期止损、复权价格、SPY 200日过滤器），
仅改变突破窗口，在完整 2004–2024 回测期对比结果。
""")

is_200 = abs(p.get("breakout_window", 100) - 200) < 1
cagr_cur     = m.get("cagr", 0)
maxdd_cur    = m.get("max_drawdown", 0)
sharpe_cur   = m.get("sharpe", 0)
turnover_cur = m.get("annual_turnover", 0)
tpy_cur      = m.get("trades_per_year", 0)
hold_cur     = m.get("avg_holding_days", 0)
cost_cur     = _cost(turnover_cur)
maxdd_dur    = m.get("max_dd_duration_days", 0)

fmt_cur = [
    f"{cagr_cur*100:+.2f}%",
    f"{maxdd_cur*100:.1f}%",
    f"{sharpe_cur:+.3f}",
    f"{turnover_cur:.2f}x",
    f"{tpy_cur:.0f} 笔/年",
    f"{hold_cur:.0f} 天",
    f"{cost_cur:.2f}%",
    f"{maxdd_dur:,} 天",
]

# N=100 reference (adj prices, trail_r1=3x run)
REF_N100 = ["+4.03%", "-28.4%", "-0.018", "7.54x", "177 笔/年", "37 天", "1.96%", "789 天"]

if is_200:
    col_n100, col_n200 = REF_N100, fmt_cur
    lbl_n100, lbl_n200 = "N=100（原版）", "**N=200（当前）**"
else:
    col_n100, col_n200 = fmt_cur, ["—"] * len(fmt_cur)
    lbl_n100, lbl_n200 = "**N=100（当前）**", "N=200（待回测）"

bw_rows = list(zip(
    ["CAGR", "最大回撤", "Sharpe（rf=5%→2%）", "年换手率", "交易频率", "平均持仓", "隐含年化成本", "最长水下时间"],
    col_n100, col_n200,
))
st.dataframe(
    pd.DataFrame(bw_rows, columns=["指标", lbl_n100, lbl_n200]),
    use_container_width=True, hide_index=True,
)
if is_200:
    st.caption("注：N=100 的 Sharpe 使用旧无风险利率 5% 计算；N=200 使用 2%（历史均值）。")

if is_200:
    cagr_chg  = cagr_cur - 0.0403
    tpy_chg   = tpy_cur - 177
    hold_chg  = hold_cur - 37
    cost_chg  = cost_cur - 1.96

    st.markdown(f"""
**结论：** 将突破窗口从 100 日延长至 200 日后：
- **交易频率**：{tpy_cur:.0f} 笔/年（原 177 笔，变化 {tpy_chg:+.0f} 笔）
- **平均持仓**：{hold_cur:.0f} 天（原 37 天，变化 {hold_chg:+.0f} 天）
- **隐含年化成本**：{cost_cur:.2f}%（原 1.96%，节省 {1.96-cost_cur:+.2f}%/年）
- **CAGR**：{cagr_cur*100:+.2f}%（原 +4.03%，变化 {cagr_chg*100:+.2f}%）
- **最大回撤**：{maxdd_cur*100:.1f}%（原 -28.4%）
- **Sharpe**：{sharpe_cur:+.3f}（原 -0.018）
- **最长水下时间**：{maxdd_dur:,} 天（原 789 天）

> **选择 {p['breakout_window']} 日突破为基准参数的理由**：
> 200 日突破（52 周新高）是业界最常用的趋势入场门槛，信号少但质量高，
> 持仓时间更长，交易摩擦成本更低。
""")
else:
    st.info("N=200 回测结果待更新，完成后此处自动显示对比数据。")

st.markdown("---")

# ── Pending analyses ───────────────────────────────────────────────────────────
st.subheader("🔜 待完成：其他参数网格搜索")
st.markdown("""
以下分析将在后续版本中完成，采用**网格搜索（Grid Search）+ 热力图**形式展示：

**分析优先级：**
1. **ATR 止损乘数**：与持仓时间和回撤深度直接相关
2. **每笔风险比例**：影响仓位规模和资金曲线波动
3. **热度上限 + 相关性阈值**：联合分析，评估分散化效果

每个参数的分析结果将包含：
- CAGR / Sharpe / MaxDD 热力图（参数 × 时间子区间）
- 最优参数区间识别
- 参数稳定性评估（避免过拟合）
""")

placeholder("Phase 6", "参数敏感性分析 — 网格搜索热力图")
