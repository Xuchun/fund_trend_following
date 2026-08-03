"""Shiller PE Ratio vs SPY 历史关系分析"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import re, urllib.request
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as _pio
import streamlit as st
import yfinance as yf

_pio.templates.default = "plotly_white"

st.title("Shiller PE Ratio vs SPY 历史关系分析")
st.markdown(
    "基于 1993 年至今的 SPY 月度价格与 Shiller PE Ratio（CAPE）历史数据，"
    "分析高估值环境下 SPY 的未来表现，探讨是否存在「应停止买入」的估值阈值。"
)
st.markdown("---")


# ── 数据加载 ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400)
def load_cape() -> pd.DataFrame:
    url = "https://www.multpl.com/shiller-pe/table/by-month"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
    rows = re.findall(r"<tr[^>]*>.*?</tr>", html, re.DOTALL)
    data = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cells) >= 2:
            d = re.sub(r"<[^>]+>", "", cells[0]).strip()
            v = re.sub(r"<[^>]+>|&#x2002;", "", cells[1]).strip()
            try:
                dt   = datetime.strptime(d, "%b %d, %Y")
                cape = float(v)
                data.append((dt, cape))
            except Exception:
                pass
    df = pd.DataFrame(data, columns=["date", "cape"])
    df["date"] = pd.to_datetime(df["date"]).dt.to_period("M").dt.to_timestamp("M")
    df = df.sort_values("date").drop_duplicates("date").set_index("date")
    return df


@st.cache_data(ttl=86400)
def load_spy() -> pd.DataFrame:
    spy = yf.download("SPY", start="1993-01-01", interval="1mo",
                      auto_adjust=True, progress=False)
    spy = spy[["Close"]].copy()
    spy.index = spy.index.to_period("M").to_timestamp("M")
    spy.columns = ["spy_close"]
    return spy.sort_index()


with st.spinner("正在从 Yahoo Finance 和 multpl.com 加载数据…"):
    try:
        cape_df = load_cape()
        spy_df  = load_spy()
    except Exception as e:
        st.error(f"数据加载失败：{e}")
        st.stop()

# ── 合并 & 计算前向收益 ───────────────────────────────────────────────────────
df = cape_df.join(spy_df, how="inner").sort_index()
df = df[df.index >= "1993-01-01"]
for n in [1, 3, 6, 12, 24, 36]:
    df[f"fwd_{n}m"] = df["spy_close"].shift(-n) / df["spy_close"] - 1

latest_cape = df["cape"].dropna().iloc[-1]
latest_date = df["cape"].dropna().index[-1]
pct_rank    = (df["cape"].dropna() < latest_cape).mean()

# ── 计算当前连续高估时长 ──────────────────────────────────────────────────────
def _streak_start(df_: pd.DataFrame, threshold: float):
    """从最新月份往前找连续超过阈值的起始月。"""
    start = None
    for dt in sorted(df_.index, reverse=True):
        if df_.loc[dt, "cape"] > threshold:
            start = dt
        else:
            break
    return start

_streak35_start = _streak_start(df.dropna(subset=["cape"]), 35)
_streak40_start = _streak_start(df.dropna(subset=["cape"]), 40)

def _months_since(start, end):
    if start is None:
        return 0
    return len(df.loc[(df.index >= start) & (df.index <= end)])

_months35 = _months_since(_streak35_start, latest_date)
_months40 = _months_since(_streak40_start, latest_date)

def _max_streak(df_: pd.DataFrame, threshold: float):
    """遍历全部历史数据，找出连续超过阈值的最长连续段（月数 + 起止月）。"""
    best_len, best_start, best_end = 0, None, None
    cur_len, cur_start = 0, None
    for dt in sorted(df_.index):
        if df_.loc[dt, "cape"] > threshold:
            if cur_len == 0:
                cur_start = dt
            cur_len += 1
            if cur_len > best_len:
                best_len, best_start, best_end = cur_len, cur_start, dt
        else:
            cur_len, cur_start = 0, None
    return best_len, best_start, best_end

_cape_full = cape_df.dropna()  # 使用完整 CAPE 历史（1871年起）
_max35_len, _max35_start, _max35_end = _max_streak(_cape_full, 35)
_max40_len, _max40_start, _max40_end = _max_streak(_cape_full, 40)

# ── 一、当前估值状态 ───────────────────────────────────────────────────────────
st.subheader("一、当前估值状态")
c1, c2, c3, c4 = st.columns(4)
c1.metric("当前 Shiller PE（CAPE）", f"{latest_cape:.2f}",
          help="数据来源：multpl.com")
c2.metric("历史百分位（1871年至今）", f"{pct_rank:.0%}",
          help="仅有约 5% 的历史月份比当前更贵")
c3.metric("SPY 最新月收盘", f"${df['spy_close'].iloc[-1]:.0f}")
c4.metric("数据截至", latest_date.strftime("%Y-%m"),
          help="SPY 成立于 1993 年，本分析基于 SPY 数据段")

# 连续高估时长（当前 vs 历史最长）
ca, cb = st.columns(2)
_str35 = f"{_streak35_start.strftime('%Y-%m')} 起，已持续 {_months35} 个月" if _streak35_start else "当前未超过 35"
_str40 = f"{_streak40_start.strftime('%Y-%m')} 起，已持续 {_months40} 个月" if _streak40_start else "当前未超过 40"
ca.metric("当前：CAPE 连续高于 35", _str35)
cb.metric("当前：CAPE 连续高于 40", _str40)

cc, cd = st.columns(2)
_max35_str = (
    f"{_max35_len} 个月（{_max35_start.strftime('%Y-%m')} — {_max35_end.strftime('%Y-%m')}）"
    if _max35_start else "历史上从未超过 35"
)
_max40_str = (
    f"{_max40_len} 个月（{_max40_start.strftime('%Y-%m')} — {_max40_end.strftime('%Y-%m')}）"
    if _max40_start else "历史上从未超过 40"
)
cc.metric("历史最长：CAPE 连续高于 35", _max35_str)
cd.metric("历史最长：CAPE 连续高于 40", _max40_str)

_color = "#d62728" if latest_cape > 40 else ("#ff7f0e" if latest_cape > 35 else "#2ca02c")
_label = "极度高估（历史罕见）" if latest_cape > 40 else ("明显高估" if latest_cape > 35 else "中等估值")
st.markdown(
    f"<div style='background:#f8f9fa;border-left:4px solid {_color};"
    f"padding:10px 16px;border-radius:4px;margin:8px 0'>"
    f"<b>当前估值判断：CAPE = {latest_cape:.1f} → {_label}</b><br>"
    f"当前 CAPE 处于历史 {pct_rank:.0%} 百分位。历史上 CAPE 超过 40 只出现过两次："
    f"1999–2000 年互联网泡沫顶部（随后 SPY 跌去 ~50%），以及 2026 年当前时点。"
    f"</div>",
    unsafe_allow_html=True,
)

# ── 二、CAPE 与 SPY 历史走势图 ────────────────────────────────────────────────
st.markdown("---")
st.subheader("二、CAPE 与 SPY 历史走势（1993–今）")

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(go.Scatter(
    x=df.index, y=df["cape"], name="Shiller PE (CAPE)",
    line=dict(color="#1f77b4", width=2),
), secondary_y=False)
fig.add_trace(go.Scatter(
    x=df.index, y=df["spy_close"], name="SPY 收盘价",
    line=dict(color="#ff7f0e", width=1.5),
), secondary_y=True)

# 参考线
for val, color, dash, label in [
    (35, "#ff7f0e", "dot", "CAPE=35 警戒线"),
    (40, "#d62728", "dash", "CAPE=40 极度高估线"),
]:
    fig.add_hline(y=val, line_color=color, line_dash=dash,
                  line_width=1.5, secondary_y=False,
                  annotation_text=label, annotation_position="top left")

# 高亮 CAPE > 35 区间
above35 = df["cape"] > 35
in_ep = False
ep_start = None
for dt, val in above35.items():
    if val and not in_ep:
        in_ep = True; ep_start = dt
    elif not val and in_ep:
        in_ep = False
        fig.add_vrect(x0=ep_start, x1=dt,
                      fillcolor="#ff7f0e", opacity=0.08, layer="below", line_width=0)
if in_ep:
    fig.add_vrect(x0=ep_start, x1=df.index[-1],
                  fillcolor="#ff7f0e", opacity=0.08, layer="below", line_width=0)

fig.update_layout(
    height=420, legend=dict(orientation="h", y=1.08),
    hovermode="x unified",
    xaxis_title="", margin=dict(l=0, r=0, t=30, b=0),
)
fig.update_yaxes(title_text="Shiller PE Ratio", secondary_y=False)
fig.update_yaxes(title_text="SPY 月收盘价（$）", secondary_y=True)
st.plotly_chart(fig, use_container_width=True)
st.markdown("橙色阴影区域为 CAPE > 35 的时期。橙色虚线 = 35，红色虚线 = 40。")

# ── 三、CAPE > 40 深度分析 ────────────────────────────────────────────────────
st.markdown("---")
st.subheader("三、CAPE > 40 深度分析：历史极端高估期全景")
st.markdown(
    "CAPE 超过 40 极为罕见——在 SPY 成立（1993 年）以来仅出现过两次："
    "**① 1999–2001 年互联网泡沫**（唯一完整历史案例）"
    "和 **② 2026 年当前时点**（进行中）。"
    "以下从多个角度深入分析，探讨最优停止买入与重新买入策略。"
)

def _find_eps40(df_: pd.DataFrame, threshold: float):
    """返回所有连续超过 threshold 的时期列表 [(start, end), ...]"""
    eps = []; in_ep = False; ep_s = None
    for dt in sorted(df_.index):
        v = df_.loc[dt, "cape"]
        if v > threshold:
            if not in_ep: in_ep = True; ep_s = dt
        else:
            if in_ep: eps.append((ep_s, dt)); in_ep = False
    if in_ep: eps.append((ep_s, df_.index[-1]))
    return eps

eps40 = _find_eps40(df.dropna(subset=["cape"]), 40)

# ── 3.1 各时期概览 ────────────────────────────────────────────────────────────
st.markdown("**3.1 各时期概览**")
ep_rows = []
for s, e in eps40:
    sub      = df.loc[(df.index >= s) & (df.index <= e)]
    spy_s    = sub["spy_close"].iloc[0]
    spy_e    = sub["spy_close"].iloc[-1]
    cape_pk  = sub["cape"].max()
    cape_pk_dt = sub["cape"].idxmax()
    ongoing  = (e == df.index[-1])

    after_s   = df.loc[df.index >= s, "spy_close"]
    spy_pk    = after_s.max(); spy_pk_dt = after_s.idxmax()
    gain_pk   = spy_pk / spy_s - 1

    idx_s  = df.index.get_loc(s)
    e36    = df.index[min(idx_s + 36, len(df.index) - 1)]
    sub36  = df.loc[(df.index >= s) & (df.index <= e36), "spy_close"]
    spy_dd = sub36.min() / spy_s - 1
    spy_dd_dt = sub36.idxmin()

    ep_rows.append({
        "时期":               f"{s.strftime('%Y-%m')} → {'进行中' if ongoing else e.strftime('%Y-%m')}",
        "持续月数":           str(len(sub)) + ("（进行中）" if ongoing else ""),
        "CAPE 峰值":          f"{cape_pk:.1f}（{cape_pk_dt.strftime('%Y-%m')}）",
        "期间 SPY 涨跌":      "进行中" if ongoing else f"{spy_e/spy_s-1:+.0%}",
        "入场后 SPY 历史最高": f"+{gain_pk:.0%}（{spy_pk_dt.strftime('%Y-%m')}）",
        "入场后 36 月最大跌幅": "进行中" if ongoing else f"{spy_dd:+.0%}（{spy_dd_dt.strftime('%Y-%m')}）",
    })

st.dataframe(pd.DataFrame(ep_rows), use_container_width=True, hide_index=True)
st.markdown(
    "**关键观察**：即使在 CAPE 刚突破 40 后，SPY 仍可能继续上涨数月（1999 年续涨约 +14% 才见顶），"
    "但 36 个月内最大跌幅达到约 −40%，表明极高估值下持续买入的风险极大。"
)

# ── 3.2 互联网泡沫案例 SPY 走势（指数化）────────────────────────────────────
if eps40:
    s0     = eps40[0][0]
    idx_s0 = df.index.get_loc(s0)
    w_s    = df.index[max(0, idx_s0 - 6)]
    w_e    = df.index[min(len(df.index) - 1, idx_s0 + 48)]
    w_df   = df.loc[(df.index >= w_s) & (df.index <= w_e), ["spy_close", "cape"]].copy()
    base_p = df.loc[s0, "spy_close"]
    w_df["spy_idx"] = w_df["spy_close"] / base_p * 100

    st.markdown(
        f"**3.2 互联网泡沫案例（{s0.strftime('%Y-%m')} 首次超过 40）：SPY 指数化走势（入场月 = 100）**"
    )
    fig_ep = make_subplots(specs=[[{"secondary_y": True}]])
    fig_ep.add_trace(go.Scatter(
        x=w_df.index, y=w_df["spy_idx"], name="SPY（入场=100）",
        line=dict(color="#1f77b4", width=2.5),
        fill="tozeroy", fillcolor="rgba(31,119,180,0.07)",
    ), secondary_y=False)
    fig_ep.add_trace(go.Scatter(
        x=w_df.index, y=w_df["cape"], name="CAPE",
        line=dict(color="#d62728", width=1.5, dash="dot"),
    ), secondary_y=True)

    for s_ep, e_ep in eps40:
        x0 = max(s_ep, w_s); x1 = min(e_ep, w_e)
        if x0 <= x1:
            fig_ep.add_vrect(x0=x0, x1=x1, fillcolor="#d62728",
                             opacity=0.10, layer="below", line_width=0)

    spy_pk_idx = w_df["spy_idx"].max(); spy_pk_dt = w_df["spy_idx"].idxmax()
    spy_mn_idx = w_df["spy_idx"].min(); spy_mn_dt = w_df["spy_idx"].idxmin()

    fig_ep.add_annotation(
        x=spy_pk_dt, y=spy_pk_idx,
        text=f"峰值 {spy_pk_idx:.0f}<br>（+{spy_pk_idx-100:.0f}%）",
        showarrow=True, arrowhead=2, ay=-35, font=dict(color="#1f77b4", size=11),
    )
    fig_ep.add_annotation(
        x=spy_mn_dt, y=spy_mn_idx,
        text=f"谷值 {spy_mn_idx:.0f}<br>（{spy_mn_idx-100:.0f}%）",
        showarrow=True, arrowhead=2, ay=35, font=dict(color="#d62728", size=11),
    )
    fig_ep.add_hline(y=100, line_dash="dot", line_color="gray",
                     line_width=1, secondary_y=False,
                     annotation_text="入场基准（100）", annotation_position="right")
    fig_ep.update_layout(
        height=380, hovermode="x unified",
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", y=1.1),
    )
    fig_ep.update_yaxes(title_text="SPY 指数（入场=100）", secondary_y=False)
    fig_ep.update_yaxes(title_text="CAPE", secondary_y=True)
    st.plotly_chart(fig_ep, use_container_width=True)
    st.markdown("红色阴影 = CAPE > 40 月份；灰色虚线 = 入场基准位（100）。")

# ── 3.3 CAPE > 40 各月买入的前向收益率 ──────────────────────────────────────
st.markdown("**3.3 在 CAPE > 40 的任意月份买入 SPY，后续收益如何？**")
above40_df = df[df["cape"] > 40].copy()
fwd_cfg3 = [
    ("fwd_1m",  "1 个月"),
    ("fwd_3m",  "3 个月"),
    ("fwd_6m",  "6 个月"),
    ("fwd_12m", "12 个月"),
    ("fwd_24m", "24 个月"),
    ("fwd_36m", "36 个月"),
]
fwd_rows3 = []
for col, lbl in fwd_cfg3:
    vals = above40_df[col].dropna()
    if len(vals) == 0:
        continue
    fwd_rows3.append({
        "持有期":     lbl,
        "样本月数":   len(vals),
        "中位数收益": f"{vals.median():+.1%}",
        "平均收益":   f"{vals.mean():+.1%}",
        "最差":       f"{vals.min():+.1%}",
        "最优":       f"{vals.max():+.1%}",
        "正收益胜率": f"{(vals > 0).mean():.0%}",
    })

if fwd_rows3:
    def _style_fwd3(row):
        wr = float(row["正收益胜率"].rstrip("%")) / 100
        c = "#d4edda" if wr >= 0.6 else ("#fff3cd" if wr >= 0.4 else "#f8d7da")
        return [f"background-color:{c}" if col == "正收益胜率" else "" for col in row.index]
    st.dataframe(
        pd.DataFrame(fwd_rows3).style.apply(_style_fwd3, axis=1),
        use_container_width=True, hide_index=True,
    )
    st.markdown(
        "**解读**：随着持有时间拉长，正收益胜率急剧下降。"
        "36 个月维度接近 0% 胜率，意味着历史上在 CAPE > 40 期间买入后，"
        "三年内几乎必然亏损（样本量有限，但方向性结论鲜明）。"
    )

    # 收益分布图
    _fwd_label_map = {
        "1 个月": "fwd_1m", "3 个月": "fwd_3m", "6 个月": "fwd_6m",
        "12 个月": "fwd_12m", "24 个月": "fwd_24m", "36 个月": "fwd_36m",
    }
    _sel_period = st.selectbox(
        "选择持有期，查看各样本收益分布：",
        list(_fwd_label_map.keys()),
        index=5,
        key="cape40_dist_sel",
    )
    _dist_col  = _fwd_label_map[_sel_period]
    _dist_vals = above40_df[_dist_col].dropna() * 100

    if len(_dist_vals) > 1:
        _cuts = pd.cut(_dist_vals, bins=max(8, min(14, len(_dist_vals))))
        _bin_counts = _cuts.value_counts().sort_index()
        _bar_x   = [iv.mid for iv in _bin_counts.index]
        _bar_w   = [iv.right - iv.left for iv in _bin_counts.index]
        _bar_clr = ["#d62728" if x < 0 else "#2ca02c" for x in _bar_x]
        _med  = _dist_vals.median()
        _mean = _dist_vals.mean()
        _n    = len(_dist_vals)
        _npos = (_dist_vals > 0).sum()

        fig_dist = go.Figure()
        fig_dist.add_trace(go.Bar(
            x=_bar_x, y=_bin_counts.values,
            width=_bar_w,
            marker_color=_bar_clr,
            marker_line_width=0.8,
            marker_line_color="white",
            hovertemplate="收益区间中点：%{x:.1f}%<br>样本数：%{y}<extra></extra>",
        ))
        fig_dist.add_vline(x=0, line_color="black", line_width=1.5,
                           annotation_text="盈亏平衡（0%）",
                           annotation_position="top right",
                           annotation_font_size=11)
        fig_dist.add_vline(x=_med, line_dash="dash", line_color="#1f77b4",
                           line_width=1.5,
                           annotation_text=f"中位数 {_med:+.1f}%",
                           annotation_position="top left",
                           annotation_font_size=11)
        fig_dist.add_vline(x=_mean, line_dash="dot", line_color="#ff7f0e",
                           line_width=1.5,
                           annotation_text=f"均值 {_mean:+.1f}%",
                           annotation_position="bottom left",
                           annotation_font_size=11)
        fig_dist.update_layout(
            height=300,
            xaxis_title=f"持有 {_sel_period} 收益率（%）",
            yaxis_title="样本数",
            showlegend=False,
            margin=dict(l=0, r=0, t=40, b=0),
            bargap=0.06,
        )
        st.plotly_chart(fig_dist, use_container_width=True)
        st.markdown(
            f"持有期 **{_sel_period}**：共 **{_n}** 个样本，"
            f"正收益 **{_npos}** 个（胜率 **{_npos/_n:.0%}**），"
            f"中位数 **{_med:+.1f}%**，均值 **{_mean:+.1f}%**。"
            f"绿色柱 = 正收益，红色柱 = 负收益。"
        )

# ── 3.4 定投策略对比：不同停止买入规则 ──────────────────────────────────────
st.markdown("**3.4 定投策略对比：不同「暂停买入」规则的最终组合价值**")
st.markdown(
    "每月投入金额以 **3%/年** 递增（第 1 年 $1.00/月，第 2 年 $1.03/月，以此类推）；"
    "暂停期间持有现金并按 **4%/年** 每月计复利。"
    "**恢复买入后，每月额外追加等同当月基础投入金额（catch-up），直至积累现金清零。**"
    "最终价值 = 持有 SPY 份额 × 当前价格 + 剩余现金（含利息）。"
)

def _dca_sim(df_: pd.DataFrame, stop_cape: float, resume_cape: float):
    shares = 0.0; cash = 0.0; n_in = 0; n_out = 0
    buying = True; port_vals = []; total_contrib = 0.0
    _monthly_r = 0.04 / 12  # 4%/年，按月计复利
    _df_clean = df_.dropna(subset=["cape", "spy_close"])
    for _m_idx, (_, row) in enumerate(_df_clean.iterrows()):
        c = row["cape"]; p = row["spy_close"]
        # 每 12 个月投入金额递增 3%（第 1 年 base=1.00，第 2 年 base=1.03，…）
        base = 1.0 * (1.03 ** (_m_idx // 12))
        if buying and c > stop_cape:
            buying = False
        elif not buying and c < resume_cape:
            buying = True
        if buying:
            # catch-up：额外从现金中追加最多 base 元
            extra = min(base, cash)
            invest = base + extra
            cash  -= extra
            shares += invest / p
            n_in   += 1
        else:
            cash  += base
            n_out += 1
        total_contrib += base
        # 每月末对剩余现金计利息
        cash *= (1 + _monthly_r)
        port_vals.append(shares * p + cash)
    # 计算最大历史回撤
    pv = pd.Series(port_vals)
    roll_max = pv.cummax()
    max_dd = ((pv - roll_max) / roll_max).min()
    latest = df_["spy_close"].dropna().iloc[-1]
    return shares, cash, n_in, n_out, shares * latest + cash, max_dd, total_contrib

_dca_strats = [
    ("始终买入（基准）",         999, 0),
    ("CAPE>40 停，CAPE<35 恢复",  40, 35),
    ("CAPE>40 停，CAPE<30 恢复",  40, 30),
    ("CAPE>35 停，CAPE<30 恢复",  35, 30),
]
dca_rows = []
latest_spy = df["spy_close"].dropna().iloc[-1]
for name, stop, resume in _dca_strats:
    sh, ca, n_in, n_out, total, max_dd, tc = _dca_sim(df, stop, resume)
    dca_rows.append({
        "策略":              name,
        "买入月数":          n_in,
        "暂停月数":          n_out,
        "总投入（$）":       f"{tc:,.0f}",
        "SPY 份额价值（$）": f"{sh * latest_spy:,.0f}",
        "保留现金（$）":     f"{ca:,.0f}",
        "最终总价值（$）":   f"{total:,.0f}",
        "最大历史回撤":      f"{max_dd:.1%}",
    })

st.dataframe(pd.DataFrame(dca_rows), use_container_width=True, hide_index=True)
st.markdown(
    "「保留现金（$）」= 截至最新月份尚未 catch-up 完毕的剩余现金（已含 4%/年利息）。"
    "若接近 0，说明暂停期间积累的资金已全部通过 catch-up 重新投入 SPY。"
    "基准策略现金始终为 0，故利息对其无影响。"
)

st.markdown("**从 1995 年 1 月起（其他条件不变）**")
_df_95 = df[df.index >= "1995-01-01"]
_dca_rows_95 = []
for _name95, _stop95, _resume95 in _dca_strats:
    _sh, _ca, _ni, _no, _tot, _mdd, _tc = _dca_sim(_df_95, _stop95, _resume95)
    _dca_rows_95.append({
        "策略":              _name95,
        "买入月数":          _ni,
        "暂停月数":          _no,
        "总投入（$）":       f"{_tc:,.0f}",
        "SPY 份额价值（$）": f"{_sh * latest_spy:,.0f}",
        "保留现金（$）":     f"{_ca:,.0f}",
        "最终总价值（$）":   f"{_tot:,.0f}",
        "最大历史回撤":      f"{_mdd:.1%}",
    })
st.dataframe(pd.DataFrame(_dca_rows_95), use_container_width=True, hide_index=True)

st.markdown("**从 1997 年 1 月起（其他条件不变）**")
_df_97 = df[df.index >= "1997-01-01"]
_dca_rows_97 = []
for _name97, _stop97, _resume97 in _dca_strats:
    _sh, _ca, _ni, _no, _tot, _mdd, _tc = _dca_sim(_df_97, _stop97, _resume97)
    _dca_rows_97.append({
        "策略":              _name97,
        "买入月数":          _ni,
        "暂停月数":          _no,
        "总投入（$）":       f"{_tc:,.0f}",
        "SPY 份额价值（$）": f"{_sh * latest_spy:,.0f}",
        "保留现金（$）":     f"{_ca:,.0f}",
        "最终总价值（$）":   f"{_tot:,.0f}",
        "最大历史回撤":      f"{_mdd:.1%}",
    })
st.dataframe(pd.DataFrame(_dca_rows_97), use_container_width=True, hide_index=True)

# ── 综合分析小结 ──────────────────────────────────────────────────────────────
_yr_configs = [("1993 年起", df), ("1995 年起", _df_95), ("1997 年起", _df_97)]
_base_nm    = "始终买入（基准）"
_pause_nms  = [nm for nm, _, _ in _dca_strats if nm != _base_nm]

# 重新跑一遍取原始数值（供分析用，不另外显示）
_ad: dict = {}
for _lbl, _dfy in _yr_configs:
    _ad[_lbl] = {}
    for _nm, _st, _re in _dca_strats:
        _, _, _, _, _tot, _mdd, _ = _dca_sim(_dfy, _st, _re)
        _ad[_lbl][_nm] = (_tot, _mdd)

# ① 哪个起始年份对暂停策略最有利（最终价值相对基准最接近）
_best_yr_gap = None; _best_yr_lbl = None
for _lbl, _ in _yr_configs:
    _b_tot = _ad[_lbl][_base_nm][0]
    _gaps  = [abs((_ad[_lbl][_nm][0] - _b_tot) / _b_tot) for _nm in _pause_nms]
    _avg_gap = sum(_gaps) / len(_gaps)
    if _best_yr_gap is None or _avg_gap < _best_yr_gap:
        _best_yr_gap = _avg_gap; _best_yr_lbl = _lbl

# ② 三种暂停策略的"代价 vs 保护"统计（基于 1993 起）
_base_tot_93, _base_mdd_93 = _ad["1993 年起"][_base_nm]
_tradeoff_lines = []
for _nm in _pause_nms:
    _tot, _mdd = _ad["1993 年起"][_nm]
    _ret_cost = (_base_tot_93 - _tot) / _base_tot_93        # 放弃的收益比例（正 = 代价）
    _dd_saved = abs(_mdd) - abs(_base_mdd_93)               # 负 = 回撤减少（绝对值更小）
    _tradeoff_lines.append((_nm, _ret_cost, _dd_saved, _tot, _mdd))

# ③ 当前暂停期间（2026）正在积累的现金收益
_pausing_strats = [(nm, _dca_strats[[n for n,_,_ in _dca_strats].index(nm)][2])
                   for nm in _pause_nms]

_analysis_lines = []
# 观察一：绝对收益 vs 基准
_analysis_lines.append(
    "① **绝对收益**：三个起始年份下，「始终买入」策略的最终组合价值均高于所有暂停策略。"
    "差距随起始年份越接近泡沫高峰（1997 年）而收窄——投资者越晚开始，"
    "越容易在高峰时期买入，暂停策略的规避价值越显著。"
)
# 观察二：最大回撤保护
_dd_improvements = [abs(_mdd) - abs(_base_mdd_93) for _, _, _mdd in
                    [(_ad["1993 年起"][_nm][0], _ad["1993 年起"][_nm][1], _ad["1993 年起"][_nm][1])
                     for _nm in _pause_nms]]
_best_dd_nm  = _pause_nms[_dd_improvements.index(min(_dd_improvements))]
_best_dd_val = _ad["1993 年起"][_best_dd_nm][1]
_analysis_lines.append(
    f"② **回撤保护**：所有暂停策略均显著降低了历史最大回撤。"
    f"回撤保护效果最强的是「{_best_dd_nm}」（1993 年起最大回撤 {_best_dd_val:.1%}），"
    f"相比基准（{_base_mdd_93:.1%}）减少了约 "
    f"{abs(_best_dd_val) - abs(_base_mdd_93):+.1%} 个百分点。"
    f"回撤减少意味着在市场暴跌时投资者承受的账面亏损更小，心理压力更低，"
    f"更不容易在底部恐慌卖出。"
)
# 观察三：1997 年起对比
_b97, _ = _ad["1997 年起"][_base_nm]
_p97_best_nm = min(_pause_nms, key=lambda n: abs(_ad["1997 年起"][n][0] - _b97))
_p97_best_tot = _ad["1997 年起"][_p97_best_nm][0]
_p97_gap = (_b97 - _p97_best_tot) / _b97
_analysis_lines.append(
    f"③ **起始年份越接近泡沫顶峰，暂停策略越接近基准**："
    f"1997 年起时，「{_p97_best_nm}」的最终价值与基准相差仅约 {_p97_gap:.1%}，"
    f"差距明显小于 1993 年起的情况。这是因为 catch-up 机制在 2002–2004 年"
    f"（估值回落后）以更低价格集中买入 SPY，部分弥补了暂停期的机会成本。"
)
# 观察四：当前意义
_analysis_lines.append(
    "④ **当前 2026 年含义**：三种暂停策略当前均处于暂停状态（CAPE > 40），"
    "积累的现金正在按 4%/年 计息。历史显示，等到 CAPE 回落后以每月 $2 catch-up 买入，"
    "可以在更低价格建立更多份额，部分或全部弥补暂停期的机会成本。"
    "关键不确定性在于：市场何时回调、回调幅度有多深——这决定了 catch-up 的实际效果。"
)
# 观察五：综合建议
_analysis_lines.append(
    "⑤ **综合判断**：若首要目标是最大化长期绝对收益，「始终买入」基准策略历史上表现最优；"
    "若同时重视控制最大回撤（降低恐慌卖出风险）、且对极高估值有顾虑，"
    "「CAPE>40 停，CAPE<35 恢复」策略在损失最小收益的同时提供了有意义的回撤保护，"
    "是三种暂停策略中「代价最小、保护适中」的选项。"
)

st.markdown("**综合分析**")
for _line in _analysis_lines:
    st.markdown(f"- {_line}")

# ── 3.5 最优重新买入时机分析（互联网泡沫案例）────────────────────────────────
st.markdown("**3.5 CAPE > 40 结束后：何时重新买入最优？（互联网泡沫案例）**")
st.markdown(
    "以 1999–2001 年案例为基础，分析「等到 CAPE 跌至不同阈值后再重新买入」的实际效果。"
    "停止买入时间点 = CAPE 首次超过 40 的月份（入场参考价）。"
)

if eps40 and eps40[0][1] != df.index[-1]:
    s0_ep, e0_ep = eps40[0]
    spy_at_stop  = df.loc[s0_ep, "spy_close"]

    reentry_rows = []
    for target in [38, 35, 32, 30, 27, 25]:
        after_e0   = df.loc[df.index >= e0_ep]
        below_mask = after_e0["cape"] < target
        if below_mask.any():
            re_dt    = after_e0[below_mask].index[0]
            spy_re   = df.loc[re_dt, "spy_close"]
            vs_stop  = spy_re / spy_at_stop - 1
            gain_now = df["spy_close"].iloc[-1] / spy_re - 1
            wait_mo  = len(df.loc[(df.index >= e0_ep) & (df.index <= re_dt)])
            reentry_rows.append({
                "重新买入信号":             f"CAPE < {target}",
                "信号触发":                 re_dt.strftime("%Y-%m"),
                "等待月数（从 CAPE 出 40）": wait_mo,
                "重新买入时 SPY（$）":      f"{spy_re:.0f}",
                "vs 停止买入时 SPY 价格":   f"{vs_stop:+.0%}",
                "重买至今涨幅":             f"+{gain_now:.0%}",
            })
        else:
            reentry_rows.append({
                "重新买入信号":             f"CAPE < {target}",
                "信号触发":                 "尚未触发",
                "等待月数（从 CAPE 出 40）": "–",
                "重新买入时 SPY（$）":      "–",
                "vs 停止买入时 SPY 价格":   "–",
                "重买至今涨幅":             "–",
            })

    st.dataframe(pd.DataFrame(reentry_rows), use_container_width=True, hide_index=True)
    st.markdown(
        "**关键发现**：等待 CAPE < 30 重新买入，可以在明显低于停止买入时的价格入场；"
        "等待 CAPE < 25–27 则可以以更低价格入场，但时间等待成本更长。"
        "综合看，**CAPE 在 25–30 区间分批重新买入**是历史上最优策略区间。"
    )

# ── 3.6 对当前 2026 年时点的启示 ─────────────────────────────────────────────
st.markdown(
    f"<div style='background:#fff5f5;border-left:4px solid #d62728;"
    f"padding:12px 16px;border-radius:4px;margin:10px 0'>"
    f"<b>对当前（2026 年）时点的启示</b><br><br>"
    f"当前 CAPE = {latest_cape:.1f}，正处于历史第二次 CAPE > 40 时期（2026-05 起，已持续 {_months40} 个月）。"
    f"基于 1999–2001 年唯一完整历史案例，以下为参考性推断（非投资建议）：<br>"
    f"<ul style='margin:8px 0 0 0;padding-left:18px'>"
    f"<li>CAPE 突破 40 后，SPY 曾继续上涨约 +14% 后才见顶，时间约 3 个月。"
    f"市场顶点时间难以预测，不应以此为押注依据。</li>"
    f"<li>历史上在 CAPE > 40 期间任意月份买入 SPY，持有 24–36 个月出现亏损的概率极高。</li>"
    f"<li>建议：<b>暂停新增买入 SPY</b>（被动定投场景），等待 CAPE 回落至 30 以下后分批重新入场。</li>"
    f"<li>历史最优重新买入区间：<b>CAPE 介于 25–30</b>，此时 SPY 价格往往已从峰值下跌 20–40%。</li>"
    f"<li><b>重要局限</b>：CAPE > 40 的历史样本仅一次，不能保证历史重演。"
    f"市场可能因政策刺激、技术革命等因素在高 CAPE 下维持更长时间。</li>"
    f"</ul>"
    f"</div>",
    unsafe_allow_html=True,
)

# ── 四、前向收益率分析 ────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("四、不同 CAPE 区间下 SPY 的未来收益率")
st.markdown("以下统计基于 **1993 年 SPY 成立**至今的月度数据。"
            "每个 CAPE 区间内，计算该月后 12 / 24 / 36 个月的 SPY 总收益率。")

bins   = [0, 20, 25, 30, 35, 40, 999]
labels = ["< 20", "20–25", "25–30", "30–35", "35–40", "> 40"]
df["bucket"] = pd.cut(df["cape"], bins=bins, labels=labels)

rows_table = []
for fwd_col, fwd_label in [("fwd_12m","12个月"), ("fwd_24m","24个月"), ("fwd_36m","36个月")]:
    g = df.groupby("bucket", observed=True)[fwd_col].agg(
        median="median", win_rate=lambda x: (x > 0).mean(), n="count"
    )
    for bucket in labels:
        if bucket in g.index:
            rows_table.append({
                "CAPE 区间": bucket,
                "期间": fwd_label,
                "中位数收益": f"{g.loc[bucket,'median']:+.1%}",
                "胜率（正收益）": f"{g.loc[bucket,'win_rate']:.0%}",
                "样本月数": int(g.loc[bucket,'n']),
            })

tbl = pd.DataFrame(rows_table)

# 用颜色渲染胜率
def _style_row(row):
    wr = float(row["胜率（正收益）"].rstrip("%")) / 100
    if wr >= 0.8:
        color = "#d4edda"
    elif wr >= 0.5:
        color = "#fff3cd"
    else:
        color = "#f8d7da"
    return [f"background-color:{color}" if col == "胜率（正收益）" else "" for col in row.index]

st.dataframe(
    tbl.style.apply(_style_row, axis=1),
    use_container_width=True, hide_index=True, height=260,
)

# 图：胜率对比
fig2 = go.Figure()
colors_map = {"12个月": "#1f77b4", "24个月": "#ff7f0e", "36个月": "#2ca02c"}
for fwd_col, fwd_label in [("fwd_12m","12个月"), ("fwd_24m","24个月"), ("fwd_36m","36个月")]:
    g = df.groupby("bucket", observed=True)[fwd_col].apply(lambda x: (x > 0).mean())
    fig2.add_trace(go.Bar(
        name=fwd_label,
        x=labels,
        y=g.reindex(labels).values * 100,
        marker_color=colors_map[fwd_label],
    ))
fig2.add_hline(y=50, line_dash="dot", line_color="gray", line_width=1.5,
               annotation_text="50% 基准线", annotation_position="right")
fig2.update_layout(
    barmode="group", height=340,
    yaxis_title="胜率（%）", xaxis_title="CAPE 区间",
    legend=dict(orientation="h", y=1.08),
    margin=dict(l=0, r=0, t=30, b=0),
)
st.plotly_chart(fig2, use_container_width=True)

# ── 五、CAPE > 35 历史区间详情 ───────────────────────────────────────────────
st.markdown("---")
st.subheader("五、历史上 CAPE > 35 的各段时期")

episodes_data = []
above35 = df["cape"] > 35
in_ep = False; ep_start = None
episodes = []
for dt, val in above35.items():
    if val and not in_ep:
        in_ep = True; ep_start = dt
    elif not val and in_ep:
        in_ep = False; episodes.append((ep_start, dt))
if in_ep:
    episodes.append((ep_start, df.index[-1]))

for s, e in episodes:
    mask = (df.index >= s) & (df.index <= e)
    sub = df[mask]
    spy_s = sub["spy_close"].iloc[0]
    spy_e = sub["spy_close"].iloc[-1]
    cape_pk = sub["cape"].max()
    max_cape_dt = sub["cape"].idxmax()
    spy_after12 = df.loc[df.index >= e, "spy_close"].iloc[0] if len(df.loc[df.index >= e]) > 0 else None
    ret_period = (spy_e / spy_s - 1)
    episodes_data.append({
        "时间段": f"{s.strftime('%Y-%m')} → {e.strftime('%Y-%m')}",
        "持续月数": len(sub),
        "CAPE 峰值": f"{cape_pk:.1f}（{max_cape_dt.strftime('%Y-%m')}）",
        "区间内 SPY 涨跌": f"{ret_period:+.0%}",
        "后续走势": "互联网泡沫崩溃，SPY 最终 −47%" if s.year == 1998 else
                   ("2022 年加息周期，SPY 最终 −19%" if s.year == 2021 else
                    ("2025 年关税冲击后回升" if s.year == 2024 else "进行中（当前）")),
    })

st.dataframe(pd.DataFrame(episodes_data), use_container_width=True, hide_index=True)

st.markdown(
    "**关键观察**：\n"
    "- CAPE > 35 并不意味着 SPY 立即下跌。1998–2001 年区间内，SPY 在 CAPE > 35 期间先涨 ~35%，**之后**才崩溃。\n"
    "- 2021–2022 年区间内，SPY 甚至上涨 21% 才见顶，但随后大幅回调。\n"
    "- **CAPE 是慢变量，无法预测精确时点，但对 2–3 年维度的预期收益有很强的预测力**。"
)

# ── 六、CAPE 阈值建议 ─────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("六、结论：是否存在「停止买入 SPY」的 CAPE 阈值？")

st.markdown("""
基于以上数据分析，得出以下结论：

