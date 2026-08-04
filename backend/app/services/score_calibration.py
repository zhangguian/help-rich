"""评分样本外验证(GB-001 IR-3)

立项时诊断的"反馈环断裂"——评分只知道"录入时分数",不知道"这分数事后是否对"。
service 周期回检:对每笔买入 (action='buy') 评分,在评分后 HORIZON_DAYS 个交易日的
窗口下计算真实持有期收益,按分数段聚合,生成"分数 → 收益"校准表,作为评判评分
规则有效性的证据。

口径(GB-001 IR-3):
- 仅验证 action='buy':该评分当时认为"该笔买入操作是合理的"
- 持有期收益 = (close_t_N / close_t_0 - 1) * 100(正值=赚)
- close_t_0 = 交易当日收盘;close_t_N = 交易日后第 N 个交易日的收盘
- 分数段:0-59 / 60-79 / 80-100
- 桶内:count / avg_return / win_rate / median_return
- 样本不足(< MIN_SAMPLES)→ 该桶返回 insufficient=true,不输出结论
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select

from app.db import async_session
from app.models.orm import KlineCache, TradeScore, Transaction
from app.services.kline_service import KLineSourceUnavailable, fetch_klines


# 持有期窗口(交易日)
HORIZON_DAYS = 20
# 桶内样本下限,低于则 insufficient(不输出结论)
MIN_SAMPLES = 3
# 评分桶定义(GB-001 IR-3)
SCORE_BUCKETS: list[tuple[str, int, int]] = [
    ("0-59", 0, 59),
    ("60-79", 60, 79),
    ("80-100", 80, 100),
]


def _bucket_for(score: int) -> tuple[str, int, int]:
    """按分数映射桶定义(含 80/100 边界)"""
    for label, lo, hi in SCORE_BUCKETS:
        if lo <= score <= hi:
            return label, lo, hi
    # 容量外(评分钳位 0-100,理论上不会发生)
    return "0-59", 0, 59


def _index_to_close(klines: list[dict]) -> dict[date, str]:
    """K 线 → {trade_date: close_price} 映射(返回 string 精度保护)"""
    out: dict[date, str] = {}
    for r in klines:
        d = r.get("date")
        c = r.get("close")
        if not d or not c:
            continue
        try:
            out[date.fromisoformat(d)] = str(c)
        except ValueError:
            continue
    return out


def _pct_return(close_0: str, close_n: str) -> float:
    """持有期收益 = (close_n / close_0 - 1) * 100"""
    a = float(close_0)
    b = float(close_n)
    if a <= 0:
        return 0.0
    return (b / a - 1.0) * 100.0


async def _klines_for(stock_code: str, around: date) -> list[dict]:
    """为校准查某只股票在 [around, around + HORIZON] 区间的日 K

    复用 kline_service.fetch_klines(DB 缓存首查, miss 走新浪)。count 取
    HORIZON_DAYS + 跳过周末 buffer(共 ~30 日),避免触发 Q1 公式边界。
    """
    try:
        return await fetch_klines(stock_code, period="daily", count=HORIZON_DAYS + 10)
    except KLineSourceUnavailable:
        return []
    except Exception:  # noqa: BLE001
        return []


async def _load_scores_with_trades() -> list[dict]:
    """加载所有 buy 评分 + 关联交易(集中查询一次)"""
    async with async_session() as session:
        stmt = (
            select(TradeScore, Transaction)
            .join(Transaction, TradeScore.trade_id == Transaction.id)
            .where(Transaction.action == "buy")
        )
        rows = list((await session.execute(stmt)).all())
    out = []
    for ts, tx in rows:
        out.append({
            "trade_id": tx.id,
            "stock_code": tx.stock_code,
            "trade_date": tx.trade_date,
            "score": ts.score,
            "scored_at": ts.created_at,
        })
    return out


async def _observe_trade(
    stock_code: str,
    trade_date: date,
    horizon_days: int = HORIZON_DAYS,
) -> float | None:
    """对单笔交易,在 [trade_date, +horizon_days] 区间计算持有期收益(%)

    返回 None 表示数据不足(交易日期后窗口 K 线缺失)。
    """
    klines = await _klines_for(stock_code, trade_date)
    if not klines:
        return None
    closes = _index_to_close(klines)
    if trade_date not in closes:
        # 交易当日未收盘或缓存不足
        return None
    # 找 trade_date 之后第 N 个交易日
    future_dates = sorted(d for d in closes.keys() if d > trade_date)
    if len(future_dates) < horizon_days:
        return None
    target = future_dates[horizon_days - 1]
    return _pct_return(closes[trade_date], closes[target])


async def compute_calibration(horizon_days: int = HORIZON_DAYS) -> dict:
    """评分样本外校准(GB-001 IR-3)

    Returns:
        {
          "horizon_days": 20,
          "sample_count": int,
          "buckets": [
            {
              "label": "0-59",
              "range": [0, 59],
              "count": int,
              "insufficient": bool,
              "avg_return": float | None,
              "median_return": float | None,
              "win_rate": float | None,
            }, ...
          ],
          "calibrated": bool,        # 是否有任一桶返回完整结论
          "generated_at": ISO date,
        }
    """
    records = await _load_scores_with_trades()

    # 1. 按桶收集所有收益样本
    bucket_returns: dict[str, list[float]] = {label: [] for label, _, _ in SCORE_BUCKETS}

    for r in records:
        ret = await _observe_trade(r["stock_code"], r["trade_date"], horizon_days)
        if ret is None:
            continue
        label, _, _ = _bucket_for(r["score"])
        bucket_returns[label].append(ret)

    # 2. 计算每桶统计
    buckets_out: list[dict[str, Any]] = []
    has_calibrated = False
    for label, lo, hi in SCORE_BUCKETS:
        samples = bucket_returns[label]
        count = len(samples)
        insufficient = count < MIN_SAMPLES
        if insufficient:
            buckets_out.append({
                "label": label,
                "range": [lo, hi],
                "count": count,
                "insufficient": True,
                "avg_return": None,
                "median_return": None,
                "win_rate": None,
            })
            continue
        avg = sum(samples) / count
        med = float(median(samples))
        wins = sum(1 for s in samples if s > 0)
        win_rate = wins / count
        buckets_out.append({
            "label": label,
            "range": [lo, hi],
            "count": count,
            "insufficient": False,
            "avg_return": round(avg, 2),
            "median_return": round(med, 2),
            "win_rate": round(win_rate, 4),
        })
        has_calibrated = True

    return {
        "horizon_days": horizon_days,
        "sample_count": sum(len(s) for s in bucket_returns.values()),
        "buckets": buckets_out,
        "calibrated": has_calibrated,
        "generated_at": date.today().isoformat(),
    }


__all__ = ["compute_calibration", "HORIZON_DAYS", "MIN_SAMPLES", "SCORE_BUCKETS"]
