"""每日作战计划 API(阶段9)

- GET  /api/battle-plan?date=YYYY-MM-DD  取指定日期的日报(默认今天)
- POST /api/battle-plan/generate        生成今天的日报(幂等)
- GET  /api/battle-plan/scope           目标股票池(持仓 ∪ ★关注)
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.battle_plan_service import (
    build_plan,
    get_plan,
    resolve_target_stocks,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/battle-plan", tags=["battle-plan"])


class GenerateRequest(BaseModel):
    date: str | None = None


def _with_outlook(plan: dict) -> dict:
    """保证响应里 `outlook` 非 null。

    落库的日报可能没有 outlook_json(早期数据 / 写入时被裁剪),而前端契约里
    `outlook` 是**必填非 null**(组件直接读 `outlook.stance`)。
    这里填一个**降级**的空 outlook —— 如实说「数据不足」,而不是让前端到处判 null。
    """
    if plan.get("outlook"):
        return plan
    out = dict(plan)
    out["outlook"] = {
        "stance": "unknown",
        "stance_label": "数据不足",
        "score": 0,
        "dims_total": 0,
        "dims_effective": 0,
        "dims": [],
        "key_levels": {
            "close": None, "ma5": None, "ma10": None, "ma20": None,
            "support": [], "resistance": [],
        },
        "disclaimer": "数据不足，无法给出明日倾向；请重新生成作战计划。",
        "degraded": True,
        "degraded_reason": ["该日期的日报没有市场预期数据"],
    }
    return out


@router.get("")
async def read_plan(plan_date: str | None = Query(default=None, alias="date")) -> dict:
    """取指定日期的作战日报;该日未生成 → 404(不返回空壳)

    ⚠️ 形参**不能叫 `date`** —— 它会遮蔽 `from datetime import date` 这个类,
    函数体内的 `date.fromisoformat(...)` 会变成在 str 上找方法 → AttributeError → 500,
    422 的「日期格式」分支永远走不到。这里用 `plan_date` + `Query(alias="date")`:
    对外查询参数仍是 `?date=YYYY-MM-DD`。
    """
    if plan_date:
        try:
            target = date.fromisoformat(plan_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD") from None
    else:
        target = date.today()
    try:
        plan = await get_plan(target)
    except Exception as e:  # noqa: BLE001
        # 迁移未执行时会是 `no such table: battle_plans` —— 必须转成可读的 500,
        # 不能把裸栈/原始驱动错误抛给前端
        logger.exception("读取作战计划失败")
        raise HTTPException(status_code=500, detail=f"读取作战计划失败: {e}") from e
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail=f"{target.isoformat()} 的作战计划尚未生成",
        )
    return _with_outlook(plan)


@router.post("/generate")
async def generate(req: GenerateRequest | None = None) -> dict:
    """生成指定日期(默认今天)的作战日报"""
    target = date.today()
    if req and req.date:
        try:
            target = date.fromisoformat(req.date)
        except ValueError:
            raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD") from None
    try:
        return _with_outlook(await build_plan(target))
    except ValueError as e:
        # build_plan 在股票池为空时抛 ValueError —— 转成可读的 422,不要 500
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("生成作战计划失败")
        raise HTTPException(status_code=500, detail=f"生成作战计划失败: {e}") from e


@router.get("/scope")
async def scope() -> list[dict]:
    """目标股票池(持仓 ∪ ★关注 去重)"""
    return await resolve_target_stocks()


__all__ = ["router"]