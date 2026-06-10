"""策略对比"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results
from website.components.strategy_badge import render_page_header
from website.components.charts import multi_strategy_nav
from website.data_loader import list_strategies, load_strategy

res  = get_results()
meta = res.meta

render_page_header("策略对比", meta)
st.caption("多版本策略净值对比")
st.markdown("---")

strategies = list_strategies()

if len(strategies) < 2:
    st.info("""
**当前仅有一个策略版本（Strategy 1.0）**

Strategy 2.0 上线后，此页面将自动显示两个策略的对比图表，包括：
- 归一化净值曲线对比（Strategy 1.0 vs 2.0 vs SPY）
- 关键指标对比表（CAGR / MaxDD / Sharpe / 胜率）
- Strategy 2.0 相对 1.0 的改进说明（引入市场环境过滤器）

**无需修改任何代码** — 只需将 Strategy 2.0 结果放入 `results/v2/` 目录即可。
""")
else:
    all_results = []
    for s in strategies:
        cache_key = f"_results_{s.id}"
        if cache_key not in st.session_state:
            with st.spinner(f"正在加载 {s.display_name}…"):
                st.session_state[cache_key] = load_strategy(s.id)
        all_results.append(st.session_state[cache_key])

    spy_nav = all_results[0].spy_nav
    st.plotly_chart(multi_strategy_nav(all_results, spy_nav), use_container_width=True)

    st.markdown("---")
    st.subheader("关键指标对比")

    import pandas as pd
    rows = []
    for r in all_results:
        m = r.metrics
        rows.append({
            "策略1.0": r.meta.display_name,
            "CAGR": f"{m.get('cagr',0)*100:+.2f}%",
            "最大回撤": f"{m.get('max_drawdown',0)*100:.1f}%",
            "Sharpe": f"{m.get('sharpe',0):+.3f}",
            "胜率": f"{m.get('win_rate',0)*100:.1f}%",
            "交易笔数": f"{int(m.get('n_trades',0)):,}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    for r in all_results:
        if r.meta.differs_from_previous:
            st.markdown(f"---")
            st.subheader(f"{r.meta.display_name} 改进点")
            diffs = r.meta.differs_from_previous
            for k, v in diffs.items():
                st.markdown(f"- **{k}**：{v}")
