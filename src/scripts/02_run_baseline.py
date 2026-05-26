"""
Script: run the Strategy 1.0 baseline backtest and generate a full report.

Usage examples:
    # Fast: ETFs only (~21 tickers, uses cache)
    python src/scripts/02_run_baseline.py --mode etf

    # Full: S&P 500 + ETFs (first run takes 30-60 min to download)
    python src/scripts/02_run_baseline.py --mode full --start 2010-01-01

    # Custom date range and output directory
    python src/scripts/02_run_baseline.py \\
        --mode etf \\
        --start 2015-01-01 \\
        --end   2024-12-31 \\
        --initial-capital 10000000 \\
        --output results/baseline/

⚠  Yahoo Finance data limitations (apply to all results from this script):
    1. Survivorship bias: no delisted stocks → results may be 20-50% too high.
    2. Market cap not point-in-time: current cap used as proxy for historical.
    3. ETF inception dates not enforced: ETFs may appear before they existed.
    These biases disappear automatically when switching to a commercial adapter.
"""

import argparse
import datetime
import json
import logging
import sys
import time
from pathlib import Path

# Allow running from project root: python src/scripts/02_run_baseline.py
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

# ── Baseline anchor parameters (design spec Section 1.2.1.1) ──────────────
# SHY used as cash proxy because it covers the full backtest period (2002+).
# SGOV only has data from 2022, which would leave pre-2022 cash earning 0%.
BASELINE_PARAMS = StrategyParams(
    min_price           = 10.0,
    min_market_cap_b    = 2.0,
    min_adv_m           = 20.0,
    breakout_window     = 200,
    atr_period          = 20,
    stop_loss_multiplier    = 2.0,
    min_stop_distance_pct   = 0.005,
    trail_multiplier_r1 = 3.0,
    trail_multiplier_r3 = 3.0,
    trail_multiplier_r5 = 5.0,
    risk_per_trade      = 0.01,
    position_cap        = 0.05,
    heat_limit          = 0.10,
    correlation_window      = 60,
    correlation_threshold   = 0.70,
    correlation_reduction   = 0.50,
    volume_filter_multiplier = 1.5,    # breakout vol must exceed 1.5× 60d avg volume
    gap_filter          = 0.025,
    commission_bps      = 3.0,
    slippage_bps        = 10.0,
    cash_proxy          = "SHY",       # 1-3Y Treasury ETF; covers full backtest period 2002+
    regime_filter_enabled = True,      # SPY 200-day SMA filter: no new entries in bear market
    regime_ticker         = "SPY",
    regime_sma_window     = 200,
)

DEFAULT_START = "2004-01-01"
DEFAULT_END   = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


# ── Argument parsing ───────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run Strategy 1.0 baseline backtest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--mode",
        choices=["etf", "sp500", "sp900", "full"],
        default="full",
        help=(
            "Universe: "
            "etf=ETFs only from ETFs.csv (fast sanity check), "
            "sp500=S&P500 large-caps only, "
            "sp900=S&P500+MidCap400 ~900 tickers, "
            "full=sp900+all ETFs from ETFs.csv [default, matches strategy spec]"
        ),
    )
    p.add_argument("--tickers", nargs="+", metavar="T",
                   help="Override --mode with an explicit ticker list")
    p.add_argument("--start",           default=DEFAULT_START, help="Start date YYYY-MM-DD")
    p.add_argument("--end",             default=DEFAULT_END,   help="End date YYYY-MM-DD")
    p.add_argument("--initial-capital", default=10_000_000, type=float,
                   help="Initial portfolio value in USD (default: $10,000,000)")
    p.add_argument("--output",          default="results/v1/",
                   help="Output directory (default: results/v1/)")
    p.add_argument("--force-download",  action="store_true",
                   help="Re-download all data even if cache exists")
    p.add_argument("--cash-proxy",      default=None,
                   help="Override cash proxy ticker (default: SHY)")
    p.add_argument("-v", "--verbose",   action="store_true",
                   help="Show debug-level logs")
    return p.parse_args()


# ── Universe building ──────────────────────────────────────────────────────

