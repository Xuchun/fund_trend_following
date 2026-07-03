#!/usr/bin/env python3
"""
增量更新 Tiingo 缓存：只对 is_active=True 的标的下载最新缺失数据。
已有缓存的文件只下载 last_cached_date+1 到 today 的增量。
"""
import os, sys, time, logging
from datetime import date
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root))

# 加载 .env
_env = _root / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import pandas as pd
from src.data.adapters.tiingo import TiingoAdapter
from src.data.pipeline import load_price_data

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")

CACHE_DIR  = _root / "data" / "cache" / "tiingo"
UNIV_CSV   = _root / "data" / "tiingo_eligible_universe.csv"
START_DATE = "2004-01-01"
END_DATE   = date.today().isoformat()
DELAY      = 0.4

token = os.environ.get("TIINGO_API_TOKEN", "")
if not token:
    print("ERROR: TIINGO_API_TOKEN not set"); sys.exit(1)

adapter = TiingoAdapter(api_token=token, request_delay=DELAY)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

df_univ = pd.read_csv(UNIV_CSV)
tickers = sorted(df_univ[df_univ["is_active"] == True]["ticker"].tolist())
total   = len(tickers)

print(f"增量更新 Tiingo 缓存")
print(f"  Active 标的: {total:,}")
print(f"  更新至:     {END_DATE}")
print(f"  缓存目录:   {CACHE_DIR}\n")

ok = skipped = failed = 0
t0 = time.time()
log_path = _root / "tmp" / "tiingo_update.log"
log_path.parent.mkdir(exist_ok=True)

with open(log_path, "w") as log_f:
    for i, ticker in enumerate(tickers, 1):
        try:
            df = load_price_data(ticker, adapter, START_DATE, END_DATE,
                                 cache_dir=CACHE_DIR, force_refresh=False)
            if df.empty:
                failed += 1
                log_f.write(f"EMPTY {ticker}\n")
            else:
                ok += 1
        except Exception as e:
            failed += 1
            log_f.write(f"FAIL  {ticker}: {e}\n")

        elapsed = time.time() - t0
        eta_s   = (elapsed / i) * (total - i) if i > 0 else 0
        eta     = f"{int(eta_s//3600)}h{int((eta_s%3600)//60):02d}m"
        bar     = "█" * int(20*i/total) + "░" * (20 - int(20*i/total))
        print(f"\r[{bar}] {i}/{total} ({i/total:.0%})  ✓{ok} ✗{failed}  ETA {eta}   ",
              end="", flush=True)

print(f"\n\n完成！✓{ok}  ✗{failed}  用时 {(time.time()-t0)/60:.1f} 分钟")
print(f"失败详情见: {log_path}")

# 打印摘要
files = list(CACHE_DIR.glob("*.parquet"))
dates = []
for f in files:
    try:
        d = pd.read_parquet(f, columns=["close"])
        if not d.empty: dates.append(d.index.max())
    except: pass
s = pd.Series(dates)
print(f"\n缓存摘要:")
print(f"  总文件数:   {len(files):,}")
print(f"  最新数据:   {s.max().date()}")
print(f"  最旧数据:   {s.min().date()}")
print(f"  数据到今日: {(s >= pd.Timestamp(END_DATE)).sum():,} 个标的")
