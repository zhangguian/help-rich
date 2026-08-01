"""交易评分器(Domain 层纯函数,backend-arch §5.2 / project-book §4.3.2 + §4.3.6)

5 维度,各 20 分,满分 100:
- 集中度:单只占持仓比例(0 数据降级:持仓 < 3 只 → 15)
- 价格合理性:买入价相对成本偏离(追涨识别)
- 操作间隔:距上次同向操作天数(0 数据降级:历史 < 2 笔 → 15)
- 市场环境:三档(顺势 20 / 中性 10 / 逆势 0)
- 板块热度:当日板块排名(前 5 → 20,6~10 → 10,> 10 → 0)

分数为相对参考,非绝对好坏。
"""
from datetime import date
from typing import Optional


# 维度键名(与 project-book §4.3.4 输出结构一致)
CONCENTRATION = "集中度"
PRICE_REASON = "价格合理性"
INTERVAL = "操作间隔"
MARKET_ENV = "市场环境"
SECTOR_HEAT = "板块热度"

DIMENSIONS = [CONCENTRATION, PRICE_REASON, INTERVAL, MARKET_ENV, SECTOR_HEAT]

# 0 数据降级分(project-book §4.3.6 注释)
DEGRADED_CONCENTRATION = 15   # 持仓 < 3 只
DEGRADED_INTERVAL = 15        # 历史交易 < 2 笔


def _to_date(d) -> Optional[date]:
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
    position_before: Optional[dict],
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


def _interval_score(recent_trades: list, trade_date, action: str) -> int:
    """维度 3:操作间隔(20)

    规则(§4.3.6):
    - 历史交易 < 2 笔 → 15(0 数据降级)
    - 距上次同向操作 > 7 天 → 20;3~7 天 → 15;< 3 天 → 10
    - 无同向操作 → 20
    """
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


def score_trade(
    trade: dict,
    position_before: Optional[dict],
    recent_trades: list,
    market_ctx: dict,
    is_in_watchlist: bool,
    all_positions: list,
) -> dict:
    """5 维度评分,纯函数(project-book §4.3.6)

    Args:
        trade: 本次交易 {
            stock_code, stock_name?, action, shares, price, trade_date
        }
        position_before: 交易前持仓 {shares, avg_cost, total_cost?} 或 None
        recent_trades: 历史交易列表(同 trade 结构),用于操作间隔
        market_ctx: {
            index_change_pct: 当日大盘涨跌幅(%),
            sector_rank: 当日板块排名(1 起)或 None,
            top5_sector_stocks: [代码] 或 [],
        }
        is_in_watchlist: 是否在自选股(仅用于 AI 评语措辞,不影响分数)
        all_positions: 全部持仓列表(集中度 + 0 数据降级)

    Returns:
        {"score": int 0~100, "score_breakdown": {维度: 分, ...}}
    """
    breakdown = {
        CONCENTRATION: _concentration_score(
            all_positions, int(trade.get("shares", 0)), trade.get("price", 0)
        ),
        PRICE_REASON: _price_reason_score(
            trade.get("action", ""), trade.get("price", 0), position_before
        ),
        INTERVAL: _interval_score(
            recent_trades, trade.get("trade_date"), trade.get("action", "")
        ),
        MARKET_ENV: _market_env_score(trade.get("action", ""), market_ctx),
        SECTOR_HEAT: _sector_heat_score(trade.get("stock_code", ""), market_ctx),
    }

    score = max(0, min(100, sum(breakdown.values())))
    return {"score": score, "score_breakdown": breakdown}


__all__ = [
    "score_trade",
    "DIMENSIONS",
    "CONCENTRATION",
    "PRICE_REASON",
    "INTERVAL",
    "MARKET_ENV",
    "SECTOR_HEAT",
]
