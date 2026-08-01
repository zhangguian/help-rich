"""管理端点(健康检查 + 备份/导出/导入)

P7.3 数据导出/导入 + P7.9 自动备份归档

- GET  /api/admin/health        健康检查
- GET  /api/admin/export       导出全部数据为 JSON
- POST /api/admin/import       导入 JSON 数据(覆盖现有)
- POST /api/admin/backup       写一次 JSON 备份到 backups/ 目录
"""
import json
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.core.db_lock import safe_write
from app.db import async_session
from app.models.orm import (
    LlmApiKey,
    LlmSettings,
    ScreenshotRecord,
    StopLoss,
    TradeScore,
    Transaction,
    Watchlist,
)

router = APIRouter(prefix="/admin", tags=["admin"])

BACKUP_DIR = Path(__file__).resolve().parents[3] / "backups"


@router.get("/health")
async def health() -> dict:
    """健康检查(P1.1)"""
    return {"status": "ok"}


# ============================================================
# === 导出 / 导入(P7.3) ===
# ============================================================

# 导出包含的表 + 各表 ORM model
EXPORT_TABLES = {
    "transactions": Transaction,
    "watchlist": Watchlist,
    "trade_scores": TradeScore,
    "stop_losses": StopLoss,
    "llm_api_keys": LlmApiKey,
    "llm_settings": LlmSettings,
    "screenshot_records": ScreenshotRecord,
}

EXCLUDE_FIELDS = {
    "encrypted_key",  # LLM Key 不导出(敏感)
}


def _row_to_dict(row, exclude: set[str]) -> dict:
    out = {}
    for col in row.__table__.columns:
        if col.name in exclude or col.name in EXCLUDE_FIELDS:
            continue
        v = getattr(row, col.name)
        if isinstance(v, (datetime, date)):
            v = v.isoformat()
        out[col.name] = v
    return out


@router.get("/export")
async def export_all() -> JSONResponse:
    """导出全部数据为 JSON(P7.3)

    返回结构:
      {
        "version": "0.1.0",
        "exported_at": "2026-08-01T...",
        "tables": {
          "transactions": [...],
          "watchlist": [...],
          ...
        }
      }
    """
    payload: dict = {
        "version": "0.1.0",
        "exported_at": datetime.now().isoformat(),
        "tables": {},
    }

    for name, model in EXPORT_TABLES.items():
        async with async_session() as session:
            rows = list((await session.execute(select(model))).scalars().all())
            # screenshot_records 排除大字段(ocr_text / raw_response)节省体积
            exclude = set()
            if name == "screenshot_records":
                exclude = {"ocr_text", "raw_response"}
            payload["tables"][name] = [_row_to_dict(r, exclude) for r in rows]

    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": f'attachment; filename="rich-export-{datetime.now().strftime("%Y%m%d-%H%M%S")}.json"',
        },
    )


class ImportRequest(BaseModel):
    """POST /api/admin/import body(P7.3)"""
    payload: dict
    mode: str = "replace"  # replace / merge(MVP 仅实现 replace)


@router.post("/import")
async def import_data(req: ImportRequest) -> dict:
    """导入 JSON 数据(P7.3)

    mode=replace:清空现有数据后全量替换(快照恢复用)
    """
    if req.mode != "replace":
        raise HTTPException(
            status_code=400,
            detail={"code": "UNSUPPORTED_MODE", "message": "MVP 仅支持 replace 模式"},
        )
    if "tables" not in req.payload:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PAYLOAD", "message": "缺少 tables 字段"},
        )

    counts: dict[str, int] = {}

    async def _do_import():
        # 清空所有表(FK cascade 处理 trade_scores 等)
        for model in reversed(list(EXPORT_TABLES.values())):
            async with async_session() as session:
                await session.execute(delete(model))
                await session.commit()

        # 插入(按字段类型还原 ISO 日期字符串 → date/datetime)
        for name, model in EXPORT_TABLES.items():
            rows = req.payload["tables"].get(name, [])
            if not rows:
                counts[name] = 0
                continue
            async with async_session() as session:
                for row_data in rows:
                    valid_cols = {c.name for c in model.__table__.columns}
                    clean = {k: v for k, v in row_data.items() if k in valid_cols}
                    if not clean:
                        continue
                    # Date / DateTime 字段从 ISO 字符串还原
                    for col in model.__table__.columns:
                        if col.name not in clean:
                            continue
                        v = clean[col.name]
                        if v is None:
                            continue
                        col_type = col.type.__class__.__name__
                        if col_type == "Date" and isinstance(v, str):
                            clean[col.name] = date.fromisoformat(v[:10])
                        elif col_type == "DateTime" and isinstance(v, str):
                            try:
                                clean[col.name] = datetime.fromisoformat(v)
                            except ValueError:
                                clean[col.name] = datetime.fromisoformat(v.replace("Z", "+00:00"))
                    obj = model(**clean)
                    session.add(obj)
                await session.commit()
                counts[name] = len(rows)

    await safe_write(_do_import)
    return {"ok": True, "mode": req.mode, "imported": counts}


# ============================================================
# === 备份归档(P7.9) ===
# ============================================================

@router.post("/backup")
async def backup() -> dict:
    """生成一次 JSON 备份,写入 backups/pre-{ts}.json(P7.9)

    用户可定期调用(自动备份建议 cron 每天 22:00)
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    payload: dict = {
        "version": "0.1.0",
        "exported_at": datetime.now().isoformat(),
        "tables": {},
    }
    for name, model in EXPORT_TABLES.items():
        async with async_session() as session:
            rows = list((await session.execute(select(model))).scalars().all())
            exclude = {"ocr_text", "raw_response"} if name == "screenshot_records" else set()
            payload["tables"][name] = [_row_to_dict(r, exclude) for r in rows]

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"pre-{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"ok": True, "path": str(path), "size_bytes": path.stat().st_size}


__all__ = ["router"]