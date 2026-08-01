"""行情 API(arch §7.1 新增 /api/quotes)"""
from fastapi import APIRouter, HTTPException, Query

from app.services.quote_service import QuoteError, QuoteService

router = APIRouter(tags=["quotes"])

_quote_service: QuoteService | None = None


def get_quote_service() -> QuoteService:
    global _quote_service
    if _quote_service is None:
        _quote_service = QuoteService()
    return _quote_service


@router.get("/quotes/{code}")
async def get_quote(code: str):
    """单只实时行情。code 形如 600519.SH / 000001.SZ"""
    if not _is_valid_code(code):
        raise HTTPException(422, "股票代码格式应为 6 位数字 + .SH/.SZ,如 600519.SH")
    try:
        quote = await get_quote_service().get_quote(code)
    except QuoteError:
        raise HTTPException(503, "行情源暂不可用,请稍后重试")
    return quote.model_dump(mode="json")


@router.get("/quotes")
async def get_quotes(codes: str = Query(..., description="逗号分隔,最多 50 只")):
    """批量实时行情"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        raise HTTPException(422, "codes 不能为空")
    if len(code_list) > 50:
        raise HTTPException(422, "一次最多查询 50 只")
    invalid = [c for c in code_list if not _is_valid_code(c)]
    if invalid:
        raise HTTPException(422, f"代码格式错误: {','.join(invalid)}")
    try:
        quotes = await get_quote_service().get_quotes(code_list)
    except QuoteError:
        raise HTTPException(503, "行情源暂不可用,请稍后重试")
    return [q.model_dump(mode="json") for q in quotes]


def _is_valid_code(code: str) -> bool:
    """600519.SH / 000001.SZ / 830799.BJ"""
    parts = code.split(".")
    if len(parts) != 2:
        return False
    num, market = parts
    return len(num) == 6 and num.isdigit() and market in {"SH", "SZ", "BJ"}
