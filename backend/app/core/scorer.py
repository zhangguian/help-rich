"""交易评分器(Domain 层纯函数,backend-arch §5.2 / project-book §4.3.2 + §4.3.6)

6 维度,各 20 分,满分 120:
- 集中度:单只占持仓比例(0 数据降级:持仓 < 3 只 → 15)
- 价格合理性:买入价相对成本偏离(追涨识别)
- 操作间隔:距上次同向操作天数(0 数据降级:历史 < 2 笔 → 15)
- 市场环境:三档(顺势 20 / 中性 10 / 逆势 0)—— 按**交易当日**的大盘涨跌幅
- 板块热度:当日板块排名(前 5 → 20,6~10 → 10,> 10 → 0)
  ⚠️ 当前 sector_rank 恒为 None → 该维恒 0 → 实际满分上限 100/120
- 交易时机:日内价格位置(低吸/追高)+ 时段适配(躲开开盘半小时与尾盘追单)

分数为相对参考,非绝对好坏。
"""
from datetime import date, time


# 维度键名(与 project-book §4.3.4 输出结构一致)
CONCENTRATION = "集中度"
PRICE_REASON = "价格合理性"
INTERVAL = "操作间隔"
MARKET_ENV = "市场环境"
SECTOR_HEAT = "板块热度"
TIMING = "交易时机"

DIMENSIONS = [CONCENTRATION, PRICE_REASON, INTERVAL, MARKET_ENV, SECTOR_HEAT, TIMING]

# 单维满分 & 总分上限
DIM_MAX = 20
SCORE_MAX = DIM_MAX * len(DIMENSIONS)  # 120

# 0 数据降级分(project-book §4.3.6 注释)
DEGRADED_CONCENTRATION = 15   # 持仓 < 3 只
DEGRADED_INTERVAL = 15        # 历史交易 < 2 笔

# 「交易时机」子项满分与中性降级分
TIMING_POSITION_MAX = 10      # 子项 A:日内价格位置
TIMING_SESSION_MAX = 10       # 子项 B:时段适配
TIMING_NEUTRAL = 5            # 缺数据时的中性降级分(不惩罚、不编造)

# 做 T 豁免窗口(GB-001 IR-2):同股近 N 日有反向交易 → 操作间隔维度豁免
# 数值取 product-requirements 场景 B 的"日内做 T + 短期做 T"覆盖范围
ROUND_TRIP_WINDOW_DAYS = 3

# A 股交易时段(分钟自 00:00 起算),用于「交易时机」的时段适配
_SESSION_OPEN = (9 * 60 + 30, 9 * 60 + 59)    # 09:30-09:59 开盘半小时
_SESSION_MORNING = (10 * 60, 11 * 60 + 29)   # 10:00-11:29 早盘
_SESSION_AFTERNOON = (13 * 60, 13 * 60 + 59)  # 13:00-13:59 午后
_SESSION_LATE = (14 * 60, 14 * 60 + 29)       # 14:00-14:29 尾盘前
_SESSION_CLOSE = (14 * 60 + 30, 15 * 60)      # 14:30-15:00 尾盘


def _to_date(d) -> date | None:
    """兼容 date / datetime / 'YYYY-MM-DD' 字符串"""
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        try:
            return date.fromisoformat(d)
        except ValueError:
            return None
    return None


def _concentration_score(all_positions: list, trade_shares: int, trade_price) -> int:
    """维度 1:集中度(20)

    规则(§4.3.6):
    - 持仓数 < 3 → 15(0 数据降级)
    - 集中度 = 本次交易市值 / (总持仓市值 + 本次市值)
      < 30% → 20;30~50% → 15;> 50% → 0
    """
    if len(all_positions) < 3:
        return DEGRADED_CONCENTRATION

    position_value = float(trade_shares) * float(trade_price)
    total_value = sum(
        float(p.get("shares", 0)) * float(p.get("avg_cost", p.get("total_cost", 0)) or 0)
        for p in all_positions
    ) + position_value

    if total_value <= 0:
        return DEGRADED_CONCENTRATION

    concentration = position_value / total_value
    if concentration < 0.30:
        return 20
    if concentration < 0.50:
        return 15
    return 0


def _price_reason_score(
    action: str,
    trade_price,
    position_before: dict | None,
) -> int:
    """维度 2:价格合理性(20)

    规则(§4.3.6):
    - buy 且已有持仓:成本偏离 |price - cost| / cost
      < 5% → 20;5~10% → 10;> 10% → 5(疑似追涨)
    - 卖出或新建仓(无持仓):默认 15
    """
    if action != "buy" or not position_before or position_before.get("shares", 0) <= 0:
        return 15

    cost = position_before.get("avg_cost")
    if cost is None or float(cost) <= 0:
        return 15

    cost_diff_pct = abs(float(trade_price) - float(cost)) / float(cost)
    if cost_diff_pct < 0.05:
        return 20
    if cost_diff_pct < 0.10:
        return 10
    return 5


