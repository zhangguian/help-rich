"""P7.3 + P7.7 导出/导入 + round-trip 还原测试

- GET /api/admin/export:导出 7 表 JSON
- POST /api/admin/import (replace):清空后还原
- 导出 → 删库 → 导入 → 一致性测试
"""
import asyncio
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.transaction_repo import transaction_repo
from app.repositories.watchlist_repo import watchlist_repo


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    from app.db import async_session
    from app.models.orm import (
        LlmApiKey,
        LlmSettings,
        Position,
        ScreenshotRecord,
        StopLoss,
        TradeScore,
        Transaction,
        Watchlist,
    )
    from sqlalchemy import delete

    async def _do():
        async with async_session() as session:
            for m in (
                TradeScore,
                StopLoss,
                ScreenshotRecord,
                LlmApiKey,
                LlmSettings,
                Watchlist,
                Transaction,
                Position,
            ):
                await session.execute(delete(m))
            await session.commit()

    asyncio.run(_do())
    yield


async def _seed_sample():
    """种 2 笔交易 + 1 个自选股,验证 export/import round-trip"""
    await transaction_repo.create(
        stock_code="600519.SH", stock_name="贵州茅台",
        action="buy", shares=100, price="1450.000",
        trade_date=date(2026, 7, 1),
    )
    await transaction_repo.create(
        stock_code="000001.SZ", stock_name="平安银行",
        action="sell", shares=200, price="12.100",
        trade_date=date(2026, 7, 15),
    )
    await watchlist_repo.add(stock_code="300750.SZ", stock_name="宁德时代")


class TestExport:
    def test_export_structure(self, client):
        """导出包含 7 个表 + version/exported_at/tables"""
        asyncio.run(_seed_sample())
        r = client.get("/api/admin/export")
        assert r.status_code == 200
        data = r.json()
        assert data["version"] == "0.1.0"
        assert "exported_at" in data
        assert "transactions" in data["tables"]
        assert "watchlist" in data["tables"]
        assert data["tables"]["transactions"][0]["stock_code"] == "600519.SH"

    def test_export_excludes_encrypted_key(self, client):
        """LLM Key 不导出(敏感)"""
        r = client.put(
            "/api/llm/keys",
            json={"deepseek": "sk-test-1234567890", "minimax": "", "doubao": ""},
        )
        assert r.status_code == 200

        r = client.get("/api/admin/export")
        data = r.json()
        for row in data["tables"]["llm_api_keys"]:
            assert "encrypted_key" not in row
            assert "provider" in row


class TestImport:
    def test_import_requires_payload(self, client):
        r = client.post("/api/admin/import", json={"payload": {}, "mode": "replace"})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "INVALID_PAYLOAD"

    def test_import_unsupported_mode(self, client):
        r = client.post(
            "/api/admin/import", json={"payload": {"tables": {}}, "mode": "merge"}
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "UNSUPPORTED_MODE"


class TestRoundTrip:
    def test_export_then_import_roundtrip(self, client):
        """P7.7:导出 → 清库 → 导入 → 数据完全一致"""
        # 1. 种数据
        asyncio.run(_seed_sample())

        # 2. 导出
        r = client.get("/api/admin/export")
        assert r.status_code == 200
        exported = r.json()

        # 3. 清库(直接 DELETE,模拟"删库")
        from app.db import async_session
        from app.models.orm import (
            LlmApiKey,
            LlmSettings,
            Position,
            ScreenshotRecord,
            StopLoss,
            TradeScore,
            Transaction,
            Watchlist,
        )
        from sqlalchemy import delete as sqla_delete

        async def _wipe():
            async with async_session() as session:
                for m in (
                    TradeScore, StopLoss, ScreenshotRecord,
                    LlmApiKey, LlmSettings, Watchlist, Transaction, Position,
                ):
                    await session.execute(sqla_delete(m))
                await session.commit()

        asyncio.run(_wipe())

        # 4. 验证清空
        r = client.get("/api/admin/export")
        assert all(len(v) == 0 for v in r.json()["tables"].values())

        # 5. 导入
        r = client.post(
            "/api/admin/import",
            json={"payload": exported, "mode": "replace"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["imported"]["transactions"] == 2
        assert body["imported"]["watchlist"] == 1

        # 6. 再次导出对比(剔除动态字段)
        r2 = client.get("/api/admin/export")
        restored = r2.json()
        # 表内容对比(忽略 timestamp 微差)
        for name, rows in exported["tables"].items():
            assert name in restored["tables"]
            assert len(restored["tables"][name]) == len(rows), f"{name} 行数不一致"
            if rows and "id" in rows[0]:
                # 按 id 对比
                a = {r["id"]: r for r in rows if "id" in r}
                b = {r["id"]: r for r in restored["tables"][name] if "id" in r}
                for k in a:
                    for kk, vv in a[k].items():
                        if kk in {"updated_at", "uploaded_at", "confirmed_at", "last_triggered_at"}:
                            continue
                        assert b[k].get(kk) == vv, f"{name}.{k}.{kk} 不一致"


class TestBackup:
    def test_backup_writes_file(self, client, tmp_path=None):
        """P7.9:POST /admin/backup 写文件"""
        r = client.post("/api/admin/backup")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "pre-" in body["path"]
        assert body["size_bytes"] > 0

    def test_health(self, client):
        r = client.get("/api/admin/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}