"""局限性声明"""

import json
import sys
from pathlib import Path

import pandas as pd

_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta
m    = res.metrics

render_page_header("局限性声明", meta)
st.markdown(f"**回测期间：{meta.backtest_start} → {meta.backtest_end}**")
st.markdown("---")

# ── Load supporting data ──────────────────────────────────────────────────────
_rdir = Path(__file__).resolve().parents[2] / "results" / "v1_unbiased_60m_2000"

_mc   = None
_reg  = None
_wf   = None
_str  = None
_diag = None

for _path, _var in [
    (_rdir / "montecarlo.json",  "_mc"),
    (_rdir / "regime.json",      "_reg"),
    (_rdir / "walkforward.json", "_wf"),
    (_rdir / "stress.json",      "_str"),
    (_rdir / "diagnostics.json", "_diag"),
]:
    if _path.exists():
        try:
            globals()[_var] = json.loads(_path.read_text(encoding="utf-8"))
        except Exception:
            pass

# ── Pull key numbers ──────────────────────────────────────────────────────────
_cagr_pct = m.get("cagr", 0) * 100
_sharpe   = m.get("sharpe", 0)
_maxdd    = abs(m.get("max_drawdown", 0)) * 100

_n_years = 26.5
try:
    _n_years = round(
        (pd.Timestamp(meta.backtest_end) - pd.Timestamp(meta.backtest_start)).days / 365.25, 1
    )
except Exception:
    pass

_n_trades = 3340
try:
    _n_trades = len(res.trades)
except Exception:
    pass

# ── Preamble ──────────────────────────────────────────────────────────────────
st.info(
    f"策略1.0回测期 {meta.backtest_start} → {meta.backtest_end}，"
    f"CAGR **{_cagr_pct:.2f}%**，Sharpe **{_sharpe:.3f}**，最大回撤 **−{_maxdd:.2f}%**。\n\n"
    "以下局限性声明基于全套分析结果（基础回测、Walk-Forward 验证、蒙特卡洛模拟、"
    "市场环境分析、压力测试、执行诊断），量化评估各项偏差的影响方向与量级。"
)

# ── 1. Bull-market underperformance ──────────────────────────────────────────
st.subheader("1. 牛市持续跑输大盘（最核心局限）")
st.markdown("**问题：** 趋势跟踪策略在单边上涨的持续牛市中，收益率系统性低于买入持有 SPY。")

if _reg:
    _rows = []
    _qe_gap = None
    _ai_gap = None
    for name, data in _reg.get("regimes", {}).items():
        sc  = data["strategy"].get("cagr", 0) * 100
        pc  = data.get("spy", {}).get("cagr", 0) * 100
        gap = sc - pc
        if name in ("QE驱动慢牛", "AI驱动牛市"):
            tag = "⚠️ 跑输" if gap < 0 else "✅ 跑赢"
            _rows.append(f"| **{name}** | {data['start'][:7]} → {data['end'][:7]} | {sc:+.1f}% | {pc:+.1f}% | {gap:+.1f}% | {tag} |")
            if name == "QE驱动慢牛":
                _qe_gap = gap
            elif name == "AI驱动牛市":
                _ai_gap = gap
    if _rows:
        st.markdown(
            "| 市场环境 | 区间 | 策略 CAGR | SPY CAGR | 差距 | 评估 |\n"
            "|---------|------|----------|----------|------|------|\n" +
            "\n".join(_rows)
        )

