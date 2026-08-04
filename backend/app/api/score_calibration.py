"""评分样本外校准 API(GB-001 IR-3)

- GET /api/score-calibration → 返回按分数段聚合的"评分 → 实际收益"校准表
  设计为独立路由,前端风险报告页 / 设置页历史工具可按需拉取。
"""
from fastapi import APIRouter

from app.services.score_calibration import compute_calibration

router = APIRouter(prefix="/score-calibration", tags=["score-calibration"])


@router.get("")
async def get_score_calibration() -> dict:
    """评分校准表(GB-001 IR-3)

    按分数段(0-59 / 60-79 / 80-100)聚合 BUY 评分后 20 个交易日的实际持有期收益。
    样本不足(MIN_SAMPLES < 3)→ 桶内 insufficient=true,前端展示"样本不足"。

    字段命名 camelCase:响应在 API 层已是 snake_case,前端拦截器自动转。
    """
    return await compute_calibration()


__all__ = ["router"]
