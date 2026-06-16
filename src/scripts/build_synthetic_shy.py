"""
build_synthetic_shy.py

Extends SHY.parquet back to 2000-01-03 by pre-pending synthetic rows for the
gap before SHY's IPO (2002-07-26).

Data source
-----------
US Treasury Daily Yield Curve Rates (treasury.gov) — fully public, no API key.

Total return approximation
--------------------------
SHY holds 1–3yr Treasuries; the index average modified duration is ~1.8 years.
We use the simple fixed-income identity:

    daily_total_return = accrual + price_change
                       = (Y_t / 252) - (duration × ΔY_t)

where Y_t is the average of the 1yr and 2yr CMT yields (both in decimals),
ΔY_t = Y_t - Y_{t-1}, and duration = 1.8.

This captures both the income component (dominant) and the price effect from
rate moves. In 2000-2002 rates fell sharply, so the price contribution is
significant (~4-6% extra total return vs. income-only).

Usage
-----
    python src/scripts/build_synthetic_shy.py [--dry-run]

Output
------
    data/cache/tiingo/SHY.parquet      ← extended (original backed up)
    data/cache/tiingo/SHY_real.parquet ← backup of original real SHY data
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pandas as pd
import requests

# ── constants ─────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parents[2]
SHY_PATH   = ROOT / "data" / "cache" / "tiingo" / "SHY.parquet"
SHY_BACKUP = ROOT / "data" / "cache" / "tiingo" / "SHY_real.parquet"

DURATION       = 1.8          # modified duration of 1-3yr Treasury portfolio (years)
BACKFILL_START = pd.Timestamp("2000-01-01")

# US Treasury yield curve — one URL per year
_TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value={year}&download=true"
)


# ── data download ─────────────────────────────────────────────────────────────

def _fetch_year(year: int) -> pd.DataFrame:
    url = _TREASURY_URL.format(year=year)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text), parse_dates=["Date"], index_col="Date")
    return df


def download_treasury_yields(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """
    Download daily 1yr and 2yr CMT yields from treasury.gov and return
    their average as a single Series (annualised %, e.g. 5.5 means 5.5%).
    """
    years = range(start.year, end.year + 1)
    frames = []
    for yr in years:
        print(f"  Downloading Treasury yields {yr} ...", end=" ", flush=True)
        df = _fetch_year(yr)
        frames.append(df)
        print(f"✓ ({len(df)} rows)")

    combined = pd.concat(frames).sort_index()
    combined = combined[~combined.index.duplicated(keep="first")]

    # Use average of 1yr and 2yr CMT as benchmark for SHY's ~1.8yr portfolio
    for col in ["1 Yr", "2 Yr"]:
        combined[col] = pd.to_numeric(combined[col], errors="coerce")
    avg_yield = combined[["1 Yr", "2 Yr"]].mean(axis=1).dropna()

    # Restrict to requested window
    avg_yield = avg_yield[
        (avg_yield.index >= start) & (avg_yield.index <= end)
    ]
    return avg_yield  # in percent (e.g. 5.5)


# ── synthetic return construction ─────────────────────────────────────────────

def build_synthetic_nav(yields_pct: pd.Series) -> pd.Series:
    """
    Convert CMT yields (% per annum) to a total-return NAV series starting at 1.0.

    daily_total_return = income + price_change
                       = (Y/100 / 252) - DURATION × (ΔY/100)
    """
    Y     = yields_pct / 100.0          # convert pct → decimal
    dY    = Y.diff().fillna(0.0)        # ΔY (same sign convention as CMT)

    income_ret = Y / 252.0
    price_ret  = -DURATION * dY         # price rises when yields fall

    daily_ret = income_ret + price_ret
    nav = (1.0 + daily_ret).cumprod()
    nav.name = "synthetic_nav"
    return nav


# ── SHY helpers ───────────────────────────────────────────────────────────────

def load_real_shy() -> pd.DataFrame:
    if not SHY_PATH.exists():
        sys.exit(f"ERROR: {SHY_PATH} not found. Run 04_download_tiingo.py first.")
    df = pd.read_parquet(SHY_PATH)
    df.index = pd.DatetimeIndex(df.index)
    return df.sort_index()


def build_synthetic_rows(
    yields_pct: pd.Series,
    shy_real: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build synthetic SHY DataFrame for the pre-IPO window.

    Scales the synthetic NAV so its last value (day before SHY IPO) connects
    seamlessly to SHY's adj_close on its first real trading day.
    """
    anchor_date  = shy_real.index[0]
    adj_close    = shy_real["close"] * shy_real["adj_factor"]
    anchor_price = float(adj_close.iloc[0])

    # Restrict yields to the window we need (up to anchor_date for scaling ref)
    yields_pre = yields_pct[yields_pct.index < anchor_date]

    if yields_pre.empty:
        sys.exit("ERROR: No Treasury yield data found before SHY's first date.")

    # Build NAV starting at 1.0, then scale to anchor
    nav = build_synthetic_nav(yields_pre)

    # Scale: we want nav(last_day) × scale → connects to SHY at anchor_price
    # The "connection" is that synthetic(last_day) → SHY(anchor_date) via
    # anchor_date's actual 1-day return (already embedded in SHY's real price).
    # So we scale so that the synthetic series would land on anchor_price on
    # the last available yield day, giving a smooth visual join.
    scale = anchor_price / float(nav.iloc[-1])
    nav_scaled = nav * scale

    # Reindex to business days, forward-fill any gaps (US public holidays that
    # treasury.gov skips but NYSE is open, e.g. Columbus Day, Veterans Day)
    bdays = pd.bdate_range(BACKFILL_START, anchor_date - pd.Timedelta(days=1))
    nav_scaled = nav_scaled.reindex(bdays).ffill().bfill()

    print(f"\n  Synthetic period     : {nav_scaled.index.min().date()} → {nav_scaled.index.max().date()}")
    print(f"  Synthetic rows       : {len(nav_scaled):,}")

    # ── assemble with SHY.parquet schema ─────────────────────────────────────
    synth = pd.DataFrame({
        "open"       : nav_scaled,
        "high"       : nav_scaled,
        "low"        : nav_scaled,
        "close"      : nav_scaled,   # close × adj_factor(=1) = adj_close
        "volume"     : 1.0,
        "adj_factor" : 1.0,
        "is_tradable": True,
    }, index=nav_scaled.index)

    return synth


