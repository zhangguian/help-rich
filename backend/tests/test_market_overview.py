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
        "app.data.sina.fetch_market_movers",
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
        "app.data.sina.fetch_market_movers",
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


# ============ sparkline ============


async def test_fetch_market_sparklines_all_ok():
    """三大指数 sparkline 全部成功"""
    spark_raw = {
        "000001.SH": [{"date": "2026-07-30", "close": 3200.5},
                      {"date": "2026-07-31", "close": 3210.2}],
        "399001.SZ": [{"date": "2026-07-30", "close": 10500.3},
                      {"date": "2026-07-31", "close": 10580.1}],
        "399006.SZ": [{"date": "2026-07-30", "close": 2100.0},
                      {"date": "2026-07-31", "close": 2108.4}],
    }
    with patch.object(
        market_overview_service, "_fetch_one_spark",
        AsyncMock(side_effect=lambda code, count: spark_raw.get(code, [])),
    ):
        out = await market_overview_service.fetch_market_sparklines(count=60)

    assert set(out.keys()) == {"000001.SH", "399001.SZ", "399006.SZ"}
    assert len(out["000001.SH"]) == 2
    assert out["000001.SH"][-1]["close"] == 3210.2


async def test_fetch_market_sparklines_partial_fail():
    """单只失败 → 该只空 list,其它正常"""
    async def side(code, count):
        if code == "399001.SZ":
            raise RuntimeError("network down")
        return [{"date": "2026-07-31", "close": 1000.0}]

    with patch.object(
        market_overview_service, "_fetch_one_spark", AsyncMock(side_effect=side),
    ):
        out = await market_overview_service.fetch_market_sparklines(count=60)

    assert out["000001.SH"] != []
    assert out["399001.SZ"] == []
    assert out["399006.SZ"] != []


# ============ sentiment ============


async def test_fetch_market_sentiment_basic():
    """涨跌家数 + 区间分布"""
    rows = [
        {"symbol": "sh600000", "name": "x", "changepercent": "10", "amount": "100000000"},
        {"symbol": "sh600001", "name": "x", "changepercent": "5.5", "amount": "50000000"},
        {"symbol": "sh600002", "name": "x", "changepercent": "1.5", "amount": "0"},
        {"symbol": "sh600003", "name": "x", "changepercent": "0.05", "amount": "0"},
        {"symbol": "sh600004", "name": "x", "changepercent": "0", "amount": "0"},
        {"symbol": "sh600005", "name": "x", "changepercent": "-0.05", "amount": "0"},
        {"symbol": "sh600006", "name": "x", "changepercent": "-1.5", "amount": "0"},
        {"symbol": "sh600007", "name": "x", "changepercent": "-5.5", "amount": "0"},
        {"symbol": "sh600008", "name": "x", "changepercent": "-10", "amount": "0"},
    ]
    with patch(
        "app.services.market_overview_service._fetch_hs_a_quotes",
        AsyncMock(return_value=rows),
    ):
        out = await market_overview_service.fetch_market_sentiment()

    assert out["sample_size"] == 9
    assert out["up_total"] == 4   # 10/5.5/1.5/0.05
    assert out["flat_total"] == 1  # 0
    assert out["down_total"] == 4  # -0.05/-1.5/-5.5/-10
    assert out["buckets"]["limit_up"] == 1
    assert out["buckets"]["up_5_10"] == 1
    assert out["buckets"]["up_1_5"] == 1
    assert out["buckets"]["up_0_1"] == 1
    assert out["buckets"]["flat"] == 1
    assert out["buckets"]["down_0_1"] == 1
    assert out["buckets"]["down_1_5"] == 1
    assert out["buckets"]["down_5_10"] == 1
    assert out["buckets"]["limit_down"] == 1
    # amount:仅 100000000 + 50000000 = 1.5 亿
    assert out["amount_yi"] == 1.5


async def test_fetch_market_sentiment_invalid_pct_skipped():
    """异常字段跳过,其余统计正确"""
    rows = [
        {"symbol": "sh600000", "name": "x", "changepercent": "bad", "amount": "0"},
        {"symbol": "sh600001", "name": "x", "changepercent": "2.5", "amount": "0"},
    ]
    with patch(
        "app.services.market_overview_service._fetch_hs_a_quotes",
        AsyncMock(return_value=rows),
    ):
        out = await market_overview_service.fetch_market_sentiment()

    assert out["up_total"] == 1
    assert out["buckets"]["up_1_5"] == 1


# ============ main fund flow ============


async def test_fetch_main_fund_flow_top_n():
    """主力净流入榜按净额降序,top N"""
    rows = [
        {"symbol": "sh600000", "name": "A", "trade": "10",
         "changepercent": "5", "amount": "100000000"},   # 1 亿
        {"symbol": "sh600001", "name": "B", "trade": "20",
         "changepercent": "-3", "amount": "50000000"},  # 0.5 亿
        {"symbol": "sh600002", "name": "C", "trade": "30",
         "changepercent": "8", "amount": "200000000"},  # 2 亿
        {"symbol": "sh600003", "name": "D", "trade": "40",
         "changepercent": "1", "amount": "100000000"},  # 1 亿
    ]
    with patch(
        "app.services.market_overview_service._fetch_hs_a_quotes",
        AsyncMock(return_value=rows),
    ):
        out = await market_overview_service.fetch_main_fund_flow(limit=2)

    assert len(out) == 2
    # C: 2 亿 × (1+8/10) = 3.6 亿(最大)
    # A: 1 亿 × (1+5/10) = 1.5 亿
    assert out[0]["code"] == "600002.SH"
    assert out[0]["netamount_yi"] == 3.6
    assert out[1]["code"] == "600000.SH"
    # B 跌最大被截
    codes = {it["code"] for it in out}
    assert "600001.SH" not in codes


