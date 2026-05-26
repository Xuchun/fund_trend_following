"""局限性声明"""

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

render_page_header("局限性声明", meta)
st.caption(f"{meta.display_name} — 诚实评估回测的固有偏差")
st.markdown("---")

st.markdown("""
<div class="warning-box">
<h4>⚠️ 整体风险声明</h4>
本回测结果仅供研究参考，不构成投资建议。真实交易表现预计低于回测值
<strong>20%–50%</strong>，主要原因如下所述。
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Limitation 1: Survivorship bias ──────────────────────────────────────────
st.subheader("1. 幸存者偏差（最主要偏差）")
st.markdown(f"""
**问题：** 本回测使用 **2024 年末**仍在 S&P 900 指数中的公司，向前追溯至 2004 年。
这意味着：

- 历史上已退市、破产或被踢出指数的公司**未被纳入**
- 典型例子：雷曼兄弟（2008年破产）、贝尔斯登（2008年危机）
- 幸存至 2024 年的公司天然具有"过去表现良好"的选择偏差

**影响估计：** CAGR 可能虚高 **2%–5%**（20年复利效应可能使总回报虚高 50%+）

**缓解措施（未来工作）：**
- 使用历史成分股数据库（如 Sharadar、Tiingo 机构数据）
- 模拟指数调整事件（加入/剔除）

---
""")

# ── Limitation 2: Long-only ───────────────────────────────────────────────────
st.subheader("2. 纯多头策略局限性")
st.markdown(f"""
**问题：** Strategy 1.0 仅做多，在熊市中无对冲机制。

- 2008 年金融危机：最大回撤 **{res.metrics.get('max_drawdown',0)*100:.1f}%**，持续约 12 年才恢复
- 2020 年疫情冲击、2022 年加息熊市均造成显著回撤
- 与对冲基金不同，无法通过做空降低系统性风险

**Strategy 2.0 改进方向：**
- 引入市场环境过滤器（SPY 200日均线规则）
- 熊市期间暂停建仓，现金权益比上升
- 预计可将最大回撤控制在 -25% 以内

---
""")

# ── Limitation 3: Transaction costs ──────────────────────────────────────────
st.subheader("3. 交易成本假设局限性")
st.markdown("""
**问题：** 实际交易成本存在以下未建模因素：

| 因素 | 模型假设 | 真实情况 |
|------|----------|---------|
| 市场冲击成本 | 未建模 | 大单（>0.5% ADV）会显著推高滑点 |
| 流动性限制 | 假设均可成交 | 中盘股可能无法以预设规模成交 |
| 借券成本 | N/A（多头） | 若将来做空则需考虑 |
| 日间价格影响 | 固定 10bps 滑点 | 高波动日（如财报日）滑点可能更高 |

---
""")

# ── Limitation 4: Data quality ────────────────────────────────────────────────
st.subheader("4. 数据质量局限性")
st.markdown("""
**Yahoo Finance 数据潜在问题：**
- 历史复权价格可能存在点误差（尤其是2004–2008年早期数据）
- 分拆、合并、股息的复权处理偶有错误
- 部分股票在某些交易日可能缺失数据（已用前向填充处理）

**建议：** 实盘前使用路孚特（Refinitiv）或彭博（Bloomberg）数据验证回测结果。

---
""")

# ── Limitation 5: Parameter optimization ─────────────────────────────────────
st.subheader("5. 参数优化偏差")
st.markdown("""
**问题：** 当前参数（100日突破、2×ATR止损等）是基于历史经验选定的，
虽然未进行显式优化，但研究者本人可能存在**无意识的参数选择偏差**。

**评估方法（Phase 6 待完成）：**
- Walk-Forward 分析验证参数在样本外是否同样有效
- 参数敏感性分析评估结果对参数变化的鲁棒性

---
""")

# ── Summary ───────────────────────────────────────────────────────────────────
st.subheader("综合评估")
st.markdown("""
| 偏差来源 | 严重程度 | 对 CAGR 的影响估计 |
|----------|---------|------------------|
| 幸存者偏差 | ⭐⭐⭐⭐⭐ 最高 | −2% ~ −5% CAGR |
| 纯多头 + 2008危机 | ⭐⭐⭐⭐ 高 | 已在回测中体现 |
| 交易成本低估 | ⭐⭐⭐ 中 | −0.5% ~ −1.5% CAGR |
| 数据质量 | ⭐⭐ 低 | 难以量化，可能双向 |
| 参数选择偏差 | ⭐⭐ 低-中 | 待 Walk-Forward 评估 |

**结论：** 考虑所有偏差后，真实 CAGR 预计比回测值低 3%–7%。
Strategy 2.0 通过引入市场环境过滤器，可能显著改善风险调整后回报。
""")
