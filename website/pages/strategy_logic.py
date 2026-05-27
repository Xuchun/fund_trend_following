"""策略逻辑"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import get_results
from website.components.strategy_badge import render_page_header

res  = get_results()
meta = res.meta
p    = meta.params_anchor

render_page_header("策略逻辑", meta)
st.caption(f"{meta.display_name} · {meta.subtitle}")
st.markdown("---")

# ── Overview ──────────────────────────────────────────────────────────────────
st.subheader("策略概述")
st.markdown(f"""
本策略是一个**经典动量突破型趋势跟踪策略**，纯多头（Long Only），适用于股票和 ETF 市场。
核心理念源自 Richard Dennis 的海龟交易法则与 David Harding 的 AHL 系统：
**顺势而为，快速止损，让利润奔跑**。

| 维度 | 说明 |
|------|------|
| 策略类型 | 趋势跟踪（Trend Following）|
| 方向 | 纯多头（Long Only） |
| 入场信号 | N 日高点突破 |
| 止损 | ATR 固定止损 + 追踪止损 |
| 仓位管理 | 固定比例风险（1% NAV/笔） |
| 执行 | 次日开盘价成交 |
""")

st.markdown("---")

# ── Universe filters ──────────────────────────────────────────────────────────
st.subheader("1. 标的过滤")
st.markdown(f"""
每个交易日扫描入场信号前，对所有候选标的逐一检查以下三个条件，**三者必须同时满足**，否则跳过该标的：

| 过滤条件 | 阈值 | 说明 |
|----------|------|------|
| 收盘价（原始价格） | > \${p.get('min_price', 10):.0f} | 排除低价股，降低数据噪声和流动性风险 |
| 市值 | > \${p.get('min_market_cap_b', 2):.0f} 亿美元（\$2B） | 排除微盘股，确保基本的机构可投资性 |
| 日均成交额（ADV） | > \${p.get('min_adv_m', 20):.0f}M 美元 | 流动性过滤，确保可在目标规模下正常进出 |

**实现细节：**
- **价格** 使用**原始价格**（非复权），确保标的在当时实际可以 ≥ \${p.get('min_price', 10):.0f} 买入
- **市值** 使用当日市值代理（当前 S&P 900 成分股市值，存在一定幸存者偏差）
- **ADV** 基于**滚动 60 日成交额均值**，包含当天 t：ADV_60[t] = mean(dollar_volume[t-59:t])（当天成交量在收盘后信号生成时已知，无前视偏差）
""")

st.markdown(f"""
<div class="info-box">
<strong>为何需要这三个过滤条件？</strong><br>
<ul>
<li><strong>价格 > \${p.get('min_price', 10):.0f}：</strong>低价股（Penny Stocks）波动极大、流动性差，ATR 计算容易失真，仓位规模计算也会产生极端结果。</li>
<li><strong>市值 > \${p.get('min_market_cap_b', 2):.0f}B：</strong>微盘股成交量小，机构资金（\$1,000 万规模）大额买入会造成明显市场冲击，回测中的成交价难以在实盘中复现。</li>
<li><strong>ADV > \${p.get('min_adv_m', 20):.0f}M：</strong>直接量化流动性——确保目标仓位（最大 5% NAV = \$50 万）不超过该股票单日成交额的 2.5%，减少实盘滑点超出假设的风险。</li>
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
**【已启用】** 当 **{regime_ticker}** 收盘价 > 其 **{regime_window} 日简单移动平均线** 时，
策略处于「牛市模式」，允许开仓。否则进入「熊市模式」，停止新建仓位。

```
牛市模式（Bull）：SPY adj-close[t] > SMA({regime_window})[t]  → 正常扫描入场信号
熊市模式（Bear）：SPY adj-close[t] ≤ SMA({regime_window})[t]  → pending_entries = []
```

**规则要点：**
- 现有持仓**不强平**——追踪止损继续保护，让利润自然奔跑
- 熊市期间所有闲置现金自动流入 **{meta.cash_proxy}**（赚取无风险利率）
- 从 2004 年起，此规则将 **熊市封仓天数约占 19%**（约 1,025 天），
  主要覆盖 2008 金融危机（封仓 373 天）和 2022 年加息熊市（封仓 261 天）
""")
else:
    st.markdown(f"""
**【未启用】—— Strategy 1.0 为纯多头策略，无市场环境过滤器。**

