"""持仓盈亏状态判定(共享口径)

**为什么从 api/stock.py 提取出来(spec 阶段9 任务1)**:
`position_status` 的判定规则是全项目**唯一来源**——决策卡、作战计划、
复盘都要用同一个口径。原先它住在 `api/stock.py` 的私有函数里,
新服务(作战计划)若复制一份,就会出现"两个判定口径"的问题:
一个真实持有 700 股 @23.04 的用户,拿不到报价时会被判成「空仓」→
对着已深套的持仓说「首仓 30%,可以建仓」(2026-10-21 评审发现的真实事故)。

本模块**纯函数、零 IO**,只接受已取好的数据。
`api/stock.py` 保留同名私有名做薄封装,既有 13 处测试 import 不破。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_position_status(
    position: Any, current_price: str | None, fallback_price: str | None = None
) -> tuple[str, float | None]:
    """根据持仓 + 现价判断 role:empty / profit / loss

    设计文档 §5「position_status 判定规则(唯一来源)」:
    ```
    shares == 0                 → 'empty'
    effective_price >= cost_basis → 'profit'
    否则                          → 'loss'
    ```
    其中 `effective_price = current_price if not None else indicators.latest_close`。

    **为什么必须有 fallback_price(2026-10-21 实跑评审发现的真实事故)**:
    原来这里在 `current_price is None` 时直接 `return "empty", None`。
    而实时价缺失是常态(非交易时段、报价源抖动、报价与 K 线偏差 >10% 被降级)。
    后果:一个**真实持有 700 股 @23.04** 的用户,拿不到报价时会被判成「空仓」→
    决策卡切到「建仓参考」模式 → 对着已深套的持仓说「首仓 30%,可以建仓」。
    实测复现:现价 14.35(不可用,按收盘价算)时 role=建仓参考、headline 写
    「当前无底仓,做 T 前需先建仓」—— 与持仓表里的 700 股直接矛盾。

    修法:报价缺失时用 **K 线最新收盘价** 兜底(与 §5 的 effective_price 口径一致);
    连兜底价都没有(极少见的 K 线也失败)时,保守取 'loss' ——
    宁可给「解套参考 + 止损/减仓」,也绝不能给「可以建仓」。

    Returns:
        (status, cost_basis_pct)
        status: empty / profit / loss
        cost_basis_pct: 基于持仓成本的盈亏百分比(0.05 = +5%);空仓 / 价格不可得时为 None
    """
    if position is None or position.shares <= 0:
        return "empty", None
    price = current_price if current_price is not None else fallback_price
    if price is None:
        # 有持仓但连收盘价都拿不到 → 无法判定盈亏,保守按 'loss' 处理
        return "loss", None
    try:
        cur = float(price)
        cost = float(position.avg_cost)
        if cost <= 0 or cur <= 0:
            return "loss", None
        pct = (cur / cost - 1.0)
        # 持平也归 'profit'(规则是 >= )—— 绝不能归 'empty':
        # 'empty' 会让决策卡给出「建仓参考 / 首仓 X%」,对已持仓者是误导。
        if cur >= cost:
            return "profit", pct
        return "loss", pct
    except (ValueError, TypeError):
        return "loss", None


def kline_fallback_price(klines: list[dict] | None) -> str | None:
    """K 线最新收盘价 —— 实时报价缺失时判定持仓盈亏的兜底价(§5 effective_price)"""
    if not klines:
        return None
    try:
        close = klines[-1].get("close")
        return str(close) if close is not None else None
    except (AttributeError, IndexError, TypeError):
        return None


def sanitize_current_price(
    quote, klines: list[dict] | None
) -> tuple[str | None, str | None]:
    """校验 current_price 与 K 线最新 close 的偏离度;偏差 > 10% 视为数据源异常,降级 None。

    Returns:
        (current_price_str, current_price_date_str) — 校验通过返回;否则 (None, None)
    """
    if quote is None:
        return None, None
    price = quote.current_price
    if price is None:
        return None, None
    current_price = str(price)
    current_price_date = quote.timestamp.date().isoformat() if quote.timestamp else None
    if klines:
        try:
            latest_close = float(klines[-1]["close"])
            cur = float(current_price)
            if latest_close > 0:
                deviation = abs(cur - latest_close) / latest_close
                if deviation > 0.10:
                    logger.warning(
                        "current_price 与 K 线 close 偏差过大: quote=%s kline=%s 偏差 %.2f%%, 降级",
                        current_price, latest_close, deviation * 100,
                    )
                    return None, None
        except (ValueError, TypeError):
            pass
    return current_price, current_price_date


__all__ = [
    "kline_fallback_price",
    "resolve_position_status",
    "sanitize_current_price",
]