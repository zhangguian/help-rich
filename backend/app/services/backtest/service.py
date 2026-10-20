"""回测用例层(阶段2)。

诚实说明:**历史信号来自已落库的 `screener_picks`**,不是用当前权重重算历史因子。
原因:选股只保存了"某日选出哪些股票",没有保存每日全市场因子矩阵;强行用
今日权重套历史会产生前视偏差(look-ahead bias),回测结果好看但不可信。

因此本服务提供两种模式:
1. **历史实盘信号回测**(默认,无偏差):把历史每日 picks 当作 buy 信号,
   按持有 N 个交易日卖出,衡量"这套选股逻辑过去表现如何"。
2. **权重对比**(前瞻性,仅供参考):对同一段历史,分别用不同权重重算评分,
   比较 Top N 组合 —— 仅用于理解权重敏感度,不能当作真实收益。

模式 2 会在返回值里显式标注 `has_lookahead_bias: true`。
"""
from __future__ import annotations

from datetime import date, timedelta

from app.core.logging import logger
from app.modules.screener import repository as screener_repo
from app.services.backtest.cost_model import CostModel
from app.services.backtest.engine import BacktestEngine
from app.modules.screener.scoring import ScoringWeights


async def _load_pick_dates(days: int) -> list[date]:
    """近 N 天里实际有选股记录的交易日(升序)。"""
    from app.db import async_session
    from app.models.orm import ScreenerRun
    from sqlalchemy import select

    since = date.today() - timedelta(days=days)
    async with async_session() as s:
        stmt = (
            select(ScreenerRun.run_date)
            .where(ScreenerRun.run_date >= since)
            .order_by(ScreenerRun.run_date)
        )
        return list((await s.execute(stmt)).scalars().all())


async def _load_picks_by_date(pick_dates: list[date]) -> dict[date, list[str]]:
    """{trade_date: [stock_code, ...]}"""
    out: dict[date, list[str]] = {}
    for d in pick_dates:
        run = await screener_repo.get_run_by_date(d)
        if run is None:
            continue
        picks = await screener_repo.get_picks_by_run(run.id)
        out[d] = [p.stock_code for p in picks]
    return out


async def _load_pick_features(pick_dates: list[date]) -> dict[date, list]:
    """{trade_date: [ScreenerPick, ...]} —— 保留因子原始值,供权重重排使用。

    `screener_picks` 表里存了 main_net_inflow_yi / volume_ratio / change_pct /
    consecutive_up_days / sector_inflow_rank,正好是 `score_stock` 的全部输入,
    所以「用不同权重重新排序当日候选」是可以真实做到的,不是伪计算。
    """
    out: dict[date, list] = {}
    for d in pick_dates:
        run = await screener_repo.get_run_by_date(d)
        if run is None:
            continue
        picks = await screener_repo.get_picks_by_run(run.id)
        if picks:
            out[d] = picks
    return out


async def _load_prices(
    codes: set[str], pick_dates: list[date], hold_days: int
) -> tuple[dict[str, dict[str, float]], list[str]]:
    """拉取覆盖 [首个选股日 - 1, 最后选股日 + hold_days] 的收盘价。

    Returns:
        (prices, trading_days) — trading_days 是所有股票日期的并集(升序)
    """
    from app.services import kline_service

    if not pick_dates or not codes:
        return {}, []

    span_days = (pick_dates[-1] - pick_dates[0]).days + hold_days + 5
    # 每只票多取一些,覆盖持有窗口
    count = min(max(span_days + 20, 120), 800)

    prices: dict[str, dict[str, float]] = {}
    all_dates: set[str] = set()
    for code in codes:
        try:
            rows = await kline_service.fetch_klines(code, period="daily", count=count)
        except Exception as e:  # noqa: BLE001 — 单只失败不中断
            logger.warning(f"[backtest] 拉 {code} K 线失败: {e}")
            continue
        series: dict[str, float] = {}
        for r in rows or []:
            d = r.get("date")
            c = r.get("close")
            if d is None or c is None:
                continue
            try:
                series[str(d)] = float(c)
            except (TypeError, ValueError):
                continue
        if series:
            prices[code] = series
            all_dates.update(series.keys())

    trading_days = sorted(all_dates)
    return prices, trading_days


