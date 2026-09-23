"""ifind_fundamentals 包装层测试 (改动 B)"""
import pytest


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