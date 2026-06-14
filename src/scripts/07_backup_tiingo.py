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

    total_uncompressed = sum(f.stat().st_size for f in files)
    print(f"\n{'='*60}")
    print(f"  Tiingo 数据备份")
    print(f"  文件数    : {len(files):,} 个")
    print(f"  原始大小  : {fmt_size(total_uncompressed)}")
    print(f"  输出文件  : {BACKUP_NAME}")
    print(f"{'='*60}\n")

    t0 = time.time()
    done = 0

    with tarfile.open(BACKUP_PATH, "w:gz") as tar:
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
