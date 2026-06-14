"""策略2.0 — 策略描述"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import render_v2_page_header, get_results

res  = get_results()
meta = res.meta
p    = meta.params_anchor

render_v2_page_header("策略描述")
st.caption("策略2.0 · 横盘收敛 + 箱体突破趋势跟踪")
st.markdown("---")

# ── 策略概述 ──────────────────────────────────────────────────────────────────
st.subheader("策略概述")
st.markdown("""
策略2.0是对策略1.0的**核心改进**，在突破信号的基础上增加了**横盘收敛过滤**，
力图在更高质量的突破点入场，减少假突破噪声。

| 维度 | 策略1.0 | 策略2.0 |
|------|---------|---------|
| 策略类型 | 趋势跟踪（Trend Following） | 与策略1.0相同 |
| 方向 | 纯多头（Long Only） | 与策略1.0相同 |
| 核心 Edge | 突破前高 + 趋势延续 | **横盘收敛 + 箱体突破** |
| 入场信号 | N 日高点突破（单一条件） | **突破 + 横盘收敛 + 突破强度（4 个条件）** |
| 止损 | ATR 固定止损 | **结构止损（ATR + 近期低点双重保护）** |
| 止盈 | 分段移动止盈（3/3/5×ATR） | 分段追踪止损（3/3/5×ATR）＋平价保护（⚠️ 设计选项，待回测验证） |
| 仓位管理 | 固定比例风险（1% NAV/笔）+ 相关性过滤 | 与策略1.0相同 |
| 相关性过滤 | 有（Pearson 60 日，阈值 0.7） | 与策略1.0相同 |
| 市场环境过滤 | 有（SPY 200 日均线） | 与策略1.0相同 |
| 执行 | 次日开盘价成交 | 与策略1.0相同 |

**核心假设**：资产价格经历充分横盘收敛并成功突破长期阻力位后，具有极强的趋势延续潜力。
横盘收敛代表供需均衡、能量积聚，突破时释放的动能往往比随机突破更持久。
""")

st.markdown("---")

# ── 1. 标的过滤 ───────────────────────────────────────────────────────────────
st.subheader("1. 标的过滤（跟策略1.0一样）")
st.markdown(f"""
每个交易日扫描入场信号前，对所有候选标的逐一检查以下三个条件，**三者必须同时满足**，否则跳过该标的：

| 过滤条件 | 阈值 | 说明 |
|----------|------|------|
| 收盘价（原始价格） | > \${p.get('min_price', 10):.0f} | 排除低价股，降低数据噪声和流动性风险 |
| 市值 | > \${p.get('min_market_cap_b', 2):.0f} 亿美元（\$2B） | 排除微盘股，确保基本的机构可投资性 |
| 日均成交额（ADV） | > \${p.get('min_adv_m', 20):.0f}M 美元 | 流动性过滤，确保可在目标规模下正常进出 |

**实现细节：**
- **价格** 使用**原始价格**（非复权），确保标的在当时实际可以 ≥ \${p.get('min_price', 10):.0f} 买入
- **市值** ⚠️ Yahoo Finance 不提供历史时间点市值数据，该过滤条件在回测中**未实际执行**。回测依赖 S&P 900 成分股名单作为隐性市值门槛（S&P 400 成分股市值约 $20亿以上），但成分股名单为静态，存在**幸存者偏差**——已退市或被踢出指数的小市值股票不在回测范围内。
- **ADV** 基于**滚动 60 日成交额均值**，包含当天 t：ADV_60[t] = mean(dollar_volume[t-59], ..., dollar_volume[t])（含当天，共 60 天；当天成交量在收盘后信号生成时已知，无前视偏差）
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

# ── 2. 市场环境过滤 ───────────────────────────────────────────────────────────
regime_enabled = p.get("regime_filter_enabled", False)
regime_ticker  = p.get("regime_ticker", "SPY")
regime_window  = p.get("regime_sma_window", 200)

st.subheader("2. 市场环境过滤（跟策略1.0一样）")

if regime_enabled:
    st.markdown(f"""
当 **{regime_ticker}** 收盘价 > 其 **{regime_window} 日简单移动平均线** 时，
策略处于「牛市模式」，允许开仓。否则进入「熊市模式」，停止新建仓位。

```
牛市模式（Bull）：SPY adj-close[t] > SMA({regime_window})[t]  → 正常扫描入场信号
熊市模式（Bear）：SPY adj-close[t] ≤ SMA({regime_window})[t]  → 停止新建仓位
```

""")
    _rs = meta.regime_stats
    if _rs:
        _bear_days_total = _rs["bear_days_total"]
        _bear_pct        = _rs["bear_pct"]
        _ep_strs = []
        for ep in _rs.get("top_episodes", [])[:2]:
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
else:
    st.markdown("""
**【当前参数未启用市场环境过滤器】**

策略 Baseline 默认启用此过滤器（`regime_filter_enabled = True`）。
当前运行已将其关闭，策略将在整个回测期内无论牛熊均扫描入场信号，
可能导致在 2008 年金融危机等极端行情中承受显著回撤。
""")

