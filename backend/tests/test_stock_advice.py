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
        self.last_system = None
        self.last_prompt = None
        self.last_messages: list[dict] | None = None

    def _record(self, system: str, messages: list[dict]) -> None:
        self.last_system = system
        self.last_messages = messages
        # 兼容老测试:last_prompt 取最后一条 user content
        for m in reversed(messages):
            if m.get("role") == "user":
                self.last_prompt = m.get("content")
                return
        self.last_prompt = None

    async def chat(self, system, user, temperature=0.3, max_retries=3):
        return await self.chat_with_messages(
            system, [{"role": "user", "content": user}], temperature, max_retries
        )

    async def chat_with_messages(self, system, messages, temperature=0.3, max_retries=3):
        self._record(system, messages)
        return self.reply

    async def chat_stream(self, system, user, temperature=0.3):
        async for piece in self.chat_stream_with_messages(
            system, [{"role": "user", "content": user}], temperature
        ):
            yield piece

    def chat_stream_with_messages(self, system, messages, temperature=0.3):
        self._record(system, messages)
        return self._stream_chunks()

    async def _stream_chunks(self):
        for i in range(0, len(self.reply), 4):
            yield self.reply[i : i + 4]


class FailStreamLLM:
    """流中途抛错(模拟 LLM 流式输出时服务端异常)"""

    name = "failstream"

    async def chat(self, system, user, temperature=0.3, max_retries=3):
        return ""

    async def chat_with_messages(self, system, messages, temperature=0.3, max_retries=3):
        return ""

    async def chat_stream(self, system, user, temperature=0.3):
        yield "前半段回答"
        raise RuntimeError("流中断")

    def chat_stream_with_messages(self, system, messages, temperature=0.3):
        async def _gen():
            yield "前半段回答"
            raise RuntimeError("流中断")
        return _gen()


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


class TestSectorScope:
    """作用域隔离:题材反查 + 作用域化系统提示词"""

    def test_match_hit(self):
        items = [{
            "name": "白酒", "netamount_yi": "2.3", "change_pct": "1.5",
            "top_stock": {"code": "600519.SH", "name": "贵州茅台"},
        }]
        r = stock_advice_service.match_sector_from_rank(items, "600519.SH")
        assert r == {"name": "白酒", "netamount_yi": 2.3, "change_pct": 1.5}

    def test_match_miss(self):
        assert stock_advice_service.match_sector_from_rank([], "600519.SH") is None
        items = [{"name": "白酒", "top_stock": {"code": "000001.SZ"}}]
        assert stock_advice_service.match_sector_from_rank(items, "600519.SH") is None

    def test_build_system_with_sector(self):
        sys = stock_advice_service.build_question_system(
            "600519.SH", "贵州茅台", {"name": "白酒", "netamount_yi": 2.3, "change_pct": 1.5}
        )
        assert "贵州茅台(600519.SH)" in sys
        assert "白酒" in sys
        assert "忽略" in sys  # 防规则绕过
        assert "只允许讨论" in sys

    def test_build_system_no_sector(self):
        sys = stock_advice_service.build_question_system("600519.SH", None, None)
        assert "600519.SH" in sys
        assert "「" not in sys  # 无题材命中,不出现题材占位
        assert "只允许讨论 600519.SH" in sys

    def test_prompt_injects_sector(self):
        p = stock_advice_service._build_question_prompt(
            "现在能买吗", _kline([100] * 40), None,
            {"name": "白酒", "netamount_yi": 2.3, "change_pct": 1.5},
            "600519.SH", "贵州茅台",
        )
        assert "股票: 贵州茅台(600519.SH)" in p
        assert '"stock_code": "600519.SH"' in p
        assert "白酒" in p
        assert "2.30" in p
        assert "+1.50%" in p

    def test_prompt_no_sector_ok(self):
        p = stock_advice_service._build_question_prompt(
            "现在能买吗", _kline([100] * 40), None, None, "600519.SH"
        )
        assert "股票: 600519.SH" in p
        assert '"stock_code": "600519.SH"' in p
        assert "题材" not in p


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

    def test_history_passed_as_messages(self, monkeypatch):
        """history 走 LLM 原生 messages 数组(ai→assistant),不拼字符串"""
        llm = FakeLLM("OK")
        _mock_llm(monkeypatch, llm)
        history = [
            {"role": "user", "text": "我成本 120,要止损吗?"},
            {"role": "ai", "text": "建议关注 117 支撑位。"},
        ]
        asyncio.run(
            stock_advice_service.ask_stock_question(
                "600519.SH",
                "那 117 破位该怎么办?",
                _kline([100] * 40),
                position_cost=120.0,
                history=history,
            )
        )
        assert llm.last_messages is not None
        # history 两条 + 当前 user 一条 = 3
        assert len(llm.last_messages) == 3
        assert llm.last_messages[0] == {"role": "user", "content": "我成本 120,要止损吗?"}
        assert llm.last_messages[1] == {"role": "assistant", "content": "建议关注 117 支撑位。"}
        assert llm.last_messages[2]["role"] == "user"
        # 当前 user 仍含 K线 + 持仓成本 + 当前问题
        assert "用户持仓成本" in llm.last_messages[2]["content"]
        assert "117 破位该怎么办?" in llm.last_messages[2]["content"]

    def test_history_truncated_to_max_turns(self, monkeypatch):
        """history 超 6 轮(12 条)时只保留最近 6 轮"""
        llm = FakeLLM("OK")
        _mock_llm(monkeypatch, llm)
        history = []
        for i in range(20):
            history.append({"role": "user", "text": f"问{i}"})
            history.append({"role": "ai", "text": f"答{i}"})
        asyncio.run(
            stock_advice_service.ask_stock_question(
                "600519.SH",
                "现在能买吗",
                _kline([100] * 40),
                position_cost=None,
                history=history,
            )
        )
        # 截到 6 轮 = 12 条 + 当前 user = 13;20 轮保留最后 6 轮(turn 15..20 → iter 14..19)
        assert llm.last_messages is not None
        assert len(llm.last_messages) == 13
        assert llm.last_messages[0]["content"] == "问14"
        assert llm.last_messages[-1]["content"] != ""
        assert "现在能买吗" in llm.last_messages[-1]["content"]

    def test_history_empty_or_none(self, monkeypatch):
        """history 为空/None 时,单条 user message(回归)"""
        llm = FakeLLM("OK")
        _mock_llm(monkeypatch, llm)
        for h in (None, [], [{"role": "user", "text": ""}], [{"role": "bogus", "text": "x"}]):
            llm.last_messages = None
            asyncio.run(
                stock_advice_service.ask_stock_question(
                    "600519.SH", "能买吗", _kline([100] * 40), history=h
                )
            )
            assert llm.last_messages is not None
            assert len(llm.last_messages) == 1
            assert llm.last_messages[0]["role"] == "user"

