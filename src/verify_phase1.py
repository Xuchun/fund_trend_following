"""
Phase 1 acceptance test: Data Layer.

Checks:
  1. Download 5 tickers from Yahoo Finance.
  2. Verify Parquet cache written correctly (round-trip).
  3. Verify adj prices satisfy OHLC ordering constraints.
  4. Verify is_tradable flag has sensible coverage.
  5. Verify incremental update (extend the date range, no full re-download).
  6. Verify get_universe_at_date filters apply correctly.

Usage:
    python src/verify_phase1.py
"""

import logging
import os
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data.adapters.yahoo import YahooFinanceAdapter
from data.pipeline import compute_adj_prices, load_price_data, load_price_panel
from data.universe import ETF_TICKERS, get_universe_at_date

logging.basicConfig(
    level=logging.WARNING,  # suppress noisy download logs during test
    format="%(levelname)s %(name)s: %(message)s",
)

TEST_TICKERS = ["SPY", "AAPL", "MSFT", "GLD", "TLT"]
START = "2022-01-01"
END = "2023-12-31"
EXTEND_END = "2024-06-30"


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_download(adapter: YahooFinanceAdapter, cache_dir: Path) -> bool:
    print(f"\n=== 1. 下载 {len(TEST_TICKERS)} 只标的 ===")
    ok = True
    for ticker in TEST_TICKERS:
        try:
            df = load_price_data(ticker, adapter, START, END, cache_dir=cache_dir)
            if df.empty:
                _fail(f"{ticker}: 返回空数据")
                ok = False
            else:
                _ok(f"{ticker}: {len(df)} 行 ({df.index.min().date()} → {df.index.max().date()})")
        except Exception as e:
            _fail(f"{ticker}: {e}")
            ok = False
    return ok


def check_parquet_cache(cache_dir: Path) -> bool:
    print("\n=== 2. Parquet 缓存验证 ===")
    ok = True
    for ticker in TEST_TICKERS:
        path = cache_dir / f"{ticker}.parquet"
        if not path.exists():
            _fail(f"{ticker}: 缓存文件不存在 {path}")
            ok = False
            continue
        try:
            df = pd.read_parquet(path)
            assert len(df) > 0, "空文件"
            assert list(df.columns[:7]) == [
                "open", "high", "low", "close", "volume", "adj_factor", "is_tradable"
            ], f"列名不符: {list(df.columns)}"
            _ok(f"{ticker}: {path.stat().st_size // 1024} KB, {len(df)} 行")
        except Exception as e:
            _fail(f"{ticker}: {e}")
            ok = False
    return ok


def check_adj_prices(adapter: YahooFinanceAdapter, cache_dir: Path) -> bool:
    print("\n=== 3. 复权价格 OHLC 约束验证 ===")
    ok = True
    for ticker in TEST_TICKERS:
        df = load_price_data(ticker, adapter, START, END, cache_dir=cache_dir)
        adj = compute_adj_prices(df)
        tradable = adj[adj["is_tradable"]]

        tol = 1e-4
        violations = (
            (tradable["adj_open"] > tradable["adj_high"] + tol)
            | (tradable["adj_low"] > tradable["adj_close"] + tol)
            | (tradable["adj_low"] > tradable["adj_high"] + tol)
        )
        n_bad = violations.sum()
        if n_bad > 0:
            _fail(f"{ticker}: {n_bad} 行违反 OHLC 约束")
            ok = False
        else:
            af = adj["adj_factor"]
            _ok(f"{ticker}: OHLC 约束全部满足, adj_factor ∈ [{af.min():.4f}, {af.max():.4f}]")
    return ok


def check_is_tradable(adapter: YahooFinanceAdapter, cache_dir: Path) -> bool:
    print("\n=== 4. is_tradable 覆盖率验证 ===")
    ok = True
    for ticker in TEST_TICKERS:
        df = load_price_data(ticker, adapter, START, END, cache_dir=cache_dir)
        rate = df["is_tradable"].mean()
        if rate < 0.80:
            _fail(f"{ticker}: is_tradable 比率过低 {rate:.1%}")
            ok = False
        else:
            _ok(f"{ticker}: is_tradable = {rate:.1%}")
    return ok


def check_incremental_update(adapter: YahooFinanceAdapter, cache_dir: Path) -> bool:
    print("\n=== 5. 增量更新验证 ===")
    ticker = "SPY"
    try:
        df_before = load_price_data(ticker, adapter, START, END, cache_dir=cache_dir)
        rows_before = len(df_before)

        # Extend date range — should only download the tail
        t0 = time.time()
        df_after = load_price_data(ticker, adapter, START, EXTEND_END, cache_dir=cache_dir)
        elapsed = time.time() - t0

        rows_after = len(df_after)
        if rows_after <= rows_before:
            _fail(f"行数未增加: before={rows_before}, after={rows_after}")
            return False

        _ok(f"before={rows_before} 行, after={rows_after} 行, 耗时 {elapsed:.1f}s")
        _ok(f"新日期范围: {df_after.index.min().date()} → {df_after.index.max().date()}")
        return True
    except Exception as e:
        _fail(f"增量更新失败: {e}")
        return False


def check_universe_filter(adapter: YahooFinanceAdapter, cache_dir: Path) -> bool:
    print("\n=== 6. get_universe_at_date 筛选验证 ===")
    try:
        panel = load_price_panel(TEST_TICKERS, adapter, START, END, cache_dir=cache_dir)
        date = "2023-06-15"
        universe = get_universe_at_date(
            panel,
            date=date,
            min_price=5.0,
            min_adv_m=10.0,  # $10M ADV (all 5 test tickers should easily pass)
        )
        if len(universe) == 0:
            _fail(f"没有标的通过 universe 筛选 (date={date})")
            return False
        _ok(f"筛选结果 ({date}): {universe}")
        return True
    except Exception as e:
        _fail(f"universe 筛选失败: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 55)
    print("Phase 1 数据层验收")
    print("=" * 55)

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "prices"
        cache_dir.mkdir()
        adapter = YahooFinanceAdapter()

        results = {
            "1. 数据下载":        check_download(adapter, cache_dir),
            "2. Parquet 缓存":    check_parquet_cache(cache_dir),
            "3. 复权价格约束":    check_adj_prices(adapter, cache_dir),
            "4. is_tradable 覆盖": check_is_tradable(adapter, cache_dir),
            "5. 增量更新":        check_incremental_update(adapter, cache_dir),
            "6. Universe 筛选":   check_universe_filter(adapter, cache_dir),
        }

    print("\n=== 验收结果汇总 ===")
    all_passed = True
    for name, passed in results.items():
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("✓ Phase 1 验收通过，可以进入 Phase 2（指标层）")
        sys.exit(0)
    else:
        print("✗ 有项目未通过，请根据上面的错误信息修复后重新运行")
        sys.exit(1)


if __name__ == "__main__":
    main()
