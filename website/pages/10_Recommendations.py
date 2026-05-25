import streamlit as st
st.set_page_config(page_title="推荐实盘参数", page_icon="✅", layout="wide")
from website.shared import setup_sidebar, placeholder
from website.components.strategy_badge import render_page_header

res  = setup_sidebar()
meta = res.meta

render_page_header("推荐实盘参数  Live Trading Recommendations", meta)
st.caption("基于回测结果的实盘操作建议（Phase 6 完成后完整填充）")
st.markdown("---")

# Show current baseline params even before Phase 6
st.subheader("当前基准参数（Baseline Anchor）")
st.markdown("以下参数为当前回测所用的基准参数，Phase 6 参数分析完成后将给出优化建议。")

p = meta.params_anchor
col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
**入场与信号参数**
| 参数 | 当前值 |
|---|---|
| 突破窗口 (breakout_window) | {p['breakout_window']} 天 |
| ATR 周期 (atr_period) | {p['atr_period']} 天 |
| Gap 过滤 (gap_filter) | ±{p['gap_filter']*100:.1f}% |

**止损参数**
| 参数 | 当前值 |
|---|---|
| 固定止损倍数 (stop_loss_multiplier) | {p['stop_loss_multiplier']}×ATR |
| 追踪止损 <1R (trail_r1) | {p['trail_multiplier_r1']}×ATR |
| 追踪止损 1-3R (trail_r3) | {p['trail_multiplier_r3']}×ATR |
| 追踪止损 >3R (trail_r5) | {p['trail_multiplier_r5']}×ATR |
""")

with col2:
    st.markdown(f"""
**仓位与风险参数**
| 参数 | 当前值 |
|---|---|
| 单笔风险 (risk_per_trade) | {p['risk_per_trade']*100:.0f}% NAV |
| 单仓上限 (position_cap) | {p['position_cap']*100:.0f}% NAV |
| 组合热度上限 (heat_limit) | {p['heat_limit']*100:.0f}% NAV |

**相关性过滤**
| 参数 | 当前值 |
|---|---|
| 相关性窗口 (correlation_window) | {p['correlation_window']} 天 |
| 相关性阈值 (correlation_threshold) | {p['correlation_threshold']} |
| 减仓比例 (correlation_reduction) | {p['correlation_reduction']*100:.0f}% |
""")

st.markdown("---")
placeholder("Phase 6 · 参数优化分析", "推荐实盘参数（基于参数敏感性 + Walk-Forward）")
