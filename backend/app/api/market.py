"""板块资金流 / 新浪快讯 / 大盘盯盘 API

- GET /api/sector-fund-flow?fenlei=0     板块资金排行(guide §7)
- GET /api/sector-fund-flow/events      SSE 板块异动推送(v0.4.1)
- GET /api/news/sina?page=1&page_size=20  新浪 7×24 快讯(guide §9.2)
- GET /api/market/overview              大盘盯盘总览(roadmap §3.9):
                                         三大主指 + 领涨/领跌 top3
"""
import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.services.event_bus import event_bus
from app.services.market_overview_service import (
    fetch_main_fund_flow,
    fetch_market_sentiment,
    fetch_market_sparklines,
    get_market_overview,
)
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


@router.get("/sector-fund-flow/events")
async def sector_fund_flow_events(fenlei: int | None = None):
    """SSE:订阅板块资金流异动(v0.4.1)

    后台调度器每 60s 检测一次,异动 publish `sector_fund_flow_alert`,
    客户端按 fenlei 过滤(fenlei 不传 = 全部)。
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    async def push(msg: dict):
        if msg.get("event") != "sector_fund_flow_alert":
            return
        if fenlei is not None and msg.get("fenlei") != fenlei:
            return
        await queue.put(msg)

    unsub = event_bus.subscribe_callback(
        push,
        filter_fn=lambda m: m.get("event") == "sector_fund_flow_alert",
    )

    async def event_stream():
        yield f"data: {json.dumps({'event': 'subscribed', 'kind': 'sector_fund_flow', 'fenlei': fenlei}, ensure_ascii=False)}\n\n"
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ":heartbeat\n\n"
        finally:
            await unsub()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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


@router.get("/market/overview")
async def market_overview_endpoint() -> dict:
    """大盘盯盘总览(roadmap §3.9)

    - 三大主指(上证 / 深证 / 创业板)+ 领涨/领跌各 top3
    - 全部失败 → 503(至少指数应可获取;主备源同时挂才会发生)
    - 单一部分失败:指数缺失位为 null,领涨/领跌为 []
    """
    data = await get_market_overview()
    has_any_index = any(it is not None for it in data["indexes"])
    if not has_any_index and not data["gainers"] and not data["losers"]:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "MARKET_UNAVAILABLE",
                "message": "大盘数据源暂不可用,请稍后重试",
            },
        )
    return data


@router.get("/market/index-sparks")
async def market_index_sparks_endpoint(count: int = 60) -> dict:
    """三大主指迷你趋势线(roadmap §3.9 sparkline)

    - 走新浪 K 线 JSONP,不落 KlineCache(避免与个股混表)
    - 单只失败 → 空 list,不影响其它
    - 全失败 → 503
    """
    if count < 10 or count > 200:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_COUNT", "message": "count 应在 10~200"},
        )
    data = await fetch_market_sparklines(count=count)
    if not any(data.values()):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SPARK_UNAVAILABLE",
                "message": "指数 sparkline 数据源暂不可用",
            },
        )
    return {"count": count, "sparks": data}


@router.get("/market/sentiment")
async def market_sentiment_endpoint() -> dict:
    """沪深 A 股涨跌家数 + 区间分布(roadmap §3.9 涨跌分布)

    注:样本量 ~200,反映情绪概览。
    """
    try:
        return await fetch_market_sentiment()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "SENTIMENT_UNAVAILABLE", "message": str(e)},
        ) from e


@router.get("/market/main-fund-flow")
async def market_main_fund_flow_endpoint(limit: int = 10) -> dict:
    """A 股个股主力净流入榜(roadmap §3.9 主力净流入)

    注:此为降级方案(按涨跌幅近似估算),非真实主力净额。
    """
    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_LIMIT", "message": "limit 应在 1~50"},
        )
    try:
        items = await fetch_main_fund_flow(limit=limit)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "MAIN_FUND_UNAVAILABLE", "message": str(e)},
        ) from e
    return {"limit": limit, "items": items}


__all__ = ["router"]