"""策略逻辑"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta
p    = meta.params_anchor

render_page_header("策略描述", meta)
st.markdown("---")

# ── Overview ──────────────────────────────────────────────────────────────────
st.subheader("策略概述")
st.markdown(f"""
本策略1.0是一个**经典动量突破型趋势跟踪策略1.0**，纯多头（Long Only），适用于股票和 ETF 市场。
核心理念源自 Richard Dennis 的海龟交易法则与 David Harding 的 AHL 系统：
**顺势而为，快速止损，让利润奔跑**。

| 维度 | 说明 |
|------|------|
| 策略类型 | 趋势跟踪（Trend Following）|
| 方向 | 纯多头（Long Only） |
| 入场信号 | N 日高点突破 |
| 止损 | ATR 止损 |
| 止盈 | 移动止盈 |
| 仓位管理 | 固定比例风险（1% NAV/笔） |
| 执行 | 次日开盘价成交 |
""")

st.markdown("---")

# ── Universe filters ──────────────────────────────────────────────────────────
st.subheader("1. 标的过滤")
st.markdown(f"""
标的池来自 **Tiingo EOD 数据**（NYSE / NASDAQ / AMEX 全量历史股票 + {meta.universe_etfs} 只 ETF，含退市标的），
采用两级过滤机制（详见「数据与标的池」页面）：

**静态预过滤（引擎启动时读取 CSV）**：仅纳入在价格 > \${p.get('min_price', 10):.0f} 且 ADV₆₀ > \$20M（粗筛）的条件下，累计满足天数 ≥ 252 天（约 1 年）的标的，确保引擎有足够的历史数据计算 200 日突破信号。（\$20M 粗筛只过滤极端低流动性标的；\$60M 精筛在引擎每日执行时再次生效。）

**引擎每日动态过滤**：每个交易日扫描入场信号前，对标的池中的每个标的动态检查以下两个条件，**两者必须同时满足**，否则跳过该标的：

| 过滤条件 | 阈值 | 说明 |
|----------|------|------|
| 收盘价（原始价格） | > \${p.get('min_price', 10):.0f} | 排除低价股，降低数据噪声和流动性风险 |
| 日均成交额 ADV₆₀ | > \${p.get('min_adv_m', 60):.0f}M 美元 | 流动性过滤，替代无法获取的历史市值数据 |

**实现细节：**
- **价格** 使用**原始价格**（非复权），确保标的在当时实际可以 ≥ \${p.get('min_price', 10):.0f} 买入
- **ADV₆₀** 基于**滚动 60 日成交额均值**，使用 shift(1) 无前视偏差：ADV₆₀[t] = mean(close × volume[t-60:t-1])（不含当天，共 60 天历史数据）；\${p.get('min_adv_m', 60):.0f}M ADV 对应约 \$12 亿以上市值
""")

st.markdown(f"""
<div class="info-box">
<strong>为何需要这两个过滤条件？</strong><br>
<ul>
<li><strong>价格 > ${p.get('min_price', 10):.0f}：</strong>低价股（Penny Stocks）波动极大、流动性差，ATR 计算容易失真，仓位规模计算也会产生极端结果。</li>
<li><strong>ADV > ${p.get('min_adv_m', 60):.0f}M：</strong>直接量化流动性，同时替代无法获取的历史市值数据。${p.get('min_adv_m', 60):.0f}M ADV 对应约 $12 亿以上市值，确保目标仓位（最大 5% NAV = $50 万）不超过该股票单日成交额的约 1%，减少实盘滑点超出假设的风险。</li>
</ul>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Regime filter ─────────────────────────────────────────────────────────────
regime_enabled = p.get("regime_filter_enabled", False)
regime_ticker  = p.get("regime_ticker", "SPY")
regime_window  = p.get("regime_sma_window", 200)

st.subheader("2. 市场环境过滤")

