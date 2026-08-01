"""P8 截图识别测试

- text_extract:持仓/流水/自选股三种布局解析
- screenshot_repo:pending 列表 + confirm/reject
- screenshot_service:OCR 失败降级 / LLM 解析 / 粘贴 JSON / 确认入库
- API:upload 类型校验 / parse-paste / confirm / reject
"""
import asyncio
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ocr.text_extract import extract_items
from app.repositories.screenshot_repo import screenshot_repo
from app.services.screenshot_service import ScreenshotError, screenshot_service


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _db_tables(client):
    """建表(lifespan create_all)+ 每个测试前清空 screenshot_records + positions"""
    from app.db import async_session
    from app.models.orm import Position, ScreenshotRecord
    from sqlalchemy import delete

    async def _clean():
        async with async_session() as session:
            await session.execute(delete(ScreenshotRecord))
            await session.execute(delete(Position))
            await session.commit()

    asyncio.run(_clean())
    yield


class TestTextExtract:
    def test_position_layout(self):
        text = """我的持仓
        600519 贵州茅台 100 1450.000 145000.00
        000001 平安银行 500 11.630 5815.00"""
        out = extract_items(text)
        assert out["screenshot_type"] == "position"
        assert len(out["items"]) == 2
        assert out["items"][0]["stock_code"] == "600519"
        assert out["items"][0]["shares"] == 100
        assert out["items"][1]["shares"] == 500

    def test_transaction_layout(self):
        text = """成交记录
        2026-07-20 600519 贵州茅台 买入 100 1450.000
        2026-07-21 000001 平安银行 卖出 300 11.800"""
        out = extract_items(text)
        assert out["screenshot_type"] == "transactions"
        assert len(out["items"]) == 2
        first = out["items"][0]
        assert first["action"] == "buy"
        assert first["trade_date"] == "2026-07-20"
        assert out["items"][1]["action"] == "sell"

    def test_watchlist_layout(self):
        text = """我的自选
        600519 贵州茅台
        300750 宁德时代"""
        out = extract_items(text)
        assert out["screenshot_type"] == "watchlist"
        assert len(out["items"]) == 2
        assert out["items"][0]["stock_code"] == "600519"
        assert out["items"][0]["stock_name"] == "贵州茅台"

    def test_empty_text(self):
        out = extract_items("")
        assert out["items"] == []
        assert out["confidence"] == 0.0

    def test_no_records_low_confidence(self):
        out = extract_items("一些没有股票代码的文本\n乱七八糟")
        assert out["items"] == []
        assert out["confidence"] == 0.0
        assert "JSON" in out["notes"]

    def test_confidence_ratio(self):
        text = """我的持仓
        600519 贵州茅台 100 1450.000 145000.00
        随便一行"""
        out = extract_items(text)
        assert len(out["items"]) == 1
        assert 0 < out["confidence"] < 1


class TestScreenshotRepo:
    def test_create_and_list_pending(self, client):
        record = asyncio.run(screenshot_repo.create(
            parsed_items=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
            screenshot_type="watchlist",
            source="manual_paste",
        ))
        pending = asyncio.run(screenshot_repo.list_pending())
        assert any(r.id == record.id for r in pending)
        parsed = json.loads(record.parsed_items)
        assert parsed[0]["stock_code"] == "600519"

    def test_mark_confirmed(self, client):
        record = asyncio.run(screenshot_repo.create(
            parsed_items=[{"stock_code": "000001", "stock_name": "平安银行"}],
            screenshot_type="watchlist",
        ))
        asyncio.run(screenshot_repo.mark_confirmed(record.id))
        got = asyncio.run(screenshot_repo.get_by_id(record.id))
        assert got.status == "confirmed"
        assert got.confirmed_at is not None
        pending = asyncio.run(screenshot_repo.list_pending())
        assert all(r.id != record.id for r in pending)

    def test_mark_rejected(self, client):
        record = asyncio.run(screenshot_repo.create(
            parsed_items=[{"stock_code": "000001"}], screenshot_type="watchlist",
        ))
        asyncio.run(screenshot_repo.mark_rejected(record.id))
        got = asyncio.run(screenshot_repo.get_by_id(record.id))
        assert got.status == "rejected"


