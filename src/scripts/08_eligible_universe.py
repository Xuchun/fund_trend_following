"""
Compute the date range each ticker was eligible for Strategy 1.0 universe.

Filters applied (point-in-time, same as strategy engine):
  - close (raw, unadjusted) > $10
  - ADV_60 = 60-day rolling avg of (close × volume), shift(1) > $20M

Output: data/cache/tiingo_eligible_universe.csv
  ticker, first_eligible, last_eligible, eligible_days,
  data_start, data_end, is_active

Usage:
    python src/scripts/08_eligible_universe.py
"""

import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "src"))

CACHE_DIR    = _root / "data" / "cache" / "tiingo"
OUTPUT_PATH  = _root / "data" / "cache" / "tiingo_eligible_universe.csv"
OUTPUT_PATH2 = _root / "data" / "tiingo_eligible_universe.csv"  # git-tracked copy for website

MIN_PRICE = 10.0        # raw close > $10
MIN_ADV_M = 60.0        # ADV_60 > $60M
ADV_WINDOW = 60
ACTIVE_CUTOFF = "2026-01-01"   # last data date >= this → still active


def check_ticker(path: Path) -> dict | None:
    ticker = path.stem
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None

    if len(df) < ADV_WINDOW + 1:
        return None

    df.index = pd.DatetimeIndex(df.index)
    df = df.sort_index()

    close  = df["close"].astype(float)
    volume = df["volume"].astype(float)

    # ADV_60: 60-day rolling avg of dollar volume, shifted 1 day (no look-ahead)
    dollar_vol = close * volume
    adv_60 = dollar_vol.rolling(window=ADV_WINDOW, min_periods=ADV_WINDOW).mean().shift(1)

    # Eligibility mask (point-in-time)
    eligible = (close > MIN_PRICE) & (adv_60 > MIN_ADV_M * 1_000_000)

    if not eligible.any():
        return None

    eligible_dates = df.index[eligible]
    data_end       = df.index.max()
    is_active      = data_end >= pd.Timestamp(ACTIVE_CUTOFF)

    return {
        "ticker":          ticker,
        "first_eligible":  eligible_dates.min().date(),
        "last_eligible":   eligible_dates.max().date(),
        "eligible_days":   int(eligible.sum()),
        "data_start":      df.index.min().date(),
        "data_end":        data_end.date(),
        "is_active":       is_active,
    }


def main() -> None:
    result = subprocess.run(
        ["find", str(CACHE_DIR), "-name", "*.parquet"],
        capture_output=True, text=True,
    )
    files = sorted(Path(p) for p in result.stdout.strip().split("\n") if p)
    total = len(files)

    print(f"\n分析 {total:,} 个 ticker（过滤条件：close > ${MIN_PRICE}, ADV_60 > ${MIN_ADV_M}M）\n")

    records = []
    t0 = time.time()

    for i, path in enumerate(files, 1):
        rec = check_ticker(path)
        if rec:
            records.append(rec)

        if i % 1000 == 0 or i == total:
            elapsed = time.time() - t0
            eta     = (elapsed / i) * (total - i)
            pct     = i / total
            bar     = "█" * int(20 * pct) + "░" * (20 - int(20 * pct))
            print(f"\r  [{bar}] {i:,}/{total:,} ({pct:.0%})  符合: {len(records):,}  ETA {eta:.0f}s",
                  end="", flush=True)

    print(f"\n\n{'='*60}")

    df = pd.DataFrame(records).sort_values("ticker")

    active   = df["is_active"].sum()
    delisted = (~df["is_active"]).sum()

    print(f"  满足条件的标的总数  : {len(df):,}")
    print(f"  ├─ 仍在交易（现役）: {active:,}")
    print(f"  └─ 已退市           : {delisted:,}")
    print(f"  平均满足天数        : {df['eligible_days'].mean():.0f} 天")
    print(f"  最早进入时间        : {df['first_eligible'].min()}")
    print(f"  总耗时              : {time.time()-t0:.0f}s")
    print(f"{'='*60}")

    df.to_csv(OUTPUT_PATH, index=False)
    df.to_csv(OUTPUT_PATH2, index=False)
    print(f"\n  CSV 已保存 → {OUTPUT_PATH}")
    print(f"  CSV 已保存 → {OUTPUT_PATH2}  (git-tracked)\n")


if __name__ == "__main__":
    main()
