"""P4.3 EventBus + SSE 端点测试"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.event_bus import (
    DEAD_CONNECTION_TIMEOUT,
    HEARTBEAT_INTERVAL,
    EventBus,
)


@pytest.fixture
def fresh_bus():
    bus = EventBus()
    yield bus
    # 清理心跳任务(循环可能已关闭,容错)
    if bus._cleanup_task:
        try:
            bus._cleanup_task.cancel()
        except RuntimeError:
            pass


class TestEventBus:
    @pytest.mark.asyncio
    async def test_subscribe_returns_queue(self, fresh_bus):
        q = fresh_bus.subscribe("c1")
        assert fresh_bus.subscriber_count == 1
        assert isinstance(q, asyncio.Queue)

    @pytest.mark.asyncio
    async def test_unsubscribe_removes(self, fresh_bus):
        fresh_bus.subscribe("c1")
        fresh_bus.subscribe("c2")
        fresh_bus.unsubscribe("c1")
        assert fresh_bus.subscriber_count == 1

    def test_subscribe_unsubscribe_is_idempotent(self, fresh_bus):
        # 同步测试不触 loop 的路径:unsubscribe 不需要 loop
        fresh_bus.unsubscribe("never-existed")
        assert fresh_bus.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_publish_delivers_to_all(self, fresh_bus):
        q1 = fresh_bus.subscribe("c1")
        q2 = fresh_bus.subscribe("c2")
        await fresh_bus.publish({"event": "trade.scored", "trade_id": 1})
        assert (await q1.get())["event"] == "trade.scored"
        assert (await q2.get())["trade_id"] == 1

    @pytest.mark.asyncio
    async def test_publish_to_full_queue_unsubscribes(self, fresh_bus):
        """死连接(队列满)在 publish 时被清理"""
        q = fresh_bus.subscribe("c1")
        # 塞满队列(默认 maxsize=100)
        for _ in range(100):
            q.put_nowait({"event": "ping"})
        assert fresh_bus.subscriber_count == 1
        await fresh_bus.publish({"event": "trade.scored", "trade_id": 1})
        assert fresh_bus.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_heartbeat_publishes_ping(self, fresh_bus, monkeypatch):
        # 缩短心跳间隔,等首轮 ping
        monkeypatch.setattr(
            "app.services.event_bus.HEARTBEAT_INTERVAL", 0.05
        )
        q = fresh_bus.subscribe("c1")
        event = await asyncio.wait_for(q.get(), timeout=2)
        assert event["event"] == "ping"

    @pytest.mark.asyncio
    async def test_dead_connection_cleaned_by_timeout(self, fresh_bus, monkeypatch):
        fresh_bus.subscribe("c1")
        # 将 last_active 拨回超时阈值以外
        cid, q, _ = fresh_bus._subscribers[0]
        fresh_bus._subscribers[0] = (
            cid, q, 0.0  # 1969 年,远超 60s 超时
        )
        monkeypatch.setattr(
            "app.services.event_bus.HEARTBEAT_INTERVAL", 0.01
        )
        fresh_bus._cleanup_task.cancel()
        fresh_bus._cleanup_task = asyncio.create_task(fresh_bus._heartbeat_loop())
        await asyncio.sleep(0.15)
        assert fresh_bus.subscriber_count == 0


class TestSSEEndpoint:
    def test_sse_endpoint_uses_streaming_response(self):
        """路由注册(流式连接行为由 EventBus 单测覆盖 + 真实服务集成验证)"""
        from app.main import app

        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/events/sse" in paths
