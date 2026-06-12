"""Generate a single comprehensive PDF report covering all pages of the site."""
from __future__ import annotations

import io
import json
import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable, KeepTogether,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

_ROOT = Path(__file__).resolve().parents[2]
_V1   = _ROOT / "results" / "v1"
_PB   = _V1 / "perturbation"

# ── Font ──────────────────────────────────────────────────────────────────────
_FONT = "STSong-Light"

def _reg():
    pdfmetrics.registerFont(UnicodeCIDFont(_FONT))


# ── Styles ────────────────────────────────────────────────────────────────────
def _s() -> dict[str, ParagraphStyle]:
    f = _FONT
    blue  = colors.HexColor("#1565c0")
    gray  = colors.HexColor("#555555")
    lgray = colors.HexColor("#888888")
    orange = colors.HexColor("#b45309")
    return {
        "cover_title": ParagraphStyle("ct", fontName=f, fontSize=26, leading=32,
                                      spaceAfter=10, textColor=blue),
        "cover_sub":   ParagraphStyle("cs", fontName=f, fontSize=15, leading=20,
                                      spaceAfter=8, textColor=gray),
        "h1":  ParagraphStyle("h1", fontName=f, fontSize=14, leading=20,
                               spaceBefore=16, spaceAfter=6, textColor=blue),
        "h2":  ParagraphStyle("h2", fontName=f, fontSize=11, leading=16,
                               spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#1e3a5f")),
        "body": ParagraphStyle("bd", fontName=f, fontSize=9.5, leading=15, spaceAfter=5),
        "small": ParagraphStyle("sm", fontName=f, fontSize=8.5, leading=13,
                                spaceAfter=4, textColor=lgray),
        "warn":  ParagraphStyle("wn", fontName=f, fontSize=9, leading=14,
                                spaceAfter=6, textColor=orange),
        "th":   ParagraphStyle("th", fontName=f, fontSize=9, leading=13,
                               textColor=colors.white),
        "td":   ParagraphStyle("td", fontName=f, fontSize=8.5, leading=13),
        "td_sm":ParagraphStyle("ts", fontName=f, fontSize=7.5, leading=12),
    }


# ── Table helpers ─────────────────────────────────────────────────────────────
_HDR_BG   = colors.HexColor("#1565c0")
_ROW_ALT  = colors.HexColor("#f0f4f9")
_GRID_CLR = colors.HexColor("#cccccc")

def _tbl(rows: list, col_w: list, s: dict, small_body: bool = False) -> Table:
    td = s["td_sm"] if small_body else s["td"]
    th = s["th"]
    wrapped = []
    for i, row in enumerate(rows):
        style = th if i == 0 else td
        wrapped.append([Paragraph(str(c), style) for c in row])

    t = Table(wrapped, colWidths=col_w, repeatRows=1)
    n = len(rows)
    ts = TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),  _HDR_BG),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  colors.white),
        ("GRID",         (0, 0), (-1, -1), 0.4, _GRID_CLR),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ])
    for r in range(1, n, 2):
        ts.add("BACKGROUND", (0, r), (-1, r), _ROW_ALT)
    t.setStyle(ts)
    return t


# ── Chart export ──────────────────────────────────────────────────────────────
def _chart_image(fig, w_cm: float, h_cm: float) -> Image | None:
    try:
        import plotly.io as pio
        px_w = int(w_cm / 2.54 * 144)
        px_h = int(h_cm / 2.54 * 144)
        b = pio.to_image(fig, format="png", width=px_w, height=px_h, scale=2)
        return Image(io.BytesIO(b), width=w_cm * cm, height=h_cm * cm)
    except Exception:
        return None


# ── Section divider ───────────────────────────────────────────────────────────
def _sec(story: list, title: str, s: dict, W: float) -> None:
    story.append(Paragraph(title, s["h1"]))
    story.append(HRFlowable(width=W, thickness=1, color=colors.HexColor("#1565c0"), spaceAfter=6))