async def run_signal_backtest(
    days: int = 180,
    hold_days: int = 10,
    initial_capital: float = 1_000_000.0,
    max_positions: int = 10,
    slippage_bps: float = 0.0,
) -> dict:
    """历史选股信号回测(无前视偏差)。

    规则:
    - 每个选股日买入当次 picks(最多 max_positions 只,等权)
    - 持有 hold_days 个交易日后卖出
    - 计入真实 A 股费用与滑点
    """
    pick_dates = await _load_pick_dates(days)
    if not pick_dates:
        return {
            "ok": False,
            "reason": f"近 {days} 天没有选股记录,无法回测",
            "trades": [],
            "metrics": {},
        }

    picks_by_date = await _load_picks_by_date(pick_dates)
    if not picks_by_date:
        return {
            "ok": False,
            "reason": "选股记录为空",
            "trades": [],
            "metrics": {},
        }

    codes = {c for lst in picks_by_date.values() for c in lst}
    prices, trading_days = await _load_prices(codes, pick_dates, hold_days)
    if not prices or not trading_days:
        return {
            "ok": False,
            "reason": "缺少历史 K 线数据,无法回测",
            "trades": [],
            "metrics": {},
        }

    # 把 date 对象转成回测引擎用的 ISO 字符串
    date_to_idx = {d: i for i, d in enumerate(trading_days)}
    signals: dict[str, dict[str, str]] = {}
    for d, stock_list in picks_by_date.items():
        key = d.isoformat()
        if key not in date_to_idx:
            continue  # 该日无行情(停市/数据缺口)
        for code in stock_list:
            if code not in prices:
                continue
            signals.setdefault(code, {})[key] = "buy"
            # 持有 N 个交易日后挂卖单
            sell_idx = date_to_idx[key] + hold_days
            if sell_idx < len(trading_days):
                signals[code][trading_days[sell_idx]] = "sell"

    engine = BacktestEngine(CostModel(slippage_bps=slippage_bps))
    result = engine.run(
        signals=signals,
        prices=prices,
        trading_days=trading_days,
        initial_capital=initial_capital,
        max_positions=max_positions,
    )
    payload = result.to_dict()
    payload.update(
        {
            "ok": True,
            "mode": "signal",
            "has_lookahead_bias": False,
            "config": {
                "days": days,
                "hold_days": hold_days,
                "initial_capital": initial_capital,
                "max_positions": max_positions,
                "slippage_bps": slippage_bps,
            },
            "pick_dates": len(picks_by_date),
            "stock_count": len(codes),
        }
    )
    return payload


