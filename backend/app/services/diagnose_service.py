"""诊断编排服务(backend-arch §5.3 + §11.3.5 / project-book §4.3)

score_and_notify(trade_id):
1. scorer 6 维度评分(纯函数)→ safe_write 写 trade_scores → publish trade.scored
2. 取激活 provider(可缺 Key)→ 调 LLM → 写 ai_comment → publish trade.commented
   缺 Key → ai_status=no_key + publish trade.failed

⚠️ 市场环境维度按**交易当日**的大盘涨跌幅算(不是「当下」):
   给 8 月的买入用今天的行情判「顺势/逆势」等于编数字。
"""
import logging
import time as time_mod

from app.core.db_lock import safe_write
from app.core.prompts import build_diagnose_user_prompt, build_trade_line, DIAGNOSE_SYSTEM
from app.core.scorer import score_trade
from app.llm.factory import provider_factory
from app.llm.sanitizer import sanitize_for_llm
from app.repositories.llm_settings_repo import llm_settings_repo
from app.repositories.trade_score_repo import trade_score_repo
from app.modules.portfolio.repository import transaction_repo
from app.repositories.watchlist_repo import watchlist_repo
from app.services.event_bus import event_bus
from app.services.market_overview_service import get_market_index_service
from app.modules.portfolio.service import get_all_positions, position_before_trade

logger = logging.getLogger(__name__)

# 诊断用的历史交易条数
RECENT_LIMIT = 5

# 评分"市场环境"维度参考指数(默认上证,留给后续可配置)
INDEX_BENCHMARK = "000001.SH"

# 当日涨跌幅中性分阈值(±0.3%,与 scorer.MARKET_ENV 规则一致)
INDEX_NEUTRAL_THRESHOLD = 0.3

# 取「交易当日」日 K 用的根数(覆盖约 1 年交易日,够回填历史流水)
HISTORY_KLINE_COUNT = 250

# 进程内缓存:同一批回填里,同一 (股票, 日期) / 指数只取一次
# key = (stock_code, iso_date) → {low, high, ...} 或 None
_DAY_BAR_CACHE: dict[tuple, dict | None] = {}
# key = iso_date → 当日大盘涨跌幅(%)
_INDEX_PCT_CACHE: dict[str, float] = {}


async def _fetch_index_change_pct(code: str = INDEX_BENCHMARK) -> float:
    """拉取当日大盘涨跌幅(失败降级 0.0 = 中性分)。

    复用 QuoteService,享受 5 分钟 JSON 缓存;交易上下文里 dex 边界不会
    拉取不到时(停牌/未开盘)返回 0.0,score 给中性。
    """
    try:
        quotes = await get_market_index_service().get_quotes([code])
        if not quotes:
            return 0.0
        pct = float(quotes[0].change_pct or 0.0)
        return pct
    except Exception as e:  # noqa: BLE001
        logger.warning("diagnose: 拉取指数 %s 涨跌幅失败,降级中性: %s", code, e)
        return 0.0


async def _index_bars() -> list[dict]:
    """上证指数日 K(DB 缓存优先,miss 走新浪)"""
    from app.services.kline_service import KLineSourceUnavailable, fetch_klines

    try:
        return await fetch_klines(INDEX_BENCHMARK, "daily", count=HISTORY_KLINE_COUNT)
    except (KLineSourceUnavailable, Exception) as e:  # noqa: BLE001
        logger.warning("diagnose: 拉取指数日 K 失败: %s", e)
        return []


async def _index_change_pct_for(trade_date) -> float:
    """**交易当日**的大盘涨跌幅(%)

    - trade_date >= 今天 → 实时报价(盘中用实时,收盘后与日 K 等价)
    - trade_date < 今天  → 指数日 K:该日 close 相对前一根 close
    - 取不到(停牌/缺数据/非交易日)→ 0.0(中性分,**不拿当天的值顶替**)
    """
    from datetime import date as date_cls

    today = date_cls.today()
    if trade_date is None:
        return 0.0
    if trade_date >= today:
        return await _fetch_index_change_pct()

    key = trade_date.isoformat()
    if key in _INDEX_PCT_CACHE:
        return _INDEX_PCT_CACHE[key]

    bars = await _index_bars()
    idx = None
    for i, b in enumerate(bars):
        if str(b.get("date", ""))[:10] == key:
            idx = i
            break
    pct = 0.0
    if idx is not None and idx > 0:
        try:
            close = float(bars[idx].get("close"))
            prev = float(bars[idx - 1].get("close"))
            if close > 0 and prev > 0:
                pct = (close - prev) / prev * 100.0
        except (TypeError, ValueError):
            pct = 0.0
    _INDEX_PCT_CACHE[key] = pct
    return pct


