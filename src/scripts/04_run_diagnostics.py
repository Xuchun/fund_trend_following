"""
CLI script: compute trade-level execution diagnostics and save JSON.

Usage:
    python src/scripts/04_run_diagnostics.py [--results-dir results/v1/] \
                                             [--output results/v1/diagnostics.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project src/ is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pandas as pd

from analysis.diagnostics import print_diagnostics_report, run_diagnostics


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run trade-level execution diagnostics and save JSON report."
    )
    parser.add_argument(
        "--results-dir",
        default="results/v1/",
        help="Directory containing trades.csv (default: results/v1/)",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output JSON path (default: <results-dir>/diagnostics.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    results_dir = Path(args.results_dir)
    trades_path = results_dir / "trades.csv"

    if not trades_path.exists():
        print(f"✗ 找不到交易日志：{trades_path}", file=sys.stderr)
        sys.exit(1)

    # ── Load trades ────────────────────────────────────────────────────────
    trade_log = pd.read_csv(
        trades_path,
        parse_dates=["entry_date", "exit_date"],
    )
    print(f"  已加载 {len(trade_log):,} 笔交易 ← {trades_path}")

    # ── Run diagnostics ────────────────────────────────────────────────────
    diag = run_diagnostics(trade_log)

    # ── Add metadata ───────────────────────────────────────────────────────
    diag["_meta"] = {
        "results_dir":    str(results_dir),
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "n_total_trades": int(len(trade_log)),
    }

    # ── Save JSON ──────────────────────────────────────────────────────────
    output_path = Path(args.output) if args.output else results_dir / "diagnostics.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(diag, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ── Print report ───────────────────────────────────────────────────────
    print_diagnostics_report(diag)

    print(f"\n✓ 诊断完成 → {output_path}")


if __name__ == "__main__":
    main()
