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

# ── Compute extended SPY metrics from spy_nav ─────────────────────────────────
import numpy as _np

_spy_metrics = dict(m)   # already has spy_cagr, spy_sharpe, spy_max_drawdown

if res.spy_nav is not None:
    _sn  = res.spy_nav
    _sr  = _sn.pct_change().fillna(0.0)
    _rf  = (1 + 0.02) ** (1 / 252) - 1

    # Total return
    _spy_metrics["spy_total_return"] = float(_sn.iloc[-1] / _sn.iloc[0] - 1)

    # Annual volatility
    _spy_metrics["spy_annual_vol"] = float(_sr.std() * _np.sqrt(252))

    # Sortino
    _exc       = _sr - _rf
    _down_std  = float(_exc[_exc < 0].std() * _np.sqrt(252))
    _spy_cagr  = m.get("spy_cagr", 0)
    _spy_metrics["spy_sortino"] = float((_spy_cagr - 0.02) / _down_std) if _down_std > 0 else 0.0

    # Calmar
    _spy_maxdd = m.get("spy_max_drawdown", 0)
    _spy_metrics["spy_calmar"] = float(_spy_cagr / abs(_spy_maxdd)) if _spy_maxdd != 0 else 0.0

    # Max drawdown duration (trading days)
    _roll_max  = _sn.cummax()
    _underwater = (_sn < _roll_max)
    _max_dur = _cur_dur = 0
    for _uw in _underwater:
        if _uw:
            _cur_dur += 1
            _max_dur  = max(_max_dur, _cur_dur)
        else:
            _cur_dur = 0
    _spy_metrics["spy_max_dd_duration_days"] = _max_dur

