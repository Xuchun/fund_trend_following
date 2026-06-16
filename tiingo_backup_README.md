# Tiingo Historical Price Data Backup
# 备份日期 / Backup Date: 2026-06-16

## 数据来源 / Data Source
Tiingo End-of-Day API (https://www.tiingo.com)
数据质量优于 Yahoo Finance，包含已退市股票（幸存者偏差防御）。

## 数据覆盖 / Coverage
- 标的数量 : 15,273 个（NYSE / NASDAQ / AMEX 全量美股 + 策略 ETF）
- 历史深度 : 1996-01-01 起（各 ticker 实际上市日起始）→ 2026-06-16
- 含退市股票: 是（约 7,400 只，用于幸存者偏差防御）
- 最早数据  : SPY（1996-01-01）、部分大盘股 1990s 即有数据

## 文件结构 / File Structure
```
data/cache/tiingo/
    AAPL.parquet                  ← 每个 ticker 一个 parquet 文件
    SPY.parquet
    ...（共 15,273 个 .parquet）
    _failed_tickers.json          ← 下载失败 / 无数据的 ticker 列表
data/cache/tiingo_quality_report.csv       ← 数据质量检查报告
data/cache/tiingo_eligible_universe.csv    ← 策略候选池（2,978 个 ticker，含资格判断列）
```

## 数据格式 / Schema
每个 .parquet 文件是一个 pandas DataFrame，索引为日期（DatetimeIndex），列如下：

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

# 日期范围
print(df.index.min(), "→", df.index.max())
print(df.tail())
```

## 如何恢复 / How to Restore
在项目根目录下运行：

```bash
tar -xzf tiingo_backup_2026-06-16.tar.gz
```

文件会自动还原到原路径 `data/cache/tiingo/`

## 注意事项 / Notes
1. 价格过滤建议用原始 close（非复权），与实际交易价格一致
2. 成交量、ADV 计算用原始 volume
3. 策略回测用复权价格（adj_close）计算突破信号和止损
4. `is_tradable=False` 的行已标记异常（复权系数跳变 >50%、零成交量、OHLC 错误），
   回测时应跳过这些行
5. 幸存者偏差：本数据集包含约 7,400 只已退市股票，
   比仅使用当前 S&P 900 成分股的数据集更能反映真实历史表现
6. SPY 数据从 1996 年起，已用于回测起始日 2000-01-03 的策略1.0基准计算
7. `tiingo_eligible_universe.csv` 记录了策略候选池中每个 ticker 的资格判断
   （`eligible_days` 等字段），可用于动态宇宙过滤
