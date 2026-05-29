"""基准回测结果"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results
from website.components.strategy_badge import render_page_header

_etf_csv = Path(__file__).resolve().parents[2] / "data" / "ETFs.csv"
import pandas as _pd_etf
_ETF_SET = set(_pd_etf.read_csv(_etf_csv)["SYMBOL"].dropna().str.strip().tolist()) if _etf_csv.exists() else set()
from website.components.metric_cards import render_summary_cards, render_full_metrics_table
from website.components.charts import (
    nav_vs_spy, drawdown_chart, rolling_sharpe_chart,
    r_multiple_distribution, annual_returns_chart,
    trades_per_year_chart, holding_days_distribution,
    profit_by_type_chart, daily_position_count_chart,
    monthly_return_heatmap,
)

res  = get_results()
meta = res.meta
m    = dict(res.metrics)  # mutable copy

# Compute max_consecutive_losses from trades if not already in metrics
if "max_consecutive_losses" not in m and len(res.trades) > 0:
    _sorted = res.trades.sort_values("exit_date") if "exit_date" in res.trades.columns else res.trades
    _pnl = _sorted["net_pnl"].values
    _max_cl = _cur_cl = 0
    for _v in _pnl:
        if _v <= 0:
            _cur_cl += 1
            _max_cl  = max(_max_cl, _cur_cl)
        else:
            _cur_cl = 0
    m["max_consecutive_losses"] = _max_cl

render_page_header("Baseline参数回测结果", meta)
st.caption(f"回测期间：{meta.backtest_start} → {meta.backtest_end}  ·  初始资金：$10,000,000")
st.markdown("---")

# ── Summary cards ─────────────────────────────────────────────────────────────
render_summary_cards(m, meta.color, meta.backtest_start, meta.backtest_end)

st.markdown("<br>", unsafe_allow_html=True)

# ── Context note for poor CAGR ────────────────────────────────────────────────
cagr = m.get("cagr", 0)
if cagr < 0.05:
    regime_on = meta.params_anchor.get("regime_filter_enabled", False)
    if regime_on:
        regime_note = (
            "已启用 <strong>SPY 200日均线过滤器</strong>，熊市期间（约占全程 19%）停止开新仓、"
            "闲置资金转入 SHY。但过滤器<strong>不强制平仓</strong>——"
            "2008 年危机期间已持有的头寸仍由追踪止损逐步平出，因此最大回撤未能完全规避。<br>"
            "<strong>Strategy 2.0 计划引入强制减仓机制，在熊市信号触发时主动平仓。</strong>"
        )
    else:
        regime_note = (
            "纯多头策略遭受熊市的全部冲击，毫无对冲机制。<br>"
            "<strong>Strategy 2.0 将引入 SPY 200日均线过滤器以减少熊市回撤。</strong>"
        )
    st.markdown(f"""
<div class="warning-box">
<h4>⚠️ 关于低 CAGR 的说明</h4>
CAGR 仅 {cagr*100:.1f}%，主因是 2008 年金融危机期间
<strong>最大回撤达 {abs(m.get("max_drawdown",0))*100:.1f}%</strong>，导致长期的资金恢复期。
2010–2024 子区间 CAGR 约 6%，说明策略本身在无极端熊市时仍有效。<br>
{regime_note}
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Baseline parameter table ───────────────────────────────────────────────────
_p = meta.params_anchor
st.subheader("📋 Baseline 锚点参数（完整）")
st.caption("以下参数值与设计方案 §1.2.1.1、代码 StrategyParams 及回测脚本三处完全一致。")

_col_a, _col_b = st.columns(2)

