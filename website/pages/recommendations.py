"""推荐实盘参数"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta
p    = meta.params_anchor

render_page_header("推荐实盘参数  Recommendations", meta)
st.caption(f"{meta.display_name} — 当前 Anchor 参数组合")
st.markdown("---")

st.markdown("""
<div class="info-box">
<strong>说明</strong><br>
以下参数为 Strategy 1.0 基准（Anchor）参数组合，作为后续参数敏感性分析的出发点。
在 Phase 6 分析完成前，<strong>不建议直接将此参数组合用于实盘</strong>。
真实部署前需完成 Walk-Forward 验证。
</div>
""", unsafe_allow_html=True)

st.markdown("---")
st.subheader("Anchor 参数表")

col1, col2 = st.columns(2)
with col1:
    st.markdown("**信号参数**")
    st.markdown(f"""
| 参数 | 值 | 说明 |
|------|-----|------|
| 突破窗口 | {p['breakout_window']} 日 | N 日高点突破 |
| ATR 周期 | {p['atr_period']} 日 | Wilder 指数平滑 |
| 初始止损 | {p['stop_loss_multiplier']:.1f}×ATR | 入场风险定义 |
| 最小止损距离 | {p.get('min_stop_distance_pct',0.005)*100:.1f}% | 防止止损过近 |
| Gap 过滤 | ±{p.get('gap_filter',0.025)*100:.1f}% | 跳空过滤阈值 |
""")

    st.markdown("**追踪止损参数**")
    st.markdown(f"""
| 盈利区间 | 追踪止损 |
|---------|---------|
| < 1R | {p['trail_multiplier_r1']:.0f}×ATR |
| 1R – 3R | {p['trail_multiplier_r3']:.0f}×ATR |
| > 3R | {p['trail_multiplier_r5']:.0f}×ATR |
""")

with col2:
    st.markdown("**仓位管理参数**")
    st.markdown(f"""
| 参数 | 值 | 说明 |
|------|-----|------|
| 每笔风险比例 | {p['risk_per_trade']*100:.0f}% NAV | 固定比例风险 |
| 单标的上限 | {p['position_cap']*100:.0f}% NAV | 集中度控制 |
| 组合热度上限 | {p['heat_limit']*100:.0f}% NAV | 总风险敞口上限 |
| 相关性阈值 | {p['correlation_threshold']:.2f} | 超过则减半仓 |
| 相关性窗口 | {p.get('correlation_window',60)} 日 | 滚动相关性 |
""")

    st.markdown("**执行成本参数**")
    st.markdown(f"""
| 参数 | 值 |
|------|-----|
| 滑点（单边） | {p.get('slippage_bps',10):.0f} bps |
| 佣金（单边） | {p.get('commission_bps',3):.0f} bps |
| 闲置资金 | {meta.cash_proxy}（短期国债） |
""")

st.markdown("---")
st.subheader("实盘部署建议")
st.markdown(f"""
**在 Phase 6 分析完成前，建议先进行以下准备工作：**

1. **选择经纪商和数据源**
   - 推荐具备 DMA（Direct Market Access）能力的机构经纪商
   - 历史数据建议使用 Refinitiv 或 Tiingo（替代 Yahoo Finance）

2. **模拟盘验证（Paper Trading）**
   - 先在模拟账户跑 3–6 个月，观察真实滑点与模型假设的差距
   - 记录实际执行成本，校准回测参数

3. **初始资金规模**
   - 建议起始规模 ≥ $100 万（确保仓位计算有效且佣金比例合理）
   - 本回测以 $1,000 万为基准设计

4. **风险预算**
   - 设定最大可承受回撤（如 −20%）
   - 若触及则暂停策略，等待 Phase 6 分析结果

5. **待 Phase 6 完成后：**
   - 参数敏感性分析将给出更稳健的参数范围
   - Walk-Forward 验证将确认样本外有效性
   - 届时可给出具体的 **推荐参数区间**
""")

st.markdown("---")
st.markdown("""
<div class="info-box">
<strong>下一步：Strategy 2.0</strong><br>
Strategy 2.0 将在 Strategy 1.0 基础上引入<strong>市场环境过滤器</strong>
（SPY 200日均线规则），预期可将最大回撤从 -54% 控制至 -25% 以内，
同时保持 CAGR > 8%。详见「下一步计划」页面。
</div>
""", unsafe_allow_html=True)
