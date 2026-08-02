"""P4.2a LLM 模块测试:sanitizer / prompts / deepseek(重试) / factory"""
import pytest

from app.core.prompts import (
    DIAGNOSE_SYSTEM,
    build_diagnose_user_prompt,
    build_trade_line,
)
from app.llm.base import LLMError
from app.llm.deepseek import DeepSeekClient
from app.llm.factory import ProviderFactory
from app.llm.sanitizer import bucket_shares, sanitize_for_llm
from app.repositories.llm_keys_repo import llm_keys_repo


class TestBucketShares:
    def test_below_100(self):
        assert bucket_shares(50) == "<100"

    def test_100_to_500(self):
        assert bucket_shares(100) == "100-500"

    def test_500_to_1000(self):
        assert bucket_shares(999) == "500-1000"

    def test_1000_to_5000(self):
        assert bucket_shares(5000 - 1) == "1000-5000"

    def test_5000_plus(self):
        assert bucket_shares(10000) == "5000+"


class TestSanitizer:
    TRADE = {
        "stock_code": "600519.SH",
        "stock_name": "贵州茅台",
        "action": "buy",
        "shares": 1200,
        "price": "1500.000",  # 不应出现在输出
        "trade_date": "2026-07-20",
    }

    def test_only_5_fields(self):
        out = sanitize_for_llm(self.TRADE, concentration_pct=12.345)
        assert set(out.keys()) == {
            "stock_code", "stock_name", "action", "shares_bucket",
            "trade_date", "concentration_pct",
        }

    def test_no_price_or_amount(self):
        out = sanitize_for_llm(self.TRADE)
        assert "price" not in out
        assert "1500.000" not in str(out)

    def test_shares_bucketed(self):
        out = sanitize_for_llm(self.TRADE)
        assert out["shares_bucket"] == "1000-5000"

    def test_concentration_formatted(self):
        out = sanitize_for_llm(self.TRADE, concentration_pct=12.345)
        assert out["concentration_pct"] == "12.3"

    def test_concentration_none(self):
        out = sanitize_for_llm(self.TRADE)
        assert out["concentration_pct"] == "未知"


class TestPrompts:
    def test_system_has_no_investment_advice(self):
        assert "以上不构成投资建议" in DIAGNOSE_SYSTEM

    def test_build_trade_line(self):
        sanitized = sanitize_for_llm({
            "stock_code": "600519.SH",
            "stock_name": "贵州茅台",
            "action": "buy",
            "shares": 1200,
            "trade_date": "2026-07-20",
        })
        line = build_trade_line(sanitized)
        assert "600519.SH" in line and "买入" in line and "1000-5000股" in line

    def test_build_trade_line_sell(self):
        sanitized = sanitize_for_llm({
            "stock_code": "000001.SZ", "stock_name": "平安银行",
            "action": "sell", "shares": 300, "trade_date": "2026-07-21",
        })
        assert "卖出" in build_trade_line(sanitized)

    def test_in_watchlist_phrasing(self):
        prompt = build_diagnose_user_prompt(
            "600519.SH 贵州茅台 买入 100-500股 @2026-07-20",
            "12.3", "近期买入较多", 85, {"集中度": 20}, True,
        )
        assert "在自选股中" in prompt

    def test_not_in_watchlist_phrasing(self):
        prompt = build_diagnose_user_prompt(
            "600519.SH 贵州茅台 买入 100-500股 @2026-07-20",
            "12.3", "近期买入较多", 85, {"集中度": 20}, False,
        )
        assert "不在自选股中" in prompt
        assert "加入自选股持续观察" in prompt

    def test_prompt_contains_score_and_breakdown(self):
        prompt = build_diagnose_user_prompt(
            "600519.SH 贵州茅台 买入 100-500股 @2026-07-20",
            "12.3", "近期买入较多", 85,
            {"集中度": 20, "价格合理性": 10}, True,
        )
        assert "85 分" in prompt
        assert "集中度 20分" in prompt and "价格合理性 10分" in prompt