class TestScreenshotService:
    def test_parse_from_paste_success(self, client):
        out = asyncio.run(screenshot_service.parse_from_paste(
            json.dumps({
                "screenshot_type": "transactions",
                "items": [{"stock_code": "600519", "stock_name": "贵州茅台",
                           "action": "buy", "shares": 100, "price": "1450.000",
                           "trade_date": "2026-07-20"}],
            })
        ))
        assert out["record_id"] > 0
        assert out["items"][0]["action"] == "buy"

    def test_parse_from_paste_invalid_json(self):
        with pytest.raises(ScreenshotError) as exc:
            asyncio.run(screenshot_service.parse_from_paste("{bad json"))
        assert exc.value.code == "INVALID_JSON"

    def test_parse_from_paste_missing_items(self):
        with pytest.raises(ScreenshotError):
            asyncio.run(screenshot_service.parse_from_paste('{"type": "x"}'))

    def test_parse_from_paste_guesses_type(self):
        out = asyncio.run(screenshot_service.parse_from_paste(
            json.dumps({"items": [{"stock_code": "600519", "action": "buy",
                                   "shares": 1, "price": "1", "trade_date": "2026-07-20"}]})
        ))
        assert out["screenshot_type"] == "transactions"

    def test_parse_from_image_ocr_failure_falls_back(self, monkeypatch):
        """OCR 失败:vision LLM(MiniMax)接管"""
        async def fake_extract(path):
            raise RuntimeError("paddle not available")

        class FakeVisionLLM:
            name = "minimax"
            supports_vision = True

            async def chat_with_image(self, system, user, image, **kw):
                assert image.startswith("data:image/png;base64,")
                return json.dumps({
                    "screenshot_type": "transactions",
                    "items": [{
                        "stock_code": "600519.SH",
                        "stock_name": "贵州茅台",
                        "action": "buy",
                        "shares": 100,
                        "price": "1450.000",
                        "trade_date": "2026-07-20",
                    }],
                    "confidence": 0.85,
                    "notes": "vision model 识别",
                })

        async def fake_get(name):
            assert name == "minimax"
            return FakeVisionLLM()

        monkeypatch.setattr(
            "app.services.screenshot_service.paddle_client.extract_text", fake_extract
        )
        monkeypatch.setattr(
            "app.services.screenshot_service.provider_factory.get", fake_get
        )
        monkeypatch.setattr(
            "app.services.screenshot_service.llm_settings_repo.get_active",
            lambda: asyncio.Future() or "minimax",
        )

        async def fake_active():
            return "minimax"

        monkeypatch.setattr(
            "app.services.screenshot_service.llm_settings_repo.get_active", fake_active
        )

        out = asyncio.run(screenshot_service.parse_from_image(
            b"\x89PNG-rgb-image-bytes",
            "x.png",
        ))
        assert out["items"][0]["stock_code"] == "600519.SH"
        # source 标记为 vision_llm
        record = asyncio.run(screenshot_repo.get_by_id(out["record_id"]))
        assert record.source == "vision_llm"

    def test_ocr_failure_no_vision_llm(self, client, monkeypatch):
        """OCR 失败 + 当前 LLM 不支持视觉 → 422 OCR_FAILED(用户需切到 paste)"""
        async def fake_extract(path):
            raise RuntimeError("paddle not available")

        class FakeTextLLM:
            name = "deepseek"
            supports_vision = False

        async def fake_get(name):
            return FakeTextLLM()

        async def fake_active():
            return "deepseek"

        monkeypatch.setattr(
            "app.services.screenshot_service.paddle_client.extract_text", fake_extract
        )
        monkeypatch.setattr(
            "app.services.screenshot_service.provider_factory.get", fake_get
        )
        monkeypatch.setattr(
            "app.services.screenshot_service.llm_settings_repo.get_active", fake_active
        )

        with pytest.raises(ScreenshotError) as exc:
            asyncio.run(screenshot_service.parse_from_image(b"fake", "x.jpg"))
        assert exc.value.code == "OCR_FAILED"
        assert "deepseek 不支持视觉识别" in str(exc.value)

    def test_parse_from_image_local_rules(self, monkeypatch):
        """本地规则直接命中:不调 LLM,不写 raw_response"""
        async def fake_extract(path):
            return "我的持仓\n600519 贵州茅台 100 1450.000 145000.00"

        monkeypatch.setattr(
            "app.services.screenshot_service.paddle_client.extract_text", fake_extract
        )
        called = {"llm": False}

        class FakeLLM:
            async def chat(self, *a, **kw):
                called["llm"] = True
                return "{}"

        async def fake_get(name):
            return FakeLLM()

        monkeypatch.setattr(
            "app.services.screenshot_service.provider_factory.get", fake_get
        )
        out = asyncio.run(screenshot_service.parse_from_image(b"img", "x.png"))
        assert called["llm"] is False
        assert out["items"][0]["stock_code"] == "600519"
        assert out["items"][0]["shares"] == 100

    def test_parse_from_image_llm_fallback(self, monkeypatch):
        """本地规则未命中 → LLM 解析"""
        async def fake_extract(path):
            return "乱序文本 600519 无规则可循"

        monkeypatch.setattr(
            "app.services.screenshot_service.paddle_client.extract_text", fake_extract
        )

        class FakeLLM:
            async def chat(self, system, user, **kw):
                assert "OCR" in system
                return json.dumps({
                    "screenshot_type": "position",
                    "items": [{"stock_code": "600519", "stock_name": "贵州茅台",
                               "shares": 100, "cost_price": "1450.000",
                               "market_value": "145000.00"}],
                    "confidence": 0.8,
                })

        async def fake_get(name):
            return FakeLLM()

        monkeypatch.setattr(
            "app.services.screenshot_service.provider_factory.get", fake_get
        )
        out = asyncio.run(screenshot_service.parse_from_image(b"img", "x.png"))
        assert out["items"][0]["stock_code"] == "600519"
        assert out["screenshot_type"] == "position"

    def test_confirm_writes_transactions(self, monkeypatch):
        from app.repositories.transaction_repo import transaction_repo

        record = asyncio.run(screenshot_repo.create(
            parsed_items=[], screenshot_type="transactions",
        ))
        items = [{
            "stock_code": "600519.SH", "stock_name": "贵州茅台", "action": "buy",
            "shares": 100, "price": "1450.000", "trade_date": "2026-07-20",
        }]
        asyncio.run(screenshot_service.confirm(record.id, items, "transactions"))

        got = asyncio.run(screenshot_repo.get_by_id(record.id))
        assert got.status == "confirmed"
        # 交易真的入库了
        trades, total = asyncio.run(transaction_repo.list_all(limit=100))
        assert any(t.stock_code == "600519.SH" and t.shares == 100 for t in trades)

    def test_confirm_writes_watchlist(self):
        from app.repositories.watchlist_repo import watchlist_repo

        record = asyncio.run(screenshot_repo.create(
            parsed_items=[], screenshot_type="watchlist",
        ))
        items = [{"stock_code": "300750.SZ", "stock_name": "宁德时代"}]
        asyncio.run(screenshot_service.confirm(record.id, items, "watchlist"))

        assert asyncio.run(watchlist_repo.contains("300750.SZ"))

    def test_confirm_holdings_imports_position(self):
        """holdings 类型:v0.4.0 起导入持仓表(持仓主数据)"""
        record = asyncio.run(screenshot_repo.create(
            parsed_items=[{"stock_code": "001896.SZ"}], screenshot_type="holdings",
        ))
        items = [
            {"stock_code": "001896.SZ", "stock_name": "豫能控股", "shares": 300,
             "price": "18.500", "current_price": "12.020",
             "profit": -1944.06, "profit_ratio": -35.027},
        ]
        asyncio.run(screenshot_service.confirm(record.id, items, "holdings"))
        # 记录确认成功
        got = asyncio.run(screenshot_repo.get_by_id(record.id))
        assert got.status == "confirmed"
        # 持仓真的入库了
        from app.services.position_service import get_position
        p = asyncio.run(get_position("001896.SZ"))
        assert p is not None
        assert p.shares == 300
        assert p.avg_cost == Decimal("18.500")

    def test_confirm_position_imports_position(self):
        """position 类型:同 holdings,导入持仓表"""
        record = asyncio.run(screenshot_repo.create(
            parsed_items=[], screenshot_type="position",
        ))
        asyncio.run(screenshot_service.confirm(
            record.id, [{"stock_code": "600519.SH", "stock_name": "贵州茅台",
                         "shares": 100, "cost_price": "1450.000"}], "position"
        ))
        from app.services.position_service import get_position
        p = asyncio.run(get_position("600519.SH"))
        assert p is not None
        assert p.shares == 100
        assert p.avg_cost == Decimal("1450.000")

    def test_confirm_position_missing_shares_rejected(self):
        """缺 shares 仍拒绝(MISSING_FIELD)"""
        record = asyncio.run(screenshot_repo.create(
            parsed_items=[], screenshot_type="position",
        ))
        with pytest.raises(ScreenshotError) as exc:
            asyncio.run(screenshot_service.confirm(
                record.id, [{"stock_code": "600519.SH"}], "position"
            ))
        assert exc.value.code == "MISSING_FIELD"

    def test_parse_paste_holdings_keeps_type(self):
        """parse_paste:holdings 类型原样存储(不做归一化)"""
        from app.repositories.screenshot_repo import screenshot_repo as _repo

        raw = json.dumps({
            "screenshot_type": "holdings",
            "items": [{"stock_code": "001896.SZ", "stock_name": "豫能控股",
                       "shares": 300, "price": "18.500"}],
        })
        out = asyncio.run(screenshot_service.parse_from_paste(raw))
        assert out["screenshot_type"] == "holdings"
        record = asyncio.run(_repo.get_by_id(out["record_id"]))
        assert record.screenshot_type == "holdings"

    def test_reject_deletes_record(self):
        record = asyncio.run(screenshot_repo.create(
            parsed_items=[{"stock_code": "600519"}], screenshot_type="position",
        ))
        asyncio.run(screenshot_service.reject(record.id))
        got = asyncio.run(screenshot_repo.get_by_id(record.id))
        assert got.status == "rejected"


