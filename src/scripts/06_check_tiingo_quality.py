"""
Post-download data quality check for Tiingo cached data.

Scans every parquet file in data/cache/tiingo/ and reports:
  1. adj_factor jumps    — rows flagged is_tradable=False due to >50% adj_factor change
  2. Price spikes        — adj_close changes >50% in a single day (possible bad data)
  3. Zero-volume days    — trading days with volume = 0
  4. Data coverage       — start date, end date, total trading days

Results saved to data/cache/tiingo_quality_report.csv

Usage:
    python src/scripts/06_check_tiingo_quality.py
    python src/scripts/06_check_tiingo_quality.py --top 30   # show top 30 worst tickers
"""

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "src"))

CACHE_DIR   = _root / "data" / "cache" / "tiingo"
REPORT_PATH = _root / "data" / "cache" / "tiingo_quality_report.csv"

ADJ_JUMP_THRESH   = 0.50   # adj_factor pct change threshold
PRICE_SPIKE_THRESH = 0.50  # adj_close pct change threshold


def check_ticker(path: Path) -> dict:
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        return {"ticker": path.stem, "error": str(e)}

    if df.empty:
        return {"ticker": path.stem, "rows": 0, "error": "empty"}

    rows = len(df)

    # ── adj_factor jumps (already flagged in is_tradable) ───────────────────
    adj_jump_rows = 0
    if "adj_factor" in df.columns:
        adj_pct = df["adj_factor"].pct_change().abs()
        adj_jump_rows = int((adj_pct > ADJ_JUMP_THRESH).sum())

    # ── is_tradable=False count ──────────────────────────────────────────────
    non_tradable = 0
    if "is_tradable" in df.columns:
        non_tradable = int((~df["is_tradable"]).sum())

    # ── price spikes in adj_close ────────────────────────────────────────────
    price_spikes = 0
    if "adj_close" in df.columns:
        price_pct = df["adj_close"].pct_change().abs()
        price_spikes = int((price_pct > PRICE_SPIKE_THRESH).sum())
    elif "close" in df.columns and "adj_factor" in df.columns:
        adj_close = df["close"] * df["adj_factor"]
        price_pct = adj_close.pct_change().abs()
        price_spikes = int((price_pct > PRICE_SPIKE_THRESH).sum())

    # ── zero-volume days ─────────────────────────────────────────────────────
    zero_vol = 0
    if "volume" in df.columns:
        zero_vol = int((df["volume"] == 0).sum())

    # ── coverage ─────────────────────────────────────────────────────────────
    idx = pd.DatetimeIndex(df.index)
    start_date = str(idx.min().date()) if len(idx) > 0 else ""
    end_date   = str(idx.max().date()) if len(idx) > 0 else ""

    return {
        "ticker":        path.stem,
        "rows":          rows,
        "start_date":    start_date,
        "end_date":      end_date,
        "adj_jump_rows": adj_jump_rows,
        "non_tradable":  non_tradable,
        "price_spikes":  price_spikes,
        "zero_vol_days": zero_vol,
        "error":         "",
    }


def main():
    p = argparse.ArgumentParser(description="Tiingo data quality check")
    p.add_argument("--top", default=20, type=int, help="Show top N worst tickers per category")
    args = p.parse_args()

    files = sorted(CACHE_DIR.glob("*.parquet"))
    if not files:
        print(f"No parquet files found in {CACHE_DIR}")
        sys.exit(1)

    total = len(files)
    print(f"\nChecking {total:,} ticker files in {CACHE_DIR} …\n")

    records = []
    t0 = time.time()

    for i, path in enumerate(files, 1):
        rec = check_ticker(path)
        records.append(rec)

        if i % 500 == 0 or i == total:
            elapsed = time.time() - t0
            pct = i / total
            eta = (elapsed / i) * (total - i)
            print(f"  [{i:>6}/{total}] {pct:.0%}  elapsed {elapsed:.0f}s  ETA {eta:.0f}s")

    df = pd.DataFrame(records)

    # ── Overall summary ──────────────────────────────────────────────────────
    ok     = df[df["error"] == ""]
    errors = df[df["error"] != ""]

    total_rows      = ok["rows"].sum()
    tickers_ok      = len(ok)
    tickers_err     = len(errors)
    has_adj_jump    = (ok["adj_jump_rows"] > 0).sum()
    has_price_spike = (ok["price_spikes"] > 0).sum()
    has_zero_vol    = (ok["zero_vol_days"] > 0).sum()

    print(f"\n{'='*65}")
    print(f"  数据质量总结  —  Tiingo cache ({CACHE_DIR.name})")
    print(f"{'='*65}")
    print(f"  总 ticker 数      : {total:,}")
    print(f"  成功加载          : {tickers_ok:,}")
    print(f"  加载失败          : {tickers_err:,}")
    print(f"  总交易日行数      : {total_rows:,}")
    print()
    print(f"  有 adj_factor 跳变: {has_adj_jump:,} 个 ticker")
    print(f"  有价格跳变 >50%   : {has_price_spike:,} 个 ticker")
    print(f"  有零成交量日      : {has_zero_vol:,} 个 ticker")
    print(f"{'='*65}")

    # ── Top worst by adj_factor jumps ────────────────────────────────────────
    _print_top(ok, "adj_jump_rows", "adj_factor 跳变最多的 ticker", args.top)

    # ── Top worst by price spikes ────────────────────────────────────────────
    _print_top(ok, "price_spikes", "价格跳变 >50% 最多的 ticker", args.top)

    # ── Tickers with very short history (< 60 trading days) ─────────────────
    short = ok[ok["rows"] < 60].sort_values("rows")
    if len(short) > 0:
        print(f"\n  数据不足 60 天的 ticker：{len(short):,} 个（已过滤出 ADV 计算窗口）")

    # ── Save full report ─────────────────────────────────────────────────────
    df_sorted = df.sort_values(["adj_jump_rows", "price_spikes"], ascending=False)
    df_sorted.to_csv(REPORT_PATH, index=False)
    print(f"\n  完整报告已保存 → {REPORT_PATH}")
    print(f"  总耗时 {time.time()-t0:.0f}s\n")


def _print_top(df: pd.DataFrame, col: str, title: str, n: int) -> None:
    top = df[df[col] > 0].nlargest(n, col)[["ticker", "rows", col, "start_date", "end_date"]]
    if top.empty:
        print(f"\n  {title}：无异常 ✓")
        return
    print(f"\n  {title} (前 {min(n, len(top))} 个)：")
    print(f"  {'Ticker':<12} {'总行数':>8} {col:>16} {'开始':>12} {'结束':>12}")
    print(f"  {'-'*62}")
    for _, r in top.iterrows():
        print(f"  {r['ticker']:<12} {int(r['rows']):>8} {int(r[col]):>16} {r['start_date']:>12} {r['end_date']:>12}")


if __name__ == "__main__":
    main()
