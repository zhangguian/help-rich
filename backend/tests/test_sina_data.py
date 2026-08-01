"""新浪客户端 + 板块资金 + 快讯测试(测试代码用 fake httpx 拦截)"""
import asyncio
import json

import httpx
import pytest

from app.data import sina
from app.data.sina import fetch_sector_fund_flow_rank, fetch_sina_news
from app.services.news_service import get_sina_news
from app.services.sector_fund_flow_service import get_sector_fund_flow


def make_fake_client(responses):
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
            resp = responses[i] if i < len(responses) else httpx.Response(200, json=[])
            if resp._request is None:
                resp._request = httpx.Request("GET", str(url))
            return resp

    return FakeAsyncClient, state


class TestSectorFundFlow:
    def test_parse_success(self, monkeypatch):
        rows = [
            {
                "category": "new_dzxx",
                "name": "电子信息",
                "avg_price": "14.17",
                "avg_changeratio": "0.036",
                "turnover": "537",
                "inamount": "117267159156",
                "outamount": "99938173033",
                "netamount": "17328986122",
                "ratioamount": "0.076",
                "ts_symbol": "sz300418",
                "ts_name": "昆仑万维",
                "ts_trade": "43.20",
                "ts_changeratio": "0.2",
                "ts_ratioamount": "0.381",
            }
        ]
        fake, _ = make_fake_client([httpx.Response(200, json=rows)])
        monkeypatch.setattr(sina.httpx, "AsyncClient", fake)

        result = asyncio.run(get_sector_fund_flow(fenlei=1, num=10))
        assert len(result) == 1
        assert result[0]["name"] == "电子信息"
        assert result[0]["inamount_yi"] == 117267159156.0
        assert result[0]["top_stock"]["code"] == "sz300418"

    def test_invalid_response_raises(self, monkeypatch):
        fake, _ = make_fake_client([httpx.Response(200, json="not array")])
        monkeypatch.setattr(sina.httpx, "AsyncClient", fake)
        with pytest.raises(ValueError):
            asyncio.run(get_sector_fund_flow())


class TestSinaNews:
    def test_parse_jsonp(self, monkeypatch):
        rows = [
            {"id": 1, "rich_text": "新闻1", "type": 0, "create_time": "2026-08-01 12:00", "tag": "财经"},
            {"id": 2, "rich_text": "新闻2", "type": 0, "create_time": "2026-08-01 12:01", "tag": "股市"},
        ]
        body = json.dumps({"result": {"status": {"code": 0}, "data": {"feed": {"list": rows}}}})
        fake, _ = make_fake_client([httpx.Response(200, text=f"callback({body});")])
        monkeypatch.setattr(sina.httpx, "AsyncClient", fake)

        result = asyncio.run(get_sina_news())
        assert len(result) == 2
        assert result[0]["rich_text"] == "新闻1"

    def test_parse_plain_json(self, monkeypatch):
        rows = [{"id": 3, "rich_text": "纯JSON新闻", "type": 0, "create_time": "2026-08-01 12:02", "tag": "国际"}]
        body = json.dumps({"result": {"status": {"code": 0}, "data": {"feed": {"list": rows}}}})
        fake, _ = make_fake_client([httpx.Response(200, text=body)])
        monkeypatch.setattr(sina.httpx, "AsyncClient", fake)

        result = asyncio.run(get_sina_news())
        assert len(result) == 1
        assert result[0]["rich_text"] == "纯JSON新闻"

    def test_invalid_jsonp_raises(self, monkeypatch):
        fake, _ = make_fake_client([httpx.Response(200, text="not jsonp")])
        monkeypatch.setattr(sina.httpx, "AsyncClient", fake)
        with pytest.raises(ValueError):
            asyncio.run(get_sina_news())


class TestMarketAPI:
    """API 端到端测试(fastapi TestClient + fake httpx)"""

    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as c:
            yield c

    def test_sector_fund_flow_endpoint(self, client, monkeypatch):
        rows = [
            {
                "category": "new_dzxx",
                "name": "电子信息",
                "avg_price": "14",
                "avg_changeratio": "0.05",
                "turnover": "100",
                "inamount": "1000",
                "outamount": "500",
                "netamount": "500",
                "ratioamount": "0.5",
            }
        ]
        fake, _ = make_fake_client([httpx.Response(200, json=rows)])
        monkeypatch.setattr(sina.httpx, "AsyncClient", fake)
        r = client.get("/api/sector-fund-flow?fenlei=0&num=5")
        assert r.status_code == 200
        data = r.json()
        assert data["fenlei"] == 0
        assert data["fenlei_label"] == "全部"
        assert data["count"] == 1

    def test_sector_fund_flow_invalid_fenlei(self, client):
        r = client.get("/api/sector-fund-flow?fenlei=9")
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "INVALID_FENLEI"

    def test_sina_news_endpoint(self, client, monkeypatch):
        rows = [{"id": 1, "rich_text": "测试快讯", "type": 0, "create_time": "2026-08-01 12:00", "tag": "财经"}]
        body = json.dumps({"result": {"data": {"feed": {"list": rows}}}})
        fake, _ = make_fake_client([httpx.Response(200, text=f"cb({body});")])
        monkeypatch.setattr(sina.httpx, "AsyncClient", fake)
        r = client.get("/api/news/sina?page=1&page_size=10")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert data["items"][0]["rich_text"] == "测试快讯"

    def test_sina_news_502(self, client, monkeypatch):
        fake, _ = make_fake_client([httpx.Response(200, text="not jsonp")])
        monkeypatch.setattr(sina.httpx, "AsyncClient", fake)
        r = client.get("/api/news/sina")
        assert r.status_code == 502
        assert r.json()["detail"]["code"] == "DATA_SOURCE_UNAVAILABLE"