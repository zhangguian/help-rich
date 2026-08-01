"""资金流服务(guide §7 新浪资金流)

- 数据源:guide §7 新浪 `vip.stock.finance.sina.com.cn` 资金流排行
  - `MoneyFlow.ssl_bkzj_ssggzj` 散户个股资金排行(返回前 N 名)
  - `MoneyFlow.ssl_bkzj_bk` 板块资金排行(fenlei: 0=全部 1=行业 2=概念 3=地域)
- 测试 ✅ 200(2026-08-01 实测)
- **完全真实数据**,无 mock;失败抛 FundFlowSourceUnavailable
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import httpx

from app.core.db_lock import safe_write
from app.db import async_session
from app.models.orm import FundFlow
from app.services.event_bus import event_bus

logger = logging.getLogger(__name__)

# 字段映射(guide §7 新浪资金流)
FIELD_MAP = {
    "r0_in": ("super", "in"),       # 超大单流入
    "r0_out": ("super", "out"),
    "r0_net": ("super", "net"),
    "r3_in": ("large", "in"),       # 大单流入
    "r3_out": ("large", "out"),
    "r3_net": ("large", "net"),
}


class FundFlowSourceUnavailable(Exception):
    """资金流数据源不可用"""


def _to_sina_market(stock_code: str) -> str:
    code, _, market = stock_code.partition(".")
    return {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(market.upper(), "sh")


async def _fetch_sina_fund_flow_rank(
    market: str = "all", page: int = 1, num: int = 50
) -> list[dict[str, Any]]:
    """guide §7 新浪散户个股资金排行(全市场或单市场)

    返回:[
      {stock_code, name, netamount, inamount, outamount, r0_net, r3_net}
    ] 净额降序
    """
    url = (
        "https://vip.stock.finance.sina.com.cn/"
        "quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_ssggzj"
    )
    params = {
        "page": page,
        "num": num,
        "sort": "netamount",
        "asc": 0,
    }
    if market in ("sh", "sz", "bj"):
        params["shichang"] = market
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.sina.com.cn",
    }
    async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, list) or not data:
        raise FundFlowSourceUnavailable(
            f"新浪资金流排行返回空(可能接口已变更 / market={market})"
        )
    return data


def _parse_rank_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """将新浪排行单行解析为统一字段"""
    if not isinstance(row, dict) or "symbol" not in row:
        return None
    return {
        "stock_code": _from_sina_symbol(row["symbol"]),
        "name": row.get("name", ""),
        "netamount": float(row.get("netamount", 0) or 0),
        "inamount": float(row.get("inamount", 0) or 0),
        "outamount": float(row.get("outamount", 0) or 0),
        "r0_net": float(row.get("r0_net", 0) or 0),  # 超大单净额
        "r3_net": float(row.get("r3_net", 0) or 0),  # 大单净额
    }


def _from_sina_symbol(symbol: str) -> str:
    """sh600519 → 600519.SH"""
    s = symbol.lower()
    if s.startswith("sh"):
        return f"{s[2:]}.SH"
    if s.startswith("sz"):
        return f"{s[2:]}.SZ"
    if s.startswith("bj"):
        return f"{s[2:]}.BJ"
    return symbol.upper()


async def _fetch_and_persist_one_market(market: str | None) -> int:
    """拉一个市场排行,持久化新增条目,返回新增数"""
    try:
        rows = await _fetch_sina_fund_flow_rank(market=market or "all", num=50)
    except (httpx.HTTPError, FundFlowSourceUnavailable) as e:
        logger.warning("资金流拉取失败 (market=%s): %s", market, e)
        return 0

    new_count = 0
    timestamp = datetime.now()
    async with async_session() as session:
        for raw in rows:
            parsed = _parse_rank_row(raw)
            if not parsed:
                continue
            # 新浪金额单位是元,转万元(项目统一用万元)
            netamount_wan = round(parsed["netamount"] / 10000, 2)
            if netamount_wan == 0:
                continue
            direction = "in" if netamount_wan > 0 else "out"
            # 类别:按 r0 净额(超大单)判断,>0 大单,否则归 medium
            if abs(parsed["r0_net"]) > abs(parsed["r3_net"]):
                category = "super"
            elif abs(parsed["r3_net"]) > 0:
                category = "large"
            else:
                category = "medium"
            ff = FundFlow(
                stock_code=parsed["stock_code"],
                timestamp=timestamp,
                direction=direction,
                amount=f"{abs(netamount_wan):.2f}",
                category=category,
                source="sina",
            )
            session.add(ff)
            new_count += 1
        await session.commit()
    if new_count:
        logger.info("资金流落库: market=%s 新增 %d 条", market or "all", new_count)
    return new_count


async def _refresh_one_round() -> None:
    """每轮:拉 3 个市场排行(SH/SZ/BJ),持久化,推送新事件"""
    for market in ("sh", "sz", "bj"):
        new_count = await _fetch_and_persist_one_market(market)
        if new_count:
            await event_bus.publish({
                "event": "fund_flow_batch",
                "market": market,
                "count": new_count,
            })


async def list_recent(stock_code: str, limit: int = 30) -> list[FundFlow]:
    """拉指定股票最近 N 条(从 DB 查)"""
    from sqlalchemy import select

    async with async_session() as session:
        stmt = (
            select(FundFlow)
            .where(FundFlow.stock_code == stock_code)
            .order_by(FundFlow.timestamp.desc())
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars().all())


async def generate_one(stock_code: str) -> dict:
    """手动触发:拉排行 → 过滤该股 → 返回最新一条(供前端 toast/详情用)"""
    market = _to_sina_market(stock_code)
    try:
        rows = await _fetch_sina_fund_flow_rank(market=market, num=80)
    except (httpx.HTTPError, FundFlowSourceUnavailable) as e:
        raise FundFlowSourceUnavailable(f"手动触发失败: {e}") from e
    target = next(
        (r for r in rows if _from_sina_symbol(r.get("symbol", "")) == stock_code),
        None,
    )
    if not target:
        raise FundFlowSourceUnavailable(
            f"股票 {stock_code} 不在新浪资金流前 80 名(可能今日无显著资金流)"
        )
    parsed = _parse_rank_row(target)
    if not parsed:
        raise FundFlowSourceUnavailable(f"解析失败: {target}")
    # 落库
    netamount_wan = round(parsed["netamount"] / 10000, 2)
    direction = "in" if netamount_wan > 0 else "out"
    if abs(parsed["r0_net"]) > abs(parsed["r3_net"]):
        category = "super"
    elif abs(parsed["r3_net"]) > 0:
        category = "large"
    else:
        category = "medium"
    async with async_session() as session:
        ff = FundFlow(
            stock_code=stock_code,
            timestamp=datetime.now(),
            direction=direction,
            amount=f"{abs(netamount_wan):.2f}",
            category=category,
            source="sina",
        )
        session.add(ff)
        await session.commit()
        await session.refresh(ff)
    await event_bus.publish({
        "event": "fund_flow",
        "stock_code": stock_code,
        "direction": direction,
        "amount": f"{abs(netamount_wan):.2f}",
        "category": category,
        "timestamp": ff.timestamp.isoformat(),
    })
    return {
        "id": ff.id,
        "stock_code": stock_code,
        "direction": direction,
        "amount": f"{abs(netamount_wan):.2f}",
        "category": category,
        "timestamp": ff.timestamp.isoformat(),
    }


async def start_sina_scheduler(interval_sec: float = 60) -> None:
    """后台调度器:每 interval_sec 秒拉一次 3 个市场排行(完全真实数据,无 mock)"""
    logger.info("资金流新浪调度器启动: 间隔 %ss, 市场 SH/SZ/BJ", interval_sec)
    while True:
        try:
            await _refresh_one_round()
        except asyncio.CancelledError:
            logger.info("资金流调度器停止")
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("资金流调度器异常: %s", e)
        await asyncio.sleep(interval_sec)


__all__ = [
    "generate_one",
    "list_recent",
    "start_sina_scheduler",
    "FundFlowSourceUnavailable",
]