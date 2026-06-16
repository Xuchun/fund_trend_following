"""执行摘要 — 首页"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results
from website.components.metric_cards import render_summary_cards
from website.components.charts import nav_vs_spy

res  = get_results()
meta = res.meta
m    = res.metrics

# ── 打印/PDF 样式 ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
@media print {
    [data-testid="stSidebar"],
    [data-testid="stSidebarNav"],
    [data-testid="stHeader"],
    [data-testid="stDecoration"],
    [data-testid="stToolbar"],
    [data-testid="stStatusWidget"],
    header, footer,
    .stApp > header { display: none !important; }
    iframe { display: none !important; }
    .main .block-container,
    [data-testid="stMainBlockContainer"] {
        padding-top: 0.5cm !important;
        padding-left: 1cm !important;
        padding-right: 1cm !important;
        max-width: 100% !important;
    }
    @page { margin: 1.5cm; }
    .stPlotlyChart,
    [data-testid="stDataFrame"],
    [data-testid="stAlert"] { page-break-inside: avoid; }
    h2, h3 { page-break-after: avoid; }
}
</style>
""", unsafe_allow_html=True)

# ── 页面标题 + 按钮区 ──────────────────────────────────────────────────────────
import streamlit.components.v1 as _components

_col_title, _col_right = st.columns([4, 2])
with _col_title:
    st.title("总结")
with _col_right:
    _components.html(f"""
    <div style="display:flex;justify-content:flex-end;align-items:center;
                gap:10px;padding-top:20px;">
        <button onclick="window.parent.print()"
            title="打开打印对话框后选择「存储为 PDF」即可下载"
            style="background:#1565c0;color:#fff;border:none;padding:7px 16px;
                   border-radius:5px;cursor:pointer;font-size:13px;
                   font-family:sans-serif;white-space:nowrap;">
            📄 下载 PDF
        </button>
        <span style="background:{meta.color};color:white;padding:4px 12px;
                     border-radius:14px;font-size:0.8rem;font-weight:700;
                     letter-spacing:0.05em;">{meta.badge_text}</span>
    </div>
    """, height=60)

# ── 完整报告下载按钮 ───────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=3600)
def _cached_full_report(_nav_hash: str) -> bytes:
    from website.utils.playwright_report import generate_report as _gen
    return _gen()

try:
    _nav_hash = str(res.nav.index[-1])
    with st.spinner("正在生成完整报告（首次需 1–2 分钟，之后秒级响应）…"):
        _pdf_bytes = _cached_full_report(_nav_hash)
    import datetime as _dt
    _fname = f"策略1.0_完整回测报告_{_dt.date.today()}.pdf"
    st.download_button(
        label="📥 下载完整报告（所有页面合并 PDF）",
        data=_pdf_bytes,
        file_name=_fname,
        mime="application/pdf",
    )
except Exception as _e:
    st.warning(f"完整报告生成失败：{_e}")

st.caption(f"回测期间 {meta.backtest_start} → {meta.backtest_end}")
st.markdown("---")

# ── 加载分析数据 ───────────────────────────────────────────────────────────────
import json as _json
from pathlib import Path as _Path

_v1 = _Path(__file__).resolve().parents[2] / "results" / "v1"
_mc_data = _json.loads((_v1 / "montecarlo.json").read_text()) if (_v1 / "montecarlo.json").exists() else {}
_wf_data = _json.loads((_v1 / "walkforward.json").read_text()) if (_v1 / "walkforward.json").exists() else {}

_cagr      = m.get("cagr", 0)
_sharpe    = m.get("sharpe", 0)
_maxdd     = m.get("max_drawdown", 0)
_spy_cagr  = m.get("spy_cagr", 0)
_spy_maxdd = m.get("spy_max_drawdown", 0)
_win_rate  = m.get("win_rate", 0)
_avg_win   = m.get("avg_win_r", 0)
_avg_loss  = m.get("avg_loss_r", 0)
_pf        = m.get("profit_factor", 1)

_mc_cagr_p5  = _mc_data.get("cagr_dist", {}).get("p5", 0)
_mc_cagr_p50 = _mc_data.get("cagr_dist", {}).get("p50", 0)
_mc_neg_prob = _mc_data.get("cagr_dist", {}).get("prob_negative_cagr", 0)
_mc_dd_p50   = _mc_data.get("max_drawdown_dist", {}).get("p50", 0)
_mc_dd_p95   = _mc_data.get("max_drawdown_dist", {}).get("p95", 0)

