"""行情 API(arch §7.1 新增 /api/quotes)

- GET /api/quotes/{code}            单只行情(带 5 分钟缓存)
- GET /api/quotes?codes=...         批量行情(带 5 分钟缓存)
- GET /api/quotes?codes=...&fresh=1 批量行情**跳过缓存**(盯盘热路径)
- GET /api/quotes/stream            SSE:盘中行情推送(3 秒快照档,ADR-0006)

⚠️ **路由顺序**:`/quotes/stream` 必须注册在 `/quotes/{code}` **之前**。
FastAPI 按注册顺序匹配(不是按字面量优先),否则 "stream" 会先被 `{code}` 吃掉
→ 422「股票代码格式应为 6 位数字」。
"""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.stock_code import normalize_code
from app.services.event_bus import event_bus
from app.services.quote_poller import (
    EVENT_QUOTE_SNAPSHOT,
    EVENT_QUOTE_UPDATE,
    get_quote_snapshot,
)
from app.services.quote_poller import poller as quote_poller
from app.services.quote_service import QuoteError, QuoteService, get_quote_service

router = APIRouter(tags=["quotes"])

# 自选 + 持仓合计可能超过 50,放宽到 200;再大需要分批
MAX_CODES_PER_REQUEST = 200

# SSE 端点的心跳间隔(秒)—— 与 event_bus 的 30s 心跳同频
SSE_HEARTBEAT_SEC = 30


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


# ============================================================
# SSE:盘中行情推送(必须注册在 /quotes/{code} 之前)
# ============================================================


@router.get("/quotes/stream")
async def quotes_stream(
    codes: str | None = Query(None, description="逗号分隔;不传 = 推全部 watchlist"),
):
    """SSE:盘中行情推送(3 秒快照档,不是逐笔 Tick —— 见 ADR-0006)

    - **首帧**:当前内存快照 `quote_snapshot`(含 stale 标记与最后更新时间)
    - **后续帧**:轮询器每轮广播的 `quote_update`
    - **过滤**:`?codes=` 只推指定代码;不传 = 全部 watchlist
    - **心跳**:30s 一条 `:heartbeat`,避免中间代理掐断长连接

    失败语义:行情源挂了 → 轮询器保留上一轮快照并标 `stale=true`,
    前端据此显示"数据可能滞后",**不会**收到编造的价格。
    """
    wanted: set[str] | None = None
    if codes:
        wanted = {c for c in _normalize_codes(codes) if normalize_code(c) is not None}

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    async def push(msg: dict) -> None:
        if msg.get("event") != EVENT_QUOTE_UPDATE:
            return
        quotes = msg.get("quotes") or []
        if wanted is not None:
            quotes = [q for q in quotes if q.get("code") in wanted]
        if not quotes:
            return
        try:
            # ⚠️ 必须把**过滤后的** quotes 放回消息再入队 ——
            # 直接 put 原 msg 会把过滤掉的票也推给客户端(过滤形同虚设)。
            queue.put_nowait({**msg, "quotes": quotes})
        except asyncio.QueueFull:
            # 队列满 = 客户端消费不过来。丢**这一帧**而不是阻塞广播:
            # 行情是易失数据,下一帧 2s 后就到;阻塞会拖垮整个广播总线。
            pass

    unsub = event_bus.subscribe_callback(push)

    async def event_stream():
        # 首帧:当前快照(可能还没有数据 → quotes 为空,前端据此显示"等待行情")
        snap = get_quote_snapshot()
        yield (
            "data: "
            + json.dumps(
                {
                    "event": EVENT_QUOTE_SNAPSHOT,
                    **snap.to_payload(),
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SEC)
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
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# REST:一次性取行情
# ============================================================


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
async def get_quotes(
    codes: str = Query(..., description=f"逗号分隔,最多 {MAX_CODES_PER_REQUEST} 只"),
    fresh: bool = Query(False, description="true=跳过 5 分钟缓存直取数据源(盯盘热路径)"),
):
    """批量实时行情(自动给无后缀代码补市场;非法代码 422)

    `fresh=1` 走 `QuoteService.get_quotes_fresh` —— **跳过缓存**。
    盯盘降级路径(前端 SSE 断了)用它按 3s 轮询,保证价格不是 5 分钟前的旧值。
    """
    code_list = _normalize_codes(codes)
    if not code_list:
        raise HTTPException(422, "codes 不能为空")
    if len(code_list) > MAX_CODES_PER_REQUEST:
        raise HTTPException(422, f"一次最多查询 {MAX_CODES_PER_REQUEST} 只")
    invalid = [c for c in code_list if normalize_code(c) is None]
    if invalid:
        raise HTTPException(422, f"代码格式错误: {','.join(invalid)}")
    service = get_quote_service()
    # 登记一次 REST 命中:轮询器据此判断"有人在看",不降到 15s 的空闲档
    quote_poller.note_rest_access()
    try:
        if fresh:
            quotes = await service.get_quotes_fresh(code_list)
        else:
            quotes = await service.get_quotes(code_list)
    except QuoteError:
        raise HTTPException(503, "行情源暂不可用,请稍后重试")
    return [q.model_dump(mode="json") for q in quotes]


def _is_valid_code(code: str) -> bool:
    """600519.SH / 000001.SZ / 830799.BJ(legacy;保留以备外部调用)"""
    return normalize_code(code) is not None


__all__ = ["router", "QuoteService"]
