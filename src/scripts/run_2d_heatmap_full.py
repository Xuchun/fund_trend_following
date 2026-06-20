"""
[已废弃] 此脚本使用 Yahoo Finance 数据，已不再使用。请改用对应 Tiingo 版本。
2-D parameter heatmap — full-metrics version.

Runs two 2-D parameter grids and saves ALL backtest metrics per combination.
Checkpoints after each combination so the run can be interrupted and resumed.

Grids:
  A) breakout_window × stop_loss_multiplier  (7 × 4 = 28 combos)
  B) breakout_window × trail_multiplier_r1   (4 × 5 = 20 combos)

Output:
  results/v1/heatmap/breakout_window_x_stop_loss_multiplier.json
  results/v1/heatmap/breakout_window_x_trail_multiplier_r1.json

Usage:
  python src/scripts/run_2d_heatmap_full.py [--grid A] [--grid B]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_OUT_DIR     = _root / "results" / "v1" / "heatmap"
_START       = "2004-01-01"
_END         = "2026-06-09"
_CAPITAL     = 10_000_000.0
_RF          = 0.02

# Grid definitions
GRIDS = {
    "A": {
        "param1":       "breakout_window",
        "param2":       "stop_loss_multiplier",
        "values1":      [150, 170, 200, 230, 250, 270, 300],
        "values2":      [1.5, 2.0, 2.5, 3.0],
        "int1":         True,
        "filename":     "breakout_window_x_stop_loss_multiplier.json",
        "label":        "N × ATR止损乘数",
    },
    "B": {
        "param2":       "trail_multiplier_r1",
        "param1":       "breakout_window",
        "values1":      [150, 200, 250, 300],
        "values2":      [2.0, 2.5, 3.0, 3.5, 4.0],
        "int1":         True,
        "filename":     "breakout_window_x_trail_multiplier_r1.json",
        "label":        "N × 移动止盈乘数",
    },
}


def _load_checkpoint(path: Path) -> dict:
    if path.exists():
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            done = {(r["param1_value"], r["param2_value"]) for r in d.get("combinations", [])}
            logger.info("Checkpoint: %d combinations already done", len(done))
            return d
        except Exception:
            pass
    return {"combinations": []}


def _save_checkpoint(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_grid(grid_key: str) -> None:
    cfg = GRIDS[grid_key]
    out_path = _OUT_DIR / cfg["filename"]
    logger.info("=" * 60)
    logger.info("Grid %s: %s", grid_key, cfg["label"])
    logger.info("Output: %s", out_path)
    logger.info("=" * 60)

    # ── Load checkpoint ──────────────────────────────────────────────────────
    ckpt = _load_checkpoint(out_path)
    done = {(r["param1_value"], r["param2_value"]) for r in ckpt["combinations"]}

    # ── Load universe data ───────────────────────────────────────────────────
    from data.adapters.yahoo import YahooFinanceAdapter
    from data.pipeline import load_price_panel
    from data.universe import ETF_TICKERS, fetch_sp900_tickers
    from indicators.precompute import precompute_indicators
    from strategy.params import StrategyParams

    params = StrategyParams()
    adapter = YahooFinanceAdapter()

    tickers = fetch_sp900_tickers()
    all_tickers = list({params.cash_proxy, "SPY"} | set(tickers) | set(ETF_TICKERS))
    strategy_tickers = [t for t in tickers if t not in {"SPY", params.cash_proxy}]
    strategy_tickers += [t for t in ETF_TICKERS if t not in strategy_tickers and t not in {"SPY", params.cash_proxy}]

    logger.info("Loading price panel (%d tickers) …", len(all_tickers))
    price_panel = load_price_panel(
        tickers=all_tickers,
        start=_START,
        end=_END,
        adapter=adapter,
    )
    strategy_tickers = [t for t in strategy_tickers if t in price_panel]
    logger.info("Price panel: %d tickers; strategy tickers: %d", len(price_panel), len(strategy_tickers))

    logger.info("Pre-computing baseline indicators …")
    baseline_indicators = precompute_indicators(price_panel, params)

    # ── Run combinations ─────────────────────────────────────────────────────
    from analysis.perturbation import _build_indicators
    from backtest.engine import BacktestEngine
    from strategy.v1.strategy_v1 import StrategyV1

    values1 = cfg["values1"]
    values2 = cfg["values2"]
    p1_name = cfg["param1"]
    p2_name = cfg["param2"]
    n_total = len(values1) * len(values2)
    run_idx = 0
    t0 = time.perf_counter()

    for v1 in values1:
        ind1 = _build_indicators(p1_name, v1, baseline_indicators, price_panel)
        params1 = replace(params, **{p1_name: v1})

        for v2 in values2:
            run_idx += 1
            key = (v1, v2)
            if key in done:
                logger.info("[%d/%d] SKIP (checkpoint)  %s=%s  %s=%s",
                            run_idx, n_total, p1_name, v1, p2_name, v2)
                continue

            logger.info("[%d/%d]  %s=%s  %s=%s …",
                        run_idx, n_total, p1_name, v1, p2_name, v2)
            t1 = time.perf_counter()

            params2 = replace(params1, **{p2_name: v2})
            ind2 = _build_indicators(p2_name, v2, ind1, price_panel)

            engine = BacktestEngine(
                strategy=StrategyV1(params2),
                price_panel=price_panel,
                indicators=ind2,
                params=params2,
                initial_capital=_CAPITAL,
            )
            results = engine.run(_START, _END, strategy_tickers)
            m = results.compute_metrics(risk_free_rate=_RF)

            combo = {
                "param1_value": v1,
                "param2_value": v2,
                **{k: float(v) if isinstance(v, (int, float)) else v for k, v in m.items()},
            }
            ckpt["combinations"].append(combo)
            _save_checkpoint(out_path, {
                "type":    "2d_full",
                "param1":  p1_name,
                "param2":  p2_name,
                "start":   _START,
                "end":     _END,
                "values1": values1,
                "values2": values2,
                "combinations": ckpt["combinations"],
            })

            elapsed_combo = time.perf_counter() - t1
            remaining = (n_total - run_idx) * elapsed_combo / 60
            logger.info(
                "  → CAGR=%+.2f%%  Sharpe=%+.3f  MaxDD=%.1f%%  "
                "(%.0fs/combo, est. %.0f min remaining)",
                m.get("cagr", 0) * 100,
                m.get("sharpe", 0),
                m.get("max_drawdown", 0) * 100,
                elapsed_combo,
                remaining,
            )

    elapsed_total = time.perf_counter() - t0
    logger.info("Grid %s done. Total: %.1f min", grid_key, elapsed_total / 60)

    # Write final file
    _save_checkpoint(out_path, {
        "type":    "2d_full",
        "param1":  p1_name,
        "param2":  p2_name,
        "start":   _START,
        "end":     _END,
        "values1": values1,
        "values2": values2,
        "combinations": ckpt["combinations"],
    })
    logger.info("Saved → %s", out_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid", choices=["A", "B", "AB"], default="AB",
                        help="Which grid(s) to run (A=N×SL, B=N×Trail, AB=both)")
    args = parser.parse_args()

    grids = ["A", "B"] if args.grid == "AB" else [args.grid]
    for g in grids:
        run_grid(g)


if __name__ == "__main__":
    main()
