"""T2.3/T3 AI 解读层 + API 测试

- service 级:mock provider_factory + llm_settings_repo(不触网)
- API 级:fake httpx.AsyncClient 拦截新浪 K 线 + mock LLM
"""
import asyncio
import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import kline_service, stock_advice_service
from app.services.stock_advice_service import StockAdviceUnavailable

VALID_AI_JSON = json.dumps({
    "view": "bullish",
    "view_reason": "站上 MA20(100.5),且放量突破",
    "trend": "上升通道,回踩 MA20 后企稳",
    "volume_note": "量比 1.8,放量上攻",
    "key_levels": [
        {"type": "stabilize", "price": 100.5, "note": "企稳点:站住 100.5 不破可看多"},
        {"type": "pressure", "price": 115.0, "note": "上方压力位 115"},
    ],
    "advice": "回踩企稳点不破可轻仓关注,跌破需止损",
    "risk_warning": "若跌破 98 支撑位注意回调风险",
}, ensure_ascii=False)


class FakeLLM:
    name = "fake"

    def __init__(self, reply: str):
        self.reply = reply

    async def chat(self, system, user, temperature=0.3, max_retries=3):
        return self.reply

    async def chat_stream(self, system, user, temperature=0.3):
        for i in range(0, len(self.reply), 4):
            yield self.reply[i : i + 4]


class FailStreamLLM:
    """流中途抛错(模拟 LLM 流式输出时服务端异常)"""

    name = "failstream"

    async def chat(self, system, user, temperature=0.3, max_retries=3):
        return ""

    async def chat_stream(self, system, user, temperature=0.3):
        yield "前半段回答"
        raise RuntimeError("流中断")


class SlowLLM:
    """模拟 LLM 卡住不返回(测试超时预算降级)"""

    name = "slow"

    def __init__(self, delay: float = 5.0):
        self.delay = delay

    async def chat(self, system, user, temperature=0.3, max_retries=3):
        await asyncio.sleep(self.delay)
        return "{}"


def _async(value):
    async def _f(*args, **kwargs):
        return value

    return _f


def _kline(closes: list[float]) -> list[dict]:
    return [
        {
            "date": f"2026-01-{i + 1:02d}",
            "open": c * 0.99,
            "high": c * 1.02,
            "low": c * 0.98,
            "close": c,
            "volume": 10000,
        }
        for i, c in enumerate(closes)
    ]


def _mock_llm(monkeypatch, llm):
    monkeypatch.setattr(
        stock_advice_service.llm_settings_repo, "get_active", _async("deepseek")
    )
    monkeypatch.setattr(stock_advice_service.provider_factory, "get", _async(llm))


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


class TestAnalysisService:
    def test_success(self, monkeypatch):
        _mock_llm(monkeypatch, FakeLLM(VALID_AI_JSON))
        closes = [100 + i * 0.5 for i in range(60)]
        r = asyncio.run(stock_advice_service.get_stock_analysis("600519.SH", _kline(closes)))
        assert r["ai"] is not None
        assert r["ai"]["view"] == "bullish"
        assert r["indicators"]["latest_close"] == pytest.approx(129.5)

    def test_invalid_json_degrades(self, monkeypatch):
        _mock_llm(monkeypatch, FakeLLM("不是 JSON 的内容"))
        closes = [100 + i * 0.5 for i in range(60)]
        r = asyncio.run(stock_advice_service.get_stock_analysis("600519.SH", _kline(closes)))
        assert r["ai"] is None
        assert r["indicators"] is not None

    def test_markdown_wrapped_json_ok(self, monkeypatch):
        _mock_llm(monkeypatch, FakeLLM(f"```json\n{VALID_AI_JSON}\n```"))
        closes = [100 + i * 0.5 for i in range(60)]
        r = asyncio.run(stock_advice_service.get_stock_analysis("600519.SH", _kline(closes)))
        assert r["ai"]["view"] == "bullish"

    def test_invalid_view_degrades(self, monkeypatch):
        bad = json.dumps({"view": "moon", "trend": "x"}, ensure_ascii=False)
        _mock_llm(monkeypatch, FakeLLM(bad))
        r = asyncio.run(stock_advice_service.get_stock_analysis("600519.SH", _kline([100] * 40)))
        assert r["ai"] is None

    def test_no_llm_degrades(self, monkeypatch):
        _mock_llm(monkeypatch, None)
        r = asyncio.run(stock_advice_service.get_stock_analysis("600519.SH", _kline([100] * 40)))
        assert r["ai"] is None
        assert r["indicators"]["latest_close"] == 100.0

    def test_llm_timeout_degrades(self, monkeypatch):
        monkeypatch.setattr(stock_advice_service, "LLM_ANALYSIS_BUDGET", 0.05)
        _mock_llm(monkeypatch, SlowLLM(delay=1.0))
        r = asyncio.run(stock_advice_service.get_stock_analysis("600519.SH", _kline([100] * 40)))
        assert r["ai"] is None
        assert r["indicators"]["latest_close"] == 100.0