class TestDeepSeekClient:
    def test_model_name(self):
        assert DeepSeekClient("sk-test").model_name == "deepseek-chat"
        assert DeepSeekClient("sk-test").name == "deepseek"

    @pytest.mark.asyncio
    async def test_chat_success(self, monkeypatch):
        class FakeResp:
            status_code = 200
            text = "{}"
            def json(self):
                return {"choices": [{"message": {"content": " 评语内容 "}}]}

        async def fake_post(self, url, headers=None, json=None):
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        client = DeepSeekClient("sk-test")
        out = await client.chat("system", "user")
        assert out == "评语内容"

    @pytest.mark.asyncio
    async def test_retry_then_success(self, monkeypatch):
        calls = {"n": 0}

        class FakeResp:
            status_code = 429
            text = "rate limited"
            def json(self):
                return {}

        async def fake_post(self, url, headers=None, json=None):
            calls["n"] += 1
            if calls["n"] < 3:
                return FakeResp()
            return type("Ok", (), {
                "status_code": 200, "text": "{}",
                "json": lambda self: {"choices": [{"message": {"content": "ok"}}]},
            })()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        # 缩短退避等待
        monkeypatch.setattr("app.llm.base.BACKOFF_BASE", 0.001)
        client = DeepSeekClient("sk-test")
        out = await client.chat("system", "user", max_retries=3)
        assert out == "ok"
        assert calls["n"] == 3

    @pytest.mark.asyncio
    async def test_all_retries_fail(self, monkeypatch):
        class FakeResp:
            status_code = 500
            text = "boom"
            def json(self):
                return {}

        async def fake_post(self, url, headers=None, json=None):
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        monkeypatch.setattr("app.llm.base.BACKOFF_BASE", 0.001)
        client = DeepSeekClient("sk-test")
        with pytest.raises(LLMError):
            await client.chat("system", "user", max_retries=3)

    @pytest.mark.asyncio
    async def test_network_error_retries(self, monkeypatch):
        import httpx
        calls = {"n": 0}

        async def fake_post(self, url, headers=None, json=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("no route")
            return type("Ok", (), {
                "status_code": 200, "text": "{}",
                "json": lambda self: {"choices": [{"message": {"content": "ok"}}]},
            })()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        monkeypatch.setattr("app.llm.base.BACKOFF_BASE", 0.001)
        client = DeepSeekClient("sk-test")
        out = await client.chat("system", "user", max_retries=3)
        assert out == "ok"

    @pytest.mark.asyncio
    async def test_auth_error_no_retry(self, monkeypatch):
        class FakeResp:
            status_code = 401
            text = "invalid key"
            def json(self):
                return {}

        calls = {"n": 0}

        async def fake_post(self, url, headers=None, json=None):
            calls["n"] += 1
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        client = DeepSeekClient("sk-bad")
        with pytest.raises(LLMError):
            await client.chat("system", "user", max_retries=3)
        assert calls["n"] == 1  # 401 不重试

    @pytest.mark.asyncio
    async def test_bad_response_format(self, monkeypatch):
        class FakeResp:
            status_code = 200
            text = "{}"
            def json(self):
                return {"choices": []}

        async def fake_post(self, url, headers=None, json=None):
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        client = DeepSeekClient("sk-test")
        with pytest.raises(LLMError):
            await client.chat("system", "user")


class TestMiniMaxClient:
    def test_meta(self):
        from app.llm.minimax import MiniMaxClient

        c = MiniMaxClient("sk-test")
        assert c.name == "minimax"
        assert c.model_name == "MiniMax-M2.5-highspeed"
        assert c.BASE_URL == "https://api.minimaxi.com/v1/chat/completions"
        assert c.VISION_MODEL == "MiniMax-M3"

    @pytest.mark.asyncio
    async def test_chat_success(self, monkeypatch):
        from app.llm.minimax import MiniMaxClient

        class FakeResp:
            status_code = 200
            text = "{}"

            def json(self):
                return {"choices": [{"message": {"content": " MiniMax 评语 "}}]}

        async def fake_post(self, url, headers=None, json=None):
            assert url.endswith("chat/completions")
            assert json["model"] == "MiniMax-M2.5-highspeed"
            assert json["reasoning_split"] is True
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        out = await MiniMaxClient("sk-test").chat("system", "user")
        assert out == "MiniMax 评语"

    @pytest.mark.asyncio
    async def test_chat_strips_think(self, monkeypatch):
        """M2.x thinking 不可关闭:即使 response 带 <think> 块也要剥离(双保险)"""
        from app.llm.minimax import MiniMaxClient, strip_think

        assert strip_think("<think>\n推理过程\n</think>\n\nOK,可以买入。") == "OK,可以买入。"
        assert strip_think("无思考块直接回答") == "无思考块直接回答"

        class FakeResp:
            status_code = 200
            text = "{}"

            def json(self):
                return {
                    "choices": [
                        {"message": {"content": "<think>思考中…</think>\n\n{\"view\": \"bullish\"}"}}
                    ]
                }

        async def fake_post(self, url, headers=None, json=None):
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        out = await MiniMaxClient("sk-test").chat("system", "user")
        assert out == '{"view": "bullish"}'

    @pytest.mark.asyncio
    async def test_chat_insufficient_balance_raises(self, monkeypatch):
        """MiniMax 余额不足:HTTP 200 + base_resp.status_code != 0(错误藏 body)"""
        from app.llm.minimax import MiniMaxClient

        class FakeResp:
            status_code = 200
            text = "{}"

            def json(self):
                return {
                    "choices": None,
                    "base_resp": {"status_code": 1008, "status_msg": "insufficient balance"},
                }

        async def fake_post(self, url, headers=None, json=None):
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        with pytest.raises(LLMError, match="1008|余额|insufficient"):
            await MiniMaxClient("sk-test").chat("system", "user")

    @pytest.mark.asyncio
    async def test_chat_empty_choices_raises(self, monkeypatch):
        """HTTP 200 但 choices 为空 → LLMError(非 NoneType 崩溃)"""
        from app.llm.minimax import MiniMaxClient

        class FakeResp:
            status_code = 200
            text = "{}"

            def json(self):
                return {"choices": None, "base_resp": {"status_code": 0, "status_msg": "ok"}}

        async def fake_post(self, url, headers=None, json=None):
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        with pytest.raises(LLMError, match="choices"):
            await MiniMaxClient("sk-test").chat("system", "user")


class TestDoubaoClient:
    def test_meta(self):
        from app.llm.doubao import DoubaoClient

        c = DoubaoClient("sk-test")
        assert c.name == "doubao"
        assert c.model_name == "doubao-pro-32k"
        assert c.BASE_URL == "https://ark.cn-beijing.volces.com/api/v3/chat/completions"

    @pytest.mark.asyncio
    async def test_chat_success(self, monkeypatch):
        from app.llm.doubao import DoubaoClient

        class FakeResp:
            status_code = 200
            text = "{}"

            def json(self):
                return {"choices": [{"message": {"content": "豆包评语"}}]}

        async def fake_post(self, url, headers=None, json=None):
            assert url.endswith("chat/completions")
            assert json["model"] == "doubao-pro-32k"
            return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
        out = await DoubaoClient("sk-test").chat("system", "user")
        assert out == "豆包评语"


class TestProviderFactory:
    def setup_method(self):
        ProviderFactory.clear_cache()

    @pytest.mark.asyncio
    async def test_missing_key_returns_none(self, monkeypatch):
        async def fake_get_decrypted(provider):
            return None
        monkeypatch.setattr(llm_keys_repo, "get_decrypted", fake_get_decrypted)
        assert await ProviderFactory.get("deepseek") is None

    @pytest.mark.asyncio
    async def test_unknown_provider_none(self):
        assert await ProviderFactory.get("unknown") is None

    @pytest.mark.asyncio
    async def test_caches_instance(self, monkeypatch):
        async def fake_get_decrypted(provider):
            return "sk-test"
        monkeypatch.setattr(llm_keys_repo, "get_decrypted", fake_get_decrypted)
        a = await ProviderFactory.get("deepseek")
        b = await ProviderFactory.get("deepseek")
        assert a is b
        assert a.name == "deepseek"

    @pytest.mark.asyncio
    async def test_available(self, monkeypatch):
        async def fake_list_status():
            return {"deepseek": True}
        monkeypatch.setattr(llm_keys_repo, "list_status", fake_list_status)
        items = await ProviderFactory.available()
        assert items[0]["name"] == "deepseek"
        assert items[0]["configured"] is True

    @pytest.mark.asyncio
    async def test_three_providers_registered(self, monkeypatch):
        """P4.2b/c 验收:minimax / doubao 注册进 factory"""
        async def fake_get_decrypted(provider):
            return "sk-test"
        monkeypatch.setattr(llm_keys_repo, "get_decrypted", fake_get_decrypted)

        ds = await ProviderFactory.get("deepseek")
        mm = await ProviderFactory.get("minimax")
        db = await ProviderFactory.get("doubao")
        assert ds.name == "deepseek"
        assert mm.name == "minimax"
        assert db.name == "doubao"

    @pytest.mark.asyncio
    async def test_available_lists_all(self, monkeypatch):
        async def fake_list_status():
            return {"deepseek": True, "minimax": False, "doubao": False}
        monkeypatch.setattr(llm_keys_repo, "list_status", fake_list_status)
        names = [i["name"] for i in await ProviderFactory.available()]
        assert names == ["deepseek", "minimax", "doubao"]
