"""
Baseline report generator.

Produces all deliverables specified in design spec Section 1.2.1.2:
  - nav.csv / trades.csv / metrics.json
  - report.html (QuantStats)
  - nav_vs_spy.png
  - rolling_sharpe.png
  - pnl_distribution.png
  - sanity check summary (console + sanity.txt)
"""

from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib
matplotlib.use("Agg")          # non-interactive backend (safe in scripts)
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from backtest.results import BacktestResults

logger = logging.getLogger(__name__)

# ── Colour palette ─────────────────────────────────────────────────────────
_STRATEGY_COLOR = "#1f77b4"
_BENCHMARK_COLOR = "#aaaaaa"
_GREEN = "#2ca02c"
_RED   = "#d62728"


# ── 1. CSV / JSON outputs ──────────────────────────────────────────────────

def save_nav_csv(results: "BacktestResults", path: Path) -> None:
    df = results.daily_nav.rename("nav").to_frame()
    df["return"] = results.daily_returns
    df.index.name = "date"
    df.to_csv(path)
    logger.info("Saved NAV → %s  (%d rows)", path, len(df))


def save_trades_csv(results: "BacktestResults", path: Path) -> None:
    results.trade_log.to_csv(path, index=False)
    logger.info("Saved trades → %s  (%d trades)", path, len(results.trade_log))


def save_metrics_json(results: "BacktestResults", spy_raw: pd.DataFrame | None,
                      path: Path) -> None:
    metrics = results.compute_metrics()

    if spy_raw is not None and len(spy_raw) > 0:
        spy_adj_close = spy_raw["close"] * spy_raw["adj_factor"]
        spy_rets      = spy_adj_close.pct_change().fillna(0.0)
        spy_nav       = (1 + spy_rets).cumprod()
        n_days        = len(spy_nav)
        spy_cagr      = float(spy_nav.iloc[-1]) ** (252 / n_days) - 1 if n_days > 1 else 0.0
        spy_vol       = float(spy_rets.std() * np.sqrt(252))
        spy_sharpe    = (float(spy_rets.mean()) * 252 - 0.02) / spy_vol if spy_vol > 0 else 0.0
        spy_cum_max   = spy_nav.cummax()
        spy_maxdd     = float(((spy_nav - spy_cum_max) / spy_cum_max).min())
        metrics["spy_cagr"]    = spy_cagr
        metrics["spy_sharpe"]  = spy_sharpe
        metrics["spy_max_drawdown"] = spy_maxdd

    # Make JSON-serialisable
    clean = {}
    for k, v in metrics.items():
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            clean[k] = None
        else:
            clean[k] = v

    path.write_text(json.dumps(clean, indent=2, default=str))
    logger.info("Saved metrics → %s", path)


# ── 2. Plots ───────────────────────────────────────────────────────────────

def _align_spy(strategy_returns: pd.Series,
               spy_raw: pd.DataFrame | None) -> pd.Series | None:
    """Extract SPY daily returns aligned to the strategy's date index."""
    if spy_raw is None:
        return None
    # Use adjusted close for total return
    adj = spy_raw["close"] * spy_raw["adj_factor"]
    spy_ret = adj.pct_change().reindex(strategy_returns.index).fillna(0.0)
    return spy_ret


def plot_nav_vs_spy(results: "BacktestResults",
                    spy_raw: pd.DataFrame | None,
                    path: Path) -> None:
    """Normalised NAV curve vs SPY (both starting at 1.0)."""
    nav  = results.daily_nav
    norm = nav / float(nav.iloc[0])

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(norm.index, norm.values, color=_STRATEGY_COLOR,
            linewidth=1.4, label="Strategy 1.0")

    if spy_raw is not None:
        spy_ret  = _align_spy(results.daily_returns, spy_raw)
        spy_norm = (1 + spy_ret).cumprod()
        ax.plot(spy_norm.index, spy_norm.values, color=_BENCHMARK_COLOR,
                linewidth=1.0, linestyle="--", label="SPY (benchmark)")

    ax.set_title("Normalised NAV vs SPY", fontsize=13)
    ax.set_ylabel("Portfolio value (1 = initial capital)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.1f}x"))
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Saved nav_vs_spy → %s", path)