def _is_round_trip(
    recent_trades: list,
    trade_date,
    stock_code: str,
    action: str,
    window_days: int = ROUND_TRIP_WINDOW_DAYS,
) -> bool:
    """识别做 T 场景(GB-001 IR-2)

    同股在交易日的 [0, window_days] 天内存在反向交易 → 视为合法做 T。
    使用条件:stock_code 必填;若缺 stock_code 视为非 T 场景(保守)。
    """
    if not stock_code:
        return False
    target = _to_date(trade_date)
    if target is None:
        return False
    opposite = "sell" if action == "buy" else "buy"
    for t in recent_trades:
        if t.get("stock_code") != stock_code:
            continue
        if t.get("action") != opposite:
            continue
        d = _to_date(t.get("trade_date"))
        if d is None:
            continue
        delta = (target - d).days
        if 0 <= delta <= window_days:
            return True
    return False


def _interval_score(
    recent_trades: list,
    trade_date,
    action: str,
    stock_code: str = "",
) -> int:
    """维度 3:操作间隔(20)

    规则(§4.3.6 + GB-001 IR-2):
    - 历史交易 < 2 笔 → 15(0 数据降级)
    - 同股近 3 日有反向交易 → 20(做 T 豁免,GB-001 IR-2)
    - 距上次同向操作 > 7 天 → 20;3~7 天 → 15;< 3 天 → 10
    - 无同向操作 → 20
    """
    # GB-001 IR-2:做 T 豁免优先判定(产品核心场景 vs 评分规则冲突的修复)
    # 即使历史 < 2 笔,也允许单笔反向交易触发豁免
    if _is_round_trip(recent_trades, trade_date, stock_code, action):
        return 20

    if len(recent_trades) < 2:
        return DEGRADED_INTERVAL

    target = _to_date(trade_date)
    if target is None:
        return DEGRADED_INTERVAL

    same_dir_dates = [
        _to_date(t.get("trade_date"))
        for t in recent_trades
        if t.get("action") == action
    ]
    same_dir_dates = [d for d in same_dir_dates if d is not None]

    if not same_dir_dates:
        return 20

    last_same = max(same_dir_dates)
    days_since = (target - last_same).days
    if days_since > 7:
        return 20
    if days_since > 3:
        return 15
    return 10


def _market_env_score(action: str, market_ctx: dict) -> int:
    """维度 4:市场环境(20,三档 v1.3)

    规则(§4.3.6):
    - buy 且大盘涨 > 0.3% → 20(顺势)
    - sell 且大盘跌 < -0.3% → 20(顺势)
    - 横盘(|pct| <= 0.3)→ 10(中性)
    - 其余 → 0(逆势)
    """
    pct = float(market_ctx.get("index_change_pct", 0) or 0)
    if action == "buy" and pct > 0.3:
        return 20
    if action == "sell" and pct < -0.3:
        return 20
    if abs(pct) <= 0.3:
        return 10
    return 0


def _sector_heat_score(stock_code: str, market_ctx: dict) -> int:
    """维度 5:板块热度(20)

    规则(§4.3.2 表格三档 + §4.3.6 简化):
    - sector_rank 提供排名:<= 5 → 20;6~10 → 10;> 10 → 0
    - 无 rank,但有 top5_sector_stocks 列表:命中 → 20,否则 → 0
    """
    rank = market_ctx.get("sector_rank")
    if rank is not None:
        if rank <= 5:
            return 20
        if rank <= 10:
            return 10
        return 0

    top5 = market_ctx.get("top5_sector_stocks", [])
    if top5 and stock_code in top5:
        return 20
    return 0


def _timing_position_score(
    action: str,
    price,
    day_bar: dict | None,
) -> int:
    """「交易时机」子项 A · 日内价格位置(0~10)

    规则:
    - pos = (成交价 − 当日最低) / (当日最高 − 当日最低),钳制到 [0, 1]
    - 买入:pos ≤ 0.30 → 10(低位买);0.30 < pos ≤ 0.70 → 6;pos > 0.70 → 2(追高)
    - 卖出:pos ≥ 0.70 → 10(高位卖);0.30 ≤ pos < 0.70 → 6;pos < 0.30 → 2(割在低位)
    - 当日无 K 线 / 一字板(high == low) → 5(中性降级,不编数字)
    """
    if not day_bar:
        return TIMING_NEUTRAL
    try:
        low = float(day_bar.get("low"))
        high = float(day_bar.get("high"))
        px = float(price)
    except (TypeError, ValueError):
        return TIMING_NEUTRAL
    if high <= low:
        return TIMING_NEUTRAL

    pos = (px - low) / (high - low)
    pos = max(0.0, min(1.0, pos))

    if action == "buy":
        if pos <= 0.30:
            return TIMING_POSITION_MAX
        if pos <= 0.70:
            return 6
        return 2
    # 卖出:高位卖为好
    if pos >= 0.70:
        return TIMING_POSITION_MAX
    if pos >= 0.30:
        return 6
    return 2


