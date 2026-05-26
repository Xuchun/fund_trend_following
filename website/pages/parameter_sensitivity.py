"""参数敏感性分析"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

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

# ── Overview ──────────────────────────────────────────────────────────────────
st.subheader("分析框架")
st.markdown(f"""
参数敏感性分析的目的是验证策略对参数选择的**鲁棒性（Robustness）**：
若策略在宽泛的参数范围内均能盈利，说明结果不依赖于特定参数的过拟合。

以下参数将逐一或联合测试，当前基准值来自 `params_anchor`：

| 参数 | 当前基准值 | 测试范围 | 分析目的 | 状态 |
|------|-----------|---------|---------|------|
| 早期追踪止损乘数（< 1R） | **{p['trail_multiplier_r1']:.0f}×ATR** | 2.0 / 2.5 / 3.0 / 4.0 | 降低换手率 vs 早期止损保护 | ✅ 已完成 |
| 突破窗口（N） | {p['breakout_window']} 日 | 50 / 75 / 100 / 150 / 200 | 动量周期敏感性 | 🔜 待分析 |
| ATR 止损乘数 | {p['stop_loss_multiplier']:.1f}× | 1.5 / 2.0 / 2.5 / 3.0 | 止损松紧对 MaxDD 的影响 | 🔜 待分析 |
| 每笔风险比例 | {p['risk_per_trade']*100:.1f}% | 0.5% / 1.0% / 1.5% / 2.0% | 仓位大小对 MaxDD 的影响 | 🔜 待分析 |
| 热度上限 | {p['heat_limit']*100:.0f}% | 5% / 10% / 15% / 20% | 组合集中度影响 | 🔜 待分析 |
| 相关性阈值 | {p['correlation_threshold']:.2f} | 0.50 / 0.60 / 0.70 / 0.80 | 分散化效果 | 🔜 待分析 |
""")

st.markdown("---")

# ── Completed: trail_multiplier_r1 ────────────────────────────────────────────
st.subheader("✅ 已完成：早期追踪止损乘数（trail_multiplier_r1）")

st.markdown("""
**背景：** 原版 2×ATR 早期追踪止损过紧，导致大量仓位在趋势充分发展前被震出，
年换手率高达 11.24x，隐含年化交易成本 2.92%。

**测试方法：** 保持所有其他参数不变，仅改变早期追踪止损乘数，
在 S&P 900 + 全部 ETF（约 983 只标的）、2004–2024 完整回测期上对比结果。

**规则说明：** 最短持仓限制和初始止损不受影响：
- 初始止损（entry − 2×ATR）无论何时都立即平仓（资金保护硬红线）
- 早期追踪止损只影响盈利 < 1R 阶段的追踪距离
""")

# Comparison table
cagr_new     = m.get("cagr", 0)
maxdd_new    = m.get("max_drawdown", 0)
sharpe_new   = m.get("sharpe", 0)
turnover_new = m.get("annual_turnover", 0)
tpy_new      = m.get("trades_per_year", 0)
hold_new     = m.get("avg_holding_days", 0)
cost_new     = turnover_new * (p.get("slippage_bps", 10) + p.get("commission_bps", 3)) * 2 / 100

is_3x = abs(p.get("trail_multiplier_r1", 2.0) - 3.0) < 0.01

if is_3x:
    col_2x = ["2.05%", "-31.6%", "-0.172", "11.24x", "261 笔/年", "24 天", "2.92%"]
    col_3x = [
        f"{cagr_new*100:+.2f}%",
        f"{maxdd_new*100:.1f}%",
        f"{sharpe_new:+.3f}",
        f"{turnover_new:.2f}x",
        f"{tpy_new:.0f} 笔/年",
        f"{hold_new:.0f} 天",
        f"{cost_new:.2f}%",
    ]
    current_label = "**3×ATR（当前）**"
    prev_label    = "2×ATR（原版）"
else:
    col_2x = [
        f"{cagr_new*100:+.2f}%",
        f"{maxdd_new*100:.1f}%",
        f"{sharpe_new:+.3f}",
        f"{turnover_new:.2f}x",
        f"{tpy_new:.0f} 笔/年",
        f"{hold_new:.0f} 天",
        f"{cost_new:.2f}%",
    ]
    col_3x = ["—", "—", "—", "—", "—", "—", "—"]
    current_label = "**2×ATR（当前）**"
    prev_label    = "3×ATR"

import pandas as pd
df_compare = pd.DataFrame({
    "指标": ["CAGR", "最大回撤", "Sharpe", "年换手率", "交易频率", "平均持仓", "隐含年化成本"],
    prev_label if is_3x else current_label: col_2x,
    current_label if is_3x else prev_label: col_3x,
})
st.dataframe(df_compare, use_container_width=True, hide_index=True)

if is_3x:
    dd_change   = maxdd_new - (-0.316)
    sharpe_chg  = sharpe_new - (-0.172)
    cagr_chg    = cagr_new - 0.0205
    cost_chg    = cost_new - 2.92
    tpy_chg     = tpy_new - 261

    st.markdown(f"""
**结论：** 将早期追踪止损从 2×ATR 放宽至 3×ATR 后：
- **换手率**：{turnover_new:.2f}x（原 11.24x，变化 {turnover_new-11.24:+.2f}x）
- **交易频率**：{tpy_new:.0f} 笔/年（原 261 笔，变化 {tpy_chg:+.0f} 笔）
- **平均持仓**：{hold_new:.0f} 天（原 24 天）
- **隐含年化成本**：{cost_new:.2f}%（原 2.92%，节省 {2.92-cost_new:+.2f}%/年）
- **CAGR**：{cagr_new*100:+.2f}%（原 +2.05%，变化 {cagr_chg*100:+.2f}%）
- **最大回撤**：{maxdd_new*100:.1f}%（原 -31.6%）
- **Sharpe**：{sharpe_new:+.3f}（原 -0.172）

> **选择 {p['trail_multiplier_r1']:.0f}×ATR 为基准参数的理由**：
> 在降低交易摩擦的同时，保持策略对趋势的跟踪能力。
> 初始止损不受影响，资金保护机制完整。
""")
else:
    st.info("3×ATR 回测结果待更新，回测完成后此处自动显示对比数据。")

st.markdown("---")

# ── Pending analyses ──────────────────────────────────────────────────────────
st.subheader("🔜 待完成：其他参数网格搜索")
st.markdown("""
以下分析将在后续版本中完成，采用**网格搜索（Grid Search）+ 热力图**形式展示：

**分析优先级：**
1. **突破窗口 N**：对策略影响最大的参数，直接决定信号频率和趋势质量
2. **ATR 止损乘数**：与持仓时间和回撤深度直接相关
3. **每笔风险比例**：影响仓位规模和资金曲线波动
4. **热度上限 + 相关性阈值**：联合分析，评估分散化效果

每个参数的分析结果将包含：
- CAGR / Sharpe / MaxDD 热力图（参数 × 时间子区间）
- 最优参数区间识别
- 参数稳定性评估（避免过拟合）
""")

placeholder("Phase 6", "参数敏感性分析 — 网格搜索热力图")
