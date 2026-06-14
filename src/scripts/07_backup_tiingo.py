"""
Backup Tiingo cache data to a single compressed archive.

Creates:  tiingo_backup_YYYY-MM-DD.tar.gz  (in project root)

The archive contains:
  - data/cache/tiingo/*.parquet      (all downloaded price data)
  - data/cache/tiingo_quality_report.csv  (quality check results, if exists)
  - data/cache/tiingo/_failed_tickers.json (if exists)

Upload the resulting file to Google Drive for safe backup.

To restore:
  tar -xzf tiingo_backup_YYYY-MM-DD.tar.gz

Usage:
    python src/scripts/07_backup_tiingo.py
"""

import sys
import tarfile
import time
from datetime import date
from pathlib import Path

_root = Path(__file__).resolve().parents[2]

CACHE_DIR   = _root / "data" / "cache" / "tiingo"
BACKUP_NAME = f"tiingo_backup_{date.today()}.tar.gz"
BACKUP_PATH = _root / BACKUP_NAME


def fmt_size(bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if bytes < 1024:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024
    return f"{bytes:.1f} TB"


def _build_readme(n_tickers: int, backup_date: str) -> str:
    return f"""\
# Tiingo Historical Price Data Backup
# 备份日期 / Backup Date: {backup_date}

## 数据来源 / Data Source
Tiingo End-of-Day API (https://www.tiingo.com)
数据质量优于 Yahoo Finance，包含已退市股票（幸存者偏差防御）。

## 数据覆盖 / Coverage
- 标的数量 : {n_tickers:,} 个（NYSE / NASDAQ / AMEX 全量美股 + 策略 ETF）
- 历史深度 : 2004-01-01 → {backup_date}
- 含退市股票: 是（约 7,400 只，用于幸存者偏差防御）

## 文件结构 / File Structure
data/cache/tiingo/
    AAPL.parquet        ← 每个 ticker 一个 parquet 文件
    SPY.parquet
    ...
    _failed_tickers.json   ← 下载失败的 ticker 列表（如有）
data/cache/tiingo_quality_report.csv  ← 数据质量检查报告

## 数据格式 / Schema
每个 .parquet 文件是一个 pandas DataFrame，索引为日期，列如下：

| 列名        | 类型    | 说明                                      |
|-------------|---------|-------------------------------------------|
| open        | float64 | 当日开盘价（原始价格，未复权）            |
| high        | float64 | 当日最高价（原始价格，未复权）            |
| low         | float64 | 当日最低价（原始价格，未复权）            |
| close       | float64 | 当日收盘价（原始价格，未复权）            |
| volume      | float64 | 当日成交量（股数）                        |
| adj_factor  | float64 | 复权系数 = adjClose / close               |
| is_tradable | bool    | 该行数据是否可用（False = 异常行，跳过）  |

## 如何读取数据 / How to Read

```python
import pandas as pd

# 读取单个 ticker
df = pd.read_parquet("data/cache/tiingo/AAPL.parquet")

# 计算复权价格
df["adj_close"] = df["close"] * df["adj_factor"]
df["adj_open"]  = df["open"]  * df["adj_factor"]
df["adj_high"]  = df["high"]  * df["adj_factor"]
df["adj_low"]   = df["low"]   * df["adj_factor"]

# 只使用可交易行
df = df[df["is_tradable"]]

print(df.tail())
```

## 如何恢复 / How to Restore
在项目根目录下运行：

    tar -xzf tiingo_backup_{backup_date}.tar.gz

文件会自动还原到原路径 data/cache/tiingo/

## 注意事项 / Notes
1. 价格过滤建议用原始 close（非复权），与实际交易价格一致
2. 成交量、ADV 计算用原始 volume
3. 策略回测用复权价格（adj_close）计算突破信号和止损
4. is_tradable=False 的行已标记异常（复权系数跳变 >50%、零成交量、OHLC 错误），
   回测时应跳过这些行
5. 幸存者偏差：本数据集包含约 7,400 只已退市股票，
   比仅使用当前 S&P 900 成分股的数据集更能反映真实历史表现
"""


def main() -> None:
    if not CACHE_DIR.exists():
        print(f"ERROR: 缓存目录不存在: {CACHE_DIR}")
        sys.exit(1)

    # Collect files to archive
    files: list[Path] = sorted(CACHE_DIR.glob("*.parquet"))
    extras = [
        _root / "data" / "cache" / "tiingo_quality_report.csv",
        CACHE_DIR / "_failed_tickers.json",
    ]
    for f in extras:
        if f.exists():
            files.append(f)

    if not files:
        print("ERROR: 没有找到任何数据文件")
        sys.exit(1)

    n_parquet = len(files)
    total_uncompressed = sum(f.stat().st_size for f in files)
    backup_date = str(date.today())

    print(f"\n{'='*60}")
    print(f"  Tiingo 数据备份")
    print(f"  文件数    : {n_parquet:,} 个")
    print(f"  原始大小  : {fmt_size(total_uncompressed)}")
    print(f"  输出文件  : {BACKUP_NAME}")
    print(f"{'='*60}\n")

    t0 = time.time()
    done = 0

    readme_content = _build_readme(n_parquet, backup_date)

    with tarfile.open(BACKUP_PATH, "w:gz") as tar:
        # Add README first
        import io
        readme_bytes = readme_content.encode("utf-8")
        info = tarfile.TarInfo(name="README.md")
        info.size = len(readme_bytes)
        tar.addfile(info, io.BytesIO(readme_bytes))

        # Add all data files
        for f in files:
            arcname = str(f.relative_to(_root))
            tar.add(f, arcname=arcname)
            done += 1
            if done % 1000 == 0 or done == len(files):
                pct = done / len(files)
                bar = "█" * int(20 * pct) + "░" * (20 - int(20 * pct))
                print(f"\r  [{bar}] {done:,}/{len(files):,} ({pct:.0%})", end="", flush=True)

    print()
    elapsed = time.time() - t0
    compressed = BACKUP_PATH.stat().st_size
    ratio = (1 - compressed / total_uncompressed) * 100

    print(f"\n{'='*60}")
    print(f"  ✓ 备份完成")
    print(f"  压缩后大小  : {fmt_size(compressed)}  （压缩率 {ratio:.0f}%）")
    print(f"  耗时        : {elapsed:.0f}s")
    print(f"  文件路径    : {BACKUP_PATH}")
    print(f"{'='*60}")
    print(f"\n  下一步：将 {BACKUP_NAME} 上传到 Google Drive")
    print(f"\n  如需恢复数据：")
    print(f"    cd {_root}")
    print(f"    tar -xzf {BACKUP_NAME}\n")


if __name__ == "__main__":
    main()
