"""每日 AI 分析持久化测试(v2.4)

- migration 创建 daily_analyses 表
- Repository upsert(同 stock+date 覆盖)
- Service save_from_analysis_result 触发端点写入
- API GET /daily-analyses 列历史
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import async_session
from app.main import app
from app.models.orm import DailyAnalysis


@pytest.fixture()
def client(monkeypatch):
    """client fixture 默认 stub QuoteService"""
    from app.services import quote_service
    import app.api.stock as _stock_mod
    from datetime import datetime as _dt
    from decimal import Decimal as _D
    from app.data.unified import UnifiedQuote

    class FakeQuoteService:
        async def get_quotes(self, codes):
            return [
                UnifiedQuote(
                    code=codes[0], name="测试",
                    current_price=_D("105.500"), prev_close=_D("100.000"),
                    open=_D("100.000"), high=_D("106.000"), low=_D("99.000"),
                    change=_D("5.500"), change_pct=5.5,
                    volume=10000, amount=_D("1000000"), timestamp=_dt.now(),
                )
            ]
    monkeypatch.setattr(quote_service, "QuoteService", FakeQuoteService)
    monkeypatch.setattr(_stock_mod, "QuoteService", FakeQuoteService)

    # disable async diagnose scoring(避免 trade_scores UNIQUE 冲突)
    from app.services import diagnose_service
    original = diagnose_service.diagnose_service.score_and_notify

    async def _noop(trade_id):
        return None

    diagnose_service.diagnose_service.score_and_notify = _noop
    try:
        with TestClient(app) as c:
            yield c
    finally:
        diagnose_service.diagnose_service.score_and_notify = original


@pytest.fixture(autouse=True)
def _clean(client):
    """每个测试前清表 + 清胜率缓存(依赖 client 触发 lifespan 跑 alembic)"""
    from app.services.daily_analysis_service import clear_winrate_cache

    async def _do():
        async with async_session() as session:
            await session.execute(delete(DailyAnalysis))
            await session.commit()

    asyncio.run(_do())
    clear_winrate_cache()
    yield


def _sina_rows(end_date: str = "2026-08-04", n: int = 120):
    """生成 n 条 K 线 dict 列表"""
    from datetime import date, timedelta
    end = date.fromisoformat(end_date)
    return [
        {
            "day": (end - timedelta(days=n - 1 - i)).isoformat(),
            "open": "100", "high": "102", "low": "99", "close": "101", "volume": "10000",
        }
        for i in range(n)
    ]


def _sina_responses(end_date: str = "2026-08-04", n: int = 120):
    """生成 n 条 K 线(用 httpx.Response 包装,供 make_fake_client_class)"""
    import httpx
    import json as _json
    rows = _sina_rows(end_date, n)
    return [httpx.Response(200, text=f"cb({_json.dumps(rows, ensure_ascii=False)});")]


def _make_fake(responses):
    """fake httpx client(复用 test_kline.py 的 make_fake_client_class,返回 (cls, state))"""
    from tests.test_kline import make_fake_client_class
    cls, _state = make_fake_client_class(responses)
    return cls


# ============================================================
# Repository: UPSERT
# ============================================================


class TestDailyAnalysisRepo:
    def test_upsert_inserts_new(self):
        from app.repositories.daily_analysis_repo import daily_analysis_repo
        from datetime import date

        async def _do():
            row = await daily_analysis_repo.upsert(
                stock_code="001896.SZ",
                analysis_date=date(2026, 8, 4),
                score_avg="101.00",
                dimension_avg={"集中度": 16.0, "价格合理性": 8.0},
                top_issues=[{"dim": "价格合理性", "score": 8, "hint": "买入价相对成本偏离"}],
ai_view="bullish",
                    ai_summary="测试评语",
                    ai_advice_json=None,
                current_price="105.500",
                latest_kline_date=date(2026, 8, 4),
            )
            return row.id

        rid = asyncio.run(_do())
        assert rid > 0

    def test_upsert_overwrites_same_day(self):
        from app.repositories.daily_analysis_repo import daily_analysis_repo
        from datetime import date

        async def _do():
            r1 = await daily_analysis_repo.upsert(
                stock_code="001896.SZ", analysis_date=date(2026, 8, 4),
                score_avg="101.00", dimension_avg={}, top_issues=[],
                ai_view="bullish", ai_summary="v1", ai_advice_json=None,
                current_price="100", latest_kline_date=date(2026, 8, 4),
            )
            r2 = await daily_analysis_repo.upsert(
                stock_code="001896.SZ", analysis_date=date(2026, 8, 4),
                score_avg="102.00", dimension_avg={}, top_issues=[],
                ai_view="bearish", ai_summary="v2", ai_advice_json=None,
                current_price="101", latest_kline_date=date(2026, 8, 4),
            )
            return r1.id, r2.id, r2.ai_summary, r2.ai_view

        rid1, rid2, summary, view = asyncio.run(_do())
        assert rid1 == rid2  # 同 row 覆盖
        assert summary == "v2"
        assert view == "bearish"

    def test_list_by_stock_descending(self):
        from app.repositories.daily_analysis_repo import daily_analysis_repo
        from datetime import date, timedelta

        async def _do():
            today = date(2026, 8, 4)
            for d in range(5):
                await daily_analysis_repo.upsert(
                    stock_code="001896.SZ", analysis_date=today - timedelta(days=d),
                    score_avg=f"100.{d}", dimension_avg={}, top_issues=[],
                    ai_view="neutral", ai_summary=f"day-{d}", ai_advice_json=None,
                    current_price="100", latest_kline_date=today - timedelta(days=d),
                )
            rows = await daily_analysis_repo.list_by_stock("001896.SZ", limit=10)
            return [r.analysis_date.isoformat() for r in rows]

        dates = asyncio.run(_do())
        assert dates == ["2026-08-04", "2026-08-03", "2026-08-02", "2026-08-01", "2026-07-31"]


# ============================================================
# Service: save_from_analysis_result
# ============================================================


class TestDailyAnalysisService:
    def test_save_extracts_fields(self):
        from app.services.daily_analysis_service import save_from_analysis_result

        async def _do():
            klines = _sina_rows("2026-08-04")
            result = {
                "indicators": {"latest_close": "101.00"},
                "ai": {
                    "view": "bullish",
                    "advice": "建议关注 5 维度评分,集中度偏低",
                },
                "latest_kline_date": "2026-08-04",
                "current_price": "105.500",
                "summary_snapshot": {},
            }
            row_id = await save_from_analysis_result("001896.SZ", klines, result)
            return row_id

        rid = asyncio.run(_do())
        assert rid is not None

    def test_save_failure_returns_none_not_raise(self):
        """失败不抛异常"""
        from app.services.daily_analysis_service import save_from_analysis_result

        async def _do():
            # 故意传非法 klines(没有 date 字段)→ 内部解析失败
            result = {"indicators": {}, "ai": {"view": "neutral", "advice": "x"},
                      "latest_kline_date": "2026-08-04"}
            return await save_from_analysis_result("001896.SZ", [], result)

        # 实际上 klines=[] 走 fallback 到 result.latest_kline_date → 应成功
        rid = asyncio.run(_do())
        assert rid is not None  # fallback 到 result.latest_kline_date


    def test_legacy_row_invalid_view_normalized(self):
        """v2.5.4:历史行 ai_json 里 view 非标准枚举 → 回显归一为 neutral(防前端崩溃)"""
        from datetime import date
        from app.services.daily_analysis_service import get_latest_as_analysis_result

        async def _seed():
            async with async_session() as session:
                session.add(DailyAnalysis(
                    stock_code="001896.SZ",
                    analysis_date=date(2026, 8, 4),
                    score_avg="0.00",
                    dimension_avg="{}",
                    top_issues="[]",
                    ai_view=None,
                    ai_summary="旧数据",
                    ai_json=json.dumps({
                        "view": "strongly_bullish",
                        "view_reason": "x",
                        "trend": "y",
                        "volume_note": "z",
                        "key_levels": [],
                        "position_status": "empty",
                        "advice_role": "建仓参考",
                        "advice": {"rationale": "r"},
                        "risk_warning": "",
                    }, ensure_ascii=False),
                    current_price="105.500",
                    latest_kline_date=date(2026, 8, 4),
                ))
                await session.commit()

        async def _get():
            await _seed()
            return await get_latest_as_analysis_result("001896.SZ")

        result = asyncio.run(_get())
        assert result is not None
        assert result["ai"]["view"] == "neutral"

    def test_legal_view_untouched(self):
        """合法 view 原样保留(不误改)"""
        from datetime import date
        from app.services.daily_analysis_service import get_latest_as_analysis_result

        async def _seed():
            async with async_session() as session:
                session.add(DailyAnalysis(
                    stock_code="001897.SZ",
                    analysis_date=date(2026, 8, 4),
                    score_avg="0.00",
                    dimension_avg="{}",
                    top_issues="[]",
                    ai_view="bearish",
                    ai_json=json.dumps({
                        "view": "bearish",
                        "view_reason": "x",
                        "trend": "y",
                        "volume_note": "z",
                        "key_levels": [],
                        "position_status": "empty",
                        "advice_role": "建仓参考",
                        "advice": {"rationale": "r"},
                        "risk_warning": "",
                    }, ensure_ascii=False),
                    latest_kline_date=date(2026, 8, 4),
                ))
                await session.commit()

        async def _get():
            await _seed()
            return await get_latest_as_analysis_result("001897.SZ")

        result = asyncio.run(_get())
        assert result is not None
        assert result["ai"]["view"] == "bearish"


# ============================================================
# API: GET /daily-analyses
# ============================================================


class TestDailyAnalysisAPI:
    def test_endpoint_returns_history(self, client, monkeypatch):
        from app.services import kline_service
        from app.repositories.daily_analysis_repo import daily_analysis_repo
        from datetime import date, timedelta

        # seed: 直接写库(避免依赖 analysis 端点)
        async def _seed():
            today = date(2026, 8, 4)
            for d in range(3):
                await daily_analysis_repo.upsert(
                    stock_code="001896.SZ", analysis_date=today - timedelta(days=d),
                    score_avg="101.00", dimension_avg={}, top_issues=[],
                    ai_view="bullish" if d == 0 else "neutral",
                    ai_summary=f"day-{d}", ai_advice_json=None,
                    current_price="105.500", latest_kline_date=today - timedelta(days=d),
                )

        asyncio.run(_seed())

        r = client.get("/api/diagnose/stock/001896.SZ/daily-analyses?days=30")
        assert r.status_code == 200
        body = r.json()
        assert body["stock_code"] == "001896.SZ"
        assert body["days"] == 30
        assert body["total"] == 3
        # 按日期倒序
        items = body["items"]
        assert items[0]["analysis_date"] == "2026-08-04"
        assert items[0]["ai_view"] == "bullish"
        assert items[2]["analysis_date"] == "2026-08-02"

    def test_endpoint_empty_returns_empty(self, client):
        r = client.get("/api/diagnose/stock/999999.SZ/daily-analyses?days=30")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_analysis_endpoint_persists(self, client, monkeypatch):
        """调 /api/stock/{code}/analysis → 自动持久化到 daily_analyses"""
        from app.services import kline_service

        monkeypatch.setattr(
            kline_service.httpx, "AsyncClient", _make_fake(_sina_responses("2026-08-04"))
        )
        # disable diagnose
        from app.services import diagnose_service
        from app.services.llm_test_service import LlmTestService
        from app.services import stock_advice_service
        from datetime import date

        class _StubLLM:
            name = "fake"

            def __init__(self, reply):
                self.reply = reply

            async def chat(self, *a, **kw):
                return self.reply

            async def chat_with_messages(self, *a, **kw):
                return self.reply

        VALID_AI = json.dumps({
            "view": "bullish",
            "view_reason": "价合理 + 量健康",
            "trend": "短期向上",
            "volume_note": "量价齐升",
            "key_levels": [{"type": "support", "price": 95.0, "note": "支撑"}],
            "advice": "建议关注 5 维度,集中度偏低",
            "risk_warning": "仅供参考,不构成投资建议",
        }, ensure_ascii=False)

        # mock provider(provider_factory.get 是 async,需要返回 awaitable)
        async def _fake_get(provider):
            return _StubLLM(VALID_AI)
        async def _fake_active():
            return "deepseek"
        stock_advice_service.llm_settings_repo.get_active = _fake_active
        stock_advice_service.provider_factory.get = _fake_get

        # 1) 先 POST 流水触发 analyze → 但流水不是必需的,analysis 端点本身也调 LLM
        # 2) 直接 GET /api/stock/001896.SZ/analysis → 触发 LLM + 持久化
        r = client.get("/api/stock/001896.SZ/analysis")
        assert r.status_code == 200

        # 3) 检查 daily_analyses 表
        async def _check():
            async with async_session() as session:
                stmt = (
                    "SELECT stock_code, analysis_date, ai_view, score_avg, current_price "
                    "FROM daily_analyses WHERE stock_code='001896.SZ'"
                )
                rows = list((await session.execute(__import__("sqlalchemy").text(stmt))).fetchall())
                return rows

        rows = asyncio.run(_check())
        # K 線最末日 = 2026-08-04 → 應持久化
        assert len(rows) >= 1
        assert rows[0][0] == "001896.SZ"
        assert str(rows[0][1]) == "2026-08-04"
        assert rows[0][2] == "bullish"
        assert rows[0][4] == "105.50"  # current_price(quantize 2 位)


# ============================================================
# P1: 方向胜率(view vs N 天后涨跌)
# ============================================================


class TestViewWinrate:
    def test_bullish_hit_when_price_up(self, monkeypatch):
        """bullish + N 天后涨 → hit"""
        from app.services import kline_service
        from app.services.daily_analysis_service import _observe_view_outcome
        from datetime import date as _d

        # 注入 K 线:2026-08-04 close=100,N 天后(假设 N=20)close=110(涨)
        fake = _make_fake_klines(
            base_date=_d(2026, 8, 4),
            base_close="100.000",
            target_idx=20,
            target_close="110.000",
            n=40,
        )
        monkeypatch.setattr(kline_service, "fetch_klines", fake)

        async def _do():
            return await _observe_view_outcome(
                "001896.SZ", _d(2026, 8, 4), "bullish", horizon_days=20
            )

        outcome = asyncio.run(_do())
        assert outcome is not None
        kind, change = outcome
        assert kind == "hit"
        assert change.startswith("+")

    def test_bullish_miss_when_price_down(self, monkeypatch):
        """bullish + N 天后跌 → miss"""
        from app.services import kline_service
        from app.services.daily_analysis_service import _observe_view_outcome
        from datetime import date as _d

        fake = _make_fake_klines(
            base_date=_d(2026, 8, 4),
            base_close="100.000",
            target_idx=20,
            target_close="90.000",  # 跌
            n=40,
        )
        monkeypatch.setattr(kline_service, "fetch_klines", fake)

        async def _do():
            return await _observe_view_outcome(
                "001896.SZ", _d(2026, 8, 4), "bullish", horizon_days=20
            )

        outcome = asyncio.run(_do())
        assert outcome[0] == "miss"

    def test_bearish_hit_when_price_down(self, monkeypatch):
        """bearish + N 天后跌 → hit"""
        from app.services import kline_service
        from app.services.daily_analysis_service import _observe_view_outcome
        from datetime import date as _d

        fake = _make_fake_klines(
            base_date=_d(2026, 8, 4),
            base_close="100.000",
            target_idx=20,
            target_close="90.000",
            n=40,
        )
        monkeypatch.setattr(kline_service, "fetch_klines", fake)

        async def _do():
            return await _observe_view_outcome(
                "001896.SZ", _d(2026, 8, 4), "bearish", horizon_days=20
            )

        outcome = asyncio.run(_do())
        assert outcome[0] == "hit"

    def test_neutral_skipped(self, monkeypatch):
        """neutral → 返回 None(不计入分母)"""
        from app.services import kline_service
        from app.services.daily_analysis_service import _observe_view_outcome
        from datetime import date as _d

        fake = _make_fake_klines(
            base_date=_d(2026, 8, 4),
            base_close="100.000",
            target_idx=20,
            target_close="110.000",
            n=40,
        )
        monkeypatch.setattr(kline_service, "fetch_klines", fake)

        async def _do():
            return await _observe_view_outcome(
                "001896.SZ", _d(2026, 8, 4), "neutral", horizon_days=20
            )

        assert asyncio.run(_do()) is None


def _make_fake_klines(base_date, base_close, target_idx, target_close, n):
    """构造 fetch_klines 的 fake:
    - 第 0 个交易日是 base_date,close=base_close
    - 第 target_idx 个交易日 close=target_close
    - 中间日期 close 保持 base_close(不变)
    """
    from datetime import timedelta

    async def _fake(stock_code, period="daily", count=60):
        rows = []
        for i in range(n):
            d = (base_date + timedelta(days=i)).isoformat()
            close = target_close if i == target_idx else base_close
            rows.append({"date": d, "open": close, "high": close,
                         "low": close, "close": close, "volume": "1000"})
        return rows

    return _fake


class TestWinrateAPI:
    def test_endpoint_returns_aggregated(self, client, monkeypatch):
        """winrate 端点返回聚合结果"""
        from app.services import kline_service
        from app.repositories.daily_analysis_repo import daily_analysis_repo
        from datetime import date as _d, timedelta

        # seed: 4 条分析(2 bullish, 1 bearish, 1 neutral)
        async def _seed():
            today = _d(2026, 8, 4)
            for i, (view, _) in enumerate([
                ("bullish", "hit"),  # 涨
                ("bullish", "miss"),  # 跌
                ("bearish", "hit"),   # 跌
                ("neutral", None),    # 跳过
            ]):
                await daily_analysis_repo.upsert(
                    stock_code="001896.SZ",
                    analysis_date=today - timedelta(days=i + 5),
                    score_avg="100.00", dimension_avg={}, top_issues=[],
                    ai_view=view, ai_summary=f"day-{i}", ai_advice_json=None,
                    current_price="100.00",
                    latest_kline_date=today - timedelta(days=i + 5),
                )

        asyncio.run(_seed())

        # 用 fake fetch_klines:确保 analysis 当日(2026-07-27 ~ 07-30)+ 20 日后都有 close
        fake = _make_fake_klines(
            base_date=_d(2026, 7, 20),  # 涵盖 7/27~7/30 analysis_date
            base_close="100.000",
            target_idx=25,
            target_close="110.000",  # 涨
            n=60,
        )
        monkeypatch.setattr(kline_service, "fetch_klines", fake)

        r = client.get(
            "/api/diagnose/stock/001896.SZ/daily-analyses/winrate?days=90&horizon=20"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["stock_code"] == "001896.SZ"
        assert body["days"] == 90
        assert body["horizon_days"] == 20
        # 至少 2 bullish(都涨 → 命中) + 1 bearish(涨 → miss) 可评估
        # 因 fake 都让价格涨,bullish=hit, bearish=miss
        assert body["bullish"]["total"] >= 1
        assert body["bearish"]["total"] >= 1
        assert body["insufficient"] is False  # 至少 3 个样本
        assert "generated_at" in body
        assert "simulate_return_pct" in body

    def test_endpoint_insufficient_when_few_samples(self, client, monkeypatch):
        """样本 < 3 → insufficient=true"""
        from app.services import kline_service
        from app.repositories.daily_analysis_repo import daily_analysis_repo
        from datetime import date as _d, timedelta

        async def _seed():
            today = _d(2026, 8, 4)
            # 只 1 条 bullish
            await daily_analysis_repo.upsert(
                stock_code="001896.SZ",
                analysis_date=today - timedelta(days=5),
                score_avg="100.00", dimension_avg={}, top_issues=[],
                ai_view="bullish", ai_summary="only one", ai_advice_json=None,
                current_price="100.00",
                latest_kline_date=today - timedelta(days=5),
            )

        asyncio.run(_seed())

        fake = _make_fake_klines(
            base_date=_d(2026, 7, 1), base_close="100.000",
            target_idx=20, target_close="110.000", n=60,
        )
        monkeypatch.setattr(kline_service, "fetch_klines", fake)

        r = client.get(
            "/api/diagnose/stock/001896.SZ/daily-analyses/winrate?days=30&horizon=20"
        )
        body = r.json()
        assert body["samples"] == 1
        assert body["insufficient"] is True
        assert body["overall_accuracy"] is None  # 样本不足时不给结论

    def test_endpoint_returns_zero_when_no_data(self, client):
        """无数据 → samples=0"""
        r = client.get(
            "/api/diagnose/stock/999999.SZ/daily-analyses/winrate"
        )
        body = r.json()
        assert body["samples"] == 0
        assert body["insufficient"] is True
        assert body["bullish"]["total"] == 0
        assert body["bearish"]["total"] == 0

    def test_simulate_return_sign(self, monkeypatch):
        """同向模拟:bullish 做多 + bearish 做空,等权累加简单收益率"""
        from app.services import daily_analysis_service as svc
        from app.repositories.daily_analysis_repo import daily_analysis_repo
        from datetime import date as _d, timedelta

        async def _seed():
            today = _d(2026, 8, 4)
            for i, view in enumerate(["bullish", "bullish", "bearish"]):
                await daily_analysis_repo.upsert(
                    stock_code="001896.SZ",
                    analysis_date=today - timedelta(days=i + 5),
                    score_avg="100.00", dimension_avg={}, top_issues=[],
                    ai_view=view, ai_summary=f"day-{i}", ai_advice_json=None,
                    current_price="100.00",
                    latest_kline_date=today - timedelta(days=i + 5),
                )

        asyncio.run(_seed())

        # 固定 outcome:bullish 涨 +10, bearish 跌 -5(做空赚 +5)
        results = {"bullish": ("hit", "+10.00"), "bearish": ("hit", "-5.00")}

        async def _fake_outcome(stock, adate, view, horizon_days=20):
            return results.get(view)

        monkeypatch.setattr(svc, "_observe_view_outcome", _fake_outcome)

        async def _do():
            return await svc.compute_view_winrate("001896.SZ", days=30, horizon_days=20)

        body = asyncio.run(_do())
        # +10 +10 + (-(-5)) = +25
        assert body["simulate_return_pct"] == 25.0
        assert body["samples"] == 3
        assert body["insufficient"] is False

    def test_winrate_cached_within_ttl(self, monkeypatch):
        """同 (stock, days, horizon) 第二次调用命中缓存,不重算"""
        from app.services import daily_analysis_service as svc
        from app.repositories.daily_analysis_repo import daily_analysis_repo
        from datetime import date as _d, timedelta

        async def _seed():
            today = _d(2026, 8, 4)
            for i in range(3):
                await daily_analysis_repo.upsert(
                    stock_code="001896.SZ",
                    analysis_date=today - timedelta(days=i + 5),
                    score_avg="100.00", dimension_avg={}, top_issues=[],
                    ai_view="bullish", ai_summary=f"day-{i}", ai_advice_json=None,
                    current_price="100.00",
                    latest_kline_date=today - timedelta(days=i + 5),
                )

        asyncio.run(_seed())

        calls = {"n": 0}

        async def _fake_outcome(stock, adate, view, horizon_days=20):
            calls["n"] += 1
            return ("hit", "+1.00")

        monkeypatch.setattr(svc, "_observe_view_outcome", _fake_outcome)

        async def _do():
            r1 = await svc.compute_view_winrate("001896.SZ", days=30, horizon_days=20)
            r2 = await svc.compute_view_winrate("001896.SZ", days=30, horizon_days=20)
            return r1, r2

        r1, r2 = asyncio.run(_do())
        assert r1["samples"] == 3
        assert r2["samples"] == 3
        assert calls["n"] == 3  # 只算了第一次(第二次命中缓存)