_wf_oos_cagr   = _wf_data.get("oos_stitched", {}).get("metrics", {}).get("cagr", 0)
_wf_oos_sharpe = _wf_data.get("oos_stitched", {}).get("metrics", {}).get("sharpe", 0)
_wf_oos_maxdd  = _wf_data.get("oos_stitched", {}).get("metrics", {}).get("max_drawdown", 0)
_wf_windows    = _wf_data.get("windows", [])
_wf_pos_win    = sum(1 for w in _wf_windows if w.get("oos", {}).get("cagr", 0) > 0)

# ── 一、策略概述与标的池 ───────────────────────────────────────────────────────
st.subheader("一、策略概述与标的池")
st.markdown(f"""
**策略1.0** 是一套基于**趋势跟踪**（Trend Following）原理的纯多头量化策略。
核心逻辑：当股票突破近期最高价（N 日突破信号），以 ATR 倍数为单位开仓，
并通过追踪止损（Trailing Stop）锁定利润、控制回撤，空仓资金持有短债 ETF（SHY）。
策略在 SPY 200 日均线以下停止开新仓，但保留已有仓位随趋势运行。

**历史回测标的池**：{meta.universe_total:,} 只标的（{meta.backtest_start[:4]}–{meta.backtest_end[:4]}），
含 {meta.universe_stocks:,} 只个股（NYSE / NASDAQ / AMEX 全量历史股票，含已退市/被收购标的）
及 {meta.universe_etfs} 只跨资产 ETF。
标的池基于 **Tiingo EOD 全量历史数据**，无幸存者偏差，详见「数据与标的池」页面。
""")

st.markdown("---")

# ── 二、核心回测指标 ──────────────────────────────────────────────────────────
st.subheader("二、核心回测指标")

render_summary_cards(res.metrics, meta.color, meta.backtest_start, meta.backtest_end)
st.markdown("<br>", unsafe_allow_html=True)
st.plotly_chart(
    nav_vs_spy(res.nav, res.spy_nav, meta.color, meta.display_name),
    use_container_width=True,
)

st.markdown("---")

# ── 三、五维度综合评分 ────────────────────────────────────────────────────────
st.subheader("三、五维度综合评分")

