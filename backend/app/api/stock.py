"""个股分析 API(v0.4-roadmap 功能2/3/4/5)

- GET  /api/stock/{code}/analysis  指标 + AI 解读(LLM 失败 → ai=null 纯指标)
- GET  /api/stock/{code}/decision  确定性决策卡(零 LLM,纯算法,秒出)
- POST /api/stock/{code}/chat      操作问答(自动携带持仓成本)
- POST /api/stock/{code}/chat/stream  操作问答流式版(SSE,打字机输出)
"""
import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.kline_service import KLineSourceUnavailable, fetch_klines
from app.modules.portfolio.service import get_position
from app.services.quote_service import QuoteService
from app.services.stock_advice_service import (
    StockAdviceUnavailable,
    ask_stock_question,
    ask_stock_question_stream,
    check_llm_available,
    find_sector_context,
    get_stock_analysis,
    stream_stock_analysis,
)
from app.services.industry_service import resolve_industry, resolve_industry_sync
from app.services.decision_service import build_decision
from app.services.decision_advice_service import build_advice, build_fact_pack
from app.services.decision_context_service import load_decision_extras
from app.services.decision_runtime import (
    DecisionDataUnavailable,
    DecisionDeps,
    build_decision_payload,
)
from app.services.market_context_service import get_market_context
from app.services.position_status import (
    kline_fallback_price as _kline_fallback_price,
    resolve_position_status as _resolve_position_status,
    sanitize_current_price as _sanitize_current_price,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stock", tags=["stock"])

# v2.3:与分析上下文一致,改用 300 根(约 12 个月交易日),与 KLineChart indicators 对齐
_KLINE_COUNT = 300


class ChatRequest(BaseModel):
    question: str
    stock_name: str | None = None
    # 多轮上下文(前端从 IndexedDB 缓存):[{role: user|ai, text}]
    history: list[dict[str, str]] | None = None


def _is_valid_code(code: str) -> bool:
    """600519.SH / 000001.SZ / 830799.BJ"""
    parts = code.split(".")
    if len(parts) != 2:
        return False
    num, market = parts
    return len(num) == 6 and num.isdigit() and market in {"SH", "SZ", "BJ"}


async def _load_klines(code: str, count: int = _KLINE_COUNT) -> list[dict]:
    try:
        return await fetch_klines(code, period="daily", count=count)
    except KLineSourceUnavailable as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "DATA_SOURCE_UNAVAILABLE", "message": str(e)},
        ) from e


async def _load_quote(code: str):
    """拉取实时行情(失败返回 None,不阻断分析)"""
    try:
        qs = await QuoteService().get_quotes([code])
        return qs[0] if qs else None
    except Exception as e:  # noqa: BLE001
        logger.warning("analysis 拉取行情失败(%s): %s", code, e)
        return None


async def _position_cost(code: str) -> float | None:
    """持仓成本(chat / chat/stream 共用)"""
    position = await get_position(code)
    return float(position.avg_cost) if position is not None else None


async def _check_code(code: str) -> None:
    if not _is_valid_code(code):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_STOCK_CODE", "message": "代码格式应为 6 位数字 + .SH/.SZ"},
        )


def _check_question(question: str) -> str:
    q = question.strip()
    if not q:
        raise HTTPException(
            status_code=422,
            detail={"code": "EMPTY_QUESTION", "message": "问题不能为空"},
        )
    return q


def _decision_deps() -> DecisionDeps:
    """决策装配依赖 —— 注入**本模块**的可 patch 点。

    装配逻辑本体已下沉到 `app/services/decision_runtime.py`(盘中信号模块要复用同源口径),
    但既有测试 patch 的是 `app.api.stock.fetch_klines` / `get_position` /
    `get_market_context` / `load_decision_extras` / `build_decision`。
    这里在**调用时**读取模块属性,保证这些 patch 依旧生效,测试无需改写。
    """
    return DecisionDeps(
        fetch_klines=fetch_klines,
        get_position=get_position,
        get_market_context=get_market_context,
        load_decision_extras=load_decision_extras,
        build_decision=build_decision,
    )