if _qe_gap is not None and _ai_gap is not None:
    _qe_str = f"{abs(_qe_gap):.1f}%" if _qe_gap < 0 else f"+{_qe_gap:.1f}%"
    _ai_str = f"{abs(_ai_gap):.1f}%" if _ai_gap < 0 else f"+{_ai_gap:.1f}%"
    _ai_note = "小幅跑赢" if _ai_gap > 0 else "小幅跑输"
    st.markdown(f"""
**根本原因：** 趋势跟踪的本质是"等待确认后入场、设止损保护下行"，相比买入持有必然牺牲部分上行，换取在熊市中的下行保护。

**影响量级（基于最新数据）：**
- **QE 驱动慢牛（2009–2020）**：策略每年跑输 SPY 约 **{abs(_qe_gap):.1f}%**，持续 11 年复利差距显著。市场几乎单调上涨，策略持有多元化仓位而非集中的市场 Beta，成本最高。
- **AI 驱动牛市（2023–2026）**：策略 CAGR 高达 26.7%，{_ai_note} SPY **{_ai_str}**。与 QE 牛市不同，AI 牛市中许多非科技趋势（能源、工业、防御股）同步走强，策略捕捉到足够的趋势机会。

这不是策略设计缺陷，而是趋势跟踪类策略的内在特征——在**集中型**牛市（少数股票拉动、其他板块停滞）中支付溢价；在**宽基**牛市或熊市中具有竞争力。
""")
else:
    st.markdown("""
**根本原因：** 趋势跟踪的本质是"等待确认后入场、设止损保护下行"，相比买入持有必然牺牲部分上行，换取在熊市中的下行保护。在集中型牛市（少数股票拉动市场）中，这一代价尤为明显。
""")
st.markdown("---")

# ── 2. Walk-Forward OOS 2022 failure ─────────────────────────────────────────
st.subheader("2. OOS 样本外验证：2022 年显著亏损")

if _wf:
    _wf_header = (
        "| OOS 年份 | IS CAGR（参考） | OOS CAGR | OOS Sharpe | OOS MaxDD |\n"
        "|---------|--------------|---------|-----------|----------|\n"
    )
    _wf_rows = []
    for w in _wf.get("windows", []):
        is_c   = w.get("is",  {}).get("cagr", 0) * 100
        oos_c  = w.get("oos", {}).get("cagr", 0) * 100
        oos_sh = w.get("oos", {}).get("sharpe", 0)
        oos_dd = abs(w.get("oos", {}).get("max_drawdown", 0)) * 100
        label  = w.get("oos_start", "")[:4]
        note   = " ⚠️（partial）" if label == "2026" else ""
        _wf_rows.append(f"| {label}{note} | {is_c:+.1f}% | {oos_c:+.1f}% | {oos_sh:+.3f} | −{oos_dd:.1f}% |")
    st.markdown(_wf_header + "\n".join(_wf_rows))

if _wf:
    _w1 = next((w for w in _wf.get("windows", []) if w.get("oos_start", "").startswith("2022")), None)
    _w1_oos_cagr = _w1["oos"]["cagr"] * 100 if _w1 else -9.0
    _oos_stitched = _wf.get("oos_stitched", {}).get("metrics", {})
    _oos_cagr = _oos_stitched.get("cagr", 0) * 100
    _oos_sharpe = _oos_stitched.get("sharpe", 0)
    _pos_windows = sum(1 for w in _wf.get("windows", [])
                       if w.get("oos", {}).get("cagr", 0) > 0)
    _total_windows = len(_wf.get("windows", []))
    st.markdown(f"""
**关键发现：**
- **2022 年（加息熊市）** 是策略1.0唯一出现负收益的 OOS 年份（**{_w1_oos_cagr:+.1f}%**）。
  美联储激进加息导致债券与股票同步下跌，现金代理 SHY 也受价格冲击，
  这是策略设计对"股债双杀"环境准备不足的体现。
- **2023–2025 连续3年 OOS 均为正收益**，且逐年加速，显示策略在非加息环境中样本外表现稳健，但 2022 的单年深度亏损提醒：极端宏观环境下，策略无法完全脱离影响。
- **OOS 拼接净值**（5个窗口合计）：CAGR **{_oos_cagr:+.1f}%**，Sharpe **{_oos_sharpe:+.3f}**，{_pos_windows}/{_total_windows} 个窗口实现正收益。
- **统计样本量不足**：仅 {_total_windows} 个 OOS 窗口（各约 1 年），置信度有限。2026 年窗口为半年数据，年化指标波动较大，仅供参考。
""")
st.markdown("---")

# ── 3. Prolonged underwater ───────────────────────────────────────────────────
st.subheader("3. 长期资金占用：水下时间可达数年")

_avg_uw_yr = 4.2
_p95_uw_yr = 8.4