st.markdown("---")

# ── 3. 入场条件 ───────────────────────────────────────────────────────────────
st.subheader("3. 入场条件（4 个条件，全部满足方可入场）")

st.markdown("""
策略2.0的入场信号由 4 个条件组成。信号在 **t 日收盘后**生成，**t+1 日开盘**执行。
""")

st.markdown("#### 条件1：基础突破（跟策略1.0一样）")
st.code("""
# 收盘价突破近 N 日最高价（与策略1.0完全一致）
adj_close[t] > max(adj_high[t-N : t-1])
N = 200
""", language="python")
st.markdown("""
> 与策略1.0入场信号完全相同：收盘价突破过去 200 个交易日（约 10 个月）的**最高价**（high）。
""")

st.markdown("#### 条件2：横盘收敛（Consolidation — 核心 Edge）")
st.code("""
# 过去 80 日价格区间宽度 < 25%
range_ratio = (max(high[t-80:t-1]) - min(low[t-80:t-1])) / min(low[t-80:t-1])
range_ratio < 0.25
""", language="python")
st.markdown("""
这是策略2.0的**核心过滤条件**，也是与策略1.0最大的区别。

横盘收敛代表：价格在一段时间内处于相对窄幅震荡，
高点阻力位与低点支撑位逐渐收敛，市场处于供需均衡、能量积聚状态。

| 参数 | Baseline 值 | 含义 |
|------|------------|------|
| 横盘回望窗口 | 80 日（约 4 个月） | 多长时间内考察震荡幅度 |
| 宽度阈值 | 25% | 震荡区间高低点差 / 低点 < 25% 才算横盘 |

**经济学含义**：25% 的阈值意味着，过去 4 个月中最高点不超过最低点的 1.25 倍。
这过滤掉了价格剧烈波动的标的，保留了真正处于积聚阶段的候选标的。
""")

st.markdown("""
<div class="info-box">
<strong>为何横盘收敛是更高质量的突破？</strong><br>
策略1.0中的 N 日突破，任何价格都可以触发——包括已经大幅上涨后的"追高突破"。
横盘收敛过滤确保：<br>
① 突破前价格长期压缩，突破是从"静止"到"运动"，动能更持久<br>
② 阻力位是多次测试过的真实压力区间，突破后的空间往往更大<br>
③ 横盘期间止损位（近期低点）更加清晰，结构止损更准确
</div>
""", unsafe_allow_html=True)

st.markdown("#### 条件3：触顶次数（Touch Count — 暂缓实施）")
st.code("""
# 过去横盘期内价格触及压力区间顶部次数 >= 2（允许 ±2% 误差）
touch_count >= 2
""", language="python")
st.markdown("""
> ⚠️ **当前状态：暂时跳过此条件，待验证增量价值后决定是否引入。**
>
> 触顶次数用于过滤"假性横盘"（即价格只在低位停留，从未测试过阻力位的情形）。
> 目前先验证横盘收敛本身是否带来统计显著的增量，再决定是否叠加此条件。
""")

st.markdown("#### 条件4：突破强度（Breakout Momentum）")
st.code("""
# 突破当日为阳线，且涨幅 > 1%
(close[t] / open[t] - 1) > 0.01
""", language="python")
st.markdown("""
要求突破当日本身是一根有力度的阳线，过滤掉"低开收涨勉强触突破位"的弱势信号。
这是动能确认：真正的突破往往伴随着当日的大涨（而非慢慢爬到突破位）。
""")

st.markdown("---")

# ── 4. 入场执行 ───────────────────────────────────────────────────────────────
st.subheader("4. 入场执行（跟策略1.0一样）")
col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
**执行模型：**
- 信号在 t 日收盘后生成
- 以 t+1 日开盘价执行（无前视偏差）
- 滑点：{p.get('slippage_bps', 10):.0f} bps（单边）
- 佣金：{p.get('commission_bps', 3):.0f} bps（单边）
- 总成本约 {(p.get('slippage_bps', 10) + p.get('commission_bps', 3)) * 2:.0f} bps/往返

