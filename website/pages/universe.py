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
    st.metric("ETF 数量", f"{meta.universe_etfs}", help="来自 ETFs.csv，涵盖大盘/板块/债券/商品/国际/另类资产等（SPY + SHY 为辅助标的不纳入策略）")
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
- 日均成交额（ADV）> $2,000 万（流动性过滤）
- 收盘价 > $10（防止低价股噪声）

> ⚠️ **幸存者偏差说明**：标的池使用的是 2024 年末仍在 S&P 900 中的公司，
> 不包含历史退市或破产公司。这是本回测最主要的偏差来源。
""")

st.markdown("---")

# ── ETF universe ──────────────────────────────────────────────────────────────
st.subheader(f"ETF 标的池：{meta.universe_etfs} 只可交易 ETF（共 85 只，SPY + SHY 为辅助标的）")

st.markdown("""
ETF 列表来自项目根目录的 **`data/ETFs.csv`**，涵盖美股宽基、行业板块、固定收益、
国际股票、大宗商品、另类资产等多个类别，为趋势跟踪策略提供多元化的信号来源。

- **SPY**：用作市场基准（Benchmark）和 Strategy 2.0 均线过滤器，不纳入策略持仓
- **SHY**：用作闲置资金的现金代理（Cash Proxy），不作为策略交易标的
""")

if meta.etf_universe:
    etf_df = pd.DataFrame(meta.etf_universe)

    # Category order for display
    cat_order = [
        "美股指数", "美股风格", "板块 SPDR", "美股行业",
        "国际股票", "美国国债", "债券", "大宗商品", "房地产",
        "波动率", "加密货币",
    ]
    etf_df["cat_order"] = etf_df["category"].apply(
        lambda c: cat_order.index(c) if c in cat_order else 99
    )
    etf_df = etf_df.sort_values(["cat_order", "ticker"]).drop(columns="cat_order")

    tab_labels = [c for c in cat_order if c in etf_df["category"].values]
    tabs = st.tabs(tab_labels)

    for tab, cat in zip(tabs, tab_labels):
        with tab:
            grp = etf_df[etf_df["category"] == cat][["ticker", "name"]]
            grp = grp.rename(columns={"ticker": "Ticker", "name": "名称 / Full Name"})
            st.dataframe(grp, use_container_width=True, hide_index=True)

    st.markdown(f"**合计：{len(etf_df)} 只 ETF**（SPY + SHY 标注为辅助标的，不纳入策略交易）")
else:
    st.info("ETF 列表未加载。请检查 results/v1/strategy_meta.json 中的 etf_universe 字段。")

st.markdown("---")

# ── Regime filter note ────────────────────────────────────────────────────────
if meta.params_anchor.get("regime_filter_enabled", False):
    ticker  = meta.params_anchor.get("regime_ticker", "SPY")
    window  = meta.params_anchor.get("regime_sma_window", 200)
    st.markdown(f"""
<div class="info-box">
<strong>市场环境过滤器已启用</strong><br>
当 <strong>{ticker}</strong> 收盘价低于其 <strong>{window} 日均线</strong>时，
停止新建仓位。SPY 本身同时担任过滤器信号源，不纳入策略交易标的。
</div>
""", unsafe_allow_html=True)
else:
    st.markdown("""
<div class="info-box">
<strong>市场环境过滤器（Strategy 1.0 未启用）</strong><br>
Strategy 2.0 将引入 <strong>SPY 200 日均线过滤器</strong>：
当 SPY 价格低于均线时，停止新建仓位，现金额外流入 SHY。
预期可将最大回撤从 -54% 显著降低。
</div>
""", unsafe_allow_html=True)

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

**ETF 来源文件：** `data/ETFs.csv`（{meta.universe_etfs + 2} 行，含 SPY + SHY 辅助标的）
""")
