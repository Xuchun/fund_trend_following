"""是否购买第二家数据源"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pandas as pd
import plotly.graph_objects as go
import plotly.io as _pio
import streamlit as st

_pio.templates.default = "plotly_white"

st.title("是否购买第二家数据源？")
st.markdown("评估 Tiingo EOD 数据质量及是否需要第二数据源交叉验证回测结论")
st.markdown("---")

# ── Tiingo Data Quality Visualization ────────────────────────────────────────
st.subheader("Tiingo 数据质量现状（基于全量 15,255 个标的扫描）")

_qr_path = _root / "data" / "cache" / "tiingo_quality_report.csv"
if _qr_path.exists():
    _qr = pd.read_csv(_qr_path)
    _total = len(_qr)
    _has_spike   = int((_qr["price_spikes"] > 0).sum())
    _has_adj     = int((_qr["adj_jump_rows"] > 0).sum())
    _has_zerovol = int((_qr["zero_vol_days"] > 0).sum())
    _clean       = int(((_qr["price_spikes"] == 0) & (_qr["adj_jump_rows"] == 0)).sum())

    _col1, _col2, _col3, _col4 = st.columns(4)
    _col1.metric("总覆盖标的数", f"{_total:,}")
    _col2.metric("完全无异常", f"{_clean:,}", f"{_clean/_total*100:.0f}%")
    _col3.metric("价格尖峰异常", f"{_has_spike:,}", f"{_has_spike/_total*100:.0f}%", delta_color="inverse")
    _col4.metric("复权系数跳变", f"{_has_adj:,}", f"{_has_adj/_total*100:.0f}%", delta_color="inverse")

    # Donut chart: issue breakdown
    _fig_qual = go.Figure(go.Pie(
        labels=["无异常（已过滤）", "含价格尖峰", "含复权跳变", "仅含零量日"],
        values=[_clean,
                _has_spike - int(((_qr["price_spikes"] > 0) & (_qr["adj_jump_rows"] > 0)).sum()),
                _has_adj - int(((_qr["price_spikes"] > 0) & (_qr["adj_jump_rows"] > 0)).sum()),
                int(((_qr["price_spikes"] == 0) & (_qr["adj_jump_rows"] == 0) & (_qr["zero_vol_days"] > 0)).sum()),
               ],
        hole=0.5,
        marker_colors=["#22c55e", "#f97316", "#ef4444", "#fbbf24"],
    ))
    _fig_qual.update_layout(
        title=f"Tiingo 全量标的数据质量分布（共 {_total:,} 个）",
        height=360,
        margin=dict(t=50, b=10),
        legend=dict(orientation="h", y=-0.1),
        annotations=[dict(text=f"{_clean/_total*100:.0f}%<br>无异常", x=0.5, y=0.5, showarrow=False, font_size=14)],
    )
    st.plotly_chart(_fig_qual, width="stretch")

    # Price spike count distribution
    _sp_dist = _qr[_qr["price_spikes"] > 0]["price_spikes"].clip(upper=10)
    _sp_vcnt = _sp_dist.value_counts().sort_index()
    _sp_xcnt = int((_qr["price_spikes"] > 10).sum())
    _sp_labels = [str(i) for i in _sp_vcnt.index] + ["11+"]
    _sp_vals   = list(_sp_vcnt.values) + [_sp_xcnt]

    _fig_sp = go.Figure(go.Bar(
        x=_sp_labels,
        y=_sp_vals,
        marker_color="#f97316",
        text=[str(v) for v in _sp_vals],
        textposition="outside",
    ))
    _fig_sp.update_layout(
        title="含价格尖峰的标的：尖峰数量分布",
        xaxis_title="价格尖峰次数",
        yaxis_title="标的数量",
        height=300,
        margin=dict(t=50, b=40),
    )
    st.plotly_chart(_fig_sp, width="stretch")

    st.info(
        f"**策略1.0的处理方式：** 引擎在回测前会扫描每个标的的价格序列，"
        f"对 {_has_spike:,} 个含价格尖峰的标的进行打标——极端异常价格（偏离均值超过 5σ）"
        "会被替换为前一日收盘价，不产生虚假突破信号。"
        f"同样，{_has_adj:,} 个含复权跳变的标的已在回测引擎中特殊处理，"
        "不会因复权调整不连续而触发错误信号。"
    )
else:
    st.info("Tiingo 数据质量报告文件未找到。")

st.markdown("---")

st.subheader("主流备选数据供应商")
st.markdown("""
| 供应商 | 费用（年）| 退市标的覆盖 | 主要特点 |
|--------|---------|------------|---------|
| **Norgate Data** | ~$300 | ✅ 完整覆盖 | 专为量化回测设计；历史成分股快照；复权算法透明；社区口碑最佳 |
| **CSI Data** | ~$500 | ✅ 完整覆盖 | 机构级历史数据；含基本面；集成于 Amibroker/TradingBlox |
| **Polygon.io** | $79/月（无限档）| 部分覆盖 | API 优先；日内数据强；退市历史覆盖不如 Norgate 完整 |
| **Bloomberg / Refinitiv** | $20,000+/年 | ✅ 完整覆盖 | 机构标准；数据质量最高；对个人策略开发者成本不可行 |
| **Compustat (WRDS)** | 学术订阅 | ✅ 含基本面 | 含历史市值、财务数据；非学术账户价格不公开 |
""")

st.markdown("---")

st.subheader("使用第二数据源的潜在收益")
st.markdown("""
**① 提升结果可信度（最主要价值）**