# ── Build downloadable markdown report (uses m, meta, res, _spy_metrics, _ETF_SET) ──
def _build_md_report():
    import datetime as _dt_r
    import pandas as _pd_r
    import numpy as _np_r

    _p_r   = meta.params_anchor
    _now_r = _dt_r.datetime.now().strftime("%Y-%m-%d %H:%M")

    # -- metrics --
    _cagr_r         = m.get("cagr", 0)
    _maxdd_r        = m.get("max_drawdown", 0)
    _sharpe_r       = m.get("sharpe", 0)
    _sortino_r      = m.get("sortino", 0)
    _calmar_r       = m.get("calmar", 0)
    _pf_r           = m.get("profit_factor", 0)
    _wr_r           = m.get("win_rate", 0)
    _n_trades_r     = m.get("n_trades", 0)
    _max_cl_r       = m.get("max_consecutive_losses", 0)
    _maxdd_dur_r    = m.get("max_dd_duration_days", 0)
    _turnover_r     = m.get("annual_turnover", 0)
    _exposure_r     = m.get("market_exposure", 0)
    _total_ret_r    = m.get("total_return", 0)
    _avg_win_r_r    = m.get("avg_win_r", 0)
    _avg_loss_r_r   = m.get("avg_loss_r", 0)
    _annual_vol_r   = m.get("annual_vol", 0)
    _tpy_r          = m.get("trades_per_year", 0)
    _avg_hold_r     = m.get("avg_holding_days", 0)
    _spy_cagr_r     = m.get("spy_cagr", 0)
    _spy_maxdd_r    = m.get("spy_max_drawdown", 0)
    _spy_sharpe_r   = m.get("spy_sharpe", 0)
    _spy_sortino_r  = _spy_metrics.get("spy_sortino", 0)
    _spy_calmar_r   = _spy_metrics.get("spy_calmar", 0)
    _spy_totret_r   = _spy_metrics.get("spy_total_return", 0)
    _spy_vol_r      = _spy_metrics.get("spy_annual_vol", 0)
    _spy_mddur_r    = _spy_metrics.get("spy_max_dd_duration_days", 0)

    _slip_r = _p_r.get("slippage_bps", 10)
    _comm_r = _p_r.get("commission_bps", 3)
    _rt_r   = (_slip_r + _comm_r) * 2
    _impl_r = _turnover_r * _rt_r / 100
    _cagr_gap_r   = _cagr_r - _spy_cagr_r
    _mddrat_r     = abs(_maxdd_r / _spy_maxdd_r) if _spy_maxdd_r != 0 else 0
    _bt_years_r   = (res.nav.index[-1] - res.nav.index[0]).days / 365.25

    # -- nav / annual returns --
    _nav_r = res.nav.copy()
    if not isinstance(_nav_r.index, _pd_r.DatetimeIndex):
        _nav_r.index = _pd_r.to_datetime(_nav_r.index)
    _ann_all_r  = _nav_r.resample("YE").last().pct_change().dropna()
    _cur_yr_r   = _nav_r.index[-1].year
    _ann_r      = _ann_all_r[_ann_all_r.index.year < _cur_yr_r]
    _spy_ann_r: dict = {}
    if res.spy_nav is not None:
        _spy_nav_r = res.spy_nav.copy()
        if not isinstance(_spy_nav_r.index, _pd_r.DatetimeIndex):
            _spy_nav_r.index = _pd_r.to_datetime(_spy_nav_r.index)
        for _idx_r2, _ret_r2 in _spy_nav_r.resample("YE").last().pct_change().dropna().items():
            if _idx_r2.year < _cur_yr_r:
                _spy_ann_r[int(_idx_r2.year)] = float(_ret_r2)
    _pos_yr_r   = int((_ann_r > 0).sum())
    _n_yr_r     = len(_ann_r)
    _worst_yr_r = int(_ann_r.idxmin().year) if _n_yr_r > 0 else 0
    _worst_rt_r = float(_ann_r.min()) if _n_yr_r > 0 else 0
    _best_yr_r  = int(_ann_r.idxmax().year) if _n_yr_r > 0 else 0
    _best_rt_r  = float(_ann_r.max()) if _n_yr_r > 0 else 0

    # -- monthly stats --
    _mo_r       = _nav_r.resample("ME").last().pct_change().dropna() * 100
    _pos_m_r    = int((_mo_r > 0).sum())
    _tot_m_r    = len(_mo_r)
    _best_m_r   = float(_mo_r.max())
    _worst_m_r  = float(_mo_r.min())
    _best_m_dt  = _mo_r.idxmax()
    _worst_m_dt = _mo_r.idxmin()

    # -- drawdown episodes --
    _vals_r  = _nav_r.values.astype(float)
    _dates_r = _nav_r.index
    _n_r     = len(_vals_r)
    _pk_v    = _vals_r[0]; _pk_i = 0; _in_ep = False
    _ep_pi = _ep_ti = 0; _ep_tv = 0.0; _ep_rows: list[dict] = []
    for _i in range(1, _n_r):
        _v = _vals_r[_i]
        if _v >= _pk_v:
            if _in_ep:
                _ep_rows.append({"高点": _dates_r[_ep_pi].strftime("%Y-%m"),
                                  "低点": _dates_r[_ep_ti].strftime("%Y-%m"),
                                  "修复": _dates_r[_i].strftime("%Y-%m"),
                                  "最大回撤%": (_ep_tv - _vals_r[_ep_pi]) / _vals_r[_ep_pi] * 100,
                                  "至低谷(交易日)": _ep_ti - _ep_pi,
                                  "修复耗时(交易日)": _i - _ep_ti,
                                  "总水下时间(交易日)": _i - _ep_pi})
                _in_ep = False
            _pk_v = _v; _pk_i = _i
        else:
            if (_v - _pk_v) / _pk_v < -0.05:
                if not _in_ep:
                    _in_ep = True; _ep_pi = _pk_i; _ep_ti = _i; _ep_tv = _v
                elif _v < _ep_tv:
                    _ep_ti = _i; _ep_tv = _v
    if _in_ep:
        _ep_rows.append({"高点": _dates_r[_ep_pi].strftime("%Y-%m"),
                          "低点": _dates_r[_ep_ti].strftime("%Y-%m"),
                          "修复": "进行中",
                          "最大回撤%": (_ep_tv - _vals_r[_ep_pi]) / _vals_r[_ep_pi] * 100,
                          "至低谷(交易日)": _ep_ti - _ep_pi,
                          "修复耗时(交易日)": _n_r - 1 - _ep_ti,
                          "总水下时间(交易日)": _n_r - 1 - _ep_pi})
    _ep_df_r = _pd_r.DataFrame(_ep_rows)

    # -- trade stats --
    _tr_r      = res.trades.copy()
    _big5_r    = int((_tr_r["pnl_r_multiple"] > 5).sum())
    _big5p_r   = _big5_r / len(_tr_r) * 100 if len(_tr_r) > 0 else 0
    _max_r_r   = float(_tr_r["pnl_r_multiple"].max())
    _med_hld_r = float(_tr_r["holding_days"].median()) if "holding_days" in _tr_r.columns else 0
    _s_pnl_r   = _tr_r[~_tr_r["ticker"].isin(_ETF_SET)]["net_pnl"].sum()
    _e_pnl_r   = _tr_r[_tr_r["ticker"].isin(_ETF_SET)]["net_pnl"].sum()
    _tot_pnl_r = _s_pnl_r + _e_pnl_r

    L: list[str] = []

    def _h(n, t): L.append(f"{'#'*n} {t}"); L.append("")
    def _row(*cells): L.append("| " + " | ".join(str(c) for c in cells) + " |")
    def _sep(n): L.append("|" + "|".join(["------"] * n) + "|")
    def _blank(): L.append("")
    def _hr(): L.append("---"); _blank()

    L.append(f"# {meta.display_name} — Baseline参数回测结果")
    _blank()
    L.append(f"**回测期间：** {meta.backtest_start} → {meta.backtest_end}  ")
    L.append(f"**初始资金：** $10,000,000  ")
    L.append(f"**生成时间：** {_now_r}")
    _blank(); _hr()

    _h(2, "核心指标摘要")
    _row("指标", "策略1.0", "SPY 基准"); _sep(3)
    _row("CAGR（年化复合回报）", f"{_cagr_r*100:+.2f}%", f"{_spy_cagr_r*100:+.2f}%")
    _row("总回报率", f"{_total_ret_r*100:+.2f}%", f"{_spy_totret_r*100:+.2f}%")
    _row("年化波动率", f"{_annual_vol_r*100:.2f}%", f"{_spy_vol_r*100:.2f}%")
    _row("最大回撤", f"{_maxdd_r*100:+.2f}%", f"{_spy_maxdd_r*100:+.2f}%")
    _row("最长水下时间", f"{_maxdd_dur_r:,} 交易日（≈ {_maxdd_dur_r/252:.1f} 年）",
         f"{_spy_mddur_r:,} 交易日（≈ {_spy_mddur_r/252:.1f} 年）")
    _row("Sharpe 比率（rf=2%）", f"{_sharpe_r:+.3f}", f"{_spy_sharpe_r:+.3f}")
    _row("Sortino 比率", f"{_sortino_r:+.3f}", f"{_spy_sortino_r:+.3f}")
    _row("Calmar 比率", f"{_calmar_r:+.3f}", f"{_spy_calmar_r:+.3f}")
    _row("Profit Factor", f"{_pf_r:.3f}", "—（买入持有）")
    _row("交易胜率", f"{_wr_r*100:.1f}%", "—（买入持有）")
    _row("总交易笔数", f"{int(_n_trades_r):,}", "—（买入持有）")
    _row("平均盈利（R 倍数）", f"{_avg_win_r_r:+.2f}R", "—（买入持有）")
    _row("平均亏损（R 倍数）", f"{_avg_loss_r_r:.2f}R", "—（买入持有）")
    _row("平均持仓天数", f"{_avg_hold_r:.0f} 天", "—（买入持有）")
    _row("中位持仓天数", f"{_med_hld_r:.0f} 天", "—（买入持有）")
    _row("交易频率", f"{_tpy_r:.0f} 笔/年", "—（买入持有）")
    _row("最长连续亏损次数", f"{int(_max_cl_r)} 笔", "—（买入持有）")
    _row("年换手率", f"{_turnover_r:.1f}x（{_turnover_r*100:.0f}%/年）", "—（买入持有）")
    _row("隐含年化交易成本", f"≈ {_impl_r:.2f}%（已含于回测）", "—（买入持有）")
    _row("市场暴露率", f"{_exposure_r*100:.1f}%", "100%（全仓持有）")
    _blank(); _hr()

    _h(2, "Baseline 锚点参数")
    _h(3, "入场信号")
    _row("参数", "代码名", "值"); _sep(3)
    _row("突破窗口", "breakout_window", f"{_p_r['breakout_window']} 日")
    _row("ATR 周期", "atr_period", f"{_p_r['atr_period']} 日（Wilder 平滑）")
    _row("成交量确认乘数", "volume_filter_multiplier", f"{_p_r['volume_filter_multiplier']:.1f}× 60日均量")
    _row("Gap 过滤", "gap_filter", f"±{_p_r['gap_filter']*100:.1f}%")
    _blank()
    _h(3, "止损 / 移动止盈")
    _row("参数", "代码名", "值"); _sep(3)
    _row("ATR 止损乘数", "stop_loss_multiplier", f"{_p_r['stop_loss_multiplier']:.1f}×ATR")
    _row("最小止损距离", "min_stop_distance_pct", f"{_p_r['min_stop_distance_pct']*100:.1f}%")
    _row("移动止盈（早期 <1R）", "trail_multiplier_r1", f"{_p_r['trail_multiplier_r1']:.1f}×ATR")
    _row("移动止盈（中期 1–3R）", "trail_multiplier_r3", f"{_p_r['trail_multiplier_r3']:.1f}×ATR")
    _row("移动止盈（大赢 ≥3R）", "trail_multiplier_r5", f"{_p_r['trail_multiplier_r5']:.1f}×ATR")
    _blank()
    _h(3, "仓位与风险")
    _row("参数", "代码名", "值"); _sep(3)
    _row("每笔风险比例", "risk_per_trade", f"{_p_r['risk_per_trade']*100:.1f}% NAV")
    _row("单标的仓位上限", "position_cap", f"{_p_r['position_cap']*100:.0f}% NAV")
    _row("热度上限", "heat_limit", f"{_p_r['heat_limit']*100:.0f}% NAV")
    _blank()
    _h(3, "相关性过滤")
    _row("参数", "代码名", "值"); _sep(3)
    _row("相关性窗口", "correlation_window", f"{_p_r['correlation_window']} 日")
    _row("相关性阈值", "correlation_threshold", f"{_p_r['correlation_threshold']:.2f}")
    _row("减仓比例", "correlation_reduction", f"{_p_r['correlation_reduction']*100:.0f}%")
    _blank()
    _h(3, "市场环境过滤（Regime Filter）")
    _row("参数", "代码名", "值"); _sep(3)
    _row("启用", "regime_filter_enabled", "是" if _p_r["regime_filter_enabled"] else "否")
    _row("基准标的", "regime_ticker", _p_r["regime_ticker"])
    _row("SMA 窗口", "regime_sma_window", f"{_p_r['regime_sma_window']} 日")
    _blank()
    _h(3, "交易成本")
    _row("参数", "代码名", "值"); _sep(3)
    _row("滑点（单边）", "slippage_bps", f"{_slip_r:.0f} bps")
    _row("佣金（单边）", "commission_bps", f"{_comm_r:.0f} bps")
    _blank(); _hr()

    # ── NAV 年度快照（对应"净值曲线 vs SPY"图表）───────────────────────────────
    _h(2, "净值曲线年度快照（对应图表：净值曲线 vs SPY）")
    _row("年末日期", "策略1.0 NAV", "SPY NAV（归一）", "策略年涨幅", "SPY年涨幅"); _sep(5)
    _nav_snap = _nav_r.resample("YE").last()
    _spy_snap = res.spy_nav.resample("YE").last() if res.spy_nav is not None else None
    if not isinstance(_spy_snap.index if _spy_snap is not None else _nav_snap.index, _pd_r.DatetimeIndex):
        pass
    _prev_nav = float(_nav_snap.iloc[0]) if len(_nav_snap) > 0 else 1.0
    _prev_spy = float(_spy_snap.iloc[0]) if _spy_snap is not None and len(_spy_snap) > 0 else None
    # First row = start date
    _start_nav = float(_nav_r.iloc[0])
    _start_spy = float(res.spy_nav.iloc[0]) if res.spy_nav is not None else None
    _row(str(_nav_r.index[0])[:10],
         f"{_start_nav:.4f}",
         f"{_start_spy:.4f}" if _start_spy is not None else "—",
         "（起始）", "（起始）")
    for _dt_s, _v_s in _nav_snap.items():
        _v_s = float(_v_s)
        _spy_v_s = float(_spy_snap[_dt_s]) if _spy_snap is not None and _dt_s in _spy_snap.index else None
        _nav_chg = (_v_s / _prev_nav - 1) * 100 if _prev_nav != 0 else 0
        _spy_chg = (_spy_v_s / _prev_spy - 1) * 100 if _spy_v_s is not None and _prev_spy is not None and _prev_spy != 0 else None
        _row(str(_dt_s)[:10],
             f"{_v_s:.4f}",
             f"{_spy_v_s:.4f}" if _spy_v_s is not None else "—",
             f"{_nav_chg:+.1f}%",
             f"{_spy_chg:+.1f}%" if _spy_chg is not None else "—")
        _prev_nav = _v_s
        _prev_spy = _spy_v_s
    _blank(); _hr()

    # ── 回撤曲线（月末回撤 %，对应图表：回撤曲线）──────────────────────────────────
    _h(2, "回撤曲线月末快照（对应图表：回撤曲线）")
    _dd_ser = _nav_r / _nav_r.cummax() - 1
    _dd_mo  = (_dd_ser.resample("ME").last() * 100)   # end-of-month drawdown in %
    _row("年份","1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"); _sep(13)
    for _yr_dd in sorted(_dd_mo.index.year.unique()):
        _row_dd = [str(_yr_dd)]
        _ym_dd  = _dd_mo[_dd_mo.index.year == _yr_dd]
        for _m_dd in range(1, 13):
            _mm_dd = _ym_dd[_ym_dd.index.month == _m_dd]
            _row_dd.append(f"{float(_mm_dd.iloc[0]):.1f}%" if len(_mm_dd) > 0 else "—")
        _row(*_row_dd)
    _blank()
    _dd_min_v  = float(_dd_mo.min())
    _dd_min_dt = str(_dd_mo.idxmin())[:7]
    _dd_avg    = float(_dd_mo.mean())
    _dd_zero   = float((_dd_mo >= -0.1).mean()) * 100
    L.append(f"历史最大月末回撤：**{_dd_min_v:.1f}%**（{_dd_min_dt}）")
    L.append(f"平均月末回撤：**{_dd_avg:.1f}%**  |  高于 -0.1% 的月份（基本在水面上）：**{_dd_zero:.0f}%**")
    _blank(); _hr()

    if len(_ep_df_r) > 0:
        _h(2, "主要回撤情节（回撤 ≥ 5%，按深度排序，前 10 次）")
        _ep_top = _ep_df_r.sort_values("最大回撤%").head(10)
        _row("高点","低点","修复","最大回撤","至低谷(交易日)","修复耗时(交易日)","总水下时间(交易日)"); _sep(7)
        for _, _er in _ep_top.iterrows():
            _row(_er["高点"], _er["低点"], _er["修复"],
                 f"{_er['最大回撤%']:.1f}%",
                 _er["至低谷(交易日)"], _er["修复耗时(交易日)"], _er["总水下时间(交易日)"])
        _blank(); _hr()

    _h(2, "逐年回报")
    _row("年份", "策略1.0", "SPY"); _sep(3)
    for _idx_a, _ret_a in _ann_r.items():
        _yr_a = int(_idx_a.year)
        _spy_a = _spy_ann_r.get(_yr_a)
        _row(_yr_a, f"{_ret_a*100:+.1f}%", f"{_spy_a*100:+.1f}%" if _spy_a is not None else "—")
    if _cur_yr_r in _ann_all_r.index.year:
        _cur_ret_a = float(_ann_all_r[_ann_all_r.index.year == _cur_yr_r].iloc[-1])
        _spy_cur_a = _spy_ann_r.get(_cur_yr_r)
        _row(f"{_cur_yr_r}（截至 {meta.backtest_end}）",
             f"{_cur_ret_a*100:+.1f}%",
             f"{_spy_cur_a*100:+.1f}%" if _spy_cur_a is not None else "—")
    _blank()
    L.append(f"**{_n_yr_r} 个完整年度中 {_pos_yr_r} 年正收益（{_pos_yr_r/_n_yr_r*100:.0f}%）**")
    L.append(f"最差年份：**{_worst_yr_r} 年（{_worst_rt_r*100:+.1f}%）**  |  最好年份：**{_best_yr_r} 年（{_best_rt_r*100:+.1f}%）**")
    _blank(); _hr()

    # ── 滚动 Sharpe 比率年度摘要（对应图表：滚动 Sharpe 比率）──────────────────────
    _h(2, "滚动 Sharpe 比率年度摘要（对应图表：滚动 Sharpe 比率）")
    _rets_r = res.returns.copy() if hasattr(res, "returns") and res.returns is not None else _nav_r.pct_change().fillna(0.0)
    if not isinstance(_rets_r.index, _pd_r.DatetimeIndex):
        _rets_r.index = _pd_r.to_datetime(_rets_r.index)
    _rf_r2     = (1 + 0.02) ** (1 / 252) - 1
    import numpy as _np_r2
    _excess_r  = _rets_r - _rf_r2
    _roll_sh   = (_excess_r.rolling(252).mean() / _rets_r.rolling(252).std()) * _np_r2.sqrt(252)
    _roll_sh_y = _roll_sh.resample("YE").agg(["mean","min","max"]).dropna()
    _row("年份","年均滚动Sharpe","年内最低","年内最高"); _sep(4)
    for _dt_rs, _row_rs in _roll_sh_y.iterrows():
        _row(int(_dt_rs.year), f"{_row_rs['mean']:+.3f}", f"{_row_rs['min']:+.3f}", f"{_row_rs['max']:+.3f}")
    _blank()
    _rs_overall_mean = float(_roll_sh.dropna().mean())
    _rs_pos_pct      = float((_roll_sh.dropna() > 0).mean()) * 100
    L.append(f"全期均值（252日滚动）：**{_rs_overall_mean:+.3f}**  |  滚动Sharpe > 0 的交易日占比：**{_rs_pos_pct:.0f}%**")
    _blank(); _hr()

    _h(2, "月度收益热力图（对应图表：月度收益热力图）")
    L.append(f"正收益月份：{_pos_m_r} / {_tot_m_r}（{_pos_m_r/_tot_m_r*100:.0f}%）  |  "
             f"最好月份：{_best_m_dt.strftime('%Y年%m月')}（{_best_m_r:+.1f}%）  |  "
             f"最差月份：{_worst_m_dt.strftime('%Y年%m月')}（{_worst_m_r:+.1f}%）")
    _blank()
    _row("年份","1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月","全年"); _sep(14)
    for _yr_h in sorted(_mo_r.index.year.unique()):
        _row_h = [str(_yr_h)]
        _yr_mos_h = _mo_r[_mo_r.index.year == _yr_h]
        for _m_h in range(1, 13):
            _mm = _yr_mos_h[_yr_mos_h.index.month == _m_h]
            _row_h.append(f"{float(_mm.iloc[0]):+.1f}%" if len(_mm) > 0 else "—")
        # full-year compound return
        if _yr_h < _cur_yr_r and _yr_h in [int(_i.year) for _i in _ann_r.index]:
            _ann_h = float(_ann_r[[_i.year == _yr_h for _i in _ann_r.index]].iloc[0]) * 100
            _row_h.append(f"{_ann_h:+.1f}%")
        else:
            _comp_h = ((_yr_mos_h / 100 + 1).prod() - 1) * 100
            _row_h.append(f"{_comp_h:+.1f}%")
        _row(*_row_h)
    _blank(); _hr()

    _h(2, "交易盈亏分布（R 倍数）")
    L.append(f"- 胜率：{_wr_r*100:.1f}%")
    L.append(f"- 平均盈利：{_avg_win_r_r:+.2f}R  |  平均亏损：{_avg_loss_r_r:.2f}R")
    L.append(f"- Profit Factor：{_pf_r:.4f}")
    L.append(f"- 超过 5R 的大赢家：{_big5_r} 笔（{_big5p_r:.1f}%），历史最大单笔：{_max_r_r:+.2f}R")
    _blank(); _hr()

    _h(2, "换手率分析")
    L.append(f"- 年换手率：{_turnover_r:.1f}x（{_turnover_r*100:.0f}%/年）")
    L.append(f"- 往返成本：{_rt_r:.0f} bps（{_slip_r:.0f} bps 滑点 + {_comm_r:.0f} bps 佣金，双边）")
    L.append(f"- 隐含年化交易摩擦：≈ {_impl_r:.2f}%（已完整计入回测净值）")
    _blank(); _hr()

    _h(2, "持仓分析（对应图表：逐年交易笔数 / 持仓天数分布）")
    L.append(f"- 平均每年交易笔数：{_tpy_r:.0f} 笔  |  市场暴露率：{_exposure_r*100:.1f}%")
    L.append(f"- 平均持仓天数：{_avg_hold_r:.0f} 天  |  中位持仓天数：{_med_hld_r:.0f} 天")
    _blank()
    # Trades per year table
    _h(3, "逐年交易笔数")
    _tr_yr_r = res.trades.copy()
    _tr_yr_r["_exit_yr"] = _pd_r.to_datetime(_tr_yr_r["exit_date"]).dt.year
    _tpy_grp = _tr_yr_r.groupby("_exit_yr").agg(
        交易笔数=("net_pnl","count"),
        胜率=("net_pnl", lambda x: (x>0).mean()),
        平均R=("pnl_r_multiple","mean"),
        净盈亏=("net_pnl","sum"),
    ).reset_index().rename(columns={"_exit_yr":"年份"})
    _row("年份","交易笔数","胜率","平均R","净盈亏($)"); _sep(5)
    for _, _tyr in _tpy_grp.iterrows():
        _row(int(_tyr["年份"]), int(_tyr["交易笔数"]),
             f"{_tyr['胜率']*100:.1f}%",
             f"{_tyr['平均R']:+.3f}",
             f"${_tyr['净盈亏']:+,.0f}")
    _blank()
    # Holding days distribution (binned)
    _h(3, "持仓天数分布")
    _hd_r = _tr_r["holding_days"].dropna()
    _hd_bins = [(0,5),(5,10),(10,20),(20,30),(30,60),(60,90),(90,120),(120,180),(180,99999)]
    _hd_labels = ["1–5天","6–10天","11–20天","21–30天","31–60天","61–90天","91–120天","121–180天","＞180天"]
    _row("区间","笔数","占比"); _sep(3)
    for (lo_b,hi_b),lbl_b in zip(_hd_bins,_hd_labels):
        _cnt_b = int((((_hd_r > lo_b) if lo_b > 0 else (_hd_r >= 0)) & (_hd_r <= hi_b if hi_b < 99999 else _pd_r.Series([True]*len(_hd_r),index=_hd_r.index))).sum())
        _row(lbl_b, _cnt_b, f"{_cnt_b/len(_hd_r)*100:.1f}%")
    _blank()

    # ── 每日持仓标的数目年度摘要（对应图表：每日持仓标的数目）────────────────────
    _h(3, "每日持仓标的数目年度摘要（对应图表：每日持仓标的数目）")
    _dc_r = res.trades.copy()
    _dc_r["_entry"] = _pd_r.to_datetime(_dc_r["entry_date"])
    _dc_r["_exit"]  = _pd_r.to_datetime(_dc_r["exit_date"])
    _nav_idx_r = _pd_r.to_datetime(_nav_r.index)
    _en_cnt = _dc_r.groupby("_entry").size().reindex(_nav_idx_r, fill_value=0)
    _ex_cnt = _dc_r.groupby("_exit").size().reindex(_nav_idx_r, fill_value=0)
    _daily_pos = (_en_cnt - _ex_cnt).cumsum().clip(lower=0)
    _daily_pos_ser = _pd_r.Series(_daily_pos.values, index=_nav_idx_r)
    _row("年份","年均持仓数","最多","最少","空仓天数","空仓占比%"); _sep(6)
    for _yr_dp in sorted(_nav_idx_r.year.unique()):
        _yr_mask = _daily_pos_ser.index.year == _yr_dp
        _yr_vals = _daily_pos_ser[_yr_mask]
        if len(_yr_vals) == 0:
            continue
        _dp_mean  = float(_yr_vals.mean())
        _dp_max   = int(_yr_vals.max())
        _dp_min   = int(_yr_vals.min())
        _dp_zero  = int((_yr_vals == 0).sum())
        _dp_zerop = _dp_zero / len(_yr_vals) * 100
        _row(int(_yr_dp), f"{_dp_mean:.1f}", _dp_max, _dp_min, _dp_zero, f"{_dp_zerop:.0f}%")
    _blank()
    _dp_overall_mean = float(_daily_pos_ser.mean())
    _dp_overall_max  = int(_daily_pos_ser.max())
    _dp_zero_pct     = float((_daily_pos_ser == 0).mean()) * 100
    L.append(f"全期日均持仓：**{_dp_overall_mean:.1f} 只**  |  历史峰值：**{_dp_overall_max} 只**  |  "
             f"空仓天数占比：**{_dp_zero_pct:.1f}%**")
    _blank(); _hr()

    _h(2, "盈利来源：股票 vs ETF")
    _row("类别", "净盈亏", "占比"); _sep(3)
    _row("股票", f"${_s_pnl_r/1e6:.1f}M", f"{_s_pnl_r/_tot_pnl_r*100:.0f}%")
    _row("ETF",  f"${_e_pnl_r/1e6:.1f}M", f"{_e_pnl_r/_tot_pnl_r*100:.0f}%")
    _row("合计", f"${_tot_pnl_r/1e6:.1f}M", "100%")
    _blank(); _hr()

    # ── 完整指标对比表（对应页面"完整指标对比表"）────────────────────────────────
    _h(2, "完整指标对比表（策略1.0 vs SPY 买入持有）")

    def _pct_md(v, d=2): return f"{v*100:+.{d}f}%" if v is not None else "—"
    def _num_md(v, d=3): return f"{v:+.{d}f}" if v is not None else "—"
    def _days_md(v): return f"{int(v):,} 交易日（≈ {int(v)/252:.1f} 年）" if v is not None else "—"
    def _cnt_md(v): return f"{int(v):,}" if v is not None else "—"

    _sm_r = _spy_metrics
    _tov_r  = m.get("annual_turnover")
    _imp_cv = (_tov_r * (_slip_r + _comm_r) * 2 / 10_000) if _tov_r else None

    _full_rows = [
        ("**收益**", "", ""),
        ("CAGR", _pct_md(m.get("cagr")), _pct_md(_sm_r.get("spy_cagr"))),
        ("总回报率", _pct_md(m.get("total_return")), _pct_md(_sm_r.get("spy_total_return"))),
        ("**风险**", "", ""),
        ("年化波动率", _pct_md(m.get("annual_vol")), _pct_md(_sm_r.get("spy_annual_vol"))),
        ("最大回撤", _pct_md(m.get("max_drawdown")), _pct_md(_sm_r.get("spy_max_drawdown"))),
        ("最长回撤（天）", _days_md(m.get("max_dd_duration_days")), _days_md(_sm_r.get("spy_max_dd_duration_days"))),
        ("**风险收益**", "", ""),
        ("Sharpe 比率（rf=2%）", _num_md(m.get("sharpe")), _num_md(_sm_r.get("spy_sharpe"))),
        ("Sortino 比率", _num_md(m.get("sortino")), _num_md(_sm_r.get("spy_sortino"))),
        ("Calmar 比率", _num_md(m.get("calmar"), 3), _num_md(_sm_r.get("spy_calmar"), 3)),
        ("**交易统计**", "", ""),
        ("总交易笔数", _cnt_md(m.get("n_trades")), "—（买入持有）"),
        ("胜率", _pct_md(m.get("win_rate"), 1), "—（买入持有）"),
        ("平均盈利（R 倍数）", _num_md(m.get("avg_win_r"), 2), "—（买入持有）"),
        ("平均亏损（R 倍数）", _num_md(m.get("avg_loss_r"), 2), "—（买入持有）"),
        ("盈亏比（Profit Factor）", f"{m.get('profit_factor',0):.2f}" if m.get("profit_factor") else "—", "—（买入持有）"),
        ("平均持仓天数", f"{m.get('avg_holding_days',0):.0f} 天", "—（买入持有）"),
        ("交易频率", f"{m.get('trades_per_year',0):.0f} 笔/年", "—（买入持有）"),
        ("**换手率**", "", ""),
        ("年换手率", f"{_tov_r:.1f}x（{_tov_r*100:.0f}%/年）" if _tov_r else "—", "—（买入持有）"),
        ("隐含年化交易成本", f"≈ {_imp_cv*100:.2f}%/年（已含于回测）" if _imp_cv else "—", "—（买入持有）"),
        ("**仓位暴露**", "", ""),
        ("市场暴露率", f"{m.get('market_exposure',0)*100:.1f}%（持仓天数/总交易日）" if m.get("market_exposure") else "—", "100%（全仓持有）"),
    ]
    _row("指标", "策略1.0", "SPY 基准"); _sep(3)
    for _fr in _full_rows:
        _row(*_fr)
    _blank(); _hr()

    _h(2, "评估")
    _h(3, f"1. 绝对收益，但跑输 SPY 约 {abs(_cagr_gap_r)*100:.1f} 个百分点")
    L.append(f"在 {meta.backtest_start[:4]}–{meta.backtest_end[:4]} 约 {_bt_years_r:.0f} 年的回测期内，"
             f"策略1.0 CAGR **{_cagr_r*100:+.2f}%**，SPY **{_spy_cagr_r*100:+.2f}%**，差距 **{_cagr_gap_r*100:+.2f}%**。"
             f"$10M 初始资金净值增长 **{_total_ret_r:.2f} 倍**（期末约 ${_total_ret_r*10:.0f}M）。")
    _blank()
    _h(3, "2. 风险调整后 Sharpe 与 SPY 大体相当")
    L.append(f"Sharpe **{_sharpe_r:+.3f}** vs SPY **{_spy_sharpe_r:+.3f}**  |  "
             f"Sortino **{_sortino_r:+.3f}**  |  Calmar **{_calmar_r:+.3f}**")
    _blank()
    _h(3, f"3. 最大回撤 {abs(_maxdd_r)*100:.1f}% 是最突出优势")
    L.append(f"SPY 最大回撤 **{abs(_spy_maxdd_r)*100:.1f}%**，策略1.0仅 **{abs(_maxdd_r)*100:.1f}%**，"
             f"下行深度约为 SPY 的 **{_mddrat_r*100:.0f}%**。"
             f"最长水下时间 **{_maxdd_dur_r} 个交易日**（约 {_maxdd_dur_r/252:.1f} 年）。")
    _blank()
    _h(3, "4. 胜率低而盈亏比高，符合趋势跟踪数学结构")
    L.append(f"胜率 **{_wr_r*100:.1f}%**（趋势策略内在特征，非缺陷）。"
             f"平均盈利 **{_avg_win_r_r:+.2f}R**，平均亏损 **{abs(_avg_loss_r_r):.2f}R**，"
             f"Profit Factor **{_pf_r:.3f}**。大赢家（>5R）{_big5_r} 笔（{_big5p_r:.1f}%），最大单笔 **{_max_r_r:+.2f}R**。")
    _blank()
    _h(3, f"5. {_n_yr_r} 个完整年度中 {_pos_yr_r} 年正收益（{_pos_yr_r/_n_yr_r*100:.0f}%）")
    L.append(f"最差年份 **{_worst_yr_r} 年（{_worst_rt_r*100:+.1f}%）**，最好年份 **{_best_yr_r} 年（{_best_rt_r*100:+.1f}%）**。")
    _blank()
    _h(3, "6. 综合定位")
    _row("维度", "结论"); _sep(2)
    _row("绝对收益", f"CAGR {_cagr_r*100:+.2f}%，{_n_yr_r}年累计 {(_total_ret_r-1)*100:.0f}%，正期望明确")
    _row("相对收益", f"落后 SPY {abs(_cagr_gap_r)*100:.1f}%/年，长牛市中的结构性弱点")
    _row("回撤控制", f"MaxDD {abs(_maxdd_r)*100:.1f}% vs SPY {abs(_spy_maxdd_r)*100:.1f}%，下行保护突出")
    _row("风险效率", f"Sharpe {_sharpe_r:.3f} vs SPY {_spy_sharpe_r:.3f}，单位风险回报大体相当")
    _row("交易成本", f"{_impl_r:.2f}%/年，已计入净值，结论可信")
    _row("适用场景", "投资组合中的防御性趋势配置，而非替代 SPY 的进攻性资产")
    _blank(); _hr()

    _h(2, f"全部历史交易（共 {len(res.trades):,} 笔，按出场日降序）")
    _dl_c = ["ticker","entry_date","exit_date","holding_days",
             "entry_price","exit_price","shares","net_pnl","pnl_r_multiple","exit_reason"]
    _dl_c = [c for c in _dl_c if c in res.trades.columns]
    _col_zh = {"ticker":"标的","entry_date":"入场日","exit_date":"出场日","holding_days":"持仓天",
               "entry_price":"入场价","exit_price":"出场价","shares":"股数",
               "net_pnl":"净盈亏($)","pnl_r_multiple":"R倍数","exit_reason":"出场原因"}
    _row(*[_col_zh.get(c, c) for c in _dl_c]); _sep(len(_dl_c))
    for _, _tr in res.trades.sort_values("exit_date", ascending=False)[_dl_c].iterrows():
        def _fmt_cell(col, v):
            if col == "entry_date" or col == "exit_date":
                return str(v)[:10]
            if col == "holding_days" or col == "shares":
                return f"{int(v):,}"
            if col == "entry_price" or col == "exit_price":
                return f"{v:.4f}"
            if col == "net_pnl":
                return f"${v:+,.0f}"
            if col == "pnl_r_multiple":
                return f"{v:.4f}"
            return str(v)
        _row(*[_fmt_cell(c, _tr[c]) for c in _dl_c])
    _blank()

    return "\n".join(L)


