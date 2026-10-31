"""盘中信号模块测试(service / repository / scheduler / API)。

不触网、不弹真实通知:通知出口统一打桩,只验证编排口径。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.notify.service import NotifyResult
from app.modules.signal.engine import Signal
from app.modules.signal.scheduler import WINDOW_MAX_FRAMES, SignalScheduler
from app.modules.signal.service import SignalConfig, signal_service

client = TestClient(app)

CODE = "002185.SZ"


def _signal(kind: str = "t_sell_point", level: float | None = 12.0) -> Signal:
    return Signal(
        kind=kind,
        stock_code=CODE,
        stock_name="测试股",
        level=level,
        value=12.0,
        title=f"测试信号 · {CODE}",
        body="正文",
        fingerprint=f"{kind}:{CODE}:{int((level or 0) * 100)}",
        dedup_by_level=True,
    )


def _ok_results() -> list[NotifyResult]:
    return [NotifyResult.success("desktop", "已弹出桌面通知")]


# ============================================================
# 配置
# ============================================================


@pytest.mark.asyncio
async def test_config_defaults() -> None:
    cfg = await signal_service.get_config()
    assert cfg.enabled is True
    assert cfg.velocity_window_sec == 60
    assert cfg.velocity_pct == 1.5
    assert cfg.breakout_up_pct == 5.0
    assert cfg.breakout_down_pct == -5.0
    assert cfg.cooldown_sec == 600
    assert cfg.daily_limit == 5
    assert cfg.channels == ["desktop"]


@pytest.mark.asyncio
async def test_update_config_persists() -> None:
    cfg = await signal_service.update_config(
        velocity_pct=2.5, enable_breakout=False, channels=["desktop", "console"]
    )
    assert cfg.velocity_pct == 2.5
    assert cfg.enable_breakout is False
    assert cfg.channels == ["desktop", "console"]
    again = await signal_service.get_config()
    assert again.velocity_pct == 2.5


# ============================================================
# 触发编排
# ============================================================


@pytest.mark.asyncio
async def test_fire_records_and_notifies() -> None:
    cfg = SignalConfig()
    with patch(
        "app.modules.notify.service.notify_service.notify_with_limit",
        AsyncMock(return_value=_ok_results()),
    ) as notify:
        ok = await signal_service.fire(_signal(), cfg)
    assert ok is True
    assert notify.await_count == 1
    rows = await signal_service.list_triggers(stock_code=CODE)
    assert len(rows) == 1
    assert rows[0]["notified"] is True
    assert rows[0]["kind"] == "t_sell_point"


@pytest.mark.asyncio
async def test_fire_same_level_only_once_per_day() -> None:
    """同一价位当日只提醒一次(指纹落库 → 跨重启也成立)。"""
    cfg = SignalConfig()
    with patch(
        "app.modules.notify.service.notify_service.notify_with_limit",
        AsyncMock(return_value=_ok_results()),
    ) as notify:
        first = await signal_service.fire(_signal(level=12.0), cfg)
        second = await signal_service.fire(_signal(level=12.0), cfg)
    assert first is True
    assert second is False
    assert notify.await_count == 1


@pytest.mark.asyncio
async def test_fire_different_level_fires_again() -> None:
    cfg = SignalConfig()
    with patch(
        "app.modules.notify.service.notify_service.notify_with_limit",
        AsyncMock(return_value=_ok_results()),
    ) as notify:
        await signal_service.fire(_signal(level=12.0), cfg)
        await signal_service.fire(_signal(level=12.5), cfg)
    assert notify.await_count == 2


@pytest.mark.asyncio
async def test_fire_limited_by_cooldown_records_skipped() -> None:
    """被冷却/限流 → 记一笔 skipped(前端能解释"为什么没推")。"""
    cfg = SignalConfig()
    with patch(
        "app.modules.notify.service.notify_service.notify_with_limit",
        AsyncMock(return_value=None),
    ):
        ok = await signal_service.fire(_signal(kind="velocity_up", level=None), cfg)
    assert ok is False
    rows = await signal_service.list_triggers(stock_code=CODE)
    assert len(rows) == 1
    assert rows[0]["notified"] is False
    assert rows[0]["error"]


@pytest.mark.asyncio
async def test_fire_notification_failure_does_not_raise() -> None:
    """通知异常绝不冒泡(盯盘主流程不受影响)。"""
    cfg = SignalConfig()
    with patch(
        "app.modules.notify.service.notify_service.notify_with_limit",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        ok = await signal_service.fire(_signal(kind="velocity_up", level=None), cfg)
    assert ok is False


# ============================================================
# 调度器
# ============================================================


def _quote(price: str, prev_close: str = "10.0", code: str = CODE) -> dict:
    return {
        "code": code,
        "name": "测试股",
        "current_price": price,
        "prev_close": prev_close,
        "change_pct": 0.0,
    }


@pytest.mark.asyncio
async def test_scheduler_skips_when_not_trading_time() -> None:
    """非交易时段不判定、不发信号。"""
    sched = SignalScheduler()
    with (
        patch("app.modules.signal.scheduler.is_trading_time", return_value=False),
        patch(
            "app.modules.signal.scheduler.signal_service.get_config",
            AsyncMock(return_value=SignalConfig()),
        ),
        patch(
            "app.modules.signal.scheduler.signal_service.fire", AsyncMock()
        ) as fire,
    ):
        await sched.on_quote_update(
            {"event": "quote_update", "quotes": [_quote("12.0")], "stale": False}
        )
    assert fire.await_count == 0


@pytest.mark.asyncio
async def test_scheduler_skips_stale_frames() -> None:
    """行情源故障(stale)→ 本帧不判定,不拿旧价编数。"""
    sched = SignalScheduler()
    with (
        patch("app.modules.signal.scheduler.is_trading_time", return_value=True),
        patch(
            "app.modules.signal.scheduler.signal_service.get_config",
            AsyncMock(return_value=SignalConfig()),
        ),
        patch(
            "app.modules.signal.scheduler.signal_service.fire", AsyncMock()
        ) as fire,
    ):
        await sched.on_quote_update(
            {"event": "quote_update", "quotes": [_quote("12.0")], "stale": True}
        )
    assert fire.await_count == 0


@pytest.mark.asyncio
async def test_scheduler_window_is_capped() -> None:
    """每票只保留 N 帧(不能无限涨内存)。"""
    sched = SignalScheduler()
    with (
        patch("app.modules.signal.scheduler.is_trading_time", return_value=True),
        patch(
            "app.modules.signal.scheduler.signal_service.get_config",
            AsyncMock(return_value=SignalConfig()),
        ),
        patch("app.modules.signal.scheduler.signal_service.fire", AsyncMock()),
    ):
        for _ in range(WINDOW_MAX_FRAMES + 40):
            await sched.on_quote_update(
                {"event": "quote_update", "quotes": [_quote("10.0")], "stale": False}
            )
    assert len(sched._windows[CODE]) == WINDOW_MAX_FRAMES


@pytest.mark.asyncio
async def test_scheduler_single_stock_error_does_not_break_others() -> None:
    """单票异常不影响其它票。"""
    sched = SignalScheduler()
    calls: list[str] = []

    async def _fire(signal, cfg):
        calls.append(signal.stock_code)
        if signal.stock_code == "000001.SZ":
            raise RuntimeError("boom")
        return True

    with (
        patch("app.modules.signal.scheduler.is_trading_time", return_value=True),
        patch(
            "app.modules.signal.scheduler.signal_service.get_config",
            AsyncMock(return_value=SignalConfig()),
        ),
        patch("app.modules.signal.scheduler.signal_service.fire", _fire),
    ):
        sched._levels["000001.SZ"] = [
            type(
                "LV", (), {"kind": "t_sell_point", "level": 10.0, "label": "L", "condition": "", "basis": ""}
            )()
        ]
        await sched.on_quote_update(
            {
                "event": "quote_update",
                "quotes": [_quote("10.5", code="000001.SZ"), _quote("10.5", code="600000.SH")],
                "stale": False,
            }
        )
    assert "600000.SH" in calls


@pytest.mark.asyncio
async def test_refresh_levels_uses_decision_runtime() -> None:
    """慢信号:持仓票的触发价从决策引擎取(口径同源)。"""
    sched = SignalScheduler()
    decision = {
        "t_plan": {"suitable": True, "t_high": 12.5, "t_low": 11.0},
        "grid_plan": {"suitable": False, "reason": "波动太小"},
    }
    pos = type("P", (), {"stock_code": CODE, "shares": 100})()
    with (
        patch(
            "app.modules.portfolio.service.get_all_positions",
            AsyncMock(return_value=[pos]),
        ),
        patch(
            "app.services.decision_runtime.build_decision_payload",
            AsyncMock(return_value={"decision": decision}),
        ),
    ):
        count = await sched.refresh_levels()
    assert count == 1
    kinds = {lv.kind for lv in sched._levels[CODE]}
    assert kinds == {"t_sell_point", "t_buyback_point"}
    assert any("波动太小" in n for n in sched._notes.get(CODE, []))


@pytest.mark.asyncio
async def test_refresh_levels_skips_zero_share_positions() -> None:
    """持仓为 0 的票不参与(范围只限持仓股)。"""
    sched = SignalScheduler()
    pos = type("P", (), {"stock_code": CODE, "shares": 0})()
    with patch(
        "app.modules.portfolio.service.get_all_positions",
        AsyncMock(return_value=[pos]),
    ):
        count = await sched.refresh_levels()
    assert count == 0


# ============================================================
# API
# ============================================================


def test_api_get_and_patch_config() -> None:
    resp = client.get("/api/signals/config")
    assert resp.status_code == 200
    body = resp.json()
    assert "config" in body and "runtime" in body

    resp = client.patch("/api/signals/config", json={"velocity_pct": 2.0})
    assert resp.status_code == 200
    assert resp.json()["config"]["velocity_pct"] == 2.0

    resp = client.get("/api/signals/config")
    assert resp.json()["config"]["velocity_pct"] == 2.0


def test_api_patch_rejects_invalid_values() -> None:
    assert client.patch("/api/signals/config", json={"velocity_pct": 0}).status_code == 422
    assert client.patch("/api/signals/config", json={"cooldown_sec": -1}).status_code == 422


def test_api_list_signals() -> None:
    resp = client.get("/api/signals?limit=10")
    assert resp.status_code == 200
    assert "items" in resp.json()


def test_api_test_endpoint_calls_notify() -> None:
    with patch(
        "app.modules.notify.service.notify_service.notify",
        AsyncMock(return_value=_ok_results()),
    ):
        resp = client.post("/api/signals/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
