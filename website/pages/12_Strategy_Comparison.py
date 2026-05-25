import streamlit as st
st.set_page_config(page_title="策略对比", page_icon="📊", layout="wide")
from website.shared import setup_sidebar
from website.components.strategy_badge import render_page_header
from website.components.charts import multi_strategy_nav
from website.data_loader import list_strategies, load_strategy

res  = setup_sidebar()
meta = res.meta

render_page_header("策略对比  Strategy Comparison", meta)
st.caption("跨策略版本的净值曲线与指标对比（全局页面，不随策略选择器变化）")
st.markdown("---")

strategies = list_strategies()

if len(strategies) < 2:
    st.markdown("""
<div class="placeholder-box">
<h3 style="color:#bbb;margin:0">仅有一个策略版本</h3>
<p style="color:#aaa;margin:12px 0 0 0">
当 <strong>Strategy 2.0</strong> 回测完成后，将 <code>results/v2/</code> 目录放入项目中，<br>
本页面将自动显示两个策略的对比图表和指标对比表。<br><br>
无需修改任何代码。
</p>
</div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("Strategy 1.0 当前指标（预览）")
    m = res.metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("CAGR", f"{m.get('cagr',0)*100:+.2f}%")
    col2.metric("Sharpe", f"{m.get('sharpe',0):+.3f}")
    col3.metric("Max Drawdown", f"{m.get('max_drawdown',0)*100:.1f}%")

else:
    # Load all strategies
    all_results = []
    for s in strategies:
        try:
            all_results.append(load_strategy(s.id))
        except Exception:
            pass

    # Multi-strategy NAV chart
    spy_nav = all_results[0].spy_nav if all_results else None
    st.plotly_chart(
        multi_strategy_nav(all_results, spy_nav),
        use_container_width=True,
    )

    # Side-by-side metrics table
    st.subheader("核心指标对比")
    import pandas as pd

    def fmt(v, pct=False, decimals=2):
        if v is None: return "—"
        if pct: return f"{v*100:+.{decimals}f}%"
        return f"{v:+.{decimals}f}"

    rows = []
    metrics_keys = [
        ("CAGR", "cagr", True),
        ("Total Return", "total_return", True),
        ("Annual Vol", "annual_vol", True),
        ("Max Drawdown", "max_drawdown", True),
        ("Sharpe", "sharpe", False),
        ("Sortino", "sortino", False),
        ("Calmar", "calmar", False),
        ("Win Rate", "win_rate", True),
        ("Profit Factor", "profit_factor", False),
    ]
    for label, key, is_pct in metrics_keys:
        row = [label]
        for r in all_results:
            v = r.metrics.get(key)
            row.append(fmt(v, pct=is_pct))
        rows.append(row)

    cols = ["指标"] + [r.meta.display_name for r in all_results]
    df = pd.DataFrame(rows, columns=cols)
    st.dataframe(df, use_container_width=True, hide_index=True)
