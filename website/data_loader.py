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
    regime_stats: dict = field(default_factory=dict)

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
        if path.is_dir() and meta_file.exists() and "backup" not in path.name.lower():
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
    """Load actual SPY daily NAV, normalised to 1.0 on the strategy start date."""
    # Priority 1: pre-exported CSV alongside results (works on Streamlit Cloud)
    spy_csv = results_dir / "spy_nav.csv"
    if spy_csv.exists():
        try:
            s = pd.read_csv(spy_csv, index_col=0, parse_dates=True).squeeze()
            s = s.reindex(nav.index).ffill().bfill()
            return s / float(s.iloc[0])
        except Exception:
            pass

    # Priority 2: local parquet cache (dev machine) — prefer Tiingo (longer history)
    _root = Path(__file__).resolve().parents[1]
    for spy_cache in [
        _root / "data" / "cache" / "tiingo" / "SPY.parquet",
        _root / "data" / "cache" / "prices" / "SPY.parquet",
    ]:
        if spy_cache.exists():
            try:
                spy_df = pd.read_parquet(spy_cache)
                adj = spy_df["close"] * spy_df["adj_factor"]
                adj.index = pd.DatetimeIndex(adj.index)
                adj = adj.reindex(nav.index).ffill().bfill()
                spy_ret = adj.pct_change().fillna(0.0)
                spy_nav = (1 + spy_ret).cumprod()
                # Guard: skip if data coverage is poor (>20% of dates missing before bfill)
                raw_coverage = spy_df.index.isin(nav.index).sum() / len(nav)
                if raw_coverage < 0.5:
                    continue
                return spy_nav
            except Exception:
                pass

    # Priority 3: smooth CAGR fallback (no real data available)
    metrics = json.loads((results_dir / "metrics.json").read_text())
    spy_cagr = metrics.get("spy_cagr")
    if spy_cagr is None:
        return None
    daily_r = (1 + spy_cagr) ** (1 / 252) - 1
    return pd.Series((1 + daily_r) ** np.arange(len(nav)), index=nav.index)


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
