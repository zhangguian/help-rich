"""盘后选股服务(v2.6)

流程(每日 15:30 自动跑):
  1. 拉候选池(沪深300+中证500 去重,~800 只)
  2. 并行批量拉今日行情 + 近 60 日 K 线
  3. 拉板块资金榜(行业,前 20 强)
  4. 计算每只 StockFeatures(主力净流入代理 + 量比 + 涨幅 + 连涨 + 板块强度)
  5. passes_filter + score_stock 排序
  6. 应用板块聚集奖励(同板块多只入榜 +5)
  7. 取 Top N 落 screener_runs + screener_picks

LLM 评选(用户主动按按钮):
  1. 取某 run_id 的 Top 20 + 各项指标 + 大盘背景
  2. 调 LLM(已严格 _parse_llm_json,失败不阻塞)
  3. 落 screener_llm_picks(每 run_id 唯一,重复请求走缓存)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime

from app.core.config import (
    SCREENER_POOL_INDEX_CODES,
    SCREENER_SCORING_VERSION,
    SCREENER_TOP_N,
)
from app.data.ifind_events import IfindUnavailable
from app.data.ifind_fundamentals import is_hit_fundamental_filter
from app.data.unified import UnifiedQuote
from app.models.orm import IndexConstituent, ScreenerPick, ScreenerRun
from app.modules.screener import repository as screener_repo
from app.services import kline_service, quote_service, sector_fund_flow_service
from app.services.event_factor_service import (
    build_event_factor_cache,
    get_event_factor_codes,
)
from app.services.industry_service import resolve_industry
from app.services.scoring import (
    StockFeatures,
    apply_sector_cluster_bonus,
    build_reason,
    event_score,
    passes_filter,
    score_stock,
)

logger = logging.getLogger(__name__)

# 并发拉取上限(800 只全市场,QPS 友好)
_QUOTE_CONCURRENCY = 32
_KLINE_CONCURRENCY = 16


# ============================================================
# 候选池
# ============================================================


async def get_pool() -> list[dict[str, str]]:
    """返回 [{stock_code, stock_name}] 去重列表"""
    rows = await screener_repo.get_constituents(SCREENER_POOL_INDEX_CODES)
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        if r.stock_code not in out:
            out[r.stock_code] = {"stock_code": r.stock_code, "stock_name": r.stock_name}
    return sorted(out.values(), key=lambda x: x["stock_code"])


# ============================================================
# 因子采集
# ============================================================


def _calc_volume_ratio(today_volume: int, recent_volumes: Sequence[int]) -> float:
    """量比 = 今日量 / 近 5 日均量(今日之前)

    recent_volumes 应按时间升序,排除今日;长度 < 5 时按现有天数算均量。
    """
    base = [v for v in recent_volumes if v]
    if not base:
        return 0.0
    avg = sum(base) / len(base)
    if avg <= 0:
        return 0.0
    return float(today_volume) / avg


def _calc_consecutive_up_days(klines: Sequence[dict]) -> int:
    """连续上涨天数(从最新一根往回数;只要 close > 前一根 close 就继续)"""
    if len(klines) < 2:
        return 0
    days = 0
    for i in range(len(klines) - 1, 0, -1):
        try:
            cur = float(klines[i]["close"])
            prev = float(klines[i - 1]["close"])
        except (KeyError, ValueError, TypeError):
            break
        if cur > prev:
            days += 1
        else:
            break
    return days


def _calc_max_drop_pct_5d(klines: Sequence[dict]) -> float:
    """近 5 日最大跌幅百分比(%,负数表示下跌)— 用于避雷过滤"""
    if len(klines) < 6:
        return 0.0
    last5 = klines[-5:]
    if not last5:
        return 0.0
    try:
        base = float(last5[0]["close"])
        cur = float(last5[-1]["close"])
    except (KeyError, ValueError, TypeError):
        return 0.0
    if base <= 0:
        return 0.0
    return float((cur / base - 1) * 100)


async def _fetch_one_quote(code: str) -> UnifiedQuote | None:
    """单只行情(失败返回 None)— 由上层并发调用"""
    from app.services.quote_service import QuoteService
    try:
        return await QuoteService().get_quote(code)
    except Exception as e:  # noqa: BLE001
        logger.debug("[screener] 行情失败 %s: %s", code, e)
        return None


async def _fetch_one_klines(code: str) -> list[dict]:
    """单只 K 线(失败返回 [])— 60 日"""
    try:
        return await kline_service.fetch_klines(code, period="daily", count=60)
    except kline_service.KLineSourceUnavailable:
        return []
    except Exception as e:  # noqa: BLE001
        logger.debug("[screener] K 线失败 %s: %s", code, e)
        return []


async def _gather_features(
    pool: list[dict[str, str]],
    sector_rank_map: dict[str, int],
    sector_inflow_yi: dict[str, float],
    sector_name_map: dict[str, str],
) -> list[tuple[StockFeatures, str | None]]:
    """并发拉行情 + K 线,组装 StockFeatures + 过滤拒绝原因"""
    codes = [p["stock_code"] for p in pool]

    sem_quote = asyncio.Semaphore(_QUOTE_CONCURRENCY)
    sem_kline = asyncio.Semaphore(_KLINE_CONCURRENCY)

    async def _q(code: str) -> UnifiedQuote | None:
        async with sem_quote:
            return await _fetch_one_quote(code)

    async def _k(code: str) -> list[dict]:
        async with sem_kline:
            return await _fetch_one_klines(code)

    quote_results, kline_results = await asyncio.gather(
        asyncio.gather(*[_q(c) for c in codes]),
        asyncio.gather(*[_k(c) for c in codes]),
    )

    out: list[tuple[StockFeatures, str | None]] = []
    for pool_item, q, ks in zip(pool, quote_results, kline_results):
        name = pool_item["stock_name"]
        if not q:
            out.append((
                StockFeatures(stock_code=pool_item["stock_code"], stock_name=name),
                "行情获取失败",
            ))
            continue
        if len(ks) < 30:
            out.append((
                StockFeatures(stock_code=pool_item["stock_code"], stock_name=name),
                f"K 线不足({len(ks)} 根,需 ≥30)",
            ))
            continue

        today_volume = q.volume
        recent_volumes = [int(k["volume"]) for k in ks[:-1]]  # 排除今日
        volume_ratio = _calc_volume_ratio(today_volume, recent_volumes)
        consecutive_up = _calc_consecutive_up_days(ks)
        max_drop_5d = _calc_max_drop_pct_5d(ks)

        sector_raw = sector_name_map.get(pool_item["stock_code"])
        if not sector_raw:
            res = await resolve_industry(pool_item["stock_code"])
            sector_raw = res.get("industry") if isinstance(res, dict) else res
        sector = sector_raw if isinstance(sector_raw, str) else None
        sector_rank = sector_rank_map.get(sector) if sector else None
        sector_yi = sector_inflow_yi.get(sector, 0.0) if sector else 0.0

        amount_yi = float(q.amount) / 1e8  # 元 → 亿元

        feat = StockFeatures(
            stock_code=pool_item["stock_code"],
            stock_name=name,
            # 主力净流入代理:用板块净流入(后续可加个股资金源)
            main_net_inflow_yi=float(sector_yi),
            volume_ratio=volume_ratio,
            change_pct=float(q.change_pct),
            turnover_yi=amount_yi,
            consecutive_up_days=consecutive_up,
            sector=sector,
            sector_inflow_rank=sector_rank,
        )

        ok, reason = passes_filter(feat, max_drop_5d)
        if not ok:
            out.append((feat, reason))
            continue
        out.append((feat, None))
    return out


def _build_sector_maps(sectors: list[dict]) -> tuple[dict[str, int], dict[str, float], dict[str, str]]:
    """拉板块资金榜 → (排名, 净流入值, 股票→板块 反查)"""
    rank_map: dict[str, int] = {}
    inflow_map: dict[str, float] = {}
    name_map: dict[str, str] = {}
    for i, s in enumerate(sectors, start=1):
        rank_map[s["name"]] = i
        inflow_map[s["name"]] = float(s.get("netamount_yi", 0))
        top = s.get("top_stock") or {}
        if top.get("code") and top.get("name"):
            name_map[top["code"]] = s["name"]
    return rank_map, inflow_map, name_map


async def _fetch_sectors_safe(num: int = 20) -> list[dict]:
    """拉行业板块资金榜(失败返回空 list,不抛)"""
    try:
        return await sector_fund_flow_service.get_sector_fund_flow(
            fenlei=1, num=num, sort="netamount"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("板块资金榜拉取失败,板块强度分将全 0: %s", e)
        return []


# ============================================================
# 只读查询(供其它域调用)
# ============================================================


async def get_latest_run() -> ScreenerRun | None:
    """最近一批选股批次(无则返回 None)

    纯转发:跨域只允许 import 本域的 service(见 tests/test_architecture_boundaries.py),
    故 repository 的两个读接口在 service 层各留一个出口。
    """
    return await screener_repo.get_latest_run()


async def get_picks_by_run(run_id: int) -> list[ScreenerPick]:
    """某批次的全部候选(按 rank 升序)"""
    return await screener_repo.get_picks_by_run(run_id)


async def get_effective_weights(refresh: bool = False):
    """当前生效的 4 因子权重(跨域出口)

    作战计划 v2 的「全市场滚动池」复用**同一套**权重与打分公式 ——
    用户在选股页调权重,池的排序也跟着变(同一套体系,两处一致)。

    跨域只允许 import 本域的 `service`(见 tests/test_architecture_boundaries.py),
    故在此开一个出口,而不是让调用方去碰 `weight_service`。
    """
    from app.modules.screener.weight_service import get_effective_weights as _get

    return await _get(refresh=refresh)


# ============================================================
# 跑批
# ============================================================


async def run_daily_pick(target_date: date | None = None) -> ScreenerRun | None:
    """每日跑批入口(可手动指定日期 — 默认今日)

    Returns:写入的 ScreenerRun(失败返回 None)
    """
    target = target_date or date.today()
    t0 = time.time()
    logger.info("[screener] 开始跑批: %s", target)
    pool = await get_pool()
    if not pool:
        logger.warning("[screener] 候选池为空,请先运行 init_index_constituents")
        return None
    logger.info("[screener] 候选池: %s 只", len(pool))

    sector_rank_map, sector_inflow_yi, sector_name_map = _build_sector_maps(
        await _fetch_sectors_safe()
    )

    features_with_reason = await _gather_features(
        pool, sector_rank_map, sector_inflow_yi, sector_name_map
    )

    # 改动 A: 先构建当日事件因子缓存 (失败 fail-fast, 不跑评分)
    try:
        await build_event_factor_cache(target)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "screener event factor unavailable today, running with 4-factor score: %s", e,
        )
        # spec §4.1: A 失败时 screener 跑无事件因子版, 不抛错

    event_codes = await get_event_factor_codes(target)

    # 阶段2:加载用户可调权重(无配置则用 config 默认常量,结果与历史一致)
    from app.modules.screener.weight_service import get_effective_weights

    weights = await get_effective_weights()

    # 评分 + 过滤
    scored: list[tuple[StockFeatures, object]] = []
    for feat, reason in features_with_reason:
        if reason is not None:
            continue
        bd = score_stock(feat, weights)
        scored.append((feat, bd))

    # 板块聚集奖励
    sector_count = Counter(f.sector for f, _ in scored if f.sector)
    for feat, bd in scored:
        if feat.sector:
            apply_sector_cluster_bonus(bd, sector_count.get(feat.sector, 0))
        # 改动 A: 叠加事件因子分
        bd.total += event_score(feat.stock_code, event_codes, set(), weights)

    # 按总分倒序
    scored.sort(key=lambda x: x[1].total, reverse=True)

    # Top N
    top = scored[:SCREENER_TOP_N]
    if not top:
        logger.warning("[screener] 无候选通过过滤(行情/K 线全失败?)")
        # 仍写一条空 run(便于前端知道跑批发生过)
        run = await screener_repo.upsert_run(
            run_date=target,
            scoring_version=SCREENER_SCORING_VERSION,
            pool_size=len(pool),
            total_picks=0,
            elapsed_sec=time.time() - t0,
            note="无候选通过过滤",
        )
        return run

    picks_payload = []
    for i, (feat, bd) in enumerate(top, start=1):
        picks_payload.append({
            "rank": i,
            "stock_code": feat.stock_code,
            "stock_name": feat.stock_name,
            "score": round(bd.total, 2),
            "main_net_inflow_yi": feat.main_net_inflow_yi or None,
            "volume_ratio": round(feat.volume_ratio, 2),
            "change_pct": round(feat.change_pct, 2),
            "turnover_proxy": round(feat.turnover_yi, 2),
            "consecutive_up_days": feat.consecutive_up_days,
            "sector": feat.sector,
            "sector_inflow_rank": feat.sector_inflow_rank,
            "triggered_rules": bd.triggered_rules,
            "reason": build_reason(feat, bd),
        })

    # 改动 B: 基本面兜底过滤 (失败 fail-fast, 不持久化不展示 — spec §6)
    try:
        top_n_picks = [_PickProxy(p) for p in picks_payload]
        await _apply_fundamental_filter(top_n_picks)
    except IfindUnavailable as e:
        logger.error("[screener] 基本面过滤失败, 不持久化 Top N: %s", e)
        return None
    for _p in top_n_picks:
        _p.commit()
    picks_payload.sort(key=lambda x: x["score"], reverse=True)
    for _i, _p in enumerate(picks_payload, start=1):
        _p["rank"] = _i

    run = await screener_repo.upsert_run(
        run_date=target,
        scoring_version=SCREENER_SCORING_VERSION,
        pool_size=len(pool),
        total_picks=len(picks_payload),
        elapsed_sec=time.time() - t0,
        note=None,
    )
    await screener_repo.replace_picks(run.id, picks_payload)
    logger.info(
        "[screener] 跑批完成: %s,候选 %s → 入库 %s, 耗时 %ss",
        target, len(pool), len(picks_payload), time.time() - t0,
    )
    return run


# ============================================================
# 后台调度(每日 15:30)
# ============================================================


async def start_screener_scheduler() -> None:
    """每日 15:30 跑一次(工作日判断 + 已有今日 run 跳过)"""
    import os as _os
    if _os.environ.get("PYTEST_CURRENT_TEST"):
        # 测试环境跳过
        return

    logger.info("选股调度器启动: 每日 15:30 跑批")
    while True:
        try:
            now = datetime.now()
            target_run = date.today()
            today_run = await screener_repo.get_run_by_date(target_run)
            if today_run is None and now.hour >= 15 and now.minute >= 30 and now.weekday() < 5:
                await run_daily_pick(target_run)
        except asyncio.CancelledError:
            logger.info("选股调度器停止")
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("选股调度器异常: %s", e)
        await asyncio.sleep(60)  # 每分钟检查一次时间窗


__all__ = [
    "get_pool",
    "run_daily_pick",
    "start_screener_scheduler",
    "add_to_watchlist",
    "remove_from_watchlist",
    "refresh_watchlist_daily",
    "compute_watchlist_summary",
]


# ============================================================
# 观察池(Watchlist)
# ============================================================


async def _fetch_marked_close(stock_code: str, marked_at) -> tuple[str | None, str | None]:
    """取标记日 close + change_pct(走 fetch_klines 直连新浪,失败 QuoteService,最后 None)

    Returns: (marked_close:str, marked_change_pct:str) — 任一失败返 (None, None)
    """
    try:
        klines = await kline_service.fetch_klines(stock_code, period="daily", count=90)
        for k in klines:
            d = k["date"]
            if hasattr(d, "isoformat"):
                d = d.isoformat()
            elif isinstance(d, str):
                d = d[:10]
            else:
                continue
            if d == marked_at.isoformat():
                return str(k["close"]), None
    except Exception as e:  # noqa: BLE001
        logger.debug("[watchlist] 拉 K 线失败 %s: %s", stock_code, e)
    # 兜底:用 QuoteService 当前 quote(精度有限)
    try:
        from app.services.quote_service import QuoteService
        q = await QuoteService().get_quote(stock_code)
        if q and q.current_price:
            return str(q.current_price), str(q.change_pct)
    except Exception as e:  # noqa: BLE001
        logger.debug("[watchlist] QuoteService 兜底失败 %s: %s", stock_code, e)
    return None, None


async def add_to_watchlist(
    stock_code: str,
    stock_name: str,
    note: str | None = None,
    marked_at=None,
) -> dict:
    """加入观察池(幂等:已存在则返 existing,不覆盖)

    Returns: {watched, watchlist_id, already_existed, marked_at, marked_close}
    """
    from app.modules.screener import repository as screener_repo
    from datetime import date as _date

    marked_at = marked_at or _date.today()
    existing = await screener_repo.get_watchlist_by_code(stock_code)
    if existing:
        return {
            "watched": True,
            "already_existed": True,
            "watchlist_id": existing.id,
            "marked_at": existing.marked_at.isoformat(),
            "marked_close": existing.marked_close,
        }
    marked_close, marked_change_pct = await _fetch_marked_close(stock_code, marked_at)
    row = await screener_repo.add_watchlist(
        stock_code=stock_code,
        stock_name=stock_name,
        marked_at=marked_at,
        marked_close=marked_close,
        marked_change_pct=marked_change_pct,
        note=note,
    )
    # 立即触发逐日记录补全(后台异步,不阻塞响应)
    if marked_close:
        try:
            await refresh_watchlist_daily(row.id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[watchlist] 立即补全 daily 失败 id=%s: %s", row.id, e)
    return {
        "watched": True,
        "already_existed": False,
        "watchlist_id": row.id,
        "marked_at": row.marked_at.isoformat(),
        "marked_close": row.marked_close,
    }


async def remove_from_watchlist(stock_code: str) -> dict:
    """取消标记"""
    from app.modules.screener import repository as screener_repo
    removed = await screener_repo.remove_watchlist(stock_code)
    return {"removed": removed}


async def refresh_watchlist_daily(watchlist_id: int) -> int:
    """补全/更新逐日 K 线记录

    Returns: 新写入行数
    """
    from app.modules.screener import repository as screener_repo

    row = None
    async with screener_repo.async_session() as session:
        from sqlalchemy import select
        from app.models.orm import ScreenerWatchlist
        stmt = select(ScreenerWatchlist).where(ScreenerWatchlist.id == watchlist_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
    if not row or not row.marked_close:
        return 0
    try:
        marked_close_f = float(row.marked_close)
    except (TypeError, ValueError):
        return 0

    try:
        klines = await kline_service.fetch_klines(
            row.stock_code, period="daily", count=60
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[watchlist] K 线拉取失败 id=%s: %s", watchlist_id, e)
        return 0

    from datetime import date as _date, datetime as _dt

    records = []
    for k in klines:
        try:
            d_str = k["date"]
            if isinstance(d_str, str):
                td = _dt.strptime(d_str[:10], "%Y-%m-%d").date()
            else:
                continue
        except (ValueError, TypeError):
            continue
        if td < row.marked_at:
            continue  # 标记日之前的 K 线不算
        try:
            close_f = float(k["close"])
        except (KeyError, ValueError, TypeError):
            continue
        pct = (close_f - marked_close_f) / marked_close_f if marked_close_f > 0 else None
        records.append({
            "trade_date": td,
            "open_price": str(k.get("open", "")),
            "high_price": str(k.get("high", "")),
            "low_price": str(k.get("low", "")),
            "close_price": str(close_f),
            "volume": int(k.get("volume", 0)),
            "pct_from_marked": f"{pct:.4f}" if pct is not None else None,
        })
    return await screener_repo.upsert_daily_records(watchlist_id, records)


async def refresh_all_watchlist_daily() -> dict:
    """遍历所有 active 观察池,刷一遍 daily(供手动调用,或每天 16:00 调度)"""
    from app.modules.screener import repository as screener_repo

    rows = await screener_repo.list_watchlist(status="active")
    added = 0
    failed = 0
    for r in rows:
        try:
            added += await refresh_watchlist_daily(r.id)
        except Exception as e:  # noqa: BLE001
            failed += 1
            logger.warning("[watchlist] daily refresh failed id=%s: %s", r.id, e)
    return {"refreshed": len(rows), "added": added, "failed": failed}


def _iso_week_label(d) -> tuple[str, str, str]:
    """date → (week_label 'YYYY-Www', week_start str, week_end str)"""
    iso = d.isocalendar()
    label = f"{iso[0]}-W{iso[1]:02d}"
    # 该周周一/周日
    from datetime import timedelta
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return label, monday.isoformat(), sunday.isoformat()


def _iso_month_label(d) -> tuple[str, str, str]:
    """date → ('YYYY-MM', first day, last day)"""
    from calendar import monthrange
    y, m = d.year, d.month
    last_day = monthrange(y, m)[1]
    from datetime import date as _date
    first = _date(y, m, 1)
    last = _date(y, m, last_day)
    return f"{y}-{m:02d}", first.isoformat(), last.isoformat()


async def compute_watchlist_summary() -> dict:
    """观察池按周/月分桶的胜率 + 汇总
    Returns:
        {
          "summary": {totalWatched, overallAvgChange, overallHitRate, refreshedAt},
          "weeks":   [{weekLabel, weekStart, weekEnd, stockCount, avgChangePct, hitCount, missCount, hitRate, stocks:[...]}],
          "months":  [{monthLabel, monthStart, monthEnd, ...same shape}]
        }
    """
    from app.modules.screener import repository as screener_repo
    from collections import defaultdict

    rows = await screener_repo.list_watchlist(status="active")
    if not rows:
        empty = {"weeks": [], "months": []}
        empty["summary"] = {
            "totalWatched": 0,
            "overallAvgChange": 0.0,
            "overallHitRate": 0.0,
            "refreshedAt": None,
        }
        return empty

    # 收集 watchlist_id → latest record(用于详情列表)
    latest_map = await screener_repo.list_latest_records([r.id for r in rows])

    # 按 (week_label, watchlist_id) 收集该股在该周的最佳(最新)记录
    week_buckets: dict[tuple[str, str], dict] = {}
    month_buckets: dict[tuple[str, str], dict] = {}
    overall_pcts: list[float] = []

    async def _bucket(rec, bucket_key, label_fn, buckets: dict):
        """把 rec 加入对应 bucket(以 trade_date 为准)"""
        if rec.pct_from_marked is None:
            return
        try:
            pct = float(rec.pct_from_marked)
        except (TypeError, ValueError):
            return
        key = (label_fn(rec.trade_date)[0], str(rec.watchlist_id))
        existing = buckets.get(key)
        if existing is None or rec.trade_date > existing["trade_date"]:
            buckets[key] = {
                "trade_date": rec.trade_date,
                "pct": pct,
                "watchlist_id": rec.watchlist_id,
            }

    for wid_obj in rows:
        records = await screener_repo.list_daily_records(wid_obj.id)
        for rec in records:
            await _bucket(rec, "", _iso_week_label, week_buckets)
            await _bucket(rec, "", _iso_month_label, month_buckets)

    def _build_period_view(buckets: dict, label_fn) -> list[dict]:
        """把 (label, watchlist_id) buckets 聚合成 {label: [records...]} → period view"""
        from collections import defaultdict as _dd
        period_map: dict[str, list[dict]] = _dd(list)
        meta_map: dict[str, tuple[str, str]] = {}
        for (label, _wid), entry in buckets.items():
            period_map[label].append(entry)
            meta_map[label] = label_fn(entry["trade_date"])[1:]  # (start, end)
        out = []
        # 按 label 倒序(最新在前)
        for label in sorted(period_map.keys(), reverse=True):
            entries = period_map[label]
            pcts = [e["pct"] for e in entries]
            avg = sum(pcts) / len(pcts) if pcts else 0.0
            hit = sum(1 for p in pcts if p > 0)
            miss = sum(1 for p in pcts if p < 0)
            hit_rate = hit / len(pcts) if pcts else 0.0
            start, end = meta_map[label]
            stocks_detail = []
            for entry in entries:
                wid_obj = next((r for r in rows if r.id == entry["watchlist_id"]), None)
                if not wid_obj:
                    continue
                # 该股在 period 内的最新记录
                rec = latest_map.get(wid_obj.id)
                stocks_detail.append({
                    "watchlist_id": wid_obj.id,
                    "stock_code": wid_obj.stock_code,
                    "stock_name": wid_obj.stock_name,
                    "marked_at": wid_obj.marked_at.isoformat(),
                    "marked_close": wid_obj.marked_close,
                    "status": wid_obj.status,
                    "latest_pct_from_marked": (
                        float(rec.pct_from_marked) if rec and rec.pct_from_marked else None
                    ),
                })
            out.append({
                "label": label,
                "start": start,
                "end": end,
                "stock_count": len(entries),
                "avg_change_pct": round(avg, 4),
                "hit_count": hit,
                "miss_count": miss,
                "hit_rate": round(hit_rate, 4),
                "stocks": stocks_detail,
            })
        return out

    weeks = _build_period_view(week_buckets, _iso_week_label)
    months = _build_period_view(month_buckets, _iso_month_label)

    # 整体平均/胜率(用所有 daily records 的最新 pct)
    overall_pcts = [
        float(rec.pct_from_marked)
        for rec in latest_map.values()
        if rec and rec.pct_from_marked is not None
    ]
    overall_avg = sum(overall_pcts) / len(overall_pcts) if overall_pcts else 0.0
    overall_hit = sum(1 for p in overall_pcts if p > 0)
    overall_hit_rate = overall_hit / len(overall_pcts) if overall_pcts else 0.0

    # 今日单日涨跌:每只股最新两条 record 的 pct_from_marked 之差
    two_latest_map = await screener_repo.list_two_latest_records(
        [r.id for r in rows]
    )
    today_changes: list[float] = []
    today_date = None
    for _wid_id, records in two_latest_map.items():
        if len(records) < 2:
            continue
        latest = records[0]
        prev = records[1]
        latest_pct = latest["pct_from_marked"]
        prev_pct = prev["pct_from_marked"]
        if not (latest_pct and prev_pct):
            continue
        try:
            today_changes.append(float(latest_pct) - float(prev_pct))
            latest_td = latest["trade_date"]
            if today_date is None or latest_td > today_date:
                today_date = latest_td
        except (TypeError, ValueError):
            continue
    today_avg = sum(today_changes) / len(today_changes) if today_changes else 0.0
    today_hit = sum(1 for c in today_changes if c > 0)
    today_miss = sum(1 for c in today_changes if c < 0)
    today_counted = len(today_changes)

    from datetime import datetime as _dt
    return {
        "summary": {
            "totalWatched": len(rows),
            "overallAvgChange": round(overall_avg, 4),
            "overallHitRate": round(overall_hit_rate, 4),
            "todayAvgChange": round(today_avg, 4),
            "todayHitCount": today_hit,
            "todayMissCount": today_miss,
            "todayCounted": today_counted,
            "todayDate": today_date.isoformat() if today_date else None,
            "refreshedAt": _dt.now().isoformat(),
        },
        "weeks": weeks,
        "months": months,
    }


# ============================================================
# 改动 B: Top N 基本面兜底过滤 (screener 落盘前 fail-fast)
# ============================================================


class _PickProxy:
    """picks_payload dict 的薄包装, 让 filter 能以 object-API (stock_code/score/
    fundamental_filter_status) 操作, 通过 commit() 把改动写回原 dict.

    只在 run_daily_pick 集成处使用, 不暴露给外部.
    """

    __slots__ = ("stock_code", "score", "fundamental_filter_status", "_p")

    def __init__(self, payload: dict) -> None:
        self._p = payload
        self.stock_code: str = payload["stock_code"]
        self.score: float = payload["score"]
        self.fundamental_filter_status: str | None = None

    def commit(self) -> None:
        self._p["score"] = self.score
        self._p["fundamental_filter_status"] = self.fundamental_filter_status


async def _apply_fundamental_filter(picks: list) -> list:
    """对 Top N 跑一次基本面兜底过滤; 任一失败直接抛 IfindUnavailable.

    行为:
    - SCREENER_FUNDAMENTAL_FILTER_ENABLED=False → 原样返
    - is_hit_fundamental_filter 返 True → fundamental_filter_status='passed', 分不变
    - 返 False → fundamental_filter_status='kicked', 扣 SCREENER_FUNDAMENTAL_KICKOUT_PENALTY
    - 任一票 ifind 调用失败 → 抛 IfindUnavailable, 不写库

    Args:
        picks: 列表, 元素需有 stock_code, score, fundamental_filter_status 属性
            (SimpleNamespace / ScreenerPick / dataclass 均可)

    Returns:
        重新排序的 picks 列表 (in-place + return)
    """
    from app.core.config import (
        SCREENER_FUNDAMENTAL_FILTER_ENABLED,
        SCREENER_FUNDAMENTAL_FILTER_QUERY,
        SCREENER_FUNDAMENTAL_KICKOUT_PENALTY,
    )
    if not SCREENER_FUNDAMENTAL_FILTER_ENABLED:
        return picks

    # 并发查 Top N
    results = await asyncio.gather(
        *[is_hit_fundamental_filter(p.stock_code, SCREENER_FUNDAMENTAL_FILTER_QUERY) for p in picks],
        return_exceptions=True,
    )
    # 任一失败 → 整体抛
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            if isinstance(r, IfindUnavailable):
                raise r
            raise IfindUnavailable(f"基本面过滤异常: {picks[i].stock_code}: {r}") from r

    for pick, hit in zip(picks, results):
        if hit:
            pick.fundamental_filter_status = "passed"
        else:
            pick.fundamental_filter_status = "kicked"
            pick.score -= SCREENER_FUNDAMENTAL_KICKOUT_PENALTY

    picks.sort(key=lambda p: p.score, reverse=True)
    return picks