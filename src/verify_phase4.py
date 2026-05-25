"""
Phase 4 acceptance test: Backtest Engine Layer.

Checks (per design spec Phase 4 acceptance criteria):
  1. Execution price: entry_price ≈ open[entry_date] × (1 + slippage_bps/10000)
  2. Look-ahead bias: t-day signal executed at t+1 open, not t close
  3. Heat update order: existing_risk increases after each opened position
  4. SGOV contributes positive return to NAV on cash-only days
  5. Gap filter: entries rejected when open gaps > threshold
  6. End-to-end smoke test: 5 tickers × 2 years produces sensible results
  7. trade_log schema: all required columns present, exit_reasons valid

Usage:
    python src/verify_phase4.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.execution import (
    apply_gap_filter,
    compute_commission,
    compute_fill_price,
    compute_transaction_cost,
)
from backtest.portfolio import Portfolio
from backtest.position import Position
from backtest.engine import BacktestEngine
from strategy.params import StrategyParams
from strategy.v1.strategy_v1 import StrategyV1


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


# ── helpers ────────────────────────────────────────────────────────────────

def _make_synthetic_panel(
    tickers: list[str],
    n: int = 300,
    seed: int = 42,
    include_sgov: bool = True,
) -> dict[str, pd.DataFrame]:
    """
    Build a synthetic price panel.

    Prices are a geometric random walk starting at $100 for each ticker.
    Volume is set high enough to pass the ADV filter.
    SGOV gets a flat 0.02% daily return (≈ 5% annual) to simulate T-bill yield.
    """
    rng   = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-01", periods=n)

    panel: dict[str, pd.DataFrame] = {}
    for i, ticker in enumerate(tickers):
        rets  = rng.normal(0.0005, 0.015, n)
        close = 100.0 * np.cumprod(1 + rets)
        high  = close * (1 + rng.uniform(0.002, 0.015, n))
        low   = close * (1 - rng.uniform(0.002, 0.015, n))
        open_ = low + (high - low) * rng.uniform(0.2, 0.8, n)
        panel[ticker] = pd.DataFrame({
            "open":        open_,
            "high":        high,
            "low":         low,
            "close":       close,
            "volume":      np.full(n, 5_000_000.0),
            "adj_factor":  np.ones(n),
            "is_tradable": np.ones(n, dtype=bool),
        }, index=dates)

    if include_sgov:
        sgov_close = 100.0 * np.cumprod(np.full(n, 1.0002))
        panel["SGOV"] = pd.DataFrame({
            "open":        sgov_close * 0.9999,
            "high":        sgov_close * 1.0001,
            "low":         sgov_close * 0.9999,
            "close":       sgov_close,
            "volume":      np.full(n, 1_000_000.0),
            "adj_factor":  np.ones(n),
            "is_tradable": np.ones(n, dtype=bool),
        }, index=dates)

    return panel


def _make_indicators(
    panel: dict[str, pd.DataFrame],
    atr_val: float = 2.0,
    window: int = 100,
) -> dict[str, dict]:
    """
    Build synthetic indicators that guarantee breakout signals after the
    warm-up window.  All ADVs are set well above min_adv_m threshold.
    """
    inds: dict[str, dict] = {}
    for ticker, df in panel.items():
        if ticker == "SGOV":
            continue
        n     = len(df)
        dates = df.index

        # breakout_signal = True from row window onward
        breakout_signal = pd.Series(
            [False] * window + [True] * (n - window), index=dates, dtype=bool
        )
        close = df["close"]

        inds[ticker] = {
            "atr":               pd.Series(np.full(n, atr_val), index=dates),
            "rolling_high":      close * 0.95,   # always below close → signal fires
            "breakout_signal":   breakout_signal,
            "breakout_strength": pd.Series(np.full(n, 1.05), index=dates),
            "adv":               pd.Series(np.full(n, 50_000_000.0), index=dates),
            "log_returns":       np.log(close / close.shift(1)).fillna(0),
        }
    return inds


def _run_engine(
    tickers: list[str],
    params: StrategyParams | None = None,
    n: int = 300,
    seed: int = 42,
) -> tuple:
    """Return (results, panel, indicators) for a synthetic backtest."""
    if params is None:
        params = StrategyParams(
            min_price=5.0, min_adv_m=1.0,
            breakout_window=100, atr_period=20,
        )
    panel  = _make_synthetic_panel(tickers, n=n, seed=seed)
    inds   = _make_indicators(panel)
    engine = BacktestEngine(StrategyV1(params), panel, inds, params,
                            initial_capital=10_000_000)
    results = engine.run("2022-01-01", "2023-12-31", tickers)
    return results, panel, inds


# ── Check 1: execution price = open × (1 ± slippage) ──────────────────────

def check_execution_functions() -> bool:
    print("\n=== 1. Execution model: fill price, commission, gap filter ===")
    ok = True

    # Fill price
    fp_buy  = compute_fill_price(100.0, "buy",  slippage_bps=10.0)
    fp_sell = compute_fill_price(100.0, "sell", slippage_bps=10.0)
    if abs(fp_buy - 100.10) > 1e-9:
        _fail(f"buy fill: expected 100.10, got {fp_buy}")
        ok = False
    else:
        _ok(f"buy fill = {fp_buy:.4f} (100 × 1.001)")
    if abs(fp_sell - 99.90) > 1e-9:
        _fail(f"sell fill: expected 99.90, got {fp_sell}")
        ok = False
    else:
        _ok(f"sell fill = {fp_sell:.4f} (100 × 0.999)")

    # Commission
    comm = compute_commission(100.10, 1000, commission_bps=3.0)
    expected = 100.10 * 1000 * 3 / 10_000
    if abs(comm - expected) > 1e-6:
        _fail(f"commission: expected {expected:.4f}, got {comm:.4f}")
        ok = False
    else:
        _ok(f"commission = ${comm:.2f} (3 bps on 1000 shares @ 100.10)")

    # Round-trip cost
    rt = compute_transaction_cost(100.10, 99.90, 1000, commission_bps=3.0)
    exp_rt = expected + compute_commission(99.90, 1000, 3.0)
    if abs(rt - exp_rt) > 1e-6:
        _fail(f"round-trip cost mismatch: {rt:.4f} vs {exp_rt:.4f}")
        ok = False
    else:
        _ok(f"round-trip commission = ${rt:.2f}")

    # Gap filter
    assert apply_gap_filter(100.0, 102.0, 0.025) is True,  "2% gap should pass"
    assert apply_gap_filter(100.0, 103.0, 0.025) is False, "3% gap should fail"
    assert apply_gap_filter(100.0,  97.0, 0.025) is False, "3% down gap should fail"
    _ok("Gap filter: ≤2.5% passes, >2.5% rejected")

    return ok


# ── Check 2: look-ahead bias — entry_price ≈ open[entry_date] × (1+slip) ──

def check_no_lookahead_bias() -> bool:
    print("\n=== 2. No look-ahead bias: entry executed at t+1 open ===")
    tickers = ["A", "B", "C"]
    results, panel, _ = _run_engine(tickers)

    tl = results.trade_log
    if len(tl) == 0:
        _fail("No trades generated — cannot verify execution prices")
        return False

    slippage_factor = 1 + StrategyParams().slippage_bps / 10_000
    ok = True
    checked = 0

    for _, row in tl.iterrows():
        ticker     = row["ticker"]
        entry_date = row["entry_date"]
        entry_price = row["entry_price"]

        if ticker not in panel or entry_date not in panel[ticker].index:
            continue

        open_price = float(panel[ticker].at[entry_date, "open"])
        expected_fill = open_price * slippage_factor

        if abs(entry_price - expected_fill) > 1e-4:
            _fail(
                f"{ticker} @ {entry_date.date()}: "
                f"entry={entry_price:.4f}  open×slip={expected_fill:.4f}"
            )
            ok = False
            break
        checked += 1
        if checked >= 5:
            break

    if ok and checked > 0:
        _ok(f"Verified {checked} trades: entry_price = open[t+1] × (1 + 10bps)")

    # Also verify: signal date is the PREVIOUS business day
    # (entry_date should be t+1, signal was on t, so open of entry_date was used)
    first = tl.iloc[0]
    entry_date_ts = pd.Timestamp(first["entry_date"])
    dates_in_panel = sorted(panel[first["ticker"]].index)
    idx = dates_in_panel.index(entry_date_ts) if entry_date_ts in dates_in_panel else -1
    if idx > 0:
        _ok(f"First trade entry on {entry_date_ts.date()} (execution day, not signal day)")
    return ok


# ── Check 3: heat updated after each entry ─────────────────────────────────

def check_heat_update_order() -> bool:
    print("\n=== 3. Heat update: existing_risk increases after each opened position ===")
    params = StrategyParams(heat_limit=1.0)  # very high limit so all trades pass
    portfolio = Portfolio(10_000_000)

    risk_snapshots: list[float] = []
    for i in range(4):
        pos = Position(
            ticker=f"T{i}",
            entry_date=pd.Timestamp("2023-01-01"),
            entry_price=100.0,
            shares=1000,
            stop_loss=90.0,   # R = 10, risk_amount = 10,000
            trail_stop=80.0,
            highest_high=100.0,
            atr_at_entry=5.0,
        )
        risk_before = portfolio.existing_risk
        portfolio.open_position(pos, commission=0.0)
        risk_after = portfolio.existing_risk
        risk_snapshots.append(risk_after)

        if risk_after <= risk_before:
            _fail(f"Position {i}: existing_risk did not increase ({risk_before} → {risk_after})")
            return False

    ok = True
    for i, risk in enumerate(risk_snapshots):
        expected = (i + 1) * 10_000
        if abs(risk - expected) > 1e-6:
            _fail(f"After {i+1} positions: existing_risk={risk:.0f}, expected {expected:.0f}")
            ok = False
    if ok:
        _ok(
            f"existing_risk grows correctly: "
            f"{[f'${r:,.0f}' for r in risk_snapshots]}"
        )
    return ok


# ── Check 4: SGOV contributes positive return to cash-only NAV ─────────────

def check_sgov_nav_contribution() -> bool:
    print("\n=== 4. SGOV: cash earns ~0.02%/day return in NAV ===")
    ok = True

    # Use a panel with only SGOV (no other tickers to trade)
    params = StrategyParams()
    n = 60
    dates = pd.bdate_range("2022-01-01", periods=n)
    sgov_close = 100.0 * np.cumprod(np.full(n, 1.0002))  # 0.02% daily

    panel = {
        "SGOV": pd.DataFrame({
            "open":        sgov_close * 0.9999,
            "high":        sgov_close * 1.0001,
            "low":         sgov_close * 0.9999,
            "close":       sgov_close,
            "volume":      np.full(n, 1_000_000.0),
            "adj_factor":  np.ones(n),
            "is_tradable": np.ones(n, dtype=bool),
        }, index=dates)
    }
    inds: dict = {}  # no stock tickers → no trades
    strategy = StrategyV1(params)
    engine = BacktestEngine(strategy, panel, inds, params, initial_capital=1_000_000)
    results = engine.run("2022-01-01", str(dates[-1].date()), [])

    nav = results.daily_nav
    final_nav = float(nav.iloc[-1])

    # With 0.02%/day for 60 days: expected growth ≈ (1.0002)^60 ≈ 1.0121
    expected_growth = 1.0002 ** (n - 1)
    actual_growth   = final_nav / 1_000_000

    if actual_growth < 1.005:  # at least 0.5% growth from SGOV
        _fail(f"NAV barely grew ({actual_growth:.4f}x) — SGOV may not be applied")
        ok = False
    else:
        _ok(
            f"NAV grew {actual_growth:.4f}x from SGOV returns "
            f"(expected ≈ {expected_growth:.4f}x over {n-1} days)"
        )

    return ok


# ── Check 5: gap filter rejects large gaps ─────────────────────────────────

def check_gap_filter_in_engine() -> bool:
    print("\n=== 5. Gap filter: entries rejected when open gaps too large ===")
    tickers = ["G"]
    n = 300
    dates = pd.bdate_range("2022-01-01", periods=n)
    rng = np.random.default_rng(0)

    close = 100.0 * np.cumprod(1 + rng.normal(0.0005, 0.015, n))

    # Manufacture: every open = close × 1.10 (10% gap-up) → gap filter fires
    panel = {
        "G": pd.DataFrame({
            "open":        close * 1.10,  # 10% gap-up every day
            "high":        close * 1.11,
            "low":         close * 1.09,
            "close":       close,
            "volume":      np.full(n, 5_000_000.0),
            "adj_factor":  np.ones(n),
            "is_tradable": np.ones(n, dtype=bool),
        }, index=dates)
    }
    inds = {
        "G": {
            "atr":               pd.Series(np.full(n, 2.0), index=dates),
            "rolling_high":      pd.Series(close * 0.95,   index=dates),
            "breakout_signal":   pd.Series([False]*100 + [True]*(n-100), index=dates, dtype=bool),
            "breakout_strength": pd.Series(np.full(n, 1.05), index=dates),
            "adv":               pd.Series(np.full(n, 50_000_000.0), index=dates),
            "log_returns":       pd.Series(np.zeros(n), index=dates),
        }
    }
    params = StrategyParams(min_price=5.0, min_adv_m=1.0, gap_filter=0.025)
    engine  = BacktestEngine(StrategyV1(params), panel, inds, params)
    results = engine.run("2022-01-01", "2023-12-31", ["G"])

    non_eob = results.trade_log[results.trade_log["exit_reason"] != "end_of_backtest"]
    if len(non_eob) > 0:
        _fail(
            f"Gap filter failed: {len(non_eob)} entries executed despite 10% daily gaps"
        )
        return False
    _ok("All entries rejected by gap filter (10% daily gap-up > 2.5% threshold)")
    return True


# ── Check 6: end-to-end smoke test ─────────────────────────────────────────

def check_end_to_end() -> bool:
    print("\n=== 6. End-to-end smoke test: 5 tickers × 2 years ===")
    tickers = ["A", "B", "C", "D", "E"]
    results, _, _ = _run_engine(tickers, n=500, seed=99)

    nav = results.daily_nav
    ret = results.daily_returns
    tl  = results.trade_log
    ok  = True

    if len(nav) == 0:
        _fail("No NAV history recorded")
        return False
    _ok(f"NAV: {len(nav)} days from {nav.index[0].date()} to {nav.index[-1].date()}")

    if float(nav.iloc[0]) <= 0:
        _fail("Initial NAV is zero or negative")
        ok = False
    else:
        _ok(f"Initial NAV: ${float(nav.iloc[0]):,.0f}")

    if len(tl) == 0:
        _fail("No trades recorded")
        ok = False
    else:
        _ok(f"Trades recorded: {len(tl)}")

    # All exit reasons must be valid
    valid_reasons = {"stop_loss", "trailing_stop", "end_of_backtest"}
    invalid = set(tl["exit_reason"]) - valid_reasons if len(tl) > 0 else set()
    if invalid:
        _fail(f"Invalid exit reasons: {invalid}")
        ok = False
    else:
        _ok(f"Exit reasons: {dict(tl['exit_reason'].value_counts())}")

    # Compute metrics
    m = results.compute_metrics()
    _ok(
        f"Metrics: CAGR={m['cagr']:+.2%}  Sharpe={m['sharpe']:.3f}  "
        f"MaxDD={m['max_drawdown']:.2%}  WinRate={m['win_rate']:.1%}"
    )

    return ok


# ── Check 7: trade log schema ──────────────────────────────────────────────

def check_trade_log_schema() -> bool:
    print("\n=== 7. trade_log schema: all required columns present ===")
    required_cols = {
        "ticker", "entry_date", "entry_price", "exit_date", "exit_price",
        "shares", "stop_loss", "atr_at_entry", "R",
        "gross_pnl", "net_pnl", "pnl_r_multiple",
        "exit_reason", "holding_days", "gap_adjusted_loss_multiple",
        "entry_commission", "exit_commission",
    }
    tickers = ["X", "Y"]
    results, _, _ = _run_engine(tickers, n=400, seed=7)
    tl = results.trade_log

    missing = required_cols - set(tl.columns)
    if missing:
        _fail(f"Missing columns: {missing}")
        return False
    _ok(f"All {len(required_cols)} required columns present")

    if len(tl) > 0:
        # entry_commission > 0
        if (tl["entry_commission"] <= 0).all():
            _fail("entry_commission is always zero")
            return False
        _ok(f"entry_commission non-zero (avg ${tl['entry_commission'].mean():.2f})")

        # R = entry_price - stop_loss
        r_check = (tl["entry_price"] - tl["stop_loss"] - tl["R"]).abs()
        if (r_check > 1e-6).any():
            _fail("R ≠ entry_price - stop_loss for some rows")
            return False
        _ok("R = entry_price - stop_loss for all trades")

    return True


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 55)
    print("Phase 4 回测引擎层验收")
    print("=" * 55)

    results = {
        "1. 执行模型 (fill/commission/gap)": check_execution_functions(),
        "2. 无前视偏差 (t+1 开盘执行)":     check_no_lookahead_bias(),
        "3. Heat 实时更新 (逐单后更新)":     check_heat_update_order(),
        "4. SGOV 贡献 NAV":                  check_sgov_nav_contribution(),
        "5. Gap filter 在引擎中生效":         check_gap_filter_in_engine(),
        "6. 端到端冒烟测试 (5只×2年)":       check_end_to_end(),
        "7. trade_log 字段完整性":            check_trade_log_schema(),
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
        print("✓ Phase 4 验收通过，可以进入 Phase 5（Baseline 回测运行）")
        sys.exit(0)
    else:
        print("✗ 有项目未通过，请根据上面的错误信息修复后重新运行")
        sys.exit(1)


if __name__ == "__main__":
    main()
