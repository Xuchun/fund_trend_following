"""
Trade execution model: gap filter, fill price, and commission.

All functions are pure (no side effects) so they can be tested in isolation
and reused by any strategy version or the engine.

Cost model summary (per design spec Section G):
  - Slippage (10 bps) is built into the fill price via compute_fill_price().
  - Commission (3 bps) is charged separately via compute_commission().
  - Both are one-way costs; round-trip total ≈ 26 bps (2 × 13 bps).
"""


def apply_gap_filter(
    signal_close: float,
    next_open: float,
    gap_filter: float = 0.025,
) -> bool:
    """
    Return True if the t+1 open is within the allowed gap range.

    Rejects the entry if:
        next_open > signal_close × (1 + gap_filter)   [gap up too far]
        next_open < signal_close × (1 - gap_filter)   [gap down]

    A large gap-up means the breakout has already run away from us;
    a gap-down on an entry signal is a red flag.

    Args:
        signal_close: Close price on the signal day (t).
        next_open:    Open price on the execution day (t+1).
        gap_filter:   Maximum allowed gap fraction (default 2.5%).

    Returns:
        True  = gap is acceptable, proceed with entry.
        False = gap too large, skip this signal.
    """
    if signal_close <= 0:
        return False
    gap_pct = abs(next_open - signal_close) / signal_close
    return gap_pct <= gap_filter


def compute_fill_price(
    open_price: float,
    direction: str,
    slippage_bps: float = 10.0,
) -> float:
    """
    Adjust the opening price for market-impact slippage.

    Buy orders pay more (price moves against buyer).
    Sell orders receive less (price moves against seller).

    Args:
        open_price:    Raw opening price at t+1.
        direction:     'buy' or 'sell'.
        slippage_bps:  One-way slippage in basis points (default 10 bps).

    Returns:
        Adjusted fill price.
    """
    factor = slippage_bps / 10_000
    if direction == "buy":
        return open_price * (1.0 + factor)
    else:
        return open_price * (1.0 - factor)


def compute_commission(
    fill_price: float,
    shares: int,
    commission_bps: float = 3.0,
) -> float:
    """
    One-way broker commission on a single leg (buy or sell).

    commission = fill_price × shares × commission_bps / 10,000

    Args:
        fill_price:      Slippage-adjusted execution price.
        shares:          Number of shares transacted.
        commission_bps:  One-way commission in basis points (default 3 bps).

    Returns:
        Commission in USD.
    """
    return fill_price * shares * commission_bps / 10_000


def compute_transaction_cost(
    entry_fill: float,
    exit_fill: float,
    shares: int,
    commission_bps: float = 3.0,
) -> float:
    """
    Total round-trip commission for one complete trade (entry + exit).

    Slippage is already embedded in entry_fill and exit_fill via
    compute_fill_price(); this function only adds the broker commission.

    Args:
        entry_fill:     Fill price on entry (with slippage already applied).
        exit_fill:      Fill price on exit (with slippage already applied).
        shares:         Number of shares.
        commission_bps: One-way commission in basis points.

    Returns:
        Total commission cost in USD.
    """
    return compute_commission(entry_fill, shares, commission_bps) + \
           compute_commission(exit_fill,  shares, commission_bps)
