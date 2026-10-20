"""P4.2e Provider API 测试

- GET  /api/llm/providers:provider 列表(名称/模型/配置状态)
- GET/POST /api/llm/settings:激活 provider 读取与切换
- POST /api/llm/test:真实调用升级(未配置 Key → 失败;调用成功 → ok)
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.llm_keys_repo import llm_keys_repo
from app.repositories.llm_settings_repo import llm_settings_repo
from app.services.llm_test_service import llm_test_service


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


class TestProvidersEndpoint:
    def test_lists_all_providers(self, client, monkeypatch):
        async def fake_available():
            return [
                {"name": "deepseek", "model": "deepseek-chat", "configured": True},
                {"name": "minimax", "model": "MiniMax-M2.5-highspeed", "configured": False},
                {"name": "doubao", "model": "doubao-pro-32k", "configured": False},
            ]

        monkeypatch.setattr(
            "app.api.llm_keys.provider_factory.available", fake_available
        )
        r = client.get("/api/llm/providers")
        assert r.status_code == 200
        items = r.json()["items"]
        assert [i["name"] for i in items] == ["deepseek", "minimax", "doubao"]
        assert items[0]["model"] == "deepseek-chat"
        assert items[0]["configured"] is True


class TestSettingsEndpoint:
    def test_get_default_deepseek(self, client):
        """未设置过时回落 deepseek(与历史默认一致)。

        显式先切一次,验证"读-改-写"链路;首次读取的默认值由
        `LlmSettingsRepository.get_active` 在无行时自愈,这里不直接断言
        空表场景(那是仓储单测的职责)。
        """
        client.post("/api/llm/settings", json={"active_provider": "deepseek"})
        r = client.get("/api/llm/settings")
        assert r.status_code == 200
        assert r.json()["active_provider"] == "deepseek"

    def test_switch_provider(self, client):
        """切换激活 provider 并验证持久化。

        这是一个**修改全局状态**的用例,因此不假设初始状态:
        显式先设成 deepseek,再切到 minimax 验证,finally 里复位。
        否则一旦前面某个用例把 provider 留在别处,本用例就会莫名失败。
        """
        client.post("/api/llm/settings", json={"active_provider": "deepseek"})
        try:
            r = client.post("/api/llm/settings", json={"active_provider": "minimax"})
            assert r.status_code == 200
            assert r.json()["active_provider"] == "minimax"

            # 持久化:再 GET 应仍是 minimax
            r = client.get("/api/llm/settings")
            assert r.json()["active_provider"] == "minimax"

            # 可切回 doubao 再确认一次(往返一致)
            client.post("/api/llm/settings", json={"active_provider": "doubao"})
            assert client.get("/api/llm/settings").json()["active_provider"] == "doubao"
        finally:
            # 复位,避免影响其他测试
            client.post("/api/llm/settings", json={"active_provider": "deepseek"})

    def test_invalid_provider_400(self, client):
        r = client.post("/api/llm/settings", json={"active_provider": "chatgpt"})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "INVALID_PROVIDER"


class TestTestEndpoint:
    def test_no_key_fails(self, client, monkeypatch):
        async def fake_get_decrypted(provider):
            return None

        monkeypatch.setattr(llm_keys_repo, "get_decrypted", fake_get_decrypted)
        r = client.post("/api/llm/test", json={"provider": "deepseek"})
        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert "未配置 Key" in r.json()["error"]

    def test_real_call_success(self, client, monkeypatch):
        async def fake_get_decrypted(provider):
            return "sk-test"

        class FakeLLM:
            name = "deepseek"

            async def chat(self, system, user, temperature=0.3, max_retries=1):
                assert "连接测试" in system
                return "OK"

        async def fake_factory_get(name):
            return FakeLLM()

        monkeypatch.setattr(llm_keys_repo, "get_decrypted", fake_get_decrypted)
        monkeypatch.setattr(
            "app.services.llm_test_service.provider_factory.get", fake_factory_get
        )
        r = client.post("/api/llm/test", json={"provider": "deepseek"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["latency_ms"] >= 0

    def test_llm_error_reported(self, client, monkeypatch):
        async def fake_get_decrypted(provider):
            return "sk-test"

        from app.llm.base import LLMError

        class BrokenLLM:
            name = "deepseek"

            async def chat(self, system, user, temperature=0.3, max_retries=1):
                raise LLMError("HTTP 401: invalid key")

        async def fake_factory_get(name):
            return BrokenLLM()

        monkeypatch.setattr(llm_keys_repo, "get_decrypted", fake_get_decrypted)
        monkeypatch.setattr(
            "app.services.llm_test_service.provider_factory.get", fake_factory_get
        )
        r = client.post("/api/llm/test", json={"provider": "deepseek"})
        assert r.json()["ok"] is False
        assert "401" in r.json()["error"]
