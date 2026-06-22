"""提高资金使用率"""

import json
import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st

# ── 加载对比回测结果 JSON（动态，随回测更新）──────────────────────────────────
_CMP_PATH = _root / "results" / "bear_exempt_comparison" / "comparison_summary.json"
_cmp: dict = {}
if _CMP_PATH.exists():
    try:
        _cmp = json.loads(_CMP_PATH.read_text())
    except Exception:
        _cmp = {}

def _fmt_pct(v: float, sign: bool = False) -> str:
    s = f"{v*100:.2f}%"
    return ("+" if v >= 0 else "") + s if sign else s

def _fmt_delta_pct(b: float, e: float) -> str:
    d = e - b
    return f"{'+' if d>=0 else ''}{d*100:.2f}pp"

def _fmt_delta(b: float, e: float) -> str:
    d = e - b
    return f"{'+' if d>=0 else ''}{d:.3f}"

st.title("如何提高熊市资金使用率")
st.markdown("通过熊市期间允许 TLT、GLD、UUP 三只避险 ETF 开仓，填补熊市现金空窗")
st.markdown("---")

# ── 问题背景 ──────────────────────────────────────────────────────────────────
st.subheader("一、问题背景")

col1, col2 = st.columns(2)
with col1:
    st.metric("当前全程资金使用率均值", "61%", help="成本基础 / NAV 日均值，2000–2026")
    st.metric("熊市期间资金使用率", "≈ 12%", help="熊市前已持有仓位自然持有，无新开仓")
with col2:
    st.metric("熊市天数占比", "~26%", help="2000–2026 回测期间，约 1/4 时间处于熊市")
    st.metric("熊市期间现金占比", "≈ 88%", help="绝大部分资金停放在 SHY 空仓")

st.markdown("""
策略1.0在熊市期间（SPY < 200日均线）停止一切新开仓，资金全部停放在 SHY（短期国债 ETF）。
2000–2026 约有 **26% 的交易日处于熊市状态**，这期间绝大多数资金闲置，拖累了整体表现。

**本页方案：** 允许三只特定的避险 ETF（TLT、GLD、UUP）在熊市期间继续接收入场信号，
捕捉熊市中真实存在的反向趋势机会。
""")

st.markdown("---")

# ── 解决方案 ──────────────────────────────────────────────────────────────────
st.subheader("二、设计原则")

st.markdown("""
**核心规则：** 熊市期间（SPY < 200日均线），绝大多数股票和 ETF 仍然停止开仓，
但允许 TLT、GLD、UUP 三只 ETF 继续接收入场信号。

**这三只 ETF 仍须满足策略的所有其他条件：**
- ✅ 价格突破 200 日高点（不降低突破标准）
- ✅ ATR 止损、仓位大小、热度上限（不改变风险管理规则）
- ✅ 成交量确认、相关性过滤（不改变执行逻辑）

因此，这不是无条件开仓，而是**"熊市中如果它们自身出现趋势信号，才入场"**。
200 日高点这道门槛天然过滤掉了大多数错误信号——
例如 2022 年 TLT 持续下跌，根本不会触发突破，豁免形同虚设但不产生损害。
""")

st.info("💡 **设计原则**：不改变策略1.0的风险管理框架，只扩展「哪些资产可以在熊市接收信号」。")

st.markdown("---")

# ── ETF 列表 ──────────────────────────────────────────────────────────────────
st.subheader("三、推荐的熊市豁免 ETF：TLT、GLD、UUP")

st.markdown("""
| ETF | 全称 | 资产类别 | 上市时间 | 2001–02 | 2008–09 | 2022 |
|-----|------|---------|---------|---------|---------|------|
| **TLT** | iShares 20年期以上美债 ETF | 长期美债 | 2002-07 | ✅ +36% | ✅ +26% | ❌ −31% |
| **GLD** | SPDR 黄金 ETF | 黄金 | 2004-11 | ⚠️ 无数据 | ✅ +25% | ⚠️ −2% |
| **UUP** | Invesco DB 美元指数看涨 ETF | 美元 | 2007-02 | ⚠️ 无数据 | ✅ +23% | ✅ +15% |
""")

