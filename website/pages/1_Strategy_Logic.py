import streamlit as st
st.set_page_config(page_title="策略逻辑", page_icon="📐", layout="wide")

from website.shared import setup_sidebar
from website.components.strategy_badge import render_page_header

res  = setup_sidebar()
meta = res.meta

render_page_header("策略逻辑  Strategy Logic", meta)
st.caption(f"{meta.display_name} · {meta.subtitle}")
st.markdown("---")

# ── Differs from previous ───────────────────────────────────────────────────
if meta.differs_from_previous:
    d = meta.differs_from_previous
    st.markdown(f"""
<div style="background:#fff8e1;border:1px solid #ffc107;border-left:5px solid #ff6f00;
border-radius:6px;padding:14px 18px;margin-bottom:16px;">
<h4 style="color:#ff6f00;margin:0 0 8px 0">⚡ 与上一版本的差异（{d.get('summary','')}）</h4>
{"".join(f'<div>{"✅" if "新增" in c else "🔄" if "修改" in c else "➖"} {c}</div>' for c in d.get("changes",[]))}
</div>""", unsafe_allow_html=True)

# ── Core philosophy ─────────────────────────────────────────────────────────
st.subheader("1.1 策略核心思想")
st.markdown("""
趋势跟踪（Trend Following）的根本逻辑：

> **"让利润奔跑，快速止损。"**（Let profits run, cut losses short.）

策略通过价格**创 N 日新高**识别正在形成的上升趋势，用基于波动率（ATR）的追踪止损锁定收益。
策略**不预测**行情方向，只跟随**已经发生**的趋势。胜率低（约 37%）是正常特征——少数大赢家覆盖多数小止损。
""")

st.markdown("---")
col1, col2 = st.columns(2)

with col1:
    st.subheader("1.2 入场信号（Breakout Entry）")
    st.latex(r"\text{Entry Signal: } \text{close}[t] > \max\bigl(\text{high}[t-N\,:\,t-1]\bigr)")
    st.markdown(f"""
- **N = {meta.params_anchor['breakout_window']} 天**（100日高点突破）
- 使用 `shift(1)` 确保只用前一日数据，**无前视偏差**
- 同日多个信号时按突破强度（`close / rolling_high`）从高到低排序处理
- **执行**：t 日收盘触发信号，**t+1 日开盘价执行**（加 {meta.params_anchor['slippage_bps']:.0f} bps 滑点）
- Gap 过滤：若开盘相对前收偏离 > ±{meta.params_anchor['gap_filter']*100:.1f}%，放弃入场
""")

    st.subheader("1.3 初始止损（Initial Stop Loss）")
    st.latex(r"\text{stop\_loss} = \text{entry} - k_1 \times \text{ATR}_{20}")
    st.markdown(f"""
- **$k_1$ = {meta.params_anchor['stop_loss_multiplier']}**（入场价下方 2 个 ATR）
- ATR 使用 Wilder's 平滑（20日），代表市场正常波动尺度
- 定义 **1R = entry - stop\_loss**，为后续 R 倍数计算基础
- 最小止损距离：{meta.params_anchor['min_stop_distance_pct']*100:.1f}%（过小时拒绝入场）
""")

with col2:
    st.subheader("1.4 追踪止损（Trailing Stop — 分段棘轮）")
    st.markdown("""
随浮盈增加，追踪止损阶梯收紧，**只能上移，不能下移**：
""")
    st.markdown(f"""
| 当前浮盈（R 倍数）| 追踪止损公式 | 含义 |
|---|---|---|
| $r < 1R$ | $\\text{{HH}} - {meta.params_anchor['trail_multiplier_r1']}\\times\\text{{ATR}}$ | 保护初始止损 |
| $1R \\leq r < 3R$ | $\\text{{HH}} - {meta.params_anchor['trail_multiplier_r3']}\\times\\text{{ATR}}$ | 给趋势更多空间 |
| $r \\geq 3R$ | $\\text{{HH}} - {meta.params_anchor['trail_multiplier_r5']}\\times\\text{{ATR}}$ | 极大趋势中宽松持有 |

其中 **HH = 持仓期间最高收盘价**（Highest High，逐日更新）。
""")

    st.subheader("1.5 出场优先级")
    st.markdown("""
每日收盘时按优先级检查：
1. 🔴 **硬止损**：当日最低价 < stop_loss → 次日开盘出场（最高优先级）
2. 🟡 **追踪止损**：当日收盘价 < trail_stop → 次日开盘出场
3. ⚪ **回测结束**：持仓期末按最后收盘价强制平仓
""")

st.markdown("---")
st.subheader("1.6 仓位计算（4步过滤）")

steps = [
    ("Step 1 · 目标风险",
     f"每笔交易最多亏损 NAV 的 **{meta.params_anchor['risk_per_trade']*100:.0f}%**",
     f"shares = NAV × {meta.params_anchor['risk_per_trade']} / (entry − stop)"),
    ("Step 2 · 单标的上限",
     f"单仓市值不超过 NAV 的 **{meta.params_anchor['position_cap']*100:.0f}%**",
     f"shares = min(Step1, NAV × {meta.params_anchor['position_cap']} / entry)"),
    ("Step 3 · 相关性调整",
     f"若新标的与已持仓相关性 > **{meta.params_anchor['correlation_threshold']}**，仓位 × **{meta.params_anchor['correlation_reduction']}**",
     f"避免持仓方向高度重叠，相关性窗口 {meta.params_anchor['correlation_window']} 日"),
    ("Step 4 · 热度检查",
     f"组合总风险敞口 ≤ NAV 的 **{meta.params_anchor['heat_limit']*100:.0f}%**（硬性上限）",
     "新仓若超出热度上限则直接拒绝，不调仓"),
]

cols = st.columns(4)
for col, (title, desc, formula) in zip(cols, steps):
    with col:
        st.markdown(f"""
<div style="border:1px solid #e0e0e0;border-radius:8px;padding:14px;height:160px;">
<div style="font-weight:700;font-size:0.85rem;color:{meta.color};margin-bottom:6px;">{title}</div>
<div style="font-size:0.82rem;margin-bottom:8px;">{desc}</div>
<div style="font-size:0.75rem;color:#888;font-family:monospace;">{formula}</div>
</div>""", unsafe_allow_html=True)

st.markdown("---")
st.subheader("1.7 现金管理")
st.markdown(f"""
- 空仓资金投入 **{meta.cash_proxy}**（iShares 1-3 年国债 ETF）作为现金代理
- 每日收益计入 NAV，使空仓资金也能获取无风险收益
- 佣金：单边 **{meta.params_anchor['commission_bps']:.0f} bps**（机构级别费率）
- 策略**不使用杠杆**，最大风险由热度上限控制
""")
