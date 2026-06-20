"""策略对比 — 策略1.0 vs 策略2.0"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import GLOBAL_CSS

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

st.markdown("""
<style>
@media print {
    [data-testid="stSidebar"], [data-testid="stSidebarNav"],
    [data-testid="stHeader"], [data-testid="stDecoration"],
    [data-testid="stToolbar"], [data-testid="stStatusWidget"],
    header, footer, .stApp > header { display: none !important; }
    iframe { display: none !important; }
    .main .block-container, [data-testid="stMainBlockContainer"] {
        padding-top: 0.5cm !important;
        padding-left: 1cm !important;
        padding-right: 1cm !important;
        max-width: 100% !important;
    }
    @page { margin: 1.5cm; }
}
</style>
""", unsafe_allow_html=True)

import streamlit.components.v1 as _cv1

col1, col2 = st.columns([4, 2])
with col1:
    st.title("策略对比")
with col2:
    _cv1.html(
        '<div style="display:flex;justify-content:flex-end;align-items:center;'
        'gap:6px;padding-top:20px;">'
        '<span style="background:#1f77b4;color:white;padding:4px 10px;'
        'border-radius:14px;font-size:0.8rem;font-weight:700;">策略1.0</span>'
        '<span style="color:#888;font-size:1.2rem;">⚖️</span>'
        '<span style="background:#ff7f0e;color:white;padding:4px 10px;'
        'border-radius:14px;font-size:0.8rem;font-weight:700;">策略2.0</span>'
        '</div>',
        height=60,
    )

st.caption("策略1.0（突破趋势）vs 策略2.0（横盘收敛 + 箱体突破）")
st.markdown("---")

# ── 待回测完成横幅 ────────────────────────────────────────────────────────────
st.markdown("""
<div style="background:#fff3cd;border-left:5px solid #e65100;padding:16px 20px;border-radius:6px;margin:8px 0 20px 0;">
<h4 style="margin:0 0 8px 0;color:#e65100;">⏳ 策略2.0回测尚未完成，本页面定量对比数据待更新</h4>
<p style="margin:0;color:#7f4000;">
策略1.0已完成全量回测及稳健性验证。策略2.0正在开发中，回测完成后此页面将自动填充
净值曲线对比、绩效指标对比、逐年收益对比及相关性分析。
</p>
</div>
""", unsafe_allow_html=True)

# ── 设计理念对比 ──────────────────────────────────────────────────────────────
st.subheader("一、设计理念对比")

col_v1, col_v2 = st.columns(2)
with col_v1:
    st.markdown("""
    <div style="background:#e3f2fd;border-left:5px solid #1f77b4;padding:16px;border-radius:6px;">
    <h4 style="margin:0 0 8px 0;color:#1565c0;">📈 策略1.0 — 突破趋势</h4>
    <ul style="margin:0;padding-left:18px;">
    <li><strong>核心 Edge</strong>：价格突破近期前高 → 趋势延续</li>
    <li><strong>入场</strong>：200 日最高价突破（单一条件）</li>
    <li><strong>止损</strong>：ATR 止损（2×ATR）</li>
    <li><strong>止盈</strong>：分段追踪止损（3/3/5×ATR）</li>
    <li><strong>过滤</strong>：市场环境 + 相关性 + 成交量</li>
    <li><strong>参数数量</strong>：~13 个</li>
    <li><strong>状态</strong>：✅ 回测完成，推荐实盘</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