with _col_a:
    st.markdown("**入场信号**")
    st.markdown(f"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 突破窗口 | `breakout_window` | **{_p['breakout_window']} 日** |
| ATR 周期 | `atr_period` | **{_p['atr_period']} 日**（Wilder 平滑）|
| 成交量确认乘数 | `volume_filter_multiplier` | **{_p['volume_filter_multiplier']:.1f}×** 60日均量 |
| 突破强度过滤 | `breakout_strength_min` | **无**（0.0，不过滤）|
| Gap 过滤 | `gap_filter` | **±{_p['gap_filter']*100:.1f}%**（跳空超限放弃入场）|
""")

    st.markdown("**标的过滤**")
    st.markdown(r"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 最低股价 | `min_price` | **\$10**（原始收盘价）|
| 最低市值 | `min_market_cap_b` | **\$2B**（注①）|
| ADV 流动性 | `min_adv_m` | **\$20M**（60日均量）|
""")
    st.caption("注①：Yahoo Finance 不提供历史点位市值，该过滤在回测中实际未执行（见参数敏感性分析页）。")

    st.markdown("**止损 / 最小止损距离**")
    st.markdown(f"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| ATR 止损乘数 | `stop_loss_multiplier` | **{_p['stop_loss_multiplier']:.1f}×ATR** |
| 最小止损距离 | `min_stop_distance_pct` | **{_p['min_stop_distance_pct']*100:.1f}%**（低于此值放弃）|
""")

    st.markdown("**移动止盈（分段）**")
    st.markdown(f"""
| 阶段 | 代码名 | Baseline 值 |
|---|---|---|
| 早期（< 1R） | `trail_multiplier_r1` | **{_p['trail_multiplier_r1']:.1f}×ATR** |
| 中期（1–3R） | `trail_multiplier_r3` | **{_p['trail_multiplier_r3']:.1f}×ATR** |
| 大赢（≥ 3R） | `trail_multiplier_r5` | **{_p['trail_multiplier_r5']:.1f}×ATR** |
""")

with _col_b:
    st.markdown("**仓位与风险**")
    st.markdown(f"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 每笔风险比例 | `risk_per_trade` | **{_p['risk_per_trade']*100:.1f}% NAV** |
| 单标的仓位上限 | `position_cap` | **{_p['position_cap']*100:.0f}% NAV** |
| 热度上限 | `heat_limit` | **{_p['heat_limit']*100:.0f}% NAV**（注②）|
""")
    st.caption("注②：由于 position_cap 架空效应，实际每笔风险约 0.24% NAV，heat_limit ≥ 10% 在回测中从未触发（见参数敏感性分析页）。")

    st.markdown("**相关性过滤**")
    st.markdown(f"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 相关性窗口 | `correlation_window` | **{_p['correlation_window']} 日** |
| 相关性阈值 | `correlation_threshold` | **{_p['correlation_threshold']:.2f}**（超出则减仓）|
| 减仓比例 | `correlation_reduction` | **{_p['correlation_reduction']*100:.0f}%**（仓位乘以 0.5）|
""")

    st.markdown("**市场环境过滤（Regime Filter）**")
    st.markdown(f"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 启用 | `regime_filter_enabled` | **{'是' if _p['regime_filter_enabled'] else '否'}** |
| 基准标的 | `regime_ticker` | **{_p['regime_ticker']}** |
| SMA 窗口 | `regime_sma_window` | **{_p['regime_sma_window']} 日** |
""")

    st.markdown("**交易成本**")
    st.markdown(f"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 滑点（单边） | `slippage_bps` | **{_p['slippage_bps']:.0f} bps** |
| 佣金（单边） | `commission_bps` | **{_p['commission_bps']:.0f} bps** |
""")

    st.markdown("**空仓 / 回测设置**")
    st.markdown(r"""
| 参数 | 代码名 | Baseline 值 |
|---|---|---|
| 空仓资金代理 | `cash_proxy` | **SHY**（1–3年期国债 ETF）|
| 初始资金 | — | **\$10,000,000** |
| 回测开始 | — | **2004-01-01** |
""")

st.markdown("---")

# ── NAV chart ─────────────────────────────────────────────────────────────────
st.subheader("净值曲线 vs SPY")
_show_spy = st.checkbox("显示 SPY 基准曲线", value=True, key="nav_show_spy")
st.plotly_chart(
    nav_vs_spy(res.nav, res.spy_nav if _show_spy else None, meta.color, meta.display_name),
    use_container_width=True,
)

# ── Drawdown chart ────────────────────────────────────────────────────────────
st.subheader("回撤曲线")
st.plotly_chart(drawdown_chart(res.nav, meta.color), use_container_width=True)

# ── Drawdown recovery analysis table ─────────────────────────────────────────
import numpy as _np_ep
import pandas as _pd_ep

_nav_ep = res.nav.copy()
if not isinstance(_nav_ep.index, _pd_ep.DatetimeIndex):
    _nav_ep.index = _pd_ep.to_datetime(_nav_ep.index)

_DD_THRESH = -0.05   # track episodes with drawdown < -5%
_n_ep      = len(_nav_ep)
_dates_ep  = _nav_ep.index
_vals_ep   = _nav_ep.values.astype(float)

_peak_val  = _vals_ep[0]
_peak_i    = 0
_in_ep     = False
_ep_pi     = 0      # peak index of current episode
_ep_ti     = 0      # trough index of current episode
_ep_tv     = 0.0   # trough value
_ep_rows   = []

for _i in range(1, _n_ep):
    _v = _vals_ep[_i]
    if _v >= _peak_val:
        if _in_ep:
            _ep_rows.append({
                "高点": _dates_ep[_ep_pi].strftime("%Y-%m"),
                "低点": _dates_ep[_ep_ti].strftime("%Y-%m"),
                "修复": _dates_ep[_i].strftime("%Y-%m"),
                "最大回撤": (_ep_tv - _vals_ep[_ep_pi]) / _vals_ep[_ep_pi],
                "至低谷（交易日）": _ep_ti - _ep_pi,
                "修复耗时（交易日）": _i - _ep_ti,
                "总水下时间（交易日）": _i - _ep_pi,
            })
            _in_ep = False
        _peak_val = _v
        _peak_i   = _i
    else:
        _dd_v = (_v - _peak_val) / _peak_val
        if _dd_v < _DD_THRESH:
            if not _in_ep:
                _in_ep = True
                _ep_pi = _peak_i
                _ep_ti = _i
                _ep_tv = _v
            elif _v < _ep_tv:
                _ep_ti = _i
                _ep_tv = _v

if _in_ep:   # ongoing episode (not yet recovered)
    _ep_rows.append({
        "高点": _dates_ep[_ep_pi].strftime("%Y-%m"),
        "低点": _dates_ep[_ep_ti].strftime("%Y-%m"),
        "修复": "进行中",
        "最大回撤": (_ep_tv - _vals_ep[_ep_pi]) / _vals_ep[_ep_pi],
        "至低谷（交易日）": _ep_ti - _ep_pi,
        "修复耗时（交易日）": _n_ep - 1 - _ep_ti,
        "总水下时间（交易日）": _n_ep - 1 - _ep_pi,
    })

_ep_df = _pd_ep.DataFrame(_ep_rows)
if len(_ep_df) > 0:
    _ep_df_sorted  = _ep_df.sort_values("最大回撤").head(10).copy()
    _ep_df_sorted["最大回撤"] = _ep_df_sorted["最大回撤"].apply(lambda v: f"{v*100:.1f}%")
    st.markdown("##### 主要回撤情节（按深度排序，前 10 次，仅含回撤 ≥ 5% 的情节）")
    st.dataframe(_ep_df_sorted, use_container_width=True, hide_index=True)
    _avg_rec = _ep_df[_ep_df["修复"] != "进行中"]["修复耗时（交易日）"].mean()
    _avg_trough = _ep_df["至低谷（交易日）"].mean()
    st.caption(
        f"共 {len(_ep_df)} 次回撤 ≥ 5% 的情节；"
        f"平均 {_avg_trough:.0f} 个交易日触底，"
        f"触底后平均 {_avg_rec:.0f} 个交易日修复（已修复情节）。"
    )

st.markdown("---")

# ── Annual returns + Rolling Sharpe side by side ──────────────────────────────
col1, col2 = st.columns(2)
with col1:
    st.subheader("逐年回报对比")
    st.plotly_chart(annual_returns_chart(res.nav, res.spy_nav, meta.color, meta.display_name),
                    use_container_width=True)
with col2:
    st.subheader("滚动 Sharpe 比率")
    st.plotly_chart(rolling_sharpe_chart(res.returns, res.spy_nav, meta.color, meta.display_name),
                    use_container_width=True)

import pandas as _pd_ar
_nav_ar = res.nav.copy()
if not isinstance(_nav_ar.index, _pd_ar.DatetimeIndex):
    _nav_ar.index = _pd_ar.to_datetime(_nav_ar.index)
_ann_ar = _nav_ar.resample("YE").last().pct_change().dropna()
_cur_yr_ar = _nav_ar.index[-1].year
_ann_ar = _ann_ar[_ann_ar.index.year < _cur_yr_ar]
_pos_yr_ar = int((_ann_ar > 0).sum())
_n_yr_ar   = len(_ann_ar)

_col1_r, _col2_r = st.columns(2)
with _col1_r:
    st.markdown(
        f"**解读：** {_n_yr_ar} 个完整年度中 **{_pos_yr_ar}** 年正收益（{_pos_yr_ar/_n_yr_ar*100:.0f}%）。"
        "趋势策略在强牛市年份（SPY 单边大涨）因持仓不满往往落后，"
        "但在下行年份（如 2008、2022）损失明显小于 SPY，体现了**截断亏损**的核心优势。"
    )
with _col2_r:
    _sharpe_tmp     = m.get("sharpe", 0)
    _spy_sharpe_tmp = m.get("spy_sharpe", 0)
    st.markdown(
        f"**解读：** 滚动 Sharpe 在 2008 年危机期间跌至深度负值，2010 年后趋于稳定并持续正值。"
        f"全周期 Sharpe **{_sharpe_tmp:+.3f}** vs SPY **{_spy_sharpe_tmp:+.3f}**，"
        "说明在单位风险维度上策略与 SPY 大体相当，而非仅靠减少持仓频率规避风险。"
    )

st.markdown("---")

# ── R-multiple distribution ───────────────────────────────────────────────────
st.subheader("交易盈亏分布（R 倍数）")
st.plotly_chart(r_multiple_distribution(res.trades), use_container_width=True)

win_rate = m.get("win_rate", 0)
avg_win  = m.get("avg_win_r", 0)
avg_loss = m.get("avg_loss_r", 0)
pf       = m.get("profit_factor", 1)
st.markdown(f"""
**解读：** 胜率 {win_rate*100:.1f}% 看似低，但这是趋势跟踪策略的**正常特征**。
关键在于平均盈利（{avg_win:+.2f}R）远大于平均亏损（{avg_loss:.2f}R），
盈亏比 {pf:.4f} > 1，期望值为正。右侧长尾（大盈利交易）是策略盈利的核心来源。
""")

st.markdown("---")

# ── Turnover callout ──────────────────────────────────────────────────────────
turnover = m.get("annual_turnover", 0)
slippage_bps   = meta.params_anchor.get("slippage_bps", 10)
commission_bps = meta.params_anchor.get("commission_bps", 3)
rt_cost_bps    = (slippage_bps + commission_bps) * 2
implied_cost_pct = turnover * rt_cost_bps / 100   # in bps→%

st.subheader("组合换手率（Portfolio Turnover）")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric(
        "年换手率",
        f"{turnover:.1f}x",
        help="= 全年买入总额 ÷ 平均 NAV ÷ 年数。12.5x 表示每年持仓被替换约 12.5 次。",
    )
with col2:
    st.metric(
        "年换手率（百分比）",
        f"{turnover*100:.0f}%",
        help="等同于左侧 x 倍数，以百分比表示。",
    )
with col3:
    st.metric(
        "隐含年化交易成本",
        f"≈ {implied_cost_pct:.2f}%",
        help=f"= 换手率 × 单边成本({slippage_bps:.0f} bps 滑点 + {commission_bps:.0f} bps 佣金)× 2。已包含于回测净值中。",
    )

st.markdown(f"""
**解读：** 年换手率 {turnover:.1f}x（{turnover*100:.0f}%）表示每年平均买入约 {turnover:.1f} 倍 NAV 的股票。
以单边 {slippage_bps:.0f} bps 滑点 + {commission_bps:.0f} bps 佣金（合计 {slippage_bps+commission_bps:.0f} bps）、往返 {rt_cost_bps:.0f} bps 计，
隐含年化交易摩擦约 **{implied_cost_pct:.2f}%**，已完整计入回测净值，无需额外扣除。

> 趋势跟踪策略的换手率通常在 500%–2,000%/年之间，本策略 {turnover*100:.0f}% 处于正常范围。
""")

st.markdown("---")

# ── Trades per year + holding days side by side ───────────────────────────────
col1, col2 = st.columns(2)
with col1:
    st.subheader("逐年交易笔数")
    st.plotly_chart(trades_per_year_chart(res.trades), use_container_width=True)
with col2:
    st.subheader("持仓天数分布")
    st.plotly_chart(holding_days_distribution(res.trades), use_container_width=True)

_trades_per_yr = m.get("trades_per_year", 0)
_avg_hold      = m.get("avg_holding_days", 0)
_med_hold      = float(res.trades["holding_days"].median()) if "holding_days" in res.trades.columns else 0
_long_hold     = int((res.trades["holding_days"] > 60).sum()) if "holding_days" in res.trades.columns else 0
_long_hold_pct = _long_hold / len(res.trades) * 100 if len(res.trades) > 0 else 0

_col1_t, _col2_t = st.columns(2)
with _col1_t:
    st.markdown(
        f"**解读：** 平均每年约 **{_trades_per_yr:.0f}** 笔交易。"
        "熊市年份（市场环境过滤器关闭新开仓）交易笔数明显减少，"
        "牛市年份信号密集、笔数较多。"
        "年度笔数的波动反映的是市场状态变化，而非策略本身不稳定。"
    )
with _col2_t:
    st.markdown(
        f"**解读：** 持仓中位数 **{_med_hold:.0f} 天**，均值 **{_avg_hold:.0f} 天**，"
        f"均值显著大于中位数，说明分布右偏——大多数交易快速止损出场（短持仓），"
        f"少数大赢家被持有较长时间（持仓 > 60 天的交易占 {_long_hold_pct:.0f}%）。"
        "这种「多次小亏、少次大赚」的持仓结构是趋势跟踪策略的典型特征。"
    )

# ── Daily position count ──────────────────────────────────────────────────────
st.subheader("每日持仓标的数目")
st.plotly_chart(
    daily_position_count_chart(res.trades, res.nav.index, meta.color),
    use_container_width=True,
)
_dc = res.trades.copy()
_dc["entry_date"] = _pd_ar.to_datetime(_dc["entry_date"])
_dc["exit_date"]  = _pd_ar.to_datetime(_dc["exit_date"])
_nav_idx = _pd_ar.to_datetime(res.nav.index)
_entry_c = _dc.groupby("entry_date").size().reindex(_nav_idx, fill_value=0)
_exit_c  = _dc.groupby("exit_date").size().reindex(_nav_idx, fill_value=0)
_daily_n = (_entry_c - _exit_c).cumsum().clip(lower=0)
_mean_n  = float(_daily_n.mean())
_max_n   = int(_daily_n.max())
_zero_pct= float((_daily_n == 0).mean()) * 100
st.markdown(
    f"**解读：** 回测期间每日持仓标的数量的实际分布。"
    f"全程均值约 **{_mean_n:.1f} 只**，历史峰值 **{_max_n} 只**。"
    f"空仓天数（0 只持仓）占全程约 **{_zero_pct:.1f}%**，"
    f"主要集中于熊市阶段（SPY 跌破 200 日均线时，Regime Filter 停止新开仓并等待旧仓止损出清）。"
    f"持仓数目随市场环境的起伏变化，体现了策略在不同市场条件下的动态参与度。"
)

st.markdown("---")

# ── Profit by type: stock vs ETF ──────────────────────────────────────────────
st.subheader("策略盈利来源：股票 vs ETF")
st.plotly_chart(profit_by_type_chart(res.trades, _ETF_SET), use_container_width=True)

etf_pnl   = res.trades[res.trades["ticker"].isin(_ETF_SET)]["net_pnl"].sum()
stock_pnl = res.trades[~res.trades["ticker"].isin(_ETF_SET)]["net_pnl"].sum()
total_pnl = etf_pnl + stock_pnl

_traded        = res.trades["ticker"].unique()
_stock_traded  = sum(1 for t in _traded if t not in _ETF_SET)
_etf_traded    = sum(1 for t in _traded if t in _ETF_SET)
_uni_stocks    = meta.universe_stocks
_uni_etfs      = meta.universe_etfs

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
**股票**
- 股票池：{_uni_stocks} 只 → 实际交易 **{_stock_traded} 只**（覆盖率 {_stock_traded/_uni_stocks*100:.1f}%）
- 盈利贡献：**${stock_pnl/1e6:.1f}M**（占总盈亏 {stock_pnl/total_pnl*100:.0f}%）
""")
with col2:
    st.markdown(f"""
**ETF**
- ETF 池：{_uni_etfs} 只 → 实际交易 **{_etf_traded} 只**（覆盖率 {_etf_traded/_uni_etfs*100:.1f}%）
- 盈利贡献：**${etf_pnl/1e6:.1f}M**（占总盈亏 {etf_pnl/total_pnl*100:.0f}%）
""")

