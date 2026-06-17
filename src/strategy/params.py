"""
StrategyParams: single source of truth for all tunable strategy parameters.

Usage:
    baseline = StrategyParams()                        # all defaults
    perturb  = StrategyParams(breakout_window=120)     # single-field override
    from dataclasses import replace
    variant  = replace(baseline, heat_limit=0.08)      # immutable copy with change
"""

from dataclasses import dataclass, field


@dataclass
class StrategyParams:
    # ── Universe filters ───────────────────────────────────────────────────
    min_price: float = 10.0          # USD; reject penny stocks
    min_market_cap_b: float = 2.0    # billion USD; strategy spec: 市值 > $20亿 = $2B (not point-in-time on Yahoo)
    min_adv_m: float = 60.0          # million USD average daily dollar volume (Baseline)

    # ── Entry signal ───────────────────────────────────────────────────────
    breakout_window: int = 200       # N-day rolling-high lookback

    # ── ATR ────────────────────────────────────────────────────────────────
    atr_period: int = 20             # Wilder smoothing period

    # ── Stop loss ──────────────────────────────────────────────────────────
    stop_loss_multiplier: float = 2.0        # stop = entry - N × ATR
    min_stop_distance_pct: float = 0.005     # reject if stop < 0.5% below entry

    # ── Trailing stop (segmented by R-multiple) ────────────────────────────
    trail_multiplier_r1: float = 3.0   # R_multiple < 1   → trail = HH - 3×ATR
    trail_multiplier_r3: float = 3.0   # 1 ≤ R_multiple < 3 → trail = HH - 3×ATR
    trail_multiplier_r5: float = 5.0   # R_multiple ≥ 3   → trail = HH - 5×ATR

    # ── Position sizing ────────────────────────────────────────────────────
    risk_per_trade: float = 0.01     # 1% of NAV risked per new position
    position_cap: float = 0.05       # single-name cap: 5% of NAV

    # ── Portfolio risk ─────────────────────────────────────────────────────
    heat_limit: float = 0.10         # max total risk across all open positions

    # ── Correlation filter ─────────────────────────────────────────────────
    correlation_window: int = 60           # days for pairwise correlation
    correlation_threshold: float = 0.7    # reduce size if corr > threshold
    correlation_reduction: float = 0.5    # multiply shares by this factor

    # ── Volume confirmation ────────────────────────────────────────────────
    volume_filter_multiplier: float = 1.5  # vol[t] ≥ 1.5×vol_ma60; set 0.0 to disable

    # ── Breakout strength filter ───────────────────────────────────────────
    breakout_strength_min: float = 0.0    # 0.0=disabled; 0.02 → close/rolling_high > 1.02

    # ── Execution model ────────────────────────────────────────────────────
    gap_filter: float = 0.025        # reject entry if open gaps > ±2.5%
    commission_bps: float = 3.0      # one-way commission in basis points
    slippage_bps: float = 10.0       # one-way slippage in basis points

    # ── Cash proxy ─────────────────────────────────────────────────────────
    cash_proxy: str = "SHY"          # 1-3Y Treasury ETF; covers full backtest period 2002+

    # ── Market regime filter ────────────────────────────────────────────────
    regime_filter_enabled: bool = True    # True → block entries when SPY < SMA
    regime_ticker: str = "SPY"            # benchmark for regime detection
    regime_sma_window: int = 200          # SMA lookback in trading days

    # ── Consolidation filter (v2+) ─────────────────────────────────────────
    consolidation_filter_enabled: bool = False   # disabled → v1 behaviour unchanged
    consolidation_window: int = 80               # lookback days for range check
    consolidation_threshold: float = 0.25        # (max_high - min_low) / min_low < threshold

    # ── Bear-market exempt tickers ─────────────────────────────────────────
    # Tickers listed here can still receive entry signals during bear markets
    # (SPY < 200-day SMA). All other strategy rules (ATR stop, position sizing,
    # heat limit, correlation filter) still apply normally.
    bear_exempt_tickers: frozenset = field(default_factory=frozenset)
