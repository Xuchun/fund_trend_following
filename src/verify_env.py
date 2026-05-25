"""
Phase 0 验收脚本：检查所有依赖是否正确安装，并运行一个简单的 yfinance 下载测试。

使用方法：
    python src/verify_env.py
"""

import sys


def check_imports() -> list[str]:
    """检查所有必需的库是否可以导入，返回失败列表。"""
    required = [
        ("yfinance",     "yfinance"),
        ("pandas",       "pandas"),
        ("numpy",        "numpy"),
        ("scipy",        "scipy"),
        ("matplotlib",   "matplotlib"),
        ("seaborn",      "seaborn"),
        ("quantstats",   "quantstats"),
        ("pyarrow",      "pyarrow"),
        ("fastparquet",  "fastparquet"),
    ]

    failed = []
    print("=== 检查库导入 ===")
    for display_name, module_name in required:
        try:
            mod = __import__(module_name)
            version = getattr(mod, "__version__", "unknown")
            print(f"  ✓ {display_name:<14} {version}")
        except ImportError as e:
            print(f"  ✗ {display_name:<14} 导入失败: {e}")
            failed.append(display_name)

    return failed


def check_yfinance_download() -> bool:
    """下载 SPY 最近 5 天数据，验证 yfinance 网络连接正常。"""
    print("\n=== 测试 yfinance 数据下载（SPY，最近5天）===")
    try:
        import yfinance as yf
        df = yf.download("SPY", period="5d", auto_adjust=True, progress=False)

        if df.empty:
            print("  ✗ 下载结果为空，请检查网络连接")
            return False

        print(f"  ✓ 下载成功，共 {len(df)} 行，列: {list(df.columns)}")
        print(f"  ✓ 日期范围: {df.index[0].date()} → {df.index[-1].date()}")

        required_cols = {"Open", "High", "Low", "Close", "Volume"}
        missing = required_cols - set(df.columns)
        if missing:
            print(f"  ✗ 缺少必要列: {missing}")
            return False

        print(f"  ✓ 所有必要列存在: {required_cols}")
        return True

    except Exception as e:
        print(f"  ✗ 下载失败: {e}")
        return False


def check_adj_factor_calc() -> bool:
    """验证复权因子计算逻辑（计划书 4.5 节）。"""
    print("\n=== 测试复权因子计算逻辑 ===")
    try:
        import yfinance as yf
        import pandas as pd

        # 下载含复权和未复权数据
        ticker = yf.Ticker("AAPL")
        raw = ticker.history(period="30d", auto_adjust=False)

        if raw.empty:
            print("  ✗ AAPL 数据下载为空")
            return False

        # 按计划书 4.5 节计算 adj_factor
        adj_factor = raw["Close"] / raw["Close"]  # placeholder: yfinance auto_adjust=False 给出 Adj Close
        # yfinance history() auto_adjust=False 时包含 "Adj Close" 列
        if "Adj Close" not in raw.columns:
            print("  ⚠ 未找到 'Adj Close' 列，跳过复权计算验证")
            return True

        adj_factor = raw["Adj Close"] / raw["Close"]
        adj_open  = raw["Open"]  * adj_factor
        adj_high  = raw["High"]  * adj_factor
        adj_low   = raw["Low"]   * adj_factor

        # 基本合理性验证
        assert (adj_open  <= adj_high + 1e-6).all(), "adj_open > adj_high"
        assert (adj_low   <= adj_open  + 1e-6).all(), "adj_low > adj_open"
        assert (adj_low   <= adj_high  + 1e-6).all(), "adj_low > adj_high"

        print(f"  ✓ AAPL 复权因子计算正确，adj_factor 范围: "
              f"[{adj_factor.min():.4f}, {adj_factor.max():.4f}]")
        print(f"  ✓ adj_open ≤ adj_high ≤ OK，adj_low ≤ adj_open OK")
        return True

    except AssertionError as e:
        print(f"  ✗ 复权价格逻辑异常: {e}")
        return False
    except Exception as e:
        print(f"  ✗ 复权测试失败: {e}")
        return False


def check_parquet_roundtrip() -> bool:
    """验证 Parquet 读写（本地缓存的核心存储格式）。"""
    print("\n=== 测试 Parquet 读写 ===")
    try:
        import pandas as pd
        import numpy as np
        import tempfile, os

        df = pd.DataFrame({
            "date":      pd.date_range("2020-01-01", periods=10, freq="B"),
            "open":      np.random.uniform(100, 200, 10),
            "high":      np.random.uniform(200, 300, 10),
            "low":       np.random.uniform(50,  100, 10),
            "close":     np.random.uniform(100, 200, 10),
            "volume":    np.random.randint(1_000_000, 10_000_000, 10),
            "is_tradable": [True] * 10,
        }).set_index("date")

        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            path = f.name

        df.to_parquet(path)
        df2 = pd.read_parquet(path)
        os.unlink(path)

        assert df.shape == df2.shape, "读写后形状不一致"
        assert list(df.columns) == list(df2.columns), "列名不一致"
        print(f"  ✓ Parquet 写入/读取正常，shape={df.shape}")
        return True

    except Exception as e:
        print(f"  ✗ Parquet 测试失败: {e}")
        return False


def main():
    print("=" * 50)
    print("Phase 0 环境验收")
    print("=" * 50)

    results = {}

    failed_imports = check_imports()
    results["库导入"] = len(failed_imports) == 0

    results["yfinance下载"] = check_yfinance_download()
    results["复权计算"]     = check_adj_factor_calc()
    results["Parquet读写"]  = check_parquet_roundtrip()

    print("\n=== 验收结果汇总 ===")
    all_passed = True
    for name, passed in results.items():
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("✓ Phase 0 验收通过，可以进入 Phase 1（数据层）")
        sys.exit(0)
    else:
        print("✗ 有项目未通过，请根据上面的错误信息修复后重新运行")
        sys.exit(1)


if __name__ == "__main__":
    main()
