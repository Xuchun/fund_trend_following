"""
One-time bulk download of historical OHLCV data from Tiingo.

Downloads S&P 900 + ETFs (≈ 940 tickers) for 2004-01-01 → today,
saving each ticker as a Parquet file under data/cache/tiingo/.

After this script finishes you can cancel the Tiingo subscription and
continue using the locally-cached data for backtesting indefinitely.

Usage:
    python src/scripts/04_download_tiingo.py
    python src/scripts/04_download_tiingo.py --start 2004-01-01 --end 2026-06-13
    python src/scripts/04_download_tiingo.py --resume          # skip tickers already cached
    python src/scripts/04_download_tiingo.py --token <KEY>     # override env var

API key is read from the TIINGO_API_TOKEN environment variable (or .env file),
or passed explicitly via --token.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "src"))

# Load .env file if present (plain key=value, no external dependency needed)
_env_file = _root / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

from data.adapters.tiingo import TiingoAdapter
from data.pipeline import load_price_data
from data.universe import ETF_TICKERS, fetch_sp900_tickers

logging.basicConfig(
    level=logging.WARNING,          # suppress per-ticker debug noise
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CACHE_DIR = _root / "data" / "cache" / "tiingo"

DEFAULT_START = "2004-01-01"
DEFAULT_END   = date.today().isoformat()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bulk-download Tiingo historical data")
    p.add_argument("--token",   default=None,          help="Tiingo API token (overrides env var)")
    p.add_argument("--start",   default=DEFAULT_START, help="Start date YYYY-MM-DD")
    p.add_argument("--end",     default=DEFAULT_END,   help="End date YYYY-MM-DD")
    p.add_argument("--resume",  action="store_true",   help="Skip tickers already cached")
    p.add_argument("--delay",   default=0.4, type=float, help="Seconds between API calls (default 0.4)")
    p.add_argument("--tickers", nargs="*",  default=None, help="Override ticker list (space-separated)")
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

    # ── Build ticker list ────────────────────────────────────────────────────
    if args.tickers:
        universe = sorted(set(t.upper() for t in args.tickers))
    else:
        print("Fetching S&P 900 ticker list from Wikipedia …", flush=True)
        sp900 = fetch_sp900_tickers()
        if not sp900:
            print("ERROR: Could not fetch S&P 900 tickers")
            sys.exit(1)
        universe = sorted(set(sp900) | set(ETF_TICKERS))

    total = len(universe)
    print(f"\n{'='*65}")
    print(f"  Tiingo bulk download")
    print(f"  Tickers  : {total}")
    print(f"  Period   : {args.start} → {args.end}")
    print(f"  Cache dir: {CACHE_DIR}")
    print(f"  Resume   : {'yes (skip existing)' if args.resume else 'no (re-download all)'}")
    print(f"{'='*65}\n")

    # ── Download loop ────────────────────────────────────────────────────────
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
            _progress(i, total, ticker, f"ERR:{e}", ok, skipped, failed, t0)

    elapsed = time.time() - t0
    print(f"\n{'='*65}")
    print(f"  완료  ✓ {ok} ok   ⊘ {skipped} skipped   ✗ {failed} failed   ({elapsed:.0f}s)")
    print(f"  Cache: {CACHE_DIR}")
    if failures:
        fail_path = CACHE_DIR / "_failed_tickers.json"
        fail_path.write_text(json.dumps(failures, indent=2))
        print(f"  Failed tickers saved → {fail_path.name}")
    print(f"{'='*65}\n")


def _progress(i: int, total: int, ticker: str, status: str,
              ok: int, skipped: int, failed: int, t0: float) -> None:
    elapsed = time.time() - t0
    eta_s = (elapsed / i) * (total - i) if i > 0 else 0
    eta = f"{int(eta_s // 60)}m{int(eta_s % 60):02d}s"
    bar_width = 20
    filled = int(bar_width * i / total)
    bar = "█" * filled + "░" * (bar_width - filled)
    print(
        f"\r[{bar}] {i}/{total}  {ticker:<8} {status:<12} "
        f"✓{ok} ✗{failed}  ETA {eta}   ",
        end="", flush=True,
    )
    if i == total:
        print()  # newline at end


if __name__ == "__main__":
    main()