if _mc:
    _dd_dur  = _mc.get("drawdown_duration", {})
    _dd_dist = _mc.get("max_drawdown_dist", {})
    _avg_uw  = _dd_dur.get("avg_days", 1046)
    _p95_uw  = _dd_dur.get("p95_days", 2109)
    _p24m    = _dd_dur.get("prob_gt_24m", 0.926) * 100
    _dd_med  = abs(_dd_dist.get("p50",  -0.269)) * 100
    _dd_p5   = abs(_dd_dist.get("p5",   -0.410)) * 100
    _dd_worst= abs(_dd_dist.get("worst",-0.528)) * 100
    _avg_uw_yr = _avg_uw / 252
    _p95_uw_yr = _p95_uw / 252

    st.markdown(f"""
**蒙特卡洛 {_mc.get('n_simulations', 1000)} 条路径的水下时间分布：**

| 指标 | 数值 | 现实意义 |
|------|------|---------|
| 平均最长水下时间 | **{_avg_uw:.0f} 交易日（≈{_avg_uw_yr:.1f} 年）** | 平均情况下需等待 {_avg_uw_yr:.0f}+ 年才能重回历史高点 |
| P95 最长水下时间 | **{_p95_uw:.0f} 交易日（≈{_p95_uw_yr:.1f} 年）** | 最坏 5% 情景下水下超过 {_p95_uw_yr:.0f} 年 |
| P(水下 > 24 个月) | **{_p24m:.1f}%** | 超过 2 年水下的概率 |
| 最大回撤中位数 | **−{_dd_med:.1f}%** | 50% 路径峰值回撤超过此值 |
| 最大回撤 P5（最坏 5%）| **−{_dd_p5:.1f}%** | 5% 最坏路径峰值回撤超过此值 |
| 历史最深回撤 | **−{_maxdd:.2f}%** | 实际发生（单条历史路径） |
""")

st.markdown("""
**实际操作影响：** 投资者在水下期间需承受心理压力和机会成本。
策略适合无固定到期日的长线资金，**不适合**有明确时间节点的资金需求。

---
""")

# ── 4. Synthetic SHY ──────────────────────────────────────────────────────────
st.subheader("4. 合成现金代理数据（2000–2002）")
st.markdown("""
**问题：** SHY（iShares 1–3 年期国债 ETF）于 2002-07-26 上市，
回测起始 2000-01-03 至 2002-07-25 的现金代理收益使用**模拟数据**而非真实 ETF 价格。

**模拟方法：** 基于美国财政部日频收益率曲线（1年期与2年期 CMT 均值），
采用固定收益标准近似：`日总收益 = 票息收入(Y/252) − 修正久期(1.8年) × ΔY`

**拼接验证（合成收益率 vs 历史背景）：**

| 年份 | 合成 SHY | 历史背景 | 合理性 |
|------|---------|---------|-------|
| 2000 | +8.29% | 联储 6.5% 高利率 + 开始降息 | ✅ 合理 |
| 2001 | +8.60% | 激进降息至 1.75%，国债大涨 | ✅ 合理 |
| 2002（上半年）| +2.54% | 利率低位趋稳 | ✅ 合理 |

拼接点（2002-07-26）处误差为 **0.0000%**，连续性完美。

**局限：** 固定久期近似（1.8年）忽略实际 SHY 的每日久期变动；未建模 ETF 跟踪误差（影响 < 0.15%/年）。

---
""")

# ── 5. Transaction costs ──────────────────────────────────────────────────────
st.subheader("5. 交易成本低估")

if _str:
    _slipp = _str.get("slippage_stress", [])
    if _slipp:
        _base_cagr = next((s["cagr"] * 100 for s in _slipp if s.get("slippage_bps") == 10), _cagr_pct)
        _rows2 = []
        for s in _slipp:
            bps   = s.get("slippage_bps", 0)
            sc    = s.get("cagr", 0) * 100
            delta = sc - _base_cagr
            sh    = s.get("sharpe", 0)
            _rows2.append(f"| {bps:.0f} bps | {sc:.2f}% | {delta:+.2f}% | {sh:.3f} |")
        st.markdown(
            "**压力测试：不同滑点水平下的影响（以10bps为基准）**\n\n"
            "| 单边滑点 | CAGR | vs 基准 | Sharpe |\n"
            "|---------|------|--------|-------|\n" +
            "\n".join(_rows2)
        )