with col_v2:
    st.markdown("""
    <div style="background:#fff3e0;border-left:5px solid #ff7f0e;padding:16px;border-radius:6px;">
    <h4 style="margin:0 0 8px 0;color:#e65100;">📊 策略2.0 — 横盘收敛突破</h4>
    <ul style="margin:0;padding-left:18px;">
    <li><strong>核心 Edge</strong>：横盘收敛积聚能量 → 突破后更持久</li>
    <li><strong>入场</strong>：100 日突破 + 80 日收敛 + 突破强度（4 条件）</li>
    <li><strong>止损</strong>：结构止损（ATR + 近期低点）</li>
    <li><strong>止盈</strong>：单层追踪止损（20日最高 - 2×ATR）</li>
    <li><strong>过滤</strong>：极简（仅跳空保护）</li>
    <li><strong>参数数量</strong>：5 个</li>
    <li><strong>状态</strong>：⏳ 开发中，回测待完成</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# ── 核心参数对比 ──────────────────────────────────────────────────────────────
st.subheader("二、核心参数对比")

import pandas as _pd
_param_rows = [
    ("入场", "突破窗口", "200 日高点（high）", "100 日收盘价（close）"),
    ("入场", "横盘收敛条件", "无", "80 日内价格区间 < 25%（必须）"),
    ("入场", "突破强度条件", "可选（close/high_N > threshold）", "必须（当日阳线 > 1%）"),
    ("入场", "成交量确认", "有（1.5×均量）", "无"),
    ("入场", "市场环境过滤", "有（SPY 200 日均线）", "无"),
    ("入场", "相关性过滤", "有（Pearson > 0.7 则减仓）", "无"),
    ("止损", "机制", "ATR 止损（entry - 2×ATR）", "结构止损（max(ATR止损, 近期低点×0.995)）"),
    ("止盈", "机制", "分段追踪（3/3/5×ATR，按盈利档位）", "单层追踪（highest(high,20) - 2×ATR）"),
    ("仓位", "风险单位", "1% NAV / 笔", "1% NAV / 笔"),
    ("仓位", "单标的上限", "5% NAV", "5% NAV"),
    ("组合", "热度上限", "10% NAV", "10% NAV"),
    ("现金", "闲置资金", "SHY（1-3 年期国债）", "BIL / SGOV（超短期国债）"),
]
st.dataframe(
    _pd.DataFrame(_param_rows, columns=["模块", "维度", "策略1.0", "策略2.0"]),
    use_container_width=True, hide_index=True,
)

st.markdown("---")

# ── 预期差异 ──────────────────────────────────────────────────────────────────
st.subheader("三、基于设计逻辑的预期差异（待回测验证）")

st.markdown("""
以下为在策略2.0回测完成之前，基于理论逻辑的预期差异分析。所有数字将在回测完成后替换为实际数据。

| 维度 | 策略2.0 预期方向 | 理由 |
|------|-----------------|------|
| 入场信号频率 | 显著低于策略1.0 | 横盘收敛条件是额外的强过滤条件 |
| 平均持仓时长 | 可能更长 | 横盘突破后趋势延续性预期更强 |
| 胜率 | 预期高于策略1.0 | 更高质量的入场信号 |
| Profit Factor | 预期改善 | 横盘突破的右尾收益可能更大 |
| 牛市参与度 | 可能偏低 | 快速上涨时无横盘期 → 无入场信号 |
| 下行保护 | 待验证 | 无市场环境过滤，熊市暴露可能更大 |
| 参数稳定性 | 预期更优 | 参数数量少 50% 以上，过拟合风险更低 |
| 策略间相关性 | 待测量 | 两策略信号重叠程度决定组合配置价值 |
""")

st.markdown("""
<div class="info-box">
<strong>最关键的验证问题</strong><br>
<ol>
<li><strong>信号频率是否足够？</strong> 若横盘过滤使年均信号降至个位数，统计显著性将大幅下降</li>
<li><strong>横盘收敛是否真的带来增量 Alpha？</strong> 需要对比相同标的在1.0和2.0中的入场点和最终收益</li>
<li><strong>两策略的相关性多高？</strong> 若相关性 > 0.8，两策略提供的分散化价值有限</li>
<li><strong>2.0的 IS→OOS 衰减是否更小？</strong> 参数更少理论上应有更好的 Walk-Forward 表现</li>
</ol>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── 净值曲线对比占位区 ────────────────────────────────────────────────────────
st.subheader("四、净值曲线对比（待回测完成）")

st.markdown("""
<div class="placeholder-box">
<h3 style="color:#bbb;margin:0">⏳ 净值曲线对比</h3>
<p style="color:#aaa;margin:8px 0 0 0">
策略2.0回测完成后，将展示：策略1.0 vs 策略2.0 vs SPY 的全周期净值曲线对比，
以及逐年收益柱状图、滚动相关性曲线。
</p>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── 绩效指标对比占位区 ────────────────────────────────────────────────────────
st.subheader("五、核心绩效指标对比（待回测完成）")

_placeholder_metrics = [
    ("CAGR", "TBD", "TBD", "SPY ~10.5%"),
    ("Sharpe Ratio", "TBD", "TBD", "SPY ~0.45"),
    ("最大回撤", "TBD", "TBD", "SPY ~-55%"),
    ("胜率", "TBD", "TBD", "—"),
    ("Profit Factor", "TBD", "TBD", "—"),
    ("平均持仓天数", "TBD", "TBD", "—"),
    ("年均信号数", "TBD", "TBD", "—"),
    ("OOS Sharpe", "TBD", "TBD", "—"),
]
st.dataframe(
    _pd.DataFrame(_placeholder_metrics,
                  columns=["指标", "策略1.0（实际）", "策略2.0（待填充）", "SPY 参考"]),
    use_container_width=True, hide_index=True,
)

st.markdown("""
> **策略1.0实际数据**将在回测完成后从结果文件动态读取，上表中"TBD"将替换为真实数值。
""")
