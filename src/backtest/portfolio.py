"""
Portfolio: manages cash, open positions, NAV history, and trade log.

Responsibilities:
  - open_position(): deduct cash, record position.
  - close_position(): add cash proceeds, append to trade_log.
  - update_nav(): mark-to-market at close prices, append to nav_history.
  - existing_risk property: live heat calculation used by sizing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from backtest.position import Position

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """Immutable record of one completed round-trip trade."""

    ticker: str
    entry_date: pd.Timestamp
    entry_price: float       # fill price (slippage applied)
    exit_date: pd.Timestamp
    exit_price: float        # fill price (slippage applied)
    shares: int
    stop_loss: float
    atr_at_entry: float
    R: float                 # entry_price - stop_loss (risk per share)
    exit_reason: str         # 'stop_loss' | 'trailing_stop' | 'end_of_backtest'
    entry_commission: float
    exit_commission: float

    @property
    def holding_days(self) -> int:
        return (self.exit_date - self.entry_date).days

    @property
    def gross_pnl(self) -> float:
        """Price-gain PnL before commissions."""
        return (self.exit_price - self.entry_price) * self.shares

    @property
    def net_pnl(self) -> float:
        """PnL after all commissions."""
        return self.gross_pnl - self.entry_commission - self.exit_commission

    @property
    def pnl_r_multiple(self) -> float:
        """
        Unrealised/realised gain in units of initial risk R.
        Negative means a loss; -1.0 is a textbook 1R stop-loss.
        """
        if self.R <= 0:
            return 0.0
        return (self.exit_price - self.entry_price) / self.R

    @property
    def gap_adjusted_loss_multiple(self) -> float:
        """
        Same as pnl_r_multiple but named for the loss-analysis context.
        Useful for stop_loss exits: tells you whether the gap made the
        actual loss worse than the intended -1R.
        """
        return self.pnl_r_multiple


class Portfolio:
    """
    Manages all portfolio state for one backtest run.

    Not thread-safe; one Portfolio per BacktestEngine instance.
    """

    def __init__(self, initial_capital: float) -> None:
        self.cash: float = initial_capital
        self.initial_capital: float = initial_capital
        self.positions: dict[str, Position] = {}
        self.nav_history: list[tuple[pd.Timestamp, float]] = []
        self.trade_records: list[TradeRecord] = []
        self._entry_commissions: dict[str, float] = {}  # ticker → commission at entry

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def existing_risk(self) -> float:
        """Sum of risk_amount across all open positions (used for heat check)."""
        return sum(p.risk_amount for p in self.positions.values())

    @property
    def last_nav(self) -> float:
        """Most recently recorded NAV (or initial_capital before first update)."""
        if self.nav_history:
            return self.nav_history[-1][1]
        return self.initial_capital

    # ── Core operations ─────────────────────────────────────────────────────

    def open_position(self, position: Position, commission: float) -> None:
        """
        Record a new long position and deduct the cost from cash.

        cost = position.shares × position.entry_price + commission
        """
        cost = position.shares * position.entry_price + commission
        if cost > self.cash:
            logger.warning(
                "Insufficient cash for %s: need %.0f, have %.0f — skipping",
                position.ticker, cost, self.cash,
            )
            return
        self.cash -= cost
        self.positions[position.ticker] = position
        self._entry_commissions[position.ticker] = commission
        logger.debug(
            "OPEN  %s: %d shares @ %.4f  stop=%.4f  cost=%.0f",
            position.ticker, position.shares, position.entry_price,
            position.stop_loss, cost,
        )

    def close_position(
        self,
        ticker: str,
        exit_date: pd.Timestamp,
        exit_price: float,
        reason: str,
        commission: float,
    ) -> TradeRecord | None:
        """
        Close an open position, credit proceeds to cash, and append a TradeRecord.

        Returns the TradeRecord, or None if the ticker is not in positions.
        """
        pos = self.positions.pop(ticker, None)
        if pos is None:
            logger.warning("close_position called for %s but not in portfolio", ticker)
            return None

        entry_commission = self._entry_commissions.pop(ticker, 0.0)
        proceeds = pos.shares * exit_price - commission
        self.cash += proceeds

        record = TradeRecord(
            ticker=ticker,
            entry_date=pos.entry_date,
            entry_price=pos.entry_price,
            exit_date=exit_date,
            exit_price=exit_price,
            shares=pos.shares,
            stop_loss=pos.stop_loss,
            atr_at_entry=pos.atr_at_entry,
            R=pos.R,
            exit_reason=reason,
            entry_commission=entry_commission,
            exit_commission=commission,
        )
        self.trade_records.append(record)
        logger.debug(
            "CLOSE %s @ %.4f  reason=%s  pnl=%.0f  R=%.2f",
            ticker, exit_price, reason, record.net_pnl, record.pnl_r_multiple,
        )
        return record

    def update_nav(
        self,
        date: pd.Timestamp,
        price_panel: dict[str, pd.DataFrame],
    ) -> float:
        """
        Mark all positions to their closing price, record NAV.

        Returns the computed NAV.
        """
        nav = self.compute_nav(date, price_panel)
        self.nav_history.append((date, nav))
        return nav

    def compute_nav(
        self,
        date: pd.Timestamp,
        price_panel: dict[str, pd.DataFrame],
    ) -> float:
        """
        Compute NAV without recording it.

        NAV = cash + Σ (shares × close) for all open positions.
        Uses the last known close if data for `date` is missing.
        """
        total = self.cash
        for ticker, pos in self.positions.items():
            price = self._get_close(ticker, date, pos.entry_price, price_panel)
            total += pos.market_value(price)
        return total

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _get_close(
        ticker: str,
        date: pd.Timestamp,
        fallback: float,
        price_panel: dict[str, pd.DataFrame],
    ) -> float:
        """Return close price for `ticker` on `date`, or `fallback` if unavailable."""
        if ticker not in price_panel:
            return fallback
        df = price_panel[ticker]
        if date in df.index:
            return float(df.at[date, "adj_close"])
        # Use last available close before date
        earlier = df.index[df.index <= date]
        if len(earlier) > 0:
            return float(df.at[earlier[-1], "adj_close"])
        return fallback

    def to_trade_log(self) -> pd.DataFrame:
        """Convert trade_records to a flat DataFrame."""
        if not self.trade_records:
            return pd.DataFrame(columns=[
                "ticker", "entry_date", "entry_price", "exit_date", "exit_price",
                "shares", "stop_loss", "atr_at_entry", "R",
                "gross_pnl", "net_pnl", "pnl_r_multiple",
                "exit_reason", "holding_days", "gap_adjusted_loss_multiple",
                "entry_commission", "exit_commission",
            ])
        rows = [
            {
                "ticker":                    r.ticker,
                "entry_date":                r.entry_date,
                "entry_price":               r.entry_price,
                "exit_date":                 r.exit_date,
                "exit_price":                r.exit_price,
                "shares":                    r.shares,
                "stop_loss":                 r.stop_loss,
                "atr_at_entry":              r.atr_at_entry,
                "R":                         r.R,
                "gross_pnl":                 r.gross_pnl,
                "net_pnl":                   r.net_pnl,
                "pnl_r_multiple":            r.pnl_r_multiple,
                "exit_reason":               r.exit_reason,
                "holding_days":              r.holding_days,
                "gap_adjusted_loss_multiple": r.gap_adjusted_loss_multiple,
                "entry_commission":          r.entry_commission,
                "exit_commission":           r.exit_commission,
            }
            for r in self.trade_records
        ]
        return pd.DataFrame(rows)
