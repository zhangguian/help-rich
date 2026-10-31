"""盘中信号调度器。

**两条数据通路**:
1. **快信号(帧驱动)**:订阅 `event_bus` 的 `quote_update` 事件(2s 一帧,
   由 `services/quote_poller.py` 广播)→ 每帧做斜率/突破判定 + 到价比对。
   **零额外网络请求** —— 复用盯盘已有的行情帧。
2. **慢信号(定时重算)**:每 60s 用 `services/decision_runtime.py` 重算一次
   持仓股的 T 点 / 网格 / 加仓触发价(决策口径与决策卡 100% 同源),
   算完缓存住;盘中每帧只做「现价 vs 触发价」比较(零 IO)。

**交易时段门禁**:非交易时段完全停跑(与秒级盯盘同一份 `core/trading_time.py` 口径)。

**并发**:慢信号重算用 `asyncio.gather` + `Semaphore(4)` 限并发,
别把行情源 / K 线源打爆。
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime

from app.core.logging import logger
from app.core.trading_time import is_trading_time
from app.modules.signal.engine import (
    Signal,
    TriggerLevel,
    detect_breakout,
    detect_level_hits,
    detect_velocity,
    extract_trigger_levels,
    extract_unsuitable_notes,
)
from app.modules.signal.service import signal_service
from app.services.event_bus import event_bus
from app.services.quote_poller import EVENT_QUOTE_UPDATE

# 慢信号重算间隔(秒)
LEVEL_REFRESH_SEC = 60.0
# 每票保留的帧数上限(2s 一帧 → 120 帧 ≈ 4 分钟,够 60s 窗口用)
WINDOW_MAX_FRAMES = 120
# 慢信号重算的并发上限
LEVEL_REFRESH_CONCURRENCY = 4


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class SignalScheduler:
    """盘中信号调度器。"""

    def __init__(self, level_refresh_sec: float = LEVEL_REFRESH_SEC) -> None:
        self.level_refresh_sec = level_refresh_sec
        # 每票的滚动窗口 [(ts, price)]
        self._windows: dict[str, deque[tuple[float, float]]] = {}
        # 每票的突破迟滞状态("up" / "down" / None)
        self._breakout_state: dict[str, str | None] = {}
        # 每票的到价触发线(慢信号算出来的)
        self._levels: dict[str, list[TriggerLevel]] = {}
        # 每票"今天不适合做T/做网格"的原文原因
        self._notes: dict[str, list[str]] = {}
        self._levels_updated_at: datetime | None = None
        self._running = False
        self._stop_event = asyncio.Event()
        self._unsub = None

    # ---------- 状态读取(前端可见) ----------

    def snapshot(self) -> dict:
        return {
            "levels_updated_at": (
                self._levels_updated_at.isoformat() if self._levels_updated_at else None
            ),
            "codes": sorted(self._levels.keys()),
            "levels": {
                code: [
                    {
                        "kind": lv.kind,
                        "level": lv.level,
                        "label": lv.label,
                        "condition": lv.condition,
                        "basis": lv.basis,
                    }
                    for lv in levels
                ]
                for code, levels in self._levels.items()
            },
            "notes": dict(self._notes),
        }

    # ---------- 快信号:帧驱动 ----------

    async def on_quote_update(self, event: dict) -> None:
        """处理一帧行情(由 event_bus 回调驱动)。"""
        if not is_trading_time():
            return
        if event.get("stale"):
            # 行情源故障 → 本帧不判定(**不拿旧价编数**)
            return
        quotes = event.get("quotes") or []
        if not quotes:
            return

        cfg = await signal_service.get_config()
        if not cfg.enabled:
            return

        now = time.time()
        for quote in quotes:
            if not isinstance(quote, dict):
                continue
            code = str(quote.get("code") or "")
            price = _to_float(quote.get("current_price"))
            if not code or price is None or price <= 0:
                continue
            name = quote.get("name")
            await self._handle_one(code, name, price, quote, now, cfg)

    async def _handle_one(self, code, name, price, quote, now, cfg) -> None:
        """单只票的一帧判定。"""
        # 1) 滚动窗口(先记帧,再判定)
        window = self._windows.get(code)
        if window is None:
            window = deque(maxlen=WINDOW_MAX_FRAMES)
            self._windows[code] = window
        window.append((now, price))

        # 2) 急速拉升 / 急速下跌
        if cfg.enable_velocity:
            signal = detect_velocity(
                code,
                name,
                list(window),
                now_ts=now,
                window_sec=cfg.velocity_window_sec,
                velocity_pct=cfg.velocity_pct,
            )
            if signal is not None:
                await self._fire(signal)

        # 3) 涨幅突破 / 跌幅突破
        if cfg.enable_breakout:
            prev_close = _to_float(quote.get("prev_close"))
            signal, new_state = detect_breakout(
                code,
                name,
                price,
                prev_close,
                up_pct=cfg.breakout_up_pct,
                down_pct=cfg.breakout_down_pct,
                state=self._breakout_state.get(code),
            )
            self._breakout_state[code] = new_state
            if signal is not None:
                await self._fire(signal)

        # 4) 到价类(慢信号算出来的触发价 → 这里只比较)
        levels = self._levels.get(code) or []
        if levels:
            for signal in detect_level_hits(code, name, price, levels):
                await self._fire(signal)

    async def _fire(self, signal: Signal) -> None:
        """推送一条信号(异常不外冒)。"""
        try:
            cfg = await signal_service.get_config()
            ok = await signal_service.fire(signal, cfg)
            if ok:
                logger.info("[signal] 触发 {} {} {}", signal.kind, signal.stock_code, signal.title)
        except Exception as e:  # noqa: BLE001 — 通知失败绝不拖垮盯盘
            logger.warning("[signal] 推送异常: {}", e)

    # ---------- 慢信号:触发价重算 ----------

    async def refresh_levels(self) -> int:
        """重算持仓股的到价触发价。返回算出的票数。"""
        from app.modules.portfolio.service import get_all_positions

        try:
            positions = await get_all_positions()
        except Exception as e:  # noqa: BLE001
            logger.warning("[signal] 读持仓失败: {}", e)
            return 0

        codes = [p.stock_code for p in positions if getattr(p, "shares", 0) and p.shares > 0]
        if not codes:
            self._levels = {}
            self._notes = {}
            return 0

        sem = asyncio.Semaphore(LEVEL_REFRESH_CONCURRENCY)

        async def _one(code: str):
            async with sem:
                try:
                    return await self._compute_levels(code)
                except Exception as e:  # noqa: BLE001 — 单票失败不影响其它票
                    logger.warning("[signal] 计算 {} 触发价失败: {}", code, e)
                    return code, [], [f"决策数据不可用:{e}"]

        results = await asyncio.gather(*[_one(c) for c in codes], return_exceptions=True)
        levels: dict[str, list[TriggerLevel]] = {}
        notes: dict[str, list[str]] = {}
        for item in results:
            if isinstance(item, BaseException):
                continue
            code, lv, nt = item
            if lv:
                levels[code] = lv
            if nt:
                notes[code] = nt
        self._levels = levels
        self._notes = notes
        self._levels_updated_at = datetime.now()
        return len(levels)

    async def _compute_levels(self, code: str):
        """用决策引擎重算一只票的触发价(与决策卡同源)。"""
        from app.services.decision_runtime import DecisionDataUnavailable, build_decision_payload

        try:
            payload = await build_decision_payload(
                code,
                include_env=False,  # 信号侧不取市场环境(省 4~5 次外部 HTTP)
                need_extras=True,  # 费用/现金口径仍与决策卡一致
            )
        except DecisionDataUnavailable as e:
            return code, [], [f"决策数据不可用:{e}"]
        except Exception as e:  # noqa: BLE001
            logger.warning("[signal] 决策装配失败({}): {}", code, e)
            return code, [], [f"决策数据不可用:{e}"]

        decision = payload.get("decision") or {}
        return code, extract_trigger_levels(decision), extract_unsuitable_notes(decision)

    # ---------- 常驻循环 ----------

    async def run(self) -> None:
        """常驻循环。由 main.py lifespan 以后台任务启动。"""
        self._running = True
        self._unsub = event_bus.subscribe_callback(
            self._on_quote_event, lambda e: e.get("event") == EVENT_QUOTE_UPDATE
        )
        logger.info("[signal] 调度器启动,慢信号重算间隔 {}s", self.level_refresh_sec)
        try:
            while self._running:
                if is_trading_time():
                    try:
                        await self.refresh_levels()
                    except Exception as e:  # noqa: BLE001 — 循环必须活着
                        logger.warning("[signal] 触发价重算异常(继续): {}", e)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.level_refresh_sec
                    )
                    break
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            logger.info("[signal] 调度器已停止")
            raise
        finally:
            self._running = False
            if self._unsub is not None:
                await self._unsub()
                self._unsub = None

    async def _on_quote_event(self, event: dict) -> None:
        """event_bus 回调入口(异常不外冒,否则会打到 event_bus 的 create_task)。"""
        try:
            await self.on_quote_update(event)
        except Exception as e:  # noqa: BLE001
            logger.warning("[signal] 帧处理异常: {}", e)

    def stop(self) -> None:
        """请求停止(下一轮等待结束后退出)"""
        self._running = False
        self._stop_event.set()


# 全局单例
scheduler = SignalScheduler()


async def start_signal_scheduler(interval_sec: float = LEVEL_REFRESH_SEC) -> None:
    """常驻循环入口。由 main.py lifespan 启动。"""
    scheduler.level_refresh_sec = interval_sec
    await scheduler.run()


__all__ = [
    "LEVEL_REFRESH_CONCURRENCY",
    "LEVEL_REFRESH_SEC",
    "SignalScheduler",
    "WINDOW_MAX_FRAMES",
    "scheduler",
    "start_signal_scheduler",
]
