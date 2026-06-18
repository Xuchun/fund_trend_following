"""如何减少大 R 的亏损交易"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[3]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st

st.title("如何减少大 R 的亏损交易")
st.caption("基于 Top 20 亏损交易分析，识别大 R 亏损的根本原因并提出可落地的改进建议")

st.markdown("---")

# ── 根本原因分类 ──────────────────────────────────────────────────────────────
st.subheader("大亏损的根本原因分类")
st.markdown("""
从 Top 20 亏损交易的数据模式看，大 R 亏损来自三类不同机制：

| 类型 | 描述 | 识别特征 |
|------|------|---------|
| **A 类：跳空穿透** | 股价一夜之间直接跳过止损价，实际亏损远超 1R | `gap_adjusted_loss_multiple < -1.05R` |
| **B 类：慢速磨损** | 趋势入场后标的缓慢横盘 / 小幅下跌，移动止损未能快速收紧，最终被拖出较大 R 亏损 | 持仓天数异常长 + R 倍数大负数 |
| **C 类：退市亏损** | 破产退市是不可控的尾部事件（被并购通常反而盈利） | `exit_reason == "delisted"` 且净盈亏为负 |

> **A 类和 B 类** 是可以用规则干预的，C 类只能通过仓位管理控制单笔损失上限。
""")

st.markdown("---")

# ── 建议 1 ────────────────────────────────────────────────────────────────────
st.subheader("建议 1：给单笔交易设实际亏损上限（Gap Cap）")
st.markdown("""
**针对 A 类跳空穿透。**

跳空本身无法提前阻止，但可以在**仓位定价时**预留缓冲——当 ATR 较大且标的历史跳空率偏高时，
自动压缩仓位，使得即便跳空 2 倍 ATR，实际损失也不超过设定的 R 上限。

**规则设计：**
""")
st.code("""
# 在计算 shares 时，额外加入跳空风险缓冲
max_loss_r = 2.0          # 单笔最大允许亏损倍数
gap_buffer = hist_gap_pct  # 该标的历史平均隔夜跳空幅度（如 3%）

effective_stop_dist = stop_dist + gap_buffer * entry_price
shares = (risk_per_trade * nav) / effective_stop_dist
shares = min(shares, (max_loss_r * risk_per_trade * nav) / stop_dist)
""", language="python")
st.markdown("""
**为什么不用 hard cap？** Hard cap（直接限制最大损失）会在跳空下方平仓，但同样会在大赢家快速回调时过早离场。
用仓位压缩而非硬止损，既控制了尾部风险，又不截断右侧收益。

**预期效果：** A 类交易的平均 R 亏损从 -2R 以上压缩到 -1.5R 以内，代价是平均仓位略有下降。
""")

st.markdown("---")

# ── 建议 2 ────────────────────────────────────────────────────────────────────
st.subheader("建议 2：财报前主动减仓或离场")
st.markdown("""
**针对 A 类跳空穿透中最高频的触发场景。**

财报日是跳空穿透最集中的来源。策略1.0当前对财报日无特殊处理，持仓直接穿越财报。

**规则设计：**
""")
st.code("""
# 每日信号生成时检查
if days_to_next_earnings(ticker) <= 3:
    if position_exists(ticker):
        # 方案 A：完全离场
        exit_position(ticker, reason="pre_earnings_exit")
        # 方案 B（保守）：将仓位压缩至 50%
        reduce_position(ticker, factor=0.5)
""", language="python")
st.markdown("""
**数据需求：** Tiingo 提供财报日历 API（`/iex/{ticker}/earnings`），可本地缓存后查询。

**收益与代价：**
- 收益：系统性消除财报跳空导致的 -2R 至 -5R 极端亏损
- 代价：会错过"财报超预期后继续飙涨"的行情，对大赢家有轻微负面影响

**建议先做回测验证**：统计 Top 20 亏损中有多少笔的最大跌幅发生在财报日附近，
若超过 50%，则财报过滤的收益非常明确。
""")

st.markdown("---")

# ── 建议 3 ────────────────────────────────────────────────────────────────────
st.subheader("建议 3：假突破快速离场（Failed Breakout Rule）")
st.markdown("""
**针对 B 类慢速磨损——这是最容易实现、副作用最小的改进。**

部分大亏损的模式是：突破后几天内价格就跌回突破位以下，然后策略持仓等到全额止损亏出去。
这类"假突破"应该在失败迹象出现时立刻离场，而不是等移动止损慢慢触发。

**规则设计：**
""")
st.code("""
FAILED_BREAKOUT_WINDOW = 10   # 入场后 N 天内观察
BREAKOUT_REFERENCE     = "entry_breakout_level"  # 突破基准线（200日高点）

# 每日收盘后检查持仓
for position in open_positions:
    days_held = (today - position.entry_date).days
    if days_held <= FAILED_BREAKOUT_WINDOW:
        if close_price < position.breakout_level:
            exit_position(position, reason="failed_breakout")
