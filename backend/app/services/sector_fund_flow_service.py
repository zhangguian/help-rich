"""板块资金流服务(guide §7 新浪)"""
import asyncio
import logging
from datetime import datetime
from typing import Any

from app.data.sina import fetch_sector_fund_flow_rank
from app.services.event_bus import event_bus

logger = logging.getLogger(__name__)

FENLEI_MAP = {
    0: "全部",
    1: "行业",
    2: "概念",
    3: "地域",
}

# 板块资金流排行不入库(高频更新,只读排行;MVP 仅查询)

# 异动阈值:净额变化绝对值 ≥ 此值视为异动(亿元)
SECTOR_ALERT_THRESHOLD_YI = 1.0

# 调度器上一次拉取的快照 {fenlei: [(name, netamount_yi, top_stock_code), ...]}
_prev_snapshots: dict[int, list[tuple[str, float, str | None]]] = {}


async def get_sector_fund_flow(
    fenlei: int = 0, num: int = 20, sort: str = "netamount"
) -> list[dict[str, Any]]:
    """拉板块资金流排行(guide §7 新浪)"""
    raw = await fetch_sector_fund_flow_rank(fenlei=fenlei, num=num, sort=sort)
    out: list[dict[str, Any]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        out.append({
            "category": r.get("category", ""),
            "name": r.get("name", ""),
            "avg_price": float(r.get("avg_price", 0) or 0),
            "change_pct": float(r.get("avg_changeratio", 0) or 0),
            "turnover_yi": float(r.get("turnover", 0) or 0),
            "inamount_yi": float(r.get("inamount", 0) or 0),
            "outamount_yi": float(r.get("outamount", 0) or 0),
            "netamount_yi": float(r.get("netamount", 0) or 0),
            "ratioamount": float(r.get("ratioamount", 0) or 0),
            "top_stock": {
                "code": r.get("ts_symbol", ""),
                "name": r.get("ts_name", ""),
                "price": float(r.get("ts_trade", 0) or 0),
                "change_pct": float(r.get("ts_changeratio", 0) or 0),
                "ratioamount": float(r.get("ts_ratioamount", 0) or 0),
            } if r.get("ts_symbol") else None,
        })
    return out


def _to_snapshot(items: list[dict[str, Any]]) -> list[tuple[str, float, str | None]]:
    """把排行列表压缩成可对比的快照(name, netamount_yi, top_stock_code)"""
    return [
        (it["name"], it["netamount_yi"], (it.get("top_stock") or {}).get("code") or None)
        for it in items
    ]


def _detect_alerts(
    fenlei: int,
    prev: list[tuple[str, float, str | None]],
    curr: list[dict[str, Any]],
    threshold_yi: float = SECTOR_ALERT_THRESHOLD_YI,
) -> list[dict[str, Any]]:
    """检测板块异动(v0.4.1 纯函数,可单测)

    规则:
    1. 净额绝对变化 ≥ threshold_yi(亿元)
    2. 领涨股进出榜(可能含义:板块资金切换至其他个股)

    Returns: alert list,每条 {fenlei, name, prev_yi, curr_yi, delta_yi, reason, top_stock_code?}
    """
    prev_map = {n: (net, code) for n, net, code in prev}
    curr_snapshot = _to_snapshot(curr)
    curr_map = {n: (net, code) for n, net, code in curr_snapshot}

    alerts: list[dict[str, Any]] = []
    # 1) 净额异动 + 2) 进出榜
    seen: set[str] = set()
    for item in curr:
        name = item["name"]
        net_yi = item["netamount_yi"]
        top_code = (item.get("top_stock") or {}).get("code") or None
        prev_entry = prev_map.get(name)
        if prev_entry is None:
            # 新进榜(尚未在 prev 中):也算异动(若净额绝对值够大)
            if abs(net_yi) >= threshold_yi:
                alerts.append({
                    "fenlei": fenlei,
                    "name": name,
                    "prev_yi": 0.0,
                    "curr_yi": net_yi,
                    "delta_yi": net_yi,
                    "reason": "new",
                    "top_stock_code": top_code,
                })
                seen.add(name)
        else:
            prev_net, prev_top = prev_entry
            delta = net_yi - prev_net
            if abs(delta) >= threshold_yi:
                alerts.append({
                    "fenlei": fenlei,
                    "name": name,
                    "prev_yi": prev_net,
                    "curr_yi": net_yi,
                    "delta_yi": delta,
                    "reason": "delta",
                    "top_stock_code": top_code,
                })
                seen.add(name)
            # 领涨股切换(原本没 = 进 / 原本有但不同 = 换)
            if prev_top and top_code and prev_top != top_code:
                alerts.append({
                    "fenlei": fenlei,
                    "name": name,
                    "prev_yi": prev_net,
                    "curr_yi": net_yi,
                    "delta_yi": delta,
                    "reason": f"top_stock_changed:{prev_top}->{top_code}",
                    "top_stock_code": top_code,
                })
                seen.add(name)
    return alerts


async def _refresh_one_fenlei(fenlei: int, top_n: int = 20) -> list[dict[str, Any]]:
    """拉一个 fenlei 排行 + 检测异动 + publish alerts + 更新快照"""
    try:
        items = await get_sector_fund_flow(fenlei=fenlei, num=top_n, sort="netamount")
    except Exception as e:  # noqa: BLE001
        logger.warning("板块资金拉取失败 (fenlei=%s): %s", fenlei, e)
        return []

    prev = _prev_snapshots.get(fenlei, [])
    alerts = _detect_alerts(fenlei, prev, items)
    _prev_snapshots[fenlei] = _to_snapshot(items)

    if alerts:
        logger.info("板块资金异动 (fenlei=%s): %d 条", fenlei, len(alerts))
        await event_bus.publish({
            "event": "sector_fund_flow_alert",
            "fenlei": fenlei,
            "fenlei_label": FENLEI_MAP[fenlei],
            "alerts": alerts,
            "ts": datetime.now().isoformat(),
        })
    return alerts


async def start_sector_scheduler(interval_sec: float = 60) -> None:
    """后台调度器:每 interval_sec 秒拉一次板块资金排行 + 异动检测 + publish

    只监控 fenlei=0(全部,覆盖全部/行业/概念/地域的高频板块);降低请求量。
    """
    logger.info("板块资金调度器启动: 间隔 %ss, fenlei=0(全部)", interval_sec)
    while True:
        try:
            await _refresh_one_fenlei(fenlei=0)
        except asyncio.CancelledError:
            logger.info("板块资金调度器停止")
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("板块资金调度器异常: %s", e)
        await asyncio.sleep(interval_sec)


def reset_snapshots() -> None:
    """测试辅助:清空快照状态"""
    _prev_snapshots.clear()


__all__ = [
    "get_sector_fund_flow",
    "FENLEI_MAP",
    "_detect_alerts",
    "start_sector_scheduler",
    "reset_snapshots",
]