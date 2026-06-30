"""
Daily update of tiingo_eligible_universe.csv using Tiingo's public ticker list.

Uses https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip
(no API key required). Updates is_active status for every ticker based on
Tiingo's reported endDate.

eligible_days is NOT recomputed here — it is a cumulative historical count and
only changes meaningfully for newly listed tickers approaching 252 days. To
recompute eligible_days, run 08_eligible_universe.py manually with the full
local Tiingo cache.

Intended to run daily at 22:45 UTC (06:45 SGT) via GitHub Actions, 15 minutes
before the main paper trading update at 23:00 UTC.
"""

import io
import json
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

_root = Path(__file__).resolve().parents[2]

TIINGO_TICKERS_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
CSV_GIT_PATH   = _root / "data" / "tiingo_eligible_universe.csv"
CSV_CACHE_PATH = _root / "data" / "cache" / "tiingo_eligible_universe.csv"
POSITIONS_PATH = _root / "results" / "paper_trading" / "positions.json"

# Ticker with endDate older than this is considered delisted
ACTIVE_WINDOW_DAYS = 45

_EXCL_TICKERS = {"FXI", "GDX", "KWEB", "VXX", "EMB", "ASHR", "ETH", "SPY", "SHY"}
_YF_UNAVAILABLE = {
    "SPLK", "SNCR", "WFC-P-L", "TTM", "TRUE",
    "ZZK", "ZK", "VEDL", "TRML", "WFC-P-Y",
    "SOVO", "T-P-A", "ZCZZT", "T-P-C", "WFC-P-Z",
    "ZAZZT", "VBTX", "WFC-P-D",
}


def fetch_tiingo_ticker_map() -> dict[str, str | None]:
    """
    Returns dict: ticker.upper() -> endDate (ISO str) or None (no known end = still active).
    """
    resp = requests.get(TIINGO_TICKERS_URL, timeout=120)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        with z.open("supported_tickers.csv") as f:
            df = pd.read_csv(f)

    result: dict[str, str | None] = {}
    for _, row in df.iterrows():
        t = row.get("ticker")
        if pd.isna(t):
            continue
        t = str(t).strip().upper()
        end = row.get("endDate")
        result[t] = None if pd.isna(end) else str(end).strip()

    return result


def ticker_active(end_date: str | None, cutoff: date) -> bool:
    """None endDate (no known end) or endDate within cutoff → active."""
    if not end_date:
        return True
    try:
        return date.fromisoformat(end_date[:10]) >= cutoff
    except ValueError:
        return True


def main() -> None:
    if not CSV_GIT_PATH.exists():
        print(f"ERROR: universe CSV not found: {CSV_GIT_PATH}", file=sys.stderr)
        sys.exit(1)

    # ── Download Tiingo ticker list ───────────────────────────────────────────
    print("Fetching Tiingo supported_tickers.zip …", flush=True)
    try:
        tiingo = fetch_tiingo_ticker_map()
    except Exception as e:
        print(f"ERROR: Tiingo download failed: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"  {len(tiingo):,} tickers in Tiingo list", flush=True)

    # ── Load current CSV ──────────────────────────────────────────────────────
    df = pd.read_csv(CSV_GIT_PATH)
    cutoff = date.today() - timedelta(days=ACTIVE_WINDOW_DAYS)

    before_active   = int((df["is_active"] == True).sum())
    before_inactive = int((df["is_active"] == False).sum())

    newly_inactive: list[str] = []
    newly_active:   list[str] = []
    not_in_tiingo:  list[str] = []

    for idx, row in df.iterrows():
        ticker     = str(row["ticker"]).strip().upper()
        was_active = bool(row["is_active"])

        if ticker not in tiingo:
            not_in_tiingo.append(ticker)
            continue

        end_date   = tiingo[ticker]
        now_active = ticker_active(end_date, cutoff)

        if now_active != was_active:
            df.at[idx, "is_active"] = now_active
            if end_date:
                df.at[idx, "data_end"] = end_date[:10]
            (newly_inactive if not now_active else newly_active).append(ticker)

    after_active   = int((df["is_active"] == True).sum())
    after_inactive = int((df["is_active"] == False).sum())

    print(f"\nStatus changes:")
    print(f"  is_active=True :  {before_active:,} → {after_active:,}  "
          f"({'−' if after_active <= before_active else '+'}{abs(after_active - before_active)})")
    print(f"  is_active=False:  {before_inactive:,} → {after_inactive:,}  "
          f"({'−' if after_inactive <= before_inactive else '+'}{abs(after_inactive - before_inactive)})")
    if newly_inactive:
        print(f"  Newly delisted ({len(newly_inactive)}): {newly_inactive[:20]}")
    if newly_active:
        print(f"  Re-activated   ({len(newly_active)}): {newly_active[:20]}")
    if not_in_tiingo:
        print(f"  Not in Tiingo  ({len(not_in_tiingo)}): {not_in_tiingo[:5]} … (status unchanged)")

    # ── Save updated CSV ──────────────────────────────────────────────────────
    df.to_csv(CSV_GIT_PATH, index=False)
    print(f"\n  Saved → {CSV_GIT_PATH.name}")
    if CSV_CACHE_PATH.parent.exists():
        df.to_csv(CSV_CACHE_PATH, index=False)
        print(f"  Saved → {CSV_CACHE_PATH.name}")

    # ── Update universe_stats + tiingo_universe_synced_utc in positions.json ─
    if not POSITIONS_PATH.exists():
        print("  positions.json not found — skipping", flush=True)
        return

    with open(POSITIONS_PATH) as f:
        state = json.load(f)

    _tiingo_pool = df[
        (df["is_active"] == True) &
        (df["eligible_days"] >= 252) &
        (~df["ticker"].isin(_EXCL_TICKERS))
    ]
    _yf_pool = df[
        (df["is_active"] == True) &
        (df["eligible_days"] >= 252) &
        (~df["ticker"].isin(_EXCL_TICKERS | _YF_UNAVAILABLE))
    ]

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["universe_stats"] = {
        "tiingo_eligible":        len(_tiingo_pool),
        "yf_downloadable":        len(_yf_pool),
        "yf_unavailable_in_pool": len(_tiingo_pool) - len(_yf_pool),
        "total_active":           int((df["is_active"] == True).sum()),
        "total_delisted":         int((df["is_active"] == False).sum()),
        "updated_utc":            now_utc,
    }
    # Separate field so the monitor can distinguish Tiingo sync time from paper trading run time
    state["tiingo_universe_synced_utc"] = now_utc

    with open(POSITIONS_PATH, "w") as f:
        json.dump(state, f, indent=2)

    print(f"\n  positions.json updated:")
    print(f"    Tiingo 标的池 (现役): {len(_tiingo_pool):,}")
    print(f"    Yahoo Finance 可下载: {len(_yf_pool):,}")
    print(f"    YF 无法下载:          {len(_tiingo_pool) - len(_yf_pool):,}")
    print(f"    Synced UTC:           {now_utc}", flush=True)


if __name__ == "__main__":
    main()