""", language="python")
st.markdown("""
**效果：** 把假突破的亏损从 -1.0R（等到全额止损）压缩到 -0.3R 至 -0.5R（提前离场）。

**关键验证点：** 需要确认这条规则不会误伤真正的大赢家——真趋势在突破后通常不会在 10 天内回到突破线下方。
可以用回测统计"最终 R > 3 的交易中，有多少在入场后 10 天内跌回突破线"来量化误伤比例。
""")

st.markdown("---")

# ── 建议 4 ────────────────────────────────────────────────────────────────────
st.subheader("建议 4：时间止损（Time Stop）")
st.markdown("""
**针对 B 类慢速磨损——与建议 3 互补，覆盖"没有回到突破线、但也没有产生盈利"的死磨场景。**

好的趋势交易在入场后不久就应该产生正浮盈。如果 30 天过去了还没有超过 +0.5R 的盈利，
这笔交易大概率是假突破或者市场时机选择不对，应该主动释放资金去寻找更好的机会。

**规则设计：**
""")
st.code("""
TIME_STOP_DAYS  = 30    # 观察窗口
MFE_THRESHOLD_R = 0.5   # 最高盈利阈值（R 倍数）

for position in open_positions:
    days_held = (today - position.entry_date).days
    mfe_r     = position.max_favorable_excursion_r  # 持仓期最高盈利

    if days_held > TIME_STOP_DAYS and mfe_r < MFE_THRESHOLD_R:
        # 将止损上移至入场价（保本离场），而非直接平仓
        position.stop_price = position.entry_price
""", language="python")
st.markdown("""
**为什么是"移止损至保本"而非直接平仓？** 直接平仓可能会错过隔天突然启动的趋势。
将止损移到保本位既保留了上行可能，又确保不会再产生亏损。

**额外收益：** 时间止损会加快资金周转，释放被"僵尸仓"占用的资金用于新的突破机会，
可能对整体 CAGR 有正面贡献。
""")

st.markdown("---")

# ── 建议 5 ────────────────────────────────────────────────────────────────────
st.subheader("建议 5：高波动环境压缩入场仓位")
st.markdown("""
**针对 A 类和 B 类——系统性降低高风险环境下的单笔敞口。**

当入场当天的 ATR% （ATR / 收盘价）显著高于该标的历史均值时，说明这是高波动环境，
跳空风险和假突破风险都更高。可以自动缩小仓位：

**规则设计：**
""")
st.code("""
# 当前 ATR% vs 历史均值的比值
atr_pct_today  = atr_today / close_today
atr_pct_hist   = atr_60d_mean / close_60d_mean  # 60日均值
vol_ratio      = atr_pct_today / atr_pct_hist

# 波动率超过历史均值时，线性压缩仓位
vol_scale = min(1.0, 1.0 / vol_ratio)   # 波动 2× 历史均值 → 仓位缩至 50%

shares = base_shares * vol_scale
""", language="python")
st.markdown("""
**适用场景：** 当市场整体波动率急升时（如 2008 年底、2020 年 3 月），
策略在每一笔新开仓上都自动降低风险敞口，而不需要依赖 Regime Filter 完全停止开仓。
这相当于在"完全开仓"和"完全停仓"之间增加一个平滑的中间档位。
""")

st.markdown("---")

# ── 效益评估汇总 ──────────────────────────────────────────────────────────────
st.subheader("综合效益评估")
st.markdown("""
| 建议 | 主要针对 | 减少大亏损效果 | 对整体 CAGR 影响 | 实现难度 | 建议优先级 |
|------|---------|--------------|----------------|---------|----------|
| 建议 3：假突破快速离场 | B 类慢速磨损 | ★★★★ | 低（甚至正向） | ★ 低 | 🔴 最高 |
| 建议 4：时间止损 | B 类慢速磨损 | ★★★ | 低偏正 | ★ 低 | 🔴 最高 |
| 建议 1：Gap Cap 压仓 | A 类跳空穿透 | ★★★★ | 低 | ★★ 中 | 🟡 高 |
| 建议 2：财报前减仓 | A 类跳空穿透 | ★★★★ | 中（需验证） | ★★ 中 | 🟡 高 |
| 建议 5：高波动压仓 | A + B 类 | ★★ | 极低 | ★ 低 | 🟢 中 |

**推荐实施顺序：**

1. **第一步**：先实现建议 3（假突破规则）+ 建议 4（时间止损）并做回测对比。
   这两条规则只需改动 `src/strategy/v1/exit.py`，无需外部数据，风险最低。

2. **第二步**：统计 l20 中跳空穿透笔数，如果 ≥ 5 笔，则进入建议 1（Gap Cap）的设计和验证。

3. **第三步**：引入 Tiingo 财报日历数据，实现建议 2，做专项回测验证净收益是否为正。
""")

st.markdown("---")

st.info(
    "以上建议均需通过参数敏感性分析和 Walk-Forward 验证后才能确认是否引入策略正式版本，"
    "避免过度拟合历史数据（尤其是针对 20 笔交易的特征做优化，样本量偏小）。"
)
