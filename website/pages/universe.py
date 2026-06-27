"""数据与标的池"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pandas as pd
import streamlit as st
from website.style import show_df
from website.shared import get_results
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta

_ticker_csv_path = Path(__file__).resolve().parents[2] / "results" / "v1" / "universe_tickers.csv"

render_page_header("数据与标的池", meta)
_cap_col, _btn_col = st.columns([5, 1])
with _cap_col:
    st.markdown(f"回测期间：{meta.backtest_start} → {meta.backtest_end}")
with _btn_col:
    if _ticker_csv_path.exists():
        st.download_button(
            label="⬇ 下载标的池",
            data=_ticker_csv_path.read_bytes(),
            file_name="universe_tickers.csv",
            mime="text/csv",
        )
    else:
        st.markdown("标的池文件未找到")
st.markdown("---")

# ── Overview ──────────────────────────────────────────────────────────────────
st.subheader("标的池概览")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("股票数量", f"{meta.universe_stocks:,}", help="S&P 900 成分股（S&P 500 + S&P MidCap 400）")
with col2:
    st.metric("ETF 数量", f"{meta.universe_etfs}", help="来自 ETFs.csv，涵盖大盘/板块/债券/商品/国际/另类资产等（SPY + SHY 为辅助标的不纳入策略1.0）")
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
st.subheader(f"ETF 标的池：{meta.universe_etfs} 只可交易 ETF（共 79 只，SPY + SHY 为辅助标的）")

st.markdown("""
ETF 列表来自项目根目录的 **`data/ETFs.csv`**，涵盖美股宽基、行业板块、固定收益、
国际股票、大宗商品、另类资产等多个类别，为趋势跟踪策略1.0提供多元化的信号来源。

- **SPY**：用作市场基准（Benchmark），不纳入策略1.0持仓
- **SHY**：用作闲置资金的现金代理（Cash Proxy），不作为策略1.0交易标的

**排除的 ETF：结构性不适合的产品（两类）**

以下 ETF 已被明确排除在标的池之外，均有具体的结构性原因，而非单纯根据历史表现筛选：

**第一类：波动率 / 反向 / 杠杆产品**（结构性负漂移）

| 代表产品 | 排除原因 |
|---------|---------|
| VXX、UVXY、VIXY | VIX 期货展期成本（Contango 损耗）导致长期必然亏损 |
| TQQQ、UPRO、SPXL、SQQQ | 每日复杠放大波动，长期受波动率拖拽侵蚀本金 |
| SSO、SDS、SH | 反向产品与纯多头趋势跟踪策略方向性矛盾 |
| LABU/LABD、NUGT/DUST、TNA/TZA | 日内重置机制在震荡市造成系统性损耗 |

**第二类：结构性不适合趋势跟踪的市场 / 资产类别**（经回测验证）

| 代码 | 产品 | 排除原因 |
|------|------|---------|
| GDX | 黄金矿业 ETF | 矿业股 = 金价 × 运营杠杆 + 公司特有风险（罢工/矿区政治），趋势性远差于实物金。策略池中已有 GLD/SLV 提供黄金敞口，GDX 是噪声更大的重复暴露（回测：3 笔 0% 胜率，亏损 $105k） |
| FXI | 中国大盘股 ETF | 中国市场受政府政策干预（2015 熔断、2021 科技监管整改、2023 房地产危机），监管行动导致突然性大跌，200 日突破信号无法预判政策风险（回测：2 笔 0% 胜率，亏损 $44k） |
| ASHR | 中国 A 股 ETF | 同 FXI，A 股受政策与资金流管控更直接（回测：1 笔 0% 胜率，亏损 $20k） |
| EMB | 新兴市场债券 ETF | 同时承受信用风险 + 利率风险 + 新兴市场风险，股市危机时与股票正相关（失去债券对冲价值），而利率上行时又受利率拖累——"最差时刻亏双份"（回测：3 笔 33% 胜率，亏损 $70k，含一笔 −4.9R 跳空） |
| KWEB | 中国互联网 ETF | 同 FXI / ASHR，政策干预风险尤为突出（2021 年单年跌逾 50%） |

> **注**：上述第二类排除在方向上与回测亏损一致，但决策依据是结构性论据而非事后拟合。
> 中国市场的政策不可预测性、新兴市场债券的双重风险暴露，是独立于回测数字的客观特征。
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
            show_df(grp, width="stretch", hide_index=True)

    st.markdown(f"**合计：{len(etf_df)} 只 ETF**（SPY + SHY 标注为辅助标的，不纳入策略1.0交易）")
else:
    st.info("ETF 列表未加载。请检查 results/v1/strategy_meta.json 中的 etf_universe 字段。")

st.markdown("""
> ℹ️ **ETF 上市日期过滤**：回测通过数据可用性自然实现——Yahoo Finance 数据从各 ETF
> 实际上市日起步，引擎对无数据日期的标的自动跳过；ADV-60 过滤额外要求至少 60 个交易日
> 的成交量历史（约 3 个月缓冲），进一步防止 ETF 在上市初期过早入场。
""")

st.markdown("---")

# ── Regime filter note ────────────────────────────────────────────────────────
if meta.params_anchor.get("regime_filter_enabled", False):
    ticker  = meta.params_anchor.get("regime_ticker", "SPY")
    window  = meta.params_anchor.get("regime_sma_window", 200)
    st.markdown(f"""
<div class="info-box">
<strong>市场环境过滤器已启用</strong><br>
当 <strong>{ticker}</strong> 收盘价低于其 <strong>{window} 日均线</strong>时，
停止新建仓位。SPY 本身同时担任过滤器信号源，不纳入策略1.0交易标的。
</div>
""", unsafe_allow_html=True)
else:
    st.markdown("""
<div class="info-box">
<strong>市场环境过滤器（当前配置未启用）</strong><br>
Strategy 1.0 设计方案包含此过滤器，当前参数配置已将其关闭（<code>regime_filter_enabled = False</code>）。
启用后，当 SPY 收盘价低于其 200 日均线时，策略1.0停止新建仓位，闲置资金流入 SHY。
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
3. 计算**复权价格**（adj_close / adj_high / adj_low）用于信号计算与指标计算
4. ATR 计算使用**复权价格**（非原始价格），避免拆股/分红导致 ATR 序列产生人为跳变

**回测覆盖期间：** {meta.backtest_start} → {meta.backtest_end}（约 {int((pd.Timestamp(meta.backtest_end) - pd.Timestamp(meta.backtest_start)).days / 365.25)} 年）

**ETF 来源文件：** `data/ETFs.csv`（{meta.universe_etfs + 2} 行，含 SPY + SHY 辅助标的）
""")