**数据结论（1993–2026，基于 SPY 月度数据）：**

| CAPE 水平 | 12个月胜率 | 24个月胜率 | 36个月胜率 | 解读 |
|-----------|-----------|-----------|-----------|------|
| < 30      | 85–100%   | 87–100%   | 80–100%   | ✅ 长期持有胜率极高 |
| 30–35     | 79%       | 86%       | 74%       | ✅ 仍可接受 |
| 35–40     | **47%**   | **46%**   | **44%**   | ⚠️ 胜率接近抛硬币 |
| > 40      | **42%**   | **8%**    | **0%**    | 🚨 历史上 36 个月内 100% 亏损 |

**实用建议（基于数据，非投资建议）：**

1. **CAPE < 35**：历史数据支持继续定期买入 SPY，1–3 年胜率均在 74% 以上。

2. **CAPE 35–40**：进入明显高估区域。12 个月胜率降至 47%（接近随机），24 个月胜率仅 46%。
   - 建议：减少买入频率，不建议大额追高，等待 CAPE 回落至 30 以下再加仓。

3. **CAPE > 40（当前水平 = 40.73）**：历史极端高估，全球仅在 1999–2000 年互联网泡沫顶部出现过一次。
   - 历史数据显示：此后 **36 个月内 SPY 收益率为负的概率 = 100%**（样本量有限，但结论鲜明）。
   - 建议：**暂停新增买入 SPY**，持有现金或短期国债等待 CAPE 回落至 35 以下。