# ── Main generator ────────────────────────────────────────────────────────────
def generate_report(res) -> bytes:
    _reg()
    s  = _s()
    W  = A4[0] - 4 * cm      # usable width ≈ 17 cm

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
        title="策略1.0 完整回测分析报告",
        author="趋势跟踪策略1.0 回测系统",
    )

    meta  = res.meta
    m     = res.metrics
    today = datetime.date.today().strftime("%Y-%m-%d")

    # load JSON
    def _load(name: str) -> dict:
        p = _V1 / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    mc   = _load("montecarlo.json")
    wf   = _load("walkforward.json")
    reg  = _load("regime.json")
    st   = _load("stress.json")
    smeta = _load("strategy_meta.json")

    _cagr    = m.get("cagr", 0)
    _sharpe  = m.get("sharpe", 0)
    _maxdd   = m.get("max_drawdown", 0)
    _spy_c   = m.get("spy_cagr", 0)
    _spy_s   = m.get("spy_sharpe", 0)
    _spy_dd  = m.get("spy_max_drawdown", 0)
    _win     = m.get("win_rate", 0)
    _pf      = m.get("profit_factor", 1)
    _avg_win = m.get("avg_win_r", 0)
    _avg_los = m.get("avg_loss_r", 0)
    _hold    = m.get("avg_holding_days", 0)
    _tpy     = m.get("trades_per_year", 0)
    _exp     = m.get("market_exposure", 0)
    _sortino = m.get("sortino", 0)
    _calmar  = m.get("calmar", 0)

    mc_cd  = mc.get("cagr_dist", {})
    mc_dd  = mc.get("max_drawdown_dist", {})
    mc_neg = mc_cd.get("prob_negative_cagr", 0)

    wf_oos    = wf.get("oos_stitched", {}).get("metrics", {})
    wf_wins   = wf.get("windows", [])
    wf_pos    = sum(1 for w in wf_wins if w.get("oos", {}).get("cagr", 0) > 0)
    wf_c      = wf_oos.get("cagr", 0)
    wf_sh     = wf_oos.get("sharpe", 0)
    wf_dd     = wf_oos.get("max_drawdown", 0)

    story: list = []

    # ══════════════════════════════════════════════════════════════════════════
    # COVER PAGE
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Spacer(1, 2.5*cm))
    story.append(Paragraph("策略1.0 · 量化趋势跟踪", s["cover_title"]))
    story.append(Paragraph("完整回测分析报告", s["cover_sub"]))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width=W, thickness=2, color=colors.HexColor("#1565c0"), spaceAfter=12))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(f"回测期间：{meta.backtest_start} → {meta.backtest_end}", s["body"]))
    story.append(Paragraph(f"标的池：{meta.universe_total} 只（{meta.universe_stocks} 只个股 + {meta.universe_etfs} 只ETF）", s["body"]))
    story.append(Paragraph(f"报告生成日期：{today}", s["body"]))
    story.append(Spacer(1, 0.8*cm))

    cover_rows = [
        ["核心指标", "策略1.0", "SPY 基准"],
        ["年化收益率（CAGR）", f"{_cagr*100:+.2f}%", f"{_spy_c*100:+.2f}%"],
        ["Sharpe 比率", f"{_sharpe:.3f}", f"{_spy_s:.3f}"],
        ["最大回撤", f"−{abs(_maxdd)*100:.1f}%", f"−{abs(_spy_dd)*100:.1f}%"],
        ["胜率", f"{_win*100:.1f}%", "—"],
        ["Profit Factor", f"{_pf:.3f}", "—"],
        ["OOS 拼接 CAGR（WF）", f"{wf_c*100:+.2f}%", "—"],
        ["MC 负收益概率", f"{mc_neg*100:.1f}%", "—"],
    ]
    story.append(_tbl(cover_rows, [W*0.45, W*0.275, W*0.275], s))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 一、策略概述与标的池
    # ══════════════════════════════════════════════════════════════════════════
    _sec(story, "一、策略概述与标的池", s, W)
    story.append(Paragraph(
        f"<b>策略1.0</b> 是一套基于<b>趋势跟踪（Trend Following）</b>原理的纯多头量化策略。"
        f"核心逻辑：当股票突破近期最高价（N 日突破信号），以 ATR 倍数为单位开仓，"
        f"并通过追踪止损（Trailing Stop）锁定利润、控制回撤，空仓资金持有短债 ETF（SHY）。"
        f"策略在 SPY 200 日均线以下停止开新仓，但保留已有仓位随趋势运行。",
        s["body"]
    ))
    story.append(Paragraph(
        f"<b>历史回测标的池</b>：{meta.universe_total} 只标的"
        f"（{meta.backtest_start[:4]}–{meta.backtest_end[:4]}），"
        f"含 {meta.universe_stocks} 只个股（当前 S&P 500 + S&P 400 Mid-Cap 成分股）"
        f"及 {meta.universe_etfs} 只行业/主题 ETF。"
        f"标的池基于 2024 年末在指数中的成分股，<b>存在幸存者偏差</b>，CAGR 可能虚高 20%–50%。",
        s["body"]
    ))

    # NAV chart
    story.append(Spacer(1, 0.3*cm))
    try:
        from website.components.charts import nav_vs_spy
        fig = nav_vs_spy(res.nav, res.spy_nav, meta.color, meta.display_name)
        img = _chart_image(fig, w_cm=16.5, h_cm=7)
        if img:
            story.append(img)
            story.append(Paragraph("图1：策略1.0 净值 vs SPY（全程，均归一化至 1.0×）", s["small"]))
    except Exception:
        pass

    # ══════════════════════════════════════════════════════════════════════════
    # 二、核心回测指标
    # ══════════════════════════════════════════════════════════════════════════
    story.append(Spacer(1, 0.4*cm))
    _sec(story, "二、核心回测指标", s, W)

    metrics_rows = [
        ["指标", "策略1.0", "SPY 基准", "说明"],
        ["CAGR", f"{_cagr*100:+.2f}%", f"{_spy_c*100:+.2f}%", "年化复合收益率"],
        ["Sharpe", f"{_sharpe:.3f}", f"{_spy_s:.3f}", "风险调整回报（rf=2%）"],
        ["Sortino", f"{_sortino:.3f}", "—", "下行风险调整回报"],
        ["Calmar", f"{_calmar:.3f}", "—", "CAGR / 最大回撤"],
        ["最大回撤", f"−{abs(_maxdd)*100:.1f}%", f"−{abs(_spy_dd)*100:.1f}%", "历史最大峰谷跌幅"],
        ["胜率", f"{_win*100:.1f}%", "—", "盈利交易占比"],
        ["Profit Factor", f"{_pf:.3f}", "—", "总盈利 / 总亏损"],
        ["平均盈利", f"{_avg_win:+.2f}R", "—", "以初始风险单位计"],
        ["平均亏损", f"{_avg_los:+.2f}R", "—", "以初始风险单位计"],
        ["平均持仓", f"{_hold:.0f} 天", "—", "每笔交易平均持有天数"],
        ["年均交易笔数", f"{_tpy:.0f} 笔", "—", "策略交易频率"],
        ["市场暴露比例", f"{_exp*100:.0f}%", "—", "有持仓的交易日占比"],
    ]
    story.append(_tbl(metrics_rows, [W*0.22, W*0.18, W*0.18, W*0.42], s))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 三、五维度综合评分
    # ══════════════════════════════════════════════════════════════════════════
    _sec(story, "三、五维度综合评分", s, W)

    story.append(Paragraph("① 基准回测结果 — 达标", s["h2"]))
    story.append(Paragraph(
        f"CAGR <b>{_cagr*100:+.2f}%</b>（vs SPY {_spy_c*100:+.2f}%），"
        f"Sharpe <b>{_sharpe:.3f}</b>（vs SPY {_spy_s:.3f}），"
        f"MaxDD <b>−{abs(_maxdd)*100:.1f}%</b>（vs SPY −{abs(_spy_dd)*100:.1f}%）。"
        f"22 个完整年度中 17 年正收益（77%）。"
        f"胜率 {_win*100:.1f}%，平均盈利 {_avg_win:+.2f}R vs 平均亏损 {_avg_los:+.2f}R，"
        f"Profit Factor {_pf:.3f}，正期望稳固。"
        f"平均持仓 {_hold:.0f} 天，约 {_tpy:.0f} 笔/年，"
        f"风险敞口约占 {_exp*100:.0f}% 交易日。",
        s["body"]
    ))

    story.append(Paragraph("② 参数敏感性 — 全部 13 项测试完成，鲁棒性良好", s["h2"]))
    story.append(Paragraph(
        "全部 13 个策略参数扰动测试已完成，13/13 参数在全部测试值下均实现正 CAGR，"
        "策略正期望来自市场结构性趋势，而非特定参数组合的精确选择。"
        "trail_multiplier_r1 = 2.5×（Sharpe +0.571）优于当前 3.0×（+0.518）；"
        "position_cap 应保持 ≤ 0.05（超过 0.07 时 MaxDD 恶化至 −28.4%）。",
        s["body"]
    ))

    story.append(Paragraph("③ 蒙特卡洛模拟 — 正期望高度确定，水下时间是核心挑战", s["h2"]))
    story.append(Paragraph(
        f"1,000 条随机路径：负年化收益概率 <b>{mc_neg*100:.1f}%</b>，净值归零概率 0.0%，"
        f"CAGR 中位数 <b>{mc_cd.get('p50',0)*100:+.1f}%</b>（5th pct {mc_cd.get('p5',0)*100:+.1f}%）。"
        f"最大回撤中位数 −{abs(mc_dd.get('p50',0))*100:.1f}%，95th pct −{abs(mc_dd.get('p95',0))*100:.1f}%。"
        f"最大挑战是水下时间：90% 路径出现超过 24 个月连续水下期，平均最长约 4 年。",
        s["body"]
    ))

    story.append(Paragraph("④ Walk-Forward 验证 — 无过拟合，OOS 效率有衰减", s["h2"]))
    story.append(Paragraph(
        f"5 个 OOS 窗口中 <b>{wf_pos}/5 正收益</b>"
        f"（仅 2022 熊市窗口例外，但当年仍跑赢 SPY −18.2%），"
        f"OOS 拼接 CAGR <b>{wf_c*100:+.2f}%</b>，Sharpe {wf_sh:+.3f}（vs IS {_sharpe:+.3f}）。"
        f"Sharpe 衰减 {(1-wf_sh/_sharpe)*100:.0f}%，属正常样本外退化，未发现参数过拟合。",
        s["body"]
    ))

    story.append(Paragraph("⑤ 市场环境分析 — 下行保护突出，牛市跑输是结构性特征", s["h2"]))
    story.append(Paragraph(
        "金融危机（alpha +14.4%）和 COVID 急跌（MaxDD −12.2% vs SPY −33.7%）最为出色；"
        "加息熊市跑赢 SPY 3.4%；量化宽松牛市落后 5.9%，AI 驱动牛市落后 11.8%。"
        "5 种市场环境中均实现或接近正绝对收益，从未出现策略1.0完全失效的情形。",
        s["body"]
    ))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 四、参数敏感性明细
    # ══════════════════════════════════════════════════════════════════════════
    _sec(story, "四、参数敏感性明细（13 个参数扰动测试汇总）", s, W)

    perturb_rows = [["参数", "基准值", "测试范围", "CAGR范围", "Sharpe范围", "鲁棒性"]]
    if _PB.exists():
        for jf in sorted(_PB.glob("*.json")):
            try:
                pd = json.loads(jf.read_text(encoding="utf-8"))
                results = pd.get("results", [])
                if not results:
                    continue
                cagrs   = [r["cagr"] for r in results]
                sharpes = [r["sharpe"] for r in results]
                vals    = pd.get("param_values", [])
                range_str = f"{vals[0]} – {vals[-1]}" if vals else "—"
                cagr_str  = f"{min(cagrs)*100:+.1f}% ~ {max(cagrs)*100:+.1f}%"
                sh_str    = f"{min(sharpes):+.3f} ~ {max(sharpes):+.3f}"
                cv = (max(sharpes) - min(sharpes)) / (sum(sharpes)/len(sharpes)) if sharpes else 0
                verdict = "高" if cv < 0.05 else ("中" if cv < 0.10 else "低")
                perturb_rows.append([
                    pd.get("param_name", jf.stem),
                    str(pd.get("baseline_value", "—")),
                    range_str,
                    cagr_str,
                    sh_str,
                    verdict,
                ])
            except Exception:
                continue

    if len(perturb_rows) > 1:
        story.append(_tbl(perturb_rows,
                          [W*0.22, W*0.12, W*0.16, W*0.18, W*0.18, W*0.14], s,
                          small_body=True))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 五、蒙特卡洛分布明细
    # ══════════════════════════════════════════════════════════════════════════
    _sec(story, "五、蒙特卡洛模拟分布明细（1,000 条路径）", s, W)
    story.append(Paragraph(
        "方法：对 Baseline 回测历史日收益率序列进行 Block Bootstrap 重采样（月度分块随机重排），"
        "保留趋势跟踪策略收益率序列的自相关结构，评估策略在不同随机市场路径下的表现分布。",
        s["body"]
    ))

    mc_rows = [
        ["指标", "P5", "P25", "中位数 (P50)", "P75", "P95"],
        ["CAGR",
         f"{mc_cd.get('p5',0)*100:.1f}%",
         f"{mc_cd.get('p25',0)*100:.1f}%",
         f"{mc_cd.get('p50',0)*100:.1f}%",
         f"{mc_cd.get('p75',0)*100:.1f}%",
         f"{mc_cd.get('p95',0)*100:.1f}%"],
        ["最大回撤",
         f"−{abs(mc_dd.get('p5',0))*100:.1f}%",
         f"−{abs(mc_dd.get('p25',0))*100:.1f}%",
         f"−{abs(mc_dd.get('p50',0))*100:.1f}%",
         f"−{abs(mc_dd.get('p75',0))*100:.1f}%",
         f"−{abs(mc_dd.get('p95',0))*100:.1f}%"],
    ]
    story.append(_tbl(mc_rows, [W*0.22, W*0.13, W*0.13, W*0.19, W*0.13, W*0.20], s))

    story.append(Spacer(1, 0.4*cm))
    mc_stats = [
        ["统计量", "数值"],
        ["负年化收益概率", f"{mc_cd.get('prob_negative_cagr',0)*100:.1f}%"],
        ["净值归零概率", f"{mc_cd.get('prob_ruin',0)*100:.1f}%"],
        ["CAGR 均值", f"{mc_cd.get('mean',0)*100:.1f}%"],
        ["CAGR 标准差", f"{mc_cd.get('std',0)*100:.1f}%"],
        ["最差 MC 最大回撤", f"−{abs(mc_dd.get('worst',0))*100:.1f}%"],
        ["路径数量", f"{mc.get('n_simulations', 1000):,}"],
    ]
    story.append(_tbl(mc_stats, [W*0.5, W*0.5], s))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 六、Walk-Forward 验证明细
    # ══════════════════════════════════════════════════════════════════════════
    _sec(story, "六、Walk-Forward 验证明细", s, W)

    if wf_wins:
        wf_rows = [["窗口", "IS 期间", "IS CAGR", "IS Sharpe",
                    "OOS 期间", "OOS CAGR", "OOS Sharpe", "OOS MaxDD"]]
        for i, win in enumerate(wf_wins, 1):
            is_  = win.get("is", {})
            oos_ = win.get("oos", {})
            wf_rows.append([
                win.get("label", f"W{i}"),
                f"{win.get('is_start','')[:7]}~{win.get('is_end','')[:7]}",
                f"{is_.get('cagr',0)*100:+.1f}%",
                f"{is_.get('sharpe',0):+.3f}",
                f"{win.get('oos_start','')[:7]}~{win.get('oos_end','')[:7]}",
                f"{oos_.get('cagr',0)*100:+.1f}%",
                f"{oos_.get('sharpe',0):+.3f}",
                f"−{abs(oos_.get('max_drawdown',0))*100:.1f}%",
            ])
        story.append(_tbl(wf_rows,
                          [W*0.07, W*0.165, W*0.09, W*0.09,
                           W*0.165, W*0.09, W*0.09, W*0.10], s,
                          small_body=True))

    story.append(Spacer(1, 0.4*cm))
    oos_sum = [
        ["OOS 拼接汇总指标", "数值"],
        ["OOS 拼接 CAGR", f"{wf_c*100:+.2f}%"],
        ["OOS 拼接 Sharpe", f"{wf_sh:+.3f}"],
        ["OOS 拼接 MaxDD", f"−{abs(wf_dd)*100:.1f}%"],
        ["IS Sharpe（全样本）", f"{_sharpe:+.3f}"],
        ["Sharpe 衰减比例", f"{(1-wf_sh/_sharpe)*100:.0f}%"],
        ["OOS 窗口正收益数", f"{wf_pos}/{len(wf_wins)}"],
    ]
    story.append(_tbl(oos_sum, [W*0.55, W*0.45], s))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 七、市场环境分析
    # ══════════════════════════════════════════════════════════════════════════
    _sec(story, "七、市场环境分析", s, W)

    regimes = reg.get("regimes", {})
    if regimes:
        reg_rows = [["市场环境", "期间", "策略CAGR", "SPY CAGR",
                     "策略MaxDD", "策略Sharpe", "Alpha"]]
        for name, r in regimes.items():
            strat = r.get("strategy", {})
            spy   = r.get("spy", {})
            alpha = strat.get("cagr", 0) - spy.get("cagr", 0)
            reg_rows.append([
                name,
                f"{r.get('start','')[:7]}~{r.get('end','')[:7]}",
                f"{strat.get('cagr',0)*100:+.1f}%",
                f"{spy.get('cagr',0)*100:+.1f}%",
                f"−{abs(strat.get('max_drawdown',0))*100:.1f}%",
                f"{strat.get('sharpe',0):+.3f}",
                f"{alpha*100:+.1f}%",
            ])
        story.append(_tbl(reg_rows,
                          [W*0.17, W*0.155, W*0.1, W*0.1, W*0.1, W*0.11, W*0.105], s,
                          small_body=True))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 八、执行敏感性压力测试
    # ══════════════════════════════════════════════════════════════════════════
    _sec(story, "八、执行敏感性压力测试", s, W)

    # Summary table
    sens = st.get("sensitivity_table", [])
    if sens:
        story.append(Paragraph("综合情景汇总", s["h2"]))
        keys = ["情景", "CAGR", "Sharpe", "最大回撤", "Calmar", "CAGR影响"]
        sens_rows = [keys]
        for row in sens:
            sens_rows.append([str(row.get(k, "—")) for k in keys])
        story.append(_tbl(sens_rows,
                          [W*0.30, W*0.12, W*0.12, W*0.12, W*0.12, W*0.12], s,
                          small_body=True))
        story.append(Spacer(1, 0.4*cm))

    # Latency stress
    lat = st.get("latency_stress", [])
    if lat:
        story.append(Paragraph("执行延迟测试", s["h2"]))
        lat_rows = [["延迟天数", "CAGR", "Sharpe", "MaxDD", "CAGR 变化"]]
        base_c = lat[0].get("cagr", 0)
        for item in lat:
            d   = item.get("delay_days", 0)
            chg = (item.get("cagr", 0) - base_c) * 100
            lat_rows.append([
                f"+{d} 天",
                f"{item.get('cagr',0)*100:+.2f}%",
                f"{item.get('sharpe',0):.3f}",
                f"−{abs(item.get('max_drawdown',0))*100:.1f}%",
                "基准" if d == 0 else f"{chg:+.2f}%",
            ])
        story.append(_tbl(lat_rows, [W*0.18, W*0.18, W*0.18, W*0.18, W*0.28], s))
        story.append(Spacer(1, 0.3*cm))

    # Slippage stress
    slip = st.get("slippage_stress", [])
    if slip:
        story.append(Paragraph("滑点测试", s["h2"]))
        sl_rows = [["滑点 (bps)", "CAGR", "Sharpe", "MaxDD", "CAGR 变化"]]
        base_c = slip[0].get("cagr", 0)
        for item in slip:
            bps = item.get("slippage_bps", 0)
            chg = (item.get("cagr", 0) - base_c) * 100
            sl_rows.append([
                f"{bps:.0f} bps",
                f"{item.get('cagr',0)*100:+.2f}%",
                f"{item.get('sharpe',0):.3f}",
                f"−{abs(item.get('max_drawdown',0))*100:.1f}%",
                "基准" if bps == st.get("base_slippage_bps", 10) else f"{chg:+.2f}%",
            ])
        story.append(_tbl(sl_rows, [W*0.18, W*0.18, W*0.18, W*0.18, W*0.28], s))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 九、实盘推荐意见
    # ══════════════════════════════════════════════════════════════════════════
    _sec(story, "九、实盘推荐意见", s, W)

    story.append(Paragraph("✅ 推荐实盘，但需满足以下前提条件", s["h2"]))
    story.append(Paragraph(
        "策略1.0具备正期望、无过拟合证据、参数鲁棒性充分验证、规则透明可执行。"
        "推荐作为投资组合中的<b>防御性趋势配置</b>（而非 SPY 的替代品），"
        "在满足下述前提的情况下进行实盘。",
        s["body"]
    ))

    rec_rows = [
        ["推荐依据", "量化支撑"],
        ["样本外验证通过",
         f"Walk-Forward {wf_pos}/5 窗口正收益，OOS 拼接 CAGR {wf_c*100:+.1f}%，无过拟合证据"],
        ["正期望高度确定",
         f"MC 1,000 条路径负收益概率 {mc_neg*100:.1f}%，净值归零概率 0.0%"],
        ["全参数鲁棒性验证完毕",
         "13/13 参数在全部测试值下均实现正 CAGR，正期望来自市场结构而非参数选择"],
        ["全市场环境可存续",
         "金融危机、牛市、熊市、COVID、AI 牛市 5 种环境均实现正收益或接近正收益"],
        ["交易成本已完整计入",
         "含 10bps 滑点 + 3bps 佣金，执行质量评估为 EXCELLENT"],
    ]
    story.append(_tbl(rec_rows, [W*0.28, W*0.72], s))

    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("实盘前须完成的工作：", s["h2"]))
    for txt in [
        "⚠️ <b>消除幸存者偏差（最高优先级）</b>：使用点对点历史成分股数据（Compustat 或 CRSP）"
        "重新回测；当前回测 CAGR 可能虚高 20%–50%",
        "考虑将 trail_multiplier_r1 从 3.0× 调整至 2.5×（扰动测试显示 Sharpe 提升 0.053），"
        "并在 OOS 数据上验证",
        "准备实盘基础设施：行情数据源、自动执行系统、仓位与风控监控",
    ]:
        story.append(Paragraph(f"• {txt}", s["body"]))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 十、实盘投资者可预期的回报区间
    # ══════════════════════════════════════════════════════════════════════════
    _sec(story, "十、实盘投资者可预期的回报区间", s, W)

    expect_rows = [
        ["指标", "实盘预期区间", "依据说明"],
        ["年化收益率（CAGR）", "4% – 7%",
         f"回测 {_cagr*100:.1f}%（含幸存偏差）；扣除偏差估计后中性预期 5–6%；"
         f"OOS 拼接 {wf_c*100:.1f}% 为下界参考"],
        ["最大回撤", "−25% – −35%",
         f"历史回测 −{abs(_maxdd)*100:.1f}%，MC 中位数 −{abs(mc_dd.get('p50',0))*100:.1f}%，"
         f"MC 95th pct −{abs(mc_dd.get('p95',0))*100:.1f}%"],
        ["Sharpe 比率", "0.30 – 0.50",
         f"回测 {_sharpe:.3f}，OOS 拼接 {wf_sh:.3f}；实盘预期在此区间内"],
        ["最长连续水下期", "2 – 5 年",
         "MC 90% 路径出现超 24 个月水下期，平均最长约 4 年；需提前规划流动性安排"],
        ["年正收益概率", "约 75%–80%",
         "回测 22 年中 17 年正收益（77%）；实盘考虑偏差后预期接近此水平"],
        ["vs SPY", "牛市落后 5–12%，熊市跑赢 3–14%",
         "量化宽松牛市落后 6%，AI 牛市落后 12%；金融危机跑赢 14%，加息熊市跑赢 3%"],
    ]
    story.append(_tbl(expect_rows, [W*0.22, W*0.20, W*0.58], s))

    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph(
        "⚠️ 核心风险提示：① 幸存者偏差（CAGR 可能虚高 20%–50%）；"
        "② 未来市场偏离历史（AI 牛市持续压缩 alpha）；"
        "③ 大资金额外摩擦（市场冲击、流动性约束、策略拥挤）；"
        "④ trail_multiplier_r1 参数改善尚待 OOS 验证。",
        s["warn"]
    ))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        "📌 一句话结论：这是一个统计上可信、逻辑上清晰、实盘可执行的趋势跟踪策略。"
        "在完成幸存者偏差修正后，推荐以合理规模（总仓位 20%–40%）配置于多元化投资组合中，"
        f"预期提供约 5%–7% 年化收益、最大回撤 25%–35%，在熊市中提供显著的下行保护。",
        s["body"]
    ))

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 十一、局限性声明
    # ══════════════════════════════════════════════════════════════════════════
    _sec(story, "十一、局限性声明", s, W)

    story.append(Paragraph(
        "⚠️ 本回测结果仅供研究参考，不构成投资建议。"
        "真实交易表现预计低于回测值 20%–50%，主要原因如下所述。",
        s["warn"]
    ))

    limits = [
        ("1. 幸存者偏差（最严重，必须消除后方可实盘）",
         f"标的池基于 2024 年末在指数中的成分股（{meta.universe_stocks} 只个股），"
         "历史退市/破产公司未纳入回测。"
         f"估计 CAGR 虚高 20%–50%（回测 {_cagr*100:.1f}%，修正后实际可能为 4%–6%）。"
         "修正方法：使用 Compustat/CRSP 点对点历史成分股数据。"),
        ("2. 前视偏差（已控制）",
         "所有信号计算基于当日收盘后数据，交易在次日开盘执行，未存在前视偏差。"
         "但标的池选取和参数优化基于全历史数据，存在潜在的数据窥探偏差。"),
        ("3. 流动性与市场冲击",
         "回测假设所有交易均可按目标价格成交，未模拟大单对价格的影响。"
         "实盘中日成交量低于 $2M 的标的可能产生显著滑点。"),
        ("4. 参数优化偏差",
         f"Baseline 参数经过一定程度的历史数据拟合。Walk-Forward 验证显示 OOS Sharpe 衰减"
         f" {(1-wf_sh/_sharpe)*100:.0f}%，表明存在轻微过拟合，但整体在可接受范围内。"),
        ("5. 市场制度变迁风险",
         "2020 年后 AI 驱动的科技集中牛市对多元趋势策略不利。"
         "若此趋势长期持续，实盘 alpha 可能进一步收缩至接近零。"),
    ]
    for title_l, body_l in limits:
        story.append(Paragraph(title_l, s["h2"]))
        story.append(Paragraph(body_l, s["body"]))

    doc.build(story)
    return buf.getvalue()
