import streamlit as st
st.set_page_config(page_title="回测方法论", page_icon="⚙️", layout="wide")

from website.shared import setup_sidebar
from website.components.strategy_badge import render_page_header

res  = setup_sidebar()
meta = res.meta

render_page_header("回测方法论  Methodology", meta)
st.caption(f"{meta.display_name} · 引擎设计与执行模型")
st.markdown("---")

# ── Backtest period ──────────────────────────────────────────────────────────
st.subheader("回测时间区间")
col1, col2, col3, col4 = st.columns(4)
col1.metric("开始日期", meta.backtest_start)
col2.metric("结束日期", meta.backtest_end)
col3.metric("回测跨度", "21 年")
col4.metric("交易日数", f"~{len(res.nav):,} 个")

events = [
    ("2004–2005", "互联网泡沫余震", "低波动复苏期，策略建立初始仓位"),
    ("2007–2009", "全球金融危机", "极端下行压力测试；纯多头策略受到最大考验"),
    ("2010–2019", "量化宽松牛市", "长期上升趋势，趋势跟踪策略的「自然栖息地」"),
    ("2020–2021", "新冠崩盘+V形复苏", "极端急跌急涨，考验止损和快速重入场能力"),
    ("2022",      "美联储加息熊市", "股债双杀，多数多头策略承压"),
    ("2023–2024", "AI驱动科技牛市", "窄幅科技行情，指数集中度高"),
]
st.markdown("**覆盖的主要市场环境**")
cols = st.columns(3)
for i, (period, title, desc) in enumerate(events):
    with cols[i % 3]:
        st.markdown(f"""
<div style="border:1px solid #e0e0e0;border-radius:6px;padding:10px;margin-bottom:8px;">
<div style="font-weight:700;font-size:0.8rem;color:{meta.color}">{period}</div>
<div style="font-weight:600;font-size:0.85rem">{title}</div>
<div style="font-size:0.78rem;color:#666;margin-top:3px">{desc}</div>
</div>""", unsafe_allow_html=True)

st.markdown("---")

# ── Engine design ────────────────────────────────────────────────────────────
st.subheader("事件驱动引擎（无前视偏差）")
st.markdown("每个交易日按以下**严格顺序**执行，信号生成与执行之间有一日延迟：")

steps = [
    ("① 开盘执行", "执行 t-1 日生成的入场/出场信号（使用 t 日开盘价）", "#1565c0"),
    ("② 现金收益", "对空仓资金应用 SHY 当日收益率（空仓也赚钱）", "#2e7d32"),
    ("③ 收盘扫描", "更新追踪止损；扫描全部标的，生成新的出场/入场信号（t+1日执行）", "#e65100"),
    ("④ NAV 更新", "按当日收盘价 mark-to-market，记录当日净值", "#6a1b9a"),
]
cols = st.columns(4)
for col, (title, desc, c) in zip(cols, steps):
    with col:
        st.markdown(f"""
<div style="border-left:4px solid {c};padding:10px 14px;background:#fafafa;border-radius:0 6px 6px 0;">
<div style="font-weight:700;color:{c};margin-bottom:4px">{title}</div>
<div style="font-size:0.82rem">{desc}</div>
</div>""", unsafe_allow_html=True)

st.markdown("""
**关键原则**：t 日收盘生成信号 → **t+1 日开盘价执行**，完全无前视偏差（look-ahead bias free）。
""")

st.markdown("---")

# ── Execution cost model ─────────────────────────────────────────────────────
st.subheader("执行成本模型")
col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
| 成本类型 | 参数 | 说明 |
|---|---|---|
| 滑点 | **{meta.params_anchor['slippage_bps']:.0f} bps**（单边） | 买入高于开盘价，卖出低于开盘价 |
| 佣金 | **{meta.params_anchor['commission_bps']:.0f} bps**（单边） | 机构级别费率估计 |
| Gap 过滤 | ±**{meta.params_anchor['gap_filter']*100:.1f}%** | 跳空超过阈值时放弃入场 |
| 市场冲击 | **未建模** | 大仓位局限性，见「局限性」页 |
| 杠杆 | **无** | 资金使用率由热度上限决定 |
""")
with col2:
    st.markdown("""
**资金使用率说明**

策略不使用杠杆，实际资金使用率取决于当时有效信号数量和热度限制：
- **典型区间**：20%–60% 仓位使用率
- **极端熊市**：接近 0%（无有效突破信号）
- **强趋势市场**：最高约 60%（受热度上限限制）

空仓资金自动投入 SHY，获取无风险利率收益。
""")

st.markdown("---")

# ── Indicator computation ────────────────────────────────────────────────────
st.subheader("指标预计算机制")
st.markdown(f"""
回测**开始前**批量预计算所有标的的所有指标，避免回测循环中的重复计算和前视偏差：

| 指标 | 计算方式 | 防前视措施 |
|---|---|---|
| ATR（20日） | Wilder's 平滑递推 | 每日 ATR 只用截至前一日的数据 |
| Rolling High（100日） | `high.shift(1).rolling(100).max()` | shift(1) 排除当日最高价 |
| ADV60（60日均成交额） | `dollar_vol.shift(1).rolling(60).mean()` | shift(1) 排除当日成交额 |
| 相关性（60日） | Pearson 对数收益率 | 用截至前一日数据计算 |
| 突破强度 | `close / rolling_high` | 依赖 rolling_high（已防前视）|
""")

st.markdown(f"""
当前回测：**{len(res.nav):,} 个交易日** × **~{meta.universe_total} 个标的**，
引擎耗时约 24 分钟（Python 单线程，参数扫描时可启用多进程）。
""")