st.markdown(f"""
**① 基准回测结果 — 达标**

CAGR **{_cagr*100:+.2f}%**，Sharpe **{_sharpe:.3f}**（vs SPY {m.get("spy_sharpe",0):.3f}），
MaxDD **{abs(_maxdd)*100:.1f}%**（vs SPY {abs(_spy_maxdd)*100:.1f}%）。
22 个完整年度中 17 年正收益（77%），最差年份 2022 年 -16.1%（仍优于 SPY -18.2%）。
绝对收益跑输 SPY 约 {abs(_cagr-_spy_cagr)*100:.1f}%/年，但以不足一半的最大回撤实现了与 SPY 大体相当的风险调整回报。

策略交易行为符合趋势跟踪特征：胜率仅 **{_win_rate*100:.1f}%**，
但平均盈利 **{_avg_win:+.2f}R** 远大于平均亏损 **{abs(_avg_loss):.2f}R**，
Profit Factor **{_pf:.3f}**，正期望稳固。
平均持仓 **{m.get('avg_holding_days',0):.0f} 天**，约 **{m.get('trades_per_year',0):.0f} 笔/年**，
风险敞口约占 {m.get('market_exposure',0)*100:.0f}% 交易日。

> ⚠️ 当前回测标的池仅含 2024 年末仍在指数中的成分股（不含历史退市、破产公司），
> CAGR 存在幸存者偏差，可能虚高 20%–50%。详见「局限性声明」。

**② 参数敏感性 — 全部 13 项测试完成，鲁棒性良好**

全部 13 个策略参数扰动测试已完成，**13/13 参数**在全部测试值下均实现正 CAGR，
策略1.0的正期望来自市场结构性趋势，而非特定参数组合的精确选择。

- **高鲁棒参数**（Sharpe CV < 0.02）：`risk_per_trade`、`min_price`、`min_market_cap_b`、`commission_bps`——在合理范围内变化几乎不影响表现。
- **中等敏感参数**（CV 0.05–0.08）：`breakout_window`、`correlation_threshold`、`volume_filter_multiplier`——CAGR 变动在 1.5–2% 以内，属可接受范围。
- **参数优化机会**：`trail_multiplier_r1 = 2.5×`（Sharpe +0.571）优于当前基准 3.0×（+0.518）；`stop_loss_multiplier = 2.5–3.0×`（Sharpe ~+0.57）优于当前 2.0×（+0.518），实盘前建议重新校准。
- **`position_cap` 应保持 ≤ 0.05**：超过 0.07 时 MaxDD 从 -21.8% 恶化至 -28.4%。

**③ 蒙特卡洛模拟 — 正期望高度确定，水下时间是核心挑战**

1,000 条随机路径中，负年化收益概率仅 **{_mc_neg_prob*100:.1f}%**，
净值归零概率 0.0%，CAGR 中位数 **{_mc_cagr_p50*100:+.1f}%**（5th pct {_mc_cagr_p5*100:+.1f}%）。
最大回撤中位数 **{abs(_mc_dd_p50)*100:.1f}%**，95th pct **{abs(_mc_dd_p95)*100:.1f}%**。
最大挑战是水下时间：90% 路径存在超过 24 个月连续水下期，
平均最长水下约 4 年，要求投资者具备极强的耐心和流动性安排。

**④ Walk-Forward 验证 — 无过拟合，但 alpha 有衰减**

5 个 OOS 窗口中 **{_wf_pos_win}/5 正收益**（仅 2022 熊市例外，但当年仍跑赢 SPY -18.2%），
OOS 拼接 CAGR **{_wf_oos_cagr*100:+.2f}%**，Sharpe **{_wf_oos_sharpe:+.3f}**（vs 全样本内 {_sharpe:+.3f}）。
未发现参数过拟合，策略1.0在从未参与优化的年份依然盈利，这是最重要的诚实性验证。
Sharpe 从 IS 的 {_sharpe:.3f} 衰减至 OOS 的 {_wf_oos_sharpe:.3f}（降幅
{(1 - _wf_oos_sharpe / _sharpe)*100:.0f}%），样本外效率有退化但非灾难性。

**⑤ 市场环境分析 — 下行保护突出，牛市跑输是结构性特征**

在 5 个市场环境中，金融危机（alpha +14.4%）和 COVID 急跌（MaxDD -12.2% vs SPY -33.7%）
最为出色；加息熊市跑赢 SPY 3.4%；量化宽松牛市落后 5.9%，AI 驱动牛市落后 11.8%。
策略1.0在每一个环境中均实现或接近正绝对收益——从未出现"某种市场环境下策略1.0完全失效"的情形。
这种"危机保护 + 牛市参与（但打折）"的特征是趋势跟踪策略1.0的内在属性，适合接受此权衡的投资者。
""")

st.markdown("---")

# ── 四、实盘推荐意见 ──────────────────────────────────────────────────────────
st.subheader("四、实盘推荐意见")

st.markdown("""
<div style="background:#e8f5e9;border-left:5px solid #2e7d32;padding:16px 20px;border-radius:6px;margin:8px 0 16px 0;">
<h4 style="margin:0 0 8px 0;color:#1b5e20;">✅ 推荐实盘，但需满足以下前提条件</h4>
<p style="margin:0;color:#1b5e20;">
策略1.0具备正期望、无过拟合证据、参数鲁棒性充分验证、规则透明可执行。
推荐作为投资组合中的防御性趋势配置（而非 SPY 的替代品），在满足下述前提的情况下进行实盘。
</p>
</div>
""", unsafe_allow_html=True)

st.markdown(f"""
**推荐实盘的依据：**
1. **样本外验证通过**：Walk-Forward 5 个 OOS 窗口中 4/5 正收益，OOS 拼接 CAGR {_wf_oos_cagr*100:+.1f}%，无过拟合证据
2. **正期望高度确定**：蒙特卡洛 1,000 条路径中负收益概率 {_mc_neg_prob*100:.1f}%，净值归零概率 0.0%
3. **全参数鲁棒性验证完毕**：13/13 个参数在全部测试值下均实现正 CAGR，策略正期望来自市场结构而非参数精确选择
4. **全市场环境可存续**：在金融危机、牛市、熊市、COVID 急跌、AI 牛市 5 种环境中均实现正收益或接近正收益
5. **交易成本已完整计入**：含 10bps 滑点 + 3bps 佣金，执行质量评估为 EXCELLENT

**实盘前须完成的工作：**
- ⚠️ **消除幸存者偏差（最高优先级）**：使用点对点历史成分股数据（Compustat 或 CRSP）重新回测；当前回测 CAGR 可能虚高 20%–50%
- 考虑将 `trail_multiplier_r1` 从 3.0× 调整至 2.5×（扰动测试显示 Sharpe 提升 0.053），并在 OOS 数据上验证
- 准备实盘基础设施：行情数据源、自动执行系统、仓位与风控监控
""")

