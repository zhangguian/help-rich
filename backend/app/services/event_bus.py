"""内部事件总线(backend-arch §8.3 + v0.2 支持回调订阅)

- 订阅:asyncio.Queue(maxsize=100),客户端断开后由心跳循环清理
- 发布:put_nowait,满队列视为死连接并清理
- 心跳:每 30s 推 {"event": "ping"},1 分钟无活动清理
- v0.2:新增 subscribe_callback(callback, filter_fn=None),用于 SSE 按条件过滤
"""
import asyncio
import time
from typing import Any, Awaitable, Callable, Optional

# 心跳间隔 / 死连接超时(秒)
HEARTBEAT_INTERVAL = 30
DEAD_CONNECTION_TIMEOUT = 60


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[tuple[str, asyncio.Queue, float]] = []
        self._callback_subscribers: list[
            tuple[Callable[[dict], Awaitable[None]], Optional[Callable[[dict], bool]]]
        ] = []
        self._cleanup_task: asyncio.Task | None = None

    def subscribe(self, client_id: str) -> asyncio.Queue:
        """注册客户端,返回其专属队列"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append((client_id, queue, time.time()))
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._heartbeat_loop())
        return queue

    def unsubscribe(self, client_id: str) -> None:
        """注销客户端"""
        self._subscribers = [
            (cid, q, t) for cid, q, t in self._subscribers if cid != client_id
        ]

    def subscribe_callback(
        self,
        callback: Callable[[dict], Awaitable[None]],
        filter_fn: Optional[Callable[[dict], bool]] = None,
    ) -> Callable[[], Awaitable[None]]:
        """v0.2:订阅回调(filter_fn 返回 True 的事件触发 callback)

        Returns: async 取消订阅函数
        """
        entry = (callback, filter_fn)
        self._callback_subscribers.append(entry)

        async def unsub():
            try:
                self._callback_subscribers.remove(entry)
            except ValueError:
                pass

        return unsub

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers) + len(self._callback_subscribers)

    async def publish(self, event: dict[str, Any]) -> None:
        """广播事件;队列满(死连接)直接清理"""
        for client_id, queue, _ in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self.unsubscribe(client_id)
        # v0.2:回调订阅(同步触发 callback,不阻塞)
        for cb, filt in list(self._callback_subscribers):
            if filt is not None and not filt(event):
                continue
            try:
                # create_task 异步执行,避免 callback 阻塞 publish
                asyncio.create_task(cb(event))
            except RuntimeError:
                # 事件循环已关闭
                pass

    async def _heartbeat_loop(self) -> None:
        """每 30s 推 ping;1 分钟无活动(队列长期满)视为死连接"""
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            now = time.time()
            for client_id, queue, last_active in list(self._subscribers):
                try:
                    queue.put_nowait({"event": "ping", "ts": now})
                except asyncio.QueueFull:
                    self.unsubscribe(client_id)
                if now - last_active > DEAD_CONNECTION_TIMEOUT:
                    self.unsubscribe(client_id)


# 全局单例
event_bus = EventBus()
