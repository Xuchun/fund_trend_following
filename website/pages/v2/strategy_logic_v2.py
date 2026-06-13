"""策略2.0 — 策略描述"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st
from website.shared import render_v2_page_header

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
| 策略类型 | 趋势跟踪（Trend Following） | 趋势跟踪（Trend Following） |
| 方向 | 纯多头（Long Only） | 纯多头（Long Only） |
| 核心 Edge | 突破前高 + 趋势延续 | **横盘收敛 + 箱体突破** |
| 入场信号 | N 日高点突破（单一条件） | 突破 + 横盘收敛 + 突破强度（4 个条件） |
| 止损 | ATR 固定止损 | **结构止损**（ATR + 近期低点双重保护） |
| 止盈 | 分段移动止盈（3/3/5×ATR） | 分段移动止盈（3/3/5×ATR，**与策略1.0相同**） |
| 仓位管理 | 固定比例风险（1% NAV/笔）+ 相关性过滤 | 固定比例风险（1% NAV/笔）+ 相关性过滤（**与策略1.0相同**） |
| 相关性过滤 | 有（Pearson 60 日，阈值 0.7） | 有（Pearson 60 日，阈值 0.7，**与策略1.0相同**） |
| 市场环境过滤 | 有（SPY 200 日均线） | 有（SPY 200 日均线，**与策略1.0相同**） |
| 执行 | 次日开盘价成交 | 次日开盘价成交 |

**核心假设**：资产价格经历充分横盘收敛并成功突破长期阻力位后，具有极强的趋势延续潜力。
横盘收敛代表供需均衡、能量积聚，突破时释放的动能往往比随机突破更持久。
""")

st.markdown("---")

# ── 基本原则 ──────────────────────────────────────────────────────────────────
st.subheader("基本原则")
st.markdown("""
- `price[t]` 指代 t 日收盘后可获得信息
- 下面所有计算，在 t 日收盘后进行，仅使用 t 日及之前的数据
- **所有信号（开仓 / 止损 / 止盈）在 t 日收盘生成，并在 t+1 日开盘执行**
- 价格约定：除 min_price 过滤器使用原始收盘价外，所有 close、high、low、open 均指**复权价格（adjusted price）**
""")

st.markdown("---")

# ── 标的过滤 ──────────────────────────────────────────────────────────────────
st.subheader("1. 标的过滤")
st.markdown("""
与策略1.0相同的流动性约束：

| 过滤条件 | 阈值 | 说明 |
|----------|------|------|
| 收盘价（原始价格） | > $10 | 排除低价股 |
| 市值 | > $20 亿美元（$2B） | 排除微盘股 |
| 日均成交额（ADV_60） | > $20M 美元 | 流动性过滤 |

```
ADV_60[t] = average(dollar_volume[t-59 : t])  # 含当日，共60天
```
""")

st.markdown("---")

# ── 入场条件 ──────────────────────────────────────────────────────────────────
st.subheader("2. 入场条件（4 个条件，全部满足方可入场）")

st.markdown("""
策略2.0的入场信号由 4 个条件组成。信号在 **t 日收盘后**生成，**t+1 日开盘**执行。
""")

