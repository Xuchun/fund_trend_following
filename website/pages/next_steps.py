"""下一步计划"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta

render_page_header("下一步计划", meta)
st.caption(f"{meta.display_name} → Strategy 2.0 及后续路线图")
st.markdown("---")

st.subheader("Phase 6：深度分析（进行中）")
st.markdown("""
| 任务 | 状态 | 说明 |
|------|------|------|
| 参数敏感性网格搜索 | ⏳ 待完成 | 5 个关键参数 × 4–5 档 |
| 蒙特卡洛模拟（1,000次） | ⏳ 待完成 | Bootstrap 重采样 |
| Walk-Forward 验证 | ⏳ 待完成 | 3年训练 + 1年测试，滚动前进 |
| 市场环境分析 | ⏳ 待完成 | 按 VIX / SPY 趋势分期分析 |
""")

st.markdown("---")
st.subheader("Strategy 2.0：市场环境过滤器")
st.markdown("""
**核心改进：** 在 Strategy 1.0 基础上增加市场环境判断，避免在熊市中持续做多。

**拟议改进（待验证）：**

1. **市场环境过滤器（Market Regime Filter）**
   - 规则：SPY 当日收盘价 < SPY 200 日简单移动平均线 → 暂停新建仓
   - 现有持仓不强制平仓，但追踪止损继续保护
   - 预期效果：大幅减少 2008 年危机期间的损失

2. **VIX 波动率过滤（可选）**
   - VIX > 30 时缩减仓位至 50%
   - 高波动环境下降低风险敞口

3. **动态仓位规模调整（可选）**
   - 根据当前 VIX / ATR 水平动态调整每笔风险比例
   - 市场平静时加仓，高波动时降仓

**预期目标（基于历史规律，未经回测验证）：**

| 指标 | Strategy 1.0 | Strategy 2.0（预期） |
|------|------------|---------------------|
| CAGR | 0.3% | 8%–12% |
| 最大回撤 | -54.2% | -20% ~ -25% |
| Sharpe 比率 | -0.26 | 0.5–0.8 |

> ⚠️ 以上 Strategy 2.0 数字为**预期估算**，需正式回测验证。
""")

st.markdown("---")
st.subheader("后续研究路线图")

tab1, tab2, tab3 = st.tabs(["短期（1–3月）", "中期（3–6月）", "长期（6月+）"])

with tab1:
    st.markdown("""
**Phase 6 深度分析（当前优先级）：**
- [ ] 完成参数敏感性分析（网格搜索 + 热力图）
- [ ] 蒙特卡洛风险模拟（1,000 条路径）
- [ ] Walk-Forward 验证（评估过拟合程度）
- [ ] 市场环境分析（按牛/熊/震荡分期）
- [ ] 更新本网站所有"待填充"章节

**Strategy 2.0 开发：**
- [ ] 实现市场环境过滤器（SPY 200日均线规则）
- [ ] Strategy 2.0 全期回测（2004–2024）
- [ ] 与 Strategy 1.0 对比分析
""")

with tab2:
    st.markdown("""
**数据质量提升：**
- [ ] 接入历史 S&P 指数成分股数据（解决幸存者偏差）
- [ ] 验证 Yahoo Finance 数据与 Bloomberg/Refinitiv 的差异
- [ ] 考虑增加国际市场（MSCI World）

**策略增强：**
- [ ] VIX 波动率过滤器测试（Strategy 2.1）
- [ ] 动态仓位规模调整（Strategy 2.2）
- [ ] 考虑做空机制（Strategy 3.0 长远目标）
""")

with tab3:
    st.markdown("""
**实盘准备：**
- [ ] 选择机构经纪商（Interactive Brokers / TD Ameritrade）
- [ ] 接入实时数据（替代 Yahoo Finance 延时数据）
- [ ] 构建自动化交易执行系统
- [ ] 模拟盘运行 6 个月验证

**风险管理体系：**
- [ ] 定义实盘风险边界（最大 NAV 回撤 = -20% 暂停）
- [ ] 建立月度绩效审查流程
- [ ] 制定参数再优化触发条件
""")