策略在整个 2004–2024 回测期内，无论市场处于牛市还是熊市，均按相同规则扫描入场信号。
这导致 Strategy 1.0 在 2008 年金融危机期间遭受了 **-54% 的最大回撤**。

**Strategy 2.0 改进：** 引入 **{regime_ticker} {regime_window} 日均线过滤器**。
当 SPY 价格低于其 200 日均线时，停止开新仓，熊市期间额外现金自动投入 SHY。
预期可将最大回撤从 -54% 降至 -25% 以内，同时显著提升 Sharpe 比率。
""")

st.markdown("---")

# ── Entry ─────────────────────────────────────────────────────────────────────
st.subheader("3. 入场条件")
st.markdown(f"""
当复权收盘价突破过去 **{p['breakout_window']} 个交易日的最高价**时触发买入信号。

```
信号（t 日收盘后）：adj_close[t] > max(adj_high[t-{p['breakout_window']}:t-1])
执行（t+1 日开盘）：以 t+1 日复权开盘价 × (1 + 滑点) 买入
```

- 使用复权价格（adj_factor），所有价格计算已包含分红
- 使用 `shift(1)` 防止前视偏差（look-ahead bias）
- 仅在满足仓位过滤条件后建仓（见仓位管理）
- Gap 过滤：若 `|t+1开盘价 − t收盘价| / t收盘价 > {p.get('gap_filter',0.025)*100:.1f}%`，跳过该信号（双向：跳空高开或跳空低开均过滤）

**多信号处理（同一天多个标的同时触发突破）：**
- 所有信号按 **突破强度（breakout_strength）降序排列**优先执行：`breakout_strength = adj_close[t] / max(adj_high[t-N:t-1])`
- 每执行完一笔后**立即更新**当前持仓和风险敞口，后续信号的相关性计算与组合热度检查均基于最新状态
- 优先处理突破最强的信号，可在热度上限耗尽前最大化资金利用效率
""")

st.markdown(f"""
<div class="info-box">
<strong>突破窗口为何选 {p['breakout_window']} 日？</strong><br>
{'<strong>200 日</strong>（约 10 个月）即市场常说的"52 周新高"，是机构趋势跟踪中最经典的突破周期。相比 100 日突破，200 日只捕捉更持久、更强劲的趋势，信号更少但质量更高，可有效减少假突破带来的频繁进出场。' if p['breakout_window'] == 200 else f'当前使用 {p["breakout_window"]} 日突破，覆盖约 {p["breakout_window"]//20} 个月的价格区间，在信号频率与趋势质量之间取得平衡。'}
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Volume filter ──────────────────────────────────────────────────────────────
vol_mult = p.get("volume_filter_multiplier", 0.0)
st.subheader("4. 成交量过滤")

if vol_mult > 0:
    st.markdown(f"""
突破信号还需通过**成交量确认**过滤：只有当突破当日成交量显著高于近期均值时，
信号才被视为有效。

```
过滤条件（t 日）：volume[t] ≥ {vol_mult:.1f} × mean(volume[t-60:t-1])
```

- 对比基准：**60 日成交量移动平均**（shift(1)，无前视偏差）
- 阈值：{vol_mult:.1f}×，即突破日成交量必须至少是近 60 日均量的 {vol_mult:.1f} 倍
- 使用**原始股数（shares）**而非美元成交量，避免股价高低对比较基准的影响
""")
    st.markdown(f"""
<div class="info-box">
<strong>为何需要成交量确认？</strong><br>
价格突破并不总是真实趋势的开始。低成交量突破（"假突破"）往往由少数买单推动，
缺乏市场参与度，极易在随后几天内反转。<br><br>
要求 volume[t] &gt; {vol_mult:.1f}×vol_ma60 能有效排除这类噪音信号：
机构资金进场时必然伴随大量成交，高成交量突破更可能代表真实的供需格局转变。<br><br>
<strong>预期效果：</strong> 入场信号减少约 20–30%，胜率提升，换手率相应下降。
</div>
""", unsafe_allow_html=True)
else:
    st.markdown("""
**【当前未启用】** `volume_filter_multiplier = 0`，所有价格突破信号均有效，不检查成交量。
""")

st.markdown("---")

# ── Breakout strength filter ──────────────────────────────────────────────────
bs_min = p.get("breakout_strength_min", 0.0)
st.subheader("5. 突破强度过滤")

