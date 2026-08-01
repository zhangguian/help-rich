"""P4.2f 多 Provider A/B 对比 fixture 测试

A/B 对比的前提:同样输入下 3 个 provider 收到的 prompt 完全一致(差异只来自模型本身)。
验证:
1. 3 个 client 发出的 HTTP body 中 messages 一致(脱敏数据相同)
2. system prompt 相同且含免责声明
3. 只有 model 字段按 provider 不同(符合预期)
"""
import pytest

from app.core.prompts import DIAGNOSE_SYSTEM, build_diagnose_user_prompt, build_trade_line
from app.llm.deepseek import DeepSeekClient
from app.llm.doubao import DoubaoClient
from app.llm.minimax import MiniMaxClient
from app.llm.sanitizer import sanitize_for_llm


@pytest.fixture()
def ab_fixture():
    """A/B 对比共享输入(脱敏后为 6 字段,含分桶与占比)"""
    trade = {
        "stock_code": "600519.SH",
        "stock_name": "贵州茅台",
        "action": "buy",
        "shares": 1200,
        "price": "1500.000",
        "trade_date": "2026-07-20",
    }
    sanitized = sanitize_for_llm(trade, concentration_pct=12.345)
    trade_line = build_trade_line(sanitized)
    user_prompt = build_diagnose_user_prompt(
        trade_line=trade_line,
        concentration_pct=sanitized["concentration_pct"],
        recent_summary="600519.SH buy 100股@2026-07-10",
        score=85,
        breakdown={"集中度": 20, "价格合理性": 15},
        is_in_watchlist=True,
    )
    return DIAGNOSE_SYSTEM, user_prompt


def _capture(monkeypatch):
    """捕获 3 个 provider 发出的 HTTP 请求 body"""
    captured = {}

    async def fake_post(self, url, headers=None, json=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers

        class FakeResp:
            status_code = 200
            text = "{}"

            def json(self):
                return {"choices": [{"message": {"content": "评语"}}]}

        return FakeResp()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    return captured


@pytest.mark.asyncio
async def test_three_providers_receive_identical_prompt(monkeypatch, ab_fixture):
    system, user = ab_fixture
    captured = _capture(monkeypatch)

    for cls in (DeepSeekClient, MiniMaxClient, DoubaoClient):
        await cls("sk-test").chat(system, user)
        body = captured["json"]
        # 3 个 provider 的 messages 完全一致(含 system 免责声明)
        assert body["messages"] == [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        assert body["temperature"] == 0.3


@pytest.mark.asyncio
async def test_model_differs_per_provider(monkeypatch, ab_fixture):
    """A/B 唯一变量:model 字段"""
    system, user = ab_fixture
    captured = _capture(monkeypatch)

    models = {}
    for cls in (DeepSeekClient, MiniMaxClient, DoubaoClient):
        await cls("sk-test").chat(system, user)
        models[cls.name] = captured["json"]["model"]

    assert models == {
        "deepseek": "deepseek-chat",
        "minimax": "abab6.5s-chat",
        "doubao": "doubao-pro-32k",
    }


@pytest.mark.asyncio
async def test_system_prompt_has_disclaimer(monkeypatch, ab_fixture):
    system, user = ab_fixture
    assert "以上不构成投资建议" in system

    captured = _capture(monkeypatch)
    await DeepSeekClient("sk-test").chat(system, user)
    assert "以上不构成投资建议" in captured["json"]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_user_prompt_contains_scored_fields(monkeypatch, ab_fixture):
    """A/B 对比的输入包含完整诊断上下文(评语才可比)"""
    system, user = ab_fixture
    assert "85 分" in user
    assert "集中度 20分" in user
    assert "12.3" in user  # 集中度百分比(脱敏 1 位小数)
    assert "贵州茅台" in user