同一策略在两套独立数据源上得出接近的 CAGR / 最大回撤 / 胜率，可以有效排除
"结果是 Tiingo 数据质量问题造成的假象"这一疑虑，使回测结论更具说服力。

**② 量化 Tiingo 已知缺陷的实际影响**

Tiingo 有两类已知数据问题（均已在引擎中打标排除）：
- **价格尖峰（5,305 个标的）**：极端异常收盘价，可能产生虚假突破信号
- **复权系数跳变（2,633 个标的）**：复权调整不连续，影响历史收益计算准确性

第二数据源可量化这两类问题对最终结果的实际影响幅度。

**③ 历史市值数据（Tiingo 缺失）**

Norgate / CSI / Compustat 均提供历史流通股数量，可以实现真正的市值过滤
（当前以 ADV > $60M 代替），这可能对标的池构成和回测结果有一定影响。
""")

st.markdown("---")

st.subheader("使用第二数据源的主要成本")
st.markdown("""
- **经济成本**：Norgate ~$300/年（最低门槛可行选项）
- **工程成本**：需重写数据下载适配层、重新构建 `tiingo_eligible_universe.csv` 等效文件、重新全量回测（约 15–20 小时机器时间）
- **维护成本**：长期维护两套数据管线，更新频率、字段格式均需同步
""")

st.markdown("---")

st.subheader("结论：当前阶段暂不必要，但值得规划")
st.info("""
**短期（策略1.0验证阶段）：无需购买**

核心理由：
1. Tiingo 已含退市标的，幸存者偏差这一最关键问题已解决；已知的价格异常已在引擎中打标排除
2. 趋势跟踪策略依赖的是**相对价格走势**（突破/ATR），对绝对价格精度要求远低于高频或套利策略，单标的数据误差对整体组合影响有限
3. 蒙特卡洛模拟和 Walk-Forward 验证已从另一角度检验了策略稳健性

**中期（策略进入实盘阶段）：值得做一次交叉验证**

建议时机：在策略1.0实盘运行满 6 个月、取得真实交易数据后，购买 **Norgate Data**（~$300/年）
重跑同一套策略，对比两套数据的 CAGR / MaxDD / 胜率差异。
若差异在 ±1pp CAGR / ±2pp MaxDD 以内，可认为 Tiingo 数据质量对结论无实质影响。
""")