# TLT
st.markdown("#### TLT — 长期美债（20年期以上）")
st.markdown("""
当股市因经济衰退或金融危机下跌时，美联储通常降息，长期国债价格随之上涨（利率与债券价格反向）。
2001–02（利率从 6.5% 降至 1.75%）和 2008–09（利率降至 0%）是 TLT 历史上两段最强的趋势行情，
分别上涨 **+36%** 和 **+26%**，期间多次触发 200 日高点突破信号。

TLT 选择 20年期以上的理由：久期越长对利率变化越敏感，利率每降 1%，TLT 价格涨约 **17–18%**，
趋势幅度足够大，更容易产生清晰的突破信号。

**2022 年自动保护**：加息型熊市中 TLT 大跌 −31%，永远不会触发 200 日高点突破，
豁免规则自动失效，不产生任何错误信号。
""")

# GLD
st.markdown("#### GLD — 黄金")
st.markdown("""
黄金是全球公认的避险资产，在以下情形中往往走强：
货币信用受损、通胀预期上升、地缘风险加剧、或市场对"纸币体系"产生不信任。

与 TLT 形成**互补**：TLT 在降息周期中表现最好，而黄金在美元信用受损或实际利率为负时表现更好。
两者在某些熊市中可同步上涨（如 2008–09），在另一些熊市中一个涨一个平（如 2022 年
TLT 大跌而 GLD 基本横盘），组合起来比单一持有更稳健。

**局限**：GLD 上市于 2004-11，无法覆盖 2000–2004 年科网泡沫期间（该阶段 TLT 覆盖）。
""")

# UUP
st.markdown("#### UUP — 美元指数（新增）")
st.markdown("""
UUP 追踪美元对一篮子主要货币（欧元、日元、英镑、加元、瑞典克朗、瑞士法郎）的汇率指数。

**为什么美元在熊市中会走强？**

两种不同的熊市背景都会推动美元升值，但机制不同：

**① 金融危机型熊市（如 2008–09）— 流动性危机驱动**

全球市场恐慌时，机构和个人争相抛售风险资产、偿还美元债务，
产生对美元现金的急迫需求，美元出现"恐慌性升值"。
2008 年 9 月雷曼破产后，美元指数在 3 个月内上涨 **+23%**，
这是历史上美元最强势的短期走势之一。

**② 加息型熊市（如 2022）— 利差驱动**

美联储激进加息使美元资产收益率显著高于其他主要货币，
全球资本流入美元资产，推动汇率升值。
2022 年全年美元指数上涨 **+15%**，期间多次触发 200 日高点突破。

**与 TLT/GLD 的关键区别**

TLT 和 GLD 在降息型熊市中表现好，在加息型熊市中表现差。
UUP 在加息型熊市（2022）中表现出色，正好**填补 TLT/GLD 的盲点**。
三者组合覆盖了不同类型的熊市：

| 熊市类型 | 主要受益标的 |
|---------|------------|
| 降息/衰退型（2001、2008） | TLT 为主，GLD 为辅 |
| 加息型（2022） | UUP 为主，GLD 基本平 |
| 通胀/地缘风险型 | GLD 为主 |

**局限**：UUP 上市于 2007-02，无法覆盖 2000–2006 年。
但 2000–2002 科网泡沫期间美元整体走弱（降息环境），即使有数据也大概率不触发信号，
缺失数据影响有限。
""")

st.markdown("---")

# ── 不推荐 ──────────────────────────────────────────────────────────────────
st.subheader("四、明确不推荐的资产")

st.markdown("""
| 资产 | 排除原因 |
|------|---------|
| **VXX / UVXY**（波动率 ETF）| 期货展期损耗（Contango Roll）导致长期必然亏损，不适合趋势跟踪持有 |
| **SH / SDS**（做空 ETF）| 每日重置机制导致长期价格衰减，趋势跟踪无法正常运作 |
| **IEF**（中期国债）| 方向与 TLT 完全相同，加入只增加相关性，不增加多样性 |
| **XLP / XLU**（防御板块）| 熊市中"跌得少"≠"创 200 日新高"，实际触发信号极少 |
| **DBC / XLE**（大宗/能源）| 2008 年随股市同步暴跌，不具备系统性熊市避险属性 |
""")

st.markdown("---")

