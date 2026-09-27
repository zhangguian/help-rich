"""ifind_fundamentals 包装层测试 (改动 B)"""
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_default_market_is_valid_connector_enum():
    """回归: market 默认值必须是 thsifind 合法枚举.

    历史 bug: 默认值曾为 "A股", 但 search_securities 的 market enum 只有
    股票/基金/港股/美股. 传 "A股" 被 connector 校验拒绝 → IfindUnavailable →
    改动 B fail-fast → screener 每天都不出 Top N. 原 4 个测试全部 mock 掉
    market 参数, 所以没能发现.
    """
    from app.data.ifind_fundamentals import is_hit_fundamental_filter

    captured: dict = {}

    async def _fake_search_securities(market: str, query: str) -> list[dict]:
        captured["market"] = market
        captured["query"] = query
        return []

    with patch("app.data.ifind_fundamentals._search_securities", _fake_search_securities):
        await is_hit_fundamental_filter("600519.SH", "扣非ROE>0")

    assert "market" in captured, "market 未传给 connector"
    assert captured["market"] in {"股票", "基金", "港股", "美股"}, (
        f"非法 market 枚举: {captured['market']!r} — 会被 connector 校验拒绝"
    )


@pytest.mark.asyncio
async def test_is_hit_returns_true_when_stock_in_results():
    from app.data.ifind_fundamentals import is_hit_fundamental_filter
    from tests.conftest import mock_thsifind

    raw = [
        {"stock_code": "600519.SH", "hit": True},
        {"stock_code": "000001.SZ", "hit": False},
    ]
    with mock_thsifind(securities=raw):
        hit = await is_hit_fundamental_filter("600519.SH", "扣非ROE>0")

    assert hit is True


@pytest.mark.asyncio
async def test_is_hit_returns_false_when_stock_not_in_results():
    from app.data.ifind_fundamentals import is_hit_fundamental_filter
    from tests.conftest import mock_thsifind

    raw = [{"stock_code": "OTHER.SH", "hit": True}]
    with mock_thsifind(securities=raw):
        hit = await is_hit_fundamental_filter("600519.SH", "扣非ROE>0")

    assert hit is False


@pytest.mark.asyncio
async def test_is_hit_empty_results_returns_false():
    from app.data.ifind_fundamentals import is_hit_fundamental_filter
    from tests.conftest import mock_thsifind

    with mock_thsifind(securities=[]):
        hit = await is_hit_fundamental_filter("600519.SH", "扣非ROE>0")

    assert hit is False


@pytest.mark.asyncio
async def test_is_hit_failure_raises():
    from app.data.ifind_fundamentals import is_hit_fundamental_filter, IfindUnavailable
    from tests.conftest import mock_thsifind

    with mock_thsifind(fail_on={"search_securities"}):
        with pytest.raises(IfindUnavailable):
            await is_hit_fundamental_filter("600519.SH", "扣非ROE>0")