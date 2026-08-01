"""OCR 文本 → 结构化字段(backend-arch §9.7.7 / P8.3)

同花顺 App 截图布局的行扫描 + 正则:
- 持仓页:  代码 + 名称 + 股数 + 成本价 + 市值
- 流水页:  日期 + 代码 + 名称 + 买/卖 + 股数 + 价格
- 自选股页:代码 + 名称

返回 {screenshot_type, items, confidence, notes}
"""
import re

CODE_RE = re.compile(r"\b\d{6}\b")
STOCK_NAME_RE = re.compile(r"[\u4e00-\u9fa5A-Z]{2,6}")
DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
NUM_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
ACTION_MAP = {"买": "buy", "卖": "sell", "买入": "buy", "卖出": "sell", "买 入": "buy", "卖 出": "sell"}


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _to_int(s: str) -> int | None:
    f = _to_float(s)
    return int(f) if f is not None and f.is_integer() else None


def _find_action(line: str) -> str | None:
    for key, val in ACTION_MAP.items():
        if key in line:
            return val
    return None


def _detect_type(lines: list[str]) -> str:
    """根据首行/整体判断截图类型"""
    for line in lines:
        if "持仓" in line or "总资产" in line or "参考市值" in line:
            return "position"
        if "交易记录" in line or "成交" in line or "买入" in line or "卖出" in line:
            return "transactions"
        if "自选" in line:
            return "watchlist"
    return "position"  # 默认


def _parse_position_line(line: str, code: str) -> dict | None:
    """代码 + 名称 + 股数 + 成本价 + 市值(顺序固定,允许缺尾项)"""
    rest = line[line.find(code) + len(code):]
    nums = NUM_RE.findall(rest)
    if not nums:
        return None
    shares = _to_int(nums[0])
    if shares is None:
        return None
    name_m = STOCK_NAME_RE.match(rest.lstrip(" \t"))
    item: dict = {
        "stock_code": code,
        "stock_name": name_m.group() if name_m else "",
        "shares": shares,
        "cost_price": nums[1] if len(nums) > 1 else None,
        "market_value": nums[-1] if len(nums) >= 3 else None,
    }
    return item


def _parse_transaction_line(line: str, code: str) -> dict | None:
    """日期 + 代码 + 名称 + 买/卖 + 股数 + 价格"""
    action = _find_action(line)
    if action is None:
        return None
    nums = NUM_RE.findall(line)
    if len(nums) < 2:
        return None
    shares = _to_int(nums[0])
    if shares is None:
        return None
    date_m = DATE_RE.search(line)
    name_m = STOCK_NAME_RE.search(line)
    return {
        "stock_code": code,
        "stock_name": name_m.group() if name_m else "",
        "action": action,
        "shares": shares,
        "price": nums[1] if len(nums) > 1 else None,
        "trade_date": f"{date_m.group(1)}-{int(date_m.group(2)):02d}-{int(date_m.group(3)):02d}"
        if date_m else None,
    }


def _parse_watchlist_line(line: str, code: str) -> dict | None:
    name_m = STOCK_NAME_RE.search(line)
    return {
        "stock_code": code,
        "stock_name": name_m.group() if name_m else "",
    }


def extract_items(ocr_text: str) -> dict:
    """OCR 文本 → {screenshot_type, items, confidence, notes}

    confidence: 0.0~1.0(可解析行占比,低则前端标红)
    """
    lines = [l.strip() for l in ocr_text.splitlines() if l.strip()]
    if not lines:
        return {"screenshot_type": None, "items": [], "confidence": 0.0, "notes": "OCR 无文本"}

    screenshot_type = _detect_type(lines)
    parser = {
        "position": _parse_position_line,
        "transactions": _parse_transaction_line,
        "watchlist": _parse_watchlist_line,
    }[screenshot_type]

    items: list[dict] = []
    for line in lines:
        code_m = CODE_RE.search(line)
        if not code_m:
            continue
        item = parser(line, code_m.group())
        if item:
            items.append(item)

    # 去掉只有代码没名称的疑似表头行
    items = [i for i in items if i.get("stock_name")]
    confidence = len(items) / max(len(lines), 1)
    notes = "" if items else "未能从截图识别出有效记录,可尝试粘贴 JSON 降级"
    return {
        "screenshot_type": screenshot_type,
        "items": items,
        "confidence": round(confidence, 2),
        "notes": notes,
    }
