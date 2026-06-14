"""
One-time bulk download of historical OHLCV data from Tiingo.

Universe (survivorship-bias-aware):
  1. All US stocks listed on NYSE / NASDAQ / AMEX that had trading activity
     during the backtest period 2004-01-01 → today.  This includes ~7,400
     stocks that were delisted during that window, which is the primary
     source of survivorship bias when using only current index members.
  2. Strategy ETFs (SHY, SPY, GLD, sector ETFs, …) from data/ETFs.csv.

Total: ~22,000 tickers.  Download time ≈ 2–3 hours (Power plan, 0.4 s/req).

After this script finishes you can cancel the Tiingo subscription and
continue using the locally-cached data for backtesting indefinitely.

Usage:
    python src/scripts/04_download_tiingo.py
    python src/scripts/04_download_tiingo.py --resume   # skip already-cached tickers
    python src/scripts/04_download_tiingo.py --token <KEY>

API key is read from the TIINGO_API_TOKEN environment variable (or .env file),
or passed explicitly via --token.
"""

import argparse
import io
import json
import logging
import os
import sys
import time
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "src"))

# Load .env file if present
_env_file = _root / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

from data.adapters.tiingo import TiingoAdapter
from data.pipeline import load_price_data
from data.universe import ETF_TICKERS

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CACHE_DIR = _root / "data" / "cache" / "tiingo"

BACKTEST_START = "2004-01-01"
BACKTEST_END   = date.today().isoformat()

# US exchanges with reliable daily data
US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX"}

SUPPORTED_TICKERS_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"


# ── Ticker universe ──────────────────────────────────────────────────────────

def fetch_us_stock_universe(start: str, end: str) -> list[str]:
    """
    Download Tiingo's full supported_tickers list and filter for US stocks
    active during [start, end].  Includes delisted stocks to reduce
    survivorship bias.
    """
    print("Downloading Tiingo supported ticker list …", flush=True)
    resp = requests.get(SUPPORTED_TICKERS_URL, timeout=60)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        with z.open("supported_tickers.csv") as f:
            df = pd.read_csv(f)

    # Filter: major US exchanges, common stock, USD, valid ticker symbol
    mask = (
        df["exchange"].isin(US_EXCHANGES) &
        (df["assetType"] == "Stock") &
        (df["priceCurrency"] == "USD") &
        df["ticker"].notna()
    )
    df = df[mask].copy()

    # Keep only tickers that overlapped with our backtest window.
    # Dates are YYYY-MM-DD strings (ISO format sorts correctly).
    # NaN = no restriction; fill with boundary values for string comparison.
    start_filled = df["startDate"].fillna("1900-01-01").astype(str)
    end_filled   = df["endDate"].fillna("2099-12-31").astype(str)

    in_window = (start_filled <= end) & (end_filled >= start)
    df = df[in_window].copy()
    ef = end_filled[in_window]

    still_active = ef >= "2026-01-01"
    delisted_ct  = (~still_active).sum()
    active_ct    = still_active.sum()
    print(f"  Active stocks  : {active_ct:,}")
    print(f"  Delisted stocks: {delisted_ct:,}  ← survivorship-bias coverage")
    print(f"  Total US stocks: {len(df):,}", flush=True)

    return sorted(df["ticker"].str.upper().tolist())


# ── Progress display ─────────────────────────────────────────────────────────

def _progress(i: int, total: int, ticker: str, status: str,
              ok: int, skipped: int, failed: int, t0: float) -> None:
    elapsed = time.time() - t0
    eta_s   = (elapsed / i) * (total - i) if i > 0 else 0
    eta     = f"{int(eta_s // 3600)}h{int((eta_s % 3600) // 60):02d}m"
    pct     = i / total
    bar_w   = 20
    filled  = int(bar_w * pct)
    bar     = "█" * filled + "░" * (bar_w - filled)
    print(
        f"\r[{bar}] {i}/{total} ({pct:.0%})  {ticker:<10} {status:<12} "
        f"✓{ok} ⊘{skipped} ✗{failed}  ETA {eta}   ",
        end="", flush=True,
    )
    if i == total:
        print()


# ── Main ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bulk-download Tiingo historical data (survivorship-bias-aware)")
    p.add_argument("--token",  default=None,           help="Tiingo API token (overrides env var)")
    p.add_argument("--start",  default=BACKTEST_START, help="Start date YYYY-MM-DD")
    p.add_argument("--end",    default=BACKTEST_END,   help="End date YYYY-MM-DD")
    p.add_argument("--resume", action="store_true",    help="Skip tickers already cached")
    p.add_argument("--delay",  default=0.4, type=float, help="Seconds between API calls (default 0.4)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    token = args.token or os.environ.get("TIINGO_API_TOKEN", "")
    if not token:
        print("ERROR: Tiingo API token not found.")
        print("  Set TIINGO_API_TOKEN in .env, or pass --token <KEY>")
        sys.exit(1)

    adapter = TiingoAdapter(api_token=token, request_delay=args.delay)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Build universe: all US stocks + ETFs
    us_stocks = fetch_us_stock_universe(args.start, args.end)
    universe  = sorted(set(us_stocks) | set(t.upper() for t in ETF_TICKERS))
    total     = len(universe)

    est_mins = total * args.delay / 60
    print(f"\n{'='*65}")
    print(f"  Tiingo bulk download  (survivorship-bias-aware)")
    print(f"  Tickers    : {total:,}  ({len(us_stocks):,} stocks + {len(ETF_TICKERS)} ETFs)")
    print(f"  Period     : {args.start} → {args.end}")
    print(f"  Cache dir  : {CACHE_DIR}")
    print(f"  Est. time  : ~{est_mins:.0f} min  ({args.delay}s/ticker)")
    print(f"  Resume     : {'yes (skip existing)' if args.resume else 'no (re-download all)'}")
    print(f"{'='*65}\n")

    ok = skipped = failed = 0
    failures: list[str] = []
    t0 = time.time()

    for i, ticker in enumerate(universe, 1):
        cache_file = CACHE_DIR / f"{ticker.upper()}.parquet"

        if args.resume and cache_file.exists():
            skipped += 1
            _progress(i, total, ticker, "SKIP", ok, skipped, failed, t0)
            continue

        try:
            df = load_price_data(
                ticker, adapter,
                start=args.start, end=args.end,
                cache_dir=CACHE_DIR,
                force_refresh=not args.resume,
            )
            if df.empty:
                failed += 1
                failures.append(ticker)
                _progress(i, total, ticker, "EMPTY", ok, skipped, failed, t0)
            else:
                ok += 1
                _progress(i, total, ticker, f"{len(df)}d", ok, skipped, failed, t0)

        except Exception as e:
            failed += 1
            failures.append(ticker)
            _progress(i, total, ticker, f"ERR", ok, skipped, failed, t0)
            logger.error("%s: %s", ticker, e)

    elapsed = time.time() - t0
    h, m, s = int(elapsed // 3600), int((elapsed % 3600) // 60), int(elapsed % 60)
    print(f"\n{'='*65}")
    print(f"  完成！  ✓ {ok:,} ok   ⊘ {skipped:,} skipped   ✗ {failed:,} failed")
    print(f"  总耗时 : {h}h {m:02d}m {s:02d}s")
    print(f"  Cache  : {CACHE_DIR}")
    if failures:
        fail_path = CACHE_DIR / "_failed_tickers.json"
        fail_path.write_text(json.dumps(failures, indent=2))
        print(f"  失败名单: {fail_path.name}  ({len(failures)} 个)")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
