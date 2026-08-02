"""交易成本计算器(Domain 层纯函数,backend-arch §5.1 / project-book §4.2)

核心算法:加权平均法
- 加仓:
    S' = S₀ + S₁
    T' = T₀ + (S₁ × P₁)
    C' = T' / S'
- 减仓:
    S' = S₀ - S₁
    C' = C₀                              # 剩余持仓成本不变(成本法)
    已实现盈亏 = (P₁ - C₀) × S₁
    T' = C₀ × S'                         # 按成本冲减(非按成交价回收;差额计入 realized)
- 清仓(S₁ = S₀):
    S' = 0
    C' = null

21 档盈亏表(基准 = C' 新成本):
    21 个点,从 -10% 到 +10%,步长 1%
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Optional


# 精度常量
PRICE_QUANTUM = Decimal("0.001")   # 价格 3 位小数
MONEY_QUANTUM = Decimal("0.01")    # 金额 2 位小数


def _q_price(d: Decimal) -> Decimal:
    """价格量化到 3 位小数"""
    return d.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)


def _q_money(d: Decimal) -> Decimal:
    """金额量化到 2 位小数"""
    return d.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def calculate_after_transaction(
    shares_before: int,
    cost_before: Decimal,
    action: Literal["buy", "sell"],
    tx_shares: int,
    tx_price: Decimal,
) -> dict:
    """计算交易后的持仓 + 已实现盈亏

    Args:
        shares_before: 交易前持仓股数(可为 0,表示空仓建仓)
        cost_before: 交易前加权平均成本(Decimal,3 位小数;空仓时给 0)
        action: 'buy' 或 'sell'
        tx_shares: 本次交易股数(必须 > 0)
        tx_price: 本次交易价格(Decimal,必须 > 0)

    Returns:
        {
          "shares_after": int,
          "cost_after": Optional[Decimal],   # 清仓时 None
          "total_cost_after": Decimal,        # 剩余持仓的总成本
          "delta_cost": Decimal,              # 新成本 - 旧成本(清仓时 None)
          "realized_pnl": Decimal,            # 已实现盈亏(本次交易产生)
          "is_closed": bool,                   # 是否清仓
        }

    Raises:
        ValueError: tx_shares <= 0 / tx_price <= 0 / 卖出超过持仓
    """
    if tx_shares <= 0:
        raise ValueError(f"tx_shares 必须 > 0,实际 {tx_shares}")
    if tx_price <= 0:
        raise ValueError(f"tx_price 必须 > 0,实际 {tx_price}")

    if action == "buy":
        new_shares = shares_before + tx_shares
        new_total_cost = (cost_before * shares_before) + (tx_price * tx_shares)
        new_cost = (new_total_cost / new_shares) if new_shares > 0 else Decimal("0")
        realized_pnl = Decimal("0")
        delta_cost = (new_cost - cost_before) if shares_before > 0 else new_cost

        return {
            "shares_after": new_shares,
            "cost_after": _q_price(new_cost) if new_shares > 0 else None,
            "total_cost_after": _q_money(new_total_cost),
            "delta_cost": _q_price(delta_cost) if shares_before > 0 else _q_price(new_cost),
            "realized_pnl": _q_money(realized_pnl),
            "is_closed": False,
        }

    # action == "sell"
    if tx_shares > shares_before:
        raise ValueError(
            f"卖出 {tx_shares} 股超过持仓 {shares_before} 股"
        )

    # 卖出前 avg_cost(未量化,避免累计精度损失)
    avg_cost_before = cost_before  # shares_before > 0 时已保证非零
    new_shares = shares_before - tx_shares
    new_cost = avg_cost_before  # 剩余持仓成本不变
    new_total_cost = avg_cost_before * new_shares
    realized_pnl = (tx_price - avg_cost_before) * tx_shares

    is_closed = new_shares == 0
    delta_cost = Decimal("0") if not is_closed else None

    return {
        "shares_after": new_shares,
        "cost_after": None if is_closed else _q_price(new_cost),
        "total_cost_after": _q_money(new_total_cost),
        "delta_cost": delta_cost,
        "realized_pnl": _q_money(realized_pnl),
        "is_closed": is_closed,
    }


def build_pnl_grid(
    cost_after: Optional[Decimal],
    shares_after: int,
    pct_range: int = 10,
) -> list[dict]:
    """21 档盈亏表(基准 = 新成本价)

    Args:
        cost_after: 新成本价(清仓时为 None,返回空 list)
        shares_after: 新持仓股数(为 0 时返回空 list)
        pct_range: ± 范围(默认 10,即 -10% ~ +10%,共 21 档)

    Returns:
        [
          {"pct": -10, "price": Decimal, "market_value": Decimal, "pnl": Decimal},
          ...
        ]
    """
    if cost_after is None or shares_after <= 0 or pct_range <= 0:
        return []

    rows = []
    for pct in range(-pct_range, pct_range + 1):
        factor = Decimal("1") + Decimal(pct) / Decimal("100")
        price = _q_price(cost_after * factor)
        market_value = _q_money(price * shares_after)
        pnl = _q_money(market_value - cost_after * shares_after)
        rows.append({
            "pct": pct,
            "price": price,
            "market_value": market_value,
            "pnl": pnl,
        })
    return rows


# 兼容别名(MVP 前端可能用)
def calc(after: dict) -> dict:
    """便捷函数:给前端返回 dict(Decimal → str)"""
    return {
        "shares_after": after["shares_after"],
        "cost_after": str(after["cost_after"]) if after["cost_after"] is not None else None,
        "total_cost_after": str(after["total_cost_after"]),
        "delta_cost": str(after["delta_cost"]) if after["delta_cost"] is not None else None,
        "realized_pnl": str(after["realized_pnl"]),
        "is_closed": after["is_closed"],
    }


__all__ = [
    "calculate_after_transaction",
    "build_pnl_grid",
    "calc",
    "PRICE_QUANTUM",
    "MONEY_QUANTUM",
]