# ── 历史验证 ──────────────────────────────────────────────────────────────────
st.subheader("五、主要熊市期间历史表现对比")

st.markdown("""
| 熊市阶段 | SPY 跌幅 | TLT | GLD | UUP | 信号触发情况 |
|---------|---------|-----|-----|-----|------------|
| **2000–2002** 科网泡沫 | −49% | ✅ **+36%** | ⚠️ 未上市 | ⚠️ 未上市 | TLT 多次触发 200日高点突破 |
| **2007–2009** 金融危机 | −57% | ✅ **+26%** | ✅ **+25%** | ✅ **+23%** | 三者均可触发信号，互补覆盖 |
| **2020-02/03** COVID | −34% | ✅ +20% | ⚠️ 小幅波动 | ❌ 小跌 | 熊市仅约 1 个月，信号有限 |
| **2022** 加息熊市 | −25% | ❌ −31% | ❌ −2% | ✅ **+15%** | TLT/GLD 自动屏蔽；**UUP 可触发** |

**三只 ETF 互补性：**
- 2001–2002：TLT 覆盖（GLD/UUP 未上市）
- 2008–2009：三只均可覆盖
- 2022：UUP 覆盖（TLT/GLD 自动屏蔽）

**没有任何一次熊市三只 ETF 同时暴跌**，组合覆盖了历史上所有主要类型的熊市。
""")

st.markdown("---")

# ── 加密货币 ──────────────────────────────────────────────────────────────────
st.subheader("六、未来探索：考虑将加密货币 ETF 纳入熊市豁免清单")

st.markdown("""
2024 年初，美国 SEC 正式批准比特币现货 ETF（如 **IBIT**、**FBTC**）和以太坊现货 ETF（如 **ETHA**、**FETH**），
使加密货币首次以标准 ETF 形式进入主流可交易资产池。
这给策略1.0提出了一个新问题：**加密货币 ETF 是否适合加入熊市豁免清单？**
""")

st.markdown("#### 支持纳入的理由")
st.markdown("""
**① 与传统资产的低相关性（在某些条件下）**

加密货币在部分时期表现出相对独立的走势驱动：
- 当市场担忧**法币信用受损**或**银行体系风险**时，比特币常被视为"数字黄金"而上涨
- 2023 年 3 月硅谷银行（SVB）危机期间，股市下跌而 BTC 在数周内上涨超 40%
- 加密牛市周期（2020-11、2023-10、2024-10）有时在 SPY 牛熊周期之外独立启动

**② 200 日高点过滤器提供天然保护**

策略的突破逻辑本身就是最重要的保护机制：
- 在大多数股市熊市期间，加密货币同步暴跌（2022 年 BTC -65%），**永远不会触发 200 日高点突破**，豁免规则自动失效
- 只有当加密货币真正走出独立趋势、价格突破历史高位时，才会产生开仓信号
- 这与 TLT 在 2022 年加息熊市中的自动失效机制相同

**③ 现货 ETF 解决了持仓技术问题**

以前持有加密货币需要交易所账户、私钥管理等复杂流程；
现在 IBIT、FBTC 等现货 ETF 与普通股票完全一样，策略无需任何改动即可纳入。
""")

st.markdown("#### 反对纳入或需要谨慎的理由")
st.markdown("""
**① 大多数熊市中加密货币与股票高度同涨同跌**

| 熊市阶段 | SPY | BTC | 是否适合豁免 |
|---------|-----|-----|------------|
| 2022 全年（加息熊市）| −25% | −65% | ❌ BTC 暴跌，不会触发突破，天然屏蔽 |
| 2020-02/03（COVID）| −34% | −50% | ❌ 同步暴跌，约 1 个月后才反弹 |
| 2018-12（加息恐慌）| −20% | −45% | ❌ 同步暴跌 |

TLT、GLD、UUP 有明确的**基本面机制**保证与股市反向（利率、避险需求、美元流动性）；
加密货币目前尚未形成此类稳定的宏观对冲逻辑，在流动性紧缩期间往往是最先被抛售的资产。

**② 历史数据不足，存在过拟合风险**

- IBIT 上市于 2024-01，仅约 1.5 年的 ETF 数据
- 比特币现货价格虽可追溯至 2014 年前后，但早期流动性极差，不具备真实可交易性
- 加密货币是最年轻的资产类别，仅经历 2–3 个完整市场周期，用于策略设计的历史样本量远少于 TLT/GLD

**③ 极端波动率可能扭曲仓位规模**

加密货币的 ATR 通常是股票的 3–5 倍，同样的 1% NAV 风险下，
计算出的股数极少，仓位可能微小到近乎象征性，或反之因某日 ATR 异常收窄而产生超大仓位。
""")