if regime_enabled:
    st.markdown(f"""
当 **{regime_ticker}** 收盘价 > 其 **{regime_window} 日简单移动平均线** 时，
策略1.0处于「牛市模式」，允许开仓。否则进入「熊市模式」，绝大多数标的停止新建仓位，
但 **TLT、GLD、UUP** 三只避险 ETF 除外（见下方说明）。

```
牛市模式（Bull）：SPY adj-close[t] > SMA({regime_window})[t]  → 全标的正常扫描入场信号
熊市模式（Bear）：SPY adj-close[t] ≤ SMA({regime_window})[t]  → 停止新建仓位（TLT / GLD / UUP 豁免，继续扫描）
```

""")
    _rs = meta.regime_stats
    if _rs:
        _bear_days_total = _rs["bear_days_total"]
        _bear_pct        = _rs["bear_pct"]
        _ep_strs = []
        for ep in _rs.get("top_episodes", [])[:3]:
            _lbl = str(ep["start_year"]) if ep["start_year"] == ep["end_year"] else f"{ep['start_year']}–{ep['end_year']}"
            _ep_strs.append(f"{_lbl}（封仓 {ep['days']} 天）")
        _ep_text = "，".join(_ep_strs) if _ep_strs else "无重大熊市封仓期"
        _regime_detail = f"从 {meta.backtest_start[:4]} 年起，此规则将<strong>熊市封仓天数约占 {_bear_pct:.0f}%</strong>（约 {_bear_days_total:,} 天），主要覆盖 {_ep_text}"
    else:
        _regime_detail = "熊市期间停止新建仓位，历史上主要覆盖 2008–2009 金融危机及 2022 年加息周期"

    st.markdown(f"""
<div class="info-box">
<strong>规则要点</strong><br>
<ul>
<li>现有持仓<strong>不强平</strong>——移动止盈继续保护，让利润自然奔跑</li>
<li>熊市期间所有闲置现金自动流入 <strong>{meta.cash_proxy}</strong>（赚取无风险利率）</li>
<li>{_regime_detail}</li>
</ul>
</div>
""", unsafe_allow_html=True)

    st.markdown("#### 熊市豁免：TLT、GLD、UUP")
    st.markdown("""
熊市期间允许三只避险 ETF 继续接收入场信号，捕捉股市下跌时真实存在的反向趋势机会。

| ETF | 资产类别 | 熊市走强的驱动逻辑 | 典型表现 |
|-----|---------|-----------------|---------|
| **TLT** | 长期美债（20年+） | 经济衰退 → 美联储降息 → 债券价格上涨 | 2001–02 +36%，2008–09 +26% |
| **GLD** | 黄金 | 货币信用受损、通胀预期上升、地缘风险加剧时走强 | 2008–09 +25% |
| **UUP** | 美元指数 | ① 金融危机：流动性恐慌驱动美元升值；② 加息型熊市：利差驱动资本流入美元 | 2008–09 +23%，2022 +15% |

三只 ETF **覆盖了不同类型的熊市**：TLT/GLD 在降息型熊市表现好，UUP 在加息型熊市（如 2022）填补前两者的盲点。
没有任何一次历史熊市三者同时暴跌。

**豁免不等于无条件开仓**——这三只 ETF 仍须满足策略的全部入场条件：
- ✅ 价格突破 200 日高点（门槛不变）
- ✅ 成交量确认、ATR 止损、仓位上限、热度上限（风险管理框架不变）

200 日高点这道门槛是天然保护：例如 2022 年 TLT 持续下跌 −31%，永远不会触发突破信号，豁免自动失效，不产生任何损害。
""")

else:
    st.markdown(f"""
**【当前参数未启用市场环境过滤器】**

Strategy 1.0 Baseline 默认启用此过滤器（regime_filter_enabled = True）。
当前运行已将其关闭，策略1.0将在整个回测期内无论牛熊均扫描入场信号，
可能导致在 2008 年金融危机等极端行情中承受显著回撤。
""")

st.markdown("---")

# ── Volume filter ──────────────────────────────────────────────────────────────
vol_mult = p.get("volume_filter_multiplier", 0.0)
st.subheader("3. 成交量过滤")

