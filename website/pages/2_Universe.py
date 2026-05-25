import streamlit as st
import pandas as pd
st.set_page_config(page_title="数据与标的池", page_icon="🌐", layout="wide")

from website.shared import setup_sidebar
from website.components.strategy_badge import render_page_header

res  = setup_sidebar()
meta = res.meta

render_page_header("数据与标的池  Data & Universe", meta)
st.caption(f"{meta.display_name} · 候选标的池构成与数据来源")
st.markdown("---")

# ── Universe summary ────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("美股个股（候选）", f"~{meta.universe_stocks:,} 只",
              help="S&P 500（503只）+ S&P MidCap 400（400只）去重合并")
with col2:
    st.metric("ETF", f"{meta.universe_etfs} 只",
              help="宽基、行业、债券、商品 ETF 手工维护清单")
with col3:
    st.metric("候选标的总计", f"~{meta.universe_total:,} 只",
              help="每日经过动态过滤后约 700–800 只实际参与信号扫描")

st.markdown("""
<div class="info-box">
<strong>每日动态过滤条件</strong>（在候选总计的基础上再过滤）：<br>
① 股价 > <strong>$10</strong> &nbsp;|&nbsp;
② 60日均成交额（ADV60）> <strong>$20M/天</strong> &nbsp;|&nbsp;
③ 数据有效（is_tradable = True，排除停牌日和脏数据日）
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Data source ─────────────────────────────────────────────────────────────
st.subheader("数据来源")
c1, c2 = st.columns(2)
with c1:
    st.markdown(f"""
| 项目 | 详情 |
|---|---|
| 数据提供商 | Yahoo Finance（yfinance 库） |
| 数据类型 | 日线 OHLCV + 复权因子 |
| 价格调整 | 按股息和拆股调整（adjusted close） |
| 缓存格式 | Parquet 文件（增量更新） |
| 回测期间 | {meta.backtest_start} → {meta.backtest_end} |
| 初始资本 | ${meta.initial_capital:,.0f} |
| 现金代理 | {meta.cash_proxy}（iShares 1-3年国债 ETF） |
""")
with c2:
    st.markdown("""
| 数据质量处理 | 说明 |
|---|---|
| `is_tradable` 标志 | 过滤停牌日、OHLC 逻辑错误日 |
| 复权因子异常检测 | adj_factor 跳变 > 50% 时标记为不可交易 |
| 开盘价修正 | open > high 或 open < low 时替换为 close |
| 增量下载 | 只下载缓存末日之后的新数据 |
""")

st.markdown("---")

# ── Stock universe ───────────────────────────────────────────────────────────
st.subheader("股票标的池")
st.markdown(f"""
**S&P 500**（大盘股，市值 ~$140亿+）：503 只当前成分股，来源：Wikipedia
**S&P MidCap 400**（中盘股，市值 ~$20亿–$140亿）：400 只当前成分股，来源：Wikipedia
合并去重后约 **{meta.universe_stocks:,} 只**，覆盖策略目标范围（市值 > $20亿）
""")

st.markdown("""
<div class="warning-box">
<h4>⚠️ 标的池局限性（幸存者偏差）</h4>
当前使用 <strong>2024年末的现有成分股</strong>，不含历史退市、破产或被摘牌的公司。
这意味着所有「活到今天」的公司都被纳入了2004年起的回测，产生显著的幸存者偏差。
详见「局限性声明」页面。
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── ETF table ────────────────────────────────────────────────────────────────
st.subheader(f"ETF 完整列表（{meta.universe_etfs} 只）")

etf_df = pd.DataFrame(meta.etf_universe)
etf_df.columns = ["Ticker", "名称", "类别"]

# Add Yahoo Finance link
etf_df["Yahoo Finance"] = etf_df["Ticker"].apply(
    lambda t: f"[{t}](https://finance.yahoo.com/quote/{t})"
)

st.dataframe(
    etf_df[["Ticker", "名称", "类别"]],
    use_container_width=True,
    hide_index=True,
    column_config={
        "Ticker": st.column_config.TextColumn("Ticker", width=80),
        "名称":   st.column_config.TextColumn("名称",   width=340),
        "类别":   st.column_config.TextColumn("类别",   width=160),
    },
)

st.caption(f"共 {len(etf_df)} 只 ETF，覆盖宽基大盘、科技、金融、能源、医疗、工业、消费、债券、商品、房地产、国际市场等类别。")
