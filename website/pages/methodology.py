"""回测方法论"""

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

render_page_header("回测方法论  Methodology", meta)
st.caption(f"回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

# ── Architecture ──────────────────────────────────────────────────────────────
st.subheader("1. 系统架构")
st.markdown("""
回测引擎采用**事件驱动型**（Event-Driven）架构，严格模拟真实交易流程：

```
数据层（Data Layer）
  └── Yahoo Finance → Parquet 缓存 → 增量更新

信号层（Signal Layer）
  └── t 日收盘后计算所有信号（突破、止损、追踪止损）

执行层（Execution Layer）
  └── t+1 日开盘价执行（含滑点、佣金、Gap 过滤）

组合层（Portfolio Layer）
  └── 每日更新持仓、NAV、风险敞口
```
""")

st.markdown("---")

# ── No lookahead bias ─────────────────────────────────────────────────────────
st.subheader("2. 防前视偏差（No Look-Ahead Bias）")
st.markdown("""
本回测严格遵循**信息隔离**原则，确保每一步只使用当时可得的历史信息：

| 操作 | 时间点 |
|------|--------|
| 突破信号计算 | t 日收盘后（使用 t-1 至 t-100 日数据） |
| 止损/追踪止损更新 | t 日收盘后 |
| ATR 计算 | 使用 Wilder 指数平滑，无未来数据 |
| 交易执行 | t+1 日开盘价 |
| 仓位规模计算 | 使用 t 日 ATR（已知量） |

关键实现：所有信号均通过 `shift(1)` 处理，确保 t 日信号**不使用** t 日数据。
""")

st.markdown("---")

# ── Transaction costs ─────────────────────────────────────────────────────────
st.subheader("3. 交易成本假设")
col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
| 成本项目 | 假设值 |
|----------|--------|
| 滑点（单边） | {meta.params_anchor.get('slippage_bps',10):.0f} bps |
| 佣金（单边） | {meta.params_anchor.get('commission_bps',3):.0f} bps |
| 往返总成本 | {(meta.params_anchor.get('slippage_bps',10)+meta.params_anchor.get('commission_bps',3))*2:.0f} bps |
""")
with col2:
    st.markdown("""
**成本合理性说明：**
- 机构交易 DMA 滑点约 5–15 bps
- 主流券商佣金 1–5 bps
- 对于 $1,000 万量级账户，13 bps 单边成本属于保守估计
- **真实成本可能更高**，尤其是中盘股流动性较差时
""")

st.markdown("---")

# ── Cash management ───────────────────────────────────────────────────────────
st.subheader("4. 资金管理")
st.markdown(f"""
**闲置资金处理：** 未持仓部分投入 **{meta.cash_proxy}**（iShares 1–3 年期国债 ETF，2002 年上市）

- 避免现金拖累（Cash Drag）
- 获取无风险利率收益，2004–2021 年约 1–4%/年，2022–2024 年高息期约 4–5%/年
- 模拟真实机构运营中的资金利用效率

**初始资本：** $10,000,000（一千万美元）
""")

st.markdown("""
<div class="info-box">
<strong>现金代理选择说明：为何用 SHY，而不用 SGOV？</strong><br>
<strong>SGOV</strong>（iShares 0–3 个月国债 ETF）是更接近"无风险利率"的工具，
但它直到 <strong>2022 年才上市</strong>。如果将 SGOV 用于 2004–2024 全期回测，
则 2004–2021 年间（共 18 年）的闲置现金收益将被记为 0%，
严重低估策略在利率正常化时期的真实回报。<br><br>
<strong>SHY</strong>（iShares 1–3 年期国债 ETF）自 <strong>2002 年上市</strong>，
可完整覆盖整个回测区间，因此选用 SHY 作为现金代理，
以确保回测结果的一致性和真实性。
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Performance metrics ───────────────────────────────────────────────────────
st.subheader("5. 绩效指标计算方法")
st.markdown("""
| 指标 | 计算方法 |
|------|---------|
| **CAGR** | (NAV_end / NAV_start)^(252/交易日数) − 1 |
| **最大回撤** | max((peak − trough) / peak) |
| **Sharpe 比率** | (年化收益 − 无风险利率) / 年化波动率，无风险利率 = 5% |
| **Sortino 比率** | (年化收益 − 无风险利率) / 下行波动率 |
| **Calmar 比率** | CAGR / \|最大回撤\| |
| **Profit Factor** | 总盈利 / 总亏损（基于 R 倍数） |
| **R 倍数** | 实际盈亏 / 入场时风险（1R） |

SPY 基准数据来自 Yahoo Finance 实际价格，归一化到回测起始日 = 1.0。
""")

st.markdown("---")

# ── Limitations reminder ──────────────────────────────────────────────────────
st.markdown("""
<div class="info-box">
<strong>方法论局限性</strong><br>
本回测使用固定标的池（S&P 900 当前成分股），不模拟指数调整事件。
详见「局限性声明」页面。
</div>
""", unsafe_allow_html=True)
