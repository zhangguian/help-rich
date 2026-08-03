"""K 线真实数据源测试(guide §3.2 新浪)

- 测试代码用 fake httpx.AsyncClient 拦截网络(测试基础设施,**非生产 mock**)
- 验证解析 + 缓存 + 错误处理
- 生产代码无任何 mock,失败抛 KLineSourceUnavailable
"""
import asyncio
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import kline_service
from app.services.kline_service import (
    KLineSourceUnavailable,
    _to_sina_scale,
    _to_sina_symbol,
    fetch_intraday,
    fetch_klines,
)
from sqlalchemy import delete


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    from app.db import async_session
    from app.models.orm import KlineCache

    async def _do():
        async with async_session() as session:
            await session.execute(delete(KlineCache))
            await session.commit()

    asyncio.run(_do())
    yield


def make_fake_client_class(responses: list[httpx.Response]) -> type:
    """构造一个 fake httpx.AsyncClient(测试专用),按调用顺序返回 responses"""
    state = {"idx": 0, "calls": []}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self._args = args
            self._kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def get(self, url, params=None, headers=None):
            state["calls"].append({"url": str(url), "params": params, "headers": headers})
            i = state["idx"]
            state["idx"] += 1
            if i >= len(responses):
                resp = httpx.Response(200, text="[]")
            else:
                resp = responses[i]
            # raise_for_status 需要 _request 属性
            if resp._request is None:
                resp._request = httpx.Request("GET", str(url))
            return resp

    return FakeAsyncClient, state


class TestSymbolConversion:
    def test_to_sina_symbol(self):
        assert _to_sina_symbol("600519.SH") == "sh600519"
        assert _to_sina_symbol("000001.SZ") == "sz000001"
        assert _to_sina_symbol("830799.BJ") == "bj830799"

    def test_to_sina_scale(self):
        assert _to_sina_scale("daily") == 240
        assert _to_sina_scale("60min") == 60
        assert _to_sina_scale("5min") == 5
        assert _to_sina_scale("unknown") == 240