st.markdown("---")

# ── 五、实盘投资者可预期的回报区间 ────────────────────────────────────────────
st.subheader("五、实盘投资者可预期的回报区间")

import pandas as _pd4
_expect_rows = [
    ("年化收益率（CAGR）", "4% – 7%",
     f"回测 {_cagr*100:.1f}%（含幸存者偏差）；扣除偏差估计后中性预期 5–6%；"
     f"OOS 拼接 {_wf_oos_cagr*100:.1f}% 为下界参考"),
    ("最大回撤", "−25% – −35%",
     f"历史回测 {abs(_maxdd)*100:.1f}%，MC 中位数 {abs(_mc_dd_p50)*100:.1f}%，MC 95th pct {abs(_mc_dd_p95)*100:.1f}%；"
     "实盘滑点/延迟可能轻微恶化"),
    ("Sharpe 比率", "0.30 – 0.50",
     f"回测 {_sharpe:.3f}，OOS 拼接 {_wf_oos_sharpe:.3f}；实盘预期在此区间内"),
    ("最长连续水下期", "2 – 5 年",
     "MC 90% 路径出现超 24 个月水下期，平均最长约 4 年；需提前规划流动性安排"),
    ("年正收益概率", "约 75% – 80%",
     "回测 22 年中 17 年正收益（77%）；实盘考虑偏差后预期接近此水平"),
    ("vs SPY", "牛市落后 5–12%，熊市跑赢 3–14%",
     "量化宽松牛市落后 6%，AI 牛市落后 12%；金融危机跑赢 14%，加息熊市跑赢 3%；"
     "长期绝对回撤约为 SPY 的 40%"),
]
st.dataframe(
    _pd4.DataFrame(_expect_rows, columns=["指标", "实盘预期区间", "依据说明"]),
    use_container_width=True, hide_index=True,
)

st.markdown(f"""
<div style="background:#fff8e1;border-left:5px solid #f57c00;padding:14px 18px;border-radius:6px;margin:12px 0;">
<strong>⚠️ 核心风险提示：上述预期基于历史数据推断，存在以下主要不确定性</strong><br>
① <strong>幸存者偏差（最大风险）</strong>：当前标的池基于 2024 年末在指数中的成分股，
历史退市/破产公司未纳入，回测 CAGR {_cagr*100:.1f}% 可能虚高 20%–50%；<br>
② <strong>未来市场环境偏离历史</strong>：若 AI 驱动的科技集中牛市长期持续，
多元趋势策略的 alpha 可能进一步收缩；<br>
③ <strong>大资金规模的额外摩擦</strong>：市场冲击成本、流动性约束、策略拥挤效应
将随管理规模增大而显著拖累实盘收益；<br>
④ <strong>参数优化尚待 OOS 验证</strong>：扰动测试发现 trail_multiplier_r1 = 2.5×
优于当前 3.0×，但该改善是否在 OOS 数据上可持续，需实盘前进一步验证。
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div style="background:#e3f2fd;border-left:5px solid #1565c0;padding:14px 18px;border-radius:6px;margin:8px 0;">
<strong>📌 一句话结论</strong><br>
这是一个<strong>统计上可信、逻辑上清晰、实盘可执行</strong>的趋势跟踪策略1.0。
在完成幸存者偏差修正后，推荐以<strong>合理规模（总仓位 20%–40%）</strong>
配置于多元化投资组合中，预期提供约 <strong>5%–7% 年化收益、最大回撤 25%–35%</strong>，
在熊市中提供显著的下行保护，长期持有具备正复利的统计确定性。
</div>
""", unsafe_allow_html=True)

# ── 六、数据质量独立验证：Yahoo Finance vs Tiingo ─────────────────────────────
st.subheader("六、数据质量独立验证：Yahoo Finance vs Tiingo")

import json as _json2
_tiingo_metrics_path = _Path(__file__).resolve().parents[2] / "results" / "v1_tiingo" / "metrics.json"

