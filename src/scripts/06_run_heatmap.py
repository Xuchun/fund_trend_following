"""
Script: parameter heatmap — Phase 6, Week 3.

Runs 1-D or 2-D parameter sensitivity sweeps on IS (in-sample) data only.
The --is-end flag hard-caps the backtest end date to prevent OOS leakage.

Usage examples
--------------
# 1-D: trail_multiplier_r1
python src/scripts/06_run_heatmap.py \\
    --type 1d \\
    --param trail_multiplier_r1 \\
    --values 2.0,2.5,3.0,3.5,4.0 \\
    --is-end 2021-12-31

# 1-D: breakout_window (integers)
python src/scripts/06_run_heatmap.py \\
    --type 1d \\
    --param breakout_window \\
    --values 150,200,250,300 \\
    --int-values \\
    --is-end 2021-12-31

# 2-D: breakout_window × stop_loss_multiplier
python src/scripts/06_run_heatmap.py \\
    --type 2d \\
    --param1 breakout_window  --values1 150,200,250,300 --int-values1 \\
    --param2 stop_loss_multiplier --values2 1.5,2.0,2.5,3.0 \\
    --metric sharpe \\
    --is-end 2021-12-31

# Quick test with ETF universe only
python src/scripts/06_run_heatmap.py \\
    --type 1d --param trail_multiplier_r1 --values 2.0,3.0,4.0 \\
    --mode etf --is-end 2021-12-31

Output
------
    results/v1/heatmap/{param}.json           (1-D)
    results/v1/heatmap/{param1}x{param2}.json (2-D)
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_project_root / "src"))

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_BASELINE_START = "2004-01-02"
_INITIAL_CAPITAL = 10_000_000.0


def _parse_values(raw: str, as_int: bool) -> list:
    parts = [v.strip() for v in raw.split(",") if v.strip()]
    return [int(v) for v in parts] if as_int else [float(v) for v in parts]


def _load_universe_and_data(mode: str, start: str, end: str, force_download: bool):
    """Load price panel and indicators from Tiingo cache."""
    from data.universe import EXCLUDED_VOL_ETFS
    from indicators.precompute import precompute_indicators
    from strategy.params import StrategyParams
    import pandas as pd

    params = StrategyParams(
        regime_filter_enabled = True,
        bear_exempt_tickers   = frozenset({"TLT", "GLD", "UUP"}),
    )

    TIINGO_CACHE  = _project_root / "data" / "cache" / "tiingo"
    EU_CSV        = _project_root / "data" / "tiingo_eligible_universe.csv"
    MIN_ELIG_DAYS = 252

    # Build universe list
    if mode == "etf":
        from data.universe import ETF_TICKERS
        tickers = [t for t in ETF_TICKERS if t not in EXCLUDED_VOL_ETFS]
    else:
        # full / sp500 / sp900 modes all use the Tiingo eligible universe
        eu = pd.read_csv(EU_CSV)
        tickers = eu[eu["eligible_days"] >= MIN_ELIG_DAYS]["ticker"].tolist()
        tickers = [t for t in tickers if t not in EXCLUDED_VOL_ETFS]

    all_tickers = list({params.cash_proxy, "SPY"} | set(tickers))

    # Load from local parquet cache (no API calls)
    start_ts = pd.Timestamp(start)
    end_ts   = pd.Timestamp(end)
    from data.pipeline import compute_adj_prices
    price_panel: dict = {}
    for ticker in all_tickers:
        path = TIINGO_CACHE / f"{ticker.upper()}.parquet"
        if not path.exists():
            continue
        try:
            df = pd.read_parquet(path)
            df.index = pd.DatetimeIndex(df.index)
            df = df.sort_index()
            df = df[(df.index >= start_ts) & (df.index <= end_ts)]
            if not df.empty:
                price_panel[ticker] = compute_adj_prices(df)
        except Exception:
            pass

    strategy_tickers = [t for t in tickers if t in price_panel and t not in {"SPY", params.cash_proxy}]
    logger.info("Price panel: %d tickers loaded (%s mode)", len(price_panel), mode)

    logger.info("Pre-computing indicators …")
    baseline_indicators = precompute_indicators(
        {t: price_panel[t] for t in strategy_tickers}, params
    )

    return params, price_panel, baseline_indicators, strategy_tickers


def _save_1d(result_df: pd.DataFrame, param_name: str, param_values: list,
             baseline_value, start: str, is_end: str, out_path: Path) -> None:
    """Serialise 1-D heatmap to JSON."""
    records = []
    for val in param_values:
        if val in result_df.index:
            row = result_df.loc[val].to_dict()
            row["param_value"] = val
            records.append(row)

    payload = {
        "type":            "1d",
        "param_name":      param_name,
        "baseline_value":  baseline_value,
        "start":           start,
        "end":             is_end,
        "results":         records,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("✓ 完成  →  %s", out_path)


def _save_2d(result_df: pd.DataFrame, param1: str, param2: str, metric: str,
             start: str, is_end: str, out_path: Path) -> None:
    """Serialise 2-D heatmap to JSON."""
    records = []
    for v1 in result_df.index:
        for v2 in result_df.columns:
            records.append({
                "param1_name":  param1,
                "param1_value": v1,
                "param2_name":  param2,
                "param2_value": v2,
                "metric_name":  metric,
                "metric_value": float(result_df.loc[v1, v2]),
            })

    payload = {
        "type":       "2d",
        "param1":     param1,
        "param2":     param2,
        "metric":     metric,
        "start":      start,
        "end":        is_end,
        "param1_values": list(result_df.index),
        "param2_values": list(result_df.columns),
        "grid":          result_df.values.tolist(),
        "records":       records,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("✓ 完成  →  %s", out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parameter heatmap (IS data only)")
    parser.add_argument("--type", choices=["1d", "2d"], required=True)

    # 1-D args
    parser.add_argument("--param",       help="Parameter name (1-D)")
    parser.add_argument("--values",      help="Comma-separated values (1-D)")
    parser.add_argument("--int-values",  action="store_true", help="Parse values as int")

    # 2-D args
    parser.add_argument("--param1",      help="First parameter name (2-D)")
    parser.add_argument("--param2",      help="Second parameter name (2-D)")
    parser.add_argument("--values1",     help="Comma-separated values for param1")
    parser.add_argument("--values2",     help="Comma-separated values for param2")
    parser.add_argument("--int-values1", action="store_true")
    parser.add_argument("--int-values2", action="store_true")
    parser.add_argument("--metric",      default="sharpe", help="Metric for 2-D grid")

    # Common args
    parser.add_argument("--is-end",    required=True, help="IS end date (YYYY-MM-DD) — OOS fence")
    parser.add_argument("--start",     default=_BASELINE_START)
    parser.add_argument("--mode",      choices=["etf", "sp500", "sp900", "full"], default="full")
    parser.add_argument("--output-dir",
                        default=str(_project_root / "results" / "v1_unbiased_60m" / "heatmap"))
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args()

    # ── Load data ────────────────────────────────────────────────────────────
    params, price_panel, baseline_indicators, strategy_tickers = _load_universe_and_data(
        mode=args.mode,
        start=args.start,
        end=args.is_end,
        force_download=args.force_download,
    )

    out_dir = Path(args.output_dir)
    t0 = time.perf_counter()

    # ── 1-D heatmap ──────────────────────────────────────────────────────────
    if args.type == "1d":
        if not args.param or not args.values:
            parser.error("--type 1d requires --param and --values")

        param_values = _parse_values(args.values, args.int_values)
        baseline_value = getattr(params, args.param, None)

        from analysis.heatmap import find_parameter_stability_region, run_1d_heatmap

        result_df = run_1d_heatmap(
            param_name=args.param,
            param_values=param_values,
            baseline_params=params,
            price_panel=price_panel,
            baseline_indicators=baseline_indicators,
            start=args.start,
            is_end=args.is_end,
            strategy_tickers=strategy_tickers,
        )

        # Print summary table
        print("\n" + "=" * 70)
        print(f"  1-D 热力图  |  {args.param}  |  IS: {args.start} → {args.is_end}")
        print("=" * 70)
        display_cols = ["cagr", "max_drawdown", "sharpe", "annual_turnover", "avg_holding_days"]
        display_cols = [c for c in display_cols if c in result_df.columns]
        print(result_df[display_cols].to_string())

        # Stability analysis
        stability = find_parameter_stability_region(result_df[display_cols])
        print("\n  稳定区间分析:")
        for metric, info in stability.items():
            rob = "✓ 鲁棒" if info["is_robust"] else "⚠ 敏感"
            print(f"    {metric:25s}  CV={info['cv']:.3f}  {rob}  "
                  f"稳定区间={info['stable_region']}")
        print("=" * 70)

        out_path = out_dir / f"{args.param}.json"
        _save_1d(result_df, args.param, param_values, baseline_value,
                 args.start, args.is_end, out_path)

    # ── 2-D heatmap ──────────────────────────────────────────────────────────
    elif args.type == "2d":
        if not all([args.param1, args.param2, args.values1, args.values2]):
            parser.error("--type 2d requires --param1 --param2 --values1 --values2")

        param1_values = _parse_values(args.values1, args.int_values1)
        param2_values = _parse_values(args.values2, args.int_values2)

        from analysis.heatmap import run_2d_heatmap

        result_df = run_2d_heatmap(
            param1_name=args.param1,
            param1_values=param1_values,
            param2_name=args.param2,
            param2_values=param2_values,
            baseline_params=params,
            price_panel=price_panel,
            baseline_indicators=baseline_indicators,
            start=args.start,
            is_end=args.is_end,
            metric=args.metric,
            strategy_tickers=strategy_tickers,
        )

        print("\n" + "=" * 70)
        print(f"  2-D 热力图  |  {args.param1} × {args.param2}  |  metric={args.metric}")
        print("=" * 70)
        print(result_df.to_string())
        print("=" * 70)

        fname = f"{args.param1}x{args.param2}_{args.metric}.json"
        out_path = out_dir / fname
        _save_2d(result_df, args.param1, args.param2, args.metric,
                 args.start, args.is_end, out_path)

    elapsed = time.perf_counter() - t0
    logger.info("总耗时 %.1f s", elapsed)


if __name__ == "__main__":
    main()