def build_universe(mode: str, custom_tickers: list[str] | None) -> list[str]:
    if custom_tickers:
        return [t.upper() for t in custom_tickers]

    if mode == "etf":
        return sorted(ETF_TICKERS)

    if mode == "sp500":
        sp500 = fetch_sp500_tickers()
        if not sp500:
            logger.error("Failed to fetch S&P 500 tickers; aborting")
            sys.exit(1)
        return sp500

    if mode == "sp900":
        # Recommended: S&P 500 (large-cap) + MidCap 400 ≈ 900 tickers
        # Covers market cap ~$2B and above, matching the strategy's $20亿 requirement.
        # Mid-caps are excluded from sp500 mode but often the best trend-following targets.
        sp900 = fetch_sp900_tickers()
        if not sp900:
            logger.error("Failed to fetch S&P 900 tickers; aborting")
            sys.exit(1)
        return sp900

    # full: sp900 + ETFs
    sp900 = fetch_sp900_tickers()
    if not sp900:
        logger.error("Failed to fetch tickers; aborting")
        sys.exit(1)
    return sorted(set(sp900) | set(ETF_TICKERS))


# ── Strategy metadata ──────────────────────────────────────────────────────

def _update_strategy_meta(
    output_dir: Path,
    params: "StrategyParams",
    start: str,
    end: str,
    initial_capital: float,
    n_strategy_stocks: int,
    n_strategy_etfs: int,
) -> None:
    """
    Write / update strategy_meta.json in output_dir.

    Preserves etf_universe (names + categories) from any existing file so the
    website's universe page keeps its rich display.  Updates all run-time fields.
    """
    meta_path = output_dir / "strategy_meta.json"

    # Preserve rich fields (etf_universe, colors, …) from an existing file
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
    else:
        meta = {
            "id": "v1", "version": "1.0",
            "display_name": "Strategy 1.0",
            "subtitle": "Trend Following — Long Only, ATR Breakout + Regime Filter",
            "color": "#1f77b4", "badge_text": "v1.0", "badge_color": "blue",
            "differs_from_previous": None,
            "etf_universe": [],
        }

    # ── Runtime-derived fields ────────────────────────────────────────────────
    meta["backtest_start"]   = start
    meta["backtest_end"]     = end
    meta["initial_capital"]  = initial_capital
    meta["cash_proxy"]       = params.cash_proxy
    meta["universe_stocks"]  = n_strategy_stocks
    meta["universe_etfs"]    = n_strategy_etfs
    meta["universe_total"]   = n_strategy_stocks + n_strategy_etfs

    # ── Params anchor ─────────────────────────────────────────────────────────
    meta["params_anchor"] = {
        "breakout_window":           params.breakout_window,
        "atr_period":                params.atr_period,
        "stop_loss_multiplier":      params.stop_loss_multiplier,
        "min_stop_distance_pct":     params.min_stop_distance_pct,
        "trail_multiplier_r1":       params.trail_multiplier_r1,
        "trail_multiplier_r3":       params.trail_multiplier_r3,
        "trail_multiplier_r5":       params.trail_multiplier_r5,
        "risk_per_trade":            params.risk_per_trade,
        "position_cap":              params.position_cap,
        "heat_limit":                params.heat_limit,
        "correlation_window":        params.correlation_window,
        "correlation_threshold":     params.correlation_threshold,
        "correlation_reduction":     params.correlation_reduction,
        "volume_filter_multiplier":  params.volume_filter_multiplier,
        "gap_filter":                params.gap_filter,
        "commission_bps":            params.commission_bps,
        "slippage_bps":              params.slippage_bps,
        "regime_filter_enabled":     params.regime_filter_enabled,
        "regime_ticker":             params.regime_ticker,
        "regime_sma_window":         params.regime_sma_window,
    }

    # ── Human-readable descriptions ───────────────────────────────────────────
    p = params
    vol_feat = (
        f"成交量确认：突破日成交量 > {p.volume_filter_multiplier:.1f}× 60日均量，排除低成交量假突破"
        if p.volume_filter_multiplier > 0 else "无成交量确认过滤"
    )
    if p.regime_filter_enabled:
        meta["subtitle"] = "Trend Following — Long Only, ATR Breakout + SPY 200-Day Regime Filter"
        meta["key_features"] = [
            f"{p.breakout_window}日高点突破入场（N-Day Breakout，N={p.breakout_window}）",
            f"ATR({p.atr_period}) Wilder平滑，固定止损 {p.stop_loss_multiplier:.0f}×ATR",
            f"分段追踪止损：<1R用{p.trail_multiplier_r1:.0f}×ATR，1-3R用{p.trail_multiplier_r3:.0f}×ATR，>3R用{p.trail_multiplier_r5:.0f}×ATR",
            vol_feat,
            f"1% NAV 风险仓位计算（4步过滤）",
            f"相关性过滤：持仓相关性 > {p.correlation_threshold:.2f} 时减半仓",
            f"组合热度上限 {p.heat_limit*100:.0f}%（总风险敞口 ≤ NAV 的 {p.heat_limit*100:.0f}%）",
            f"{p.regime_ticker} {p.regime_sma_window}日均线市场环境过滤：熊市停止开仓，现金投入 {p.cash_proxy}",
            f"空仓资金投入 {p.cash_proxy}（1-3年期国债 ETF，覆盖完整回测期 2002+）",
        ]
        regime_desc = (
            f"启用——{p.regime_ticker} adj-close[t] > SMA({p.regime_sma_window})[t] "
            f"为牛市（允许开仓），否则为熊市（停止新建仓，追踪止损继续运行，"
            f"闲置现金投入 {p.cash_proxy}）"
        )
    else:
        meta["subtitle"] = "Trend Following — Long Only, ATR Breakout"
        meta["key_features"] = [
            f"100日高点突破入场（N-Day Breakout，N={p.breakout_window}）",
            f"ATR({p.atr_period}) Wilder平滑，固定止损 {p.stop_loss_multiplier:.0f}×ATR",
            f"分段追踪止损：<1R用{p.trail_multiplier_r1:.0f}×ATR，1-3R用{p.trail_multiplier_r3:.0f}×ATR，>3R用{p.trail_multiplier_r5:.0f}×ATR",
            "1% NAV 风险仓位计算（4步过滤）",
            f"相关性过滤：持仓相关性 > {p.correlation_threshold:.2f} 时减半仓",
            f"组合热度上限 {p.heat_limit*100:.0f}%（总风险敞口 ≤ NAV 的 {p.heat_limit*100:.0f}%）",
            f"空仓资金投入 {p.cash_proxy}（1-3年期国债 ETF，覆盖完整回测期 2002+）",
            "无市场环境过滤器（纯多头，全程持仓机会均等）",
        ]
        regime_desc = "不启用——Strategy 1.0 原版为纯多头策略，无市场环境过滤器"

    meta.setdefault("logic_sections", {})
    meta["logic_sections"].update({
        "entry":  f"close[t] > max(high[t-{p.breakout_window}:t-1])，使用shift(1)防前视偏差，次日开盘执行",
        "regime": regime_desc,
        "stop":   f"entry_price - {p.stop_loss_multiplier:.0f} × ATR({p.atr_period})，入场价与止损价之差定义为 1R",
        "trail":  f"棘轮式追踪止损：<1R用{p.trail_multiplier_r1:.0f}×ATR，1-3R用{p.trail_multiplier_r3:.0f}×ATR，≥3R用{p.trail_multiplier_r5:.0f}×ATR；只能上移不能下移",
        "sizing": f"Step1目标风险({p.risk_per_trade*100:.0f}%NAV)→Step2单标的上限({p.position_cap*100:.0f}%NAV)→Step3相关性调整→Step4热度检查({p.heat_limit*100:.0f}%)",
        "direction": "纯多头（Long Only）",
        "execution": f"t日收盘生成信号，t+1日开盘价执行；滑点{p.slippage_bps:.0f}bps，佣金{p.commission_bps:.0f}bps，Gap过滤±{p.gap_filter*100:.1f}%",
    })

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    logger.info("strategy_meta.json updated → %s", meta_path)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    params = BASELINE_PARAMS
    if args.cash_proxy:
        from dataclasses import replace
        params = replace(params, cash_proxy=args.cash_proxy.upper())

    # ── Step 1: build universe ─────────────────────────────────────────────
    universe = build_universe(args.mode, args.tickers)
    logger.info("Universe: %d tickers  (mode=%s)", len(universe), args.mode)

    # Always download benchmark (SPY) and cash proxy (SHY/SGOV) even if not in universe
    must_have = {params.cash_proxy, "SPY"}
    download_tickers = sorted(set(universe) | must_have)

    # ── Step 2: download / load data ──────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Strategy 1.0 — Baseline Backtest")
    print(f"  Universe  : {len(universe)} tickers ({args.mode})")
    print(f"  Period    : {args.start} → {args.end}")
    print(f"  Capital   : ${args.initial_capital:,.0f}")
    print(f"  Cash proxy: {params.cash_proxy}")
    print(f"  Output    : {output_dir.resolve()}")
    print(f"{'='*60}\n")

    adapter = YahooFinanceAdapter()

    t0 = time.time()
    logger.info("Loading price data (%d tickers) …", len(download_tickers))
    panel = load_price_panel(
        download_tickers, adapter,
        start=args.start, end=args.end,
        force_refresh=args.force_download,
    )
    logger.info("Loaded %d tickers in %.1fs", len(panel), time.time() - t0)

    if len(panel) == 0:
        logger.error("No data loaded — check network connection and date range")
        sys.exit(1)

    # Tickers available for strategy (exclude SPY and cash proxy)
    auxiliary = {params.cash_proxy, "SPY"}
    strategy_tickers = [t for t in universe if t in panel and t not in auxiliary]
    if not strategy_tickers:
        logger.error("No strategy tickers with data — aborting")
        sys.exit(1)

    logger.info(
        "Strategy tickers with data: %d / %d",
        len(strategy_tickers), len(universe),
    )

    # ── Step 3: precompute indicators ─────────────────────────────────────
    t1 = time.time()
    logger.info("Precomputing indicators …")
    strategy_panel = {t: panel[t] for t in strategy_tickers}
    indicators = precompute_indicators(strategy_panel, params)
    logger.info(
        "Indicators computed for %d tickers in %.1fs",
        len(indicators), time.time() - t1,
    )

    # ── Step 4: run backtest ───────────────────────────────────────────────
    t2 = time.time()
    logger.info("Running backtest …")
    strategy = StrategyV1(params)
    engine   = BacktestEngine(
        strategy=strategy,
        price_panel=panel,           # full panel including SPY + cash proxy
        indicators=indicators,
        params=params,
        initial_capital=args.initial_capital,
    )
    results = engine.run(args.start, args.end, strategy_tickers)
    logger.info(
        "Backtest completed in %.1fs  (%d trading days, %d trades)",
        time.time() - t2, len(results.daily_nav), len(results.trade_log),
    )

    # ── Step 5: generate report ───────────────────────────────────────────
    t3 = time.time()
    logger.info("Generating report …")
    spy_raw = panel.get("SPY")
    generate_baseline_report(results, spy_raw, output_dir)
    logger.info("Report saved in %.1fs → %s", time.time() - t3, output_dir.resolve())

    # ── Step 5b: update strategy_meta.json ───────────────────────────────
    etf_set = set(ETF_TICKERS)
    n_strategy_etfs   = len([t for t in strategy_tickers if t in etf_set])
    n_strategy_stocks = len(strategy_tickers) - n_strategy_etfs
    _update_strategy_meta(
        output_dir=output_dir,
        params=params,
        start=args.start,
        end=args.end,
        initial_capital=args.initial_capital,
        n_strategy_stocks=n_strategy_stocks,
        n_strategy_etfs=n_strategy_etfs,
    )

    # ── Step 6: print summary ─────────────────────────────────────────────
    print()
    print(results.summary())

    # SPY comparison side-by-side
    if spy_raw is not None:
        spy_adj = spy_raw["close"] * spy_raw["adj_factor"]
        spy_ret = spy_adj.pct_change().reindex(results.daily_nav.index).fillna(0.0)
        spy_nav = (1 + spy_ret).cumprod()
        n_days  = len(spy_nav)
        spy_cagr  = float(spy_nav.iloc[-1] ** (252 / n_days) - 1) if n_days > 1 else 0.0
        spy_vol   = float(spy_ret.std() * (252 ** 0.5))
        spy_sharpe = (float(spy_ret.mean()) * 252 - 0.02) / spy_vol if spy_vol > 0 else 0.0

        m = results.compute_metrics()
        print(f"\n{'='*55}")
        print(f"  对比 SPY (benchmark)")
        print(f"{'='*55}")
        print(f"  {'指标':<20} {'Strategy':>12} {'SPY':>12}")
        print(f"  {'-'*44}")
        print(f"  {'CAGR':<20} {m['cagr']:>+11.2%} {spy_cagr:>+11.2%}")
        print(f"  {'Annual Vol':<20} {m['annual_vol']:>11.2%} {spy_vol:>11.2%}")
        print(f"  {'Sharpe':<20} {m['sharpe']:>12.3f} {spy_sharpe:>12.3f}")
        print(f"  {'Max Drawdown':<20} {m['max_drawdown']:>11.2%}")
        print(f"{'='*55}")

    total = time.time() - t0
    print(f"\n✓ 完成。总耗时 {total:.1f}s")
    print(f"  输出目录: {output_dir.resolve()}")
    print(f"  文件列表: {[f.name for f in sorted(output_dir.iterdir())]}")


if __name__ == "__main__":
    main()
