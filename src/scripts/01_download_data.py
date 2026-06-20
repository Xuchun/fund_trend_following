"""
[已废弃] 此脚本使用 Yahoo Finance 数据，已不再使用。请改用对应 Tiingo 版本。
Script: download and cache historical price data.

Usage examples:
    # Download ETFs only (fast smoke test)
    python src/scripts/01_download_data.py --mode etf

    # Download full S&P 500 + ETFs (takes 30-60 min on first run)
    python src/scripts/01_download_data.py --mode full

    # Download specific tickers
    python src/scripts/01_download_data.py --tickers AAPL MSFT SPY --start 2015-01-01

    # Force re-download (ignore cache)
    python src/scripts/01_download_data.py --mode etf --force
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Allow running from project root: python src/scripts/01_download_data.py
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from data.adapters.yahoo import YahooFinanceAdapter
from data.pipeline import load_price_data
from data.universe import ETF_TICKERS, fetch_sp500_tickers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_START = "2010-01-01"
DEFAULT_END = "2025-12-31"
# Pause between downloads to avoid hammering Yahoo Finance
SLEEP_BETWEEN_TICKERS = 0.3  # seconds


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Download and cache price data from Yahoo Finance")
    p.add_argument(
        "--mode",
        choices=["etf", "sp500", "full"],
        default="etf",
        help=(
            "etf: ETFs only (fast); "
            "sp500: S&P 500 only; "
            "full: S&P 500 + ETFs (default: etf)"
        ),
    )
    p.add_argument(
        "--tickers",
        nargs="+",
        metavar="TICKER",
        help="Override --mode with an explicit list of tickers",
    )
    p.add_argument("--start", default=DEFAULT_START, help="Start date YYYY-MM-DD")
    p.add_argument("--end",   default=DEFAULT_END,   help="End date YYYY-MM-DD")
    p.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if cache exists",
    )
    return p.parse_args()


def build_ticker_list(args: argparse.Namespace) -> list[str]:
    if args.tickers:
        return [t.upper() for t in args.tickers]

    if args.mode == "etf":
        return sorted(ETF_TICKERS)

    sp500 = fetch_sp500_tickers()
    if not sp500:
        logger.error("Could not fetch S&P 500 tickers; aborting")
        sys.exit(1)

    if args.mode == "sp500":
        return sp500
    # full
    return sorted(set(sp500) | set(ETF_TICKERS))


def main() -> None:
    args = parse_args()
    tickers = build_ticker_list(args)

    logger.info(
        "Downloading %d tickers from %s to %s (force=%s)",
        len(tickers), args.start, args.end, args.force,
    )

    adapter = YahooFinanceAdapter()
    success, failed = 0, []

    for i, ticker in enumerate(tickers):
        try:
            df = load_price_data(
                ticker,
                adapter,
                start=args.start,
                end=args.end,
                force_refresh=args.force,
            )
            if df.empty:
                logger.warning("[%d/%d] %s: no data", i + 1, len(tickers), ticker)
                failed.append(ticker)
            else:
                logger.info(
                    "[%d/%d] %s: %d rows (%s → %s)",
                    i + 1, len(tickers), ticker, len(df),
                    df.index.min().date(), df.index.max().date(),
                )
                success += 1
        except Exception as e:
            logger.error("[%d/%d] %s: error: %s", i + 1, len(tickers), ticker, e)
            failed.append(ticker)

        if i < len(tickers) - 1:
            time.sleep(SLEEP_BETWEEN_TICKERS)

    print(f"\n{'='*50}")
    print(f"Done: {success}/{len(tickers)} tickers downloaded successfully")
    if failed:
        print(f"Failed ({len(failed)}): {', '.join(failed)}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
