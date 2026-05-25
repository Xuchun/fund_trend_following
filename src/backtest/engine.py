"""
BacktestEngine: event-driven daily loop for Strategy 1.0.

Each calendar day processes events in this strict order:

  ① Open  — execute yesterday's exit and entry orders at today's open price.
  ② Cash  — apply SGOV return to uninvested cash (end-of-open approximation).
  ③ Close — generate new exit/entry signals from today's close.
  ④ NAV   — mark all positions to close prices, record daily NAV.

Signals generated on day t are executed on day t+1.  No look-ahead.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from backtest.execution import apply_gap_filter, compute_commission, compute_fill_price
from backtest.portfolio import Portfolio
from backtest.position import Position
from backtest.results import BacktestResults
from strategy.v1.sizing import compute_position_size

if TYPE_CHECKING:
    from strategy.base import BaseStrategy
    from strategy.params import StrategyParams

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Main backtest controller.

    Usage
    -----
    engine  = BacktestEngine(strategy, price_panel, indicators, params)
    results = engine.run("2010-01-01", "2023-12-31", universe)
    print(results.summary())
    """

    def __init__(
        self,
        strategy: "BaseStrategy",
        price_panel: dict[str, pd.DataFrame],
        indicators: dict[str, dict],
        params: "StrategyParams",
        initial_capital: float = 10_000_000,
    ) -> None:
        self.strategy        = strategy
        self.price_panel     = price_panel
        self.indicators      = indicators
        self.params          = params
        self.initial_capital = initial_capital
        self._regime         = self._build_regime_series()

    # ── Public API ──────────────────────────────────────────────────────────

    def run(
        self,
        start: str,
        end: str,
        universe: list[str],
    ) -> BacktestResults:
        """
        Run the backtest over [start, end] and return results.

        Args:
            start:    Start date "YYYY-MM-DD" (inclusive).
            end:      End date "YYYY-MM-DD" (inclusive).
            universe: List of tickers to scan for entries each day.

        Returns:
            BacktestResults with daily_nav, daily_returns, trade_log.
        """
        start_ts = pd.Timestamp(start)
        end_ts   = pd.Timestamp(end)

        trading_dates = self._get_trading_dates(start_ts, end_ts)
        if not trading_dates:
            raise ValueError(f"No trading dates found in [{start}, {end}]")

        logger.info(
            "Backtest: %s → %s  (%d days, %d tickers in universe)",
            start, end, len(trading_dates), len(universe),
        )

        portfolio = Portfolio(self.initial_capital)
        sgov_returns = self._build_sgov_returns(trading_dates)
        log_returns  = {
            t: self.indicators[t]["log_returns"]
            for t in self.indicators
        }

        pending_exits:   list[dict] = []
        pending_entries: list[dict] = []
        last_nav = float(self.initial_capital)

        for date in trading_dates:

            # ── ① OPEN: execute yesterday's orders ─────────────────────────
            carried_exits: list[dict] = []
            for sig in pending_exits:
                executed = self._execute_exit(sig, date, portfolio)
                if not executed:
                    carried_exits.append(sig)   # no open price today; retry next day
            pending_exits = carried_exits

            for sig in pending_entries:
                self._execute_entry(sig, date, portfolio, log_returns, last_nav)
            pending_entries = []

            # ── ② CASH: apply SGOV return to uninvested cash ────────────────
            sgov_ret = sgov_returns.get(date, 0.0)
            portfolio.cash *= (1.0 + sgov_ret)

            # ── ③ CLOSE: generate new signals from today's close ────────────
            pending_exits = self.strategy.generate_exit_signals(
                date, portfolio, self.price_panel, self.indicators
            )

            # Regime filter: block new entries when SPY ≤ its 200-day SMA.
            # Existing positions are NOT touched; cash continues to earn the proxy rate.
            in_bull = self._is_bull_market(date)
            if in_bull:
                pending_entries = self.strategy.generate_entry_signals(
                    date, universe, self.price_panel, self.indicators, portfolio
                )
            else:
                pending_entries = []

            # ── ④ NAV: mark-to-market at today's close ──────────────────────
            last_nav = portfolio.update_nav(date, self.price_panel)

        # ── End of loop: close all remaining positions at last date's close ──
        last_date = trading_dates[-1]
        self._close_all_at_end(last_date, portfolio)
        # Re-record final NAV after forced liquidation
        portfolio.update_nav(last_date, self.price_panel)
        # Remove the duplicate NAV entry (last_date was already added in loop)
        if len(portfolio.nav_history) > 1 and portfolio.nav_history[-2][0] == last_date:
            portfolio.nav_history.pop(-2)

        return self._build_results(portfolio)

    # ── Execution helpers ───────────────────────────────────────────────────

    def _execute_exit(
        self,
        signal: dict,
        date: pd.Timestamp,
        portfolio: Portfolio,
    ) -> bool:
        """
        Execute an exit order at today's open price.

        Returns True if executed, False if no open price is available.
        """
        ticker = signal["ticker"]

        if ticker not in portfolio.positions:
            return True  # already closed (e.g., duplicate signal)

        df = self.price_panel.get(ticker)
        if df is None or date not in df.index:
            logger.debug("Exit %s: no open price on %s, carrying to next day", ticker, date.date())
            return False  # will retry next trading day

        open_price = float(df.at[date, "open"])
        fill_price = compute_fill_price(open_price, "sell", self.params.slippage_bps)
        commission = compute_commission(fill_price, portfolio.positions[ticker].shares,
                                        self.params.commission_bps)
        portfolio.close_position(ticker, date, fill_price, signal["reason"], commission)
        return True

    def _execute_entry(
        self,
        signal: dict,
        date: pd.Timestamp,
        portfolio: Portfolio,
        log_returns: dict[str, pd.Series],
        last_nav: float,
    ) -> None:
        """
        Attempt to execute an entry order at today's open price.

        Applies gap filter, recomputes stop/trail using actual fill price,
        then runs position sizing before committing.
        """
        ticker = signal["ticker"]

        # Already holding this ticker (could happen if yesterday we opened it)
        if ticker in portfolio.positions:
            return

        df = self.price_panel.get(ticker)
        if df is None or date not in df.index:
            return

        row = df.loc[date]
        if not bool(row["is_tradable"]):
            return

        open_price   = float(row["open"])
        signal_close = signal["signal_close"]

        # ── Gap filter ──────────────────────────────────────────────────────
        if not apply_gap_filter(signal_close, open_price, self.params.gap_filter):
            logger.debug(
                "Entry %s rejected: gap %.2f%% > %.2f%%",
                ticker,
                abs(open_price - signal_close) / signal_close * 100,
                self.params.gap_filter * 100,
            )
            return

        # ── Fill price (slippage) ────────────────────────────────────────────
        entry_price = compute_fill_price(open_price, "buy", self.params.slippage_bps)

        # ── Recompute stop & trail based on actual fill ──────────────────────
        atr       = signal["atr"]
        stop_loss = entry_price - self.params.stop_loss_multiplier * atr
        if stop_loss >= entry_price:
            return  # degenerate: stop above/at entry

        trail_stop = entry_price - self.params.trail_multiplier_r1 * atr

        # ── Position sizing ──────────────────────────────────────────────────
        nav = last_nav if last_nav > 0 else self.initial_capital
        shares = compute_position_size(
            entry_price=entry_price,
            stop_loss=stop_loss,
            nav=nav,
            existing_risk=portfolio.existing_risk,
            current_positions=list(portfolio.positions.keys()),
            log_returns=log_returns,
            new_ticker=ticker,
            as_of_date=date,
            params=self.params,
        )
        if shares is None:
            return

        # ── Cash check ───────────────────────────────────────────────────────
        commission = compute_commission(entry_price, shares, self.params.commission_bps)
        total_cost = shares * entry_price + commission
        if total_cost > portfolio.cash:
            logger.debug(
                "Entry %s skipped: cost=%.0f > cash=%.0f",
                ticker, total_cost, portfolio.cash,
            )
            return

        # ── Open position ────────────────────────────────────────────────────
        position = Position(
            ticker=ticker,
            entry_date=date,
            entry_price=entry_price,
            shares=shares,
            stop_loss=stop_loss,
            trail_stop=trail_stop,
            highest_high=entry_price,
            atr_at_entry=atr,
        )
        portfolio.open_position(position, commission)

    # ── End-of-backtest liquidation ─────────────────────────────────────────

    def _close_all_at_end(
        self,
        date: pd.Timestamp,
        portfolio: Portfolio,
    ) -> None:
        """
        Close all remaining positions at the last day's close price.
        Tagged as 'end_of_backtest' in the trade log.
        """
        for ticker in list(portfolio.positions.keys()):
            pos = portfolio.positions[ticker]
            df  = self.price_panel.get(ticker)
            if df is not None and date in df.index:
                close_price = float(df.at[date, "close"])
            else:
                close_price = pos.entry_price  # fallback: no gain/loss

            commission = compute_commission(close_price, pos.shares, self.params.commission_bps)
            portfolio.close_position(ticker, date, close_price, "end_of_backtest", commission)

    # ── Utility ─────────────────────────────────────────────────────────────

    def _get_trading_dates(
        self,
        start_ts: pd.Timestamp,
        end_ts: pd.Timestamp,
    ) -> list[pd.Timestamp]:
        """
        Return sorted list of dates present in at least one ticker's price panel,
        within [start_ts, end_ts].
        """
        all_dates: set[pd.Timestamp] = set()
        for df in self.price_panel.values():
            all_dates.update(df.index.tolist())
        return sorted(d for d in all_dates if start_ts <= d <= end_ts)

    def _build_sgov_returns(
        self,
        trading_dates: list[pd.Timestamp],
    ) -> dict[pd.Timestamp, float]:
        """
        Build a dict of {date: daily_return} for the cash proxy (SGOV).

        Uses adjusted close (close × adj_factor) to capture the interest income.
        Returns an empty dict if SGOV is not in the price panel (cash earns 0%).
        """
        proxy = self.params.cash_proxy
        if proxy not in self.price_panel:
            logger.warning(
                "Cash proxy '%s' not in price panel; cash earns 0%% return.", proxy
            )
            return {}

        df   = self.price_panel[proxy]
        adj  = df["close"] * df["adj_factor"]
        rets = adj.pct_change().dropna()

        date_set = set(trading_dates)
        return {d: float(r) for d, r in rets.items() if d in date_set}

    def _build_results(self, portfolio: Portfolio) -> BacktestResults:
        """Assemble BacktestResults from a completed portfolio run."""
        nav_series = pd.Series(
            {date: nav for date, nav in portfolio.nav_history},
            name="nav",
            dtype=float,
        )
        nav_series.index.name = "date"

        returns = nav_series.pct_change()
        returns.iloc[0] = 0.0   # first day has no prior NAV

        trade_log = portfolio.to_trade_log()

        return BacktestResults(
            params=self.params,
            daily_nav=nav_series,
            daily_returns=returns,
            trade_log=trade_log,
            initial_capital=self.initial_capital,
        )
