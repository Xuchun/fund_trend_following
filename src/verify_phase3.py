"""
Phase 3 acceptance test: Strategy Logic Layer.

Checks:
  1. Position sizing: manual verification of raw→capped→correlation→heat pipeline.
  2. Trail stop: segmented multiplier formula (3 R_multiple regimes).
  3. Exit priority: stop_loss checked before trailing_stop.
  4. Trail stop ratchet: trail_stop never decreases.
  5. Entry signal generation: filters (price, ADV, breakout) + sort order.
  6. Entry signal: currently_held tickers are excluded.
  7. StrategyV1 wires entry/exit correctly via mock Portfolio.

Usage:
    python src/verify_phase3.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.position import Position
from strategy.params import StrategyParams
from strategy.v1.exit import check_exit_signals_v1, update_trail_stop_v1
from strategy.v1.sizing import compute_position_size
from strategy.v1.entry import generate_entry_signals_v1
from strategy.v1.strategy_v1 import StrategyV1


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


# ── helpers ────────────────────────────────────────────────────────────────

def _make_position(
    ticker="AAPL",
    entry_price=100.0,
    stop_loss=90.0,
    atr=5.0,
    trail_stop=None,
) -> Position:
    if trail_stop is None:
        trail_stop = entry_price - 2.0 * atr  # default: r1 multiplier
    return Position(
        ticker=ticker,
        entry_date=pd.Timestamp("2023-01-01"),
        entry_price=entry_price,
        shares=1000,
        stop_loss=stop_loss,
        trail_stop=trail_stop,
        highest_high=entry_price,
        atr_at_entry=atr,
    )


def _make_log_returns(n=100, seed=42) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-01", periods=n)
    return pd.Series(rng.normal(0, 0.01, n), index=dates)


# ── Check 1: position sizing pipeline ──────────────────────────────────────

def check_sizing() -> bool:
    print("\n=== 1. Position sizing: raw → capped → correlation → heat ===")
    params = StrategyParams()  # defaults
    ok = True

    nav = 10_000_000.0
    entry_price = 100.0
    stop_loss = 90.0           # risk_per_share = 10
    existing_risk = 0.0
    date = pd.Timestamp("2023-06-15")
    log_returns: dict[str, pd.Series] = {}  # no existing positions → corr = 0

    # Expected:
    #   raw   = (10M × 1%) / 10 = 10,000 shares
    #   capped = (10M × 5%) / 100 = 5,000 shares
    #   preliminary = min(10000, 5000) = 5,000
    #   no correlation reduction
    #   heat = (0 + 5000×10) / 10M = 0.5% < 10% → pass
    #   result = 5,000

    result = compute_position_size(
        entry_price=entry_price,
        stop_loss=stop_loss,
        nav=nav,
        existing_risk=existing_risk,
        current_positions=[],
        log_returns=log_returns,
        new_ticker="AAPL",
        as_of_date=date,
        params=params,
    )
    if result != 5000:
        _fail(f"Expected 5000 shares, got {result}")
        ok = False
    else:
        _ok(f"Clean case: 5000 shares (raw=10000 capped to 5000 by position_cap)")

    # Case: raw is the binding constraint (tight stop)
    #   entry=100, stop=99.9 → risk_per_share=0.1
    #   raw = 100,000 / 0.1 = 1,000,000 shares
    #   capped = 500,000 / 100 = 5,000 shares
    #   preliminary = 5,000 (capped binds)
    result2 = compute_position_size(
        entry_price=100.0, stop_loss=99.9, nav=nav,
        existing_risk=0.0, current_positions=[], log_returns={},
        new_ticker="AAPL", as_of_date=date, params=params,
    )
    if result2 != 5000:
        _fail(f"Tight stop: expected 5000 (capped), got {result2}")
        ok = False
    else:
        _ok("Tight stop: position_cap is binding → 5000 shares")

    # Case: correlation reduction applied (need correlated returns)
    n = 100
    dates = pd.bdate_range("2022-01-01", periods=n)
    r_base = np.linspace(0.001, 0.002, n)  # near-identical → corr ≈ 1
    lr_new = pd.Series(r_base, index=dates)
    lr_pos = pd.Series(r_base * 1.001, index=dates)
    lr_dict = {"NEW": lr_new, "POS": lr_pos}
    params_corr = replace(params, correlation_threshold=0.5)
    result3 = compute_position_size(
        entry_price=100.0, stop_loss=90.0, nav=nav,
        existing_risk=0.0, current_positions=["POS"],
        log_returns=lr_dict, new_ticker="NEW",
        as_of_date=dates[-1], params=params_corr,
    )
    # preliminary=5000, corr>0.5 → ×0.5 → 2500
    if result3 != 2500:
        _fail(f"Corr reduction: expected 2500, got {result3}")
        ok = False
    else:
        _ok("Correlation >threshold → size halved to 2500 shares")

    # Case: heat limit blocks the trade
    params_hot = replace(params, heat_limit=0.001)  # 0.1%
    result4 = compute_position_size(
        entry_price=100.0, stop_loss=90.0, nav=nav,
        existing_risk=0.0, current_positions=[], log_returns={},
        new_ticker="AAPL", as_of_date=date, params=params_hot,
    )
    # new_risk = 5000 × 10 = 50,000; total_heat = 0.5% > 0.1% → None
    if result4 is not None:
        _fail(f"Heat limit: expected None, got {result4}")
        ok = False
    else:
        _ok("Heat limit triggered → None returned (trade abandoned)")

    # Case: stop above entry → None
    result5 = compute_position_size(
        entry_price=90.0, stop_loss=100.0, nav=nav,
        existing_risk=0.0, current_positions=[], log_returns={},
        new_ticker="AAPL", as_of_date=date, params=params,
    )
    if result5 is not None:
        _fail(f"Stop above entry: expected None, got {result5}")
        ok = False
    else:
        _ok("Stop above entry price → None returned")

    return ok


# ── Check 2: trail stop segmented formula ──────────────────────────────────

def check_trail_stop() -> bool:
    print("\n=== 2. Trail stop: segmented R_multiple formula ===")
    params = StrategyParams()
    ok = True

    # Setup: entry=100, stop=90, ATR=5, R=10, initial trail=90 (=entry - 2×ATR)
    pos = _make_position(entry_price=100.0, stop_loss=90.0, atr=5.0, trail_stop=90.0)

    # Day 1: high=105, close=108 → R_multiple=(108-100)/10=0.8 < 1 → mult=2.0
    #   highest_high = max(100, 105) = 105
    #   new_trail = 105 - 2.0×5 = 95  → trail_stop = max(90, 95) = 95
    update_trail_stop_v1(pos, high=105.0, close=108.0, atr=5.0, params=params)
    if abs(pos.highest_high - 105.0) > 1e-9:
        _fail(f"Day1 highest_high: expected 105, got {pos.highest_high}")
        ok = False
    if abs(pos.trail_stop - 95.0) > 1e-9:
        _fail(f"Day1 trail_stop: expected 95, got {pos.trail_stop}")
        ok = False
    if ok:
        _ok(f"Day1 (R_mult=0.8 → ×2.0): trail_stop={pos.trail_stop}, highest_high={pos.highest_high}")

    # Day 2: high=120, close=125 → R_multiple=(125-100)/10=2.5, 1≤2.5<3 → mult=3.0
    #   highest_high = max(105, 120) = 120
    #   new_trail = 120 - 3.0×5 = 105 → trail_stop = max(95, 105) = 105
    update_trail_stop_v1(pos, high=120.0, close=125.0, atr=5.0, params=params)
    if abs(pos.trail_stop - 105.0) > 1e-9:
        _fail(f"Day2 trail_stop: expected 105, got {pos.trail_stop}")
        ok = False
    if ok:
        _ok(f"Day2 (R_mult=2.5 → ×3.0): trail_stop={pos.trail_stop}, highest_high={pos.highest_high}")

    # Day 3: high=150, close=155 → R_multiple=(155-100)/10=5.5 ≥ 3 → mult=5.0
    #   highest_high = max(120, 150) = 150
    #   new_trail = 150 - 5.0×5 = 125 → trail_stop = max(105, 125) = 125
    update_trail_stop_v1(pos, high=150.0, close=155.0, atr=5.0, params=params)
    if abs(pos.trail_stop - 125.0) > 1e-9:
        _fail(f"Day3 trail_stop: expected 125, got {pos.trail_stop}")
        ok = False
    if ok:
        _ok(f"Day3 (R_mult=5.5 → ×5.0): trail_stop={pos.trail_stop}, highest_high={pos.highest_high}")

    return ok


# ── Check 3: exit priority ──────────────────────────────────────────────────

def check_exit_priority() -> bool:
    print("\n=== 3. Exit priority: stop_loss > trailing_stop ===")
    params = StrategyParams()
    date = pd.Timestamp("2023-06-15")
    ok = True

    # Scenario A: low < stop_loss AND close < trail_stop → stop_loss wins
    pos_a = _make_position(entry_price=100.0, stop_loss=90.0, atr=5.0, trail_stop=95.0)
    sig_a = check_exit_signals_v1(
        date=date, position=pos_a,
        high=91.0, low=88.0, close=89.0,  # low < stop_loss, close < trail_stop
        atr=5.0, params=params,
    )
    if sig_a is None or sig_a["reason"] != "stop_loss":
        _fail(f"Scenario A: expected stop_loss, got {sig_a}")
        ok = False
    else:
        _ok("Scenario A: both conditions true → stop_loss wins (correct priority)")

    # Scenario B: low > stop_loss, close < trail_stop → trailing_stop
    pos_b = _make_position(entry_price=100.0, stop_loss=90.0, atr=5.0, trail_stop=105.0)
    sig_b = check_exit_signals_v1(
        date=date, position=pos_b,
        high=102.0, low=92.0, close=103.0,  # close < trail_stop=105
        atr=5.0, params=params,
    )
    if sig_b is None or sig_b["reason"] != "trailing_stop":
        _fail(f"Scenario B: expected trailing_stop, got {sig_b}")
        ok = False
    else:
        _ok("Scenario B: only trailing_stop triggered (close < trail_stop)")

    # Scenario C: no exit
    pos_c = _make_position(entry_price=100.0, stop_loss=90.0, atr=5.0, trail_stop=95.0)
    sig_c = check_exit_signals_v1(
        date=date, position=pos_c,
        high=108.0, low=104.0, close=107.0,  # no trigger
        atr=5.0, params=params,
    )
    if sig_c is not None:
        _fail(f"Scenario C: expected None, got {sig_c}")
        ok = False
    else:
        _ok("Scenario C: no exit triggered → None returned")

    return ok


# ── Check 4: trail stop ratchet (never decreases) ──────────────────────────

def check_trail_stop_ratchet() -> bool:
    print("\n=== 4. Trail stop ratchet: trail_stop never decreases ===")
    params = StrategyParams()
    ok = True

    pos = _make_position(entry_price=100.0, stop_loss=90.0, atr=5.0, trail_stop=95.0)
    pos.highest_high = 120.0
    # Simulate price falling back toward entry
    # close=102 → R_multiple=0.2 < 1 → mult=2.0
    # new_trail = max(120, high=102) - 2×5 = 120 - 10 = 110
    # trail_stop = max(95, 110) = 110
    update_trail_stop_v1(pos, high=102.0, close=102.0, atr=5.0, params=params)
    trail_after_rise = pos.trail_stop

    # Now price falls further; trail_stop must NOT drop
    # close=98 → R_multiple < 1 → mult=2.0
    # new_trail = max(120, high=98) - 2×5 = 120 - 10 = 110
    # trail_stop = max(trail_after_rise, 110) = trail_after_rise (unchanged)
    before = pos.trail_stop
    update_trail_stop_v1(pos, high=98.0, close=98.0, atr=5.0, params=params)
    after = pos.trail_stop

    if after < before:
        _fail(f"Trail stop decreased: {before:.2f} → {after:.2f}")
        ok = False
    else:
        _ok(f"Trail stop held at {after:.2f} when price fell (ratchet confirmed)")

    return ok


# ── Check 5: entry signal filters and sort order ───────────────────────────

def check_entry_signals() -> bool:
    print("\n=== 5. Entry signals: filters and breakout_strength sort order ===")
    params = StrategyParams(min_price=10.0, min_adv_m=5.0)
    date = pd.Timestamp("2023-06-15")
    ok = True

    dates = pd.bdate_range("2022-01-01", periods=400)

    def _df(close_val, volume=10_000_000, is_tradable=True):
        n = len(dates)
        close = pd.Series([close_val] * n, index=dates, dtype=float)
        high  = close * 1.01
        low   = close * 0.99
        # rolling_high = high.shift(1).rolling(100).max()
        # For breakout: close > rolling_high → close_val > close_val*1.01*(0.99...)
        # Let's set close slightly above the 100-day max, which requires engineered data
        # Instead, rely on the indicator dict for signals
        return pd.DataFrame({
            "open": close * 0.995, "high": high, "low": low, "close": close,
            "volume": pd.Series([float(volume)] * n, index=dates),
            "adj_factor": pd.Series([1.0] * n, index=dates),
            "is_tradable": pd.Series([is_tradable] * n, index=dates),
        })

    def _ind(breakout=True, atr=2.0, adv=10_000_000, close_val=100.0, rolling_high_val=95.0):
        n = len(dates)
        return {
            "breakout_signal":   pd.Series([breakout] * n, index=dates),
            "breakout_strength": pd.Series([close_val / rolling_high_val] * n, index=dates),
            "atr":               pd.Series([atr] * n, index=dates),
            "adv":               pd.Series([float(adv)] * n, index=dates),
            "rolling_high":      pd.Series([rolling_high_val] * n, index=dates),
            "log_returns":       pd.Series([0.001] * n, index=dates),
        }

    price_panel = {
        "AAPL": _df(150.0),             # passes: breakout, ADV OK
        "MSFT": _df(200.0),             # passes: breakout, ADV OK, higher strength
        "LOW_P": _df(5.0),              # fails: price < min_price (10)
        "LOW_ADV": _df(100.0, volume=1_000),  # fails: ADV too low
        "NO_BRK": _df(100.0),           # fails: no breakout signal
        "NO_TRAD": _df(100.0, is_tradable=False),  # fails: not tradable
    }

    indicators = {
        "AAPL":    _ind(breakout=True,  atr=2.0, adv=10_000_000, close_val=150.0, rolling_high_val=140.0),
        "MSFT":    _ind(breakout=True,  atr=3.0, adv=20_000_000, close_val=200.0, rolling_high_val=180.0),
        "LOW_P":   _ind(breakout=True,  atr=0.2, close_val=5.0,  rolling_high_val=4.0),
        "LOW_ADV": _ind(breakout=True,  atr=2.0, adv=50_000,     close_val=100.0, rolling_high_val=90.0),
        "NO_BRK":  _ind(breakout=False, atr=2.0, close_val=100.0, rolling_high_val=105.0),
        "NO_TRAD": _ind(breakout=True,  atr=2.0, close_val=100.0, rolling_high_val=90.0),
    }

    signals = generate_entry_signals_v1(
        date=date,
        universe=list(price_panel.keys()),
        price_panel=price_panel,
        indicators=indicators,
        currently_held=set(),
        params=params,
    )

    tickers = [s["ticker"] for s in signals]

    # Only AAPL and MSFT should pass
    if set(tickers) != {"AAPL", "MSFT"}:
        _fail(f"Expected {{AAPL, MSFT}}, got {set(tickers)}")
        ok = False
    else:
        _ok("Correct tickers: LOW_P, LOW_ADV, NO_BRK, NO_TRAD all filtered out")

    # MSFT has higher breakout_strength (200/180=1.111) vs AAPL (150/140=1.071)
    if len(signals) == 2 and signals[0]["ticker"] != "MSFT":
        _fail(f"Sort order wrong: expected MSFT first, got {signals[0]['ticker']}")
        ok = False
    else:
        _ok(f"Sort order correct: {[s['ticker'] for s in signals]} (MSFT strength={200/180:.4f} > AAPL={150/140:.4f})")

    return ok


# ── Check 6: currently_held exclusion ──────────────────────────────────────

def check_currently_held_excluded() -> bool:
    print("\n=== 6. currently_held tickers are excluded from signals ===")
    params = StrategyParams(min_price=10.0, min_adv_m=0.0)
    date = pd.Timestamp("2023-06-15")

    dates = pd.bdate_range("2022-01-01", periods=400)
    n = len(dates)

    price_panel = {
        "AAPL": pd.DataFrame({
            "open": [100.0]*n, "high": [101.0]*n, "low": [99.0]*n,
            "close": [100.0]*n, "volume": [1e7]*n,
            "adj_factor": [1.0]*n, "is_tradable": [True]*n,
        }, index=dates),
    }
    indicators = {
        "AAPL": {
            "breakout_signal":   pd.Series([True]*n, index=dates),
            "breakout_strength": pd.Series([1.05]*n, index=dates),
            "atr":               pd.Series([2.0]*n,  index=dates),
            "adv":               pd.Series([1e7]*n,  index=dates),
            "rolling_high":      pd.Series([95.0]*n, index=dates),
            "log_returns":       pd.Series([0.001]*n, index=dates),
        }
    }

    # Without holding AAPL → signal generated
    sigs_free = generate_entry_signals_v1(
        date=date, universe=["AAPL"], price_panel=price_panel,
        indicators=indicators, currently_held=set(), params=params,
    )
    # With AAPL in currently_held → no signal
    sigs_held = generate_entry_signals_v1(
        date=date, universe=["AAPL"], price_panel=price_panel,
        indicators=indicators, currently_held={"AAPL"}, params=params,
    )

    ok = True
    if len(sigs_free) != 1:
        _fail(f"Expected 1 signal when not held, got {len(sigs_free)}")
        ok = False
    else:
        _ok("Signal generated when ticker is not held")
    if len(sigs_held) != 0:
        _fail(f"Expected 0 signals when held, got {len(sigs_held)}")
        ok = False
    else:
        _ok("No signal generated when ticker is in currently_held")
    return ok


# ── Check 7: StrategyV1 wiring via mock Portfolio ──────────────────────────

def check_strategy_v1_wiring() -> bool:
    print("\n=== 7. StrategyV1 wiring via mock Portfolio ===")
    params = StrategyParams(min_price=10.0, min_adv_m=0.0)
    strategy = StrategyV1(params)
    date = pd.Timestamp("2023-06-15")

    dates = pd.bdate_range("2022-01-01", periods=400)
    n = len(dates)

    # Mock Portfolio with one open position
    open_pos = _make_position(
        ticker="HELD", entry_price=100.0, stop_loss=90.0,
        atr=5.0, trail_stop=90.0
    )
    mock_portfolio = SimpleNamespace(positions={"HELD": open_pos})

    price_panel = {
        "CAND": pd.DataFrame({
            "open": [50.0]*n, "high": [51.0]*n, "low": [49.0]*n,
            "close": [50.0]*n, "volume": [1e7]*n,
            "adj_factor": [1.0]*n, "is_tradable": [True]*n,
        }, index=dates),
        "HELD": pd.DataFrame({
            "open": [100.0]*n, "high": [102.0]*n, "low": [88.0]*n,
            "close": [90.0]*n, "volume": [1e7]*n,
            "adj_factor": [1.0]*n, "is_tradable": [True]*n,
        }, index=dates),
    }
    indicators = {
        "CAND": {
            "breakout_signal":   pd.Series([True]*n, index=dates),
            "breakout_strength": pd.Series([1.05]*n, index=dates),
            "atr":               pd.Series([1.0]*n, index=dates),
            "adv":               pd.Series([1e7]*n, index=dates),
            "rolling_high":      pd.Series([47.0]*n, index=dates),
            "log_returns":       pd.Series([0.001]*n, index=dates),
        },
        "HELD": {
            "atr": pd.Series([5.0]*n, index=dates),
            "breakout_signal":   pd.Series([False]*n, index=dates),
            "breakout_strength": pd.Series([1.0]*n, index=dates),
            "adv":               pd.Series([1e7]*n, index=dates),
            "rolling_high":      pd.Series([95.0]*n, index=dates),
            "log_returns":       pd.Series([0.001]*n, index=dates),
        },
    }

    ok = True

    # Entry: CAND should appear, HELD should not (it's in portfolio)
    entry_sigs = strategy.generate_entry_signals(
        date=date, universe=["CAND", "HELD"],
        price_panel=price_panel, indicators=indicators,
        portfolio=mock_portfolio,
    )
    if len(entry_sigs) != 1 or entry_sigs[0]["ticker"] != "CAND":
        _fail(f"Entry: expected [CAND], got {[s['ticker'] for s in entry_sigs]}")
        ok = False
    else:
        _ok("Entry: CAND signal generated; HELD (held) excluded")

    # Exit: HELD has low=88 < stop_loss=90 → should trigger stop_loss
    exit_sigs = strategy.generate_exit_signals(
        date=date, portfolio=mock_portfolio,
        price_panel=price_panel, indicators=indicators,
    )
    if len(exit_sigs) != 1 or exit_sigs[0]["reason"] != "stop_loss":
        _fail(f"Exit: expected [stop_loss], got {exit_sigs}")
        ok = False
    else:
        _ok("Exit: HELD stop_loss triggered (low=88 < stop=90)")

    return ok


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 55)
    print("Phase 3 策略逻辑层验收")
    print("=" * 55)

    results = {
        "1. 仓位计算 (raw→cap→corr→heat)": check_sizing(),
        "2. Trail stop 分段公式":           check_trail_stop(),
        "3. Exit 优先级 (stop > trail)":    check_exit_priority(),
        "4. Trail stop 棘轮 (只涨不跌)":    check_trail_stop_ratchet(),
        "5. 开仓信号过滤与排序":            check_entry_signals(),
        "6. 已持仓标的排除":                check_currently_held_excluded(),
        "7. StrategyV1 整体接线":           check_strategy_v1_wiring(),
    }

    print("\n=== 验收结果汇总 ===")
    all_passed = True
    for name, passed in results.items():
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("✓ Phase 3 验收通过，可以进入 Phase 4（回测引擎层）")
        sys.exit(0)
    else:
        print("✗ 有项目未通过，请根据上面的错误信息修复后重新运行")
        sys.exit(1)


if __name__ == "__main__":
    main()
