"""行情 API(arch §7.1 新增 /api/quotes)"""
from fastapi import APIRouter, HTTPException, Query

from app.core.stock_code import normalize_code
from app.services.quote_service import QuoteError, QuoteService

router = APIRouter(tags=["quotes"])

_quote_service: QuoteService | None = None

# 自选 + 持仓合计可能超过 50,放宽到 200;再大需要分批
MAX_CODES_PER_REQUEST = 200


def get_quote_service() -> QuoteService:
    global _quote_service
    if _quote_service is None:
        _quote_service = QuoteService()
    return _quote_service


def _normalize_codes(codes: str) -> list[str]:
    """逗号分隔 → 规范化的 [code.SH/.SZ/.BJ] 列表;非法保留原值供 422 提示"""
    raw = [c.strip() for c in codes.split(",") if c.strip()]
    if not raw:
        return []
    out: list[str] = []
    for c in raw:
        n = normalize_code(c)
        out.append(n if n is not None else c)
    return out


@router.get("/quotes/{code}")
async def get_quote(code: str):
    """单只实时行情。code 形如 600519.SH / 000001.SZ;无后缀时按前缀推断市场"""
    normalized = normalize_code(code)
    if normalized is None:
        raise HTTPException(422, "股票代码格式应为 6 位数字 + .SH/.SZ,如 600519.SH")
    try:
        quote = await get_quote_service().get_quote(normalized)
    except QuoteError:
        raise HTTPException(503, "行情源暂不可用,请稍后重试")
    return quote.model_dump(mode="json")


@router.get("/quotes")
async def get_quotes(codes: str = Query(..., description=f"逗号分隔,最多 {MAX_CODES_PER_REQUEST} 只")):
    """批量实时行情(自动给无后缀代码补市场;非法代码 422)"""
    code_list = _normalize_codes(codes)
    if not code_list:
        raise HTTPException(422, "codes 不能为空")
    if len(code_list) > MAX_CODES_PER_REQUEST:
        raise HTTPException(422, f"一次最多查询 {MAX_CODES_PER_REQUEST} 只")
    invalid = [c for c in code_list if normalize_code(c) is None]
    if invalid:
        raise HTTPException(422, f"代码格式错误: {','.join(invalid)}")
    try:
        quotes = await get_quote_service().get_quotes(code_list)
    except QuoteError:
        raise HTTPException(503, "行情源暂不可用,请稍后重试")
    return [q.model_dump(mode="json") for q in quotes]


def _is_valid_code(code: str) -> bool:
    """600519.SH / 000001.SZ / 830799.BJ(legacy;保留以备外部调用)"""
    return normalize_code(code) is not None
