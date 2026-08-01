"""多 Provider 占比月度统计(A3 / v0.4.1)

聚合 trade_scores 表的 ai_provider / ai_status 字段,按月返回分布。
用于评估多 Provider 配置的实际使用情况(默认 deepseek 是否被切换)。
"""
from collections import defaultdict
from datetime import date

from sqlalchemy import extract, select

from app.db import async_session
from app.models.orm import TradeScore


async def get_monthly_provider_stats(year: int) -> list[dict]:
    """返回 year 内 12 个月的 Provider 分布

    每条:{"month": "2026-01", "total": N, "providers": {provider: count, ...},
          "statuses": {status: count, ...}}
    - 空月也返回(total=0, providers={}, statuses={})
    - 只统计 ai_provider 非空的 trade_scores
    """
    async with async_session() as session:
        stmt = (
            select(TradeScore)
            .where(extract("year", TradeScore.created_at) == year)
        )
        rows = list((await session.execute(stmt)).scalars().all())

    # 按月聚合
    monthly: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {"providers": defaultdict(int), "statuses": defaultdict(int)}
    )
    for r in rows:
        if not r.ai_provider:
            continue
        key = f"{r.created_at.year:04d}-{r.created_at.month:02d}"
        monthly[key]["providers"][r.ai_provider] += 1
        monthly[key]["statuses"][r.ai_status or "pending"] += 1

    # 生成 12 个月(补全空月)
    out: list[dict] = []
    for m in range(1, 13):
        month_key = f"{year:04d}-{m:02d}"
        entry = monthly.get(month_key, {"providers": {}, "statuses": {}})
        providers = dict(entry["providers"])
        statuses = dict(entry["statuses"])
        out.append({
            "month": month_key,
            "total": sum(providers.values()),
            "providers": providers,
            "statuses": statuses,
        })
    return out


async def get_provider_summary(year: int) -> dict:
    """年度 Provider 汇总(柱状图友好)

    返回:{"year": 2026, "total": N,
          "providers": [{"provider": "deepseek", "count": x, "pct": 50.0}, ...]}
    """
    monthly = await get_monthly_provider_stats(year)
    totals: dict[str, int] = defaultdict(int)
    grand = 0
    for m in monthly:
        for prov, n in m["providers"].items():
            totals[prov] += n
            grand += n
    items = [
        {"provider": p, "count": n, "pct": round(n / grand * 100, 2) if grand else 0.0}
        for p, n in sorted(totals.items(), key=lambda kv: -kv[1])
    ]
    return {"year": year, "total": grand, "providers": items}


__all__ = ["get_monthly_provider_stats", "get_provider_summary"]


# 日期守卫:仅允许年份 2020~当前+1(防止用户乱传)
_MIN_YEAR = 2020
_MAX_YEAR = date.today().year + 1


def validate_year(year: int) -> bool:
    return _MIN_YEAR <= year <= _MAX_YEAR