if vol_mult > 0:
    st.markdown(f"""
突破开仓信号还需通过**成交量确认**过滤：只有当突破当日成交量显著高于近期均值时，
信号才被视为有效。

```
过滤条件（t 日）：volume[t] ≥ {vol_mult:.1f} × mean(volume[t-60:t-1])
```

- 对比基准：**60 日成交量移动平均**（shift(1)，无前视偏差）
- 阈值：{vol_mult:.1f}×，即突破日成交量必须至少是近 60 日均量的 {vol_mult:.1f} 倍
- 使用**原始股数**（shares）而非美元成交量，避免股价高低对比较基准的影响
""")
    st.markdown(f"""
<div class="info-box">
<strong>为何需要成交量确认？</strong><br>
价格突破并不总是真实趋势的开始。低成交量突破（"假突破"）往往由少数买单推动，
缺乏市场参与度，极易在随后几天内反转。<br><br>
要求 volume[t] ≥ {vol_mult:.1f}×vol_ma60 能有效排除这类噪音信号：
机构资金进场时必然伴随大量成交，高成交量突破更可能代表真实的供需格局转变。<br><br>
<strong>注：</strong> {vol_mult:.1f}× 阈值为经验设定，目前尚无针对本策略1.0的实证验证。为什么是 {vol_mult:.1f}× 而非 1.2× 或 2.0×？若参数敏感性分析显示绩效对该阈值高度敏感，则存在过拟合风险，建议通过 Walk-Forward 验证其稳健性。
</div>
""", unsafe_allow_html=True)
else:
    st.markdown("""
**【当前未启用】** volume_filter_multiplier = 0，所有价格突破信号均有效，不检查成交量。
""")

st.markdown("---")

# ── Entry ─────────────────────────────────────────────────────────────────────
st.subheader("4. 入场条件")
st.markdown(f"""
当复权收盘价突破过去 **{p['breakout_window']} 个交易日的最高价**时触发买入信号。

```
信号（t 日收盘后）：adj_close[t] > max(adj_high[t-{p['breakout_window']}:t-1])
执行（t+1 日开盘）：以 t+1 日复权开盘价 × (1 + 滑点) 买入
```

- 使用复权价格（adj_factor），所有价格计算已包含分红
- 使用 shift(1) 防止前视偏差（look-ahead bias）
- 仅在满足仓位过滤条件后建仓（见仓位管理）
- Gap 过滤：若 |t+1开盘价 − t收盘价| / t收盘价 > {p.get('gap_filter',0.025)*100:.1f}%，跳过该信号（双向：跳空高开或跳空低开均过滤）

**多信号处理（同一天多个标的同时触发突破）：**
- 所有信号按 **突破强度（breakout_strength）降序排列**优先执行：breakout_strength = adj_close[t] / max(adj_high[t-N:t-1])
- 每执行完一笔后**立即更新**当前持仓和风险敞口，后续信号的相关性计算与组合热度检查均基于最新状态
- 优先处理突破最强的信号，可在热度上限耗尽前最大化资金利用效率
""")