> 实现说明：代码中滑点已直接嵌入成交价，
> `fill_price = open_price × (1 + slippage_bps/10000)`，
> 与设计方案将 entry_price 和成本分开记录的方式在 PnL 上数值等价。
""")
with col2:
    st.markdown(f"""
**Gap 过滤（双向对称）：**
- 若 `|t+1开盘价 − t收盘价| / t收盘价 > {p.get('gap_filter', 0.025) * 100:.1f}%`
- 跳空高开或跳空低开均跳过该信号

| 参数 | 值 |
|------|----|
| Gap filter | ±{p.get('gap_filter', 0.025) * 100:.1f}% |
| Slippage | {p.get('slippage_bps', 10):.0f} bps |
| Commission | {p.get('commission_bps', 3):.0f} bps |
""")

st.markdown("---")

# ── 5. 止损 ───────────────────────────────────────────────────────────────────
st.subheader("5. 止损 — 结构止损（Structure Stop）")
st.code("""
# 结构止损 = ATR 止损 与 近期低点止损 取较高值（即更保守的那个）
initial_stop   = entry_price - 2 × ATR(20)
structure_stop = lowest(low, 20) × 0.995   # 近 20 日最低价再下移 0.5%

stop = max(initial_stop, structure_stop)    # 取两者中较高的那个
""", language="python")

st.markdown("""
这是策略2.0与策略1.0最关键的技术差异之一。

| 止损类型 | 策略1.0 | 策略2.0 |
|---------|---------|---------|
| 方法 | ATR 固定止损（`entry - 2×ATR`） | **结构止损**（ATR 止损与近期低点止损取较高值） |
| 优势 | 简单、一致 | 结合市场结构，止损更贴近价格行为 |
| 含义 | 基于波动率设定风险单位 | 近期低点是真实的支撑位，跌破即趋势转弱 |
""")

st.markdown("""
<div class="info-box">
<strong>结构止损的逻辑</strong><br>
<ul>
<li><strong>initial_stop = entry - 2×ATR(20)</strong>：基于波动率，确保止损距离合理（不会过近被噪音震出）</li>
<li><strong>structure_stop = lowest(low,20) × 0.995</strong>：近 20 日的价格低点是市场参与者认可的真实支撑位，
跌破代表横盘结构被破坏，突破失效</li>
<li><strong>取较高值（max）</strong>：两者取更严格的止损位。若近期低点离入场价很近（横盘极度收敛），
结构止损主导；若横盘结构宽松，ATR 止损主导，防止止损过近</li>
</ul>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── 6. 止盈 ───────────────────────────────────────────────────────────────────
st.subheader("6. 移动止盈 + 平价保护（需要测试）")
st.code("""
# 初始追踪止损（开仓时设定）
trail_stop[t0] = entry_price - 3 × ATR(20)

# 每日收盘后更新
highest_high[t] = max(highest_high[t-1], high[t])

R = entry_price - stop_loss          # 初始风险单位
R_multiple[t] = (highest_high[t] - entry_price) / R

if R_multiple[t] < 1:
    trail_stop[t] = max(trail_stop[t-1], highest_high[t] - 3 × ATR(20))
elif R_multiple[t] < 3:
    trail_stop[t] = max(trail_stop[t-1], highest_high[t] - 3 × ATR(20))
else:
    trail_stop[t] = max(trail_stop[t-1], highest_high[t] - 5 × ATR(20))

# 触发退出（两者取先触发）
if low[t] < stop_loss:
    exit at open[t+1]       # 止损触发（日内最低价）
elif close[t] < trail_stop[t]:
    exit at open[t+1]       # 追踪止损触发（收盘价）
""", language="python")

st.markdown("""
与策略1.0使用**完全相同**的分段追踪止损机制：

| R 档位 | 追踪止损倍数 | 含义 |
|--------|------------|------|
| R_multiple < 1 | highest_high − **3×ATR** | 早期阶段，给趋势充分发展空间 |
| 1 ≤ R_multiple < 3 | highest_high − **3×ATR** | 中期跟踪，松紧一致 |
| R_multiple ≥ 3 | highest_high − **5×ATR** | 大趋势阶段，放宽止损锁住更多利润 |

**只升不降**：trail_stop 只能上移，不能因 ATR 扩大而下移。

开仓初期，追踪止损初始值（entry − 3×ATR）低于止损（entry − 2×ATR），故止损先提供保护；
当 highest_high > entry + 1×ATR 时，trail_stop 自然超过止损，成为约束性条件。
""")