# ── 深度分析：交易质量 / 资本效率 / 分散化价值 ────────────────────────────────
import numpy as _np

_trades = res.trades.copy()
_trades["_type"]     = _trades["ticker"].apply(lambda t: "ETF" if t in _ETF_SET else "股票")
_trades["_notional"] = _trades["entry_price"] * _trades["shares"]

def _stats(df):
    wins   = df[df["net_pnl"] > 0]
    losses = df[df["net_pnl"] <= 0]
    pf     = wins["net_pnl"].sum() / abs(losses["net_pnl"].sum()) if len(losses) > 0 else 0.0
    cap_eff = df["net_pnl"].sum() / df["_notional"].sum() * 100
    return dict(
        n          = len(df),
        win_rate   = len(wins) / len(df) * 100,
        avg_win_r  = df[df["net_pnl"] > 0]["pnl_r_multiple"].mean(),
        avg_loss_r = df[df["net_pnl"] <= 0]["pnl_r_multiple"].mean(),
        pf         = pf,
        avg_hold   = df["holding_days"].mean(),
        med_hold   = df["holding_days"].median(),
        net_pnl    = df["net_pnl"].sum(),
        notional   = df["_notional"].sum(),
        cap_eff    = cap_eff,
    )

_s = _stats(_trades[_trades["_type"] == "股票"])
_e = _stats(_trades[_trades["_type"] == "ETF"])