async def test_fetch_main_fund_flow_handles_missing_fields():
    """symbol/changepct 缺失 → 跳过"""
    rows = [
        {"name": "A", "trade": "10", "changepercent": "5", "amount": "100000000"},
        {"symbol": "sh600000", "name": "B", "trade": "abc",
         "changepercent": "bad", "amount": "100000000"},
        {"symbol": "sh600001", "name": "C", "trade": "10",
         "changepercent": "2", "amount": "100000000"},
    ]
    with patch(
        "app.services.market_overview_service._fetch_hs_a_quotes",
        AsyncMock(return_value=rows),
    ):
        out = await market_overview_service.fetch_main_fund_flow(limit=10)

    assert len(out) == 1
    assert out[0]["code"] == "600001.SH"


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


# ============ /api/market/index-sparks ============


def test_api_index_sparks_ok(client):
    """GET /api/market/index-sparks:全成功 → 200"""
    payload = {
        "000001.SH": [{"date": "2026-07-30", "close": 3200.5},
                      {"date": "2026-07-31", "close": 3210.2}],
        "399001.SZ": [{"date": "2026-07-30", "close": 10500.3}],
        "399006.SZ": [],
    }
    with patch(
        "app.api.market.fetch_market_sparklines",
        AsyncMock(return_value=payload),
    ):
        r = client.get("/api/market/index-sparks?count=60")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 60
    assert "000001.SH" in body["sparks"]
    assert len(body["sparks"]["000001.SH"]) == 2


def test_api_index_sparks_invalid_count(client):
    """count 越界 → 400"""
    r = client.get("/api/market/index-sparks?count=5")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_COUNT"
    r = client.get("/api/market/index-sparks?count=500")
    assert r.status_code == 400


def test_api_index_sparks_all_empty_503(client):
    """全部指数空 → 503"""
    with patch(
        "app.api.market.fetch_market_sparklines",
        AsyncMock(return_value={"000001.SH": [], "399001.SZ": [], "399006.SZ": []}),
    ):
        r = client.get("/api/market/index-sparks")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "SPARK_UNAVAILABLE"


def test_api_index_sparks_partial_200(client):
    """部分指数有数据 → 200(不视为完全不可用)"""
    payload = {
        "000001.SH": [{"date": "2026-07-31", "close": 3200}],
        "399001.SZ": [],
        "399006.SZ": [],
    }
    with patch(
        "app.api.market.fetch_market_sparklines",
        AsyncMock(return_value=payload),
    ):
        r = client.get("/api/market/index-sparks")
    assert r.status_code == 200


# ============ /api/market/sentiment ============


def test_api_sentiment_ok(client):
    """GET /api/market/sentiment:成功 → 200"""
    payload = {
        "sample_size": 200, "up_total": 100, "down_total": 80,
        "flat_total": 20, "buckets": {"limit_up": 5}, "amount_yi": 100.5,
    }
    with patch(
        "app.api.market.fetch_market_sentiment",
        AsyncMock(return_value=payload),
    ):
        r = client.get("/api/market/sentiment")
    assert r.status_code == 200
    body = r.json()
    assert body["up_total"] == 100
    assert body["buckets"]["limit_up"] == 5


def test_api_sentiment_failed_502(client):
    """service 抛错 → 502"""
    with patch(
        "app.api.market.fetch_market_sentiment",
        AsyncMock(side_effect=RuntimeError("network down")),
    ):
        r = client.get("/api/market/sentiment")
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "SENTIMENT_UNAVAILABLE"


# ============ /api/market/main-fund-flow ============


def test_api_main_fund_flow_ok(client):
    """GET /api/market/main-fund-flow:成功 → 200"""
    payload = [
        {"code": "600519.SH", "name": "贵州茅台", "current_price": "1700",
         "change_pct": 5.0, "netamount_yi": 12.5},
    ]
    with patch(
        "app.api.market.fetch_main_fund_flow",
        AsyncMock(return_value=payload),
    ):
        r = client.get("/api/market/main-fund-flow?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 10
    assert len(body["items"]) == 1
    assert body["items"][0]["code"] == "600519.SH"


def test_api_main_fund_flow_invalid_limit(client):
    """limit 越界 → 400"""
    r = client.get("/api/market/main-fund-flow?limit=100")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_LIMIT"


def test_api_main_fund_flow_failed_502(client):
    """service 抛错 → 502"""
    with patch(
        "app.api.market.fetch_main_fund_flow",
        AsyncMock(side_effect=RuntimeError("network down")),
    ):
        r = client.get("/api/market/main-fund-flow")
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "MAIN_FUND_UNAVAILABLE"