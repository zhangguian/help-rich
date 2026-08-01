"""评分仓储(P2.1 实施)"""
from typing import Optional

from sqlalchemy import select

from app.db import async_session
from app.models.orm import TradeScore


class TradeScoreRepository:
    async def upsert(
        self,
        *,
        trade_id: int,
        score: int,
        score_breakdown: str,  # JSON string
        ai_provider: str = "deepseek",
    ) -> TradeScore:
        """写入或更新评分(ai_comment / ai_status / ai_model / latency 后补)"""
        async with async_session() as session:
            stmt = select(TradeScore).where(TradeScore.trade_id == trade_id)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                existing.score = score
                existing.score_breakdown = score_breakdown
                existing.ai_provider = ai_provider
            else:
                existing = TradeScore(
                    trade_id=trade_id,
                    score=score,
                    score_breakdown=score_breakdown,
                    ai_provider=ai_provider,
                )
                session.add(existing)
            await session.commit()
            await session.refresh(existing)
            return existing

    async def update_ai_comment(
        self,
        trade_id: int,
        ai_comment: str,
        *,
        ai_status: str = "success",
        ai_model: str | None = None,
        ai_latency_ms: int | None = None,
    ) -> Optional[TradeScore]:
        async with async_session() as session:
            stmt = select(TradeScore).where(TradeScore.trade_id == trade_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            row.ai_comment = ai_comment
            row.ai_status = ai_status
            if ai_model:
                row.ai_model = ai_model
            if ai_latency_ms is not None:
                row.ai_latency_ms = ai_latency_ms
            await session.commit()
            await session.refresh(row)
            return row

    async def get_by_trade_id(self, trade_id: int) -> Optional[TradeScore]:
        async with async_session() as session:
            stmt = select(TradeScore).where(TradeScore.trade_id == trade_id)
            return (await session.execute(stmt)).scalar_one_or_none()

    async def update_ai_status(self, trade_id: int, status: str) -> None:
        """用于 no_key 等失败场景,只更新状态,不写 comment"""
        async with async_session() as session:
            stmt = select(TradeScore).where(TradeScore.trade_id == trade_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row:
                row.ai_status = status
                await session.commit()

    async def update_feedback(self, trade_id: int, feedback: str | None) -> None:
        """P4.9 评语价值反馈(useful / useless / null)"""
        async with async_session() as session:
            stmt = select(TradeScore).where(TradeScore.trade_id == trade_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row:
                row.feedback = feedback
                await session.commit()


trade_score_repo = TradeScoreRepository()