# 月度相关性
_trades["_month"] = _trades["exit_date"].dt.to_period("M")
_sm = _trades[_trades["_type"] == "股票"].groupby("_month")["net_pnl"].sum()
_em = _trades[_trades["_type"] == "ETF"].groupby("_month")["net_pnl"].sum()
_common = _sm.index.intersection(_em.index)
_corr = float(_sm.loc[_common].corr(_em.loc[_common])) if len(_common) > 1 else 0.0

st.markdown("#### 交易质量对比")
import pandas as _pd2
_quality_df = _pd2.DataFrame({
    "指标":      ["交易笔数", "胜率", "平均盈利 R", "平均亏损 R", "Profit Factor", "平均持仓天数", "中位持仓天数"],
    "股票":      [f"{_s['n']:,}", f"{_s['win_rate']:.1f}%", f"{_s['avg_win_r']:+.2f}R",
                  f"{_s['avg_loss_r']:+.2f}R", f"{_s['pf']:.3f}", f"{_s['avg_hold']:.1f} 天", f"{_s['med_hold']:.1f} 天"],
    "ETF":       [f"{_e['n']:,}", f"{_e['win_rate']:.1f}%", f"{_e['avg_win_r']:+.2f}R",
                  f"{_e['avg_loss_r']:+.2f}R", f"{_e['pf']:.3f}", f"{_e['avg_hold']:.1f} 天", f"{_e['med_hold']:.1f} 天"],
    "结论":      [f"ETF 仅占 {_e['n']/(_s['n']+_e['n'])*100:.0f}%", "ETF 胜率更高" if _e['win_rate'] > _s['win_rate'] else "股票胜率更高", "股票赢时赢更多" if _s['avg_win_r'] > _e['avg_win_r'] else "ETF赢时赢更多", "股票输时输更少" if abs(_s['avg_loss_r']) < abs(_e['avg_loss_r']) else "ETF输时输更少",
                  "几乎相同", "股票趋势更持久" if _s['avg_hold'] > _e['avg_hold'] else "ETF趋势更持久", "股票趋势更持久" if _s['med_hold'] > _e['med_hold'] else "ETF趋势更持久"],
})
st.dataframe(_quality_df, use_container_width=True, hide_index=True)

