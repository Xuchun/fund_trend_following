"""
Phase 6 Week 1 — Verification Script

Loads saved backtest results from results/v1/ and validates that
analysis.metrics.compute_metrics() produces correct values.

Usage:
    python src/scripts/verify_phase6.py

Acceptance criteria (design-spec Section 12):
  ✓ analysis.metrics importable without any backtest/strategy dependencies
  ✓ All expected metric keys present
  ✓ Key values match saved metrics.json (within floating-point tolerance)
  ✓ market_exposure is in [0, 1] and plausible
  ✓ Drawdown helpers (drawdown_series, rolling_sharpe, annual_returns) run without error
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── path setup ─────────────────────────────────────────────────────────────
_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "src"))

import pandas as pd

# ── import ONLY from analysis — no backtest/strategy imports ───────────────
from analysis.metrics import (          # noqa: E402
    annual_returns,
    compute_metrics,
    drawdown_series,
    rolling_sharpe,
)

RESULTS_DIR   = _root / "results" / "v1"
INITIAL_CAP   = 10_000_000.0
RISK_FREE_RATE = 0.02
TOL           = 1e-6   # tolerance for float comparisons

REQUIRED_KEYS = [
    # Returns
    "total_return", "cagr",
    # Risk
    "annual_vol", "max_drawdown", "max_dd_duration_days",
    "avg_deep_dd_duration_days", "n_deep_dd_episodes",
    # Risk-adjusted
    "sharpe", "sortino", "calmar",
    # Trade stats
    "n_trades", "win_rate", "avg_win_r", "avg_loss_r",
    "profit_factor", "avg_holding_days", "trades_per_year",
    # Portfolio
    "annual_turnover", "market_exposure",
]

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"

_ok    = f"{GREEN}✓{RESET}"
_fail  = f"{RED}✗{RESET}"
_warn  = f"{YELLOW}⚠{RESET}"


def _check(label: str, cond: bool, detail: str = "") -> bool:
    status = _ok if cond else _fail
    print(f"  {status}  {label}" + (f"  ({detail})" if detail else ""))
    return cond


def main() -> int:
    print("\n" + "=" * 62)
    print("  Phase 6 Week 1 — analysis/metrics.py  Verification")
    print("=" * 62)

    failures = 0

    # ── 1. Load data ────────────────────────────────────────────────────────
    print("\n[1] Loading saved results …")
    nav_df   = pd.read_csv(RESULTS_DIR / "nav.csv",    index_col="date", parse_dates=True)
    nav      = nav_df["nav"]
    ret      = nav_df["return"]
    trades   = pd.read_csv(RESULTS_DIR / "trades.csv", parse_dates=["entry_date", "exit_date"])
    with open(RESULTS_DIR / "metrics.json") as f:
        saved = json.load(f)
    print(f"  {_ok}  nav.csv  ({len(nav):,} rows, {nav.index[0].date()} → {nav.index[-1].date()})")
    print(f"  {_ok}  trades.csv  ({len(trades):,} trades)")
    print(f"  {_ok}  metrics.json  ({len(saved)} keys)")

    # ── 2. Run analysis.metrics.compute_metrics() ───────────────────────────
    print("\n[2] Running analysis.metrics.compute_metrics() …")
    m = compute_metrics(
        daily_nav=nav,
        daily_returns=ret,
        trade_log=trades,
        initial_capital=INITIAL_CAP,
        risk_free_rate=RISK_FREE_RATE,
    )
    print(f"  {_ok}  Returned dict with {len(m)} keys")

    # ── 3. Required keys ────────────────────────────────────────────────────
    print("\n[3] Checking required keys …")
    for key in REQUIRED_KEYS:
        ok = key in m
        if not _check(key, ok, f"value={m.get(key, 'MISSING'):.6g}" if ok else "MISSING"):
            failures += 1

    # ── 4. Cross-validate against saved metrics.json ───────────────────────
    print("\n[4] Cross-validating against saved metrics.json …")
    cross_check = [
        "cagr", "total_return", "annual_vol",
        "max_drawdown", "max_dd_duration_days",
        "sharpe", "sortino", "calmar",
        "n_trades", "win_rate", "profit_factor",
        "annual_turnover",
    ]
    for key in cross_check:
        if key not in saved or key not in m:
            _check(key, False, "key missing in saved or computed")
            failures += 1
            continue
        sv = saved[key]
        cv = m[key]
        if sv is None:
            _check(key, True, "saved=None (skip)")
            continue
        diff = abs(float(sv) - float(cv))
        ok   = diff < TOL
        _check(
            key,
            ok,
            f"saved={sv:.8g}  computed={cv:.8g}  diff={diff:.2e}",
        )
        if not ok:
            failures += 1

    # ── 5. market_exposure sanity ───────────────────────────────────────────
    print("\n[5] market_exposure sanity …")
    exp = m.get("market_exposure", -1)
    if not _check("market_exposure in [0, 1]", 0.0 <= exp <= 1.0, f"{exp:.4f}"):
        failures += 1
    if not _check("market_exposure > 0.10", exp > 0.10,
                  f"{exp:.2%} (trend-following should be in market >10% of time)"):
        failures += 1
    print(f"  {_warn}  market_exposure = {exp:.2%}  "
          f"(days in market / total trading days)")

    # ── 6. Drawdown helpers ─────────────────────────────────────────────────
    print("\n[6] Drawdown helpers …")
    dd = drawdown_series(nav)
    _check("drawdown_series shape", len(dd) == len(nav), f"{len(dd):,} rows")
    _check("drawdown_series ≤ 0",   float(dd.max()) <= 0.0 + 1e-10,
           f"max={float(dd.max()):.6f}")
    _check("drawdown_series min matches max_drawdown",
           abs(float(dd.min()) - m["max_drawdown"]) < TOL,
           f"{float(dd.min()):.6f} vs {m['max_drawdown']:.6f}")

    rs = rolling_sharpe(ret, window=252, risk_free_rate=RISK_FREE_RATE)
    _check("rolling_sharpe shape",    len(rs) == len(ret), f"{len(rs):,} rows")
    _check("rolling_sharpe has NaNs", rs.isna().any(), "first 251 rows are NaN — expected")

    ar = annual_returns(nav)
    if not _check("annual_returns non-empty", len(ar) > 0, f"{len(ar)} years"):
        failures += 1
    is_int = pd.api.types.is_integer_dtype(ar.index.dtype)
    if not _check("annual_returns index is integer", is_int, f"dtype={ar.index.dtype}"):
        failures += 1

    # ── 7. Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    if failures == 0:
        print(f"  {GREEN}ALL CHECKS PASSED — Phase 6 Week 1 ACCEPTED{RESET}")
    else:
        print(f"  {RED}{failures} CHECK(S) FAILED{RESET}")

    # Print key metrics for human review
    print("\n  Key metrics (rf=2%):")
    print(f"    CAGR              : {m['cagr']*100:+.2f}%")
    print(f"    Total Return      : {m['total_return']*100:+.1f}%")
    print(f"    Max Drawdown      : {m['max_drawdown']*100:.1f}%")
    print(f"    Max DD Duration   : {m['max_dd_duration_days']:,} trading days")
    print(f"    Sharpe (rf=2%)    : {m['sharpe']:+.4f}")
    print(f"    Sortino           : {m['sortino']:+.4f}")
    print(f"    Calmar            : {m['calmar']:+.4f}")
    print(f"    Win Rate          : {m['win_rate']:.1%}")
    print(f"    Profit Factor     : {m['profit_factor']:.3f}")
    print(f"    Avg Holding Days  : {m['avg_holding_days']:.1f} days")
    print(f"    Trades / Year     : {m['trades_per_year']:.0f}")
    print(f"    Annual Turnover   : {m['annual_turnover']:.2f}×")
    print(f"    Market Exposure   : {m['market_exposure']:.2%}")
    print("=" * 62 + "\n")

    return failures


if __name__ == "__main__":
    sys.exit(main())
