"""一键复盘服务(v2.3)

提供单只股票在指定时间窗口内的聚合复盘:
- summarize_stock:窗口内流水 + 评分聚合 + Top 3 问题 + 派生建议
- generate_replay_comment:LLM 调,200~300 字综合评语
- get_or_generate:cache 命中(latest_tx_id 一致)→ 直接返回,否则 LLM + UPSERT
- force_replay:跳过缓存强制重算

窗口定义(交易日口径):
- 1d / 3d / 5d(=1 周) / 10d(=2 周) / 20d(=4 周) / 60d(=1 季度)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from app.core.prompts import REPLAY_SYSTEM, build_replay_user_prompt
from app.core.stock_code import normalize_code
from app.db import async_session
from app.llm.factory import provider_factory
from app.models.orm import ReplayRecord, TradeScore, Transaction
from app.repositories.llm_settings_repo import llm_settings_repo
from app.repositories.replay_record_repo import replay_record_repo
from app.repositories.watchlist_repo import watchlist_repo
from sqlalchemy import select

logger = logging.getLogger(__name__)


# 窗口档位:标签 + 自然日数(用于 trade_date 过滤;以"自然日"近似"交易日")
WINDOWS: dict[str, int] = {
    "1d": 1,
    "3d": 3,
    "5d": 7,    # 1 周 ≈ 5 交易日,但日历跨度 7 天,过滤更宽容
    "10d": 14,  # 2 周
    "20d": 28,  # 4 周
    "60d": 90,  # 1 季度
}

WINDOW_LABELS = {
    "1d": "1 日",
    "3d": "3 日",
    "5d": "1 周",
    "10d": "2 周",
    "20d": "4 周",
    "60d": "1 季度",
}

# 维度名(scorer 同款,中文直接展示)
DIMS = ["集中度", "价格合理性", "操作间隔", "市场环境", "板块热度"]

# 维度一句话解释(给小白用户)— 前端复用 tooltip
DIM_HINTS: dict[str, str] = {
    "集中度": "本次交易市值 / 总持仓市值",
    "价格合理性": "买入价相对成本偏离(追涨识别)",
    "操作间隔": "距上次同向操作天数",
    "市场环境": "大盘顺势 / 中性 / 逆势",
    "板块热度": "当日板块排名",
}


@dataclass
class ReplaySnapshot:
    """单只股票在窗口内的复盘快照(纯数据,无 LLM 评语)"""
    stock_code: str
    window: str
    window_days: int
    start_date: date
    end_date: date
    tx_count: int = 0
    buy_count: int = 0
    sell_count: int = 0
    tx_lines: list[str] = field(default_factory=list)
    score_avg: Optional[float] = None
    dimension_avg: dict = field(default_factory=dict)
    top_issues: list = field(default_factory=list)
    concentration_pct: str = "0.00"
    realized_pnl: str = "0.00"
    is_in_watchlist: bool = False
    latest_tx_id: int = 0


def window_label(window: str) -> str:
    return WINDOW_LABELS.get(window, window)


def window_to_days(window: str) -> int:
    if window not in WINDOWS:
        raise ValueError(f"未知窗口: {window},合法值: {list(WINDOWS.keys())}")
    return WINDOWS[window]


def _filter_tx_by_window(
    all_tx: list[Transaction], window_days: int, end_date: date
) -> list[Transaction]:
    """窗口过滤:trade_date >= end_date - (window_days - 1),按 (date, id) 排序"""
    if not all_tx:
        return []
    cutoff = end_date - timedelta(days=max(window_days - 1, 0))
    return [t for t in all_tx if t.trade_date >= cutoff]


async def _aggregate_scores_async(tx_ids: list[int]) -> tuple[Optional[float], dict]:
    """异步版聚合:窗口内 trade_scores → 平均分 + 5 维度均值"""
    if not tx_ids:
        return None, {}
    async with async_session() as session:
        stmt = select(TradeScore).where(TradeScore.trade_id.in_(tx_ids))
        scores = list((await session.execute(stmt)).scalars().all())
    if not scores:
        return None, {}

    avg_total = sum(s.score for s in scores) / len(scores)
    dim_sums: dict[str, int] = {d: 0 for d in DIMS}
    dim_counts: dict[str, int] = {d: 0 for d in DIMS}
    for s in scores:
        try:
            breakdown = json.loads(s.score_breakdown)
        except (ValueError, TypeError):
            continue
        for d in DIMS:
            v = breakdown.get(d)
            if isinstance(v, (int, float)):
                dim_sums[d] += int(v)
                dim_counts[d] += 1
    dim_avg = {
        d: round(dim_sums[d] / dim_counts[d], 1) if dim_counts[d] > 0 else 0.0
        for d in DIMS
    }
    return round(avg_total, 1), dim_avg


def _derive_top_issues(dimension_avg: dict) -> list:
    """按维度均值升序取前 3,附 hint"""
    if not dimension_avg:
        return []
    items = sorted(dimension_avg.items(), key=lambda kv: kv[1])
    return [
        {
            "dim": dim,
            "score": score,
            "hint": DIM_HINTS.get(dim, ""),
        }
        for dim, score in items[:3]
    ]


def _derive_suggestions(top_issues: list) -> list[str]:
    """从低分维度派生 1~2 条可执行建议(V1 静态规则,不做 LLM)"""
    rules = {
        "集中度": "单笔交易市值控制在总持仓 30% 以内,避免单一标的拖累整体",
        "价格合理性": "买入价相对成本偏离 ≥10% 时暂停,等板块回归后再开仓",
        "操作间隔": "同向操作间隔保持 ≥3 个交易日,避免情绪化连续交易",
        "市场环境": "大盘中性以下时新开仓位降低 20%",
        "板块热度": "板块排名 >10 时不追高,等待板块回暖再进入",
    }
    out = []
    for it in top_issues[:2]:
        if it["score"] <= 10 and it["dim"] in rules:
            out.append(rules[it["dim"]])
    return out or ["下次保持现有节奏,关注 5 维度均衡"]


async def summarize_stock(stock_code: str, window: str) -> ReplaySnapshot:
    """汇总单只股票在窗口内的复盘快照(纯数据,无 LLM)"""
    days = window_to_days(window)
    norm = normalize_code(stock_code) or stock_code

    today = date.today()
    start = today - timedelta(days=days - 1)

    # 1. 加载该股全部流水(窗口外的不影响 Tx 数量,但参与背景统计)
    async with async_session() as session:
        stmt = (
            select(Transaction)
            .where(Transaction.stock_code == norm)
            .order_by(Transaction.trade_date, Transaction.id)
        )
        all_tx = list((await session.execute(stmt)).scalars().all())

    in_window = _filter_tx_by_window(all_tx, days, today)
    latest_tx_id = max((t.id for t in all_tx), default=0)

    # 2. 窗口内流水汇总
    buy_count = sum(1 for t in in_window if t.action == "buy")
    sell_count = sum(1 for t in in_window if t.action == "sell")
    tx_lines = [
        f"{t.trade_date} {t.action} {t.shares}股 @¥{t.price}"
        for t in in_window
    ]

    # 3. 评分聚合(关联窗口内流水的 trade_scores)
    score_avg, dim_avg = await _aggregate_scores_async([t.id for t in in_window])

    # 4. Top 3 + 建议
    top_issues = _derive_top_issues(dim_avg)
    suggestions = _derive_suggestions(top_issues)

    # 5. 持仓占比 + 窗口内已实现盈亏
    from app.modules.portfolio.service import get_position, aggregate_positions

    pos = await get_position(norm)
    concentration_pct = "0.00"
    if pos and pos.shares > 0:
        # 简化:单股持仓占比 = 该股市值 / (所有持仓 + 窗口内交易市值)
        from app.modules.portfolio.service import get_all_positions

        all_pos = await get_all_positions()
        total_value = Decimal("0")
        for p in all_pos:
            total_value += Decimal(p.total_cost)
        # 加上窗口内 buy 流水市值
        for t in in_window:
            if t.action == "buy":
                total_value += Decimal(t.price) * t.shares
        pos_value = Decimal(pos.total_cost) + sum(
            (Decimal(t.price) * t.shares for t in in_window if t.action == "buy"),
            Decimal("0"),
        )
        if total_value > 0:
            concentration_pct = f"{float(pos_value / total_value * 100):.2f}"

    flow_pnl = aggregate_positions(in_window, strict=False, keep_zero=True)
    realized_pnl = "0.00"
    for p in flow_pnl:
        if p.stock_code == norm:
            realized_pnl = format(p.realized_pnl.quantize(Decimal("0.01")), ".2f")
            break

    # 6. 自选股状态
    in_watch = await watchlist_repo.contains(norm)

    return ReplaySnapshot(
        stock_code=norm,
        window=window,
        window_days=days,
        start_date=start,
        end_date=today,
        tx_count=len(in_window),
        buy_count=buy_count,
        sell_count=sell_count,
        tx_lines=tx_lines,
        score_avg=score_avg,
        dimension_avg=dim_avg,
        top_issues=top_issues,
        concentration_pct=concentration_pct,
        realized_pnl=realized_pnl,
        is_in_watchlist=in_watch,
        latest_tx_id=latest_tx_id,
    )


async def generate_replay_comment(snapshot: ReplaySnapshot) -> dict:
    """调 LLM 生成 200~300 字综合评语,失败/缺 Key 返回 status=failed/no_key"""
    # 维度均值序列
    dim_avg_lines = snapshot.dimension_avg
    dimension_avg = {
        d: round(dim_avg_lines.get(d, 0.0), 1) for d in DIMS
    }
    top_issues_lines = snapshot.top_issues

    user_prompt = build_replay_user_prompt(
        window_label=window_label(snapshot.window),
        tx_count=snapshot.tx_count,
        buy_count=snapshot.buy_count,
        sell_count=snapshot.sell_count,
        score_avg=f"{snapshot.score_avg:.1f}" if snapshot.score_avg is not None else "无",
        dimension_avg=dimension_avg,
        top_issues=top_issues_lines,
        concentration_pct=snapshot.concentration_pct,
        realized_pnl=snapshot.realized_pnl,
        snapshot_lines="\n".join(snapshot.tx_lines) or "窗口内无流水",
        is_in_watchlist=snapshot.is_in_watchlist,
    )

    active = (await llm_settings_repo.get_active()) or "deepseek"
    llm = await provider_factory.get(active)
    if llm is None:
        return {"ai_status": "no_key", "ai_comment": None, "ai_provider": active,
                "ai_model": None, "ai_latency_ms": None}

    t0 = time.time()
    try:
        ai_comment = await llm.chat(REPLAY_SYSTEM, user_prompt)
        latency_ms = int((time.time() - t0) * 1000)
        return {
            "ai_status": "success",
            "ai_comment": ai_comment,
            "ai_provider": active,
            "ai_model": None,
            "ai_latency_ms": latency_ms,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("replay LLM failed: %s", e)
        return {"ai_status": "failed", "ai_comment": None, "ai_provider": active,
                "ai_model": None, "ai_latency_ms": None}


async def get_or_generate(stock_code: str, window: str) -> ReplayRecord:
    """读 DB → 若 latest_tx_id 匹配最新流水 → 直接返回(避免重算);

    否则 LLM 重算 + UPSERT 写库(同窗口多次复盘 → 覆盖最新)。
    """
    norm = normalize_code(stock_code) or stock_code
    snapshot = await summarize_stock(norm, window)
    existing = await replay_record_repo.get(norm, window)

    # 缓存命中:最新流水 id 一致 + 24h 内(简单时效策略)
    if (
        existing is not None
        and existing.latest_tx_id == snapshot.latest_tx_id
        and (date.today() - existing.updated_at.date()).days < 1
    ):
        return existing

    # 重算
    ai_result = await generate_replay_comment(snapshot)
    score_avg_str = (
        format(Decimal(str(snapshot.score_avg)).quantize(Decimal("0.01")), ".2f")
        if snapshot.score_avg is not None
        else None
    )
    snapshot_dict = {
        "tx_count": snapshot.tx_count,
        "buy_count": snapshot.buy_count,
        "sell_count": snapshot.sell_count,
        "tx_lines": snapshot.tx_lines,
        "concentration_pct": snapshot.concentration_pct,
        "realized_pnl": snapshot.realized_pnl,
        "is_in_watchlist": snapshot.is_in_watchlist,
        "start_date": snapshot.start_date.isoformat(),
        "end_date": snapshot.end_date.isoformat(),
    }
    return await replay_record_repo.upsert(
        stock_code=norm,
        window=window,
        score_avg=score_avg_str,
        dimension_avg={d: float(snapshot.dimension_avg.get(d, 0.0)) for d in DIMS},
        top_issues=snapshot.top_issues,
        summary_snapshot=snapshot_dict,
        ai_comment=ai_result["ai_comment"],
        ai_status=ai_result["ai_status"],
        ai_provider=ai_result["ai_provider"],
        ai_model=ai_result["ai_model"],
        ai_latency_ms=ai_result["ai_latency_ms"],
        latest_tx_id=snapshot.latest_tx_id,
    )


async def force_replay(stock_code: str, window: str) -> ReplayRecord:
    """强制重算(跳过缓存)— 用户主动点 🔍 一键复盘"""
    norm = normalize_code(stock_code) or stock_code
    snapshot = await summarize_stock(norm, window)
    ai_result = await generate_replay_comment(snapshot)
    score_avg_str = (
        format(Decimal(str(snapshot.score_avg)).quantize(Decimal("0.01")), ".2f")
        if snapshot.score_avg is not None
        else None
    )
    snapshot_dict = {
        "tx_count": snapshot.tx_count,
        "buy_count": snapshot.buy_count,
        "sell_count": snapshot.sell_count,
        "tx_lines": snapshot.tx_lines,
        "concentration_pct": snapshot.concentration_pct,
        "realized_pnl": snapshot.realized_pnl,
        "is_in_watchlist": snapshot.is_in_watchlist,
        "start_date": snapshot.start_date.isoformat(),
        "end_date": snapshot.end_date.isoformat(),
    }
    return await replay_record_repo.upsert(
        stock_code=norm,
        window=window,
        score_avg=score_avg_str,
        dimension_avg={d: float(snapshot.dimension_avg.get(d, 0.0)) for d in DIMS},
        top_issues=snapshot.top_issues,
        summary_snapshot=snapshot_dict,
        ai_comment=ai_result["ai_comment"],
        ai_status=ai_result["ai_status"],
        ai_provider=ai_result["ai_provider"],
        ai_model=ai_result["ai_model"],
        ai_latency_ms=ai_result["ai_latency_ms"],
        latest_tx_id=snapshot.latest_tx_id,
    )


async def get_latest(stock_code: str, window: str) -> Optional[ReplayRecord]:
    """只读 DB,不调 LLM(切换窗口秒回)"""
    norm = normalize_code(stock_code) or stock_code
    return await replay_record_repo.get(norm, window)


async def list_all_for_stock(stock_code: str) -> list[ReplayRecord]:
    """列出该股所有 6 窗口的最新记录(初始化用)"""
    norm = normalize_code(stock_code) or stock_code
    return await replay_record_repo.list_by_stock(norm)


__all__ = [
    "WINDOWS",
    "WINDOW_LABELS",
    "DIMS",
    "DIM_HINTS",
    "ReplaySnapshot",
    "summarize_stock",
    "generate_replay_comment",
    "get_or_generate",
    "force_replay",
    "get_latest",
    "list_all_for_stock",
    "window_label",
    "window_to_days",
]