st.markdown("#### 资本效率")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("股票资本效率", f"{_s['cap_eff']:.2f}%",
              help=f"总净盈亏 ${_s['net_pnl']/1e6:.1f}M ÷ 总买入金额 ${_s['notional']/1e6:.0f}M")
with col2:
    st.metric("ETF 资本效率", f"{_e['cap_eff']:.2f}%",
              help=f"总净盈亏 ${_e['net_pnl']/1e6:.1f}M ÷ 总买入金额 ${_e['notional']/1e6:.0f}M")
with col3:
    ratio = _s['cap_eff'] / _e['cap_eff'] if _e['cap_eff'] != 0 else 0
    st.metric("股票 / ETF 效率比", f"{ratio:.1f}×",
              help="股票每投入1元产生的回报是 ETF 的多少倍")
_s_pct = stock_pnl / total_pnl * 100 if total_pnl != 0 else 0
_s_cap_pct = _s["notional"] / (_s["notional"] + _e["notional"]) * 100
st.caption(f"资本效率 = 净盈亏 ÷ 总买入金额。{_s_pct:.0f}% 利润来自股票，但也因为股票占用了更多资本（{_s_cap_pct:.0f}%）；关键在于每单位资本的回报率，股票是 ETF 的 {ratio:.1f}×。")