async def _day_bar_for(stock_code: str, trade_date) -> dict | None:
    """交易当日该股的日 K {open, high, low, close};取不到 → None

    给「交易时机」维的日内价格位置用。取不到时该子项按中性降级(5 分),
    **不编造**当日高低点。
    """
    if trade_date is None:
        return None
    key = (stock_code, trade_date.isoformat())
    if key in _DAY_BAR_CACHE:
        return _DAY_BAR_CACHE[key]

    from app.services.kline_service import KLineSourceUnavailable, fetch_klines

    bar: dict | None = None
    try:
        bars = await fetch_klines(stock_code, "daily", count=HISTORY_KLINE_COUNT)
        for b in bars:
            if str(b.get("date", ""))[:10] == trade_date.isoformat():
                bar = b
                break
    except (KLineSourceUnavailable, Exception) as e:  # noqa: BLE001
        logger.warning("diagnose: 拉取 %s 日 K 失败(交易时机降级): %s", stock_code, e)
        bar = None

    _DAY_BAR_CACHE[key] = bar
    return bar


def _load_context_trades(all_tx: list, target_id: int):
    """按链全序键排序,返回目标交易之前的流水

    Returns:
        (before_trades, found): 目标交易之前的流水、是否找到目标
    """
    from app.modules.portfolio.service import chain_sort_key

    ordered = sorted(
        all_tx,
        key=lambda t: chain_sort_key(
            t.trade_date, getattr(t, "trade_time", None), t.id
        ),
    )
    before: list = []
    found = False
    for tx in ordered:
        if tx.id == target_id:
            found = True
            continue
        if not found:
            before.append(tx)
    return before, found


def _resolve_model_name(llm) -> str:
    """安全解析 LLM 模型名。

    历史问题:此处曾直接 `llm.model_name`,一旦 provider client 或测试桩
    没实现该属性就抛 AttributeError,把"评语已生成"的最后一步持久化打断,
    整条 SSE 推送也丢失。改为按优先级兜底取名,取不到不影响主流程。
    """
    for attr in ("model_name", "model", "name"):
        value = getattr(llm, attr, None)
        if isinstance(value, str) and value:
            return value
    return "unknown"


