"""盘中复盘编排层(阶段 T2 · 唯一做 IO 的地方)

流程:今日作战计划 → 股票池 → **一次**批量实时报价 → 纯函数判定 → 落库(幂等) → 返回。

**边界**:
- 今日作战计划缺失 → **响亮失败**(抛 `IntradayReviewError`),不产出半成品建议;
- 某只票取不到报价 → 该票动作判「数据不足」,其余票照常产出;
- **零 LLM**:复盘里的每个数字都来自作战计划 / 实时报价 / 显式四则运算;
- **生成与推送分离**:本模块只负责生成;推送走 `dispatch_intraday_review()`
  (真发消息,不可撤回),沿用 BriefPanel 既有设计原则。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.core.logging import logger
from app.modules.analysis.workflow import WorkflowResult, workflow_agent_service
from app.repositories.intraday_review_repo import intraday_review_repo
from app.services.battle_plan_service import get_plan, resolve_target_stocks
from app.services.intraday_advice import (
    STATE_TRIGGERED,
    build_intraday_advice,
)
from app.services.quote_service import QuoteService

# 复盘档位:与调度窗口一一对应
VALID_SLOTS = ("11:30", "14:00")


class IntradayReviewError(ValueError):
    """盘中复盘的业务失败(如:今日作战计划还没生成)。

    继承 `ValueError` —— API 层对 ValueError 统一转 422(可读的失败,不是 500)。
    """


# ============================ 取数 ============================

async def _load_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    """实时行情(一次批量;整体失败 → 空字典,由决策层判「数据不足」)"""
    if not codes:
        return {}
    try:
        quotes = await QuoteService().get_quotes(codes)
    except Exception as e:  # noqa: BLE001 — 行情失败不阻断复盘,由降级标记体现
        logger.warning(f"[intraday_review] 拉取实时行情失败: {e}")
        return {}
    out: dict[str, dict[str, Any]] = {}
    for q in quotes or []:
        code = getattr(q, "code", None)
        if not code:
            continue
        price = getattr(q, "current_price", None)
        change_pct = getattr(q, "change_pct", None)
        out[str(code)] = {
            "price": float(price) if price is not None else None,
            "change_pct": float(change_pct) if change_pct is not None else None,
        }
    return out


# ============================ 主入口 ============================

async def run_intraday_review(
    slot: str, trading_day: dict[str, Any] | None = None
) -> dict[str, Any]:
    """生成一次盘中复盘(幂等:同日同档重跑覆盖)。

    Args:
        slot: `"11:30"` | `"14:00"`。
        trading_day: 交易日标注(由调用方从交易日历取),缺省则不带该标注。
    """
    if slot not in VALID_SLOTS:
        raise IntradayReviewError(
            f"不支持的复盘档位: {slot}(可用: {', '.join(VALID_SLOTS)})"
        )

    today = date.today()
    plan = await get_plan(today)
    if not plan:
        raise IntradayReviewError(
            f"今日作战计划还没生成({today.isoformat()}),请先生成作战计划再跑盘中复盘"
        )

    outlook = plan.get("outlook") or {}
    items = plan.get("items") or []

    scope = await resolve_target_stocks()
    codes = [str(s.get("stock_code")) for s in scope if s.get("stock_code")]
    quotes = await _load_quotes(codes)

    advice = build_intraday_advice(
        outlook, items, quotes, datetime.now().isoformat(timespec="seconds")
    )

    # 异动扫描(原 run_intraday 的能力)作为**补充段**并入,不丢既有功能
    extra_lines, extra_codes = await workflow_agent_service.scan_intraday_moves()

    payload: dict[str, Any] = {
        "trade_date": today.isoformat(),
        "slot": slot,
        "market_opinion": advice["market_opinion"],
        "actions": advice["actions"],
        "extra_lines": extra_lines,
        "extra_stock_codes": extra_codes,
        "degraded": advice["degraded"],
        "degraded_reason": advice["degraded_reason"],
        "as_of": advice.get("as_of"),
        "scope_count": len(codes),
        "quote_count": len(quotes),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if trading_day:
        payload.update({
            "is_trading_day": bool(trading_day.get("is_trading_day")),
            "trade_date_source": trading_day.get("trade_date_source"),
            "trading_day_estimated": bool(trading_day.get("trading_day_estimated")),
            "trading_day_trade_date": trading_day.get("trade_date"),
        })

    await intraday_review_repo.upsert(today.isoformat(), slot, payload)
    logger.info(
        f"[intraday_review] {slot} 复盘已生成: 动作 {len(advice['actions'])} 条, "
        f"degraded={advice['degraded']}"
    )
    return payload


async def get_reviews(trade_date: str) -> list[dict[str, Any]]:
    """取某日的全部档位(升序)"""
    return await intraday_review_repo.list_by_date(trade_date)


# ============================ 推送 ============================

def _fmt_levels(values: Any) -> str:
    out: list[str] = []
    for v in values or []:
        try:
            out.append(f"{float(v):.2f}")
        except (TypeError, ValueError):
            out.append(str(v))
    return "/".join(out) if out else "无"


def build_dispatch_result(payload: dict[str, Any]) -> WorkflowResult:
    """把复盘结果组装成推送消息。

    消息体必须含:倾向 + 关键位 + 「已到价待执行」的动作清单(每条带股价与依据)
    + **诚实标注**(盘前推断口径)。
    """
    market_opinion = payload.get("market_opinion") or {}
    actions = payload.get("actions") or []
    slot = payload.get("slot") or ""

    stance_label = market_opinion.get("stance_label") or market_opinion.get("stance") or "未知"
    lines: list[str] = [
        f"市场意见:{stance_label}({market_opinion.get('basis') or '盘前推断口径'})",
    ]

    key_levels = market_opinion.get("key_levels") or {}
    support = _fmt_levels(key_levels.get("support"))
    resistance = _fmt_levels(key_levels.get("resistance"))
    lines.append(f"关键位:支撑 {support} / 压力 {resistance}")

    triggered = [a for a in actions if a.get("action_state") == STATE_TRIGGERED]
    if triggered:
        lines.append(f"已到价待执行({len(triggered)} 条):")
        for a in triggered:
            basis = a.get("basis") or []
            basis_text = basis[0] if basis else "无依据"
            price = a.get("current_price")
            trigger = a.get("trigger_price")
            gap = a.get("gap_pct")
            lines.append(
                f"· {a.get('stock_code')} {a.get('stock_name') or ''} "
                f"现价 {price} / 触发价 {trigger}"
                + (f"({gap:+.2f}%)" if isinstance(gap, (int, float)) else "")
                + f" 依据:{basis_text}"
            )
    else:
        lines.append("已到价待执行:暂无")

    extra_lines = payload.get("extra_lines") or []
    if extra_lines:
        lines.append("异动扫描:")
        lines.extend(str(x) for x in extra_lines[:10])

    if payload.get("trading_day_estimated"):
        lines.append("交易日判定:推算口径(交易日历数据源不可用或今日未被真实日K覆盖)")

    summary = market_opinion.get("summary") or "盘中复盘已生成"
    return WorkflowResult(
        kind="intraday_review",
        title=f"买股工具室 · 盘中复盘({slot})",
        summary=summary,
        lines=lines,
        stock_codes=list(dict.fromkeys(
            str(a.get("stock_code")) for a in triggered if a.get("stock_code")
        )),
        degraded=bool(payload.get("degraded")),
    )


async def dispatch_intraday_review(payload: dict[str, Any]) -> list:
    """把复盘推送到已启用渠道(真发消息,不可撤回)。失败只 warning。"""
    result = build_dispatch_result(payload)
    return await workflow_agent_service.dispatch(result)


__all__ = [
    "IntradayReviewError",
    "VALID_SLOTS",
    "build_dispatch_result",
    "dispatch_intraday_review",
    "get_reviews",
    "run_intraday_review",
]
