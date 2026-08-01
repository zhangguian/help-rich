"""P4.4 diagnose_service 测试

- score_and_notify 全链路:评分 → 写库 → SSE → LLM → 评语
- 缺 Key 降级(no_key)
- LLM 失败降级(failed)
- 交易不存在跳过
- diagnose API(触发 / 查询)
"""
import asyncio
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.transaction_repo import transaction_repo
from app.services.diagnose_service import diagnose_service, _load_context_trades


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db(client):
    """清空交易 + 评分,保证断言独立"""
    from app.db import async_session
    from app.models.orm import TradeScore, Transaction
    from sqlalchemy import delete

    async def _clean():
        async with async_session() as session:
            await session.execute(delete(TradeScore))
            await session.execute(delete(Transaction))
            await session.commit()

    asyncio.run(_clean())
    yield


async def _seed_trades():
    """两条流水(顺序可预测)"""
    t1 = await transaction_repo.create(
        stock_code="600519.SH", stock_name="贵州茅台",
        action="buy", shares=100, price="1400.000",
        trade_date=date(2026, 7, 10),
    )
    t2 = await transaction_repo.create(
        stock_code="600519.SH", stock_name="贵州茅台",
        action="buy", shares=100, price="1450.000",
        trade_date=date(2026, 7, 20),
    )
    return t1, t2


class TestContextTrades:
    def test_load_context_before_target(self):
        class T:
            def __init__(self, id_, d):
                self.id = id_
                self.trade_date = date.fromisoformat(d)

        all_tx = [
            T(1, "2026-07-01"), T(2, "2026-07-05"),
            T(3, "2026-07-10"), T(4, "2026-07-20"),
        ]
        before, found = _load_context_trades(all_tx, 3)
        assert found is True
        assert [t.id for t in before] == [1, 2]

    def test_load_context_first_trade(self):
        class T:
            def __init__(self, id_, d):
                self.id = id_
                self.trade_date = date.fromisoformat(d)

        all_tx = [T(1, "2026-07-01"), T(2, "2026-07-05")]
        before, found = _load_context_trades(all_tx, 1)
        assert found is True
        assert before == []

    def test_load_context_not_found(self):
        class T:
            def __init__(self, id_, d):
                self.id = id_
                self.trade_date = date.fromisoformat(d)

        all_tx = [T(1, "2026-07-01")]
        before, found = _load_context_trades(all_tx, 99)
        assert found is False
        assert len(before) == 1
        assert before[0].id == 1


