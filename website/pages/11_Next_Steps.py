import streamlit as st
st.set_page_config(page_title="下一步计划", page_icon="🚀", layout="wide")
from website.shared import setup_sidebar
from website.components.strategy_badge import render_page_header

res  = setup_sidebar()
meta = res.meta

render_page_header("下一步计划  Next Steps", meta)
st.caption("从 Yahoo Finance 原型走向真实可部署策略的路线图")
st.markdown("---")

actions = [
    ("★★★", "切换至 Polygon.io（含历史退市股）",
     "消除幸存者偏差——这是当前回测最大的不确定性来源。Polygon.io 的 US Stocks 历史数据含全部已退市股，切换后 CAGR 预计下调 20%–50%，但回测才真正可信。",
     "#c62828", "立即行动"),
    ("★★★", "Paper Trading 验证（3–6 个月）",
     "在真实市场用模拟账户跑策略（Interactive Brokers / Alpaca 均支持），验证实盘执行质量：滑点是否与模型一致？信号生成延迟多少？Gap 开盘如何处理？",
     "#c62828", "数据切换后立即开始"),
    ("★★", "完成 Phase 6 分析层",
     "扰动测试（15个参数）、蒙特卡洛（1000条路径）、Walk-Forward（4个窗口）、Regime 分析。完成后才能给出有数据支撑的推荐参数。",
     "#e65100", "进行中"),
    ("★★", "引入历史 S&P 成分股变动记录",
     "使用 CRSP 或 Compustat 的 Point-in-Time 成分股数据，替代当前「用现有成分股回溯历史」的做法，消除 Universe 构建偏差。",
     "#e65100", "中期"),
    ("★", "Strategy 2.0 开发",
     "在 Strategy 1.0 框架上引入：① 市场环境过滤器（SPY 在 200MA 以下时禁止开多）② 做空信号（N日低点突破做空）。预计将 2008 年回撤从 -54% 控制到 -15% 以内。",
     "#1565c0", "中期"),
    ("★", "多策略组合",
     "将趋势跟踪策略与其他低相关性策略（如均值回归、波动率套利）组合，降低单策略风险集中度，平滑不同市场环境下的表现。",
     "#1565c0", "长期"),
]

for priority, title, desc, color, timing in actions:
    st.markdown(f"""
<div style="border:1px solid #e0e0e0;border-left:5px solid {color};
border-radius:0 8px 8px 0;padding:14px 18px;margin-bottom:12px;background:#fafafa;">
<div style="display:flex;justify-content:space-between;align-items:center;">
<div>
<span style="background:{color};color:white;padding:2px 8px;border-radius:10px;
font-size:0.75rem;font-weight:700">{priority}</span>
<strong style="margin-left:8px;font-size:1rem">{title}</strong>
</div>
<span style="font-size:0.78rem;color:#888;white-space:nowrap">{timing}</span>
</div>
<div style="font-size:0.85rem;color:#555;margin-top:8px">{desc}</div>
</div>
""", unsafe_allow_html=True)

st.markdown("---")
st.markdown("""
<div class="info-box">
<strong>Strategy 2.0 网站适配说明</strong><br>
当 Strategy 2.0 回测完成后，只需：<br>
① 运行回测脚本，输出至 <code>results/v2/</code><br>
② 编辑 <code>results/v2/strategy_meta.json</code>（填写差异说明）<br>
③ git push → 网站自动识别 v2，侧边栏自动出现策略选择器<br>
<strong>网站代码无需任何改动。</strong>
</div>
""", unsafe_allow_html=True)
