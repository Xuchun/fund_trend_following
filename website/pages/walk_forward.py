"""Walk-Forward 验证"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results, placeholder
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta

render_page_header("Walk-Forward 验证  Walk-Forward Analysis", meta)
st.caption(f"{meta.display_name} · 回测期间：{meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

st.subheader("验证方法")
st.markdown("""
Walk-Forward 分析是评估策略**过拟合风险**的标准方法，模拟真实参数优化与实盘切换流程：

```
训练窗口（3年）→ 参数优化 → 测试窗口（1年）→ 记录样本外表现
─────────────────────────────────────────────────────────────►
[2004─2006] 优化 → [2007] 测试
         [2005─2007] 优化 → [2008] 测试
                  [2006─2008] 优化 → [2009] 测试
                           ... （滚动前进）
```

**分析输出（待生成）：**
1. 各期样本内 vs 样本外 CAGR 对比（评估参数是否过拟合）
2. 参数稳定性分析（不同时期优化出的参数是否一致）
3. 样本外综合绩效曲线
4. IS/OOS 衰减比率（理想值 < 30%）
""")

placeholder("Phase 6", "Walk-Forward 验证")
