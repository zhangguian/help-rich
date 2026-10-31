"""找股编排(behavior_screener)

三级流水线(与作战计划 v2 同构 —— 见 docs/superpowers/specs/2026-10-25-...):

    Stage A · 快照级粗筛   全市场 5574 → 主板/非ST/成交额达标 → 候选 Top 120
    Stage B · 逐票算信号   候选拉 K线(120) + 逐日资金流(120) → 四信号判定
    Stage C · 打分排序     信号类型权重 × 新鲜度 × 强度 → 分组 + 综合排序

**为什么必须分级**:5700 只逐票拉 K 线 + 资金流不现实(实测 12 只 0.85s
→ 120 只约 7s,5700 只要 5 分钟+)。先快照级收窄,再逐票精算。

**与 screener 的口径区别**:screener 按**因子打分**排 Top 20;
本模块按 **K 线行为信号命中**分组。两页都在 NavRail「决策」组,前端必须写清区别。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.core.config import (
    BEHAVIOR_SCREENER_CANDIDATE_LIMIT,
    BEHAVIOR_SCREENER_CONCURRENCY,
    BEHAVIOR_SCREENER_FLOW_COUNT,
    BEHAVIOR_SCREENER_KLINE_COUNT,
    BEHAVIOR_SCREENER_TOP_N,
    POOL_MIN_AMOUNT_YI,
)
from app.data.market_snapshot import MarketSnapshotUnavailable, fetch_market_snapshot
from app.modules.behavior_screener import repository as repo
from app.modules.behavior_screener.logic import (
    SignalHit,
    score_hit,
    sort_hits,
)
from app.modules.stock_pool.service import UniverseStats, filter_universe
from app.services import kline_service
from app.services.behavior_fund_flow_service import (
    FundFlowUnavailable,
    align_by_date,
    fetch_flow_daily,
)
from app.services.behavior_signal_service import detect_behavior_markers

logger = logging.getLogger(__name__)


def _to_float(value: Any) -> float | None:
    """宽松转 float(接口可能给字符串);转不了 → None(**不编数字**)。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _signal_day_change_pct(
    klines: list[dict[str, Any]],
    marker: Any,
) -> float | None:
    """信号**当日**的涨跌幅(%)。

    ⚠️ **口径**:找股页把涨跌幅显示在「信号日 2026-10-30(1 天前)」旁边,
    它必须是**信号那一天**的涨跌幅。早先版本误用了全市场快照里的
    **当日(今天)**涨跌幅 —— 于是同一条记录里「+0.02%」和依据里的
    「当日涨跌 +10.00%」互相矛盾,用户无法判断哪个说的是信号当天。

    取值优先级:
    1. marker 自己的 `metrics.change_pct`(主力异动判定时用的实测值,
       与依据文字**逐字一致**);
    2. 从 K 线算(`close[i] / close[i-1] - 1`)—— 其余三类信号没有资金流
       里的涨跌字段,用 K 线算,四类口径统一。

    算不出 → None(前端显示 `-`),**不编数字**。
    """
    metrics = getattr(marker, "metrics", None) or {}
    raw = metrics.get("change_pct")
    if isinstance(raw, (int, float)):
        return round(float(raw), 2)

    ks = [k for k in (klines or []) if isinstance(k, dict)]
    target = str(getattr(marker, "date", "") or "")
    idx = next((i for i, k in enumerate(ks) if str(k.get("date") or "") == target), -1)
    if idx <= 0 or idx >= len(ks):
        return None
    prev_close = _to_float(ks[idx - 1].get("close"))
    close = _to_float(ks[idx].get("close"))
    if prev_close is None or close is None or prev_close <= 0:
        return None
    return round((close / prev_close - 1.0) * 100.0, 2)


@dataclass
class ScanResult:
    """一次找股扫描的完整结论。"""

    hits: list[SignalHit] = field(default_factory=list)
    universe: UniverseStats = field(default_factory=UniverseStats)
    candidates_considered: int = 0
    elapsed_sec: float = 0.0
    degraded: list[str] = field(default_factory=list)


