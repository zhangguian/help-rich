"""screener._apply_fundamental_filter 测试 (改动 B)"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_apply_filter_all_pass_keeps_order():
    from app.services.screener_service import _apply_fundamental_filter

    picks = [
        SimpleNamespace(stock_code="600519.SH", score=100, fundamental_filter_status=None),
        SimpleNamespace(stock_code="000001.SZ", score=95, fundamental_filter_status=None),
    ]

    async def _hit(code, query):
        return True

    with patch("app.services.screener_service.is_hit_fundamental_filter", new=_hit):
        result = await _apply_fundamental_filter(picks)

    assert len(result) == 2
    assert all(p.fundamental_filter_status == "passed" for p in result)


@pytest.mark.asyncio
async def test_apply_filter_kicked_gets_penalty_and_resorts():
    from app.services.screener_service import _apply_fundamental_filter

    picks = [
        SimpleNamespace(stock_code="600519.SH", score=100, fundamental_filter_status=None),
        SimpleNamespace(stock_code="000001.SZ", score=99, fundamental_filter_status=None),
    ]

    async def _hit(code, query):
        return code != "000001.SZ"  # 000001 被踢

    with patch("app.services.screener_service.is_hit_fundamental_filter", new=_hit):
        result = await _apply_fundamental_filter(picks)

    assert result[0].stock_code == "600519.SH"
    assert result[0].fundamental_filter_status == "passed"
    assert result[1].stock_code == "000001.SZ"
    assert result[1].fundamental_filter_status == "kicked"
    assert result[1].score == 69


@pytest.mark.asyncio
async def test_apply_filter_failure_raises():
    """任一票基本面查失败 → 整体抛 IfindUnavailable"""
    from app.services.screener_service import _apply_fundamental_filter
    from app.data.ifind_events import IfindUnavailable

    picks = [
        SimpleNamespace(stock_code="600519.SH", score=100, fundamental_filter_status=None),
        SimpleNamespace(stock_code="000001.SZ", score=99, fundamental_filter_status=None),
    ]

    async def _hit(code, query):
        if code == "000001.SZ":
            raise IfindUnavailable("mocked")
        return True

    with patch("app.services.screener_service.is_hit_fundamental_filter", new=_hit):
        with pytest.raises(IfindUnavailable):
            await _apply_fundamental_filter(picks)


@pytest.mark.asyncio
async def test_apply_filter_disabled_short_circuits():
    """SCREENER_FUNDAMENTAL_FILTER_ENABLED=False 时原样返回"""
    from app.services.screener_service import _apply_fundamental_filter
    from app.core import config

    picks = [SimpleNamespace(stock_code="600519.SH", score=100, fundamental_filter_status=None)]

    with patch.object(config, "SCREENER_FUNDAMENTAL_FILTER_ENABLED", False):
        result = await _apply_fundamental_filter(picks)

    assert result == picks
    assert result[0].fundamental_filter_status is None


# ============================================================
# run_daily_pick 集成测试 (改动 B)
# ============================================================


def _stub_pool() -> list[dict[str, str]]:
    return [{"stock_code": "600519.SH", "stock_name": "贵州茅台"}]


def _stub_features():
    from app.services.scoring import StockFeatures
    # features 必须能通过 passes_filter — 给足量字段
    return [(
        StockFeatures(
            stock_code="600519.SH",
            stock_name="贵州茅台",
            main_net_inflow_yi=2.0,
            volume_ratio=2.0,
            change_pct=5.0,
            turnover_yi=2.0,
            consecutive_up_days=2,
            sector="白酒",
            sector_inflow_rank=3,
        ),
        None,
    )]


def _stub_upsert_run():
    row = MagicMock()
    row.id = 999
    return row


@pytest.mark.asyncio
async def test_run_daily_pick_calls_fundamental_filter():
    """run_daily_pick 必须在 replace_picks 之前调用 _apply_fundamental_filter"""
    from app.services import screener_service
    from datetime import date

    async def _hit(code, query):
        return True

    with patch.object(screener_service, "get_pool", new=AsyncMock(return_value=_stub_pool())):
        with patch.object(screener_service, "_fetch_sectors_safe", new=AsyncMock(return_value=[])):
            with patch.object(screener_service, "_gather_features", new=AsyncMock(return_value=_stub_features())):
                with patch.object(screener_service, "build_event_factor_cache", new=AsyncMock()):
                    with patch.object(screener_service, "get_event_factor_codes", new=AsyncMock(return_value=set())):
                        with patch.object(screener_service, "is_hit_fundamental_filter", new=AsyncMock(side_effect=_hit)) as mock_hit:
                            with patch.object(screener_service.screener_repo, "upsert_run", new=AsyncMock(return_value=_stub_upsert_run())):
                                with patch.object(screener_service.screener_repo, "replace_picks", new=AsyncMock()) as mock_replace:
                                        await screener_service.run_daily_pick(target_date=date.today())
                                        mock_hit.assert_awaited()
                                        # 替换的 picks 必须带 fundamental_filter_status 字段
                                        persisted = mock_replace.await_args.args[1]
                                        assert all(
                                            p.get("fundamental_filter_status") == "passed"
                                            for p in persisted
                                        )


@pytest.mark.asyncio
async def test_run_daily_pick_skips_persist_on_fundamental_filter_failure():
    """基本面过滤失败 → run_daily_pick 不持久化 (spec §6)"""
    from app.services import screener_service
    from app.data.ifind_events import IfindUnavailable
    from datetime import date

    async def _hit(code, query):
        raise IfindUnavailable("mocked ifind down")

    with patch.object(screener_service, "get_pool", new=AsyncMock(return_value=_stub_pool())):
        with patch.object(screener_service, "_fetch_sectors_safe", new=AsyncMock(return_value=[])):
            with patch.object(screener_service, "_gather_features", new=AsyncMock(return_value=_stub_features())):
                with patch.object(screener_service, "build_event_factor_cache", new=AsyncMock()):
                    with patch.object(screener_service, "get_event_factor_codes", new=AsyncMock(return_value=set())):
                        with patch.object(screener_service, "is_hit_fundamental_filter", new=AsyncMock(side_effect=_hit)):
                            with patch.object(screener_service.screener_repo, "upsert_run", new=AsyncMock(return_value=_stub_upsert_run())) as mock_upsert:
                                with patch.object(screener_service.screener_repo, "replace_picks", new=AsyncMock()) as mock_replace:
                                        result = await screener_service.run_daily_pick(target_date=date.today())
                                        # 失败 → 不持久化, 不展示
                                        assert result is None
                                        mock_upsert.assert_not_awaited()
                                        mock_replace.assert_not_awaited()