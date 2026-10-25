"""决策上下文的共享装配(v0.10 操作建议增强)

**为什么需要这个模块**:决策上下文有两个装配点——

- `app/api/stock.py::decision`            —— 决策卡(实时行情路径)
- `app/modules/calculator/service.py::build_decision_context` —— 计算器 T 卡(60s 慢缓存路径)

v0.10 之后两者都要注入**同一批新输入**(费用档 / 账户现金 / 集中度 / 持有天数)。
若各写各的,两处就会给出两套口径 → 与「消除两套说法打架」的目标直接矛盾。

**分工**:
- 本模块只负责**新增输入**的读取与注入;
- klines / indicators / env / quote / 单票持仓仍由各装配点自行取
  (两者的缓存语义不同:calculator 走 60s 慢缓存,合并会改变其响应时间)。

**纪律**:
- 每个来源**独立** try/except:某个读不到就置 None + 记 degraded,**不阻塞其余**;
- 绝不用默认值冒充缺失数据(费用档除外 —— 见 `decision_service._effective_fees`:
  费用设置未启用时按**已存储的费率档**估算,属系统常量,不是编造)。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

from app.core.cost_engine import TradeFees
from app.core.instrument import fees_for_instrument
from app.repositories.cost_settings_repo import cost_settings_repo
from app.services.decision_service import DecisionContext

# 跨域只准 import 对方的 service.py(ADR-0001 / 架构守卫测试)
from app.modules.portfolio.service import (
    get_all_positions,
    get_cash_available,
    get_position_start_date,
)


@dataclass(frozen=True)
class DecisionExtras:
    """决策层的新增输入(全部可缺;None = 取不到,调用方据此降级)"""

    fees: TradeFees | None = None
    cash_available: float | None = None
    position_share_pct: float | None = None
    holding_days: int | None = None
    degraded: list[str] = field(default_factory=list)


def parse_date(value: Any) -> date | None:
    """把 K 线的 'YYYY-MM-DD' 字符串解析成 date;失败返回 None"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(value.strip()[:10], fmt).date()
            except ValueError:
                continue
    return None


async def load_decision_extras(
    code: str,
    as_of: date | None = None,
) -> DecisionExtras:
    """读取决策层的新增输入。

    Args:
        code: 6 位代码 + 市场后缀(如 '000807.SZ')
        as_of: 计算「持有天数」的基准日(通常是 K 线最新日);None = 今天

    Returns:
        DecisionExtras —— 任一项取不到时该字段为 None,并在 degraded 里说明。
    """
    degraded: list[str] = []

    # --- 费用档(按品种选档:ETF 免印花税/过户费) ---
    fees: TradeFees | None = None
    try:
        base = await cost_settings_repo.get()
        fees = fees_for_instrument(code, base)
    except Exception as exc:  # noqa: BLE001
        degraded.append(f"费用档读取失败,费用相关维度不可用({exc})")

    # --- 账户可用资金 ---
    cash: float | None = None
    try:
        raw_cash = await get_cash_available()
        cash = float(raw_cash) if raw_cash is not None else None
        if raw_cash is None:
            degraded.append("账户可用资金未填写")
    except Exception as exc:  # noqa: BLE001
        degraded.append(f"账户可用资金读取失败({exc})")

    # --- 集中度:该票持仓成本 ÷ 全量持仓成本合计 ---
    share_pct: float | None = None
    try:
        positions = await get_all_positions()
        total_cost = sum(
            float(p.total_cost) for p in positions if p.shares > 0
        )
        if total_cost > 0:
            own = next(
                (float(p.total_cost) for p in positions if p.stock_code == code),
                None,
            )
            if own is not None:
                share_pct = own / total_cost * 100
    except Exception as exc:  # noqa: BLE001
        degraded.append(f"全量持仓读取失败,集中度不可用({exc})")

    # --- 持有天数 ---
    holding_days: int | None = None
    try:
        start = await get_position_start_date(code)
        if start is None:
            degraded.append("持仓起始日不可用,持有天数未知")
        else:
            end = as_of or date.today()
            holding_days = max((end - start).days, 0)
    except Exception as exc:  # noqa: BLE001
        degraded.append(f"持仓起始日读取失败,持有天数未知({exc})")

    return DecisionExtras(
        fees=fees,
        cash_available=cash,
        position_share_pct=share_pct,
        holding_days=holding_days,
        degraded=degraded,
    )


def enrich_decision_context(
    ctx: DecisionContext,
    extras: DecisionExtras,
) -> DecisionContext:
    """把新增输入注入决策上下文(纯函数)。

    既有字段一律不动 —— 这保证「只增信息,不改既有判定」。
    """
    return replace(
        ctx,
        fees=extras.fees,
        cash_available=extras.cash_available,
        position_share_pct=extras.position_share_pct,
        holding_days=extras.holding_days,
    )


__all__ = [
    "DecisionExtras",
    "load_decision_extras",
    "enrich_decision_context",
    "parse_date",
]
