"""每日 AI 分析仓储(v2.4 一键复盘演进)

同 (stock_code, analysis_date) UPSERT 覆盖最新内容。
- upsert:写入或覆盖
- get:取单条
- list_by_stock:按股票倒序拉历史
- list_range:区间查询(为胜率 P1 预留)
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional

from sqlalchemy import select

from app.db import async_session
from app.models.orm import DailyAnalysis


class DailyAnalysisRepository:
    async def upsert(
        self,
        *,
        stock_code: str,
        analysis_date: date,
        score_avg: str | None,
        dimension_avg: dict,
        top_issues: list,
        ai_view: str | None,
        ai_summary: str | None,
        current_price: str | None,
        latest_kline_date: date | None,
    ) -> DailyAnalysis:
        """同 (stock_code, analysis_date) UPSERT 覆盖最新内容"""
        async with async_session() as session:
            stmt = select(DailyAnalysis).where(
                DailyAnalysis.stock_code == stock_code,
                DailyAnalysis.analysis_date == analysis_date,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            dim_json = json.dumps(dimension_avg, ensure_ascii=False)
            issues_json = json.dumps(top_issues, ensure_ascii=False)
            if existing:
                existing.score_avg = score_avg
                existing.dimension_avg = dim_json
                existing.top_issues = issues_json
                existing.ai_view = ai_view
                existing.ai_summary = ai_summary
                existing.current_price = current_price
                existing.latest_kline_date = latest_kline_date
                # updated_at 由 onupdate 自动更新;created_at 保留首写时间
                row = existing
            else:
                row = DailyAnalysis(
                    stock_code=stock_code,
                    analysis_date=analysis_date,
                    score_avg=score_avg,
                    dimension_avg=dim_json,
                    top_issues=issues_json,
                    ai_view=ai_view,
                    ai_summary=ai_summary,
                    current_price=current_price,
                    latest_kline_date=latest_kline_date,
                )
                session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get(
        self, stock_code: str, analysis_date: date
    ) -> Optional[DailyAnalysis]:
        async with async_session() as session:
            stmt = select(DailyAnalysis).where(
                DailyAnalysis.stock_code == stock_code,
                DailyAnalysis.analysis_date == analysis_date,
            )
            return (await session.execute(stmt)).scalar_one_or_none()

    async def list_by_stock(
        self, stock_code: str, limit: int = 30
    ) -> list[DailyAnalysis]:
        """按股票倒序拉最近 N 条(最新在前)"""
        async with async_session() as session:
            stmt = (
                select(DailyAnalysis)
                .where(DailyAnalysis.stock_code == stock_code)
                .order_by(DailyAnalysis.analysis_date.desc())
                .limit(limit)
            )
            return list((await session.execute(stmt)).scalars().all())

    async def list_range(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[DailyAnalysis]:
        """区间查询(为 P1 胜率准备)"""
        async with async_session() as session:
            stmt = (
                select(DailyAnalysis)
                .where(
                    DailyAnalysis.stock_code == stock_code,
                    DailyAnalysis.analysis_date >= start_date,
                    DailyAnalysis.analysis_date <= end_date,
                )
                .order_by(DailyAnalysis.analysis_date.asc())
            )
            return list((await session.execute(stmt)).scalars().all())


daily_analysis_repo = DailyAnalysisRepository()