# ── diagnostics ───────────────────────────────────────────────────────────────

def verify_junction(extended: pd.DataFrame, anchor_date: pd.Timestamp) -> None:
    adj  = extended["close"] * extended["adj_factor"]
    pre  = adj[adj.index <  anchor_date]
    post = adj[adj.index >= anchor_date]
    if pre.empty or post.empty:
        return
    last_s  = float(pre.iloc[-1])
    first_r = float(post.iloc[0])
    gap_pct = (first_r - last_s) / last_s * 100
    status  = "✓" if abs(gap_pct) < 2.0 else "⚠ check this"
    print(f"\n  Junction ({pre.index[-1].date()} → {post.index[0].date()}):")
    print(f"    Last synthetic adj_close : {last_s:.6f}")
    print(f"    First real SHY adj_close : {first_r:.6f}")
    print(f"    1-day gap                : {gap_pct:+.4f}%  {status}")


def show_annual_returns(synth_nav: pd.Series) -> None:
    """Print year-by-year synthetic SHY returns as a sanity check."""
    print("\n  Synthetic SHY annual returns (sanity check):")
    print(f"  {'Year':<6}  {'Return':>8}  {'(expect ~6-10% in 2000-2002 during rate-cut cycle)':}")
    for year, grp in synth_nav.groupby(synth_nav.index.year):
        ret = float(grp.iloc[-1]) / float(grp.iloc[0]) - 1
        print(f"  {year:<6}  {ret*100:>7.2f}%")


def show_sample_table(shy_orig: pd.DataFrame, extended: pd.DataFrame) -> None:
    adj_ext  = extended["close"] * extended["adj_factor"]
    adj_orig = shy_orig["close"] * shy_orig["adj_factor"]
    print("\n  Sample adj_close (extended vs original):")
    print(f"  {'Date':<14}  {'Extended':>10}  {'Original':>10}")
    for d in ["2000-01-03", "2001-01-02", "2002-01-02", "2002-07-25", "2002-07-26", "2002-12-31"]:
        ts = pd.Timestamp(d)
        ve = f"{adj_ext[ts]:.4f}"  if ts in adj_ext.index  else "—"
        vo = f"{adj_orig[ts]:.4f}" if ts in adj_orig.index else "—"
        print(f"  {d:<14}  {ve:>10}  {vo:>10}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="Run all steps but do not write any files.")
    args = parser.parse_args()

    print("=" * 60)
    print("  build_synthetic_shy.py")
    print("=" * 60)

    # 1. Load real SHY (or backup if already extended)
    if SHY_BACKUP.exists():
        print(f"\nLoading original SHY from backup ({SHY_BACKUP.name}) ...")
        shy_real = pd.read_parquet(SHY_BACKUP)
        shy_real.index = pd.DatetimeIndex(shy_real.index)
        shy_real = shy_real.sort_index()
    else:
        shy_real = load_real_shy()

    anchor_date = shy_real.index[0]
    print(f"Real SHY: {anchor_date.date()} → {shy_real.index.max().date()}  ({len(shy_real):,} rows)")

    # 2. Download Treasury yields for the pre-SHY window
    print(f"\nDownloading US Treasury yields for {BACKFILL_START.year}–{anchor_date.year} ...")
    yields = download_treasury_yields(BACKFILL_START, anchor_date)
    print(f"  Combined: {yields.index.min().date()} → {yields.index.max().date()}  ({len(yields):,} days)")

    # 3. Build synthetic rows
    synth = build_synthetic_rows(yields, shy_real)

    # 4. Merge
    extended = pd.concat([synth, shy_real]).sort_index()
    extended = extended[~extended.index.duplicated(keep="last")]

    # 5. Diagnostics
    verify_junction(extended, anchor_date)

    synth_nav = synth["close"]
    show_annual_returns(synth_nav)
    show_sample_table(shy_real, extended)

    print(f"\n  Extended range  : {extended.index.min().date()} → {extended.index.max().date()}")
    print(f"  Total rows      : {len(extended):,}  (synthetic: {len(synth):,}  +  real: {len(shy_real):,})")

    # 6. Write
    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        return

    if not SHY_BACKUP.exists():
        shy_real.to_parquet(SHY_BACKUP)
        print(f"\n  Backup saved     → {SHY_BACKUP.name}")

    extended.to_parquet(SHY_PATH)
    print(f"  Extended SHY saved → {SHY_PATH}")

    print("\n✓ Done.")
    print("\nNext steps:")
    print("  1. Re-run backtest: python src/scripts/09_run_v1_unbiased.py")
    print("  2. Check if CAGR improved (expect +0.1 to +0.3% from pre-SHY cash returns).")


if __name__ == "__main__":
    main()
