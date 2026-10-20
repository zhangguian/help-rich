"""多智能体深度分析 API(阶段4)

- GET /api/multi-agent/{stock_code}          → 完整决策书(多空辩论 + 风控 + PM 裁决)
- GET /api/multi-agent/meta/roles            → 角色与动作枚举(前端渲染用)

说明:单次分析要调 7~8 次 LLM,耗时较长(10~40s),因此不做 SSE 流式;
前端展示 loading 即可。若要流式推理链,留作后续增强。
"""
from fastapi import APIRouter, HTTPException

from app.modules.analysis.contracts import (
    ACTION_LABELS,
    ROLE_LABELS,
    STANCE_LABELS,
)
from app.modules.analysis.service import multi_agent_service

router = APIRouter(prefix="/multi-agent", tags=["multi-agent"])


@router.get("/meta/roles")
async def roles_meta() -> dict:
    return {
        "roles": [{"key": k, "label": v} for k, v in ROLE_LABELS.items()],
        "stances": [{"key": k, "label": v} for k, v in STANCE_LABELS.items()],
        "actions": [{"key": k, "label": v} for k, v in ACTION_LABELS.items()],
    }


@router.get("/{stock_code}")
async def analyze(stock_code: str) -> dict:
    try:
        report = await multi_agent_service.analyze(stock_code)
    except Exception as e:  # noqa: BLE001 — 顶层兜底,避免 500 泄漏堆栈
        raise HTTPException(status_code=502, detail=f"多智能体分析失败: {e}") from e
    return report.to_dict()