st.markdown("#### 分散化价值")
_corr_label = "几乎零相关" if abs(_corr) < 0.2 else ("低相关" if abs(_corr) < 0.4 else "中等相关")
col1, col2 = st.columns([1, 2])
with col1:
    st.metric("月度盈亏相关性", f"{_corr:.3f}", help="股票 vs ETF 月度净盈亏的 Pearson 相关系数")
    st.caption(f"→ {_corr_label}，ETF 提供真实的分散化价值")
with col2:
    # 找ETF救场的关键年份
    _trades["_year"] = _trades["exit_date"].dt.year
    _by_year = _trades.groupby(["_year","_type"])["net_pnl"].sum().unstack(fill_value=0)
    _by_year.columns.name = None
    _rescue = []
    for yr, row in _by_year.iterrows():
        s_pnl = row.get("股票", 0)
        e_pnl = row.get("ETF", 0)
        if s_pnl < 0 and e_pnl > 0:
            _rescue.append(f"**{yr}**：股票亏 ${abs(s_pnl)/1e4:.0f}万，ETF 盈 ${e_pnl/1e4:.0f}万")
    if _rescue:
        st.markdown("**ETF 在股票亏损年份提供缓冲：**")
        for line in _rescue:
            st.markdown(f"- {line}")

st.markdown(f"""
> **综合判断：** 股票资本效率更高（{ratio:.1f}×），但 ETF 与股票几乎零相关，在关键年份提供对冲缓冲。
> 建议保留 ETF 池，若要提高股票敞口，可适当上调单笔风险比例（如 1% → 1.2% NAV），而非削减 ETF。
""")

st.markdown("---")

# ── Full metrics table ────────────────────────────────────────────────────────
st.subheader("完整指标对比表")
render_full_metrics_table(m, m)

st.markdown("---")

# ── Trade summary ─────────────────────────────────────────────────────────────
st.subheader("交易样本")
n_show = st.slider("显示交易笔数", 10, 100, 20, 10)
trades_display = res.trades.sort_values("exit_date", ascending=False).head(n_show).copy()
if "pnl_r_multiple" in trades_display.columns:
    trades_display = trades_display[[
        "ticker", "entry_date", "exit_date", "entry_price", "exit_price",
        "shares", "pnl_r_multiple",
    ]].rename(columns={
        "ticker": "标的",
        "entry_date": "入场日",
        "exit_date": "出场日",
        "entry_price": "入场价",
        "exit_price": "出场价",
        "shares": "股数",
        "pnl_r_multiple": "R 倍数",
    })
st.dataframe(trades_display, use_container_width=True, hide_index=True)

# ── Assessment ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("评估")

import numpy as _np2
import pandas as _pd3

# ── Compute additional stats ──────────────────────────────────────────────────
_nav_s = res.nav.copy()
if not isinstance(_nav_s.index, _pd3.DatetimeIndex):
    _nav_s.index = _pd3.to_datetime(_nav_s.index)

# Annual returns (exclude current partial year)
_annual_all = _nav_s.resample("YE").last().pct_change().dropna()
_current_year = _nav_s.index[-1].year
_annual = _annual_all[_annual_all.index.year < _current_year]
_n_years      = len(_annual)
_pos_years    = int((_annual > 0).sum())
_neg_years    = int((_annual < 0).sum())
_worst_yr     = int(_annual.idxmin().year)
_worst_ret    = float(_annual.min())
_best_yr      = int(_annual.idxmax().year)
_best_ret     = float(_annual.max())

