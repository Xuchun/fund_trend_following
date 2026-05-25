"""
Script: run Strategy 2.0 backtest — adds SPY 200-day SMA regime filter.

New in v2 vs v1:
  - regime_filter_enabled = True
  - No new entries when SPY adj-close ≤ its 200-day SMA
  - Existing positions remain open; trailing stops still protect them
  - Idle cash continues to earn the cash-proxy (SHY) rate

Why SHY (not SGOV) as cash proxy:
  SGOV was launched in 2022; using it pre-2022 would yield 0% on cash.
  SHY (1–3Y Treasuries) covers the full 2004–2024 backtest period.

Usage:
    python src/scripts/03_run_v2.py
    python src/scripts/03_run_v2.py --mode etf               # fast sanity check
    python src/scripts/03_run_v2.py --start 2004-01-01 --end 2024-12-31
    python src/scripts/03_run_v2.py --output results/v2/
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from data.adapters.yahoo import YahooFinanceAdapter
from data.pipeline import load_price_panel
from data.universe import ETF_TICKERS, fetch_sp500_tickers, fetch_sp900_tickers
from indicators.precompute import precompute_indicators
from backtest.engine import BacktestEngine
from reports.baseline import generate_baseline_report
from strategy.params import StrategyParams
from strategy.v1.strategy_v1 import StrategyV1

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Strategy 2.0 parameters ────────────────────────────────────────────────
V2_PARAMS = StrategyParams(
    min_price               = 10.0,
    min_market_cap_b        = 2.0,
    min_adv_m               = 20.0,
    breakout_window         = 100,
    atr_period              = 20,
    stop_loss_multiplier    = 2.0,
    min_stop_distance_pct   = 0.005,
    trail_multiplier_r1     = 2.0,
    trail_multiplier_r3     = 3.0,
    trail_multiplier_r5     = 5.0,
    risk_per_trade          = 0.01,
    position_cap            = 0.05,
    heat_limit              = 0.10,
    correlation_window      = 60,
    correlation_threshold   = 0.70,
    correlation_reduction   = 0.50,
    gap_filter              = 0.025,
    commission_bps          = 3.0,
    slippage_bps            = 10.0,
    cash_proxy              = "SHY",   # covers full 2004–2024 period
    # ── NEW in v2 ──
    regime_filter_enabled   = True,
    regime_ticker           = "SPY",
    regime_sma_window       = 200,
)

DEFAULT_START = "2004-01-01"
DEFAULT_END   = "2024-12-31"

# ── Strategy 2.0 metadata ──────────────────────────────────────────────────
STRATEGY_META = {
    "id": "v2",
    "version": "2.0",
    "display_name": "Strategy 2.0",
    "subtitle": "Trend Following — Long Only, ATR Breakout + Regime Filter",
    "color": "#ff7f0e",
    "badge_text": "v2.0",
    "badge_color": "orange",
    "universe_stocks": 903,
    "universe_etfs": 21,
    "universe_total": 924,
    "backtest_start": DEFAULT_START,
    "backtest_end":   DEFAULT_END,
    "initial_capital": 10_000_000,
    "cash_proxy": "SHY",
    "key_features": [
        "100日高点突破入场（N-Day Breakout）",
        "ATR(20) Wilder平滑，固定止损 2×ATR",
        "分段追踪止损：<1R用2×ATR，1-3R用3×ATR，>3R用5×ATR",
        "1% NAV 风险仓位计算（4步过滤）",
        "相关性过滤：持仓相关性 > 0.70 时减半仓",
        "组合热度上限 10%（总风险敞口 ≤ NAV 的 10%）",
        "【新增】SPY 200日均线市场环境过滤：熊市不开新仓",
        "空仓资金投入 SHY 获取无风险收益",
    ],
    "differs_from_previous": {
        "市场环境过滤器": "当 SPY 收盘价 ≤ SPY 200日均线时，禁止新建仓位；现有持仓不强平，追踪止损继续保护",
        "空仓资金": "熊市期间额外现金同样投入 SHY（风险资金自然减少，SHY 比例提高）",
        "预期改善": "大幅减少 2008/2022 等系统性熊市的最大回撤，预计从 -54% 降至 -25% 以内",
    },
    "params_anchor": {
        "breakout_window": 100,
        "atr_period": 20,
        "stop_loss_multiplier": 2.0,
        "min_stop_distance_pct": 0.005,
        "trail_multiplier_r1": 2.0,
        "trail_multiplier_r3": 3.0,
        "trail_multiplier_r5": 5.0,
        "risk_per_trade": 0.01,
        "position_cap": 0.05,
        "heat_limit": 0.1,
        "correlation_window": 60,
        "correlation_threshold": 0.7,
        "correlation_reduction": 0.5,
        "gap_filter": 0.025,
        "commission_bps": 3.0,
        "slippage_bps": 10.0,
        "regime_filter_enabled": True,
        "regime_ticker": "SPY",
        "regime_sma_window": 200,
    },
    "logic_sections": {
        "entry": "close[t] > max(high[t-100:t-1])，使用shift(1)防前视偏差，次日开盘执行；且当日 SPY > SPY SMA(200)",
        "regime": "SPY adj-close[t] > rolling_mean(SPY adj-close, 200)[t]；否则 pending_entries 清空",
        "stop": "entry_price - 2 × ATR(20)，入场价与止损价之差定义为 1R",
        "trail": "棘轮式追踪止损：<1R用2×ATR，1-3R用3×ATR，≥3R用5×ATR；只能上移不能下移",
        "sizing": "Step1目标风险(1%NAV)→Step2单标的上限(5%NAV)→Step3相关性调整→Step4热度检查(10%)",
        "direction": "纯多头（Long Only）",
        "execution": "t日收盘生成信号，t+1日开盘价执行；滑点10bps，佣金3bps，Gap过滤±2.5%",
    },
    "etf_universe": [],
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run Strategy 2.0 backtest (regime filter)")
    p.add_argument("--mode", choices=["etf", "sp500", "sp900", "full"],
                   default="full", help="Universe mode (default: full = sp900 + all ETFs from ETFs.csv)")
    p.add_argument("--tickers", nargs="+", metavar="T",
                   help="Override --mode with an explicit ticker list")
    p.add_argument("--start",           default=DEFAULT_START)
    p.add_argument("--end",             default=DEFAULT_END)
    p.add_argument("--initial-capital", default=10_000_000, type=float)
    p.add_argument("--output",          default="results/v2/")
    p.add_argument("--force-download",  action="store_true")
    p.add_argument("-v", "--verbose",   action="store_true")
    return p.parse_args()


def build_universe(mode: str, custom_tickers: list[str] | None) -> list[str]:
    if custom_tickers:
        return [t.upper() for t in custom_tickers]
    if mode == "etf":
        return sorted(ETF_TICKERS)
    if mode == "sp500":
        tickers = fetch_sp500_tickers()
        if not tickers:
            logger.error("Failed to fetch S&P 500 tickers; aborting")
            sys.exit(1)
        return tickers
    if mode in ("sp900", "full"):
        tickers = fetch_sp900_tickers()
        if not tickers:
            logger.error("Failed to fetch S&P 900 tickers; aborting")
            sys.exit(1)
        if mode == "full":
            return sorted(set(tickers) | set(ETF_TICKERS))
        return tickers
    return []


def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    params = V2_PARAMS

    universe = build_universe(args.mode, args.tickers)
    logger.info("Universe: %d tickers  (mode=%s)", len(universe), args.mode)

    must_have        = {params.cash_proxy, "SPY", params.regime_ticker}
    download_tickers = sorted(set(universe) | must_have)

    print(f"\n{'='*65}")
    print(f"Strategy 2.0 — Backtest with SPY 200-Day Regime Filter")
    print(f"  Universe  : {len(universe)} tickers ({args.mode})")
    print(f"  Period    : {args.start} → {args.end}")
    print(f"  Capital   : ${args.initial_capital:,.0f}")
    print(f"  Cash proxy: {params.cash_proxy}")
    print(f"  Regime    : {params.regime_ticker} SMA({params.regime_sma_window})")
    print(f"  Output    : {output_dir.resolve()}")
    print(f"{'='*65}\n")

    adapter = YahooFinanceAdapter()

    t0 = time.time()
    logger.info("Loading price data (%d tickers) …", len(download_tickers))
    panel = load_price_panel(
        download_tickers, adapter,
        start=args.start, end=args.end,
        force_refresh=args.force_download,
    )
    logger.info("Loaded %d tickers in %.1fs", len(panel), time.time() - t0)

    if not panel:
        logger.error("No data loaded — aborting")
        sys.exit(1)

    auxiliary       = {params.cash_proxy, "SPY", params.regime_ticker}
    strategy_tickers = [t for t in universe if t in panel and t not in auxiliary]
    logger.info("Strategy tickers with data: %d / %d", len(strategy_tickers), len(universe))

    t1 = time.time()
    logger.info("Precomputing indicators …")
    strategy_panel = {t: panel[t] for t in strategy_tickers}
    indicators     = precompute_indicators(strategy_panel, params)
    logger.info("Indicators ready in %.1fs", time.time() - t1)

    t2 = time.time()
    logger.info("Running backtest (regime filter: %s) …", params.regime_filter_enabled)
    strategy = StrategyV1(params)   # same signal logic; regime handled by engine
    engine   = BacktestEngine(
        strategy=strategy,
        price_panel=panel,
        indicators=indicators,
        params=params,
        initial_capital=args.initial_capital,
    )
    results = engine.run(args.start, args.end, strategy_tickers)
    logger.info(
        "Backtest done in %.1fs  (%d trading days, %d trades)",
        time.time() - t2, len(results.daily_nav), len(results.trade_log),
    )

    # ── Save results ───────────────────────────────────────────────────────
    spy_raw = panel.get("SPY")
    generate_baseline_report(results, spy_raw, output_dir)

    # ── Save strategy_meta.json for website auto-discovery ─────────────────
    meta = dict(STRATEGY_META)
    meta["backtest_start"] = args.start
    meta["backtest_end"]   = args.end
    meta["initial_capital"] = args.initial_capital
    (output_dir / "strategy_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )
    logger.info("Saved strategy_meta.json → %s", output_dir / "strategy_meta.json")

    # ── Print summary ──────────────────────────────────────────────────────
    print()
    print(results.summary())

    if spy_raw is not None:
        spy_adj   = spy_raw["close"] * spy_raw["adj_factor"]
        spy_ret   = spy_adj.pct_change().reindex(results.daily_nav.index).fillna(0.0)
        spy_nav   = (1 + spy_ret).cumprod()
        n_days    = len(spy_nav)
        spy_cagr  = float(spy_nav.iloc[-1] ** (252 / n_days) - 1) if n_days > 1 else 0.0
        spy_vol   = float(spy_ret.std() * (252 ** 0.5))
        spy_sharpe = (float(spy_ret.mean()) * 252 - 0.05) / spy_vol if spy_vol > 0 else 0.0

        m = results.compute_metrics()
        print(f"\n{'='*55}")
        print(f"  对比 SPY (benchmark)")
        print(f"{'='*55}")
        print(f"  {'指标':<20} {'Strategy 2.0':>12} {'SPY':>12}")
        print(f"  {'-'*44}")
        print(f"  {'CAGR':<20} {m['cagr']:>+11.2%} {spy_cagr:>+11.2%}")
        print(f"  {'Annual Vol':<20} {m['annual_vol']:>11.2%} {spy_vol:>11.2%}")
        print(f"  {'Sharpe':<20} {m['sharpe']:>12.3f} {spy_sharpe:>12.3f}")
        print(f"  {'Max Drawdown':<20} {m['max_drawdown']:>11.2%}")
        print(f"{'='*55}")

    total = time.time() - t0
    print(f"\n✓ 完成。总耗时 {total:.1f}s")
    print(f"  输出目录: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
