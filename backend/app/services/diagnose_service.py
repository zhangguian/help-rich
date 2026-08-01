"""诊断编排服务(backend-arch §5.3 + §11.3.5 / project-book §4.3)

score_and_notify(trade_id):
1. scorer 5 维度评分(纯函数)→ safe_write 写 trade_scores → publish trade.scored
2. 取激活 provider(可缺 Key)→ 调 LLM → 写 ai_comment → publish trade.commented
   缺 Key → ai_status=no_key + publish trade.failed
"""
import logging
import time
from decimal import Decimal

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
from app.services.position_service import Position, aggregate_positions, get_all_positions, get_position

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
    """目标交易之前该股票的持仓(流水聚合,供诊断上下文使用)"""
    pos = aggregate_positions(before_trades)
    for p in pos:
        if p.stock_code == stock_code:
            return p
    return None


def _merge_delta_and_flow(
    delta: Position | None, flow_before: Position | None
) -> Position | None:
    """持仓 = 导入基准(delta) + 流水聚合(v0.4.0 主数据语义)

    delta:持仓表当前 − 全部流水聚合(导入/手动调整部分)
    flow_before:目标交易之前的流水聚合
    """
    d_shares = delta.shares if delta else 0
    d_cost = delta.total_cost if delta else Decimal("0")
    d_pnl = delta.realized_pnl if delta else Decimal("0")
    f_shares = flow_before.shares if flow_before else 0
    f_cost = flow_before.total_cost if flow_before else Decimal("0")
    f_pnl = flow_before.realized_pnl if flow_before else Decimal("0")

    total_shares = d_shares + f_shares
    if total_shares <= 0:
        return None
    return Position(
        stock_code=(delta or flow_before).stock_code,
        stock_name=(delta or flow_before).stock_name,
        shares=total_shares,
        total_cost=d_cost + f_cost,
        realized_pnl=d_pnl + f_pnl,
    )


class DiagnoseService:
    async def score_and_notify(self, trade_id: int) -> None:
        """评分 + AI 评语 + SSE 推送(后台任务,不阻塞录入)"""
        # 1. 取交易
        trade = await transaction_repo.get_by_id(trade_id)
        if trade is None:
            logger.warning("diagnose: trade %s not found, skip", trade_id)
            return

        # 2. 聚合上下文(目标交易之前 / 全部)
        # 加载全部流水(供交易前状态判定;持仓视图从真实持仓表取)
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

        # v0.4.0:持仓上下文从真实持仓表出发
        #   position_before = 导入基准(delta) + 交易前流水聚合
        #   all_positions = 持仓表当前(集中度维度,真实持仓)
        from decimal import Decimal as _D

        flow_before = position_before_stock(before_trades, trade.stock_code)

        cur = await get_position(trade.stock_code)
        # 全部流水聚合(含本交易) → delta = 持仓表当前 - 流水聚合
        flow_all = aggregate_positions(all_tx)
        flow_all_stock = next(
            (p for p in flow_all if p.stock_code == trade.stock_code), None
        )
        if cur is not None or flow_all_stock is not None:
            delta = Position(
                stock_code=trade.stock_code,
                stock_name=(cur or flow_all_stock).stock_name,
                shares=(cur.shares if cur else 0) - (flow_all_stock.shares if flow_all_stock else 0),
                total_cost=(cur.total_cost if cur else _D("0"))
                - (flow_all_stock.total_cost if flow_all_stock else _D("0")),
                realized_pnl=(cur.realized_pnl if cur else _D("0"))
                - (flow_all_stock.realized_pnl if flow_all_stock else _D("0")),
            )
            position_before = _merge_delta_and_flow(delta, flow_before)
        else:
            position_before = flow_before

        # 当前全部持仓(真实持仓表,用于集中度 + 0 数据降级)
        all_positions = await get_all_positions()

        recent_objs = before_trades[-RECENT_LIMIT:]
        recent = [
            {"action": t.action, "trade_date": t.trade_date}
            for t in recent_objs
        ]

        # 3. market_ctx(MVP 中性:大盘涨跌待接指数行情,先给中性分)
        market_ctx = {"index_change_pct": 0.0, "sector_rank": None}

        is_in_watchlist = await watchlist_repo.contains(trade.stock_code)

        # 激活 provider(P4.2d:写 provider 标签用,缺 Key 时降级)
        active = await llm_settings_repo.get_active()

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
                ai_provider=active,
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
            for t in recent_objs
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