if bs_min > 0:
    st.markdown(f"""
突破信号还需通过**突破强度过滤**：不仅要求收盘价超过 N 日高点，
还要求**超出幅度至少达到 {bs_min*100:.0f}%**，排除边际突破。

```
过滤条件（t 日）：close[t] / rolling_high_{p['breakout_window']}[t] ≥ {1+bs_min:.2f}
等价于：close[t] ≥ rolling_high_{p['breakout_window']}[t] × {1+bs_min:.2f}
```

- 突破强度（`breakout_strength`）= close[t] / rolling_high_N[t]
- 当前阈值：**{bs_min*100:.0f}%**，即收盘价须高于 {p['breakout_window']} 日高点 {bs_min*100:.0f}% 以上
- 边际突破（仅超出 0.1%）被过滤，只保留有决定性突破意义的信号
""")
    st.markdown(f"""
<div class="info-box">
<strong>为何需要突破强度过滤？</strong><br>
传统的 N 日突破条件（close &gt; rolling_high）对于"仅超出一分钱"的突破同样有效，
这类边际突破缺乏真正的动量支撑，更可能是随机噪音而非趋势起点。<br><br>
要求 <strong>close/rolling_high &gt; {1+bs_min:.2f}</strong>（即超出 {bs_min*100:.0f}%）能确保：
<ul>
<li>进场信号具有一定的趋势惯性，不会因微小波动立即回撤触发止损</li>
<li>与成交量确认配合，大幅提升每笔入场的质量</li>
<li>预期效果：入场信号进一步减少约 15–20%，但胜率和平均盈亏比（profit factor）改善</li>
</ul>
</div>
""", unsafe_allow_html=True)
else:
    st.markdown("""
**【当前未启用】** `breakout_strength_min = 0`，只要价格高于 N 日高点即触发入场信号，不要求最小突破幅度。
""")

st.markdown("---")

# ── Stop loss ─────────────────────────────────────────────────────────────────
st.subheader("6. 初始止损（Initial Stop Loss）")
st.markdown(f"""
入场后立即设置固定止损位，基于 **ATR(20) Wilder 平滑**计算：

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
- 使用**日内最低价**（非收盘价）检查，盘中只要跌破止损线即触发
- 与追踪止损（用收盘价触发）不同：硬止损更激进，能在当日即捕捉到价格大幅下破
""")