class TestScreenshotAPI:
    def test_upload_unsupported_type(self, client):
        r = client.post(
            "/api/screenshot/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert r.status_code == 415
        assert r.json()["detail"]["code"] == "UNSUPPORTED_TYPE"

    def test_parse_paste_success(self, client):
        r = client.post(
            "/api/screenshot/parse-paste",
            json={"raw_json": json.dumps({
                "screenshot_type": "watchlist",
                "items": [{"stock_code": "600519.SH", "stock_name": "贵州茅台"}],
            })},
        )
        assert r.status_code == 200
        assert r.json()["items"][0]["stock_code"] == "600519.SH"

    def test_parse_paste_invalid(self, client):
        r = client.post(
            "/api/screenshot/parse-paste", json={"raw_json": "{bad"}
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "INVALID_JSON"

    def test_pending_list(self, client):
        asyncio.run(screenshot_repo.create(
            parsed_items=[{"stock_code": "600519.SH"}], screenshot_type="position",
            source="manual_paste",
        ))
        r = client.get("/api/screenshot/pending")
        assert r.status_code == 200
        assert any(i["items"][0]["stock_code"] == "600519.SH" for i in r.json()["items"])

    def test_confirm_not_found(self, client):
        r = client.post("/api/screenshot/99999/confirm",
                        json={"items": [{"stock_code": "1"}], "screenshot_type": "position"})
        assert r.status_code == 404

    def test_confirm_and_reject_flow(self, client):
        record = asyncio.run(screenshot_repo.create(
            parsed_items=[], screenshot_type="watchlist",
        ))
        r = client.post(
            f"/api/screenshot/{record.id}/confirm",
            json={"items": [{"stock_code": "000001.SZ", "stock_name": "平安银行"}],
                  "screenshot_type": "watchlist"},
        )
        assert r.status_code == 200
        # 重复确认 → 409
        r2 = client.post(
            f"/api/screenshot/{record.id}/confirm",
            json={"items": [{"stock_code": "000001.SZ", "stock_name": "平安银行"}],
                  "screenshot_type": "watchlist"},
        )
        assert r2.status_code == 409

        record2 = asyncio.run(screenshot_repo.create(
            parsed_items=[], screenshot_type="position",
        ))
        r3 = client.post(f"/api/screenshot/{record2.id}/reject")
        assert r3.status_code == 200
        got = asyncio.run(screenshot_repo.get_by_id(record2.id))
        assert got.status == "rejected"

    def test_confirm_empty_items_422(self, client):
        record = asyncio.run(screenshot_repo.create(
            parsed_items=[], screenshot_type="position",
        ))
        r = client.post(
            f"/api/screenshot/{record.id}/confirm",
            json={"items": [], "screenshot_type": "position"},
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "EMPTY_ITEMS"
