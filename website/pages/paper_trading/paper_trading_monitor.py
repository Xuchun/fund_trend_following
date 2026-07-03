"""策略1.0模拟交易监控"""

import sys, json
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.style import show_df
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from src.strategy.params import StrategyParams as _StrategyParams
from src.indicators.atr import compute_atr as _compute_atr

_results  = _root / "results" / "v1_unbiased_60m_2000"
_pt_dir   = _root / "results" / "paper_trading"
_m1_file  = _pt_dir / "positions.json"
_m2_file  = _pt_dir / "ib_state.json"

_meta_path = _results / "strategy_meta.json"
_ETF_SET: set = set()
if _meta_path.exists():
    _ETF_SET = {e["ticker"] for e in json.loads(_meta_path.read_text()).get("etf_universe", [])}

_bt_metrics: dict = {}
_bt_metrics_path = _results / "metrics.json"
if _bt_metrics_path.exists():
    try:
        _bt_metrics = json.loads(_bt_metrics_path.read_text())
    except Exception:
        pass

def _asset_type(ticker: str) -> str:
    return "ETF" if ticker in _ETF_SET else "股票"

# Read all display-critical parameters from StrategyParams — the single source of truth
# used by both the backtest engine and the paper trading daily script.
_V1_PARAMS  = _StrategyParams()
_TRAIL_R1   = _V1_PARAMS.trail_multiplier_r1   # 3.0
_TRAIL_R3   = _V1_PARAMS.trail_multiplier_r3   # 3.0
_TRAIL_R5   = _V1_PARAMS.trail_multiplier_r5   # 5.0
_ATR_PERIOD = _V1_PARAMS.atr_period            # 20
_SMA_WINDOW = _V1_PARAMS.regime_sma_window     # 200

st.markdown("""
<style>
@media print {
    [data-testid="stSidebar"],
    [data-testid="stSidebarNav"],
    [data-testid="stHeader"],
    [data-testid="stDecoration"],
    [data-testid="stToolbar"],
    [data-testid="stStatusWidget"],
    header, footer,
    .stApp > header { display: none !important; }
    iframe { display: none !important; }
    .main .block-container,
    [data-testid="stMainBlockContainer"] {
        padding-top: 0.5cm !important;
        padding-left: 1cm !important;
        padding-right: 1cm !important;
        max-width: 100% !important;
    }
    @page { margin: 1.5cm; }
    .stPlotlyChart,
    [data-testid="stDataFrame"],
    [data-testid="stAlert"] { page-break-inside: avoid; }
    h2, h3 { page-break-after: avoid; }
}
</style>
""", unsafe_allow_html=True)

_col_pt_title, _col_pt_right = st.columns([4, 1])
with _col_pt_title:
    st.title("策略1.0 模拟交易监控")
with _col_pt_right:
    st.html("""
    <div style="display:flex;justify-content:flex-end;align-items:center;padding-top:20px;">
        <button id="pt-pdf-btn"
            title="打开打印对话框后选择「存储为 PDF」即可下载"
            style="background:#1565c0;color:#fff;border:none;padding:7px 16px;
                   border-radius:5px;cursor:pointer;font-size:13px;
                   font-family:sans-serif;white-space:nowrap;">
            📄 下载 PDF
        </button>
    </div>
    <script>
    (function() {
        var btn = document.getElementById('pt-pdf-btn');
        if (btn) btn.onclick = function() { window.print(); };
    })();
    </script>
    """, unsafe_allow_javascript=True)
st.markdown("同时运行两种模拟交易方法，互相验证信号与执行质量")

# ── 数据完整性警告（在 tabs 之前，确保渲染在页面最顶部）──────────────────────
if _m1_file.exists():
    _warn_data        = json.loads(_m1_file.read_text())
    _warn_err_log     = _warn_data.get("data_error_log", [])
    _warn_univ        = _warn_data.get("universe_size", 0)
    _warn_pending     = _warn_data.get("pending_retry", {})
    _warn_pending_tks = _warn_pending.get("tickers", [])

    if _warn_err_log or _warn_pending_tks:
        _warn_lines = []

        # ① 历史已知失败（data_error_log）
        for _wlog in _warn_err_log:
            _wlog_tks  = _wlog.get("tickers_missed", [])
            _wlog_date = _wlog.get("date", "")
            # last_attempt_sgt: 用 pending_retry.created_utc 转换，若无则只显示日期
            _wlog_last = _wlog_date  # fallback
            _wlog_created = _wlog.get("created_utc", "")
            if _wlog_created:
                try:
                    import datetime as _dt
                    _utc = _dt.datetime.fromisoformat(_wlog_created.replace("Z", "+00:00"))
                    _sgt = _utc + _dt.timedelta(hours=8)
                    _wlog_last = _sgt.strftime("%Y-%m-%d %H:%M 新加坡时间（SGT）")
                except Exception:
                    pass
            _wlog_dl    = _wlog.get("downloaded_count")
            _wlog_total = _wlog.get("total_scanned")
            _wlog_line  = (
                f"- 数据下载失败标的：**{'、'.join(_wlog_tks)}**。"
                f"最后尝试下载时间：**{_wlog_last}**。"
            )
            if _wlog_dl is not None and _wlog_total:
                _wlog_line += f"本次成功下载 **{_wlog_dl:,}** 个，标的池共 **{_wlog_total:,}** 个。"
            _warn_lines.append(_wlog_line)

        # ② 当前等待自动重试（pending_retry）
        if _warn_pending_tks:
            _pr_sgt     = _warn_pending.get("next_retry_sgt", "")
            _pr_attempt = _warn_pending.get("attempt", 1)
            # 优先用 last_attempt_utc（最近一次实际运行时间），回退到 created_utc
            _pr_last_raw = _warn_pending.get("last_attempt_utc") or _warn_pending.get("created_utc", "")
            _pr_last     = _warn_pending.get("scan_date", "")
            if _pr_last_raw:
                try:
                    import datetime as _dt2
                    _utc2 = _dt2.datetime.fromisoformat(_pr_last_raw.replace("Z", "+00:00"))
                    _sgt2 = _utc2 + _dt2.timedelta(hours=8)
                    _pr_last = _sgt2.strftime("%Y-%m-%d %H:%M 新加坡时间（SGT）")
                except Exception:
                    pass
            _pr_dl    = _warn_pending.get("downloaded_count")
            _pr_total = _warn_pending.get("total_scanned")
            _pr_line  = (
                f"- **⏳ 第 {_pr_attempt} 次自动重试等待中**：**{'、'.join(_warn_pending_tks)}** "
                f"数据仍未下载成功。最后尝试下载时间：**{_pr_last}**。"
            )
            if _pr_dl is not None and _pr_total:
                _pr_line += f"本次成功下载 **{_pr_dl:,}** 个，标的池共 **{_pr_total:,}** 个。"
            _pr_line += f"系统将于 **{_pr_sgt}** 自动重试，成功后此提示消失。"
            _warn_lines.append(_pr_line)

        # 计算下次重下时间：pending_retry 有则用其精确时间，否则用下一个交易日自动运行时间
        if _warn_pending_tks:
            _next_retry_str = f"下次自动重试：**{_warn_pending.get('next_retry_sgt', '待定')}**。"
        else:
            _next_run_day = (
                pd.Timestamp.now(tz="Asia/Singapore").normalize().tz_localize(None)
                + pd.tseries.offsets.BDay(1)
            )
            _next_run_sgt = _next_run_day.strftime("%Y-%m-%d（%A）早上 07:00 新加坡时间（SGT）")
            _next_retry_str = f"下次自动重新下载全量标的数据的时间：**{_next_run_sgt}**。"

        st.error(
            "**⚠️ 数据完整性警告：Yahoo Finance 限速导致部分标的漏评**\n\n"
            + "\n\n".join(_warn_lines)
            + "\n\n**自动重试机制**：一旦检测到标的数据下载失败，系统每隔 **1 小时**自动重新"
            f"尝试下载，直到成功为止，无需人工干预。{_next_retry_str}"
        )

tab1, tab2 = st.tabs(["📊 方法一：手动跟踪（Yahoo Finance）", "🤖 方法二：IB 自动交易（Interactive Brokers）"])

# ═══════════════════════════════════════════════════════════════════════════════
# ── Shared helpers ─────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _build_method_zip(data: dict, method: str) -> bytes:
    import zipfile, io, csv
    from datetime import date as _d

    def _rows_to_csv(rows: list, fieldnames: list) -> bytes:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue().encode("utf-8-sig")

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{method}_raw.json",
                    json.dumps(data, ensure_ascii=False, indent=2))

        nav_h = data.get("nav_history", [])
        if nav_h:
            zf.writestr(f"{method}_nav_history.csv",
                _rows_to_csv(nav_h, ["date", "nav", "regime", "spy_close"]))

        sh = data.get("signals_history", [])
        if sh:
            zf.writestr(f"{method}_signals_history.csv",
                _rows_to_csv(sh, [
                    "date", "regime", "spy_close",
                    "n_raw_breakouts",              # raw breakouts before portfolio constraints
                    "n_candidates",                 # passed all portfolio constraints (approved)
                    "n_heat_blocked", "n_cash_blocked", "n_corr_reduced",
                    "n_entries", "n_executed", "n_exits",
                ]))

        # Full breakout candidate list for EVERY historical day (all stored in signals_history).
        # Each row is one ticker on one day: includes rejection reason, strength, and sizing.
        # Supersedes the old today-only export; enables per-day funnel analysis over time.
        _all_cands: list[dict] = []
        for _sh_rec in data.get("signals_history", []):
            _sh_date = _sh_rec.get("date", "")
            for _c in _sh_rec.get("candidate_signals", []):
                _all_cands.append({"date": _sh_date, **_c})
        if _all_cands:
            zf.writestr(f"{method}_all_candidate_signals.csv",
                _rows_to_csv(_all_cands, [
                    "date", "ticker", "signal_price", "stop_price", "shares",
                    "trade_risk", "strength", "rejection", "corr_with",
                ]))

        # Historical per-day entry signals with breakout strength
        # Built from signals_history[].entry_signals (approved signals each day, pending T+1 execution).
        _daily_entries = []
        for _sh in data.get("signals_history", []):
            _d = _sh.get("date", "")
            for _e in _sh.get("entry_signals", []):
                _daily_entries.append({
                    "date":         _d,
                    "ticker":       _e.get("ticker", ""),
                    "strength":     _e.get("strength"),
                    "signal_price": _e.get("signal_price"),
                    "stop_price":   _e.get("stop_price"),
                    "shares":       _e.get("shares"),
                    "trade_risk":   _e.get("trade_risk"),
                })
        if _daily_entries:
            zf.writestr(f"{method}_daily_entry_signals.csv",
                _rows_to_csv(_daily_entries, [
                    "date", "ticker", "strength", "signal_price",
                    "stop_price", "shares", "trade_risk",
                ]))

        ct = data.get("closed_trades", [])
        if ct:
            zf.writestr(f"{method}_closed_trades.csv",
                _rows_to_csv(ct, list(ct[0].keys())))

        op = [p for p in data.get("positions", []) if not p.get("closed")]
        if op:
            zf.writestr(f"{method}_open_positions.csv",
                _rows_to_csv(op, list(op[0].keys())))

        # 开仓历史：持仓中 + 已平仓的开仓数据合并（closed trades now carry signal_price & atr_at_entry）
        _entry_hist = sorted([
            {"ticker": p["ticker"],
             "signal_date": p.get("signal_date", ""), "signal_price": p.get("signal_price", ""),
             "entry_date": p["entry_date"], "open_price": p.get("open_price", ""), "entry_price": p["entry_price"],
             "shares": p["shares"], "stop_loss": p.get("stop_loss", ""),
             "atr_at_entry": p.get("atr_at_entry"), "status": "open"}
            for p in op
        ] + [
            {"ticker": c["ticker"],
             "signal_date": c.get("signal_date", ""), "signal_price": c.get("signal_price", ""),
             "entry_date": c.get("entry_date", ""), "entry_price": c.get("entry_price", ""),
             "shares": c.get("shares", ""), "stop_loss": c.get("stop_loss", c.get("initial_stop", "")),
             "open_price": c.get("open_price", ""), "atr_at_entry": c.get("atr_at_entry"),
             "status": "closed"}
            for c in ct
        ], key=lambda x: x["entry_date"], reverse=True)
        if _entry_hist:
            zf.writestr(f"{method}_entry_history.csv",
                _rows_to_csv(_entry_hist,
                    ["ticker","signal_date","signal_price","entry_date","open_price","entry_price",
                     "shares","stop_loss","atr_at_entry","status"]))

        # ── 回测参考数据（用于过拟合分析：以回测分布为基准，比较模拟交易表现）──────────
        for _bt_fname in ("metrics.json", "trades.csv", "nav.csv"):
            _bt_path = _results / _bt_fname
            if _bt_path.exists():
                zf.writestr(f"backtest_reference_{_bt_fname}", _bt_path.read_bytes())

    return zbuf.getvalue()

_YF_FETCH_FILE = Path(__file__).resolve().parents[3] / "results" / "paper_trading" / "last_yf_fetch.json"

@st.cache_data(ttl=3600)
def _fetch_yf(tickers: tuple, period: str = "300d", day: str = ""):
    """Returns (DataFrame, fetch_time_sgt_str). Both are cached together for 1 hour.
    Also persists the fetch timestamp to last_yf_fetch.json so it survives page reloads."""
    from datetime import datetime, timezone, timedelta
    import yfinance as yf
    _sgt = timezone(timedelta(hours=8))
    _fetch_time = datetime.now(_sgt).strftime("%Y-%m-%d %H:%M 新加坡时间（SGT，UTC+8）")
    if not tickers:
        return pd.DataFrame(), _fetch_time
    _df = yf.download(list(tickers), period=period, auto_adjust=True, progress=False)
    # Persist timestamp — this block only runs on a real download (cache miss), not on cache hits
    try:
        _YF_FETCH_FILE.parent.mkdir(parents=True, exist_ok=True)
        _YF_FETCH_FILE.write_text(
            json.dumps({"last_fetch_sgt": _fetch_time}, ensure_ascii=False)
        )
    except Exception:
        pass
    return _df, _fetch_time


@st.cache_data(ttl=3600)
def _fetch_yf_chart_single(ticker: str) -> pd.DataFrame:
    """单股K线图数据拉取，缓存1小时（与批量价格缓存TTL一致）。"""
    import yfinance as yf
    if not ticker:
        return pd.DataFrame()
    tk = yf.Ticker(ticker)

    # 主数据：2年历史（约500根K线）
    df = tk.history(period="2y", auto_adjust=True)

    # 补充最近1天：Yahoo Finance 1d端点使用实时API，确认能返回最新交易日K线
    try:
        _df1d = tk.history(period="1d", auto_adjust=True)
        if not _df1d.empty:
            df = pd.concat([df, _df1d])
            df = df[~df.index.duplicated(keep="last")].sort_index()
    except Exception:
        pass

    if df.empty:
        return pd.DataFrame()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df.sort_index().dropna(subset=["Close"])


@st.cache_data(ttl=86400)
def _fetch_sector_cached(ticker: str) -> str:
    """Fetch sector from Yahoo Finance; raises on failure so cache stays empty."""
    import yfinance as yf
    info = yf.Ticker(ticker).info
    result = info.get("sector") or info.get("quoteType") or ""
    if not result:
        raise ValueError(f"No sector data for {ticker}")
    return result


def _fetch_sector(ticker: str, prefetched: str = "") -> str:
    """返回 ticker 的行业/板块，优先用 positions.json 中预取的值（日程序写入）。"""
    if prefetched and prefetched != "N/A":
        return prefetched
    try:
        return _fetch_sector_cached(ticker)
    except Exception:
        return "N/A"


def _build_kline_fig(kdf, title, x_start, x_end, hlines=None, vlines=None):
    """构建K线图（日本蜡烛图 + 成交量），返回 plotly Figure。

    hlines: list of dict，每项 keys: y, color, dash (默认"dash"), width (默认1.5), label
    vlines: list of dict，每项 keys: x (ISO date str), color, dash, width, text,
            use_domain (True=标注贴价格子图底部，False=标注用paper坐标), y_paper (float)
    """
    from plotly.subplots import make_subplots
    vol_colors = [
        "#2ca02c" if float(kdf["Close"].iloc[i]) >= float(kdf["Open"].iloc[i])
        else "#d62728"
        for i in range(len(kdf))
    ]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, row_heights=[0.75, 0.25])
    fig.add_trace(go.Candlestick(
        x=kdf.index,
        open=kdf["Open"].values, high=kdf["High"].values,
        low=kdf["Low"].values,   close=kdf["Close"].values,
        increasing_line_color="#2ca02c", decreasing_line_color="#d62728",
        increasing_fillcolor="#2ca02c", decreasing_fillcolor="#d62728",
        name="K线", showlegend=False,
    ), row=1, col=1)
    fig.add_trace(go.Bar(
        x=kdf.index, y=kdf["Volume"].values,
        marker_color=vol_colors, showlegend=False,
    ), row=2, col=1)
    # 止损价（红 #d62728）→ 标注在线上方（top left）
    # 移动止盈（橘 #ff7f0e）→ 标注在线下方（bottom left）
    # 两者位于对立方向，贴近各自线条，与蓝色买入价标注距离一致
    # 当红线在下/橘线在上时（少见），方向互换
    _hl_list  = list(hlines or [])
    _RED_C    = "#d62728"
    _ORANGE_C = "#ff7f0e"
    _ri = next((i for i, h in enumerate(_hl_list) if h.get("color") == _RED_C),    None)
    _oi = next((i for i, h in enumerate(_hl_list) if h.get("color") == _ORANGE_C), None)

    _red_pos, _orange_pos = "top left", "bottom left"   # 红上橘下（默认）
    if _ri is not None and _oi is not None:
        if _hl_list[_ri]["y"] < _hl_list[_oi]["y"]:
            _red_pos, _orange_pos = "bottom left", "top left"  # 红下橘上

    for _idx, hl in enumerate(_hl_list):
        if _idx == _ri:
            _pos = _red_pos
        elif _idx == _oi:
            _pos = _orange_pos
        else:
            _pos = "top left"   # 其他线（买入价等）默认在线上方
        fig.add_hline(
            y=hl["y"], row=1, col=1,
            line_color=hl["color"],
            line_dash=hl.get("dash", "dash"),
            line_width=hl.get("width", 1.5),
            annotation_text=hl["label"],
            annotation_position=_pos,
            annotation_font_color=hl["color"],
        )
    for vl in (vlines or []):
        fig.add_vline(
            x=vl["x"],
            line_color=vl["color"],
            line_dash=vl.get("dash", "dash"),
            line_width=vl.get("width", 1.5),
        )
        if vl.get("use_domain"):
            fig.add_annotation(
                x=vl["x"], xref="x",
                y=0, yref="y domain",
                text=vl["text"], showarrow=False,
                font=dict(color=vl["color"], size=11),
                xanchor="right", yanchor="bottom",
                row=1, col=1,
            )
        else:
            fig.add_annotation(
                x=vl["x"], xref="x",
                y=vl.get("y_paper", 0.28), yref="paper",
                text=vl["text"], showarrow=False,
                font=dict(color=vl["color"], size=11),
                xanchor="right", yanchor="bottom",
            )
    fig.update_layout(
        title=title, height=520, template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=20),
        legend=dict(orientation="h", y=1.02, x=0, xanchor="left"),
    )
    fig.update_layout(xaxis_rangeslider_visible=False)
    fig.update_yaxes(title_text="价格 ($)", row=1, col=1, showgrid=True, gridcolor="#eeeeee")
    fig.update_yaxes(title_text="成交量", row=2, col=1, showgrid=True, gridcolor="#eeeeee")
    fig.update_xaxes(showgrid=True, gridcolor="#eeeeee", range=[x_start, x_end])
    return fig


def _us_open_to_sgt(date_str: str) -> str:
    """把交易日（美股开盘 9:30 AM 美东时间）转换为新加坡时间字符串，自动处理夏/冬令时。"""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    try:
        _et  = ZoneInfo("America/New_York")
        _sgt = ZoneInfo("Asia/Singapore")
        _dt_sgt = datetime.strptime(date_str, "%Y-%m-%d") \
                           .replace(hour=9, minute=30, tzinfo=_et) \
                           .astimezone(_sgt)
        return _dt_sgt.strftime("%Y-%m-%d %H:%M SGT")
    except Exception:
        return date_str  # 无法转换时退回纯日期


def _us_close_to_sgt(date_str: str) -> str:
    """把信号日（美股收盘 4:00 PM 美东时间）转换为新加坡时间字符串，自动处理夏/冬令时。
    夏令时：4:00 PM EDT = 次日 04:00 SGT；冬令时：4:00 PM EST = 次日 05:00 SGT。"""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    try:
        _et  = ZoneInfo("America/New_York")
        _sgt = ZoneInfo("Asia/Singapore")
        _dt_sgt = datetime.strptime(date_str, "%Y-%m-%d") \
                           .replace(hour=16, minute=0, tzinfo=_et) \
                           .astimezone(_sgt)
        return _dt_sgt.strftime("%Y-%m-%d %H:%M SGT")
    except Exception:
        return date_str


def _get_df(raw: pd.DataFrame, ticker: str):
    if raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        if ticker not in raw.columns.get_level_values(1):
            return None
        df = raw.xs(ticker, level=1, axis=1).dropna(subset=["Close"])
    else:
        df = raw.dropna(subset=["Close"])
    return df if not df.empty else None


