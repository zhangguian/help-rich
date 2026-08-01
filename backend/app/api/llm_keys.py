"""LLM Key 管理 API(v2.1 §11.3 / api-contract §11.4-11.6)

- GET  /api/llm/keys     → 返回 3 Provider 配置状态(不返回明文)
- PUT  /api/llm/keys     → 更新 Key(body: {deepseek, minimax, doubao})
- POST /api/llm/test     → 测试连接(body: {provider})
"""
from fastapi import APIRouter, HTTPException

from app.models.schemas import LlmKeysStatus, LlmKeysUpdate, LlmTestRequest, LlmTestResponse
from app.repositories.llm_keys_repo import llm_keys_repo
from app.services.llm_test_service import llm_test_service

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/keys", response_model=LlmKeysStatus)
async def get_llm_keys() -> LlmKeysStatus:
    """返回 3 Provider 的 Key 配置状态(不返回明文)"""
    status = await llm_keys_repo.list_status()
    return LlmKeysStatus(**status)


@router.put("/keys")
async def update_llm_keys(payload: LlmKeysUpdate) -> dict:
    """更新 Key

    body 中空字符串表示不修改 / 清空该 Provider 的 Key。
    若 3 个都是空字符串,返回 400(必须至少改一个)。
    """
    updates = {
        "deepseek": payload.deepseek.strip(),
        "minimax": payload.minimax.strip(),
        "doubao": payload.doubao.strip(),
    }

    if not any(updates.values()):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EMPTY_UPDATE",
                "message": "至少填写一个 Provider 的 Key",
            },
        )

    # 空字符串 = 删除该 Provider 的 Key
    for provider, key in updates.items():
        if key == "":
            await llm_keys_repo.delete(provider)
        else:
            await llm_keys_repo.upsert(provider, key)

    return {"ok": True}


@router.post("/test", response_model=LlmTestResponse)
async def test_llm(payload: LlmTestRequest) -> LlmTestResponse:
    """测试 provider 连接

    P1.4 阶段只验证 Key 存在 + 格式。P4.2 升级为真实 API 调用。
    """
    return await llm_test_service.test_provider(payload.provider)