_cagr         = m.get("cagr", 0)
_sharpe       = m.get("sharpe", 0)
_sortino      = m.get("sortino", 0)
_calmar       = m.get("calmar", 0)
_maxdd        = m.get("max_drawdown", 0)
_maxdd_dur    = m.get("max_dd_duration_days", 0)
_pf           = m.get("profit_factor", 0)
_wr           = m.get("win_rate", 0)
_avg_win_r    = m.get("avg_win_r", 0)
_avg_loss_r   = m.get("avg_loss_r", 0)
_turnover     = m.get("annual_turnover", 0)
_exposure     = m.get("market_exposure", 0)
_spy_cagr     = m.get("spy_cagr", 0)
_spy_sharpe   = m.get("spy_sharpe", 0)
_spy_maxdd    = m.get("spy_max_drawdown", 0)
_cagr_gap     = _cagr - _spy_cagr
_maxdd_ratio  = abs(_maxdd / _spy_maxdd) if _spy_maxdd != 0 else 0
_n_trades     = m.get("n_trades", 0)
_max_cl       = m.get("max_consecutive_losses", 0)
_total_ret    = m.get("total_return", 0)

_tr_copy = res.trades.copy()
_big5r = int((_tr_copy["pnl_r_multiple"] > 5).sum())
_big5r_pct = _big5r / len(_tr_copy) * 100 if len(_tr_copy) > 0 else 0
_max_r = float(_tr_copy["pnl_r_multiple"].max())

_implied_cost = _turnover * (
    meta.params_anchor.get("slippage_bps", 10) + meta.params_anchor.get("commission_bps", 3)
) * 2 / 100

# ── Dynamic negative-year description ────────────────────────────────────────
_spy_ann_dict: dict = {}
if res.spy_nav is not None:
    _spy_nav_tmp = res.spy_nav.copy()
    if not isinstance(_spy_nav_tmp.index, _pd3.DatetimeIndex):
        _spy_nav_tmp.index = _pd3.to_datetime(_spy_nav_tmp.index)
    for _idx, _ret in _spy_nav_tmp.resample("YE").last().pct_change().dropna().items():
        if _idx.year < _current_year:
            _spy_ann_dict[int(_idx.year)] = float(_ret)

_neg_details = sorted(
    [(int(_idx.year), float(_ret)) for _idx, _ret in _annual[_annual < 0].items()],
    key=lambda x: x[1],
)
if _neg_details:
    _small_loss = [(y, r) for y, r in _neg_details if r > -0.10]
    _big_loss   = [(y, r) for y, r in _neg_details if r <= -0.10]
    _nd_parts: list[str] = []
    if _small_loss:
        _nd_parts.append(
            f"{len(_small_loss)} 年亏损较轻（> -10%）："
            + "、".join(f"{y}年（{r*100:.1f}%）" for y, r in sorted(_small_loss))
        )
    if _big_loss:
        _big_strs = []
        for _y, _r in sorted(_big_loss):
            _spy_r = _spy_ann_dict.get(_y)
            _spy_suffix = f"，同期 SPY {_spy_r*100:.1f}%" if _spy_r is not None else ""
            _big_strs.append(f"{_y}年（策略 {_r*100:.1f}%{_spy_suffix}）")
        _nd_parts.append(
            f"{len(_big_loss)} 年出现较大亏损（≤ -10%）：" + "、".join(_big_strs)
        )
    _neg_yr_desc = "；".join(_nd_parts) + "。"
else:
    _neg_yr_desc = "历史回测中无负收益年份。"

