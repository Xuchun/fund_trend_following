"""
Tiingo 版参数敏感性分析 — 批量扰动测试脚本。

数据来源: Tiingo 本地 parquet 缓存（无 API 调用）
标的池:   data/tiingo_eligible_universe.csv（2,937 只历史标的）
基准参数: min_adv_m=$50M（Tiingo Baseline）
输出目录: results/v1_unbiased_50m/perturbation/

用法:
    cd /Users/xuchun/Documents/fund_trend_following
    /Users/xuchun/anaconda3/bin/python3.11 src/scripts/run_all_perturbations_tiingo.py

已存在的 JSON 文件会自动跳过（删除对应文件可强制重跑单个参数）。
"""

import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from data.pipeline import compute_adj_prices
from data.universe import EXCLUDED_VOL_ETFS
from indicators.precompute import precompute_indicators
from strategy.params import StrategyParams
from analysis.perturbation import run_perturbation_test

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 路径配置 ────────────────────────────────────────────────────────────────────
TIINGO_CACHE = ROOT / "data" / "cache" / "tiingo"
EU_CSV       = ROOT / "data" / "tiingo_eligible_universe.csv"
OUTPUT_DIR   = ROOT / "results" / "v1_unbiased_60m" / "perturbation"

START           = "2004-01-02"
END             = "2026-06-12"
INITIAL_CAPITAL = 10_000_000.0
MIN_ELIGIBLE_DAYS = 252

# ── Baseline 参数（与 09_run_v1_unbiased.py Run A 一致，min_adv_m=$60M） ──────
BASELINE = StrategyParams(
    min_price               = 10.0,
    min_market_cap_b        = 2.0,
    min_adv_m               = 60.0,   # Tiingo Baseline
    breakout_window         = 200,
    atr_period              = 20,
    stop_loss_multiplier    = 2.0,
    min_stop_distance_pct   = 0.005,
    trail_multiplier_r1     = 3.0,
    trail_multiplier_r3     = 3.0,
    trail_multiplier_r5     = 5.0,
    risk_per_trade          = 0.01,
    position_cap            = 0.05,
    heat_limit              = 0.10,
    correlation_window      = 60,
    correlation_threshold   = 0.70,
    correlation_reduction   = 0.50,
    volume_filter_multiplier= 1.5,
    breakout_strength_min   = 0.0,
    gap_filter              = 0.025,
    commission_bps          = 3.0,
    slippage_bps            = 10.0,
    cash_proxy              = "SHY",
    regime_filter_enabled   = True,
    regime_ticker           = "SPY",
    regime_sma_window       = 200,
    consolidation_filter_enabled = False,
    consolidation_window    = 80,
    consolidation_threshold = 0.25,
)

# ── 扫描配置 ────────────────────────────────────────────────────────────────────
# 格式: (参数名, [测试值列表], 是否整数)
# 注意: min_adv_m 的测试范围改为 $40M–$80M，基准为 $60M
SWEEPS = [
    ("trail_multiplier_r1",      [2.0, 2.5, 3.0, 3.5, 4.0],          False),
    ("breakout_window",          [150, 170, 200, 230, 250, 270, 300], True),
    ("stop_loss_multiplier",     [1.5, 2.0, 2.5, 3.0],               False),
    ("risk_per_trade",           [0.005, 0.010, 0.015, 0.020],        False),
    ("position_cap",             [0.03, 0.05, 0.07, 0.10],            False),
    ("heat_limit",               [0.05, 0.10, 0.15, 0.20],            False),
    ("correlation_threshold",    [0.5, 0.6, 0.7, 0.8, 0.9],          False),
    ("volume_filter_multiplier", [1.0, 1.2, 1.5, 1.7, 2.0],          False),
    ("min_price",                [8.0, 10.0, 12.0, 15.0],             False),
    ("min_market_cap_b",         [2.0, 3.0, 4.0],                     False),
    ("min_adv_m",                [40.0, 50.0, 60.0, 70.0, 80.0],      False),  # Tiingo: $60M baseline
    ("slippage_bps",             [5.0, 8.0, 10.0, 12.0, 15.0],        False),
    ("commission_bps",           [1.0, 3.0, 5.0],                     False),
]


def load_universe() -> list[str]:
    if not EU_CSV.exists():
        raise FileNotFoundError(f"Universe CSV not found: {EU_CSV}\n"
                                "Run: python src/scripts/08_eligible_universe.py")
    eu = pd.read_csv(EU_CSV)
    tickers = eu[eu["eligible_days"] >= MIN_ELIGIBLE_DAYS]["ticker"].tolist()
    excluded = [t for t in tickers if t in EXCLUDED_VOL_ETFS]
    if excluded:
        logger.info("Excluding %d vol/inverse ETFs: %s", len(excluded), excluded)
    tickers = [t for t in tickers if t not in EXCLUDED_VOL_ETFS]
    logger.info("Dynamic universe (%d-day filter): %d tickers", MIN_ELIGIBLE_DAYS, len(tickers))
    return sorted(tickers)


