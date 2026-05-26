"""
BacktestResults: container for a completed backtest run.

Stores daily NAV, daily returns, and the full trade log.
compute_metrics() delegates to analysis/metrics.py (Phase 6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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
        Compute all core performance indicators.

        Delegates to analysis.metrics.compute_metrics() — Phase 6 implementation.
        The `benchmark_returns` parameter is accepted for API compatibility but
        benchmark stats (spy_cagr, spy_sharpe, spy_max_drawdown) are computed
        separately in reports/baseline.py where raw SPY data is available.
        """
        from analysis.metrics import compute_metrics as _compute  # noqa: PLC0415
        return _compute(
            daily_nav=self.daily_nav,
            daily_returns=self.daily_returns,
            trade_log=self.trade_log,
            initial_capital=self.initial_capital,
            risk_free_rate=risk_free_rate,
        )

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
