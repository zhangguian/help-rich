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
        ai_advice_json: str | None,
        current_price: str | None,
        latest_kline_date: date | None,
        indicators_json: str | None = None,
        ai_json: str | None = None,
        signal_winrate_json: str | None = None,
        quote_change_pct: str | None = None,
        position_status: str | None = None,
        cost_basis_pct: str | None = None,
    ) -> DailyAnalysis:
        """同 (stock_code, analysis_date) UPSERT 覆盖最新内容

        v2.5.2:加 6 个 snapshot 字段(indicators / ai / signal_winrate / quote_change_pct /
        position_status / cost_basis_pct)供 analysis-latest 端点回显。
        """
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
                existing.ai_advice_json = ai_advice_json
                existing.current_price = current_price
                existing.latest_kline_date = latest_kline_date
                existing.indicators_json = indicators_json
                existing.ai_json = ai_json
                existing.signal_winrate_json = signal_winrate_json
                existing.quote_change_pct = quote_change_pct
                existing.position_status = position_status
                existing.cost_basis_pct = cost_basis_pct
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
                    ai_advice_json=ai_advice_json,
                    current_price=current_price,
                    latest_kline_date=latest_kline_date,
                    indicators_json=indicators_json,
                    ai_json=ai_json,
                    signal_winrate_json=signal_winrate_json,
                    quote_change_pct=quote_change_pct,
                    position_status=position_status,
                    cost_basis_pct=cost_basis_pct,
                )
                session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_latest_by_stock(self, stock_code: str) -> Optional[DailyAnalysis]:
        """取该股票最新一条 daily_analysis(按 analysis_date 倒序 LIMIT 1)

        防御:#1 双校验 — 返回的 row.stock_code 必须等于请求的 stock_code
        不等 → raise RuntimeError(防止 ORM/DB 异常导致 stock_code 字段被污染)
        """
        async with async_session() as session:
            stmt = (
                select(DailyAnalysis)
                .where(DailyAnalysis.stock_code == stock_code)
                .order_by(DailyAnalysis.analysis_date.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is not None and row.stock_code != stock_code:
                raise RuntimeError(
                    f"[isolation] repo stock_code mismatch: row.stock_code={row.stock_code} != requested={stock_code}"
                )
            return row

    async def get_most_recent_with_ai(self, stock_code: str) -> Optional[DailyAnalysis]:
        """取该股票最近一条带 AI 解读的 daily_analysis(analysis_date 倒序 LIMIT 1,
        过滤 ai_json IS NOT NULL AND ai_view IS NOT NULL)。

        用途:v2.5.4 兜底 — 当前 LLM 超时时,从历史成功解读里挑一条返回给前端,
        避免用户白等。返回的可能是当日行(若 ai_json 已写入),也可能是历史行。
        调用方负责按 latest_kline_date 判断"是否当日"以决定 ai_source 取值。
        """
        async with async_session() as session:
            stmt = (
                select(DailyAnalysis)
                .where(
                    DailyAnalysis.stock_code == stock_code,
                    DailyAnalysis.ai_json.isnot(None),
                    DailyAnalysis.ai_view.isnot(None),
                )
                .order_by(DailyAnalysis.analysis_date.desc())
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is not None and row.stock_code != stock_code:
                raise RuntimeError(
                    f"[isolation] repo stock_code mismatch: row.stock_code={row.stock_code} != requested={stock_code}"
                )
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