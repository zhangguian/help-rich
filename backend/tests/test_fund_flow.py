"""资金流真实数据源测试(guide §7 新浪)

- 测试代码用 fake httpx.AsyncClient 拦截(测试基础设施,**非生产 mock**)
- 验证解析 + 落库 + 错误处理
- 生产代码无任何 mock
"""
import asyncio
import json
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import fund_flow_service
from app.services.fund_flow_service import (
    FundFlowSourceUnavailable,
    _from_sina_symbol,
    _parse_rank_row,
    _to_sina_market,
    generate_one,
    list_recent,
)
from sqlalchemy import delete


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    from app.db import async_session
    from app.models.orm import FundFlow

    async def _do():
        async with async_session() as session:
            await session.execute(delete(FundFlow))
            await session.commit()

    asyncio.run(_do())
    yield


def make_fake_client_class(responses: list[httpx.Response]) -> type:
    state = {"idx": 0, "calls": []}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def get(self, url, params=None, headers=None):
            state["calls"].append({"url": str(url), "params": params, "headers": headers})
            i = state["idx"]
            state["idx"] += 1
            if i >= len(responses):
                resp = httpx.Response(200, json=[])
            else:
                resp = responses[i]
            if resp._request is None:
                resp._request = httpx.Request("GET", str(url))
            return resp

    return FakeAsyncClient, state


class TestHelpers:
    def test_to_sina_market(self):
        assert _to_sina_market("600519.SH") == "sh"
        assert _to_sina_market("000001.SZ") == "sz"
        assert _to_sina_market("830799.BJ") == "bj"
        assert _to_sina_market("XXX.YY") == "sh"  # 默认

    def test_from_sina_symbol(self):
        assert _from_sina_symbol("sh600519") == "600519.SH"
        assert _from_sina_symbol("sz000001") == "000001.SZ"
        assert _from_sina_symbol("bj830799") == "830799.BJ"

    def test_parse_rank_row(self):
        raw = {
            "symbol": "sh600519",
            "name": "贵州茅台",
            "inamount": "1000000",
            "outamount": "500000",
            "netamount": "500000",
            "r0_net": "200000",
            "r3_net": "300000",
        }
        out = _parse_rank_row(raw)
        assert out is not None
        assert out["stock_code"] == "600519.SH"
        assert out["netamount"] == 500000.0
        assert out["r0_net"] == 200000.0

    def test_parse_rank_row_invalid(self):
        assert _parse_rank_row({"no_symbol": True}) is None
        assert _parse_rank_row("not a dict") is None


class TestSinaFundFlow:
    def test_fetch_rank_success(self, monkeypatch):
        rows = [
            {
                "symbol": "sh600519",
                "name": "贵州茅台",
                "inamount": "1000000",
                "outamount": "500000",
                "netamount": "500000",
                "r0_net": "200000",
                "r3_net": "300000",
            }
        ]
        fake_class, state = make_fake_client_class([
            httpx.Response(200, json=rows)
        ])
        monkeypatch.setattr(fund_flow_service.httpx, "AsyncClient", fake_class)

        result = asyncio.run(
            fund_flow_service._fetch_sina_fund_flow_rank(market="sh", num=50)
        )
        assert len(result) == 1
        assert state["calls"][0]["params"]["shichang"] == "sh"

    def test_fetch_empty_raises(self, monkeypatch):
        fake_class, _ = make_fake_client_class([httpx.Response(200, json=[])])
        monkeypatch.setattr(fund_flow_service.httpx, "AsyncClient", fake_class)
        with pytest.raises(FundFlowSourceUnavailable):
            asyncio.run(fund_flow_service._fetch_sina_fund_flow_rank())

    def test_generate_one(self, monkeypatch):
        rows = [
            {
                "symbol": "sh600519",
                "name": "贵州茅台",
                "inamount": "1000000",
                "outamount": "500000",
                "netamount": "500000",
                "r0_net": "200000",
                "r3_net": "300000",
            }
        ]
        fake_class, _ = make_fake_client_class([httpx.Response(200, json=rows)])
        monkeypatch.setattr(fund_flow_service.httpx, "AsyncClient", fake_class)

        out = asyncio.run(generate_one("600519.SH"))
        assert out["stock_code"] == "600519.SH"
        assert out["direction"] == "in"  # 净额 50 万 > 0
        assert float(out["amount"]) == 50.0  # 500000 / 10000 = 50 万

    def test_generate_one_not_in_rank(self, monkeypatch):
        rows = [{"symbol": "sz000001", "name": "平安"}]  # 没有 600519
        fake_class, _ = make_fake_client_class([httpx.Response(200, json=rows)])
        monkeypatch.setattr(fund_flow_service.httpx, "AsyncClient", fake_class)

        with pytest.raises(FundFlowSourceUnavailable):
            asyncio.run(generate_one("600519.SH"))

    def test_generate_one_outflow(self, monkeypatch):
        rows = [
            {
                "symbol": "sh600519",
                "name": "贵州茅台",
                "inamount": "500000",
                "outamount": "1000000",
                "netamount": "-500000",
                "r0_net": "0",
                "r3_net": "-200000",
            }
        ]
        fake_class, _ = make_fake_client_class([httpx.Response(200, json=rows)])
        monkeypatch.setattr(fund_flow_service.httpx, "AsyncClient", fake_class)

        out = asyncio.run(generate_one("600519.SH"))
        assert out["direction"] == "out"
        assert float(out["amount"]) == 50.0  # 绝对值


class TestFundFlowAPI:
    def test_get_recent(self, client):
        r = client.get("/api/fund-flow/600519.SH")
        assert r.status_code == 200
        assert r.json()["stock_code"] == "600519.SH"

    def test_manual_generate_502(self, client, monkeypatch):
        fake_class, _ = make_fake_client_class([httpx.Response(200, json=[])])
        monkeypatch.setattr(fund_flow_service.httpx, "AsyncClient", fake_class)
        r = client.post("/api/fund-flow/600519.SH/generate")
        assert r.status_code == 502
        assert r.json()["detail"]["code"] == "DATA_SOURCE_UNAVAILABLE"

    def test_sse_endpoint_exists(self, client):
        r = client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        assert "/api/fund-flow/{stock_code}/events" in paths