def _enrich_position(pos: dict, raw_yf: pd.DataFrame) -> dict:
    """Add live price + computed trailing/hard stop to a position dict.

    Mirrors backtest dual-stop logic exactly:
      - stop_loss:  fixed hard stop (intraday low trigger)
      - trail_stop: trailing stop that ratchets up (close trigger)
      - R-multiple for trail_mult selection uses highest_high (peak), not current close
      - entry_price is slip-adjusted so R = entry_price - stop_loss = 2×ATR exactly
    """
    df = _get_df(raw_yf, pos["ticker"])

    # Backward-compatibility: migrate old schema fields on the fly
    if "stop_loss" not in pos:
        pos = {**pos, "stop_loss": pos.get("initial_stop_loss", 0.0)}
    if "trail_stop" not in pos:
        pos = {**pos, "trail_stop": pos.get("current_stop_loss", pos["stop_loss"])}
    if "highest_high" not in pos:
        pos = {**pos, "highest_high": pos.get("peak_price", pos["entry_price"])}

    R_base = pos["entry_price"] - pos["stop_loss"]   # = 2×ATR; both slip-adjusted

    def _compute_stop(peak: float, atr: float, stored_trail: float) -> tuple[float, float, float]:
        """Returns (effective_stop, trail_stop_live, trail_mult)."""
        r_mult_peak = (peak - pos["entry_price"]) / R_base if R_base > 0 else 0.0
        tm = _TRAIL_R5 if r_mult_peak >= 3.0 else (_TRAIL_R3 if r_mult_peak >= 1.0 else _TRAIL_R1)
        trail_live = max(stored_trail, peak - tm * atr)
        effective  = max(pos["stop_loss"], trail_live)   # hard stop may be binding early on
        return effective, trail_live, tm

    # Fallback when YF fetch fails — only close price available, no intraday low
    # Hard stop approximated with close (same as trailing stop check); mark stale
    if df is None:
        fallback = pos.get("last_known_price")
        if not fallback:
            return {**pos, "_ok": False}
        peak_hh = pos["highest_high"]
        eff_stop, trail_live, tm = _compute_stop(peak_hh, pos["atr_at_entry"], pos["trail_stop"])
        R = (fallback - pos["entry_price"]) / R_base if R_base > 0 else 0.0
        # Without intraday low, approximate: triggered if close < stop_loss OR close < trail_stop
        if fallback < pos["stop_loss"]:
            stop_reason = "stop_loss"
        elif fallback < trail_live:
            stop_reason = "trailing_stop"
        else:
            stop_reason = None
        return {
            **pos,
            "_ok":             True,
            "_stale":          True,
            "current_price":   fallback,
            "current_date":    pos.get("last_price_date", "N/A"),
            "highest_high":    peak_hh,
            "current_atr":     pos["atr_at_entry"],
            "current_stop":    eff_stop,
            "trail_stop_live": trail_live,
            "trail_mult":      tm,
            "R":               R,
            "mkt_value":       fallback * pos["shares"],
            "unreal_pnl":      (fallback - pos["entry_price"]) * pos["shares"],
            "stop_buffer_pct": (fallback - eff_stop) / fallback * 100,
            "is_stopped":      stop_reason is not None,
            "stop_reason":     stop_reason,
        }

    # Compare dates only to avoid timezone mismatch between yfinance (tz-aware) and entry_date (tz-naive)
    entry_d     = pd.to_datetime(pos["entry_date"]).date()
    since_entry = df[pd.to_datetime(df.index).date >= entry_d] if not df.empty else df
    if since_entry.empty:
        fallback = pos.get("last_known_price")
        if not fallback:
            return {**pos, "_ok": False}
        peak_hh = pos["highest_high"]
        eff_stop, trail_live, tm = _compute_stop(peak_hh, pos["atr_at_entry"], pos["trail_stop"])
        R = (fallback - pos["entry_price"]) / R_base if R_base > 0 else 0.0
        if fallback < pos["stop_loss"]:
            stop_reason = "stop_loss"
        elif fallback < trail_live:
            stop_reason = "trailing_stop"
        else:
            stop_reason = None
        return {
            **pos,
            "_ok":             True,
            "_stale":          True,
            "current_price":   fallback,
            "current_date":    pos.get("last_price_date", "N/A"),
            "highest_high":    peak_hh,
            "current_atr":     pos["atr_at_entry"],
            "current_stop":    eff_stop,
            "trail_stop_live": trail_live,
            "trail_mult":      tm,
            "R":               R,
            "mkt_value":       fallback * pos["shares"],
            "unreal_pnl":      (fallback - pos["entry_price"]) * pos["shares"],
            "stop_buffer_pct": (fallback - eff_stop) / fallback * 100,
            "is_stopped":      stop_reason is not None,
            "stop_reason":     stop_reason,
        }

    cur_price    = float(since_entry["Close"].iloc[-1])
    low_today    = float(since_entry["Low"].iloc[-1])
    cur_date     = str(since_entry.index[-1].date())
    highest_high = max(pos["highest_high"], float(since_entry["High"].max()))

    atr_s   = _compute_atr(df["High"], df["Low"], df["Close"], _ATR_PERIOD)
    cur_atr = float(atr_s.iloc[-1])
    if pd.isna(cur_atr):
        cur_atr = pos["atr_at_entry"]

    eff_stop, trail_live, tm = _compute_stop(highest_high, cur_atr, pos["trail_stop"])

    # Dual-trigger — matches strategy description and backtest exit.py exactly:
    #   Priority 1: hard stop  — intraday low[t] < stop_loss
    #   Priority 2: trail stop — close[t]         < trail_stop
    if low_today < pos["stop_loss"]:
        stop_reason = "stop_loss"
    elif cur_price < trail_live:
        stop_reason = "trailing_stop"
    else:
        stop_reason = None
    is_stopped = stop_reason is not None

    # Display R: unrealized gain in units of initial risk (uses current close, not peak)
    R = (cur_price - pos["entry_price"]) / R_base if R_base > 0 else 0.0

    return {
        **pos,
        "_ok":             True,
        "current_price":   cur_price,
        "current_date":    cur_date,
        "highest_high":    highest_high,
        "current_atr":     cur_atr,
        "current_stop":    eff_stop,
        "trail_stop_live": trail_live,
        "trail_mult":      tm,
        "R":               R,
        "mkt_value":       cur_price * pos["shares"],
        "unreal_pnl":      (cur_price - pos["entry_price"]) * pos["shares"],
        "stop_buffer_pct": (cur_price - eff_stop) / cur_price * 100,
        "is_stopped":      is_stopped,
        "stop_reason":     stop_reason,
    }


@st.cache_data(ttl=86400)
def _load_bt():
    with open(_results / "metrics.json") as f:
        m = json.load(f)
    nav = pd.read_csv(_results / "nav.csv", index_col=0, parse_dates=True)
    spy = pd.read_csv(_results / "spy_nav.csv", index_col=0, parse_dates=True)
    trades = pd.read_csv(_results / "trades.csv", parse_dates=["entry_date", "exit_date"])
    return m, nav, spy, trades


try:
    _bm, _bt_nav, _bt_spy, _bt_trades = _load_bt()
except FileNotFoundError:
    st.error("⚠️ 回测结果文件缺失，无法加载基准数据。请确认 `results/v1_unbiased_60m_2000/` 目录已同步到 GitHub。")
    st.stop()


@st.cache_data(ttl=120)
def _load_m1():
    if _m1_file.exists():
        return json.loads(_m1_file.read_text()), False
    return {
        "initial_nav": 200000.0, "cash": 200000.0,
        "positions": [], "closed_trades": [],
        "nav_history": [{"date": "2026-06-19", "nav": 200000.0}],
        "last_update_date": "尚未运行",
    }, True


@st.cache_data(ttl=120)
def _load_m2():
    if _m2_file.exists():
        return json.loads(_m2_file.read_text())
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — 方法一：手动跟踪（Yahoo Finance）
# ═══════════════════════════════════════════════════════════════════════════════