st.markdown("#### 条件1：基础突破（Breakout）")
st.code("""
# 收盘价突破近 N 日最高收盘价
close[t] > max(close[t-N : t-1])
N = 100  # Baseline 参数
""", language="python")
st.markdown("""
> 使用过去 100 个交易日（约 5 个月）的最高**收盘价**作为突破基准，
> 捕捉中期趋势的启动点。比策略1.0的 200 日突破窗口更敏感，
> 信号更多但过滤条件也更严格（横盘收敛是真正的门槛）。
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

# ── 入场执行 ──────────────────────────────────────────────────────────────────
st.subheader("3. 入场执行")
st.code("""
# 在 t+1 日开盘价买入
entry_price = open[t+1] × (1 + slippage_bps / 10000)

# ── 跳空保护（唯一执行过滤）──
gap = open[t+1] / close[t] - 1

if gap > 0.05:          # 跳空高开 > 5%：放弃（风险过高）
    skip_trade = True
elif gap > 0.025:       # 跳空高开 2.5%-5%：仓位减半
    risk_multiplier = 0.5
elif gap < -0.02:       # 跳空低开 > 2%：放弃（可选）
    skip_trade = True
else:                   # 正常开盘
    risk_multiplier = 1.0
""", language="python")

st.markdown("---")

# ── 止损 ──────────────────────────────────────────────────────────────────────
st.subheader("4. 止损 — 结构止损（Structure Stop）")
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

# ── 止盈 ──────────────────────────────────────────────────────────────────────
st.subheader("5. 移动止盈 — 分段追踪止损（与策略1.0相同）")
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

# 触发退出：收盘价跌破追踪止损
if close[t] < trail_stop[t]:
    exit at open[t+1]
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

st.markdown("---")

# ── 仓位管理 ──────────────────────────────────────────────────────────────────
st.subheader("6. 仓位管理 — 4步风险等权（与策略1.0相同）")
st.code("""
# Step 1：原始仓位（1% NAV 风险）
risk_amount  = NAV × 1%
raw_shares   = risk_amount / (entry_price - stop_loss)

# Step 2：单标的市值上限（5% NAV）
capped_shares = NAV × 5% / entry_price
preliminary_shares = min(raw_shares, capped_shares)

# Step 3：相关性调整（见下节）
final_shares = preliminary_shares × (0.5 if max_corr > 0.7 else 1.0)

# Step 4：组合热度检查（见第9节）
new_risk   = final_shares × (entry_price - stop_loss)
total_heat = (existing_risk + new_risk) / NAV
if total_heat > 0.10:
    skip_trade   # 放弃开仓（不是减仓）
""", language="python")

st.markdown("---")

# ── 相关性过滤 ──────────────────────────────────────────────────────────────────
st.subheader("7. 相关性过滤（与策略1.0相同）")
st.code("""
# 对数收益率
r[t] = ln(close[t] / close[t-1])

# 对每个候选标的，计算与所有当前持仓的 Pearson 相关性
# 使用过去 60 个共有交易日的对数收益率序列（inner join + 取最近 60 个）
# 若有效样本 < 40 或标准差为 0，则视为不相关（不触发减仓）

max_corr = max(pearson_corr(r_new, r_i, window=60)
               for r_i in current_positions)

# 仅考虑正相关；负相关视为 0（负相关具有对冲效果，不减仓）
if max_corr > 0.7:
    final_shares = preliminary_shares × 0.5
else:
    final_shares = preliminary_shares
""", language="python")

st.markdown("""
| 参数 | 值 | 说明 |
|------|-----|------|
| Correlation window | 60 日 | 计算相关性使用的历史窗口 |
| Min samples | 40 个 | 有效样本不足则视为不相关 |
| Correlation threshold | 0.7 | 超过此值触发减仓 |
| Correlation reduction | 0.5× | 仓位减半 |
""")

st.markdown("---")

# ── 市场环境过滤 ──────────────────────────────────────────────────────────────
st.subheader("8. 市场环境过滤 — SPY 200 日均线（与策略1.0相同）")
st.code("""
# 牛市（Bull）：SPY adj_close[t] > SMA(200)[t]
#   → 正常扫描入场信号，允许开新仓

# 熊市（Bear）：SPY adj_close[t] ≤ SMA(200)[t]
#   → 停止新开仓（pending_entries = []）
#   → 已有持仓按止损 / 追踪止损继续运行，不强制平仓
#   → 空仓资金继续配置到短债 ETF
""", language="python")

st.markdown("""
| 模式 | 条件 | 策略行为 |
|------|------|---------|
| 牛市（Bull） | SPY > SMA(200) | 正常扫描入场信号 |
| 熊市（Bear） | SPY ≤ SMA(200) | 停止新开仓；持仓继续运行；现金投入短债 ETF |
""")

st.markdown("---")

# ── 组合风险控制 ──────────────────────────────────────────────────────────────
st.subheader("9. 组合层风险控制（Heat Limit）— 与策略1.0相同")
st.code("""
# 组合总热度 = 所有持仓的当前风险金额之和 / 净值
total_heat = sum(position_risk_i for all positions) / NAV

new_position_risk = final_shares × (entry_price - stop_loss)

if (total_heat + new_position_risk / NAV) > 0.10:
    skip_trade  # 放弃开仓（不是减仓）
""", language="python")

st.markdown("""
Heat Limit（10% NAV）是组合级别的风险上限，确保在极端行情下（多个仓位同时亏损）
总损失不超过可接受范围。与策略1.0相同，超过热度上限时**放弃**新开仓，而非减少仓位规模。
""")

st.markdown("---")

# ── 现金管理 ──────────────────────────────────────────────────────────────────
st.subheader("10. 现金管理")
st.markdown("""
空仓资金自动配置到**短期国债 ETF**，赚取无风险利率，不参与策略信号计算。

与策略1.0使用 **SHY**（1-3 年期国债 ETF，覆盖完整回测期 2002+）保持一致。
""")

st.markdown("---")

# ── 信号执行顺序 ──────────────────────────────────────────────────────────────
st.subheader("11. 信号执行顺序")
st.markdown("""
与策略1.0相同的执行时序：

1. **t 日收盘后**：更新持仓状态（highest_high、trail_stop）；生成止盈信号；生成开仓信号
2. **t+1 日开盘**：先执行平仓指令，再执行开仓指令；同一标的在同一时点不会同时开仓与平仓
""")

st.markdown("---")

# ── 参数敏感性分析范围 ──────────────────────────────────────────────────────────
st.subheader("12. 参数敏感性分析范围")
st.markdown("策略2.0的核心参数及敏感性测试范围：")

import pandas as _pd
_param_rows = [
    ("Entry", "突破回望窗口 N", "100", "80 / 100 / 120", "调整信号频率"),
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

# ── 与策略1.0对比总结 ────────────────────────────────────────────────────────
st.subheader("13. 策略2.0 vs 策略1.0 — 核心差异总结")

_diff_rows = [
    ("入场", "突破窗口 N", "200 日最高价（high）", "100 日最高收盘价（close）", "2.0 更灵敏，配合横盘过滤补偿"),
    ("入场", "横盘收敛过滤", "无", "✅ 必须：80 日内价格区间 < 25%", "2.0 核心 Edge"),
    ("入场", "突破强度条件", "突破倍数（可配置，默认关闭）", "当日阳线幅度 > 1%", "2.0 直接验证当日动能"),
    ("入场", "成交量过滤", "1.5×均量", "无", "2.0 暂不引入（横盘收敛已过滤低质量信号）"),
    ("止损", "机制", "ATR 固定止损（entry - 2×ATR）", "结构止损（max(ATR止损, 近期低点×0.995)）", "2.0 结合价格结构"),
    ("止盈", "机制", "分段追踪（3/3/5×ATR，按 R 档位）", "分段追踪（3/3/5×ATR，按 R 档位）", "相同"),
    ("仓位", "相关性过滤", "有（阈值 0.7，仓位减半）", "有（阈值 0.7，仓位减半）", "相同"),
    ("入场", "市场环境过滤", "SPY 200 日均线", "SPY 200 日均线", "相同"),
    ("组合", "Heat Limit", "10% NAV", "10% NAV", "相同"),
]
st.dataframe(
    _pd.DataFrame(_diff_rows,
                  columns=["模块", "维度", "策略1.0", "策略2.0", "说明"]),
    use_container_width=True, hide_index=True,
)