async def _compute_decision(
    code: str,
    klines: list[dict] | None = None,
    quote=None,
    _provided: bool = False,
    include_env: bool = True,
) -> dict:
    """装配决策上下文并算出决策(零 LLM)。

    装配本体在 `app/services/decision_runtime.py`;本函数只做**api 层适配**:
    1. 按 `_provided` 决定是否自行取 K 线 / 行情;
    2. 把 service 层的 `DecisionDataUnavailable` 翻译成 HTTP 502。

    `/decision` 与 `/decision-advice` 共用这一条路径 → 两处口径必然一致。
    盘中信号模块也走同一条 runtime → 决策卡与桌面信号**口径 100% 同源**。

    ⚠️ `_provided=True` 表示「klines/quote 已由调用方给出」—— 即使 quote 为 None
    (拿不到报价)也不重复拉取。否则 analysis 端点会多打一次 K 线接口。
    ⚠️ `include_env=False` 表示**不取市场环境**(analysis 端点用):
    市场环境是 4~5 次外部 HTTP,带进来会让 analysis 端点平白多打一轮网络。
    事实包只用确定性数字(价位/止损/仓位/网格),不需要市场环境;
    「大盘普跌时不要加仓」这条全局规则由决策卡自己承担。
    """
    if not _provided:
        klines, quote = await asyncio.gather(
            _load_klines(code),
            _load_quote(code),
        )
    try:
        return await build_decision_payload(
            code,
            klines=klines,
            quote=quote,
            include_env=include_env,
            need_extras=True,
            # `_provided=True` → 报价已由调用方给过,即便为 None 也不重复拉取
            quote_is_final=_provided,
            deps=_decision_deps(),
        )
    except DecisionDataUnavailable as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "DATA_SOURCE_UNAVAILABLE", "message": str(e)},
        ) from e