async def _fetch_candidate_data(
    codes: list[str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    """并发拉候选票的 K 线 + 逐日资金流。

    Returns: `(klines_by_code, flows_by_code)`;失败的那只票对应 key 缺失
    (调用方按「无法判定」处理,不当成「没有信号」)。
    """
    if not codes:
        return {}, {}

    sem = asyncio.Semaphore(BEHAVIOR_SCREENER_CONCURRENCY)

    async def _one(code: str) -> tuple[str, list[dict], list[dict]]:
        async with sem:
            ks: list[dict[str, Any]] = []
            flows: list[dict[str, Any]] = []
            try:
                ks = list(
                    await kline_service.fetch_klines(
                        code, period="daily", count=BEHAVIOR_SCREENER_KLINE_COUNT
                    )
                    or []
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("[behavior_screener] K线失败 %s: %s", code, e)
            try:
                flows = list(
                    await fetch_flow_daily(code, count=BEHAVIOR_SCREENER_FLOW_COUNT)
                    or []
                )
            except FundFlowUnavailable as e:
                logger.debug("[behavior_screener] 资金流失败 %s: %s", code, e)
            except Exception as e:  # noqa: BLE001
                logger.debug("[behavior_screener] 资金流异常 %s: %s", code, e)
            return code, ks, flows

    results = await asyncio.gather(*[_one(c) for c in codes])
    klines_map = {code: ks for code, ks, _ in results}
    flows_map = {code: flows for code, _, flows in results}
    return klines_map, flows_map


def _pick_candidates(
    rows: list[dict[str, Any]],
    stats: UniverseStats,
    limit: int,
) -> list[dict[str, Any]]:
    """Stage A 粗筛后取候选。

    口径与作战计划 v2 同源(`filter_universe`),但**排序维度不同**:
    作战计划按成交额降序(要的是「流动性好的票」);
    找股按**当日主力资金异动强度**降序(要的是「有资金异动的票」)。
    """
    candidates, _ = filter_universe(rows, min_amount_yi=POOL_MIN_AMOUNT_YI)
    return candidates[:limit]


async def scan_market(
    run_date: date | None = None,
    *,
    candidate_limit: int = BEHAVIOR_SCREENER_CANDIDATE_LIMIT,
) -> ScanResult:
    """跑一次全市场找股扫描(不落库)。

    Returns: `ScanResult`。
    """
    t0 = time.time()
    degraded: list[str] = []

    try:
        rows = await fetch_market_snapshot()
    except MarketSnapshotUnavailable as e:
        logger.warning("[behavior_screener] 全市场快照不可用: %s", e)
        return ScanResult(
            universe=UniverseStats(),
            candidates_considered=0,
            elapsed_sec=round(time.time() - t0, 2),
            degraded=[f"全市场快照不可用: {e}"],
        )

    candidates, stats = filter_universe(rows, min_amount_yi=POOL_MIN_AMOUNT_YI)
    precands = candidates[:candidate_limit]
    if not precands:
        return ScanResult(
            universe=stats,
            candidates_considered=0,
            elapsed_sec=round(time.time() - t0, 2),
            degraded=["候选池为空"],
        )

    codes = [str(c.get("code") or "") for c in precands if c.get("code")]
    name_by_code = {
        str(c.get("code") or ""): str(c.get("name") or "") for c in precands
    }

    klines_map, flows_map = await _fetch_candidate_data(codes)

    today = run_date or date.today()
    hits: list[SignalHit] = []

    for code in codes:
        ks = klines_map.get(code) or []
        flows = flows_map.get(code) or []
        if not ks or not flows:
            continue
        flows_by_date = align_by_date(flows)
        result = detect_behavior_markers(ks, flows_by_date)
        if result.degraded:
            continue
        for marker in result.markers:
            try:
                signal_day = datetime.strptime(marker.date, "%Y-%m-%d").date()
            except ValueError:
                continue
            days_ago = max(0, (today - signal_day).days)
            score = score_hit(marker, days_ago=days_ago)
            change_pct = _signal_day_change_pct(ks, marker, )
            hits.append(
                SignalHit(
                    stock_code=code,
                    stock_name=name_by_code.get(code) or None,
                    kind=marker.kind,
                    signal_date=marker.date,
                    days_ago=days_ago,
                    reason=marker.reason,
                    metrics=marker.metrics,
                    score=score,
                    change_pct=change_pct,
                )
            )

    if not any(flows_map.get(c) for c in codes):
        degraded.append("逐日资金流全部不可用,本次无行为信号命中")

    return ScanResult(
        hits=sort_hits(hits),
        universe=stats,
        candidates_considered=len(codes),
        elapsed_sec=round(time.time() - t0, 2),
        degraded=degraded,
    )


async def run_daily_scan(
    target_date: date | None = None,
    *,
    candidate_limit: int = BEHAVIOR_SCREENER_CANDIDATE_LIMIT,
) -> tuple[Any, list[SignalHit]] | None:
    """跑批并落库(同日重复跑覆盖)。

    Returns: `(BehaviorSignalRun, hits)`;快照不可用时返回 None。
    """
    target = target_date or date.today()
    result = await scan_market(target, candidate_limit=candidate_limit)

    if not result.universe.total:
        logger.warning("[behavior_screener] 扫描失败(快照不可用),不落库")
        return None

    # 只保留分数最高的前 N 条入库
    top = result.hits[:BEHAVIOR_SCREENER_TOP_N]
    run = await repo.upsert_run(
        target,
        pool_size=result.universe.total,
        main_board_count=result.universe.main_board,
        non_st_count=result.universe.non_st,
        after_filters_count=result.universe.after_filters,
        candidates_considered=result.candidates_considered,
        total_picks=len(top),
        elapsed_sec=result.elapsed_sec,
        note="; ".join(result.degraded) if result.degraded else None,
    )

    await repo.replace_picks(
        run.id,
        [
            {
                **h.to_dict(),
                "run_date": target,
                "metrics": h.metrics,
            }
            for h in top
        ],
    )
    return run, top


def pick_to_dict(p: Any) -> dict[str, Any]:
    """ORM 行 → API dict。"""
    metrics: dict[str, Any] = {}
    if p.metrics_json:
        try:
            loaded = json.loads(p.metrics_json)
            if isinstance(loaded, dict):
                metrics = loaded
        except json.JSONDecodeError:
            metrics = {}
    from app.services.behavior_signal_service import KIND_META

    return {
        "stock_code": p.stock_code,
        "stock_name": p.stock_name,
        "kind": p.kind,
        "kind_label": KIND_META.get(p.kind, {}).get("label", p.kind),
        "signal_date": p.signal_date.isoformat() if p.signal_date else None,
        "days_ago": p.days_ago,
        "reason": p.reason,
        "metrics": metrics,
        "score": round(float(p.score or 0.0), 2),
        "change_pct": p.change_pct,
    }


def run_to_dict(r: Any) -> dict[str, Any]:
    """ORM 行 → API dict。"""
    return {
        "id": r.id,
        "run_date": r.run_date.isoformat() if r.run_date else None,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "pool_size": r.pool_size,
        "main_board_count": r.main_board_count,
        "non_st_count": r.non_st_count,
        "after_filters_count": r.after_filters_count,
        "candidates_considered": r.candidates_considered,
        "total_picks": r.total_picks,
        "elapsed_sec": r.elapsed_sec,
        "note": r.note,
    }


async def get_latest_run() -> Any:
    """最新批次(跨域出口)。"""
    return await repo.get_latest_run()


async def get_picks_by_run(run_id: int) -> list[Any]:
    """某批次的命中记录(跨域出口)。"""
    return await repo.get_picks_by_run(run_id)


__all__ = [
    "ScanResult",
    "get_latest_run",
    "get_picks_by_run",
    "pick_to_dict",
    "run_to_dict",
    "scan_market",
]