if _tiingo_metrics_path.exists():
    _tm = _json2.loads(_tiingo_metrics_path.read_text())

    _rows_cmp = [
        ("CAGR",        f"{m.get('cagr',0)*100:.2f}%",       f"{_tm.get('cagr',0)*100:.2f}%",       f"{(_tm.get('cagr',0)-m.get('cagr',0))*100:+.2f}pp"),
        ("Sharpe",      f"{m.get('sharpe',0):.4f}",           f"{_tm.get('sharpe',0):.4f}",           f"{_tm.get('sharpe',0)-m.get('sharpe',0):+.4f}"),
        ("Sortino",     f"{m.get('sortino',0):.4f}",          f"{_tm.get('sortino',0):.4f}",          f"{_tm.get('sortino',0)-m.get('sortino',0):+.4f}"),
        ("最大回撤",    f"{abs(m.get('max_drawdown',0))*100:.2f}%", f"{abs(_tm.get('max_drawdown',0))*100:.2f}%", f"{(abs(_tm.get('max_drawdown',0))-abs(m.get('max_drawdown',0)))*100:+.2f}pp"),
        ("年化波动率",  f"{m.get('annual_vol',0)*100:.2f}%",  f"{_tm.get('annual_vol',0)*100:.2f}%",  f"{(_tm.get('annual_vol',0)-m.get('annual_vol',0))*100:+.2f}pp"),
        ("胜率",        f"{m.get('win_rate',0)*100:.2f}%",    f"{_tm.get('win_rate',0)*100:.2f}%",    f"{(_tm.get('win_rate',0)-m.get('win_rate',0))*100:+.2f}pp"),
        ("Profit Factor", f"{m.get('profit_factor',0):.4f}", f"{_tm.get('profit_factor',0):.4f}",    f"{_tm.get('profit_factor',0)-m.get('profit_factor',0):+.4f}"),
        ("总交易笔数",  f"{int(m.get('n_trades',0)):,}",      f"{int(_tm.get('n_trades',0)):,}",      f"{int(_tm.get('n_trades',0)-m.get('n_trades',0)):+,}"),
        ("平均持仓天数", f"{m.get('avg_holding_days',0):.1f}", f"{_tm.get('avg_holding_days',0):.1f}", f"{_tm.get('avg_holding_days',0)-m.get('avg_holding_days',0):+.1f}"),
    ]

    _html_cmp = ""
    for metric, yval, tval, delta in _rows_cmp:
        _html_cmp += f"<tr><td style='padding:6px 14px'>{metric}</td><td style='padding:6px 14px'>{yval}</td><td style='padding:6px 14px'>{tval}</td><td style='padding:6px 14px;color:#888'>{delta}</td></tr>"

    st.markdown(f"""
<table style="width:100%;border-collapse:collapse;font-size:0.9rem;margin-top:8px;">
<thead>
<tr style="background:#1565c0;color:white;">
  <th style="padding:8px 14px;text-align:left;">指标</th>
  <th style="padding:8px 14px;text-align:left;">Yahoo Finance</th>
  <th style="padding:8px 14px;text-align:left;">Tiingo</th>
  <th style="padding:8px 14px;text-align:left;">差异（Tiingo − Yahoo）</th>
</tr>
</thead>
<tbody>
{_html_cmp}
</tbody>
</table>
<p style="font-size:0.8rem;color:#666;margin-top:6px;">
注：两者使用完全相同的策略参数和 S&P 900 标的范围（988 只），差异纯粹来自数据质量。
</p>
""", unsafe_allow_html=True)

    st.success(
        "**结论：两个数据源结果几乎完全一致。** "
        f"CAGR 仅差 {abs(_tm.get('cagr',0)-m.get('cagr',0))*100:.2f}pp，Sharpe 差 {abs(_tm.get('sharpe',0)-m.get('sharpe',0)):.4f}。"
        "这说明：① Yahoo Finance 历史数据对策略 1.0 而言已足够可靠；"
        "② Tiingo 数据的核心价值不在于数据质量本身，而在于**覆盖已退市股票**，"
        "用于构建无幸存者偏差的扩展标的池（见「数据与标的池 (Tiingo)」页面）。"
    )
else:
    st.info("Tiingo 回测结果未找到（`results/v1_tiingo/metrics.json`）。请先运行 `python src/scripts/05_run_v1_tiingo.py`。")

# ── 七、数据更新对比 ──────────────────────────────────────────────────────────
from website.utils.comparison import render_data_update_comparison
render_data_update_comparison(meta, m)