async def _build_fact_pack(
    code: str,
    klines: list[dict],
    quote,
    latest_kline_date: str | None,
) -> dict | None:
    """决策事实包(供 analysis 提示词注入)。

    决策算不出来时返回 None —— **不得让事实包拖垮分析端点**:
    analysis 有自己的降级链(纯指标),事实包只是让数字同源的增强。
    """
    try:
        result = await _compute_decision(
            code, klines=klines, quote=quote, _provided=True, include_env=False
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("生成决策事实包失败(%s,降级为无事实包): %s", code, e)
        return None
    return build_fact_pack(result["decision"], as_of=latest_kline_date)


@router.get("/{code}/decision")
async def decision(code: str) -> dict:
    """确定性决策卡(零 LLM):现在该做什么 + 价位 + 触发条件 + 止损 + 别动清单

    与 /analysis 的分工:
    - /decision  **纯算法**,秒出、无费用、无 LLM 依赖,回答「该买/该卖/做T/走势/市场情况」
    - /analysis  LLM 白话解读(可选),是 /decision 的解释层

    任何一个数据源失败都只降级对应项(字段为 null + data_quality.degraded),
    只有 K 线完全不可用才返回 502。
    """
    await _check_code(code)
    result = await _compute_decision(code)
    return {"decision": result["decision"]}


@router.get("/{code}/decision-advice")
async def decision_advice(code: str) -> dict:
    """操作建议白话(v0.10):把决策事实包翻译成大白话。

    **显式触发**(前端按钮),不在决策卡首屏自动烧 token。
    LLM 不可用 / 超时 → 自动退回规则文案,仍返回 200,卡片永不空白。
    """
    await _check_code(code)
    result = await _compute_decision(code)
    payload = await build_advice(
        code,
        result["decision"],
        use_llm=True,
        as_of=result["latest_kline_date"],
    )
    return payload


@router.get("/{code}/analysis")
async def analysis(code: str, force: bool = False) -> dict:
    """指标 + AI 解读;AI 不可用自动降级纯指标(200 返回,ai=null)

    v2.3:返回 current_price(实时盘中) + latest_kline_date(K线最新日),前端可据此:
    - 区分盘中/盘后/历史日
    - 用 latest_kline_date 做缓存失效键(同 replay_records 思路)

    current_price 与 K 线最新 close 偏差 > 10% 视为数据源异常,降级为 None(避免 LLM
    基于陈旧/异常报价给出错误解读)。

    v2.5:返回 position_status / cost_basis_pct — 基于用户当前持仓判断 role,
    AI 按 role 输出对应角色的单段操作参考(建仓参考 / 止盈参考 / 解套参考)。

    v2.5.3:节点缓存命中 — daily_analyses 当日行 + ai_json 非空 → 直接返回(from_cache=true),
    免重复调 LLM。节点代表日 == K 线最新日(与"昨日 19:00 ~ 今日 19:00"窗口等价)。
    ?force=true 跳过缓存,强制重算 LLM(用户主动「重试」场景)。
    """
    await _check_code(code)
    klines, quote = await asyncio.gather(
        _load_klines(code),
        _load_quote(code),
    )
    current_price, current_price_date = _sanitize_current_price(quote, klines)
    position = await get_position(code)
    position_status, cost_basis_pct = _resolve_position_status(
        position, current_price, _kline_fallback_price(klines)
    )
    latest_kline_date = klines[-1]["date"] if klines else None

    # v0.10 口径统一:把决策事实包注入 AI 提示词(数字与决策卡同源)。
    # 复用本端点已取到的 klines/quote,不重复拉行情。
    fact_pack = await _build_fact_pack(code, klines, quote, latest_kline_date)

    # 行业标签(纯本地表,零网络开销):
    #   股票 → baostock 行业名;ETF → 「跟踪{指数}」(ETF 不在个股行业表里)
    ind = resolve_industry_sync(code)

    # v2.5.3:节点缓存命中(仅当 force=false 且 K 线日期有效)
    if not force and latest_kline_date:
        from app.services.daily_analysis_service import get_cached_analysis
        cached = await get_cached_analysis(code, latest_kline_date)
        if cached is not None:
            # 注入本次实时的 current_price / quote_change_pct / position 字段
            cached["latest_kline_date"] = latest_kline_date
            cached["current_price"] = current_price
            cached["industry"] = ind.get("industry")
            cached["industry_source"] = ind.get("source")
            cached["industry_note"] = ind.get("note")
            cached["quote_change_pct"] = (
                float(quote.change_pct)
                if quote is not None and quote.change_pct is not None
                else None
            )
            cached["position_status"] = position_status
            cached["cost_basis_pct"] = cost_basis_pct
            cached["from_cache"] = True
            # 同步 ai 子对象角色 — 防止 position 变化后旧 LLM 文案与新角色不一致
            if isinstance(cached.get("ai"), dict):
                cached["ai"]["positionStatus"] = position_status
                cached["ai"]["adviceRole"] = {
                    "empty": "建仓参考",
                    "profit": "止盈参考",
                    "loss": "解套参考",
                }[position_status]
                if position_status == "empty":
                    advice = cached["ai"].get("advice") or {}
                    if isinstance(advice, dict):
                        advice["tStrategy"] = None
                        cached["ai"]["advice"] = advice
            return cached

    result = await get_stock_analysis(
        code, klines,
        current_price=current_price,
        position=position,
        position_status=position_status,
        fact_pack=fact_pack,
    )
    result["latest_kline_date"] = latest_kline_date
    result["current_price"] = current_price
    result["industry"] = ind.get("industry")
    result["industry_source"] = ind.get("source")
    result["industry_note"] = ind.get("note")
    result["quote_change_pct"] = (
        float(quote.change_pct) if quote is not None and quote.change_pct is not None else None
    )
    result["position_status"] = position_status
    result["cost_basis_pct"] = cost_basis_pct
    result["from_cache"] = False
    # 仅 ai_source=="live"(本次 LLM 真成功)才落库;None / 其他都不覆盖今日行
    if result.get("ai") is not None and result.get("ai_source") == "live":
        from app.services.daily_analysis_service import save_from_analysis_result
        await save_from_analysis_result(code, klines, result)
    return result


@router.get("/{code}/industry")
async def industry(code: str) -> dict:
    """M2.1 行业归属(三级兜底:离线表→新浪排行→降级提示)"""
    await _check_code(code)
    return await resolve_industry(code)


async def _sse_event(payload: dict) -> bytes:
    """SSE 单事件编码:data: <json>\\n\\n"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


@router.get("/{code}/analysis/stream")
async def analysis_stream(code: str, force: bool = False) -> StreamingResponse:
    """流式个股分析(v2.5.4):SSE 输出 indicators/cache/ai 进度/done 事件。

    ?force=true 跳过节点缓存,强制重算 LLM(与同步 /analysis 同语义)。

    事件序列见 stock_advice_service.stream_stock_analysis 注释。
    旧 /analysis 同步端点保留(diagnose 等内部调用)。
    """
    await _check_code(code)
    klines, quote = await asyncio.gather(
        _load_klines(code),
        _load_quote(code),
    )
    current_price, _ = _sanitize_current_price(quote, klines)
    position = await get_position(code)
    position_status, _ = _resolve_position_status(
        position, current_price, _kline_fallback_price(klines)
    )

    # v0.10 口径统一:流式分析同样注入决策事实包
    latest_kline_date = klines[-1]["date"] if klines else None
    fact_pack = await _build_fact_pack(code, klines, quote, latest_kline_date)

    async def gen():
        try:
            async for evt in stream_stock_analysis(
                code, klines,
                current_price=current_price,
                position=position,
                position_status=position_status,
                force=force,
                fact_pack=fact_pack,
            ):
                yield await _sse_event(evt)
        except asyncio.CancelledError:
            logger.info("analysis_stream 客户端断开(code=%s)", code)
            raise

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/{code}/chat")
async def chat(code: str, payload: ChatRequest) -> dict:
    """操作问答:结合行情 + 指标 + 持仓成本 + 实时报价"""
    await _check_code(code)
    question = _check_question(payload.question)

    klines, quote = await asyncio.gather(
        _load_klines(code),
        _load_quote(code),
    )
    cost, sector = await asyncio.gather(
        _position_cost(code), find_sector_context(code)
    )
    # 偏差 > 10% 视为数据源异常,降级
    current_price, current_price_date = _sanitize_current_price(quote, klines)

    try:
        answer = await ask_stock_question(
            code,
            question,
            klines,
            position_cost=cost,
            stock_name=payload.stock_name,
            sector=sector,
            history=payload.history,
            current_price=current_price,
            current_price_date=current_price_date,
        )
    except StockAdviceUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail={"code": "LLM_UNAVAILABLE", "message": str(e)},
        ) from e
    return {
        "stock_code": code,
        "answer": answer,
        "current_price": current_price,
        "current_price_date": current_price_date,
    }


@router.post("/{code}/chat/stream")
async def chat_stream(code: str, payload: ChatRequest) -> StreamingResponse:
    """操作问答流式版(SSE):data: {"text": ...} 增量,结束时 data: {"done": true}

    流中途失败发 data: {"error": "..."} 后断开;未配置 Key 直接 503。
    """
    await _check_code(code)
    question = _check_question(payload.question)

    # 前置校验:LLM 未配置在流开始前抛 503(流中途失败才走 SSE error 事件)
    try:
        await check_llm_available()
    except StockAdviceUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail={"code": "LLM_UNAVAILABLE", "message": str(e)},
        ) from e

    klines, quote = await asyncio.gather(
        _load_klines(code),
        _load_quote(code),
    )
    cost, sector = await asyncio.gather(
        _position_cost(code), find_sector_context(code)
    )
    current_price, current_price_date = _sanitize_current_price(quote, klines)

    async def gen():
        try:
            async for piece in ask_stock_question_stream(
                code,
                question,
                klines,
                position_cost=cost,
                stock_name=payload.stock_name,
                sector=sector,
                history=payload.history,
                current_price=current_price,
                current_price_date=current_price_date,
            ):
                yield f"data: {json.dumps({'text': piece}, ensure_ascii=False)}\n\n"
        except StockAdviceUnavailable as e:
            logger.warning("流式问答失败(%s): %s", code, e)
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            return
        yield 'data: {"done": true}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")


__all__ = ["router"]
