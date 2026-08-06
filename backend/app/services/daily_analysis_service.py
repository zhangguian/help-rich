"""每日 AI 分析 service(v2.4 一键复盘演进)

- save_from_analysis_result:从 /analysis 端点结果 UPSERT 入库
- list_history:列出某股票最近 N 天的分析
- 失败不阻断主流程(返回 None)
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from app.core.stock_code import normalize_code
from app.repositories.daily_analysis_repo import daily_analysis_repo

logger = logging.getLogger(__name__)


def _to_decimal_str(v: Any) -> Optional[str]:
    """Decimal-as-string 精度保护(无法转换时返回 None)"""
    if v is None:
        return None
    try:
        return str(Decimal(str(v)).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError, TypeError):
        return None


async def save_from_analysis_result(
    stock_code: str,
    klines: list[dict[str, Any]],
    result: dict[str, Any],
) -> Optional[int]:
    """从 analysis 端点结果 UPSERT 入 daily_analyses

    analysis_date = K 线最新交易日(fallback result.latest_kline_date ?? today)
    失败不抛,仅 log
    """
    try:
        norm = normalize_code(stock_code) or stock_code
        # 优先用 result.latest_kline_date(后端已明确);fallback klines 末尾
        latest = result.get("latest_kline_date")
        if not latest and klines:
            latest = klines[-1].get("date")
        if not latest:
            latest = date.today().isoformat()
        analysis_date = datetime.fromisoformat(latest).date()

        # indicators / ai 字段
        indicators = result.get("indicators") or {}
        score_avg = _to_decimal_str(indicators.get("latest_close"))
        dimension_avg: dict[str, float] = {}
        top_issues: list[dict] = []
        ai = result.get("ai") or {}
        ai_view = ai.get("view") if ai else None
        # v2.5:advice 改结构化 dict;旧 ai_summary 兼容存 rationale 单字符串
        ai_advice = ai.get("advice") if ai else None
        if isinstance(ai_advice, dict):
            ai_summary = ai_advice.get("rationale") or ""
            ai_advice_json = json.dumps(ai_advice, ensure_ascii=False)
        elif isinstance(ai_advice, str):
            ai_summary = ai_advice
            ai_advice_json = None
        else:
            ai_summary = None
            ai_advice_json = None
        # 关联流水概要(供历史查看)
        summary_snapshot = result.get("summary_snapshot") or {}
        current_price = _to_decimal_str(result.get("current_price"))

        row = await daily_analysis_repo.upsert(
            stock_code=norm,
            analysis_date=analysis_date,
            score_avg=score_avg,
            dimension_avg=dimension_avg,
            top_issues=top_issues,
            ai_view=ai_view,
            ai_summary=ai_summary,
            ai_advice_json=ai_advice_json,
            current_price=current_price,
            latest_kline_date=analysis_date,
        )
        logger.info(
            "daily_analysis upsert: %s %s view=%s score=%s",
            norm, analysis_date, ai_view, score_avg,
        )
        return row.id
    except Exception as e:  # noqa: BLE001
        logger.warning("daily_analysis upsert 失败(%s): %s", stock_code, e)
        return None


async def list_history(
    stock_code: str, days: int = 30, horizon_days: int = 20
) -> list[dict[str, Any]]:
    """列历史(转 dict 数组,按日期倒序)

    每条带 actual_change_pct:N 天后相对 analysis_date 的涨跌幅(%)
    - null:分析当日 K 线缺失 / N 天后 K 线不足 / 非 bullish/bearish
    - 供前端"历史查看 + N 天后涨跌"展示
    """
    norm = normalize_code(stock_code) or stock_code
    rows = await daily_analysis_repo.list_by_stock(norm, limit=days)
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _row_to_dict(r)
        # 计算 N 天后涨跌(复用 _observe_view_outcome)
        change_pct: str | None = None
        outcome: str | None = None
        if r.ai_view and r.analysis_date:
            res = await _observe_view_outcome(
                norm, r.analysis_date, r.ai_view, horizon_days
            )
            if res is not None:
                outcome_kind, change_pct = res
                outcome = outcome_kind
        d["actual_change_pct"] = change_pct
        d["outcome"] = outcome  # 'hit' / 'miss' / null
        out.append(d)
    return out


def _row_to_dict(r) -> dict[str, Any]:
    """ORM row → API dict(供前端展示)"""
    import json as _json
    try:
        dim = _json.loads(r.dimension_avg)
    except (ValueError, TypeError):
        dim = {}
    try:
        issues = _json.loads(r.top_issues)
    except (ValueError, TypeError):
        issues = []
    return {
        "stock_code": r.stock_code,
        "analysis_date": r.analysis_date.isoformat() if r.analysis_date else None,
        "score_avg": r.score_avg,
        "dimension_avg": dim,
        "top_issues": issues,
        "ai_view": r.ai_view,
        "ai_summary": r.ai_summary,
        "current_price": r.current_price,
        "latest_kline_date": r.latest_kline_date.isoformat() if r.latest_kline_date else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


__all__ = ["save_from_analysis_result", "list_history", "compute_view_winrate"]


# ============================================================
# P1:分析方向胜率(view vs N 天后真实涨跌)
# ============================================================


# 胜率最小样本数,低于则 insufficient
WINRATE_MIN_SAMPLES = 3

# 胜率结果内存缓存(避免切窗口/刷新页面重复计算)
# - key: (stock_code, days, horizon_days)
# - 命中前提:TTL 内直接返回;uvicorn 单进程共享
# - 真正延迟源是 fetch_klines 的 stale 强拉(>1 天),不是聚合本身
WINRATE_CACHE_TTL_SECONDS = 300  # 5 分钟
_winrate_cache: dict[tuple[str, int, int], tuple[dict, float]] = {}


def clear_winrate_cache() -> None:
    """清空胜率缓存(测试隔离用)"""
    _winrate_cache.clear()


async def _observe_view_outcome(
    stock_code: str,
    analysis_date: date,
    ai_view: str,
    horizon_days: int = 20,
) -> tuple[str, str] | None:
    """对一条 daily_analysis,观测 N 天后实际涨跌,判定是否命中

    Returns:
        (outcome, change_pct)
        outcome: 'hit' / 'miss' / 'skipped'(neutral 或数据不足)
    """
    # neutral 不计入胜率分母
    if ai_view not in ("bullish", "bearish"):
        return None

    try:
        from app.services.kline_service import KLineSourceUnavailable, fetch_klines

        # 取 analysis_date 之后的 N 个交易日 K 线;count 多取一些留 buffer
        klines = await fetch_klines(stock_code, period="daily", count=horizon_days + 15)
    except KLineSourceUnavailable:
        return None
    except Exception:  # noqa: BLE001
        return None

    if not klines:
        return None

    # 索引: trade_date → close
    closes_by_date: dict[date, str] = {}
    for r in klines:
        d_str = r.get("date")
        c = r.get("close")
        if not d_str or not c:
            continue
        try:
            closes_by_date[date.fromisoformat(d_str)] = str(c)
        except ValueError:
            continue

    if analysis_date not in closes_by_date:
        return None  # analysis 当日 K 线缺失
    close_t0 = closes_by_date[analysis_date]

    # 找 analysis_date 后第 N 个交易日
    future_dates = sorted(d for d in closes_by_date if d > analysis_date)
    if len(future_dates) < horizon_days:
        return None  # 数据不足
    target_date = future_dates[horizon_days - 1]
    close_t_n = closes_by_date[target_date]

    # 计算涨跌幅
    try:
        a = float(close_t0)
        b = float(close_t_n)
    except (ValueError, TypeError):
        return None
    if a <= 0:
        return None
    change_pct = (b / a - 1.0) * 100.0
    went_up = change_pct > 0

    # 判定命中
    if ai_view == "bullish" and went_up:
        return ("hit", f"{change_pct:+.2f}")
    if ai_view == "bearish" and not went_up:
        return ("hit", f"{change_pct:+.2f}")
    return ("miss", f"{change_pct:+.2f}")


async def compute_view_winrate(
    stock_code: str,
    days: int = 60,
    horizon_days: int = 20,
) -> dict:
    """计算某只股票 AI 分析方向胜率(view vs N 天后涨跌)

    - 结果按 (stock, days, horizon) 内存缓存 5 分钟,避免重复计算
    - simulate_return_pct:同向模拟累计简单收益率(%)
      每条可评估信号等权 1 单位:bullish 按收盘做多 / bearish 按收盘做空,
      N 天后平仓;neutral 及数据不足不参与;样本 < MIN 时为 None

    Returns:
        {
          "stock_code": str,
          "days": int,
          "horizon_days": int,
          "samples": int,           # 总样本数(只算 bullish/bearish)
          "bullish": { "total": N, "hits": M, "winrate": float|null },
          "bearish": { "total": N, "hits": M, "winrate": float|null },
          "overall_accuracy": float|null,
          "insufficient": bool,     # 总样本 < WINRATE_MIN_SAMPLES
          "simulate_return_pct": float|null,  # 同向模拟累计收益率(%)
          "generated_at": ISO date,
        }
    """
    norm = normalize_code(stock_code) or stock_code
    key = (norm, days, horizon_days)
    now = time.time()
    cached = _winrate_cache.get(key)
    if cached is not None and now - cached[1] < WINRATE_CACHE_TTL_SECONDS:
        return cached[0]

    # 拉最近 N 天 daily_analysis(取的范围比 days 略大,确保够 horizon_days 后还有数据)
    # 简单实现:拉 days * 1.5,实际只看 <= today - horizon_days 的可评估项
    from datetime import timedelta

    end = date.today()
    start = end - timedelta(days=days)
    rows = await daily_analysis_repo.list_range(norm, start, end)

    # 聚合
    bullish_total = 0
    bullish_hits = 0
    bearish_total = 0
    bearish_hits = 0
    skipped = 0
    simulate_sum = 0.0
    simulate_count = 0

    for row in rows:
        if not row.ai_view or not row.analysis_date:
            continue
        outcome = await _observe_view_outcome(
            norm, row.analysis_date, row.ai_view, horizon_days
        )
        if outcome is None:
            skipped += 1
            continue
        outcome_kind, change_pct = outcome
        # 同向模拟:等权 1 单位/条,bullish 做多 / bearish 做空
        try:
            c = float(change_pct)
        except (ValueError, TypeError):
            c = None
        if c is not None:
            simulate_count += 1
            if row.ai_view == "bullish":
                simulate_sum += c
            elif row.ai_view == "bearish":
                simulate_sum -= c
        if row.ai_view == "bullish":
            bullish_total += 1
            if outcome_kind == "hit":
                bullish_hits += 1
        elif row.ai_view == "bearish":
            bearish_total += 1
            if outcome_kind == "hit":
                bearish_hits += 1

    samples = bullish_total + bearish_total
    insufficient = samples < WINRATE_MIN_SAMPLES

    def _ratio(hits: int, total: int) -> float | None:
        if total == 0:
            return None
        return round(hits / total, 4)

    total_hits = bullish_hits + bearish_hits
    # insufficient 时 overall_accuracy 给 None,避免样本少时的误导性结论
    overall_accuracy = _ratio(total_hits, samples) if samples >= WINRATE_MIN_SAMPLES else None
    # 各方向 winrate 也只在样本 >= WINRATE_MIN_SAMPLES 时给具体数字,否则 None
    bullish_winrate = (
        _ratio(bullish_hits, bullish_total) if bullish_total >= WINRATE_MIN_SAMPLES else None
    )
    bearish_winrate = (
        _ratio(bearish_hits, bearish_total) if bearish_total >= WINRATE_MIN_SAMPLES else None
    )

    simulate_return_pct = (
        round(simulate_sum, 2) if simulate_count >= WINRATE_MIN_SAMPLES else None
    )

    result = {
        "stock_code": norm,
        "days": days,
        "horizon_days": horizon_days,
        "samples": samples,
        "skipped": skipped,
        "bullish": {
            "total": bullish_total,
            "hits": bullish_hits,
            "winrate": bullish_winrate,
        },
        "bearish": {
            "total": bearish_total,
            "hits": bearish_hits,
            "winrate": bearish_winrate,
        },
        "overall_accuracy": overall_accuracy,
        "insufficient": insufficient,
        "simulate_return_pct": simulate_return_pct,
        "generated_at": date.today().isoformat(),
    }
    _winrate_cache[key] = (result, now)
    return result