_md_report = _build_md_report()

render_page_header("Baseline参数回测结果", meta)
_hdr_cap_col, _hdr_btn_col = st.columns([5, 1])
with _hdr_cap_col:
    st.caption(f"回测期间：{meta.backtest_start} → {meta.backtest_end}  ·  初始资金：$10,000,000")
with _hdr_btn_col:
    st.download_button(
        label="⬇ 下载报告(MD)",
        data=_md_report.encode("utf-8"),
        file_name=f"baseline_results_{meta.backtest_end[:10]}.md",
        mime="text/markdown",
    )
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
            "纯多头策略1.0遭受熊市的全部冲击，毫无对冲机制。<br>"
            "<strong>Strategy 2.0 将引入 SPY 200日均线过滤器以减少熊市回撤。</strong>"
        )
    st.markdown(f"""
<div class="warning-box">
<h4>⚠️ 关于低 CAGR 的说明</h4>
CAGR 仅 {cagr*100:.1f}%，主因是 2008 年金融危机期间
<strong>最大回撤达 {abs(m.get("max_drawdown",0))*100:.1f}%</strong>，导致长期的资金恢复期。
2010–2024 子区间 CAGR 约 6%，说明策略1.0本身在无极端熊市时仍有效。<br>
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
        "趋势策略1.0在强牛市年份（SPY 单边大涨）因持仓不满往往落后，"
        "但在下行年份（如 2008、2022）损失明显小于 SPY，体现了**截断亏损**的核心优势。"
    )
with _col2_r:
    _sharpe_tmp     = m.get("sharpe", 0)
    _spy_sharpe_tmp = m.get("spy_sharpe", 0)
    st.markdown(
        f"**解读：** 滚动 Sharpe 在 2008 年危机期间跌至深度负值，2010 年后趋于稳定并持续正值。"
        f"全周期 Sharpe **{_sharpe_tmp:+.3f}** vs SPY **{_spy_sharpe_tmp:+.3f}**，"
        "说明在单位风险维度上策略1.0与 SPY 大体相当，而非仅靠减少持仓频率规避风险。"
    )

st.markdown("---")

# ── Monthly return heatmap ────────────────────────────────────────────────────
st.subheader("月度收益热力图")
st.plotly_chart(monthly_return_heatmap(res.nav), use_container_width=True)

_nav_mh = res.nav.copy()
if not isinstance(_nav_mh.index, _pd_ar.DatetimeIndex):
    _nav_mh.index = _pd_ar.to_datetime(_nav_mh.index)
_monthly_mh  = _nav_mh.resample("ME").last().pct_change().dropna() * 100
_pos_m_cnt   = int((_monthly_mh > 0).sum())
_neg_m_cnt   = int((_monthly_mh <= 0).sum())
_best_m_val  = float(_monthly_mh.max())
_worst_m_val = float(_monthly_mh.min())
_best_m_dt   = _monthly_mh.idxmax()
_worst_m_dt  = _monthly_mh.idxmin()
st.markdown(
    f"**解读：** {_pos_m_cnt + _neg_m_cnt} 个月中 **{_pos_m_cnt}** 个月正收益（{_pos_m_cnt/(_pos_m_cnt+_neg_m_cnt)*100:.0f}%）。"
    f"最好月份 **{_best_m_dt.strftime('%Y年%m月')}（{_best_m_val:+.1f}%）**，"
    f"最差月份 **{_worst_m_dt.strftime('%Y年%m月')}（{_worst_m_val:+.1f}%）**。"
    "热力图可直观识别季节性规律：红色集中区域（如某季度持续亏损）是策略1.0改进的潜在方向。"
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
**解读：** 胜率 {win_rate*100:.1f}% 看似低，但这是趋势跟踪策略1.0的**正常特征**。
关键在于平均盈利（{avg_win:+.2f}R）远大于平均亏损（{avg_loss:.2f}R），
盈亏比 {pf:.4f} > 1，期望值为正。右侧长尾（大盈利交易）是策略1.0盈利的核心来源。
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

> 趋势跟踪策略的换手率通常在每年 500%–2,000%，本策略 {turnover*100:.0f}% 处于正常范围。
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
        "年度笔数的波动反映的是市场状态变化，而非策略1.0本身不稳定。"
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
    f"持仓数目随市场环境的起伏变化，体现了策略1.0在不同市场条件下的动态参与度。"
)

st.markdown("---")

# ── Profit by type: stock vs ETF ──────────────────────────────────────────────
st.subheader("策略1.0盈利来源：股票 vs ETF")
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
render_full_metrics_table(m, _spy_metrics)

st.markdown("---")

# ── Trade summary ─────────────────────────────────────────────────────────────
_trade_hdr_col, _trade_btn_col = st.columns([5, 1])
with _trade_hdr_col:
    st.subheader("交易样本")
with _trade_btn_col:
    _dl_cols = ["ticker", "entry_date", "exit_date", "holding_days",
                "entry_price", "exit_price", "shares", "net_pnl",
                "pnl_r_multiple", "exit_reason"]
    _dl_cols = [c for c in _dl_cols if c in res.trades.columns]
    _all_trades_dl = (
        res.trades.sort_values("exit_date", ascending=False)[_dl_cols]
        .rename(columns={
            "ticker":         "标的",
            "entry_date":     "入场日",
            "exit_date":      "出场日",
            "holding_days":   "持仓天",
            "entry_price":    "入场价",
            "exit_price":     "出场价",
            "shares":         "股数",
            "net_pnl":        "净盈亏($)",
            "pnl_r_multiple": "R倍数",
            "exit_reason":    "出场原因",
        })
    )
    st.download_button(
        label="⬇ 下载全部交易",
        data=_all_trades_dl.to_csv(index=False).encode("utf-8"),
        file_name="all_trades.csv",
        mime="text/csv",
    )
n_show = st.slider("显示交易笔数", 10, 100, 20, 10)
trades_display = res.trades.sort_values("exit_date", ascending=False).head(n_show).copy()
_td_cols = ["ticker", "entry_date", "exit_date", "holding_days",
            "entry_price", "exit_price", "shares", "net_pnl",
            "pnl_r_multiple", "exit_reason"]
_td_cols = [c for c in _td_cols if c in trades_display.columns]
trades_display = trades_display[_td_cols].rename(columns={
    "ticker":         "标的",
    "entry_date":     "入场日",
    "exit_date":      "出场日",
    "holding_days":   "持仓天",
    "entry_price":    "入场价",
    "exit_price":     "出场价",
    "shares":         "股数",
    "net_pnl":        "净盈亏($)",
    "pnl_r_multiple": "R 倍数",
    "exit_reason":    "出场原因",
})
if "净盈亏($)" in trades_display.columns:
    trades_display["净盈亏($)"] = trades_display["净盈亏($)"].apply(
        lambda v: f"${v:+,.0f}"
    )
st.dataframe(trades_display, use_container_width=True, hide_index=True)

# ── Streak analysis ───────────────────────────────────────────────────────────
import json as _json_br
_DIAG_PATH_BR = Path(__file__).resolve().parents[2] / "results" / "v1" / "diagnostics.json"

st.markdown("---")
st.subheader("连续亏损序列分析（基于baseline参数得到的历史回测交易）")

if _DIAG_PATH_BR.exists():
    import plotly.graph_objects as _go_br

    _diag_br = _json_br.loads(_DIAG_PATH_BR.read_text(encoding="utf-8"))
    _sa_br   = _diag_br.get("streak_analysis", {})
    _streak_counts_br: dict = _sa_br.get("streak_counts", {})

    if _streak_counts_br:
        _x_labels_br: list[str] = []
        _y_counts_br: list[int] = []
        _bar_colors_br: list[str] = []

        for _length_br in range(1, 10):
            _x_labels_br.append(str(_length_br))
            _y_counts_br.append(_streak_counts_br.get(str(_length_br), 0))
            if _length_br <= 4:
                _bar_colors_br.append("#2ca02c")
            else:
                _bar_colors_br.append("#f57c00")

        _x_labels_br.append("≥10")
        _y_counts_br.append(_streak_counts_br.get("10+", 0))
        _bar_colors_br.append("#d62728")

        _fig_streak = _go_br.Figure(
            data=[_go_br.Bar(
                x=_x_labels_br,
                y=_y_counts_br,
                marker_color=_bar_colors_br,
                text=_y_counts_br,
                textposition="outside",
            )]
        )
        _fig_streak.update_layout(
            title="历史连续亏损序列分布",
            xaxis_title="连续亏损笔数",
            yaxis_title="出现次数",
            showlegend=False,
            height=360,
            margin=dict(t=50, b=40, l=40, r=20),
        )
        st.plotly_chart(_fig_streak, use_container_width=True)

    _sc1, _sc2, _sc3 = st.columns(3)
    _sc1.metric("最长连续亏损（笔）", _sa_br.get("max_consecutive_losses", 0))
    _sc2.metric("总亏损序列数",       _sa_br.get("total_streaks", 0))
    _sc3.metric("平均序列长度",       f"{_sa_br.get('avg_streak_length', 0.0):.2f}")

    _max_cl_br = _sa_br.get("max_consecutive_losses", 0)
    st.markdown(
        f'<div class="info-box">'
        f'在 38% 胜率下，随机期望每隔约 2.6 笔交易出现一次亏损连续段。'
        f'最长 <strong>{_max_cl_br} 笔</strong>连续亏损是心理上最难承受的时刻，'
        f'但从统计上看并不异常。'
        f'</div>',
        unsafe_allow_html=True,
    )
else:
    st.info("连续亏损数据尚未生成。运行：python src/scripts/04_run_diagnostics.py")

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
_bt_years     = (_nav_s.index[-1] - _nav_s.index[0]).days / 365.25  # actual backtest duration
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
            _big_strs.append(f"{_y}年（策略1.0 {_r*100:.1f}%{_spy_suffix}）")
        _nd_parts.append(
            f"{len(_big_loss)} 年出现较大亏损（≤ -10%）：" + "、".join(_big_strs)
        )
    _neg_yr_desc = "；".join(_nd_parts) + "。"
else:
    _neg_yr_desc = "历史回测中无负收益年份。"

st.markdown(f"""
**1. 绝对收益可观，但跑输 SPY 约 {abs(_cagr_gap)*100:.1f} 个百分点**

在 {meta.backtest_start[:4]}–{meta.backtest_end[:4]} 约 {_bt_years:.0f} 年的回测期内，
策略1.0 CAGR **{_cagr*100:+.2f}%**，同期 SPY 为 **{_spy_cagr*100:+.2f}%**，差距 **{_cagr_gap*100:+.2f}%**。
以 $10M 初始资金计算，净值增长 **{_total_ret:.2f} 倍**（期末约 ${_total_ret*10:.0f}M）。
跑输 SPY 是这份结果最直接的弱点，也是向任何潜在投资者解释时需要正面回答的第一个问题。
对此的核心回答是：**SPY 在相同时间内最大回撤 {abs(_spy_maxdd)*100:.1f}%，而策略1.0最大回撤仅 {abs(_maxdd)*100:.1f}%**——
收益更低，但承受的风险断崖式下降。

**2. Sharpe 轻微领先 SPY，风险调整后有竞争力**

策略1.0 Sharpe **{_sharpe:+.3f}** vs SPY **{_spy_sharpe:+.3f}**，差距微小但方向有利。
Sortino **{_sortino:+.3f}**（对下行波动的惩罚更严格），Calmar **{_calmar:+.3f}**（CAGR / MaxDD）。
这三个指标共同说明：在单位风险维度上，策略1.0与 SPY 大体相当，
并非用大幅更低的风险调整收益换来了更低的绝对回撤——而是在**基本等效的风险效率下**，
大幅压缩了最大回撤的绝对深度。

**3. 最大回撤 {abs(_maxdd)*100:.1f}% 是策略1.0最突出的实际优势**

SPY 在回测期内最大回撤高达 **{abs(_spy_maxdd)*100:.1f}%**（2008–2009 金融危机），
策略1.0同期最大回撤仅 **{abs(_maxdd)*100:.1f}%**，下行深度约为 SPY 的 **{_maxdd_ratio*100:.0f}%**。
最长水下时间 **{_maxdd_dur} 个交易日**（约 {_maxdd_dur/252:.1f} 年）。
对于以保全本金为前提的机构资金而言，这一差距具有实质意义：
**{abs(_spy_maxdd)*100:.0f}%** 的跌幅需要涨 **{(1/(1-min(abs(_spy_maxdd),0.99))-1)*100:.0f}%** 才能回本，而策略1.0 **{abs(_maxdd)*100:.0f}%** 仅需涨 **{(1/(1-min(abs(_maxdd),0.99))-1)*100:.0f}%**。

**4. 胜率低而盈亏比高，符合趋势跟踪的数学结构**

胜率 **{_wr*100:.1f}%** 在表观上偏低，但这是趋势策略的内在特征，而非缺陷。
盈利交易平均 **{_avg_win_r:+.2f}R**，亏损交易平均 **{abs(_avg_loss_r):.2f}R**，
Profit Factor **{_pf:.3f}**——每亏 1 元预期赚回 {_pf:.2f} 元。
在 {_n_trades:,} 笔交易中，超过 5R 的大赢家 {_big5r} 笔（占比 {_big5r_pct:.1f}%），
最大单笔 **{_max_r:+.2f}R**。
**大赢家的右尾贡献是策略1.0盈利的核心来源**——不能因为胜率偏低就轻易判断策略1.0无效。

**5. 年度表现稳定，{_n_years} 年中 {_pos_years} 年正收益（{_pos_years/_n_years*100:.0f}%）**

{_n_years} 个完整年度中，{_pos_years} 年正收益，{_neg_years} 年负收益。
最差年份 **{_worst_yr} 年（{_worst_ret*100:+.1f}%）**，最好年份 **{_best_yr} 年（{_best_ret*100:+.1f}%）**。
{_neg_yr_desc}
这种"负收益年份损失可控、正收益年份收益可观"的结构，
是趋势策略长期正复利的基础。

**6. 交易成本与换手率处于合理区间**

年换手率 **{_turnover:.2f}x**，隐含年化交易摩擦约 **{_implied_cost:.2f}%**，
已完整计入回测净值。市场暴露率 **{_exposure*100:.1f}%**（约 {100-_exposure*100:.1f}% 时间现金转入 SHY），
说明策略1.0全年大部分时间有仓位，并非依赖少数几笔交易的偶然发挥。

**7. 策略1.0定位的准确理解**
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
        f"策略1.0的核心价值在于**用约 {abs(_cagr_gap)*100:.1f}% 的年化收益损失，换取约 {(abs(_spy_maxdd)-abs(_maxdd))*100:.1f}% 的最大回撤保护**，"
        f"是风险厌恶型投资者在权益资产中最值得考虑的量化选项之一。"
    )
elif _cagr > 0.05:
    verdict_icon = "🟡"
    verdict_body = (
        f"综合评价：结果整体可接受，CAGR {_cagr*100:+.2f}%，但 Sharpe 或回撤控制仍有提升空间。"
    )
else:
    verdict_icon = "⚠️"
    verdict_body = f"综合评价：CAGR {_cagr*100:+.2f}% 偏低，需审查策略1.0参数或回测设置。"

st.markdown(
    f'<div class="info-box"><strong>{verdict_icon} {verdict_body}</strong></div>',
    unsafe_allow_html=True,
)