with tab1:
    st.markdown("""
    **运行方式：** 由 **GitHub Actions 自动运行**，每个交易日美东时间收盘后自动触发（夏令时 7:00 PM / 冬令时 6:00 PM，即新加坡时间次日早上 **7:00 AM**），
    无需任何手动操作。运行结果自动推送到 GitHub，本页面随即刷新。
    """)

    with st.expander("⚙️ 自动化配置说明"):
        st.markdown("""
**GitHub Actions 自动运行**（无需任何手动操作）

- 工作流文件：`.github/workflows/paper_trading_m1.yml`
- 触发时间：每个交易日 **夏令时 7:00 PM / 冬令时 6:00 PM**（23:00 UTC）自动运行，确保 Yahoo Finance 收盘数据已就绪
- 运行内容：下载 Yahoo Finance 数据 → 计算信号 → 更新 positions.json → 自动推送到 GitHub
- 也可在 GitHub → Actions → "模拟交易 M1" 页面手动触发

如需临时手动运行（调试用）：
```bash
python src/scripts/paper_trading_daily.py --date YYYY-MM-DD
```
""")

    # ── Load Method 1 state ──────────────────────────────────────────────────
    _m1, _m1_fallback = _load_m1()
    if _m1_fallback:
        st.info("ℹ️ positions.json 尚未生成，等待 GitHub Actions 首次运行后自动创建。")

    _m1_positions  = [p for p in _m1["positions"] if not p.get("closed")]
    _m1_closed     = _m1.get("closed_trades", [])
    _m1_history    = _m1.get("nav_history", [])
    _m1_cash       = _m1.get("cash", 0.0)
    _m1_init_nav   = _m1["initial_nav"]
    _m1_last_upd_raw = _m1.get("last_update_utc") or ""   # guard against JSON null
    if _m1_last_upd_raw:
        from datetime import datetime, timezone, timedelta
        _sgt = timezone(timedelta(hours=8))
        _m1_last_upd = (datetime.strptime(_m1_last_upd_raw, "%Y-%m-%dT%H:%M:%SZ")
                        .replace(tzinfo=timezone.utc)
                        .astimezone(_sgt)
                        .strftime("%Y-%m-%d %H:%M 新加坡时间（SGT，UTC+8）"))
    else:
        # last_update_utc not yet written by this run; fall back to date-only field
        _m1_last_upd = _m1.get("last_update_date", "N/A") + "（仅限日期，时间不详）"
    _m1_today_sig  = _m1.get("today_signals")

    # ── Fetch live prices ────────────────────────────────────────────────────
    _m1_tickers = tuple(sorted(set([p["ticker"] for p in _m1_positions] + ["SPY"])))
    with st.spinner("从 Yahoo Finance 加载行情…"):
        _m1_raw, _m1_fetch_time = _fetch_yf(_m1_tickers, "300d")

    _m1_live = [_enrich_position(p, _m1_raw) for p in _m1_positions]
    _m1_ok   = [p for p in _m1_live if p.get("_ok")]
    _m1_act  = [p for p in _m1_ok if not p["is_stopped"]]
    _m1_stop = [p for p in _m1_ok if p["is_stopped"]]

    # SPY regime
    _spy_df    = _get_df(_m1_raw, "SPY")
    _spy_close = None; _spy_sma = None; _bull = False
    if _spy_df is not None and len(_spy_df) >= _SMA_WINDOW:
        _spy_close = float(_spy_df["Close"].iloc[-1])
        _spy_sma   = float(_spy_df["Close"].rolling(_SMA_WINDOW).mean().iloc[-1])
        _bull      = _spy_close > _spy_sma

    _m1_mkt   = sum(p["mkt_value"] for p in _m1_ok)
    _m1_unrl  = sum(p["unreal_pnl"] for p in _m1_ok)
    _m1_cost  = sum(p["entry_price"] * p["shares"] for p in _m1_ok)
    _m1_nav   = _m1_mkt + _m1_cash
    _m1_date  = max((p.get("current_date", "") for p in _m1_ok), default="N/A")
    _m1_stale = any(p.get("_stale") for p in _m1_ok)

    # 优先从持久化文件读取上次下载时间；文件不存在时回退到本次会话的缓存时间戳
    try:
        _last_fetch_sgt = json.loads(_YF_FETCH_FILE.read_text())["last_fetch_sgt"]
    except Exception:
        _last_fetch_sgt = _m1_fetch_time

    # ═══════════════════════════════════════════════════════════════════════════
    # ── 数据 & 标的池 ───────────────────────────────────────────────────────────
    # ═══════════════════════════════════════════════════════════════════════════
    st.divider()
    st.subheader("一、数据 & 标的池")

    # ── 常量 ──────────────────────────────────────────────────────────────────
    _DS_EXCL = {"FXI", "GDX", "KWEB", "VXX", "EMB", "ASHR", "ETH", "SPY", "SHY"}
    # Dynamic YF-unavailable list — read from positions.json (maintained automatically
    # by paper_trading_daily.py; fallback to known initial set if not yet populated).
    _DS_YF_UNAVAIL = set(_m1.get("yf_persistent_unavailable", [
        "SPLK", "SNCR", "WFC-P-L", "TTM", "TRUE",
    ]))

    # ── 加载标的池 CSV ─────────────────────────────────────────────────────────
    _ds_csv  = _root / "data" / "tiingo_eligible_universe.csv"
    _ds_df   = pd.read_csv(_ds_csv) if _ds_csv.exists() else pd.DataFrame()

    if not _ds_df.empty:
        _ds_active_all = int((_ds_df["is_active"] == True).sum())
        _ds_delisted   = int((_ds_df["is_active"] == False).sum())
        _ds_tiingo_eligible = _ds_df[
            (_ds_df["is_active"] == True) &
            (_ds_df["eligible_days"] >= 252) &
            (~_ds_df["ticker"].isin(_DS_EXCL))
        ]
        _ds_n_tiingo = len(_ds_tiingo_eligible)
        _ds_pt = _ds_df[
            (_ds_df["is_active"] == True) &
            (_ds_df["eligible_days"] >= 252) &
            (~_ds_df["ticker"].isin(_DS_EXCL | _DS_YF_UNAVAIL))
        ]
        _ds_n_etf   = int(_ds_pt["ticker"].isin(_ETF_SET).sum())
        _ds_n_stock = len(_ds_pt) - _ds_n_etf
        _ds_n_total = len(_ds_pt)
    else:
        _ds_active_all = _ds_delisted = _ds_n_etf = _ds_n_stock = _ds_n_total = _ds_n_tiingo = 0

    # ── 数据来源 ───────────────────────────────────────────────────────────────
    _dsc1, _dsc2 = st.columns(2)
    with _dsc1:
        st.markdown("**数据来源**")
        st.markdown(
            "| 用途 | 来源 |\n|---|---|\n"
            "| 每日价格数据（信号计算、止损更新） | **Yahoo Finance** |\n"
            "| 标的池资格认定（历史价格 / 成交量筛选 + 是否仍在交易） | **Tiingo** |"
        )
    with _dsc2:
        # ── 下载统计 ──────────────────────────────────────────────────────────
        _ds_stats   = _m1.get("last_download_stats", {})
        _ds_pending = _m1.get("pending_retry", {})
        _ds_dl_ok    = _ds_stats.get("downloaded_count", 0) if _ds_stats else 0
        _ds_dl_total = _ds_stats.get("total_scanned", 0)   if _ds_stats else 0
        _ds_dl_fail  = _ds_dl_total - _ds_dl_ok

        _fetch_count_note = f"，共获取 **{len(_m1_tickers):,}** 个标的实时行情" if _m1_tickers else ""
        _scan_count_note  = f"，共扫描 **{_ds_dl_ok:,}** 个标的" if _ds_dl_ok else ""

        st.markdown("**最新数据更新时间**")
        st.markdown(
            f"- **价格数据（Yahoo Finance）**：{_last_fetch_sgt}{_fetch_count_note}\n"
            f"- **策略信号计算**：{_m1_last_upd}{_scan_count_note}"
        )

        if _ds_stats:
            # 转换更新时间为 SGT
            _ds_upd_raw  = _ds_stats.get("updated_utc", "")
            _ds_upd_sgt  = ""
            if _ds_upd_raw:
                try:
                    import datetime as _ddt
                    _u = _ddt.datetime.fromisoformat(_ds_upd_raw.replace("Z", "+00:00"))
                    _ds_upd_sgt = (_u + _ddt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M SGT")
                except Exception:
                    pass

            if _ds_dl_fail == 0:
                st.success(
                    f"上次下载（{_ds_upd_sgt}）：成功下载 **{_ds_dl_ok:,}** 个，"
                    f"扫描范围共 **{_ds_dl_total:,}** 个，**全部下载成功**。"
                )
            else:
                _ds_retry_tks  = _ds_pending.get("tickers", [])
                _ds_next_retry = _ds_pending.get("next_retry_sgt", "")
                st.warning(
                    f"上次下载（{_ds_upd_sgt}）：成功下载 **{_ds_dl_ok:,}** 个，"
                    f"扫描范围共 **{_ds_dl_total:,}** 个，"
                    f"**{_ds_dl_fail}** 个下载失败"
                    + (f"（{'、'.join(_ds_retry_tks)}）" if _ds_retry_tks else "") + "。"
                    + (f"\n\n下次自动重试：**{_ds_next_retry}**。" if _ds_next_retry else "")
                )

    # ── 标的池数量统计 ─────────────────────────────────────────────────────────
    # 从 positions.json 读取每日脚本写入的最新统计（含时间戳）
    _ds_univ_stats = _m1.get("universe_stats", {})
    if _ds_univ_stats:
        _ds_n_tiingo   = _ds_univ_stats.get("tiingo_eligible",  _ds_n_tiingo)
        _ds_n_total    = _ds_univ_stats.get("yf_downloadable",  _ds_n_total)
        _ds_active_all = _ds_univ_stats.get("total_active",     _ds_active_all)
        _ds_delisted   = _ds_univ_stats.get("total_delisted",   _ds_delisted)

    # 优先显示 Tiingo 同步时间；若无则回退到 universe_stats.updated_utc
    def _to_sgt(utc_str: str) -> str:
        if not utc_str:
            return ""
        try:
            import datetime as _ddt2
            _u = _ddt2.datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            return (_u + _ddt2.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M SGT")
        except Exception:
            return ""

    _ds_tiingo_sync_sgt = _to_sgt(_m1.get("tiingo_universe_synced_utc", ""))
    _ds_sync_label      = _ds_tiingo_sync_sgt  # 只显示 Tiingo 专用同步时间，不 fallback 到交易程序运行时间

    _ds_upd_label = (
        f"&nbsp;&nbsp;Tiingo 最后同步：{_ds_sync_label}"
        if _ds_sync_label else ""
    )
    st.markdown(
        f"<strong>标的池统计</strong>{_ds_upd_label}",
        unsafe_allow_html=True,
    )

    _dsm0, _dsm1, _dsm2, _dsm3, _dsm4 = st.columns(5)
    _dsm0.metric("Tiingo 标的池（现役）", f"{_ds_n_tiingo:,}",
                 help="粗筛口径：Tiingo 确认仍在交易（is_active=True）且历史上曾有 ≥252 天同时满足"
                      "原始收盘价 > $10 与 ADV₆₀ > $20M 的标的，排除结构性标的。"
                      "注意：这是历史资格认定，不代表标的当前一定满足价格/成交量条件。"
                      "实际信号生成时会再次实时检查 price > $10、ADV₆₀ > $60M、且今日成交量 ≥ 1.5× 60日均量（精筛）。")
    _dsm1.metric("每日YF可下载标的数", f"{_ds_n_total:,}",
                 help="每天 模拟交易程序实际下载并扫描的标的数。"
                      "= Tiingo 标的池 − YF 无法下载（持续无法从 Yahoo Finance 下载的标的）。"
                      "信号生成时还会进一步实时检查 price > $10、ADV₆₀ > $60M、且今日成交量 ≥ 1.5× 60日均量（精筛）。")
    _dsm2.metric("其中股票", f"{_ds_n_stock:,}")
    _dsm3.metric("其中 ETF", f"{_ds_n_etf:,}")
    _dsm4.metric("YF 无法下载", f"{_ds_n_tiingo - _ds_n_total:,}",
                 help="Tiingo 确认仍在正常交易，但 Yahoo Finance 持续无法下载，不参与每日扫描。由系统自动维护。")

    st.markdown(
        "<strong>Tiingo 标的池定义（粗筛口径）：</strong>"
        "历史上曾有 ≥252 个交易日同时满足原始收盘价 > &#36;10 、且 ADV₆₀ > &#36;20M、"
        "且 Tiingo 确认仍在交易的标的。"
        "这是历史资格认定，不代表当前一定满足价格/成交量条件。"
        "实际信号生成时会额外实时检查（精筛）：price > &#36;10、ADV₆₀ > &#36;60M、且今日成交量 ≥ 1.5× 60日均量，三项均须满足，否则不产生信号。",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<strong>每日YF可下载标的数定义：</strong>"
        "Tiingo 标的池中，Yahoo Finance 可正常下载价格数据的标的，"
        "即每个工作日 模拟交易程序实际下载并扫描信号的范围。"
        "= Tiingo 标的池（现役）− YF 无法下载。",
        unsafe_allow_html=True,
    )
    # ── Yahoo Finance 无法下载的标的明细（动态列表，来自 positions.json）────────
    # All tickers in yf_persistent_unavailable are by construction in the Tiingo pool
    # (eligible_days≥252), because they were only flagged after failing to download
    # while they were part of active_set (which already filters eligible_days≥252).
    _ds_yf_unavail_list = sorted(_DS_YF_UNAVAIL)

    with st.expander(
        f"Tiingo 标的池中 Yahoo Finance 无法下载的 {len(_ds_yf_unavail_list)} 个标的"
        "（自动维护，点击展开）"
    ):
        st.markdown(
            f"以下 **{len(_ds_yf_unavail_list)}** 个标的在 Tiingo 标的池内（eligible_days≥252），"
            "但 Yahoo Finance 持续无法下载，已从每日扫描中排除。"
            "此列表由系统自动维护：连续失败且重试后仍无法恢复的标的自动加入；"
            "每周一自动尝试重新下载，成功则自动移出。"
        )
        _ds_yf_rows = []
        for _dst in _ds_yf_unavail_list:
            if not _ds_df.empty:
                _dsr = _ds_df[_ds_df["ticker"] == _dst]
                _ds_days = int(_dsr["eligible_days"].values[0]) if len(_dsr) else "N/A"
            else:
                _ds_days = "N/A"
            _ds_type = "ETF" if _dst in _ETF_SET else "股票"
            _ds_yf_rows.append({"标的": _dst, "类型": _ds_type, "Tiingo 历史天数": _ds_days})
        if _ds_yf_rows:
            st.dataframe(pd.DataFrame(_ds_yf_rows).sort_values("标的"),
                         use_container_width=True, hide_index=True)
        else:
            st.markdown("（当前无 YF 无法下载的标的）")

    st.markdown("**Tiingo 标的池的局限性与维护建议**")
    st.markdown(
        "每个工作日（周一至周五）自动运行的 Tiingo 同步程序只做一件事：更新 CSV 中所有标的的交易状态（是否仍在交易）。"
        "它**不会**发现新的、尚未进入 CSV 的标的。\n\n"
        "**CSV 的筛选口径：** CSV 由本地脚本 `08_eligible_universe.py` 手动生成，"
        "扫描本地 Tiingo 历史数据缓存（约 22,000 个标的），"
        "保留**历史上至少有一天同时满足原始收盘价 > &#36;10 且 ADV₆₀ > &#36;20M** 的标的，共 4,477 个。"
        "从未达到这一门槛的标的（长期低价股、极低流动性股）完全不在 CSV 内。\n\n"
        "**因此存在以下局限：** 若某标的历史价格从未超过 &#36;10，当初生成 CSV 时已被排除。"
        "即使该标的半年后价格远超 &#36;10 且成交量满足条件，每天的自动程序也不会把它加进来——"
        "因为 CSV 里根本没有这个标的的记录。"
        "同理，新上市（IPO）标的或此前流动性不足、后来达标的标的，均无法被自动纳入。"
    )
    st.info(
        "**标的池完整更新流程（手动，需在本地运行，建议每 3～6 个月执行一次）**\n\n"
        "1. 更新本地 Tiingo 数据缓存（约 22,000 个标的的历史价格 parquet 文件）\n"
        "2. 重新运行 `python src/scripts/08_eligible_universe.py`，重新计算所有标的的 `eligible_days`、`is_active` 等字段\n"
        "3. 将生成的 `data/tiingo_eligible_universe.csv` 推送到 GitHub"
    )

    st.divider()

    # ═══════════════════════════════════════════════════════════════════════════
    st.subheader("二、策略状态概览")
    st.markdown("**初始资金：** $200,000 USD（全新独立账户，调试期 2026-06-19 起，正式启动 2026-07-01）")
    st.markdown(f"上次更新：{_last_fetch_sgt} ｜ Yahoo Finance")

    # ── GitHub Actions 运行状态 ────────────────────────────────────────────────
    if _m1_last_upd_raw:
        try:
            import datetime as _dt_ga
            _ga_last  = _dt_ga.datetime.strptime(_m1_last_upd_raw, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=_dt_ga.timezone.utc
            )
            _ga_hours = (_dt_ga.datetime.now(_dt_ga.timezone.utc) - _ga_last).total_seconds() / 3600
            if _ga_hours < 26:
                _ga_color, _ga_icon, _ga_note = "#2ca02c", "🟢", "正常"
            elif _ga_hours < 48:
                _ga_color, _ga_icon, _ga_note = "#ff7f0e", "🟡", "⚠️ 超过 26 小时未更新"
            else:
                _ga_color, _ga_icon, _ga_note = "#d62728", "🔴", "❌ 超过 48 小时未更新，请检查 GitHub Actions 工作流"
            st.markdown(
                f"<div style='padding:5px 14px;border-radius:6px;background:{_ga_color}18;"
                f"border:1px solid {_ga_color}55;display:inline-block;margin:4px 0'>"
                f"<span style='color:{_ga_color};font-weight:bold'>{_ga_icon} GitHub Actions 上次运行："
                f"距今 <b>{_ga_hours:.1f} 小时</b>（{_ga_note}）</span></div>",
                unsafe_allow_html=True,
            )
        except Exception:
            pass

    # Current drawdown from all-time peak (nav_history + live nav)
    _all_nav_vals = [float(h["nav"]) for h in _m1_history] + [_m1_nav]
    _peak_nav     = max(_all_nav_vals) if _all_nav_vals else _m1_nav
    _cur_dd       = (_m1_nav / _peak_nav - 1) * 100 if _peak_nav > 0 else 0.0

    # Portfolio heat = total dollar risk across positions / nav
    _heat_used_abs  = sum((p["entry_price"] - p["stop_loss"]) * p["shares"] for p in _m1_ok)
    _heat_pct       = _heat_used_abs / _m1_nav * 100 if _m1_nav > 0 else 0.0
    _heat_limit_pct = _V1_PARAMS.heat_limit * 100        # e.g. 10%
    _heat_rem_pct   = _heat_limit_pct - _heat_pct
    _risk_per_trade_pct = _V1_PARAMS.risk_per_trade * 100  # e.g. 1%
    _slots_left     = int(_heat_rem_pct / _risk_per_trade_pct) if _risk_per_trade_pct > 0 else 0

    _nav_pnl_pct = (_m1_nav / _m1_init_nav - 1) * 100
    _nav_pnl_usd = _m1_nav - _m1_init_nav
    _nav_label = f"净值（{_m1_date} 最后记录价格）" if _m1_stale else "净值"

    # 每日净值变化：最后一个交易日收盘后 NAV vs 之前一个交易日收盘后 NAV
    # 两者均取 nav_history（由每日脚本在收盘后用 Yahoo Finance 计算并写入）
    if len(_m1_history) >= 2:
        _latest_close_nav = float(_m1_history[-1]["nav"])
        _prev_nav         = float(_m1_history[-2]["nav"])
        _prev_date        = _m1_history[-2]["date"]
        _latest_date      = _m1_history[-1]["date"]
    elif len(_m1_history) == 1:
        _latest_close_nav = float(_m1_history[-1]["nav"])
        _prev_nav         = _m1_init_nav
        _prev_date        = "起始"
        _latest_date      = _m1_history[-1]["date"]
    else:
        _latest_close_nav = _m1_nav
        _prev_nav         = _m1_init_nav
        _prev_date        = "起始"
        _latest_date      = "—"
    _daily_chg_pct = (_latest_close_nav / _prev_nav - 1) * 100 if _prev_nav > 0 else 0.0

    # 去掉 st.metric() 数值的粗体，与自定义指标保持一致
    st.markdown(
        "<style>[data-testid='stMetricValue']{font-weight:400!important;}</style>",
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)

    def _colored_metric(col, label, value_str, is_positive, sub=None):
        if is_positive is None:
            clr = "inherit"
        else:
            clr = "#2ca02c" if is_positive else "#d62728"
        sub_clr = clr if is_positive is not None else "rgba(49,51,63,0.4)"
        sub_html = f"<div style='font-size:0.8em;color:{sub_clr};margin-top:2px'>{sub}</div>" if sub else ""
        col.markdown(
            f"<div style='font-size:0.875rem;color:rgba(49,51,63,0.6);margin-bottom:4px'>{label}</div>"
            f"<div style='font-size:2.25rem;font-weight:400;color:{clr};line-height:1.2'>{value_str}</div>"
            + sub_html,
            unsafe_allow_html=True,
        )

    _colored_metric(c1, "每日净值变化（%）", f"{_daily_chg_pct:+.2f}%", _daily_chg_pct >= 0)
    _colored_metric(c2, "最新净值", f"${_m1_nav/1e3:,.0f}K", None)
    _colored_metric(c3, "净值浮盈/亏（%）", f"{_nav_pnl_pct:+.2f}%", _nav_pnl_pct >= 0)
    _colored_metric(c4, "净值浮盈/亏（$）", f"${_nav_pnl_usd:+,.0f}", _nav_pnl_usd >= 0)
    _dd_sub = "当前在历史高点" if _cur_dd >= -0.01 else f"峰值 ${_peak_nav/1e3:,.0f}K"
    _colored_metric(c5, "净值从峰值回撤", f"{_cur_dd:.2f}%", _cur_dd >= -0.01, sub=_dd_sub)
    c6.metric("持仓数量", f"{len(_m1_ok)} 只",
              delta=f"其中 {len(_m1_stop)} 只触止损" if _m1_stop else None,
              delta_color="inverse" if _m1_stop else "normal")
    c7.metric("持仓市值", f"${_m1_mkt/1e3:,.0f}K",
              delta=f"占 NAV {_m1_mkt/_m1_nav*100:.1f}%" if _m1_nav else None)
    c8.metric("现金", f"${_m1_cash/1e3:,.0f}K")

    # Portfolio heat progress bar
    _hfill   = min(_heat_pct / _heat_limit_pct, 1.0) * 100
    _hcolor  = "#d62728" if _heat_pct > _heat_limit_pct * 0.85 else ("#ff7f0e" if _heat_pct > _heat_limit_pct * 0.6 else "#2ca02c")
    st.markdown(
        f"<div style='margin:10px 0 4px'>"
        f"<span style='color:#111;font-size:0.88em'><b>组合热度（风险预算）</b>："
        f"已用 <b>{_heat_pct:.1f}%</b> / 上限 {_heat_limit_pct:.0f}%，"
        f"剩余 <b>{_heat_rem_pct:.1f}%</b>（约可新开 <b>{_slots_left}</b> 笔）</span>"
        f"<div style='background:#e0e0e0;border-radius:4px;height:8px;margin-top:5px'>"
        f"<div style='background:{_hcolor};width:{_hfill:.0f}%;height:8px;border-radius:4px'></div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    # ── 最新交易日小结 ────────────────────────────────────────────────────────────
    _ds = _m1.get("daily_summary", {})
    if _ds and _ds.get("bullets"):
        _ds_nav_pct = _ds.get("nav_change_pct", 0)
        _ds_spy_pct = _ds.get("spy_change_pct", 0)
        _ds_vs      = _ds.get("vs_spy_pct", 0)
        _ds_color   = "#d62728" if _ds_nav_pct < -1 else ("#ff7f0e" if _ds_nav_pct < 0 else "#2ca02c")
        st.markdown(
            f"<div style='background:#f8f9fa;border-left:4px solid {_ds_color};"
            f"padding:10px 16px;border-radius:4px;margin:10px 0'>"
            f"<div style='font-weight:700;color:#0f1117;font-size:1em;margin-bottom:8px'>"
            f"最新交易日小结 · {_ds.get('updated_sgt','')}（每日收盘后自动更新）</div>",
            unsafe_allow_html=True,
        )
        for _b in _ds["bullets"]:
            _b_clean = _b.replace("<small>", "").replace("</small>", "")
            st.markdown(f"- {_b_clean}")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")

    # ── Today's trades (executions at today's open) ───────────────────────────
    st.subheader("三、今日完成的交易")
    _trade_rows = []
    if _m1_today_sig:
        _ts_trade_date     = _m1_today_sig.get("date", "N/A")
        _ts_trade_datetime = _us_open_to_sgt(_ts_trade_date)
        # New schema: exits_executed / entries_executed (executed at T+1 open with slippage+commission)
        # Old schema fallback: exits (same-day, no slip/comm) / entries (executed at open)
        _exits_exec   = _m1_today_sig.get("exits_executed") or []
        _entries_exec = _m1_today_sig.get("entries_executed") or _m1_today_sig.get("entries", [])
        for e in _exits_exec:
            _open_px  = e.get("exit_open")
            _fill_px  = e.get("exit_price")
            _reason   = e.get("exit_reason", "")
            _reason_label = {"stop_loss": "🔴 触止损", "trailing_stop": "🔴 触移动止盈"}.get(_reason, _reason)
            _pnl_r    = e.get("pnl_r")
            _net_pnl  = e.get("net_pnl")
            _trade_rows.append({
                "交易日期/时间": _ts_trade_datetime,
                "方向": "🔴 卖出",
                "标的": e["ticker"],
                "类型": _asset_type(e["ticker"]),
                "成交量": e.get("shares", ""),
                "开盘价（无滑点）": f"${_open_px:.2f}" if _open_px else "—",
                "成交价（有滑点）": f"${_fill_px:.2f}" if _fill_px else "—",
                "原因": _reason_label,
                "盈亏（R）": f"{_pnl_r:+.2f}R" if _pnl_r is not None else "—",
                "净盈亏（$）": f"${_net_pnl:+,.0f}" if _net_pnl is not None else "—",
            })
        for e in _entries_exec:
            _open_px  = e.get("open_price")
            _entry_px = e.get("entry_price")
            _stop     = e.get("stop_price")
            _sig_px   = e.get("signal_price")
            _shares   = e.get("shares", 0)
            _risk_pct = e.get("trade_risk")
            # "原因" reflects the actual entry trigger per strategy description Section 4:
            # adj_close[t] > max(adj_high[t-200:t-1]) → 突破200日高点
            if _sig_px and _stop:
                _entry_reason = f"突破200日高点（信号收盘 ${_sig_px:.2f}，止损 ${_stop:.2f}）"
            elif _stop:
                _entry_reason = f"突破200日高点（止损 ${_stop:.2f}）"
            else:
                _entry_reason = "突破200日高点"
            _trade_rows.append({
                "交易日期/时间": _ts_trade_datetime,
                "方向": "🟢 买入",
                "标的": e["ticker"],
                "类型": _asset_type(e["ticker"]),
                "成交量": _shares,
                "开盘价（无滑点）": f"${_open_px:.2f}" if _open_px else "—",
                "成交价（有滑点）": f"${_entry_px:.2f}" if _entry_px else "—",
                "原因": _entry_reason,
                "盈亏（R）": "—",
                "净盈亏（$）": f"风险 {_risk_pct*100:.2f}% NAV" if _risk_pct else "—",
            })
    if _trade_rows:
        _trade_df = pd.DataFrame(sorted(_trade_rows, key=lambda x: (0 if "卖出" in x["方向"] else 1, x["标的"])))

        def _style_trade_col(val):
            if not isinstance(val, str) or val in ("—",):
                return ""
            num = None
            if val.endswith("R"):
                try:
                    num = float(val.rstrip("R"))
                except ValueError:
                    pass
            elif val.startswith("$"):
                try:
                    num = float(val.replace("$", "").replace(",", ""))
                except ValueError:
                    pass
            if num is None:
                return ""
            if num > 0:
                return "color:#2ca02c;font-weight:bold"
            if num < 0:
                return "color:#d62728;font-weight:bold"
            return ""

        show_df(
            _trade_df.style.map(_style_trade_col, subset=["盈亏（R）", "净盈亏（$）"]),
            width="stretch",
            hide_index=True,
        )

        # ── K线图（今日已执行交易）────────────────────────────────────────────
        _s2_sell_tks = [e["ticker"] for e in _exits_exec]
        _s2_buy_tks  = [e["ticker"] for e in _entries_exec]
        _s2_all_tks  = _s2_sell_tks + _s2_buy_tks
        if _s2_all_tks:
            _s2_exec_dt = pd.Timestamp(_ts_trade_date)
            _s2_opts = (
                [f"🔴 已平仓  {t}" for t in _s2_sell_tks]
                + [f"🟢 已开仓  {t}" for t in _s2_buy_tks]
            )
            _s2_opt_to_tk = {
                **{f"🔴 已平仓  {t}": t for t in _s2_sell_tks},
                **{f"🟢 已开仓  {t}": t for t in _s2_buy_tks},
            }
            _s2_sel_opt = st.selectbox(
                "选择标的查看K线图",
                _s2_opts,
                key="s2_kline_sel",
            )
            _s2_sel_tk   = _s2_opt_to_tk[_s2_sel_opt]
            _s2_is_sell  = _s2_sel_tk in _s2_sell_tks
            _s2_kline_n  = 300
            _s2_entry_dt = None
            _s2_ep = _s2_sp = None
            _s2_cl   = None
            _s2_esig = None

            if _s2_is_sell:
                _s2_cl = next(
                    (c for c in _m1_closed
                     if c["ticker"] == _s2_sel_tk and c.get("exit_date") == _ts_trade_date),
                    None,
                )
                if _s2_cl:
                    _s2_entry_dt = pd.Timestamp(_s2_cl["entry_date"])
                    _s2_ep       = _s2_cl.get("entry_price")
                    _s2_sp       = _s2_cl.get("stop_used") or _s2_cl.get("stop_loss")
                    _s2_trail    = _s2_cl.get("trail_stop_at_exit")
                    _s2_kline_n  = 300 + max(0, (_s2_exec_dt - _s2_entry_dt).days * 5 // 7)

            _s2_kdf    = _fetch_yf_chart_single(_s2_sel_tk)

            if _s2_kdf is not None and not _s2_kdf.empty:
                if _s2_is_sell and _s2_entry_dt is not None:
                    _s2_kline_n = 300 + int((_s2_kdf.index >= _s2_entry_dt).sum())
                _s2_kdf = _s2_kdf.tail(_s2_kline_n).copy()

                _s2_hlines = []
                _s2_vlines = []
                _s2_esig   = None
                if _s2_is_sell:
                    if _s2_ep:
                        _s2_hlines.append({"y": _s2_ep, "color": "#1f77b4", "dash": "dash", "label": f"买入价 ${_s2_ep:.2f}"})
                    if _s2_sp:
                        _s2_hlines.append({"y": _s2_sp, "color": "#d62728", "dash": "dash", "label": f"止损价 ${_s2_sp:.2f}"})
                    if _s2_trail and _s2_sp and abs(_s2_trail - _s2_sp) > 0.01:
                        _s2_hlines.append({"y": _s2_trail, "color": "#ff7f0e", "dash": "dot", "label": f"移动止盈 ${_s2_trail:.2f}"})
                    if _s2_entry_dt is not None:
                        _s2_vlines.append({"x": _s2_entry_dt.isoformat(), "color": "#1f77b4", "dash": "dot", "width": 1.5, "text": "开仓日", "use_domain": True})
                    _s2_vlines.append({"x": _s2_exec_dt.isoformat(), "color": "#ff7f0e", "dash": "dash", "width": 2, "text": "今日平仓", "use_domain": False, "y_paper": 0.36})
                else:
                    _s2_esig = next((e for e in _entries_exec if e["ticker"] == _s2_sel_tk), None)
                    if _s2_esig:
                        _s2_sig_p  = _s2_esig.get("signal_price")
                        _s2_stop_p = _s2_esig.get("stop_price")
                        if _s2_sig_p:
                            _s2_hlines.append({"y": _s2_sig_p, "color": "#2ca02c", "dash": "dash", "label": f"信号价 ${_s2_sig_p:.2f}"})
                        if _s2_stop_p:
                            _s2_hlines.append({"y": _s2_stop_p, "color": "#d62728", "dash": "dash", "label": f"止损价 ${_s2_stop_p:.2f}"})
                    _s2_vlines.append({"x": _s2_exec_dt.isoformat(), "color": "#2ca02c", "dash": "dash", "width": 2, "text": "今日开仓", "use_domain": False, "y_paper": 0.28})

                _s2_x_end  = _s2_exec_dt + pd.Timedelta(days=4)
                _s2_action = "今日已平仓" if _s2_is_sell else "今日已开仓"
                _s2_title_info = ""
                if _s2_is_sell and _s2_cl:
                    _s2_t_ent = f"{_s2_cl.get('entry_date','')}  ${_s2_cl['entry_price']:.2f}"
                    _s2_t_ext = f"{_s2_cl.get('exit_date', _ts_trade_date)}  ${_s2_cl.get('exit_price', 0):.2f}"
                    _s2_t_r   = _s2_cl.get("pnl_r")
                    _s2_title_info = (
                        f"　｜　开仓 {_s2_t_ent}"
                        f"　→　平仓 {_s2_t_ext}"
                        + (f"　R={_s2_t_r:+.2f}" if _s2_t_r is not None else "")
                    )
                elif not _s2_is_sell and _s2_esig:
                    _s2_t_px = _s2_esig.get("entry_price")
                    _s2_title_info = (
                        f"　｜　开仓 {_ts_trade_date}"
                        + (f"  ${_s2_t_px:.2f}" if _s2_t_px else "")
                    )

                _s2_fig = _build_kline_fig(
                    _s2_kdf,
                    title=f"{_s2_sel_tk}　{_s2_action}{_s2_title_info}　（最近 {_s2_kline_n} 根日K线）",
                    x_start=_s2_kdf.index[0].isoformat(),
                    x_end=_s2_x_end.isoformat(),
                    hlines=_s2_hlines,
                    vlines=_s2_vlines,
                )
                st.plotly_chart(_s2_fig, width="stretch")
            else:
                st.warning(f"无法获取 {_s2_sel_tk} 的K线数据，请稍后刷新重试。")

    else:
        st.info("今日无交易（今日开盘时无来自昨日的挂单）")

    st.markdown("---")

    # ── 接近止损持仓预警 ─────────────────────────────────────────────────────────
    _near_stop = [p for p in _m1_ok if not p.get("is_stopped") and p.get("stop_buffer_pct", 999) < 5.0]
    if _near_stop:
        _ns_sorted = sorted(_near_stop, key=lambda x: x["stop_buffer_pct"])
        _ns_lines  = []
        for _nsp in _ns_sorted:
            _ns_lines.append(
                f"- **{_nsp['ticker']}**：当前价 ${_nsp['current_price']:.2f}，"
                f"有效止损 ${_nsp['current_stop']:.2f}，"
                f"缓冲 **{_nsp['stop_buffer_pct']:.1f}%**"
            )
        st.warning(
            f"**⚠️ 接近止损预警（缓冲 < 5%）：以下 {len(_near_stop)} 只持仓接近止损线，请关注**\n\n"
            + "\n".join(_ns_lines)
        )

    # ── Tomorrow's orders ────────────────────────────────────────────────────
    st.subheader("四、明日要执行的交易")
    import datetime as _dt

    # New schema: pending_exits + pending_entries (both from today's close detections)
    _pend_exits   = _m1.get("pending_exits", [])
    _pend_entries = _m1.get("pending_entries", [])

    # 执行日 = signal_date 后的下一个交易日（不是 date.today()+1）
    # 优先从 pending 订单的 signal_date 推算，确保跨天查看时日期正确
    _sig_date_str = None
    if _pend_entries:
        _sig_date_str = _pend_entries[0].get("signal_date")
    elif _pend_exits:
        _sig_date_str = _pend_exits[0].get("detected_date") or _pend_exits[0].get("signal_date")
    if _sig_date_str:
        _sig_d = _dt.date.fromisoformat(_sig_date_str)
        _next_td = _sig_d + _dt.timedelta(days=1)
        while _next_td.weekday() >= 5:
            _next_td += _dt.timedelta(days=1)
    else:
        _today_dt = _dt.date.today()
        _next_td  = _today_dt + _dt.timedelta(days=1)
        while _next_td.weekday() >= 5:
            _next_td += _dt.timedelta(days=1)

    _next_td_sgt = _us_open_to_sgt(str(_next_td))
    st.markdown(f"<span style='color:#111111'>执行日/时间：{_next_td_sgt} 开盘 ｜ 以下订单在开盘后按市价执行</span>", unsafe_allow_html=True)
    _order_rows   = []

    # ① 平仓优先（策略描述：T+1 开盘先执行平仓，再执行开仓）
    for s in sorted(_pend_exits, key=lambda x: x["ticker"]):
        _reason = s.get("exit_reason", "")
        _reason_label = {"stop_loss": "止损触发", "trailing_stop": "移动止盈触发"}.get(_reason, _reason)
        _order_rows.append({
            "操作": "🔴 平仓卖出",
            "标的": s["ticker"],
            "股数": s.get("shares", ""),
            "参考价": f"${s['stop_used']:.2f}" if s.get("stop_used") else "—",
            "总金额": f"${s.get('shares', 0) * s.get('stop_used', 0):,.0f}" if s.get("stop_used") else "—",
            "订单类型": "市价单（开盘执行）",
            "备注": _reason_label,
        })

    # ② 开仓按突破强度（strength = 信号收盘 ÷ 200日最高价）从高到低排序，模拟现金流逐笔判断
    # 预计T+1可用现金 = 当前现金 + 所有平仓回款（以止损价估算），只显示现金够用的开仓
    _exit_proceeds_proj = sum(s.get("shares", 0) * s.get("stop_used", 0) for s in _pend_exits)
    _proj_cash = _m1_cash + _exit_proceeds_proj
    _blocked_entries = []
    # 从 candidate_signals 建立 ticker → {rejection, corr_with} 映射，用于备注说明
    _cand_meta = {
        c["ticker"]: {"rejection": c.get("rejection"), "corr_with": c.get("corr_with")}
        for c in (_m1_today_sig or {}).get("candidate_signals", [])
    }
    for e in sorted(_pend_entries, key=lambda x: x.get("strength", 0), reverse=True):
        _strength    = e.get("strength", 0)
        _strength_str = f"突破强度 {_strength:.4f}，" if _strength else ""
        _cost        = e.get("shares", 0) * e.get("signal_price", 0)
        _meta        = _cand_meta.get(e["ticker"], {})
        if _meta.get("rejection") == "corr_reduced":
            _corr_with = _meta.get("corr_with")
            _corr_note = f"⚠️ 相关性减仓（×0.5，与 {_corr_with} 相关），" if _corr_with else "⚠️ 相关性减仓（×0.5），"
        else:
            _corr_note = ""
        if _proj_cash >= _cost:
            _proj_cash -= _cost
            _order_rows.append({
                "操作":     "🟢 开仓买入",
                "标的":     e["ticker"],
                "股数":     e.get("shares", ""),
                "参考价":   f"${e['signal_price']:.2f}" if e.get("signal_price") else "—",
                "总金额":   f"${_cost:,.0f}",
                "订单类型": "市价单（开盘执行）",
                "备注":     (f"{_corr_note}{_strength_str}止损 ${e['stop_price']:.2f}，风险 {e['trade_risk']*100:.2f}% NAV"
                             if e.get("stop_price") else "—"),
            })
        else:
            _blocked_entries.append(e["ticker"])

    # 加入执行顺序列（第一列）
    for _i, _row in enumerate(_order_rows):
        _row["执行顺序"] = _i + 1

    if _order_rows:
        _ord_cols = ["执行顺序", "操作", "标的", "股数", "参考价", "总金额", "订单类型", "备注"]
        show_df(pd.DataFrame(_order_rows)[_ord_cols], width="stretch", hide_index=True)

        n_sell      = len(_pend_exits)
        n_buy       = len(_pend_entries) - len(_blocked_entries)
        n_blocked   = len(_blocked_entries)
        _total_sell = sum(s.get("shares", 0) * s.get("stop_used", 0) for s in _pend_exits)
        _exec_entries = [e for e in _pend_entries if e["ticker"] not in _blocked_entries]
        _total_buy  = sum(e.get("shares", 0) * e.get("signal_price", 0) for e in _exec_entries)
        _net        = _total_buy - _total_sell
        _cash_after = _m1_cash + _total_sell - _total_buy
        st.markdown(
            f"共 {n_sell} 笔平仓、{n_buy} 笔开仓，合计 {n_sell+n_buy} 笔订单　｜　"
            f"预计卖出回款 \\${_total_sell:,.0f}，买入支出 \\${_total_buy:,.0f}，"
            f"净资金变动 {'−' if _net > 0 else '+'}\\${abs(_net):,.0f}，"
            f"执行后剩余现金 \\${_cash_after:,.0f}"
        )
        if _blocked_entries:
            # 热度拦截数：从今日信号的 candidate_signals 里统计
            _cands_for_heat = (_m1_today_sig or {}).get("candidate_signals", [])
            _n_heat_blocked = sum(1 for c in _cands_for_heat if c.get("rejection") == "heat_limit")
            _heat_tickers   = [c["ticker"] for c in _cands_for_heat if c.get("rejection") == "heat_limit"]
            _n_total_skipped = _n_heat_blocked + n_blocked
            _heat_line = (f"其中 **{_n_heat_blocked} 笔**因组合热度上限已由每日程序拒绝"
                          f"（{', '.join(_heat_tickers)}）；" if _n_heat_blocked else "")
            st.warning(
                f"⚠️ 共 **{_n_total_skipped} 笔**开仓不执行：{_heat_line}"
                f"**{n_blocked} 笔**因现金不足从本表格移除（{', '.join(_blocked_entries)}）。\n\n"
                f"预计T+1可用现金（当前现金 \\${_m1_cash:,.0f} + 平仓回款 \\${_exit_proceeds_proj:,.0f}"
                f" = \\${_m1_cash + _exit_proceeds_proj:,.0f}）不够支付全部开仓，"
                f"已按突破强度由高到低优先执行前 {n_buy} 笔。"
            )

        # ── K线图（明日要执行交易的标的）────────────────────────────────────────
        _chart_sell_tks = [s["ticker"] for s in _pend_exits]
        _chart_buy_tks  = sorted(
            [e["ticker"] for e in _exec_entries],
            key=lambda t: next((e.get("strength", 0) for e in _exec_entries if e["ticker"] == t), 0),
            reverse=True,
        )
        _chart_all_tks  = _chart_sell_tks + _chart_buy_tks
        if _chart_all_tks:
            _chart_opts = (
                [f"🔴 平仓卖出  {t}" for t in _chart_sell_tks]
                + [f"🟢 开仓买入  {t}" for t in _chart_buy_tks]
            )
            _chart_opt_to_tk = {
                **{f"🔴 平仓卖出  {t}": t for t in _chart_sell_tks},
                **{f"🟢 开仓买入  {t}": t for t in _chart_buy_tks},
            }
            _sel_opt = st.selectbox(
                "选择标的查看K线图",
                _chart_opts,
                key="s3_kline_sel",
            )
            _sel_tk          = _chart_opt_to_tk[_sel_opt]
            _is_sell_chart   = _sel_tk in _chart_sell_tks
            _pos_info_chart  = None
            _entry_sig_chart = None
            _entry_dt_chart  = None
            _kline_n         = 300

            if _is_sell_chart:
                _pos_info_chart = next(
                    (p for p in _m1_positions if p["ticker"] == _sel_tk), None
                )
                if _pos_info_chart:
                    _entry_dt_chart = pd.Timestamp(_pos_info_chart["entry_date"])
                    _holding_approx = max(
                        0, (pd.Timestamp.today() - _entry_dt_chart).days * 5 // 7
                    )
                    _kline_n = 300 + _holding_approx

            # 拉取数据：600d ≈ 420 交易日，足够 300 + 任意典型持仓天数
            _kdf = _fetch_yf_chart_single(_sel_tk)

            if _kdf is not None and not _kdf.empty:
                # 精确计算开仓后的交易日数
                if _is_sell_chart and _entry_dt_chart is not None:
                    _holding_tds = int((_kdf.index >= _entry_dt_chart).sum())
                    _kline_n = 300 + _holding_tds
                _kdf = _kdf.tail(_kline_n).copy()

                # 执行日（明日）的 Timestamp，用于平仓/开仓竖线
                _exec_dt = pd.Timestamp(str(_next_td))

                _hlines_3      = []
                _vlines_3      = []
                _entry_sig_chart = None
                if _is_sell_chart and _pos_info_chart:
                    _ep      = _pos_info_chart.get("entry_price")
                    _sp      = next((s.get("stop_used") for s in _pend_exits if s["ticker"] == _sel_tk), None)
                    _trail_p = _pos_info_chart.get("trail_stop")
                    if _ep:
                        _hlines_3.append({"y": _ep, "color": "#1f77b4", "dash": "dash", "label": f"买入价 ${_ep:.2f}"})
                    if _sp:
                        _hlines_3.append({"y": _sp, "color": "#d62728", "dash": "dash", "label": f"止损价 ${_sp:.2f}"})
                    if _trail_p and _sp and abs(_trail_p - _sp) > 0.01:
                        _hlines_3.append({"y": _trail_p, "color": "#ff7f0e", "dash": "dot", "label": f"移动止盈 ${_trail_p:.2f}"})
                    if _entry_dt_chart is not None:
                        _vlines_3.append({"x": _entry_dt_chart.isoformat(), "color": "#1f77b4", "dash": "dot", "width": 1.5, "text": "开仓日", "use_domain": True})
                    _vlines_3.append({"x": _exec_dt.isoformat(), "color": "#ff7f0e", "dash": "dash", "width": 2, "text": "明日平仓", "use_domain": False, "y_paper": 0.36})
                else:
                    _entry_sig_chart = next((e for e in _exec_entries if e["ticker"] == _sel_tk), None)
                    if _entry_sig_chart:
                        _sig_p  = _entry_sig_chart.get("signal_price")
                        _stop_p = _entry_sig_chart.get("stop_price")
                        if _sig_p:
                            _hlines_3.append({"y": _sig_p, "color": "#2ca02c", "dash": "dash", "label": f"信号价 ${_sig_p:.2f}"})
                        if _stop_p:
                            _hlines_3.append({"y": _stop_p, "color": "#d62728", "dash": "dash", "label": f"止损价 ${_stop_p:.2f}"})
                    _vlines_3.append({"x": _exec_dt.isoformat(), "color": "#2ca02c", "dash": "dash", "width": 2, "text": "明日开仓", "use_domain": False, "y_paper": 0.28})

                _x_end       = _exec_dt + pd.Timedelta(days=4)
                _action_str  = "明日平仓" if _is_sell_chart else "明日开仓"
                _title_info_3 = ""
                if _is_sell_chart and _pos_info_chart:
                    _t3_ent_d = _pos_info_chart.get("entry_date", "")
                    _t3_ent_p = _pos_info_chart.get("entry_price")
                    _title_info_3 = f"　｜　开仓 {_t3_ent_d}" + (f"  ${_t3_ent_p:.2f}" if _t3_ent_p else "")
                elif not _is_sell_chart and _entry_sig_chart:
                    _t3_sig_p = _entry_sig_chart.get("signal_price")
                    _t3_stp   = _entry_sig_chart.get("stop_price") or _entry_sig_chart.get("stop_loss")
                    _title_info_3 = (
                        (f"　｜　信号价 ${_t3_sig_p:.2f}" if _t3_sig_p else "")
                        + (f"　止损 ${_t3_stp:.2f}" if _t3_stp else "")
                    )

                _fig_k = _build_kline_fig(
                    _kdf,
                    title=f"{_sel_tk}　{_action_str}{_title_info_3}　（最近 {_kline_n} 根日K线）",
                    x_start=_kdf.index[0].isoformat(),
                    x_end=_x_end.isoformat(),
                    hlines=_hlines_3,
                    vlines=_vlines_3,
                )
                st.plotly_chart(_fig_k, width="stretch", key="s3_kline_chart")
            else:
                st.warning(f"无法获取 {_sel_tk} 的K线数据，请稍后刷新重试。")

    else:
        st.info("明日无需执行任何交易")

    st.markdown("---")

    # ── Today's signals (detected at close, pending for tomorrow) ────────────
    st.subheader("五、今日开平仓信号")
    if _m1_today_sig:
        _ts_date   = _m1_today_sig.get("date", "N/A")
        _ts_regime = _m1_today_sig.get("regime", "N/A")
        # exit_signals / candidate_signals / entry_signals: new schema (detected at close, pending tomorrow)
        # Always fall back to pending_exits/pending_entries as canonical source.
        _ts_exit_sigs    = _m1_today_sig.get("exit_signals")      or _m1.get("pending_exits",   [])
        _ts_all_cands    = _m1_today_sig.get("candidate_signals",  [])   # ALL raw breakouts w/ rejection
        _ts_entry_sigs   = _m1_today_sig.get("entry_signals")     or _m1.get("pending_entries", [])

        # Build the approved-ticker set for marking selected candidates
        # Exclude entries blocked by cash constraint (computed in Section 三)
        _approved_tickers = {e["ticker"] for e in _ts_entry_sigs} - set(_blocked_entries)
        if not _approved_tickers:
            _approved_tickers = {p["ticker"] for p in _m1.get("pending_entries", [])} - set(_blocked_entries)

        # Strength lookup: pending_entries always carry strength (stored since day 1).
        # today_signals.entry_signals only has strength after the 2026-06-29 code fix,
        # so use pending_entries as the authoritative source for the fallback.
        _entry_strength_map = {e["ticker"]: e.get("strength")
                               for e in _m1.get("pending_entries", [])
                               if e.get("strength")}

        _ts_regime_str = "🟢 BULL" if _ts_regime == "BULL" else "🔴 BEAR"
        if _spy_close and _spy_sma:
            _ts_gap = (_spy_close / _spy_sma - 1) * 100
            _ts_op  = "＞" if _spy_close > _spy_sma else "＜"
            _ts_regime_str += f"，SPY {_spy_close:.2f} {_ts_op} SMA200 {_spy_sma:.2f}（{_ts_gap:+.1f}%）"
        _ts_datetime_sgt = _us_close_to_sgt(_ts_date) if _ts_date != "N/A" else "N/A"
        st.markdown(f"信号日期/时间：{_ts_datetime_sgt} 盘后 ｜ Regime：{_ts_regime_str}")

        # Tab title: show all-candidate count if available, else approved count
        _entry_tab_label = (
            f"开仓信号（{len(_ts_all_cands)} 笔突破，{len(_approved_tickers)} 笔已选）"
            if _ts_all_cands else
            f"开仓信号（{len(_ts_entry_sigs)} 笔）"
        )
        _tab_exit, _tab_entry = st.tabs([f"平仓信号（{len(_ts_exit_sigs)} 笔）", _entry_tab_label])
        with _tab_exit:
            if _ts_exit_sigs:
                _exit_reason_map = {"stop_loss": "🔴 触止损", "trailing_stop": "🔴 触移动止盈"}
                show_df(pd.DataFrame([{
                    "标的":    s["ticker"],
                    "触发类型": _exit_reason_map.get(s.get("exit_reason", ""), s.get("exit_reason", "")),
                    "参考价":  f"${s['stop_used']:.2f}" if s.get("stop_used") else (
                               f"${s.get('stop_price', 0):.2f}" if s.get("stop_price") else ""),
                    "股数":    s.get("shares", ""),
                    "执行方式": "市价单（次日开盘）",
                } for s in sorted(_ts_exit_sigs, key=lambda x: x["ticker"])]), width="stretch", hide_index=True)
            else:
                st.info("今日无退出信号")

        with _tab_entry:
            _rejection_label = {
                None:              "✅ 已选入（次日执行）",
                "corr_reduced":    "⚠️ 已选入（相关性减仓）",
                "heat_limit":      "🔴 未选（热度上限）",
                "cash_limit":      "🔴 未选（现金不足）",
                "data_error":      "⚠️ 程序漏评（应选入）",
                "execution_error": "⚠️ 执行失败（应开仓，程序错误）",
            }
            if _ts_all_cands:
                # Full funnel view: all raw breakout candidates with rejection reason
                st.caption(
                    f"共 **{len(_ts_all_cands)}** 只个股触发突破信号（通过全部个股筛选），"
                    f"其中 **{len(_approved_tickers)}** 只通过全部约束被选入（含现金约束），"
                    f"剩余因热度上限或现金不足被跳过。"
                )
                _status_order = {
                    "✅ 已选入（次日执行）":         0,
                    "⚠️ 已选入（相关性减仓）":      1,
                    "⚠️ 执行失败（应开仓，程序错误）": 2,
                    "🔴 未选（现金不足）":           3,
                    "🔴 未选（热度上限）":           4,
                }
                _cand_rows = []
                for c in _ts_all_cands:
                    _tk  = c["ticker"]
                    _rej = c.get("rejection")
                    _strength = c.get("strength") or _entry_strength_map.get(_tk)
                    # Determine status — three levels of cash blocking:
                    # 1. Website-side T+1 projected-cash check (_blocked_entries)
                    # 2. Script main() sequential deduction (in candidates but not entry_signals)
                    # 3. scan_entries portfolio-level rejection (heat_limit / cash_limit)
                    if _tk in _blocked_entries:
                        _status = "🔴 未选（现金不足）"
                    elif _rej in (None, "corr_reduced") and _tk not in _approved_tickers:
                        _status = "🔴 未选（现金不足）"
                    else:
                        _status = _rejection_label.get(_rej, _rej or "✅ 已选入")
                    _strength_disp = f"{(_strength - 1)*100:+.3f}%" if _strength else "—"
                    _cand_rows.append({
                        "标的":         _tk,
                        "突破强度":     _strength_disp,
                        "_strength_val": _strength or 0,
                        "信号价（今收）": f"${c.get('signal_price', 0):.2f}" if c.get("signal_price") else "",
                        "参考止损":      f"${c.get('stop_price', 0):.2f}"   if c.get("stop_price")   else "",
                        "股数":          int(c["shares"]) if c.get("shares") else "",
                        "风险% NAV":     f"{c['trade_risk']*100:.2f}%" if c.get("trade_risk") else "",
                        "状态":          _status,
                        "执行方式":      "市价单（次日开盘）" if _tk in _approved_tickers else "—",
                    })
                _cand_rows.sort(key=lambda r: r["_strength_val"], reverse=True)
                for _r in _cand_rows:
                    _r.pop("_strength_val", None)
                show_df(pd.DataFrame(_cand_rows), width="stretch", hide_index=True)
            elif _ts_entry_sigs:
                # Fallback: only approved signals available (old schema or first run)
                st.caption("仅显示已选入信号（候选汇总数据将在下次日程序运行后更新）")
                show_df(pd.DataFrame([{
                    "标的":    e["ticker"],
                    "突破强度": (f"{(e['strength']-1)*100:+.3f}%" if e.get("strength") else "—"),
                    "信号价（今收）": f"${e.get('signal_price', 0):.2f}" if e.get("signal_price") else "",
                    "参考止损":      f"${e.get('stop_price', 0):.2f}"   if e.get("stop_price")   else "",
                    "股数":          e.get("shares", ""),
                    "风险% NAV":     f"{e['trade_risk']*100:.2f}%" if e.get("trade_risk") else "",
                    "状态":          ("🔴 未选（现金不足）" if e["ticker"] in _blocked_entries
                                      else "✅ 已选入（次日执行）"),
                    "执行方式":      "—" if e["ticker"] in _blocked_entries else "市价单（次日开盘）",
                } for e in sorted(_ts_entry_sigs, key=lambda x: x["ticker"])]), width="stretch", hide_index=True)
            else:
                st.info("今日无入场信号")

        # ── K线图：平仓 / 开仓信号（同"三"section 规则）──────────────────────
        # 开仓候选：优先用 _ts_all_cands（含所有被拒绝候选），与表格一致
        _s4_all_cand_src = _ts_all_cands or _ts_entry_sigs
        _s4_sell_tks = sorted({s["ticker"] for s in _ts_exit_sigs})
        _s4_str_map  = {e["ticker"]: e.get("strength", 0) for e in _s4_all_cand_src}
        _s4_buy_tks  = sorted(_s4_str_map, key=lambda t: _s4_str_map[t], reverse=True)
        if _s4_sell_tks or _s4_buy_tks:
            _s4_opts = (
                [f"🔴 平仓卖出  {t}" for t in _s4_sell_tks] +
                [f"🟢 开仓买入  {t}" for t in _s4_buy_tks]
            )
            _s4_opt_to_tk = {
                **{f"🔴 平仓卖出  {t}": t for t in _s4_sell_tks},
                **{f"🟢 开仓买入  {t}": t for t in _s4_buy_tks},
            }
            _s4_sel     = st.selectbox("选择标的查看K线图", _s4_opts, key="s4_kline_sel")
            _s4_tk      = _s4_opt_to_tk[_s4_sel]
            _s4_is_sell = _s4_tk in _s4_sell_tks

            _s4_kdf = _fetch_yf_chart_single(_s4_tk)
            if _s4_kdf is not None and not _s4_kdf.empty:
                _s4_exec_dt = pd.Timestamp(str(_next_td))
                _s4_kline_n = 300
                _s4_hlines  = []
                _s4_vlines  = []

                if _s4_is_sell:
                    _s4_pos = next((p for p in _m1_positions if p["ticker"] == _s4_tk), None)
                    if _s4_pos:
                        _s4_entry_dt = pd.Timestamp(_s4_pos["entry_date"])
                        _s4_kline_n  = 300 + int((_s4_kdf.index >= _s4_entry_dt).sum())
                        _s4_ep       = _s4_pos.get("entry_price")
                        _s4_sig_exit = next((s for s in _ts_exit_sigs if s["ticker"] == _s4_tk), None)
                        _s4_sp       = (_s4_sig_exit.get("stop_used") if _s4_sig_exit
                                        else _s4_pos.get("stop_loss"))
                        _s4_trail    = _s4_pos.get("trail_stop")
                        if _s4_ep:
                            _s4_hlines.append({"y": _s4_ep,    "color": "#1f77b4", "dash": "dash", "label": f"买入价 ${_s4_ep:.2f}"})
                        if _s4_sp:
                            _s4_hlines.append({"y": _s4_sp,    "color": "#d62728", "dash": "dash", "label": f"止损价 ${_s4_sp:.2f}"})
                        if _s4_trail and _s4_sp and abs(_s4_trail - _s4_sp) > 0.01:
                            _s4_hlines.append({"y": _s4_trail, "color": "#ff7f0e", "dash": "dot",  "label": f"移动止盈 ${_s4_trail:.2f}"})
                        _s4_vlines.append({"x": _s4_entry_dt.isoformat(), "color": "#1f77b4", "dash": "dot",  "width": 1.5, "text": "开仓日",  "use_domain": True})
                        _s4_title_info = (
                            f"　｜　开仓 {_s4_pos.get('entry_date', '')}"
                            + (f"  ${_s4_ep:.2f}" if _s4_ep else "")
                        )
                    else:
                        _s4_title_info = ""
                    _s4_vlines.append({"x": _s4_exec_dt.isoformat(), "color": "#ff7f0e", "dash": "dash", "width": 2,   "text": "明日平仓", "use_domain": False, "y_paper": 0.36})
                    _s4_action = "明日平仓"
                else:
                    # 先从全部候选里查（包含被拒绝的），再回落到 entry_sigs
                    _s4_ent_sig = (
                        next((e for e in _s4_all_cand_src if e["ticker"] == _s4_tk), None)
                        or next((e for e in _ts_entry_sigs if e["ticker"] == _s4_tk), None)
                    )
                    if _s4_ent_sig:
                        _s4_sig_p  = _s4_ent_sig.get("signal_price")
                        _s4_stop_p = _s4_ent_sig.get("stop_price")
                        if _s4_sig_p:
                            _s4_hlines.append({"y": _s4_sig_p,  "color": "#2ca02c", "dash": "dash", "label": f"信号价 ${_s4_sig_p:.2f}"})
                        if _s4_stop_p:
                            _s4_hlines.append({"y": _s4_stop_p, "color": "#d62728", "dash": "dash", "label": f"止损价 ${_s4_stop_p:.2f}"})
                        _s4_stp2 = _s4_ent_sig.get("stop_price") or _s4_ent_sig.get("stop_loss")
                        _s4_title_info = (
                            (f"　｜　信号价 ${_s4_sig_p:.2f}" if _s4_sig_p else "")
                            + (f"　止损 ${_s4_stp2:.2f}" if _s4_stp2 else "")
                        )
                    else:
                        _s4_title_info = ""
                    _s4_vlines.append({"x": _s4_exec_dt.isoformat(), "color": "#2ca02c", "dash": "dash", "width": 2,   "text": "明日开仓", "use_domain": False, "y_paper": 0.28})
                    _s4_action = "明日开仓"

                _s4_kdf   = _s4_kdf.tail(_s4_kline_n).copy()
                _s4_x_end = _s4_exec_dt + pd.Timedelta(days=4)
                _s4_fig   = _build_kline_fig(
                    _s4_kdf,
                    title=f"{_s4_tk}　{_s4_action}{_s4_title_info}　（最近 {_s4_kline_n} 根日K线）",
                    x_start=_s4_kdf.index[0].isoformat(),
                    x_end=_s4_x_end.isoformat(),
                    hlines=_s4_hlines,
                    vlines=_s4_vlines,
                )
                st.plotly_chart(_s4_fig, width="stretch", key="s4_kline_chart")
            else:
                st.warning(f"无法获取 {_s4_tk} 的K线数据，请稍后刷新重试。")

    else:
        _ts_regime_cap = "🟢 BULL" if _bull else "🔴 BEAR"
        st.markdown(f"信号日期：N/A ｜ Regime：{_ts_regime_cap}")
        _tab_exit, _tab_entry = st.tabs(["平仓信号（0 笔）", "开仓信号（0 笔）"])
        with _tab_exit:
            st.info("无退出信号")
        with _tab_entry:
            st.info("无入场信号")

    st.markdown("---")

    # ── Live positions ───────────────────────────────────────────────────────
    st.subheader("六、当前持仓实时状态")
    if _m1_date and _m1_date != "N/A":
        st.markdown(f"上次更新：{_last_fetch_sgt} ｜ Yahoo Finance（数据截至 {_m1_date} 收盘）")
    if _m1_stop:
        st.warning(f"⚠️ **{len(_m1_stop)} 只已触及止损** — 建议执行止损出场")

    if _m1_ok:
        def _status_label(p: dict) -> str:
            sr = p.get("stop_reason")
            if sr == "stop_loss":      return "🔴 触止损"
            if sr == "trailing_stop":  return "🔴 触移动止盈"
            return "🟢 持有"

        # Default sort: 触止损/触移动止盈 first, then 缓冲 ascending within each group
        import datetime as _dt_pos
        _today_pos = _dt_pos.date.today()
        def _status_sort_key(p):
            sr = p.get("stop_reason")
            if sr == "stop_loss":     return (0, p["stop_buffer_pct"])
            if sr == "trailing_stop": return (1, p["stop_buffer_pct"])
            return (2, p["stop_buffer_pct"])
        _pos_sorted = sorted(_m1_ok, key=_status_sort_key)
        _pos_df = pd.DataFrame([{
            "标的":      p["ticker"],
            "状态":      _status_label(p),
            "当前价":    p["current_price"],
            "止损":      p["stop_loss"],
            "移动止盈":  p["trail_stop_live"],
            "缓冲":      p["stop_buffer_pct"],
            "浮盈(R)":   p["R"],
            "浮盈($)":   p["unreal_pnl"],
            "风险%NAV":  round((p["entry_price"] - p["stop_loss"]) * p["shares"] / _m1_nav * 100, 3) if _m1_nav else 0,
            "持仓天数":  (_today_pos - _dt_pos.date.fromisoformat(p["entry_date"])).days,
            "当前市值":  p["mkt_value"] / 1000,
            "入场日":    p["entry_date"],
            "入场价":    p["entry_price"],
        } for p in _pos_sorted])

        def _style_pos(df):
            s = pd.DataFrame('', index=df.index, columns=df.columns)
            for i, p in enumerate(_pos_sorted):
                s.at[i, "止损" if p["stop_loss"] >= p["trail_stop_live"] else "移动止盈"] = "font-weight: bold"
                if p["stop_buffer_pct"] <= 3.0:
                    s.at[i, "缓冲"] = "color: #d62728; font-weight: bold"
                s.at[i, "当前价"] = (
                    "color: #d62728" if p["current_price"] < p["entry_price"]
                    else "color: #2ca02c"
                )
            return s

        show_df(
            _pos_df.style.apply(_style_pos, axis=None),
            column_config={
                "当前价":   st.column_config.NumberColumn(format="$%.2f"),
                "止损":     st.column_config.NumberColumn(format="$%.2f"),
                "移动止盈": st.column_config.NumberColumn(format="$%.2f"),
                "缓冲":     st.column_config.NumberColumn(format="%.1f%%"),
                "浮盈(R)":  st.column_config.NumberColumn(label="浮盈（R）", format="%+.2fR"),
                "浮盈($)":  st.column_config.NumberColumn(label="浮盈（$）", format="$%+.0f"),
                "风险%NAV": st.column_config.NumberColumn(label="风险% NAV", format="%.3f%%"),
                "持仓天数": st.column_config.NumberColumn(format="%d 天"),
                "当前市值": st.column_config.NumberColumn(format="$%.0fK"),
                "入场价":   st.column_config.NumberColumn(format="$%.2f"),
            },
        )
        st.markdown(
            "<span style='color:#111111'>**缓冲** = (当前价 − 有效止损) / 当前价 × 100%，其中有效止损 = max(止损, 移动止盈)（即粗体显示的那个）</span><br>"
            "<span style='color:#111111'>**浮盈（R）** = (当前价 − 入场价) / (入场价 − 止损价)，其中分母 = 2 × ATR = 初始每股风险</span>",
            unsafe_allow_html=True,
        )

        _sorted = sorted(_m1_ok, key=lambda x: x.get("R", 0), reverse=True)
        _fig = go.Figure(go.Bar(
            y=[p["ticker"] for p in _sorted],
            x=[p["R"] for p in _sorted],
            orientation="h",
            marker_color=["#d62728" if p["is_stopped"] else ("#2ca02c" if p["R"] >= 0 else "#ff7f0e")
                          for p in _sorted],
            text=[f"{p['R']:+.2f}R" for p in _sorted],
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>R = %{x:+.2f}<extra></extra>",
        ))
        _fig.update_layout(
            title="持仓浮盈（R 倍数，红色 = 触及止损）",
            xaxis_title="R 倍数", height=max(380, len(_sorted) * 26),
            margin=dict(l=70, r=100, t=50, b=40),
            template="plotly_white", showlegend=False,
        )
        st.plotly_chart(_fig, width="stretch")

        # ── 组合相关性热力图 ─────────────────────────────────────────────────────
        _corr_tickers = [p["ticker"] for p in _m1_ok]
        if len(_corr_tickers) >= 2:
            _corr_closes: dict = {}
            for _ct_tk in _corr_tickers:
                _ct_df = _get_df(_m1_raw, _ct_tk)
                if _ct_df is not None and len(_ct_df) >= 20:
                    _corr_closes[_ct_tk] = _ct_df["Close"].rename(_ct_tk)
            if len(_corr_closes) >= 2:
                _corr_price_df = pd.concat(list(_corr_closes.values()), axis=1).dropna()
                _corr_rets     = _corr_price_df.pct_change().dropna()
                _corr_mat      = _corr_rets.corr()
                _n_corr        = len(_corr_mat)
                _fig_corr = go.Figure(go.Heatmap(
                    z=_corr_mat.values,
                    x=_corr_mat.columns.tolist(),
                    y=_corr_mat.index.tolist(),
                    colorscale="RdYlGn",
                    zmin=-1, zmax=1,
                    text=[[f"{v:.2f}" for v in row] for row in _corr_mat.values],
                    texttemplate="%{text}",
                    hovertemplate="<b>%{y} × %{x}</b><br>相关性 = %{z:.2f}<extra></extra>",
                ))
                _fig_corr.update_layout(
                    title=f"持仓相关性热力图（{_n_corr} 只，基于最近 300 日日收益率，绿=低相关/分散，红=高相关/集中）",
                    height=max(340, _n_corr * 42 + 120),
                    margin=dict(l=70, r=30, t=60, b=50),
                    template="plotly_white",
                )
                st.plotly_chart(_fig_corr, width="stretch")

                # 相关性解读
                _corr_pairs = [
                    (_corr_mat.columns[_ci], _corr_mat.columns[_cj], float(_corr_mat.iloc[_ci, _cj]))
                    for _ci in range(_n_corr) for _cj in range(_ci + 1, _n_corr)
                ]
                if _corr_pairs:
                    _avg_corr = sum(p[2] for p in _corr_pairs) / len(_corr_pairs)
                    _max_pair = max(_corr_pairs, key=lambda x: x[2])
                    if _avg_corr > 0.6:
                        _corr_verdict = f"⚠️ 平均相关 **{_avg_corr:.2f}**（偏高）——组合多数持仓在押注同一方向，回撤时会同步下跌，分散化效果有限"
                    elif _avg_corr > 0.35:
                        _corr_verdict = f"平均相关 **{_avg_corr:.2f}**（中等）——有一定分散效果，但高相关对需关注"
                    else:
                        _corr_verdict = f"✅ 平均相关 **{_avg_corr:.2f}**（低）——持仓分散化较好，各标的走势独立"
                    _max_note = (f"；最高对 **{_max_pair[0]} × {_max_pair[1]}** = **{_max_pair[2]:.2f}**"
                                 + ("，二者实质押注同一行情，若市场转向将同步触损" if _max_pair[2] > 0.7 else ""))
                    st.markdown(f"<span style='color:#111111'>**解读：** {_corr_verdict}{_max_note}。</span>", unsafe_allow_html=True)
                    st.markdown(
                        "<span style='color:#111111;font-size:0.85em'>"
                        "判断标准：两两相关均值 **< 0.35** = 分散化良好；**0.35 – 0.60** = 中等，须关注高相关对；**> 0.60** = 偏高，组合实质同向。"
                        "相关性基于最近 300 个交易日的日收益率计算，反映当前市场环境下各标的的历史同步程度。"
                        "</span>",
                        unsafe_allow_html=True,
                    )

        # ── 持仓行业/板块集中度 ──────────────────────────────────────────────────
        with st.spinner("加载行业数据…"):
            _sec_data = [
                (p["ticker"], _fetch_sector(p["ticker"], p.get("sector", "")), p["mkt_value"])
                for p in _m1_ok
            ]
        _sec_grp_dict: dict = {}
        for _stk, _ssec, _smv in _sec_data:
            _sec_grp_dict.setdefault(_ssec, {"tickers": [], "mkt_value": 0.0})
            _sec_grp_dict[_ssec]["tickers"].append(_stk)
            _sec_grp_dict[_ssec]["mkt_value"] += _smv
        _sec_grp_rows = [
            {"行业/板块": k, "持仓数量": len(v["tickers"]), "市值合计": v["mkt_value"],
             "占NAV(%)": round(v["mkt_value"] / _m1_nav * 100, 1) if _m1_nav else 0.0,
             "标的列表": "、".join(sorted(v["tickers"]))}
            for k, v in sorted(_sec_grp_dict.items(), key=lambda x: -x[1]["mkt_value"])
        ]
        _sec_grp_df = pd.DataFrame(_sec_grp_rows)
        _fig_sec = go.Figure(go.Bar(
            x=_sec_grp_df["行业/板块"],
            y=_sec_grp_df["市值合计"] / 1000,
            text=[f"{v:.1f}%" for v in _sec_grp_df["占NAV(%)"]],
            textposition="auto",
            marker_color="#1f77b4",
            hovertemplate="<b>%{x}</b><br>市值 $%{y:.0f}K<extra></extra>",
        ))
        _fig_sec.update_layout(
            title="持仓行业/板块集中度（市值加权）",
            xaxis_title="行业/板块", yaxis_title="市值（$K）",
            height=320, template="plotly_white",
            margin=dict(l=60, r=20, t=60, b=100),
            xaxis_tickangle=-30,
        )
        st.plotly_chart(_fig_sec, width="stretch")
        show_df(
            _sec_grp_df,
            column_config={
                "市值合计": st.column_config.NumberColumn(format="$%.0f"),
                "占NAV(%)": st.column_config.NumberColumn(format="%.1f%%"),
            },
            hide_index=True,
        )

        # 板块集中度解读
        if not _sec_grp_df.empty:
            _sec_top   = _sec_grp_df.iloc[0]
            _sec_top_pct = float(_sec_top["占NAV(%)"])
            _sec_top_name = str(_sec_top["行业/板块"])
            _sec_n     = len(_sec_grp_df)
            _sec_hhi   = sum((float(w) / 100) ** 2 for w in _sec_grp_df["占NAV(%)"])
            if _sec_top_pct > 30:
                _sec_verdict = (
                    f"⚠️ **{_sec_top_name}** 占 NAV **{_sec_top_pct:.1f}%**——"
                    f"若该板块整体回调，组合实际跌幅会远超单只止损预期，须关注行业层面的尾部风险"
                )
            elif _sec_hhi > 0.25:
                _sec_verdict = (
                    f"集中度偏高（HHI={_sec_hhi:.2f}），**{_sec_top_name}** 主导组合风险——"
                    f"考虑是否补充非相关板块标的来分散"
                )
            else:
                _sec_verdict = (
                    f"✅ {_sec_n} 个板块均衡分布（HHI={_sec_hhi:.2f}），"
                    f"无单一行业主导，板块层面分散化合理"
                )
            st.markdown(f"<span style='color:#111111'>**解读：** {_sec_verdict}。</span>", unsafe_allow_html=True)
            st.markdown(
                "<span style='color:#111111;font-size:0.85em'>"
                "判断标准：最大单一板块占 NAV **> 30%** = 敞口过高，板块系统性回撤时损失超出单只止损预期；"
                "**HHI（赫芬达尔指数）> 0.25** = 集中度偏高，少数板块主导组合风险；"
                "**HHI ≤ 0.25** = 集中度合理，各板块均衡分布。"
                "HHI = 各板块占 NAV 权重的平方和，完全集中于单一板块时 HHI = 1，完全均匀分布时 HHI = 1/板块数。"
                "</span>",
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ── Stop detail ──────────────────────────────────────────────────────────
    st.subheader("七、止损/移动止盈明细")
    if _m1_ok:
        _sd_sorted = sorted(_m1_ok, key=lambda x: (
            0 if x.get("stop_reason") == "stop_loss" else
            1 if x.get("stop_reason") == "trailing_stop" else 2,
            x["ticker"]
        ))
        _sd_df = pd.DataFrame([{
            "标的":          p["ticker"],
            "状态":          ("🔴 触止损（待次日清仓）" if p.get("stop_reason") == "stop_loss"
                             else ("🔴 触移动止盈（待次日清仓）" if p.get("stop_reason") == "trailing_stop" else "✅ 持仓中")),
            "当前价":        p["current_price"],
            "买入价":        p["entry_price"],
            "历史最高":      p["highest_high"],
            "ATR(20)":      p["current_atr"],
            "止盈ATR倍":     p["trail_mult"],
            "止损":          p["stop_loss"],
            "移动止盈":      p["trail_stop_live"],
            "有效止损/止盈": p["current_stop"],
            "距止损/止盈":   p["stop_buffer_pct"],
        } for p in _sd_sorted])
        def _style_sd(df):
            s = pd.DataFrame("", index=df.index, columns=df.columns)
            for i, p in enumerate(_sd_sorted):
                # Bold whichever is the binding (effective) stop
                if p["stop_loss"] >= p["trail_stop_live"]:
                    s.at[i, "止损"] = "font-weight: bold"
                else:
                    s.at[i, "移动止盈"] = "font-weight: bold"
                s.at[i, "当前价"] = (
                    "color: #d62728" if p["current_price"] < p["entry_price"]
                    else "color: #2ca02c"
                )
            return s
        show_df(_sd_df.style.apply(_style_sd, axis=None),
            column_config={
                "当前价":        st.column_config.NumberColumn(format="$%.2f"),
                "买入价":        st.column_config.NumberColumn(format="$%.2f"),
                "历史最高":      st.column_config.NumberColumn(format="$%.2f"),
                "ATR(20)":      st.column_config.NumberColumn(format="$%.2f"),
                "止盈ATR倍":     st.column_config.NumberColumn(format="%.1fx"),
                "止损":          st.column_config.NumberColumn(format="$%.2f"),
                "移动止盈":      st.column_config.NumberColumn(format="$%.2f"),
                "有效止损/止盈": st.column_config.NumberColumn(format="$%.2f"),
                "距止损/止盈":   st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
        st.markdown(
            "<span style='color:#555555;font-size:0.85em'>"
            "**有效止损/止盈** = max(止损, 移动止盈)，即当前实际生效的离场触发价。"
            "建仓初期移动止盈尚未超过初始止损时，以「止损」为准；"
            "随着持仓盈利移动止盈上移超过初始止损后，以「移动止盈」为准。"
            "**距止损/止盈** = (当前价 − 有效止损/止盈) / 当前价 × 100%。"
            "</span>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── NAV history ──────────────────────────────────────────────────────────
    if _m1_history:
        st.subheader("八、NAV 走势")
        _nh = pd.DataFrame(_m1_history)
        _nh["date"] = pd.to_datetime(_nh["date"])
        _nh = _nh.sort_values("date").reset_index(drop=True)
        if _m1_date != "N/A" and not (_nh["date"] == pd.to_datetime(_m1_date)).any():
            _nh = pd.concat([_nh, pd.DataFrame([{"date": pd.to_datetime(_m1_date), "nav": _m1_nav}])], ignore_index=True)
        _nh_s = _nh.set_index("date")["nav"]

        _show_spy_m1 = st.checkbox("显示 SPY 基准曲线", value=True, key="m1_nav_show_spy")

        _nav_min_dt_m1 = _nh_s.index[0].to_pydatetime()
        _nav_max_dt_m1 = _nh_s.index[-1].to_pydatetime()
        _has_range_m1  = _nav_min_dt_m1 != _nav_max_dt_m1

        import datetime as _dt_m1nav
        _periods_m1 = [("1年", 1), ("3年", 3), ("5年", 5), ("10年", 10), ("全程", None)]
        _pc_m1 = st.columns([1, 1, 1, 1, 1, 6])
        for _ci_m1, (_lbl_m1, _yrs_m1) in enumerate(_periods_m1):
            with _pc_m1[_ci_m1]:
                if st.button(_lbl_m1, key=f"m1_nav_btn_{_lbl_m1}") and _has_range_m1:
                    _ps_m1 = (_nav_min_dt_m1 if _yrs_m1 is None else
                              max(_nav_min_dt_m1, _nav_max_dt_m1 - _dt_m1nav.timedelta(days=round(365.25 * _yrs_m1))))
                    st.session_state["m1_nav_slider"] = (_ps_m1, _nav_max_dt_m1)

        if _has_range_m1:
            _sel_s_m1, _sel_e_m1 = st.slider(
                "选择时间范围",
                min_value=_nav_min_dt_m1, max_value=_nav_max_dt_m1,
                value=(_nav_min_dt_m1, _nav_max_dt_m1),
                format="YYYY-MM-DD", key="m1_nav_slider",
                label_visibility="collapsed",
            )
            _nav_sl_m1 = _nh_s.loc[_sel_s_m1:_sel_e_m1]
            if len(_nav_sl_m1) < 2:
                _nav_sl_m1 = _nh_s
        else:
            _nav_sl_m1 = _nh_s

        # SPY for comparison (strip timezone from YF index)
        _has_spy_m1 = _show_spy_m1 and _spy_df is not None
        if _has_spy_m1:
            _spy_cmp = _spy_df["Close"].copy()
            _spy_cmp.index = pd.to_datetime(_spy_cmp.index).tz_localize(None) if pd.to_datetime(_spy_cmp.index).tz is not None else pd.to_datetime(_spy_cmp.index)
            if _has_range_m1:
                _spy_sl_m1 = _spy_cmp.loc[_sel_s_m1:_sel_e_m1]
                if len(_spy_sl_m1) < 2:
                    _spy_sl_m1 = _spy_cmp
            else:
                _spy_sl_m1 = _spy_cmp
            if not _spy_sl_m1.empty:
                # 找到策略和 SPY 共同的最早日期，确保两条曲线从同一日期归一化到 1
                _common_start = max(_nav_sl_m1.index[0], _spy_sl_m1.index[0])
                _nav_sl_m1    = _nav_sl_m1[_nav_sl_m1.index >= _common_start]
                _spy_sl_m1    = _spy_sl_m1[_spy_sl_m1.index >= _common_start]
                _spy_norm_m1  = _spy_sl_m1 / float(_spy_sl_m1.iloc[0])
                _spy_dd_m1    = (_spy_sl_m1 - _spy_sl_m1.cummax()) / _spy_sl_m1.cummax() * 100
            else:
                _has_spy_m1 = False

        _nav_norm_m1 = _nav_sl_m1 / float(_nav_sl_m1.iloc[0])
        _dd_m1 = (_nav_sl_m1 - _nav_sl_m1.cummax()) / _nav_sl_m1.cummax() * 100

        _fig_nav = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            row_heights=[0.65, 0.35], vertical_spacing=0.05,
            subplot_titles=["", ""],
        )
        _fig_nav.add_trace(go.Scatter(
            x=_nav_norm_m1.index, y=_nav_norm_m1.values,
            name="策略1.0（模拟）", mode="lines+markers",
            line=dict(color="#1f77b4", width=2),
            hovertemplate="%{x|%Y-%m-%d}<br>NAV: %{y:.2f}x<extra></extra>",
        ), row=1, col=1)
        if _has_spy_m1:
            _fig_nav.add_trace(go.Scatter(
                x=_spy_norm_m1.index, y=_spy_norm_m1.values,
                name="SPY", line=dict(color="#888888", width=1.2, dash="dash"),
                hovertemplate="%{x|%Y-%m-%d}<br>SPY: %{y:.2f}x<extra></extra>",
            ), row=1, col=1)
        _fig_nav.add_trace(go.Scatter(
            x=_dd_m1.index, y=_dd_m1.values,
            fill="tozeroy", fillcolor="rgba(214,39,40,0.25)",
            line=dict(color="#d62728", width=1),
            hovertemplate="%{x|%Y-%m-%d}<br>回撤: %{y:.1f}%<extra></extra>",
            showlegend=False,
        ), row=2, col=1)
        if _has_spy_m1:
            _fig_nav.add_trace(go.Scatter(
                x=_spy_dd_m1.index, y=_spy_dd_m1.values,
                line=dict(color="#888888", width=1.2, dash="dash"),
                hovertemplate="%{x|%Y-%m-%d}<br>SPY回撤: %{y:.1f}%<extra></extra>",
                showlegend=False,
            ), row=2, col=1)
        _fig_nav.update_layout(
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=60, r=20, t=60, b=40),
            height=620,
        )
        _fig_nav.update_yaxes(ticksuffix="x", title_text="净值（倍）", row=1, col=1)
        _fig_nav.update_yaxes(ticksuffix="%", title_text="回撤 %", row=2, col=1)
        st.plotly_chart(_fig_nav, width="stretch")

    # ── Trade history (open + closed) ────────────────────────────────────────
    st.subheader("九、交易历史")
    _all_trades = []
    for p in sorted(_m1_positions, key=lambda x: x["entry_date"]):
        _all_trades.append({
            "状态": "🟢 持仓中",
            "标的": p["ticker"],
            "入场日": p["entry_date"],
            "出场日": "—",
            "入场价": f"${p['entry_price']:.2f}",
            "出场价": "—",
            "股数": p["shares"],
            "持仓天数": None,
            "R": "—",
            "净盈亏": "—",
        })
    for c in sorted(_m1_closed, key=lambda x: x.get("exit_date",""), reverse=True):
        _all_trades.insert(0, {
            "状态": "🔴 已平仓",
            "标的": c["ticker"],
            "入场日": c.get("entry_date", ""),
            "出场日": c.get("exit_date", ""),
            "入场价": f"${c.get('entry_price',0):.2f}",
            "出场价": f"${c.get('exit_price',0):.2f}",
            "股数": c.get("shares"),
            "持仓天数": c.get("holding_days"),
            "R": f"{c['pnl_r']:+.2f}R" if c.get("pnl_r") is not None else "—",
            "净盈亏": f"${c['net_pnl']:+,.0f}" if c.get("net_pnl") is not None else "—",
        })
    if _all_trades:
        _all_trades_df = pd.DataFrame(_all_trades)
        show_df(_all_trades_df, width="stretch", hide_index=True)
        _csv_trades = _all_trades_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "⬇️ 下载交易历史 CSV",
            data=_csv_trades,
            file_name="trade_history.csv",
            mime="text/csv",
        )

        # ── K线图（交易历史）──────────────────────────────────────────────────
        # 下拉选项：持仓中 + 已平仓（同一标的多笔用出场日区分）
        _s9_open_opts   = [f"🟡 持仓中  {p['ticker']}" for p in sorted(_m1_positions, key=lambda x: x["entry_date"])]
        _s9_closed_opts = [
            f"{'🟢' if c.get('pnl_r', 0) > 0 else '🔴'} 已平仓  {c['ticker']}  (出场 {c.get('exit_date','')})"
            for c in sorted(_m1_closed, key=lambda x: x.get("exit_date", ""), reverse=True)
        ]
        _s9_all_opts = _s9_open_opts + _s9_closed_opts
        if _s9_all_opts:
            _s9_sel_opt = st.selectbox(
                "选择标的查看K线图",
                _s9_all_opts,
                key="s9_kline_sel",
            )
            _s9_is_open = _s9_sel_opt.startswith("🟡")

            if _s9_is_open:
                # 从 _m1_positions 取对应记录（按下拉选项顺序匹配）
                _s9_idx   = _s9_open_opts.index(_s9_sel_opt)
                _s9_pos   = sorted(_m1_positions, key=lambda x: x["entry_date"])[_s9_idx]
                _s9_tk    = _s9_pos["ticker"]
                _s9_ep    = _s9_pos.get("entry_price")
                # 当前有效止损：从 _m1_live 取
                _s9_live  = next((lp for lp in _m1_live if lp["ticker"] == _s9_tk), None)
                _s9_sp    = _s9_live.get("current_stop") if _s9_live else _s9_pos.get("stop_loss")
                _s9_entry_dt = pd.Timestamp(_s9_pos["entry_date"])
                _s9_exit_dt  = None
                _s9_holding_approx = max(0, (pd.Timestamp.today() - _s9_entry_dt).days * 5 // 7)
                _s9_kline_n  = 300 + _s9_holding_approx
            else:
                _s9_cl_idx = _s9_closed_opts.index(_s9_sel_opt)
                _s9_cl     = sorted(_m1_closed, key=lambda x: x.get("exit_date", ""), reverse=True)[_s9_cl_idx]
                _s9_tk     = _s9_cl["ticker"]
                _s9_ep     = _s9_cl.get("entry_price")
                _s9_sp     = _s9_cl.get("stop_used") or _s9_cl.get("stop_loss")
                _s9_entry_dt = pd.Timestamp(_s9_cl["entry_date"])
                _s9_exit_dt  = pd.Timestamp(_s9_cl["exit_date"]) if _s9_cl.get("exit_date") else None
                _s9_holding_approx = max(0, int(_s9_cl.get("holding_days", 0)))
                _s9_kline_n  = 300 + _s9_holding_approx

            _s9_kdf = _fetch_yf_chart_single(_s9_tk)

            if _s9_kdf is not None and not _s9_kdf.empty:
                # 精确计算
                _s9_kline_n = 300 + int((_s9_kdf.index >= _s9_entry_dt).sum())
                _s9_kdf = _s9_kdf.tail(_s9_kline_n).copy()

                _s9_hlines = []
                _s9_vlines = []
                if _s9_ep:
                    _s9_hlines.append({"y": _s9_ep, "color": "#1f77b4", "dash": "dash", "label": f"买入价 ${_s9_ep:.2f}"})
                if _s9_is_open:
                    _s9_init_stop = _s9_pos.get("stop_loss")
                    _s9_trl_stop  = _s9_pos.get("trail_stop")
                    if _s9_init_stop:
                        _s9_hlines.append({"y": _s9_init_stop, "color": "#d62728", "dash": "dash", "label": f"止损 ${_s9_init_stop:.2f}"})
                    if _s9_trl_stop and _s9_init_stop and abs(_s9_trl_stop - _s9_init_stop) > 0.01:
                        _s9_hlines.append({"y": _s9_trl_stop, "color": "#ff7f0e", "dash": "dot", "label": f"移动止盈 ${_s9_trl_stop:.2f}"})
                else:
                    if _s9_sp:
                        _s9_hlines.append({"y": _s9_sp, "color": "#d62728", "dash": "dash", "label": f"止损价 ${_s9_sp:.2f}"})
                    _s9_trl_cl = _s9_cl.get("trail_stop_at_exit")
                    if _s9_trl_cl and _s9_sp and abs(_s9_trl_cl - _s9_sp) > 0.01:
                        _s9_hlines.append({"y": _s9_trl_cl, "color": "#ff7f0e", "dash": "dot", "label": f"移动止盈 ${_s9_trl_cl:.2f}"})

                _s9_vlines.append({"x": _s9_entry_dt.isoformat(), "color": "#1f77b4", "dash": "dot", "width": 1.5, "text": "开仓日", "use_domain": True})
                if _s9_exit_dt is not None:
                    _s9_vlines.append({"x": _s9_exit_dt.isoformat(), "color": "#ff7f0e", "dash": "dash", "width": 2, "text": "出场日", "use_domain": False, "y_paper": 0.36})

                _s9_x_end = (
                    _s9_exit_dt + pd.Timedelta(days=4) if _s9_exit_dt is not None
                    else pd.Timestamp.today() + pd.Timedelta(days=4)
                )
                if _s9_is_open:
                    _s9_action     = "持仓中"
                    _s9_title_info = f"　｜　开仓 {_s9_pos.get('entry_date', '')}" + (f"  ${_s9_ep:.2f}" if _s9_ep else "")
                else:
                    _s9_action = "已平仓"
                    _s9_t_r    = _s9_cl.get("pnl_r")
                    _s9_title_info = (
                        f"　｜　开仓 {_s9_cl.get('entry_date', '')}  ${_s9_cl.get('entry_price', 0):.2f}"
                        f"　→　平仓 {_s9_cl.get('exit_date', '')}  ${_s9_cl.get('exit_price', 0):.2f}"
                        + (f"　R={_s9_t_r:+.2f}" if _s9_t_r is not None else "")
                    )

                _s9_fig = _build_kline_fig(
                    _s9_kdf,
                    title=f"{_s9_tk}　{_s9_action}{_s9_title_info}　（最近 {_s9_kline_n} 根日K线）",
                    x_start=_s9_kdf.index[0].isoformat(),
                    x_end=_s9_x_end.isoformat(),
                    hlines=_s9_hlines,
                    vlines=_s9_vlines,
                )
                st.plotly_chart(_s9_fig, width="stretch")
            else:
                st.warning(f"无法获取 {_s9_tk} 的K线数据，请稍后刷新重试。")

        # ── 批量下载所有交易K线图 ─────────────────────────────────────────────
        _s8_zip_key = "s8_all_charts_zip"
        if st.button("📊 生成所有交易K线图（准备下载）", key="s8_gen_zip"):
            with st.spinner("正在生成所有交易的K线图，请稍候…"):
                import io as _io, zipfile as _zf_mod
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.font_manager as _fm_batch
                import matplotlib.pyplot as _plt
                import matplotlib.patches as _mpatch
                import mplfinance as _mpf
                # 用 fc-list 查找系统中文字体路径，直接传给 FontProperties 绕过 cache
                _zh_font_path = None
                try:
                    import subprocess as _sp
                    _fc = _sp.run(
                        ["fc-list", ":lang=zh", "--format=%{file}\n"],
                        capture_output=True, text=True, timeout=5
                    )
                    _zh_font_files = [f.strip() for f in _fc.stdout.splitlines() if f.strip()]
                    if _zh_font_files:
                        _zh_font_path = _zh_font_files[0]
                except Exception:
                    pass
                matplotlib.rcParams["axes.unicode_minus"] = False
                # FontProperties 对象：直接指定字体文件，完全不依赖 font cache
                _cn_fp  = _fm_batch.FontProperties(fname=_zh_font_path) if _zh_font_path else None
                _cn_fp8 = _fm_batch.FontProperties(fname=_zh_font_path, size=8) if _zh_font_path else None

                _batch_tks = tuple(sorted(set(
                    [p["ticker"] for p in _m1_positions] +
                    [c["ticker"] for c in _m1_closed]
                )))
                _batch_raw, _ = _fetch_yf(_batch_tks, "600d")

                # mplfinance 样式：绿涨红跌
                _mpf_mc = _mpf.make_marketcolors(
                    up="#2ca02c", down="#d62728",
                    edge="inherit",
                    wick={"up": "#2ca02c", "down": "#d62728"},
                    volume={"up": "#2ca02c", "down": "#d62728"},
                )
                _mpf_style = _mpf.make_mpf_style(
                    base_mpf_style="charles",
                    marketcolors=_mpf_mc,
                    gridstyle="--", gridcolor="#eeeeee",
                    facecolor="white", edgecolor="white",
                )

                _zip_buf = _io.BytesIO()
                with _zf_mod.ZipFile(_zip_buf, "w", _zf_mod.ZIP_DEFLATED) as _zf:
                    _batch_items = (
                        [("open", p) for p in sorted(_m1_positions, key=lambda x: x["entry_date"])] +
                        [("closed", c) for c in sorted(_m1_closed, key=lambda x: x.get("exit_date", ""), reverse=True)]
                    )
                    for _bstat, _bt in _batch_items:
                        _btk   = _bt["ticker"]
                        _b_edt = pd.Timestamp(_bt["entry_date"])
                        _b_ep  = _bt.get("entry_price")
                        if _bstat == "open":
                            _b_sp  = _bt.get("stop_loss")
                            _b_xdt = None
                            _b_lbl = "持仓中"
                        else:
                            _b_sp  = _bt.get("stop_used") or _bt.get("stop_loss")
                            _b_xdt = pd.Timestamp(_bt["exit_date"]) if _bt.get("exit_date") else None
                            _b_lbl = f"已平仓 R{_bt.get('pnl_r', 0):+.2f}"

                        _bkdf_raw = _get_df(_batch_raw, _btk)
                        if _bkdf_raw is None or _bkdf_raw.empty:
                            continue
                        _b_n   = 300 + int((_bkdf_raw.index >= _b_edt).sum())
                        _bkdf2 = _bkdf_raw.tail(_b_n).copy()
                        # mplfinance 需要 DatetimeIndex 且含 OHLCV 列
                        _bkdf2.index = pd.DatetimeIndex(_bkdf2.index)
                        _bkdf2 = _bkdf2[["Open", "High", "Low", "Close", "Volume"]].dropna()

                        # 获取移动止盈价
                        _b_trl = (
                            _bt.get("trail_stop") if _bstat == "open"
                            else _bt.get("trail_stop_at_exit")
                        )
                        _b_show_trl = bool(_b_trl and _b_sp and abs(_b_trl - _b_sp) > 0.01)

                        # 水平线附加图
                        _add_plots = []
                        if _b_ep:
                            _add_plots.append(_mpf.make_addplot(
                                [_b_ep] * len(_bkdf2), type="line",
                                color="#1f77b4", linestyle="--", width=1.5, panel=0,
                            ))
                        if _b_sp:
                            _add_plots.append(_mpf.make_addplot(
                                [_b_sp] * len(_bkdf2), type="line",
                                color="#d62728", linestyle="--", width=1.5, panel=0,
                            ))
                        if _b_show_trl:
                            _add_plots.append(_mpf.make_addplot(
                                [_b_trl] * len(_bkdf2), type="line",
                                color="#ff7f0e", linestyle=":", width=1.5, panel=0,
                            ))

                        _mpf_kwargs = dict(
                            type="candle",
                            volume=True,
                            style=_mpf_style,
                            figsize=(16, 7),
                            returnfig=True,
                            warn_too_much_data=9999,
                        )
                        if _add_plots:
                            _mpf_kwargs["addplot"] = _add_plots

                        _bfig_mpf, _baxes_mpf = _mpf.plot(_bkdf2, **_mpf_kwargs)
                        _ax_price = _baxes_mpf[0]

                        # 标题（直接指定字体文件，绕过 font cache）
                        _b_title_info = f"  |  开仓 {_b_edt.date()}" + (f"  ${_b_ep:.2f}" if _b_ep else "")
                        if _bstat == "closed" and _b_xdt is not None:
                            _b_exit_px = _bt.get("exit_price")
                            _b_r       = _bt.get("pnl_r")
                            _b_title_info += (
                                f"  →  平仓 {_b_xdt.date()}"
                                + (f"  ${_b_exit_px:.2f}" if _b_exit_px else "")
                                + (f"  R={_b_r:+.2f}" if _b_r is not None else "")
                            )
                        _b_title = f"{_btk}  {_b_lbl}{_b_title_info}  （最近 {_b_n} 根日K线）"
                        if _cn_fp:
                            _bfig_mpf.suptitle(_b_title, fontproperties=_cn_fp, fontsize=12)
                        else:
                            _bfig_mpf.suptitle(_b_title, fontsize=12)

                        # Entry date vline (blue dotted)
                        if _b_edt in _bkdf2.index:
                            _b_edt_pos = _bkdf2.index.get_loc(_b_edt)
                            _ax_price.axvline(x=_b_edt_pos, color="#1f77b4",
                                              linestyle=":", linewidth=1.5)
                            _ax_price.text(_b_edt_pos, _ax_price.get_ylim()[0],
                                           " 开仓日", color="#1f77b4", fontsize=8,
                                           va="bottom", ha="left",
                                           fontproperties=_cn_fp8)
                        # Exit date vline (orange dashed)
                        if _b_xdt is not None and _b_xdt in _bkdf2.index:
                            _b_xdt_pos = _bkdf2.index.get_loc(_b_xdt)
                            _ax_price.axvline(x=_b_xdt_pos, color="#ff7f0e",
                                              linestyle="--", linewidth=2)
                            _ax_price.text(_b_xdt_pos, _ax_price.get_ylim()[1],
                                           " 出场日", color="#ff7f0e", fontsize=8,
                                           va="top", ha="left",
                                           fontproperties=_cn_fp8)
                        # Entry price / stop price / trailing stop labels
                        # 规则：红（止损价）与橘（移动止盈）标注始终朝对立方向
                        #   红线在上 → 红标注在线上方(va=bottom)，橘标注在线下方(va=top)
                        #   红线在下 → 红标注在线下方(va=top)，橘标注在线上方(va=bottom)
                        #   无移动止盈时 → 红标注默认在线上方(va=bottom)
                        if _b_ep:
                            _ax_price.text(0, _b_ep, f" 买入价 ${_b_ep:.2f}",
                                           color="#1f77b4", fontsize=8,
                                           va="bottom", transform=_ax_price.get_yaxis_transform(),
                                           fontproperties=_cn_fp8)
                        if _b_sp:
                            if _b_show_trl:
                                _b_red_va = "bottom" if _b_sp >= _b_trl else "top"
                                _b_ora_va = "top"    if _b_sp >= _b_trl else "bottom"
                            else:
                                _b_red_va = "bottom"   # 无移动止盈：红标注在线上方
                            _ax_price.text(0, _b_sp, f" 止损价 ${_b_sp:.2f}",
                                           color="#d62728", fontsize=8,
                                           va=_b_red_va, transform=_ax_price.get_yaxis_transform(),
                                           fontproperties=_cn_fp8)
                        if _b_show_trl:
                            _ax_price.text(0, _b_trl, f" 移动止盈 ${_b_trl:.2f}",
                                           color="#ff7f0e", fontsize=8,
                                           va=_b_ora_va, transform=_ax_price.get_yaxis_transform(),
                                           fontproperties=_cn_fp8)

                        _buf = _io.BytesIO()
                        _bfig_mpf.savefig(_buf, format="png", dpi=150, bbox_inches="tight")
                        _plt.close(_bfig_mpf)
                        _buf.seek(0)

                        _b_status_str = "已开仓" if _bstat == "open" else "已平仓"
                        _b_fname = f"{_b_status_str}_{_btk}_{_bt.get('entry_date', 'unknown')}.png"
                        _zf.writestr(_b_fname, _buf.read())

                _zip_buf.seek(0)
                st.session_state[_s8_zip_key] = _zip_buf.read()

        if st.session_state.get(_s8_zip_key):
            st.download_button(
                "⬇️ 下载所有交易K线图 (ZIP)",
                data=st.session_state[_s8_zip_key],
                file_name="trade_charts.zip",
                mime="application/zip",
                key="s8_dl_zip_btn",
            )

    else:
        st.info("暂无交易记录")

    st.markdown("---")

    # ── Closed trades + 平仓深度分析 ──────────────────────────────────────────
    st.subheader("十、已完成交易的分析")

    # 统一在此计算平仓指标（供本节 + 后续对比面板复用）
    _n_cl = len(_m1_closed)
    if _m1_closed:
        _ct       = pd.DataFrame(_m1_closed)
        _wins     = _ct[_ct["pnl_r"] > 0]  if "pnl_r" in _ct.columns else pd.DataFrame()
        _losses   = _ct[_ct["pnl_r"] <= 0] if "pnl_r" in _ct.columns else pd.DataFrame()
        _win_rate   = len(_wins) / _n_cl * 100
        _avg_r      = float(_ct["pnl_r"].mean())        if "pnl_r"        in _ct.columns else 0.0
        _tot_pnl    = float(_ct["net_pnl"].sum())       if "net_pnl"      in _ct.columns else 0.0
        _avg_days   = float(_ct["holding_days"].mean()) if "holding_days" in _ct.columns else 0.0
        _avg_win_r  = float(_wins["pnl_r"].mean())     if len(_wins)   > 0 else 0.0
        _avg_loss_r = float(_losses["pnl_r"].mean())   if len(_losses) > 0 else 0.0
        # 连续盈亏 Streak
        _ct_by_date = sorted(_m1_closed, key=lambda x: (x.get("exit_date", ""), x.get("ticker", "")))
        _cur_ws = _cur_ls = _max_ws = _max_ls = 0
        for _tr in _ct_by_date:
            if _tr.get("pnl_r", 0) > 0:
                _cur_ws += 1; _cur_ls = 0; _max_ws = max(_max_ws, _cur_ws)
            else:
                _cur_ls += 1; _cur_ws = 0; _max_ls = max(_max_ls, _cur_ls)
        _streak_str = f"连赢 {_cur_ws} 笔" if _cur_ws > 0 else f"连亏 {_cur_ls} 笔"
        _bt_max_cl  = int(_bt_metrics.get("max_consecutive_losses", 0)) if _bt_metrics else 0

        _n_total_trades  = len(_m1_positions) + _n_cl
        _bt_per_year     = _bt_metrics.get("trades_per_year", 0) if _bt_metrics else 0
        _bt_per_month    = _bt_per_year / 12 if _bt_per_year else 0
        sa1, sa2, sa3 = st.columns(3)
        sa1.metric("累计开仓笔数（含当前持仓）", f"{_n_total_trades} 笔",
                   delta=f"已平仓 {_n_cl} 笔 / 持仓中 {len(_m1_positions)} 笔", delta_color="off")
        sa2.metric("回测平均每年平仓笔数", f"{_bt_per_year:.0f} 笔/年",
                   delta=f"回测共 {int(_bt_metrics.get('n_trades',0))} 笔 / 24 年" if _bt_metrics else None,
                   delta_color="off")
        sa3.metric("回测平均每月平仓笔数", f"{_bt_per_month:.1f} 笔/月")

        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("已平仓笔数", f"{_n_cl} 笔")
        sc2.metric("胜率", f"{_win_rate:.1f}%")
        sc3.metric("平均持仓", f"{_avg_days:.0f} 天")
        sc4.metric("平均R", f"{_avg_r:+.2f}R")
        sc5, sc6, sc7 = st.columns(3)
        sc5.metric("盈亏比", f"{abs(_avg_win_r/(_avg_loss_r or 1)):.2f}x",
                   delta=f"赢 {_avg_win_r:+.2f}R / 亏 {_avg_loss_r:+.2f}R")
        sc6.metric("总净盈亏", f"${_tot_pnl:+,.0f}")
        sc7.metric("当前连续盈亏", _streak_str,
                   delta=f"本轮最长：连赢 {_max_ws} / 连亏 {_max_ls}（回测最大连亏 {_bt_max_cl} 笔）",
                   delta_color="off")


        st.markdown("---")
        _ct_sorted = _ct.sort_values("exit_date", ascending=False)
        show_df(
            _ct_sorted[["ticker","entry_date","exit_date","holding_days","pnl_r","net_pnl","exit_reason"]].rename(
                columns={"ticker":"标的","entry_date":"入场日","exit_date":"出场日",
                         "holding_days":"天数","pnl_r":"R","net_pnl":"净盈亏","exit_reason":"原因"}
            ),
            column_config={
                "R":    st.column_config.NumberColumn(format="%+.2fR"),
                "净盈亏": st.column_config.NumberColumn(format="$%+.0f"),
            },
        )

        # ── R 值分布直方图 ─────────────────────────────────────────────────────
        if "pnl_r" in _ct.columns and _n_cl > 0:
            _r_neg = _ct.loc[_ct["pnl_r"] <= 0, "pnl_r"].dropna().tolist()
            _r_pos = _ct.loc[_ct["pnl_r"] >  0, "pnl_r"].dropna().tolist()
            _fig_r = go.Figure()
            if _r_neg:
                _fig_r.add_trace(go.Histogram(
                    x=_r_neg, name="亏损", marker_color="#d62728",
                    nbinsx=max(5, min(len(_r_neg) * 3, 25)),
                    marker_line_width=1, marker_line_color="white",
                ))
            if _r_pos:
                _fig_r.add_trace(go.Histogram(
                    x=_r_pos, name="盈利", marker_color="#2ca02c",
                    nbinsx=max(5, min(len(_r_pos) * 3, 25)),
                    marker_line_width=1, marker_line_color="white",
                ))
            _fig_r.add_vline(x=0, line_dash="dash", line_color="#888888")
            if _avg_r:
                _fig_r.add_vline(x=_avg_r, line_dash="dot", line_color="#1f77b4",
                                 annotation_text=f"实盘均值 {_avg_r:+.2f}R",
                                 annotation_position="top right")
            if _bt_metrics:
                _bt_ev = (_bt_metrics.get("avg_win_r", 0) * _bt_metrics.get("win_rate", 0)
                          + _bt_metrics.get("avg_loss_r", 0) * (1 - _bt_metrics.get("win_rate", 0)))
                _fig_r.add_vline(x=_bt_ev, line_dash="dashdot", line_color="#ff7f0e",
                                 annotation_text=f"回测期望值 {_bt_ev:+.2f}R",
                                 annotation_position="top left")
            _fig_r.update_layout(
                barmode="overlay",
                title=f"已平仓 R 值分布（{_n_cl} 笔，红=亏损，绿=盈利）",
                xaxis_title="R 倍数", yaxis_title="笔数",
                height=300, template="plotly_white",
                legend=dict(orientation="h", y=1.02, x=1, xanchor="right"),
                margin=dict(l=60, r=20, t=60, b=40),
            )
            st.plotly_chart(_fig_r, width="stretch")

        # ── 交易执行质量汇总 ────────────────────────────────────────────────────
        # signal_price=0.0 是旧数据缺失，需显式过滤（0.0 在 Python 中是 falsy）
        _eq_slip_valid = [
            c for c in _m1_closed
            if c.get("open_price") and float(c.get("signal_price") or 0) > 0 and c.get("entry_price")
        ]
        _eq_r_vals = _ct["pnl_r"].dropna() if "pnl_r" in _ct.columns else pd.Series(dtype=float)
        _eq_r_2p   = int((_eq_r_vals > 2).sum())
        _eq_r_5p   = int((_eq_r_vals > 5).sum())
        _eq_r_neg  = int((_eq_r_vals < -1.05).sum())
        st.markdown("**执行质量汇总**")
        _eq1, _eq2, _eq3, _eq4 = st.columns(4)
        if _eq_slip_valid:
            _eq_gaps  = [(c["open_price"] - c["signal_price"]) / c["signal_price"] * 10000
                          for c in _eq_slip_valid]
            _eq_fav   = sum(1 for g in _eq_gaps if g <= 0)
            _eq_avg_g = sum(_eq_gaps) / len(_eq_gaps)
            _eq1.metric(
                "隔夜跳空均值",
                f"{_eq_avg_g:+.0f} bps",
                delta="有利（低开）" if _eq_avg_g < 0 else "不利（高开）",
                delta_color="normal" if _eq_avg_g < 0 else "inverse",
                help="开盘价 vs 信号收盘价之差（bps）。负值=低开=实际买入成本低于信号价，有利。"
            )
            _eq2.metric(
                "有利跳空笔数",
                f"{_eq_fav} / {len(_eq_gaps)}",
                delta=f"{_eq_fav / len(_eq_gaps) * 100:.0f}% 笔低开（有利）",
                delta_color="normal",
                help="低开（开盘价 ≤ 信号收盘价）= 有利；高开 = 不利。"
            )
        else:
            _eq1.metric("隔夜跳空均值", "N/A", delta="早期数据无信号价记录", delta_color="off",
                        help="早期手动开仓的平仓记录未保存信号价，无法计算隔夜跳空。")
            _eq2.metric("有利跳空笔数", "N/A", delta_color="off")
        _eq3.metric(
            "R > 2R 的笔数",
            f"{_eq_r_2p} 笔",
            delta=f"其中 {_eq_r_5p} 笔 > 5R" if _eq_r_5p else None,
            delta_color="normal",
            help="已平仓笔数中浮盈超过 2R（2倍初始风险）的笔数。"
        )
        _eq4.metric(
            "超额亏损笔数（< −1R）",
            f"{_eq_r_neg} 笔",
            delta="止损执行超出预期" if _eq_r_neg > 0 else "止损执行符合预期",
            delta_color="inverse" if _eq_r_neg > 0 else "normal",
            help="已平仓笔数中实际亏损超过初始风险（< −1R）的笔数，通常由隔夜跳空造成。"
        )

        # ── 入场滑点（隔夜跳空）分析 ───────────────────────────────────────────
        _slip_rows = [
            {
                "标的":            c["ticker"],
                "入场日":          c.get("entry_date", ""),
                "信号价（T收盘）":  c.get("signal_price"),
                "开盘价（T+1）":    c.get("open_price"),
                "入场价（含滑点）": c.get("entry_price"),
                "隔夜跳空(bps)":   round(
                    (c["open_price"] - c["signal_price"]) / c["signal_price"] * 10000, 1
                ) if c.get("open_price") and c.get("signal_price") else None,
                "应用滑点(bps)":   round(
                    (c["entry_price"] - c["open_price"]) / c["open_price"] * 10000, 1
                ) if c.get("entry_price") and c.get("open_price") else None,
            }
            for c in sorted(_m1_closed, key=lambda x: x.get("entry_date", ""))
            if c.get("signal_price") and c.get("open_price") and c.get("entry_price")
        ]
        if _slip_rows:
            _slip_df     = pd.DataFrame(_slip_rows)
            _avg_gap_bps = _slip_df["隔夜跳空(bps)"].dropna().mean()
            _avg_slp_bps = _slip_df["应用滑点(bps)"].dropna().mean()
            st.markdown(
                f"**入场滑点分析** — 隔夜跳空均值 **{_avg_gap_bps:+.0f} bps**"
                f"（正=高开，买入成本高于信号收盘价；负=低开，实际成本更低）"
                f"，策略固定应用滑点 **{_avg_slp_bps:.1f} bps**（回测假设 {int(_V1_PARAMS.slippage_bps)} bps）"
            )
            show_df(
                _slip_df,
                column_config={
                    "信号价（T收盘）":  st.column_config.NumberColumn(format="$%.2f"),
                    "开盘价（T+1）":    st.column_config.NumberColumn(format="$%.2f"),
                    "入场价（含滑点）": st.column_config.NumberColumn(format="$%.4f"),
                    "隔夜跳空(bps)":   st.column_config.NumberColumn(format="%+.1f"),
                    "应用滑点(bps)":   st.column_config.NumberColumn(format="%.1f"),
                },
                width="stretch", hide_index=True,
            )

        # ── 累计滑点与手续费对NAV的影响 ───────────────────────────────────────
        _cost_entry_slip_closed = sum(
            (c["entry_price"] - c["open_price"]) * c["shares"]
            for c in _m1_closed
            if c.get("entry_price") and c.get("open_price") and c.get("shares")
        )
        _cost_exit_slip_closed = sum(
            (c["exit_open"] - c["exit_price"]) * c["shares"]
            for c in _m1_closed
            if c.get("exit_open") and c.get("exit_price") and c.get("shares")
        )
        _cost_entry_comm_closed = sum(
            c.get("entry_commission", 0.0) for c in _m1_closed
        )
        _cost_exit_comm_closed = sum(
            c.get("exit_commission", 0.0) for c in _m1_closed
        )
        _cost_entry_slip_open = sum(
            (p["entry_price"] - p["open_price"]) * p["shares"]
            for p in _m1_positions
            if p.get("entry_price") and p.get("open_price") and p.get("shares")
        )
        _cost_entry_comm_open = sum(
            p.get("entry_commission", 0.0) for p in _m1_positions
        )
        _total_entry_slip  = _cost_entry_slip_closed + _cost_entry_slip_open
        _total_exit_slip   = _cost_exit_slip_closed
        _total_entry_comm  = _cost_entry_comm_closed + _cost_entry_comm_open
        _total_exit_comm   = _cost_exit_comm_closed
        _total_slip        = _total_entry_slip + _total_exit_slip
        _total_comm        = _total_entry_comm + _total_exit_comm
        _total_cost        = _total_slip + _total_comm

        st.markdown("**累计滑点与手续费对策略净值的影响**（含当前持仓已发生成本）")
        _ca, _cb, _cc, _cd = st.columns(4)
        _ca.metric(
            "入场滑点合计",
            f"−${_total_entry_slip:,.0f}",
            delta=f"{_total_entry_slip / _m1_init_nav * -100:.3f}% 初始NAV" if _m1_init_nav else None,
            delta_color="inverse",
        )
        _cb.metric(
            "出场滑点合计",
            f"−${_total_exit_slip:,.0f}",
            delta=f"{_total_exit_slip / _m1_init_nav * -100:.3f}% 初始NAV" if _m1_init_nav else None,
            delta_color="inverse",
        )
        _cc.metric(
            "手续费合计（进+出）",
            f"−${_total_comm:,.0f}",
            delta=f"{_total_comm / _m1_init_nav * -100:.3f}% 初始NAV" if _m1_init_nav else None,
            delta_color="inverse",
        )
        _cd.metric(
            "总成本合计",
            f"−${_total_cost:,.0f}",
            delta=f"{_total_cost / _m1_init_nav * -100:.3f}% 初始NAV" if _m1_init_nav else None,
            delta_color="inverse",
        )
        st.markdown(
            f"<span style='color:#000000;font-size:0.85em'>"
            f"说明：入场/出场滑点 = 成交价与开盘参考价之差 × 股数；"
            f"手续费 = 策略设定的按成交额计收；"
            f"出场滑点与出场手续费仅统计已平仓笔数，当前持仓尚未发生出场成本。"
            f"模拟交易采用滑点 {int(_V1_PARAMS.slippage_bps)} bps（单边）、手续费 {_V1_PARAMS.commission_bps:.0f} bps（单边），与回测假设一致。"
            f"</span>",
            unsafe_allow_html=True,
        )

    else:
        _win_rate = _avg_r = _avg_days = _avg_win_r = _avg_loss_r = _tot_pnl = 0.0
        _max_ws = _max_ls = 0
        st.info("暂无平仓记录")

    st.markdown("---")

    # ── 十、信号漏斗历史趋势 ───────────────────────────────────────────────────
    _sig_hist = _m1.get("signals_history", [])
    if _sig_hist:
        st.subheader("十一、信号漏斗历史趋势")
        _sh_df = pd.DataFrame(_sig_hist)
        _sh_df["date"] = pd.to_datetime(_sh_df["date"])
        _sh_df = _sh_df.sort_values("date").reset_index(drop=True)

        _sh_df = _sh_df.copy()
        _n_entries  = _sh_df.get("n_entries",      pd.Series([0]*len(_sh_df)))
        _n_raw      = _sh_df.get("n_raw_breakouts", pd.Series([0]*len(_sh_df)))
        _blocked    = (_n_raw - _n_entries).clip(lower=0)

        _fig_sh = go.Figure()
        _fig_sh.add_trace(go.Bar(
            x=_sh_df["date"],
            y=_n_entries,
            name="已选入（通过全部约束）",
            marker_color="#2ca02c",
        ))
        _fig_sh.add_trace(go.Bar(
            x=_sh_df["date"],
            y=_blocked,
            name="被拦截（热度/现金）",
            marker_color="#d62728",
        ))
        _fig_sh.add_trace(go.Scatter(
            x=_sh_df["date"],
            y=_sh_df.get("n_raw_breakouts", _sh_df.get("n_candidates", pd.Series([0]*len(_sh_df)))),
            name="原始突破数（通过个股筛选）",
            mode="lines+markers",
            line=dict(color="#1f77b4", width=2),
            yaxis="y",
        ))
        _fig_sh.update_layout(
            barmode="stack",
            title="每日信号漏斗（原始突破 = 已选入 + 被拦截）",
            xaxis_title="日期",
            yaxis_title="信号数量",
            xaxis=dict(
                tickformat="%Y-%m-%d",
                dtick="D1",
                tickangle=-30,
            ),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=60, r=20, t=60, b=60),
            height=350,
            template="plotly_white",
        )
        st.plotly_chart(_fig_sh, width="stretch")
        st.markdown(
            "<span style='color:#111111'>蓝线 = 每日通过个股筛选的突破总数；绿色 = 被组合约束选入；红色 = 被热度/现金上限拦截。</span>",
            unsafe_allow_html=True,
        )
        st.markdown("---")

    # ── 十一、回测 vs 实盘对比面板 ─────────────────────────────────────────────
    if _bt_metrics:
        st.subheader("十二、回测 vs 实盘对比")
        # 实盘最大回撤：覆盖 nav_history + 当前实时 NAV
        _nh_nav_vals_cmp = pd.Series(
            [float(h["nav"]) for h in _m1_history] + [_m1_nav]
        ) if _m1_history else pd.Series([_m1_nav])
        _live_dd_series  = (_nh_nav_vals_cmp - _nh_nav_vals_cmp.cummax()) / _nh_nav_vals_cmp.cummax() * 100
        _live_max_dd_pct = float(_live_dd_series.min()) if len(_nh_nav_vals_cmp) > 1 else 0.0

        _bt_pf = _bt_metrics["avg_win_r"] / abs(_bt_metrics["avg_loss_r"])
        _live_pf = abs(_avg_win_r / (_avg_loss_r or 1)) if _n_cl else None

        _cmp_data = [
            {"指标": "胜率",         "回测预期": f"{_bt_metrics['win_rate']*100:.1f}%",
             "实盘至今": f"{_win_rate:.1f}%" if _n_cl else "—（无平仓）",
             "差值": f"{_win_rate - _bt_metrics['win_rate']*100:+.1f}%" if _n_cl else "—",
             "说明": "盈利交易占全部平仓笔数的比例"},
            {"指标": "平均盈利（R）", "回测预期": f"{_bt_metrics['avg_win_r']:+.2f}R",
             "实盘至今": f"{_avg_win_r:+.2f}R" if _n_cl else "—",
             "差值": f"{_avg_win_r - _bt_metrics['avg_win_r']:+.2f}R" if _n_cl else "—",
             "说明": "盈利交易的平均 R 倍数"},
            {"指标": "平均亏损（R）", "回测预期": f"{_bt_metrics['avg_loss_r']:+.2f}R",
             "实盘至今": f"{_avg_loss_r:+.2f}R" if _n_cl else "—",
             "差值": f"{_avg_loss_r - _bt_metrics['avg_loss_r']:+.2f}R" if _n_cl else "—",
             "说明": "亏损交易的平均 R 倍数（越接近 -1 越好）"},
            {"指标": "盈亏比",        "回测预期": f"{_bt_pf:.2f}x",
             "实盘至今": f"{_live_pf:.2f}x" if _live_pf else "—",
             "差值": f"{_live_pf - _bt_pf:+.2f}x" if _live_pf else "—",
             "说明": "平均盈利 R / |平均亏损 R|"},
            {"指标": "平均持仓天数",  "回测预期": f"{_bt_metrics['avg_holding_days']:.0f} 天",
             "实盘至今": f"{_avg_days:.0f} 天" if _n_cl else "—",
             "差值": f"{_avg_days - _bt_metrics['avg_holding_days']:+.0f} 天" if _n_cl else "—",
             "说明": "从开仓到平仓的持有天数均值"},
            {"指标": "最大回撤",      "回测预期": f"{_bt_metrics['max_drawdown']*100:.1f}%",
             "实盘至今": f"{_live_max_dd_pct:.1f}%",
             "差值": f"{_live_max_dd_pct - _bt_metrics['max_drawdown']*100:+.1f}%",
             "说明": "NAV 从历史峰值的最大跌幅"},
            {"指标": "最大连续亏损",  "回测预期": f"{int(_bt_metrics.get('max_consecutive_losses',0))} 笔",
             "实盘至今": f"{_max_ls} 笔",
             "差值": f"{_max_ls - int(_bt_metrics.get('max_consecutive_losses',0)):+d} 笔",
             "说明": "连续亏损交易的最多笔数（回测为 24 年统计）"},
        ]
        if _n_cl < 30:
            _bt_n = int(_bt_metrics.get("n_trades", 0))
            st.caption(
                f"⚠️ 实盘仅 {_n_cl} 笔平仓，样本量不足，差值无统计意义，"
                f"仅供趋势观察（回测基于 {_bt_n} 笔 / 24 年数据）。"
            )
        show_df(pd.DataFrame(_cmp_data), width="stretch", hide_index=True)
        st.markdown("---")

    # ── 十二、月度 P&L 汇总 ───────────────────────────────────────────────────
    if _m1_history and len(_m1_history) >= 2:
        st.subheader("十三、月度 P&L 汇总")
        _nh_mon = pd.DataFrame(_m1_history)
        _nh_mon["date"] = pd.to_datetime(_nh_mon["date"])
        _nh_mon = _nh_mon.sort_values("date").reset_index(drop=True)
        _nh_mon["ym"] = _nh_mon["date"].dt.to_period("M")

        _monthly_rows = []
        for _ym, _grp in _nh_mon.groupby("ym"):
            _nav_s = float(_grp["nav"].iloc[0])
            _nav_e = float(_grp["nav"].iloc[-1])
            _strat = (_nav_e / _nav_s - 1) * 100 if _nav_s else 0.0
            _spy_v = pd.to_numeric(_grp.get("spy_close", pd.Series(dtype=float)), errors="coerce").dropna()
            _spy_r = (float(_spy_v.iloc[-1]) / float(_spy_v.iloc[0]) - 1) * 100 if len(_spy_v) >= 2 else None
            _rel   = (_strat - _spy_r) if _spy_r is not None else None
            _regime_vals = _grp["regime"].dropna().values if "regime" in _grp.columns else []
            _regime_mon  = str(_regime_vals[-1]) if len(_regime_vals) > 0 else ""
            _monthly_rows.append({
                "月份":        str(_ym),
                "月初NAV":     f"${_nav_s:,.0f}",
                "月末NAV":     f"${_nav_e:,.0f}",
                "策略月收益率": _strat,
                "SPY月收益率":  _spy_r,
                "超额收益（α）": _rel,
                "Regime":      _regime_mon,
            })

        show_df(
            pd.DataFrame(_monthly_rows),
            column_config={
                "策略月收益率":  st.column_config.NumberColumn(format="%+.2f%%"),
                "SPY月收益率":   st.column_config.NumberColumn(format="%+.2f%%"),
                "超额收益（α）": st.column_config.NumberColumn(format="%+.2f%%"),
            },
            width="stretch", hide_index=True,
        )
        if len(_monthly_rows) >= 2:
            _fig_mon = go.Figure()
            _fig_mon.add_trace(go.Bar(
                x=[r["月份"] for r in _monthly_rows],
                y=[r["策略月收益率"] for r in _monthly_rows],
                name="策略",
                marker_color=["#2ca02c" if r["策略月收益率"] >= 0 else "#d62728"
                              for r in _monthly_rows],
            ))
            _spy_mon_pairs = [(r["月份"], r["SPY月收益率"]) for r in _monthly_rows
                             if r["SPY月收益率"] is not None]
            if _spy_mon_pairs:
                _fig_mon.add_trace(go.Scatter(
                    x=[v[0] for v in _spy_mon_pairs], y=[v[1] for v in _spy_mon_pairs],
                    name="SPY", mode="lines+markers",
                    line=dict(color="#888888", dash="dash", width=1.5),
                ))
            _fig_mon.update_layout(
                title="月度收益率（绿=正收益，红=负收益）",
                xaxis_title="月份", yaxis_title="月收益率 (%)",
                yaxis=dict(ticksuffix="%"),
                height=320, template="plotly_white",
                legend=dict(orientation="h", y=1.02, x=1, xanchor="right"),
                margin=dict(l=60, r=20, t=60, b=40),
            )
            st.plotly_chart(_fig_mon, width="stretch")
        st.markdown("---")

    # ── 数据下载（方法一）────────────────────────────────────────────────────
    st.subheader("数据下载（用于未来策略1.0的过拟合分析）")
    st.markdown(
        "包含所有模拟交易数据：NAV 历史、开仓记录、平仓记录、"
        "信号历史（每日漏斗计数）、**今日突破候选明细**（含拒绝原因）、当前持仓、回测参考数据。"
    )

    _dl1_nav   = _m1.get("nav_history", [])
    _dl1_sig   = _m1.get("signals_history", [])
    _dl1_ct    = _m1.get("closed_trades", [])
    _dl1_op    = [p for p in _m1.get("positions", []) if not p.get("closed")]
    _dl1_ts    = _m1.get("today_signals", {})
    _dl1_cands = _dl1_ts.get("candidate_signals", [])   # full funnel for most recent run

    # 开仓历史 = 所有已开仓交易（持仓中 + 已平仓），按开仓日期排序
    _dl1_entries = sorted([
        {"ticker": p["ticker"],
         "signal_date": p.get("signal_date", ""), "signal_price": p.get("signal_price"),
         "entry_date": p["entry_date"], "open_price": p.get("open_price"), "entry_price": p["entry_price"],
         "shares": p["shares"], "stop_loss": p.get("stop_loss"),
         "atr_at_entry": p.get("atr_at_entry"), "状态": "持仓中"}
        for p in _dl1_op
    ] + [
        {"ticker": c["ticker"],
         "signal_date": c.get("signal_date", ""), "signal_price": c.get("signal_price"),
         "entry_date": c.get("entry_date", ""), "open_price": c.get("open_price"),
         "entry_price": c.get("entry_price"),
         "shares": c.get("shares"), "stop_loss": c.get("stop_loss"),
         "atr_at_entry": None, "状态": "已平仓"}
        for c in _dl1_ct
    ], key=lambda x: x["entry_date"], reverse=True)

    _dl1_rejection_label = {
        None:           "✅ 已选入",
        "corr_reduced": "⚠️ 已选入（相关性减仓）",
        "heat_limit":   "🔴 未选（热度上限）",
        "cash_limit":   "🔴 未选（现金不足）",
        "data_error":   "⚠️ 程序漏评（应选入）",
    }

    with st.expander(f"NAV 历史（{len(_dl1_nav)} 条）"):
        if _dl1_nav:
            show_df(
                pd.DataFrame(_dl1_nav).sort_values("date", ascending=False),
                width="stretch", hide_index=True)
        else:
            st.info("暂无数据")

    with st.expander(f"开仓记录（{len(_dl1_entries)} 笔，含持仓中 + 已平仓）"):
        if _dl1_entries:
            show_df(pd.DataFrame(_dl1_entries), width="stretch", hide_index=True)
        else:
            st.info("暂无开仓记录")

    with st.expander(f"平仓记录（{len(_dl1_ct)} 笔）"):
        if _dl1_ct:
            show_df(
                pd.DataFrame(_dl1_ct).sort_values("exit_date", ascending=False),
                width="stretch", hide_index=True)
        else:
            st.info("暂无平仓记录")

    with st.expander(f"信号历史（{len(_dl1_sig)} 条，每日漏斗计数）"):
        st.caption(
            "每行代表一个交易日的信号漏斗统计。"
            "原始突破数 → 热度/现金拦截 → 通过约束数（候选）→ 实际执行数。"
            "用于分析组合约束对策略执行率的影响。"
        )
        if _dl1_sig:
            show_df(pd.DataFrame([{
                "日期":           s["date"],
                "Regime":         s.get("regime", ""),
                "SPY收盘":        s.get("spy_close"),
                "原始突破数":     s.get("n_raw_breakouts"),  # 通过个股过滤器的总突破数
                "热度拦截":       s.get("n_heat_blocked"),   # 被组合热度限制拦截
                "现金拦截":       s.get("n_cash_blocked"),   # 被现金不足拦截
                "相关性减仓":     s.get("n_corr_reduced"),   # 触发相关性减半（仍执行）
                "候选信号数":     s.get("n_candidates"),     # 通过全部约束的信号数
                "当日开仓信号":   s.get("n_entries"),        # 保存为 pending
                "当日已执行":     s.get("n_executed"),       # T+1 开盘实际成交
                "平仓数":         s.get("n_exits"),
            } for s in reversed(_dl1_sig)]), width="stretch", hide_index=True)
        else:
            st.info("暂无数据")

    _dl1_cands_approved = sum(1 for c in _dl1_cands if c.get("rejection") in (None, "corr_reduced"))
    _dl1_cands_rejected = len(_dl1_cands) - _dl1_cands_approved
    with st.expander(
        f"今日突破候选明细（{len(_dl1_cands)} 只突破，{_dl1_cands_approved} 只已选，{_dl1_cands_rejected} 只被拦截）"
        + f"  ·  信号日期：{_dl1_ts.get('date', 'N/A')}"
    ):
        st.caption(
            "所有通过**个股筛选**（价格、ADV、突破、ATR、成交量）的标的，"
            "含被组合约束（热度上限/现金不足）拦截的个股及原因。"
            "注：此处仅显示最近一次日程序运行的候选明细；历史每日明细见『信号历史』表（汇总计数）。"
        )
        if _dl1_cands:
            show_df(pd.DataFrame([{
                "标的":         c["ticker"],
                "突破强度":     (f"{(c['strength']-1)*100:+.3f}%" if c.get("strength") else "—"),
                "信号价（今收）": f"${c.get('signal_price', 0):.2f}" if c.get("signal_price") else "",
                "参考止损":      f"${c.get('stop_price', 0):.2f}"   if c.get("stop_price")   else "",
                "股数":          c.get("shares", ""),
                "风险% NAV":     f"{c['trade_risk']*100:.2f}%" if c.get("trade_risk") else "",
                "状态":          _dl1_rejection_label.get(c.get("rejection"), c.get("rejection", "✅ 已选入")),
            } for c in sorted(_dl1_cands, key=lambda x: x["ticker"])]),
            width="stretch", hide_index=True)
        else:
            st.info(
                "候选明细将在下次日程序运行后自动填充（需运行更新后的 paper_trading_daily.py）。"
            )

    # 每日开仓信号明细（含突破强度）：从 signals_history 汇聚每天的 entry_signals
    _dl1_daily_entries = []
    for _sh in _dl1_sig:
        _d = _sh.get("date", "")
        for _e in _sh.get("entry_signals", []):
            _dl1_daily_entries.append({
                "日期":     _d,
                "标的":     _e.get("ticker", ""),
                "突破强度": (f"{(_e['strength']-1)*100:+.3f}%" if _e.get("strength") else "—"),
                "信号价":   f"${_e['signal_price']:.2f}" if _e.get("signal_price") else "",
                "参考止损": f"${_e['stop_price']:.2f}"   if _e.get("stop_price")   else "",
                "股数":     _e.get("shares", ""),
                "风险% NAV": f"{_e['trade_risk']*100:.2f}%" if _e.get("trade_risk") else "",
            })
    with st.expander(f"每日开仓信号明细（{len(_dl1_daily_entries)} 笔，含突破强度）"):
        st.caption(
            "每个交易日所有通过组合约束、进入候选池的开仓信号及其突破强度。"
            "突破强度 = 信号日收盘价 ÷ 前200日最高价 - 1，反映突破幅度。"
            "下载 ZIP 中对应文件为 m1_daily_entry_signals.csv。"
        )
        if _dl1_daily_entries:
            show_df(
                pd.DataFrame(_dl1_daily_entries).sort_values(["日期", "突破强度"], ascending=[False, False]),
                width="stretch", hide_index=True)
        else:
            st.info("每日开仓信号数据将在下次日程序运行后填充。")

    with st.expander(f"当前持仓（{len(_dl1_op)} 只）"):
        if _dl1_op:
            show_df(pd.DataFrame(_dl1_op), width="stretch", hide_index=True)
        else:
            st.info("当前无持仓")

    from datetime import date as _date_cls
    st.download_button(
        label="⬇️ 下载方法一全部数据（ZIP）",
        data=_build_method_zip(_m1, "m1"),
        file_name=f"m1_paper_trading_{_date_cls.today().isoformat()}.zip",
        mime="application/zip",
        help=(
            "包含（CSV + 完整JSON）：\n"
            "• m1_nav_history.csv — 每日 NAV\n"
            "• m1_entry_history.csv — 所有开仓记录（持仓中 + 已平仓）\n"
            "• m1_closed_trades.csv — 已平仓记录（含 pnl_r、signal_strength、lowest_low/MAE、entry_regime、exit_regime）\n"
            "• m1_signals_history.csv — 每日信号漏斗计数\n"
            "• m1_all_candidate_signals.csv — 历史每日突破候选明细（含拒绝原因，所有日期）\n"
            "• m1_daily_entry_signals.csv — 历史每日通过热度筛选的入场信号\n"
            "• m1_open_positions.csv — 当前持仓\n"
            "• backtest_reference_metrics.json / trades.csv / nav.csv — 回测基准数据"
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — 方法二：IB 自动交易
# ═══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.markdown("""
    **运行方式：** 每个交易日收盘后在本地运行 `python src/scripts/ib_paper_trading_daily.py`，
    程序自动连接 IB TWS（模拟交易模式）下单，并将结果推送到 GitHub。

    **初始资金：** $200,000 USD（独立账户，不依赖回测历史）
    """)

    # ── Load Method 2 state ──────────────────────────────────────────────────
    _m2 = _load_m2()

    if _m2 is None:
        # Fallback: show empty $200K initial state
        st.info("ℹ️ ib_state.json 尚未生成，显示初始状态（$200K，0 持仓）。")
        _m2 = {
            "schema_version": 1, "method": "ib_paper_trading",
            "debug_start_date": "2026-06-19", "live_start_date": "2026-07-01",
            "initial_capital": 200000.0, "currency": "USD",
            "last_update_date": None, "nav": 200000.0, "cash": 200000.0,
            "account_summary": {}, "positions": [], "closed_trades": [],
            "nav_history": [], "orders_history": [], "today_signals": {},
        }

    _m2_positions  = [p for p in _m2.get("positions", []) if not p.get("closed")]
    _m2_closed     = _m2.get("closed_trades", [])
    _m2_history    = _m2.get("nav_history", [])
    _m2_last_upd   = _m2.get("last_update_date") or "尚未运行"
    _m2_init_cap   = _m2.get("initial_capital", 200_000.0)
    _m2_nav        = _m2.get("nav", _m2_init_cap)
    _m2_cash       = _m2.get("cash", _m2_init_cap)
    _m2_orders_hist = _m2.get("orders_history", [])
    _m2_today_sig  = _m2.get("today_signals", {})
    _m2_live_start = _m2.get("live_start_date", "2026-07-01")
    _m2_debug_start = _m2.get("debug_start_date", "2026-06-19")
    _m2_ib_summary = _m2.get("account_summary", {})

    # Phase banner
    import datetime as _dt
    _today_dt = _dt.date.today()
    _live_start_dt = _dt.date.fromisoformat(_m2_live_start)
    if _today_dt < _live_start_dt:
        days_left = (_live_start_dt - _today_dt).days
        st.warning(f"🔧 **调试阶段** — 正式启动日期：{_m2_live_start}（还有 {days_left} 天）。建议使用 `--dry-run` 参数先验证信号。")
    else:
        st.success(f"🚀 **已正式启动** — 自 {_m2_live_start} 起实盘模拟交易运行中")

    st.markdown("---")

    # ── Overview metrics ─────────────────────────────────────────────────────
    st.subheader("一、账户状态概览")
    st.markdown(f"上次程序运行：{_m2_last_upd} ｜ 初始资金：${_m2_init_cap:,.0f}")

    _m2_pnl = _m2_nav - _m2_init_cap
    _m2_pnl_pct = (_m2_nav / _m2_init_cap - 1) * 100

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("账户 NAV", f"${_m2_nav:,.0f}",
              delta=f"{_m2_pnl_pct:+.2f}%  (${_m2_pnl:+,.0f})",
              delta_color="normal" if _m2_pnl >= 0 else "inverse")
    a2.metric("当前持仓", f"{len(_m2_positions)} 只")
    a3.metric("现金", f"${_m2_cash:,.0f}",
              delta=f"{_m2_cash/_m2_nav*100:.1f}% of NAV" if _m2_nav else None)
    a4.metric("已平仓笔数", f"{len(_m2_closed)} 笔")

    # IB Account Summary (if available)
    if _m2_ib_summary:
        st.markdown("#### IB 账户实时数据（最近一次连接）")
        ib1, ib2, ib3, ib4 = st.columns(4)
        ib1.metric("IB NetLiquidation", f"${_m2_ib_summary.get('NetLiquidation', 0):,.0f}")
        ib2.metric("IB AvailableFunds", f"${_m2_ib_summary.get('AvailableFunds', 0):,.0f}")
        ib3.metric("IB UnrealizedPnL",  f"${_m2_ib_summary.get('UnrealizedPnL', 0):+,.0f}")
        ib4.metric("IB RealizedPnL",    f"${_m2_ib_summary.get('RealizedPnL', 0):+,.0f}")

    st.markdown("---")

    # ── Today's signals ───────────────────────────────────────────────────────
    st.subheader("二、今日信号")
    if _m2_today_sig:
        sig_date    = _m2_today_sig.get("date", "N/A")
        sig_regime  = _m2_today_sig.get("regime", "N/A")
        sig_spy     = _m2_today_sig.get("spy_close")
        sig_exits   = _m2_today_sig.get("exits", [])
        sig_entries = _m2_today_sig.get("entries", [])
        st.markdown(f"信号日期：{sig_date} 盘后 ｜ Regime：{'🟢 BULL' if sig_regime == 'BULL' else '🔴 BEAR'}" +
                   (f" ｜ SPY：${sig_spy:.2f}" if sig_spy else ""))

        _sc1, _sc2 = st.columns(2)
        with _sc1:
            st.markdown(f"**退出信号（{len(sig_exits)} 笔）**")
            if sig_exits:
                _ex_df = pd.DataFrame([{
                    "标的": e["ticker"],
                    "操作": "SELL",
                    "股数": e["shares"],
                    "止损价": f"${e['stop_price']:.2f}",
                    "订单类型": e["order_type"],
                } for e in sig_exits])
                show_df(_ex_df, width="stretch", hide_index=True)
            else:
                st.info("无退出信号")

        with _sc2:
            st.markdown(f"**入场信号（{len(sig_entries)} 笔）**")
            if sig_entries:
                _en_df = pd.DataFrame([{
                    "标的": e["ticker"],
                    "操作": "BUY",
                    "股数": e["shares"],
                    "信号价": f"${e['signal_price']:.2f}",
                    "止损价": f"${e['stop_price']:.2f}",
                    "风险%": f"{e['trade_risk']*100:.2f}%",
                    "订单类型": e["order_type"],
                } for e in sig_entries])
                show_df(_en_df, width="stretch", hide_index=True)
            else:
                st.info("无入场信号")
    else:
        st.info(f"尚无今日信号。请运行 `python src/scripts/ib_paper_trading_daily.py`")

    st.markdown("---")

    # ── Live positions (fetch prices from Yahoo Finance) ──────────────────────
    st.subheader("三、当前持仓状态")
    if _m2_positions:
        _m2_tickers = tuple(sorted(set([p["ticker"] for p in _m2_positions] + ["SPY"])))
        with st.spinner("从 Yahoo Finance 加载持仓行情…"):
            _m2_raw, _ = _fetch_yf(_m2_tickers, "300d")

        _m2_live = [_enrich_position(p, _m2_raw) for p in _m2_positions]
        _m2_ok   = [p for p in _m2_live if p.get("_ok")]
        _m2_stp  = [p for p in _m2_ok if p["is_stopped"]]

        if _m2_stp:
            st.warning(f"⚠️ **{len(_m2_stp)} 只已触及止损** — IB 程序运行后将自动生成退出订单")

        def _m2_status(p: dict) -> str:
            sr = p.get("stop_reason")
            if sr == "stop_loss":      return "🔴 触止损"
            if sr == "trailing_stop":  return "🔴 触移动止盈"
            return "🟢 持有"

        _m2_rows = [{
            "标的": p["ticker"],
            "状态": _m2_status(p),
            "入场日": p["entry_date"],
            "入场价": f"${p['entry_price']:.2f}",
            "当前价": f"${p['current_price']:.2f}",
            "移动止损": f"${p['current_stop']:.2f}",
            "缓冲": f"{p['stop_buffer_pct']:.1f}%",
            "R": f"{p['R']:+.2f}R",
            "浮盈 $": f"${p['unreal_pnl']:+,.0f}",
            "股数": p["shares"],
        } for p in sorted(_m2_ok, key=lambda x: x.get("R", 0), reverse=True)]

        if _m2_rows:
            show_df(pd.DataFrame(_m2_rows), width="stretch", hide_index=True)
    else:
        st.info("当前无持仓。Regime 允许时，下次运行程序将扫描开仓信号。")

    st.markdown("---")

    # ── NAV History ───────────────────────────────────────────────────────────
    if _m2_history:
        st.subheader("四、NAV 走势")
        _m2_nh = pd.DataFrame(_m2_history)
        _m2_nh["date"] = pd.to_datetime(_m2_nh["date"])
        _m2_nh = _m2_nh.sort_values("date")
        _fig_m2nav = go.Figure(go.Scatter(
            x=_m2_nh["date"], y=_m2_nh["nav"] / _m2_init_cap,
            mode="lines+markers", line=dict(color="#ff7f0e", width=2.5),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.3f}x<extra></extra>",
        ))
        _fig_m2nav.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5)
        _fig_m2nav.update_layout(
            title="方法二 NAV（相对起始 $200K）", yaxis_title="倍数",
            height=280, margin=dict(l=60, r=20, t=45, b=40), template="plotly_white",
        )
        st.plotly_chart(_fig_m2nav, width="stretch")
        st.markdown("---")

    # ── Closed trades ─────────────────────────────────────────────────────────
    if _m2_closed:
        st.subheader(f"五、已平仓记录（{len(_m2_closed)} 笔）")
        _m2_ct = pd.DataFrame(_m2_closed).sort_values("exit_date", ascending=False)
        _m2_rename = {"ticker":"标的","entry_date":"入场日","exit_date":"出场日","holding_days":"天数","exit_reason":"原因"}
        _m2_cfg: dict = {}
        if "pnl_r_est" in _m2_ct.columns:
            _m2_rename["pnl_r_est"] = "R"
            _m2_cfg["R"] = st.column_config.NumberColumn(format="%+.2fR")
        if "net_pnl_est" in _m2_ct.columns:
            _m2_rename["net_pnl_est"] = "净盈亏(估)"
            _m2_cfg["净盈亏(估)"] = st.column_config.NumberColumn(format="$%+.0f")
        _m2_cols = [c for c in ["ticker","entry_date","exit_date","holding_days","pnl_r_est","net_pnl_est","exit_reason"] if c in _m2_ct.columns]
        show_df(_m2_ct[_m2_cols].rename(columns=_m2_rename), column_config=_m2_cfg or None)
        st.markdown("---")

    # ── Order history ─────────────────────────────────────────────────────────
    if _m2_orders_hist:
        with st.expander(f"📋 订单历史（最近 {min(50, len(_m2_orders_hist))} 条）"):
            _ord_df = pd.DataFrame(_m2_orders_hist[-50:][::-1])
            _show_cols = [c for c in ["ticker","action","shares","order_type","reason","signal_price","stop_price","ib_status","submitted_at","dry_run"] if c in _ord_df.columns]
            show_df(_ord_df[_show_cols], width="stretch", hide_index=True)

    # ── Setup guide ───────────────────────────────────────────────────────────
    with st.expander("⚙️ IB 模拟交易配置与使用指南"):
        st.markdown(f"""
### IB TWS 配置

1. 登录 **IB 模拟交易账户**（TWS 或 IB Gateway）
2. **启用 API 连接**：
   - TWS：File → Global Configuration → API → Settings
   - 勾选 "Enable ActiveX and Socket Clients"
   - Socket port：**7497**（TWS 模拟交易）
   - 勾选 "Allow connections from localhost only"（安全）
3. 推荐**重置模拟交易账户**初始资金：
   - 右键账户 → Reset Paper Trading Account（IB 界面按钮原文）
   - 程序使用自己的 $200K NAV 计算，但 IB 账户余额一致更易对账

### 每日运行

```bash
# 调试阶段（不实际下单，只看信号）
python src/scripts/ib_paper_trading_daily.py --dry-run

# 正式模式（实际通过 IB API 下单）
python src/scripts/ib_paper_trading_daily.py

# 可选参数
python src/scripts/ib_paper_trading_daily.py \\
    --port 4002 \\          # IB Gateway 端口（默认 7497 为 TWS）
    --client-id 10 \\       # IB 客户端 ID（避免与 TWS 手动操作冲突）
    --no-entries            # 只检查止损，不扫描开仓

# 完成后推送到 GitHub
git add results/paper_trading/ib_state.json
git commit -m "IB 模拟交易: YYYY-MM-DD"
git push
```

### 关键参数

| 参数 | 值 |
|------|-----|
| 初始资金 | $200,000 |
| 每笔风险 | 1% NAV ($2,000 at start) |
| 最大热度 | 10% NAV |
| 单仓上限 | 5% NAV ($10,000 at start) |
| 开仓信号 | 200日突破 + ATR止损 |
| 止损方式 | 移动止盈（ATR×3/5，每日更新） |
| 订单类型 | MOO（次日开盘价执行） |
| 股数取整 | **四舍五入**（小数≥0.5进一） |
| 正式启动 | **{_m2_live_start}** |
""")

    st.markdown("---")

    # ── 数据下载（方法二）────────────────────────────────────────────────────
    st.subheader("数据下载（用于未来策略1.0的过拟合分析）")
    st.markdown(
        "包含所有模拟交易数据：NAV 历史、开仓记录、平仓记录、"
        "信号历史（每日漏斗计数）、**今日突破候选明细**（含拒绝原因）、当前持仓、回测参考数据。"
    )

    _dl2_nav   = _m2.get("nav_history", [])
    _dl2_sig   = _m2.get("signals_history", [])
    _dl2_ct    = _m2.get("closed_trades", [])
    _dl2_op    = [p for p in _m2.get("positions", []) if not p.get("closed")]
    _dl2_ts    = _m2.get("today_signals", {})
    _dl2_cands = _dl2_ts.get("candidate_signals", [])

    _dl2_entries = sorted([
        {"ticker": p["ticker"], "entry_date": p["entry_date"],
         "entry_price": p["entry_price"], "shares": p["shares"],
         "stop_loss": p.get("stop_loss", p.get("initial_stop_loss", "")), "atr_at_entry": p.get("atr_at_entry"),
         "状态": "持仓中"}
        for p in _dl2_op
    ] + [
        {"ticker": c["ticker"], "entry_date": c.get("entry_date", ""),
         "entry_price": c.get("entry_price", ""), "shares": c.get("shares", ""),
         "stop_loss": c.get("stop_loss", c.get("initial_stop", "")), "atr_at_entry": None,
         "状态": "已平仓"}
        for c in _dl2_ct
    ], key=lambda x: x["entry_date"], reverse=True)

    _dl2_rejection_label = {
        None:           "✅ 已选入",
        "corr_reduced": "⚠️ 已选入（相关性减仓）",
        "heat_limit":   "🔴 未选（热度上限）",
        "cash_limit":   "🔴 未选（现金不足）",
        "data_error":   "⚠️ 程序漏评（应选入）",
    }

    with st.expander(f"NAV 历史（{len(_dl2_nav)} 条）"):
        if _dl2_nav:
            show_df(
                pd.DataFrame(_dl2_nav).sort_values("date", ascending=False),
                width="stretch", hide_index=True)
        else:
            st.info("暂无数据")

    with st.expander(f"开仓记录（{len(_dl2_entries)} 笔，含持仓中 + 已平仓）"):
        if _dl2_entries:
            show_df(pd.DataFrame(_dl2_entries), width="stretch", hide_index=True)
        else:
            st.info("暂无开仓记录")

    with st.expander(f"平仓记录（{len(_dl2_ct)} 笔）"):
        if _dl2_ct:
            show_df(
                pd.DataFrame(_dl2_ct).sort_values("exit_date", ascending=False),
                width="stretch", hide_index=True)
        else:
            st.info("暂无平仓记录")

    with st.expander(f"信号历史（{len(_dl2_sig)} 条，每日漏斗计数）"):
        st.caption(
            "每行代表一个交易日的信号漏斗统计。"
            "原始突破数 → 热度/现金拦截 → 通过约束数（候选）→ 实际执行数。"
        )
        if _dl2_sig:
            show_df(pd.DataFrame([{
                "日期":           s["date"],
                "Regime":         s.get("regime", ""),
                "SPY收盘":        s.get("spy_close"),
                "原始突破数":     s.get("n_raw_breakouts"),
                "热度拦截":       s.get("n_heat_blocked"),
                "现金拦截":       s.get("n_cash_blocked"),
                "相关性减仓":     s.get("n_corr_reduced"),
                "候选信号数":     s.get("n_candidates"),
                "当日开仓信号":   s.get("n_entries"),
                "当日已执行":     s.get("n_executed"),
                "平仓数":         s.get("n_exits"),
            } for s in reversed(_dl2_sig)]), width="stretch", hide_index=True)
        else:
            st.info("暂无数据")

    _dl2_cands_approved = sum(1 for c in _dl2_cands if c.get("rejection") in (None, "corr_reduced"))
    _dl2_cands_rejected = len(_dl2_cands) - _dl2_cands_approved
    with st.expander(
        f"今日突破候选明细（{len(_dl2_cands)} 只突破，{_dl2_cands_approved} 只已选，{_dl2_cands_rejected} 只被拦截）"
        + f"  ·  信号日期：{_dl2_ts.get('date', 'N/A')}"
    ):
        st.caption(
            "所有通过**个股筛选**的标的（含被组合约束拦截的个股及原因）。"
            "注：仅显示最近一次日程序运行的候选明细；历史每日明细见『信号历史』表（汇总计数）。"
        )
        if _dl2_cands:
            show_df(pd.DataFrame([{
                "标的":         c["ticker"],
                "突破强度":     (f"{(c['strength']-1)*100:+.3f}%" if c.get("strength") else "—"),
                "信号价（今收）": f"${c.get('signal_price', 0):.2f}" if c.get("signal_price") else "",
                "参考止损":      f"${c.get('stop_price', 0):.2f}"   if c.get("stop_price")   else "",
                "股数":          c.get("shares", ""),
                "风险% NAV":     f"{c['trade_risk']*100:.2f}%" if c.get("trade_risk") else "",
                "状态":          _dl2_rejection_label.get(c.get("rejection"), c.get("rejection", "✅ 已选入")),
            } for c in sorted(_dl2_cands, key=lambda x: x["ticker"])]),
            width="stretch", hide_index=True)
        else:
            st.info("候选明细将在方法二日程序运行后自动填充。")

    _dl2_daily_entries = []
    for _sh in _dl2_sig:
        _d = _sh.get("date", "")
        for _e in _sh.get("entry_signals", []):
            _dl2_daily_entries.append({
                "日期":     _d,
                "标的":     _e.get("ticker", ""),
                "突破强度": (f"{(_e['strength']-1)*100:+.3f}%" if _e.get("strength") else "—"),
                "信号价":   f"${_e['signal_price']:.2f}" if _e.get("signal_price") else "",
                "参考止损": f"${_e['stop_price']:.2f}"   if _e.get("stop_price")   else "",
                "股数":     _e.get("shares", ""),
                "风险% NAV": f"{_e['trade_risk']*100:.2f}%" if _e.get("trade_risk") else "",
            })
    with st.expander(f"每日开仓信号明细（{len(_dl2_daily_entries)} 笔，含突破强度）"):
        st.caption(
            "每个交易日所有通过组合约束的开仓信号及其突破强度。"
            "突破强度 = 信号日收盘价 ÷ 前200日最高价 - 1。"
            "下载 ZIP 中对应文件为 m2_daily_entry_signals.csv。"
        )
        if _dl2_daily_entries:
            show_df(
                pd.DataFrame(_dl2_daily_entries).sort_values(["日期", "突破强度"], ascending=[False, False]),
                width="stretch", hide_index=True)
        else:
            st.info("每日开仓信号数据将在方法二日程序运行后填充。")

    with st.expander(f"当前持仓（{len(_dl2_op)} 只）"):
        if _dl2_op:
            show_df(pd.DataFrame(_dl2_op), width="stretch", hide_index=True)
        else:
            st.info("当前无持仓")

    from datetime import date as _date_cls
    st.download_button(
        label="⬇️ 下载方法二全部数据（ZIP）",
        data=_build_method_zip(_m2, "m2"),
        file_name=f"m2_paper_trading_{_date_cls.today().isoformat()}.zip",
        mime="application/zip",
        help=(
            "包含（CSV + 完整JSON）：\n"
            "• m2_nav_history.csv — 每日 NAV\n"
            "• m2_entry_history.csv — 所有开仓记录（持仓中 + 已平仓）\n"
            "• m2_closed_trades.csv — 已平仓记录\n"
            "• m2_signals_history.csv — 每日信号漏斗计数\n"
            "• m2_today_candidate_signals.csv — 最近一次运行的突破候选明细（含拒绝原因）\n"
            "• m2_open_positions.csv — 当前持仓\n"
            "• backtest_reference_metrics.json / trades.csv / nav.csv — 回测基准数据"
        ),
    )
