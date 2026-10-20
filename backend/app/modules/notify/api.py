"""通知渠道配置 API(阶段1)

- GET  /api/notify/channels          → 渠道列表(含启用状态与提示,不含明文凭据)
- PUT  /api/notify/channels/{ch}     → 保存配置(凭据加密落库)
- POST /api/notify/channels/{ch}/test → 发一条测试消息验证连通性

本模块只做 HTTP 映射;凭据加解密与渠道构造在
`services/notify/config_service.py`,以守住 api → repositories 的边界规则。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.modules.notify.base import NotifyChannel
from app.modules.notify.config_service import notify_config_service

router = APIRouter(prefix="/notify", tags=["notify"])


class ChannelConfigIn(BaseModel):
    enabled: bool = True
    # 各渠道需要的字段:webhook/secret/device_key/server/url/headers
    config: dict = Field(default_factory=dict)


@router.get("/channels")
async def list_channels() -> dict:
    items = await notify_config_service.list_channels()
    return {"items": items}


@router.put("/channels/{channel}")
async def upsert_channel(channel: str, payload: ChannelConfigIn) -> dict:
    try:
        NotifyChannel(channel)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"未知渠道: {channel}") from e
    return await notify_config_service.save_channel(
        channel=channel, enabled=payload.enabled, config=payload.config
    )


@router.post("/channels/{channel}/test")
async def test_channel(channel: str) -> dict:
    try:
        return await notify_config_service.test_channel(channel)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
