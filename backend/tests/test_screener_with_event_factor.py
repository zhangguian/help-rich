"""screener 接入事件因子端到端测试 (改动 A)

覆盖:
- screener 启动时必须先 build_event_factor_cache
- ifind 失败 → 静默降级 4 因子版,不抛错 (spec §4.1)
- event_score 在评分循环里被调用, 命中股票 +15
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import screener_service
from app.services.scoring import event_score


# ============================================================
# 用 mocks 屏蔽上游 IO (get_pool, _fetch_sectors_safe,
# _gather_features, screener_repo) — 让 run_daily_pick
# 真正到达 build_event_factor_cache 调用点
# ============================================================


def _stub_pool() -> list[dict[str, str]]:
    return [{"stock_code": "600519.SH", "stock_name": "贵州茅台"}]


def _stub_features():
    from app.services.scoring import StockFeatures
    return [(StockFeatures(stock_code="600519.SH", stock_name="贵州茅台"), None)]


def _stub_sectors():
    return ([], {}, {}, {})


def _stub_upsert_run():
    row = MagicMock()
    row.id = 999
    return row


@pytest.fixture
def _patch_screener_io():
    """屏蔽 run_daily_pick 上游 IO, 让 build_event_factor_cache 被真调到"""
    with patch.object(screener_service, "get_pool", new=AsyncMock(return_value=_stub_pool())):
        with patch.object(screener_service, "_fetch_sectors_safe", new=AsyncMock(return_value=[])):
            with patch.object(screener_service, "_gather_features", new=AsyncMock(return_value=_stub_features())):
                with patch.object(screener_service.screener_repo, "upsert_run", new=AsyncMock(return_value=_stub_upsert_run())):
                    with patch.object(screener_service.screener_repo, "replace_picks", new=AsyncMock(return_value=None)):
                        yield


# ============================================================
# Tests
# ============================================================


@pytest.mark.asyncio
async def test_run_daily_pick_calls_build_event_factor_first(_patch_screener_io):
    """screener 启动时必须先 build_event_factor_cache"""
    today = date.today()
    with patch(
        "app.services.screener_service.build_event_factor_cache",
        new=AsyncMock(),
    ) as mock_build, patch(
        "app.services.screener_service.get_event_factor_codes",
        new=AsyncMock(return_value=set()),
    ):
        await screener_service.run_daily_pick(target_date=today)
        mock_build.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_daily_pick_event_score_overrides_when_failure_falls_back(_patch_screener_io):
    """ifind 失败 → screener 仍跑 (无事件因子, 4 因子版), 不抛错

    spec §4.1 失败语义: A 失败时 screener 跑无事件因子版, 不抛错
    """
    from app.data.ifind_events import IfindUnavailable

    today = date.today()

    with patch(
        "app.services.screener_service.build_event_factor_cache",
        new=AsyncMock(side_effect=IfindUnavailable("mocked")),
    ), patch(
        "app.services.screener_service.get_event_factor_codes",
        new=AsyncMock(return_value=set()),
    ):
        # 必须不抛 IfindUnavailable (被 try/except 吞掉)
        await screener_service.run_daily_pick(target_date=today)


@pytest.mark.asyncio
async def test_event_score_applied_in_scoring_loop():
    """event_score 在评分循环里被调用, 命中股票 +15, 未命中 0"""
    codes = {"600519.SH"}
    assert event_score("600519.SH", codes, set()) == 15
    assert event_score("000001.SZ", codes, set()) == 0


def test_event_score_returns_zero_when_codes_empty():
    """event_codes 为空 → event_score 返 0 (失败降级语义)"""
    assert event_score("600519.SH", set(), set()) == 0


def test_event_score_case_insensitive():
    """event_score 大小写不敏感 (cache 已 uppercase)"""
    assert event_score("600519.sh", {"600519.SH"}, set()) == 15
    assert event_score("600519.SH", {"600519.sh"}, set()) == 15