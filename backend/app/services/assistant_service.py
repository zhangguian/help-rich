"""全局 AI 助手(阶段 T4 · 后端)

定位:右下角悬浮球的对话后端。助手是**全局**的 —— 它不只服务于某一只票,
而是把「当前选中的票 + 持仓 + ★关注 + 今日作战计划 + 今日盘中复盘 + 指数快照」
拼成一份**事实包**喂给 LLM。

**铁律(项目级「LLM 只翻译不计算」)**:事实包是**唯一**的数字来源。
作战计划的倾向 / 四维 / 关键位、盘中复盘的到价动作,都是**规则层算好的结论**,
这里只负责原样搬运;prompt 里明确要求
「所有数字都必须来自事实包;事实包里没有的,就说没有,禁止编造」。

**降级纪律**:事实包的每一段**独立取数、独立兜底**。
某一段挂了只把那一段标成「取不到」,不影响其余段落 ——
宁可少说,不可瞎说。
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

from app.llm.factory import provider_factory
from app.modules.analysis.intraday_review import get_reviews
from app.modules.portfolio.service import get_all_positions
from app.repositories.llm_settings_repo import llm_settings_repo
from app.repositories.watchlist_repo import watchlist_repo
from app.services.battle_plan_service import get_plan
from app.services.quote_service import QuoteService

logger = logging.getLogger(__name__)

# 多轮历史上限(与个股问答的 MAX_HISTORY_TURNS 对齐)
MAX_HISTORY_TURNS = 6

# 指数快照代码
INDEX_CODES = ("000001.SH", "399001.SZ", "399006.SZ")


class AssistantUnavailable(Exception):
    """LLM 未配置 / 调用失败(助手无法回答时抛出)"""


# ============================ 取数(每段独立兜底) ============================


async def _load_positions() -> tuple[list[dict[str, Any]], bool]:
    """持仓(代码 / 名称 / 股数 / 摊薄成本)→ (数据, 是否取到)"""
    out: list[dict[str, Any]] = []
    try:
        positions = await get_all_positions()
    except Exception as e:  # noqa: BLE001
        logger.warning("助手事实包:持仓取数失败: %s", e)
        return out, False
    for p in positions:
        try:
            cost = float(p.avg_cost)
        except Exception:  # noqa: BLE001
            cost = None
        out.append(
            {
                "code": p.stock_code,
                "name": p.stock_name,
                "shares": p.shares,
                "avg_cost": cost,
            }
        )
    return out, True


async def _load_favorites() -> tuple[list[dict[str, Any]], bool]:
    """★特别关注清单 → (数据, 是否取到)"""
    out: list[dict[str, Any]] = []
    try:
        items = await watchlist_repo.list_all()
    except Exception as e:  # noqa: BLE001
        logger.warning("助手事实包:自选取数失败: %s", e)
        return out, False
    for it in items:
        if not getattr(it, "is_favorite", False):
            continue
        out.append({"code": it.stock_code, "name": it.stock_name})
    return out, True


async def _load_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    """批量报价(一次请求覆盖事实包需要的全部代码)"""
    if not codes:
        return {}
    try:
        quotes = await QuoteService().get_quotes(codes)
    except Exception as e:  # noqa: BLE001
        logger.warning("助手事实包:报价取数失败: %s", e)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for q in quotes:
        code = str(getattr(q, "code", "") or "")
        if not code:
            continue
        price = getattr(q, "current_price", None)
        change_pct = getattr(q, "change_pct", None)
        out[code] = {
            "price": float(price) if price is not None else None,
            "change_pct": float(change_pct) if change_pct is not None else None,
        }
    return out


async def _load_plan(today: date) -> tuple[dict[str, Any] | None, bool]:
    """今日作战计划 → (计划, 是否取到)"""
    try:
        return await get_plan(today), True
    except Exception as e:  # noqa: BLE001
        logger.warning("助手事实包:作战计划取数失败: %s", e)
        return None, False


async def _load_reviews(today: date) -> tuple[list[dict[str, Any]], bool]:
    """今日盘中复盘(可能一档都没产出)→ (数据, 是否取到)"""
    try:
        return await get_reviews(today.isoformat()), True
    except Exception as e:  # noqa: BLE001
        logger.warning("助手事实包:盘中复盘取数失败: %s", e)
        return [], False


# ============================ 事实包 ============================


def _trim_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """作战计划 → 事实包片段(只留要展示/要引用的字段)"""
    outlook = plan.get("outlook") or {}
    items = []
    for it in plan.get("items") or []:
        basis = it.get("basis")
        if isinstance(basis, list):
            basis = basis[0] if basis else None
        items.append(
            {
                "code": it.get("stock_code"),
                "name": it.get("stock_name"),
                "kind": it.get("item_kind"),
                "direction": it.get("direction"),
                "label": it.get("label"),
                "trigger_price": it.get("trigger_price"),
                "basis": basis,
                "invalid_if": it.get("invalid_if"),
            }
        )
    return {
        "plan_date": plan.get("plan_date"),
        "target_date": plan.get("target_date"),
        "stance": outlook.get("stance"),
        "stance_label": outlook.get("stance_label"),
        "dims": outlook.get("dims"),
        "key_levels": outlook.get("key_levels"),
        "summary": outlook.get("summary"),
        "scope_count": (plan.get("meta") or {}).get("scope_count"),
        "items": items,
    }


def _trim_review(row: dict[str, Any]) -> dict[str, Any]:
    """盘中复盘 → 事实包片段

    `get_reviews()` 返回的行结构是 `{"trade_date", "slot", "payload": {...}}`,
    而 `payload` 才是复盘对象本体 —— 这里两种形状都认,
    免得以后有人直接传 payload 进来就读空了。
    """
    payload = row.get("payload") or row
    mo = payload.get("market_opinion") or {}
    actions = []
    for a in payload.get("actions") or []:
        actions.append(
            {
                "code": a.get("stock_code"),
                "name": a.get("stock_name"),
                "label": a.get("label"),
                "direction": a.get("direction"),
                "trigger_price": a.get("trigger_price"),
                "current_price": a.get("current_price"),
                "gap_pct": a.get("gap_pct"),
                "action_state": a.get("action_state"),
                "basis": a.get("basis"),
            }
        )
    return {
        "slot": row.get("slot") or payload.get("slot"),
        "stance": mo.get("stance"),
        "stance_label": mo.get("stance_label"),
        "summary": mo.get("summary"),
        "basis": mo.get("basis"),
        "key_levels": mo.get("key_levels"),
        "dims": mo.get("dims"),
        "degraded": payload.get("degraded"),
        "actions": actions,
        "extra_lines": payload.get("extra_lines") or [],
    }


async def build_context(stock_code: str | None = None) -> dict[str, Any]:
    """组装助手事实包。

    每一段独立取数:某段失败只影响该段(标进 `unavailable`),
    其余段落照常 —— 助手因此可以诚实地说「持仓数据取不到」,
    而不是整段崩掉什么都不说。
    """
    today = date.today()
    unavailable: list[str] = []

    positions, pos_ok = await _load_positions()
    favorites, fav_ok = await _load_favorites()
    if not pos_ok:
        unavailable.append("持仓")
    if not fav_ok:
        unavailable.append("★关注清单")

    # 指数快照(取不到就空,不编)
    indexes: list[dict[str, Any]] = []
    try:
        idx_quotes = await QuoteService().get_quotes(list(INDEX_CODES))
        for q in idx_quotes:
            price = getattr(q, "current_price", None)
            change_pct = getattr(q, "change_pct", None)
            indexes.append(
                {
                    "code": str(getattr(q, "code", "") or ""),
                    "name": getattr(q, "name", None),
                    "price": float(price) if price is not None else None,
                    "change_pct": float(change_pct) if change_pct is not None else None,
                }
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("助手事实包:指数取数失败: %s", e)
        unavailable.append("指数快照")

    # 批量报价(持仓 / ★关注 / 当前选中票)
    codes = {p["code"] for p in positions} | {f["code"] for f in favorites}
    if stock_code:
        codes.add(stock_code)
    quotes = await _load_quotes(sorted(codes))

    # 持仓挂上现价与浮盈(用显式四则运算,不在这里猜)
    for p in positions:
        q = quotes.get(p["code"]) or {}
        price = q.get("price")
        cost = p.get("avg_cost")
        p["price"] = price
        p["change_pct"] = q.get("change_pct")
        p["floating_pnl_pct"] = (
            round((price - cost) / cost * 100, 2)
            if price is not None and cost not in (None, 0)
            else None
        )

    for f in favorites:
        q = quotes.get(f["code"]) or {}
        f["price"] = q.get("price")
        f["change_pct"] = q.get("change_pct")

    # 当前选中票
    selected: dict[str, Any] | None = None
    if stock_code:
        q = quotes.get(stock_code) or {}
        pos = next((p for p in positions if p["code"] == stock_code), None)
        selected = {
            "code": stock_code,
            "price": q.get("price"),
            "change_pct": q.get("change_pct"),
            "position": pos,
        }
        if not q:
            unavailable.append(f"选中票 {stock_code} 的报价")

    plan_raw, plan_ok = await _load_plan(today)
    if not plan_ok or plan_raw is None:
        unavailable.append("今日作战计划")
    plan = _trim_plan(plan_raw) if plan_raw else None

    reviews_raw, rev_ok = await _load_reviews(today)
    if not rev_ok:
        unavailable.append("今日盘中复盘")
    reviews = [_trim_review(r) for r in reviews_raw]

    return {
        "as_of": datetime.now().isoformat(timespec="seconds"),
        "trade_date": today.isoformat(),
        "selected": selected,
        "positions": positions,
        "favorites": favorites,
        "indexes": indexes,
        "plan": plan,
        "intraday_reviews": reviews,
        "unavailable": unavailable,
    }


# ============================ Prompt ============================


SYSTEM_PROMPT = """你是「买股工具室」的盯盘助手,一个交易台上的行情副驾。

