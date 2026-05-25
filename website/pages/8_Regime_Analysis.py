import streamlit as st
import pandas as pd
st.set_page_config(page_title="市场环境分析", page_icon="🌦️", layout="wide")
from website.shared import setup_sidebar, placeholder
from website.components.strategy_badge import render_page_header

res = setup_sidebar()
render_page_header("市场环境分析  Regime Analysis", res.meta)
st.caption("策略在不同市场环境下的表现分解")
st.markdown("---")

# Show what we CAN compute from existing data
st.subheader("各年度表现（已有数据）")

annual = res.nav.resample("YE").last().pct_change().dropna()
annual.index = annual.index.year
df = pd.DataFrame({"年度回报": annual}).reset_index()
df.columns = ["年份", "年度回报"]
df["年度回报%"] = df["年度回报"].map(lambda x: f"{x*100:+.1f}%")
df["盈亏"] = df["年度回报"].map(lambda x: "✅" if x > 0 else "❌")
st.dataframe(df[["年份","年度回报%","盈亏"]], use_container_width=True, hide_index=True)

st.markdown("---")
st.markdown("""
**完整 Regime 分析将包含：**

| 市场环境 | 区间 | 策略 CAGR | SPY CAGR | 策略 MaxDD |
|---|---|---|---|---|
| 金融危机 | 2008–2009 | 待计算 | — | — |
| 量化宽松牛市 | 2010–2019 | 待计算 | — | — |
| 新冠崩盘+复苏 | 2020–2021 | 待计算 | — | — |
| 加息熊市 | 2022 | 待计算 | — | — |
| AI 驱动牛市 | 2023–2024 | 待计算 | — | — |
""")
placeholder("Phase 6 · 市场环境分析", "Regime Analysis 详细分解")