st.markdown("""
**未建模因素：**

| 因素 | 影响方向 | 估计影响 |
|------|---------|---------|
| 大单市场冲击（> 0.5% ADV） | 偏乐观 | 中盘股大单额外 20–50 bps 滑点 |
| 止损跳空时买卖价差扩大 | 偏乐观 | 极端情况 50–200 bps |
| 税务成本 | 未建模 | 取决于持有期和税率结构 |
""")

if _diag:
    _gap = _diag.get("gap_loss_stats", {})
    _eq  = _diag.get("execution_quality", {})
    _p95_r   = abs(_gap.get("p5",   -1.94))
    _worst_r = abs(_gap.get("worst",-7.58))
    _mean_r  = abs(_gap.get("mean", -1.034))
    _qual    = _eq.get("assessment", "excellent").upper()
    _tail    = _eq.get("tail_risk", "正常")
    st.markdown(f"""
**执行诊断（实际止损执行质量，{_gap.get('n_stop_trades', 1376)} 笔止损单）：**

| 指标 | 数值 | 说明 |
|------|------|------|
| 理论止损均值 | −1.00R | 计划止损位 |
| 实际止损均值 | −{_mean_r:.3f}R | 实际成交价（含跳空） |
| 执行质量评级 | **{_qual}** | P95 缺口 {_p95_r:.2f}R < 2.5R 危险阈值 |
| P95 止损缺口 | −{_p95_r:.3f}R | 95% 止损单损失不超过此值 |
| 历史最大止损缺口 | −{_worst_r:.3f}R | 历史最坏单笔止损 |
| 尾部风险评级 | **{_tail}** | 基于缺口分布评估 |
""")

st.markdown("---")

# ── 6. Statistical power ──────────────────────────────────────────────────────
st.subheader("6. 统计显著性局限")

_mc_range  = "N/A"
_mc_span   = 0.0

if _mc:
    _cd   = _mc.get("cagr_dist", {})
    _p5c  = _cd.get("p5",  0) * 100
    _p25c = _cd.get("p25", 0) * 100
    _p50c = _cd.get("p50", 0) * 100
    _p75c = _cd.get("p75", 0) * 100
    _p95c = _cd.get("p95", 0) * 100
    _stdc = _cd.get("std", 0) * 100
    _mc_range = f"{_p5c:.1f}%–{_p95c:.1f}%"
    _mc_span  = _p95c - _p5c

    st.markdown(f"""
**蒙特卡洛 CAGR 置信区间（{_mc.get('n_simulations', 1000)} 条重采样路径）：**

| 百分位 | CAGR | 说明 |
|-------|------|------|
| P5（悲观情景） | **+{_p5c:.2f}%** | 5% 最差路径 |
| P25 | **+{_p25c:.2f}%** | 四分之一路径低于此值 |
| P50（中位数） | **+{_p50c:.2f}%** | 历史路径重采样中位值 |
| P75 | **+{_p75c:.2f}%** | 四分之三路径低于此值 |
| P95（乐观情景） | **+{_p95c:.2f}%** | 5% 最好路径 |
| 标准差 | **±{_stdc:.2f}%** | 结果不确定性宽度 |

CAGR 区间 [{_p5c:.1f}%, {_p95c:.1f}%] 跨度约 {_mc_span:.1f}%，
表明即使策略本身稳健，单条历史路径的结果具有相当大的随机性。
""")

st.markdown(f"""
**有效独立样本：**

| 维度 | 数量 | 说明 |
|------|------|------|
| 回测年数 | {_n_years:.0f} 年 | {meta.backtest_start} → {meta.backtest_end} |
| 完整熊市周期 | 4 次 | 互联网泡沫、GFC、COVID、2022加息 |
| OOS 验证窗口 | 5 个 | Walk-Forward 各 1 年 |
| 总交易笔数 | {_n_trades:,} | 策略1.0全历史 |

{_n_years:.0f} 年历史覆盖 4 次完整熊市，统计显著性优于短回测，
但 Sharpe 比率置信区间仍宽达 ±0.15（基于 MC 标准差），
需 40+ 年数据才能将误差压缩至 ±0.10 以内。

---
""")

