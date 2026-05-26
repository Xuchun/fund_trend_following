"""
Data loader: auto-discovers strategy versions from results/ directory.
Adding Strategy 2.0 requires only placing results in results/v2/ — no code changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results"


@dataclass
class StrategyMeta:
    id: str
    version: str
    display_name: str
    subtitle: str
    color: str
    badge_text: str
    badge_color: str
    universe_stocks: int
    universe_etfs: int
    universe_total: int
    backtest_start: str
    backtest_end: str
    initial_capital: float
    cash_proxy: str
    key_features: list[str]
    differs_from_previous: Optional[dict]
    params_anchor: dict
    logic_sections: dict
    etf_universe: list[dict] = field(default_factory=list)

    @property
    def results_dir(self) -> Path:
        return RESULTS_ROOT / self.id


@dataclass
class StrategyResults:
    meta: StrategyMeta
    nav: pd.Series          # index=date, values=nav
    returns: pd.Series      # daily returns
    trades: pd.DataFrame
    metrics: dict
    spy_nav: Optional[pd.Series] = None   # SPY normalised to 1.0 on same start


def list_strategies() -> list[StrategyMeta]:
    """Auto-discover all results/{id}/strategy_meta.json directories."""
    metas = []
    if not RESULTS_ROOT.exists():
        return metas
    for path in sorted(RESULTS_ROOT.iterdir()):
        meta_file = path / "strategy_meta.json"
        if path.is_dir() and meta_file.exists():
            try:
                metas.append(_load_meta(meta_file))
            except Exception:
                pass
    return metas


def load_strategy(strategy_id: str) -> StrategyResults:
    results_dir = RESULTS_ROOT / strategy_id
    meta = _load_meta(results_dir / "strategy_meta.json")

    nav_df = pd.read_csv(results_dir / "nav.csv", index_col="date", parse_dates=True)
    nav    = nav_df["nav"].rename("nav")
    rets   = nav_df["return"].rename("return")

    trades  = pd.read_csv(results_dir / "trades.csv",
                          parse_dates=["entry_date", "exit_date"])
    metrics = json.loads((results_dir / "metrics.json").read_text())

    spy_nav = _compute_spy_nav(nav, results_dir)

    return StrategyResults(meta=meta, nav=nav, returns=rets,
                           trades=trades, metrics=metrics, spy_nav=spy_nav)


# ── helpers ────────────────────────────────────────────────────────────────

def _load_meta(path: Path) -> StrategyMeta:
    d = json.loads(path.read_text())
    return StrategyMeta(**d)


def _compute_spy_nav(nav: pd.Series, results_dir: Path) -> Optional[pd.Series]:
    """Re-derive SPY normalised NAV from metrics.json spy_cagr if available."""
    metrics = json.loads((results_dir / "metrics.json").read_text())
    spy_cagr = metrics.get("spy_cagr")
    if spy_cagr is None:
        return None
    n = len(nav)
    # Reconstruct a smooth SPY curve from CAGR (approximation for display)
    # Actual daily SPY data isn't stored, so we use the real cached price data if available
    spy_cache = Path(__file__).resolve().parents[1] / "data" / "cache" / "prices" / "SPY.parquet"
    if spy_cache.exists():
        try:
            spy_df = pd.read_parquet(spy_cache)
            adj = spy_df["close"] * spy_df["adj_factor"]
            adj = adj.reindex(nav.index).ffill().bfill()
            spy_ret = adj.pct_change().fillna(0.0)
            spy_nav = (1 + spy_ret).cumprod()
            return spy_nav
        except Exception:
            pass
    # Fallback: smooth CAGR line
    daily_r = (1 + spy_cagr) ** (1 / 252) - 1
    spy_nav = pd.Series(
        (1 + daily_r) ** np.arange(n),
        index=nav.index,
    )
    return spy_nav


def compute_rolling_sharpe(returns: pd.Series, window: int = 252,
                            rf_annual: float = 0.02) -> pd.Series:
    rf_daily = (1 + rf_annual) ** (1 / 252) - 1
    excess   = returns - rf_daily
    rs = excess.rolling(window).apply(
        lambda x: (x.mean() * 252) / (x.std() * np.sqrt(252)) if x.std() > 0 else np.nan,
        raw=True,
    )
    return rs


def compute_drawdown(nav: pd.Series) -> pd.Series:
    peak = nav.cummax()
    return (nav - peak) / peak * 100


def compute_annual_returns(nav: pd.Series) -> pd.DataFrame:
    annual = nav.resample("YE").last().pct_change()
    annual.index = annual.index.year
    annual.name  = "return"
    return annual.dropna().reset_index().rename(columns={"date": "year"})
