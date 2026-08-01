"""截图识别记录仓储(backend-arch §9.7 / P8.1)"""
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.db import async_session
from app.models.orm import ScreenshotRecord


class ScreenshotRepository:
    async def create(
        self,
        *,
        parsed_items: list[dict],
        file_path: str | None = None,
        ocr_text: str | None = None,
        raw_response: str | None = None,
        screenshot_type: str | None = None,
        source: str = "ocr_llm",
    ) -> ScreenshotRecord:
        """写入一条截图记录(status=pending)"""
        async with async_session() as session:
            record = ScreenshotRecord(
                file_path=file_path,
                ocr_text=ocr_text,
                raw_response=raw_response,
                parsed_items=json.dumps(parsed_items, ensure_ascii=False),
                screenshot_type=screenshot_type,
                source=source,
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def get_by_id(self, record_id: int) -> Optional[ScreenshotRecord]:
        async with async_session() as session:
            return await session.get(ScreenshotRecord, record_id)

    async def list_pending(self) -> list[ScreenshotRecord]:
        async with async_session() as session:
            stmt = (
                select(ScreenshotRecord)
                .where(ScreenshotRecord.status == "pending")
                .order_by(ScreenshotRecord.id.desc())
            )
            return list((await session.execute(stmt)).scalars().all())

    async def mark_confirmed(self, record_id: int) -> None:
        """用户确认后:status=confirmed + confirmed_at"""
        async with async_session() as session:
            record = await session.get(ScreenshotRecord, record_id)
            if record:
                record.status = "confirmed"
                record.confirmed_at = datetime.now()
                await session.commit()

    async def mark_rejected(self, record_id: int) -> None:
        """用户取消:status=rejected"""
        async with async_session() as session:
            record = await session.get(ScreenshotRecord, record_id)
            if record:
                record.status = "rejected"
                await session.commit()


screenshot_repo = ScreenshotRepository()
