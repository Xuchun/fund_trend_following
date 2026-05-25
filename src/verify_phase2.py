"""
Phase 2 acceptance test: Indicator Calculation Layer.

Checks:
  1. ATR (Wilder's smoothing) — spot-check against manual calculation.
  2. rolling_high uses shift(1): rolling_high[t] = max(high[t-N:t-1]).
  3. ADV uses shift(1): no look-ahead bias.
  4. breakout_signal fires only when close strictly exceeds rolling_high.
  5. breakout_strength = close / rolling_high.
  6. log_returns first row is NaN; subsequent rows match manual calc.
  7. pairwise_correlation returns None for insufficient data.
  8. compute_max_correlation returns 0.0 with no open positions.
  9. precompute_indicators runs end-to-end on a 5-ticker panel.

Usage:
    python src/verify_phase2.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from indicators.atr import compute_atr, compute_true_range
from indicators.breakout import (
    compute_breakout_signal,
    compute_breakout_strength,
    compute_rolling_high,
)
from indicators.adv import compute_adv, compute_dollar_volume
from indicators.correlation import (
    compute_log_returns,
    compute_max_correlation,
    compute_pairwise_correlation,
)


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

def _make_price_series(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Random OHLCV with guaranteed OHLC consistency."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n)
    close = 100 * np.cumprod(1 + rng.normal(0.0003, 0.012, n))
    spread = close * rng.uniform(0.002, 0.015, n)
    high  = close + spread * rng.uniform(0.3, 1.0, n)
    low   = close - spread * rng.uniform(0.3, 1.0, n)
    open_ = low + (high - low) * rng.uniform(0, 1, n)
    volume = rng.integers(1_000_000, 10_000_000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_atr() -> bool:
    print("\n=== 1. ATR (Wilder's smoothing) ===")
    df = _make_price_series(200)
    period = 20
    atr = compute_atr(df["high"], df["low"], df["close"], period=period)

    # First period rows should be NaN
    first_valid = atr.first_valid_index()
    expected_first_valid_pos = period  # index position (0-based): rows 0..period-1 are NaN
    actual_pos = df.index.get_loc(first_valid)
    if actual_pos != expected_first_valid_pos:
        _fail(f"First valid ATR at position {actual_pos}, expected {expected_first_valid_pos}")
        return False
    _ok(f"First {period} rows NaN, first valid at row {actual_pos}")

    # Seed value = simple mean of TR[1:period+1]
    tr = compute_true_range(df["high"], df["low"], df["close"])
    seed = tr.iloc[1: period + 1].mean()
    atr_seed = atr.iloc[period]
    if abs(atr_seed - seed) > 1e-8:
        _fail(f"Seed ATR={atr_seed:.6f}, expected={seed:.6f}")
        return False
    _ok(f"Seed value matches simple mean of first {period} TR values ({seed:.4f})")

    # Wilder's recursion: ATR[i] = (ATR[i-1] * (period-1) + TR[i]) / period
    ok = True
    for i in range(period + 1, period + 11):  # check 10 consecutive rows
        expected = (atr.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period
        actual   = atr.iloc[i]
        if abs(actual - expected) > 1e-8:
            _fail(f"Wilder recursion failed at row {i}: got {actual:.6f}, expected {expected:.6f}")
            ok = False
            break
    if ok:
        _ok("Wilder's recursive formula verified for 10 consecutive rows")

    # ATR must be positive
    valid_atr = atr.dropna()
    if (valid_atr <= 0).any():
        _fail("ATR contains non-positive values")
        return False
    _ok(f"All ATR values positive. Range: [{valid_atr.min():.4f}, {valid_atr.max():.4f}]")
    return True


def check_rolling_high_no_lookahead() -> bool:
    print("\n=== 2. rolling_high uses shift(1): no look-ahead bias ===")
    df = _make_price_series(150)
    window = 20
    rh = compute_rolling_high(df["high"], window=window)

    # rolling_high[t] must equal max(high[t-window : t-1])
    ok = True
    for pos in range(window + 5, window + 15):
        date = df.index[pos]
        expected = df["high"].iloc[pos - window: pos].max()
        actual   = rh.iloc[pos]
        if abs(actual - expected) > 1e-8:
            _fail(f"rolling_high at pos {pos}: got {actual:.4f}, expected {expected:.4f}")
            ok = False
            break

    if ok:
        _ok("rolling_high[t] = max(high[t-N : t-1]) verified for 10 rows")

    # Inflating only the LAST row's high must not change rolling_high for that row.
    # shift(1) means rolling_high[t] looks at [t-N, t-1], so today's high is excluded.
    df2 = df.copy()
    last_date = df2.index[-1]
    df2.loc[last_date, "high"] = df2["high"].max() * 1000  # extreme value
    rh2 = compute_rolling_high(df2["high"], window=window)
    if not np.isclose(rh.loc[last_date], rh2.loc[last_date], rtol=1e-8):
        _fail(
            f"rolling_high[last] changed when last-row high was inflated: "
            f"{rh.loc[last_date]:.4f} → {rh2.loc[last_date]:.4f} (look-ahead bias!)"
        )
        return False
    _ok("Inflating the last row's high does not change rolling_high for that row (shift=1 confirmed)")
    return ok


def check_adv_no_lookahead() -> bool:
    print("\n=== 3. ADV uses shift(1): no look-ahead bias ===")
    df = _make_price_series(150)
    window = 60
    dv = compute_dollar_volume(df["close"], df["volume"])
    adv = compute_adv(dv, window=window)

    ok = True
    for pos in range(window + 5, window + 10):
        expected = dv.iloc[pos - window: pos].mean()
        actual   = adv.iloc[pos]
        if abs(actual - expected) > 1e-6:
            _fail(f"ADV at pos {pos}: got {actual:.2f}, expected {expected:.2f}")
            ok = False
            break
    if ok:
        _ok("ADV[t] = mean(dollar_vol[t-60 : t-1]) verified (shift=1)")

    # Today's volume must not affect ADV for today
    df2 = df.copy()
    df2["volume"] = df2["volume"] * 1000
    dv2 = compute_dollar_volume(df2["close"], df2["volume"])
    adv2 = compute_adv(dv2, window=window)
    if not np.allclose(adv.dropna().values, adv2.dropna().values, rtol=1e-5):
        _fail("ADV is affected by same-day volume (look-ahead bias!)")
        return False
    _ok("Inflating today's volume does not change ADV (shift=1 confirmed)")
    return ok


def check_breakout_signal() -> bool:
    print("\n=== 4. breakout_signal: close > rolling_high ===")
    df = _make_price_series(150)
    window = 20
    rh = compute_rolling_high(df["high"], window=window)
    sig = compute_breakout_signal(df["close"], rh)
    strength = compute_breakout_strength(df["close"], rh)

    # Manually verify signal matches close > rolling_high
    valid = rh.dropna()
    for date in valid.index[:20]:
        expected_sig = df["close"][date] > rh[date]
        if sig[date] != expected_sig:
            _fail(f"breakout_signal mismatch at {date.date()}")
            return False
    _ok("breakout_signal[t] == (close[t] > rolling_high[t]) verified for 20 rows")

    # strength = close / rolling_high where signal is True
    signal_dates = sig[sig].index
    if len(signal_dates) == 0:
        _ok("No breakout signals in test window (rare but not an error)")
        return True

    for date in signal_dates[:5]:
        expected_str = df["close"][date] / rh[date]
        actual_str   = strength[date]
        if abs(actual_str - expected_str) > 1e-8:
            _fail(f"breakout_strength mismatch at {date.date()}: {actual_str:.6f} vs {expected_str:.6f}")
            return False
    _ok(f"breakout_strength = close/rolling_high verified. "
        f"{len(signal_dates)} breakout days found")

    # NaN in rolling_high → signal must be False, not NaN
    nan_dates = rh[rh.isna()].index
    if sig[nan_dates].any():
        _fail("breakout_signal is True where rolling_high is NaN")
        return False
    _ok("breakout_signal is False (not NaN) where rolling_high is NaN")
    return True


def check_log_returns() -> bool:
    print("\n=== 5. log_returns ===")
    df = _make_price_series(100)
    lr = compute_log_returns(df["close"])

    if not pd.isna(lr.iloc[0]):
        _fail("First log_return should be NaN")
        return False
    _ok("First row is NaN")

    # Spot-check 5 values
    ok = True
    for i in range(1, 6):
        expected = np.log(df["close"].iloc[i] / df["close"].iloc[i - 1])
        actual   = lr.iloc[i]
        if abs(actual - expected) > 1e-10:
            _fail(f"log_return mismatch at row {i}: {actual:.8f} vs {expected:.8f}")
            ok = False
            break
    if ok:
        _ok("ln(close[t]/close[t-1]) matches manual calculation for rows 1-5")
    return ok


def check_correlation() -> bool:
    print("\n=== 6. correlation edge cases ===")
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2022-01-01", periods=100)
    r1 = pd.Series(rng.normal(0, 0.01, 100), index=dates)
    r2 = pd.Series(rng.normal(0, 0.01, 100), index=dates)

    # Normal case: should return a float in [-1, 1]
    corr = compute_pairwise_correlation(r1, r2, window=60, min_samples=40)
    if corr is None or not (-1.0 <= corr <= 1.0):
        _fail(f"Expected float in [-1,1], got {corr}")
        return False
    _ok(f"Normal correlation = {corr:.4f}")

    # Too few samples → None
    short = pd.Series(rng.normal(0, 0.01, 30), index=dates[:30])
    corr_short = compute_pairwise_correlation(r1, short, window=60, min_samples=40)
    if corr_short is not None:
        _fail(f"Expected None for short series, got {corr_short}")
        return False
    _ok("Returns None when fewer than min_samples observations")

    # Constant series → None
    const = pd.Series(0.0, index=dates)
    corr_const = compute_pairwise_correlation(r1, const, window=60, min_samples=40)
    if corr_const is not None:
        _fail(f"Expected None for constant series, got {corr_const}")
        return False
    _ok("Returns None when one series has zero std dev")

    # No positions → max_corr = 0.0
    log_returns = {"SPY": r1, "AAPL": r2}
    mc = compute_max_correlation(
        "SPY", [], log_returns, as_of_date=dates[-1], window=60
    )
    if mc != 0.0:
        _fail(f"Expected 0.0 with no positions, got {mc}")
        return False
    _ok("max_correlation = 0.0 when current_positions is empty")

    # Perfectly correlated series → max_corr ≈ 1.0
    r_correlated = r1 * 2 + 0.001  # deterministic linear transform
    log_returns2 = {"NEW": r1, "POS": r_correlated}
    mc2 = compute_max_correlation(
        "NEW", ["POS"], log_returns2, as_of_date=dates[-1], window=60
    )
    if mc2 < 0.99:
        _fail(f"Expected near-1 correlation for linearly scaled series, got {mc2:.4f}")
        return False
    _ok(f"max_correlation ≈ 1.0 for perfectly correlated pair ({mc2:.4f})")
    return True


def check_precompute() -> bool:
    print("\n=== 7. precompute_indicators end-to-end ===")
    try:
        # Import here to avoid circular-import issues at module level
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent))

        from data.adapters.yahoo import YahooFinanceAdapter
        from data.pipeline import load_price_panel
        from indicators.precompute import precompute_indicators

        # Minimal stub params
        class _Params:
            atr_period = 20
            breakout_window = 100

        tickers = ["SPY", "QQQ", "GLD"]
        adapter = YahooFinanceAdapter()
        panel = load_price_panel(tickers, adapter, "2022-01-01", "2023-12-31")

        indicators = precompute_indicators(panel, _Params())

        expected_keys = {
            "atr", "rolling_high", "breakout_signal",
            "breakout_strength", "adv", "log_returns",
        }
        ok = True
        for ticker in tickers:
            if ticker not in indicators:
                _fail(f"{ticker} missing from indicator dict")
                ok = False
                continue
            got_keys = set(indicators[ticker].keys())
            missing = expected_keys - got_keys
            if missing:
                _fail(f"{ticker} missing indicator keys: {missing}")
                ok = False
                continue
            _ok(
                f"{ticker}: all 6 indicator series present. "
                f"ATR range [{indicators[ticker]['atr'].dropna().min():.3f}, "
                f"{indicators[ticker]['atr'].dropna().max():.3f}]"
            )
        return ok
    except Exception as e:
        _fail(f"precompute_indicators failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 55)
    print("Phase 2 指标计算层验收")
    print("=" * 55)

    results = {
        "1. ATR (Wilder's)":       check_atr(),
        "2. rolling_high (shift=1)": check_rolling_high_no_lookahead(),
        "3. ADV (shift=1)":        check_adv_no_lookahead(),
        "4. breakout_signal":      check_breakout_signal(),
        "5. log_returns":          check_log_returns(),
        "6. correlation":          check_correlation(),
        "7. precompute_indicators": check_precompute(),
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
        print("✓ Phase 2 验收通过，可以进入 Phase 3（策略逻辑层）")
        sys.exit(0)
    else:
        print("✗ 有项目未通过，请根据上面的错误信息修复后重新运行")
        sys.exit(1)


if __name__ == "__main__":
    main()