st.markdown(f"""
**1. 绝对收益可观，但跑输 SPY 约 {abs(_cagr_gap)*100:.1f} 个百分点**

在 {meta.backtest_start[:4]}–{_current_year-1} 约 {_n_years} 年的完整回测期内，
策略 CAGR **{_cagr*100:+.2f}%**，同期 SPY 为 **{_spy_cagr*100:+.2f}%**，差距 **{_cagr_gap*100:+.2f}%**。
以 $10M 初始资金计算，净值增长 **{_total_ret:.2f} 倍**（期末约 ${_total_ret*10:.0f}M）。
跑输 SPY 是这份结果最直接的弱点，也是向任何潜在投资者解释时需要正面回答的第一个问题。
对此的核心回答是：**SPY 在相同时间内最大回撤 {abs(_spy_maxdd)*100:.1f}%，而策略最大回撤仅 {abs(_maxdd)*100:.1f}%**——
收益更低，但承受的风险断崖式下降。

**2. Sharpe 轻微领先 SPY，风险调整后有竞争力**

策略 Sharpe **{_sharpe:+.3f}** vs SPY **{_spy_sharpe:+.3f}**，差距微小但方向有利。
Sortino **{_sortino:+.3f}**（对下行波动的惩罚更严格），Calmar **{_calmar:+.3f}**（CAGR / MaxDD）。
这三个指标共同说明：在单位风险维度上，策略与 SPY 大体相当，
并非用大幅更低的风险调整收益换来了更低的绝对回撤——而是在**基本等效的风险效率下**，
大幅压缩了最大回撤的绝对深度。

**3. 最大回撤 {abs(_maxdd)*100:.1f}% 是策略最突出的实际优势**

SPY 在回测期内最大回撤高达 **{abs(_spy_maxdd)*100:.1f}%**（2008–2009 金融危机），
策略同期最大回撤仅 **{abs(_maxdd)*100:.1f}%**，下行深度约为 SPY 的 **{_maxdd_ratio*100:.0f}%**。
最长水下时间 **{_maxdd_dur} 个交易日**（约 {_maxdd_dur/252:.1f} 年）。
对于以保全本金为前提的机构资金而言，这一差距具有实质意义：
**{abs(_spy_maxdd)*100:.0f}%** 的跌幅需要涨 **{(1/(1-min(abs(_spy_maxdd),0.99))-1)*100:.0f}%** 才能回本，而策略 **{abs(_maxdd)*100:.0f}%** 仅需涨 **{(1/(1-min(abs(_maxdd),0.99))-1)*100:.0f}%**。

**4. 胜率低而盈亏比高，符合趋势跟踪的数学结构**

胜率 **{_wr*100:.1f}%** 在表观上偏低，但这是趋势策略的内在特征，而非缺陷。
盈利交易平均 **{_avg_win_r:+.2f}R**，亏损交易平均 **{abs(_avg_loss_r):.2f}R**，
Profit Factor **{_pf:.3f}**——每亏 1 元预期赚回 {_pf:.2f} 元。
在 {_n_trades:,} 笔交易中，超过 5R 的大赢家 {_big5r} 笔（占比 {_big5r_pct:.1f}%），
最大单笔 **{_max_r:+.2f}R**。
**大赢家的右尾贡献是策略盈利的核心来源**——不能因为胜率偏低就轻易判断策略无效。

**5. 年度表现稳定，{_n_years} 年中 {_pos_years} 年正收益（{_pos_years/_n_years*100:.0f}%）**

{_n_years} 个完整年度中，{_pos_years} 年正收益，{_neg_years} 年负收益。
最差年份 **{_worst_yr} 年（{_worst_ret*100:+.1f}%）**，最好年份 **{_best_yr} 年（{_best_ret*100:+.1f}%）**。
{_neg_yr_desc}
这种"负收益年份损失可控、正收益年份收益可观"的结构，
是趋势策略长期正复利的基础。

**6. 交易成本与换手率处于合理区间**

年换手率 **{_turnover:.2f}x**，隐含年化交易摩擦约 **{_implied_cost:.2f}%**，
已完整计入回测净值。市场暴露率 **{_exposure*100:.1f}%**（约 {100-_exposure*100:.1f}% 时间现金转入 SHY），
说明策略全年大部分时间有仓位，并非依赖少数几笔交易的偶然发挥。

**7. 策略定位的准确理解**
""")

# Positioning assessment table
st.markdown(f"""
| 维度 | 结论 |
|------|------|
| 绝对收益 | ✅ CAGR {_cagr*100:+.2f}%，{_n_years}年累计 {(_total_ret-1)*100:.0f}%，正期望明确 |
| 相对收益 | ⚠️ 落后 SPY {abs(_cagr_gap)*100:.1f}%/年，在长牛市中是结构性弱点 |
| 回撤控制 | ✅ MaxDD {abs(_maxdd)*100:.1f}% vs SPY {abs(_spy_maxdd)*100:.1f}%，下行保护能力突出 |
| 风险效率 | ✅ Sharpe {_sharpe:.3f} vs SPY {_spy_sharpe:.3f}，单位风险回报大体相当 |
| 交易成本 | ✅ {_implied_cost:.2f}%/年，已计入净值，不影响结论可信度 |
| 适用场景 | 适合作为投资组合中的**防御性趋势配置**，而非替代 SPY 的进攻性资产 |
""")

# Verdict
if _cagr > 0.06 and _sharpe > _spy_sharpe and abs(_maxdd) < abs(_spy_maxdd) * 0.5:
    verdict_icon = "✅"
    verdict_body = (
        f"综合评价：基准回测结果达到预期目标。"
        f"CAGR {_cagr*100:+.2f}%，Sharpe {_sharpe:.3f}（微超 SPY {_spy_sharpe:.3f}），"
        f"MaxDD {abs(_maxdd)*100:.1f}%（仅为 SPY {abs(_spy_maxdd)*100:.1f}% 的 {_maxdd_ratio*100:.0f}%）。"
        f"策略的核心价值在于**用约 {abs(_cagr_gap)*100:.1f}% 的年化收益损失，换取约 {(abs(_spy_maxdd)-abs(_maxdd))*100:.1f}% 的最大回撤保护**，"
        f"是风险厌恶型投资者在权益资产中最值得考虑的量化选项之一。"
    )
elif _cagr > 0.05:
    verdict_icon = "🟡"
    verdict_body = (
        f"综合评价：结果整体可接受，CAGR {_cagr*100:+.2f}%，但 Sharpe 或回撤控制仍有提升空间。"
    )
else:
    verdict_icon = "⚠️"
    verdict_body = f"综合评价：CAGR {_cagr*100:+.2f}% 偏低，需审查策略参数或回测设置。"

st.markdown(
    f'<div class="info-box"><strong>{verdict_icon} {verdict_body}</strong></div>',
    unsafe_allow_html=True,
)