def plot_rolling_sharpe(results: "BacktestResults",
                        spy_raw: pd.DataFrame | None,
                        path: Path,
                        window: int = 252) -> None:
    """252-day rolling annualised Sharpe ratio."""
    ret   = results.daily_returns
    rs    = ret.rolling(window).apply(
        lambda x: (x.mean() * 252) / (x.std() * np.sqrt(252)) if x.std() > 0 else 0.0,
        raw=True,
    )

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(rs.index, rs.values, color=_STRATEGY_COLOR, linewidth=1.2,
            label=f"Strategy rolling Sharpe ({window}d)")

    if spy_raw is not None:
        spy_ret = _align_spy(ret, spy_raw)
        spy_rs  = spy_ret.rolling(window).apply(
            lambda x: (x.mean() * 252) / (x.std() * np.sqrt(252)) if x.std() > 0 else 0.0,
            raw=True,
        )
        ax.plot(spy_rs.index, spy_rs.values, color=_BENCHMARK_COLOR,
                linewidth=0.8, linestyle="--", label="SPY rolling Sharpe")

    ax.axhline(0, color="black", linewidth=0.8, linestyle=":")
    ax.axhline(1, color=_GREEN,  linewidth=0.6, linestyle="--", alpha=0.5)
    ax.set_title(f"Rolling {window}-Day Sharpe Ratio", fontsize=13)
    ax.set_ylabel("Sharpe")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Saved rolling_sharpe → %s", path)


def plot_pnl_distribution(results: "BacktestResults", path: Path) -> None:
    """Histogram of trade R-multiples with win/loss colouring."""
    tl = results.trade_log
    if len(tl) == 0:
        logger.warning("No trades — skipping pnl_distribution plot")
        return

    r_mult = tl["pnl_r_multiple"].dropna()

    fig, ax = plt.subplots(figsize=(10, 4))
    bins = np.linspace(max(r_mult.min() - 0.5, -6), min(r_mult.max() + 0.5, 8), 50)

    wins   = r_mult[r_mult > 0]
    losses = r_mult[r_mult <= 0]
    ax.hist(losses.values, bins=bins, color=_RED,   alpha=0.7, label=f"Loss  ({len(losses)})")
    ax.hist(wins.values,   bins=bins, color=_GREEN, alpha=0.7, label=f"Win   ({len(wins)})")

    for x, ls in [(-1, "--"), (0, "-"), (2, ":")]:
        ax.axvline(x, color="black", linewidth=0.8, linestyle=ls, alpha=0.7)

    ax.set_title("Trade PnL Distribution (R-multiples)", fontsize=13)
    ax.set_xlabel("R-multiple  (1R = entry risk)")
    ax.set_ylabel("Number of trades")
    ax.legend()
    ax.grid(alpha=0.3, axis="y")

    textstr = (
        f"n={len(r_mult)}  "
        f"median={r_mult.median():.2f}R  "
        f"mean={r_mult.mean():.2f}R  "
        f"win%={len(wins)/len(r_mult):.1%}"
    )
    ax.text(0.98, 0.97, textstr, transform=ax.transAxes,
            ha="right", va="top", fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="wheat", alpha=0.5))

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Saved pnl_distribution → %s", path)


def plot_drawdown(results: "BacktestResults", path: Path) -> None:
    """Underwater equity curve (drawdown from peak)."""
    nav     = results.daily_nav
    cum_max = nav.cummax()
    dd      = (nav - cum_max) / cum_max * 100   # in %

    fig, ax = plt.subplots(figsize=(12, 3))
    ax.fill_between(dd.index, dd.values, 0, color=_RED, alpha=0.5)
    ax.plot(dd.index, dd.values, color=_RED, linewidth=0.6)
    ax.set_title("Drawdown from Peak (%)", fontsize=13)
    ax.set_ylabel("Drawdown %")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0f}%"))
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Saved drawdown → %s", path)


# ── 3. QuantStats HTML ─────────────────────────────────────────────────────

def generate_quantstats_html(results: "BacktestResults",
                              spy_raw: pd.DataFrame | None,
                              path: Path) -> bool:
    """
    Generate a QuantStats tearsheet HTML report.
    Returns True on success, False if QuantStats is unavailable.
    """
    try:
        import quantstats as qs
    except ImportError:
        logger.warning("quantstats not installed — skipping HTML report")
        return False

    ret = results.daily_returns.copy()
    ret = ret.iloc[1:]           # drop first 0.0 row
    ret.index = pd.DatetimeIndex(ret.index)

    benchmark = None
    if spy_raw is not None:
        spy_ret   = _align_spy(results.daily_returns, spy_raw).iloc[1:]
        spy_ret.index = pd.DatetimeIndex(spy_ret.index)
        benchmark = spy_ret

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            qs.reports.html(
                returns=ret,
                benchmark=benchmark,
                output=str(path),
                title="Strategy 1.0 — Baseline Backtest",
                download_filename=path.name,
            )
            logger.info("Saved QuantStats HTML → %s", path)
            return True
        except Exception as e:
            logger.warning("QuantStats HTML generation failed: %s", e)
            return False


# ── 4. Sanity checks ───────────────────────────────────────────────────────