class TestSinaKline:
    def test_parse_success(self, monkeypatch):
        rows = [
            {"day": "2026-07-30", "open": "1500", "high": "1530", "low": "1495", "close": "1520", "volume": "28000"},
            {"day": "2026-07-31", "open": "1520", "high": "1550", "low": "1510", "close": "1540", "volume": "30000"},
        ]
        fake_class, state = make_fake_client_class([
            httpx.Response(200, text=f"callback_x({json.dumps(rows, ensure_ascii=False)});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        result = asyncio.run(kline_service._fetch_sina_kline("600519.SH", "daily", 60))
        assert len(result) == 2
        assert result[0]["date"] == "2026-07-30"
        assert result[0]["close"] == "1520"
        assert result[1]["volume"] == 30000
        assert state["calls"][0]["params"]["symbol"] == "sh600519"

    def test_invalid_jsonp_raises(self, monkeypatch):
        fake_class, _ = make_fake_client_class([httpx.Response(200, text="not jsonp")])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        with pytest.raises(KLineSourceUnavailable):
            asyncio.run(kline_service._fetch_sina_kline("600519.SH", "daily", 60))

    def test_empty_response_raises(self, monkeypatch):
        fake_class, _ = make_fake_client_class([httpx.Response(200, text="[]")])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        with pytest.raises(KLineSourceUnavailable):
            asyncio.run(kline_service._fetch_sina_kline("600519.SH", "daily", 60))


class TestFetchKlines:
    def test_cache_miss_then_persist(self, monkeypatch):
        rows = [
            {"day": "2026-07-30", "open": "1500", "high": "1530", "low": "1495", "close": "1520", "volume": "28000"},
        ]
        fake_class, _ = make_fake_client_class([
            httpx.Response(200, text=f"callback_x({json.dumps(rows, ensure_ascii=False)});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        out = asyncio.run(fetch_klines("600519.SH", "daily", 30))
        assert len(out) == 1
        assert out[0]["close"] == "1520"

    def test_source_unavailable_propagates(self, monkeypatch):
        fake_class, _ = make_fake_client_class([httpx.Response(200, text="[]")])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        with pytest.raises(KLineSourceUnavailable):
            asyncio.run(fetch_klines("600519.SH", "daily", 30))


class TestIntraday:
    def test_keep_time_parsing(self, monkeypatch):
        """keep_time=True 时分钟级保留 HH:MM:SS 秒级时间戳"""
        rows = [
            {"day": "2026-07-31 09:30:00", "open": "1500", "high": "1502", "low": "1499", "close": "1501", "volume": "100", "amount": "150100"},
            {"day": "2026-07-31 09:31:00", "open": "1501", "high": "1503", "low": "1500", "close": "1502", "volume": "200", "amount": "300300"},
        ]
        fake_class, _ = make_fake_client_class([
            httpx.Response(200, text=f"callback_x({json.dumps(rows, ensure_ascii=False)});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        out = asyncio.run(kline_service._fetch_sina_kline("600519.SH", "1min", 60, keep_time=True))
        assert out[0]["date"] == "2026-07-31 09:30:00"
        assert out[0]["amount"] == "150100"

    def test_keep_time_false_strips_to_date(self, monkeypatch):
        """默认 keep_time=False 保持旧行为(分钟级降到日期)"""
        rows = [{"day": "2026-07-31 09:30:00", "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1"}]
        fake_class, _ = make_fake_client_class([
            httpx.Response(200, text=f"callback_x({json.dumps(rows, ensure_ascii=False)});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        out = asyncio.run(kline_service._fetch_sina_kline("600519.SH", "1min", 60))
        assert out[0]["date"] == "2026-07-31"

    def test_fetch_intraday_aggregates(self, monkeypatch):
        """min K线 → 聚合分时点:均价 = 累计额/累计量,仅保留最新交易日"""
        minutes = [
            {"day": "2026-07-29 14:59:00", "open": "1498.0", "high": "1499.0", "low": "1496.0", "close": "1497.0", "volume": "500", "amount": "748500"},
            {"day": "2026-07-30 09:30:00", "open": "1500.000", "high": "1501.0", "low": "1499.0", "close": "1500.5", "volume": "1000", "amount": "1500500"},
            {"day": "2026-07-30 09:31:00", "open": "1500.5", "high": "1502.0", "low": "1498.0", "close": "1501.0", "volume": "1000", "amount": "1501500"},
        ]
        daily = [
            {"day": "2026-07-29", "open": "1500", "high": "1530", "low": "1495", "close": "1497", "volume": "28000"},
            {"day": "2026-07-30", "open": "1500", "high": "1530", "low": "1495", "close": "1560", "volume": "30000"},
        ]
        fake_class, _ = make_fake_client_class([
            httpx.Response(200, text=f"callback_x({json.dumps(daily, ensure_ascii=False)});"),
            httpx.Response(200, text=f"callback_x({json.dumps(minutes, ensure_ascii=False)});"),
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        out = asyncio.run(fetch_intraday("600519.SH"))
        assert out["date"] == "2026-07-30"
        assert out["count"] == 2
        assert out["prev_close"] == "1497"  # 昨日(2026-07-29)收盘
        # 09:30 均价 = 1500500/1000 = 1500.500;09:31 均价 = (1500500+1501500)/2000
        assert out["items"][0]["time"] == "09:30"
        assert out["items"][0]["avg_price"] == 1500.5
        assert abs(out["items"][1]["avg_price"] - 1501.0) < 1e-3
        assert out["items"][1]["volume"] == 1000

    def test_fetch_intraday_no_minutes_raises(self, monkeypatch):
        fake_class, _ = make_fake_client_class([httpx.Response(200, text="[]")])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        with pytest.raises(KLineSourceUnavailable):
            asyncio.run(fetch_intraday("600519.SH"))


class TestKlineAPI:
    def test_get_kline(self, client, monkeypatch):
        rows = [{"day": "2026-07-31", "open": "1500", "high": "1530", "low": "1495", "close": "1520", "volume": "100"}]
        fake_class, _ = make_fake_client_class([
            httpx.Response(200, text=f"callback_api({json.dumps(rows, ensure_ascii=False)});")
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        r = client.get("/api/kline/600519.SH?limit=30")
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_data_source_unavailable_502(self, client, monkeypatch):
        fake_class, _ = make_fake_client_class([httpx.Response(200, text="[]")])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        r = client.get("/api/kline/600519.SH?limit=30")
        assert r.status_code == 502
        assert r.json()["detail"]["code"] == "DATA_SOURCE_UNAVAILABLE"

    def test_invalid_period(self, client):
        r = client.get("/api/kline/600519.SH?period=hourly")
        assert r.status_code == 400

    def test_invalid_limit(self, client):
        r = client.get("/api/kline/600519.SH?limit=999")
        assert r.status_code == 400

    def test_intraday_api(self, client, monkeypatch):
        minutes = [
            {"day": "2026-07-31 09:30:00", "open": "1500", "high": "1502", "low": "1499", "close": "1501", "volume": "100", "amount": "150100"},
            {"day": "2026-07-31 09:31:00", "open": "1501", "high": "1503", "low": "1500", "close": "1502", "volume": "200", "amount": "300300"},
        ]
        daily = [
            {"day": "2026-07-30", "open": "1490", "high": "1500", "low": "1488", "close": "1495", "volume": "1000"},
            {"day": "2026-07-31", "open": "1495", "high": "1503", "low": "1490", "close": "1502", "volume": "1000"},
        ]
        fake_class, _ = make_fake_client_class([
            httpx.Response(200, text=f"callback_x({json.dumps(daily, ensure_ascii=False)});"),
            httpx.Response(200, text=f"callback_x({json.dumps(minutes, ensure_ascii=False)});"),
        ])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        r = client.get("/api/kline/600519.SH/intraday")
        assert r.status_code == 200
        body = r.json()
        assert body["date"] == "2026-07-31"
        assert body["prev_close"] == "1495"
        assert body["count"] == 2
        assert body["items"][0]["time"] == "09:30"

    def test_intraday_api_source_unavailable_502(self, client, monkeypatch):
        fake_class, _ = make_fake_client_class([httpx.Response(200, text="[]")])
        monkeypatch.setattr(kline_service.httpx, "AsyncClient", fake_class)
        r = client.get("/api/kline/600519.SH/intraday")
        assert r.status_code == 502
        assert r.json()["detail"]["code"] == "DATA_SOURCE_UNAVAILABLE"