def load_panel_from_cache(tickers: list[str]) -> dict[str, pd.DataFrame]:
    start_ts = pd.Timestamp(START)
    end_ts   = pd.Timestamp(END)
    panel: dict[str, pd.DataFrame] = {}
    missing = 0
    for ticker in tickers:
        path = TIINGO_CACHE / f"{ticker.upper()}.parquet"
        if not path.exists():
            missing += 1
            continue
        try:
            df = pd.read_parquet(path)
            df.index = pd.DatetimeIndex(df.index)
            df = df.sort_index()
            df = df[(df.index >= start_ts) & (df.index <= end_ts)]
            if not df.empty:
                panel[ticker] = compute_adj_prices(df)
        except Exception as e:
            logger.warning("Could not read %s: %s", ticker, e)
    if missing:
        logger.warning("%d tickers not found in cache (skipped)", missing)
    logger.info("Panel loaded: %d tickers", len(panel))
    return panel


def save_result(param_name, param_values, results_df, baseline_value, elapsed):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    for pval, row in results_df.iterrows():
        rec = {"param_value": pval}
        for k, v in row.items():
            try:
                rec[k] = float(v)
            except (TypeError, ValueError):
                rec[k] = v
        records.append(rec)

    out = {
        "param_name":      param_name,
        "param_values":    param_values,
        "baseline_value":  baseline_value,
        "start":           START,
        "end":             END,
        "initial_capital": INITIAL_CAPITAL,
        "universe_mode":   "tiingo_v1_unbiased_50m",
        "risk_free_rate":  0.02,
        "elapsed_seconds": round(elapsed, 1),
        "results":         records,
    }
    path = OUTPUT_DIR / f"{param_name}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    logger.info("Saved → %s", path)
    return path


def main():
    t_total = time.time()

    # ── 1. 加载标的池 ──────────────────────────────────────────────────────────
    universe = load_universe()
    must_have = {BASELINE.cash_proxy, "SPY"}
    all_tickers = sorted(set(universe) | must_have)

    # ── 2. 从 Tiingo 缓存加载价格面板 ─────────────────────────────────────────
    logger.info("Loading price panel (%d tickers) from Tiingo cache …", len(all_tickers))
    t0 = time.time()
    panel = load_panel_from_cache(all_tickers)
    logger.info("Panel loaded: %d tickers in %.1fs", len(panel), time.time() - t0)

    auxiliary = {BASELINE.cash_proxy, "SPY"}
    strategy_tickers = [t for t in universe if t in panel and t not in auxiliary]
    logger.info("Strategy tickers with data: %d / %d", len(strategy_tickers), len(universe))

    # ── 3. 预计算基准指标（所有扫描共用） ───────────────────────────────────
    logger.info("Precomputing baseline indicators (min_adv_m=$50M) …")
    t1 = time.time()
    strategy_panel = {t: panel[t] for t in strategy_tickers}
    baseline_indicators = precompute_indicators(strategy_panel, BASELINE)
    logger.info("Indicators ready in %.1fs", time.time() - t1)

    # ── 4. 逐参数扫描 ────────────────────────────────────────────────────────
    n_sweeps = len(SWEEPS)
    for sweep_idx, (param_name, param_values, _use_int) in enumerate(SWEEPS, 1):
        out_path = OUTPUT_DIR / f"{param_name}.json"
        if out_path.exists():
            logger.info(
                "[%d/%d] SKIP %s — already exists (delete file to re-run)",
                sweep_idx, n_sweeps, param_name,
            )
            continue

        logger.info(
            "\n%s\n[%d/%d] Sweeping %s over %s\n%s",
            "=" * 65, sweep_idx, n_sweeps, param_name, param_values, "=" * 65,
        )
        t2 = time.time()

        results_df = run_perturbation_test(
            param_name=param_name,
            param_values=param_values,
            baseline_params=BASELINE,
            price_panel=panel,
            baseline_indicators=baseline_indicators,
            start=START,
            end=END,
            initial_capital=INITIAL_CAPITAL,
            risk_free_rate=0.02,
            strategy_tickers=strategy_tickers,
        )

        elapsed = time.time() - t2
        save_result(
            param_name, param_values, results_df,
            getattr(BASELINE, param_name), elapsed,
        )

        display_cols = ["cagr", "max_drawdown", "sharpe", "sortino", "calmar",
                        "annual_turnover", "avg_holding_days"]
        avail = [c for c in display_cols if c in results_df.columns]
        print(f"\n{'='*65}")
        print(f"  {param_name} results  (Tiingo / ADV>$50M baseline)")
        print(f"{'='*65}")
        print(results_df[avail].to_string(float_format=lambda x: f"{x:+.4f}"))
        print(f"  Elapsed: {elapsed:.1f}s")
        print(f"{'='*65}\n")

    total = time.time() - t_total
    logger.info("\n✓ All sweeps complete. Total wall time: %.0fs (%.1fh)", total, total / 3600)
    print(f"\n✓ 全部完成。结果已保存至 {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