st.warning("""
**⚠️ 设计选项（待回测验证）：平价保护（Break-Even Stop）**

**概念**：浮盈达到 1R 后，将止损上移至开仓价，确保该笔交易不亏损。

```python
if R_multiple[t] >= 1:
    stop_loss = max(stop_loss, entry_price)
```

**支持的理由**：结构止损比 v1 更宽，平价保护可以对冲初始风险敞口；心理上也有助于持仓者更从容持仓。

**主要风险（尚未验证）**：

1. **回踩是突破策略的常见形态**：箱体突破后，价格常见"创新高 → 回踩原阻力位（≈入场价）→ 继续上涨"。
   平价保护在回踩时触发出场，会错失突破策略最重要的一类机会——**回踩后继续上涨的大趋势**。

2. **与追踪止损逻辑矛盾**：当浮盈正好达到 1R 时，trail_stop 仍低于入场价（entry − ATR），
   说明追踪止损认为此时距离合理噪音范围还有空间。平价保护强行插入更紧的约束，
   与"给趋势充分发展空间"的设计初衷冲突。

**结论**：在策略2.0完成回测之前，**暂不引入平价保护**。
回测完成后，通过分析"曾达到 1R 浮盈、最终被止损亏损出场"的交易数量和规模，
再决定是否引入，以及是否应将触发点调整为 **2R**（减少回踩触发风险）。
""")

st.markdown("---")

# ── 7. 仓位管理 ───────────────────────────────────────────────────────────────
st.subheader("7. 仓位管理（跟策略1.0一样）")

