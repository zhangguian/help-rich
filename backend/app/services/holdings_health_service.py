"""持仓体检服务(v0.4.0)

从持仓主数据表出发(结合实时行情 + 风险计算),输出:
- 组合:总市值 / 总浮盈 / 盈亏率 / 风险评分(复用 calc_risk)
- 单只:每只股票的 现价/浮盈/浮亏率/集中度/状态(健康/浮亏/高集中)
- 与 risk_report 的区别:本服务带实时行情浮盈,risk_report 纯结构风险
"""
import logging
from decimal import Decimal

from app.services.position_service import get_all_positions
from app.services.quote_service import QuoteService
from app.services.risk_service import PositionExposure, calc_risk

logger = logging.getLogger(__name__)


def _q2(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01")))


async def get_holdings_health() -> dict:
    """持仓体检(真实持仓表 + 实时行情)"""
    positions = await get_all_positions()
    if not positions:
        return {
            "total_positions": 0,
            "total_market_value": "0.00",
            "total_floating_pnl": "0.00",
            "pnl_ratio_pct": 0.0,
            "risk_level": "低",
            "risk_score": 0,
            "items": [],
            "quotes_unavailable": False,
        }

    # 实时行情(失败则该只降级为成本价,并标记)
    quote_service = QuoteService()
    codes = [p.stock_code for p in positions]
    quotes = {}
    try:
        for q in await quote_service.get_quotes(codes):
            quotes[q.code] = q
    except Exception as e:  # noqa: BLE001
        logger.warning("holdings-health: 行情获取失败,降级为成本价: %s", e)

    # 风险报告(纯结构)
    exposures: list[PositionExposure] = [
        PositionExposure(
            stock_code=p.stock_code,
            stock_name=p.stock_name,
            shares=p.shares,
            avg_cost=str(p.avg_cost),
            market_value=float(p.shares * p.avg_cost),
        )
        for p in positions
    ]
    risk = calc_risk(exposures)

    items = []
    total_mv = Decimal("0")
    total_pnl = Decimal("0")
    for p in positions:
        cost = p.total_cost
        q = quotes.get(p.stock_code)
        if q is not None:
            mv = q.current_price * p.shares
            pnl = (q.current_price - p.avg_cost) * p.shares
            current_price = q.current_price
            price_available = True
        else:
            mv = p.total_cost
            pnl = Decimal("0")
            current_price = p.avg_cost
            price_available = False
        total_mv += mv
        total_pnl += pnl

        ratio = risk["single_stock_concentration"].get(p.stock_code, 0.0)
        # 状态判定
        if ratio >= 30:
            status = "high_concentration"
        elif not price_available:
            status = "unknown"
        elif pnl > 0:
            status = "profit"
        elif pnl == 0:
            status = "flat"
        else:
            status = "loss"

        items.append({
            "stock_code": p.stock_code,
            "stock_name": p.stock_name,
            "shares": p.shares,
            "avg_cost": str(p.avg_cost),
            "current_price": _q2(current_price),
            "floating_pnl": _q2(pnl),
            "floating_pnl_ratio_pct": round(
                float(pnl / cost * 100) if cost > 0 else 0.0, 2
            ),
            "concentration_pct": ratio,
            "status": status,
            "price_available": price_available,
        })

    pnl_ratio = round(
        float(total_pnl / total_mv * 100) if total_mv > 0 else 0.0, 2
    )
    return {
        "total_positions": len(items),
        "total_market_value": _q2(total_mv),
        "total_floating_pnl": _q2(total_pnl),
        "pnl_ratio_pct": pnl_ratio,
        "risk_level": risk["risk_level"],
        "risk_score": risk["risk_score"],
        "warnings": risk["warnings"],
        "items": items,
        "quotes_unavailable": any(not it["price_available"] for it in items),
    }


__all__ = ["get_holdings_health"]
