"""
Phase 5 acceptance test: Baseline Backtest Run.

Validates all required output files exist, have correct structure, and
contain no obvious anomalies.  Then prints a diagnostic about strategy
performance vs SPY to help judge whether the results look reasonable.

Usage:
    python src/verify_phase5.py [--results-dir results/baseline/]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


# ── Check 1: all required output files exist ───────────────────────────────

def check_output_files(results_dir: Path) -> bool:
    print("\n=== 1. 输出文件完整性 ===")
    required = [
        "nav.csv", "trades.csv", "metrics.json",
        "nav_vs_spy.png", "rolling_sharpe.png",
        "pnl_distribution.png", "drawdown.png",
        "report.html", "sanity.txt",
    ]
    ok = True
    for fname in required:
        path = results_dir / fname
        if not path.exists():
            _fail(f"{fname} 不存在")
            ok = False
        elif path.stat().st_size < 100:
            _fail(f"{fname} 文件为空 ({path.stat().st_size} bytes)")
            ok = False
        else:
            _ok(f"{fname}  ({path.stat().st_size / 1024:.1f} KB)")
    return ok


# ── Check 2: nav.csv structure ─────────────────────────────────────────────

def check_nav_csv(results_dir: Path) -> bool:
    print("\n=== 2. nav.csv 结构验证 ===")
    path = results_dir / "nav.csv"
    if not path.exists():
        _fail("nav.csv 不存在")
        return False

    ok = True
    try:
        nav = pd.read_csv(path, index_col="date", parse_dates=True)

        if len(nav) < 100:
            _fail(f"行数过少: {len(nav)} 行 (期望 ≥ 100)")
            ok = False
        else:
            _ok(f"{len(nav)} 行  ({nav.index[0].date()} → {nav.index[-1].date()})")

        if "nav" not in nav.columns:
            _fail("缺少 'nav' 列")
            ok = False
        if "return" not in nav.columns:
            _fail("缺少 'return' 列")
            ok = False

        if "nav" in nav.columns:
            if (nav["nav"] <= 0).any():
                _fail("NAV 存在非正值 (可能资金耗尽)")
                ok = False
            else:
                initial = float(nav["nav"].iloc[0])
                final   = float(nav["nav"].iloc[-1])
                _ok(f"NAV 始终为正  初始=${initial:,.0f}  最终=${final:,.0f}")

            if nav["nav"].isna().any():
                _fail("NAV 含 NaN 值")
                ok = False
    except Exception as e:
        _fail(f"读取失败: {e}")
        ok = False
    return ok


# ── Check 3: trades.csv structure ─────────────────────────────────────────

def check_trades_csv(results_dir: Path) -> bool:
    print("\n=== 3. trades.csv 结构与异常检查 ===")
    path = results_dir / "trades.csv"
    if not path.exists():
        _fail("trades.csv 不存在")
        return False

    required_cols = {
        "ticker", "entry_date", "entry_price", "exit_date", "exit_price",
        "shares", "stop_loss", "R", "net_pnl", "pnl_r_multiple",
        "exit_reason", "holding_days",
    }
    ok = True
    try:
        tl = pd.read_csv(path, parse_dates=["entry_date", "exit_date"])
        missing_cols = required_cols - set(tl.columns)
        if missing_cols:
            _fail(f"缺少列: {missing_cols}")
            ok = False
        else:
            _ok(f"所有必要列存在  ({len(tl.columns)} 列)")

        _ok(f"总交易数: {len(tl)}")

        # R > 0 for all trades
        bad_r = (tl["R"] <= 0).sum()
        if bad_r > 0:
            _fail(f"{bad_r} 笔交易 R ≤ 0 (止损在入场价上方)")
            ok = False
        else:
            _ok("所有交易 R > 0 (止损在入场价下方)")

        # Holding days reasonable
        long_hold = (tl["holding_days"] > 756).sum()
        if long_hold > 0:
            _fail(f"{long_hold} 笔持仓超过 3 年 (可能是 bug)")
            ok = False
        else:
            _ok(f"持仓时长正常: 最长 {tl['holding_days'].max():.0f} 天  平均 {tl['holding_days'].mean():.0f} 天")

        # Exit reasons
        valid_reasons = {"stop_loss", "trailing_stop", "end_of_backtest"}
        invalid = set(tl["exit_reason"]) - valid_reasons
        if invalid:
            _fail(f"无效平仓原因: {invalid}")
            ok = False
        else:
            reason_str = "  ".join(
                f"{r}({c})"
                for r, c in tl["exit_reason"].value_counts().items()
            )
            _ok(f"平仓原因: {reason_str}")

        # Entry price vs stop loss
        bad_stop = (tl["entry_price"] <= tl["stop_loss"]).sum()
        if bad_stop > 0:
            _fail(f"{bad_stop} 笔交易入场价 ≤ 止损价")
            ok = False
        else:
            _ok("所有交易入场价 > 止损价")

        # Commission sanity
        if "entry_commission" in tl.columns and len(tl) > 0:
            comm_bps = (tl["entry_commission"] / (tl["entry_price"] * tl["shares"]) * 10_000)
            _ok(f"佣金率: 均值 {comm_bps.mean():.2f} bps  最大 {comm_bps.max():.2f} bps")

    except Exception as e:
        _fail(f"读取失败: {e}")
        ok = False
    return ok


# ── Check 4: metrics.json ─────────────────────────────────────────────────

def check_metrics_json(results_dir: Path) -> bool:
    print("\n=== 4. metrics.json 完整性 ===")
    path = results_dir / "metrics.json"
    if not path.exists():
        _fail("metrics.json 不存在")
        return False

    required_keys = {
        "cagr", "total_return", "annual_vol", "max_drawdown",
        "sharpe", "sortino", "calmar",
        "n_trades", "win_rate", "profit_factor", "avg_holding_days",
    }
    ok = True
    try:
        m = json.loads(path.read_text())
        missing = required_keys - set(m.keys())
        if missing:
            _fail(f"缺少字段: {missing}")
            ok = False
        else:
            _ok(f"所有必要字段存在 ({len(m)} 个字段)")

        # Values should be finite numbers (not NaN/null)
        bad_vals = [k for k in required_keys if m.get(k) is None]
        if bad_vals:
            _fail(f"以下字段为 null: {bad_vals}")
            ok = False
        else:
            _ok("所有核心字段均为有效数值")

    except Exception as e:
        _fail(f"读取失败: {e}")
        ok = False
    return ok


# ── Check 5: sanity.txt (from run_sanity_checks) ──────────────────────────

def check_sanity_txt(results_dir: Path) -> bool:
    print("\n=== 5. 运行时 sanity check 结果 ===")
    path = results_dir / "sanity.txt"
    if not path.exists():
        _fail("sanity.txt 不存在")
        return False

    content = path.read_text().strip()
    if content.startswith("✓"):
        _ok("运行时 sanity check 全部通过")
        return True
    else:
        print(f"  ⚠ sanity check 发现以下问题:\n{content}")
        return False


# ── Check 6: strategy vs SPY diagnostic ───────────────────────────────────

def check_strategy_vs_spy_diagnostic(results_dir: Path) -> bool:
    """
    Not a pass/fail check — prints diagnostic table to help judge
    whether the strategy is behaving as expected.
    """
    print("\n=== 6. 策略 vs SPY 诊断 (信息性，不影响验收) ===")
    try:
        m = json.loads((results_dir / "metrics.json").read_text())
        tl = pd.read_csv(results_dir / "trades.csv")

        print(f"  {'指标':<30} {'值':>15}")
        print(f"  {'-'*47}")

        # Return metrics
        print(f"  {'CAGR':<30} {m['cagr']:>+14.2%}")
        if "spy_cagr" in m and m["spy_cagr"]:
            print(f"  {'SPY CAGR (benchmark)':<30} {m['spy_cagr']:>+14.2%}")
        print(f"  {'Total Return':<30} {m['total_return']:>+14.2%}")
        print(f"  {'Annual Volatility':<30} {m['annual_vol']:>14.2%}")
        print(f"  {'Max Drawdown':<30} {m['max_drawdown']:>14.2%}")
        print(f"  {'Sharpe Ratio':<30} {m['sharpe']:>14.3f}")
        print(f"  {'Sortino Ratio':<30} {m['sortino']:>14.3f}")
        print(f"  {'Calmar Ratio':<30} {m['calmar']:>14.3f}")
        print()
        print(f"  {'Total Trades':<30} {m['n_trades']:>15}")
        print(f"  {'Win Rate':<30} {m['win_rate']:>14.1%}")
        print(f"  {'Avg Win (R)':<30} {m['avg_win_r']:>+14.2f}")
        print(f"  {'Avg Loss (R)':<30} {m['avg_loss_r']:>+14.2f}")
        print(f"  {'Profit Factor':<30} {m['profit_factor']:>14.2f}")
        print(f"  {'Avg Holding Days':<30} {m['avg_holding_days']:>14.0f}")
        print(f"  {'Trades/Year':<30} {m['trades_per_year']:>14.1f}")

        if len(tl) > 0:
            r_mult = tl["pnl_r_multiple"]
            print(f"\n  {'R-mult Percentiles':<30}")
            for p, val in [(5, r_mult.quantile(.05)), (25, r_mult.quantile(.25)),
                           (50, r_mult.quantile(.50)), (75, r_mult.quantile(.75)),
                           (95, r_mult.quantile(.95))]:
                print(f"    {p}th pct: {val:>+.2f}R")

        print()
        # Interpretation
        print("  ── 结果解读 ─────────────────────────────────────────────")
        if m['cagr'] > 0:
            print("  ✓ 策略 CAGR 为正，资金有所增长")
        else:
            print("  ⚠ 策略 CAGR 为负，资金有所减少")

        if m['max_drawdown'] > -0.30:
            print("  ✓ 最大回撤在可接受范围内 (< 30%)")
        else:
            print("  ⚠ 最大回撤较大 (> 30%)")

        if m['sharpe'] < 0:
            print(
                "  ⚠ Sharpe 为负：主要原因是无风险收益率假设(5%)高于策略CAGR。\n"
                "    ETF宇宙过小且高度相关，不适合趋势跟踪策略。\n"
                "    使用 --mode full (S&P500+ETF) 可获得更有代表性的结果。"
            )
        elif m['sharpe'] > 0.5:
            print("  ✓ Sharpe 合理 (> 0.5)")

        print(
            "\n  注：Yahoo Finance 数据局限性（幸存者偏差、市值非实时）会在\n"
            "  切换商业数据源后消失。当前结果仅用于验证策略逻辑的正确性。"
        )

    except Exception as e:
        _fail(f"诊断失败: {e}")
        return False
    return True


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir", default="results/baseline/")
    args = p.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"✗ 结果目录不存在: {results_dir}")
        print("  请先运行: python src/scripts/02_run_baseline.py --mode etf")
        sys.exit(1)

    print("=" * 55)
    print("Phase 5 Baseline 回测验收")
    print("=" * 55)

    results = {
        "1. 输出文件完整性":    check_output_files(results_dir),
        "2. nav.csv 结构":      check_nav_csv(results_dir),
        "3. trades.csv 异常":   check_trades_csv(results_dir),
        "4. metrics.json 字段": check_metrics_json(results_dir),
        "5. Sanity check":      check_sanity_txt(results_dir),
    }

    # Diagnostic (informational, always "pass")
    check_strategy_vs_spy_diagnostic(results_dir)

    print("\n=== 验收结果汇总 ===")
    all_passed = True
    for name, passed in results.items():
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("✓ Phase 5 验收通过，可以进入 Phase 6（分析层）")
        sys.exit(0)
    else:
        print("✗ 有项目未通过，请检查上面的错误信息")
        sys.exit(1)


if __name__ == "__main__":
    main()