cols = st.columns(4)
steps = [
    ("Step 1", "目标风险", f"每笔交易风险 = NAV × {p['risk_per_trade']*100:.0f}%\n股数 = 目标风险 ÷ (入场价 − 止损价)"),
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

# ── 8. 相关性过滤 ─────────────────────────────────────────────────────────────
st.subheader("8. 相关性过滤（跟策略1.0一样）")
st.markdown(f"""
对每个候选标的，计算与**所有当前持仓**的 Pearson 相关系数，使用过去 60 个共有交易日的对数收益率序列。
若有效样本不足 40 天或标准差为 0，则视为不相关（不触发减仓）。

```python
r[t] = ln(close[t] / close[t-1])

max_corr = max(pearson_corr(r_new, r_i, window=60)
               for r_i in current_positions)

# 仅考虑正相关；负相关视为 0（负相关具有对冲效果，不减仓）
if max_corr > {p['correlation_threshold']:.2f}:
    final_shares = preliminary_shares × {p.get('correlation_reduction', 0.5):.1f}
else:
    final_shares = preliminary_shares
```

| 参数 | 值 | 说明 |
|------|-----|------|
| Correlation window | 60 日 | 计算相关性使用的历史窗口 |
| Min samples | 40 个 | 有效样本不足则视为不相关 |
| Correlation threshold | {p['correlation_threshold']:.2f} | 超过此值触发减仓 |
| Correlation reduction | {p.get('correlation_reduction', 0.5):.1f}× | 仓位减半 |
""")

st.markdown("---")

# ── 9. 组合层风险控制 ─────────────────────────────────────────────────────────
st.subheader("9. 组合层风险控制 — Heat Limit（跟策略1.0一样）")
st.markdown(f"""
```python
# 组合总热度 = 所有持仓的当前风险金额之和 / 净值
total_heat = sum(position_risk_i for all positions) / NAV

new_position_risk = final_shares × (entry_price - stop_loss)

if (total_heat + new_position_risk / NAV) > {p['heat_limit']:.2f}:
    skip_trade  # 放弃开仓（不是减仓）
```

Heat Limit（**{p['heat_limit']*100:.0f}% NAV**）是组合级别的风险上限，确保在极端行情下（多个仓位同时亏损）
总损失不超过可接受范围。超过热度上限时**放弃**新开仓，而非减少仓位规模。
""")

st.markdown("---")

# ── 10. 现金管理 ──────────────────────────────────────────────────────────────
st.subheader("10. 现金管理（跟策略1.0一样）")
st.markdown(f"""
**闲置资金管理：**
- 未持仓资金投入 **{meta.cash_proxy}**（iShares 1–3 年期国债 ETF）
- 获取无风险收益，降低现金拖累
""")

st.markdown("""
<div class="info-box">
<strong>为何使用 SHY 而非 SGOV？</strong><br>
SGOV（0–3 个月国债 ETF）于 <strong>2022 年</strong>才上市，若用于 2004–2021 年的回测，
现金将在该期间产生 0% 收益，严重低估策略的真实表现。
SHY（1–3 年期国债 ETF）自 <strong>2002 年</strong>起就有数据，可覆盖完整的 2004–2026 回测期，
能够正确模拟闲置资金赚取无风险利率的效果。
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# ── 11. 信号执行顺序 ──────────────────────────────────────────────────────────
st.subheader("11. 信号执行顺序（跟策略1.0一样）")
st.markdown("""
**多信号处理（同一天多个标的同时触发突破）：**
- 所有信号按 **突破强度（breakout_strength）降序排列**优先执行：`breakout_strength = adj_close[t] / max(adj_high[t-N:t-1])`
- 每执行完一笔后**立即更新**当前持仓和风险敞口，后续信号的相关性计算与组合热度检查均基于最新状态
- 优先处理突破最强的信号，可在热度上限耗尽前最大化资金利用效率

**退出优先级顺序：**

| 优先级 | 条件 | 触发方式 |
|--------|------|---------|
| Priority 1 | 止损：`low[t] < stop_loss` | 日内最低价，同日两条件均满足时此项优先 |
| Priority 2 | 移动止盈：`close[t] < trail_stop` | 收盘价，仅在止损未触发时检查 |

**执行时序：**
1. **t 日收盘后**：更新持仓状态（highest_high、trail_stop）；生成止盈信号；生成开仓信号
2. **t+1 日开盘**：先执行平仓指令，再执行开仓指令；同一标的在同一时点不会同时开仓与平仓

策略无固定止盈价位（Take Profit），持仓仅通过止损或移动止盈退出。
""")

st.markdown("---")

# ── 12. 参数敏感性分析范围 ────────────────────────────────────────────────────
st.subheader("12. 参数敏感性分析范围")
st.markdown("策略2.0的核心参数及敏感性测试范围：")

import pandas as _pd
_param_rows = [
    ("Entry", "突破回望窗口 N", "200", "150 / 200 / 250", "调整信号频率"),
    ("Entry", "横盘收敛回望窗口", "80 日", "60 / 80 / 100 日", "横盘期评估时间跨度"),
    ("Entry", "横盘收敛宽度阈值", "25%", "20% / 25% / 30%", "更严格/宽松的收敛要求"),
    ("Exit",  "追踪止损早期倍数（R<1）", "3×ATR", "2× / 3× / 4×", "早期止损松紧"),
    ("Exit",  "追踪止损后期倍数（R≥3）", "5×ATR", "4× / 5× / 6×", "大趋势阶段止损宽松程度"),
    ("Sizing", "相关性阈值", "0.7", "0.5 / 0.6 / 0.7 / 0.8", "过滤相关性的松紧"),
    ("Regime", "市场环境 SMA 窗口", "200 日", "100 / 150 / 200 日", "牛熊判断时间周期"),
]
st.dataframe(
    _pd.DataFrame(_param_rows, columns=["模块", "参数", "Baseline值", "测试值", "经济含义"]),
    use_container_width=True, hide_index=True,
)

st.markdown("---")

# ── 13. 与策略1.0对比总结 ─────────────────────────────────────────────────────
st.subheader("13. 策略2.0 vs 策略1.0 — 核心差异总结")

_diff_rows = [
    ("入场", "突破窗口 N", "200 日最高价（high）", "200 日最高价（high）", "完全相同"),
    ("入场", "横盘收敛过滤", "无", "✅ 必须：80 日内价格区间 < 25%", "2.0 核心 Edge"),
    ("入场", "突破强度条件", "突破倍数（可配置，默认关闭）", "当日阳线幅度 > 1%", "2.0 直接验证当日动能"),
    ("入场", "成交量过滤", "1.5×均量", "无", "2.0 暂不引入（横盘收敛已过滤低质量信号）"),
    ("止损", "机制", "ATR 固定止损（entry - 2×ATR）", "结构止损（max(ATR止损, 近期低点×0.995)）", "2.0 结合价格结构"),
    ("止盈", "机制", "分段追踪（3/3/5×ATR，按 R 档位）", "分段追踪（3/3/5×ATR，按 R 档位）", "相同（平价保护为待验证设计选项，暂不引入）"),
    ("仓位", "相关性过滤", "有（阈值 0.7，仓位减半）", "有（阈值 0.7，仓位减半）", "相同"),
    ("入场", "市场环境过滤", "SPY 200 日均线", "SPY 200 日均线", "相同"),
    ("组合", "Heat Limit", "10% NAV", "10% NAV", "相同"),
]
st.dataframe(
    _pd.DataFrame(_diff_rows,
                  columns=["模块", "维度", "策略1.0", "策略2.0", "说明"]),
    use_container_width=True, hide_index=True,
)
