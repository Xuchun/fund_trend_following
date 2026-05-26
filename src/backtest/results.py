"""
BacktestResults: container for a completed backtest run.

Stores daily NAV, daily returns, and the full trade log.
compute_metrics() provides a basic summary; Phase 6 will expand this
by delegating to analysis/metrics.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from strategy.params import StrategyParams


@dataclass
class BacktestResults:
    """
    Complete output of a single backtest run.

    Fields
    ------
    params          : StrategyParams used for this run.
    daily_nav       : pd.Series (index=date, value=NAV in USD).
    daily_returns   : pd.Series (index=date, value=daily return fraction).
    trade_log       : pd.DataFrame — one row per completed trade.
    initial_capital : Starting NAV (used for CAGR denominator).
    """

    params: "StrategyParams"
    daily_nav: pd.Series
    daily_returns: pd.Series
    trade_log: pd.DataFrame
    initial_capital: float

    # ── Public API ──────────────────────────────────────────────────────────

    def compute_metrics(
        self,
        benchmark_returns: pd.Series | None = None,
        risk_free_rate: float = 0.02,
    ) -> dict:
        """
        Compute a summary of key performance indicators.

        Returns a dict with the following keys:
          cagr, total_return, annual_vol, max_drawdown, max_dd_duration_days,
          sharpe, sortino, calmar,
          n_trades, win_rate, avg_win_r, avg_loss_r, profit_factor,
          avg_holding_days, trades_per_year.

        Phase 6 will replace this with a full call to analysis/metrics.py.
        """
        nav = self.daily_nav
        ret = self.daily_returns
        tl  = self.trade_log

        n_days = len(nav)
        metrics: dict = {}

        # ── Return metrics ─────────────────────────────────────────────────
        final_nav = float(nav.iloc[-1]) if n_days > 0 else self.initial_capital
        total_return = (final_nav / self.initial_capital) - 1.0
        metrics["total_return"] = total_return

        if n_days > 1:
            metrics["cagr"] = (final_nav / self.initial_capital) ** (252.0 / n_days) - 1.0
        else:
            metrics["cagr"] = 0.0

        # ── Risk metrics ───────────────────────────────────────────────────
        annual_vol = float(ret.std() * math.sqrt(252)) if len(ret) > 1 else 0.0
        metrics["annual_vol"] = annual_vol

        # Max drawdown
        cum_max = nav.cummax()
        dd = (nav - cum_max) / cum_max
        metrics["max_drawdown"] = float(dd.min())

        # Max drawdown duration (consecutive days below peak)
        in_dd = dd < 0
        max_dur = 0
        cur_dur = 0
        for v in in_dd:
            if v:
                cur_dur += 1
                max_dur = max(max_dur, cur_dur)
            else:
                cur_dur = 0
        metrics["max_dd_duration_days"] = max_dur

        # Avg duration of deep-drawdown episodes (drawdown continuously > 10%)
        DEEP_DD_THRESHOLD = -0.10
        in_deep = dd < DEEP_DD_THRESHOLD
        deep_segs: list[int] = []
        seg_start: int | None = None
        for i, v in enumerate(in_deep):
            if v and seg_start is None:
                seg_start = i
            elif not v and seg_start is not None:
                deep_segs.append(i - seg_start)
                seg_start = None
        if seg_start is not None:
            deep_segs.append(len(in_deep) - seg_start)
        metrics["avg_deep_dd_duration_days"] = (
            float(sum(deep_segs) / len(deep_segs)) if deep_segs else 0.0
        )
        metrics["n_deep_dd_episodes"] = len(deep_segs)

        # ── Risk-adjusted metrics ──────────────────────────────────────────
        mean_ret = float(ret.mean()) if len(ret) > 0 else 0.0
        rf_daily = risk_free_rate / 252

        if annual_vol > 0:
            metrics["sharpe"] = (mean_ret * 252 - risk_free_rate) / annual_vol
        else:
            metrics["sharpe"] = 0.0

        downside = ret[ret < rf_daily]
        down_vol = float(downside.std() * math.sqrt(252)) if len(downside) > 1 else 0.0
        if down_vol > 0:
            metrics["sortino"] = (mean_ret * 252 - risk_free_rate) / down_vol
        else:
            metrics["sortino"] = 0.0

        max_dd = abs(metrics["max_drawdown"])
        metrics["calmar"] = metrics["cagr"] / max_dd if max_dd > 1e-9 else 0.0

        # ── Trade statistics ───────────────────────────────────────────────
        n_trades = len(tl)
        metrics["n_trades"] = n_trades

        if n_trades > 0:
            wins   = tl[tl["net_pnl"] > 0]
            losses = tl[tl["net_pnl"] <= 0]

            metrics["win_rate"] = len(wins) / n_trades

            avg_win_r  = float(tl.loc[tl["net_pnl"] > 0,  "pnl_r_multiple"].mean()) \
                         if len(wins) > 0 else 0.0
            avg_loss_r = float(tl.loc[tl["net_pnl"] <= 0, "pnl_r_multiple"].mean()) \
                         if len(losses) > 0 else 0.0
            metrics["avg_win_r"]  = avg_win_r
            metrics["avg_loss_r"] = avg_loss_r

            total_wins   = float(wins["net_pnl"].sum())   if len(wins)   > 0 else 0.0
            total_losses = float(losses["net_pnl"].abs().sum()) if len(losses) > 0 else 1e-9
            metrics["profit_factor"] = total_wins / total_losses if total_losses > 0 else 0.0

            metrics["avg_holding_days"] = float(tl["holding_days"].mean())
            years = n_days / 252
            metrics["trades_per_year"]  = n_trades / years if years > 0 else 0.0
        else:
            metrics.update({
                "win_rate": 0.0, "avg_win_r": 0.0, "avg_loss_r": 0.0,
                "profit_factor": 0.0, "avg_holding_days": 0.0, "trades_per_year": 0.0,
            })

        # ── Portfolio turnover ─────────────────────────────────────────────
        # Annual Turnover = total buy value / (avg NAV × years)
        # Measures how many times the portfolio is "turned over" each year.
        # Example: 12.5 means the portfolio's full value is bought/sold 12.5× per year.
        if (n_trades > 0 and n_days > 0
                and "entry_price" in tl.columns and "shares" in tl.columns):
            total_buy_value = float((tl["entry_price"] * tl["shares"]).sum())
            avg_nav_value   = float(self.daily_nav.mean())
            n_years_turn    = n_days / 252
            if avg_nav_value > 0 and n_years_turn > 0:
                metrics["annual_turnover"] = total_buy_value / (avg_nav_value * n_years_turn)
            else:
                metrics["annual_turnover"] = 0.0
        else:
            metrics["annual_turnover"] = 0.0

        return metrics

    def to_dict(self) -> dict:
        """
        Serialize results to a plain dict (for multiprocessing result collection).
        """
        return {
            "daily_nav":     self.daily_nav.to_dict(),
            "daily_returns": self.daily_returns.to_dict(),
            "trade_log":     self.trade_log.to_dict(orient="records"),
            "initial_capital": self.initial_capital,
            "metrics":       self.compute_metrics(),
        }

    def summary(self) -> str:
        """Return a human-readable one-page summary."""
        m = self.compute_metrics()
        tl = self.trade_log
        nav = self.daily_nav

        lines = [
            "=" * 55,
            "回测结果摘要",
            "=" * 55,
            f"  回测期间:   {nav.index[0].date()} → {nav.index[-1].date()}",
            f"  初始资金:   ${self.initial_capital:>14,.0f}",
            f"  最终 NAV:   ${float(nav.iloc[-1]):>14,.0f}",
            "",
            "  ── 收益 ──────────────────────────────────",
            f"  总收益率:   {m['total_return']:>+.2%}",
            f"  CAGR:       {m['cagr']:>+.2%}",
            "",
            "  ── 风险 ──────────────────────────────────",
            f"  年化波动率: {m['annual_vol']:.2%}",
            f"  最大回撤:   {m['max_drawdown']:.2%}",
            f"  最长回撤:   {m['max_dd_duration_days']} 天",
            "",
            "  ── 风险收益 ──────────────────────────────",
            f"  Sharpe:     {m['sharpe']:.3f}",
            f"  Sortino:    {m['sortino']:.3f}",
            f"  Calmar:     {m['calmar']:.3f}",
            "",
            "  ── 交易统计 ──────────────────────────────",
            f"  总交易数:   {m['n_trades']}",
            f"  胜率:       {m['win_rate']:.1%}",
            f"  平均盈利 R: {m['avg_win_r']:>+.2f}",
            f"  平均亏损 R: {m['avg_loss_r']:>+.2f}",
            f"  盈亏比:     {m['profit_factor']:.2f}",
            f"  平均持仓:   {m['avg_holding_days']:.0f} 天",
        ]

        if len(tl) > 0:
            lines += [
                "",
                "  ── 平仓原因 ──────────────────────────────",
            ]
            for reason, cnt in tl["exit_reason"].value_counts().items():
                lines.append(f"  {reason:<22} {cnt:>4} 次  ({cnt/len(tl):.1%})")

        lines.append("=" * 55)
        return "\n".join(lines)
