"""秒级盯盘轮询器(盘中行情推送的数据源)

**为什么需要它**:盯盘要"端到端 ≤3s 的价格刷新",而现有链路有三处结构性障碍:

1. `QuoteService` 默认缓存 300s —— 研究路径必须保留,盯盘必须绕过
   (见 `services/quote_service.py::get_quotes_fresh`)。
2. 前端自己轮询 `/api/quotes` → N 个浏览器标签 = N 倍公司网络出口压力,
   而新浪/腾讯对高频请求会限流。
3. 没有"一次取数、处处消费"的单点 —— 每处 REST 调用各自去摸数据源。

所以本模块是**服务端单例**:常驻循环 → 拉一次 watchlist 行情 → 写内存快照 →
通过 `services/event_bus.py` 广播 → SSE 端点推给前端。前端只订一条流。

**口径:3 秒快照(Level-1),不是逐笔 Tick**
- 数据源:新浪(主)/ 腾讯(备),实测批量多代码单请求 0.6s 内返回;
- ms 级 Tick 需要 WebSocket 推送或通达信 TCP,实测在公司网络下不通(见 ADR-0006);
- 因此本模块**不承诺** tick 级精度,前端与文档统一表述为"3 秒快照"。

**失败语义**:缺数据就标 `stale=True` 并保留上一轮快照,**绝不编造价格**。
判定层(纯函数)只吃快照里的真实报价,拿不到就降级。

**触发频率的自我保护**:
- 盘中 2s 一轮;非交易时段完全停拉(复用 `core/trading_time.py` 的口径);
- 连续失败 → 退避 2s → 5s → 10s → 30s 封顶;
- 无人订阅(SSE 与 REST 都没人要)→ 降到 15s 一轮,省出口配额。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from app.core.logging import logger
from app.core.trading_time import is_trading_time
from app.data.unified import UnifiedQuote
from app.services.event_bus import event_bus
from app.services.quote_service import QuoteError, QuoteService, get_quote_service

# 盘中轮询间隔(秒)
INTERVAL_SEC = 2.0
# 无人订阅时的降频间隔(秒)
IDLE_INTERVAL_SEC = 15.0
# 连续失败退避阶梯(秒);最后一档封顶
BACKOFF_LADDER = (2.0, 5.0, 10.0, 30.0)
# REST 命中后的"保持高频"时长(秒):REST 降级路径要随时拿得到新鲜价
REST_ACCESS_GRACE_SEC = 60.0
# 事件名(与 event_bus 其它事件区分开)
EVENT_QUOTE_UPDATE = "quote_update"
EVENT_QUOTE_SNAPSHOT = "quote_snapshot"


@dataclass
class QuoteSnapshot:
    """当前 watchlist 行情快照(由 poller 独占写入,其它方只读)"""

    quotes: dict[str, UnifiedQuote] = field(default_factory=dict)
    updated_at: datetime | None = None
    stale: bool = True
    source: str | None = None
    last_error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构(quote 用 model_dump,时间用 ISO 串)"""
        return {
            "quotes": [q.model_dump(mode="json") for q in self.quotes.values()],
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "stale": self.stale,
            "source": self.source,
            "last_error": self.last_error,
        }


