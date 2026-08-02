"""大盘盯盘总览测试(roadmap §3.9)

- service 层:指数 / 领涨 / 领跌的拉取与降级
- API 层:/market/overview 返回结构与失败语义
"""
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import market_overview_service


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_singleton():
    """每个测试前重置指数服务单例 + 退避缓存"""
    market_overview_service.reset_market_overview_service()
    yield
    market_overview_service.reset_market_overview_service()


def _mk_quote(code: str, name: str, price: str, prev: str) -> Any:
    from app.data.unified import UnifiedQuote
    from datetime import datetime

    cur = Decimal(price)
    prev_c = Decimal(prev)
    return UnifiedQuote(
        code=code,
        name=name,
        current_price=cur,
        prev_close=prev_c,
        open=cur,
        high=cur,
        low=cur,
        change=cur - prev_c,
        change_pct=float(cur / prev_c * 100 - 100) if prev_c else 0.0,
        volume=0,
        amount=Decimal("0"),
        timestamp=datetime.now(),
    )


# ============ service 层 ============


async def test_get_market_overview_all_ok():
    """指数 + 领涨 + 领跌全部成功 → 全部填充"""
    idx_quotes = [
        _mk_quote("000001.SH", "上证指数", "3200.50", "3180.00"),
        _mk_quote("399001.SZ", "深证成指", "10500.30", "10480.00"),
        _mk_quote("399006.SZ", "创业板指", "2100.10", "2080.00"),
    ]
    gainers_raw = [
        {"symbol": "sh600519", "name": "贵州茅台", "trade": "1700.50", "changeratio": "5.23"},
        {"symbol": "sz000858", "name": "五粮液", "trade": "180.30", "changeratio": "4.85"},
        {"symbol": "sz300750", "name": "宁德时代", "trade": "240.10", "changeratio": "4.10"},
    ]
    losers_raw = [
        {"symbol": "sh601318", "name": "中国平安", "trade": "45.20", "changeratio": "-3.50"},
        {"symbol": "sz000001", "name": "平安银行", "trade": "12.30", "changeratio": "-3.20"},
        {"symbol": "sh600036", "name": "招商银行", "trade": "32.10", "changeratio": "-2.90"},
    ]

    with patch.object(
        market_overview_service, "_fetch_indexes",
        AsyncMock(return_value=[
            market_overview_service._quote_to_index_dict(q) for q in idx_quotes
        ]),
    ), patch(
        "app.services.market_overview_service.fetch_market_movers",
        AsyncMock(side_effect=lambda direction, num=3:
            gainers_raw if direction == "up" else losers_raw),
    ):
        out = await market_overview_service.get_market_overview()

    assert len(out["indexes"]) == 3
    assert out["indexes"][0]["code"] == "000001.SH"
    assert out["indexes"][0]["name"] == "上证指数"
    assert out["indexes"][0]["change_pct"] > 0

    assert len(out["gainers"]) == 3
    assert out["gainers"][0]["code"] == "600519.SH"
    assert out["gainers"][0]["change_pct"] == 5.23
    assert out["gainers"][0]["current_price"] == "1700.500"

    assert len(out["losers"]) == 3
    assert out["losers"][0]["change_pct"] == -3.50
    assert "fetched_at" in out


async def test_get_market_overview_movers_failed_degrade():
    """领涨/领跌拉取失败 → 返回空数组,但接口仍 200,指数保留"""
    idx_dicts = [
        market_overview_service._quote_to_index_dict(_mk_quote("000001.SH", "上证指数", "3200", "3180")),
        market_overview_service._quote_to_index_dict(_mk_quote("399001.SZ", "深证成指", "10500", "10480")),
        market_overview_service._quote_to_index_dict(_mk_quote("399006.SZ", "创业板指", "2100", "2080")),
    ]

    with patch.object(
        market_overview_service, "_fetch_indexes", AsyncMock(return_value=idx_dicts),
    ), patch.object(
        market_overview_service, "_fetch_movers", AsyncMock(return_value=[]),
    ):
        out = await market_overview_service.get_market_overview()

    assert len(out["indexes"]) == 3
    assert out["gainers"] == []
    assert out["losers"] == []