def _timing_session_score(action: str, trade_time: time | None) -> int:
    """「交易时机」子项 B · 时段适配(0~10)

    规则(A 股时段;非交易时段 / 时间未知 → 5 中性降级):
    - 买入:09:30-09:59 → 3(开盘半小时追高风险);10:00-11:29 → 10;
      13:00-13:59 → 10;14:00-14:29 → 7;14:30-15:00 → 3(尾盘隔夜风险)
    - 卖出:09:30-09:59 → 7(开盘冲高卖,波动大);10:00-14:29 → 10;14:30-15:00 → 8
    """
    if trade_time is None:
        return TIMING_NEUTRAL
    minutes = trade_time.hour * 60 + trade_time.minute

    def _in(win: tuple[int, int]) -> bool:
        return win[0] <= minutes <= win[1]

    if _in(_SESSION_OPEN):
        return 3 if action == "buy" else 7
    if _in(_SESSION_MORNING) or _in(_SESSION_AFTERNOON):
        return TIMING_SESSION_MAX
    if _in(_SESSION_LATE):
        return 7 if action == "buy" else TIMING_SESSION_MAX
    if _in(_SESSION_CLOSE):
        return 3 if action == "buy" else 8
    # 午休 / 非交易时段
    return TIMING_NEUTRAL


def _timing_score(
    action: str,
    price,
    trade_time: time | None,
    day_bar: dict | None,
) -> int:
    """「交易时机」维(0~20)= 日内价格位置(10) + 时段适配(10)"""
    return (
        _timing_position_score(action, price, day_bar)
        + _timing_session_score(action, trade_time)
    )


def score_trade(
    trade: dict,
    position_before: dict | None,
    recent_trades: list,
    market_ctx: dict,
    is_in_watchlist: bool,
    all_positions: list,
    day_bar: dict | None = None,
    trade_time: time | None = None,
) -> dict:
    """6 维度评分,纯函数(project-book §4.3.6)

    Args:
        trade: 本次交易 {
            stock_code, stock_name?, action, shares, price, trade_date, trade_time?
        }
        position_before: 交易前持仓 {shares, avg_cost, total_cost?} 或 None
        recent_trades: 历史交易列表(同 trade 结构),用于操作间隔
        market_ctx: {
            index_change_pct: **交易当日**大盘涨跌幅(%),
            sector_rank: 当日板块排名(1 起)或 None,
            top5_sector_stocks: [代码] 或 [],
        }
        is_in_watchlist: 是否在自选股(仅用于 AI 评语措辞,不影响分数)
        all_positions: 全部持仓列表(集中度 + 0 数据降级)
        day_bar: 交易当日该股日 K {low, high, ...} 或 None(交易时机·价格位置)
        trade_time: 交易时间点(HH:MM:SS)或 None(交易时机·时段适配)

    Returns:
        {"score": int 0~120, "score_breakdown": {维度: 分, ...}}
    """
    # 时间点:显式入参优先,其次从 trade 字典取
    if trade_time is None:
        trade_time = trade.get("trade_time")

    breakdown = {
        CONCENTRATION: _concentration_score(
            all_positions, int(trade.get("shares", 0)), trade.get("price", 0)
        ),
        PRICE_REASON: _price_reason_score(
            trade.get("action", ""), trade.get("price", 0), position_before
        ),
        INTERVAL: _interval_score(
            recent_trades,
            trade.get("trade_date"),
            trade.get("action", ""),
            trade.get("stock_code", ""),
        ),
        MARKET_ENV: _market_env_score(trade.get("action", ""), market_ctx),
        SECTOR_HEAT: _sector_heat_score(trade.get("stock_code", ""), market_ctx),
        TIMING: _timing_score(
            trade.get("action", ""),
            trade.get("price", 0),
            trade_time,
            day_bar,
        ),
    }

    score = max(0, min(SCORE_MAX, sum(breakdown.values())))
    return {"score": score, "score_breakdown": breakdown}


__all__ = [
    "score_trade",
    "DIMENSIONS",
    "DIM_MAX",
    "SCORE_MAX",
    "CONCENTRATION",
    "PRICE_REASON",
    "INTERVAL",
    "MARKET_ENV",
    "SECTOR_HEAT",
    "TIMING",
]