**绝对规则(违反即错)**:
1. 所有数字必须**原样取自**下面提供的「事实包」。事实包里没有的数字,
   一律回答「这个数据我现在没有」——**禁止推算、禁止估计、禁止编造**。
2. 事实包里的结论(倾向 / 四维度 / 关键位 / 到价动作)已经是系统算好的,
   你只负责把它们说成人话,**不要自己改判**。
3. 事实包标注 `unavailable` 的部分,明确说「取不到」,不要绕过去不提。
4. 回答用简体中文,简洁、直接、可执行。不要客套,不要重复用户的问题。
5. 涉及具体某只票时,带上代码;涉及价格时标明单位(元)。
6. **价格逐字引用**:事实包里写 `11.625` 就写 `11.625`,**不要四舍五入**成 `11.62`,
   也不要补零或截断小数位。触发价 / 止损价 / 现价一律如此 —— 改一个数字就是改判。

**口径提醒**:作战计划里的倾向与四维度是**盘前推断**,盘中复盘里的动作状态是
**按现价与触发价比对**得出的。两者口径不同,别混着说。"""


def build_user_prompt(question: str, ctx: dict[str, Any]) -> str:
    """把事实包 + 问题拼成一条 user 消息"""
    facts = json.dumps(ctx, ensure_ascii=False, indent=2, default=str)
    return (
        "以下是你当前能看到的**事实包**(JSON)。\n"
        "请只依据它回答用户的问题,数字一律**逐字原样引用**(保留原始小数位,不要四舍五入)。\n\n"
        f"【事实包】\n{facts}\n\n"
        f"【用户问题】\n{question}"
    )


def _to_llm_messages(history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """前端 history → LLM 原生 messages(ai→assistant),截到最近 N 轮"""
    if not history:
        return []
    msgs: list[dict[str, str]] = []
    for h in history:
        role = h.get("role")
        text = (h.get("text") or "").strip()
        if not text:
            continue
        if role == "user":
            msgs.append({"role": "user", "content": text})
        elif role == "ai":
            msgs.append({"role": "assistant", "content": text})
    max_msgs = MAX_HISTORY_TURNS * 2
    if len(msgs) > max_msgs:
        msgs = msgs[-max_msgs:]
    return msgs


# ============================ LLM 交互 ============================


async def _get_llm():
    active = await llm_settings_repo.get_active()
    return await provider_factory.get(active)


async def check_assistant_available() -> None:
    """流开始前的前置校验:LLM 没配置就抛(API 层转 503)"""
    if await _get_llm() is None:
        raise AssistantUnavailable("未配置 LLM Key,助手暂时无法回答")


async def stream_assistant_answer(
    question: str,
    stock_code: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str]:
    """流式产出回答增量。

    调用方需 async for 完整消费;LLM 未配置 / 调用失败抛 AssistantUnavailable。
    """
    llm = await _get_llm()
    if llm is None:
        raise AssistantUnavailable("未配置 LLM Key,助手暂时无法回答")

    ctx = await build_context(stock_code)
    messages = _to_llm_messages(history) + [
        {"role": "user", "content": build_user_prompt(question, ctx)}
    ]
    try:
        async for piece in llm.chat_stream_with_messages(
            SYSTEM_PROMPT, messages, temperature=0.4
        ):
            yield piece
    except Exception as e:  # noqa: BLE001
        raise AssistantUnavailable(f"LLM 调用失败: {e}") from e


__all__ = [
    "AssistantUnavailable",
    "MAX_HISTORY_TURNS",
    "SYSTEM_PROMPT",
    "build_context",
    "build_user_prompt",
    "check_assistant_available",
    "stream_assistant_answer",
]