async def test_get_market_overview_index_quotes_service_raises():
    """QuoteService 抛错 → 指数空 list,接口仍 200"""
    with patch.object(
        market_overview_service, "_fetch_indexes", AsyncMock(return_value=[]),
    ), patch.object(
        market_overview_service, "_fetch_movers", AsyncMock(return_value=[]),
    ):
        out = await market_overview_service.get_market_overview()

    assert out["indexes"] == []
    assert out["gainers"] == []
    assert out["losers"] == []


async def test_fetch_movers_parses_empty_and_invalid():
    """_fetch_movers 内部 parser:跳过 symbol 缺失与异常字段"""
    raw = [
        {"symbol": "sh600519", "name": "贵州茅台", "trade": "1700", "changeratio": "5.2"},
        {"symbol": "", "name": "无效", "trade": "0", "changeratio": "0"},
        {"symbol": "sz000858", "name": "五粮液", "trade": "abc", "changeratio": "bad"},
    ]
    with patch(
        "app.services.market_overview_service.fetch_market_movers",
        AsyncMock(return_value=raw),
    ):
        out = await market_overview_service._fetch_movers("up", 3)

    # 只有第一条完整数据被解析
    assert len(out) == 1
    assert out[0]["code"] == "600519.SH"
    assert out[0]["change_pct"] == 5.2
    assert out[0]["current_price"] == "1700.000"


async def test_fetch_movers_direction_invalid():
    """_fetch_movers 方向非法直接报错"""
    with pytest.raises(ValueError):
        await market_overview_service._fetch_movers("invalid", 3)


async def test_index_codes_constant():
    """三大主指常量固定(下游依赖)"""
    assert market_overview_service.INDEX_CODES == [
        "000001.SH", "399001.SZ", "399006.SZ",
    ]


# ============ API 层 ============


def test_api_market_overview_all_ok(client):
    """GET /api/market/overview:全成功 → 200"""
    payload = {
        "indexes": [
            {"code": "000001.SH", "name": "上证指数", "current_price": "3200.5",
             "prev_close": "3180", "open": "3190", "high": "3210", "low": "3180",
             "change": "20.5", "change_pct": 0.6447,
             "volume": 0, "amount": "0", "timestamp": "2026-08-02T10:00:00"},
        ],
        "gainers": [{"code": "600519.SH", "name": "贵州茅台",
                     "current_price": "1700.5", "change_pct": 5.2}],
        "losers": [{"code": "601318.SH", "name": "中国平安",
                    "current_price": "45.2", "change_pct": -3.5}],
        "fetched_at": "2026-08-02T10:00:00",
    }
    with patch(
        "app.api.market.get_market_overview", AsyncMock(return_value=payload),
    ):
        r = client.get("/api/market/overview")
    assert r.status_code == 200
    body = r.json()
    assert len(body["indexes"]) == 1
    assert body["gainers"][0]["code"] == "600519.SH"
    assert body["losers"][0]["code"] == "601318.SH"


def test_api_market_overview_all_empty_503(client):
    """指数 + 领涨 + 领跌全空 → 503"""
    with patch(
        "app.api.market.get_market_overview",
        AsyncMock(return_value={"indexes": [], "gainers": [], "losers": [], "fetched_at": ""}),
    ):
        r = client.get("/api/market/overview")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "MARKET_UNAVAILABLE"


def test_api_market_overview_partial_200(client):
    """指数全空但领涨/领跌有数据 → 200(不视为完全不可用)"""
    payload = {
        "indexes": [],
        "gainers": [{"code": "1.SH", "name": "x", "current_price": "0", "change_pct": 1}],
        "losers": [],
        "fetched_at": "",
    }
    with patch(
        "app.api.market.get_market_overview", AsyncMock(return_value=payload),
    ):
        r = client.get("/api/market/overview")
    assert r.status_code == 200


def test_api_market_overview_indexes_none_partial_200(client):
    """指数列表含 None 占位(单只失败)但部分成功 → 200"""
    payload = {
        "indexes": [
            {"code": "000001.SH", "name": "上证", "current_price": "3200",
             "prev_close": "3180", "open": "3190", "high": "3210", "low": "3180",
             "change": "20", "change_pct": 0.6, "volume": 0, "amount": "0",
             "timestamp": "2026-08-02T10:00:00"},
            None,  # 单只失败
        ],
        "gainers": [], "losers": [], "fetched_at": "",
    }
    with patch(
        "app.api.market.get_market_overview", AsyncMock(return_value=payload),
    ):
        r = client.get("/api/market/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["indexes"][1] is None