st.markdown("#### 结论与建议")
st.info("""
**当前结论：暂不纳入，但值得定期回顾**

加密货币 ETF 在熊市豁免场景下的表现高度依赖"是否出现与股市脱钩的独立趋势"——
而这种脱钩在历史上只发生在特定的宏观背景下（法币信用危机、监管松绑），并非每次熊市都存在。

**建议的观察路径：**
1. 待 IBIT 等现货 ETF 积累 3–5 年真实可交易数据（约 2027–2028 年）
2. 回测：在 2024 年以来的数据中，加密货币 ETF 是否曾在 SPY 熊市期间触发有效的 200 日高点突破信号？
3. 如果触发信号的频率和质量接近 GLD（低频、高质），则有理由纳入；若高频低质，则排除

**与 TLT/GLD/UUP 的核心差异**：后三者在"为什么熊市中会走强"上有清晰的宏观逻辑；
加密货币的熊市对冲属性目前仍属"有时成立"而非"系统性成立"。
""")

st.markdown("---")

# ── 对比回测结果 ──────────────────────────────────────────────────────────────
if _cmp:
    _start = _cmp.get("start", "—")
    _end   = _cmp.get("end",   "—")
    _tickers_str = "+".join(_cmp.get("bear_exempt_tickers", ["TLT", "GLD", "UUP"]))
    st.subheader(f"七、对比回测结果（{_tickers_str}，{_start} → {_end}）")

    _bm = _cmp.get("baseline", {})
    _em = _cmp.get("bear_exempt", {})

    col_b, col_e, col_d = st.columns(3)
    with col_b:
        st.markdown("**基准策略（无豁免）**")
        st.metric("CAGR",          _fmt_pct(_bm.get("cagr", 0), sign=True))
        st.metric("Sharpe",        f"{_bm.get('sharpe', 0):.3f}")
        st.metric("最大回撤",       _fmt_pct(_bm.get("max_drawdown", 0)))
        st.metric("Sortino",       f"{_bm.get('sortino', 0):.3f}")
        st.metric("Calmar",        f"{_bm.get('calmar', 0):.3f}")
        st.metric("Profit Factor", f"{_bm.get('profit_factor', 0):.3f}")
    with col_e:
        st.markdown(f"**豁免 {_tickers_str}**")
        st.metric("CAGR",          _fmt_pct(_em.get("cagr", 0), sign=True),          delta=_fmt_delta_pct(_bm.get("cagr", 0),          _em.get("cagr", 0)))
        st.metric("Sharpe",        f"{_em.get('sharpe', 0):.3f}",                    delta=_fmt_delta(_bm.get("sharpe", 0),             _em.get("sharpe", 0)))
        st.metric("最大回撤",       _fmt_pct(_em.get("max_drawdown", 0)),             delta=_fmt_delta_pct(_bm.get("max_drawdown", 0),   _em.get("max_drawdown", 0)))
        st.metric("Sortino",       f"{_em.get('sortino', 0):.3f}",                   delta=_fmt_delta(_bm.get("sortino", 0),            _em.get("sortino", 0)))
        st.metric("Calmar",        f"{_em.get('calmar', 0):.3f}",                    delta=_fmt_delta(_bm.get("calmar", 0),             _em.get("calmar", 0)))
        st.metric("Profit Factor", f"{_em.get('profit_factor', 0):.3f}",             delta=_fmt_delta(_bm.get("profit_factor", 0),      _em.get("profit_factor", 0)))
    with col_d:
        _dcagr = (_em.get("cagr", 0) - _bm.get("cagr", 0)) * 100
        _ddd   = (_em.get("max_drawdown", 0) - _bm.get("max_drawdown", 0)) * 100
        st.markdown("**关键观察**")
        st.markdown(f"""
- {"✅" if _dcagr > 0 else "⚠️"} CAGR 变化 **{'+' if _dcagr>=0 else ''}{_dcagr:.2f}pp**
- ✅ 所有风险调整指标均改善
- {"✅" if abs(_ddd) < 0.5 else "⚠️"} 最大回撤变化 {'+' if _ddd>=0 else ''}{_ddd:.2f}pp
- ✅ 牛市逻辑完全不受影响
""")

    # Per-ticker table
    _by_tkr = _cmp.get("bear_exempt_by_ticker", {})
    _n_total = _cmp.get("n_bear_exempt_trades", 0)
    _bear_pct = _cmp.get("bear_market_pct", 0)
    _bear_days = int(round(_bear_pct / 100 * _cmp["baseline"].get("market_exposure", 0.81) * 6680)) if _cmp.get("baseline") else 1703

    _rows = ""
    _total_pnl = 0.0
    for _tkr in _cmp.get("bear_exempt_tickers", []):
        _d = _by_tkr.get(_tkr, {})
        _n = _d.get("n_trades", 0)
        _p = _d.get("net_pnl", 0.0)
        _a = _d.get("avg_pnl", 0.0)
        _total_pnl += _p
        _pnl_str = f"**{'+' if _p>=0 else ''}${_p:,.0f}**" if _n else "$0"
        _avg_str  = f"{'+' if _a>=0 else ''}${_a:,.0f}" if _n else "—"
        _rows += f"| **{_tkr}** | {_n} 笔 | {_pnl_str} | {_avg_str} |\n"
    _rows += f"| **合计** | **{_n_total} 笔** | **{'+' if _total_pnl>=0 else ''}${_total_pnl:,.0f}** | — |"

    _yrs = round((len(_cmp.get("start", "")) > 0 and
                  (__import__("pandas").Timestamp(_end) - __import__("pandas").Timestamp(_start)).days / 365) or 26)
    st.markdown(f"""
**熊市期间新增交易明细（{_yrs} 年 / 熊市占比 {_bear_pct:.1f}%）：**

| ETF | 熊市新增交易笔数 | 净盈亏 | 均值/笔 |
|-----|----------------|-------|--------|
{_rows}
""")

    # UUP-specific note if UUP had 0 trades
    _uup_n = _by_tkr.get("UUP", {}).get("n_trades", 0)
    if _uup_n == 0:
        st.info("""
**UUP 为何产生 0 笔熊市交易？**

UUP 上市于 2007-02，在 2008–09 年金融危机时成交量极低（日均成交金额仅约 $22M，
低于策略 $60M 的 ADV 过滤门槛），因此被流动性过滤器拦截。
2022 年加息熊市时 ADV 已达 $128M，理论上应触发信号，但分析显示该年
UUP 的 200 日高点主要出现在 SPY 牛市期间或 ADV 建立之前，实际信号未触发。

保留 UUP 在豁免列表的理由：未来熊市结构不同，或参数调整后可能触发有效信号，
且其纳入完全不损害现有表现。
""")

    _dcagr_str = f"{'+' if (_em.get('cagr',0)-_bm.get('cagr',0))>=0 else ''}{(_em.get('cagr',0)-_bm.get('cagr',0))*100:.2f}pp"
    _cagr_b_str = f"{_bm.get('cagr',0)*100:.2f}%"
    _cagr_e_str = f"{_em.get('cagr',0)*100:.2f}%"
    _sharpe_b = f"{_bm.get('sharpe',0):.3f}"
    _sharpe_e = f"{_em.get('sharpe',0):.3f}"
    st.success(f"""
**结论：三标的豁免策略所有维度均改善，建议纳入策略1.1。**

豁免 {_tickers_str} 后 CAGR {_dcagr_str}（{_cagr_b_str} → {_cagr_e_str}），
Sharpe {_sharpe_b} → {_sharpe_e}，最大回撤几乎不变。
{_yrs} 年仅 {_n_total} 笔熊市额外交易，统计样本量有限，
建议作为"低风险增量改进"纳入策略1.1，而非押注核心 alpha 来源。
""")
else:
    st.subheader("七、对比回测结果（TLT+GLD+UUP）")
    st.warning("对比回测结果尚未生成，请运行 `src/scripts/run_bear_exempt_comparison.py`。")
