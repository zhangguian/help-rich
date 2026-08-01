"""截图识别服务(backend-arch §9.7 / P8.4)

- parse_from_image:主路径(OCR + LLM 解析)
- parse_from_paste:降级路径(用户粘贴 JSON)
- confirm / reject:用户确认 / 取消

隐私:原图只存本地 uploads/,LLM 只接收 OCR 文本,不接收图片。
"""
import json
import logging
import uuid
from pathlib import Path

from app.core.db_lock import safe_write
from app.core.prompts import build_ocr_prompt, OCR_SYSTEM
from app.llm.base import LLMError
from app.llm.factory import provider_factory
from app.ocr.paddle_client import paddle_client
from app.ocr.text_extract import extract_items
from app.repositories.llm_settings_repo import llm_settings_repo
from app.repositories.screenshot_repo import screenshot_repo
from app.repositories.transaction_repo import transaction_repo
from app.repositories.watchlist_repo import watchlist_repo

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(__file__).resolve().parents[3] / "uploads"

# 置信度低于此值的行前端标红,用户手动改
LOW_CONFIDENCE = 0.5


class ScreenshotError(Exception):
    def __init__(self, message: str, code: str = "SCREENSHOT_ERROR"):
        super().__init__(message)
        self.code = code


class ScreenshotService:
    async def parse_from_image(self, file_bytes: bytes, filename: str) -> dict:
        """主路径:OCR + LLM 解析(LLM 仅文本)"""
        # 1. 保存原图到本地 uploads/
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        file_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{Path(filename).suffix or '.jpg'}"
        file_path.write_bytes(file_bytes)

        # 2. OCR 提取文本(失败 → 走降级提示)
        try:
            ocr_text = await paddle_client.extract_text(str(file_path))
        except RuntimeError as e:
            raise ScreenshotError(f"OCR 失败:{e}", code="OCR_FAILED") from e

        if not ocr_text.strip():
            raise ScreenshotError("OCR 未识别到文本", code="OCR_EMPTY")

        # 3. 先用本地规则提取(无 LLM 成本;confidence 高则直接预览)
        extracted = extract_items(ocr_text)

        raw = ""
        items = extracted["items"]
        screenshot_type = extracted["screenshot_type"]
        if not items:
            # 4. 本地规则失败 → LLM 解析
            active = await llm_settings_repo.get_active()
            llm = await provider_factory.get(active)
            if llm is None:
                raise ScreenshotError("本地规则未命中且未配置 LLM Key,可粘贴 JSON 降级", code="NO_KEY")
            prompt = build_ocr_prompt(ocr_text)
            try:
                raw = await llm.chat(OCR_SYSTEM, prompt)
                parsed = self._parse_llm_json(raw)
                items = parsed.get("items", [])
                screenshot_type = parsed.get("screenshot_type") or "position"
            except (LLMError, ScreenshotError) as e:
                raise ScreenshotError(f"LLM 解析失败:{e}", code="LLM_PARSE_FAILED") from e

        # 5. 写记录(pending)
        record = await screenshot_repo.create(
            file_path=str(file_path),
            ocr_text=ocr_text,
            raw_response=raw,
            parsed_items=items,
            screenshot_type=screenshot_type,
            source="ocr_llm",
        )
        return {"record_id": record.id, "items": items, "ocr_text": ocr_text,
                "screenshot_type": screenshot_type}

    async def parse_from_paste(self, raw_json: str) -> dict:
        """降级路径:用户粘贴外网模型输出,直接解析(无 LLM 调用)"""
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise ScreenshotError(f"JSON 格式错误:{e}", code="INVALID_JSON") from e

        if not isinstance(data, dict) or "items" not in data:
            raise ScreenshotError("JSON 缺少 items 字段", code="INVALID_JSON")

        items = data["items"]
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            raise ScreenshotError("items 必须是对象数组", code="INVALID_JSON")

        screenshot_type = data.get("screenshot_type") or self._guess_type(items)

        # 写记录(source='manual_paste', file_path=NULL)
        record = await screenshot_repo.create(
            parsed_items=items,
            screenshot_type=screenshot_type,
            raw_response=raw_json,
            source="manual_paste",
        )
        return {"record_id": record.id, "items": items, "screenshot_type": screenshot_type}

    @staticmethod
    def _parse_llm_json(raw: str) -> dict:
        """解析 LLM 返回 JSON(容忍 markdown 代码块包裹)"""
        text = raw.strip()
        if text.startswith("```"):
            # 去掉 ```json ... ``` 包裹
            first_nl = text.find("\n")
            last_marker = text.rfind("```")
            text = text[first_nl + 1:last_marker].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ScreenshotError(f"LLM 返回非法 JSON:{e}", code="INVALID_JSON") from e
        if not isinstance(data, dict) or "items" not in data:
            raise ScreenshotError("LLM 返回缺少 items", code="INVALID_JSON")
        return data

    @staticmethod
    def _guess_type(items: list[dict]) -> str:
        if items and "action" in items[0]:
            return "transactions"
        return "position"

    async def confirm(self, record_id: int, items: list[dict], screenshot_type: str) -> None:
        """用户确认后入库 transactions / watchlist"""
        from datetime import date as date_cls

        async def _do():
            if screenshot_type == "transactions":
                for item in items:
                    trade_date = item["trade_date"]
                    if isinstance(trade_date, str):
                        trade_date = date_cls.fromisoformat(trade_date[:10])
                    await transaction_repo.create(
                        stock_code=item["stock_code"],
                        stock_name=item.get("stock_name"),
                        action=item["action"],
                        shares=int(item["shares"]),
                        price=str(item["price"]),
                        trade_date=trade_date,
                    )
            elif screenshot_type == "watchlist":
                for item in items:
                    await watchlist_repo.add(
                        stock_code=item["stock_code"],
                        stock_name=item.get("stock_name"),
                    )
            await screenshot_repo.mark_confirmed(record_id)

        await safe_write(_do)

    async def reject(self, record_id: int) -> None:
        """用户取消:标记 rejected + 删除原图"""
        record = await screenshot_repo.get_by_id(record_id)
        if record and record.file_path:
            try:
                Path(record.file_path).unlink(missing_ok=True)
            except OSError:
                logger.warning("删除原图失败: %s", record.file_path)
        await screenshot_repo.mark_rejected(record_id)


screenshot_service = ScreenshotService()