class TestChatService:
    def test_success(self, monkeypatch):
        _mock_llm(monkeypatch, FakeLLM("建议减仓一半。风险提示:以上仅供参考。"))
        closes = [100 + i * 0.5 for i in range(60)]
        answer = asyncio.run(
            stock_advice_service.ask_stock_question(
                "600519.SH", "我成本 120,现在该止损吗?", _kline(closes), position_cost=120.0
            )
        )
        assert "减仓" in answer

    def test_no_llm_raises(self, monkeypatch):
        _mock_llm(monkeypatch, None)
        with pytest.raises(StockAdviceUnavailable):
            asyncio.run(
                stock_advice_service.ask_stock_question(
                    "600519.SH", "能买吗?", _kline([100] * 40), position_cost=None
                )
            )

    def test_llm_timeout_raises(self, monkeypatch):
        monkeypatch.setattr(stock_advice_service, "LLM_QUESTION_BUDGET", 0.05)
        _mock_llm(monkeypatch, SlowLLM(delay=1.0))
        with pytest.raises(StockAdviceUnavailable):
            asyncio.run(
                stock_advice_service.ask_stock_question(
                    "600519.SH", "能买吗?", _kline([100] * 40), position_cost=None
                )
            )

    def test_llm_error_raises(self, monkeypatch):
        """LLM 报错(余额不足等)→ StockAdviceUnavailable(503),不冒 500"""

        class BoomLLM:
            name = "boom"

            async def chat(self, system, user, temperature=0.3, max_retries=3):
                raise RuntimeError("MiniMax 响应错误(1008): insufficient balance")

        _mock_llm(monkeypatch, BoomLLM())
        with pytest.raises(StockAdviceUnavailable):
            asyncio.run(
                stock_advice_service.ask_stock_question(
                    "600519.SH", "能买吗?", _kline([100] * 40), position_cost=None
                )
            )


def make_fake_client_class(responses: list[httpx.Response]) -> type:
    state = {"idx": 0}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def get(self, url, params=None, headers=None):
            i = state["idx"]
            state["idx"] += 1
            resp = responses[i] if i < len(responses) else httpx.Response(200, text="[]")
            if resp._request is None:
                resp._request = httpx.Request("GET", str(url))
            return resp

    return FakeAsyncClient


def _sina_rows(n: int = 120) -> list[dict]:
    return [
        {
            "day": f"2026-01-{i % 28 + 1:02d}",
            "open": "100", "high": "102", "low": "99", "close": "101", "volume": "10000",
        }
        for i in range(n)
    ]