async def compare_weights(
    weight_sets: dict[str, dict],
    days: int = 180,
    hold_days: int = 10,
    initial_capital: float = 1_000_000.0,
    max_positions: int = 10,
) -> dict:
    """多套权重在同一段历史上的对比(**含前视偏差,仅供理解敏感度**)。

    weight_sets: {"默认": {factor: weight}, "重资金": {...}}

    与早期实现的区别(重要):先前版本对每个权重集复用**同一批**历史 picks,
    导致各套权重的回测结果完全相同 —— 那种"对比"是没有信息量的。
    现在改为:用每套权重对当日候选**重新打分并重排**,取 Top `max_positions`,
    再各自回测。这样差异来自权重本身。

    仍然存在的前视偏差:候选池只有当日已入选的 Top N(不是全市场),
    且用「今天的权重偏好」回看历史。因此本接口只用于回答
    "权重变化会不会显著改变选股结果",不能当作收益预期。
    """
    from app.modules.screener.scoring import default_weights as _defaults
    from app.modules.screener.scoring import weights_from_mapping
    from app.services.scoring import StockFeatures, score_stock
    pick_dates = await _load_pick_dates(days)
    if not pick_dates:
        return {"ok": False, "reason": "没有可用历史记录"}

    features_by_date = await _load_pick_features(pick_dates)
    if not features_by_date:
        return {"ok": False, "reason": "没有可用历史记录"}

    codes = {p.stock_code for lst in features_by_date.values() for p in lst}
    prices, trading_days = await _load_prices(codes, pick_dates, hold_days)
    if not prices or not trading_days:
        return {"ok": False, "reason": "缺少历史 K 线数据"}

    date_to_idx = {d: i for i, d in enumerate(trading_days)}
    base = _defaults()
    results: dict[str, dict] = {}

    for label, wdict in weight_sets.items():
        weights = weights_from_mapping(wdict) if wdict else ScoringWeights()
        signals: dict[str, dict[str, str]] = {}
        selected_total = 0

        for d, picks in features_by_date.items():
            key = d.isoformat()
            if key not in date_to_idx:
                continue

            # 用该套权重重新打分 + 重排
            scored = []
            for p in picks:
                feats = StockFeatures(
                    stock_code=p.stock_code,
                    stock_name=p.stock_name or "",
                    main_net_inflow_yi=float(p.main_net_inflow_yi or 0.0),
                    volume_ratio=float(p.volume_ratio or 0.0),
                    change_pct=float(p.change_pct or 0.0),
                    consecutive_up_days=int(p.consecutive_up_days or 0),
                    sector=getattr(p, "sector", None),
                    sector_inflow_rank=getattr(p, "sector_inflow_rank", None),
                )
                scored.append((score_stock(feats, weights).total, p.stock_code))
            scored.sort(key=lambda x: x[0], reverse=True)
            chosen = [code for _, code in scored[:max_positions]]
            selected_total += len(chosen)

            for code in chosen:
                if code not in prices:
                    continue
                signals.setdefault(code, {})[key] = "buy"
                sell_idx = date_to_idx[key] + hold_days
                if sell_idx < len(trading_days):
                    signals[code][trading_days[sell_idx]] = "sell"

        engine = BacktestEngine()
        r = engine.run(signals, prices, trading_days, initial_capital, max_positions)
        results[label] = {
            "metrics": r.metrics,
            "max_total_weight": weights.max_total,
            "weights": weights.to_dict(),
            "selected_count": selected_total,
            "traded_symbols": len(signals),
            # 具体选了哪些票 —— 判断"权重是否敏感"必须比对集合本身,
            # 只比数量会把"A 换成 B"误判为"没变化"
            "selected_codes": sorted(set(signals)),
        }

    # 差异是否显著 —— 若各套权重选出完全相同的股票,告诉用户"权重不敏感",
    # 比让用户自己比对一堆相同数字更有用
    code_sets = {lbl: frozenset(r["selected_codes"]) for lbl, r in results.items()}
    returns = {
        lbl: (r["metrics"] or {}).get("total_return_pct", 0.0)
        for lbl, r in results.items()
    }
    distinct_holdings = len(set(code_sets.values())) > 1
    distinct_return = len({round(float(v), 4) for v in returns.values()}) > 1

    note = "历史 picks 未按新权重重排,此对比仅用于理解权重敏感度"
    if not distinct_holdings and not distinct_return:
        note = (
            "各套权重在所选区间内选出了完全相同的股票,说明权重对结果不敏感。"
            "可尝试拉长区间,或把权重差异调大。"
        )
    elif not distinct_return:
        note = "各套权重选股不同,但区间内收益恰好接近。"

    return {
        "ok": True,
        "has_lookahead_bias": True,
        "note": note,
        "weights_sensitive": distinct_holdings or distinct_return,
        "results": results,
    }


__all__ = ["compare_weights", "run_signal_backtest"]