class QuotePoller:
    """常驻轮询器:拉 watchlist 行情 → 更新快照 → 广播事件"""

    def __init__(
        self,
        quote_service: QuoteService | None = None,
        codes_provider: Callable[[], list[str]] | None = None,
        interval_sec: float = INTERVAL_SEC,
        idle_interval_sec: float = IDLE_INTERVAL_SEC,
    ) -> None:
        self._quote_service = quote_service
        self._codes_provider = codes_provider
        self.interval_sec = interval_sec
        self.idle_interval_sec = idle_interval_sec
        self.snapshot = QuoteSnapshot()
        self._fail_streak = 0
        self._running = False
        self._lock = asyncio.Lock()
        self._last_rest_access: datetime | None = None
        self._stop_event = asyncio.Event()

    # ---------- watchlist 代码集合 ----------

    async def resolve_codes_async(self) -> list[str]:
        """watchlist = 自选表全部 ∪ 持仓(去重、保序)。

        为什么不用 `battle_plan_service.resolve_target_stocks()`:它只并了
        "持仓 ∪ ★关注",而首页列表展示的是**自选表全部** —— 漏掉非★自选票会让
        前端那一行的价格永远停在首屏那一帧。这里按"首页看到什么就盯什么"取全集。

        `codes_provider` 注入点只给测试用(生产路径不打桩)。
        """
        if self._codes_provider is not None:
            return list(self._codes_provider())

        from app.modules.portfolio.service import get_all_positions
        from app.repositories.watchlist_repo import watchlist_repo

        codes: list[str] = []
        seen: set[str] = set()

        def _add(code: str | None) -> None:
            c = (code or "").strip()
            if c and c not in seen:
                seen.add(c)
                codes.append(c)

        try:
            for row in await watchlist_repo.list_all():
                _add(getattr(row, "stock_code", None))
        except Exception as e:  # noqa: BLE001 — 自选取不到不该拖垮持仓
            logger.warning("[quote-poller] 读自选失败: {}", e)
        try:
            for pos in await get_all_positions():
                _add(getattr(pos, "stock_code", None))
        except Exception as e:  # noqa: BLE001
            logger.warning("[quote-poller] 读持仓失败: {}", e)
        return codes

    # ---------- 单轮 ----------

    async def poll_once(self) -> QuoteSnapshot:
        """跑一轮:取数 → 更新快照 → 广播。返回本轮快照。"""
        async with self._lock:
            service = self._quote_service or get_quote_service()
            codes = await self.resolve_codes_async()

            if not codes:
                # 没有要盯的票:清空快照并标 stale(而不是留着旧价格装作还新鲜)
                self.snapshot = QuoteSnapshot(stale=True)
                self._fail_streak = 0
                return self.snapshot

            try:
                quotes = await service.get_quotes_fresh(codes)
            except QuoteError as e:
                self._fail_streak += 1
                logger.warning("[quote-poller] 第 {} 次连续失败: {}", self._fail_streak, e)
                # 保留上一轮快照,但**明确标记陈旧** —— 前端据此显示"数据可能滞后"
                self.snapshot.stale = True
                self.snapshot.last_error = str(e)
                return self.snapshot
            except Exception as e:  # noqa: BLE001 — 任何异常都不该打死循环
                self._fail_streak += 1
                logger.warning("[quote-poller] 第 {} 次连续异常: {}", self._fail_streak, e)
                self.snapshot.stale = True
                self.snapshot.last_error = str(e)
                return self.snapshot

            self._fail_streak = 0
            self.snapshot = QuoteSnapshot(
                quotes={q.code: q for q in quotes},
                updated_at=datetime.now(),
                stale=False,
                source=getattr(service.primary, "name", None),
                last_error=None,
            )
            await self._broadcast()
            return self.snapshot

    async def _broadcast(self) -> None:
        payload = self.snapshot.to_payload()
        await event_bus.publish(
            {
                "event": EVENT_QUOTE_UPDATE,
                "quotes": payload["quotes"],
                "updated_at": payload["updated_at"],
                "stale": payload["stale"],
                "source": payload["source"],
            }
        )

    # ---------- 常驻循环 ----------

    def _next_delay(self) -> float:
        """下一轮等待时长:失败退避优先,无人订阅再降频。"""
        if self._fail_streak:
            idx = min(self._fail_streak - 1, len(BACKOFF_LADDER) - 1)
            return BACKOFF_LADDER[idx]
        if event_bus.subscriber_count == 0 and not self._has_recent_rest_access():
            return self.idle_interval_sec
        return self.interval_sec

    def _has_recent_rest_access(self) -> bool:
        """最近是否有人走 REST 取过行情。

        SSE 订阅数只是"有人在看"的一半:前端 SSE 断了会退回 REST 轮询,
        那时订阅数为 0 但仍需要新鲜价 —— 所以 REST 命中也要记一笔。
        """
        if self._last_rest_access is None:
            return False
        return (datetime.now() - self._last_rest_access).total_seconds() < REST_ACCESS_GRACE_SEC

    def note_rest_access(self) -> None:
        """REST 端点被调用时登记一笔(供降频判定)"""
        self._last_rest_access = datetime.now()

    async def run(self) -> None:
        """常驻循环。由 main.py lifespan 以后台任务启动。"""
        self._running = True
        logger.info("[quote-poller] 启动,盘中间隔 {}s", self.interval_sec)
        try:
            while self._running:
                if is_trading_time():
                    await self.poll_once()
                # 用「等停止信号」代替 sleep:既能立刻退出,也不会在测试里
                # 去 monkeypatch 全局 asyncio.sleep(那会污染整个进程)。
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._next_delay())
                    break  # stop() 被调用 → 收工
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            logger.info("[quote-poller] 已停止")
            raise
        finally:
            self._running = False

    def stop(self) -> None:
        """请求停止(下一轮等待结束后退出)"""
        self._running = False
        self._stop_event.set()


# 全局单例(与 event_bus 一致的服务级单例风格)
poller = QuotePoller()


async def start_quote_poller(interval_sec: float = INTERVAL_SEC) -> None:
    """常驻轮询循环入口。由 main.py lifespan 启动。"""
    poller.interval_sec = interval_sec
    await poller.run()


def get_quote_snapshot() -> QuoteSnapshot:
    """读当前快照(供 REST 降级路径与 SSE 首帧使用)"""
    return poller.snapshot


__all__ = [
    "QuotePoller",
    "QuoteSnapshot",
    "poller",
    "get_quote_snapshot",
    "start_quote_poller",
    "EVENT_QUOTE_UPDATE",
    "EVENT_QUOTE_SNAPSHOT",
    "INTERVAL_SEC",
    "IDLE_INTERVAL_SEC",
]
