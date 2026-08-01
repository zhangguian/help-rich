"""健康检查 + 系统管理端点"""
from fastapi import APIRouter

router = APIRouter(tags=["admin"])


@router.get("/health")
async def health() -> dict:
    """健康检查(MVP P1.1)

    期望响应:200 + {"status": "ok"}
    """
    return {"status": "ok"}


__all__ = ["router"]