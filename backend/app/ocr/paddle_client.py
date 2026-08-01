"""PaddleOCR 异步封装(backend-arch §9.7.6 / P8.2)

- lazy init:首次调用才加载模型(~50MB)
- asyncio.to_thread 跑 CPU 密集 OCR(不阻塞事件循环)
- 兼容 paddleocr 3.x(`predict`)与 2.x(`ocr`)两种 API
- 置信度 < 0.5 的行丢弃
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PaddleOCRClient:
    def __init__(self):
        self._ocr: Optional[object] = None
        self._load_error: Optional[str] = None

    async def _get_ocr(self):
        """lazy init:首次调用加载模型,失败缓存错误(降级用)"""
        if self._ocr is None and self._load_error is None:
            try:
                from paddleocr import PaddleOCR

                self._ocr = await asyncio.to_thread(
                    PaddleOCR, use_angle_cls=True, lang="ch", show_log=False
                )
            except Exception as e:  # noqa: BLE001
                self._load_error = str(e)
                logger.warning("PaddleOCR 加载失败(走降级): %s", e)
        return self._ocr

    async def extract_text(self, image_path: str) -> str:
        """提取图片文本(行分隔);OCR 不可用时抛异常,由上层走降级"""
        ocr = await self._get_ocr()
        if ocr is None:
            raise RuntimeError(f"PaddleOCR 不可用: {self._load_error}")

        try:
            # paddleocr 3.x:ocr.predict(path) 返回 result.json
            result = await asyncio.to_thread(self._call_ocr, ocr, image_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("OCR 识别失败: %s", e)
            raise RuntimeError(f"OCR 识别失败: {e}") from e

        return self._format_result(result)

    @staticmethod
    def _call_ocr(ocr, image_path: str):
        """兼容 2.x / 3.x 调用方式"""
        if hasattr(ocr, "predict"):
            return ocr.predict(image_path)
        return ocr.ocr(image_path, cls=True)

    def _format_result(self, result) -> str:
        """拼接所有识别文本(置信度 > 0.5),行分隔"""
        lines = []
        for box_group in self._iter_boxes(result):
            for item in box_group:
                text, conf = self._parse_item(item)
                if text and conf > 0.5:
                    lines.append(text)
        return "\n".join(lines)

    @staticmethod
    def _iter_boxes(result):
        """3.x:result 是 list[dict],含 'rec_texts'/'rec_scores';2.x:result[0] 是 [[box, (text, conf)], ...]"""
        if isinstance(result, dict):
            # 3.x 单张:result['rec_texts'] / result['rec_scores']
            return [list(zip(result.get("rec_texts", []), result.get("rec_scores", [])))]
        if isinstance(result, list) and result and isinstance(result[0], dict):
            return [list(zip(r.get("rec_texts", []), r.get("rec_scores", []))) for r in result]
        if isinstance(result, list) and result:
            return [result[0] if isinstance(result[0], list) else result]
        return []

    @staticmethod
    def _parse_item(item):
        """2.x: ('text', conf);3.x 已展平为 (text, conf)"""
        if isinstance(item, (tuple, list)):
            if len(item) == 2 and isinstance(item[1], (int, float)):
                return item
            if len(item) == 2:
                inner = item[1]
                if isinstance(inner, (tuple, list)) and len(inner) == 2:
                    return inner
        return None, 0.0


paddle_client = PaddleOCRClient()
