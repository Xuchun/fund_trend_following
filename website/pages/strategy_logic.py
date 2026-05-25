"""策略逻辑"""

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

render_page_header("策略逻辑  Strategy Logic", meta)
st.caption(f"{meta.display_name} · {meta.subtitle}")
st.markdown("---")

# ── Overview ──────────────────────────────────────────────────────────────────
st.subheader("策略概述")
st.markdown(f"""
本策略是一个**经典动量突破型趋势跟踪策略**，纯多头（Long Only），适用于股票和 ETF 市场。
核心理念源自 Richard Dennis 的海龟交易法则与 David Harding 的 AHL 系统：
**顺势而为，快速止损，让利润奔跑**。

| 维度 | 说明 |
|------|------|
| 策略类型 | 趋势跟踪（Trend Following）|
| 方向 | 纯多头（Long Only） |
| 入场信号 | N 日高点突破 |
| 止损 | ATR 固定止损 + 追踪止损 |
| 仓位管理 | 固定比例风险（1% NAV/笔） |
| 执行 | 次日开盘价成交 |
""")

st.markdown("---")

# ── Entry ─────────────────────────────────────────────────────────────────────
st.subheader("1. 入场条件（Entry）")
st.markdown(f"""
当收盘价突破过去 **{p['breakout_window']} 个交易日的最高价**时触发买入信号。

```
信号（t 日收盘后）：close[t] > max(high[t-{p['breakout_window']}:t-1])
执行（t+1 日开盘）：以 t+1 日开盘价 × (1 + 滑点) 买入
```

- 使用 `shift(1)` 防止前视偏差（look-ahead bias）
- 仅在满足仓位过滤条件后建仓（见仓位管理）
- Gap 过滤：若开盘价偏离昨收 >{p.get('gap_filter',0.025)*100:.1f}%，跳过该信号
""")

st.markdown("---")

# ── Stop loss ─────────────────────────────────────────────────────────────────
st.subheader("2. 初始止损（Initial Stop）")
st.markdown(f"""
入场后立即设置固定止损位，基于 **ATR(20) Wilder 平滑**计算：

```
止损价  = 入场价 − {p['stop_loss_multiplier']:.1f} × ATR(20)
1R      = 入场价 − 止损价   （每笔交易的单位风险）
```

- ATR 使用 Wilder 指数平滑（alpha = 1/20）
- 最小止损距离：入场价的 {p.get('min_stop_distance_pct',0.005)*100:.1f}%（防止止损过近）
""")

st.markdown("---")

# ── Trailing stop ─────────────────────────────────────────────────────────────
st.subheader("3. 分段追踪止损（Segmented Trailing Stop）")
st.markdown(f"""
随着持仓盈利增加，逐步收紧追踪止损以锁定利润：

| 当前盈利区间 | 追踪止损距离 | 说明 |
|------------|------------|------|
| < 1R | {p['trail_multiplier_r1']:.0f}×ATR | 宽松，给趋势发展空间 |
| 1R – 3R | {p['trail_multiplier_r3']:.0f}×ATR | 中等，开始锁定利润 |
| > 3R | {p['trail_multiplier_r5']:.0f}×ATR | 收紧，保护大盈利 |

追踪止损**只升不降**：`new_stop = max(old_stop, close − k×ATR)`
""")

st.markdown("---")

# ── Position sizing ───────────────────────────────────────────────────────────
st.subheader("4. 仓位管理（Position Sizing — 4 步过滤）")

cols = st.columns(4)
steps = [
    ("Step 1", "目标风险", f"每笔交易风险 = NAV × {p['risk_per_trade']*100:.0f}%\n股数 = 目标风险 ÷ (入场价 − 止损价)"),
    ("Step 2", "单标的上限", f"单标的持仓市值上限 = NAV × {p['position_cap']*100:.0f}%"),
    ("Step 3", "相关性调整", f"若持仓中已有相关性 > {p['correlation_threshold']:.2f} 的标的，\n新仓位减半"),
    ("Step 4", "组合热度检查", f"组合总风险敞口 ≤ NAV × {p['heat_limit']*100:.0f}%\n超限则拒绝开仓"),
]
for col, (step, title, body) in zip(cols, steps):
    with col:
        st.markdown(f"""
<div class="info-box">
<strong>{step}：{title}</strong><br>
<small>{body.replace(chr(10), '<br>')}</small>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Execution ─────────────────────────────────────────────────────────────────
st.subheader("5. 执行与成本假设")
col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
**执行模型：**
- 信号在 t 日收盘后生成
- 以 t+1 日开盘价执行（无前视偏差）
- 滑点：{p.get('slippage_bps',10):.0f} bps（单边）
- 佣金：{p.get('commission_bps',3):.0f} bps（单边）
- 总成本约 {(p.get('slippage_bps',10)+p.get('commission_bps',3))*2:.0f} bps/往返
""")
with col2:
    st.markdown(f"""
**闲置资金管理：**
- 未持仓资金投入 **{meta.cash_proxy}**（短期国债 ETF）
- 获取无风险收益，降低现金拖累
- 相关窗口：{p.get('correlation_window',60)} 日滚动相关性
""")
