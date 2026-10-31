"""全市场选股与滚动池编排(作战计划 v2)

三级流水线(为什么要切三级 —— 见 docs/superpowers/specs):

    Stage A · 快照级粗筛   5568 只 → 主板/非ST/成交额达标 → 按成交额取前 80
    Stage B · 4 因子精排   80 只拉 K 线 → 次新剔除 → 量比/动能/板块因子 → 打分排序
    Stage C · 决策级       最终 scope(自选 + 池)才跑决策引擎(在 battle_plan_service)

**为什么不能直接对全市场跑决策引擎**:决策引擎每只票要 190 根 K 线 + 指标 + 决策,
现有 11 只就要 15~25 秒;5568 只在 60 秒内绝无可能。

**为什么 Stage B 只取 80 只**:Stage B 的成本是「拉 K 线」(80 只 × 并发 16 ≈ 2~3 秒);
排序只需要一个足够好的候选集,不需要全市场都打分。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import (
    POOL_LIMIT,
    POOL_MISS_THRESHOLD,
    POOL_MIN_AMOUNT_YI,
    POOL_NEW_LISTING_TRADING_DAYS,
    POOL_PRECANDIDATE_LIMIT,
    POOL_RANK_KLINE_CONCURRENCY,
    POOL_RANK_KLINE_COUNT,
)
from app.data.market_snapshot import MarketSnapshotUnavailable, fetch_market_snapshot
from app.data.sector_constituents import (
    SectorMembersUnavailable,
    fetch_sector_members,
)
from app.modules.stock_pool.pool_logic import (
    Candidate,
    PoolDecision,
    PoolMember,
    UniverseStats,
    calc_consecutive_up_days,
    calc_max_drop_pct_5d,
    calc_volume_ratio,
    filter_universe,
    is_new_listing,
    select_pool,
)
from app.modules.stock_pool.repository import stock_pool_repo
from app.services import kline_service
from app.services.scoring import (
    StockFeatures,
    build_reason,
    passes_filter,
    score_stock,
)
from app.services.sector_fund_flow_service import get_sector_fund_flow

logger = logging.getLogger(__name__)

# 申万行业板块资金榜的板块分类(fenlei=2)
# ⚠️ **不是 1**:fenlei=1 是「概念板块」(gn_*),fenlei=2 才是「行业板块」(hangye_*)。
# 计划书里写的 fenlei=1 来自接口注释("1=行业"),实测与注释不符 ——
# 用概念板块会导致「一只票属于十几个板块」,还要额外裁决「取哪条主线」;
# 申万一级行业是 1:1,语义干净且成分股总量≈全市场,可全天复用。
_SECTOR_FENLEI = 2
_SECTOR_FETCH_NUM = 40
# 只有排名 ≤ 20 的板块才可能拿到「板块强度」分(见 scoring._score_sector_strength),
# 排名更靠后的板块本来就不给分 → 只拉前 20 个板块的成分股即可。
_SECTOR_MEMBERS_TOP = 20
# K 线少于这个根数 → 指标不可靠,跳过(沿用 screener 的既有规则)
_MIN_KLINES = 30


@dataclass
class PoolBuildResult:
    """一次选池的结果"""

    decision: PoolDecision
    universe: UniverseStats = field(default_factory=UniverseStats)
    timings: dict[str, float] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


@dataclass
class _SectorContext:
    """板块上下文:节点 → (名称, 排名, 净流入亿元) + 股票 → 节点"""

    name_by_node: dict[str, str]
    rank_by_node: dict[str, int]
    inflow_by_node: dict[str, float]
    node_by_code: dict[str, str]


async def _load_sector_context(degraded: list[str]) -> _SectorContext:
    """拉申万行业资金榜 + 行业成分股(股票 → 行业)

    ⚠️ **这里必须用与资金榜同源的分类**:
    项目离线表 `industry_map.json` 是**证监会行业分类**(J66货币金融服务…),
    与申万行业(hangye_*)名称永不相交 → 用它查资金榜永远查不到,
    「主力净流入」「板块强度」两个因子会恒为 0 分。
    """
    name_by_node: dict[str, str] = {}
    rank_by_node: dict[str, int] = {}
    inflow_by_node: dict[str, float] = {}

    try:
        sectors = await get_sector_fund_flow(
            fenlei=_SECTOR_FENLEI, num=_SECTOR_FETCH_NUM, sort="netamount"
        )
    except Exception as e:  # noqa: BLE001
        degraded.append(f"申万行业资金流不可用,板块资金与板块强度因子记 0 分: {e}")
        return _SectorContext({}, {}, {}, {})

    for i, s in enumerate(sectors or [], start=1):
        node = str(s.get("category") or "")
        if not node:
            continue
        name_by_node[node] = str(s.get("name") or "")
        rank_by_node[node] = i
        inflow_by_node[node] = float(s.get("netamount_yi") or 0.0)

    top_nodes = [
        str(s.get("category") or "")
        for s in (sectors or [])[:_SECTOR_MEMBERS_TOP]
        if s.get("category")
    ]
    node_by_code: dict[str, str] = {}
    if top_nodes:
        try:
            node_by_code = await fetch_sector_members(top_nodes)
        except SectorMembersUnavailable as e:
            degraded.append(f"申万行业成分股不可用,板块资金与板块强度因子记 0 分: {e}")

    return _SectorContext(name_by_node, rank_by_node, inflow_by_node, node_by_code)


async def _fetch_klines(
    codes: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """并发拉 K 线(失败返回空列表,由调用方按「无法判定」处理)"""
    if not codes:
        return {}
    sem = asyncio.Semaphore(POOL_RANK_KLINE_CONCURRENCY)

    async def _one(code: str) -> tuple[str, list[dict[str, Any]]]:
        async with sem:
            try:
                ks = await kline_service.fetch_klines(
                    code, period="daily", count=POOL_RANK_KLINE_COUNT
                )
                return code, list(ks or [])
            except Exception as e:  # noqa: BLE001
                logger.debug("[stock_pool] K线失败 %s: %s", code, e)
                return code, []

    results = await asyncio.gather(*[_one(c) for c in codes])
    return dict(results)


async def _rank_candidates(
    rows: list[dict[str, Any]],
    degraded: list[str],
) -> tuple[list[Candidate], UniverseStats, list[str]]:
    """Stage A + Stage B:从全市场快照里挑出并排序候选

    Returns: `(候选列表(按分降序), universe 统计, 跳过说明)`
    """
    # ---- Stage A · 快照级粗筛 ----
    candidates, stats = filter_universe(rows, min_amount_yi=POOL_MIN_AMOUNT_YI)
    precands = candidates[:POOL_PRECANDIDATE_LIMIT]
    skipped: list[str] = []
    if not precands:
        return [], stats, skipped

    # ---- 板块上下文 ----
    sector_ctx = await _load_sector_context(degraded)

    # ---- Stage B · K 线 + 4 因子打分 ----
    klines_map = await _fetch_klines([str(c.get("code") or "") for c in precands])

    # 权重与选股页共用一套(用户在选股页调权重 → 池的排序跟着变)
    weights = None
    try:
        from app.modules.screener.service import get_effective_weights

        weights = await get_effective_weights()
    except Exception as e:  # noqa: BLE001
        logger.warning("[stock_pool] 读取选股权重失败,回落到默认权重: %s", e)

    out: list[Candidate] = []
    for row in precands:
        code = str(row.get("code") or "")
        if not code:
            continue
        ks = klines_map.get(code) or []
        if not ks:
            skipped.append(f"{code} K线不可用,已跳过")
            continue
        if is_new_listing(len(ks), POOL_NEW_LISTING_TRADING_DAYS):
            skipped.append(f"{code} 次新股(上市不足 {POOL_NEW_LISTING_TRADING_DAYS} 个交易日),已跳过")
            continue
        if len(ks) < _MIN_KLINES:
            skipped.append(f"{code} K线不足({len(ks)} 根,需 ≥{_MIN_KLINES}),已跳过")
            continue

        node = sector_ctx.node_by_code.get(code)
        sector_name = sector_ctx.name_by_node.get(node) if node else None
        features = StockFeatures(
            stock_code=code,
            stock_name=str(row.get("name") or "") or None,
            # 主力净流入代理:用**所属板块**的净流入(个股资金流数据源不可得)
            main_net_inflow_yi=float(sector_ctx.inflow_by_node.get(node, 0.0)) if node else 0.0,
            volume_ratio=calc_volume_ratio(ks),
            change_pct=float(row.get("change_pct") or 0.0),
            turnover_yi=float(row.get("amount_yi") or 0.0),
            consecutive_up_days=calc_consecutive_up_days(ks),
            sector=sector_name,
            sector_inflow_rank=sector_ctx.rank_by_node.get(node) if node else None,
        )
        max_drop_5d = calc_max_drop_pct_5d(ks)
        ok, reason = passes_filter(features, max_drop_5d)
        if not ok:
            skipped.append(f"{code} {reason},已跳过")
            continue
        bd = score_stock(features, weights)
        out.append(
            Candidate(
                stock_code=code,
                stock_name=str(row.get("name") or "") or None,
                score=float(bd.total),
                reason=build_reason(features, bd),
            )
        )

    out.sort(key=lambda c: (-c.score, c.stock_code))
    return out, stats, skipped


async def _load_pool_state() -> list[PoolMember]:
    """读池成员状态(失败返回空池,不阻断生成)"""
    try:
        rows = await stock_pool_repo.list_members(active_only=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("[stock_pool] 读取滚动池状态失败,按空池处理: %s", e)
        return []
    return [
        PoolMember(
            stock_code=str(r.get("stock_code") or ""),
            stock_name=r.get("stock_name"),
            miss_streak=int(r.get("miss_streak") or 0),
            last_evaluated_on=r.get("last_evaluated_on"),
            last_status=r.get("last_status"),
            last_score=r.get("last_score"),
            joined_on=str(r.get("joined_on") or ""),
        )
        for r in rows
        if r.get("stock_code")
    ]


async def build_market_pool(
    prev_fulfillment: dict[str, str] | None,
    watchlist_codes: set[str] | None,
    evaluated_on: str,
    degraded: list[str],
) -> PoolBuildResult:
    """构建全市场滚动池(**编排层** —— 唯一做 IO 的地方)

    `prev_fulfillment` = 昨日各票的兑现状态(code → executed/touched/missed/n_a/no_data)
    `watchlist_codes` = 自选(持仓 ∪ ★关注)的代码集合 —— 自选单独覆盖,不占池席位
    `evaluated_on` = 本次判定的基准日(幂等键:同一天重复生成不重复累计连续天数)

    降级:快照不可用 → 池保持原样(已有成员仍留在池里),只覆盖自选票,并如实披露。
    """
    timings: dict[str, float] = {}
    skipped: list[str] = []

    # ---- Stage A/B:候选榜 ----
    t0 = time.monotonic()
    candidates: list[Candidate] = []
    stats = UniverseStats()
    try:
        rows = await fetch_market_snapshot()
        candidates, stats, skipped = await _rank_candidates(rows, degraded)
    except MarketSnapshotUnavailable as e:
        degraded.append(f"全市场快照不可用,本次全市场滚动池无新候选: {e}")
    except Exception as e:  # noqa: BLE001
        degraded.append(f"全市场选股失败,本次全市场滚动池无新候选: {e}")
    timings["select_stage"] = round(time.monotonic() - t0, 2)

    # ---- 池记忆:更新计数 → 剔除 → 占席 → 补位 ----
    t1 = time.monotonic()
    pool_state = await _load_pool_state()
    decision = select_pool(
        pool_state=pool_state,
        prev_fulfillment=prev_fulfillment,
        ranked_candidates=candidates,
        watchlist_codes=watchlist_codes,
        limit=POOL_LIMIT,
        miss_threshold=POOL_MISS_THRESHOLD,
        evaluated_on=evaluated_on,
    )
    timings["select_pool"] = round(time.monotonic() - t1, 2)

    if decision.degraded_reason:
        degraded.extend(decision.degraded_reason)

    # ---- 落库池状态 ----
    if decision.members:
        try:
            await stock_pool_repo.upsert_members(decision.members)
        except Exception as e:  # noqa: BLE001
            degraded.append(f"滚动池状态落库失败,本次池记忆未持久化: {e}")

    return PoolBuildResult(
        decision=decision,
        universe=stats,
        timings=timings,
        skipped=skipped,
    )


async def get_current_pool() -> list[dict[str, Any]]:
    """当前在池成员(给 `/scope` 出参用)

    读的是 `battle_plan_pool` 表 —— **不是**「今天会选出什么」,而是「池里现在是谁」。
    """
    rows = await _load_pool_state()
    return [
        {
            "stock_code": m.stock_code,
            "stock_name": m.stock_name,
            "miss_streak": m.miss_streak,
            "last_status": m.last_status,
            "last_score": m.last_score,
            "joined_on": m.joined_on,
        }
        for m in rows
    ]


async def get_universe_stats() -> dict[str, Any] | None:
    """当前 universe 口径统计(只跑快照级过滤,不跑打分)

    给空态页面显示「本次能从多少只里选」。快照不可用 → 返回 None(前端如实显示
    「universe 暂不可用」,不编数字)。
    """
    try:
        rows = await fetch_market_snapshot()
    except MarketSnapshotUnavailable:
        return None
    _, stats = filter_universe(rows, min_amount_yi=POOL_MIN_AMOUNT_YI)
    return stats.to_dict()


__all__ = [
    "PoolBuildResult",
    "UniverseStats",
    "build_market_pool",
    "filter_universe",
    "get_current_pool",
    "get_universe_stats",
]