class DiagnoseService:
    async def score_and_notify(self, trade_id: int, with_comment: bool = True) -> None:
        """评分 + AI 评语 + SSE 推送(后台任务,不阻塞录入)

        with_comment=False → 只算分不调 LLM(补评时省 token),ai_status 记 'scored'
        """
        # 1. 取交易
        trade = await transaction_repo.get_by_id(trade_id)
        if trade is None:
            logger.warning("diagnose: trade %s not found, skip", trade_id)
            return

        # 2. 聚合上下文(目标交易之前 / 全部)
        # 加载全部流水(供交易前状态判定;持仓视图从真实持仓表取)
        from app.db import async_session
        from app.models.orm import Transaction
        from sqlalchemy import select

        async with async_session() as session:
            stmt = select(Transaction).order_by(Transaction.trade_date, Transaction.id)
            all_tx = list((await session.execute(stmt)).scalars().all())

        before_trades, found = _load_context_trades(all_tx, trade_id)
        if not found:
            # 防御:交易不在库里(已删除等)
            before_trades = [t for t in all_tx if t.id != trade_id]

        # v0.5.0:持仓上下文从**链重放**出发
        #   position_before = 基准(base_*) + 该笔之前的链尾重放(与持仓真相同源)
        #   all_positions = 持仓表当前(集中度维度,真实持仓)
        #
        # 旧口径(已作废):position_before = 持仓行现值 − 从 0 起的流水聚合 + 交易前流水聚合
        # → 与持仓真相不同源,导入基准一旦被历史流水重复计入就会偏。
        position_before = await position_before_trade(trade.stock_code, trade_id)

        # 当前全部持仓(真实持仓表,用于集中度 + 0 数据降级)
        all_positions = await get_all_positions()

        recent_objs = before_trades[-RECENT_LIMIT:]
        recent = [
            {"action": t.action, "trade_date": t.trade_date}
            for t in recent_objs
        ]

        # 3. market_ctx(GB-001 IR-1:按**交易当日**的大盘涨跌幅,失败降级 0.0 中性)
        index_change_pct = await _index_change_pct_for(trade.trade_date)
        market_ctx = {
            "index_change_pct": index_change_pct,
            "sector_rank": None,
        }

        is_in_watchlist = await watchlist_repo.contains(trade.stock_code)

        # 激活 provider(P4.2d:写 provider 标签用,缺 Key 时降级)
        active = await llm_settings_repo.get_active()

        # 时间节点(HH:MM:SS);未知 → None(不编造)
        from app.core.trade_time import format_trade_time

        trade_time_str = format_trade_time(getattr(trade, "trade_time", None))

        trade_dict = {
            "stock_code": trade.stock_code,
            "stock_name": trade.stock_name or "",
            "action": trade.action,
            "shares": trade.shares,
            "price": trade.price,
            "trade_date": trade.trade_date,
            "trade_time": trade_time_str,
        }

        # 4. 评分(纯函数)
        #    「交易时机」维需要:交易当日该股日 K(日内价格位置)+ 时间点(时段适配)
        day_bar = await _day_bar_for(trade.stock_code, trade.trade_date)
        score_result = score_trade(
            trade_dict,
            (
                {
                    "shares": position_before.shares,
                    "avg_cost": str(position_before.avg_cost),
                    "total_cost": str(position_before.total_cost),
                }
                if position_before
                else None
            ),
            recent,
            market_ctx,
            is_in_watchlist,
            [
                {
                    "stock_code": p.stock_code,
                    "shares": p.shares,
                    "avg_cost": str(p.avg_cost),
                }
                for p in all_positions
            ],
            day_bar=day_bar,
            trade_time=getattr(trade, "trade_time", None),
        )

        import json

        breakdown_json = json.dumps(score_result["score_breakdown"], ensure_ascii=False)

        # 5. safe_write 写评分
        async def _do_upsert():
            return await trade_score_repo.upsert(
                trade_id=trade_id,
                score=score_result["score"],
                score_breakdown=breakdown_json,
                ai_provider=active,
            )

        await safe_write(_do_upsert)

        # 6. SSE 推送评分(先到,不等 LLM)
        await event_bus.publish({
            "event": "trade.scored",
            "trade_id": trade_id,
            "score": score_result["score"],
            "breakdown": score_result["score_breakdown"],
        })

        # 7. AI 评语(可失败降级)
        if not with_comment:
            # 只算分不调 LLM(补评省 token):分数已落库,评语留空
            await safe_write(
                lambda: trade_score_repo.update_ai_status(trade_id, "scored")
            )
            return

        llm = await provider_factory.get(active)

        if llm is None:
            # 缺 Key:优雅降级
            await safe_write(
                lambda: trade_score_repo.update_ai_status(trade_id, "no_key")
            )
            await event_bus.publish({
                "event": "trade.failed",
                "trade_id": trade_id,
                "reason": f"{active} 未配置 Key,请到设置页填写",
            })
            return

        # 集中度%(脱敏字段)
        concentration_pct = None
        if position_before and all_positions:
            pos_val = position_before.shares * position_before.avg_cost
            total_val = sum(p.shares * p.avg_cost for p in all_positions)
            if total_val > 0:
                concentration_pct = (pos_val / total_val) * 100

        sanitized = sanitize_for_llm(trade_dict, concentration_pct)
        trade_line = build_trade_line(sanitized)
        recent_summary = "、".join(
            f"{t.stock_code} {t.action} {t.shares}股@{t.trade_date}"
            for t in recent_objs
        ) or "无"
        user_prompt = build_diagnose_user_prompt(
            trade_line=trade_line,
            concentration_pct=sanitized["concentration_pct"],
            recent_summary=recent_summary,
            score=score_result["score"],
            breakdown=score_result["score_breakdown"],
            is_in_watchlist=is_in_watchlist,
        )

        # 8. 调 LLM(记录延迟)
        t0 = time_mod.time()
        try:
            ai_comment = await llm.chat(DIAGNOSE_SYSTEM, user_prompt)
            latency_ms = int((time_mod.time() - t0) * 1000)
        except Exception as e:  # noqa: BLE001
            logger.warning("diagnose %s: LLM failed: %s", trade_id, e)
            await safe_write(
                lambda: trade_score_repo.update_ai_status(trade_id, "failed")
            )
            await event_bus.publish({
                "event": "trade.failed",
                "trade_id": trade_id,
                "reason": str(e),
            })
            return

        # 9. safe_write 写评语
        # 模型名取不到不能影响主流程(评语已生成,这是最后一步持久化)
        model_name = _resolve_model_name(llm)

        async def _do_comment():
            return await trade_score_repo.update_ai_comment(
                trade_id,
                ai_comment,
                ai_status="success",
                ai_model=model_name,
                ai_latency_ms=latency_ms,
            )

        await safe_write(_do_comment)

        # 10. SSE 推送评语
        await event_bus.publish({
            "event": "trade.commented",
            "trade_id": trade_id,
            "comment": ai_comment,
            "provider": llm.name,
            "model": model_name,
            "latency_ms": latency_ms,
        })


async def find_backfill_candidates(
    stock_code: str | None = None,
    force: bool = False,
    limit: int = 200,
) -> list[int]:
    """补评候选流水 id 列表

    - force=False → 只取**没有评分记录**的流水
      (漏评的来源:一键清仓 / 截图导入流水 / 评分功能之前的老流水)
    - force=True  → 取全部(评分口径升级后全量重算用)

    幂等:重复执行安全(trade_scores 是 upsert)。
    """
    from app.db import async_session
    from app.models.orm import TradeScore, Transaction
    from sqlalchemy import select

    async with async_session() as session:
        stmt = select(Transaction.id).order_by(
            Transaction.trade_date, Transaction.id
        )
        if stock_code:
            stmt = stmt.where(Transaction.stock_code == stock_code)
        if not force:
            scored = select(TradeScore.trade_id)
            stmt = stmt.where(Transaction.id.notin_(scored))
        stmt = stmt.limit(limit)
        return list((await session.execute(stmt)).scalars().all())


diagnose_service = DiagnoseService()