def test_history_stream_passes_messages(monkeypatch):
    """流式版同样走 messages 数组(history 注入 LLM)"""
    llm = FakeLLM("流式OK")
    _mock_llm(monkeypatch, llm)
    history = [{"role": "user", "text": "Q1"}, {"role": "ai", "text": "A1"}]
    async def _run():
        chunks = []
        async for piece in stock_advice_service.ask_stock_question_stream(
            "600519.SH", "Q2", _kline([100] * 40), history=history
        ):
            chunks.append(piece)
        return "".join(chunks)

    result = asyncio.run(_run())
    assert result == "流式OK"
    assert llm.last_messages is not None
    assert len(llm.last_messages) == 3
    assert llm.last_messages[1] == {"role": "assistant", "content": "A1"}


class TestParseLlmJson:
    """_parse_llm_json 鲁棒性:容忍 markdown 包裹 + 前置/后置自然语言 + 多个 JSON 块"""

    def test_pure_json(self):
        d = stock_advice_service._parse_llm_json('{"view": "bullish", "score": 80}')
        assert d == {"view": "bullish", "score": 80}

    def test_markdown_fenced(self):
        raw = "```json\n{\"view\": \"bearish\"}\n```"
        d = stock_advice_service._parse_llm_json(raw)
        assert d == {"view": "bearish"}

    def test_markdown_no_lang(self):
        raw = "```\n{\"view\": \"neutral\"}\n```"
        d = stock_advice_service._parse_llm_json(raw)
        assert d == {"view": "neutral"}

    def test_natural_language_prefix(self):
        """LLM 经常在 JSON 前面加"好的,以下是分析:"等自然语言"""
        raw = '好的,以下是分析:\n{"view": "bullish", "advice": "持有"}'
        d = stock_advice_service._parse_llm_json(raw)
        assert d == {"view": "bullish", "advice": "持有"}

    def test_natural_language_suffix(self):
        raw = '{"view": "bullish"}\n希望对您有帮助'
        d = stock_advice_service._parse_llm_json(raw)
        assert d == {"view": "bullish"}

    def test_multiple_json_blocks_picks_first(self):
        raw = '{"view": "bullish"}\n{"view": "bearish"}'
        d = stock_advice_service._parse_llm_json(raw)
        assert d == {"view": "bullish"}

    def test_nested_braces_inside_string(self):
        """字符串内的花括号不计入深度(防 LLM 输出 {"a": "b{c}d"} 时误截断)"""
        raw = '{"view": "text with {curly} inside", "ok": true}'
        d = stock_advice_service._parse_llm_json(raw)
        assert d["view"] == "text with {curly} inside"
        assert d["ok"] is True

    def test_escaped_quote_in_string(self):
        raw = '{"view": "he said \\"hi\\"", "ok": true}'
        d = stock_advice_service._parse_llm_json(raw)
        assert d["view"] == 'he said "hi"'

    def test_no_json_raises(self):
        with pytest.raises(ValueError, match="无 JSON 对象"):
            stock_advice_service._parse_llm_json("这是纯文本,没有 JSON")

    def test_bracket_unclosed_raises(self):
        with pytest.raises(ValueError, match="未闭合"):
            stock_advice_service._parse_llm_json('{"view": "bullish"')

    def test_array_not_object_rejected(self):
        """纯数组(无对象)被拒;数组中含对象时提取首个对象"""
        with pytest.raises(ValueError, match="无 JSON 对象"):
            stock_advice_service._parse_llm_json('[1, 2, 3]')
        # 数组包对象:提取首个对象 OK
        d = stock_advice_service._parse_llm_json('[{"view": "x"}, {"view": "y"}]')
        assert d == {"view": "x"}


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

    @pytest.fixture(autouse=True)
    def _no_net_sector(self, monkeypatch):
        """chat 端点的题材反查不触网(测试内可覆盖为命中场景)"""

        async def fake_get(*args, **kwargs):
            return []

        monkeypatch.setattr(stock_advice_service, "get_sector_fund_flow", fake_get)

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

    def test_chat_stream_sector_scope_injection(self, client, monkeypatch):
        """题材反查命中:系统提示词含作用域 + prompt 注入题材资金数据"""
        fake = make_fake_client_class([
            httpx.Response(200, text=f"cb({json.dumps(_sina_rows())});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake)
        llm = FakeLLM("建议先观望。以上仅供参考。")
        _mock_llm(monkeypatch, llm)

        async def fake_sector(*args, **kwargs):
            return [{
                "name": "白酒", "netamount_yi": "2.3", "change_pct": "1.5",
                "top_stock": {"code": "600519.SH", "name": "贵州茅台"},
            }]

        monkeypatch.setattr(stock_advice_service, "get_sector_fund_flow", fake_sector)

        r = client.post(
            "/api/stock/600519.SH/chat/stream",
            json={"question": "现在能买吗?", "stock_name": "贵州茅台"},
        )
        assert r.status_code == 200
        assert "贵州茅台(600519.SH)" in llm.last_system
        assert "白酒" in llm.last_system
        assert "只允许讨论" in llm.last_system
        assert "忽略" in llm.last_system  # 防注入规则
        assert "题材资金动向" in llm.last_prompt

    def test_chat_sector_miss_still_ok(self, client, monkeypatch):
        """题材反查未命中:作用域仅限股票本身,请求正常"""
        fake = make_fake_client_class([
            httpx.Response(200, text=f"cb({json.dumps(_sina_rows())});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake)
        llm = FakeLLM("建议先观望。以上仅供参考。")
        _mock_llm(monkeypatch, llm)
        r = client.post("/api/stock/600519.SH/chat", json={"question": "能买吗?"})
        assert r.status_code == 200
        assert "只允许讨论" in llm.last_system
        assert "「" not in llm.last_system
        assert "题材资金动向" not in llm.last_prompt

    def test_chat_with_history_injected(self, client, monkeypatch):
        """POST /chat 带 history → LLM 收到多轮 messages,ai→assistant 转换"""
        fake = make_fake_client_class([
            httpx.Response(200, text=f"cb({json.dumps(_sina_rows())});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake)
        llm = FakeLLM("OK")
        _mock_llm(monkeypatch, llm)
        r = client.post(
            "/api/stock/600519.SH/chat",
            json={
                "question": "现在能加仓吗?",
                "history": [
                    {"role": "user", "text": "我成本 120"},
                    {"role": "ai", "text": "目前被套,建议观望"},
                ],
            },
        )
        assert r.status_code == 200
        assert llm.last_messages is not None
        assert len(llm.last_messages) == 3
        assert llm.last_messages[0]["role"] == "user"
        assert llm.last_messages[1] == {"role": "assistant", "content": "目前被套,建议观望"}
        assert llm.last_messages[2]["role"] == "user"
        assert "现在能加仓吗?" in llm.last_messages[2]["content"]

    def test_chat_stream_with_history_injected(self, client, monkeypatch):
        """POST /chat/stream 带 history → 流式 messages 注入"""
        fake = make_fake_client_class([
            httpx.Response(200, text=f"cb({json.dumps(_sina_rows())});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake)
        llm = FakeLLM("流式OK")
        _mock_llm(monkeypatch, llm)
        r = client.post(
            "/api/stock/600519.SH/chat/stream",
            json={
                "question": "Q2",
                "history": [{"role": "user", "text": "Q1"}, {"role": "ai", "text": "A1"}],
            },
        )
        assert r.status_code == 200
        assert '"text": "流式OK"' in r.text
        assert llm.last_messages is not None
        assert llm.last_messages[1] == {"role": "assistant", "content": "A1"}
