"""LLM Key 管理 API(v2.1 §11.3 / api-contract §11.4-11.6 / P4.2e)

- GET  /api/llm/keys       → 返回 3 Provider 配置状态(不返回明文)
- PUT  /api/llm/keys       → 更新 Key(body: {deepseek, minimax, doubao})
- GET  /api/llm/providers  → 返回可用 provider 列表(名称 + 模型 + 配置状态)
- GET  /api/llm/settings   → 获取当前激活 provider
- POST /api/llm/settings   → 切换激活 provider
- POST /api/llm/test       → 测试连接(真实调一次 API)
"""
from fastapi import APIRouter, HTTPException

from app.llm.factory import provider_factory
from app.models.schemas import (
    LlmKeysStatus,
    LlmKeysUpdate,
    LlmProvidersOut,
    LlmSettingsOut,
    LlmTestRequest,
    LlmTestResponse,
)
from app.repositories.llm_keys_repo import llm_keys_repo
from app.repositories.llm_settings_repo import llm_settings_repo
from app.services.llm_test_service import llm_test_service

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/keys", response_model=LlmKeysStatus)
async def get_llm_keys() -> LlmKeysStatus:
    """返回 3 Provider 的 Key 配置状态(不返回明文)"""
    status = await llm_keys_repo.list_status()
    return LlmKeysStatus(**status)


@router.get("/providers", response_model=LlmProvidersOut)
async def get_llm_providers() -> LlmProvidersOut:
    """返回可用 provider 列表(前端设置页下拉用,P4.2e)"""
    items = await provider_factory.available()
    return LlmProvidersOut(items=items)


@router.get("/settings", response_model=LlmSettingsOut)
async def get_llm_settings() -> LlmSettingsOut:
    """获取当前激活 provider(P4.2e)"""
    active = await llm_settings_repo.get_active()
    return LlmSettingsOut(active_provider=active)


@router.post("/settings", response_model=LlmSettingsOut)
async def set_llm_settings(payload: LlmSettingsOut) -> LlmSettingsOut:
    """切换激活 provider(P4.2e)"""
    if payload.active_provider not in ("deepseek", "minimax", "doubao"):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_PROVIDER",
                "message": "未知 Provider,仅支持 deepseek / minimax / doubao",
            },
        )
    active = await llm_settings_repo.set_active(payload.active_provider)
    return LlmSettingsOut(active_provider=active)


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

    P4.2e 升级:真实调一次 API(重试 1 次)。
    """
    return await llm_test_service.test_provider(payload.provider)