def run_sanity_checks(results: "BacktestResults",
                      spy_raw: pd.DataFrame | None) -> list[str]:
    """
    Run basic sanity checks on backtest results.

    Returns a list of warning strings (empty = all clear).
    """
    warnings_list: list[str] = []
    tl  = results.trade_log
    nav = results.daily_nav
    m   = results.compute_metrics()

    # NAV should never go to zero or negative
    if float(nav.min()) <= 0:
        warnings_list.append(f"NAV went non-positive: min={float(nav.min()):.0f}")

    # Trades per year sanity
    n_years = len(nav) / 252
    if n_years > 0:
        tpy = m["n_trades"] / n_years
        if tpy < 2:
            warnings_list.append(f"Very few trades: {tpy:.1f}/year (expected ≥5)")
        if tpy > 500:
            warnings_list.append(f"Suspiciously many trades: {tpy:.1f}/year")

    if len(tl) > 0:
        # Any trade with R ≤ 0
        bad_r = tl[tl["R"] <= 0]
        if len(bad_r) > 0:
            warnings_list.append(f"{len(bad_r)} trades with R ≤ 0 (stop above entry)")

        # Holding days: anything > 3 years is suspicious
        long_hold = tl[tl["holding_days"] > 756]
        if len(long_hold) > 0:
            warnings_list.append(
                f"{len(long_hold)} trades held > 3 years "
                f"(tickers: {list(long_hold['ticker'].unique()[:5])})"
            )

        # Commission sanity: should be ≈ 3 bps, not much more
        tl2 = tl[tl["entry_price"] * tl["shares"] > 0].copy()
        if len(tl2) > 0:
            comm_bps = (tl2["entry_commission"] /
                        (tl2["entry_price"] * tl2["shares"]) * 10_000)
            if comm_bps.mean() > 10:
                warnings_list.append(
                    f"Average entry commission {comm_bps.mean():.1f} bps "
                    f"(expected ≈ 3 bps)"
                )

        # Any trade where exit_price < stop_loss by more than 5R (large gap risk)
        stop_loss_exits = tl[tl["exit_reason"] == "stop_loss"]
        if len(stop_loss_exits) > 0:
            gap_mult = stop_loss_exits["gap_adjusted_loss_multiple"]
            extreme  = gap_mult[gap_mult < -5]
            if len(extreme) > 0:
                warnings_list.append(
                    f"{len(extreme)} stop-loss exits with gap > 5R "
                    f"(worst: {gap_mult.min():.1f}R)"
                )

    # Correlation with SPY (strategy shouldn't be 100% correlated)
    if spy_raw is not None:
        spy_ret = _align_spy(results.daily_returns, spy_raw)
        corr    = results.daily_returns.corr(spy_ret)
        if corr > 0.95:
            warnings_list.append(
                f"Strategy return correlation with SPY is very high ({corr:.2f}) "
                f"— may be tracking SPY rather than trend-following"
            )

    return warnings_list


# ── 5. Full report orchestrator ────────────────────────────────────────────

def generate_baseline_report(
    results: "BacktestResults",
    spy_raw: pd.DataFrame | None,
    output_dir: Path,
) -> None:
    """
    Generate all baseline deliverables and save to output_dir.

    Outputs:
      nav.csv, trades.csv, metrics.json,
      nav_vs_spy.png, rolling_sharpe.png, pnl_distribution.png,
      drawdown.png, report.html, sanity.txt
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # CSVs and JSON
    save_nav_csv   (results,              output_dir / "nav.csv")
    save_trades_csv(results,              output_dir / "trades.csv")
    save_metrics_json(results, spy_raw,   output_dir / "metrics.json")
    if not results.daily_entry_stats.empty:
        results.daily_entry_stats.to_csv(output_dir / "daily_entry_stats.csv")

    # Plots
    plot_nav_vs_spy      (results, spy_raw, output_dir / "nav_vs_spy.png")
    plot_rolling_sharpe  (results, spy_raw, output_dir / "rolling_sharpe.png")
    plot_pnl_distribution(results,          output_dir / "pnl_distribution.png")
    plot_drawdown        (results,          output_dir / "drawdown.png")

    # QuantStats HTML (optional dependency)
    generate_quantstats_html(results, spy_raw, output_dir / "report.html")

    # Sanity check
    issues = run_sanity_checks(results, spy_raw)
    sanity_path = output_dir / "sanity.txt"
    if issues:
        sanity_lines = ["⚠ Sanity check warnings:\n"] + [f"  - {w}\n" for w in issues]
        sanity_path.write_text("".join(sanity_lines))
        print("\n⚠ Sanity check warnings:")
        for w in issues:
            print(f"  - {w}")
    else:
        sanity_path.write_text("✓ All sanity checks passed.\n")
        print("\n✓ All sanity checks passed.")
