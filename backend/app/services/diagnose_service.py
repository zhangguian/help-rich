"""诊断编排服务(backend-arch §5.3 + §11.3.5 / project-book §4.3)

score_and_notify(trade_id):
1. scorer 5 维度评分(纯函数)→ safe_write 写 trade_scores → publish trade.scored
2. 取激活 provider(可缺 Key)→ 调 LLM → 写 ai_comment → publish trade.commented
   缺 Key → ai_status=no_key + publish trade.failed
"""
import logging
import time

from app.core.db_lock import safe_write
from app.core.prompts import build_diagnose_user_prompt, build_trade_line, DIAGNOSE_SYSTEM
from app.core.scorer import score_trade
from app.llm.factory import provider_factory
from app.llm.sanitizer import sanitize_for_llm
from app.repositories.llm_settings_repo import llm_settings_repo
from app.repositories.trade_score_repo import trade_score_repo
from app.repositories.transaction_repo import transaction_repo
from app.repositories.watchlist_repo import watchlist_repo
from app.services.event_bus import event_bus
from app.services.position_service import Position, aggregate_positions

logger = logging.getLogger(__name__)

# 诊断用的历史交易条数
RECENT_LIMIT = 5


def _load_context_trades(all_tx: list, target_id: int):
    """按 (trade_date, id) 排序,返回目标交易之前的流水

    Returns:
        (before_trades, found): 目标交易之前的流水、是否找到目标
    """
    ordered = sorted(all_tx, key=lambda t: (t.trade_date, t.id))
    before: list = []
    found = False
    for tx in ordered:
        if tx.id == target_id:
            found = True
            continue
        if not found:
            before.append(tx)
    return before, found


def position_before_stock(
    before_trades: list, stock_code: str
) -> Position | None:
    """目标交易之前该股票的持仓(加权平均)"""
    pos = aggregate_positions(before_trades)
    for p in pos:
        if p.stock_code == stock_code:
            return p
    return None


class DiagnoseService:
    async def score_and_notify(self, trade_id: int) -> None:
        """评分 + AI 评语 + SSE 推送(后台任务,不阻塞录入)"""
        # 1. 取交易
        trade = await transaction_repo.get_by_id(trade_id)
        if trade is None:
            logger.warning("diagnose: trade %s not found, skip", trade_id)
            return

        # 2. 聚合上下文(目标交易之前 / 全部)
        from app.services.position_service import get_all_positions

        # 加载全部流水(复用 get_all_positions 的查询,避免重复实现)
        from app.db import async_session
        from app.models.orm import Transaction
        from sqlalchemy import select

        async with async_session() as session:
            stmt = select(Transaction).order_by(Transaction.trade_date, Transaction.id)
            all_tx = list((await session.execute(stmt)).scalars().all())

        before_trades, found = _load_context_trades(all_tx, trade_id)
        if not found:
            # 防御:交易不在库里(已删除等)
            before_trades = [t for t in all_tx if t.id != trade_id]

        position_before = position_before_stock(before_trades, trade.stock_code)
        # 当前全部持仓(含目标交易,用于集中度 + 0 数据降级)
        all_positions = aggregate_positions(all_tx)

        recent = before_trades[-RECENT_LIMIT:]

        # 3. market_ctx(MVP 中性:大盘涨跌待接指数行情,先给中性分)
        market_ctx = {"index_change_pct": 0.0, "sector_rank": None}

        is_in_watchlist = await watchlist_repo.contains(trade.stock_code)

        trade_dict = {
            "stock_code": trade.stock_code,
            "stock_name": trade.stock_name or "",
            "action": trade.action,
            "shares": trade.shares,
            "price": trade.price,
            "trade_date": trade.trade_date,
        }

        # 4. 评分(纯函数)
        score_result = score_trade(
            trade_dict,
            (
                {
                    "shares": position_before.shares,
                    "avg_cost": str(position_before.avg_cost),
                    "total_cost": str(position_before.total_cost),
                }
                if position_before
                else None
            ),
            recent,
            market_ctx,
            is_in_watchlist,
            [
                {
                    "stock_code": p.stock_code,
                    "shares": p.shares,
                    "avg_cost": str(p.avg_cost),
                }
                for p in all_positions
            ],
        )

        import json

        breakdown_json = json.dumps(score_result["score_breakdown"], ensure_ascii=False)

        # 5. safe_write 写评分
        async def _do_upsert():
            return await trade_score_repo.upsert(
                trade_id=trade_id,
                score=score_result["score"],
                score_breakdown=breakdown_json,
            )

        await safe_write(_do_upsert)

        # 6. SSE 推送评分(先到,不等 LLM)
        await event_bus.publish({
            "event": "trade.scored",
            "trade_id": trade_id,
            "score": score_result["score"],
            "breakdown": score_result["score_breakdown"],
        })

        # 7. AI 评语(可失败降级)
        active = await llm_settings_repo.get_active()
        llm = await provider_factory.get(active)

        if llm is None:
            # 缺 Key:优雅降级
            await safe_write(
                lambda: trade_score_repo.update_ai_status(trade_id, "no_key")
            )
            await event_bus.publish({
                "event": "trade.failed",
                "trade_id": trade_id,
                "reason": f"{active} 未配置 Key,请到设置页填写",
            })
            return

        # 集中度%(脱敏字段)
        concentration_pct = None
        if position_before and all_positions:
            pos_val = position_before.shares * position_before.avg_cost
            total_val = sum(p.shares * p.avg_cost for p in all_positions)
            if total_val > 0:
                concentration_pct = (pos_val / total_val) * 100

        sanitized = sanitize_for_llm(trade_dict, concentration_pct)
        trade_line = build_trade_line(sanitized)
        recent_summary = "、".join(
            f"{t.stock_code} {t.action} {t.shares}股@{t.trade_date}"
            for t in recent
        ) or "无"
        user_prompt = build_diagnose_user_prompt(
            trade_line=trade_line,
            concentration_pct=sanitized["concentration_pct"],
            recent_summary=recent_summary,
            score=score_result["score"],
            breakdown=score_result["score_breakdown"],
            is_in_watchlist=is_in_watchlist,
        )

        # 8. 调 LLM(记录延迟)
        t0 = time.time()
        try:
            ai_comment = await llm.chat(DIAGNOSE_SYSTEM, user_prompt)
            latency_ms = int((time.time() - t0) * 1000)
        except Exception as e:  # noqa: BLE001
            logger.warning("diagnose %s: LLM failed: %s", trade_id, e)
            await safe_write(
                lambda: trade_score_repo.update_ai_status(trade_id, "failed")
            )
            await event_bus.publish({
                "event": "trade.failed",
                "trade_id": trade_id,
                "reason": str(e),
            })
            return

        # 9. safe_write 写评语
        async def _do_comment():
            return await trade_score_repo.update_ai_comment(
                trade_id,
                ai_comment,
                ai_status="success",
                ai_model=llm.model_name,
                ai_latency_ms=latency_ms,
            )

        await safe_write(_do_comment)

        # 10. SSE 推送评语
        await event_bus.publish({
            "event": "trade.commented",
            "trade_id": trade_id,
            "comment": ai_comment,
            "provider": llm.name,
            "model": llm.model_name,
            "latency_ms": latency_ms,
        })


diagnose_service = DiagnoseService()
