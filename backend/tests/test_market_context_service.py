"""市场环境聚合单测(全部数据源 mock,验证降级不崩、不编数字)"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.decision_service import MarketContext
from app.services.market_context_service import get_market_context


def _sentiment(up=3777, down=1667, flat=124, lu=59, ld=10):
    return {
        "up_total": up, "down_total": down, "flat_total": flat,
        "limit_up": lu, "limit_down": ld, "sample_size": 5568,
        "amount_yi": 14711.94, "partial": False,
    }


def _overview(chg=0.12):
    return {"indexes": [{"code": "000001.SH", "name": "上证指数",
                         "close": 3735.37, "change_pct": chg}]}


def _sector_kline(close1=100.0, close2=101.5):
    """行业等权 K 线(只有 date/close,涨幅 +1.5%)"""
    return {"items": [
        {"date": "2026-10-19", "close": close1},
        {"date": "2026-10-20", "close": close2},
    ]}


def _patched(sentiment=None, overview=None, industry=None, flows=None, stock_flows=None,
             sector_kline=None):
    """统一 patch 全部 6 个数据源(不 patch 会真联网,测试会变慢且不稳定)"""
    return (
        patch("app.services.market_context_service.fetch_market_sentiment",
              AsyncMock(return_value=sentiment if sentiment is not None else _sentiment())),
        patch("app.services.market_context_service.get_market_overview",
              AsyncMock(return_value=overview if overview is not None else _overview())),
        patch("app.services.market_context_service.resolve_industry",
              AsyncMock(return_value=industry if industry is not None
                        else {"code": "002185.SZ", "industry": "C39计算机、通信和其他电子设备制造业",
                              "source": "baostock", "note": None})),
        patch("app.services.market_context_service.get_sector_fund_flow",
              AsyncMock(return_value=flows if flows is not None else [])),
        patch("app.services.market_context_service.list_recent",
              AsyncMock(return_value=stock_flows if stock_flows is not None else [])),
        # ↓ 第 6 个数据源,必须 patch,否则单测真联网
        patch("app.services.market_context_service.get_sector_kline",
              AsyncMock(return_value=sector_kline if sector_kline is not None else _sector_kline())),
    )


@pytest.mark.asyncio
async def test_market_warm_when_up_dominates():
    p = _patched()
    with p[0], p[1], p[2], p[3], p[4], p[5]:
        ctx = await get_market_context("002185.SZ")
    assert ctx.market["state"] == "warm"
    assert ctx.market["up_total"] == 3777
    assert ctx.market["change_pct"] == 0.12


@pytest.mark.asyncio
async def test_all_sources_failing_does_not_raise():
    with patch("app.services.market_context_service.fetch_market_sentiment",
               AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("app.services.market_context_service.get_market_overview",
               AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("app.services.market_context_service.resolve_industry",
               AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("app.services.market_context_service.get_sector_fund_flow",
               AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("app.services.market_context_service.list_recent",
               AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("app.services.market_context_service.get_sector_kline",
               AsyncMock(side_effect=RuntimeError("boom"))):
        ctx = await get_market_context("002185.SZ")
    assert ctx.market["state"] is None
    assert ctx.market["change_pct"] is None
    assert ctx.sector["industry"] is None
    assert ctx.stock_flow["direction"] is None
    assert len(ctx.degraded) >= 3


@pytest.mark.asyncio
async def test_missing_fields_are_none_not_zero():
    p = _patched(sentiment={"up_total": 100, "down_total": 90})
    with p[0], p[1], p[2], p[3], p[4], p[5]:
        ctx = await get_market_context("002185.SZ")
    assert ctx.market.get("limit_up") is None
    assert ctx.market.get("limit_down") is None


@pytest.mark.asyncio
async def test_leading_sectors_available_even_when_name_mismatch():
    """证监会行业名匹配不上新浪板块名时,仍应给出「资金主攻板块」"""
    flows = [
        {"name": "电子元件", "netamount_yi": 12.3, "change_pct": 2.1},
        {"name": "半导体", "netamount_yi": 8.1, "change_pct": 1.4},
        {"name": "银行", "netamount_yi": -3.2, "change_pct": -0.5},
    ]
    p = _patched(flows=flows)
    with p[0], p[1], p[2], p[3], p[4], p[5]:
        ctx = await get_market_context("002185.SZ")
    assert ctx.sector["fund_net_yi"] is None          # 口径不匹配 → 不编数字
    assert len(ctx.sector["leading"]) == 2              # 只取净流入为正的 Top N
    assert ctx.sector["leading"][0]["name"] == "电子元件"
    assert ctx.sector["leading"][0]["net_yi"] == 12.3
    assert any("口径" in d for d in ctx.degraded)


@pytest.mark.asyncio
async def test_sector_change_pct_from_equally_weighted_kline():
    p = _patched()
    with p[0], p[1], p[2], p[3], p[4], p[5]:
        ctx = await get_market_context("002185.SZ")
    # _sector_kline() 夹具:100.0 → 101.5 = +1.5%
    assert ctx.sector["change_pct"] == 1.5
    assert ctx.sector["state"] == "leading"      # > 1% → leading


@pytest.mark.asyncio
async def test_sector_vs_market_pct_uses_real_index_change_pct():
    """设计文档 §7.2:vs_market_pct = 行业涨幅 - 大盘涨幅"""
    p = _patched()
    with p[0], p[1], p[2], p[3], p[4], p[5]:
        ctx = await get_market_context("002185.SZ")
    # 行业 +1.5% - 上证 +0.12% = +1.38%
    assert ctx.sector["vs_market_pct"] == 1.38


@pytest.mark.asyncio
async def test_sector_vs_market_pct_none_when_index_missing():
    """大盘涨跌幅拿不到 → vs_market_pct 为 None(不编数字)"""
    p = _patched(overview={"indexes": []})
    with p[0], p[1], p[2], p[3], p[4], p[5]:
        ctx = await get_market_context("002185.SZ")
    assert ctx.market["change_pct"] is None
    assert ctx.sector["vs_market_pct"] is None
