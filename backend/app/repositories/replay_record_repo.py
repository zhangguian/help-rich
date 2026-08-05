"""复盘记录仓储(v2.3 一键复盘)

同 (stock_code, window) UPSERT,保证多次复盘只保留最新一条。
"""
import json
from typing import Optional

from sqlalchemy import select

from app.db import async_session
from app.models.orm import ReplayRecord


class ReplayRecordRepository:
    async def get(self, stock_code: str, window: str) -> Optional[ReplayRecord]:
        async with async_session() as session:
            stmt = select(ReplayRecord).where(
                ReplayRecord.stock_code == stock_code,
                ReplayRecord.window == window,
            )
            return (await session.execute(stmt)).scalar_one_or_none()

    async def list_by_stock(self, stock_code: str) -> list[ReplayRecord]:
        async with async_session() as session:
            stmt = select(ReplayRecord).where(
                ReplayRecord.stock_code == stock_code
            )
            return list((await session.execute(stmt)).scalars().all())

    async def upsert(
        self,
        *,
        stock_code: str,
        window: str,
        score_avg: str | None,
        dimension_avg: dict,
        top_issues: list,
        summary_snapshot: dict,
        ai_comment: str | None,
        ai_status: str,
        ai_provider: str | None,
        ai_model: str | None,
        ai_latency_ms: int | None,
        latest_tx_id: int,
    ) -> ReplayRecord:
        """同 (stock_code, window) UPSERT(同窗口多次复盘 → 覆盖为最新)"""
        async with async_session() as session:
            stmt = select(ReplayRecord).where(
                ReplayRecord.stock_code == stock_code,
                ReplayRecord.window == window,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                existing.score_avg = score_avg
                existing.dimension_avg = json.dumps(dimension_avg, ensure_ascii=False)
                existing.top_issues = json.dumps(top_issues, ensure_ascii=False)
                existing.summary_snapshot = json.dumps(summary_snapshot, ensure_ascii=False)
                existing.ai_comment = ai_comment
                existing.ai_status = ai_status
                existing.ai_provider = ai_provider
                existing.ai_model = ai_model
                existing.ai_latency_ms = ai_latency_ms
                existing.latest_tx_id = latest_tx_id
                row = existing
            else:
                row = ReplayRecord(
                    stock_code=stock_code,
                    window=window,
                    score_avg=score_avg,
                    dimension_avg=json.dumps(dimension_avg, ensure_ascii=False),
                    top_issues=json.dumps(top_issues, ensure_ascii=False),
                    summary_snapshot=json.dumps(summary_snapshot, ensure_ascii=False),
                    ai_comment=ai_comment,
                    ai_status=ai_status,
                    ai_provider=ai_provider,
                    ai_model=ai_model,
                    ai_latency_ms=ai_latency_ms,
                    latest_tx_id=latest_tx_id,
                )
                session.add(row)
            await session.commit()
            await session.refresh(row)
            return row


replay_record_repo = ReplayRecordRepository()