class TestScoreAndNotify:
    def test_full_flow_scores_and_publishes(self, client, monkeypatch):
        """全链路:评分 → 写库 → SSE 评分 → LLM → 评语"""
        t1, t2 = asyncio.run(_seed_trades())
        events = []

        async def fake_publish(event):
            events.append(event)

        monkeypatch.setattr(
            "app.services.diagnose_service.event_bus.publish", fake_publish
        )

        class FakeLLM:
            name = "deepseek"
            model_name = "deepseek-chat"

            async def chat(self, system, user, temperature=0.3, max_retries=3):
                assert "以上不构成投资建议" in system
                assert "评分" in user
                return "买入价高于成本,建议等待回调。以上不构成投资建议。"

        async def fake_get(name):
            return FakeLLM()

        monkeypatch.setattr(
            "app.services.diagnose_service.provider_factory.get", fake_get
        )

        asyncio.run(diagnose_service.score_and_notify(t2.id))

        # 1. 写库
        from app.repositories.trade_score_repo import trade_score_repo

        score = asyncio.run(trade_score_repo.get_by_trade_id(t2.id))
        assert score is not None
        assert 0 <= score.score <= 100
        breakdown = json.loads(score.score_breakdown)
        assert set(breakdown.keys()) == {"集中度", "价格合理性", "操作间隔", "市场环境", "板块热度"}
        assert score.ai_status == "success"
        assert score.ai_provider == "deepseek"
        assert "不构成投资建议" in (score.ai_comment or "")
        evt_names = [e["event"] for e in events]
        assert evt_names[0] == "trade.scored"
        assert evt_names[1] == "trade.commented"
        assert events[0]["trade_id"] == t2.id
        assert events[0]["score"] == score.score
        assert events[1]["comment"] == score.ai_comment

    def test_provider_label_from_active(self, client, monkeypatch):
        """P4.2d:激活 provider 非 deepseek 时,provider 标签随之写入"""
        t1, t2 = asyncio.run(_seed_trades())

        async def fake_publish(event):
            pass

        monkeypatch.setattr(
            "app.services.diagnose_service.event_bus.publish", fake_publish
        )

        from app.llm.minimax import MiniMaxClient

        async def fake_get(name):
            assert name == "minimax"
            return MiniMaxClient("sk-test")

        monkeypatch.setattr(
            "app.services.diagnose_service.provider_factory.get", fake_get
        )

        async def fake_chat(system, user, temperature=0.3, max_retries=3):
            return "OK。以上不构成投资建议。"

        monkeypatch.setattr(MiniMaxClient, "chat", fake_chat)

        async def fake_active():
            return "minimax"

        monkeypatch.setattr(
            "app.services.diagnose_service.llm_settings_repo.get_active", fake_active
        )

        asyncio.run(diagnose_service.score_and_notify(t2.id))

        from app.repositories.trade_score_repo import trade_score_repo

        score = asyncio.run(trade_score_repo.get_by_trade_id(t2.id))
        assert score.ai_provider == "minimax"
        assert score.ai_model == "abab6.5s-chat"

    def test_no_key_degrades(self, client, monkeypatch):
        """缺 Key:评分仍出,ai_status=no_key,推 trade.failed"""
        t1, t2 = asyncio.run(_seed_trades())
        events = []

        async def fake_publish(event):
            events.append(event)

        monkeypatch.setattr(
            "app.services.diagnose_service.event_bus.publish", fake_publish
        )

        async def fake_get(name):
            return None

        monkeypatch.setattr(
            "app.services.diagnose_service.provider_factory.get", fake_get
        )

        asyncio.run(diagnose_service.score_and_notify(t2.id))

        from app.repositories.trade_score_repo import trade_score_repo

        score = asyncio.run(trade_score_repo.get_by_trade_id(t2.id))
        assert score is not None
        assert score.ai_status == "no_key"
        assert score.ai_comment is None

        failed = [e for e in events if e["event"] == "trade.failed"]
        assert len(failed) == 1
        assert "未配置 Key" in failed[0]["reason"]

    def test_llm_failure_degrades(self, client, monkeypatch):
        """LLM 抛异常:ai_status=failed,推 trade.failed"""
        t1, t2 = asyncio.run(_seed_trades())
        events = []

        async def fake_publish(event):
            events.append(event)

        monkeypatch.setattr(
            "app.services.diagnose_service.event_bus.publish", fake_publish
        )

        class BrokenLLM:
            name = "deepseek"
            model_name = "deepseek-chat"

            async def chat(self, system, user, temperature=0.3, max_retries=3):
                raise RuntimeError("LLM timeout")

        async def fake_get(name):
            return BrokenLLM()

        monkeypatch.setattr(
            "app.services.diagnose_service.provider_factory.get", fake_get
        )

        asyncio.run(diagnose_service.score_and_notify(t2.id))

        from app.repositories.trade_score_repo import trade_score_repo

        score = asyncio.run(trade_score_repo.get_by_trade_id(t2.id))
        assert score is not None
        assert score.ai_status == "failed"
        assert score.ai_comment is None

        failed = [e for e in events if e["event"] == "trade.failed"]
        assert len(failed) == 1

    def test_trade_not_found_skips(self, client, monkeypatch):
        published = []

        async def fake_publish(event):
            published.append(event)

        monkeypatch.setattr(
            "app.services.diagnose_service.event_bus.publish", fake_publish
        )

        # 不报错,不发事件
        asyncio.run(diagnose_service.score_and_notify(99999))
        assert published == []


class TestDiagnoseAPI:
    def test_trigger_returns_pending(self, client):
        t1, t2 = asyncio.run(_seed_trades())
        r = client.post(f"/api/diagnose/{t2.id}")
        assert r.status_code == 200
        data = r.json()
        assert data["trade_id"] == t2.id
        assert data["status"] == "pending"

    def test_trigger_not_found(self, client):
        r = client.post("/api/diagnose/99999")
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "TX_NOT_FOUND"

    def test_get_pending_when_no_score(self, client):
        t1, t2 = asyncio.run(_seed_trades())
        r = client.get(f"/api/diagnose/{t2.id}")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "pending"
        assert data["score"] is None

    def test_get_after_score(self, client, monkeypatch):
        """先跑 score_and_notify(假 LLM),再 GET 应返回评分"""
        t1, t2 = asyncio.run(_seed_trades())

        async def fake_publish(event):
            pass

        monkeypatch.setattr(
            "app.services.diagnose_service.event_bus.publish", fake_publish
        )

        class FakeLLM:
            name = "deepseek"
            model_name = "deepseek-chat"

            async def chat(self, system, user, temperature=0.3, max_retries=3):
                return "OK。以上不构成投资建议。"

        async def fake_get(name):
            return FakeLLM()

        monkeypatch.setattr(
            "app.services.diagnose_service.provider_factory.get", fake_get
        )

        asyncio.run(diagnose_service.score_and_notify(t2.id))

        r = client.get(f"/api/diagnose/{t2.id}")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["score"] is not None
        assert set(data["breakdown"].keys()) == {"集中度", "价格合理性", "操作间隔", "市场环境", "板块热度"}
        assert data["ai_comment"] == "OK。以上不构成投资建议。"
