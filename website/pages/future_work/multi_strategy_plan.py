"""多策略开发 Plan"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pandas as pd
import streamlit as st
from website.style import show_df

st.title("多策略开发 Plan")
st.markdown("从单 Breakout 系统升级为 Multi-Alpha 专业趋势组合")
st.markdown("---")

# ── 核心思想 ──────────────────────────────────────────────────────────────────
st.subheader("一、核心思想")
st.markdown("""
当前策略的问题是：**Alpha 来源过于单一**，几乎完全依赖"200日 Breakout"。

成熟 CTA 不会只依赖单一 Breakout、单一时间框架或单一退出逻辑，而是通过
**Multi-Alpha Trend Stack** 叠加多个不同来源的趋势信号，从而：

- 降低单一参数依赖
- 降低不同市场环境（Regime）下的失效风险
- 提高 Sharpe 与资金曲线平滑度
- 降低回撤
""")
st.markdown("---")

# ── 核心升级 ──────────────────────────────────────────────────────────────────
st.subheader("二、核心升级方向")
st.markdown("从**单 Breakout 策略**升级为 **Multi-Speed / Multi-Alpha Trend System**")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**推荐 Alpha 层**")
    show_df(pd.DataFrame({
        "Alpha 类型": [
            "短周期 Breakout",
            "长周期 Breakout",
            "Moving Average Trend",
            "Relative Strength Momentum",
            "Volatility Expansion",
            "Pullback Continuation",
        ],
        "作用": [
            "更快进入趋势",
            "抓大趋势",
            "平滑趋势",
            "强者恒强",
            "抓波动爆发",
            "减少假 Breakout",
        ],
    }))

with col2:
    st.markdown("**推荐组合权重**")
    show_df(pd.DataFrame({
        "模块": [
            "Long Breakout（现有系统）",
            "Relative Strength Momentum",
            "Pullback Trend Continuation",
            "Volatility Expansion",
        ],
        "权重": ["40%", "30%", "20%", "10%"],
    })

st.markdown("---")

# ── Alpha Modules ─────────────────────────────────────────────────────────────
st.subheader("三、核心 Alpha 模块")

with st.expander("1. Relative Strength Momentum（优先级最高）", expanded=True):
    st.markdown("""
**核心思想：只做市场中最强的股票。**

每周计算 RS Score，仅做 Top 15%，再叠加趋势过滤：

$$RS = 0.5 \\times Return_{3M} + 0.5 \\times Return_{6M}$$

附加条件：$Price > MA_{200}$

**作用：**
- 非常适合美股市场特性
- 能显著提高组合 Sharpe
- 与 Breakout 信号来源不同，提供新的 Alpha 维度
""")

with st.expander("2. Pullback Continuation", expanded=True):
    st.markdown("""
**核心思想：不追高 Breakout，而是等强趋势中的回调后再继续上攻。**

入场条件：

$$Price > MA_{200},\\quad ADX > 25,\\quad \\text{回调} < 8\\%,\\quad \\text{突破 10 日新高}$$

**作用：**
- 提高胜率，降低假突破
- 资金曲线更平滑，回撤通常更低
""")

with st.expander("3. Multi-Timeframe Confirmation", expanded=True):
    st.markdown("""
**核心思想：多个时间周期同时确认趋势，过滤低质量信号。**

条件：

$$Price > MA_{50},\\quad MA_{50} > MA_{200},\\quad \\text{同时出现 52 周新高}$$

**作用：**
- 明显减少震荡市垃圾 Breakout
- 提高趋势质量，降低假信号
""")

st.markdown("---")

# ── Position Sizing 修复 ──────────────────────────────────────────────────────
st.subheader("四、Position Sizing 重要修复")
st.markdown("""
**当前问题：`position_cap` 把 ATR Risk Sizing 架空了。**

当 ATR 计算出的仓位远低于 `position_cap`（5% NAV）时，两者不冲突；
但当 ATR 仓位超过 5%，`position_cap` 截断后真实风险远低于设定的 1%，
导致 `risk_per_trade` 实际不起作用。
""")

st.markdown("**推荐修复方案：**")
show_df(pd.DataFrame({
    "参数": ["risk_per_trade", "position_cap"],
    "当前值": ["1%", "5%"],
    "建议值": ["0.20%", "15%–20%"],
    "目的": ["让 ATR Sizing 真正生效", "放宽单标的上限，让风险计算主导"],
})

st.info("修复后效果：更真实的风险标准化、更合理的仓位分配、更高的资本效率。")
st.markdown("---")

# ── 组合管理方式 ──────────────────────────────────────────────────────────────
st.subheader("五、专业级组合管理方式")
st.markdown("""
**核心原则：不把所有 Alpha 混成一个策略，而是 Alpha Separate → Portfolio Combine。**
""")

col_l, col_r = st.columns(2)
with col_l:
    st.markdown("**每个 Alpha 模块独立：**")
    st.markdown("""
- 独立开发与回测
- 独立评估 Sharpe / DD
- 独立交易执行
""")
with col_r:
    st.markdown("**在组合层统一管理：**")
    st.markdown("""
- Risk Parity（风险平价）
- Volatility Targeting（波动率目标）
- Exposure Control（敞口控制）
- Correlation Control（相关性控制）
""")

st.markdown("---")

# ── 最终目标 ──────────────────────────────────────────────────────────────────
st.subheader("六、最终目标")
st.markdown('从"单 Breakout 系统"升级为**多 Alpha 专业趋势组合**：')
show_df(pd.DataFrame({
    "目标": [
        "Alpha Diversification",
        "Multi-Timeframe Trend",
        "Better Position Sizing",
        "Portfolio-Level Risk Control",
    ],
    "预期效果": [
        "降低单策略失效风险",
        "提高跨 Regime 稳定性",
        "提高资本效率",
        "提高 Sharpe，降低回撤",
    ],
})