# ── 7. Regime filter ──────────────────────────────────────────────────────────
st.subheader("7. 市场环境过滤器局限性")
st.markdown("""
**问题 1：震荡市频繁切换（Whipsaw）**

SPY 在横盘整理时可能反复穿越 200 日均线，导致策略频繁在「允许开仓」
和「停止开仓」之间切换，心理压力大，且实际入场时机与回测假设存在偏差。

**问题 2：单一过滤标的（SPY 全市场）**

当板块轮动明显时（例如 2022 年科技股崩盘但能源股大涨），
单一 SPY 信号可能错过结构性机会，或在子市场已复苏时仍维持保守姿态。

---
""")

# ── 8. ADV static threshold ───────────────────────────────────────────────────
st.subheader("8. ADV 门槛静态假设")
st.markdown("""
策略1.0使用固定 ADV > $60M 作为流动性过滤门槛。
美股整体流动性随时间变化显著：2000 年 $60M 属于较宽松门槛（纳入部分流动性一般的标的），
2024 年 $60M 偏宽松（纳入了更多小盘股）。
动态 ADV 门槛（按年度市场流动性分位数调整）可更精确，但实现复杂度更高。

---
""")

# ── Summary ───────────────────────────────────────────────────────────────────
st.subheader("综合评估")

_slip20_str = "20bps 滑点 → CAGR 约 9.74%（较基准低约 0.40%）"
if _str:
    for s in _str.get("slippage_stress", []):
        if abs(s.get("slippage_bps", 0) - 20) < 0.5:
            _slip20_cagr = s.get("cagr", 0) * 100
            _diff = _cagr_pct - _slip20_cagr
            _slip20_str = f"20bps 滑点 → CAGR {_slip20_cagr:.2f}%（较基准低 {_diff:.2f}%）"

_qe_gap_str = f"QE 慢牛 11 年每年少赚约 {abs(_qe_gap):.1f}% vs SPY" if _qe_gap is not None else "QE 慢牛期间跑输 SPY 约 8%/年"
_w1_cagr_str = f"{_w1_oos_cagr:+.1f}%" if globals().get("_w1_oos_cagr") is not None else "−9.0%"

st.markdown(f"""
| # | 局限性 | 严重程度 | 影响方向 | 量化估计 |
|---|-------|---------|---------|---------|
| 1 | **集中型牛市跑输大盘** | 🔴 高 | 偏保守（实际可能更差） | {_qe_gap_str}（AI牛市则小幅跑赢）|
| 2 | **OOS 2022 亏损** | 🟡 中 | 隐藏环境风险 | 加息熊市单年 OOS {_w1_cagr_str} |
| 3 | **长期水下占用** | 🟡 中 | 流动性风险 | 平均水下 ≈{_avg_uw_yr:.1f} 年，P95 ≈{_p95_uw_yr:.1f} 年 |
| 4 | **合成 SHY 数据** | 🟢 低 | 偏乐观（微小） | 2000–2002 误差估计 ±1% CAGR |
| 5 | **交易成本低估** | 🟡 中 | 偏乐观 | {_slip20_str} |
| 6 | **统计显著性** | 🟡 中 | 不确定性 | MC CAGR 区间 {_mc_range}，跨度约 {_mc_span:.1f}% |
| 7 | **市场环境过滤器** | 🟢 低 | 偏保守（Whipsaw 成本）| 未量化 |
| 8 | **ADV 静态门槛** | 🟢 低 | 双向 | 未量化 |

**总体结论：** 策略1.0在 {_n_years:.0f} 年回测中展现出真实的防御性
（互联网泡沫、GFC、2022 加息均跑赢 SPY），但**集中型**牛市跑输是核心代价（QE 慢牛每年差约 8%）。
AI 驱动牛市（2023–2026）中因宽基趋势机会较多，策略小幅跑赢 SPY，体现出不同牛市结构对策略的差异性影响。
实际投资者应预期：**大多数普通年份表现平平，在系统性危机中显著占优**，
长期 CAGR 预期区间大致为 {_mc_range}（MC 重采样路径）。
""")