st.markdown("""
<div style="background:#e3f2fd;border-left:4px solid #1565c0;padding:12px 16px;border-radius:6px;margin-top:4px;">
<strong>0.5% 最小止损距离的作用</strong><br>
这个门槛不是策略噪音防护的主要机制，而是一个<strong>数据质量兜底检查</strong>：
当 ATR 异常趋近于零时（数据错误或极端低波动），拒绝入场，防止仓位计算出现除以近零的错误。<br>
实盘中几乎从不触发——3,336 笔历史交易中无一笔止损距离低于 0.5%，
实际止损距离中位数为 <strong>4.4%</strong>（= 2×ATR）。
真正防止被噪音震出的机制是 <strong>2×ATR 初始止损</strong>本身：ATR(20) 已量化了该股票正常的日波动幅度，
2×ATR 的止损天然位于日常噪音范围之外。
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── Trailing stop ─────────────────────────────────────────────────────────────
st.subheader("7. 分段追踪止损（Segmented Trailing Stop）")
st.markdown(f"""
随着持仓盈利增加，逐步收紧追踪止损以锁定利润：

| 当前盈利区间 | 追踪止损距离 | 说明 |
|------------|------------|------|
| < 1R | {p['trail_multiplier_r1']:.0f}×ATR | 宽松，给趋势充分发展空间 |
| 1R – 3R | {p['trail_multiplier_r3']:.0f}×ATR | 中等，开始锁定利润 |
| > 3R | {p['trail_multiplier_r5']:.0f}×ATR | 收紧，保护大盈利 |

追踪止损**只升不降**：`new_stop = max(old_stop, highest_high − k×ATR)`

其中 `highest_high` = 持仓期间（自入场日起）的历史最高价（adj_high 的累计最大值）。止损线锚定最高点而非当日收盘价，确保止损线仅在创新高时上移，不会因某天大涨后小幅回调就提前触发。

**初始值与硬止损的切换逻辑：**

```
开仓时：trail_stop[t0] = entry_price − 3×ATR   （追踪止损初始值，宽于硬止损）
硬止损：stop_loss      = entry_price − 2×ATR   （固定，日内最低价触发）
```

开仓初期，硬止损（2×ATR）比追踪止损（3×ATR）更紧，由硬止损提供主要保护。
当持仓最高价突破 `entry_price + 1×ATR` 后，追踪止损线（`highest_high − 3×ATR`）
开始低于硬止损线（`entry − 2×ATR`），从此由追踪止损主导退出。
两者同时有效，以**收盘价穿越追踪止损**或**日内最低价穿越硬止损**中先触发者为准。
""")

st.markdown(f"""
<div class="info-box">
<strong>早期追踪止损为何设为 {p['trail_multiplier_r1']:.0f}×ATR？</strong><br>
早期阶段（盈利 &lt; 1R）价格波动频繁，过窄的追踪止损容易被短期噪音触发，
导致大量仓位在趋势尚未发展时就被震出。原版 2×ATR 设置导致平均持仓仅 24 天、
年换手率高达 11.24x，隐含年化交易成本 2.92%。<br>
调整为 {p['trail_multiplier_r1']:.0f}×ATR 后，给予早期趋势更多发展空间，
预期降低换手率约 20%，节省约 0.6%/年的交易摩擦成本。
初始止损（Initial Stop）不受影响——跌破入场价 − 2×ATR 仍立即平仓。<br><br>
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
| Priority 1 | 硬止损：`low[t] < stop_loss` | 日内最低价，同日两条件均满足时此项优先 |
| Priority 2 | 追踪止损：`close[t] < trail_stop` | 收盘价，仅在硬止损未触发时检查 |

Strategy 1.0 无止盈（Take Profit）条件，持仓仅通过止损退出。
""")

st.markdown("---")

# ── Position sizing ───────────────────────────────────────────────────────────
st.subheader("8. 仓位管理（Position Sizing — 4 步过滤）")

cols = st.columns(4)
steps = [
    ("Step 1", "目标风险", f"每笔交易风险 = NAV × {p['risk_per_trade']*100:.0f}%\n股数 = 目标风险 ÷ (入场价 − 止损价)"),
    ("Step 2", "单标的上限", f"单标的持仓市值上限 = NAV × {p['position_cap']*100:.0f}%"),
    ("Step 3", "相关性调整", f"若持仓中已有相关性 > {p['correlation_threshold']:.2f} 的标的，\n新仓位减半"),
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
| 相关系数处理 | 取绝对值 | 正相关（同涨同跌）与负相关（反向）均算入 |
| 触发阈值 | max_abs_corr > {p['correlation_threshold']:.2f} | 与任意一个已持仓标的超阈值即触发 |
| 触发效果 | 仓位减半 × {p.get('correlation_reduction', 0.5):.1f} | 不拒绝开仓，仅降低头寸 |
| 空仓时 | 跳过检查 | 无已持仓标的时不触发减仓 |
""")

st.markdown("---")

# ── Execution ─────────────────────────────────────────────────────────────────
st.subheader("9. 执行与成本假设")
col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
**执行模型：**
- 信号在 t 日收盘后生成
- 以 t+1 日开盘价执行（无前视偏差）
- 滑点：{p.get('slippage_bps',10):.0f} bps（单边）
- 佣金：{p.get('commission_bps',3):.0f} bps（单边）
- 总成本约 {(p.get('slippage_bps',10)+p.get('commission_bps',3))*2:.0f} bps/往返

> 实现说明：代码中滑点已直接嵌入成交价，
> `fill_price = open_price × (1 + slippage_bps/10000)`，
> 与设计方案将 entry_price 和成本分开记录的方式在 PnL 上数值等价。
""")
with col2:
    st.markdown(f"""
**闲置资金管理：**
- 未持仓资金投入 **{meta.cash_proxy}**（iShares 1–3 年期国债 ETF）
- 获取无风险收益，降低现金拖累
- 相关窗口：{p.get('correlation_window',60)} 日滚动相关性
""")

st.markdown("""
<div class="info-box">
<strong>为何使用 SHY 而非 SGOV？</strong><br>
SGOV（0–3 个月国债 ETF）于 <strong>2022 年</strong>才上市，若用于 2004–2021 年的回测，
现金将在该期间产生 0% 收益，严重低估策略的真实表现。
SHY（1–3 年期国债 ETF）自 <strong>2002 年</strong>起就有数据，可覆盖完整的 2004–2024 回测期，
能够正确模拟闲置资金赚取无风险利率的效果。
</div>
""", unsafe_allow_html=True)
