"""每日作战计划编排(取数 → 三模块 → 落库 → 回填兑现)

设计文档 §4.6。本模块是**唯一**做 IO 的地方;三个纯函数模块
(outlook_service / plan_item_builder / fulfillment_checker)只管算。

**降级原则**:单票失败不影响其余票;缺数据如实标注,绝不编造。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.repositories.battle_plan_repo import battle_plan_repo
from app.services.fulfillment_checker import check_fulfillment, summarize_fulfillment
from app.services.kline_service import fetch_klines
from app.services.market_context_service import get_market_context
from app.services.market_overview_service import fetch_market_sentiment
from app.services.outlook_service import build_outlook
from app.services.plan_item_builder import build_items, build_todos
from app.services.position_status import (
    kline_fallback_price,
    resolve_position_status,
    sanitize_current_price,
)
from app.services.quote_service import QuoteService
from app.services.sector_fund_flow_service import get_sector_fund_flow
from app.services.ta_service import compute_indicators

logger = logging.getLogger(__name__)

MAX_SCOPE = 20              # 目标股票池上限
KLINE_COUNT = 190           # 决策引擎需要足够 K 线
INDEX_CODE = "000001.SH"    # 上证指数
INDEX_KLINE_COUNT = 30      # 算 MA20 + 5 日均量足够


# ============================ 取数 ============================

async def _load_positions() -> list[dict[str, Any]]:
    """持仓(已是聚合结果)"""
    from app.modules.portfolio.service import get_all_positions

    positions = await get_all_positions()
    out: list[dict[str, Any]] = []
    for p in positions or []:
        shares = int(getattr(p, "shares", 0) or 0)
        if shares <= 0:
            continue
        out.append({
            "stock_code": getattr(p, "stock_code", ""),
            "stock_name": getattr(p, "stock_name", None),
            "shares": shares,
            "avg_cost": float(getattr(p, "avg_cost", 0) or 0),
        })
    return out


async def _load_favorites() -> list[dict[str, Any]]:
    """★关注票"""
    from app.repositories import watchlist_repo

    rows = await watchlist_repo.list_all()
    return [
        {"stock_code": getattr(r, "stock_code", ""), "stock_name": getattr(r, "stock_name", None)}
        for r in rows or []
        if getattr(r, "is_favorite", False)
    ]


async def _load_quotes(codes: list[str]):
    """实时行情(失败返回空列表,不阻断)"""
    try:
        return await QuoteService().get_quotes(codes)
    except Exception as e:  # noqa: BLE001
        logger.warning("作战计划拉取行情失败: %s", e)
        return []


async def _load_transactions(plan_date: str) -> list[dict[str, Any]]:
    """目标日交易流水"""
    from app.modules.portfolio.repository import transaction_repo

    try:
        rows, _total = await transaction_repo.list_all(limit=500)
    except Exception as e:  # noqa: BLE001
        logger.warning("作战计划读取流水失败: %s", e)
        return []
    out: list[dict[str, Any]] = []
    for r in rows or []:
        trade_date = getattr(r, "trade_date", None)
        if trade_date is None:
            continue
        iso = trade_date.isoformat() if hasattr(trade_date, "isoformat") else str(trade_date)[:10]
        if iso != plan_date:
            continue
        # Transaction.price 是 String 列,可能是非数字字符串 —— 必须 try/except,
        # 否则一个脏价格会让整份日报生成失败(而不是只丢这一条流水的价格)
        price: float | None = None
        raw_price = getattr(r, "price", None)
        if raw_price is not None:
            try:
                price = float(raw_price)
            except (TypeError, ValueError):
                price = None
        out.append({
            "stock_code": getattr(r, "stock_code", ""),
            "action": getattr(r, "action", ""),
            "shares": int(getattr(r, "shares", 0) or 0),
            "price": price,
            "trade_date": iso,
        })
    return out


# ============================ 股票池 ============================

async def resolve_target_stocks() -> list[dict[str, Any]]:
    """持仓 ∪ ★关注,按 code 去重。持仓优先。"""
    positions = await _load_positions()
    favorites = await _load_favorites()

    merged: dict[str, dict[str, Any]] = {}
    for p in positions:
        code = p["stock_code"]
        if not code:
            continue
        merged[code] = {
            "stock_code": code, "stock_name": p.get("stock_name"),
            "in_position": True, "is_favorite": False,
            "shares": p.get("shares", 0), "avg_cost": p.get("avg_cost", 0.0),
        }
    for f in favorites:
        code = f["stock_code"]
        if not code:
            continue
        if code in merged:
            merged[code]["is_favorite"] = True
        else:
            merged[code] = {
                "stock_code": code, "stock_name": f.get("stock_name"),
                "in_position": False, "is_favorite": True,
                "shares": 0, "avg_cost": 0.0,
            }
    scope = list(merged.values())
    scope.sort(key=lambda s: (not s["in_position"], s["stock_code"]))
    # ⚠️ 这里**不做上限截断** —— 截断与「是否真的截断」这个标志必须由同一处产出。
    # 若这里先切一刀,build_plan 再切一次就永远切不动(len 恰好 == MAX_SCOPE),
    # meta["truncated"] 会恒为 False —— 等于向用户谎称「一只票都没砍掉」。
    # 上限截断只在 build_plan 里做一次(见 `_truncate_scope`)。
    return scope


def _truncate_scope(scope: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """超过 MAX_SCOPE 时截断,并**精确**返回是否真的发生了截断。

    为什么不写成 `len(scope) >= MAX_SCOPE`:恰好等于上限时并没有真的截断,
    那种写法会误报 truncated=True —— 等于向用户谎称"砍掉了一些票"。
    """
    if len(scope) > MAX_SCOPE:
        return scope[:MAX_SCOPE], True
    return scope, False


# ============================ 单票决策 ============================

async def _build_one_decision(
    stock: dict[str, Any], quotes_by_code: dict[str, Any]
) -> tuple[dict | None, list[dict] | None, list[str]]:
    """返回 (decision, todos, errors);失败返回 (None, None, [原因])"""
    code = stock["stock_code"]
    errors: list[str] = []
    try:
        klines = await fetch_klines(code, period="daily", count=KLINE_COUNT)
    except Exception as e:  # noqa: BLE001
        return None, None, [f"{code} K线不可用: {e}"]
    if not klines:
        return None, None, [f"{code} K线为空"]

    try:
        indicators = compute_indicators(klines)
    except Exception as e:  # noqa: BLE001
        return None, None, [f"{code} 指标计算失败: {e}"]

    quote = quotes_by_code.get(code)
    current_price, _date = sanitize_current_price(quote, klines)
    fallback = kline_fallback_price(klines)
    price_for_status = current_price if current_price is not None else fallback
    shares = int(stock.get("shares") or 0)
    avg_cost = float(stock.get("avg_cost") or 0.0)
    position_status, _pct = resolve_position_status(
        PositionView(shares=shares, avg_cost=avg_cost) if shares > 0 else None,
        price_for_status, fallback
    )

    prev_close = None
    if len(klines) >= 2:
        try:
            prev_close = float(klines[-2]["close"])
        except (TypeError, ValueError, KeyError):
            prev_close = None

    try:
        env = await get_market_context(code, stock_change_pct=None)
    except Exception as e:  # noqa: BLE001
        logger.warning("作战计划取市场环境失败 %s: %s", code, e)
        from app.services.decision_service import MarketContext
        env = MarketContext(degraded=["市场环境不可用"])

    from app.services.decision_service import DecisionContext, build_decision

    ctx = DecisionContext(
        stock_code=code,
        stock_name=stock.get("stock_name"),
        indicators=indicators,
        klines=klines,
        current_price=float(current_price) if current_price is not None else None,
        prev_close=prev_close,
        cost_basis=avg_cost if shares > 0 else None,
        shares=shares,
        position_status=position_status,
        env=env,
    )
    decision = build_decision(ctx)
    todos = build_todos(decision)
    return decision, todos, errors


@dataclass(frozen=True)
class PositionView:
    """持仓视图 —— 同时满足两个下游契约(**属性形状,不是 dict**):

    - `services/position_status.resolve_position_status`:须含 `.shares` / `.avg_cost` 属性
    - `services/plan_item_builder.build_items`:须含 `.shares` 属性

    两边统一成属性形状(2026-10-21 跨任务裁决),避免接线层出现 dict/对象两套契约。
    """

    shares: int
    avg_cost: float


# ============================ 目标交易日 ============================

def _next_trading_day(index_klines: list[dict], plan_date: date) -> tuple[str, bool]:
    """下一个交易日;返回 (日期字符串, 是否为推算值)"""
    last_date = None
    for k in reversed(index_klines or []):
        d = (k or {}).get("date")
        if d:
            last_date = str(d)[:10]
            break
    base = date.fromisoformat(last_date) if last_date else plan_date
    nxt = base + timedelta(days=1)
    while nxt.weekday() >= 5:  # 跳过周末
        nxt += timedelta(days=1)
    return nxt.isoformat(), True   # 未能从真实日历确认,标记为推算


# ============================ 主入口 ============================

async def _persist(plan: dict[str, Any]) -> int:
    """落库(可被测试替换)

    **幂等覆盖的例外**(spec §4.6.3):D 日报的 items 若已有非 pending 的 fulfillment,
    说明那批兑现状态已被判定过(生成 D+1 日报时回填的)。重新生成 D 日报时
    **保留原 items 不动**,只更新 outlook / review / meta —— 否则会把已判定的
    兑现状态冲回 pending,把复盘历史抹掉。
    """
    plan_date = plan["plan_date"]
    meta = plan.setdefault("meta", {})

    judged = False
    row = await battle_plan_repo.get_plan(plan_date)
    if row:
        existing = await battle_plan_repo.get_items(row["id"])
        judged = any((i.get("fulfillment") or "pending") != "pending" for i in existing)
    meta["items_preserved"] = judged

    plan_id = await battle_plan_repo.upsert_plan(
        plan_date=plan_date,
        outlook_json=json.dumps(plan.get("outlook"), ensure_ascii=False),
        review_json=json.dumps(plan.get("review"), ensure_ascii=False),
        meta_json=json.dumps(meta, ensure_ascii=False),
    )
    if not judged:
        await battle_plan_repo.replace_items(plan_id, plan_date, plan.get("items") or [])
    return plan_id


async def build_plan(plan_date: date) -> dict[str, Any]:
    """生成一份作战日报(幂等;同日重复生成覆盖)"""
    ds = plan_date.isoformat()
    degraded: list[str] = []

    scope, truncated = _truncate_scope(await resolve_target_stocks())
    if not scope:
        raise ValueError("目标股票池为空:既无持仓也无★关注票,无法生成作战计划")

    quotes = await _load_quotes([s["stock_code"] for s in scope])
    quotes_by_code = {getattr(q, "code", None): q for q in (quotes or [])}

    # ---- 市场数据(明日预期原料) ----
    index_klines: list[dict] = []
    try:
        index_klines = await fetch_klines(INDEX_CODE, period="daily", count=INDEX_KLINE_COUNT)
    except Exception as e:  # noqa: BLE001
        degraded.append(f"上证指数K线不可用: {e}")

    sentiment = None
    try:
        sentiment = await fetch_market_sentiment()
    except Exception as e:  # noqa: BLE001
        degraded.append(f"涨跌家数不可用: {e}")

    sector_flows = None
    try:
        sector_flows = await get_sector_fund_flow(fenlei=1, num=40, sort="netamount")
    except Exception as e:  # noqa: BLE001
        degraded.append(f"板块资金流不可用: {e}")

    outlook = build_outlook(index_klines, sentiment, sector_flows)

    # ---- 逐票预案 ----
    items: list[dict[str, Any]] = []
    todos: list[dict[str, Any]] = []
    for stock in scope:
        decision, stock_todos, errors = await _build_one_decision(stock, quotes_by_code)
        degraded.extend(errors)
        if decision is None:
            continue
        todos.extend(stock_todos or [])
        pos = PositionView(
            shares=int(stock.get("shares") or 0),
            avg_cost=float(stock.get("avg_cost") or 0.0),
        )
        items.extend(build_items(decision, pos if stock.get("in_position") else None))

    # ---- 昨日兑现(闭环) ----
    prev_date = (plan_date - timedelta(days=1)).isoformat()
    review = await _build_review(prev_date, plan_date, degraded, todos)

    target_date, estimated = _next_trading_day(index_klines, plan_date)
    meta = {
        "scope_count": len(scope),
        "scope": scope,
        "truncated": truncated,
        "degraded": bool(degraded),
        "degraded_reason": degraded,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target_date": target_date,
        "target_date_estimated": estimated,
    }

    plan = {
        "plan_date": ds,
        "target_date": target_date,
        "outlook": outlook,
        "review": review,
        "items": items,
        "todos": todos,
        "meta": meta,
    }
    await _persist(plan)
    return plan


async def _build_review(
    prev_date: str,
    plan_date: str,
    degraded: list[str],
    pending_todos: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """今日复盘 = 昨日预案兑现比对 + 今日待办

    `pending_todos` = 本次各票决策里 status=="now" 的动作(条件已满足但用户还没做)。
    它们**必须进复盘段**:写进明日预案是「已经过期的建议」,只有推到今日待办
    才能逼用户面对(见 spec §4.4.2 三路分流)。
    """
    todos = list(pending_todos or [])
    prev = await battle_plan_repo.get_plan(prev_date)
    if not prev:
        return {
            "market": None,
            "fulfillment": None,
            "pending_todos": todos,
            "note": "没有找到昨日作战计划,今日暂无兑现比对",
        }
    prev_items = await battle_plan_repo.get_items(prev["id"])

    # 目标日 = 昨日预案所面向的那一天 = 昨日日报的 meta.target_date(缺失时退回 plan_date)
    prev_meta = prev.get("meta") or {}
    target_day = str(prev_meta.get("target_date") or plan_date)
    codes = {i["stock_code"] for i in prev_items}
    target_klines: dict[str, list[dict]] = {}
    for code in codes:
        try:
            ks = await fetch_klines(code, period="daily", count=5)
            # ⚠️ **只取目标日那一根**:`check_fulfillment` 会把传入 K 线的 high/low 合成为当日极值,
            # 一次给 5 根等于把「5 天极值」当成「单日极值」→ 「当日触及」被夸大,
            # 昨天没到位的价位会被说成昨天触及了。宁可少数据,不可假触及。
            day_ks = [
                k for k in (ks or [])
                if str((k or {}).get("date") or "")[:10] == target_day
            ]
            target_klines[code] = day_ks
        except Exception as e:  # noqa: BLE001
            degraded.append(f"{code} 兑现比对取K线失败: {e}")
            target_klines[code] = []

    transactions = await _load_transactions(target_day)
    checked = check_fulfillment(prev_items, target_klines, transactions)
    summary = summarize_fulfillment(checked)

    # 回填昨日日报的兑现状态
    for it in checked:
        try:
            await battle_plan_repo.update_item_fulfillment(
                it["id"], it["fulfillment"], it.get("fulfillment_note") or ""
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("回填兑现状态失败 item=%s: %s", it.get("id"), e)

    return {
        "market": None,
        "fulfillment": {**summary, "items": [
            {
                "stock_code": i["stock_code"], "stock_name": i.get("stock_name"),
                "label": i.get("label"), "item_kind": i.get("item_kind"),
                "fulfillment": i["fulfillment"], "note": i.get("fulfillment_note"),
            }
            for i in checked
        ]},
        "pending_todos": todos,
        "note": None,
    }


async def get_plan(plan_date: date) -> dict[str, Any] | None:
    """读取指定日期的日报(不存在返回 None)"""
    row = await battle_plan_repo.get_plan(plan_date.isoformat())
    if not row:
        return None
    items = await battle_plan_repo.get_items(row["id"])
    return {
        "plan_date": row["plan_date"],
        "target_date": (row.get("meta") or {}).get("target_date"),
        "outlook": row.get("outlook"),
        "review": row.get("review"),
        "items": items,
        "meta": row.get("meta"),
    }


__all__ = ["build_plan", "get_plan", "resolve_target_stocks", "MAX_SCOPE"]
