"""
Trade-level execution diagnostics — Phase 6, Week 2.

Standalone module: accepts only pd.DataFrame (trade log), returns plain dict.
No imports from backtest/, strategy/, or data/.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ── Public API ─────────────────────────────────────────────────────────────


def run_diagnostics(trade_log: pd.DataFrame) -> dict:
    """
    Compute trade-level execution diagnostics.

    Parameters
    ----------
    trade_log : pd.DataFrame
        One row per completed trade.  Expected columns (subset):
        exit_reason, gap_adjusted_loss_multiple, net_pnl, pnl_r_multiple,
        exit_date, entry_date, holding_days.

    Returns
    -------
    dict with sections: gap_loss_stats, execution_quality,
    streak_analysis, yearly_stats.
    """
    diag: dict = {}

    diag["gap_loss_stats"]    = _gap_loss_stats(trade_log)
    diag["execution_quality"] = _execution_quality(diag["gap_loss_stats"])
    diag["streak_analysis"]   = _streak_analysis(trade_log)
    diag["yearly_stats"]      = _yearly_stats(trade_log)

    return diag


def print_diagnostics_report(diag: dict) -> None:
    """Print a formatted diagnostics summary to stdout."""
    _print_gap_loss(diag.get("gap_loss_stats", {}))
    _print_execution_quality(diag.get("execution_quality", {}))
    _print_streak_analysis(diag.get("streak_analysis", {}))
    _print_yearly_stats(diag.get("yearly_stats", []))


# ── Gap-loss stats ─────────────────────────────────────────────────────────


def _gap_loss_stats(tl: pd.DataFrame) -> dict:
    col = "gap_adjusted_loss_multiple"
    reason_col = "exit_reason"

    if reason_col not in tl.columns or col not in tl.columns:
        return _empty_gap_stats()

    stop_mask = tl[reason_col] == "stop_loss"
    stop_trades = tl.loc[stop_mask, col].dropna()
    n = len(stop_trades)

    if n == 0:
        return _empty_gap_stats()

    arr = stop_trades.values.astype(float)

    return {
        "n_stop_trades":   int(n),
        "mean":            float(arr.mean()),
        "median":          float(np.median(arr)),
        "p5":              float(np.percentile(arr, 5)),
        "p25":             float(np.percentile(arr, 25)),
        "p75":             float(np.percentile(arr, 75)),
        "p95":             float(np.percentile(arr, 95)),
        "worst":           float(arr.min()),
        "best":            float(arr.max()),
        "pct_within_1r":  float((arr >= -1.0).sum() / n),
        "pct_beyond_2r":  float((arr < -2.0).sum() / n),
        "pct_beyond_5r":  float((arr < -5.0).sum() / n),
    }


def _empty_gap_stats() -> dict:
    return {
        "n_stop_trades": 0,
        "mean": 0.0, "median": 0.0,
        "p5": 0.0, "p25": 0.0, "p75": 0.0, "p95": 0.0,
        "worst": 0.0, "best": 0.0,
        "pct_within_1r": 0.0, "pct_beyond_2r": 0.0, "pct_beyond_5r": 0.0,
    }


# ── Execution quality ──────────────────────────────────────────────────────


def _execution_quality(gap_stats: dict) -> dict:
    expected = -1.0
    actual   = gap_stats.get("mean", 0.0)
    impact   = actual - expected

    if impact > -0.3:
        assessment = "excellent"
    elif impact > -0.7:
        assessment = "acceptable"
    else:
        assessment = "concerning"

    return {
        "expected_avg_loss_r": expected,
        "actual_avg_loss_r":   actual,
        "gap_impact_r":        impact,
        "assessment":          assessment,
    }


# ── Streak analysis ────────────────────────────────────────────────────────


def _streak_analysis(tl: pd.DataFrame) -> dict:
    if len(tl) == 0:
        return _empty_streak()

    sort_col = "exit_date" if "exit_date" in tl.columns else None
    if sort_col:
        tl_sorted = tl.sort_values(sort_col)
    else:
        tl_sorted = tl.copy()

    pnl_col = "net_pnl" if "net_pnl" in tl_sorted.columns else "gross_pnl"
    if pnl_col not in tl_sorted.columns:
        return _empty_streak()

    is_loss = (tl_sorted[pnl_col].values <= 0)

    # Collect all losing streaks
    streaks: list[int] = []
    cur = 0
    for loss in is_loss:
        if loss:
            cur += 1
        else:
            if cur > 0:
                streaks.append(cur)
            cur = 0
    if cur > 0:
        streaks.append(cur)

    if not streaks:
        return _empty_streak()

    max_streak  = max(streaks)
    total       = len(streaks)
    avg_length  = float(sum(streaks) / total)

    # Build streak_counts: keys are str(length), lengths >= 10 grouped under "10+"
    counts: dict[str, int] = {}
    for s in streaks:
        key = str(s) if s < 10 else "10+"
        counts[key] = counts.get(key, 0) + 1

    pct_ge_5  = float(sum(1 for s in streaks if s >= 5)  / total)
    pct_ge_10 = float(sum(1 for s in streaks if s >= 10) / total)

    return {
        "max_consecutive_losses": int(max_streak),
        "streak_counts":          counts,
        "pct_streak_ge_5":        pct_ge_5,
        "pct_streak_ge_10":       pct_ge_10,
        "avg_streak_length":      avg_length,
        "total_streaks":          total,
    }


def _empty_streak() -> dict:
    return {
        "max_consecutive_losses": 0,
        "streak_counts":          {},
        "pct_streak_ge_5":        0.0,
        "pct_streak_ge_10":       0.0,
        "avg_streak_length":      0.0,
        "total_streaks":          0,
    }


# ── Yearly stats ───────────────────────────────────────────────────────────


def _yearly_stats(tl: pd.DataFrame) -> list[dict]:
    if len(tl) == 0 or "exit_date" not in tl.columns:
        return []

    df = tl.copy()
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    df["_year"] = df["exit_date"].dt.year

    pnl_col = "net_pnl" if "net_pnl" in df.columns else "gross_pnl"
    r_col   = "pnl_r_multiple" if "pnl_r_multiple" in df.columns else None
    hold_col = "holding_days" if "holding_days" in df.columns else None

    rows = []
    for year, grp in df.groupby("_year"):
        n      = len(grp)
        n_wins = int((grp[pnl_col] > 0).sum()) if pnl_col in grp.columns else 0
        wr     = n_wins / n if n > 0 else 0.0

        avg_r    = float(grp[r_col].mean())   if r_col and r_col in grp.columns else 0.0
        worst_r  = float(grp[r_col].min())    if r_col and r_col in grp.columns else 0.0
        best_r   = float(grp[r_col].max())    if r_col and r_col in grp.columns else 0.0
        avg_hold = float(grp[hold_col].mean()) if hold_col and hold_col in grp.columns else 0.0

        rows.append({
            "year":           int(year),
            "n_trades":       int(n),
            "n_wins":         n_wins,
            "win_rate":       wr,
            "avg_r":          avg_r,
            "avg_hold_days":  avg_hold,
            "worst_r":        worst_r,
            "best_r":         best_r,
        })

    return rows


# ── Print helpers ──────────────────────────────────────────────────────────


def _print_gap_loss(gs: dict) -> None:
    print("\n" + "=" * 60)
    print("  Gap 止损分析 (Gap-Loss Statistics)")
    print("=" * 60)
    if not gs or gs.get("n_stop_trades", 0) == 0:
        print("  (无止损交易数据)")
        return
    print(f"  止损交易笔数 : {gs['n_stop_trades']:,}")
    print(f"  均值          : {gs['mean']:+.3f}R")
    print(f"  中位数        : {gs['median']:+.3f}R")
    print(f"  P5 / P95      : {gs['p5']:+.3f}R / {gs['p95']:+.3f}R")
    print(f"  最差          : {gs['worst']:+.3f}R")
    print(f"  在计划止损内  : {gs['pct_within_1r']*100:.1f}%")
    print(f"  缺口 > 2R     : {gs['pct_beyond_2r']*100:.1f}%")
    print(f"  缺口 > 5R     : {gs['pct_beyond_5r']*100:.1f}%")


def _print_execution_quality(eq: dict) -> None:
    print("\n" + "-" * 60)
    print("  执行质量 (Execution Quality)")
    print("-" * 60)
    if not eq:
        return
    print(f"  理论平均止损  : {eq['expected_avg_loss_r']:+.2f}R")
    print(f"  实际平均止损  : {eq['actual_avg_loss_r']:+.3f}R")
    print(f"  缺口影响      : {eq['gap_impact_r']:+.3f}R")
    print(f"  评估          : {eq['assessment'].upper()}")


def _print_streak_analysis(sa: dict) -> None:
    print("\n" + "-" * 60)
    print("  连续亏损序列分析 (Losing Streak Analysis)")
    print("-" * 60)
    if not sa or sa.get("total_streaks", 0) == 0:
        print("  (无亏损序列数据)")
        return
    print(f"  最长连续亏损  : {sa['max_consecutive_losses']} 笔")
    print(f"  亏损序列总数  : {sa['total_streaks']}")
    print(f"  平均序列长度  : {sa['avg_streak_length']:.2f}")
    print(f"  >= 5 笔占比   : {sa['pct_streak_ge_5']*100:.1f}%")
    print(f"  >= 10 笔占比  : {sa['pct_streak_ge_10']*100:.1f}%")
    print()
    print("  序列长度分布:")
    counts = sa.get("streak_counts", {})
    for k in sorted(counts, key=lambda x: int(x.replace("10+", "10"))):
        print(f"    长度 {k:>3}  : {counts[k]} 次")


def _print_yearly_stats(ys: list[dict]) -> None:
    print("\n" + "-" * 60)
    print("  逐年交易质量 (Yearly Trade Quality)")
    print("-" * 60)
    if not ys:
        print("  (无逐年数据)")
        return
    hdr = f"  {'年份':>4}  {'笔数':>5}  {'胜率':>6}  {'均R':>7}  {'最佳R':>7}  {'最差R':>7}  {'均持仓':>6}"
    print(hdr)
    print("  " + "-" * 54)
    for row in ys:
        print(
            f"  {row['year']:>4}  {row['n_trades']:>5}  "
            f"{row['win_rate']*100:>5.1f}%  "
            f"{row['avg_r']:>+7.3f}  "
            f"{row['best_r']:>+7.3f}  "
            f"{row['worst_r']:>+7.3f}  "
            f"{row['avg_hold_days']:>5.0f}d"
        )
    print()
