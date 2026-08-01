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
                {"name": "minimax", "model": "abab6.5s-chat", "configured": False},
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
        r = client.get("/api/llm/settings")
        assert r.status_code == 200
        assert r.json()["active_provider"] == "deepseek"

    def test_switch_provider(self, client):
        r = client.post("/api/llm/settings", json={"active_provider": "minimax"})
        assert r.status_code == 200
        assert r.json()["active_provider"] == "minimax"

        # 持久化:再 GET 应仍是 minimax
        r = client.get("/api/llm/settings")
        assert r.json()["active_provider"] == "minimax"

        # 切回,避免影响其他测试
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
