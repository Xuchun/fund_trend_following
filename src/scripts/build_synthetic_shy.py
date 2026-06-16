"""
build_synthetic_shy.py

Extends SHY.parquet back to 2000-01-01 by splicing the ICE BofA 1-3yr US
Treasury Total Return Index (FRED: BAMLCC1A013YTRIV) into the pre-IPO gap.

SHY launched 2002-07-26. For 2000-01-03 → 2002-07-25, the backtest engine
currently gives cash 0% return. This script fixes that by pre-pending synthetic
rows whose daily return mirrors the underlying Treasury index.

Splicing method
---------------
  1. Download BAMLCC1A013YTRIV from FRED (total return index, 1983-present).
  2. Scale so the index level on SHY's first real trading day equals SHY's
     adj_close on that day. This makes the synthetic series continuous with
     the real data at the junction.
  3. Pre-pend the scaled synthetic rows (close = synthetic_adj_close,
     adj_factor = 1.0) to SHY.parquet. The engine reads close × adj_factor,
     so adj_close is preserved correctly.

Usage:
    python src/scripts/build_synthetic_shy.py [--dry-run]

Output:
    data/cache/tiingo/SHY.parquet      ← extended file (original backed up)
    data/cache/tiingo/SHY_real.parquet ← backup of original real SHY data
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pandas as pd
import requests

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parents[2]
SHY_PATH   = ROOT / "data" / "cache" / "tiingo" / "SHY.parquet"
SHY_BACKUP = ROOT / "data" / "cache" / "tiingo" / "SHY_real.parquet"

FRED_URL        = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLCC1A013YTRIV"
BACKFILL_START  = pd.Timestamp("2000-01-01")


# ── helpers ───────────────────────────────────────────────────────────────────

def download_fred() -> pd.Series:
    """Download ICE BofA 1-3yr US Treasury Total Return Index from FRED."""
    print("Downloading BAMLCC1A013YTRIV from FRED ...", end=" ", flush=True)
    resp = requests.get(FRED_URL, timeout=30)
    resp.raise_for_status()

    df = pd.read_csv(io.StringIO(resp.text), parse_dates=["DATE"], index_col="DATE")
    df.columns = ["level"]
    df["level"] = pd.to_numeric(df["level"], errors="coerce")
    df = df.dropna()
    df.index = pd.DatetimeIndex(df.index)
    s = df["level"].sort_index()

    print(f"✓  {s.index.min().date()} → {s.index.max().date()}  ({len(s):,} observations)")
    return s


def load_real_shy() -> pd.DataFrame:
    """Load SHY from Tiingo cache. Raises if missing."""
    if not SHY_PATH.exists():
        sys.exit(f"ERROR: {SHY_PATH} not found. Run 04_download_tiingo.py first.")
    df = pd.read_parquet(SHY_PATH)
    df.index = pd.DatetimeIndex(df.index)
    return df.sort_index()


def build_synthetic_rows(fred: pd.Series, shy: pd.DataFrame) -> pd.DataFrame:
    """
    Construct synthetic SHY rows for the pre-IPO window using the FRED index.

    Returns a DataFrame with the same schema as SHY.parquet covering
    BACKFILL_START → (first real SHY date - 1 day).
    """
    anchor_date  = shy.index[0]
    adj_close    = shy["close"] * shy["adj_factor"]
    anchor_price = float(adj_close.iloc[0])

    print(f"\n  Real SHY first date  : {anchor_date.date()}")
    print(f"  Anchor adj_close     : {anchor_price:.6f}")

    # ── scale FRED index so its level on anchor_date == anchor_price ──────────
    # Use the last available FRED observation on or before anchor_date
    # (handles calendar mismatches between FRED and NYSE).
    fred_at_anchor = fred[fred.index <= anchor_date].iloc[-1]
    scale = anchor_price / fred_at_anchor

    # ── build synthetic adj_close series for backfill window ─────────────────
    fred_pre = fred[(fred.index >= BACKFILL_START) & (fred.index < anchor_date)] * scale

    if fred_pre.empty:
        sys.exit("ERROR: No FRED data in the requested backfill window. "
                 "Check BACKFILL_START and FRED coverage.")

    # ── reindex to business days and forward-fill gaps ────────────────────────
    # Ensures every NYSE trading day has a value even if FRED was closed
    # for a US holiday that NYSE observed.
    bdays = pd.bdate_range(BACKFILL_START, anchor_date - pd.Timedelta(days=1))
    fred_pre = fred_pre.reindex(bdays).ffill().bfill()

    print(f"  Synthetic period     : {fred_pre.index.min().date()} → {fred_pre.index.max().date()}")
    print(f"  Synthetic rows       : {len(fred_pre):,}")

    # ── assemble DataFrame matching SHY.parquet schema ────────────────────────
    synth = pd.DataFrame({
        "open"       : fred_pre,
        "high"       : fred_pre,
        "low"        : fred_pre,
        "close"      : fred_pre,   # close × adj_factor (=1) = adj_close
        "volume"     : 1.0,        # non-zero so volume filters pass
        "adj_factor" : 1.0,
        "is_tradable": True,
    }, index=fred_pre.index)

    return synth


def verify_junction(extended: pd.DataFrame, anchor_date: pd.Timestamp) -> None:
    adj   = extended["close"] * extended["adj_factor"]
    pre   = adj[adj.index <  anchor_date]
    post  = adj[adj.index >= anchor_date]
    if pre.empty or post.empty:
        return
    last_synthetic = float(pre.iloc[-1])
    first_real     = float(post.iloc[0])
    gap_pct = (first_real - last_synthetic) / last_synthetic * 100
    status  = "✓" if abs(gap_pct) < 2.0 else "⚠ check this"
    print(f"\n  Junction ({pre.index[-1].date()} → {post.index[0].date()}):")
    print(f"    Last synthetic adj_close : {last_synthetic:.6f}")
    print(f"    First real SHY adj_close : {first_real:.6f}")
    print(f"    1-day gap                : {gap_pct:+.4f}%  {status}")
    print()
    # Print YTM-implied annualised return for early 2000-2002 period
    # (sanity check that the synthetic series looks right)
    pre_2001 = adj[(adj.index >= "2000-01-03") & (adj.index <= "2000-12-31")]
    if len(pre_2001) > 1:
        annual_ret = (float(pre_2001.iloc[-1]) / float(pre_2001.iloc[0])) ** (252 / len(pre_2001)) - 1
        print(f"  Implied annual return 2000 : {annual_ret*100:.2f}%  (expect ~6% for 1-3yr Treasuries)")


def print_comparison(shy_orig: pd.DataFrame, extended: pd.DataFrame) -> None:
    """Show before/after adj_close for a few anchor dates."""
    adj_orig = shy_orig["close"] * shy_orig["adj_factor"]
    adj_ext  = extended["close"] * extended["adj_factor"]
    print("\n  Sample adj_close comparison:")
    print(f"  {'Date':<14} {'Extended':>12}  {'Original':>12}")
    for d in ["2000-01-03", "2001-09-10", "2002-07-25", "2002-07-26", "2003-01-02"]:
        ts = pd.Timestamp(d)
        v_ext = f"{adj_ext.get(ts, float('nan')):.4f}" if ts in adj_ext.index else "—"
        v_ori = f"{adj_orig.get(ts, float('nan')):.4f}" if ts in adj_orig.index else "—"
        print(f"  {d:<14} {v_ext:>12}  {v_ori:>12}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Run all steps but do not write any files.")
    args = parser.parse_args()

    # 1. Download FRED data
    fred = download_fred()

    # 2. Load real SHY
    shy_real = load_real_shy()
    print(f"\n  Real SHY loaded      : {shy_real.index.min().date()} → {shy_real.index.max().date()}  ({len(shy_real):,} rows)")

    # Guard: check if SHY was already extended (backup exists → real SHY loaded)
    if SHY_BACKUP.exists():
        print(f"\n  ⚠  Backup {SHY_BACKUP.name} already exists.")
        print("     Loading backup as the true original to avoid double-extension.")
        shy_real = pd.read_parquet(SHY_BACKUP)
        shy_real.index = pd.DatetimeIndex(shy_real.index)
        shy_real = shy_real.sort_index()

    anchor_date = shy_real.index[0]

    # 3. Build synthetic rows
    synth = build_synthetic_rows(fred, shy_real)

    # 4. Merge
    extended = pd.concat([synth, shy_real]).sort_index()
    extended = extended[~extended.index.duplicated(keep="last")]

    # 5. Diagnostics
    verify_junction(extended, anchor_date)
    print_comparison(shy_real, extended)

    print(f"\n  Full extended range  : {extended.index.min().date()} → {extended.index.max().date()}")
    print(f"  Total rows           : {len(extended):,}  "
          f"(synthetic: {len(synth):,}  +  real: {len(shy_real):,})")

    # 6. Write
    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        return

    if not SHY_BACKUP.exists():
        shy_real.to_parquet(SHY_BACKUP)
        print(f"\n  Backup saved         → {SHY_BACKUP.name}")

    extended.to_parquet(SHY_PATH)
    print(f"  Extended SHY saved   → {SHY_PATH}")
    print("\n✓ Done.")
    print("\nNext steps:")
    print("  1. Re-run backtest: python src/scripts/09_run_v1_unbiased.py (2000-start)")
    print("  2. Compare new CAGR vs old to quantify the impact of synthetic SHY.")


if __name__ == "__main__":
    main()