st.markdown(f"""
<div class="info-box">
<strong>突破窗口为何选 {p['breakout_window']} 日？</strong><br>
{'<strong>200 日</strong>（约 10 个月）即市场常说的"52 周新高"，是机构趋势跟踪中最经典的突破周期。相比 100 日突破，200 日只捕捉更持久、更强劲的趋势，信号更少但质量更高，可有效减少假突破带来的频繁进出场。200日突破是 Donchian 通道的经典实现，学术和实践中均有充分验证。' if p['breakout_window'] == 200 else f'当前使用 {p["breakout_window"]} 日突破，覆盖约 {p["breakout_window"]//20} 个月的价格区间，在信号频率与趋势质量之间取得平衡。'}
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Stop loss ─────────────────────────────────────────────────────────────────
st.subheader("5. 止损")
st.markdown(f"""
入场后立即设置止损位，基于 **ATR(20) Wilder 平滑**计算：

```
止损价  = 入场价 − {p['stop_loss_multiplier']:.1f} × ATR(20)
1R      = 入场价 − 止损价   （每笔交易的单位风险）
```

- ATR 使用 Wilder 指数平滑（alpha = 1/20）
- 最小止损距离：入场价的 {p.get('min_stop_distance_pct',0.005)*100:.1f}%（防止止损过近）

**触发条件：**
```
若 low[t] < stop_loss  →  生成止损信号，次日（t+1）开盘价平仓
```
- 每日收盘后，检查当天最低价是否跌破止损线（模拟实盘盘中实时止损触发的效果）
- 与移动止盈（用收盘价触发）不同：止损使用日内最低价，能捕捉当天盘中价格大幅下破的情形
""")

_stop_dist    = (res.trades["entry_price"] - res.trades["stop_loss"]) / res.trades["entry_price"] * 100
_n_trades     = len(res.trades)
_n_below_05   = int((_stop_dist < 0.5).sum())
_median_dist  = round(_stop_dist.median(), 1)

st.markdown(f"""
<div style="background:#e3f2fd;border-left:4px solid #1565c0;padding:12px 16px;border-radius:6px;margin-top:4px;">
<strong>0.5% 最小止损距离的作用</strong><br>
这个门槛不是策略1.0噪音防护的主要机制，而是一个<strong>数据质量兜底检查</strong>：
当 ATR 异常趋近于零时（数据错误或极端低波动），拒绝入场，防止仓位计算出现除以近零的错误。<br>
实盘中几乎从不触发——{_n_trades:,} 笔历史交易中{"无一笔" if _n_below_05 == 0 else f"{_n_below_05} 笔"}止损距离低于 0.5%，
实际止损距离中位数为 <strong>{_median_dist}%</strong>（= 2×ATR）。
真正防止被噪音震出的机制是 <strong>2×ATR 止损</strong>本身：ATR(20) 已量化了该股票正常的日波动幅度，
2×ATR 的止损天然位于日常噪音范围之外。
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Trailing stop ─────────────────────────────────────────────────────────────
st.subheader("6. 分段移动止盈")
st.markdown(f"""
根据持仓期间**历史峰值盈利**（R_peak）动态调整移动止盈距离。R_peak 以持仓最高价计算，一旦达到某区间后**不因回撤而退档**，避免大赢家回撤时止盈收紧：

| 历史峰值盈利（R_peak） | 移动止盈距离 | 说明 |
|------------|------------|------|
| < 1R | {p['trail_multiplier_r1']:.0f}×ATR | 宽松，给趋势充分发展空间 |
| 1R – 3R | {p['trail_multiplier_r3']:.0f}×ATR | 趋势中段，继续保护利润 |
| ≥ 3R | {p['trail_multiplier_r5']:.0f}×ATR | 放宽，让利润继续奔跑 |

移动止盈**只升不降**：new_stop = max(old_stop, highest_high − k×ATR)

其中 highest_high = 持仓期间（自入场日起）adj_high 的累计最大值；**初始化为 entry_price**（不使用入场日当天盘中最高价，避免引入未来信息）。移动止盈锚定最高点而非当日收盘价，确保移动止盈仅在创新高时上移，不会因某天大涨后小幅回调就提前触发。

**初始值与止损的切换逻辑：**

```
开仓时：trail_stop[t0] = entry_price − 3×ATR   （移动止盈初始值，宽于止损）
止损：stop_loss      = entry_price − 2×ATR   （固定，日内最低价触发）
```

开仓初期，止损（2×ATR）比移动止盈（3×ATR）更紧，由止损提供主要保护。
当持仓最高价突破 entry_price + 1×ATR 后，移动止盈线（highest_high − 3×ATR）
开始高于止损线（entry − 2×ATR），从此由移动止盈主导退出。
（此接管时机由数学自然保证，代码无需显式判断：trail_stop 从 entry − 3×ATR 起步，
低于止损位 entry − 2×ATR；一旦 highest_high 超过 entry + 1×ATR，
trail_stop 数学上必然超过止损位，自动成为约束性条件。）
两者同时有效，以**收盘价穿越移动止盈**或**日内最低价穿越止损**中先触发者为准。
""")

st.markdown(f"""
<div class="info-box">
<strong>早期移动止盈为何设为 {p['trail_multiplier_r1']:.0f}×ATR？</strong><br>
早期阶段（盈利 &lt; 1R）价格波动频繁，过窄的移动止盈容易被短期噪音触发，
导致大量仓位在趋势尚未发展时就被震出。原版 2×ATR 设置导致平均持仓仅 24 天、
年换手率高达 11.24x，隐含年化交易成本 2.92%（基于早期参数实验的估算值）。<br>
调整为 {p['trail_multiplier_r1']:.0f}×ATR 后，给予早期趋势更多发展空间，
预期降低换手率约 20%，节省约 0.6%/年的交易摩擦成本。
止损（Initial Stop）不受影响——跌破入场价 − 2×ATR 仍立即平仓。<br><br>
<strong>盈利 &gt; 3R 后为何改用 {p['trail_multiplier_r5']:.0f}×ATR，反而更宽？</strong><br>
k 越大，止损线离当前价格越远，需要股价跌得更多才能触发止损。
5×ATR 比 3×ATR 更宽松，不是"更早卖出"，而是"更晚卖出"——
代价是如果趋势反转，会多回吐约 2×ATR 的利润才被止出。
这是趋势跟踪"让利润奔跑"的核心体现：仓位盈利越丰厚，越不应被短期震荡提前踢出，
宁可多给一点回撤空间，也要争取捕捉完整的大趋势。
</div>
""", unsafe_allow_html=True)

st.markdown("""
**退出优先级顺序：**

| 优先级 | 条件 | 触发方式 |
|--------|------|---------|
| Priority 1 | 止损：low[t] < stop_loss | 日内最低价，同日两条件均满足时此项优先 |
| Priority 2 | 移动止盈：close[t] < trail_stop | 收盘价，仅在止损未触发时检查 |

策略 1.0 无固定止盈价位（Take Profit），持仓仅通过止损或移动止盈退出。
""")

st.markdown("---")

# ── Position sizing ───────────────────────────────────────────────────────────
st.subheader("7. 仓位管理")

cols = st.columns(4)
steps = [
    ("Step 1", "目标风险", f"每笔交易风险 = NAV × {p['risk_per_trade']*100:.0f}%（目标值）\n股数 = 目标风险 ÷ (入场价 − 止损价)\n若超过 Step 2 上限则截断\n→ 历史实际均值约 0.24% NAV"),
    ("Step 2", "单标的上限", f"单标的持仓市值上限 = NAV × {p['position_cap']*100:.0f}%"),
    ("Step 3", "相关性调整", f"若持仓中已有<strong>正相关性</strong> > {p['correlation_threshold']:.2f} 的标的，\n新仓位减半（负相关不触发）"),
    ("Step 4", "组合热度检查", f"组合总风险敞口 ≤ NAV × {p['heat_limit']*100:.0f}%\n超限则拒绝开仓"),
]
for col, (step, title, body) in zip(cols, steps):
    with col:
        st.markdown(f"""
<div class="info-box">
<strong>{step}：{title}</strong><br>
<small>{body.replace(chr(10), '<br>')}</small>
</div>
""", unsafe_allow_html=True)

st.markdown(f"""
**Step 3 相关性调整——实现细节：**

| 参数 | 值 | 说明 |
|------|----|------|
| 收益率类型 | 对数收益率 | ln(close[t] / close[t-1]) |
| 滚动窗口 | 60 个交易日 | 与新标的和每个已持仓标的逐对计算 |
| 最少样本 | 40 个有效交易日 | 共同有数据的天数不足 40 → 视为不相关 |
| 相关系数处理 | 仅正相关 | 负相关视为 0，不触发减仓（多头组合中负相关具有对冲效果） |
| 触发阈值 | max_pos_corr > {p['correlation_threshold']:.2f} | 与任意一个已持仓标的超阈值即触发 |
| 触发效果 | 仓位减半 × {p.get('correlation_reduction', 0.5):.1f} | 不拒绝开仓，仅降低头寸 |
| 空仓时 | 跳过检查 | 无已持仓标的时不触发减仓 |
""")

st.markdown("---")

# ── Execution ─────────────────────────────────────────────────────────────────
st.subheader("8. 执行与成本假设")
col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
**执行模型：**
- 信号在 t 日收盘后生成
- 以 t+1 日开盘价执行（无前视偏差）
- 滑点：{p.get('slippage_bps',10):.0f} bps（单边）
- 佣金：{p.get('commission_bps',3):.0f} bps（单边）
- 总成本约 {(p.get('slippage_bps',10)+p.get('commission_bps',3))*2:.0f} bps/往返
""")
with col2:
    st.markdown(f"""
**闲置资金管理：**
- 未持仓资金投入 **{meta.cash_proxy}**（iShares 1–3 年期国债 ETF）
- 获取无风险收益，降低现金拖累
""")
