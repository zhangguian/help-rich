"""作战计划编排层测试(外部 IO 全部 mock)"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models.orm import BattlePlan
from app.repositories.battle_plan_repo import battle_plan_repo
from app.services import battle_plan_service as svc


def _stock(code="001896.SZ", name="豫能控股", price=9.92, shares=600, avg_cost=15.578):
    return {
        "stock_code": code, "stock_name": name, "in_position": True,
        "is_favorite": False, "shares": shares, "avg_cost": avg_cost,
        "current_price": price,
    }


@pytest.mark.asyncio
async def test_resolve_scope_merges_positions_and_favorites(monkeypatch):
    async def _pos():
        return [_stock("001896.SZ"), _stock("000807.SZ", "云铝股份", 24.93, 100, 8.977)]
    async def _fav():
        return [{"stock_code": "001896.SZ", "stock_name": "豫能控股"},
                {"stock_code": "300394.SZ", "stock_name": "天孚通信"}]
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    scope = await svc.resolve_target_stocks()
    codes = {s["stock_code"] for s in scope}
    assert codes == {"001896.SZ", "000807.SZ", "300394.SZ"}
    by_code = {s["stock_code"]: s for s in scope}
    assert by_code["001896.SZ"]["in_position"] is True
    assert by_code["001896.SZ"]["is_favorite"] is True
    assert by_code["300394.SZ"]["in_position"] is False


@pytest.mark.asyncio
async def test_resolve_scope_merges_without_truncating(monkeypatch):
    """resolve_target_stocks 只做**合并去重**,不做上限截断。

    为什么:截断与「是否真的截断」这个标志必须由同一处产出。
    若这里先切一刀,build_plan 里再切一次就永远切不动(len 恰好 == MAX_SCOPE),
    meta["truncated"] 恒为 False —— 等于向用户谎称「一只票都没砍掉」。
    """
    async def _pos():
        return [_stock(f"00000{i}.SZ", f"票{i}", 10.0, 100, 9.0) for i in range(25)]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)
    scope = await svc.resolve_target_stocks()
    assert len(scope) == 25
    # 截断标志必须精确:只有真的砍掉了票才为 True
    cut, truncated = svc._truncate_scope(scope)
    assert len(cut) == svc.MAX_SCOPE
    assert truncated is True
    _exact, not_truncated = svc._truncate_scope(
        [_stock(f"00000{i}.SZ") for i in range(svc.MAX_SCOPE)]
    )
    assert not_truncated is False


@pytest.mark.asyncio
async def test_build_plan_degrades_when_one_stock_fails(monkeypatch):
    async def _pos():
        return [_stock("001896.SZ"), _stock("000807.SZ", "云铝股份", 24.93, 100, 8.977)]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    async def _one(code, *a, **kw):
        if code == "000807.SZ":
            raise RuntimeError("K 线不可用")
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]
    monkeypatch.setattr(svc, "fetch_klines", _one)

    def _ind(klines):
        """⚠️ `compute_indicators` 是**同步**函数(ta_service.py: `def compute_indicators`),
        这里必须用同步 mock —— 写成 async 会让 indicators 变成协程对象,
        build_decision 访问 ctx.indicators.xxx 时炸 AttributeError。"""
        return {"latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
                "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": 8.26,
                             "support_price": 8.5, "risk_band": "mid"},
                "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
                "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
                "stabilize": {"state": False, "price": None}, "signal": {"score": 50}}
    monkeypatch.setattr(svc, "compute_indicators", _ind)

    async def _quote(codes):
        return []
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    async def _sent():
        return {"up_total": 50, "down_total": 50}
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    async def _txns(*a, **kw):
        return [], True   # F4: (流水列表, 是否读取成功)
    monkeypatch.setattr(svc, "_load_transactions", _txns)

    async def _save(*a, **kw):
        return 1
    monkeypatch.setattr(svc, "_persist", _save)

    plan = await svc.build_plan(date(2026, 10, 21))
    codes = {i["stock_code"] for i in plan["items"]}
    assert "000807.SZ" not in codes
    assert plan["meta"]["degraded"] is True
    assert any("000807.SZ" in r for r in plan["meta"]["degraded_reason"])


@pytest.mark.asyncio
async def test_build_plan_returns_three_sections(monkeypatch):
    async def _pos():
        return [_stock()]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)
    async def _k(code, *a, **kw):
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]
    monkeypatch.setattr(svc, "fetch_klines", _k)
    def _ind(klines):
        """⚠️ `compute_indicators` 是**同步**函数(ta_service.py: `def compute_indicators`),
        这里必须用同步 mock —— 写成 async 会让 indicators 变成协程对象,
        build_decision 访问 ctx.indicators.xxx 时炸 AttributeError。"""
        return {"latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
                "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": 8.26,
                             "support_price": 8.5, "risk_band": "mid"},
                "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
                "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
                "stabilize": {"state": False, "price": None}, "signal": {"score": 50}}
    monkeypatch.setattr(svc, "compute_indicators", _ind)
    async def _quote(codes):
        return []
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    async def _sent():
        return {"up_total": 60, "down_total": 40}
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    async def _txns(*a, **kw):
        return [], True   # F4: (流水列表, 是否读取成功)
    monkeypatch.setattr(svc, "_load_transactions", _txns)
    async def _save(*a, **kw):
        return 1
    monkeypatch.setattr(svc, "_persist", _save)

    plan = await svc.build_plan(date(2026, 10, 21))
    assert {"plan_date", "outlook", "review", "items", "meta"} <= set(plan)
    assert plan["outlook"]["stance"] in ("bullish", "bearish", "neutral", "unknown")
    assert len(plan["outlook"]["dims"]) == 4
    assert plan["meta"]["scope_count"] >= 1


@pytest.mark.asyncio
async def test_build_plan_puts_now_actions_into_review_pending_todos(monkeypatch):
    """status=="now" 的动作必须进 review.pending_todos(今日未执行待办)

    这是 spec §4.4.2 三路分流的核心:now 不进明日预案,只进复盘待办。
    mock 让止损位(9.95)高于现价(9.9)→ 决策引擎产出 status=="now" 的 stop 动作。
    """
    async def _pos():
        return [_stock()]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    async def _k(code, *a, **kw):
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]
    monkeypatch.setattr(svc, "fetch_klines", _k)

    def _ind(klines):
        """⚠️ `compute_indicators` 是**同步**函数(ta_service.py: `def compute_indicators`),
        这里必须用同步 mock —— 写成 async 会让 indicators 变成协程对象,
        build_decision 访问 ctx.indicators.xxx 时炸 AttributeError。"""
        return {"latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
                "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": 9.95,
                             "support_price": 8.5, "risk_band": "mid"},
                "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
                "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
                "stabilize": {"state": False, "price": None}, "signal": {"score": 50}}
    monkeypatch.setattr(svc, "compute_indicators", _ind)

    async def _quote(codes):
        return []
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    async def _sent():
        return {"up_total": 50, "down_total": 50}
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    async def _txns(*a, **kw):
        return [], True   # F4: (流水列表, 是否读取成功)
    monkeypatch.setattr(svc, "_load_transactions", _txns)
    async def _save(*a, **kw):
        return 1
    monkeypatch.setattr(svc, "_persist", _save)

    plan = await svc.build_plan(date(2026, 10, 21))
    todos = plan["review"]["pending_todos"]
    assert len(todos) >= 1
    assert todos[0]["stock_code"] == "001896.SZ"
    assert todos[0]["label"]
    # now 动作不得出现在明日预案里
    assert all(i["status_now"] != "now" for i in plan["items"])


@pytest.mark.asyncio
async def test_build_plan_meta_truncated_flag_is_true_when_scope_exceeds_max(monkeypatch):
    """端到端:股票池超上限时 meta["truncated"] 必须为 True —— 不许谎称没砍票"""
    async def _pos():
        return [_stock(f"00000{i}.SZ", f"票{i}", 10.0, 100, 9.0) for i in range(25)]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    async def _k(code, *a, **kw):
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]
    monkeypatch.setattr(svc, "fetch_klines", _k)

    def _ind(klines):
        return {"latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
                "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": 8.26,
                             "support_price": 8.5, "risk_band": "mid"},
                "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
                "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
                "stabilize": {"state": False, "price": None}, "signal": {"score": 50}}
    monkeypatch.setattr(svc, "compute_indicators", _ind)

    async def _quote(codes):
        return []
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    async def _sent():
        return {"up_total": 50, "down_total": 50}
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    async def _txns(*a, **kw):
        return [], True   # F4: (流水列表, 是否读取成功)
    monkeypatch.setattr(svc, "_load_transactions", _txns)
    async def _save(*a, **kw):
        return 1
    monkeypatch.setattr(svc, "_persist", _save)

    plan = await svc.build_plan(date(2026, 10, 21))
    assert plan["meta"]["truncated"] is True
    assert plan["meta"]["scope_count"] == svc.MAX_SCOPE


@pytest.mark.asyncio
async def test_fulfillment_uses_only_target_day_kline(monkeypatch):
    """兑现比对只能用**目标日那一根** K 线。

    check_fulfillment 会把传入 K 线的 high/low 合成为当日极值 ——
    一次给 5 根等于把「5 天极值」当成「单日极值」→ 昨天没到位的价位
    会被说成目标日触及了。这里造一根「前一天击穿、目标日没击穿」的 K 线锁死该行为。
    """
    prev_plan = {
        "id": 1, "plan_date": "2026-10-21",
        "outlook": None, "review": None,
        "meta": {"target_date": "2026-10-22"},
    }
    prev_items = [{
        "id": 1, "stock_code": "001896.SZ", "item_kind": "entry", "direction": "buy",
        "trigger_price": 9.62, "status_now": "armed", "label": "建仓",
    }]

    class _Repo:
        async def get_plan(self, plan_date):
            return prev_plan if plan_date == "2026-10-21" else None

        async def get_items(self, plan_id):
            return prev_items

        async def update_item_fulfillment(self, item_id, fulfillment, note=""):
            return None

    monkeypatch.setattr(svc, "battle_plan_repo", _Repo())

    async def _k(code, *a, **kw):
        return [
            {"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.80,
             "close": 9.9, "volume": 100},
            {"date": "2026-10-22", "open": 9.0, "high": 9.90, "low": 9.70,
             "close": 9.8, "volume": 100},
        ]
    monkeypatch.setattr(svc, "fetch_klines", _k)

    async def _txns(*a, **kw):
        return [], True   # F4: (流水列表, 是否读取成功)
    monkeypatch.setattr(svc, "_load_transactions", _txns)

    review = await svc._build_review("2026-10-21", "2026-10-22", [])
    assert review["fulfillment"]["items"][0]["fulfillment"] == "missed"


# ============================================================
# Task 6 · fix round 1
# ============================================================

PLAN_DATE = date(2026, 10, 21)      # 周三


def _indicators(stop_loss=8.26):
    """⚠️ `compute_indicators` 是**同步**函数,这里必须返回普通 dict"""
    return {
        "latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
        "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": stop_loss,
                     "support_price": 8.5, "risk_band": "mid"},
        "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
        "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
        "stabilize": {"state": False, "price": None}, "signal": {"score": 50},
    }


def _index_bars(last_date="2026-10-21"):
    """指数日K(升序)。last_date='2026-10-20' 即「盘中生成、今天还没出 K 线」"""
    return [
        {"date": "2026-10-19", "open": 2990, "high": 3010, "low": 2980,
         "close": 3000, "volume": 1000},
        {"date": last_date, "open": 3000, "high": 3040, "low": 2995,
         "close": 3030, "volume": 1100, "amount": 4.2e9},
    ]


def _patch_plan_env(monkeypatch, stocks=None, index_last_date="2026-10-21"):
    """把 build_plan 的外部 IO 全部打桩(**不打桩 _persist**)"""
    stocks = stocks if stocks is not None else [_stock()]
    bars = _index_bars(index_last_date)

    async def _pos():
        return list(stocks)

    async def _fav():
        return []

    async def _k(code, *a, **kw):
        if code == svc.INDEX_CODE:
            return list(bars)
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]

    async def _quote(codes):
        return []

    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])

    async def _sent():
        return {"up_total": 50, "down_total": 50}

    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]

    async def _txns(*a, **kw):
        return [], True

    async def _save(*a, **kw):
        return 1

    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)
    monkeypatch.setattr(svc, "fetch_klines", _k)
    monkeypatch.setattr(svc, "compute_indicators", lambda klines: _indicators())
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    monkeypatch.setattr(svc, "_load_transactions", _txns)
    monkeypatch.setattr(svc, "_persist", _save)
    return bars


@pytest.mark.asyncio
async def test_resolve_target_stocks_against_real_loaders(monkeypatch):
    """真实取数路径(不 mock `resolve_target_stocks` 本身)—— 集成缺陷必须在这里被抓住。

    ⚠️ 上一轮把 `resolve_target_stocks` 整个 monkeypatch 掉,于是它内部的
    `_load_favorites` 导入缺陷(`from app.repositories import watchlist_repo`
    拿到的是**子模块**而不是单例 → `.list_all()` AttributeError)完全逃逸,
    真实调用 `/scope` 与 `/generate` 必 500。
    本用例只打桩**最底层的两个数据源**,让真实合并逻辑整条跑一遍。
    """
    from types import SimpleNamespace

    from app.modules.portfolio import service as portfolio_service
    from app.repositories.watchlist_repo import watchlist_repo as watchlist_singleton

    async def _positions(account_id=None):
        return [
            SimpleNamespace(stock_code="600519.SH", stock_name="贵州茅台",
                            shares=100, avg_cost=1600.0),
            SimpleNamespace(stock_code="000807.SZ", stock_name="云铝股份",
                            shares=200, avg_cost=20.0),
        ]

    async def _list_all():
        # is_favorite=False 的行必须被过滤掉(★关注票才是关注票)
        return [
            SimpleNamespace(stock_code="000807.SZ", stock_name="云铝股份", is_favorite=True),
            SimpleNamespace(stock_code="300394.SZ", stock_name="天孚通信", is_favorite=True),
            SimpleNamespace(stock_code="002049.SZ", stock_name="紫光国微", is_favorite=False),
        ]

    # ⚠️ patch 单例**对象**上的方法,不是 patch 模块上的 `watchlist_repo` 名字 ——
    # 后者会把被导入的名字整个换掉,等于又 mock 掉了被测单元。
    monkeypatch.setattr(portfolio_service, "get_all_positions", _positions)
    monkeypatch.setattr(watchlist_singleton, "list_all", _list_all)

    scope = await svc.resolve_target_stocks()

    assert isinstance(scope, list)
    codes = [s["stock_code"] for s in scope]
    assert set(codes) == {"600519.SH", "000807.SZ", "300394.SZ"}
    assert codes.count("000807.SZ") == 1              # 持仓 ∪ 关注合并成一条
    by_code = {s["stock_code"]: s for s in scope}
    assert by_code["600519.SH"]["in_position"] is True
    assert by_code["600519.SH"]["is_favorite"] is False
    assert by_code["300394.SZ"]["in_position"] is False
    assert by_code["300394.SZ"]["is_favorite"] is True
    assert by_code["000807.SZ"]["in_position"] is True  # 既持仓又关注
    assert by_code["000807.SZ"]["is_favorite"] is True
    # 持仓在前,关注票保持 list_all 的 added_at desc(F7)
    assert codes == ["600519.SH", "000807.SZ", "300394.SZ"]


# ---------------- F4:流水读取失败的检测路径本身也要有锁 ----------------

@pytest.mark.asyncio
async def test_load_transactions_reports_failure(monkeypatch):
    """流水读失败 → 返回 ([], False),调用方据此降级披露(spec §六)

    ⚠️ 必须**真的让仓储抛异常**,不能 stub 掉 `_load_transactions` 本身 ——
    复审 M17 变异(把 except 改成 `return [], True`)曾让全量用例全绿,
    正是因为此前的 7 处引用**全是 stub**,真实读失败路径从未被执行到。
    """
    from app.modules.portfolio.repository import transaction_repo

    async def _boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(transaction_repo, "list_all", _boom)
    rows, ok = await svc._load_transactions("2026-10-21")
    assert rows == []
    assert ok is False


# ---------------- F5:并发取数后 `zip(scope, results)` 必须保持逐票配对 ----------------

@pytest.mark.asyncio
async def test_items_paired_with_their_own_stock(monkeypatch):
    """并发取数的 `zip(scope, results)` 必须保持**逐票配对**(asyncio.gather 保序)。

    ⚠️ 配对错位在断言层面本来**不可见**:`build_items` 用的是 decision 自带的
    `stock_code`,不是循环里的 `stock` —— 错位后「票号」看着全对,
    只有**该票的持仓上下文(股数/成本)**被安到了别的票身上,失败归因静默错位
    (复审 M22 变异存活的原因)。故用 spy 记录 `(decision.stock_code, position.shares)`
    配对,把错位钉死。
    """
    stocks = [
        _stock("600001.SH", "票甲", 10.0, 100, 9.0),
        _stock("600002.SH", "票乙", 10.0, 200, 9.5),
        _stock("600003.SH", "票丙", 10.0, 300, 9.9),
    ]
    _patch_plan_env(monkeypatch, stocks=stocks)

    real_build_items = svc.build_items
    pairs: list[tuple[str, int | None]] = []

    def _spy(decision, position):
        pairs.append((decision.get("stock_code"), getattr(position, "shares", None)))
        return real_build_items(decision, position)

    monkeypatch.setattr(svc, "build_items", _spy)

    plan = await svc.build_plan(PLAN_DATE)

    assert sorted(pairs) == [("600001.SH", 100), ("600002.SH", 200), ("600003.SH", 300)]
    assert len(pairs) == 3                      # 没有重复、没有丢失
    assert len({c for c, _ in pairs}) == 3
    assert {i["stock_code"] for i in plan["items"]} <= {"600001.SH", "600002.SH", "600003.SH"}


# ---------------- F2:R(上一份日报)数据驱动 ----------------

@pytest.mark.asyncio
async def test_prev_plan_date_skips_weekend(monkeypatch):
    """周一生成日报时,R 必须是**上周五**那份,不是「减一天」的周日。

    「减一天」在周一/长假后必然落空 → 复盘段恒为「没有找到昨日作战计划」,
    且周五面向下个交易日的预案永远停在 pending,闭环每周一断裂。

    ⚠️ 必须**端到端**跑 build_plan:直接调 `_find_prev_plan_date` 只能锁住那个
    helper,锁不住「build_plan 真的用它取 R」这条接线。
    """
    class _Repo:
        async def list_plan_dates(self, limit=30):
            return ["2026-10-26", "2026-10-23", "2026-10-22"]

        async def get_plan(self, plan_date):
            if plan_date == "2026-10-23":           # 只有上周五那份是真的
                return {"id": 9, "plan_date": plan_date, "outlook": None,
                        "review": None, "meta": {"target_date": "2026-10-26"}}
            return None

        async def get_items(self, plan_id):
            return [_prev_item()]

        async def update_item_fulfillment(self, item_id, fulfillment, note=""):
            return None

    _patch_plan_env(monkeypatch)
    monkeypatch.setattr(svc, "battle_plan_repo", _Repo())

    monday = date(2026, 10, 26)
    assert monday.weekday() == 0                    # 前提:这天是周一
    plan = await svc.build_plan(monday)
    assert plan["review"]["note"] is None           # 找到了上一份,不是「没有找到」
    assert plan["review"]["fulfillment"]["total"] == 1


@pytest.mark.asyncio
async def test_prev_plan_date_none_when_no_earlier_plan(monkeypatch):
    """库里没有更早的日报 → None(复盘段如实说「没有找到上一份作战计划」)"""
    class _Repo:
        async def list_plan_dates(self, limit=30):
            return ["2026-10-26", "2026-10-26"]

    monkeypatch.setattr(svc, "battle_plan_repo", _Repo())
    assert await svc._find_prev_plan_date(date(2026, 10, 26)) is None


# ---------------- F3:target_date 基准 ----------------

@pytest.mark.asyncio
async def test_next_trading_day_from_plan_date_not_last_bar(monkeypatch):
    """盘中生成时指数最后一根还是昨天 → 明日**不能**算成今天。

    基准必须用 plan_date(D):D/D+1 契约塌成今日,整份日报的语义就错了。
    """
    _patch_plan_env(monkeypatch, index_last_date="2026-10-20")
    plan = await svc.build_plan(PLAN_DATE)
    assert plan["target_date"] == "2026-10-22"          # 周四
    assert plan["meta"]["target_date"] == "2026-10-22"
    assert plan["meta"]["target_date_estimated"] is True
    # 周末顺延:周五的日报面向下周一
    assert svc._next_trading_day(date(2026, 10, 23))[0] == "2026-10-26"


# ---------------- F4:流水读取失败必须披露 ----------------

class _WriteRecorder:
    """假 repo:记录回填调用"""

    def __init__(self, prev_items):
        self.prev_items = prev_items
        self.written: list[tuple] = []

    async def get_plan(self, plan_date):
        if plan_date == "2026-10-21":
            return {"id": 1, "plan_date": "2026-10-21", "outlook": None,
                    "review": None, "meta": {"target_date": "2026-10-22"}}
        return None

    async def get_items(self, plan_id):
        return [dict(i) for i in self.prev_items]

    async def update_item_fulfillment(self, item_id, fulfillment, note=""):
        self.written.append((item_id, fulfillment))


def _patch_review(monkeypatch, prev_items, target_bars=None, transactions=None, tx_ok=True):
    repo = _WriteRecorder(prev_items)
    monkeypatch.setattr(svc, "battle_plan_repo", repo)

    async def _k(code, *a, **kw):
        return list(target_bars or [])

    async def _txns(*a, **kw):
        return list(transactions or []), tx_ok

    monkeypatch.setattr(svc, "fetch_klines", _k)
    monkeypatch.setattr(svc, "_load_transactions", _txns)
    return repo


def _prev_item(item_id=1, kind="entry", direction="buy", price=9.62, label="建仓"):
    return {"id": item_id, "stock_code": "001896.SZ", "stock_name": "豫能控股",
            "item_kind": kind, "direction": direction, "trigger_price": price,
            "status_now": "armed", "label": label}


@pytest.mark.asyncio
async def test_transactions_load_failure_marks_degraded(monkeypatch):
    """流水读失败 → degraded 里有记录(不许静默吞掉)"""
    items = [_prev_item()]
    _patch_review(monkeypatch, items, target_bars=[], tx_ok=False)
    degraded: list[str] = []
    review = await svc._build_review("2026-10-21", "2026-10-22", degraded)
    assert any("流水不可用" in r for r in degraded), degraded
    assert review["fulfillment"]["items"][0]["fulfillment"] == "no_data"


@pytest.mark.asyncio
async def test_transactions_failure_does_not_claim_no_operation(monkeypatch):
    """读不到流水 ≠ 当日无操作:note 必须写「流水不可用,未核对执行」"""
    items = [
        _prev_item(1, kind="entry", direction="buy", price=9.62, label="建仓"),
        _prev_item(2, kind="exit", direction="sell", price=12.03, label="减仓"),
    ]
    # 目标日一根 K 线:low 9.70 > 9.62 → 建仓未触及;high 12.5 >= 12.03 → 减仓触及
    _patch_review(
        monkeypatch, items,
        target_bars=[{"date": "2026-10-22", "open": 9.0, "high": 12.5, "low": 9.70,
                      "close": 12.0, "volume": 100}],
        tx_ok=False,
    )
    review = await svc._build_review("2026-10-21", "2026-10-22", [])
    by_kind = {i["item_kind"]: i for i in review["fulfillment"]["items"]}
    assert by_kind["entry"]["fulfillment"] == "missed"
    assert by_kind["entry"]["note"] == "流水不可用,未核对执行"
    assert by_kind["exit"]["fulfillment"] == "touched"
    # R1 裁决(fix round 2):触及分支的文案**不得**再声称「当日无对应操作」——
    # 那是「没核对」被写成了事实,正是 F4 要消除的那类不诚实。
    assert by_kind["exit"]["note"] == "价格已触及触发位,但流水不可用,未核对执行"
    assert "无对应操作" not in by_kind["exit"]["note"]


# ---------------- F1:no_data 不回填 ----------------

@pytest.mark.asyncio
async def test_no_data_items_are_not_written_back(monkeypatch):
    """目标日无 K 线 → `no_data`,**不回填**昨日日报(等数据补齐后可重判)。

    回填等于把「没判定」永久定成「未兑现」,还会被 items_preserved 冻结成死结论。
    """
    items = [
        _prev_item(1, kind="entry", direction="buy", price=9.62, label="建仓"),
        _prev_item(2, kind="exit", direction="sell", price=12.03, label="减仓"),
    ]
    repo = _patch_review(
        monkeypatch, items, target_bars=[],
        transactions=[{"stock_code": "001896.SZ", "action": "buy", "shares": 100,
                       "price": 9.62, "trade_date": "2026-10-22"}],
    )
    review = await svc._build_review("2026-10-21", "2026-10-22", [])
    by_kind = {i["item_kind"]: i for i in review["fulfillment"]["items"]}
    assert by_kind["entry"]["fulfillment"] == "executed"
    assert by_kind["exit"]["fulfillment"] == "no_data"
    # 只有可信判定回填;no_data 保持 pending
    assert repo.written == [(1, "executed")]


# ---------------- F6 / F1:_persist 幂等(不打桩,走真库) ----------------

def _plan_payload(plan_date="2026-11-02", items=None):
    return {
        "plan_date": plan_date,
        "outlook": {"stance": "neutral"},
        "review": None,
        "items": items if items is not None else [_prev_item()],
        "meta": {"scope_count": 1},
    }


@pytest.mark.asyncio
async def test_persist_is_idempotent_for_same_day():
    """同一天连续 _persist 两次 → battle_plans 里该 plan_date 只有 1 行"""
    pid1 = await svc._persist(_plan_payload())
    pid2 = await svc._persist(_plan_payload())
    assert pid1 == pid2
    async with async_session() as s:
        rows = (await s.execute(
            select(BattlePlan).where(BattlePlan.plan_date == "2026-11-02")
        )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_persist_keeps_judged_items():
    """已有可信判定(executed)→ items 原样保留,重新生成不冲掉复盘历史"""
    pid = await svc._persist(_plan_payload())
    items = await battle_plan_repo.get_items(pid)
    await battle_plan_repo.update_item_fulfillment(items[0]["id"], "executed", "已按计划执行")

    await svc._persist(_plan_payload(items=[_prev_item(item_id=0, kind="watch",
                                                      direction="none", price=None,
                                                      label="不该出现")]))
    after = await battle_plan_repo.get_items(pid)
    assert [i["stock_code"] for i in after] == ["001896.SZ"]
    assert after[0]["label"] == "建仓"
    assert after[0]["fulfillment"] == "executed"
    row = await battle_plan_repo.get_plan("2026-11-02")
    assert row["meta"]["items_preserved"] is True


@pytest.mark.asyncio
async def test_persist_replaces_items_when_all_pending():
    """全是 pending(还没判)→ 不可信 → items 被替换成新值"""
    pid = await svc._persist(_plan_payload())
    await svc._persist(_plan_payload(items=[_prev_item(kind="exit", direction="sell",
                                                      price=12.03, label="减仓")]))
    after = await battle_plan_repo.get_items(pid)
    assert [i["item_kind"] for i in after] == ["exit"]
    row = await battle_plan_repo.get_plan("2026-11-02")
    assert row["meta"]["items_preserved"] is False


@pytest.mark.asyncio
async def test_persist_replaces_items_when_only_no_data():
    """全是 no_data(没数据,判不了)→ 不可信 → 不冻结,items 被替换"""
    pid = await svc._persist(_plan_payload(items=[
        {"id": 1, "stock_code": "001896.SZ", "item_kind": "entry", "direction": "buy",
         "trigger_price": 9.62, "status_now": "armed", "label": "建仓",
         "fulfillment": "no_data", "fulfillment_note": "目标日无行情数据,未判定"},
    ]))
    assert [i["fulfillment"] for i in await battle_plan_repo.get_items(pid)] == ["no_data"]

    await svc._persist(_plan_payload(items=[_prev_item(kind="exit", direction="sell",
                                                      price=12.03, label="减仓")]))
    after = await battle_plan_repo.get_items(pid)
    assert [i["item_kind"] for i in after] == ["exit"]
    assert all(i["fulfillment"] == "pending" for i in after)
    row = await battle_plan_repo.get_plan("2026-11-02")
    assert row["meta"]["items_preserved"] is False


# ---------------- F7:关注票顺序 ----------------

@pytest.mark.asyncio
async def test_scope_keeps_favorite_order_by_added_at_desc(monkeypatch):
    """关注票顺序必须保留 `watchlist_repo.list_all()` 的 added_at desc。

    按 code 重排会把「最近加入的关注票」排到最后,截断上限时先砍掉最该保留的票。
    """
    async def _pos():
        return [_stock("600519.SH", "贵州茅台")]
    async def _fav():
        # list_all() 已按 added_at 倒序返回:最近加入的在最前
        return [{"stock_code": "300750.SZ", "stock_name": "宁德时代"},
                {"stock_code": "000001.SZ", "stock_name": "平安银行"},
                {"stock_code": "600036.SH", "stock_name": "招商银行"}]
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    scope = await svc.resolve_target_stocks()
    assert [s["stock_code"] for s in scope] == [
        "600519.SH", "300750.SZ", "000001.SZ", "600036.SH"]


# ---------------- F9 / F11 / F12:meta 形状与契约 ----------------

@pytest.mark.asyncio
async def test_scope_meta_excludes_cost_fields(monkeypatch):
    """meta.scope 只留 4 个字段 —— 真实持仓成本不该扩散到落库/出参"""
    _patch_plan_env(monkeypatch)
    plan = await svc.build_plan(PLAN_DATE)
    assert plan["meta"]["scope"]
    for entry in plan["meta"]["scope"]:
        assert set(entry) == {"stock_code", "stock_name", "in_position", "is_favorite"}


@pytest.mark.asyncio
async def test_top_level_todos_removed(monkeypatch):
    """顶层不得有 todos(spec §4.7 契约里待办只在 review.pending_todos)"""
    _patch_plan_env(monkeypatch)
    plan = await svc.build_plan(PLAN_DATE)
    assert "todos" not in plan
    assert set(plan) == {"plan_date", "target_date", "outlook", "review", "items", "meta"}


@pytest.mark.asyncio
async def test_generated_at_has_timezone(monkeypatch):
    """generated_at 必须带时区(否则跨时区/跨端无法还原真实生成时刻)"""
    _patch_plan_env(monkeypatch)
    plan = await svc.build_plan(PLAN_DATE)
    parsed = datetime.fromisoformat(plan["meta"]["generated_at"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None


# ---------------- F8:review.market 实况快照 ----------------

@pytest.mark.asyncio
async def test_review_market_snapshot_present(monkeypatch):
    """review.market 是 D 当天的指数实况,不是恒 None(spec §4.7)"""
    _patch_plan_env(monkeypatch, index_last_date="2026-10-21")
    plan = await svc.build_plan(PLAN_DATE)
    market = plan["review"]["market"]
    assert market is not None
    assert market["index_close"] == 3030.0
    assert market["change_pct"] == 1.0            # (3030-3000)/3000×100
    assert market["volume_note"] == "成交额 42 亿"


# ---------------- F13:单票决策/转换失败隔离 ----------------

@pytest.mark.asyncio
async def test_one_stock_failure_does_not_break_others(monkeypatch):
    """一只票的决策阶段炸了 → 整份日报照出,那一只记 degraded"""
    from app.services import decision_service

    real_build = decision_service.build_decision

    def _boom(ctx):
        if ctx.stock_code == "000807.SZ":
            raise RuntimeError("决策引擎内部错误")
        return real_build(ctx)

    _patch_plan_env(monkeypatch, stocks=[
        _stock(), _stock("000807.SZ", "云铝股份", 24.93, 100, 8.977)])
    monkeypatch.setattr(decision_service, "build_decision", _boom)

    plan = await svc.build_plan(PLAN_DATE)
    codes = {i["stock_code"] for i in plan["items"]}
    assert "000807.SZ" not in codes
    assert "001896.SZ" in codes
    assert plan["meta"]["degraded"] is True
    assert any("000807.SZ" in r and "决策计算失败" in r
               for r in plan["meta"]["degraded_reason"])


@pytest.mark.asyncio
async def test_stocks_are_fetched_concurrently(monkeypatch):
    """逐票取数必须**并发**(spec §4.7:串行 20 轮 × 2 次上游往返会打爆 60s 预算),
    且必须**限流**(Semaphore(6))—— 不限流的并发会把上游打挂。

    锁「同时在飞的取数」:串行实现 peak == 1,本用例必须转红。
    """
    import asyncio

    stocks = [_stock(f"0000{i:02d}.SZ", f"票{i}") for i in range(4)]
    _patch_plan_env(monkeypatch, stocks=stocks)
    base_k = svc.fetch_klines

    inflight = 0
    peak = 0

    async def _counting_k(code, *a, **kw):
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        try:
            await asyncio.sleep(0.01)       # 撑开窗口,让并发可观测
            return await base_k(code, *a, **kw)
        finally:
            inflight -= 1

    monkeypatch.setattr(svc, "fetch_klines", _counting_k)
    plan = await svc.build_plan(PLAN_DATE)

    assert 2 <= peak <= 6, f"逐票取数未并发或未限流: peak={peak}"
    assert plan["meta"]["scope_count"] == 4


@pytest.mark.asyncio
async def test_build_items_failure_is_isolated(monkeypatch):
    """预案转换(build_items)炸了 → 记 degraded,不冒泡成整份日报 500"""
    _patch_plan_env(monkeypatch)

    def _boom(*a, **kw):
        raise ValueError("预案转换炸了")

    monkeypatch.setattr(svc, "build_items", _boom)
    plan = await svc.build_plan(PLAN_DATE)
    assert plan["items"] == []
    assert plan["meta"]["degraded"] is True
    assert any("预案转换失败" in r for r in plan["meta"]["degraded_reason"])
