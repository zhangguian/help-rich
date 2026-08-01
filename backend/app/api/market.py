"""板块资金流 / 新浪快讯 API

- GET /api/sector-fund-flow?fenlei=0  板块资金排行(guide §7)
- GET /api/news/sina?page=1&page_size=20  新浪 7×24 快讯(guide §9.2)
"""
from fastapi import APIRouter, HTTPException

from app.services.news_service import get_sina_news
from app.services.sector_fund_flow_service import FENLEI_MAP, get_sector_fund_flow

router = APIRouter(tags=["market"])


@router.get("/sector-fund-flow")
async def get_sector_fund_flow_endpoint(
    fenlei: int = 0, num: int = 20, sort: str = "netamount"
) -> dict:
    """板块资金流排行(guide §7 新浪)

    fenlei: 0=全部 1=行业 2=概念 3=地域
    """
    if fenlei not in FENLEI_MAP:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_FENLEI",
                "message": f"fenlei 应为 0/1/2/3,不是 {fenlei}",
            },
        )
    if num < 1 or num > 100:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_NUM", "message": "num 应在 1~100"},
        )
    if sort not in {"netamount", "netbuy", "change"}:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_SORT", "message": "sort 必须是 netamount/netbuy/change"},
        )
    try:
        items = await get_sector_fund_flow(fenlei=fenlei, num=num, sort=sort)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "DATA_SOURCE_UNAVAILABLE", "message": str(e)},
        ) from e
    return {
        "fenlei": fenlei,
        "fenlei_label": FENLEI_MAP[fenlei],
        "count": len(items),
        "items": items,
    }


@router.get("/news/sina")
async def get_sina_news_endpoint(page: int = 1, page_size: int = 20) -> dict:
    """新浪 7×24 快讯(guide §9.2)"""
    if page < 1 or page > 100:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PAGE", "message": "page 应在 1~100"},
        )
    if page_size < 1 or page_size > 50:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PAGE_SIZE", "message": "page_size 应在 1~50"},
        )
    try:
        items = await get_sina_news(page=page, page_size=page_size)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "DATA_SOURCE_UNAVAILABLE", "message": str(e)},
        ) from e
    return {
        "page": page,
        "count": len(items),
        "items": items,
    }


__all__ = ["router"]