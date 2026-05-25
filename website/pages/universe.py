"""数据与标的池"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pandas as pd
import streamlit as st
from website.shared import get_results
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta

render_page_header("数据与标的池  Universe & Data", meta)
st.caption(f"回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

# ── Overview ──────────────────────────────────────────────────────────────────
st.subheader("标的池概览")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("股票数量", f"{meta.universe_stocks:,}", help="S&P 900 成分股（S&P 500 + S&P MidCap 400）")
with col2:
    st.metric("ETF 数量", f"{meta.universe_etfs}", help="涵盖大盘/板块/债券/商品等 ETF")
with col3:
    st.metric("合计标的数", f"{meta.universe_total:,}")

st.markdown("---")

# ── Stock universe ────────────────────────────────────────────────────────────
st.subheader("股票标的池：S&P 900")
st.markdown(f"""
本回测使用 **S&P 900** 作为股票选股池，由以下两个指数成分股合并去重构成：

| 指数 | 成分股数量 | 覆盖范围 |
|------|-----------|---------|
| S&P 500 | ~503 | 美国大盘股，市值前 500 |
| S&P MidCap 400 | ~400 | 美国中盘股，市值 $20亿–$120亿 |
| **S&P 900（合并）** | **~{meta.universe_stocks}** | **大盘 + 中盘，市值约 $20亿以上** |

**入场过滤条件（逐笔检查）：**
- 市值 > $20 亿美元（$2B）
- 日均成交额 > $2,000 万（流动性过滤）
- 收盘价 > $10（防止低价股噪声）

> ⚠️ **幸存者偏差说明**：标的池使用的是 2024 年末仍在 S&P 900 中的公司，
> 不包含历史退市或破产公司。这是本回测最主要的偏差来源。
""")

st.markdown("---")

# ── ETF universe ──────────────────────────────────────────────────────────────
st.subheader(f"ETF 标的池：{meta.universe_etfs} 只 ETF")

if meta.etf_universe:
    etf_df = pd.DataFrame(meta.etf_universe)
    if "category" in etf_df.columns:
        for cat, grp in etf_df.groupby("category"):
            st.markdown(f"**{cat}**")
            display = grp[["ticker", "name"]].rename(columns={"ticker": "Ticker", "name": "名称"})
            st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.dataframe(etf_df, use_container_width=True, hide_index=True)
else:
    st.markdown("""
| 类别 | Ticker | 说明 |
|------|--------|------|
| 大盘 ETF | SPY, QQQ, IWM, DIA, MDY | 标普/纳斯达克/罗素/道琼斯/中盘 |
| 板块 ETF | XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLB, XLU, XLRE | S&P 500 各行业 SPDR |
| 债券 ETF | TLT, IEF, SHY, HYG | 长/中/短期国债、高收益债 |
| 商品 ETF | GLD, SLV, USO, DBA | 黄金/白银/石油/农业 |
| 国际 ETF | EEM, EFA | 新兴市场/发达市场 |
""")

st.markdown("---")

# ── Data source ───────────────────────────────────────────────────────────────
st.subheader("数据来源与处理")
st.markdown(f"""
**数据来源：** Yahoo Finance（通过 `yfinance` 库）

**数据处理流程：**
1. 下载日度 OHLCV 数据 + 分红/拆股复权因子
2. 以 Parquet 格式本地缓存，支持增量更新
3. 计算**复权收盘价**（close × adj_factor）用于信号计算
4. ATR 计算使用**原始价格**（非复权），保持一致性

**回测覆盖期间：** {meta.backtest_start} → {meta.backtest_end}（约 21 年）
""")
