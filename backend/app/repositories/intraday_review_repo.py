"""盘中复盘持久化(同日同档唯一 → 重跑覆盖)

⚠️ **导入形态**:必须写
`from app.repositories.intraday_review_repo import intraday_review_repo`,
**不能**写 `from app.repositories import intraday_review_repo` ——
`app.repositories` 是包,成员名被子模块占位,那样拿到的是**子模块**而不是单例,
调 `.upsert()` 直接 AttributeError(本项目已同型踩坑 3 次)。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.db import async_session
from app.models.orm import IntradayReview


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _row_to_dict(r: IntradayReview) -> dict[str, Any]:
    return {
        "id": r.id,
        "trade_date": r.trade_date,
        "slot": r.slot,
        "payload": _loads(r.payload_json) or {},
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


class IntradayReviewRepo:
    """盘中复盘仓储。所有方法都是幂等的。"""

    async def upsert(
        self, trade_date: str, slot: str, payload: dict[str, Any]
    ) -> int:
        """写入某日某档的复盘(已存在 → 覆盖,不新增行)"""
        async with async_session() as session:
            row = (await session.execute(
                select(IntradayReview).where(
                    IntradayReview.trade_date == trade_date,
                    IntradayReview.slot == slot,
                )
            )).scalar_one_or_none()
            if row is None:
                row = IntradayReview(trade_date=trade_date, slot=slot)
                session.add(row)
            row.payload_json = json.dumps(payload, ensure_ascii=False)
            # 幂等覆盖 → 刷新「最后写入时间」
            row.created_at = datetime.now()
            await session.commit()
            return row.id

    async def get(self, trade_date: str, slot: str) -> dict[str, Any] | None:
        """取某日某档的复盘(不存在 → None)"""
        async with async_session() as session:
            row = (await session.execute(
                select(IntradayReview).where(
                    IntradayReview.trade_date == trade_date,
                    IntradayReview.slot == slot,
                )
            )).scalar_one_or_none()
            if row is None:
                return None
            return _row_to_dict(row)

    async def list_by_date(self, trade_date: str) -> list[dict[str, Any]]:
        """取某日的全部档位(按档位排序)"""
        async with async_session() as session:
            rows = (await session.execute(
                select(IntradayReview)
                .where(IntradayReview.trade_date == trade_date)
                .order_by(IntradayReview.slot)
            )).scalars().all()
            return [_row_to_dict(r) for r in rows]


intraday_review_repo = IntradayReviewRepo()

__all__ = ["IntradayReviewRepo", "intraday_review_repo"]
