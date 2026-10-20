"""回测成本模型(阶段2)。

直接复用 `app.core.cost_engine` 的 A 股真实费率(佣金万2.5/最低5元、
印花税卖出 0.05%、过户费双向),**不另造一套** —— 回测成本口径必须和
实盘成本口径一致,否则回测结果没有参考价值。

额外提供回测专用能力:
- `round_trip_cost_pct`:估算一次完整买卖的成本占比(用于滑点预估)
- `apply_slippage`:滑点(默认 0,即按收盘价成交;可设 bps)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.cost_engine import TradeFees, buy_fee, sell_fee


@dataclass(slots=True)
class CostModel:
    """回测成本配置。

    默认 **强制开启费用**:`TradeFees.enabled` 默认 False(实盘用于"双口径展示"),
    若直接复用会让回测收益虚高 —— 一次完整买卖约 0.13% 的成本在高频轮换下
    会显著扭曲结果。回测必须默认计费,除非调用方显式关掉。
    """

    fees: TradeFees = field(default_factory=lambda: TradeFees(enabled=True))
    # 滑点(基点,bps)。0 = 按信号日收盘价成交;10bps = 成交价劣化 0.1%
    slippage_bps: float = 0.0

    def buy_cost(self, shares: int, price: float) -> float:
        p = Decimal(str(price)) * (1 + Decimal(str(self.slippage_bps)) / 10000)
        return float(buy_fee(shares, p, self.fees))

    def sell_cost(self, shares: int, price: float) -> float:
        p = Decimal(str(price)) * (1 - Decimal(str(self.slippage_bps)) / 10000)
        return float(sell_fee(shares, p, self.fees))

    def buy_fill_price(self, price: float) -> float:
        """买入成交价(含滑点)。"""
        return price * (1 + self.slippage_bps / 10000)

    def sell_fill_price(self, price: float) -> float:
        """卖出成交价(含滑点)。"""
        return price * (1 - self.slippage_bps / 10000)

    def round_trip_cost_pct(self, price: float = 10.0, shares: int = 100) -> float:
        """一次完整买卖的成本占成交额比例(粗估,用于预期校验)。"""
        total = self.buy_cost(shares, price) + self.sell_cost(shares, price)
        amount = price * shares * 2
        return total / amount if amount else 0.0


# 无滑点的默认模型(最常用)
DEFAULT_COST_MODEL = CostModel()

__all__ = ["CostModel", "DEFAULT_COST_MODEL"]