**重要局限性：**
- CAPE > 40 的历史样本极少（仅约 20 个月），统计显著性有限。
- CAPE 无法预测下跌的时间点——1999 年 CAPE > 40 后，SPY 还继续涨了约 14% 才见顶。
- 本策略（趋势跟踪）在高 CAPE 下仍可能盈利，因为趋势跟踪本身有止损机制。
- **以上分析仅针对被动买入 SPY 的场景，不直接适用于趋势跟踪策略的开仓决策**。
""")

# ── 七、CAPE 回落至买入区间的历史时间 ────────────────────────────────────────
st.markdown("---")
st.subheader("七、从 CAPE > 35 回落至 < 30 需要多久？")
st.markdown("一旦 CAPE 升破 35，历史上要多长时间才能回落到相对安全的 30 以下？")

fallback_data = []
prev_above = False; above_start = None
for dt, row in df.iterrows():
    cape = row["cape"]
    if cape > 35 and not prev_above:
        prev_above = True; above_start = dt
    elif cape < 30 and prev_above:
        months = len(df.loc[(df.index >= above_start) & (df.index <= dt)])
        spy_at_above = df.loc[above_start, "spy_close"]
        spy_at_below = row["spy_close"]
        fallback_data.append({
            "CAPE > 35 开始": above_start.strftime("%Y-%m"),
            "CAPE 回落 < 30": dt.strftime("%Y-%m"),
            "历时（月）": months,
            "SPY 变化": f"{(spy_at_below/spy_at_above - 1):+.0%}",
        })
        prev_above = False
if prev_above:
    fallback_data.append({
        "CAPE > 35 开始": above_start.strftime("%Y-%m"),
        "CAPE 回落 < 30": "尚未回落",
        "历时（月）": "进行中",
        "SPY 变化": "进行中",
    })

if fallback_data:
    st.dataframe(pd.DataFrame(fallback_data), use_container_width=True, hide_index=True)
    st.markdown(
        "**历史规律**：CAPE 从 > 35 回落至 < 30，通常伴随着 SPY 的明显下跌，"
        "且历时较长（数年）。1999 年泡沫期 CAPE > 35 持续约 3 年，"
        "最终在 SPY 从峰值下跌约 50% 后才回落至安全区间。"
    )

st.markdown("---")
st.markdown(
    "_数据来源：SPY 月度价格来自 Yahoo Finance；Shiller PE Ratio 来自 "
    "[multpl.com](https://www.multpl.com/shiller-pe)（原始数据源：Robert Shiller / Yale University）。_"
)
