"""截图识别 API(backend-arch §7.1 / P8.5)

- POST /api/screenshot/upload       → 上传截图 + 异步识别主路径
- GET  /api/screenshot/pending      → 待确认列表(前端预览)
- POST /api/screenshot/{id}/confirm → 用户确认入库(可编辑)
- POST /api/screenshot/{id}/reject  → 取消,删除原图
- POST /api/screenshot/parse-paste  → 降级:粘贴 JSON 解析

隐私:原图只存本地 uploads/,LLM 只接收 OCR 文本。
"""
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile

from app.models.schemas import (
    ScreenshotConfirmRequest,
    ScreenshotParseOut,
    ScreenshotPasteRequest,
)
from app.repositories.screenshot_repo import screenshot_repo
from app.services.screenshot_service import ScreenshotError, screenshot_service

router = APIRouter(prefix="/screenshot", tags=["screenshot"])

# 图片格式白名单 + 大小上限(5MB)
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_SIZE = 5 * 1024 * 1024


@router.post("/upload", response_model=ScreenshotParseOut)
async def upload_screenshot(file: UploadFile) -> ScreenshotParseOut:
    """上传截图,OCR + LLM 识别(主路径)"""
    suffix = (file.filename or "").lower()
    if not suffix.endswith(tuple(ALLOWED_EXT)):
        raise HTTPException(
            status_code=415,
            detail={"code": "UNSUPPORTED_TYPE", "message": "暂只支持 jpg / png / webp 格式"},
        )
    file_bytes = await file.read()
    if len(file_bytes) > MAX_SIZE:
        raise HTTPException(
            status_code=413,
            detail={"code": "FILE_TOO_LARGE", "message": "图片过大,请压缩后重试(≤5MB)"},
        )
    try:
        result = await screenshot_service.parse_from_image(file_bytes, file.filename or "upload")
    except ScreenshotError as e:
        raise HTTPException(status_code=422, detail={"code": e.code, "message": str(e)}) from e
    return ScreenshotParseOut(**result)


@router.post("/parse-paste", response_model=ScreenshotParseOut)
async def parse_paste(payload: ScreenshotPasteRequest) -> ScreenshotParseOut:
    """降级路径:用户粘贴外网模型输出 JSON"""
    try:
        result = await screenshot_service.parse_from_paste(payload.raw_json)
    except ScreenshotError as e:
        raise HTTPException(status_code=422, detail={"code": e.code, "message": str(e)}) from e
    return ScreenshotParseOut(**result)


@router.get("/pending")
async def list_pending() -> dict:
    """待确认截图列表(前端预览)"""
    records = await screenshot_repo.list_pending()
    items = []
    for r in records:
        items.append({
            "record_id": r.id,
            "items": json.loads(r.parsed_items),
            "screenshot_type": r.screenshot_type,
            "source": r.source,
            "uploaded_at": r.uploaded_at.isoformat(),
        })
    return {"items": items}


@router.post("/{record_id}/confirm")
async def confirm_screenshot(record_id: int, payload: ScreenshotConfirmRequest) -> dict:
    """用户确认(可编辑)后入库 transactions / watchlist"""
    record = await screenshot_repo.get_by_id(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "RECORD_NOT_FOUND", "message": "记录不存在"})
    if record.status == "confirmed":
        raise HTTPException(status_code=409, detail={"code": "ALREADY_CONFIRMED", "message": "该记录已确认"})
    if not payload.items:
        raise HTTPException(status_code=422, detail={"code": "EMPTY_ITEMS", "message": "没有可入库的数据"})
    await screenshot_service.confirm(record_id, payload.items, payload.screenshot_type)
    return {"ok": True, "record_id": record_id}


@router.post("/{record_id}/reject")
async def reject_screenshot(record_id: int) -> dict:
    """用户取消:标记 rejected + 删除原图"""
    record = await screenshot_repo.get_by_id(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "RECORD_NOT_FOUND", "message": "记录不存在"})
    await screenshot_service.reject(record_id)
    return {"ok": True, "record_id": record_id}