class TestStockAPI:
    @pytest.fixture(autouse=True)
    def _clean_kline_cache(self, client):
        from app.db import async_session
        from app.models.orm import KlineCache
        from sqlalchemy import delete

        async def _do():
            async with async_session() as session:
                await session.execute(delete(KlineCache))
                await session.commit()

        asyncio.run(_do())
        yield

    def test_analysis_ok(self, client, monkeypatch):
        fake = make_fake_client_class([
            httpx.Response(200, text=f"cb({json.dumps(_sina_rows())});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake)
        _mock_llm(monkeypatch, FakeLLM(VALID_AI_JSON))
        r = client.get("/api/stock/600519.SH/analysis")
        assert r.status_code == 200
        body = r.json()
        assert body["ai"]["view"] == "bullish"
        assert body["indicators"]["latest_close"] == 101.0

    def test_analysis_llm_fail_still_200(self, client, monkeypatch):
        fake = make_fake_client_class([
            httpx.Response(200, text=f"cb({json.dumps(_sina_rows())});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake)
        _mock_llm(monkeypatch, FakeLLM("垃圾输出"))
        r = client.get("/api/stock/600519.SH/analysis")
        assert r.status_code == 200
        assert r.json()["ai"] is None

    def test_analysis_invalid_code(self, client):
        r = client.get("/api/stock/abc/analysis")
        assert r.status_code == 422

    def test_analysis_source_502(self, client, monkeypatch):
        fake = make_fake_client_class([httpx.Response(200, text="[]")])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake)
        r = client.get("/api/stock/600519.SH/analysis")
        assert r.status_code == 502
        assert r.json()["detail"]["code"] == "DATA_SOURCE_UNAVAILABLE"

    def test_chat_ok(self, client, monkeypatch):
        fake = make_fake_client_class([
            httpx.Response(200, text=f"cb({json.dumps(_sina_rows())});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake)
        _mock_llm(monkeypatch, FakeLLM("建议先观望。以上仅供参考。"))
        r = client.post("/api/stock/600519.SH/chat", json={"question": "现在能买吗?"})
        assert r.status_code == 200
        assert "观望" in r.json()["answer"]

    def test_chat_empty_question(self, client):
        r = client.post("/api/stock/600519.SH/chat", json={"question": "  "})
        assert r.status_code == 422

    def test_chat_no_llm_503(self, client, monkeypatch):
        fake = make_fake_client_class([
            httpx.Response(200, text=f"cb({json.dumps(_sina_rows())});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake)
        _mock_llm(monkeypatch, None)
        r = client.post("/api/stock/600519.SH/chat", json={"question": "能买吗?"})
        assert r.status_code == 503

    def test_chat_stream_ok(self, client, monkeypatch):
        fake = make_fake_client_class([
            httpx.Response(200, text=f"cb({json.dumps(_sina_rows())});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake)
        _mock_llm(monkeypatch, FakeLLM("建议先观望。以上仅供参考。"))
        r = client.post("/api/stock/600519.SH/chat/stream", json={"question": "能买吗?"})
        assert r.status_code == 200
        body = r.text
        texts = re.findall(r'"text": "([^"]*)"', body)
        assert "".join(texts) == "建议先观望。以上仅供参考。"
        assert body.strip().endswith('data: {"done": true}')

    def test_chat_stream_mid_error_sends_error_event(self, client, monkeypatch):
        fake = make_fake_client_class([
            httpx.Response(200, text=f"cb({json.dumps(_sina_rows())});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake)
        _mock_llm(monkeypatch, FailStreamLLM())
        r = client.post("/api/stock/600519.SH/chat/stream", json={"question": "能买吗?"})
        assert r.status_code == 200
        assert '"text": "前半段回答"' in r.text
        assert '"error"' in r.text
        assert 'data: {"done": true}' not in r.text

    def test_chat_stream_no_llm_503(self, client, monkeypatch):
        fake = make_fake_client_class([
            httpx.Response(200, text=f"cb({json.dumps(_sina_rows())});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake)
        _mock_llm(monkeypatch, None)
        r = client.post("/api/stock/600519.SH/chat/stream", json={"question": "能买吗?"})
        assert r.status_code == 503

    def test_chat_stream_invalid_code_422(self, client):
        r = client.post("/api/stock/abc/chat/stream", json={"question": "能买吗?"})
        assert r.status_code == 422
